# Eval Results — WorthIt.gg

Append-only. One row per run. Rubric wording lives in evals/rubric.md (authored by owner).

| Date | Run | QR-1 Faithfulness | QR-2 Segment acc. | QR-3 Shape diversity | QR-4 Safety | Notes |
|---|---|---|---|---|---|---|
| 2026-07-31 | 2.3 baseline, rubric v1.1 | **67.1%** scoring 2 (mean 1.67, **0 zeros**) | 100% Y — by construction, see caveat | *not yet assessed* | **PASS** (0 failures / 198 citations) | First filed baseline. Rubric took three drafts to handle compound claims correctly. |

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

**QR-3 — Verdict-shape diversity: not yet assessed**

Not scored per case. Per the rubric it is a whole-set qualitative judgment made by
reading all five seed verdicts and asking whether they differ structurally rather than
only in wording. Owner-authored; left open rather than guessed.

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
