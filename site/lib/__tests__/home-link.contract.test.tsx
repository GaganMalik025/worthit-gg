/**
 * EVERY VERDICT PAGE CARRIES A WAY BACK TO THE CATALOG
 *
 * Distribution is shared links - Reddit and Twitter - so the verdict page is
 * the LANDING page for most first-time visitors, not a place they arrive at
 * from home. Before 2026-08-28 the site had no navigation of any kind: layout
 * .tsx rendered only the backdrop and children, and VerdictPage opened straight
 * into the game title. Someone opening a pasted link in a new tab had no route
 * to the search box at all - not even browser back, which has no history to go
 * to in a fresh tab.
 *
 * That is a silent failure: the page looks complete, and nothing about it says
 * a catalog exists. Only an assertion catches its removal, because deleting the
 * link breaks no other test - it renders, it validates, every existing contract
 * still passes. The suite was 121 green before this file and 121 green after
 * the link was added, which is precisely the blind spot being closed.
 *
 * WHAT IS NOT ASSERTED HERE: position, colour, or size. Those are DESIGN.md's
 * business and change without breaking the promise. The promise is that a
 * reachable link to "/" exists on the page, exactly once.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { loadVerdictStatic } from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const read = (p: string) => readFile(path.join(REPO, p), "utf-8");

// The committed seed set - real pipeline output, not fixtures.
const FIXTURES = [233860, 1091500, 379720, 413150, 553850, 1190460];

describe("every verdict page links back to the catalog", () => {
  it.each(FIXTURES)("appid %i: exactly one link to /", async (appid) => {
    const v = await loadVerdictStatic(appid, read);
    const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
    const hrefs = html.match(/href="\/"/g) ?? [];
    expect(hrefs).toHaveLength(1);
    expect(html).toContain("WorthIt.gg");
  });

  it("the link sits OUTSIDE the case column, so choreography cannot gate it", async () => {
    // case-hero.test.tsx pins that the ANSWER is never inside the case column.
    // The same reasoning applies to the only way out of the page: it must not
    // live inside a subtree whose transform is driven by scroll position.
    const v = await loadVerdictStatic(233860, read);
    const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
    const caseCol = html.slice(html.indexOf("case-col"));
    expect(caseCol).not.toContain('href="/"');
    // and it precedes the hero copy, so it is first in reading and tab order
    expect(html.indexOf('href="/"')).toBeLessThan(html.indexOf("hero-copy"));
  });

  it("it is a real anchor with text, not an icon or an empty box", async () => {
    // A link with no accessible name is not a way back for a screen reader.
    const v = await loadVerdictStatic(233860, read);
    const html = renderToStaticMarkup(<VerdictPage verdict={v} />);
    expect(html).toMatch(/<a[^>]*href="\/"[^>]*>\s*WorthIt\.gg\s*<\/a>/);
  });
});
