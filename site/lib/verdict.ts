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

/**
 * Where this cohort's claims came from, computed in pipeline/sourcing.py.
 *
 * `level` and `triggers` are the ONLY fields that may drive rendering, and the
 * disclosure they drive is deliberately numberless (owner decision,
 * 2026-08-17). The counts below are pipeline diagnostics carried for the
 * contract test, on the same footing as every other post-filter count
 * invariant 13 keeps off the page: DESIGN.md:238 calls the per-claim receipts
 * tag the one sanctioned non-pool number, and a cohort-level count would be a
 * second one. Rendering `cited_reviews` - as a count, a rate, or a share -
 * needs an explicit DESIGN.md amendment first, as its own decision.
 *
 * null when nothing renders beneath the heading: a muted cohort (invariant 12)
 * or an unmuted one whose claims all dropped.
 */
export interface Sourcing {
  level: "baseline" | "escalated";
  triggers: ("thin" | "divergent")[];
  cited_reviews: number;
  cited_recommend: number;
  divergence_p: number | null;
  basis: string;
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
  sourcing: Sourcing | null;
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
 * EVERY COMMITTED VERDICT NOW CARRIES THE SPLIT SHAPE. Hades (1145360) and
 * Hollow Knight (367520) were the last two on the pre-split header — generated
 * live on the CI runner, so their data/claims/ artifacts never reached the dev
 * machine and the rollout could not re-synthesize them — and both were
 * re-ingested end to end on 2026-08-10.
 *
 * The shim stays anyway, for the reason it was written: the `verdicts` branch
 * is append-only artifact storage that is never pruned, and /api/verdict serves
 * straight off it, so a title generated before the split is still one fetch
 * away from a reader. Retire it only once nothing older than the rollout
 * survives on that branch — not because the catalog looks clean.
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
      // Absent on any verdict generated before 2026-08-17. Normalising to null
      // means those pages render without the note rather than throwing - the
      // backfill is what puts it on them, not the renderer.
      sourcing: c.sourcing ?? null,
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
