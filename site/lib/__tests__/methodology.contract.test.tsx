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
    expect(html).toContain(`${all.length - pass} had`);
  });

  it("the citation count is the committed QR-4 run, and that run passed", () => {
    const qr4 = read("../evals/qr4-2026-11-03.txt");
    expect(qr4).toContain("QR4_RC=0");
    const n = /([\d]+) citations checked/.exec(qr4)?.[1] as string;
    expect(html).toContain(Number(n).toLocaleString("en-US"));
  });

  it("the Death Stranding example is what that page shows", () => {
    const v = json("public/verdicts/1190460.json");
    const vet = v.cohorts.find((c: { bucket: string }) => c.bucket === "veteran");
    expect(html).toContain(`${vet.pct_positive}%`);
    expect(html).toContain(`>${vet.pool_n}<`);
  });

  it("it reports the disappointing results as well as the good ones", () => {
    for (const s of ["3 of 10", "Six claims is a small test", "have not fixed that"]) {
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
    expect(read("components/Home.tsx")).toMatch(/<a href="\/methodology">\s*how this works/);
  });

  it("it links back to the catalog", () => {
    expect(html).toContain('href="/"');
  });

  it("the sitemap lists it", () => {
    expect(read("app/sitemap.ts")).toContain("/methodology");
  });
});
