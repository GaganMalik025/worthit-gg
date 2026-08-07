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
 * obliged to follow redirects. `header.jpg` is a straight 200 on every app
 * checked and 460x215 clears the summary_large_image floor of 300x157.
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
export function verdictMetadata(
  v: { game_name: string; verdict: { word: string; for_whom: string } },
  appid: string | number,
) {
  const title = `${v.game_name}: ${v.verdict.word} — WorthIt.gg`;
  const description = v.verdict.for_whom;
  const url = `${SITE_URL}/verdict/${appid}`;
  const images = [{
    url: `${CDN}/${appid}/header.jpg`,
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
