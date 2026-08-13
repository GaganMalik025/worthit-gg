/**
 * Client-side typeahead over the static search index.
 *
 * Hand-rolled rather than Fuse.js on purpose: a fuzzy library costs ~8 KB and
 * runs 100-300 ms per keystroke over ~46k entries, which is felt. Normalized
 * prefix/substring ranking over the same set runs in single-digit milliseconds,
 * because it is one pass of indexOf per entry and nothing else.
 *
 * The index arrives sorted by review count descending, so array position IS
 * popularity rank. That is the tiebreaker, and it means no score has to be
 * stored per entry.
 */

export type Entry = [appid: number, title: string];

export interface Shard {
  v: number;
  n: number;
  t: Entry[];
  min_reviews: number;
  max_reviews: number | null;
}

export interface Hit {
  appid: number;
  title: string;
  rank: number; // position in the index = popularity
}

/**
 * Capsule art for a dropdown row.
 *
 * The legacy pattern below is still right for ~97% of titles and stays as the
 * fallback, but Steam is migrating store art to a content-hash path that CANNOT
 * be derived from the appid - the hash differs per asset and the filename
 * varies (`capsule_231x87_alt_assets_0.jpg`). Measured 2026-08-13: 13 manifest
 * titles have no working legacy art at all.
 *
 * The real suffixes are already sitting in the store-search pages the index is
 * built from, so `search-index-art.json` carries them at ZERO network cost -
 * no API, no key, one more parse of pages already on disk.
 *
 * Only the ~8.6k HASHED entries are stored. A store_item_assets URL with no
 * hash segment is derivable, and 21.7k of the 30.4k indexed titles are that
 * shape - storing them would triple the file to buy nothing.
 */
export interface ArtMap {
  host: string;
  /** appid -> path suffix after `/apps/<appid>/`, e.g. `<hash>/capsule_231x87.jpg` */
  c: Record<string, string>;
}

export const CAPSULE = (appid: number, art?: ArtMap | null) => {
  const suffix = art?.c?.[String(appid)];
  if (suffix) {
    return `https://${art!.host}/store_item_assets/steam/apps/${appid}/${suffix}`;
  }
  return `https://cdn.cloudflare.steamstatic.com/steam/apps/${appid}/capsule_231x87.jpg`;
};

/** Lowercase, strip diacritics, collapse punctuation to single spaces. */
export function normalize(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

// Match tiers, best first. Lower is better.
const EXACT = 0;
const PREFIX = 1;
const WORD_PREFIX = 2;
const SUBSTRING = 3;

function tier(haystack: string, needle: string): number | null {
  if (haystack === needle) return EXACT;
  if (haystack.startsWith(needle)) return PREFIX;
  const at = haystack.indexOf(needle);
  if (at < 0) return null;
  // a match starting right after a space is a word-start match
  return haystack[at - 1] === " " ? WORD_PREFIX : SUBSTRING;
}

/**
 * Rank entries against a query. `offset` is added to every rank so a later
 * shard never outranks an earlier one at equal tier.
 */
export function search(
  shards: { entries: Entry[]; offset: number }[],
  query: string,
  limit = 8,
): Hit[] {
  const q = normalize(query);
  if (!q) return [];

  const hits: { hit: Hit; tier: number }[] = [];
  for (const { entries, offset } of shards) {
    for (let i = 0; i < entries.length; i++) {
      const [appid, title] = entries[i];
      const t = tier(normalize(title), q);
      if (t === null) continue;
      hits.push({ hit: { appid, title, rank: offset + i }, tier: t });
    }
  }

  hits.sort((a, b) => a.tier - b.tier || a.hit.rank - b.hit.rank);
  return hits.slice(0, limit).map((h) => h.hit);
}

/**
 * Loads both shards. Core resolves first so the box is usable immediately;
 * tail is kicked off in the same tick, not on demand, because a tail-only
 * query must resolve without a visible stall.
 */
export function createIndexLoader(base = "") {
  let started = false;
  let core: Entry[] = [];
  let tail: Entry[] = [];
  let art: ArtMap | null = null;
  let corePromise: Promise<void> | null = null;
  let tailPromise: Promise<void> | null = null;

  const get = async (path: string): Promise<Entry[]> => {
    const res = await fetch(`${base}/${path}`);
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    const shard: Shard = await res.json();
    return shard.t;
  };

  return {
    /** Idempotent. Safe to call on every focus. */
    start() {
      if (started) return;
      started = true;
      corePromise = get("search-index-core.json")
        .then((t) => {
          core = t;
        })
        .catch(() => {});
      tailPromise = get("search-index-tail.json")
        .then((t) => {
          tail = t;
        })
        .catch(() => {});
      // Art is DECORATION: fetched alongside, never awaited, and a failure is
      // swallowed. Rows render with the legacy capsule until (and if) it lands,
      // so a missing or slow art file can never delay or break the typeahead.
      fetch(`${base}/search-index-art.json`)
        .then((r) => (r.ok ? r.json() : null))
        .then((m) => {
          if (m && m.host && m.c) art = m as ArtMap;
        })
        .catch(() => {});
    },
    /** Resolves once every title >= the review floor is searchable. */
    async whenComplete() {
      await Promise.all([corePromise, tailPromise]);
    },
    get ready() {
      return core.length > 0;
    },
    get complete() {
      return tail.length > 0;
    },
    /** The hash-path capsule map, or null until it lands. Never awaited. */
    get art() {
      return art;
    },
    shards() {
      return [
        { entries: core, offset: 0 },
        { entries: tail, offset: core.length },
      ];
    },
  };
}
