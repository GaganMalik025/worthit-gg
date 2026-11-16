"use client";
import { SiteShell } from "./SiteShell";
import { PosterCard } from "./PosterCard";
import type { CatalogEntry } from "../lib/catalog";

/** One section's full list: the shared header, the section name, every game in
 *  a five-column grid (fewer columns where five do not fit). */
export function BrowseSection({
  entries,
  name,
  games,
}: {
  entries: CatalogEntry[];
  name: string;
  games: CatalogEntry[];
}) {
  return (
    <SiteShell entries={entries} brandIsHeading={false}>
      <section className="browse">
        <a className="browse-back" href="/">&larr; All sections</a>
        <h1>{name}</h1>
        <div className="browse-grid">
          {games.map((e) => (
            <PosterCard key={e.appid} entry={e} />
          ))}
        </div>
      </section>
    </SiteShell>
  );
}
