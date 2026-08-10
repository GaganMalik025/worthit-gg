/**
 * The two loaders behind a verdict page, and the one shape they both produce.
 *
 * A verdict can arrive by two routes:
 *
 *   loadVerdictStatic   - read from site/public/verdicts/ at build time. Catalog
 *                         titles, and anything already merged from the
 *                         `verdicts` branch. Prerendered.
 *   loadVerdictProxied  - fetched at request time from the `verdicts` branch
 *                         via /api/verdict/[appid]. Titles generated live and
 *                         not yet merged to main.
 *
 * Both feed the SAME component. That is the whole design, and it is also the
 * risk: two code paths producing one page can drift silently, and the drift
 * would only ever show on freshly generated titles - the least-watched pages on
 * the site. verdict-render.contract.test.tsx exists to make that drift loud.
 *
 * Anything that shapes, defaults or normalizes a verdict belongs in
 * normalizeVerdict() so both loaders inherit it. A fix applied in one loader
 * and not the other is exactly the bug the contract test is looking for.
 */

export interface Citation {
  recommendationid: string;
  hours_at_review: number | null;
  voted_up: boolean;
  date: string | null;
  review_text: string;
  truncated?: boolean;
}

export interface Claim {
  claim_id: string;
  claim: string;
  citation_verdict: string;
  citation_split: { positive: number; negative: number };
  citations: Citation[];
}

export interface Cohort {
  bucket: string;
  label: string;
  hours_range: string;
  pool_n: number;
  pct_positive: number;
  muted: boolean;
  n_note: string | null;
  summary: string | null;
  themes: { theme: string; claims: Claim[] }[];
}

export interface Verdict {
  appid: string;
  game_name: string;
  generated_at: string;
  verdict: {
    word: string;
    /** One line about the game. Never an audience, never a condition. */
    tagline: string;
    /** Short clauses. Written on every verdict, Skip included. */
    for_you_if: string[];
    not_for_you_if: string[];
  };
  split_bar: {
    bucket: string;
    label: string;
    pool_n: number;
    pct_positive: number;
    muted: boolean;
  }[];
  distortion_flags: unknown[];
  cohorts: Cohort[];
  footer: {
    pool_n: number;
    steam_total_reviews: number;
    cohort_count: number;
    basis: string;
  };
}

/** The pre-split header: one sentence doing the job the three fields now do. */
interface LegacyVerdictBlock {
  word: string;
  for_whom?: string;
  tagline?: string;
  for_you_if?: string[];
  not_for_you_if?: string[];
}

/**
 * Single source of shaping. Both loaders end here, so neither can apply a
 * default the other misses.
 *
 * THE LEGACY SHIM IS NOT DEFENSIVE PADDING. The `verdicts` branch is
 * append-only artifact storage that is never pruned, and /api/verdict serves
 * straight off it - so a title generated before the header split is still one
 * fetch away from a reader for as long as that copy exists. Without this, its
 * page renders `undefined` where the tagline goes, on the proxied path only,
 * which is the least-watched path on the site.
 *
 * A pre-split verdict maps to: tagline = the old for-whom sentence, both lists
 * empty. VerdictPage renders no box for an empty list, so it degrades to
 * exactly the page it had before.
 *
 * IT IS ALSO LOAD-BEARING FOR TWO TITLES IN THE COMMITTED CATALOG, not only for
 * the branch: Hades (1145360) and Hollow Knight (367520) were generated live on
 * the CI runner, so their data/claims/ artifacts never existed on the dev
 * machine and the header rollout could not re-synthesize them. They ship the
 * pre-split shape today. See BACKLOG.md, 2026-08-10 — removing this shim
 * requires re-ingesting those two first, which means new citations, a fresh
 * QR-4 gate and a fresh manual audit for each.
 */
export function normalizeVerdict(raw: unknown): Verdict {
  const v = raw as Verdict;
  const block = (v.verdict ?? {}) as LegacyVerdictBlock;
  return {
    ...v,
    appid: String(v.appid),
    verdict: {
      word: block.word,
      tagline: block.tagline ?? block.for_whom ?? "",
      for_you_if: block.for_you_if ?? [],
      not_for_you_if: block.not_for_you_if ?? [],
    },
    split_bar: (v.split_bar ?? []).map((b) => ({ ...b, muted: Boolean(b.muted) })),
    distortion_flags: v.distortion_flags ?? [],
    cohorts: (v.cohorts ?? []).map((c) => ({
      ...c,
      muted: Boolean(c.muted),
      n_note: c.n_note ?? null,
      summary: c.summary ?? null,
      themes: (c.themes ?? []).map((t) => ({
        ...t,
        claims: (t.claims ?? []).map((cl) => ({
          ...cl,
          citations: cl.citations ?? [],
        })),
      })),
    })),
  };
}

/** Build-time path: the committed artifact. */
export async function loadVerdictStatic(
  appid: number | string,
  readFile: (p: string) => Promise<string>,
  dir = "public/verdicts",
): Promise<Verdict> {
  const text = await readFile(`${dir}/${appid}.json`);
  return normalizeVerdict(JSON.parse(text));
}

/** Request-time path: the same bytes, from the `verdicts` branch. */
export async function loadVerdictProxied(
  appid: number | string,
  fetchImpl: typeof fetch = fetch,
  base = "",
): Promise<Verdict> {
  const res = await fetchImpl(`${base}/api/verdict/${appid}`);
  if (!res.ok) throw new Error(`verdict ${appid}: ${res.status}`);
  return normalizeVerdict(await res.json());
}
