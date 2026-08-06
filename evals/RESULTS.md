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

**Developer notes on the audit:** _(left blank — to be filled by the author)_
