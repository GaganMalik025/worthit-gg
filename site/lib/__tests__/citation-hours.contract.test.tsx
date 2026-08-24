/**
 * MINUTES ARE A PRECISION INPUT AND MUST NEVER BE DISPLAYED
 *
 * Citations carry `minutes_at_review` so the hours figure shown beneath a
 * cohort heading can be kept inside that cohort. The bucket is assigned on raw
 * minutes (invariant 2); the display was rounded from hours; the two disagree
 * on the boundary. 118 minutes IS `refund_window` and always was, but
 * 118/60 = 1.966 rounds to "2.0 hrs" and rendered under "<2h refund window".
 * 78 citation instances across 514 verdicts read that way (BACKLOG 2026-08-17).
 *
 * CLAUDE.md invariant 1 says minutes must never reach an LLM prompt, and must
 * never be shown to a reader. Carrying them into the citation record puts them
 * one careless `{cit.minutes_at_review}` away from the page - the same hazard
 * shape as `n_note`, and the same reason the 2026-08-10 sourcing work built a
 * sentinel guard instead of trusting a comment. This file is that guard for the
 * minutes half of invariant 1, and it is what the invariant's wording now points
 * at.
 *
 * The 60x silent error is exactly what makes this worth a test: a minutes value
 * rendered as hours looks like a plausible number, not like a bug.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { citationHours, normalizeVerdict, type Citation, type Verdict } from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const APPID = 107410; // Arma 3 - carries the entry's own example, 230637493
const EXAMPLE = "230637493";

/** Implausible as a real playtime, so a hit cannot be a coincidence. A real
 *  118 shows up all over a page of review text. */
const SENTINEL_MINUTES = 8675309;

async function verdict(mutate?: (c: Citation) => void): Promise<Verdict> {
  const raw = JSON.parse(
    await readFile(path.join(REPO, `public/verdicts/${APPID}.json`), "utf-8"),
  );
  if (mutate) {
    for (const c of raw.cohorts ?? []) {
      for (const t of c.themes ?? []) {
        for (const cl of t.claims ?? []) {
          for (const cit of cl.citations ?? []) mutate(cit);
        }
      }
    }
  }
  return normalizeVerdict(raw);
}

describe("citation hours", () => {
  it("minutes survive normalizeVerdict - so the assertions below are real", async () => {
    const v = await verdict();
    const all = v.cohorts.flatMap((c) =>
      c.themes.flatMap((t) => t.claims.flatMap((cl) => cl.citations)),
    );
    expect(all.length).toBeGreaterThan(0);
    expect(all.some((c) => typeof c.minutes_at_review === "number")).toBe(true);
  });

  it("no raw minutes value reaches the markup", async () => {
    const v = await verdict((c) => {
      c.minutes_at_review = SENTINEL_MINUTES;
    });
    const markup = renderToStaticMarkup(<VerdictPage verdict={v} />);
    expect(markup).not.toContain(String(SENTINEL_MINUTES));
    expect(markup.toLowerCase()).not.toContain("minutes_at_review");
    expect(markup).not.toContain("min ·");
  });

  it("the boundary case renders inside its own cohort, not outside it", () => {
    // 118 minutes under refund_window: 1.966h. Rounding gives 2.0, which reads
    // as outside "<2h". Flooring gives 1.9, which is true to the bucket.
    const cit = { minutes_at_review: 118, hours_at_review: 2.0 } as Citation;
    expect(citationHours(cit, "refund_window")).toBe("1.9");
    expect(citationHours({ minutes_at_review: 5997 } as Citation, "mid")).toBe("99.9");
    expect(citationHours({ minutes_at_review: 1199 } as Citation, "early")).toBe("19.9");
  });

  it("ordinary values are untouched - this is a boundary fix, not a rounding change", () => {
    expect(citationHours({ minutes_at_review: 60 } as Citation, "refund_window")).toBe("1.0");
    expect(citationHours({ minutes_at_review: 3168 } as Citation, "mid")).toBe("52.8");
    expect(citationHours({ minutes_at_review: 12000 } as Citation, "veteran")).toBe("200.0");
    // veteran has no upper bound; nothing may be floored off the top of it
    expect(citationHours({ minutes_at_review: 599940 } as Citation, "veteran")).toBe("9999.0");
  });

  it("without minutes it is exactly today's behaviour", () => {
    // The 27 citations the page cache cannot supply, and every verdict
    // generated before the backfill, must render as they always have.
    const cit = { hours_at_review: 2.0 } as Citation;
    expect(citationHours(cit, "refund_window")).toBe("2.0");
    expect(citationHours({ hours_at_review: null } as Citation, "early")).toBe("0.0");
  });

  it("the real Arma 3 citation the BACKLOG entry names renders as 1.9", async () => {
    const v = await verdict();
    let found: Citation | undefined;
    let bucket = "";
    for (const c of v.cohorts) {
      for (const t of c.themes) {
        for (const cl of t.claims) {
          for (const cit of cl.citations) {
            if (cit.recommendationid === EXAMPLE) {
              found = cit;
              bucket = c.bucket;
            }
          }
        }
      }
    }
    expect(found).toBeTruthy();
    expect(bucket).toBe("refund_window");
    expect(found!.minutes_at_review).toBe(118);
    expect(citationHours(found!, bucket)).toBe("1.9");

    const markup = renderToStaticMarkup(<VerdictPage verdict={v} />);
    expect(markup).toContain("1.9 hrs");
  });
});
