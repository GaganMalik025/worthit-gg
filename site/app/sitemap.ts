import type { MetadataRoute } from "next";
import { catalog } from "../lib/catalog";
import { loadGenres } from "../lib/genres.server";
import { SITE_URL } from "../lib/site";

/** Every prerendered verdict and section page. Live titles join when the nightly
 *  publish deploys them. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries = await catalog();
  const genres = await loadGenres();
  return [
    { url: SITE_URL },
    { url: `${SITE_URL}/methodology` },
    ...genres.sections.map((s) => ({ url: `${SITE_URL}/browse/${s.slug}` })),
    ...entries.map((e) => ({ url: `${SITE_URL}/verdict/${e.appid}` })),
  ];
}
