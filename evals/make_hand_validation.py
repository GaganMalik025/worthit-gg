"""
Builds evals/hand-validation-2.4.md, the sheet for BUILD_PLAN 2.4: the owner scores
10 cases by hand so the LLM judge's scores can be checked before they are trusted.

Selection (rubric "Judge validation", RESULTS 2026-07-31): the 6 cases where the >=2
rule and the judge's own holistic score disagreed, 3 with a split citation_verdict,
and 1 random from the rest. Shuffled with a fixed seed. BLIND: the sheet never shows a
judge score or says why a case was picked. Selection only; no rubric wording here.

    .venv/bin/python -B evals/make_hand_validation.py
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261103
OUT = ROOT / "evals/hand-validation-2.4.md"

scores = json.loads((ROOT / "evals/judge_scores.json").read_text("utf-8"))["scores"]
cases = {c["case_id"]: c for c in
         json.loads((ROOT / "evals/candidates.json").read_text("utf-8"))["cases"]}
rng = random.Random(SEED)

picked = [s["case_id"] for s in scores if s["qr1_rule_disagreement"]]
mixed = [s["case_id"] for s in scores
         if s.get("_citation_verdict_not_judged") == "mixed" and s["case_id"] not in picked]
rng.shuffle(mixed)
picked += mixed[:3]
rest = sorted(set(cases) - set(picked))
rng.shuffle(rest)
picked += rest[:10 - len(picked)]
assert len(picked) == len(set(picked)) == 10, picked
rng.shuffle(picked)

L = ["# Hand validation of the AI judge (BUILD_PLAN 2.4)", "",
     "Score each case using `evals/rubric.md`. Fill in the three lines at the end of "
     "each case and leave everything else as it is.", "",
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
          "**Note, only if it was not obvious:** ___", ""]
OUT.write_text("\n".join(L), encoding="utf-8")
print("wrote %s: 10 cases, %d citations"
      % (OUT.relative_to(ROOT), sum(len(cases[c]["citations"]) for c in picked)))
