"""
Builds evals/hand-validation-round2.md: 10 cases drawn at RANDOM from the 60 the owner
has not seen, because the first sheet's judge scores have now been shown to them.
Random rather than selected, so unlike round 1 this also reads as a fair sample.

BLIND: never shows a judge score, and this script prints none. Selection only.

    .venv/bin/python -B evals/make_hand_validation_round2.py
"""

import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261104
OUT = ROOT / "evals/hand-validation-round2.md"

cases = {c["case_id"]: c for c in
         json.loads((ROOT / "evals/candidates.json").read_text("utf-8"))["cases"]}
seen = set(re.findall(r"^## Case \d+ of 10: `([^`]+)`",
                      (ROOT / "evals/hand-validation-2.4.md").read_text("utf-8"), re.M))
assert len(seen) == 10
pool = sorted(set(cases) - seen)
assert len(pool) == 60
picked = random.Random(SEED).sample(pool, 10)

L = ["# Hand validation, round 2", "",
     "Score each case using `evals/rubric.md`. Fill in the lines at the end of each "
     "case and leave everything else as it is.", "",
     "- **QR-1 asks only: do these reviews say this?** Ignore tone and anything the "
     "claim leaves out. That now belongs to QR-6.",
     "- **QR-6 asks your new question:** does the claim frame itself the way the "
     "review's gist does?", "",
     "**Do not open `evals/judge_scores.json` until you have finished.**", ""]
for n, cid in enumerate(picked, 1):
    c = cases[cid]
    L += ["---", "", "## Case %d of 10: `%s`" % (n, cid), "",
          "**Game:** %s  " % c["game_name"],
          "**Cohort:** %s (%s)" % (c["cohort_label"], c["cohort_hours"]), "",
          "**Claim:** %s" % c["claim"], ""]
    for i, cit in enumerate(c["citations"], 1):
        L += ["### Citation %d of %d" % (i, len(c["citations"])), "",
              "%s, %.1f hours at review, %s" % (
                  "recommends" if cit["voted_up"] else "does not recommend",
                  cit["hours_at_review"] or 0.0, cit["date"]), ""]
        L += ["> %s" % ln for ln in (cit["review_text"] or "").strip().splitlines()]
        L += [""]
    L += ["**QR-1 score (0, 1 or 2):** ___", "",
          "**QR-4 (pass or fail):** ___", "",
          "**QR-6 (pass or fail):** ___", "",
          "**Note, only if it was not obvious:** ___", ""]
OUT.write_text("\n".join(L), encoding="utf-8")
print("wrote %s: 10 cases, %d citations, %d words"
      % (OUT.relative_to(ROOT), sum(len(cases[c]["citations"]) for c in picked),
         len(" ".join(L).split())))
print("overlap with round 1: %d" % len(set(picked) & seen))
