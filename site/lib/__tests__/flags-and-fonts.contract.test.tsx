/**
 * The distortion flags reach the page, closed, with every figure carrying its count.
 * They were computed and paid for on 336 titles and rendered on none.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { flagEvidence, normalizeVerdict, stripBBCode, type DistortionFlag } from "../verdict";

const SITE = path.resolve(__dirname, "../..");
const read = (p: string) => readFileSync(path.join(SITE, p), "utf-8");
const verdict = (id: number, edit: (v: Record<string, unknown>) => void = () => {}) => {
  const raw = JSON.parse(read(`public/verdicts/${id}.json`));
  edit(raw);
  return normalizeVerdict(raw);
};
const html = (id: number, edit?: (v: Record<string, unknown>) => void) =>
  renderToStaticMarkup(<VerdictPage verdict={verdict(id, edit)} />);

const KENSHI = 233860;   // cohort_divergence
const CYBERPUNK = 1091500;   // recency_shift
const strips = (h: string) => h.split('<aside class="flag">').slice(1);

describe("distortion flags render", () => {
  it("a segmentation flag shows its sentence and every cohort with its count", () => {
    const v = verdict(KENSHI);
    const [strip] = strips(html(KENSHI));
    expect(strip).toContain(v.distortion_flags[0].sentence as string);
    expect(strip).toContain("SCORE DISTORTION DETECTED");
    for (const s of v.distortion_flags[0].evidence.sequence ?? []) {
      expect(strip).toContain(`${s.pct_positive.toFixed(1)}% positive, based on ${s.pool_n.toLocaleString("en-US")} reviews`);
    }
  });

  it("a recency flag shows both sides with their counts", () => {
    const e = verdict(CYBERPUNK).distortion_flags[0].evidence;
    const [strip] = strips(html(CYBERPUNK));
    expect(strip).toContain(`based on ${(e.steam_total_reviews as number).toLocaleString("en-US")} reviews`);
    expect(strip).toContain(`based on ${(e.recent_pool_n as number).toLocaleString("en-US")} reviews`);
  });

  it("evidence is closed by default", () => {
    for (const s of strips(html(KENSHI))) {
      expect(s).toContain("<details>");
      expect(s).not.toContain("<details open");
    }
  });

  it("no raw field name reaches the page", () => {
    const [strip] = strips(html(KENSHI));
    for (const f of ["pool_n", "pct_positive", "gap_pts", "flag_id", "cohort_divergence"]) {
      expect(strip).not.toContain(f);
    }
  });

  it("a verdict with no flags renders no strip", () => {
    const h = html(KENSHI, (v) => { v.distortion_flags = []; });
    expect(strips(h)).toHaveLength(0);
  });
});

describe("a flag that cannot back itself up does not ship", () => {
  const base = { flag_id: "x", type: "x" };

  it("no figures, no evidence rows", () => {
    expect(flagEvidence({ ...base, sentence: "s", evidence: {} } as DistortionFlag)).toEqual([]);
  });

  it("every row of every committed flag that has a rate also has its count", () => {
    for (const id of [KENSHI, CYBERPUNK, 553850, 1190460, 413150]) {
      for (const f of verdict(id).distortion_flags) {
        for (const [, figure] of flagEvidence(f)) {
          if (figure.includes("%")) expect(figure).toMatch(/based on [\d,]+ reviews/);
        }
      }
    }
  });

  it("no sentence, no strip", () => {
    const h = html(KENSHI, (v) => {
      (v.distortion_flags as DistortionFlag[]).forEach((f) => { f.sentence = null; });
    });
    expect(strips(h)).toHaveLength(0);
  });

  it("no figures, no strip", () => {
    const h = html(KENSHI, (v) => {
      (v.distortion_flags as DistortionFlag[]).forEach((f) => { f.evidence = {}; });
    });
    expect(strips(h)).toHaveLength(0);
  });
});

describe("stripBBCode", () => {
  it("removes Steam's markup and keeps every word", () => {
    expect(stripBBCode("[h1]Great[/h1] [b]game[/b] [url=https://x.y]link[/url] [list][*]a[/list]"))
      .toBe("Great game link a");
    expect(stripBBCode("[spoiler]end[/spoiler]")).toBe("end");
  });

  it("leaves a reviewer's own brackets alone", () => {
    expect(stripBBCode("it runs [sic] well [10/10]")).toBe("it runs [sic] well [10/10]");
  });

  it("the page uses it, and stored text is untouched", () => {
    const h = html(KENSHI, (v) => {
      const c = (v.cohorts as { themes: { claims: { citations: { review_text: string }[] }[] }[] }[])
        .flatMap((x) => x.themes).flatMap((t) => t.claims)[0].citations[0];
      c.review_text = "[h1]MARKER-TEXT[/h1]";
    });
    expect(h).toContain("MARKER-TEXT");
    expect(h).not.toContain("[h1]");
  });
});

describe("the design typefaces and discovery files are wired", () => {
  it("the layout loads all three faces and the stylesheet uses them", () => {
    const layout = read("app/layout.tsx");
    for (const f of ["Inter", "Space_Grotesk", "IBM_Plex_Mono"]) expect(layout).toContain(f);
    expect(layout).toContain("body.variable");
    const css = read("app/globals.css");
    for (const v of ["--font-body", "--font-display", "--font-mono"]) {
      expect(css).toContain(`var(${v})`);
    }
  });
});
