/**
 * "AS OF" DATE CONTRACT (owner, 2026-11-18)
 *
 * The catalog refresh leaves verdicts on different dates, so each page says when
 * its evidence is from, under the verdict stamp. Pinned here:
 *
 *   - the line reads "As of <D Mon YYYY>" from the verdict's own generated_at
 *   - it is the same day the footer prints, so the two can never disagree
 *   - it sits in the header copy, after the stamp and before the playtime bars
 *   - a malformed or missing generated_at renders no line rather than "As of null"
 *   - both loaders render it identically (it comes from shared normalised data)
 *
 * Run: cd site && npm test
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { asOfDate, loadVerdictProxied, loadVerdictStatic, normalizeVerdict } from "../verdict";

const SITE = path.resolve(__dirname, "../..");
const read = (p: string) => readFile(path.join(SITE, p), "utf-8");
const render = (v: ReturnType<typeof normalizeVerdict>) =>
  renderToStaticMarkup(<VerdictPage verdict={v} />);
const FIXTURES = [233860, 1091500, 553850, 1332010];

describe("asOfDate", () => {
  it("formats the UTC date as D Mon YYYY", () => {
    expect(asOfDate("2026-11-18T13:31:55Z")).toBe("18 Nov 2026");
    expect(asOfDate("2026-07-01T00:00:00Z")).toBe("1 Jul 2026");
  });

  it("uses the date in the string, never the reader's timezone", () => {
    // 23:59 UTC is already the next day east of UTC; the page must still say the 31st
    expect(asOfDate("2026-12-31T23:59:59Z")).toBe("31 Dec 2026");
  });

  it("returns null for anything malformed", () => {
    for (const bad of [null, undefined, "", "yesterday", "2026-13-01T00:00:00Z", "2026-11-00T00:00:00Z"]) {
      expect(asOfDate(bad as string)).toBeNull();
    }
  });
});

describe("the As of line on a verdict page", () => {
  it.each(FIXTURES)("appid %i: shows the generated date, matching the footer", async (appid) => {
    const v = await loadVerdictStatic(appid, read);
    const html = render(v);
    expect(html).toContain(`<p class="as-of mono">As of ${asOfDate(v.generated_at)}</p>`);
    // the footer prints generated_at's YYYY-MM-DD; both read the same date
    const [y, m, d] = v.generated_at.slice(0, 10).split("-").map(Number);
    expect(html).toContain(`generated ${v.generated_at.slice(0, 10)}`);
    expect(asOfDate(v.generated_at)).toBe(
      `${d} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]} ${y}`,
    );
  });

  it("sits after the verdict stamp and before the playtime bars", async () => {
    const html = render(await loadVerdictStatic(233860, read));
    const stamp = html.indexOf('class="stamp ');
    const asOf = html.indexOf('class="as-of mono"');
    const spine = html.indexOf('class="spine"');
    expect(stamp).toBeGreaterThan(-1);
    expect(asOf).toBeGreaterThan(stamp);
    expect(spine).toBeGreaterThan(asOf);
  });

  it("renders nothing, not 'As of null', when generated_at is malformed", async () => {
    const raw = JSON.parse(await read("public/verdicts/233860.json"));
    raw.generated_at = "not a date";
    const html = render(normalizeVerdict(raw));
    expect(html).not.toContain('class="as-of');
    expect(html).not.toContain("As of null");
  });

  it("renders identically on the static and proxied paths", async () => {
    const text = await read("public/verdicts/1332010.json");
    const a = await loadVerdictStatic(1332010, read);
    const b = await loadVerdictProxied(1332010, (async () =>
      new Response(text, { status: 200, headers: { "content-type": "application/json" } })
    ) as unknown as typeof fetch);
    expect(render(b)).toBe(render(a));
    expect(render(a)).toContain("As of ");
  });
});
