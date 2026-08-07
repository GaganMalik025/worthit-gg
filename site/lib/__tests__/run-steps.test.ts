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

import { uiStatus } from "../github";

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
