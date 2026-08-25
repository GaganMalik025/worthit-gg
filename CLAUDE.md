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

## Bash commands

Prefer these over defaults when available. Fall back silently if missing.

- **Search content:** `rg` over `grep`
- **Find files:** `fd` over `find`
- **Never** use `find -exec` or `xargs` chains when `fd -x` or `rg -l | xargs` would be clearer. Prefer readable pipelines.
- **Structural/AST search:** `ast-grep` (`sg`) for refactors and pattern-based code search, especially in TS/TSX
- **JSON:** `jq` for any parsing, filtering, or transformation in pipelines
- **YAML/TOML:** `yq`
- **GitHub operations:** `gh` for PRs, issues, reviews, CI status, and releases. Do not scrape github.com or hit the REST API directly when `gh` can do it.
- **Benchmarking:** `hyperfine` when comparing command performance
- **Circular deps (JS/TS):** `madge --circular`
- **Dead code (JS/TS):** `knip`
- **Duplication (JS/TS):** `jscpd`
- **Typecheck only:** `tsc --noEmit` (or `tsc -b --noEmit` in monorepos)

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
   minutes must **never reach an LLM prompt**, and must **never be displayed**.
   - **Amended 2026-08-22.** This used to read "never reach an LLM prompt or the
     UI". Citations now carry `minutes_at_review` beside `hours_at_review`,
     because the bucket is assigned on minutes (invariant 2) while the display
     was rounded from hours, and the two disagreed at the boundary: 118 minutes
     is `refund_window` and always was, but rendered as `2.0 hrs` under a
     `<2h refund window` heading. 78 citation instances across 514 verdicts read
     that way. Minutes are a **precision input for the renderer and nothing
     else** — `site/lib/verdict.ts:citationHours` is the only consumer.
   - The LLM-prompt half is unchanged and absolute. The display half is now
     enforced in code rather than promised in prose:
     `site/lib/__tests__/citation-hours.contract.test.tsx` renders a sentinel
     minutes value and asserts it never reaches the markup. A 60× silent error
     looks like a plausible number, which is why this gets a test and not a
     comment.
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
10. `site/public/verdicts/` is committed to git on purpose — it is what the static
    site serves. Never add it to `.gitignore`. It lives under `site/` because Vercel's Root Directory is `site/`, and a Vercel app cannot read files outside its root. `data/raw/` stays gitignored
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
    - **Event frequency is not prevalence (2026-08-21).** How often a *thing*
      happens — "occasional crashes", "persistent startup failures" — is allowed;
      how many *people* is not. The guard's frequency words were freed in full
      (`pipeline/prevalence_guard.py`, `FREED_FREQUENCY_PATTERNS`) after they cost
      real output: RuneScape burned 9 calls and published nothing, Insurgency
      deadlocked three nights. Population, proportion, ratio, percentage and
      consensus language stay banned and are what invariant 11 now means.
      **The prompt is derived from the guard** via `banned_words()` and must never
      name a word the guard permits — a model told to avoid a word spells around
      it rather than dropping it.
12. **Minimum cohort evidence is 20 surviving reviews.** [see invariant 13 for
    how the resulting `n=` label is sourced] Below 20 reviews in a
    bucket after filtering, no claim may be attributed to that cohort; the
    section renders muted with an explicit `n=` label instead. Refund-window
    counts pre-filter on the seed set: Kenshi 47, Helldivers 2 30, Death
    Stranding 26, Stardew Valley 24, **Cyberpunk 2077 12** — already below the
    floor before the filter runs. Cohorts are exhausted at ingestion (kept ==
    pool), so a review the filter drops cannot be replaced.
    - **ZERO IS INCLUDED, and is the default since 2026-08-21.** A cohort that
      filters to no survivors mutes exactly like an under-20 one and renders its
      pool figure. It does **not** fail the title. Settled by three titles in six
      nights — Hotline Miami (1 of 400 veteran reviews), A Way Out (2 of 400),
      A Plague Tale: Innocence (1 of 1,203) — all short finite games, where a
      100-hour cohort is undefined by construction rather than thin by sampling
      accident. Failing the title published nothing at all instead of three sound
      cohorts and one honest muted section. `pipeline/data/zero_cohort_exceptions.txt`
      is superseded by this and decides nothing; its one entry is kept as the
      record of how the question was decided, and new titles need no entry.
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
    - **`citation_verdict` on a claim is not the claim's sentiment.** It is the
      aggregate `voted_up` of that claim's cited reviews — what those reviewers
      thought of *the game overall* — computed in code, never model-inferred,
      and shipped with its raw split (`4u/1d`). Kenshi veterans produce "the
      game features frequent bugs and technical jank" at 4u/1d: a complaint from
      people who recommend the game. Nothing may render it as claim valence.
      Claims group by **theme** (DESIGN.md); cohort sentiment comes from **pool
      rates**. There is no per-claim sentiment field and nothing should add one.

## Budget rules

- **Total budget is ₹0.** Gemini free tier only. The real per-model daily
  ceilings, verified from the 429 body and encoded in `pipeline/live_quota.py`:
  **Flash-Lite 500/day** (`DAILY_LIMIT`), **Flash 20/day**
  (`FLASH_DAILY_LIMIT`). Never suggest a paid model, paid API, paid hosting, or
  any paid service. If a problem seems to need one, the answer is architecture
  (grounding checks, self-consistency, caching, precompute), not spend.
- Quota discipline: self-consistency double-runs only on the 5 seed games and
  contested outputs; single-pass the long tail. Batch runs go overnight with
  backoff; raw responses cached to disk; never re-fetch what exists.
- API key lives in `.env` (gitignored). If any code would print, log, or
  commit it, stop and fix.

## Batch-night operating procedure

**This section does not license starting a batch.** The trigger to run
`pipeline/run_batch.py` always comes from the developer, explicitly, in that
session. Nothing here is standing permission — not a clean tree, not a full
400-call ledger, not a stale `LIVE_QUOTA`. Orientation and the quota check are
free; spending quota is not.

Standing rules, every session:

- **Real measurement before any threshold or rule change.** No "probably".
- **Break-then-confirm on every new test or guard:** prove it FAILS on a
  deliberate mutation before trusting that it passes. A green suite is not
  evidence the suite works.
- **Mutation drivers, raw logs and cited output live in the repo at a real
  path** — `evals/` or `pipeline/`, never a `scratchpad/...` path. A citation
  that cannot be opened is not verifiable. Citing a QR-4 run as evidence means
  committing the raw output (`evals/qr4-<date>.txt`), not a restatement of it.
- **Live verification on production before calling anything done.** Passing
  tests alone do not count as shipped. This is about output that REACHES USERS —
  verdicts, the site, published artifacts. A change that ships no new output
  (guards, tests, eval drivers, prompts, docs) is done when its own committed
  evidence is green; **do not watch the CI run after pushing it** (developer
  instruction, 2026-08-26). Report the push and stop. CI failures surface on
  their own, and are worth checking only when asked or when a later step
  depends on the run.
- **Never commit or push without explicit go-ahead.** Report first, every time.
- **New findings mid-task go to BACKLOG.md's "Captured during build / launch"** —
  record, don't fix, unless told otherwise. If a fix lands as a side effect of
  unrelated work, update the entry it closes in the same change: a stale "not
  yet fixed" entry misleads exactly as much as a wrong one (see the
  `select_publishable.py` record correction, 2026-08-17).
- **Report only commands actually run.** Never reconstruct, summarise or
  predict output that was not produced — see the 2026-08-16 INCIDENT entry in
  `evals/RESULTS.md`, a fabricated QR-4 PASS caught only because the developer
  cross-checked file timestamps against the disk. Assume every number, path and
  timestamp is independently re-derived against the filesystem, every time.
- **Start the batch through `pipeline/run_batch_logged.sh`, never bare.**
  `run_batch.py` exits 1 when any title ends `stage_failed` and never prints
  that value, so a log alone cannot show what a run returned — and
  `python run_batch.py | tee log` makes `$?` **tee's** status, which is 0
  whenever the file is writable. An "exit 0" read off a clean summary block is
  therefore an inference, and it was wrong on 08-18 and 08-19 (BACKLOG,
  2026-08-20). The wrapper sets `pipefail`, reads `PIPESTATUS[0]`, and writes
  `EXIT_RC=` into the log itself. Never report an exit code the log does not
  carry.

**Post-batch sequence — reference, not an instruction to run it unprompted.**
Each step waits for the developer.

1. `run_batch.py` completes → report titles attempted, published, gate-drops
   with reasons, stage failures, calls spent, real cost/title, new published
   catalog total, Buy/Wait/Skip mix. A run that dies with no
   summary/interrupt/budget-stop line in the log is reconstructed from what the
   ledger and `batch_state.json` arithmetic can prove, with the gap stated
   plainly and the cause asked about — never guessed.
2. On go-ahead: `pipeline/qr4_gate.py --all` (invariant 8 — any failure blocks).
3. `pipeline/build_search_index.py` — confirm every verdict appid is present by
   **set membership, 0 missing**, not a row-count diff.
4. `evals/make_audit_sample.py --date <date> --seed <YYYYMMDD>` — a new seed per
   round, never a previous night's.
5. Developer reads the audit directly. Wait for it.
6. Commit + `evals/RESULTS.md` entry + push, on explicit go-ahead.
7. Verify the Vercel deploy, then fetch a new verdict from production and
   confirm it by its real `generated_at`, not by name. This step stays — a batch
   night ships user-facing output. The CI run itself is not watched.

`evals/positivity_by_night.py` carries a hardcoded `NIGHTS` list — extend it
with tonight's date before running, if the verdict mix looks worth checking
against the trend.

## Non-goals — refuse and add to BACKLOG.md instead

No accounts/login/history. No monetization. No non-Steam platforms. No price
tracking/deals/wishlists. No recommendation engine ("what should I play"). No
non-English reviews. No database. No
paid anything. If asked to build any of these — including by the developer in
a moment of enthusiasm — decline, cite this section, and append the idea to
`BACKLOG.md` with a one-line reason.

## Live on-demand generation — allowed, but only fully guarded

Reversed on 2026-07-31 (was a non-goal; see BACKLOG I1). A cache miss from the
search box may generate a verdict live. It is in scope **only** with all four
guards below intact. Remove any one of them and it goes back to being a
non-goal — they are the reason it is permitted, not decoration.

1. **Global daily quota reserve, not per-IP.** A single global counter reserves
   the tail of the daily Gemini budget (`LIVE_RESERVE`, **default 100 of 500**)
   for live generation, leaving 400/day for batch work. When the reserve is
   spent, live generation switches itself off for the rest of the day and cache
   misses fall back to the queue
   flow. Per-IP throttling exists only as a secondary guard against one user
   burning the global reserve — it is never the primary limit, because per-IP
   is unbounded across IPs and cannot protect a global quota.
2. **The automated QR-4 gate runs in-pipeline, before anything renders.** If any
   citation fails it, the verdict is **not published**: the title drops into the
   queue for manual audit and the user sees the queue copy. Nothing reaches a
   user that the automated gate has not passed. Invariant 8 is unchanged.
3. **Honest copy, set from measured runs.** The wait is stated in real observed
   numbers and progress is legible per stage (ingest → filter → per-cohort
   extraction → synthesis), never a bare spinner and never an optimistic
   estimate. If a measured run gets slower, the copy changes, not the claim.
4. **Cached verdicts are never affected.** They stay static files on the CDN:
   zero marginal cost, instant, and completely unaffected by reserve
   exhaustion, generation failures, or traffic spikes.

## Working rules for Claude Code sessions

- Plan mode first for every non-trivial step; wait for approval before writing
  code.
- One commit per completed sub-phase (see `docs/BUILD_PLAN.md` numbering).
  Commit messages reference the sub-phase, e.g. `1.2: content filter layer`.
- New session per phase; at session start re-read this file, `docs/PRD.md`,
  `docs/BUILD_PLAN.md`, `BACKLOG.md` in full (including every `>` follow-up
  block — a follow-up often reverses or narrows the entry above it) and
  `evals/RESULTS.md`'s most recent entries, then `git log --oneline -20`.
  Confirm the working tree is clean and main matches origin/main before acting.
- Do NOT write the eval rubric wording or the post-launch decision doc — the
  developer authors those personally (they are interview material). Build the
  harness and tooling around them.
- When output of a pipeline stage is first produced for a game, print it and
  stop so the developer can read it before the next stage is built.
- UI work follows `docs/DESIGN.md` exactly. Do not substitute generic
  shadcn-default styling.
- **Reports are SHORT — and shortness NEVER comes from leaving something out.**
  These are two rules and the second one wins. **Nothing may be omitted,
  softened, deferred or rounded away to save space**: not a stage failure, a
  gate result, a caveat, a number that complicates the story, a limit on what
  was actually verified, an assumption, or an error made mid-task. If it would
  change what the developer does next, it appears — every time, however tight
  the report. An omission is a silent error and is strictly worse than a long
  report. Shortness comes from COMPRESSION instead: headline result, one table
  of numbers, one line each for anything that failed or needs a decision. No
  restatement, no preamble, no narration of process, no re-explaining a finding
  already written to BACKLOG or RESULTS — cite the path. One sentence where
  three would do. Every item still present, each stated once and briefly rather
  than argued; the full reasoning lives in the committed entry, which is the
  citable artifact. **If the two pull against each other, keep the item and cut
  the words around it.**

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
- **Gemini `AQ.` auth keys need an explicit service-account binding, and AI
  Studio's key-creation flow omits it.** Symptom: a well-formed `AQ.` key returns
  `401 UNAUTHENTICATED / ACCESS_TOKEN_TYPE_UNSUPPORTED` on every auth form
  (`x-goog-api-key`, `?key=`, `Bearer`) and on any SDK version — it looks like a
  bad key or a Vertex misroute and is neither. Fix: create the key from **Cloud
  Console** with *"Authenticate API calls through a service account"* ticked.
  Do not re-debug this from the client side; the client is fine.
  (`AIza` standard keys are rejected outright from September 2026.)
- `pipeline/fetch_reviews.py` exists (ingestion v0) — harden per plan 1.1, do
  not rewrite from scratch.
- Seed games (eval basis): Helldivers 2 (review-bombed), Cyberpunk 2077
  (launch disaster since patched), Kenshi (good but niche), Stardew Valley
  (near-universal acclaim), Death Stranding (genuinely divisive). Verify each
  appid from its store URL before first fetch.
- Launch target: Day 3 from build start. Users/interviews/iteration happen
  Days 4–8; feature freeze applies after launch.
