"""
Compares the owner's scores in evals/hand-validation-2.4.md with the LLM judge's.
Refuses to run on an unfinished sheet, because a partial comparison would read as a
result. Writes nothing: the owner decides what goes in RESULTS.md.

    .venv/bin/python -B evals/compare_hand_validation.py [sheet] [--counts-only] [--allow-partial]

QR-6 (2026-11-16): when the sheet carries QR-6 lines, they are compared OFFLINE with
the judge's QR-6 run over all 70 cases (evals/judge-qr6-all-2026-11-03.json), so no
Gemini call is made. That run is a different invocation from the one round 2's first
six were compared against (evals/judge-qr6-2026-11-03.json), and the output names its
source.
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
QR6 = {}
for part in re.split(r"^## Case \d+ of 10: ", text, flags=re.M)[1:]:
    cid = re.match(r"`([^`]+)`", part).group(1)
    q1 = re.search(r"\*\*QR-1 score \(0, 1 or 2\):\*\*\s*([012])\s*$", part, re.M)
    q4 = re.search(r"\*\*QR-4 \(pass or fail\):\*\*\s*(pass|fail)\s*$", part, re.M | re.I)
    q6 = re.search(r"\*\*QR-6 \(pass or fail\):\*\*\s*(pass|fail)\s*$", part, re.M | re.I)
    QR6[cid] = q6 and q6.group(1).lower()
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

scored6 = [(cid, QR6[cid]) for cid, _, _ in rows if QR6.get(cid)]
if scored6:
    src = "evals/judge-qr6-all-2026-11-03.json"
    j6 = json.loads((ROOT / src).read_text("utf-8"))
    a_rule = a_hol = 0
    lines6 = []
    for cid, mine in scored6:
        s = j6[cid]
        a_rule += mine == s["rule"]
        a_hol += mine == s["holistic"]
        lines6.append("%-28s you %s | >=2 rule %s (%s of %s match) | holistic %s%s"
                      % (cid, mine, s["rule"], s["matches"], s["n"], s["holistic"],
                         "" if mine == s["rule"] else "   <-- DISAGREE"))
    print("\nQR-6, owner vs judge (n=%d; judge source %s)" % (len(scored6), src))
    if "--counts-only" not in sys.argv:
        print("\n".join(lines6))
    print("QR-6 agreement: >=2 rule %d/%d, holistic %d/%d"
          % (a_rule, len(scored6), a_hol, len(scored6)))
