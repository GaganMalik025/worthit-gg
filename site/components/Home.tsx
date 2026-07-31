"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SearchBox } from "./SearchBox";
import { GenerationProgress, QueueFallback } from "./GenerationProgress";
import type { CatalogEntry } from "../lib/catalog";
import type { Hit } from "../lib/search";

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

  if (fallback) return <main><QueueFallback gameName={fallback.title} /></main>;
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
          <a key={e.appid} className="card" href={`/verdict/${e.appid}`}>
            <h3>{e.game_name}</h3>
            <span className={`chip ${e.word.toLowerCase()}`}>{e.word}</span>
            <div className="ministripe" aria-hidden="true">
              {e.split_bar.map((b) => (
                <i key={b.bucket}><b style={{ width: `${b.pct_positive}%` }} /></i>
              ))}
            </div>
          </a>
        ))}
      </div>
      <footer className="mono">
        Verdicts from real Steam reviews, split by playtime · how this works &rarr;
      </footer>
    </main>
  );
}
