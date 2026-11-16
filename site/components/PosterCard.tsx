"use client";
import type { CatalogEntry } from "../lib/catalog";
import { coverStages } from "../lib/art";

/**
 * A home poster: the cover art, and nothing else, until you ask.
 *
 * At rest the card is pure cover art - no title, no chip, no Split Bar. The
 * overlay (title + verdict) fades in on hover, so browsing reads as posters and
 * the verdict is the payoff for interaction.
 *
 * WHERE HOVER DOES NOT EXIST, THE OVERLAY IS ALWAYS ON. Keyed on `@media
 * (hover: none)` rather than a width breakpoint, because the question is
 * whether the device can hover, not how wide it is - a touch laptop would fail
 * a width test and leave a card that never reveals its verdict at all.
 *
 * The art fallback chain is the same function as the case hero's (lib/art.ts),
 * differing only in that posters allow SteamGridDB fan art and the hero does not.
 * If every stage fails, the card switches to a text card with the overlay pinned
 * on, because a blank untitled tile is not a degraded card, it is an unusable one.
 *
 * onError still walks the remaining stages, because a stored URL can rot. It
 * cannot catch Battlefield 6's failure mode: the legacy path returns HTTP 200
 * with a 1.6KB blank placeholder, so no error ever fires. That title is only
 * fixed by starting from a stored URL - which is why grid stays first here.
 *
 * Moved out of Home.tsx unchanged (2026-11-16) so the home sections and the
 * /browse pages render one card.
 */
export function PosterCard({ entry: e }: { entry: CatalogEntry }) {
  const stages = coverStages(e.appid, e.art, { allowGrid: true });
  const onError = (ev: React.SyntheticEvent<HTMLImageElement>) => {
    const img = ev.currentTarget;
    const card = img.closest(".card");
    const next = Number(img.dataset.stage ?? "0") + 1;
    const stage = stages[next];
    if (!stage) {
      card?.classList.add("artless");
      return;
    }
    img.dataset.stage = String(next);
    card?.classList.toggle("letterbox", stage.letterbox);
    img.src = stage.src;
  };
  return (
    <a
      className={`card${stages[0].letterbox ? " letterbox" : ""}`}
      href={`/verdict/${e.appid}`}
    >
      <img
        className="poster"
        data-stage="0"
        src={stages[0].src}
        alt=""
        aria-hidden="true"
        loading="lazy"
        onError={onError}
      />
      {/* Always in the DOM, never display:none - the link's accessible name
          comes from here, so a screen reader announces the game at rest even
          though sighted users see only art. */}
      <div className="overlay">
        <h3>{e.game_name}</h3>
        <span className={`chip ${e.word.toLowerCase()}`}>{e.word}</span>
      </div>
    </a>
  );
}
