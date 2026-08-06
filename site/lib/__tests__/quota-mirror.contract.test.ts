/**
 * CROSS-LANGUAGE CONSTANT GUARD
 *
 * site/lib/quota.ts says it mirrors pipeline/live_quota.py — "same JSON shape,
 * same rules, two transports". Nothing enforced it, and it drifted: the Python
 * side moved to DAILY_LIMIT 500 / LIVE_RESERVE 100 and a midnight-Pacific day
 * boundary, while the TypeScript kept 1500 / 300 and midnight UTC.
 *
 * That is not a cosmetic difference. The live path would have authorised ~23
 * generations against ~107 requests of real remaining headroom, and rolled its
 * day seven hours before the quota it is protecting actually resets. It sat
 * that way for days, because a mirror that is only asserted in a comment is not
 * a mirror.
 *
 * This test parses the Python and compares. A future edit to one file without
 * the other fails the build instead of drifting silently.
 *
 * NOTE ON CI SCOPE: ci.yml must trigger on the pipeline files too, not only on
 * site/**. A change to live_quota.py alone is exactly the case that caused this
 * drift, and it is the case a site-only path filter would miss.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { DAILY_LIMIT, IP_LIMIT_PER_HOUR, LIVE_RESERVE } from "../quota";

const REPO = path.resolve(__dirname, "../../..");
const py = (f: string) => readFileSync(path.join(REPO, "pipeline", f), "utf-8");

/** Read `NAME = 123` out of a Python module. Throws if absent, so a renamed or
 *  deleted constant fails loudly rather than silently comparing undefined. */
function pyInt(source: string, name: string): number {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*(\\d+)`, "m"));
  if (!m) throw new Error(`constant ${name} not found in the Python source`);
  return Number(m[1]);
}

describe("quota.ts mirrors pipeline/live_quota.py", () => {
  const liveQuota = py("live_quota.py");

  it("DAILY_LIMIT matches", () => {
    expect(DAILY_LIMIT).toBe(pyInt(liveQuota, "DAILY_LIMIT"));
  });

  it("LIVE_RESERVE matches", () => {
    expect(LIVE_RESERVE).toBe(pyInt(liveQuota, "LIVE_RESERVE"));
  });

  it("IP_LIMIT_PER_HOUR matches", () => {
    expect(IP_LIMIT_PER_HOUR).toBe(pyInt(liveQuota, "IP_LIMIT_PER_HOUR"));
  });

  it("both roll the quota day on the same timezone", () => {
    // Python's boundary lives in quota_day.py; the TS inlines the zone name.
    const zone = py("quota_day.py").match(/ZoneInfo\("([^"]+)"\)/)?.[1];
    expect(zone).toBe("America/Los_Angeles");
    const ts = readFileSync(path.join(REPO, "site/lib/quota.ts"), "utf-8");
    expect(ts).toContain(zone!);
    // and neither may quietly go back to a UTC day key
    expect(ts).not.toMatch(/const today = \(\) =>\s*new Date\(\)\.toISOString\(\)/);
  });

  it("the reserve leaves a sane batch budget", () => {
    // catches a swap that keeps both files equal but sets a nonsense pair,
    // e.g. a reserve larger than the day
    expect(LIVE_RESERVE).toBeGreaterThan(0);
    expect(LIVE_RESERVE).toBeLessThan(DAILY_LIMIT);
  });
});
