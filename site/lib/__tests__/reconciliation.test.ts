/**
 * RESERVATION RECONCILIATION
 *
 * /api/generate charges EST_COST=13 before dispatching, because the check and
 * the spend cannot be atomic across a repository_dispatch boundary. Real cost
 * is a median of 9 (295 published titles in data/batch_state.json: p25 7,
 * median 9, p90 12, max 14), so ~34% of every reservation was budget nobody
 * spent and the ledger never learned otherwise.
 *
 * Two things are pinned here, and they are the two that can go wrong quietly.
 *
 * 1. THE CORRECTION IS A DERIVATION, NOT A DECREMENT. If it were a decrement it
 *    would need a dedup marker, and a marker can land when the correction does
 *    not. effectiveLiveUsed is a pure function of (live_used, reconciled), so
 *    applying the same fact twice cannot double-credit. The idempotency tests
 *    below are the whole reason the design has this shape.
 *
 * 2. IT MUST BE ABLE TO CORRECT UPWARD. EST_COST is ~p99 of measured cost, not
 *    a ceiling - 1 of 295 titles spent 14 - so a run that overran has to charge
 *    MORE than it reserved. Clamping the term at zero would under-count exactly
 *    those runs, and under-counting is what authorises generation against
 *    budget the Gemini quota does not have.
 *
 * Offline: no network, no token, no quota. The sweep's three IO calls are
 * injected, the same way pipeline/live_quota.py injects its `gh` runner.
 */

import { describe, expect, it, vi } from "vitest";

import {
  SWEEP_LIMIT,
  sweepReconciliations,
  type Outcome,
  type RunInfo,
  type SweepDeps,
} from "../github";
import {
  canGenerate,
  effectiveLiveUsed,
  EST_COST,
  LIVE_RESERVE,
  reconcileKey,
  remaining,
  rollDay,
  type QuotaState,
} from "../quota";

const IP = "203.0.113.7";

describe("effectiveLiveUsed", () => {
  it("is the raw counter when nothing has been reconciled", () => {
    expect(effectiveLiveUsed({ live_used: 26 })).toBe(26);
    expect(effectiveLiveUsed({ live_used: 26, reconciled: {} })).toBe(26);
  });

  it("gives back the difference between the reservation and the real cost", () => {
    // two dispatches reserved 26; one of them really cost 9
    const s: QuotaState = { live_used: 26, reconciled: { "413150|1": 9 } };
    expect(effectiveLiveUsed(s)).toBe(26 - (EST_COST - 9));
    expect(effectiveLiveUsed(s)).toBe(22);
  });

  /**
   * THE LOAD-BEARING ONE. A run that spent 14 overran its 13-request
   * reservation, so the ledger must end up HIGHER, not unchanged. Clamping the
   * per-entry term at zero passes every other test in this file and fails only
   * this one.
   */
  it("corrects UPWARD when a run cost more than it reserved", () => {
    const s: QuotaState = { live_used: 13, reconciled: { "413150|1": 14 } };
    expect(effectiveLiveUsed(s)).toBe(14);
    expect(effectiveLiveUsed(s)).toBeGreaterThan(13);
  });

  it("nets a cheap run against an expensive one", () => {
    const s: QuotaState = {
      live_used: 26,
      reconciled: { "413150|1": 14, "233860|2": 7 },
    };
    // -1 for the overrun, +6 for the cheap one
    expect(effectiveLiveUsed(s)).toBe(26 - (-1 + 6));
    expect(effectiveLiveUsed(s)).toBe(21);
  });

  it("a null entry keeps the whole reservation", () => {
    // qr4_failed / stage_failed: the artifact is gone and the cost with it
    const s: QuotaState = { live_used: 26, reconciled: { "413150|1": null } };
    expect(effectiveLiveUsed(s)).toBe(26);
  });

  it("never reports a negative total", () => {
    const s: QuotaState = { live_used: 5, reconciled: { "413150|1": 1 } };
    expect(effectiveLiveUsed(s)).toBe(0);
  });

  describe("idempotency", () => {
    it("re-applying the SAME fact changes nothing", () => {
      const once: QuotaState = { live_used: 13, reconciled: { "413150|1": 9 } };
      const twice: QuotaState = {
        live_used: 13,
        reconciled: { ...once.reconciled, "413150|1": 9 },
      };
      expect(effectiveLiveUsed(twice)).toBe(effectiveLiveUsed(once));
      expect(effectiveLiveUsed(twice)).toBe(9);
    });

    it("is stable over repeated evaluation", () => {
      const s: QuotaState = { live_used: 39, reconciled: { "1|1": 9, "2|2": 7 } };
      const reads = Array.from({ length: 5 }, () => effectiveLiveUsed(s));
      expect(new Set(reads).size).toBe(1);
    });

    it("a repeated sweep of an already-known run is a no-op on the state", async () => {
      // the end-to-end version of the same property: sweeping twice must not
      // credit the same generation twice
      const state: QuotaState = { dispatched: { "413150": "2026-08-16T10:00:00Z" } };
      const deps = depsFor({
        runs: [run(1, "413150")],
        outcomes: { 1: "published" },
        costs: { "413150": 9 },
      });
      const first = await sweepReconciliations(state, deps);
      const second = await sweepReconciliations(first, deps);
      expect(second.reconciled).toEqual({ "413150|1": 9 });
      expect(effectiveLiveUsed({ ...second, live_used: 13 })).toBe(9);
      // and the second pass did no work at all
      expect(deps.fetchVerdictCost).toHaveBeenCalledTimes(1);
    });
  });

  describe("the admission path reads the derived figure, not the raw one", () => {
    it("remaining() reflects a reconciled run", () => {
      const s: QuotaState = { live_used: 26, reconciled: { "413150|1": 9 } };
      expect(remaining(s)).toBe(LIVE_RESERVE - 22);
    });

    it("a reconciled run can re-open a reserve that reads exhausted", () => {
      // 96 reserved of 100 leaves 4 - below EST_COST, so live generation is off
      const raw: QuotaState = { live_used: 96, by_ip_hour: {} };
      expect(canGenerate(raw, IP).allowed).toBe(false);
      expect(canGenerate(raw, IP).reason).toBe("reserve_exhausted");

      // but four of those generations really cost 7, freeing 24 requests
      const reconciled: QuotaState = {
        ...raw,
        reconciled: { "1|1": 7, "2|2": 7, "3|3": 7, "4|4": 7 },
      };
      expect(effectiveLiveUsed(reconciled)).toBe(72);
      expect(canGenerate(reconciled, IP).allowed).toBe(true);
    });
  });

  it("rollDay clears the facts along with the counters", () => {
    const stale: QuotaState = {
      date: "1999-12-31",
      live_used: 91,
      reconciled: { "413150|1": 9 },
    };
    const rolled = rollDay(stale);
    expect(rolled.reconciled).toEqual({});
    expect(effectiveLiveUsed(rolled)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// the sweep
// ---------------------------------------------------------------------------

const run = (
  id: number,
  appid: string,
  status = "completed",
  created_at = `2026-08-16T10:${String(id).padStart(2, "0")}:00Z`,
): RunInfo => ({ id, status, conclusion: null, created_at, appid });

function depsFor(opts: {
  runs: RunInfo[];
  outcomes?: Record<number, Outcome>;
  costs?: Record<string, number | null>;
}): SweepDeps & { fetchVerdictCost: ReturnType<typeof vi.fn> } {
  return {
    listRuns: vi.fn(async () => opts.runs),
    runOutcome: vi.fn(async (id: number) => opts.outcomes?.[id] ?? null),
    fetchVerdictCost: vi.fn(async (appid: string) => opts.costs?.[appid] ?? null),
  };
}

const dispatched = (...appids: string[]): QuotaState => ({
  dispatched: Object.fromEntries(
    appids.map((a, i) => [a, `2026-08-16T10:0${i}:00Z`]),
  ),
});

describe("sweepReconciliations", () => {
  it("records the real cost of a published run", async () => {
    const deps = depsFor({
      runs: [run(1, "413150")],
      outcomes: { 1: "published" },
      costs: { "413150": 9 },
    });
    const out = await sweepReconciliations(dispatched("413150"), deps);
    expect(out.reconciled).toEqual({ "413150|1": 9 });
  });

  it("records the null sentinel for a terminal failure", async () => {
    // the artifact was deleted (qr4) or never written (stage_failed), and the
    // runner's filesystem is gone - this cost is unrecoverable for good
    for (const outcome of ["qr4_failed", "stage_failed"] as Outcome[]) {
      const deps = depsFor({
        runs: [run(1, "413150")],
        outcomes: { 1: outcome },
        costs: { "413150": 9 },   // an artifact exists, and must NOT be read
      });
      const out = await sweepReconciliations(dispatched("413150"), deps);
      expect(out.reconciled).toEqual({ "413150|1": null });
      expect(deps.fetchVerdictCost).not.toHaveBeenCalled();
    }
  });

  it("the null sentinel stops the run being re-examined forever", async () => {
    const deps = depsFor({
      runs: [run(1, "413150")],
      outcomes: { 1: "stage_failed" },
    });
    const first = await sweepReconciliations(dispatched("413150"), deps);
    await sweepReconciliations(first, deps);
    expect(deps.runOutcome).toHaveBeenCalledTimes(1);
  });

  describe("never writes a value it did not read", () => {
    it("skips a run that is still going", async () => {
      const deps = depsFor({
        runs: [run(1, "413150", "in_progress")],
        outcomes: { 1: "published" },
        costs: { "413150": 9 },
      });
      const out = await sweepReconciliations(dispatched("413150"), deps);
      expect(out.reconciled ?? {}).toEqual({});
      expect(deps.runOutcome).not.toHaveBeenCalled();
    });

    it("skips a published run whose cost cannot be read", async () => {
      // 404, unparseable JSON, a verdict predating the cost field, or a 0 -
      // fetchVerdictCost collapses all of them to null
      const deps = depsFor({
        runs: [run(1, "413150")],
        outcomes: { 1: "published" },
        costs: { "413150": null },
      });
      const out = await sweepReconciliations(dispatched("413150"), deps);
      expect(out.reconciled ?? {}).toEqual({});
      // left standing at the full reservation - the safe direction
      expect(effectiveLiveUsed({ ...out, live_used: 13 })).toBe(13);
    });

    it("skips a run deriveOutcome cannot call terminal", async () => {
      const deps = depsFor({ runs: [run(1, "413150")], outcomes: {} });
      const out = await sweepReconciliations(dispatched("413150"), deps);
      expect(out.reconciled ?? {}).toEqual({});
    });
  });

  /**
   * MIS-ATTRIBUTION. A stage_failed run #1 is retried as run #2, which
   * publishes. Both charged EST_COST, so both need a key - and #1 must NOT be
   * credited with the artifact #2 committed, which is the only artifact on the
   * branch for that appid. Resolving each run from its OWN outcome is what
   * prevents it; keying by appid alone could not.
   */
  it("does not credit a failed run with a later run's artifact", async () => {
    const deps = depsFor({
      runs: [run(1, "413150"), run(2, "413150")],
      outcomes: { 1: "stage_failed", 2: "published" },
      costs: { "413150": 9 },
    });
    const out = await sweepReconciliations(dispatched("413150"), deps);
    expect(out.reconciled).toEqual({ "413150|1": null, "413150|2": 9 });
    // the artifact was read once, for the run that actually produced it
    expect(deps.fetchVerdictCost).toHaveBeenCalledTimes(1);
    // and the refund is one run's worth, not two
    expect(effectiveLiveUsed({ ...out, live_used: 26 })).toBe(22);
  });

  it("caps the sweep, oldest first", async () => {
    const runs = Array.from({ length: 9 }, (_, i) => run(i + 1, String(i + 1)));
    const deps = depsFor({
      runs,
      outcomes: Object.fromEntries(runs.map((r) => [r.id, "published"])),
      costs: Object.fromEntries(runs.map((r) => [r.appid as string, 9])),
    });
    const out = await sweepReconciliations(
      dispatched(...runs.map((r) => r.appid as string)),
      deps,
    );
    const keys = Object.keys(out.reconciled ?? {});
    expect(keys).toHaveLength(SWEEP_LIMIT);
    expect(keys).toEqual(["1|1", "2|2", "3|3", "4|4", "5|5"]);
  });

  it("drains a backlog across successive sweeps", async () => {
    const runs = Array.from({ length: 7 }, (_, i) => run(i + 1, String(i + 1)));
    const deps = depsFor({
      runs,
      outcomes: Object.fromEntries(runs.map((r) => [r.id, "published"])),
      costs: Object.fromEntries(runs.map((r) => [r.appid as string, 9])),
    });
    const appids = runs.map((r) => r.appid as string);
    const first = await sweepReconciliations(dispatched(...appids), deps);
    const second = await sweepReconciliations(first, deps);
    expect(Object.keys(second.reconciled ?? {})).toHaveLength(7);
  });

  it("costs nothing when there is nothing reserved", async () => {
    const deps = depsFor({ runs: [run(1, "413150")] });
    const out = await sweepReconciliations({}, deps);
    expect(out).toEqual({});
    expect(deps.listRuns).not.toHaveBeenCalled();
  });

  it("ignores runs for appids this ledger never reserved", async () => {
    // a batch-era or manually-triggered run must not invent a correction
    const deps = depsFor({
      runs: [run(1, "999999")],
      outcomes: { 1: "published" },
      costs: { "999999": 9 },
    });
    const out = await sweepReconciliations(dispatched("413150"), deps);
    expect(out.reconciled ?? {}).toEqual({});
  });

  it("leaves a lost dispatch at its full reservation", async () => {
    // dispatched, but GitHub never created a run: nothing to iterate, so
    // nothing is reconciled and the charge stands
    const deps = depsFor({ runs: [] });
    const out = await sweepReconciliations(dispatched("413150"), deps);
    expect(out.reconciled ?? {}).toEqual({});
    expect(effectiveLiveUsed({ ...out, live_used: 13 })).toBe(13);
  });
});
