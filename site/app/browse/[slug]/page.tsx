import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { catalog } from "../../../lib/catalog";
import { sectionGames } from "../../../lib/genres";
import { loadGenres } from "../../../lib/genres.server";
import { BrowseSection } from "../../../components/BrowseSection";

/**
 * "Show all games" for one home section (owner, 2026-11-16): every game in it,
 * most popular first, five columns on a desktop. Prerendered for each section;
 * any other slug is a 404.
 */
export async function generateStaticParams() {
  return (await loadGenres()).sections.map((s) => ({ slug: s.slug }));
}

export const dynamicParams = false;

async function find(slug: string) {
  return (await loadGenres()).sections.find((s) => s.slug === slug) ?? null;
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> },
): Promise<Metadata> {
  const section = await find((await params).slug);
  return section ? { title: `${section.name} — WorthIt.gg` } : {};
}

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const genres = await loadGenres();
  const section = genres.sections.find((s) => s.slug === slug);
  if (!section) notFound();
  const entries = await catalog();
  return (
    <BrowseSection
      entries={entries}
      name={section.name}
      games={sectionGames(entries, genres, slug)}
    />
  );
}
