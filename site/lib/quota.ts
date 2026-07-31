/**
 * The global daily reserve, mirrored from pipeline/live_quota.py.
 *
 * Same JSON shape, same rules, two transports: Python reads a file, this reads
 * the LIVE_QUOTA repository variable. The reserve is GLOBAL on purpose - per-IP
 * cannot protect a global budget because the number of IPs is not bounded by
 * anything we control. Per-IP survives only as a secondary guard against one
 * client burning the shared reserve.
 */

export const DAILY_LIMIT = 1500;
export const LIVE_RESERVE = 300;
export const IP_LIMIT_PER_HOUR = 5;
export const EST_COST = 13; // charged up front; the workflow records the actual

const today = () => new Date().toISOString().slice(0, 10);
const hour = () => new Date().toISOString().slice(0, 13);

export interface QuotaState {
  date?: string;
  live_used?: number;
  generations?: number;
  by_ip_hour?: Record<string, number>;
  outcomes?: Record<string, { state: string; at: string; run_id?: string }>;
}

export function rollDay(s: QuotaState): QuotaState {
  if (s.date !== today()) {
    return { date: today(), live_used: 0, generations: 0, by_ip_hour: {}, outcomes: s.outcomes ?? {} };
  }
  return { live_used: 0, generations: 0, by_ip_hour: {}, outcomes: {}, ...s };
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
      detail: { remaining: left, reserve, resets: "00:00 UTC" },
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
