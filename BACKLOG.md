# BACKLOG — WorthIt.gg

**Purpose:** this file exists to stop things from being built. Every feature idea
lands here instead of in the codebase. Nothing moves from here into the repo
before the case study is published.

**Rules**
1. If an idea arrives mid-build — mine, a user's, or Claude Code's — it gets
   written here and the current task continues.
2. Anything in "Rejected" stays rejected. Re-litigating a rejection costs more
   than the feature is worth.
3. Every entry records *why*. The reasoning is the point, not the list.
4. Entries sourced from real users are marked `[user]` — those are the only ones
   with earned priority after launch.

---

## Deferred until after launch + case study

| # | Item | Why deferred |
|---|---|---|
| D1 | Custom `.gg` domain | Vercel subdomain converts fine; costs money; zero learning value |
| D2 | Expand catalog beyond ~150 titles | Request queue reveals real demand first; batch quota is the constraint |
| D3 | Automated weekly regeneration (GitHub Actions) | Manual re-run is 20 min; automation is engineering polish, not product evidence |
| D4 | Non-English reviews | Adds translation cost + doubles eval surface for marginal coverage |
| D5 | Steam Deck as a first-class segment | `primarily_steam_deck` exists but playtime segmentation is the thesis; don't dilute it |
| D6 | Hardware-tier grouping (F9) if data density is low | Only ships where ≥15 reviews carry hardware data; otherwise it's noise dressed as insight |
| D7 | "Buy on sale" as a fourth verdict | Open question in PRD §11 — resolve with interview evidence, not intuition |
| D8 | Naming the review-bombing cause in distortion flags | Accuracy risk; test in interviews before shipping |
| D9 | Comparison view (game A vs game B) | Different job-to-be-done; would double the surface area |
| D10 | Shareable verdict images / OG cards | Real distribution value, but post-launch — launch beats polish |

## Rejected — do not build

| # | Item | Why rejected |
|---|---|---|
| R1 | Accounts / login / saved history | Friction with zero decision value; PRD non-goal |
| R2 | Monetization of any kind | Changes ToS exposure with Steam; adds nothing to the learning objective |
| R3 | Console / non-Steam platforms | No equivalent open review data source exists |
| ~~R4~~ | ~~Live on-demand generation per request~~ | **Reversed 2026-07-31 — moved to Implemented as I1.** Rule 2 says rejections stay rejected; this one was overturned by explicit owner decision, which is the only thing that may overturn one. Recorded rather than deleted. |
| R5 | Price tracking, deal alerts, wishlists | Different product entirely |
| R6 | Recommendation engine ("what should I play") | We answer "should I buy X" — narrower question is the wedge |
| R7 | Switching to a paid model to fix hallucination | Wrong diagnosis; grounding checks + self-consistency solve it for free |
| R8 | Database / backend service | Static JSON is the architecture; a DB is unrequested complexity |
| R9 | User-submitted reviews or ratings | Moderation burden, cold-start problem, dilutes the source-of-truth story |

## Implemented — moved out of Deferred/Rejected

| # | Item | Why it moved, and what it cost |
|---|---|---|
| I1 | **Live on-demand generation on cache miss** (was R4) | Reconsidered for early-days UX: with a ~100–150 title catalog, most first visits from Reddit will miss, and "check back tomorrow" spends the one moment of attention a launch gets. Owner decision, 2026-07-31. **Admitted only with four guards** (CLAUDE.md § "Live on-demand generation"): a *global* daily quota reserve — per-IP was rejected as the primary limit because it is unbounded across IPs — with automatic fallback to the queue when spent; the automated QR-4 gate in-pipeline, failure meaning *not published*; honest copy set from measured runs, never "under a minute"; and cached verdicts untouched on the CDN. D1's spike-proof property is now conditional on the reserve rather than absolute — that is the real price paid, and it is recorded in PRD §9. |

## Open questions (from PRD §11) — resolve with evidence, not building

- Optimal review sample size per title (400? 800?) → tune against eval scores
- Verdict taxonomy sufficiency (see D7)
- Distortion-flag specificity (see D8)
- Minimum hardware-data density for F9 to be trustworthy
- Does the refund cohort deserve visual primacy, or does leading with it read as negative bias?

## Captured during build / launch

<!-- Append below. Format: date | item | source | why it's here and not in the code -->

2026-07-30 | **Watch claim-drop rate against cohort review length during the
Phase 4 catalog batch** | build, phase 1.4 | Kenshi's `early` cohort burned both
grounding retries and still lost 3 of 9 claims, while its other three cohorts
lost none. Not a Kenshi quirk: `early` has the shortest surviving reviews across
the whole seed set (median 23 words, 45% under 20 words, vs veteran's 36 words /
32%). Short reviews carry few content tokens, which depresses lexical coverage,
and make it less likely that two separate reviewers name the same specific thing
— so the ≥2-supporting-citations rule bites hardest exactly where reviews are
shortest. The real predictor is **cohort median length, not the cohort label**:
Cyberpunk's `early` runs 32 words and should behave fine, while Stardew `early`
(18 words, 55% short) and Death Stranding `mid` (21 words, 49%) should struggle.
Falsifiable, and 1.5's runs on the other four games test it for free. Not acting
now because the fix would be either lowering the grounding threshold (ships
unverifiable claims) or relaxing the ≥2 rule (breaks invariant 3) — both worse
than a thinner early section. If it recurs catalog-wide, the honest response is a
UI one: let a cohort render with fewer claims rather than pretending to parity.

> **2026-07-30, tested — the prediction was wrong.** Across the other four seed
> games, drops were 2 in total (Stardew `mid` 1, Helldivers `mid` 1) against
> Kenshi's 3 in one cohort. The named cohorts did not struggle: Stardew `early`
> (18-word median, the shortest in the set) lost nothing, and Death Stranding
> `mid` lost nothing. Cohort median length does **not** predict claim drops.
> Kenshi `early` remains a one-off, and 20-word medians elsewhere were fine.
> What does vary is **claim yield**, not drop rate: Stardew `refund_window`
> produced a single claim from 20 reviews while its `veteran` cohort produced
> six. Watch yield per cohort in the Phase 4 batch, not drops — a cohort that
> renders with one claim is the thin-section risk, and it comes from reviewers
> having little specific to say rather than from the grounding check.

2026-07-29 | **Temporal bucketing (pre/post-patch splits) alongside playtime
buckets** | build, phase 1.1 | Cyberpunk 2077 exposed the limit of the thesis:
playtime segmentation cannot see a redemption arc. A 2020 launch review and a
2025 post-2.0 review both land in `veteran` and get averaged — exactly the
failure mode the product exists to correct, on a different axis. `timestamp_created`
is already ingested, so the data is there. Not built now because it doubles the
segmentation surface, invalidates the bucket definitions the evals are pinned to
(invariant 2), and would push launch past Day 3. Revisit with the post-launch
iteration if the Cyberpunk verdict reads as wrong to users — that would be
evidence, which is the bar.

---

*This file is a case-study artifact. What got deferred, and the reasoning for
each, is evidence of prioritisation under constraint — link it from the case
study's decision section.*
