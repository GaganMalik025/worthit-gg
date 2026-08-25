# Superseded audit rounds

Audit records that have been **replaced by a fresh draw**, kept because the
reasoning in BACKLOG is only checkable against the artifact it describes.

**Nothing in here is edited.** Both files are byte-identical to what was
committed on the day they were produced. The 2026-08-20 BACKLOG entry considered
correcting their headline counts in place and declined — that edits an audit
record after the fact — and prepending a pointer note would be the same move in
a smaller coat. The explanation lives here and in the superseding round instead.

They live in this subfolder rather than under a renamed suffix so they fall
**outside** the `evals/audit-4.4-*.md` glob. A future
`check_sample_overlap.py evals/audit-4.4-*.md` therefore cannot pick up rounds
whose duplicates are already known and explained, and report a failure that
history has already answered.

| file | round date | presents | actually audits | why superseded |
|---|---|---|---|---|
| `audit-4.4-live.md` | 2026-08-07 | 20 citations | **18 distinct** (`229019339`, `229669874` twice) | drawn with replacement |
| `audit-4.4-hades-hollowknight.md` | 2026-08-10 | 20 citations | **19 distinct** (`230859797` twice) | drawn with replacement |

Both predate `4d3f3c0` (2026-08-14), which gave `make_audit_sample.py` a `seen`
set of `recommendationid` and a `pool[b].pop()` draw. That is why they carry
duplicates and no dated round does — the batch rounds are clean by construction
rather than by luck. The two rounds also shared 2 reviews **with each other**,
which was never a sampler defect: both audit Hades, so their citation pools
overlap on all 40 of its cited reviews by construction.

**Superseded by `evals/audit-4.4-2026-08-25-reaudit.md`** — one combined round
over the three distinct titles (Hades `1145360`, GTA:SA Definitive `1547000`,
Hollow Knight `367520`), 20 slots and 20 distinct reviews. One round rather than
two precisely because of that shared-Hades overlap: re-auditing them separately
would have presented 40 slots and audited ~38 distinct reviews, a milder
instance of the defect being repaired.
