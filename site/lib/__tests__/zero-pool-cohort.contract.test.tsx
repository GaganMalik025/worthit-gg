/**
 * A COHORT WITH NO REVIEWS IN THE POOL RENDERS.
 *
 * pipeline/fetch_reviews.pool_stats writes pct_positive null for an empty bucket,
 * and VerdictPage called .toFixed on it. No committed verdict has this shape yet,
 * but Hotline Miami and A Plague Tale hold 1 veteran review each, so a slightly
 * shorter game gets there - and one such file would fail the prerender for every
 * page on the site and the nightly publish gate for every title queued with it.
 *
 * Built from real committed output: Hotline Miami, with its veteran pool emptied.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CaseHero } from "../../components/CaseHero";
import { VerdictPage } from "../../components/VerdictPage";
import { isAppid, loadVerdictProxied, loadVerdictStatic } from "../verdict";

const FILE = path.resolve(__dirname, "../../public/verdicts/219150.json");

function zeroPoolText() {
  const raw = JSON.parse(readFileSync(FILE, "utf-8"));
  for (const row of [...raw.split_bar, ...raw.cohorts]) {
    if (row.bucket === "veteran") {
      row.pool_n = 0;
      row.pct_positive = null;
    }
  }
  return JSON.stringify(raw);
}

const veteranRow = (html: string) =>
  html.slice(html.indexOf("100h+"), html.indexOf("</section>"));

describe("a zero-review cohort", () => {
  it("renders on the static path and the proxied path, identically", async () => {
    const text = zeroPoolText();
    const a = await loadVerdictStatic(219150, async () => text);
    const b = await loadVerdictProxied(
      219150,
      (async () => new Response(text)) as unknown as typeof fetch,
    );
    const html = renderToStaticMarkup(<VerdictPage verdict={a} />);
    expect(html).toBe(renderToStaticMarkup(<VerdictPage verdict={b} />));
    expect(html).toContain("0 reviews · too few to call");
    expect(html).toContain("no reviews in this cohort");
  });

  it("shows no percentage and no filled bar, because 0 of 0 is not a rate", async () => {
    const v = await loadVerdictStatic(219150, async () => zeroPoolText());
    const row = veteranRow(renderToStaticMarkup(<VerdictPage verdict={v} />));
    expect(row).toContain("bar-track");
    expect(row).not.toContain("bar-pos");
    expect(row).not.toMatch(/\d%/);
    expect(row).not.toContain("null");
    expect(row).not.toContain("NaN");
  });

  it("leaves every other cohort's rate alone", async () => {
    const v = await loadVerdictStatic(219150, async () => zeroPoolText());
    const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
    expect((html.match(/bar-pos/g) ?? []).length).toBe(3);
  });

  it("the case motif tolerates it", () => {
    const html = renderToStaticMarkup(
      <CaseHero
        appid={1}
        gameName="x"
        splitBar={[{ bucket: "veteran", pct_positive: null }]}
      />,
    );
    expect(html).toContain("width:0%");
  });
});

describe("every path that builds a lookup from a URL value validates it first", () => {
  // Source-level on purpose: these are Next route handlers, which this suite does
  // not boot. The behaviour itself was checked against a running server.
  const src = (p: string) =>
    readFileSync(path.resolve(__dirname, "../..", p), "utf-8");

  for (const [file, guard] of [
    ["app/api/status/route.ts", "if (!isAppid(appid)) return NextResponse.json"],
    ["app/api/generate/route.ts", "if (!isAppid(appid)) {"],
    ["app/verdict/[appid]/page.tsx", "if (!isAppid(appid)) return null;"],
  ]) {
    it(file, () => expect(src(file)).toContain(guard));
  }
});

describe("isAppid", () => {
  it("accepts what Steam issues", () => {
    for (const ok of ["10", "233860", 413150, "4128580"]) {
      expect(isAppid(ok)).toBe(true);
    }
  });

  it("rejects everything that could build a path or misattribute a run", () => {
    for (const bad of [
      "../../package", "..%2F..%2Fpackage", "1/../2", "1e3", "-5", "0", "01",
      "1.5", " 1", "1 ", "", null, undefined, {}, [1], true, 1.5, -5,
      "12345678901",
    ]) {
      expect(isAppid(bad)).toBe(false);
    }
  });
});
