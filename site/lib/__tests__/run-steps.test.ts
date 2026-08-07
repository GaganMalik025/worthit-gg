/**
 * STEP -> STAGE MAPPING
 *
 * The fixture below is not invented: it is the literal step shape GitHub
 * returned for generate-verdict run #3 (id 31177627980), the live-generation
 * test that died at ingest. Every stage after ingest came back `skipped`, the
 * old mapping read any truthy conclusion as a failure, and the user watching
 * the progress feed saw FIVE red stages for one real failure.
 *
 * Keeping the real payload as the fixture means this test fails for the reason
 * the bug happened, rather than for a shape we imagined.
 */

import { describe, expect, it } from "vitest";

import { deriveOutcome, runAppid, uiStatus } from "../github";

/** run #3's actual steps, verbatim from /actions/runs/31177627980/jobs */
const RUN_3 = [
  { name: "ingest", status: "completed", conclusion: "failure" },
  { name: "filter", status: "completed", conclusion: "skipped" },
  { name: "extract", status: "completed", conclusion: "skipped" },
  { name: "verdict", status: "completed", conclusion: "skipped" },
  { name: "qr4", status: "completed", conclusion: "skipped" },
];

describe("uiStatus", () => {
  it("marks only the step that actually failed", () => {
    const mapped = RUN_3.map(uiStatus);
    expect(mapped).toEqual(["failed", "pending", "pending", "pending", "pending"]);
    expect(mapped.filter((s) => s === "failed")).toHaveLength(1);
  });

  it("skipped is not a failure and not a success", () => {
    const s = uiStatus({ status: "completed", conclusion: "skipped" });
    expect(s).toBe("pending");
    expect(s).not.toBe("failed");
    expect(s).not.toBe("completed");
  });

  it("still reports real terminal failures", () => {
    for (const c of ["failure", "cancelled", "timed_out"]) {
      expect(uiStatus({ status: "completed", conclusion: c })).toBe("failed");
    }
  });

  it("reports success and in-flight states unchanged", () => {
    expect(uiStatus({ status: "completed", conclusion: "success" })).toBe("completed");
    expect(uiStatus({ status: "in_progress", conclusion: null })).toBe("in_progress");
    expect(uiStatus({ status: "queued", conclusion: null })).toBe("pending");
  });
});

describe("runAppid", () => {
  it("reads the appid out of the run-name", () => {
    expect(runAppid({ display_title: "verdict 1547000" })).toBe("1547000");
    expect(runAppid({ name: "verdict 233860" })).toBe("233860");
  });

  it("returns null rather than guessing", () => {
    // runs created before run-name existed, and the workflow's own name
    expect(runAppid({ display_title: "generate-verdict" })).toBeNull();
    expect(runAppid({})).toBeNull();
  });

  it("does not match a different workflow that happens to carry a number", () => {
    expect(runAppid({ display_title: "publish 12 verdicts" })).toBeNull();
  });
});

describe("deriveOutcome", () => {
  const ok = [
    { key: "ingest", status: "completed" }, { key: "filter", status: "completed" },
    { key: "extract", status: "completed" }, { key: "verdict", status: "completed" },
    { key: "qr4", status: "completed" },
  ];

  it("a fully successful run is published", () => {
    expect(deriveOutcome("completed", "success", ok)).toBe("published");
  });

  it("run #3's shape - died at ingest - is stage_failed", () => {
    expect(deriveOutcome("completed", "failure", [
      { key: "ingest", status: "failed" }, { key: "filter", status: "pending" },
      { key: "extract", status: "pending" }, { key: "verdict", status: "pending" },
      { key: "qr4", status: "pending" },
    ])).toBe("stage_failed");
  });

  it("a QR-4 rejection is its own state, not a generic failure", () => {
    expect(deriveOutcome("completed", "failure", [
      ...ok.slice(0, 4), { key: "qr4", status: "failed" },
    ])).toBe("qr4_failed");
  });

  it("a run that failed BEFORE any stage is still terminal", () => {
    // e.g. the seed step now failing loudly: no UI step ran at all, but the
    // client must still be told to stop polling.
    expect(deriveOutcome("completed", "failure", [])).toBe("stage_failed");
  });

  it("an unfinished run is not terminal", () => {
    expect(deriveOutcome("in_progress", null, ok)).toBeNull();
    expect(deriveOutcome("queued", null, [])).toBeNull();
  });
});
