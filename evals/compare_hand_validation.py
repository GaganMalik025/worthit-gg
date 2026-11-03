"""
Compares the owner's scores in evals/hand-validation-2.4.md with the LLM judge's.
Refuses to run on an unfinished sheet, because a partial comparison would read as a
result. Writes nothing: the owner decides what goes in RESULTS.md.

    .venv/bin/python -B evals/compare_hand_validation.py [sheet] [--counts-only] [--allow-partial]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
sheet = Path(args[0]) if args else ROOT / "evals/hand-validation-2.4.md"
text = sheet.read_text(encoding="utf-8")

rows = []
for part in re.split(r"^## Case \d+ of 10: ", text, flags=re.M)[1:]:
    cid = re.match(r"`([^`]+)`", part).group(1)
    q1 = re.search(r"\*\*QR-1 score \(0, 1 or 2\):\*\*\s*([012])\s*$", part, re.M)
    q4 = re.search(r"\*\*QR-4 \(pass or fail\):\*\*\s*(pass|fail)\s*$", part, re.M | re.I)
    rows.append((cid, q1 and int(q1.group(1)), q4 and q4.group(1).lower()))

missing = [c for c, a, b in rows if a is None or b is None]
if len(rows) != 10 or (missing and "--allow-partial" not in sys.argv):
    sys.exit("sheet not finished: %d cases parsed, unscored: %s" % (len(rows), missing))
if missing:
    # Explicit, and printed, so a partial comparison cannot read as a full one.
    print("PARTIAL: %d of 10 scored. Unscored and excluded: %s\n"
          % (10 - len(missing), ", ".join(missing)))
    rows = [r for r in rows if r[0] not in missing]

judge = {s["case_id"]: s for s in
         json.loads((ROOT / "evals/judge_scores.json").read_text("utf-8"))["scores"]}
agree = agree_h = agree4 = 0
out = []
for cid, q1, q4 in rows:
    s = judge[cid]
    agree += q1 == s["qr1"]
    agree_h += q1 == s["qr1_judge"]
    agree4 += q4 == s["qr4"]
    out.append("%-28s you %d | >=2 rule %d | judge holistic %d | QR-4 you %s, judge %s%s"
               % (cid, q1, s["qr1"], s["qr1_judge"], q4, s["qr4"],
                  "" if q1 == s["qr1"] else "   <-- DISAGREE"))
if "--counts-only" not in sys.argv:
    print("\n".join(out) + "\n")
n = len(rows)
print("QR-1 agreement, published score (>=2 rule): %d/%d" % (agree, n))
print("QR-1 agreement, judge's holistic score    : %d/%d" % (agree_h, n))
print("QR-4 agreement                            : %d/%d" % (agree4, n))
