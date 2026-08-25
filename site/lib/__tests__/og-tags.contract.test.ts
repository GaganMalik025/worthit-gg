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

  it("uses a header asset for THIS app, which does not redirect", () => {
    // capsule_616x353.jpg is bigger but 301s on some titles, and unfurlers are
    // not obliged to follow redirects. What must hold is "a header asset for
    // this appid, not a capsule" - the exact path LAYOUT is Steam's business
    // and it serves three: /apps/<id>/header.jpg, /apps/<id>/<sha1>/header.jpg,
    // and a seasonal /apps/<id>/<sha1>/header_alt_assets_<n>.jpg. This used to
    // assert `/233860/header.jpg` literally, which pinned the first layout and
    // went red on 2026-08-25 when the art backfill gave Kenshi the second one
    // (verified 200, 0 redirects). Pinning a vendor's URL shape tested Steam,
    // not us.
    expect(m.openGraph.images[0].url).toContain("/233860/");
    expect(m.openGraph.images[0].url).toMatch(/\/header[^/]*\.jpg(\?|$)/);
    expect(m.openGraph.images[0].url).not.toContain("capsule");
  });

  it("prefers Steam's captured header_image over the legacy pattern", () => {
    const withArt = verdictMetadata(
      { ...v, art: { header_image: "https://shared.akamai.steamstatic.com/x/header.jpg" } },
      233860,
    );
    expect(withArt.openGraph.images[0].url)
      .toBe("https://shared.akamai.steamstatic.com/x/header.jpg");
  });

  /**
   * THE LOAD-BEARING ONE. `art.grid` is community-uploaded SteamGridDB art. It
   * is allowed in a home-grid tile and NEVER in an unfurl, where it would sit
   * beside our verdict in a Reddit feed and read as Valve's official art.
   *
   * This fails if anyone ever "unifies" the tile and unfurl art chains.
   */
  it("NEVER puts SteamGridDB fan art in an unfurl", () => {
    const fanart = "https://cdn2.steamgriddb.com/grid/deadbeef.png";
    const withGrid = verdictMetadata(
      { ...v, art: { grid: fanart } } as Parameters<typeof verdictMetadata>[0],
      233860,
    );
    expect(withGrid.openGraph.images[0].url).not.toContain("steamgriddb");
    expect(withGrid.openGraph.images[0].url).toContain("/233860/header.jpg");

    // ...and it still refuses even when both are present.
    const both = verdictMetadata(
      { ...v, art: { header_image: "https://shared.akamai.steamstatic.com/x/header.jpg",
                     grid: fanart } } as Parameters<typeof verdictMetadata>[0],
      233860,
    );
    expect(both.openGraph.images[0].url).not.toContain("steamgriddb");
  });

  it("declares dimensions clearing the summary_large_image floor (300x157)", () => {
    expect(HEADER.width).toBeGreaterThanOrEqual(300);
    expect(HEADER.height).toBeGreaterThanOrEqual(157);
    expect(m.twitter.card).toBe("summary_large_image");
  });

  it("the description is the verdict's own tagline", () => {
    expect(m.openGraph.description).toBe(v.verdict.tagline);
    expect(m.openGraph.description).toBeTruthy();
    // DESIGN.md voice rule, and it ships to every share surface
    expect(m.openGraph.description).not.toContain("!");
  });

  it("a pre-split verdict still unfurls with a description, not undefined", () => {
    // The `verdicts` branch keeps copies written before the header split, and
    // /api/verdict serves straight off it. An unfurl reading `undefined` would
    // only ever happen on those, i.e. on the newest titles.
    const legacy = JSON.parse(raw);
    legacy.verdict = { word: "Buy", for_whom: "A line from before the split." };
    const card = verdictMetadata(normalizeVerdict(legacy), 233860);
    expect(card.openGraph.description).toBe("A line from before the split.");
  });

  it("static and proxied loaders produce the SAME card", async () => {
    const a = await loadVerdictStatic(233860, async () => raw);
    const b = normalizeVerdict(JSON.parse(raw));   // the proxy's parse path
    expect(verdictMetadata(b, 233860)).toEqual(verdictMetadata(a, 233860));
  });
});
