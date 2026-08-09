# Eval Results — WorthIt.gg

Append-only. One row per run. Rubric wording lives in evals/rubric.md (authored by owner).

| Date | Run | QR-1 Faithfulness | QR-2 Segment acc. | QR-3 Shape diversity | QR-4 Safety | Notes |
|---|---|---|---|---|---|---|
| 2026-07-31 | 2.3 baseline, rubric v1.1 | **67.1%** scoring 2 (mean 1.67, **0 zeros**) | 100% Y — by construction, see caveat | **PASS** — 5 distinct flag profiles | **PASS** (0 failures / 198 citations) | First filed baseline. Rubric took three drafts to handle compound claims correctly. |

---

## 2026-07-31 — 2.3 baseline (rubric v1.1)

**Provenance**

| | |
|---|---|
| Rubric | `evals/rubric.md` v1.1, `sha256 4200c44b4554c45d25d9bcf329dbd803e73a602ba52e0bbf7627725d8552e51f` |
| Test set | `evals/candidates.json` — 70 cases, 198 citations, 5 seed games |
| Claims produced by | `gemini-3.5-flash-lite` (extraction, `thinking_level: minimal`, no sampling params) |
| Grounding thresholds | `min_coverage 0.25`, `min_citation_coverage 0.1`, `min_supporting 2`, `retries_allowed 2` |
| Judge | `gemini-3.5-flash-lite`, `thinking_level: low`, no sampling params, one request per case |
| Output | `evals/judge_scores.json` |

The rubric hash is recorded because **two different drafts both carried the version
string `1.1`** during authoring. Version alone does not identify the standard a row
was scored against; the hash does.

**QR-1 — Faithfulness: 67.1% scoring 2, mean 1.67**

| Score | Cases |
|---|---|
| 2 — fully supported | 47 |
| 1 — partially supported | 23 |
| 0 — unsupported | **0** |

No case scored 0: no claim in the set cites reviews that fail to discuss its subject.
Per cohort, `refund_window` is weakest (mean 1.43) and `early` strongest (1.83); per
game, Death Stranding is weakest (1.47) and Cyberpunk strongest (1.90).

The case-level ≥2 rule is computed in code from per-citation `full`/`partial`/`none`
levels rather than trusted to the judge's arithmetic. It disagreed with the judge's own
holistic score on **6 of 70 cases**, every one in the same direction: the judge rounding
up to 2 where only one citation reached `full`. Those 6 are the priority set for the
2.4 hand validation.

**QR-2 — Segment accuracy: 100% Y — a regression guard, not a measurement**

Computed in code, never judged. This figure is **100% by construction on this test
set**: `make_candidates.py` asserts every citation is in-cohort and exits 1 otherwise,
and the 1.4 grounding check rejects out-of-bucket citations upstream. It is worth
recording because it will catch a future regression, but it is not evidence that
segmentation is accurate — nothing here could have scored otherwise.

**QR-3 — Verdict-shape diversity: PASS**

Not scored per case: a whole-set qualitative judgment made by reading all five seed
verdicts and asking whether they differ structurally rather than only in wording.

**All five games produced a distinct distortion-flag profile — no two alike:**

| Game | Cohort sequence (pool % positive) | Spread | Flag profile |
|---|---|---|---|
| Kenshi | 40.4 → 87.4 → 93.7 → 98.0 | 57.6 | `cohort_divergence` / monotonic_increase |
| Helldivers 2 | 50.0 → 88.2 → 85.2 → 65.7 | 38.2 | `cohort_divergence` / **rise_then_fall** |
| Death Stranding | 50.0 → 74.3 → 93.7 → 95.3 | 45.3 | `recency_shift` / **declined** (−9.5 pts) |
| Cyberpunk 2077 | 91.7 → 93.8 → 98.3 → 98.0 | 6.6 | `recency_shift` / **improved** (+8.7 pts) |
| Stardew Valley | 75.0 → 97.3 → 98.5 → 99.0 | 24.0 | none — consensus |

Kenshi is the only monotonic staircase to fire a divergence flag; Helldivers 2 the only
non-monotonic shape, peaking at `early` and falling 22.5 points to `veteran`. Death
Stranding and Cyberpunk both surface through recency rather than playtime — in opposite
directions, a decline against lifetime score versus a redemption arc. Stardew fires
nothing at all, which is itself the finding for a consensus title. Five games, five
profiles: the pipeline is surfacing genuine per-game structure, not a templated output.

Cyberpunk 2077 is worth stating in its own terms: it reads flat **via a temporal
redemption arc rather than playtime segmentation**, surfaced by the recency flag
instead. Its cohorts genuinely do not disagree — the structure in this title is
chronological, not segmental, and a tool that only looked across playtime would report
it as consensus and miss the story entirely.

Three corrections against the figures as first drafted, made from the pipeline's own
output rather than carried through:

1. **Kenshi's veteran cohort is 98.0%, not 99%.**
2. **Stardew's spread is 24.0 points, which is not "narrow."** It is flat *only* among
   the three cohorts clearing the flag-evidence floor (`pool_n ≥ 30`): 97.3 → 98.5 →
   99.0, a 1.7-point spread. Its 75.0% refund figure rests on `pool_n = 24` and is
   excluded from flag evidence. Both statements are true; pairing "75 → 99" with
   "narrow spread" is not.
3. **"No two games produced the same *shape*" does not hold as stated.** The pipeline's
   own `classify_shape` labels four of five `monotonic_increase` — Kenshi's staircase
   and Death Stranding's slow burn carry the same label. The claim that survives, and
   the one recorded above, is that no two games produced the same **flag profile**.
   That is the stronger test anyway: it is what a reader actually sees on the verdict
   page, and it distinguishes all five rather than four.

Note that Death Stranding's headline 45.3-point spread does **not** fire a divergence
flag: its refund cohort (`n = 26`) falls below the flag floor, leaving an eligible
spread of 21.0 against a 25-point threshold. Its verdict presents as a recency story.

**QR-4 — Content safety: PASS (launch gate, invariant 8)**

Zero failures across all 198 citations, including the 18 carrying filter annotations
(13 `profanity_soft`, 7 `hearts_present`) that the rubric's reading order puts first.
Nothing blocks deploy on this gate.

**Note on the rubric — three drafts to handle compound claims**

v1.0 had no rule for claims asserting several things at once, so the judge required a
single citation to carry an entire compound claim. Two defects were found and closed
across three drafts, each validated against 5 hand-picked adversarial cases before any
full run:

1. **Symmetric-permission gap.** The section defined when a claim decomposes but never
   stated what a citation covering one component *earns*, leaving the restrictive
   crediting rule as the only explicit instruction. Closed by granting FULL for a
   component a citation fully and specifically supports, tied back to the case-level
   ≥2 rule so one citation still cannot carry a case.
2. **Whole-claim crediting ambiguity.** The phrase *"score it as a single whole
   assertion, even if a citation happens to address part of the phrasing"* switched
   subject mid-clause and was read in opposite directions on two cases — as licence to
   award FULL for partial coverage. Closed by separating the crediting rule for
   non-decomposing claims: partial coverage scores PARTIAL, never FULL.

**Direction of the change: v1.1 is stricter, not looser.** Against the same 70 cases
under the pre-final v1.0 wording (**74.3%** scoring 2, mean 1.74 — never filed as a row,
and not comparable), v1.1 moved **5 cases down, 0 up, 65 unchanged**. Every one of the
five is a *non-decomposing* claim, so the entire delta comes from defect 2's fix. The
compound-claim permission that motivated the whole revision changed **no** case-level
score: it fires at citation level, but the decomposing claims it touches were already
scoring 2.

The claims did not get worse — the standard got more honest. Per the rubric's Versioning
section, the v1.0 figure is not a valid comparison point and no improvement is claimed
against it.

---

## 2026-08-06 — 4.4 catalog audit (BUILD_PLAN DoD)

**QR-4 — Content safety: PASS (launch gate, invariant 8)**

| | |
|---|---|
| Automated gate | `pipeline/qr4_gate.py --all` — **7,102 citations across 131 verdicts, 0 failures** |
| Manual audit | 10 verdicts spot-checked, 20 citations read — **20/20 clean** |
| Sample | `evals/audit-4.4-sample.md`, sampled deterministically from the audit-stable set |
| Published | 119 verdicts, in two commits (34 flash-tier day 1–2; 85 non-tier + day 3) |

The audit sample was drawn only from **audit-stable** verdicts — those whose
synthesis model will not change again. The 12 day-3 titles still awaiting a
flash upgrade were excluded: auditing a verdict that is about to be regenerated
spends the audit on something that will not survive.

**Catalog position:** 119 of 150 published · 4 gate-rejected as thin-segmentation
· 27 outstanding (12 day-3 flash upgrades, 20 day-4 titles, 2 rolled over by the
budget stop; the day-3 upgrades overlap the outstanding count).

**Developer notes on the audit:** Read all 20 sampled citations against the filter
annotations (`hearts_present`, `profanity_soft`, `all_caps`); no slurs, no explicit
content, no distressing material found. Clean.

---

## 2026-08-06 — 4.4 audit, day-3 flash-lite verdicts

**QR-4 — Content safety: PASS**

| | |
|---|---|
| Automated gate | **541 citations across 12 verdicts, 0 failures** |
| Manual audit | 10 verdicts spot-checked, 20 citations read — **20/20 clean** |
| Sample | `evals/audit-4.4-day3.md` |

These 12 reached `main` briefly inside an unrelated UI commit (`2177675`, a
`git add -A site/` that swept up files being held back), were reverted out in
`3e4bc6e`, audited, and re-committed on their own in `d03bea8`. Recorded because
the gate exists to be auditable, and a gate that was skipped and then repaired
is part of that record.

They are flash-lite-final — dropped from the flash tier rather than upgraded,
since re-synthesis changes which claims are selected and therefore which
citations render, which would mean paying for this audit twice.

**Developer notes on the audit:** Read all 20 sampled citations against the filter
annotations; no slurs, no explicit content, no distressing material found. Clean.


## 2026-08-08 — Verdict override bug (rule 9): overcorrection, root cause, and a code-side fix

**Found via:** manual 4.4 audit (citation-level review), not automated
QR-4 — this was a soundness/consistency issue, not a grounding or safety
issue, and QR-4 passed cleanly throughout.

**Bug 1 — theme misclassification.** Extraction's theme enum had no
category for access/DRM requirements (mandatory launchers, account
linking); such claims were absorbed into "monetization," "performance," or
"other." Final measured scope: 38 claims across 18 titles (an earlier
estimate of 11/8 undercounted by not searching all themes; a second
estimate of 29/14 undercounted by conflating launcher *requirements* with
launcher *malfunctions*, which are correctly "performance"). Fix: added an
"access" theme, defined all six themes explicitly in the extraction
prompt. Re-extraction of 6 titles (as a side effect of the verdict fix
below) confirmed the fix works cleanly; 18 titles remain outstanding for a
dedicated re-extraction pass (~110 calls).

**Bug 2 — verdict rule 9 override, and a failed first fix.** Original rule
9 permitted the model to override cohort sentiment toward Skip on claim
severity, via one undefined worked example. GTA:SA scored Skip at 83.4%
mean post-refund positive sentiment — the only Skip among 90 titles with
post-refund cohorts all ≥80%. Proven via A/B isolation (identical claims,
prompt-only diff) as the cause, not extraction variance.

A first rewrite of rule 9 (defining Buy/Wait/Skip, adding a "broad
recommendation makes Skip almost certainly wrong" guardrail) fixed GTA:SA
but introduced the mirror bias: Starfield (57.5% mean, 78.4% negative
claims — both signals pointing to Skip) returned Wait 3/3 under two
different wordings of the fix. Skip had effectively left the model's
vocabulary. All 6 titles regenerated under the first fix flipped Skip ->
Wait (100% flip rate), which in hindsight was a symptom of overcorrection,
not confirmation of a clean fix.

**Root cause:** the verdict word was the one high-stakes output still
decided by prose instruction alone, contrary to the pipeline's own design
principle (model output stays narrow; consequential decisions are
computed in code). A prompt-only fix could not hold — it just moved the
bias.

**Real fix — code-side band rail.** `post_refund_mean(cohorts)` computes
mean `pct_positive` across non-muted, non-refund post-refund cohorts, and
`forbidden_verdicts(mean)` maps that to the rejected set (refund
window excluded — it's the cohort that already bounced, and cohorts below
the invariant-12 evidence floor are excluded from the mean). Rejects
verdicts outside the allowed set per band, reusing the existing
check-and-retry machinery (same pattern as invariants 4/11/12/13):

| mean post-refund | rejects | rationale |
|---|---|---|
| >= 80% | Skip | catches the original failure (GTA:SA 83.4%, Megabonk 85.8%) |
| 70-80% | nothing | genuine ambiguous band — claims decide |
| 60-70% | Buy | a game a third of remaining players won't recommend isn't a Buy |
| < 60% | Buy, Wait | only Skip; 6 of 7 published titles here already were |

No verdict is written if a title exhausts retries without landing on an
allowed word (same posture as every other invariant) — logged as a
distinct `verdict_rail_exhausted` count to make the rate measurable rather
than inferred.

**Verified:** 25 offline boundary tests (13 band-edge cases from both
sides, 5 cohort-inclusion cases, 7 through `check_response`'s real retry
path). Break-then-confirm:
disabling the rail failed exactly the 3 wiring tests, correctly leaving
the pure band-function tests green. Live A/B on the 8 touched titles
(verdict-only, nothing committed) — rail fired on exactly 1 of 8
(Starfield), matching the pre-fix prediction that it would not sweep the
catalog.

**Published outcomes (Skip -> Wait, rail-compliant, held from the first
fix):** GTA:SA Definitive (83.5%), Megabonk (85.8%, re-rolled to Buy on
re-test — high band (>=80%), not forced), The Sims 4 (79.97% — free band, not
>=80 as earlier reported), The Isle (78.97%), Hell Let Loose (78.87%).

**Corrected by the rail (Wait -> Skip):** Starfield (57.5% mean, 78.4%
negative claims). Regenerated verdict -> qr4, QR-4 108/108 clean, page and
OG tags verified correct (`Starfield: Skip — WorthIt.gg`).

**Left unchanged, free-band judgment calls, not rail violations:** ESO
(70.4%, stayed Skip — correctly did not flip under either rule 9 wording;
used as the control confirming the rail doesn't over-sweep), MORDHAU
(70.2%, returned Skip under the final rule after earlier appearing to
"converge" on Wait 6/6 — that convergence was an artifact of a fixed
prompt state across repeated runs, not a stable property of the title; a
mistake made and caught twice in this investigation, worth remembering).

**Separate defect found and fixed:** Starfield published with
`game_name: null` from a transient ingestion lookup failure written
through uncaught, breaking its page title and OG unfurl (`null: Skip`).
Fixed at the source with a guard in both ingestion and synthesis refusing
to proceed without a resolved name.

**Separate defect found and fixed:** for-whom lines could contradict their
own verdict stamp (e.g., "should buy this" text under a Skip stamp — found
on MORDHAU). Added a directive-language check (should buy/buy it/skip
it/avoid it) to check_response, verified against 8 cases including the
real failure.

**Open, flagged for later:** 6 band-edge titles (Marvel Rivals, Apex
Legends, Last Epoch, Hunt: Showdown 1896, ESO, Borderlands 3) hold the
minority verdict word for their band under rules that have since changed
— rail-compliant, reported as judgment calls, not regenerated. Also open:
Marvel Rivals (95.7% negative claims) and Megabonk (52.9% negative claims,
above the Buy-population mean of 16.2%) show a claims-content-vs-verdict-
word mismatch distinct from the cohort-mean rail above — flagged as a
candidate for a second, separate rail; deliberately not folded into this
fix, per the same discipline that caused the original overcorrection.
18 titles still need the access-theme re-extraction pass. Batch ledger:
83/400 used today.

---

## 2026-08-08 — Claim sourcing balance: measured, partially fixed, NOT rolled out

**Question.** A reader sees the Split Bar say a cohort is 72% positive, then
reads a claim list built overwhelmingly from people who did not recommend the
game. Is extraction under-sampling positive reviews, or is the pool genuinely
that negative?

**Answer: extraction, and catalog-wide.** New tool
`pipeline/measure_claim_balance.py` compares, per cohort, the share of
`voted_up` reviews **available** to extraction (the filtered survivors) against
the share among reviews it **actually cited**. It counts SOURCES, never claims —
invariant 13 forbids a per-claim valence, and `citation_verdict` is what the
citing reviewers thought of the *game*, so it cannot stand in for one.

Baseline, 131 titles (`evals/baselines/claim-balance-before.json`):

| | |
|---|---|
| cited more negatively than their own pool | **120 of 131 (92%)** |
| mean delta | **−20.2 pts** (median −20.4, min −56.7, max +6.1) |
| by pool sentiment | <60% −24.5 · 60–75% −31.2 · 75–90% −23.9 · ≥90% −9.4 |

Extraction receives *all* of a cohort's filtered survivors, so the input is
already representative. The whole skew is in what it chooses to cite.

**Two mechanisms.** (a) Prompt framing: extraction rule 2 defined a claim as
"what breaks, what is hard, what is missing, what works" — three negative
framings to one, with a complaint as its only worked example. (b) Structural:
positive reviews are half the length of negative ones (median 20 vs 40 words;
49% vs 28% under 20 words), so praise clears invariant 3's ≥2-supporting-
citations bar and the "specific and falsifiable" test far less often.

**Change tested (a only).** Rule 2 reordered to lead with "what works", a
positive worked example added beside the negative one, and one sentence added
that a cohort's praise is evidence on the same terms as its complaints.
Deliberately **no ratio target and no instruction to produce balance** — that
would be fabrication pressure against invariant 3, installing a counter-bias
rather than removing a bias.

**A/B: 10 titles, re-extraction only, same review pools.** Gate criteria were
fixed in the plan before any measurement.

| title | pool | Δ before | Δ after | move |
|---|---|---|---|---|
| Binding of Isaac | 87.2% | −56.7 | −36.3 | +20.4 |
| Last Epoch | 62.6% | −46.5 | −27.9 | +18.6 |
| Slay the Spire | 88.0% | −39.3 | −16.6 | +22.7 |
| Megabonk | 75.2% | −37.2 | −25.2 | +12.0 |
| Marvel Rivals | 37.7% | −31.6 | −25.1 | +6.5 |
| Divinity: OS2 | 89.3% | −27.6 | −25.0 | +2.6 |
| Apex Legends | 52.4% | −23.2 | −3.1 | +20.1 |
| Hunt: Showdown | 59.9% | −21.3 | −16.5 | +4.8 |
| **ARK: Survival Ascended** | 28.7% | −15.0 | **−16.1** | **−1.1** |
| *DOOM (control)* | 93.8% | −1.7 | +3.6 | +5.3 |

| criterion | required | actual | |
|---|---|---|---|
| mean \|Δ\| improvement | ≥ 33.3% | 33.2 → 21.3 = 35.7% | PASS |
| no title worsens | zero tolerance | ARK −1.1 | **FAIL** |
| control moves | < 10 pts | 5.3 | PASS |

**Not rolled out.** The failing criterion was held absolute rather than relaxed
after seeing the data — relaxing a pre-set bar post hoc is how a fix gets talked
into looking better than it measured. All 10 test titles' claims were restored
to their pre-A/B state; no verdict or published page changed.

**The over-correction question is closed — no evidence of it.** The first A/B's
control (DOOM) crossed from −1.7 to +3.6, raising the possibility that the new
wording over-corrected toward praise. Widening to two more high-sentiment titles
with real headroom settled it: Slay the Spire (88.0%) and Divinity: OS2 (89.3%)
both moved *toward* zero and stopped well short of it (−16.6, −25.0), as did
Binding of Isaac (−36.3). DOOM began at −1.7 against a 93.8% positive pool and
had nowhere else to go — a ceiling effect, not a signal.

**Mechanism (b) is the dominant remaining cause, and prompt changes do not
resolve it.** Residual mean \|Δ\| is 21.3, and Binding of Isaac still sits at
−36.3 against an 87.2% positive pool. The change helps most where the skew was
largest (Δ worse than −25 improved +12 to +23) and does nothing where the pool
is already overwhelmingly negative — the signature of removing a framing bias,
not of installing a counter-bias. What remains is a property of the evidence:
people who like a game write "10/10 great game"; people who do not write
paragraphs explaining why. Closing it would require weakening invariant 3 or the
falsifiability bar, both of which cost more than the distortion they would fix.
BACKLOG.md recorded this same length asymmetry earlier as a driver of claim
*drops*; this is the same effect showing up as claim *sourcing*.

**Not affected:** the 18-title access-theme re-extraction pass is independent of
this result and was never contingent on it.


## 2026-08-08 (cont'd) — Verdict word moved fully into code

**Context:** the earlier entry this session documented the rule-9 override
bug and two failed prompt-only attempts to fix it (Skip-biased, then
Wait-biased). Root cause: the verdict word was the one high-stakes output
still decided by prose instruction, against this module's own stated
contract ("the model's job is deliberately tiny; everything else is
computed in code"). This entry documents the architectural fix.

**Decision:** the verdict word (Buy/Wait/Skip) is now computed in code from
`post_refund_mean(cohorts)`, not returned by the model. The model receives
the computed word as an input and writes only the for-whom prose to match
it.

**Threshold derivation:** anchored to the catalog's own statistical
distribution, not round numbers. Two corrections were made to the input
before finalizing thresholds:
- `post_refund_mean` is now pool_n-weighted (previously an unweighted
  mean, which let a 27-review cohort outvote a 560-review one) with a
  pool_n >= 30 inclusion floor (previously a cohort could be admitted on
  survivor count alone even with an unreliable pool rate).
- These corrections shifted several titles meaningfully (e.g. ARC Raiders
  -6.9pts, War Thunder -4.6pts) and moved the Skip/Wait boundary itself
  (from an initial 68% to 64%) — thresholds were re-derived after the
  correction, not assumed to hold.

**Final thresholds:** Buy >= 89% · Skip < 64% · Wait between. Both are the
empirical error-minimizing points on the corrected distribution (Buy p10
89.2 / Wait p90 93.9; Skip p90 68.5 / Wait p10 69.8).

**Rejected alternatives, with reasons:** Buy >=75%/Skip<50% (round numbers)
was tested and rejected — Skip could never fire (catalog minimum is
51.8%), and would have reversed today's earlier Starfield correction; Buy
>=80% was tested and rejected — Halo: The Master Chief Collection and ARK:
Survival Evolved would enter Buy despite ~75-80% of their claims being
negatively-sourced. Buy >=89%/Skip<68% (pre-correction) was superseded once
weighting/flooring changed where the data actually separates.

**Catalog impact:** Buy 68->79, Wait 53->43, Skip 12->11 (24 titles
changed word on the arithmetic pass; scope for the full rollout below).
Starfield stays Skip in every candidate tested. Marvel Rivals correctly
enters Skip (58.9%, 95.7% negatively-sourced claims) — the sharpest
confirmation the new logic works as intended.

**Second, related fix — friction-as-disclosure, not condition (rule 7):**
for-whom lines could previously frame material friction (mandatory
launchers, account requirements) as a purchase condition ("buy only if
you're willing to..."). Fixed in two passes: the first removed the hard
"buy only if" form but left a softer audience-framing construction
("suits players willing to tolerate X") that does the same work under a
different grammar. Tightened to require a flat disclosure form ("worth
knowing: requires X"). Verified this doesn't hold on repeated generation
by prose alone — codified as a `check_response` guard
(`for_whom_frames_friction_as_a_condition`) in the retry loop, the same
pattern as every other invariant here, rather than trusted to a paragraph
of instructions. A second obligation-verb variant ("must tolerate") was
found escaping the first version of this guard and folded in.

**Scope-finding, worth recording on its own:** the rollout's true scope
was computed twice before being trusted. An initial regex-based estimate
(66 of 133) was wrong in both directions — it missed titles failing
`for_whom_contradicts_verdict` for an unrelated reason (Buy verdicts
reading "but skip it if...", e.g. Baldur's Gate 3, Cyberpunk 2077), and it
over-counted via a proxy pattern. Running the actual code guards against
every title, rather than a text proxy, gave the true figure: 50 of 133 (20
word changes, 36 for-whom guard failures, 13 overlap).

**Rollout:** 50 titles, verdict stage only (no re-extraction — claims and
citations untouched). 57 model calls (50 + 7 retries, guards firing
correctly: 3 friction-condition rejections, 4 other prose rejections, all
recovered on first retry). 0 failures. Final catalog: Buy 79 / Wait 43 /
Skip 11 — matches the pre-rollout projection exactly.

**Verification:** offline boundary tests at both thresholds (88.9/89.0/
89.1, 63.9/64.0/64.1) plus weighting/floor cases; break-then-confirm on
every new invariant (one weighting test initially couldn't fail — its
fixture used a 27-review cohort, below the pool floor, so weighting never
engaged; caught and fixed before trusting the result, the second time
today break-then-confirm caught an unfireable test); dead-reference grep
confirming `forbidden_verdicts`, `verdict_out_of_band`, and
`verdict_rail_exhausted` have zero live references; live A/B on 6 boundary
titles before rollout; catalog-wide consistency check post-rollout (0
titles disagree with their computed word, 0 fail a for-whom guard, across
all 133); QR-4 on the 50 regenerated (2,607 citations, 0 failures) and
catalog-wide (7,084 citations / 133 verdicts, PASS); site suite 52/52;
pipeline guards green.

**Audit disposition:** for the 50 regenerated titles, extraction and
citations are unchanged — only the verdict word and for-whom prose
changed. Existing 4.4/4.5 QR-4 findings on those citations still hold; no
fresh citation re-audit was performed, since re-reading unchanged citations
spends audit effort on nothing. This note is that record.

**Known, accepted limitation (documented, not fixed):** 17 of 133 titles
sit within a 95% confidence interval of a threshold, computed by
propagating each cohort's binomial error into the mean — these titles'
published verdict could plausibly flip on a different day's sampling. This
is treated as an accepted property of any threshold-based system, not a
defect. No tie-break rule was added, deliberately — a tie-break would
reintroduce the kind of ad-hoc judgment this whole change removed.

**Explicitly deferred:** a second rail for claims-content-vs-verdict-word
mismatch (Age of Empires II, Palworld — strong sentiment against
negatively-sourced claims, both partly explained by the ~20pt extraction
sourcing bias measured earlier today, not folded into this fix); the
paused 18-title access-theme 4.5 audit, now unblocked since these titles'
verdicts have settled.