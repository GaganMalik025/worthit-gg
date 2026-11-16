"use client";
import { useRef } from "react";
import { PosterCard } from "./PosterCard";
import type { CatalogEntry } from "../lib/catalog";

/**
 * One home section (owner, 2026-11-16): a heading, then two rows of posters that
 * scroll sideways - up to 30 games, most popular first - ending in a two-row-tall
 * "Show all games" wall that opens /browse/<slug>.
 *
 * Column-major on purpose (grid-auto-flow: column): the most popular games fill
 * the first columns of BOTH rows, so the first screen shows the top of the list.
 *
 * The arrows exist because a mouse without a trackpad cannot scroll sideways
 * comfortably. They are hidden where hover does not exist: touch swipes.
 */
export function SectionRow({
  slug,
  name,
  games,
}: {
  slug: string;
  name: string;
  games: CatalogEntry[];
}) {
  const row = useRef<HTMLDivElement>(null);
  const scroll = (dir: number) =>
    row.current?.scrollBy({ left: dir * row.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <section className="shelf" aria-labelledby={`shelf-${slug}`}>
      <div className="shelf-head">
        <h2 id={`shelf-${slug}`}>{name}</h2>
        <div className="shelf-arrows">
          <button type="button" aria-label={`Scroll ${name} left`} onClick={() => scroll(-1)}>
            &larr;
          </button>
          <button type="button" aria-label={`Scroll ${name} right`} onClick={() => scroll(1)}>
            &rarr;
          </button>
        </div>
      </div>
      <div className="shelf-row" ref={row}>
        {games.map((e) => (
          <PosterCard key={e.appid} entry={e} />
        ))}
        <a className="shelf-wall" href={`/browse/${slug}`}>
          Show all games <span aria-hidden="true">&rarr;</span>
        </a>
      </div>
    </section>
  );
}
