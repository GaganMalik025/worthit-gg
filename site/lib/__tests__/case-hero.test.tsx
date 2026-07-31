/**
 * Case hero, across ALL six committed verdicts.
 *
 * The fallback chain cannot be observed naturally here: checked 2026-07-31,
 * every one of the six has library_600x900, library_hero AND header on the
 * Steam CDN, so nothing 404s. The chain is therefore tested by DRIVING the
 * error handlers directly, which is the only honest way to cover it until a
 * title without the assets enters the catalog.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { VerdictPage } from "../../components/VerdictPage";
import { loadVerdictStatic } from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const read = (p: string) => readFile(path.join(REPO, p), "utf-8");
const FIXTURES = [233860, 1091500, 379720, 413150, 553850, 1190460];

describe("case hero renders for every committed verdict", () => {
  it.each(FIXTURES)("appid %i: case, disc and ghost all present", async (appid) => {
    const v = await loadVerdictStatic(appid, read);
    const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
    // cover face: library_600x900, the 2:3 portrait the case face expects
    expect(html).toContain(`apps/${appid}/library_600x900.jpg`);
    // disc face: library_hero, a different and darker asset
    expect(html).toContain(`apps/${appid}/library_hero.jpg`);
    expect(html).toContain('class="sheen"');
    // inner-left panel: the ghosted cover behind frosted plastic
    expect(html).toContain('class="ghost"');
    // PC spine band, not PS5
    expect(html).toContain(">PC<");
    // the answer is NOT inside the case column - never gated by choreography
    const heroCopy = html.slice(html.indexOf("hero-copy"), html.indexOf("case-col"));
    expect(heroCopy).toContain("stamp");
    expect(heroCopy).toContain("How satisfaction changes with playtime");
  });

  it("every cohort's split bar still carries its evidence count", async () => {
    for (const appid of FIXTURES) {
      const v = await loadVerdictStatic(appid, read);
      const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
      for (const b of v.split_bar) {
        expect(html).toContain(
          b.muted ? `${b.pool_n} reviews · too few to call` : `based on ${b.pool_n} reviews`,
        );
      }
      expect(html).not.toContain("pool_n");
    }
  });

  it("the mini Split Bar motif is present as the last-resort face", async () => {
    const v = await loadVerdictStatic(233860, read);
    const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
    // one stripe per cohort, on both the disc label and the cover fallback
    expect((html.match(/class="ms"/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });
});
