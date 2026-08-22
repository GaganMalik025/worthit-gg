/**
 * `n_note` IS A PIPELINE DIAGNOSTIC AND MUST NEVER REACH THE PAGE
 *
 * synthesize.py:663 writes a preformatted string onto every muted cohort:
 *
 *     "n=0 - too few reviews to call"
 *
 * That number is the count of reviews SURVIVING THE FILTER, not the pool figure
 * sitting beside it in the same object. Measured on 2026-08-17 across all 346
 * verdicts then published: 135 muted cohorts, and 132 of them carry an `n_note`
 * that disagrees with their own `pool_n`. Path of Exile's refund_window is
 * `pool_n` 77 against `n=18`; Hotline Miami's veteran cohort is `pool_n` 1
 * against `n=0`.
 *
 * Invariant 13 says every user-facing number is a pool figure, and post-filter
 * counts are diagnostics that never render. `n_note` is the most dangerous
 * diagnostic in the schema, and not because it is the largest error:
 *
 *   - Every other tolerated diagnostic is a bare number a renderer would have
 *     to compose into a sentence deliberately. This one arrives PRE-COMPOSED in
 *     the exact register of the UI - `n=` prefix, dashed explanation - ready to
 *     drop into a JSX expression.
 *   - It sits in the view model directly beside the field that should be used.
 *     VerdictPage builds the muted label itself from `pool_n`; writing
 *     `{c.n_note}` instead is a one-token edit.
 *   - The resulting page would look completely plausible. A SMALLER number under
 *     a "too few reviews" heading reads as more correct, not less, so nothing
 *     about the output would prompt anyone to check it.
 *
 * The 2026-08-10 sourcing work established this guard shape (cdebb6d) for
 * exactly this hazard, and `n_note` had no equivalent until now. This file is
 * that equivalent. It does not rename or restructure the field - the field is
 * fine where it is, it simply may not be rendered.
 *
 * normalizeVerdict spreads the raw cohort and maps `n_note` explicitly
 * (verdict.ts:159), so the sentinel genuinely reaches the component. A comment
 * could not hold this; only a failing test can.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { normalizeVerdict, type Verdict } from "../verdict";

const REPO = path.resolve(__dirname, "../..");

/** Hotline Miami. Chosen because it genuinely HAS a muted cohort (veteran,
 *  1 of 400 reviews, filtered to 0) in committed pipeline output. Kenshi - the
 *  fixture the sourcing contract test uses - has no muted cohort at all, so it
 *  cannot carry this test: every assertion below would pass vacuously. */
const APPID = 219150;

/** Not a plausible count. A real 0 or 18 appears in a hundred innocent places
 *  in the markup, so it could not distinguish "the note rendered" from "the
 *  page contains a zero". These cannot occur by accident. */
const SENTINEL_COUNT = 8675309;
const SENTINEL_NOTE = `n=${SENTINEL_COUNT} - N-NOTE-SENTINEL-DO-NOT-RENDER`;

async function mutedVerdict(): Promise<{ verdict: Verdict; muted: number }> {
  const raw = JSON.parse(
    await readFile(path.join(REPO, `public/verdicts/${APPID}.json`), "utf-8"),
  );
  let muted = 0;
  for (const c of raw.cohorts ?? []) {
    if (c.muted) {
      c.n_note = SENTINEL_NOTE;
      muted += 1;
    }
  }
  return { verdict: normalizeVerdict(raw), muted };
}

describe("n_note never renders", () => {
  it("the fixture really has a muted cohort - or every assertion here is vacuous", async () => {
    const { muted } = await mutedVerdict();
    expect(muted).toBeGreaterThan(0);
  });

  it("the sentinel survives normalizeVerdict - so the assertions below are real", async () => {
    const { verdict } = await mutedVerdict();
    const cohort = verdict.cohorts.find((c) => c.muted);
    expect(cohort).toBeTruthy();
    expect(cohort?.n_note).toBe(SENTINEL_NOTE);
  });

  it("no part of n_note reaches the markup", async () => {
    const { verdict } = await mutedVerdict();
    const markup = renderToStaticMarkup(<VerdictPage verdict={verdict} />);
    expect(markup).not.toContain(SENTINEL_NOTE);
    expect(markup).not.toContain("N-NOTE-SENTINEL-DO-NOT-RENDER");
    expect(markup).not.toContain(String(SENTINEL_COUNT));
    expect(markup.toLowerCase()).not.toContain("n_note");
  });

  it("the muted label that DOES render is built from the pool figure", async () => {
    const { verdict } = await mutedVerdict();
    const markup = renderToStaticMarkup(<VerdictPage verdict={verdict} />);
    const muted = verdict.split_bar.filter((b) => b.muted);
    expect(muted.length).toBeGreaterThan(0);
    for (const b of muted) {
      expect(markup).toContain(`${b.pool_n} reviews · too few to call`);
    }
  });

  it("the canary proves the searches would find something if it DID render", async () => {
    // Without this, a VerdictPage that rendered nothing at all would pass every
    // not.toContain above. The searches have to be shown capable of hitting.
    const { verdict } = await mutedVerdict();
    const markup = renderToStaticMarkup(<VerdictPage verdict={verdict} />);
    expect(markup).toContain("Hotline Miami");
    expect(markup).toContain("too few to call");
  });
});
