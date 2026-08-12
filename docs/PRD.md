# PRD v1.0 — WorthIt.gg

**Owner:** Gagan Malik · **Status:** Approved for build · **Version:** 1.0 · **Date:** July 2026 · **Target public launch:** Day 3 of build (compressed timeline; see docs/BUILD_PLAN.md)

**Changelog from v0:** Renamed from VerdictGG. Data schema confirmed against a live Steam API response — playtime segmentation validated as feasible. Added hardware-tier enrichment (F9), content safety filter (F10, launch gate), refund-cohort identification, QR-4.

---

## 1. Problem

PC gamers deciding whether to buy a game can't trust the two signals available to them. Aggregate review scores are distorted by review bombing (protests unrelated to game quality), launch-state reviews that no longer describe the patched product, and genre-mismatch negativity. Reading raw reviews solves this but costs 30–60 minutes per game, and Steam's default helpfulness-ranked ordering biases which reviews you see. The result: buyers either over-research manually or make ₹1,500–₹4,000 mistakes.

Communities like r/ShouldIBuyThisGame exist entirely because this problem is unsolved — thousands of people per week outsource the judgment to strangers and wait hours for an answer.

**Core insight:** review disagreement is usually not noise — it's segmentation. Players who refunded at 2 hours and players at 100+ hours are describing genuinely different experiences of the same product. Every existing tool, including Steam's own review summaries, averages these voices into consensus. Averaging destroys exactly the information the buyer needs.

**Validated:** Steam's public review API exposes `playtime_at_review` on every review, and Steam's 2-hour refund window makes the refund cohort a clean, non-inferred filter.

## 2. Target user

**Primary persona — "The Deliberate Buyer":** PC gamer, 18–35, buys 5–15 games/year on a constrained budget, has been burned by a hyped purchase before, already reads reviews and watches videos before buying. Found on r/ShouldIBuyThisGame, r/patientgamers, r/pcgaming, and game-specific Discords.

**Job to be done:** *"When I'm considering a specific game, help me find out in under two minutes whether people like me regret buying it — so I can decide without reading 200 reviews."*

**Not the user (v0):** console-only players, deal hunters wanting price alerts, developers wanting review analytics.

## 3. Goals & success metrics

**Product metrics (through end of post-launch window):**

| Metric | Target | Instrument |
|---|---|---|
| Unique users generating ≥1 verdict | 15+ | PostHog |
| Verdict → citation-expand rate | ≥30% | PostHog event |
| Return users | ≥15% | PostHog |
| Game requests logged (demand signal) | 20+ | Request log |
| User interviews completed | 8 | Manual |

**Quality metrics (eval harness — tracked independently of usage):**

| Metric | Baseline → Target |
|---|---|
| QR-1 Claim faithfulness | Measure at baseline → +10pts post-iteration |
| QR-2 Segment attribution accuracy | Measure at baseline → ≥90% |
| QR-3 Verdict-shape diversity across seed set | Qualitative pass/fail |
| QR-4 Content safety (zero NSFW/slur citations surfaced) | **100% — launch gate** |

**Learning goal (primary):** one shipped iteration where the change traces to user evidence and the before/after is measured.

## 4. Non-goals (v0)

- No accounts, login, or saved history. Friction with zero decision value.
- No monetization. Changes ToS exposure with Steam; adds nothing to the learning objective.
- No platforms beyond Steam/PC. No equivalent open review data exists for console.
- ~~No live/on-demand generation.~~ **Reversed 2026-07-31.** Catalog verdicts stay precomputed and static; a cache miss may generate live, but only behind a global daily quota reserve, the in-pipeline automated QR-4 gate, and honest measured-timing copy. When the reserve is spent or QR-4 fails, the title falls back to the request queue. See §5.3, D1, and CLAUDE.md § "Live on-demand generation".
- No price tracking, deal alerts, or wishlists. Different product.
- No recommendation engine. We answer *"should I buy X,"* not *"what should I buy."*
- No non-English reviews in v0.

## 5. The single workflow

1. User lands → search box + grid of available games.
2. Selects a game → **Verdict page** renders instantly from static JSON:
   - **The Verdict** — Buy / Wait / Skip, with a one-line "for whom" qualifier.
   - **Segmented reality** — refund cohort (<2h), early (2–20h), mid (20–100h), veteran (100h+). Disagreements surfaced, not averaged.
   - **Claims with receipts** — every claim expandable to verbatim source reviews with playtime context.
   - **Score-distortion flag** — review bombing / pre-patch / early-access skew, stated with evidence.
   - **Hardware context** (where data density allows) — performance claims attributed to reported GPU tiers.
3. Game not in catalog → **generated live** (a few minutes, with legible
   per-stage progress: ingest → filter → per-cohort extraction → synthesis),
   then cached permanently as static JSON like any other verdict.
   Falls back to a title request (no email) → batch-generated within 24–48 hrs
   when **either** the global daily generation reserve is spent **or** the
   automated QR-4 gate fails, in which case the title is queued for manual
   audit and nothing is published. Search is selection-only from the static
   index, so a request always carries a resolved appid, never free text.

## 6. Data foundation (validated live)

Source: `GET store.steampowered.com/appreviews/<appid>?json=1`. Public, no API key. Cursor-paginated, up to 100/page.

| Field | Use |
|---|---|
| `recommendationid` | **Citation key.** No claim ships without one. |
| `author.playtime_at_review` | Segmentation. **Minutes — converted to hours once at ingestion.** |
| `author.playtime_forever`, `playtime_last_two_weeks` | "Still playing" signal |
| `timestamp_created`, `timestamp_updated` | Pre/post-patch temporal splits |
| `voted_up` | Sentiment |
| `refunded` | Explicit refund-cohort flag — **near-empty in practice, do not rely on it** |
| `written_during_early_access` | EA distortion flag |
| `weighted_vote_score`, `votes_up`, `votes_funny` | Helpfulness / joke-review signal |
| `primarily_steam_deck` | Secondary segment |
| `hardware.*` (GPU, CPU, RAM, OS) | Optional enrichment — minority of reviews |

**Refund signal (measured, 1.1):** the `refunded` field is effectively empty —
across 400-review samples it returned Kenshi 11, Helldivers 2 6, Cyberpunk 2077
1, Stardew Valley 0, Death Stranding 0. It is a nice-to-have annotation, not a
cohort definition. **`playtime_at_review` < 120 minutes is the operative refund
signal**, and it is what `refund_window` means everywhere in this codebase.

**Known traps:** `playtime_at_review` is minutes (60× silent error if mishandled); `query_summary.num_reviews` is batch count, not total (`total_reviews` is real); default sort is helpfulness-ranked — which *is* the bias being corrected (`filter=recent` + deliberate cross-bucket sampling); `day_range` only works with `filter=all`; Steam censors profanity into `♥♥♥` sequences.

## 7. Functional requirements

- **F1 — Ingestion.** ~400 reviews/title, sampled across playtime buckets and recency, not helpfulness rank.
- **F2 — Extraction pass** (Flash-Lite). Per bucket → discrete claims tagged with supporting `recommendationid`s. **≥2-review support rule.**
- **F3 — Synthesis pass** (Flash). Verdict JSON from extracted claims only; may not introduce information absent from extraction.
- **F4 — Static delivery.** Verdict JSONs committed, served static. Zero marginal cost per user.
- **F5 — Catalog.** ~100–150 precomputed titles at launch; weekly regeneration script (manual trigger).
- **F6 — Live generation on cache miss, with request queue as fallback.** A miss from the (selection-only) search box generates the verdict live and caches it permanently as static JSON. Guarded by the global daily reserve and the in-pipeline automated QR-4 gate; when either stops it, the title falls back to a logged request, batch-processed overnight. See CLAUDE.md § "Live on-demand generation".
- **F7 — Analytics.** PostHog: session, search, verdict view, citation expand, request submit.
- **F8 — Methodology page.** Segmentation logic + live eval scores + sample-distribution transparency + Steam-summary-vs-WorthIt comparison (Death Stranding). The trust artifact.
- **F9 — Hardware enrichment.** Where ≥15 reviews carry hardware data, group performance claims by GPU tier. Degrade silently below threshold.
- **F10 — Content safety filter.** Pre-extraction: ♥-density, funny>up ratio, wordlist, low-information heuristic, cheap LLM pass on survivors. **Launch gate.**

## 8. Quality requirements (eval harness)

- ~50-case test set from the 5 seed games; each case = generated claim + cited `recommendationid`s.
- **QR-1 Faithfulness:** 0 = unsupported/hallucinated, 1 = partial, 2 = fully supported by cited reviews.
- **QR-2 Segment accuracy:** cited reviews genuinely belong to the claimed bucket (Y/N).
- **QR-3 Shape diversity:** verdicts across the 5 seed games must differ structurally; identical shapes = eval failure even if claims are faithful.
- **QR-4 Content safety:** zero NSFW/slur reviews surfaced in citations. Blocks launch.
- LLM-as-judge, validated against a manual 10-case spot-check before its scores are trusted. Rubric wording authored by the owner, not generated.
- Runs at baseline, post-iteration, and before any regeneration ships. Scores published on the methodology page.

## 9. Constraints & decision log

**Budget: ₹0.** Gemini free tier. Verified per-model daily ceilings (from the 429 body, encoded in `pipeline/live_quota.py`): Flash-Lite 500/day, Flash 20/day. Steam data keyless. Vercel + PostHog free tiers. Domain deferred.

| # | Decision | Rationale | Tradeoff |
|---|---|---|---|
| D1 | Precomputed verdicts, **plus reserve-guarded live generation on cache miss** (revised 2026-07-31) | Cached views keep ₹0 marginal cost and instant latency. Live generation buys the first-visit experience a 150-title catalog cannot: the answer now, not tomorrow | **Spike-proof is now conditional, not absolute.** Cached verdicts remain spike-proof — static files on a CDN. *Generation* is protected only by the global daily reserve (`LIVE_RESERVE`, default 100 of 500 req/day, leaving 400/day for batch): a large enough spike exhausts it, after which generation degrades to the queue. Degradation is graceful and automatic, but it is a real ceiling, and per-IP limits cannot substitute for it |
| D2 | Playtime segmentation as core differentiator | Existing summaries flatten disagreement into consensus | More complex pipeline |
| D3 | Two-pass extraction → synthesis | Hallucination becomes measurable and localizable | 2× calls/title (immaterial at free-tier volume) |
| D4 | ≥2-review support rule | Suppresses one-off opinions presented as patterns | Loses rare-but-real signals |
| D5 | Content filter as launch gate | A trust product citing a slur is unrecoverable at first impression | Slight recall loss on blunt-but-legit reviews |
| D6 | Deterministic grounding check before LLM judging | Free, runs on every generation; catches crude hallucination without spend | Lexical overlap is a coarse instrument |
| D7 | Self-consistency (double-run) on seed set only | Direct free substitute for a paid stronger model; quota-bounded | Long tail gets single-pass quality |

## 10. Risks & mitigations (all ₹0)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Hallucinated claims in a trust product | High (Flash-class) | Deterministic grounding check; structural constraint (synthesis limited to extracted claim IDs); structured output schema + `thinking_level: minimal` with no sampling parameters (Gemini 3.x deprecates temperature/top_p/top_k — invariant 6); self-consistency on seed set; 10 manual judge-validation checks |
| **Daily Gemini quota exhausted by a traffic spike** (added 2026-07-31 with live generation) | Medium — one Reddit front-page hit is enough | Global daily reserve (`LIVE_RESERVE`, default 100 of 500), checked before dispatch, not per-IP — per-IP is unbounded across clients and cannot protect a global budget. On exhaustion live generation switches off automatically and misses fall back to the queue; **cached verdicts are unaffected**, being static files on a CDN. Degradation is graceful, but it is a real ceiling (see D1) |
| **A live-generated verdict reaching a user unaudited** | Medium — no human is in the loop | The automated QR-4 gate (`pipeline/qr4_gate.py`) runs after synthesis and before publication; on any failing citation the artifact is deleted, nothing is committed, and the title is queued for manual audit. Invariant 8 holds for generated titles by construction |
| **NSFW/slur citation at launch** | **High — observed in live sample** | F10 filter stack; QR-4 hard gate; citations behind expand only (blast radius); manual audit of 20 random citations pre-launch |
| Dead launch | Medium | Reply-first on r/ShouldIBuyThisGame; per-game subreddit posts; warm channels pre-seeded; Steam-sale timing; pivot to interview depth if no traction by Day 5 |
| Sampling bias reproduces the problem being solved | Medium | Per-bucket quotas; merge recent+all filters, dedupe on ID; distribution report per run; publish sample-vs-Steam distribution on methodology page |
| Steam throttling during batch | Low–Med | Overnight batch, backoff on 429, disk cache, never re-fetch, incremental refresh by timestamp |
| "Steam already summarizes reviews" | Certain | Positioning = decision + segmentation + receipts; side-by-side comparison on methodology page |
| Scope creep (Claude Code makes building too cheap) | High | BACKLOG.md protocol; non-goals as contract; feature freeze post-launch; only the decision-doc iteration ships in the tail week |

## 11. Open questions

- Optimal review sample size per title (400? 800?) — tune against eval scores.
- Verdict taxonomy: is Buy/Wait/Skip sufficient, or does "Buy on sale" earn a place? Test in interviews.
- Should distortion flags name the review-bombing cause? Accuracy risk vs. usefulness — test in interviews.
- Minimum hardware-data density for F9 to be signal rather than noise.
- Does the refund cohort deserve visual primacy, or does leading with it read as negative bias?

## 12. Seed set (eval basis)

| Game | Case | What it tests |
|---|---|---|
| Helldivers 2 | Review-bombed | Distortion flagging without dismissing legitimate complaints mixed in |
| Cyberpunk 2077 | Launch disaster, since patched | Recency weighting; naive sampling describes a game that no longer exists |
| Kenshi | Good but niche | The "for whom" qualifier — Buy for a narrow persona, Skip for most |
| Stardew Valley | Near-universal acclaim | Value-add when the answer looks obvious (surfacing real minority dissent) |
| Death Stranding | Genuinely divisive | Preserving disagreement instead of averaging it into mush |

Correct verdicts differ in *shape* across all five — the property QR-3 measures. Verify each appid from its Steam store URL before first fetch.
