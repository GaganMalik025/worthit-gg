/**
 * Two behaviours probed for the 2026-11-03 codebase analysis. A MEASUREMENT
 * DRIVER, not part of the site suite: it prints what happens and asserts only
 * that the probe ran, so a green result is not a statement that either is fine.
 *
 *   site/node_modules/.bin/vitest run \
 *     --config evals/analysis-2026-11-03.vitest.config.ts
 */
import { readFileSync } from "node:fs";
import { createElement } from "../site/node_modules/react/index.js";
import { renderToStaticMarkup } from "../site/node_modules/react-dom/server.node.js";
import { VerdictPage } from "../site/components/VerdictPage";
import { sweepReconciliations } from "../site/lib/github";
import { effectiveLiveUsed } from "../site/lib/quota";
import { normalizeVerdict } from "../site/lib/verdict";

test("sweep: a previous quota day's run of the same appid", async () => {
  const state = {
    date: "2026-11-03",
    live_used: 13,
    dispatched: { "42": "2026-11-03T10:00:00Z" },
    reconciled: {},
  };
  const out = await sweepReconciliations(state, {
    listRuns: async () => [
      { id: 1, status: "completed", conclusion: "success",
        created_at: "2026-11-02T10:00:00Z", appid: "42" },
      { id: 2, status: "queued", conclusion: null,
        created_at: "2026-11-03T10:00:01Z", appid: "42" },
    ],
    runOutcome: async () => "published" as const,
    fetchVerdictCost: async () => 5,
  });
  console.log(
    `sweep: one reservation today, its run still queued -> reconciled=` +
      `${JSON.stringify(out.reconciled)} raw=${out.live_used} ` +
      `effective=${effectiveLiveUsed(out)}`,
  );
  expect(out.live_used).toBe(13);
});

test("render: a cohort whose pool holds zero reviews", () => {
  // pipeline/fetch_reviews.pool_stats writes pct_positive None for an empty
  // bucket. Hotline Miami (219150) has 1 veteran in its pool; this is that title
  // with 0, which is what a slightly shorter game would produce.
  const raw = JSON.parse(
    readFileSync("site/public/verdicts/219150.json", "utf-8"),
  );
  for (const row of [...raw.split_bar, ...raw.cohorts]) {
    if (row.bucket === "veteran") {
      row.pool_n = 0;
      row.pct_positive = null;
    }
  }
  let outcome = "rendered";
  try {
    renderToStaticMarkup(
      createElement(VerdictPage, { verdict: normalizeVerdict(raw) }),
    );
  } catch (exc) {
    outcome = `THROWS: ${(exc as Error).message}`;
  }
  console.log(`render with pool_n=0, pct_positive=null: ${outcome}`);
  expect(outcome).toBeTruthy();
});
