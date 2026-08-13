/**
 * The site's absolute origin.
 *
 * Lives here rather than in app/layout.tsx because Next only permits a fixed
 * set of exports from a route file - a stray `export const` there fails the
 * build with an unhelpful "not assignable to type 'never'".
 *
 * It has to be absolute. Open Graph consumers (Reddit, Slack, Discord, X) do
 * not resolve relative image paths: a relative og:image is dropped and the card
 * renders without art. Next only emits absolute URLs when metadataBase is set
 * from this.
 */
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://worthit-gg.vercel.app";

/**
 * Steam's own art, used as the unfurl image.
 *
 * NOT `capsule_616x353.jpg`, which is larger and better-proportioned but
 * 301-redirects on some titles (GTA:SA among them), and unfurlers are not
 * obliged to follow redirects. 460x215 clears the summary_large_image floor
 * of 300x157.
 *
 * CORRECTED 2026-08-13: this used to say `header.jpg` "is a straight 200 on
 * every app checked". It is not. Measured across the 411-title manifest, 14
 * appids 404 on it and one (Battlefield 6) returns a 1.6KB blank placeholder
 * with HTTP 200. Steam is migrating store art to a content-hash path that
 * cannot be derived from the appid, so this pattern is now the FALLBACK and
 * the real URL is captured at ingestion - see unfurlImage below.
 */
export const CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps";
export const HEADER = { width: 460, height: 215 };

/**
 * The unfurl card for one verdict.
 *
 * A PURE FUNCTION ON PURPOSE. The verdict page has two loaders - prerendered
 * from disk, and proxied from the verdicts branch for a title generated
 * seconds ago - and generateMetadata calls the same `load()` the page does, so
 * both funnel through here. There is no second place metadata is built, which
 * is the only way the two paths cannot drift apart.
 */
/**
 * The unfurl image: Steam's own art, else the legacy pattern. TWO TIERS ONLY.
 *
 * It deliberately does NOT read `art.grid`. That field is SteamGridDB fan art,
 * and an unfurl card puts the image beside our verdict in a Reddit or Twitter
 * feed, where a community upload would be read as Valve's official art - a
 * claim this product has no business making. The grid tile may use it; this
 * may not. Enforced by reading a different field, not by a flag, so there is no
 * default to get wrong. See pipeline/art.py `og_art`, which mirrors this.
 */
export function unfurlImage(art: { header_image?: string } | undefined,
                            appid: string | number) {
  return art?.header_image ?? `${CDN}/${appid}/header.jpg`;
}

export function verdictMetadata(
  v: {
    game_name: string;
    verdict: { word: string; tagline: string };
    art?: { header_image?: string };
  },
  appid: string | number,
) {
  const title = `${v.game_name}: ${v.verdict.word} — WorthIt.gg`;
  // The tagline, not the fit clauses. An unfurl gets one line, and a line about
  // the game travels better in a Reddit comment than a list of audience
  // conditions - which would also arrive stripped of the headings that make
  // them honest.
  const description = v.verdict.tagline;
  const url = `${SITE_URL}/verdict/${appid}`;
  const images = [{
    url: unfurlImage(v.art, appid),
    ...HEADER,
    alt: `${v.game_name} on Steam`,
  }];
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      type: "article" as const,
      siteName: "WorthIt.gg", url, title, description, images,
    },
    twitter: { card: "summary_large_image" as const, title, description, images },
  };
}
