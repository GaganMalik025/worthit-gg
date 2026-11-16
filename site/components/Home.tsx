"use client";
import { SiteShell } from "./SiteShell";
import { SectionRow } from "./SectionRow";
import type { CatalogEntry } from "../lib/catalog";
import type { Section } from "../lib/genres";

/**
 * The home page (owner, 2026-11-16; DESIGN.md "Home"): the header, then one
 * sideways-scrolling section per genre. The sections are computed at build time
 * (lib/genres.ts homeSections) and arrive here already trimmed and ordered.
 *
 * Replaced the 3-column grid of every title. A title in no section is still
 * reachable through search; nothing here drops it from the catalog.
 */
export function Home({
  entries,
  sections,
}: {
  entries: CatalogEntry[];
  sections: (Section & { games: CatalogEntry[] })[];
}) {
  return (
    <SiteShell entries={entries}>
      {sections.map((s) => (
        <SectionRow key={s.slug} slug={s.slug} name={s.name} games={s.games} />
      ))}
    </SiteShell>
  );
}
