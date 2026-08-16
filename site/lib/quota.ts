/**
 * The global daily reserve, mirrored from pipeline/live_quota.py.
 *
 * Same JSON shape, same rules, two transports: Python reads a file, this reads
 * the LIVE_QUOTA repository variable. The reserve is GLOBAL on purpose - per-IP
 * cannot protect a global budget because the number of IPs is not bounded by
 * anything we control. Per-IP survives only as a secondary guard against one
 * client burning the shared reserve.
 */

// VERIFIED from the 429 body, not assumed: gemini-3.5-flash-lite is 500/day.
// This file mirrors pipeline/live_quota.py and had DRIFTED - it still carried
// 1500/300 after the Python side was corrected to 500/100, so the live path
// would authorise ~23 generations against a real remaining headroom of ~107.
export const DAILY_LIMIT = 500;
export const LIVE_RESERVE = 100;
export const IP_LIMIT_PER_HOUR = 5;
/**
 * Charged up front, in full, on every dispatch.
 *
 * NOTHING IN THE RUNNER EVER CORRECTS THIS. That is worth stating plainly
 * because this comment used to claim the opposite ("the workflow records the
 * actual"), and generate/route.ts carried the matching claim that "the workflow
 * writes the authoritative charge afterwards, so the ledger self-corrects".
 * Both described a bookkeeping step that was deleted: the runner's GITHUB_TOKEN
 * cannot write repository variables at all, so the step reported success while
 * writing nothing (see generate-verdict.yml, "THIS STEP NO LONGER RECORDS
 * ANYTHING"). A reservation stayed a reservation for the rest of the day.
 *
 * The correction now happens HERE, on the site side, from the cost the runner
 * writes into the verdict artifact it commits - see effectiveLiveUsed below.
 * 13 stays deliberately conservative: it is roughly p99 of measured cost, not a
 * true ceiling (one title in 295 spent 14), and reconciliation makes
 * over-reserving free, so the safe error is to keep reserving high.
 */
export const EST_COST = 13;

// Google resets RPD at MIDNIGHT PACIFIC, not midnight UTC. Keying the day on
// UTC zeroed this ledger seven hours early - the same defect fixed on the
// Python side in pipeline/quota_day.py. en-CA gives YYYY-MM-DD directly.
const PACIFIC = "America/Los_Angeles";
const today = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: PACIFIC });
const hour = () =>
  `${today()}T${new Date().toLocaleString("en-GB", {
    timeZone: PACIFIC, hour: "2-digit", hour12: false }).slice(0, 2)}`;

export interface QuotaState {
  date?: string;
  live_used?: number;
  generations?: number;
  by_ip_hour?: Record<string, number>;
  outcomes?: Record<string, { state: string; at: string; run_id?: string }>;
  /** appid -> ISO time we asked GitHub to create a run. See recordDispatch. */
  dispatched?: Record<string, string>;
  /**
   * `appid|run_id` -> what that generation ACTUALLY cost, or null when the cost
   * is unrecoverable. Facts, never arithmetic: see effectiveLiveUsed.
   */
  reconciled?: Record<string, number | null>;
}

/** The reconciliation key. Keyed by RUN, not by appid.
 *
 *  A retry after a stage_failed is a second dispatch, a second EST_COST charge
 *  and a second run - so it is a second key. Keying on appid alone would let
 *  one run's cost stand in for another's, in either direction. */
export const reconcileKey = (appid: number | string, runId: number | string) =>
  `${appid}|${runId}`;

/**
 * Live requests spent today, with completed generations corrected to what they
 * really cost.
 *
 * THE SHAPE IS THE WHOLE POINT, so it is worth saying why it is not a
 * decrement. The obvious implementation is "when a run finishes, subtract
 * (EST_COST - actual) from live_used", which needs a dedup marker so the same
 * generation is not credited twice - and under-counting is the one direction
 * that can hand out budget the Gemini quota does not have. A marker is then a
 * second thing that can land or fail to land independently of the correction.
 *
 * So there is no decrement and no marker. `live_used` stays the pure sum of
 * reservations, the ledger records the FACT of each run's cost, and the
 * corrected figure is derived here. That is idempotent by construction rather
 * than by protocol:
 *
 *   1. writing reconciled[key] = 9 five times equals writing it once - a set,
 *      not an increment, so "have I already applied this?" is never a question
 *      anyone has to answer correctly;
 *   2. this function is pure in (live_used, reconciled), so any reader
 *      recomputing it any number of times gets the same number;
 *   3. the fact and the counter are ONE JSON blob behind ONE PATCH, so there is
 *      no interleaving in which the dedup marker is durable and the correction
 *      is not.
 *
 * THE TERM IS ALLOWED TO GO NEGATIVE, and that is not an oversight. EST_COST is
 * ~p99 of measured cost, not a ceiling: 1 of 295 published titles spent 14. A
 * 14-call run therefore charges 1 MORE than it reserved. Clamping the term at
 * zero would silently under-count exactly the runs that overran, which is the
 * dangerous direction. Only the total is clamped, and only at zero.
 *
 * A null entry contributes nothing: it means "this run is finished and its cost
 * is unrecoverable, keep the full reservation" - see sweepReconciliations.
 */
export function effectiveLiveUsed(s: QuotaState): number {
  const correction = Object.values(s.reconciled ?? {}).reduce(
    (acc: number, actual) =>
      typeof actual === "number" ? acc + (EST_COST - actual) : acc,
    0,
  );
  return Math.max(0, (s.live_used ?? 0) - correction);
}

/**
 * How long a dispatched request may show no workflow run before we call it
 * lost. repository_dispatch returns 204 on ACCEPTANCE, not on run creation, and
 * the run takes a few seconds to appear - so a naive "no runs => lost" would
 * fire on every healthy request during that window.
 */
export const DISPATCH_GRACE_MS = 90_000;

export function recordDispatch(s: QuotaState, appid: number | string): QuotaState {
  const dispatched = { ...(s.dispatched ?? {}), [String(appid)]: new Date().toISOString() };
  // keep it bounded - this rides in a repository variable
  const trimmed = Object.fromEntries(Object.entries(dispatched).slice(-200));
  return { ...s, dispatched: trimmed };
}

/** true once a dispatch is old enough that a missing run means it never came. */
export function dispatchLost(s: QuotaState, appid: number | string, now = Date.now()) {
  const at = s.dispatched?.[String(appid)];
  if (!at) return false;          // never dispatched in this day's ledger
  return now - Date.parse(at) > DISPATCH_GRACE_MS;
}

export function rollDay(s: QuotaState): QuotaState {
  if (s.date !== today()) {
    return { date: today(), live_used: 0, generations: 0, by_ip_hour: {},
             outcomes: s.outcomes ?? {}, dispatched: {}, reconciled: {} };
  }
  return { live_used: 0, generations: 0, by_ip_hour: {}, outcomes: {},
           dispatched: {}, reconciled: {}, ...s };
}

/**
 * Headroom left in the reserve.
 *
 * Reads the DERIVED figure, not the raw counter, so every admission decision
 * downstream (canGenerate, and the status detail it reports) inherits the
 * correction from one place rather than each remembering to apply it.
 */
export function remaining(s: QuotaState, reserve = LIVE_RESERVE) {
  return Math.max(0, reserve - effectiveLiveUsed(s));
}

export type Denied = "reserve_exhausted" | "ip_limited";

export function canGenerate(
  s: QuotaState,
  ip: string,
  reserve = LIVE_RESERVE,
): { allowed: boolean; reason: "ok" | Denied; detail: Record<string, number | string> } {
  const left = remaining(s, reserve);
  // global first, so a rejection is attributed to the limit that actually
  // protects the quota rather than to the secondary guard
  if (left < EST_COST) {
    return {
      allowed: false,
      reason: "reserve_exhausted",
      detail: { remaining: left, reserve, resets: "00:00 America/Los_Angeles" },
    };
  }
  const used = s.by_ip_hour?.[`${ip}|${hour()}`] ?? 0;
  if (used >= IP_LIMIT_PER_HOUR) {
    return { allowed: false, reason: "ip_limited", detail: { used, limit: IP_LIMIT_PER_HOUR } };
  }
  return { allowed: true, reason: "ok", detail: { remaining: left } };
}

export function chargeReservation(s: QuotaState, ip: string): QuotaState {
  const key = `${ip}|${hour()}`;
  return {
    ...s,
    live_used: (s.live_used ?? 0) + EST_COST,
    generations: (s.generations ?? 0) + 1,
    by_ip_hour: { ...(s.by_ip_hour ?? {}), [key]: (s.by_ip_hour?.[key] ?? 0) + 1 },
  };
}
