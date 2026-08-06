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
export const EST_COST = 13; // charged up front; the workflow records the actual

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
             outcomes: s.outcomes ?? {}, dispatched: {} };
  }
  return { live_used: 0, generations: 0, by_ip_hour: {}, outcomes: {}, dispatched: {}, ...s };
}

export function remaining(s: QuotaState, reserve = LIVE_RESERVE) {
  return Math.max(0, reserve - (s.live_used ?? 0));
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
