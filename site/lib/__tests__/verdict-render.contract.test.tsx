/**
 * DUAL-PATH CONTRACT TEST
 *
 * A verdict page can be built two ways - prerendered from public/verdicts/, or
 * fetched at request time from the `verdicts` branch through /api/verdict/.
 * Both feed the same component, and only freshly generated titles ever take the
 * second path, so divergence between them would surface on the least-watched
 * pages on the site and could sit there for a long time.
 *
 * This test makes that divergence loud. It runs offline against a committed
 * seed verdict: no network, no Gemini quota, no GitHub token - the same spirit
 * as pipeline/test_ground_check.py.
 *
 * KNOWN LIMIT, deliberately recorded rather than discovered later:
 * renderToStaticMarkup compares SERVER MARKUP AND DATA. It does not catch
 * post-hydration behavioural divergence - if either loader ever grows
 * client-side logic (different event wiring, different lazy fetches, different
 * effects), two paths could produce identical markup and still behave
 * differently in the browser. Adequate for the current scope, where both
 * loaders are pure data fetches into one component. If that stops being true,
 * this test needs a hydration-level companion.
 *
 * Run: cd site && npm test        (CI runs it on every push/PR touching site/)
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import {
  loadVerdictProxied,
  loadVerdictStatic,
  normalizeVerdict,
  type Verdict,
} from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const APPID = 233860; // Kenshi - committed seed, real pipeline output

const readRepoFile = (p: string) => readFile(path.join(REPO, p), "utf-8");

/**
 * EVERY committed verdict, not one.
 *
 * This started as a single Kenshi fixture and a deliberately injected bug
 * walked straight through it: the proxied loader was made to default a null
 * `summary` to "", and Kenshi has no null summaries, so the divergent branch
 * never executed. A contract test is only as strong as the branches its
 * fixtures reach. Across the committed set: Cyberpunk carries the only muted
 * cohort and a null summary, DOOM carries another null summary, and every game
 * carries null n_notes.
 */
const FIXTURES = [233860, 1091500, 379720, 413150, 553850, 1190460];

/** Stands in for /api/verdict/[appid]: same bytes, over fetch. */
const fakeProxyFetchFor = (appid: number) =>
  (async () => {
    const text = await readRepoFile(`public/verdicts/${appid}.json`);
    return new Response(text, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;

const render = (v: Verdict) =>
  renderToStaticMarkup(<VerdictPage verdict={v} />);

describe("verdict render contract: static path === proxied path", () => {
  it.each(FIXTURES)("appid %i: both loaders parse identically", async (appid) => {
    const a = await loadVerdictStatic(appid, readRepoFile);
    const b = await loadVerdictProxied(appid, fakeProxyFetchFor(appid));
    expect(b).toEqual(a);
  });

  it.each(FIXTURES)("appid %i: byte-identical markup", async (appid) => {
    const a = await loadVerdictStatic(appid, readRepoFile);
    const b = await loadVerdictProxied(appid, fakeProxyFetchFor(appid));
    // the load-bearing assertion: a field dropped by either loader, a date
    // normalized on one side only, or a default applied in one and not the
    // other all fail here
    expect(render(b)).toBe(render(a));
  });

  it("covers the nullable and muted branches somewhere in the fixture set", async () => {
    // guards the gap that let an injected bug through: if the committed set
    // ever stops exercising these, the contract test silently weakens
    const all = await Promise.all(
      FIXTURES.map((a) => loadVerdictStatic(a, readRepoFile)),
    );
    const cohorts = all.flatMap((v) => v.cohorts);
    expect(cohorts.some((c) => c.muted)).toBe(true);
    expect(cohorts.some((c) => c.summary === null)).toBe(true);
    expect(cohorts.some((c) => c.n_note === null)).toBe(true);
  });

  it("a synthetic edge verdict also renders identically", async () => {
    // branches no real verdict reaches yet: a claim with no citations, and an
    // empty theme list on a muted cohort
    const base = JSON.parse(
      await readRepoFile(`public/verdicts/${APPID}.json`),
    );
    base.cohorts[0].summary = null;
    base.cohorts[0].n_note = null;
    base.cohorts[0].muted = true;
    base.cohorts[0].themes[0].claims[0].citations = [];
    const text = JSON.stringify(base);
    const a = normalizeVerdict(JSON.parse(text));
    const b = await loadVerdictProxied(
      APPID,
      (async () =>
        new Response(text, {
          status: 200,
          headers: { "content-type": "application/json" },
        })) as unknown as typeof fetch,
    );
    expect(b).toEqual(a);
    expect(render(b)).toBe(render(a));
  });

  it("a pre-split verdict renders identically on both paths", async () => {
    // The header split (tagline + for_you_if + not_for_you_if) replaced a single
    // for_whom sentence. The `verdicts` branch is append-only and holds copies
    // written before it, and the PROXIED loader is the one that serves them - so
    // the shim has to be in normalizeVerdict, where both loaders inherit it, not
    // in the page. Delete the shim and this pair fails: `undefined` where the
    // tagline goes, and only on freshly generated titles.
    const base = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
    base.verdict = { word: "Buy", for_whom: "A line from before the split." };
    const text = JSON.stringify(base);
    const a = normalizeVerdict(JSON.parse(text));
    const b = await loadVerdictProxied(
      APPID,
      (async () =>
        new Response(text, {
          status: 200,
          headers: { "content-type": "application/json" },
        })) as unknown as typeof fetch,
    );
    expect(b).toEqual(a);
    expect(render(b)).toBe(render(a));
    // it degrades to the page it had before: tagline carries the old sentence,
    // and neither fit box renders rather than rendering empty
    expect(render(a)).toContain("A line from before the split.");
    expect(render(a)).not.toContain("For you if");
    expect(render(a)).not.toContain("undefined");
  });

  it("a split-header verdict renders both fit boxes on both paths", async () => {
    // No committed verdict has the new shape yet - the catalog re-synthesis is
    // what produces it - so the branch that renders the boxes would otherwise
    // be unreached by every fixture here. That is the precise gap that let an
    // injected bug through the single-fixture version of this test.
    const base = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
    base.verdict = {
      word: "Skip",
      tagline: "Great heroes, rough machine.",
      for_you_if: ["you are here for the roster", "you play in a stack"],
      not_for_you_if: ["you want fair matchmaking", "you need stable frames"],
    };
    const text = JSON.stringify(base);
    const a = normalizeVerdict(JSON.parse(text));
    const b = await loadVerdictProxied(
      APPID,
      (async () =>
        new Response(text, {
          status: 200,
          headers: { "content-type": "application/json" },
        })) as unknown as typeof fetch,
    );
    expect(b).toEqual(a);
    expect(render(b)).toBe(render(a));
    const html = render(a);
    expect(html).toContain("Great heroes, rough machine.");
    expect(html).toContain("For you if");
    expect(html).toContain("Not for you if");
    expect(html).toContain("you play in a stack");
    expect(html).toContain("you need stable frames");
    // Polarity is never carried by colour alone (DESIGN.md pairing rule).
    // MATCHED ON THE FULL SPAN, not on the bare glyph: citation metadata
    // renders "▲ recommends" on every page, so `toContain("▲")` passes with the
    // fit-box glyph deleted. It did - the assertion was written that way first
    // and a mutation removing the glyph walked straight through it.
    expect(html).toContain('<span class="glyph" aria-hidden="true">▲</span>');
    expect(html).toContain('<span class="glyph" aria-hidden="true">▼</span>');
  });

  it("renders only the side that has clauses", async () => {
    // Reachable branch, not a hypothetical: an artifact carrying one list and
    // not the other must render one box, never an empty panel with a heading
    // and nothing under it.
    const base = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
    base.verdict = {
      word: "Buy", tagline: "A farm, and nowhere in particular to be.",
      for_you_if: ["you like setting your own goals"], not_for_you_if: [],
    };
    const text = JSON.stringify(base);
    const a = normalizeVerdict(JSON.parse(text));
    const b = await loadVerdictProxied(
      APPID,
      (async () =>
        new Response(text, {
          status: 200,
          headers: { "content-type": "application/json" },
        })) as unknown as typeof fetch,
    );
    expect(render(b)).toBe(render(a));
    const html = render(a);
    expect(html).toContain("For you if");
    expect(html).not.toContain("Not for you if");
    expect(html).not.toContain('<span class="glyph" aria-hidden="true">▼</span>');
  });

  it("renders real evidence, so an empty page cannot pass the comparison", async () => {
    const v = await loadVerdictStatic(APPID, readRepoFile);
    const html = render(v);
    expect(v.cohorts.length).toBeGreaterThan(0);
    expect(html).toContain("Kenshi");
    expect(html).toContain("How satisfaction changes with playtime");
    // invariant 13: evidence counts read as English, never the raw field name
    expect(html).toContain("based on 47 reviews");
    expect(html).not.toContain("pool_n");
  });

  it("keeps citations behind a closed expander (invariant 9)", async () => {
    const v = await loadVerdictStatic(APPID, readRepoFile);
    const html = render(v);
    expect(html).toContain("<details>");
    expect(html).not.toContain("<details open");
    expect(html).toContain("Show receipts");
  });
});
