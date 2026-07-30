# CLAUDE.md — WorthIt.gg

## What this is

WorthIt.gg answers one question: **"Should I buy this Steam game?"** — with a
citation-backed verdict built from real Steam reviews, segmented by how long the
reviewer actually played. The core thesis: review disagreement is segmentation,
not noise. Players who refunded at 2 hours and players at 100+ hours describe
different products. Every existing tool (including Steam's own AI summary)
averages these voices; we surface the split.

This is a **product-management portfolio project on a compressed timeline**,
built by an MBA student (ex-SDE) for PM job interviews. The deliverables that
matter, in order: (1) a working shipped product with real users, (2) a
published eval harness with before/after numbers, (3) a case study. Code
quality matters only insofar as it serves those three.

## The single workflow (the entire product)

1. User lands → search box + grid of available games.
2. Picks a game → verdict page renders **instantly from static JSON** (no
   inference at request time): Buy/Wait/Skip verdict + "for whom" qualifier;
   per-playtime-segment sections; claims expandable to cited source reviews;
   score-distortion flags.
3. Game not in catalog → request queue (title only, no email), batch-generated
   overnight.

Anything not in this workflow is out of scope. See `BACKLOG.md`.

## Architecture

```
Steam public API → pipeline/ (Python)                → public/verdicts/*.json → site/ (Next.js, static)
                   ingest → filter → extract → ground → synthesize
evals/ (Python)    50-case test set + LLM-as-judge → evals/RESULTS.md
```

- **Pipeline:** Python 3, `requests`, Gemini API (`google-genai` SDK).
- **Site:** Next.js (App Router), static generation from `public/verdicts/`,
  deployed on Vercel free tier. Tailwind for styling. PostHog for analytics.
- **No database. No backend service. No auth.** Static JSON is the
  architecture — it is a deliberate product decision (zero marginal cost per
  user, instant latency, spike-proof), not a shortcut to fix later.

## Hard invariants — never violate, never "improve"

1. `playtime_at_review` from Steam is in **MINUTES**. It is converted to hours
   exactly once, at ingestion (`pipeline/fetch_reviews.py:normalize`). Raw
   minutes must never reach an LLM prompt or the UI.
2. Playtime buckets (minutes at review): `refund_window` <120, `early`
   120–1200, `mid` 1200–6000, `veteran` 6000+. 120 = Steam's refund window.
   Changing buckets invalidates all eval results — do not change without
   explicit instruction.
3. **Every claim carries ≥2 supporting `recommendationid`s**, enforced in code,
   not just in the prompt.
4. The synthesis pass may only reference claim IDs emitted by the extraction
   pass. Unknown IDs are rejected in code.
5. A deterministic grounding check (IDs exist + lexical overlap between claim
   and cited review text) runs on every generation, before any LLM judging.
6. Extraction runs with a **structured output schema** and
   `thinking_level: minimal`, and sends **no sampling parameters**.
   `temperature`/`top_p`/`top_k` are deprecated and ignored on Gemini 3.x and
   return HTTP 400 in future model generations — do not reintroduce them.
   Repeatability comes from the schema, the pinned model id
   (`gemini-3.5-flash-lite`) and the fixed prompt; where it has to be proven,
   from the self-consistency double-run on the seed set, not a sampling knob.
7. The content filter (pipeline/filter step) runs **before** extraction. Its
   signals: `♥` density (Steam censors profanity into ♥♥♥ sequences),
   `votes_funny > votes_up` (joke reviews/copypasta — exclude entirely),
   LDNOOBW wordlist, length/low-information heuristic.
8. **QR-4 is a launch gate:** zero NSFW/slur-bearing reviews surfaced in any
   citation. Any failure blocks deploy.
9. Review text appears in the UI **only behind a citation expand** — never in
   the verdict summary itself (blast-radius design).
10. `public/verdicts/` is committed to git on purpose — it is what the static
    site serves. Never add it to `.gitignore`. `data/raw/` stays gitignored
    EXCEPT the 5 seed games, which are committed so the eval harness is
    reproducible.
11. **The sample is deliberately non-representative.** Per-bucket quotas
    over-sample thin cohorts on purpose — the refund cohort is ~3% of the pool
    and ~10% of the sample. Therefore nothing in a prompt, claim, verdict, or
    UI string may infer prevalence, proportion, or "how many players" from
    sample counts: no "most players", "a third of reviewers", "commonly".
    True population proportions are computed **in code** from the full
    pre-quota pool and passed through explicitly. If a proportion was not
    passed in that way, it does not get stated.
12. **Minimum cohort evidence is 20 surviving reviews.** [see invariant 13 for
    how the resulting `n=` label is sourced] Below 20 reviews in a
    bucket after filtering, no claim may be attributed to that cohort; the
    section renders muted with an explicit `n=` label instead. Refund-window
    counts pre-filter on the seed set: Kenshi 47, Helldivers 2 30, Death
    Stranding 26, Stardew Valley 24, **Cyberpunk 2077 12** — already below the
    floor before the filter runs. Cohorts are exhausted at ingestion (kept ==
    pool), so a review the filter drops cannot be replaced.
13. **Every user-facing number is a pool figure.** Split Bar rates, cohort `n=`
    labels, distortion-flag evidence and footer counts all read the `pool` block
    of the verdict JSON. Post-quota and post-filter counts — how many reviews
    the quota kept, how many the filter spared, how many an LLM read — are
    pipeline diagnostics and never render. Every rate ships with its `pool_n`;
    a percentage without its denominator does not render.
    - The word is **pool**, not "population": it is every review we swept, not
      every review that exists (Helldivers 2: 1,930 of 815,955). Naming it a
      population overclaims, in the UI and in the case study alike.
    - **One carve-out:** the receipts tag on a claim (`▸ 6 reviews · 2 cohorts`)
      counts *citations attached to that claim*, which is evidence, not
      prevalence. It renders. It must never be phrased as a rate, a share, or
      "6 players" — and no claim may be built from it.
    - The filter's `sentiment_shift` is reported in the pipeline and published
      on the methodology page, never used to correct the sample.

## Budget rules

- **Total budget is ₹0.** Gemini free tier only (Flash / Flash-Lite,
  ~1,500 requests/day). Never suggest a paid model, paid API, paid hosting, or
  any paid service. If a problem seems to need one, the answer is architecture
  (grounding checks, self-consistency, caching, precompute), not spend.
- Quota discipline: self-consistency double-runs only on the 5 seed games and
  contested outputs; single-pass the long tail. Batch runs go overnight with
  backoff; raw responses cached to disk; never re-fetch what exists.
- API key lives in `.env` (gitignored). If any code would print, log, or
  commit it, stop and fix.

## Non-goals — refuse and add to BACKLOG.md instead

No accounts/login/history. No monetization. No non-Steam platforms. No live
on-demand generation. No price tracking/deals/wishlists. No recommendation
engine ("what should I play"). No non-English reviews. No database. No
paid anything. If asked to build any of these — including by the developer in
a moment of enthusiasm — decline, cite this section, and append the idea to
`BACKLOG.md` with a one-line reason.

## Working rules for Claude Code sessions

- Plan mode first for every non-trivial step; wait for approval before writing
  code.
- One commit per completed sub-phase (see `docs/BUILD_PLAN.md` numbering).
  Commit messages reference the sub-phase, e.g. `1.2: content filter layer`.
- New session per phase; re-read this file, `docs/PRD.md`, and
  `docs/BUILD_PLAN.md` at session start.
- Do NOT write the eval rubric wording or the post-launch decision doc — the
  developer authors those personally (they are interview material). Build the
  harness and tooling around them.
- When output of a pipeline stage is first produced for a game, print it and
  stop so the developer can read it before the next stage is built.
- UI work follows `docs/DESIGN.md` exactly. Do not substitute generic
  shadcn-default styling.

## Key docs

- `docs/PRD.md` — full requirements, metrics, risks, decision log. Source of
  truth on scope.
- `docs/BUILD_PLAN.md` — phased ASAP plan with sub-phase numbering and
  definitions of done.
- `docs/DESIGN.md` — visual direction, tokens, component specs for the site.
- `BACKLOG.md` — deferred and rejected items with reasons. Rejections stay
  rejected.
- `evals/RESULTS.md` — dated eval scores (QR-1..4). Append-only.

## Context: things already true

- Steam endpoint validated live: `store.steampowered.com/appreviews/<appid>?json=1`,
  public, no key, cursor-paginated. Field traps documented in PRD §6.
- `pipeline/fetch_reviews.py` exists (ingestion v0) — harden per plan 1.1, do
  not rewrite from scratch.
- Seed games (eval basis): Helldivers 2 (review-bombed), Cyberpunk 2077
  (launch disaster since patched), Kenshi (good but niche), Stardew Valley
  (near-universal acclaim), Death Stranding (genuinely divisive). Verify each
  appid from its store URL before first fetch.
- Launch target: Day 3 from build start. Users/interviews/iteration happen
  Days 4–8; feature freeze applies after launch.
