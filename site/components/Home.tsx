"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SearchBox } from "./SearchBox";
import { GenerationProgress, QueueFallback } from "./GenerationProgress";
import type { CatalogEntry } from "../lib/catalog";
import type { Hit } from "../lib/search";

const CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps";

/**
 * A home-grid card: the poster, and nothing else, until you ask.
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
 * The art fallback chain matches the case hero: library_600x900 -> header
 * (letterboxed) -> no art. If every image fails, the card switches to a text
 * card with the overlay pinned on, because a blank untitled tile is not a
 * degraded card, it is an unusable one.
 */
/**
 * The tile art chain, resolved at BUILD time from the verdict's `art` block
 * where possible, with the legacy URL pattern as the last resort.
 *
 * Ordered deliberately, and not the same order as the unfurl image:
 *
 *   1. art.grid        - SteamGridDB portrait. Fan art, tiles ONLY. Portrait
 *                        is the shape this grid is designed around (DESIGN.md),
 *                        and for the ~13 titles Steam serves no reachable
 *                        portrait for, this is the only portrait that exists.
 *   2. art.header_image- Steam's own art, but LANDSCAPE, so it letterboxes.
 *   3. legacy pattern  - correct for ~97% of titles, 404s on recently
 *                        refreshed store listings.
 *
 * onError still walks the remaining stages, because a stored URL can rot. It
 * cannot, however, catch Battlefield 6's failure mode: the legacy path returns
 * HTTP 200 with a 1.6KB blank placeholder, so no error ever fires. That title
 * is only fixed by starting from a stored URL - which is the point of tiers 1-2.
 */
function tileStages(e: CatalogEntry): { src: string; letterbox: boolean }[] {
  const stages: { src: string; letterbox: boolean }[] = [];
  if (e.art?.grid) stages.push({ src: e.art.grid, letterbox: false });
  if (e.art?.header_image) stages.push({ src: e.art.header_image, letterbox: true });
  stages.push({ src: `${CDN}/${e.appid}/library_600x900.jpg`, letterbox: false });
  stages.push({ src: `${CDN}/${e.appid}/header.jpg`, letterbox: true });
  return stages;
}

function PosterCard({ entry: e }: { entry: CatalogEntry }) {
  const stages = tileStages(e);
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

export function Home({ entries }: { entries: CatalogEntry[] }) {
  const router = useRouter();
  const have = new Map(entries.map((e) => [e.appid, e]));
  const [gen, setGen] = useState<Hit | null>(null);
  const [fallback, setFallback] = useState<Hit | null>(null);

  async function select(hit: Hit) {
    if (have.has(hit.appid)) return router.push(`/verdict/${hit.appid}`);
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ appid: hit.appid }),
    }).then((r) => r.json()).catch(() => ({ state: "queue_fallback" }));
    if (res.state === "dispatched") setGen(hit);
    else setFallback(hit);
  }

  if (fallback)
    return (
      <main>
        <QueueFallback appid={fallback.appid} gameName={fallback.title} />
      </main>
    );
  if (gen)
    return (
      <main>
        <GenerationProgress
          appid={gen.appid}
          gameName={gen.title}
          onPublished={() => router.push(`/verdict/${gen.appid}`)}
          onFallback={() => { setGen(null); setFallback(gen); }}
        />
      </main>
    );

  return (
    <main>
      <h1 className="wordmark">WorthIt.gg</h1>
      <p className="promise">Should you buy it? The verdict, with receipts.</p>
      <SearchBox
        haveVerdict={(a) => have.has(a)}
        verdictWord={(a) => have.get(a)?.word ?? null}
        onSelect={select}
      />
      <div className="grid">
        {entries.map((e) => (
          <PosterCard key={e.appid} entry={e} />
        ))}
      </div>
      <footer className="mono">
        Verdicts from real Steam reviews, split by playtime · how this works &rarr;
      </footer>
    </main>
  );
}
