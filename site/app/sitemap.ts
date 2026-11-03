import type { MetadataRoute } from "next";
import { catalog } from "../lib/catalog";
import { SITE_URL } from "../lib/site";

/** Every prerendered verdict. Live titles join when the nightly publish deploys them. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries = await catalog();
  return [
    { url: SITE_URL },
    ...entries.map((e) => ({ url: `${SITE_URL}/verdict/${e.appid}` })),
  ];
}
