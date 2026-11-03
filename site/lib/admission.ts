/**
 * Whether one POST to /api/generate may spend quota, and the spending itself.
 *
 * Separate from the route so every refusal can be tested with the IO injected,
 * the same way sweepReconciliations is: the property that matters is "a refusal
 * charges nothing and dispatches nothing", and only a test holding the write and
 * the dispatch can see that.
 *
 * THE ORDER IS CHEAPEST-AND-MOST-FINAL FIRST:
 *
 *   1. in the search index?  Search is selection-only (DESIGN.md), so anything
 *      else came from something other than the search box. CDN read, no token.
 *   2. a verdict already?    Live generation answers a cache MISS. Regenerating
 *      a held title spent quota for nothing, and a direct POST against a catalog
 *      title would have replaced an audited verdict: select_publishable promotes
 *      whatever is newer, with only the automated gate behind it.
 *   3. already running?      A second person asking for the same title joins the
 *      run in progress. /api/status polls by appid, so there is nothing to wire.
 *   4. the reserve (guard 1), with the sweep folded in as before.
 *
 * EVERYTHING THAT CANNOT BE ANSWERED BECOMES THE QUEUE FALLBACK, never a guess.
 * Refusing to generate is recoverable; authorising against an unknown is not.
 *
 * WHAT THIS DOES NOT STOP, stated so nobody reads it as more: requests for many
 * real uncached titles from many IPs can still spend the reserve. That is guard
 * 1's designed ceiling, and it degrades to the queue. And two simultaneous POSTs
 * can still both pass step 3 and lose each other's charge, because a repository
 * variable has no compare-and-swap.
 */

import { createHmac } from "node:crypto";

import {
  isActive,
  sweepReconciliations,
  type RunInfo,
  type SweepDeps,
} from "./github";
import {
  canGenerate,
  chargeReservation,
  dispatchLost,
  recordDispatch,
  rollDay,
  type QuotaState,
} from "./quota";

/**
 * The per-IP guard's key, instead of the address.
 *
 * It only ever has to answer "has this client had 5 this hour", and a keyed hash
 * answers that as well as the address did, without writing the one identifier the
 * product receives into repository state. Keyed because an unkeyed hash of an IPv4
 * address is reversible by trying them all. The key is the dispatch token, a secret
 * every path here already needs, so this adds no configuration; rotating it resets
 * only the counters for the current hour.
 */
export function hashClient(ip: string, key = process.env.GH_DISPATCH_TOKEN ?? "") {
  return createHmac("sha256", key).update(ip).digest("hex").slice(0, 16);
}

/** How far a run's clock may lead the dispatch timestamp we recorded. */
const CLOCK_SKEW_MS = 5_000;

/** Is a run for this title in flight, or requested and not yet visible? */
export function alreadyRunning(
  appid: string,
  state: QuotaState,
  runs: RunInfo[],
  now = Date.now(),
): boolean {
  const mine = runs.filter((r) => r.appid === appid);
  if (mine.some(isActive)) return true;
  // repository_dispatch returns before the run exists, so for up to the grace
  // window "no run yet" means "on its way". A finished run newer than the dispatch
  // means it already came and went - a fast failure may be retried.
  const at = state.dispatched?.[appid];
  if (!at || dispatchLost(state, appid, now)) return false;
  return !mine.some(
    (r) => Date.parse(r.created_at) >= Date.parse(at) - CLOCK_SKEW_MS,
  );
}

export interface AdmissionDeps extends Omit<SweepDeps, "listRuns"> {
  inSearchIndex: (appid: string) => Promise<boolean>;
  verdictExists: (appid: string) => Promise<{ found: boolean; source?: string }>;
  readQuota: () => Promise<Record<string, unknown>>;
  writeQuota: (state: Record<string, unknown>) => Promise<void>;
  /** Must throw when the list cannot be read: see listRunsStrict. */
  listRuns: () => Promise<RunInfo[]>;
  dispatch: (appid: number, quota: Record<string, unknown>) => Promise<void>;
}

export interface Admission {
  status: number;
  body: Record<string, unknown>;
}

const fallback = (reason: string, detail?: unknown): Admission => ({
  status: 200,
  // Identical copy for every reason, per DESIGN.md: the distinction is ours.
  body: { state: "queue_fallback", reason, ...(detail ? { detail } : {}) },
});

/** `client` is already hashed: the raw address never enters this function. */
export async function admit(
  appid: string,
  client: string,
  deps: AdmissionDeps,
): Promise<Admission> {
  let known: boolean;
  let exists: { found: boolean; source?: string };
  let read: QuotaState;
  let runs: RunInfo[];
  try {
    known = await deps.inSearchIndex(appid);
    if (!known) {
      return { status: 404, body: { error: "not a known title" } };
    }
    exists = await deps.verdictExists(appid);
    if (exists.found) {
      return {
        status: 200,
        body: { state: "exists", appid: Number(appid), source: exists.source },
      };
    }
    read = rollDay((await deps.readQuota()) as QuotaState);
    runs = await deps.listRuns();
  } catch {
    return fallback("unverifiable");
  }

  if (alreadyRunning(appid, read, runs)) {
    return {
      status: 200,
      body: { state: "dispatched", appid: Number(appid), joined: true },
    };
  }

  // Give back what today's FINISHED generations did not spend, before deciding
  // whether this one fits. Between the read and the charge on purpose: the
  // correction rides the write this already performs, so it adds no writer to a
  // ledger with no compare-and-swap, and the fact and the counter land in one
  // PATCH. A sweep failure falls back to the higher, un-reconciled figure.
  const state = await sweepReconciliations(read, {
    listRuns: async () => runs,
    runOutcome: deps.runOutcome,
    fetchVerdictCost: deps.fetchVerdictCost,
  }).catch(() => read);

  const check = canGenerate(state, client);
  if (!check.allowed) return fallback(check.reason, check.detail);

  // Reserve up front, in full, so a burst cannot oversubscribe between check and
  // record. WRITE BEFORE DISPATCH, and a failed write stops here: spending without
  // a booked reservation is the direction that overruns the Gemini budget.
  const charged = recordDispatch(
    chargeReservation(state, client),
    appid,
  ) as Record<string, unknown>;
  try {
    await deps.writeQuota(charged);
  } catch {
    return fallback("ledger_unwritable");
  }
  try {
    // The ledger travels WITH the dispatch - the runner cannot read it itself.
    await deps.dispatch(Number(appid), charged);
  } catch {
    // The reservation stands: over-counting until the day rolls is the safe error.
    return fallback("dispatch_failed");
  }
  return { status: 200, body: { state: "dispatched", appid: Number(appid) } };
}

/**
 * Search-index membership, read from the static shards this deployment serves.
 *
 * Fetched rather than read from disk because files under public/ are not in the
 * function bundle (see verdictExists). Held for the life of the instance: the
 * shards only change with a deploy, and a deploy brings new instances. Both shards
 * must load, or the answer is unknown rather than "no".
 */
let indexed: Set<number> | null = null;

export async function inSearchIndex(
  appid: string,
  origin: string,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  if (!indexed) {
    const shards = await Promise.all(
      ["search-index-core.json", "search-index-tail.json"].map(async (f) => {
        const res = await fetchImpl(`${origin}/${f}`);
        if (!res.ok) throw new Error(`${f}: ${res.status}`);
        return ((await res.json()) as { t: [number, string][] }).t;
      }),
    );
    indexed = new Set(shards.flat().map(([id]) => id));
  }
  return indexed.has(Number(appid));
}

/** Test seam: the membership set is per-instance state. */
export function resetSearchIndexForTest() {
  indexed = null;
}
