/**
 * ONE-REVIEWER POINTS CONTRACT (owner, 2026-11-16)
 *
 * The meaning check (pipeline/verify_claims.py) sends a point only one review makes
 * to its own section instead of padding it with a second review that does not say
 * it. What this pins on the page:
 *
 *   - both loaders render it identically (the dual-path contract, extended)
 *   - it is one slim section, closed by default, below the flags and above the
 *     first cohort
 *   - its summary carries NO COUNT (invariant 13: a count of points would be a
 *     post-filter number on the page)
 *   - points are grouped under their cohort's label
 *   - a muted cohort shows none (invariant 12)
 *   - review text is reachable only behind the receipts expand (invariant 9)
 *   - every verdict generated before the meaning check renders no section at all
 *
 * No committed verdict carries single_points yet: the catalog regeneration is what
 * produces them. So the fixture is synthetic, built on a real one, the same way the
 * split-header test in verdict-render.contract.test.tsx had to be.
 *
 * Run: cd site && npm test
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { loadVerdictProxied, loadVerdictStatic, normalizeVerdict, type Verdict } from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const APPID = 233860; // Kenshi - committed seed, real pipeline output
const FIXTURES = [233860, 1091500, 379720, 413150, 553850, 1190460];
const readRepoFile = (p: string) => readFile(path.join(REPO, p), "utf-8");
const render = (v: Verdict) => renderToStaticMarkup(<VerdictPage verdict={v} />);

const POINT_A = "One reviewer says the starting zone punishes early exploration.";
const POINT_B = "One reviewer says squad pathing breaks on steep terrain.";
const SENTINEL_REVIEW = "SENTINEL-REVIEW-TEXT the hills ate my squad";

/** Kenshi, with one-reviewer points on two unmuted cohorts and one muted cohort. */
async function fixture() {
  const base = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
  const open = base.cohorts
    .map((c: { muted?: boolean }, i: number) => [c, i] as const)
    .filter(([c]: readonly [{ muted?: boolean }, number]) => !c.muted)
    .map(([, i]: readonly [unknown, number]) => i);
  if (open.length < 2) throw new Error("fixture needs two unmuted cohorts");
  const citeFrom = (i: number, text?: string) => {
    const cit = base.cohorts[i].themes[0].claims[0].citations[0];
    return { ...cit, review_text: text ?? cit.review_text };
  };
  const [i, j] = open;
  base.cohorts[i].single_points = [
    { point_id: "one-a", text: POINT_A, theme: "difficulty", citation: citeFrom(i, SENTINEL_REVIEW) },
  ];
  base.cohorts[j].single_points = [
    { point_id: "one-b", text: POINT_B, theme: "performance", citation: citeFrom(j) },
  ];
  // a muted cohort carrying points must still render none
  const k = base.cohorts.findIndex((_: unknown, n: number) => n !== i && n !== j);
  base.cohorts[k].muted = true;
  base.cohorts[k].single_points = [
    { point_id: "one-m", text: "One reviewer says MUTED-COHORT-POINT.", theme: "other",
      citation: citeFrom(i) },
  ];
  return { text: JSON.stringify(base), i, j };
}

const proxied = (text: string) =>
  loadVerdictProxied(APPID, (async () =>
    new Response(text, { status: 200, headers: { "content-type": "application/json" } })
  ) as unknown as typeof fetch);

/** The section's own markup, from its opening tag to the cohort sections after it. */
function section(html: string) {
  const start = html.indexOf('<details class="one-reviewer"');
  const end = html.indexOf('<section class="cohort"', start);
  return { start, end, body: html.slice(start, end) };
}

describe("one-reviewer points", () => {
  it("renders identically on the static and proxied paths", async () => {
    const { text } = await fixture();
    const a = normalizeVerdict(JSON.parse(text));
    const b = await proxied(text);
    expect(b).toEqual(a);
    expect(render(b)).toBe(render(a));
  });

  it("is one closed section, below the flags and above the first cohort", async () => {
    const { text } = await fixture();
    const html = render(normalizeVerdict(JSON.parse(text)));
    const { start, end } = section(html);
    expect(start).toBeGreaterThan(-1);
    expect(html.indexOf('<details class="one-reviewer"', start + 1)).toBe(-1);
    expect(html).not.toContain('<details class="one-reviewer" open');
    expect(end).toBeGreaterThan(start);
    const lastFlag = html.lastIndexOf('<aside class="flag"');
    if (lastFlag > -1) expect(lastFlag).toBeLessThan(start);
  });

  it("carries no count in its summary (invariant 13)", async () => {
    const { text } = await fixture();
    const { body } = section(render(normalizeVerdict(JSON.parse(text))));
    const summary = body.slice(body.indexOf("<summary>"), body.indexOf("</summary>"));
    expect(summary).toContain("POINTS MENTIONED IN ONLY SINGLE REVIEWS");
    expect(summary).not.toMatch(/\d/);
  });

  it("groups each point under its own cohort's label", async () => {
    const { text, i, j } = await fixture();
    const v = normalizeVerdict(JSON.parse(text));
    const { body } = section(render(v));
    // labels carry "<" ("<2h refund window"), which the markup escapes
    const esc = (s: string) => renderToStaticMarkup(<>{s}</>);
    const hA = body.indexOf(`<h3>${esc(v.cohorts[i].label)}</h3>`);
    const hB = body.indexOf(`<h3>${esc(v.cohorts[j].label)}</h3>`);
    expect(hA).toBeGreaterThan(-1);
    expect(hB).toBeGreaterThan(hA);
    const pA = body.indexOf(POINT_A);
    const pB = body.indexOf(POINT_B);
    expect(pA).toBeGreaterThan(hA);
    expect(pA).toBeLessThan(hB);
    expect(pB).toBeGreaterThan(hB);
  });

  it("shows nothing for a muted cohort (invariant 12)", async () => {
    const { text } = await fixture();
    const v = normalizeVerdict(JSON.parse(text));
    expect(render(v)).not.toContain("MUTED-COHORT-POINT");
    expect(v.cohorts.filter((c) => c.muted).every((c) => c.single_points.length === 0)).toBe(true);
  });

  it("keeps the review behind the receipts expand (invariant 9)", async () => {
    const { text } = await fixture();
    const { body } = section(render(normalizeVerdict(JSON.parse(text))));
    const at = body.indexOf(SENTINEL_REVIEW);
    expect(at).toBeGreaterThan(-1);
    // the nearest <details> opened before the review is the point's own receipts,
    // not the section wrapper: the review needs a second click, like every claim's
    const inner = body.lastIndexOf("<details>", at);
    expect(inner).toBeGreaterThan(body.indexOf("</summary>"));
    expect(body.slice(inner, at)).toContain("Show receipts");
    expect(body.slice(inner, at)).toContain("1 review");
  });

  it.each(FIXTURES)("appid %i: a verdict without points renders no section", async (appid) => {
    const v = await loadVerdictStatic(appid, readRepoFile);
    expect(v.cohorts.every((c) => Array.isArray(c.single_points))).toBe(true);
    expect(render(v)).not.toContain("one-reviewer");
  });
});
