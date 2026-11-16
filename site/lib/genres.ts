/**
 * The home page's genre sections (owner, 2026-11-16).
 *
 * Membership comes from public/genres.json, written by pipeline/build_genres.py
 * from Steam user tags. It is read at build time like the verdicts, so no visitor
 * request ever reaches the tag source. A title can sit in several sections; a
 * title in none is still reachable through search.
 */
import type { CatalogEntry } from "./catalog";

export interface Section {
  slug: string;
  name: string;
}

export interface Genres {
  sections: Section[];
  members: Record<string, string[]>;
}

/** Games shown in one home section before the "Show all games" wall. */
export const ROW_LIMIT = 30;

/** Most popular first: Steam's lifetime review count, then appid so the order
 *  never depends on directory listing order. Pure, so client code can use it. */
export function byPopularity(a: CatalogEntry, b: CatalogEntry) {
  return b.steam_total_reviews - a.steam_total_reviews || a.appid - b.appid;
}

/** Every catalog game in a section, most popular first. */
export function sectionGames(entries: CatalogEntry[], genres: Genres, slug: string) {
  return entries
    .filter((e) => (genres.members[String(e.appid)] ?? []).includes(slug))
    .sort(byPopularity);
}

/** The home page: each section with at most ROW_LIMIT games, empty ones dropped. */
export function homeSections(entries: CatalogEntry[], genres: Genres) {
  return genres.sections
    .map((s) => ({ ...s, games: sectionGames(entries, genres, s.slug).slice(0, ROW_LIMIT) }))
    .filter((s) => s.games.length > 0);
}
