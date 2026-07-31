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
  verdict: { word: string; for_whom: string };
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

/**
 * Single source of shaping. Both loaders end here, so neither can apply a
 * default the other misses.
 */
export function normalizeVerdict(raw: unknown): Verdict {
  const v = raw as Verdict;
  return {
    ...v,
    appid: String(v.appid),
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
