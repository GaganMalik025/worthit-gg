# Eval Rubric — WorthIt.gg

**Author:** Gagan Malik
**Version:** 1.1
**Applies to:** `evals/candidates.json` — 70 cases, 198 citations, 5 seed games
**Claims produced by:** `gemini-3.5-flash-lite`, grounding thresholds
`{min_coverage: 0.25, min_citation_coverage: 0.1, min_supporting: 2}`

This rubric defines how a generated claim is scored against the reviews cited
to support it. It exists to answer one question honestly: **can a buyer trust
what this tool tells them?**

Three checks per case, scored independently. A case can pass two and fail one;
record all three regardless.

v1.1 — added compound-claim/component-scoring rule after 553850-ref-ff0ba4 surfaced a rubric gap

---

## Scoring procedure

For each case:

1. Read the claim text.
2. Read **every** citation's full review text — not the excerpt, not the first
   one that looks confirming.
3. Score QR-1, QR-2, QR-4 independently.
4. Where a score is not obvious, write one sentence of reasoning. Cases with
   reasoning attached are the ones worth revisiting when the rubric is revised.

Do not consult `citation_verdict` when scoring QR-1. See "Out of scope" below.

---

## QR-1 — Faithfulness (0 / 1 / 2)

**What this measures:** whether the cited reviews support the **literal
content** of the claim — what it asserts happened. Not its tone, not its
implied conclusion, not whether the reviewers liked the game.

**Case-level rule:** a claim scores at the level supported by **at least two
citations**, mirroring the ≥2-review rule enforced in the pipeline. If four
citations fully support the claim and one doesn't, the case scores 2 — a
single weak citation does not drag down a well-supported claim. If only one
citation fully supports it, the case cannot score above 1.

### Score 2 — fully supported

Two or more citations state or clearly convey exactly what the claim asserts,
with no inferential gap.

> **Claim:** "reviewers report performance issues, bugs, and crashes"
> **Citation (thumbs-up):** "Pretty good, sadly didnt get full experience due
> to computer issues"
>
> → **2.** The claim asserts only that performance issues occurred. This
> citation confirms that. The reviewer's positive overall verdict is
> irrelevant to whether the factual content is supported. Had the claim read
> *"performance issues that ruin the experience"*, this same citation would
> score lower — that is a stronger, different assertion.

**Low word overlap is not evidence against faithfulness.** Reviewers
paraphrase heavily and write colourfully. Judge meaning, not vocabulary:

> **Claim:** "characters are repeatedly defeated, beaten up, or enslaved"
> **Citations:** "get your ass beat 1 million times" · "captured by slavers…
> gobbled up alive"
>
> → **2.** Almost no shared vocabulary, complete semantic support. The
> pipeline's lexical grounding check is deliberately cruder than this rubric;
> QR-1 is where meaning gets judged.

### Score 1 — partially supported

The citations point the right direction, but the claim adds something not
present: an intensifier, a broader scope, a stated cause, or a second
assertion only one citation covers.

> **Claim:** "Reviewers note a lack of progression or meaningful rewards after completing missions, stating that items and armor lack unique stats."
> **Citation:** "I haven't been here for all the drama so I'm just basing this review on my gameplay experience. \n\n1. It drives me crazy that your loadout doesn't save between rounds. I avoid purchasing new items because I don't want my loadout screen to have a hundred items that I have to sort through before each mission. \n\nI bought two warbonds with real money and the rest will sit unpurchased because I don't want to have to search through stratagems every mission, they're literally losing money over this.\n\n2. There's not really any incentive to play. You don't really get anything for beating a mission other than some level xp and a few research samples. You can go tens of hours without unlocking anything new, even longer if you're purposefully avoiding useless item unlocks because your loadouts don't save between rounds (see point 1).\n\nThe gameplay is actually fun, but the game itself doesn't feel finished."

>
> → **1.** Lack of progression mentioned in Claim doesn't specify what kind. There are multiple progressions, like "cross-progression" which means carrying over save data between consoles/PC. There is also no mention of Loadouts not saving after each mission, leading to doing same tasks (of applying your own fixed loadout) after every mission. Because words are not specific in Claim, it can be misread or misrepresented.

Note: even though this claim mentions two things, it doesn't split into separate components, because it's phrased as one blended idea ('lack of X or Y'), not an explicit list like 'X, Y, and Z

Typical 1-scoring patterns:
- claim names a cause the reviewer never gave
- claim bundles two findings, only one of which is cited
- claim generalises a single reviewer's experience into a property of the game

### Score 0 — unsupported

The citations do not discuss the claim's subject, or the claim has stretched
adjacent material into a different assertion.

> **Claim:** "technical issues occur specifically when alt-tabbing"
> **Citations:** reviews describing crashes, none mentioning alt-tabbing
>
> → **0.** General crashing does not support a specific alt-tab trigger. This
> is a real claim the 1.4 grounding check rejected three times before
> dropping it — included here as the canonical shape of a 0, even though it
> never reached the dataset.

### Compound claims and component-level scoring

A claim decomposes into components when it lists coordinate examples of one
category — signaled by "such as" followed by two or more comma-separated
items, or an explicit "X, Y, and Z" list. Each listed item is an independent
component, scorable on its own, because each is a specific instance of the
same general assertion the claim makes. For a decomposing claim, a citation 
that fully and specifically supports one listed component earns FULL for that 
component, notwithstanding silence on the sibling components — the case-level 
score is then governed by how many components across the citation set reach FULL, 
per the case scoring procedure above (at least two citations, collectively covering 
the claim, required for a case-level 2).

A claim does NOT decompose when a clause is subordinate by cause,
consequence, or elaboration rather than list membership — signaled by words
like "requiring," "resulting in," "because," or a single dependent clause
following a comma. That subordinate clause is not a component; it is not
independently scorable, and a citation supporting only it does not earn
FULL.

**Test:** if you can rewrite the tail as "for example, A; B; and C" without
changing the claim's meaning, it's a list and decomposes. If rewriting it
that way is nonsensical, it's a subordinate clause and does not.

If a claim does not decompose, score it as one whole assertion. A citation
that addresses only part of a non-decomposing claim's phrasing — without
covering the full assertion — scores PARTIAL, never FULL, regardless of how
confidently it matches the fragment it does cover.

---

## QR-2 — Segment accuracy (Y / N)

**What this measures:** whether every citation genuinely belongs to the
playtime cohort the claim is filed under (refund / early / mid / veteran).

- **Y** — every citation's recorded bucket matches the case's cohort.
- **N** — any citation is out of bucket.

One mismatch fails the case. There is no partial credit: a misplaced citation
attributes a finding to the wrong kind of player, which is the specific error
this product exists to avoid.

Each citation in `candidates.json` carries its own bucket beside the case's
cohort, so this is a direct comparison rather than a judgment call. Score it
mechanically and move on.

---

## QR-4 — Content safety (pass / fail)

**What this measures:** whether any cited review text would be inappropriate
to surface to a buyer who clicks "show receipts."

**Fail** if any citation contains slurs or hate speech, sexually explicit
content, graphic sexual violence, or material that would be distressing or
embarrassing to encounter unexpectedly.

A single failing citation fails the case. QR-4 is a launch gate, not an
average — it must be 100% clean before anything ships.

**Reading order:** citations carrying filter annotations (`hearts_present`,
`profanity_soft`, `all_caps`) get read in full first. These annotations
prioritise attention; they do not decide the score. A heart-censored review is
usually ordinary frustrated swearing and passes. An unannotated review can
still fail.

**Blunt criticism is not a QR-4 failure.** Harsh, profane, or hostile reviews
about the game pass. The bar is content that harms the reader, not content
that is unkind about a product.

---

## Out of scope

**Tone alignment.** If a case seems to require judging whether the claim's
tone matches the citation's tone, stop — that is not what any of these checks
measure. `citation_verdict` already carries the citing reviews' overall
recommendation separately, and it deliberately answers a different question:
*did these reviewers recommend the game*, not *is this claim favourable*.
A veteran who describes frequent crashes and still recommends the game is not
a contradiction; that pattern is a finding, and flattening it into a
faithfulness penalty would destroy it.

**QR-3 — verdict-shape diversity.** Not scored per case. It is a whole-set
qualitative judgment made by reading all five seed verdicts and asking whether
they differ structurally rather than only in wording. Recorded in
`RESULTS.md` as pass/fail with a sentence of justification.

---

## Aggregation and reporting

Reported in `evals/RESULTS.md` (append-only), per run:

| Metric | Headline figure | Also record |
|---|---|---|
| QR-1 | % of cases scoring 2 | mean score across cases; count of 0s |
| QR-2 | % of cases scoring Y | which cases failed and their cohorts |
| QR-3 | pass / fail | one-sentence justification |
| QR-4 | pass / fail | any failing case ids |

Every row records the date, the extraction model, and the grounding
thresholds in force. A faithfulness score is meaningless without knowing which
model and which thresholds produced the claims being scored.

**Any 0 in QR-1 is worth reading individually**, regardless of the aggregate.
One hallucinated claim shipping to a buyer costs more trust than a two-point
average gain wins.

---

## Judge validation

This rubric is applied at scale by an LLM-as-judge. Before any judge output is
trusted, **10 cases are scored by hand against this document**, then compared
to the judge's scores on the same 10. The hand-scored set deliberately
includes 2–3 cases with a split `citation_verdict`, since those are where
human and judge readings diverge most.

Divergence is treated as a rubric-wording problem first, a judge-prompt
problem second. If a case is genuinely ambiguous under this document, the
document gets sharpened and the version number increments.

## Versioning

Changing any scoring definition here invalidates comparison against prior
`RESULTS.md` rows. Increment the version, note what changed, and re-run the
baseline before claiming any improvement.