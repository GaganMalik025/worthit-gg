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

2026-08-20 | **Two one-off audit rounds read fewer distinct reviews than the 20
slots they present, and nothing had ever checked them** | build, running
`check_sample_overlap.py` over every audit file rather than only the batch
nights | `evals/audit-4.4-hades-hollowknight.md` presents 20 citation slots and
audits **18** distinct reviews (`229019339` and `229669874` each appear twice);
`evals/audit-4.4-live.md` presents 20 and audits **19** (`230859797` twice). The
two rounds also **share 2 reviews** with each other. Counted directly from the
files, not restated from the checker's output.
**Not tonight's rounds, and not any batch night.** Scoped to the batch-night
files the record actually claims — `evals/audit-4.4-2026-*.md`, all eight
including tonight — the checker exits **0**: distinct within each round,
independent across every pair. So the "20/20 distinct and independent" claims in
RESULTS.md are sound as written. These two files are one-off audits from
2026-08-07 (the live-generated pair) and 2026-08-10 (Hades and Hollow Knight),
unmodified since, and they surfaced only because tonight's invocation globbed
`audit-4.4-*.md` instead of the dated subset.
**Why it is worth recording rather than shrugging at:** QR-4 is the launch gate,
and a manual audit is the half of it a human performs. A round that says "20
citations read" and contains 18 distinct ones overstates its own coverage by
10% — small in size, but the number is the entire evidentiary claim, and the
same generator produced every batch night's sample. The batch rounds being clean
today is a fact about their draws, not proof the generator cannot repeat: what
distinguishes them is unexamined, and a with-replacement draw that has not yet
collided looks identical to a without-replacement one. The 08-10 round is also
the one cited in RESULTS.md as the first audit of Hades and Hollow Knight.
**Not fixed**, and the honest options differ in kind: re-audit the two rounds
against fresh draws (costs developer reading time, changes a historical record
that is otherwise accurate about what was read), correct the two files' headline
counts to 18 and 19 in place (cheapest, but edits an audit record after the
fact), add the de-duplication guarantee to `make_audit_sample.py` and leave
history alone (right for the future, silent about the past), or wire
`check_sample_overlap.py` over the full glob into the post-batch sequence so a
repeat cannot go unnoticed again. The last two are complementary and are what a
fix should probably be; none of it belongs in a batch commit. Whether
`make_audit_sample.py` samples with replacement was NOT determined here — that
is the question to open with, and it is a code read rather than a guess.
Related: [[verify-the-verifier]].

> **2026-08-21, the open question is ANSWERED by the code read it asked for:
> `make_audit_sample.py` does NOT sample with replacement, and has not since
> `4d3f3c0` (2026-08-14).** Section B builds its pool one entry per REVIEW behind
> a `seen` set of `recommendationid`, dedup running before the shuffle, and draws
> with `pool[b].pop()`, which removes the entry. Both halves are needed and both
> are there, so a review cannot be drawn twice within a round.
> **The fix was made for exactly this defect, on the round that exhibited it.**
> The comment above the pool names the case: 2026-08-14 drew `196900480` (Trove)
> at both #4 and #16, auditing 19 distinct reviews in 20 slots. `git log -L`
> puts the `seen` set in `4d3f3c0`, the 08-14 batch commit itself — and the
> committed `evals/audit-4.4-2026-08-14.md` contains **no** occurrence of
> `196900480`, so that round was regenerated after the fix before it was
> committed. The 08-14 file on disk is a post-fix sample.
> **So the batch rounds are clean by construction, not by luck**, which is the
> half the 08-20 entry could not distinguish and deliberately refused to assume:
> it wrote that "a with-replacement draw that has not yet collided looks
> identical to a without-replacement one", and that is the ambiguity now removed.
> The two one-off rounds it found — `audit-4.4-live.md` (2026-08-07) and
> `audit-4.4-hades-hollowknight.md` (2026-08-10) — **both predate `4d3f3c0`**,
> which is the whole reason they carry duplicates and no dated round does.
> **What this does NOT close.** Those two files still overstate their own
> coverage (20 slots, 18 and 19 distinct reviews) and are unchanged; the four
> repair options in the entry above are still the options, and the choice is
> still the owner's. Nor does it make cross-round independence a guarantee —
> that comes from each round scoping to one night's `new_ids`, which is a
> property of the inputs rather than of the dedup. Tonight's round was checked
> rather than assumed: `evals/check_sample_overlap.py` over all nine dated files,
> **36 pairwise comparisons, distinct within and independent across, `rc=0`**
> (`evals/sample-overlap-2026-08-21.txt`).

2026-08-20 | **`run_batch.py`'s exit code is never printed in its own output, so
two RESULTS.md entries recorded an exit status that was inferred from a clean
summary block rather than observed** | build, 2026-08-20 batch night | Tonight's
run returned **1**, which is CORRECT: `run_batch.py:323` is
`sys.exit(1 if any(d["outcome"] == "stage_failed" for d in done) else 0)`, and A
Way Out ended `stage_failed`. That line is unchanged since `0054991`
(2026-08-01, verified with `git log -L 323,323`), and both 08-18 (1 stage
failure) and 08-19 (2 stage failures) also ended with stage failures — so both
nights must have returned 1 as well. Both RESULTS.md entries say the run ended
"with a real summary block and **exit 0**".
**Neither night's committed log contains an exit code at all.** Checked rather
than assumed: `grep -n 'rc=\|EXIT\|exit'` over `evals/batch-2026-08-18.txt` and
`evals/batch-2026-08-19.txt` returns nothing, and both files end at the
`batch budget : N of 400 left` line. `run_batch.py` prints its summary and then
calls `sys.exit()` without ever emitting the value, so the log is silent on the
one number those entries asserted. The claim came from the summary block looking
clean.
**Same failure class as the 2026-08-16 INCIDENT, and milder in degree — the
distinction matters and is not a softening.** There, a QR-4 PASS was fabricated
for a run that never happened. Here the batches genuinely ran, the summary
blocks are real, and every other figure in both entries (calls, titles, cost per
title, the three-way ledger reconciliation) was derived from files on disk and
is unaffected. What was assumed is exactly one field, and it was assumed because
the observable — a clean summary — genuinely does correlate with success on most
nights. That is what makes it the more insidious shape: an inference that is
usually right, drawn from real evidence, sitting in the same sentence as figures
that were properly measured, in a file whose whole purpose is to be citable.
**Not fixed retroactively, because it cannot be.** Those two processes are gone
and their exit statuses were never written anywhere — no wrapper, no CI record,
no shell history that captured `$?`. The true values are unrecoverable, so the
honest repair is a correction appended to each entry saying the figure was
inferred and is now unknown, which is what was done rather than editing the
original claims (RESULTS.md is append-only, and the same discipline every other
correction in that file uses). Any "it must have been 1" written into those rows
would be a second inference dressed as a fix.
**Fixed going forward** in `pipeline/run_batch_logged.sh`: the batch is started
through a wrapper that sets `pipefail`, takes `PIPESTATUS[0]`, and writes
`EXIT_RC=` into the batch log itself, so the code is in the artifact rather than
in a session transcript. CLAUDE.md's batch-night section now names it as the
invocation. **The trap it exists for was measured, not argued** — in this repo's
shell (zsh 5.9), `( exit 7 ) | tee /dev/null` records `rc=7` under `pipefail`
and `rc=0` without it, so the naive pipe silently manufactures exactly the "exit
0" being corrected here. Mutation-proved 9/9 by
`evals/verify_batch_rc_capture.sh` (raw output
`evals/batch-rc-capture-2026-08-20.txt`), which drives the real wrapper file
byte-for-byte inside a throwaway repo with a stub interpreter, and whose case 2
is a **control that reproduces the bug** — the pre-fix shape recording 0 for a
batch that exited 3. Without that control a green run would prove nothing, since
a wrapper that always reported failure would pass the other cases. Case 3 pins
the opposite direction (a clean batch still records 0) and case 4 pins that a
second same-day run appends rather than destroying the first run's evidence.
**What this does NOT fix:** tonight's own log, `evals/batch-2026-08-20.txt`, was
produced by the pre-wrapper invocation, so its `EXIT_RC=1` was captured in the
session's task output rather than in the file. The wrapper starts paying from
the next night. Related: [[verify-the-verifier]].

2026-08-20 | **The digit-in-prose guard is teaching the model to spell numbers
out, and one of those spellings shipped** | build, the Insurgency retry-cache fix
| Insurgency's published verdict carries
`not_for_you_if: "you run Windows eleven with startup crashes"`. Invariant 13's
digit rule rejected "Windows 11" on the frozen attempt 1 (`digit_in_prose:
not_for_you_if[0]`); given a genuinely fresh attempt, the model kept the fact and
spelled the numeral out instead. **The guard did its job and the output is
worse** — no reader writes "Windows eleven", and the failure is invisible to the
guard by construction, since the whole check is for digits. Not a regression
introduced by the cache fix: the fix is only what made a fresh attempt possible,
and the same pressure existed on every title whose real story involves a version
number. **Why it is worth recording rather than shrugging at:** the guard exists
to stop a *count* being stated as prevalence (invariant 11's territory), and an
OS version is not a count. This is the same false-positive class the 08-18 entry
identified in "persistent", one step further along — there the guard blocked a
true statement, here it deformed one into shipping. **Scope measured rather than
guessed: exactly 1 occurrence across all 432 published verdicts.** Swept every
prose field that renders — tagline, `for_you_if`, `not_for_you_if` and every
cohort summary — for spelled-out numerals (`eleven`, `ten`, `twelve`, `sixty`,
`ninety`, `seven`, `eight`, `nine`); this is the only hit. So it is a real defect
with a demonstrably tiny blast radius today, which is an argument for deciding it
calmly, not for treating it as theoretical: the pressure is structural and the
catalog keeps growing. **Not fixed
because the honest options differ in kind:** allow digits when adjacent to a
known product/OS token (narrow, needs a list nobody maintains), move the check to
reject only digits in *quantity* contexts (right in principle, and a rewrite of a
guard that currently has one unambiguous rule), or leave the guard and add
"spell numerals out" to the banned-phrasing list so the model must drop the
detail rather than disguise it. The last is smallest and loses information on
purpose, which is a product call. One observed instance so far.

> **2026-08-21, RESOLVED — narrow allowlist taken, and the shipped string is
> repaired.** Invariant 13's rule was a bare `\d` with no categories, so the
> prevalence split could not reach it; it got its own fix.
> `synthesize.PLATFORM_TOKEN` permits a digit bound into a platform or version
> name (Windows 11, DirectX 12, RTX 4090, PS5, Core i7) and `has_bare_digit()`
> rejects every other digit. Quantities are untouched — "20 hours", "6 players",
> "3 of 5" and a claim id in prose all still fail, which is the half of
> invariant 13 that carries the weight.
>
> **The prompt moved with the guard, and that is the actual fix.** Rule 2 used to
> end "Any digit in prose is rejected", which is what made the model spell the
> numeral out; it now teaches the exception by example and names the wrong
> answer: WRONG "you run Windows eleven", RIGHT "you run Windows 11". This is the
> `banned_words()` lesson applied to the other guard — a model told to avoid a
> token spells around it rather than dropping the fact, and a prompt that has
> fallen behind its guard is how that happens.
>
> **222880 regenerated for 1 call** (ledger 397 → 398), `--force-lite`, raw output
> `evals/insurgency-verdict-2026-08-21.txt`. The published `not_for_you_if` now
> reads **"you run Windows 11 with BattlEye issues"**. QR-4 on the new verdict:
> 53 citations, PASS, `rc=0` (`evals/qr4-2026-08-21-insurgency.txt`). Repaired by
> regeneration, not by editing a published artifact.
>
> **Re-measured across all 514 rather than assumed: 0 evasions remain.** The
> sweep for spelled-out numerals in rendering prose returns 9 occurrences, all
> ordinary English — "two players", "one-versus-one", "one-shot deaths", "one
> sitting", "one-hit-kill", "turn-one dominance". None is a numeral in disguise,
> and writing them as digits would be worse prose and would be rejected as
> quantities anyway. The one real instance this entry recorded is gone.

2026-08-18 | **Insurgency's verdict stage is deadlocked by its own response
cache — three rejected answers replayed nightly, forever, at zero cost** | build,
third consecutive failure of `222880` | Diagnosed at **zero Gemini spend**, by
running the stage standalone; raw output committed at
`evals/insurgency-verdict-2026-08-18.txt`. The synthesis retry loop burns all
three attempts against guard rejections, and **every one of the three is served
from cache**:

    [cached] attempt 0 -> ! prevalence:tagline:persistent
    [cached] attempt 1 -> ! digit_in_prose:not_for_you_if[0]
    [cached] attempt 2 -> ! prevalence:summary[mid]:persistent
    FAILED after 3 attempts - no verdict written for 222880

The three cached responses are `data/cache/extract/222880/synthesis_*.json`, all
stamped **2026-08-16 14:53 and untouched since** — so 08-17 and 08-18 sent no
request at all and cannot have produced a different answer. That is exactly why
the failure costs 0 calls and 1.7s, and why it is not transient: the 08-16 entry
guessed "probably transient, same shape as V Rising on 08-12", and it is not.
The offending strings, read out of the cache files:

| attempt | field | text | guard |
|---|---|---|---|
| 0 | `tagline` | "Lethal tactical combat meets **persistent** startup crashes on modern systems." | prevalence |
| 1 | `not_for_you_if[0]` | "you use Windows **11** with BattlEye" | digit in prose |
| 2 | `summary[mid]` | "…noting **persistent** anti cheat compatibility problems." | prevalence |

**`synthesize.py:805-812` already anticipated this hazard and fixed the wrong
half of it.** That comment puts the attempt number in the cache key precisely so
a retry that fails the SAME way cannot replay its predecessor's answer — the
Stardew Valley case it names. Insurgency fails a *different* way each attempt, so
the retry prompts genuinely differ, each gets its own key, and the loop writes
**three** distinct poisoned entries instead of one. The existing fix makes the
attempts distinct; nothing makes them expire. A cache that is right for
resumability is wrong for a retry loop whose whole purpose is to get a different
answer.

**Why the guards fire here is not model sloppiness, and that is the interesting
part.** This title's dominant complaint IS a long-running BattlEye failure on
Windows 11. "Persistent" is banned as a prevalence word (invariant 11) but here
describes a *bug's* persistence, not how many players hit it; "Windows 11" trips
the digit-in-prose rule (invariant 13) as an OS name, not a count. Both guards
are behaving as written and both are catching a false positive that the subject
matter pulls the model toward on every attempt. A title whose real story sits on
top of two guards will fail three times in a row reliably — which is the
condition that mints the poisoned cache.

**Third mechanism in the same family, and the family is now the finding.**
`stage_failed` is not in `run_batch`'s TERMINAL set, so this re-enters the queue
every night at zero cost — the 2026-08-16 Hotline Miami entry's exact shape
(empty cohort), reached the 2026-08-12 entry's way (no usable record), by a
third route (cached rejections). Three distinct causes, one behaviour: a title
that can never resolve, retried nightly, padding the pending count. Hotline Miami
was resolved by a scoped allowlist and this one will not be, because the cause is
not the same and an allowlist is not the shape of the fix.

**Not fixed — the honest options are a spend decision, not a bug fix**, and they
differ in kind. (a) `synthesize.py --force` on this one title bypasses the cache
and spends ~3 calls for a fresh set of attempts; cheapest, unblocks tonight, and
fixes nothing structural — the next such title mints its own deadlock. (b) Do not
cache a REJECTED response at all, which is arguably what the cache means, but
changes the write path every title's synthesis passes through on a batch night.
(c) Retry-loop bypasses the cache after attempt 0, keeping the cache for
resumability and denying it to the retries — closest to the intent of the
805-812 comment. (d) Make a rejection-exhausted `stage_failed` terminal, which
buries the question the way the Hotline Miami entry warned against. **(c) looks
right and (a) is what tonight would want**, but both spend quota to verify, and
neither should ride along with a batch commit. Related: [[verify-the-verifier]].

> **2026-08-20, RESOLVED — option (c) taken, and Insurgency published on the
> first real run in four days.** The retry loop no longer reads the cache;
> attempt 0 still does. One line in `synthesize.py`:
>
>     -        if cpath.exists() and not args.force:
>     +        if cpath.exists() and not args.force and attempt == 0:
>
> Writes are unchanged on every attempt, so standalone diagnostics — the way
> this entry was written in the first place — still work. The comment above the
> line now states the distinction it got wrong: keying on the attempt number
> stopped a retry replaying a *different* attempt's answer within one run, and
> did nothing about a later run where every prompt is byte-identical and each
> attempt replays *its own* prior rejection.
>
> **The real run, `evals/insurgency-verdict-2026-08-20.txt`, 2 calls:**
>
>     [cached] attempt 0
>     attempt 0 rejected:  ! prevalence:tagline:persistent
>     attempt 1 rejected:  ! prevalence:summary[veteran]:persistent
>     -> site/public/verdicts/222880.json  [Wait] Tactical shooter depth marred
>        by startup crashes and anti-cheat hurdles.
>
> Attempt 0 replayed the 2026-08-16 cached rejection at 0 calls, exactly as
> designed — the cache still pays for itself. Attempt 1 was the **first real
> synthesis request this title has sent since 2026-08-16** and failed on a
> *different* cohort than any cached attempt (`summary[veteran]`, where the
> frozen set had `summary[mid]`), which is itself the proof the loop is no
> longer replaying. Attempt 2 passed. QR-4 on the new verdict: **53 citations,
> PASS, rc=0**. Ledger 390 → 392, so the whole fix cost **2 calls**.
>
> **Mutation-proved 5/5** (`evals/mutate_retry_cache.py`, logs
> `evals/mutation-logs/m01..m03`, alongside the 24 kept from the earlier
> campaigns): control green, the pre-fix line puts
> the suite red, and the failure NAMES the deadlock rather than merely failing —
> `attempt 1 is NOT served from cache` and `second run still sends a request for
> each retry`. `synthesize.py` restored byte-identical (sha `8fa530dafbd3` both
> sides) and green again. The new test drives the real loop twice over committed
> seed-game fixtures, so run 2 *is* the next night: under the old line it sends 0
> requests, which is the deadlock itself.
>
> **What this does NOT fix, stated so nobody reads it as more than it is.**
> `stage_failed` is still not TERMINAL, so the third-mechanism finding above —
> a title that can never resolve retrying nightly at zero cost — is untouched,
> and the 2026-08-19 zero-cohort entry is a live instance of it. The two guards
> also still fire on this title's subject matter every attempt; the fix buys
> fresh attempts, not agreement.
>
> **One thing surfaced by the fresh output, worth its own note:** the published
> `not_for_you_if` reads **"you run Windows eleven with startup crashes"**. The
> model spelled the OS version out to get past the digit-in-prose guard
> (invariant 13). It is guard-compliant and it is not prose anyone would write.
> Recorded below rather than fixed here.

2026-08-17 | **`n_note` is a post-filter count wearing a user-facing label, one
wire-up away from breaking invariant 13** | build, confirming Hotline Miami's
muted veteran cohort | Every muted cohort ships a preformatted string like
`"n=0 - too few reviews to call"` in `n_note`, and that number is the count of
reviews SURVIVING THE FILTER, not the pool figure sitting beside it in the same
object. Measured across all 346 verdicts: **135 muted cohorts, 132 whose `n_note`
disagrees with their own `pool_n`.** The three that agree
(Firewatch mid 15, Firewatch veteran 2, Dispatch veteran 3) agree only by
coincidence — nothing dropped in the filter there. The gap is not marginal at the
tail: **Path of Exile's refund_window is `pool_n` 77 against `n=18`**, and the
title that surfaced this, Hotline Miami's veteran cohort, is `pool_n` 1 against
`n=0`. No unmuted cohort carries an `n_note` at all, so the field exists solely
for the muted case, which is exactly the case invariant 12 sends to invariant 13
for its label.
**Nothing renders it today, and that is the only reason this is a note.**
`VerdictPage.tsx:139` builds the muted label itself from the pool figure —
``${b.pool_n} reviews · too few to call`` — so what a reader actually sees on
Hotline Miami is "1 reviews · too few to call", the pool number, correctly.
`n_note` is carried into the view model at `site/lib/verdict.ts:159` and then
read by no component; a grep across `site/components`, `site/app` and `site/lib`
finds it only in the type, that one mapping line, and two contract-test
references. It is a pipeline diagnostic, which invariant 13 explicitly permits.
**Why it is worth recording rather than shrugging at:** every other diagnostic
invariant 13 tolerates is a bare number that a renderer would have to compose
into a sentence deliberately. This one arrives pre-composed in the exact register
of the UI — `n=` prefix, em-dashed explanation, ready to drop into a JSX
expression — and it sits in the view model beside the field that should be used.
The cheapest possible mistake, wiring `{c.n_note}` into the muted branch instead
of rebuilding the string, is a silent invariant-13 violation on 132 of 135 muted
cohorts, and the resulting page would look completely plausible: a smaller number
under a "too few reviews" heading reads as correct. The 2026-08-10 sourcing work
guarded its diagnostics with a render-side contract test using sentinel values
for precisely this hazard; `n_note` has no equivalent guard.
**Not fixed** because the honest options are a product call rather than a bug fix,
and they differ in kind: drop the field from the verdict schema (touches every
verdict and the pipeline that writes them), rename it to something no one would
render (`filter_survivors_note` — cheap, but keeps a formatted string nobody
reads), restate it as a bare integer so it cannot be pasted into the UI at all,
or add a sentinel contract test in the shape `cdebb6d` already established and
leave the field alone. The last is the smallest change that closes the actual
hazard, since the hazard is a future edit rather than current output. Cheap and
safe whenever the verdict schema or `VerdictPage`'s muted branch is next open.
Predates tonight's batch and is unrelated to it — Portal, Warframe and Kingdom
Come II all carry it. Related: [[verify-the-verifier]].

> **2026-08-22, RESOLVED — the last option, and deliberately the smallest one:
> the field is unchanged and now guarded.** This entry listed four repairs and
> judged that "add a sentinel contract test in the shape `cdebb6d` already
> established and leave the field alone" was the smallest change that closes the
> actual hazard, "since the hazard is a future edit rather than current output".
> That is what was built. `n_note` is not renamed, not restated as an integer,
> not dropped from the schema, and every value it carries is exactly what it
> carried yesterday.
>
> `site/lib/__tests__/n-note-never-renders.contract.test.tsx` injects
> `n=8675309 - N-NOTE-SENTINEL-DO-NOT-RENDER` into every muted cohort and
> asserts no part of it reaches the markup, plus that the label which DOES render
> is built from `pool_n`.
>
> **The fixture is `219150`, not Kenshi, and that choice is load-bearing.** The
> sourcing guard this copies uses Kenshi, which has **no muted cohort at all** —
> so on that fixture every `not.toContain` here would pass while testing
> nothing. Hotline Miami is committed pipeline output with a genuinely muted
> veteran cohort (`pool_n` 1, `n_note` "n=0"), which is the disagreement this
> entry measured at 132 of 135.
>
> **Mutation-proved 6/6** (`evals/mutate_n_note_render.py`, logs `n00`–`n05`).
> n01 is not an invented perturbation — it is the exact edit this entry predicts,
> `{c.n_note}` wired into the muted branch of the real `VerdictPage.tsx`, and the
> guard is required to fail **by name**: the driver checks for the string
> `no part of n_note reaches the markup` in the output, not merely a red run.
> That distinction was earned during the work: under that mutation the canary and
> the pool-figure assertions also fail, because the label they search for is the
> one being replaced, and either could have turned the suite red while proving
> nothing about whether the diagnostic reached the page.
> n02 and n03 are the vacuity controls — a fixture with nothing muted, and a
> page that renders nothing at all, both of which would satisfy every
> `not.toContain` in the file. `VerdictPage.tsx` and the test restored
> byte-identical, sha verified.
>
> **What this does NOT do:** the underlying disagreement is untouched. `n_note`
> still reports post-filter survivors while `pool_n` sits beside it, and the
> three cohorts where they agree still agree only by coincidence. This closes the
> render hazard, which is what the entry said was worth closing.

2026-08-17 | **40 citations render an hours figure that contradicts the cohort
heading above them** | build, cohort-sourcing measurement | Sweeping every
citation in all 306 verdicts against its cohort's hour range finds **40 of
15,736** sitting exactly on a boundary and reading as outside it: `2.0 hrs`
under `<2h refund window` (28 of them), `20.0 hrs` under the early heading (8),
`100.0 hrs` under mid (4). Not a bucketing error — invariant 1 puts bucketing on
raw MINUTES at ingestion, and the bucket is right; 119 minutes is
`refund_window` and always was. What renders is `hours_at_review` rounded to
one decimal, and 119/60 = 1.983 displays as `2.0`. The rounding is already
baked into `data/filtered/` (Arma 3's `230637493` is stored as
`hours_at_review: 2.0, bucket: refund_window`), so the display value and the
bucketing input have been separate quantities since ingestion. **Why it is
worth recording rather than shrugging at:** the whole citation UI exists to let
a sceptical reader check the receipts, and 0.25% of the time the receipt
appears to disprove the heading it sits under. A reader who notices cannot
distinguish "rounding" from "the segmentation is wrong", and the segmentation
*is* the product thesis. **Not fixed** because the honest options differ in
kind and the choice is a display decision, not a bug fix: floor the display
instead of rounding (`1.9 hrs`, truthful to the bucket, slightly wrong as a
duration), carry a second decimal at the boundary only (`1.98 hrs`, precise and
fussy), or keep minutes alongside hours in the citation record so the UI can
choose. All three touch what renders on every citation on every page, for 40
cases. Cheap and safe whenever the citation row is next open.

> **2026-08-22, RESOLVED — the third option: minutes are carried and the UI
> chooses. 78 boundary cases, now 0.**
>
> **Re-measured first, and the figure grew with the catalog.** This entry counted
> 40 of 15,736 at 306 verdicts. At 514 verdicts it is **78 instances / 59
> distinct of 26,806**, in the same three shapes: `2.0 hrs` under refund_window
> (63), `20.0` under early (9), `100.0` under mid (6). Same rate, more catalog.
>
> **The premise had to be checked before it could be built on, and it was wrong
> in a way that mattered.** `minutes_at_review` did **not** exist upstream:
> `fetch_reviews.py:238` does `round(at_review_min / 60, 1)` and keeps no
> minutes, so raw, filtered, claims and every published verdict had lost them.
> They were nonetheless recoverable **at zero cost and with no re-fetch**,
> because `fetch_reviews` caches every raw Steam page verbatim at
> `data/cache/<appid>/<filter>_<NN>.json` with `playtime_at_review` untouched
> inside. Recovery measured before any file was written: **26,779 of 26,806
> citation instances (99.90%)**, all 78 boundary cases included, and this entry's
> own Arma 3 example (`107410` / `230637493`) recovers as **118 minutes**.
>
> **Re-fetching would have been the wrong repair, not merely a slower one.**
> Steam's corpus moves, cohorts are exhausted at ingestion, and these citations
> reference specific `recommendationid`s. A re-fetch would not have repaired
> these files; it would have invalidated them. `pipeline/backfill_minutes.py`
> therefore reads the page cache and never the network.
>
> **What shipped**, in four places and no more:
> `fetch_reviews.normalize()` carries `minutes_at_review` beside the single
> hours conversion; `synthesize.build_citation()` threads it into the citation
> record; `backfill_minutes.py` fills the existing 514 from cache;
> `site/lib/verdict.ts:citationHours()` derives the displayed figure and is
> called from the one render site (`VerdictPage.tsx:201` — grepped across
> `site/lib`, `site/components` and `site/app`; there is no second).
> The rule: round to one decimal, but if that lands outside the cohort's own
> minute bounds, round toward the interior. 118 renders `1.9`, 5997 renders
> `99.9`.
>
> **Absent minutes are a supported state, not a gap to paper over.** 27
> citations — all in `2073850`, the live-generated title whose runner filesystem
> was discarded — have no cache entry. The key is left absent and
> `citationHours` falls back to rounding hours, which is exactly today's
> behaviour, so those citations and every pre-backfill verdict render unchanged.
> None of the 27 was a boundary case.
>
> **Verified by re-sweep, not by inspection: 78 → 0.** The sweep reimplements
> the display rule in Python rather than calling the renderer's own function,
> because a sweep that asked the renderer whether the renderer was right would
> answer yes either way. Backfill proved additive by `--check`: strip the new key
> and every one of the 514 files is byte-identical to what it was.
>
> **Invariant 1 was amended rather than quietly contradicted.** It read "raw
> minutes must never reach an LLM prompt or the UI", and the citation record puts
> minutes in the UI. It now forbids minutes being **displayed** and keeps the
> LLM-prompt half absolute, with
> `site/lib/__tests__/citation-hours.contract.test.tsx` rendering a sentinel
> minutes value and asserting it never reaches the markup — the prose promise
> replaced by a machine-checked one. A 60× silent error looks like a plausible
> number, which is why it gets a test.

2026-08-16 | **The 2026-08-13 guard-suite flake reproduced in CI, with the
evidence captured this time — it is a TOCTOU race in `model_pacer._locked`, not
a timing-sensitive assertion** | build, CI run 31956075631 on the action-version
bump | `pipeline/model_pacer.py:107` reads

    age = time.time() - lock.stat().st_mtime if lock.exists() else 0

`exists()` and `stat()` are two syscalls against a path another process is
racing to `rmdir()`. When the holder releases in that window, `stat()` raises
`FileNotFoundError`, it propagates out of `_locked`, and the child dies
**before charging**. Captured verbatim from the failing job:

    3 FAILURES:
      all 12 charge processes exited 0 rc=1 ^^^
      FileNotFoundError: [Errno 2] No such file or directory:
        '/tmp/tmpy6bohrk8/q.json.lock'
      12 concurrent charges of 1 all land 11

**`adf26e3` is what made this diagnosable, and it worked exactly as designed.**
The 2026-08-11 entry's whole complaint was that
`test_ledger_charge_is_atomic` could not tell a crashed child from a lost
update, and set a standing rule that a flake on it is UNVERIFIED rather than
"probably fine". Here the exit-code assertion fired first and named the mode:
`all 12 charge processes exited 0` FAILED with `rc=1`, so this is a **crashed
child, not a lost update** — the lock's mutual exclusion is not implicated, and
the atomicity guard itself is not in question. That distinction was
unobtainable before `adf26e3` and is the entire reason this entry can state a
cause rather than list candidates.

It also closes the 2026-08-13 entry's open question. That entry named two
candidates — "a timing-sensitive check under load, or a temp-dir/filesystem
race" — and could not choose between them because the output had gone to
`/dev/null`. It is the second one.

**Not caused by the action bump it surfaced on.** `fff2aa5` changes only
`.github/workflows/ci.yml`; `git diff --stat 2d2f5e4 fff2aa5` touches no Python,
so the suite's code is byte-identical across the failing and passing runs, and
both ran Python 3.12.13. Re-running the identical commit went green, which is
the definition of nondeterministic. The bump is a bystander that happened to
provide the 13th sample.

**Why not fixed here:** the fix is small and obvious in isolation — catch
`FileNotFoundError`/`OSError` around the age probe and treat an vanished lock as
age 0, i.e. retry the `mkdir` — but it is a change to the lock every Gemini
charge in the project passes through, on the night a batch is due, and the
honest way to land it is with a reproduction harness that fails first. That is
buildable: the race needs contention plus a holder releasing mid-probe, which
the existing 12-process fixture already produces at roughly 1-in-13. Do it as
its own change, mutation-proved against the captured traceback above, not as a
ride-along on a version bump. Until then the suite retains a ~7% false-failure
rate in CI, which is itself an argument for doing it soon: a gate that cries
wolf gets ignored. Related: [[verify-the-verifier]].

> **2026-08-22, RESOLVED — fixed exactly as this entry specified, and the
> reproduction it asked for came first.** `pipeline/model_pacer.py`'s probe is
> now one guarded syscall:
>
>     -  age = time.time() - lock.stat().st_mtime if lock.exists() else 0
>     +  try:
>     +      age = time.time() - lock.stat().st_mtime
>     +  except OSError:
>     +      age = 0
>
> `FileNotFoundError` subclasses `OSError`, so one clause covers both forms this
> entry named. **`age = 0` and fall through rather than `continue`**, so the
> `time.time() - start > timeout` check still runs on every pass; the cost is
> the same ~50ms sleep every other contended iteration already pays. 15 lines
> added, 1 removed, all inside `_locked`. Nothing else in the file moved, which
> matters because this is the lock every Gemini charge in the project passes
> through — `live_quota.charge()` uses it at `live_quota.py:397`, which is why
> the captured traceback names `q.json.lock` and not the pacer file.
>
> **THE WINDOW WAS FORCED, NOT WAITED FOR — that is the part this entry got
> right and it deserves restating.** The entry measured the race at ~1-in-13
> under natural contention. A 1-in-13 sample is not a reproduction: the green
> runs prove nothing and the red one arrives without evidence, which is exactly
> how the 2026-08-13 entry lost its own failure. So `Path.stat` is patched, for
> the lock path only, to **actually `rmdir` the directory and then call the real
> `stat`** — the `FileNotFoundError` comes from the OS on a path that genuinely
> is not there, and the interleaving is precisely "the holder released inside the
> probe". The injection is also agnostic to which syscall the code uses, so one
> harness drives both the pre-fix body (after `exists()` returns True) and the
> fixed one.
>
> **Fresh traceback captured, not copied from this entry**, at
> `evals/pacer-toctou-2026-08-22.txt` — `model_pacer.py`, line 107, `in _locked`,
> caret on `lock.stat()`, `FileNotFoundError: [Errno 2] ... q.json.lock`. The
> same shape as the CI capture above, produced on demand rather than waited for.
>
> **Mutation-proved 6/6** (`evals/mutate_pacer_toctou.py`, logs
> `evals/mutation-logs/t01`–`t06`): t01 is the CONTROL and puts the pre-fix probe
> back into the real file to watch it die; t02 acquires instead of raising; t03
> pins that **a genuinely stale lock is still broken** (aged past `LOCK_TIMEOUT`
> with `os.utime` — `age = 0` must not disable stale-breaking, or an unattended
> batch could wedge on a killed holder); t04 pins that the lock still BLOCKS on a
> live holder, so the fix did not turn it into a no-op; t05 runs 12 concurrent
> `live_quota.charge(1)` children and asserts **the ledger reads 12**, not an
> exit code and not a console line. `model_pacer.py` restored byte-identical,
> sha `0130a0cc89fb` both sides.
>
> **One case was deliberately DEMOTED rather than kept.** The first draft had a
> `t05a` control running the charge race against the pre-fix body — hardcoded to
> pass, because the outcome is a ~1-in-13 coin flip. A case that cannot fail is
> the vacuity this whole file exists to prevent, so it is now an unnumbered
> observation that records the sampled figure and asserts nothing. Both runs so
> far sampled 12 of 12 with no deaths, which is what a 1-in-13 event looks like
> and is why t01 rather than t05a is the control that proves the defect.
>
> **Also covered permanently, by owner decision**, in
> `test_a_vanished_lock_is_a_retry_not_a_crash` (`pipeline/test_batch_guards.py`)
> — CI has run `python-guards` on a clean runner since `f9bb6fe`, so this
> executes on every push touching `pipeline/**`, which the driver alone does not.
> Proven able to fail: against the pre-fix probe the suite exits 1 and names the
> mode — `_locked survives the probe (no FileNotFoundError escapes)
> FileNotFoundError(2, 'No such file or directory')`. The two failure modes
> ("died in the probe" and "did not acquire") are reported under separate names,
> because a test whose output does not identify the failure is not yet a test.
>
> **Regression: the full suite run 10×, 0 failures, 279 assertions each.** Once
> would not have been evidence about a race — that is what let this sit open from
> 2026-08-13.
>
> **What this does NOT change.** The lock is still `mkdir`-based with a 120s
> stale-break; no new dependency, no new mechanism. And the 2026-08-11 standing
> rule survives untouched: a future flake on `test_ledger_charge_is_atomic` is
> still **UNVERIFIED** unless its output is kept. This removes one known cause of
> that flake; it does not license reading the next one as "probably this, now
> fixed". Related: [[verify-the-verifier]].

2026-08-16 | **The live path keeps a second, doubled ledger on the runner that
nothing reads** | build, implementing EST_COST reconciliation | The workflow's
`seed the ledger from the dispatch payload` step writes the site's counters into
the runner's `data/live_quota.json` — and `live_used` in that payload ALREADY
includes the `EST_COST = 13` reservation `/api/generate` charged before
dispatching. Then every request the run makes is charged again, +1 at a time, by
`model_pacer._charge_ledger` at the pacer's choke point. So by the end of a live
run that file reads roughly `13 + actual` for a generation that cost `actual`,
which is not a quantity that means anything. **Harmless today, on three separate
counts, which is the only reason this is a note and not a fix:** the file is
gitignored so it is never committed; `run_single_stage` performs no quota check,
so nothing consults it during the run (the five stages just execute); and the
runner's filesystem is discarded when the job ends. The double-count therefore
has no reader and no lifetime. **Why record it anyway:** it is a file named
`live_quota.json` sitting on disk holding a number that looks authoritative and
is not, and the obvious future change — having a stage check its own budget
before spending, or having the runner report its ledger back — would read it as
truth. Whoever does that must reconcile the seeding and the charging first
(seed the pre-reservation figure, or have the pacer not charge on a path whose
reservation is already booked); the two are counting the same spend twice by
construction, not by accident. Same family as the 2026-08-12 two-ledger entry
resolved in `573a1d6`, one level further in: there, two ledgers of one budget
that never reconciled; here, one ledger double-counting one spend because two
mechanisms both book it. Not fixed because nothing reads it, and changing the
seeding or the charge point on the live path touches CLAUDE.md guard 1's
machinery for a number with no consumer — the fix belongs to whoever gives it a
consumer. Related: [[verify-the-verifier]].

2026-08-16 | **A title whose cohort is empty fails forever, and `stage_failed`
retries it every night** | build, investigating Hotline Miami's filter-stage
failure | Reproduced deterministically at zero Gemini cost
(`generate_one.py 219150 --stage filter`): of 400 swept reviews Hotline Miami has
**one** veteran review, the filter drops it as low-information, and the stage
hard-fails — `FAIL: veteran has 0 surviving reviews - the segment page breaks`.
Nothing about that is transient: the same input produces the same failure on
every retry, and `stage_failed` is not in `run_batch`'s TERMINAL set, so this
title re-enters the queue every night forever. It costs 0 calls per attempt, so
it burns no quota — it just never resolves and quietly pads the pending count.
**The real question is which of two rules wins**, and that is a product call,
not a bug fix. Invariant 12 already says a cohort under 20 surviving reviews
does not get claims and renders muted with an explicit `n=` label — a cohort of
zero is the same situation further along, and the muted-section path appears to
handle it. The filter instead treats zero survivors as fatal for the whole
title. If invariant 12's treatment is right, a title like this should publish
with three cohorts and a muted veteran section rather than being unpublishable
because 1 of 400 reviewers passed 100 hours. **Not fixed here** because it
changes what gets published, touches the invariant-12 boundary, and wants the
owner's call — and because the cheap half (making a deterministic
`stage_failed` terminal so it stops being retried) would paper over the
question rather than answer it. Related: [[verify-the-verifier]].

> **2026-08-16, resolved for THIS TITLE ONLY — as a scoped exception, not a rule
> change.** Owner decision: `pipeline/data/zero_cohort_exceptions.txt` is a new
> audited allowlist (same shape as `duplicate_editions.txt`), and `219150` is on
> it. An allowlisted appid mutes an empty cohort the way invariant 12 already
> mutes an under-20 one; every other title keeps today's behaviour, where zero
> survivors still fails the whole title. Verified both directions: with the entry
> present the filter reports `n=0 EXCEPTION: veteran has 0 surviving reviews -
> muted, not a title-level failure` and exits 0; with it commented out the same
> title reports `FAIL: veteran has 0 surviving reviews` and exits 1 — so the
> allowlist, not a weakened default, is what changed.
> **THE GENERAL QUESTION STAYS OPEN.** Whether *every* zero-survivor cohort
> should mute automatically is still undecided and deliberately so; one title is
> decided, nothing else. The exceptions file says the same thing at the point of
> use, and notes that growth past a handful of entries is the signal the general
> question needs answering rather than more exceptions.

> **2026-08-19 — SECOND OCCURRENCE, unallowlisted and deliberately so.** A Way
> Out (`1222700`) failed the filter stage on tonight's batch in exactly this
> shape: of 400 swept reviews it has **2** veteran reviews, the filter drops both
> as low-information, and the stage hard-fails the whole title —
> `FAIL: veteran has 0 surviving reviews - the segment page breaks`. Reproduced
> standalone at **zero Gemini cost** with the ledger unchanged at 390 either
> side; raw output committed at `evals/awayout-filter-2026-08-19.txt`. Same
> cohort as Hotline Miami, one review further along, and the same 0 calls / retry
> every night at `stage_failed`.
> **Not added to the allowlist.** The note above says growth past a handful of
> entries is the signal the general question needs answering rather than more
> exceptions — so adding a second entry the moment a second title appears would
> spend the signal instead of reading it. Two titles in four nights, out of 431
> published, is the first datapoint on the rate that question turns on, and it is
> recorded here rather than absorbed. What is still undecided is unchanged: **not
> whether `1222700` should publish, but whether a zero-survivor cohort should
> mute automatically the way invariant 12 mutes an under-20 one.** Both titles
> now sit behind that one call. Related: [[verify-the-verifier]].

> **2026-08-21, RESOLVED — the general question is answered, and the answer is
> the default rather than a third exception.** Owner decision: a zero-survivor
> cohort MUTES, exactly as invariant 12 already mutes an under-20 one, and does
> not fail the title. `pipeline/filter_reviews.py`'s two identical gates
> (`all(st["kept"] > 0 or st.get("zero_cohort_exception") ...)`) now return True;
> the `FAIL:` report line became an `invariant 12: <cohort> has n=0` line.
>
> **What made the question answerable was the third case, not the count.**
> A Plague Tale: Innocence arrived on the 2026-08-21 batch with veteran `in`=1,
> `kept`=0. Veteran pool shares across the three: Hotline Miami 1 of 400, A Way
> Out 2 of 400, A Plague Tale 1 of 1,203 — all short, finite,
> single-playthrough games. Invariant 2 puts `veteran` at 6000+ minutes, so for a
> game that ends at ten hours the cohort is **undefined by construction**, not
> thin by sampling accident. That is what this entry could not see with one
> title, and it is why the answer is not "mute at zero" as a mechanical rule so
> much as "a fixed 100-hour bucket is the wrong instrument for a finite game" —
> muting is the smallest honest response to that, and the only one that does not
> touch invariant 2 and invalidate every eval result.
>
> **Nothing else in the pipeline needed changing, which is the strongest evidence
> the muted path was always the right one.** `"muted": kept < MIN_COHORT` already
> covered zero, `extract_claims.py` already skipped it, `post_refund_mean()`
> already excluded muted cohorts, and `VerdictPage.tsx` already rendered the pool
> figure. The 2026-08-16 entry guessed "the muted-section path appears to handle
> it"; that is now checked rather than guessed — Hotline Miami has been publishing
> in exactly this shape since 08-16 (`veteran muted=true, pool_n=1, 0 claims`,
> rendering "1 reviews · too few to call").
>
> **Both blocked titles verified publishable at ZERO Gemini cost**, ledger
> unchanged at 397 either side: `generate_one.py 1222700 --stage filter` and
> `752590 --stage filter` both now exit 0 and report
> `invariant 12: veteran has n=0 - renders muted, carries no claims`. A Way Out
> also mutes `mid` at n=12, which the under-20 rule already covered. Neither was
> force-published tonight; both publish on the next batch night.
>
> **Mutation-proved** (`evals/mutate_guard_split_2026-08-21.py`, g09/g09b/g10):
> the old gate put back into the real file makes a fabricated zero-survivor title
> fail with `zero survivors`, the file restores byte-identical by sha, and the
> new gate publishes the same fixture with the cohort muted. The control is the
> load-bearing half — a filter that published everything would pass g10 alone.
>
> **`zero_cohort_exceptions.txt` is superseded and decides nothing.** It is kept,
> annotated at the top, with `219150` still in it: the record of how this was
> decided one audited title at a time. New titles need no entry. Its loader still
> runs so the historical note prints.

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

> **2026-08-13, campaign result — did not recur.** 40 runs under the same load
> the flake appeared under (`vitest` + `tsc --noEmit` concurrent), every run's
> stdout/stderr to a real file and its exit code recorded: **40/40 rc=0, zero
> failure logs**. The 40 are only worth something because the harness was proven
> able to fail: removing the lock from `live_quota.charge()` and pushing it
> through the identical campaign body recorded `rc=1`, kept the log, and named
> it — `12 concurrent charges of 1 all land 1 (all children exited 0, so this is
> a LOST UPDATE, not a crash)`. `live_quota.py` restored byte-identical after.
> **The original flake's cause remains unknown and stays UNVERIFIED** per the
> 2026-08-11 standing rule below: its output was discarded, and later green runs
> are not evidence about what failed. What has changed is that rule's premise —
> it was written for a test that "does not record which happened", and `adf26e3`
> fixed exactly that, which is why the mutation probe could tell the two modes
> apart at all. Unblocks batch nights; does not close this entry.

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

> **2026-08-17, RESOLVED — and the resolution is stronger than this entry
> anticipated.** The entry assumed the fix was *visibility*: record the project
> somewhere the repo can read, so a collision becomes detectable. The Console
> check the owner ran removes the collision instead. The project's display name
> is **"Review Summariser"** — an earlier working name for THIS project, not a
> second project sharing the key — and nothing else bills to it. So the hazard
> the entry described, "other work on the account drawing from the same 500/day
> pool with no local signal", does not exist to be detected: the project is
> single-purpose, and the 500/day Flash-Lite and 20/day Flash ceilings in
> `live_quota.py` are WorthIt.gg's alone. A batch night plans against the whole
> 500 without an invisible competitor.
> **Recorded in both places the entry named:** a comment beside the
> `DAILY_LIMIT`/`FLASH_DAILY_LIMIT` constants, and a new `.env.example` — which
> `.gitignore:4` had already carved an exception for (`!.env.example`) and which
> had never actually been written, so the key setup, the `AQ.`
> service-account trap and the project note now all live in one committed file
> instead of in session transcripts.
> **One honest limit on what was verified.** What the owner confirmed is the
> console DISPLAY NAME, not the project ID. A display name is mutable and not
> unique, so it identifies the project well enough for a human to recognise it
> in Console and cannot be used as a machine-checkable key — the entry's
> preferred `GOOGLE_CLOUD_PROJECT` line would be that, and is still not
> present. If the two ever disagree, Console is right and the committed note is
> stale. That is a weaker artifact than an ID and a stronger outcome than the
> entry asked for, and both halves are worth keeping straight.

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

> **2026-08-16, RESOLVED — both halves landed together** (`f9bb6fe`, developed on
> `ci/python-guards`). Trigger gains `pipeline/**` and `requirements.txt`; a new
> `python-guards` job builds a real `.venv` at the repo root, because the suite
> hardcodes `PY = <repo>/.venv/bin/python` and spawns subprocesses through it.
> Ran to completion on a clean runner: 236 assertions, `all guard tests passed`,
> python 3.12.13 — answering the "does it pass on a clean runner" question this
> entry ended on.
> **Proven able to fail, not just to pass.** A lock-removal mutation was pushed
> to the branch and CI caught it, verbatim from the job log:
> `12 concurrent charges of 1 all land 2 (all children exited 0, so this is a
> LOST UPDATE, not a crash)` — so the `adf26e3` crash-vs-lost-update diagnostic
> works in the CI environment too. Reverted, green again. The mutation/revert
> pair was deliberately kept out of main's history; this note is the record.
> **Accepted side effect:** path filters are workflow-level, so the site suite
> now also runs on pipeline-only changes. Not split with `dorny/paths-filter` —
> the quota-mirror contract test spans `site/lib/quota.ts` and
> `pipeline/live_quota.py`, so a pipeline change genuinely can break the site
> suite, and the drift that motivated those paths is exactly that pair.

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

> **2026-08-17, RESOLVED in `36aad66` — exactly the treatment this entry
> specified.** `stderr=PIPE`, all five children's `(rc, stdout, stderr)`
> collected before anything is parsed, exit codes asserted first, then a
> separate named check for a child that exits 0 but prints nothing parsable
> (a third cause this entry did not enumerate), and only then the behavioural
> asserts. Those behavioural checks still REPORT on a bad run rather than being
> skipped — an unreported check reads as a pass in the final tally.
> **The bar was never redness, and the campaign was built accordingly.** This
> entry was careful that the test "already cannot pass silently", so a mutation
> merely turning the suite red would prove nothing. `evals/mutate_pacer_diagnosis.py`
> therefore asserts on the OUTPUT TEXT and carries a pre-fix control, 3/3
> CAUGHT+NAMED:
>
>     p01  child exits 3, current test  -> "all 5 pacer processes exited 0 rc=3"
>                                          + 3 more named checks, run continues
>     p02  same child, PRE-FIX body     -> json.decoder.JSONDecodeError, aborts
>     p03  child writes stderr, exits 4 -> "rc=4 PACER-CHILD-DIED-HERE"
>
> p03 exists because p01's child dies silently: p01 proves the check fires but
> leaves the stderr-capture branch untested, which would have made "capture
> stderr" an untested line shipped under a passing campaign.
> **Incidental finding from the p02 control, worth keeping.** The old shape did
> not merely misname the failure — it aborted inside
> `with tempfile.TemporaryDirectory()`, tearing the directory down while the
> other four children were still running, so they died in `os.mkdir` on a
> deleted parent: `FileNotFoundError` on the `.lock` path at
> `model_pacer.py:104`. One dead child therefore produced TWO misleading
> tracebacks stacked on each other. **This is not the TOCTOU race** of the
> 2026-08-16 entry, and the difference is checkable rather than argued: that one
> is line 107, `lock.stat()` after `lock.exists()` inside
> `except FileExistsError`, under contention; this is line 104, `lock.mkdir()`,
> with the parent directory removed by the test's own cleanup. It appears only
> in the pre-fix control and never in the fixed test, which waits for all five
> children before touching anything. The line-107 race remains open and
> untouched.

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

> **2026-08-16, RESOLVED — and deliberately NARROWER than this entry framed it.**
> The fix is a read-only pre-flight reconciliation, not the "one ledger, one
> writer" sync described above. `live_quota.fetch_remote_live_used()` shells out
> to `gh variable get LIVE_QUOTA` **once at batch startup**,
> `reconcile_live_used()` folds it in as `max(local, remote)`, and
> **`sync_live_used()` PERSISTS that figure to the local ledger through the
> locked path before any worker starts** — that last function is the one that
> actually closes the gap; the first two alone do not. The manual "check the
> variable before a night" mitigation is now the code path.
>
> **The first cut reconciled in memory only, and that was a real bug.**
> `run_batch`'s per-title stop calls `can_batch(live_quota.load(), ...)`, a fresh
> read of the file on every iteration, so a merged-but-unsaved figure reached the
> startup banner and **nothing else** — the actual stop condition, the thing that
> gates spending, ran on unreconciled numbers. It was **caught in review, not by
> the test suite that shipped with it**: those tests asserted
> `reconcile_live_used()` returned the right value in isolation, which is true
> and useless, because the defect was in the wiring rather than the helper.
> `test_reconciled_live_used_survives_the_reload_the_loop_does` exists because
> that coverage gap was itself the finding — it reloads the ledger the way the
> loop does and drives `can_batch()` at the exact boundary, and a companion
> assertion pins that `run_batch` persists rather than merges. Both were
> mutation-proved against the original bug. The lesson generalises past this
> entry: a test that exercises a helper directly cannot see that nobody calls it
> correctly.
> **Why narrower is correct rather than a compromise: the risk was only ever
> one-directional.** Live spend eating batch headroom is dangerous, and
> `batch_remaining()` already charges `live_used` against the batch — it simply
> could not *learn* it. Batch spend reaching `LIVE_QUOTA` buys nothing, because
> `can_generate()` measures live generation against the reserve alone and never
> consults `batch_used`, so a batch night cannot consume the live path's floor
> however much it spends. One read therefore closes the whole exposure, and it
> avoids exactly the trade this entry refused: no per-title network write, no
> rate-limited API in the hot loop, no new failure mode.
> **Fail-safe, in the project's over-count-never-under posture:** every
> unreadable case raises `RemoteQuotaUnavailable` and the batch REFUSES TO START
> (exit 1) rather than assuming `live_used=0`, which is the one unsafe answer.
> `--skip-remote-check` is the explicit, loudly-printed opt-out. A remote ledger
> from an earlier quota day counts 0 rather than its stale figure — day
> semantics, matching `load()`, not under-counting.
> Covered offline by `test_remote_live_ledger_read_is_offline_and_fail_safe` and
> `test_run_batch_refuses_to_start_on_an_unreadable_live_ledger` — the gh call is
> an injected runner, so CI needs no network, no gh and no auth. Mutation-proved:
> making failures report 0 turns three of those assertions red.
> **Still open:** the underlying two-writer split is unchanged. This closes the
> dangerous direction, not the architecture.

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

> **2026-08-16, RESOLVED in `2d2f5e4` — and the framing this entry ends on is
> now obsolete: the reserve is measured in REAL REQUESTS, not reservations.**
> The mechanism is the one this entry named as acceptable — "the runner
> reporting spend through an artifact the site already reads" — so the PAT it
> ruled out is still ruled out and no new credential surface exists.
> `synthesize.py` writes `cost.model_calls` from `model_pacer.calls_for(appid)`
> into the verdict itself (the one artifact the runner does commit);
> `fetchVerdictCost()` reads it back; `sweepReconciliations()` walks recent runs
> and books the difference; and `effectiveLiveUsed()` is what admission actually
> reads, so the correction reaches the DECISION rather than only the display.
> EST_COST stays 13 as the up-front reservation — the check and the spend still
> cannot be atomic across a `repository_dispatch` boundary — but the unspent
> part now comes back instead of being lost, so the 100-request reserve is worth
> roughly the ~18 generations/day this entry computed rather than ~7. The
> direction of failure is unchanged and still over-counts: a run whose cost
> cannot be read keeps its whole reservation. Mutation-proved 11/11
> (`evals/mutate_reconciliation.py`, logs `01`–`11`), including the two that
> matter most here — a clamp that would refuse to charge a 14-call overrun, and
> a constant standing in for the measured figure.
> **It also closed two stale comments found on the way**, in
> `site/app/api/generate/route.ts` and `site/lib/quota.ts`: both still described
> the reserve as unreconcilable, which is exactly the sentence a future reader
> would have trusted instead of reading the code.
> **THE ONE HONEST LIMIT: none of this has ever run against a real live
> generation.** It is fully built and fully tested, and the tests are the only
> thing that has exercised it. Checked rather than assumed — the remote
> `LIVE_QUOTA` variable today reads
> `{"date":"2026-08-10","live_used":13,"generations":1,...,"outcomes":{}}`. That
> ledger predates `2d2f5e4` by six days, and `outcomes` — the map
> `sweepReconciliations()` writes into — is still empty. So the first real live
> generation is simultaneously the sweep's first real exercise, and the thing to
> watch on it is a `reconciled` map appearing there. Until then this is verified
> code, not verified behaviour, and that distinction is the whole reason this
> note says so.

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

> **2026-08-17, RESOLVED — direction (b) is built, shipped and live in
> `cdebb6d`. Direction (a) was not touched, per this entry's own caution.**
>
> **The measurement was re-run first, on the full catalog rather than the ~135
> this entry was written against, and it changed the shape of the problem.** At
> TITLE level the tail is as rare as before: 17 of 304 past −40 (5.6%) against
> 7 of 131 (5.3%) at the 08-08 baseline, and the catalog mean barely moved
> (−20.2 → −20.9; the 131 titles present in both files moved a paired mean of
> +0.2, and the 173 added since arrive at −21.5). But the page renders COHORTS,
> not titles, and at cohort level the same data reads completely differently:
> **231 of 1,077 unmuted sections (21.4%) diverge more than 40 points from the
> rate printed directly above them, mean −22.6, and exactly ONE section
> diverges +40 the other way.** The title-level average was hiding one broken
> cohort behind three sound ones. AoE2 veteran and Palworld mid reproduce
> exactly (−78.8 and −74.4 against filtered survivors) and are still 6th and
> 9th of 1,077 — outliers, but no longer alone.
> **That measurement is what set the design.** Because divergence is the NORMAL
> state rather than the tail, tier 1 is unconditional: a note that fired only
> on the extremes would tell a reader, by its silence, that every other claim
> list was drawn representatively. Tier 2 escalates on two rules taken from the
> measured distribution, neither of them round numbers — thin (≤ 4 distinct
> cited reviews, the p10 against a median of 10; fires 11.0%) and divergent
> (exact binomial lower tail against the POOL rate, p < 0.05/1077, Bonferroni
> over the family of sections that actually render; fires 6.6%). They overlap
> on one section of 1,077, so they are kept as two rules rather than merged.
> **B2 (no number) over B1 (print the cited count), and the reason is
> `DESIGN.md:238`:** it calls the per-claim receipts tag "the one sanctioned
> non-pool number on the page", so a cohort-level count would be a second one —
> which needs an explicit DESIGN.md amendment as its own decision, not a
> ride-along on this feature. Two further hazards B2 avoids by construction:
> adjacency (a cited count under "based on 439 reviews" invites the reader to
> compute 6/439, a prevalence inference from sample counts that invariant 11
> forbids) and arithmetic (77.3% of cohorts cite some review from more than one
> claim — 15,736 citation instances over 11,882 distinct review-cohort pairs —
> so a distinct count is NOT the sum of the receipts tags above it and cannot
> honestly be presented as one). The counts still ship in the JSON as pipeline
> diagnostics, and a render-side contract test with sentinel values is what
> keeps them off the page.
> **Verified end to end, not just built:** backfilled across all 306 verdicts
> at zero Gemini cost (every input was already in the published JSON) and
> proven additive — all 306 files parse identically with the `sourcing` key
> stripped, and QR-4 re-run for real afterwards at 15,736 citations / 306
> verdicts, PASS. Mutation-proved 10/10 (`evals/mutate_sourcing.py`, logs
> `s01`–`s10`). Confirmed on PRODUCTION rather than locally: `813780`'s veteran
> cohort serves `"level":"escalated","triggers":["divergent"]` and the page
> renders "…here, reviews leaning more negative than the cohort above." beneath
> its 87.7%-of-439 stats line — the exact case this entry opened with.
> **(a) remains untouched and this note is not an argument for it.** Nothing in
> the fresh measurement makes extraction-side rebalancing newly necessary: the
> skew is stable rather than worsening, and the 08-08 finding stands that the
> dominant residual mechanism is review-length asymmetry, which prompt work
> cannot reach. The caution in this entry is unchanged for whoever picks it up.

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

> **2026-08-17, RECORD CORRECTION — the fix has been in for a while; this entry
> was stale, not open.** Everything the entry asked for is implemented in
> `select_publishable.py` and has been for some time: `DEFAULT_FROM =
> "origin/verdicts"` (line 68), a fetch before the script decides anything, and
> an outright refusal of a `--from` that is not remote-tracking, with an
> explicit opt-in flag to override and a printed warning when it is used. It
> also distinguishes "the branch does not exist" from "the network failed",
> which the entry did not ask for and which is the more dangerous of the two.
> Covered by five dedicated tests in `test_batch_guards.py`, all green:
> `test_select_refuses_a_ref_it_cannot_read`,
> `test_select_defaults_to_the_remote_and_refuses_local`,
> `test_select_tells_no_branch_apart_from_no_network`,
> `test_select_surfaces_failures_it_cannot_reproduce_locally`, and
> `test_publish_never_replaces_newer_with_older`.
>
> **Why the record went stale is the part worth keeping.** The fix landed as a
> side effect of adjacent publish-path work rather than as the scoped change
> this entry called for, and nothing updated the entry when it did. So the
> BACKLOG carried a solved problem as an open one, which is the mirror image of
> the failure this file is meant to prevent: the register of what is undone was
> itself undone. Anyone reading it since would have re-investigated a closed
> question, or worse, trusted "not yet fixed" and worked around a guard that
> was already there. Worth a habit rather than a note: when a fix lands
> incidentally, the entry it closes is part of the change.
>
> **The genuinely leftover half is now done too.** The `verdicts-migrate`
> branch is deleted; the two abandoned worktrees the entry mentions are already
> gone (`git worktree list` shows only the main checkout, and
> `git worktree prune --dry-run` finds nothing), and `/private/tmp/vw2` — the
> worktree that made `git fetch origin verdicts:verdicts` fail outright — no
> longer exists, so that specific footgun is gone with it.
> `git branch -d` **refused** the branch as not fully merged, so `-D` was used
> deliberately: it carried 2 commits that are not ancestors of main
> (`f967e95` "migrate verdicts to site/public/verdicts/", a pure set of renames,
> and `a8ce50f` "verdict: 367520 (generated live)"). Neither is lost work — the
> migration was redone on main rather than merged, and 367520 (Hollow Knight) is
> live in `site/public/verdicts/` today. SHA recorded here because `-D` leaves
> only the reflog: **the deleted tip was `f967e95`.**

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

> **2026-08-11, RESOLVED in `adf26e3`** — each child's return code is collected
> and asserted before the count is trusted, with stderr captured from any
> non-zero child, so a crash now reports as a crash. **The standing rule above
> is discharged**: the two failure modes are distinguishable, so a flake on this
> test is no longer uninformative by construction. Kept short because the fix's
> consequences are narrated where they were earned rather than here — the
> 2026-08-13 campaign could tell a lost update from a crash only because of it,
> and the 2026-08-16 entry names a cause rather than listing candidates for the
> same reason. Its sibling test got the same treatment in `36aad66`.

---

*This file is a case-study artifact. What got deferred, and the reasoning for
each, is evidence of prioritisation under constraint — link it from the case
study's decision section.*

2026-08-21 | **A third zero-survivor veteran cohort, and all three titles are
short finite games — the pattern is now about what the veteran bucket MEANS, not
about the filter** | build, 2026-08-21 batch night | A Plague Tale: Innocence
(`752590`) failed the filter stage in the exact shape of the 2026-08-16 Hotline
Miami and 2026-08-19 A Way Out entries: **veteran `in`=1, `kept`=0** (the single
review dropped as `low_information`), and the stage hard-fails the whole title.
0 Gemini calls, 55.4s, all of it Steam ingestion. Read out of
`data/filtered/752590.json`'s `filter_report`, not re-run.
**What is new is not the third instance, it is what the three have in common.**
Veteran pool shares, each measured from its own filtered artifact: Hotline Miami
**1 of 400**, A Way Out **2 of 400**, A Plague Tale **1 of 1,203** (0.1% of pool,
against 25,379 reviews on Steam). All three are short, finite, single-playthrough
games — a 6-hour co-op story, a ~10-hour linear stealth game, a score-attack
arcade game. Invariant 2 defines `veteran` as 6000+ minutes, i.e. 100 hours, and
**for a game that ends at ten hours there is no such player**, so the cohort is
not thin by accident of sampling — it is undefined by construction. Whether the
rest of the catalog is mostly open-ended by contrast was NOT measured here and is
not asserted; what is measured is these three.
**Why that reframes the open question rather than just incrementing it.** The
2026-08-16 note asks whether *every* zero-survivor cohort should mute
automatically, and says growth past a handful of entries is the signal to answer
it rather than add exceptions. Three titles in six nights is that growth — but
the answer it points at is not "mute at zero". It is that a fixed 100-hour
veteran bucket is the wrong instrument for a finite game, and muting is the
smallest of at least three responses: mute the empty cohort (cheapest, keeps the
bucket definition, renders a section that can never have content), make the top
bucket relative to the title's own playtime distribution (right in principle,
**invalidates every eval result** — invariant 2 forbids changing buckets without
explicit instruction, and this would be exactly that), or let a title publish
with three cohorts and no veteran section at all (a UI change, honest for a game
that has no such players). **Not added to `zero_cohort_exceptions.txt`**, on the
same reasoning A Way Out was not: a third exception spends the signal instead of
reading it. Both `752590` and `1222700` now retry nightly at 0 calls, costing
only Steam ingestion time, behind one owner call. Related:
[[verify-the-verifier]].

2026-08-21 | **The retry-cache fix turned a free deadlock into a paid one — a
title sitting on a prevalence-guard false positive now burns 9 calls a night
instead of 0** | build, 2026-08-21 batch night | RuneScape ® (`1343400`)
exhausted all three synthesis attempts and published nothing, at a cost of **9
model calls** — 6 extraction (two cohorts needed a grounding retry) plus 3
synthesis. It is the single largest wasted spend of the night and 2.3% of the
whole 397-call budget.
**All three rejections are invariant-11 prevalence hits, and all three are false
positives of the same family already recorded twice.** Reasons recovered offline
at **zero Gemini cost** by replaying `synthesize.check_response()` over the three
cached responses the run left on disk (`evals/diagnose_stage_failures_2026-08-21.py`,
raw output `evals/stage-failures-2026-08-21.txt`) — the batch runs `quiet=True`,
so only the `[FAIL]` line reached `evals/batch-2026-08-21.txt`:

| attempt | field | text | guard hit |
|---|---|---|---|
| 0 | `summary[veteran]` | "…required memberships, overwhelming interfaces, and **occasional** crashes or blockers." | `occasional`, frequency adjective |
| 1 | `summary[veteran]` | "…subscription walls, cluttered interfaces, and **occasional** crashes." | `occasional`, frequency adjective |
| 2 | `not_for_you_if[0]` | "you expect free access to **all** content" | `all`, absolute quantifier |

Neither word is stating prevalence. "Occasional crashes" describes how often a
*bug* occurs; "all content" describes the *game's* content behind a membership.
Invariant 11 exists to stop a sample count being read as how many players — and
on this title it fired three times without a population claim in sight. Attempt 2
is the informative one: the model **fixed** the veteran summary the guard had
just rejected twice (dropping the adjective entirely — "content locked behind
memberships, complex interfaces, and crashes") and tripped a *different*
guard on a *different* field. That is whack-a-mole, not sloppiness, and it is the
Insurgency shape exactly.
**This is the cost side of the 2026-08-20 retry-cache fix, and it is not an
argument against that fix.** Pre-fix, a title in this state replayed cached
rejections forever at 0 calls — the deadlock that entry correctly called a bug.
Post-fix the retries are genuinely fresh, which is what allows a title to escape,
and Insurgency did escape on attempt 2. The unintended half is that a title
which CANNOT escape now pays full freight **every night**: RuneScape will spend
~9 calls again tomorrow and publish nothing again, because `stage_failed` is not
in `run_batch`'s TERMINAL set. The old failure was free and permanent; the new
one is recurring and metered. Three cached `synthesis_*.json` files, all stamped
today, are the proof the requests were real.
**Fourth title in the guard-false-positive family** — Insurgency's "persistent"
(08-18), the "Windows eleven" spelling that shipped (08-20), and now two words on
one title. The 08-20 entry offered three fixes for the digit rule; this entry
adds the evidence that the prevalence rule has the same shape and now has a
price attached. **Not fixed**, and the options are unchanged in kind: scope the
guard to quantity contexts (right, and a rewrite of a rule that currently has one
unambiguous form), narrow the wordlist by category (`occasional`/`frequent`
describe events, `most`/`all` describe populations — cheap, and it is a real
weakening of invariant 11), or cap the spend rather than the failure (make a
rejection-exhausted `stage_failed` terminal after N nights, which buries the
question the 08-16 entry warned against burying). What is newly decidable is the
priority: this one has a running meter. Related: [[verify-the-verifier]].

> **2026-08-21, RESOLVED — the guard was split, and the fix is proved against
> the run that failed.** Owner decision: event frequency is not prevalence.
> `pipeline/prevalence_guard.py` now keeps population, proportion, ratio,
> percentage and consensus patterns in `PATTERNS`, and moves both frequency
> categories into `FREED_FREQUENCY_PATTERNS`, which is retained in the file,
> uncompiled and unchecked, so the history reads and a reversal is one line.
>
> **Verified on RuneScape's own cached responses, at zero Gemini cost.**
> Replaying its three rejected attempts through the new `check_response()`
> (`evals/diagnose_stage_failures_2026-08-21.py`) flips attempts 0 and 1 from
> `prevalence:summary[veteran]:occasional` to **PASS**. The title would have
> published on its first attempt for 1 call instead of failing on three for 9.
>
> **One of the three is still rejected, and that is a decision rather than an
> oversight.** Attempt 2's `not_for_you_if[0]` — "you expect free access to
> **all** content" — still trips `absolute quantifier`. "All content" is the
> game's content, not a share of players, so it is the same false-positive
> family one category over; `all` was deliberately kept banned. Recorded as
> still-open rather than counted as fixed.
>
> **Scope is wider than the instruction that requested it, on an explicit later
> decision.** Both frequency categories were freed IN FULL, including the extent
> words `commonly`, `widespread`, `prevalent`, `commonplace`, `widely`,
> `universally`, `unanimously`, `overwhelmingly`. The instruction had named
> `commonly` as a population word to keep banned; asked directly, the owner
> chose to free them with the rest. "widely praised" does lean on how many
> people, so this is the loosest reading of the split, and it is written down
> here because a future reader would otherwise find the code contradicting the
> instruction that produced it.
>
> **KNOWN SEAM, not resolved:** `unanimously` is now allowed while `unanimous`
> and `consensus` stay banned under `consensus language`, a category that was
> not part of the decision. Nothing in the catalog exercises it today.
>
> **Mutation-proved 12/12** (`evals/mutate_guard_split_2026-08-21.py`, logs
> `evals/mutation-logs/g01..g10`). Every loosened guard carries a CONTROL that
> reproduces the pre-fix behaviour — g01 rebuilds the old wordlist and rejects
> RuneScape's real summary, g06 drives the old bare-digit rule, g09 puts the old
> filter gate back and watches a title fail — because a guard widened too far
> passes every test written to check it stopped blocking something. g03 pins the
> nine population phrasings that must STILL be rejected, and a deliberate
> over-free mutation (`check_claim` returning clean) turns exactly those red and
> names each one. `filter_reviews.py` restored byte-identical, sha verified.
>
> **RuneScape was NOT force-regenerated**, per the owner's call — no quota to
> spare tonight. It retries on the next batch night, where it should now cost
> ~1 synthesis call instead of 3.

2026-08-21 | **BidKing: a catalogued title too small to ever produce a verdict,
refusing correctly and retrying nightly** | build, 2026-08-21 batch night |
`4128580` failed the verdict stage at **0 calls in 9.1s**. Not a bug and not a
guard false positive — the title has **124 reviews on Steam in total** (21.8%
positive), and after filtering every one of its four cohorts sits below
invariant 12's 20-review floor (`refund_window` 14, `early` 18, `mid` 14,
`veteran` 3), so extraction skipped all four as `below_cohort_floor`, every
cohort is muted, `post_refund_mean()` returns `None`, and synthesis refuses
before sending anything. Verified offline from `data/claims/4128580.json` and
`load_inputs()`, zero cost. **The refusal is the system working**: a title with
no cohort clearing the evidence floor has nothing to say, and `MIN_POOL_FOR_MEAN`
= 30 is what stops it saying it anyway.
**What is worth recording is that it is on the catalog at all.** `data/catalog.json`
was assembled 2026-08-12 from a store walk, and a 124-review title got in; it
will now re-enter the queue every night forever, costing a Steam sweep each time
and never publishing, because `stage_failed` is non-terminal. Same family as the
zero-cohort entry above and the 08-18 Insurgency one — a title that can never
resolve, retried nightly — reached by a **fourth** distinct route: not an empty
cohort, not a poisoned cache, not a guard, simply not enough reviews to exist.
**Not fixed**, and unlike the others this one has an obvious cheap answer worth
weighing: a minimum-reviews floor at catalog-build or queue time would drop it
before ingestion rather than after, and could be derived from the same
`steam_total_reviews` the pipeline already reads. That is a catalog change rather
than a pipeline one, and it wants a measurement first — **how many of the 25
still-pending and 514 published titles sit near the floor was NOT determined
here**, and guessing it is exactly the kind of "probably" the standing rules
forbid.
