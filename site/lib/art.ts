/**
 * The cover-art fallback chain, in ONE place.
 *
 * It used to be written twice - `Home.tsx:tileStages()` for the grid, and a
 * hardcoded two-step inside `CaseHero.tsx` for the case face - and the two had
 * drifted into different orders and different tiers. That drift is exactly the
 * defect this file exists to make impossible: the hero could not see the art
 * block at all, so a title whose legacy URLs 404 rendered a blank face while a
 * perfectly good stored URL sat unused in its own verdict JSON (2806050,
 * BACKLOG 2026-08-28).
 *
 * ORDER: ALL PORTRAITS BEFORE ALL LANDSCAPES.
 *
 *   1. art.grid           portrait, SteamGridDB fan art   TILES ONLY
 *   2. library_600x900    portrait, Valve, legacy pattern
 *   3. art.header_image   landscape, Valve, stored        letterboxed
 *   4. header.jpg         landscape, Valve, legacy        letterboxed
 *
 * A working portrait must never lose to a letterboxed landscape - which it did:
 * 1641890 has no grid, so its tile started at the 460x215 header while its own
 * 300x450 portrait sat two stages down the chain. `header.jpg` is now the true
 * last resort, immediately before the caller's own terminal state (the motif on
 * the hero, `artless` on a tile).
 *
 * `allowGrid` IS THE ONLY DIFFERENCE BETWEEN THE TWO SURFACES, and it is not a
 * style preference. Tier 2 is community-uploaded fan art. pipeline/art.py's OG
 * rule forbids it in an unfurl; DESIGN.md:132 separately says the case cover is
 * "the game's real Steam library art", and site/lib/catalog.ts calls grid
 * "licensed here for grid tiles only". So it stays a TILE asset: `allowGrid`
 * is true for the home grid and false for the case hero (owner decision,
 * 2026-08-28). The hero loses nothing by it - 2806050's stored header_image is
 * a live 200 and renders where the blank motif used to be.
 *
 * NOTE ON THE PORTRAIT-FIRST RISK, measured rather than waved off. art.py's
 * docstring records that the legacy path can return HTTP 200 with a ~1.6KB
 * BLANK placeholder (Battlefield 6), which no `onError` can ever catch, and
 * that starting from a stored URL is the only defence. Putting the legacy
 * portrait ahead of the stored header therefore reopens that hazard - but only
 * for a title that is BOTH grid-less AND blank-placeholder. Checked
 * 2026-08-28: Battlefield 6 (2807960) carries a grid and so never reaches the
 * legacy stage, and the single grid-less verdict of 539 (1641890) has a real
 * 300x450 portrait at HTTP 200. The intersection is empty today and shrinks
 * further once live generations start capturing grids. Revisit if a grid-less
 * title ever renders a blank face.
 */

const CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps";

export interface Art {
  header_image?: string;
  capsule_image?: string;
  grid?: string;
}

export interface Stage {
  src: string;
  /** Landscape art on a portrait face: contain it, and fill the remainder with
   *  a blurred scaled copy rather than cropping (DESIGN.md:167). */
  letterbox: boolean;
}

export function coverStages(
  appid: number | string,
  art: Art | null | undefined,
  { allowGrid }: { allowGrid: boolean },
): Stage[] {
  const stages: Stage[] = [];
  if (allowGrid && art?.grid) stages.push({ src: art.grid, letterbox: false });
  stages.push({ src: `${CDN}/${appid}/library_600x900.jpg`, letterbox: false });
  if (art?.header_image) stages.push({ src: art.header_image, letterbox: true });
  stages.push({ src: `${CDN}/${appid}/header.jpg`, letterbox: true });
  return stages;
}
