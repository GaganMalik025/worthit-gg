"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SearchBox } from "./SearchBox";
import { GenerationProgress, QueueFallback } from "./GenerationProgress";
import type { CatalogEntry } from "../lib/catalog";
import type { Hit } from "../lib/search";

/**
 * The browse pages' frame (owner, 2026-11-16): wordmark and promise top left,
 * search top right, then the page. Shared by the home page and every
 * /browse/<section> page, so search behaves the same on both.
 *
 * The search flow is the one Home.tsx always had, moved here unchanged: a title
 * we hold opens its verdict; one we do not asks /api/generate, then shows the
 * live progress or the queue copy IN PLACE OF the page body.
 */
export function SiteShell({
  entries,
  brandIsHeading = true,
  children,
}: {
  entries: CatalogEntry[];
  /** The home page's <h1> is the wordmark; a browse page's is its section name. */
  brandIsHeading?: boolean;
  children: React.ReactNode;
}) {
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
    // The sections and search only know this build's titles, so a verdict
    // generated since the last deploy reads as "not yet" until the server says
    // otherwise.
    if (res.state === "exists") return router.push(`/verdict/${hit.appid}`);
    if (res.state === "dispatched") setGen(hit);
    else setFallback(hit);
  }

  const Brand = brandIsHeading ? "h1" : "p";
  let body = children;
  if (fallback) {
    body = (
      <div className="narrow">
        <QueueFallback appid={fallback.appid} gameName={fallback.title} />
      </div>
    );
  } else if (gen) {
    body = (
      <div className="narrow">
        <GenerationProgress
          appid={gen.appid}
          gameName={gen.title}
          onPublished={() => router.push(`/verdict/${gen.appid}`)}
          onFallback={() => { setGen(null); setFallback(gen); }}
        />
      </div>
    );
  }

  return (
    <main className="home-main">
      <header className="site-header">
        <a className="brand" href="/">
          <Brand className="wordmark">WorthIt.gg</Brand>
          <span className="promise">Should you buy it? The verdict, with receipts.</span>
        </a>
        <div className="header-search">
          <SearchBox
            haveVerdict={(a) => have.has(a)}
            verdictWord={(a) => have.get(a)?.word ?? null}
            onSelect={select}
          />
        </div>
      </header>
      {body}
      <footer className="mono">
        Verdicts from real Steam reviews, split by playtime ·{" "}
        <a href="/methodology">how this works &rarr;</a>
      </footer>
    </main>
  );
}
