/**
 * UNFURL CARD CONTRACT
 *
 * DESIGN.md's quality floor requires real title AND OG tags per game, because
 * Reddit is the distribution channel: a shared link that renders as a bare URL
 * is a post nobody clicks. It went unimplemented - every verdict page shipped
 * with zero og: tags, static and proxied alike - so this pins it.
 *
 * The load-bearing assertion is the dual-path one. The verdict page has two
 * loaders (prerendered from disk; proxied from the verdicts branch for a title
 * generated seconds ago) and the card must be identical either way, or a
 * freshly generated title unfurls worse than a catalog one at exactly the
 * moment someone is most likely to share it.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { HEADER, SITE_URL, verdictMetadata } from "../site";
import { loadVerdictStatic, normalizeVerdict } from "../verdict";

const REPO = path.resolve(__dirname, "../../..");
const FIXTURE = path.join(REPO, "site/public/verdicts/233860.json"); // Kenshi
const raw = readFileSync(FIXTURE, "utf-8");

describe("verdictMetadata", () => {
  const v = normalizeVerdict(JSON.parse(raw));
  const m = verdictMetadata(v, 233860);

  it("carries the three required tags", () => {
    expect(m.openGraph.title).toBeTruthy();
    expect(m.openGraph.description).toBeTruthy();
    expect(m.openGraph.images[0].url).toBeTruthy();
  });

  it("names the game and its verdict in the title", () => {
    expect(m.openGraph.title).toBe("Kenshi: Buy — WorthIt.gg");
    expect(m.title).toBe(m.openGraph.title);
  });

  it("the image URL is ABSOLUTE - a relative one is dropped by unfurlers", () => {
    expect(m.openGraph.images[0].url).toMatch(/^https:\/\//);
    expect(m.openGraph.url).toMatch(/^https:\/\//);
    expect(m.openGraph.url).toBe(`${SITE_URL}/verdict/233860`);
  });

  it("uses header.jpg, which does not redirect", () => {
    // capsule_616x353.jpg is bigger but 301s on some titles, and unfurlers are
    // not obliged to follow redirects.
    expect(m.openGraph.images[0].url).toContain("/233860/header.jpg");
    expect(m.openGraph.images[0].url).not.toContain("capsule");
  });

  it("declares dimensions clearing the summary_large_image floor (300x157)", () => {
    expect(HEADER.width).toBeGreaterThanOrEqual(300);
    expect(HEADER.height).toBeGreaterThanOrEqual(157);
    expect(m.twitter.card).toBe("summary_large_image");
  });

  it("the description is the verdict's own for-whom line", () => {
    expect(m.openGraph.description).toBe(v.verdict.for_whom);
    // DESIGN.md voice rule, and it ships to every share surface
    expect(m.openGraph.description).not.toContain("!");
  });

  it("static and proxied loaders produce the SAME card", async () => {
    const a = await loadVerdictStatic(233860, async () => raw);
    const b = normalizeVerdict(JSON.parse(raw));   // the proxy's parse path
    expect(verdictMetadata(b, 233860)).toEqual(verdictMetadata(a, 233860));
  });
});
