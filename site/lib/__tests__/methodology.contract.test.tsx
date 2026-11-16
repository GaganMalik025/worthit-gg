/**
 * The trust page must not overclaim. Its figures are pinned to the committed evidence
 * they came from, and every page that promises it must link to it.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Methodology from "../../app/methodology/page";
import { VerdictPage } from "../../components/VerdictPage";
import { normalizeVerdict } from "../verdict";

const SITE = path.resolve(__dirname, "../..");
const read = (p: string) => readFileSync(path.join(SITE, p), "utf-8");
const json = (p: string) => JSON.parse(read(p));
const html = renderToStaticMarkup(<Methodology />);

describe("the methodology page's figures match their evidence", () => {
  const scores = json("../evals/judge_scores.json").aggregate.qr1.distribution;

  it("QR-1 is the committed judge run", () => {
    expect(html).toContain(`${scores["2"]} of 70 fully, ${scores["1"]} partly, ${scores["0"]} unsupported`);
  });

  it("the two-reviews check is the committed run", () => {
    const all = Object.values(json("../evals/judge-qr6-all-2026-11-03.json")) as { rule: string }[];
    const pass = all.filter((r) => r.rule === "pass").length;
    expect(html).toContain(`${pass} of ${all.length}`);
  });

  it("the thin-claims figure is the committed catalog sample", () => {
    const s = Object.values(json("../evals/thin-claims-sample-2026-11-04.json")) as { yes: number }[];
    const thin = s.filter((r) => r.yes < 2).length;
    expect(html).toContain(`<span class="mono">${s.length}</span> of the`);
    expect(html).toContain(`<span class="mono">${thin}</span> of them cite`);
  });

  it("the citation count is the committed QR-4 run, and that run passed", () => {
    // moved to the 2026-11-16 run, the latest over the whole catalog
    const qr4 = read("../evals/qr4-2026-11-16.txt");
    expect(qr4).toContain("EXIT_RC=0");
    const n = /([\d,]+) citations checked across \d+ verdicts -> PASS/.exec(qr4)?.[1] as string;
    expect(n).toBeTruthy();
    expect(html).toContain(`0 in ${Number(n.replace(/,/g, "")).toLocaleString("en-US")} citations`);
  });

  it("the judge-vs-person figures are the committed 10-case comparison", () => {
    const out = read("../evals/hand-validation-round2-complete-2026-11-16.txt");
    expect(out).toContain("EXIT_RC=0");
    const q1 = /QR-1 agreement, published score \(>=2 rule\): (\d+)\/(\d+)/.exec(out)!;
    const q6 = /QR-6 agreement: >=2 rule (\d+)\/(\d+)/.exec(out)!;
    const n = q1[2];
    expect(html).toContain(`On ${n} randomly chosen claims`);
    expect(html).toContain(
      q1[1] === n ? `agreed on all ${n} for the first check` : `agreed on ${q1[1]} of ${n}`,
    );
    expect(html).toContain(`${q6[1]} of ${q6[2]} for the third`);
  });

  it("the meaning-check pilot figure is the committed comparison", () => {
    const rows = Object.values(json("../evals/pilot-compare-2026-11-16.json")) as {
      verify_backed: string[]; judge_yes: string[];
    }[];
    const kept = rows.filter((r) => r.verify_backed.length >= 2);
    const thin = kept.filter((r) => r.judge_yes.length < 2);
    expect(html).toContain(
      `<span class="mono">${thin.length}</span> of the <span class="mono">${kept.length}</span> claims`,
    );
  });

  it("it says the catalog is still being regenerated, not that it is done", () => {
    expect(html).toContain("Pages are being regenerated with it");
    expect(html).toContain("a page from before 16 November has only the word check");
    expect(html).not.toContain("we do not refresh them on a schedule");
  });

  it("the Death Stranding example is what that page shows", () => {
    const v = json("public/verdicts/1190460.json");
    const vet = v.cohorts.find((c: { bucket: string }) => c.bucket === "veteran");
    expect(html).toContain(`${vet.pct_positive}%`);
    expect(html).toContain(`>${vet.pool_n}<`);
  });

  it("it reports the disappointing results as well as the good ones", () => {
    for (const s of ["3 of 10", "Ten claims is a small test", "have not fixed that",
                     "it does not show the judge spotting a bad claim"]) {
      expect(html).toContain(s);
    }
  });
});

describe("the page is reachable", () => {
  it("every verdict footer links to it", () => {
    const v = normalizeVerdict(json("public/verdicts/233860.json"));
    const out = renderToStaticMarkup(<VerdictPage verdict={v} />);
    expect(out).toMatch(/<a[^>]*href="\/methodology"[^>]*>how this works/);
  });

  it("the home footer links to it", () => {
    // the footer moved into the shared header shell (2026-11-16), so it is on the
    // home page and every /browse page
    expect(read("components/SiteShell.tsx")).toMatch(/<a href="\/methodology">\s*how this works/);
  });

  it("it links back to the catalog", () => {
    expect(html).toContain('href="/"');
  });

  it("the sitemap lists it", () => {
    expect(read("app/sitemap.ts")).toContain("/methodology");
  });
});
