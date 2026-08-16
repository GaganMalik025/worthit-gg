/**
 * Server-only GitHub access. The token never reaches the browser — every call
 * that needs it goes through an /api/* route, which is why the progress feed is
 * a proxy rather than the client polling GitHub directly.
 */

import { reconcileKey, type QuotaState } from "./quota";

const API = "https://api.github.com";

function env() {
  const token = process.env.GH_DISPATCH_TOKEN;
  const repo = process.env.GH_REPO;
  if (!token || !repo) {
    throw new Error("GH_DISPATCH_TOKEN and GH_REPO must be set");
  }
  return { token, repo };
}

async function gh(path: string, init: RequestInit = {}) {
  const { token, repo } = env();
  const res = await fetch(`${API}/repos/${repo}${path}`, {
    ...init,
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${token}`,
      "x-github-api-version": "2022-11-28",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  return res;
}

/** The quota ledger. A repository variable, not a committed file: writable from
 *  here, always fresh, and it does not trigger a redeploy on every request. */
export async function readQuota(): Promise<Record<string, unknown>> {
  const res = await gh("/actions/variables/LIVE_QUOTA");
  if (res.status === 404) return {};
  if (!res.ok) throw new Error(`quota read: ${res.status}`);
  const { value } = (await res.json()) as { value: string };
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

export async function writeQuota(state: Record<string, unknown>) {
  const body = JSON.stringify({ name: "LIVE_QUOTA", value: JSON.stringify(state) });
  const patch = await gh("/actions/variables/LIVE_QUOTA", { method: "PATCH", body });
  if (patch.ok || patch.status === 204) return;
  await gh("/actions/variables", { method: "POST", body });
}

/**
 * Fire the generation run, CARRYING TODAY'S LEDGER WITH IT.
 *
 * The workflow used to fetch the shared ledger itself, with `gh api
 * .../variables/LIVE_QUOTA`. It cannot: the runner's GITHUB_TOKEN can neither
 * read nor write repository variables (verified on run #5 - the read fails, and
 * an earlier write reported success while writing nothing). So the runner was
 * either silently falling back to the stale committed file, or - once that
 * fallback was removed - failing outright.
 *
 * We already hold the real ledger here, one line before dispatching, read with
 * the token that does have access. Sending the counters in the payload gives
 * the runner today's true numbers with no second credential and no second
 * source of truth. Counters only: `outcomes` and `by_ip_hour` are not the
 * runner's business and would bloat the payload.
 */
export async function dispatchGeneration(
  appid: number,
  ip: string,
  quota: Record<string, unknown> = {},
) {
  const COUNTERS = [
    "date", "live_used", "batch_used", "flash_used",
    "generations", "batch_generations", "flash_generations",
  ];
  const snapshot = Object.fromEntries(
    COUNTERS.filter((k) => k in quota).map((k) => [k, quota[k]]),
  );
  const res = await gh("/dispatches", {
    method: "POST",
    body: JSON.stringify({
      event_type: "generate-verdict",
      client_payload: { appid: String(appid), ip, quota: snapshot },
    }),
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`dispatch: ${res.status}`);
  }
}

/**
 * Does the verdict actually exist on the `verdicts` branch?
 *
 * GROUND TRUTH, and the reason it exists: the outcome variable is written by a
 * bookkeeping step that can fail (and did). When it failed, a verdict that had
 * genuinely generated and committed was invisible to the client, which sat on
 * "queued" until its 8-minute timeout and then told the user to request a page
 * that already existed.
 *
 * The artifact is the source of truth; the variable is only a hint that saves a
 * round trip. Anything that decides "published" asks this first.
 */
export async function verdictExists(
  appid: number | string,
): Promise<{ found: boolean; source?: string }> {
  // 1. main, as of the last build. Anything the nightly publish workflow has
  //    already squash-merged is prerendered and on disk - no API call needed,
  //    and a title stays "published" after the merge rather than reverting to
  //    "queued" because it left the verdicts branch view.
  try {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    await fs.access(
      path.join(process.cwd(), `public/verdicts/${appid}.json`),
    );
    return { found: true, source: "main" };
  } catch {
    /* not merged yet - fall through to the branch */
  }

  // 2. the verdicts branch. Both layouts are checked: public/verdicts/ was the
  //    path until the Vercel Root Directory move, and verdicts generated before
  //    that move still sit there. Dropping the legacy path would strand them.
  for (const [dir, source] of [
    ["site/public/verdicts", "verdicts"],
    ["public/verdicts", "verdicts:legacy-path"],
  ]) {
    const res = await gh(`/contents/${dir}/${appid}.json?ref=verdicts`);
    if (res.ok) return { found: true, source };
  }
  return { found: false };
}

/**
 * What one generation actually cost, read back out of the artifact it committed.
 *
 * THE ONLY CHANNEL THERE IS. The runner knows the true figure
 * (model_pacer.calls_for) and cannot tell us: its GITHUB_TOKEN cannot write
 * repository variables, and `variables` is not in that token's permission
 * surface at all, so no `permissions:` widening reaches it. The only in-runner
 * alternative is a PAT, which is new long-lived credential surface for a
 * bookkeeping nicety. So the number rides out in the one thing the runner does
 * commit - the verdict JSON - and is read back here with the credential the
 * site already holds. No new credential, no runner cooperation.
 *
 * Returns null for ANYTHING it cannot read as a real positive count: absent
 * file, unparseable JSON, a verdict generated before the cost field existed, or
 * a zero. Zero is refused on purpose - synthesis is mandatory, so a live
 * generation cannot really have cost nothing, and a 0 means something is wrong
 * rather than something was free. Every one of those cases leaves the full
 * reservation standing, which over-counts, which is the safe direction.
 */
export async function fetchVerdictCost(
  appid: number | string,
): Promise<number | null> {
  const usable = (raw: string): number | null => {
    try {
      const cost = (JSON.parse(raw) as { cost?: { model_calls?: unknown } })
        ?.cost?.model_calls;
      return typeof cost === "number" && Number.isInteger(cost) && cost > 0
        ? cost
        : null;
    } catch {
      return null;
    }
  };

  // Same dual lookup as verdictExists, and in the same order. A live-generated
  // title is normally still branch-only (main catches up at the nightly
  // promote), but once promoted the committed file carries the field too.
  try {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    return usable(
      await fs.readFile(
        path.join(process.cwd(), `public/verdicts/${appid}.json`),
        "utf-8",
      ),
    );
  } catch {
    /* not merged yet - fall through to the branch */
  }

  for (const dir of ["site/public/verdicts", "public/verdicts"]) {
    const res = await gh(`/contents/${dir}/${appid}.json?ref=verdicts`, {
      headers: { accept: "application/vnd.github.raw" },
    });
    if (res.ok) return usable(await res.text());
  }
  return null;
}

export interface RunInfo {
  id: number;
  status: string;
  conclusion: string | null;
  created_at: string;
  appid: string | null;
}

/**
 * The appid a run was dispatched for, read from its run-name.
 *
 * repository_dispatch does not surface client_payload on the runs API, so the
 * workflow puts the appid in `run-name:` and this reads it back out. Anything
 * unparseable (runs created before that existed) returns null and simply never
 * matches, which degrades to the old behaviour rather than mis-attributing.
 */
export function runAppid(r: { name?: string; display_title?: string }): string | null {
  return /verdict\s+(\d+)/.exec(r.display_title || r.name || "")?.[1] ?? null;
}

/**
 * Statuses that mean a run is FINISHED. Everything else is treated as still
 * live - see listActiveRuns for why the list is inverted.
 *
 * From GitHub's workflow-runs API (docs fetched 2026-08-06), the full status
 * vocabulary is: completed, action_required, cancelled, failure, neutral,
 * skipped, stale, success, timed_out, in_progress, queued, requested, waiting,
 * pending. The non-terminal ones are queued, in_progress, requested, waiting,
 * pending and action_required.
 */
const TERMINAL_RUN_STATUS = new Set([
  "completed", "cancelled", "failure", "neutral",
  "skipped", "stale", "success", "timed_out",
]);

/**
 * Runs of the generate workflow that have not finished, oldest first.
 *
 * TWO THINGS CHANGED HERE, AND BOTH WERE CAUSING A STUCK UI.
 *
 * 1. It used to poll only `queued` and `in_progress`. GitHub also parks runs in
 *    `waiting`, `requested`, `pending` and `action_required` - a run awaiting a
 *    runner or an approval sits in one of those and was invisible, so
 *    /api/status saw zero active runs and told the user "You're next" forever.
 *
 * 2. The filter is now by EXCLUSION of terminal statuses, in a single
 *    unfiltered request, rather than one request per status. That is fewer API
 *    calls per poll, and it fails safe: a status GitHub adds later counts as
 *    active and stays visible, instead of silently vanishing from the queue the
 *    way `waiting` did.
 */
export async function listRuns(): Promise<RunInfo[]> {
  const res = await gh(
    "/actions/workflows/generate-verdict.yml/runs?per_page=50",
  );
  if (!res.ok) return [];
  const { workflow_runs = [] } = (await res.json()) as {
    workflow_runs: {
      id: number; status: string; conclusion: string | null;
      created_at: string; name?: string; display_title?: string;
    }[];
  };
  return workflow_runs
    .map((r) => ({
      id: r.id, status: r.status, conclusion: r.conclusion,
      created_at: r.created_at, appid: runAppid(r),
    }))
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export const isActive = (r: RunInfo) => !TERMINAL_RUN_STATUS.has(r.status);

export async function listActiveRuns(): Promise<RunInfo[]> {
  return (await listRuns()).filter(isActive);
}

/**
 * The terminal state of a FINISHED run, read from the run itself.
 *
 * This replaces trusting `outcomes` in the LIVE_QUOTA variable. That variable
 * is written by a bookkeeping step inside the workflow, and the runner's
 * GITHUB_TOKEN cannot write repository variables - so the step reported success
 * (it is `continue-on-error`) while writing nothing. A run that had genuinely
 * failed left no record at all, and /api/status fell through to the lost-
 * dispatch branch and told the user their request was never received.
 *
 * The run's own steps cannot silently fail to record: they ARE the record.
 * Deriving from them needs no extra credential, and it cannot go stale.
 */
export type Outcome = "published" | "qr4_failed" | "stage_failed" | null;

/** The decision itself, separated from the fetch so it can be tested directly. */
export function deriveOutcome(
  status: string,
  conclusion: string | null,
  steps: { key: string; status: string }[],
): Outcome {
  if (status !== "completed") return null;        // still going; not terminal
  if (conclusion === "success") return "published";
  // invariant 8 gets its own state: a QR-4 rejection is a content decision, not
  // a crash, and the UI says something different about it.
  if (steps.find((s) => s.key === "qr4")?.status === "failed") return "qr4_failed";
  return "stage_failed";
}

export async function runOutcome(runId: number): Promise<Outcome> {
  const { status, conclusion, steps } = await runSteps(runId);
  return deriveOutcome(status, conclusion, steps);
}

/**
 * At most this many reservations are reconciled per dispatch. Oldest first, so
 * a backlog drains in order rather than starving. The cap exists because this
 * runs INSIDE /api/generate: an unbounded sweep would put N artifact fetches in
 * front of a user waiting to be dispatched.
 */
export const SWEEP_LIMIT = 5;

export interface SweepDeps {
  listRuns: () => Promise<RunInfo[]>;
  runOutcome: (runId: number) => Promise<Outcome>;
  fetchVerdictCost: (appid: string) => Promise<number | null>;
}

/**
 * Learn what today's finished generations really cost, and record it.
 *
 * WHY THIS RUNS AT ADMISSION TIME AND NOT ON A STATUS POLL. Reconciling when a
 * poller notices a run finish would add a second writer to a store with no CAS
 * - every writer here is a read-modify-write of one repository variable - and
 * the interleave is live: a reconcile write that reads before a concurrent
 * /api/generate and writes after it erases that dispatch's whole 13-request
 * reservation. Under-counting the ledger is the one direction that hands out
 * budget the Gemini quota does not have.
 *
 * Folding the sweep into the read-modify-write /api/generate ALREADY performs
 * means no new writer and no new race. (The pre-existing generate-vs-generate
 * race is untouched; this neither fixes nor worsens it.)
 *
 * It also answers the abandoned-tab case better than polling could. Nothing
 * here is event-driven: the work list is derived from ledger state - a
 * reservation with no matching fact - so a user who closed the tab is
 * reconciled by whoever generates next. And if nobody ever generates again
 * today, the over-count is never read: the only consumer of the corrected
 * number is an admission decision that is not happening, and the whole ledger
 * resets at the Pacific day roll. The correction has value only at admission
 * time, so doing it at admission time gives up nothing.
 *
 * KEYED BY RUN. Iterating runs rather than dispatched-appids is what makes a
 * retry safe: a failed run #1 and a successful run #2 for one appid are two
 * keys, and #1 is resolved from ITS OWN outcome - so #1 can never be credited
 * with the artifact #2 committed. Only a run that deriveOutcome calls
 * "published" ever reads an artifact at all.
 *
 * NEVER WRITES A NUMBER IT DID NOT READ. A run still in flight, a cost that
 * cannot be parsed, an artifact that is not there, a verdict predating the cost
 * field - all skip, leaving the full reservation standing until a later sweep.
 * A terminal FAILURE instead records the null sentinel: qr4_failed and
 * stage_failed delete or never write the artifact and the runner's filesystem
 * is gone, so that cost is unrecoverable for good. Recording null keeps the
 * full 13 and stops the sweep re-checking it on every future dispatch.
 *
 * A reservation whose run never appeared at all (a lost dispatch) has nothing
 * to iterate and is never reconciled. It keeps its full charge for the day,
 * which is the safe reading of "we do not know what happened".
 */
export async function sweepReconciliations(
  state: QuotaState,
  deps: SweepDeps,
  limit = SWEEP_LIMIT,
): Promise<QuotaState> {
  const reserved = new Set(Object.keys(state.dispatched ?? {}));
  if (reserved.size === 0) return state;
  const known = state.reconciled ?? {};

  // listRuns returns oldest-first; keep that order so the cap drains a backlog
  // rather than repeatedly re-examining the newest few.
  const pending = (await deps.listRuns())
    .filter(
      (r) =>
        r.appid !== null &&
        reserved.has(r.appid) &&
        !isActive(r) &&
        !(reconcileKey(r.appid, r.id) in known),
    )
    .slice(0, limit);
  if (pending.length === 0) return state;

  const found: Record<string, number | null> = {};
  for (const run of pending) {
    const appid = run.appid as string;
    const outcome = await deps.runOutcome(run.id);
    if (outcome === null) continue;                 // not terminal after all
    if (outcome !== "published") {
      found[reconcileKey(appid, run.id)] = null;    // cost gone for good
      continue;
    }
    const cost = await deps.fetchVerdictCost(appid);
    if (cost === null) continue;                    // no real number in hand
    found[reconcileKey(appid, run.id)] = cost;
  }
  if (Object.keys(found).length === 0) return state;
  return { ...state, reconciled: { ...known, ...found } };
}

/**
 * One workflow step -> one stage dot in the progress feed.
 *
 * `skipped` IS A TRUTHY CONCLUSION. The old expression was
 * `s.conclusion ? "failed" : ...`, so when a run died at ingest the four stages
 * that never ran came back as `skipped` and rendered as four more failures. A
 * single real failure showed the user five red stages and implied the whole
 * pipeline collapsed.
 *
 * Skipped means DID NOT RUN, which on this feed is `pending` - the same thing a
 * stage shows before its turn. It is not a success and it is certainly not a
 * failure, and only the step that actually failed should be marked as one.
 */
export function uiStatus(s: { status: string; conclusion: string | null }) {
  if (s.conclusion === "success") return "completed";
  if (s.conclusion === "skipped") return "pending";
  if (s.conclusion) return "failed";        // failure, cancelled, timed_out
  return s.status === "in_progress" ? "in_progress" : "pending";
}

/** Step names of a run's job, in order — the five UI stages. */
export async function runSteps(runId: number) {
  const res = await gh(`/actions/runs/${runId}/jobs`);
  if (!res.ok) {
    return {
      status: "unknown", conclusion: null as string | null,
      steps: [] as { key: string; status: string }[],
    };
  }
  const { jobs = [] } = (await res.json()) as {
    jobs: {
      status: string;
      conclusion: string | null;
      steps?: { name: string; status: string; conclusion: string | null }[];
    }[];
  };
  const job = jobs[0];
  const UI = ["ingest", "filter", "extract", "verdict", "qr4"];
  const steps = (job?.steps ?? [])
    .filter((s) => UI.includes(s.name))
    .map((s) => ({
      key: s.name,
      status: uiStatus(s),
    }));
  return {
    status: job?.status ?? "unknown",
    conclusion: job?.conclusion ?? null,
    steps,
  };
}
