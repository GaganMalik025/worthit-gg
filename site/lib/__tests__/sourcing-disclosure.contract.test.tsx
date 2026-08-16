/**
 * THE SOURCING DISCLOSURE IS NUMBERLESS, AND THAT IS THE WHOLE DESIGN
 *
 * pipeline/sourcing.py writes a `sourcing` block onto every cohort that renders
 * claims. Two fields are allowed to drive rendering - `level` and `triggers`.
 * The rest (`cited_reviews`, `cited_recommend`, `divergence_p`) are pipeline
 * diagnostics, carried so the contract test can recompute them, and invariant
 * 13 keeps every post-filter count off the page.
 *
 * B1 - printing the cited count - was considered and rejected on 2026-08-17 for
 * three reasons this test is the enforcement of:
 *
 *   1. DESIGN.md:238 calls the per-claim receipts tag "the one sanctioned
 *      non-pool number on the page". A cohort-level count is a second one, and
 *      that needs an explicit DESIGN.md amendment as its own decision.
 *   2. ADJACENCY. The stats line directly above says "based on 439 reviews".
 *      A "6 reviews" beneath it invites the reader to compute 6/439 - a
 *      prevalence inference from sample counts, which invariant 11 forbids.
 *   3. ARITHMETIC. 77.3% of cohorts cite some review from more than one claim
 *      (15,736 citation instances over 11,882 distinct review-cohort pairs), so
 *      a distinct count is NOT the sum of the receipts tags above it and cannot
 *      honestly be presented as one.
 *
 * normalizeVerdict spreads the raw object, so the counts genuinely reach the
 * component - as with `cost`, a comment could not hold this.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage, sourcingNote } from "../../components/VerdictPage";
import { normalizeVerdict, type Sourcing, type Verdict } from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const APPID = 233860; // Kenshi - committed seed, real pipeline output

const readRepoFile = (p: string) => readFile(path.join(REPO, p), "utf-8");

/** Not plausible counts. A real 6 appears in a hundred innocent places on the
 *  page, so it could not distinguish "the count rendered" from "the page
 *  contains a 6". These cannot occur by accident. */
const SENTINEL_REVIEWS = 8675309;
const SENTINEL_RECOMMEND = 5551212;
const SENTINEL_BASIS = "SOURCING-BASIS-SENTINEL-DO-NOT-RENDER";

function sentinel(level: Sourcing["level"], triggers: Sourcing["triggers"]) {
  return {
    level,
    triggers,
    cited_reviews: SENTINEL_REVIEWS,
    cited_recommend: SENTINEL_RECOMMEND,
    divergence_p: 0.0000123456,
    basis: SENTINEL_BASIS,
  };
}

async function verdictWith(
  level: Sourcing["level"],
  triggers: Sourcing["triggers"],
): Promise<Verdict> {
  const raw = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
  for (const c of raw.cohorts ?? []) {
    if (!c.muted && (c.themes ?? []).length) c.sourcing = sentinel(level, triggers);
  }
  return normalizeVerdict(raw);
}

describe("sourcing disclosure", () => {
  it("the counts survive normalizeVerdict - so the assertions below are real", async () => {
    const v = await verdictWith("baseline", []);
    const live = v.cohorts.find((c) => c.sourcing);
    expect(live?.sourcing?.cited_reviews).toBe(SENTINEL_REVIEWS);
  });

  it("no count, denominator or probability reaches the markup", async () => {
    for (const [level, triggers] of [
      ["baseline", []],
      ["escalated", ["thin"]],
      ["escalated", ["divergent"]],
      ["escalated", ["thin", "divergent"]],
    ] as [Sourcing["level"], Sourcing["triggers"]][]) {
      const markup = renderToStaticMarkup(
        <VerdictPage verdict={await verdictWith(level, triggers)} />,
      );
      expect(markup).not.toContain(String(SENTINEL_REVIEWS));
      expect(markup).not.toContain(String(SENTINEL_RECOMMEND));
      expect(markup).not.toContain(SENTINEL_BASIS);
      expect(markup).not.toContain("0.0000123456");
      expect(markup.toLowerCase()).not.toContain("cited_reviews");
    }
  });

  it("the note itself contains no digit at all, under every trigger combination", () => {
    // The strongest form of the rule, and the one that survives refactoring:
    // whatever the copy becomes, it may not acquire a number.
    for (const triggers of [
      [],
      ["thin"],
      ["divergent"],
      ["thin", "divergent"],
    ] as Sourcing["triggers"][]) {
      const note = sourcingNote(
        sentinel(triggers.length ? "escalated" : "baseline", triggers),
      );
      expect(note).toBeTruthy();
      expect(note).not.toMatch(/\d/);
    }
  });

  it("the canary proves the searches would find something if it DID render", async () => {
    const markup = renderToStaticMarkup(
      <VerdictPage verdict={await verdictWith("baseline", [])} />,
    );
    expect(markup).toContain("Kenshi");
    expect(markup).toContain("come from the reviews that described something specific");
  });

  it("tier 1 is unconditional, and escalation adds to it rather than replacing it", () => {
    // Divergence is the catalog's normal state (21.4% of sections past -40
    // points, 1 of 1,077 the other way), so the baseline note must appear on
    // every cohort - a note that fired only on the tail would certify the rest
    // by silence. Escalation is a clause on the same sentence.
    const base = sourcingNote(sentinel("baseline", []))!;
    expect(base).toContain("The rate above covers all reviews in this cohort");
    for (const triggers of [
      ["thin"],
      ["divergent"],
      ["thin", "divergent"],
    ] as Sourcing["triggers"][]) {
      const note = sourcingNote(sentinel("escalated", triggers))!;
      expect(note).toContain("The rate above covers all reviews in this cohort");
      expect(note.length).toBeGreaterThan(base.length);
    }
    expect(sourcingNote(sentinel("escalated", ["divergent"]))).toContain(
      "more negative",
    );
    expect(sourcingNote(sentinel("escalated", ["thin"]))).toContain(
      "unusually small",
    );
  });

  it("renders nothing where nothing is claimed beneath the heading", async () => {
    // A muted cohort (invariant 12) and a cohort whose claims all dropped both
    // ship sourcing: null. "The points below" under an empty section would be
    // a statement about nothing.
    const raw = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
    for (const c of raw.cohorts ?? []) c.sourcing = null;
    const markup = renderToStaticMarkup(
      <VerdictPage verdict={normalizeVerdict(raw)} />,
    );
    expect(markup).toContain("Kenshi");
    expect(markup).not.toContain("The rate above covers all reviews");
  });

  it("a verdict predating the field renders without throwing", async () => {
    // Verdicts on the `verdicts` branch generated before 2026-08-17 have no
    // sourcing key at all. They must render as they did, not crash.
    const raw = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
    for (const c of raw.cohorts ?? []) delete c.sourcing;
    const v = normalizeVerdict(raw);
    expect(v.cohorts.every((c) => c.sourcing === null)).toBe(true);
    expect(
      renderToStaticMarkup(<VerdictPage verdict={v} />).length,
    ).toBeGreaterThan(1000);
  });
});
