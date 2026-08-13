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

2026-08-13 | **`pipeline/test_batch_guards.py` failed once, unreproducibly, and
the evidence was thrown away** | build, regression run before the art commit |
One run exited 1 where the twelve runs around it exited 0. The failing run's
output went to `/dev/null`, so WHICH check failed is unknown and unrecoverable.
Attempts to reproduce: 3 sequential, 3 with `npm test` running concurrently (the
condition the failure occurred under), 5 more sequential - **11/11 green**. The
suite touches no network; its git tests build real repos in temp dirs, so a
remote transient is not the explanation. Two candidates, neither confirmed: a
timing-sensitive check under load (the pacer tests assert on wall-clock windows,
and `test_ledger_charge_is_atomic` spawns 12 processes with a 90s budget), or a
temp-dir/filesystem race. **Why this is not being chased now:** a 1-in-12 flake
with no captured output is not debuggable from the outside - it needs the
failure in hand. What SHOULD happen next time the suite is touched: stop
redirecting it to `/dev/null` in any script or check, and have failures write to
a kept log. That is also the cheap half of the fix for `e06538a` (CI never runs
this suite) - a suite that flakes silently is worse in CI than out of it,
because there it fails a push nobody can explain. Related: [[verify-the-verifier]].

2026-08-13 | **The pipeline's Gemini project binding is undocumented locally, so
quota collisions with other work on the same account are undetectable from the
repo** | build, checking whether a second AI Studio project shares this key |
`.env` carries `GEMINI_API_KEY` (a 53-char `AQ.` service-account-bound key) and
nothing else that identifies where it draws from: no `GOOGLE_CLOUD_PROJECT`, no
project ID in `.env` or anywhere under `pipeline/` (the "project" strings in the
code are all comments *about* the per-project quota scope, not an identifier).
An `AQ.` key does not self-describe its project, so answering "does this key
share a project with X?" requires Cloud Console or an authenticated `gcloud` —
it cannot be answered from a checkout. **Why it matters:** the ceiling is
`GenerateRequestsPerDayPerProjectPerModel-FreeTier` — per project, per model. If
other work on the account sits in the same project, it draws from the same
500/day Flash-Lite pool a batch night plans against, and the batch would collide
with it mid-run with no local signal that anything was competing. **Same shape
as `2ec78e6`, one level up the stack:** there, two ledgers of one budget that
never reconcile; here, one ledger that cannot see a whole other consumer of the
same budget. Not fixed — it needs the project ID recorded somewhere the repo can
read (even a comment in `live_quota.py` next to the DAILY_LIMIT note, or a
`GOOGLE_CLOUD_PROJECT` line in `.env.example`), which is a decision about what to
commit rather than a code change, and the ID is not something this session can
verify without Console access.

2026-08-12 | **Nothing in CI ever runs `pipeline/test_batch_guards.py` — two
independent gaps, not one** | build, after pushing the concurrency-test fix |
`ci.yml` did not run on the push carrying `adf26e3`, and would not have run on
any change to the guard suite. **Gap one, the trigger:** the push path filter
lists `site/**`, `site/public/verdicts/**`, `pipeline/live_quota.py`,
`pipeline/quota_day.py` and the workflow file. `pipeline/test_batch_guards.py`
is not among them. (Note the trigger is *not* site-only — two pipeline files are
there deliberately, because quota-constant drift between `site/lib/quota.ts` and
`pipeline/live_quota.py` is what motivated them. The gap is the guard suite
specifically, not pipeline coverage in general.) **Gap two, and the reason the
obvious fix is not a fix:** the single `test` job is `actions/checkout` →
`actions/setup-node` → `npm ci` → `npm test`, all in `site/`. There is no
`setup-python`, no venv, no dependency install, and no step that invokes any
Python at all. Adding `pipeline/**` to the path filter would therefore start
triggering the workflow on guard-suite changes and still not execute a single
guard test — arguably worse than today, because the run would go green and look
like coverage. What this costs right now: tonight's fix to
`test_ledger_charge_is_atomic` is verified **only** by the local
break-then-confirm run (three mutations, each caught, suite green after
restore). That is real evidence and it is the only evidence; nothing re-runs it
on the next push, so a future change that quietly breaks the guard suite —
including one that breaks the atomicity guard it protects — surfaces at the next
manual run rather than at the next push. Deferred rather than fixed because it
needs both halves done together: a path-filter entry AND a new job step
(`setup-python`, install, `pipeline/test_batch_guards.py`), and the suite shells
out to `git` against real refs in temp worktrees, so it wants a check that it
actually passes on a clean runner before it is trusted as a gate.

2026-08-12 | **The pacer's cross-process test has the same unchecked-exit-code
shape the ledger test just had** | build, fixing test_ledger_charge_is_atomic |
`test_pacer_ceiling_across_processes` (test_batch_guards.py:67) spawns 5
children and never looks at a return code either. It is **less dangerous than
the ledger case was**, and that is the whole reason it is here rather than
fixed: it reads each child's stdout through `json.loads`, so a child that dies
produces a `JSONDecodeError` and the test fails loudly instead of quietly
counting lower. The failure is honest but unhelpful — a decode traceback points
at the parse, not at "a child process died", so whoever hits it starts by
debugging the pacer rather than the environment. Worth the same treatment as
`adf26e3` (assert exit codes first, capture stderr, then assert the behaviour)
next time that file is open. Not doing it now because it is a diagnosis-quality
improvement to a test that already cannot pass silently, and the standing
instruction for tonight is to record rather than widen scope.

2026-08-12 | **A title that raises inside run_title() spends quota but leaves no
trace in batch_state.json** | build, 2026-08-12 overnight batch | Marvel's
Spider-Man Remastered (`1817070`) timed out tonight — `extract_claims.py` hit its
900s limit — and the exception propagated out of `run_title()` to the
`except Exception` around `f.result()` in `run_batch.main()`. That handler prints
`[ERR]` and continues, which is right: one title must not end a night. But
`record()` is called at the *end* of `run_title()`, so a raise anywhere before it
means the title is never written to `data/batch_state.json` at all. The calls it
already made were charged to the quota ledger by `generate_one`, which charges as
it goes. So the spend is real and the record is absent: tonight the run summary
reported 391 model calls while the ledger reported 396, and the 5-call gap is
exactly this title. Two consequences. First, `batch_state` is not a reliable
account of what a night cost — anything reconciling the two will keep finding
drift. Second, because the appid has no entry, it is not in the `TERMINAL` set,
so it lands back in `todo` on the next run and retries: a title that times out
*reliably* will burn ~5 calls and up to 15 minutes every single night, silently,
and nothing in the state file ever shows it happening. Tonight that is 1 title
out of 45; it stops being cosmetic the moment it is a title that always fails.
Not fixed now because the fix is not just moving `record()` into a `finally` —
the entry needs an outcome the retry logic can reason about, and deciding whether
a timeout is terminal (never retry, may be a genuinely un-processable title) or
transient (retry, may have been a slow API night) is a real product call that
wants more than one night of evidence. Cheap interim step when it is picked up:
record the failure with a `timed_out` outcome, leave it non-terminal, and count
retries so a permanent failure becomes visible instead of silent.

2026-08-12 | **The live and batch quota ledgers are two independent counters of
one 500/day budget** | build, pre-batch LIVE_QUOTA check | Tonight's parity check
found `live_used` at 13 in the `LIVE_QUOTA` GitHub variable against 5 in
`data/live_quota.json`. This is **structural, not staleness**: `site/lib/github.ts`
reads and writes the repository variable, `pipeline/live_quota.py` reads and
writes the local file, and a grep for any reconciliation path finds none in
either direction. Neither ledger can see the other's spend. It did not block the
2026-08-12 batch because both carried a stale `date` and `load()` zeroes a ledger
whose date is not the current Pacific quota day, so the night started at a true
400/400. The failure it sets up is a **heavy live-traffic night**: live
generation beyond its 100-request reserve is invisible to the batch ledger, so
the batch keeps dispatching against headroom it believes it has and takes 429s
mid-run. Not fixed now because the honest fix is one ledger with one writer, and
the only shared store both sides can reach is the GitHub variable — that makes
every batch title a network write against a rate-limited API, mid-run, which is a
new failure mode traded for an old one. Revisit after launch, when real live
traffic shows whether the 100 reserve is ever actually exceeded. Until then the
mitigation is operational: check the variable before a night, not the file.

2026-08-12 | **Raw end-user IP addresses are stored unhashed in the `LIVE_QUOTA`
GitHub variable** | build, pre-batch LIVE_QUOTA check | `by_ip_hour` keys are
built as `"<ip>|<hour>"` and persisted verbatim — `site/lib/quota.ts`
(`chargeReservation`) and `pipeline/live_quota.py` (`record`) both do it, so it
is intended behavior in both implementations rather than drift. One real
visitor's address was sitting in the variable when it was read. This sits oddly
against the project's no-accounts, no-database stance: the product deliberately
collects nothing about who is asking, and then writes the one identifier it does
receive into repository state. The per-IP counter only ever needs to answer "has
this client had 5 this hour", which a salted hash of the address answers exactly
as well. Not fixed now because it touches the live path on the night of a batch
and the guards in CLAUDE.md § "Live on-demand generation" are load-bearing —
changing the key format without care silently resets every in-flight per-IP
counter. Cheap and worth doing early post-launch: hash the address with a salt
that is not in the repo, keep the hour suffix, and the guard behaves identically.
(The observed address is deliberately not recorded here — writing it into a
committed file would reproduce the exact exposure being flagged.)

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

2026-08-07 | **Reconcile the live reserve against real generation cost** | build,
live generation | `/api/generate` reserves `EST_COST = 13` requests before
dispatching, because the check and the spend cannot be atomic across a
`repository_dispatch` boundary and a burst must not oversubscribe the reserve.
Measured cost of a real generation is **~5–6 calls** (Hades: 4 cohort extractions
+ 1 synthesis). So the 100-request reserve is worth ~7 generations/day rather
than the ~18 it could be. Not fixed because reconciliation requires the runner to
write the shared ledger back after the run, and the runner's `GITHUB_TOKEN` can
neither read nor write repository variables — `variables` is not in that token's
permission surface at all, so no `permissions:` widening reaches it. The only
in-runner fix is a PAT, which is new long-lived credential surface for a
bookkeeping nicety. The current behaviour **fails safe**: it over-counts, never
under, so the reserve can shut live generation off early but can never let it
overrun the Gemini budget. Revisit if a safe mechanism emerges — a callback the
site can authenticate, or the runner reporting spend through an artifact the site
already reads. Until then the honest framing is that the reserve is measured in
*reservations*, not requests.

2026-08-10 | **Single-stage runs bypass the ledger charge entirely** | build,
quota discipline | `generate_one.run_single_stage()` charges `live_quota` in the
**qr4 stage only**, as a delta from the baseline the **ingest** stage writes. A
full run therefore charges once, correctly, at the end. But a run invoked as
`--stage verdict` (or `--stage extract`, or any stage in isolation) never reaches
that branch, so the shared daily counter never learns the spend happened. The
header rollout hit this at full scale: **170 flash-lite requests spent, ledger
read 0**, and `batch_remaining` still showed the full 400. Reconciled by hand
with `live_quota.charge(176, ledger="batch")`, verified against the pacer's
`requests_today`. This is structural, not a one-off — every future single-stage
batch run has the same hole, and the failure is silent in the direction that
matters: the ledger UNDER-reports, so guard 1's reserve can be granted against
budget that is already spent, which is the exact condition it exists to prevent
(the opposite of the `EST_COST` entry above, which over-counts and fails safe).
Fix is one of: charge per stage as each completes; charge unconditionally at the
start of `run_single_stage` and reconcile at the end; or have the pacer be the
single source of truth and derive the ledger from it rather than maintaining a
parallel count. The last is probably right — two counters for one quantity is
what produced this. Not blocking, because the real Gemini quota still enforces
itself with a 429 and the ledger resets at midnight Pacific.

2026-08-10 | **Cohort sourcing representativeness — the claim list can be built
from a sample that contradicts the rate printed above it** | build, second-rail
investigation | Investigated as a possible verdict-word problem and found not to
be one. Age of Empires II (post-refund mean 91.9%, 58% negatively-sourced
claims) and Palworld (91.8%, 62%) were flagged as Buy verdicts whose claim lists
read overwhelmingly negative. **The verdicts are correct and stay as they are:**
reading every claim on both titles shows narrow, specific, often
platform-scoped complaints — AoE2's are substantially about the *macOS* build's
cross-play, Palworld's are keybinding papercuts — none of which contradicts
"most post-refund reviewers recommend this". That is invariant 13's Kenshi case
at larger scale, and a rail loose enough to catch these two also fires on Slay
the Spire, Monster Hunter: World and Disco Elysium. Decision: **no rail**
(owner, 2026-08-10), which also keeps the 2026-08-09 product decision intact —
the verdict word is driven solely by cohort sentiment, never downweighted by
claim content.

What the investigation *did* surface is a real but different defect, in page
coherence rather than in the verdict:

    AoE2, veteran:     80 reviews available, 78.8% recommend
                        9 reviews cited,      0.0% recommend    delta -78.8
    Palworld, mid:     90 reviews available, 74.4% recommend
                        6 reviews cited,      0.0% recommend    delta -74.4

The Split Bar tells a reader that 78.8% of 100-hour players recommend the game,
and the claim list beneath it is built from nine reviews of which none do. Rare:
**6 titles catalog-wide exceed a -40 source delta** against a catalog mean of
-19.8, and 4 of those 6 are Wait titles, so it is not a Buy-band property.

DISTINCT FROM THE 2026-08-08 CLAIM-BALANCE WORK, which measured the same
underlying sourcing skew catalog-wide (mean delta -20.3) and tried to correct it
by rebalancing extraction rule 2. That attempt **failed its own A/B safety gate**
(ARK, -1.1) and was not shipped, by design — the gate was held absolute rather
than relaxed post-hoc. This entry is about the extreme tail of that
distribution and about what the *page* does with it, not about the average.

Two directions, neither started:
  (a) Extraction-side: make cited samples representative of their cohort. Same
      category as the attempt that already failed once - approach with caution,
      and re-read the RESULTS.md write-up of that failure before spending
      quota on it.
  (b) Page-level disclosure: flag a cohort whose cited sample is thin or whose
      cited rate diverges sharply from its pool rate, so the reader can see the
      provenance rather than being left to reconcile two numbers that do not
      agree. Untried, no gate has rejected it, and it treats the honest problem
      (what we show) rather than the hard one (what the model reaches for). The
      more promising of the two.

Deferred deliberately: measured, understood, and not urgent. Nothing in the
pipeline or the site was changed by this investigation.

2026-08-10 | **`select_publishable.py` defaults to the local `verdicts` ref,
which is stale on any dev machine** | build, verdicts-branch pruning | The
script's `--from` defaults to `verdicts` — the *local* branch, i.e. whatever
that machine last fetched. In CI this is harmless (fresh clone, explicit
`git fetch origin verdicts:verdicts` immediately before). Locally it is a
footgun: on the machine this was found on, the local ref sat at 131 files
against origin's 133, and worse, `git fetch origin verdicts:verdicts` **fails
outright** because an abandoned worktree at `/private/tmp/vw2` has that branch
checked out — so the ref cannot even be refreshed without noticing the worktree
first. Any local invocation therefore reports a publish decision derived from a
stale view, and the failure is silent: the output looks exactly like a correct
run. `prune_verdicts.py` sidesteps it by defaulting to `origin/verdicts` and
refusing any ref that is not remote-tracking, but the underlying default is
unchanged and the next person to run the publisher by hand inherits it. Fix is
small — default to `origin/verdicts`, fetch first, refuse a non-remote ref, same
as the pruner — but it touches the nightly publish path, which is the one script
whose failure mode is silent data loss, so it gets its own scoped change with
its own test rather than riding along with cleanup work. Also worth clearing the
two abandoned worktrees (`git worktree prune`, plus the `verdicts-migrate`
branch) while in there.

2026-08-11 | **`generate-verdict.yml`'s fetch fallback can branch from the wrong
base** | build, live generation | The commit-to-branch step runs
`git fetch origin verdicts:verdicts 2>/dev/null || git branch verdicts`. This is
**not** the publish-path bug fixed the same day: that one swallowed a fetch
failure into a false success, whereas this fallback does something deliberate —
it creates the branch when it genuinely does not exist yet, which is a real
first-run state. The hazard is narrower. `git branch verdicts` with no start
point branches from **current HEAD**, which in that job is main's code plus the
freshly generated verdict. So if the fetch ever failed on a repo where
`verdicts` *does* exist — a transient network error, a partial clone, a
ref-lock — the step would build its commit on main rather than on the branch,
and then `git push origin verdicts` would try to replace the branch's history
with main's. Almost certainly rejected as a non-fast-forward, and the step's
`|| (sleep 5 && git pull --rebase ...)` would then rebase onto the real branch,
which is probably why this has never been seen. "Probably caught downstream" is
not a guard, though, and the failure would be a live-generated verdict lost
after the quota was already spent on it. Fix is small — drop the `||` fallback
and create the branch explicitly from `origin/main` only when `ls-remote` says
it is absent, the same probe-before-acting shape `select_publishable.py` now
uses — but it touches the live-generation commit step, so it gets its own scoped
change rather than riding along with a publish-path fix.

> **2026-08-11, reproduced — the "probably rejected" reasoning above was wrong,
> and the bug was live. FIXED.** Staged in throwaway repos rather than argued
> about. The push is **accepted**: `git pull --rebase` replays main's commits on
> top of `origin/verdicts`, which makes the result a fast-forward, so the push
> has nothing to object to and main's files land on the artifact branch
> silently. The rejection only happens when the two sides touch the same appid,
> and there the rebase conflicts instead — loud, but the verdict is lost after
> its quota was spent. Worse, **this repo had just moved into the silent
> regime**: after the same day's prune the branch held zero verdict files, so
> replaying main's commits would conflict with nothing and would have quietly
> copied all 134 verdicts back onto the branch, undoing the prune.
>
> Fixed by probing with `git ls-remote --exit-code --heads` before acting, so
> the fallback is reachable only when the branch is confirmed absent, and by
> dropping `|| true` from the rebase. That second change **broke the first-run
> path** — there is nothing to pull from when the branch does not exist yet, and
> `|| true` had been hiding that too — so the pull is now guarded on
> `BRANCH_EXISTS`. Caught by the absent-branch fixture, not by reading it.
>
> The lesson worth keeping: "almost certainly rejected" was a mechanism I had
> not tested, written down as if it were one I had.

2026-08-11 | **`test_ledger_charge_is_atomic` cannot tell a crashed child from a
lost update** | build, test integrity | The test spawns 12 subprocesses that each
`live_quota.charge(1, ledger="batch")` and asserts the ledger reads 12. It calls
`pr.wait(timeout=90)` on each and **never checks their return codes**. So a child
that died before charging — an import error, an OOM, a transient under load —
produces the identical output to a genuinely lost update under the lock:
`12 concurrent charges of 1 all land   11`. Those two have opposite meanings. One
is a flaky test; the other is the ledger's atomicity guard being broken, which is
the exact defect the test was written for after a verification run spent 28
requests and recorded 17.

Observed twice on 2026-08-11, both times while the machine was busy running other
subprocess-heavy work, and green on every deliberate re-run afterwards: 12/12 on
an isolated stress loop and 5/5 on the full suite. That pattern *suggests* dying
children rather than a lock failure — but suggesting is all it can do, because
the test does not record which happened.

**Fix:** collect each child's return code and assert all 12 are 0 before
asserting the total, so a crash reports as a crash. Consider also capturing
stderr from any non-zero child, since the point is to know *why* it died.

**Standing rule until this is fixed:** a flake on this test is **unverified**,
not "probably fine". Do not treat the passing runs as proof of atomicity — the
green runs and the red ones are equally uninformative about the lock while the
two failure modes remain indistinguishable. This is the same class as the
break-then-confirm harness that read a non-compiling mutation as "no test caught
it": a test whose failure output does not identify the failure is not yet a test.

---

*This file is a case-study artifact. What got deferred, and the reasoning for
each, is evidence of prioritisation under constraint — link it from the case
study's decision section.*
