/**
 * HOME SECTIONS CONTRACT (owner, 2026-11-16; DESIGN.md "Home")
 *
 * The home page replaced its 3-column grid with genre sections. Pinned here:
 *
 *   - header: wordmark and promise top left, search top right
 *   - each section shows at most 30 games, most popular first, then a
 *     "Show all games" wall linking /browse/<slug>
 *   - a game can sit in several sections; a game in none still exists in search
 *   - posters are 174px, 75% of the old 232px grid card
 *   - /browse/<slug> lists every game in the section, five columns, and is
 *     prerendered for exactly the sections genres.json names
 *
 * Runs against the real catalog and the committed public/genres.json, plus small
 * synthetic cases for edges the real data may not reach.
 *
 * Run: cd site && npm test
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => {} }),
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
}));

import { Home } from "../../components/Home";
import { BrowseSection } from "../../components/BrowseSection";
import { catalog, type CatalogEntry } from "../catalog";
import { byPopularity, homeSections, ROW_LIMIT, sectionGames, type Genres } from "../genres";
import { loadGenres } from "../genres.server";
import * as browse from "../../app/browse/[slug]/page";

const SITE = path.resolve(__dirname, "../..");

const entry = (appid: number, reviews: number): CatalogEntry => ({
  appid, game_name: `G${appid}`, word: "Buy", pool_n: 100, steam_total_reviews: reviews,
  art: {} as CatalogEntry["art"], split_bar: [],
});

/** The <section class="shelf"> blocks of a rendered page, in order. */
const shelves = (html: string) => html.split('<section class="shelf"').slice(1);

describe("home sections: the rules", () => {
  const genres: Genres = {
    sections: [{ slug: "a", name: "A" }, { slug: "b", name: "B" }, { slug: "empty", name: "E" }],
    members: Object.fromEntries(
      Array.from({ length: 40 }, (_, i) => [String(i + 1), i % 2 ? ["a"] : ["a", "b"]]),
    ),
  };
  const entries = Array.from({ length: 41 }, (_, i) => entry(i + 1, (i * 7919) % 1000));

  it("caps a section at 30 games", () => {
    const a = homeSections(entries, genres).find((s) => s.slug === "a")!;
    expect(ROW_LIMIT).toBe(30);
    expect(a.games).toHaveLength(30);
  });

  it("orders most popular first", () => {
    const a = homeSections(entries, genres).find((s) => s.slug === "a")!;
    const counts = a.games.map((g) => g.steam_total_reviews);
    expect(counts).toEqual([...counts].sort((x, y) => y - x));
    // and the 30 shown are the 30 most popular of the section, not any 30
    const all = sectionGames(entries, genres, "a").map((g) => g.steam_total_reviews);
    expect(Math.min(...counts)).toBeGreaterThanOrEqual(all[29]);
  });

  it("lets a game sit in several sections", () => {
    const s = homeSections(entries, genres);
    const inA = new Set(s.find((x) => x.slug === "a")!.games.map((g) => g.appid));
    expect(s.find((x) => x.slug === "b")!.games.some((g) => inA.has(g.appid))).toBe(true);
  });

  it("drops a section with no games, and leaves an unsectioned game out of every row", () => {
    const s = homeSections(entries, genres);
    expect(s.map((x) => x.slug)).not.toContain("empty");
    expect(s.flatMap((x) => x.games).some((g) => g.appid === 41)).toBe(false);
  });

  it("breaks popularity ties by appid, so order never depends on file order", () => {
    expect([entry(9, 5), entry(3, 5)].sort(byPopularity).map((e) => e.appid)).toEqual([3, 9]);
  });
});

describe("home page markup", () => {
  it("puts the wordmark and promise top left and the search top right", async () => {
    const entries = await catalog();
    const html = renderToStaticMarkup(
      <Home entries={entries} sections={homeSections(entries, await loadGenres())} />,
    );
    const header = html.slice(html.indexOf('<header class="site-header"'), html.indexOf("</header>"));
    const brand = header.indexOf('class="brand"');
    const search = header.indexOf('class="header-search"');
    expect(brand).toBeGreaterThan(-1);
    expect(search).toBeGreaterThan(brand);
    expect(header.slice(brand, search)).toContain('<h1 class="wordmark">WorthIt.gg</h1>');
    expect(header.slice(brand, search)).toContain("Should you buy it? The verdict, with receipts.");
    // the old 3-column grid of every title is gone
    expect(html).not.toContain('class="grid"');
  });

  it("renders every section with at most 30 posters, then the wall", async () => {
    const entries = await catalog();
    const genres = await loadGenres();
    const sections = homeSections(entries, genres);
    const html = renderToStaticMarkup(<Home entries={entries} sections={sections} />);
    const blocks = shelves(html);
    expect(blocks).toHaveLength(sections.length);
    expect(sections.length).toBe(12);
    blocks.forEach((b, i) => {
      const cards = b.split('<a class="card').length - 1;
      expect(cards).toBeGreaterThan(0);
      expect(cards).toBeLessThanOrEqual(30);
      // the wall is the row's LAST link, after every poster
      const wall = b.indexOf('<a class="shelf-wall" href="/browse/' + sections[i].slug + '"');
      expect(wall).toBeGreaterThan(b.lastIndexOf('<a class="card'));
      expect(b.slice(wall)).toContain("Show all games");
    });
  });

  it("orders the real sections by Steam review count", async () => {
    const entries = await catalog();
    for (const s of homeSections(entries, await loadGenres())) {
      const counts = s.games.map((g) => g.steam_total_reviews);
      expect(counts).toEqual([...counts].sort((x, y) => y - x));
    }
  });

  it("every genres.json member is a title we hold", async () => {
    const ids = new Set((await catalog()).map((e) => String(e.appid)));
    const raw = JSON.parse(await readFile(path.join(SITE, "public/genres.json"), "utf-8"));
    expect(Object.keys(raw.members).filter((a) => !ids.has(a))).toEqual([]);
  });
});

describe("poster size and the show-all page", () => {
  it("posters are 174px wide, 75% of the old 232px grid card, in rows and on browse pages", async () => {
    const css = await readFile(path.join(SITE, "app/globals.css"), "utf-8");
    expect(css).toMatch(/\.shelf-row\{[^}]*grid-auto-columns:174px/);
    expect(css).toMatch(/\.browse-grid\{[^}]*grid-template-columns:repeat\(5,174px\)/);
  });

  it("a browse page lists every game in the section, with the section as its heading", async () => {
    const entries = await catalog();
    const genres = await loadGenres();
    const games = sectionGames(entries, genres, "story-driven");
    const html = renderToStaticMarkup(
      <BrowseSection entries={entries} name="Story-driven" games={games} />,
    );
    const grid = html.slice(html.indexOf('class="browse-grid"'));
    expect(grid.split('<a class="card').length - 1).toBe(games.length);
    expect(games.length).toBeGreaterThan(30);
    expect(html).toContain("<h1>Story-driven</h1>");
    // one h1 per page: the wordmark steps down on a browse page
    expect(html).not.toContain('<h1 class="wordmark"');
  });

  it("prerenders exactly the sections genres.json names, and nothing else", async () => {
    const params = await browse.generateStaticParams();
    expect(params.map((p) => p.slug)).toEqual((await loadGenres()).sections.map((s) => s.slug));
    expect(browse.dynamicParams).toBe(false);
    await expect(
      browse.default({ params: Promise.resolve({ slug: "no-such-section" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
