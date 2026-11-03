"""
Runs the LLM judge on QR-6 (framing) for the cases the owner has scored, and compares.
The judge has never scored QR-6. Spends one Gemini call per case, booked to the batch
ledger. STATE-CHANGING: do not run it to read its usage.

The rubric goes verbatim, as in run_judge.py. The owner's "at least two" rule is applied
in code from per-citation answers rather than trusted to the model's arithmetic; its
holistic answer is kept beside it. The owner's scores are read only after the judge has
answered, and are never in the prompt.

    .venv/bin/python -u -B evals/run_judge_qr6_2026-11-03.py        # owner-scored cases
    .venv/bin/python -u -B evals/run_judge_qr6_2026-11-03.py --all  # the full 70
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "pipeline"))

import extract_claims as ec  # noqa: E402

SHEET = ROOT / "evals/hand-validation-round2.md"
OUT = ROOT / "evals/judge-qr6-2026-11-03.json"
MODEL, THINKING = ec.DEFAULT_MODEL, "low"

PREAMBLE = """\
You are applying a fixed scoring rubric to ONE test case. The complete rubric follows, \
reproduced verbatim. It is the only standard.

Operative for this case: "QR-6 - Framing" and nothing else. Every other section is context.

Report whether EACH citation frames the claim's topic the way the claim does ("match": \
"yes" or "no"), then your own overall answer, "pass" or "fail". One sentence of reasoning \
for every field.

--- BEGIN RUBRIC (evals/rubric.md) ---
%s
--- END RUBRIC ---
"""

SCHEMA = {
    "type": "object",
    "required": ["citations", "qr6", "reasoning"],
    "properties": {
        "citations": {"type": "array", "items": {
            "type": "object",
            "required": ["recommendationid", "match", "reasoning"],
            "properties": {"recommendationid": {"type": "string"},
                           "match": {"type": "string", "enum": ["yes", "no"]},
                           "reasoning": {"type": "string"}}}},
        "qr6": {"type": "string", "enum": ["pass", "fail"]},
        "reasoning": {"type": "string"},
    },
}


def owner_scores():
    out = {}
    text = SHEET.read_text("utf-8")
    for part in re.split(r"^## Case \d+ of 10: ", text, flags=re.M)[1:]:
        cid = re.match(r"`([^`]+)`", part).group(1)
        m = re.search(r"\*\*QR-6 \(pass or fail\):\*\*\s*(pass|fail)\s*$", part, re.M | re.I)
        if m:
            out[cid] = m.group(1).lower()
    return out


cases = {c["case_id"]: c for c in
         json.loads((ROOT / "evals/candidates.json").read_text("utf-8"))["cases"]}
ALL = "--all" in sys.argv
ids = sorted(cases) if ALL else sorted(owner_scores())   # which cases, not their scores
if ALL:
    OUT = ROOT / "evals/judge-qr6-all-2026-11-03.json"
rubric = (ROOT / "evals/rubric.md").read_text("utf-8")
assert "## QR-6" in rubric

ec.load_env()
from google import genai  # noqa: E402
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
os.environ["WORTHIT_LEDGER"] = "batch"

results = {}
for cid in ids:
    c = cases[cid]
    os.environ["WORTHIT_APPID"] = str(c["appid"])
    blocks = ["CASE %s\nGame: %s\nCohort: %s (%s)\n\nCLAIM: %s\n"
              % (cid, c["game_name"], c["cohort_label"], c["cohort_hours"], c["claim"])]
    for cit in c["citations"]:
        blocks.append("--- CITATION ---\nrecommendationid: %s\nthis reviewer's overall "
                      "verdict: %s\n\n%s\n"
                      % (cit["recommendationid"],
                         "recommend" if cit["voted_up"] else "not recommend",
                         (cit["review_text"] or "").strip()))
    resp = ec.call_model(client, MODEL, PREAMBLE % rubric, "\n".join(blocks),
                         schema=SCHEMA, thinking_level=THINKING)
    text, _ = ec.response_text(resp)
    parsed = json.loads(text)
    matches = sum(1 for x in parsed["citations"] if x.get("match") == "yes")
    results[cid] = {"rule": "pass" if matches >= 2 else "fail", "matches": matches,
                    "n": len(c["citations"]), "holistic": parsed["qr6"],
                    "reasoning": parsed["reasoning"], "citations": parsed["citations"]}
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), "utf-8")
    print("  judged %s" % cid, flush=True)

if ALL:
    fails = [c for c in ids if results[c]["rule"] == "fail"]
    print("\nQR-6 over all %d cases, >=2 rule: %d pass (%.1f%%), %d fail"
          % (len(ids), len(ids) - len(fails), 100.0 * (len(ids) - len(fails)) / len(ids),
             len(fails)))
    print("holistic pass: %d" % sum(results[c]["holistic"] == "pass" for c in ids))
    for c in fails:
        print("  FAIL %-22s %d of %d match | %s"
              % (c, results[c]["matches"], results[c]["n"], cases[c]["claim"][:90]))
    sys.exit(0)

owner = owner_scores()
print("\nQR-6, owner vs judge (n=%d)" % len(ids))
a = h = 0
for cid in ids:
    r = results[cid]
    a += owner[cid] == r["rule"]
    h += owner[cid] == r["holistic"]
    print("  %-22s you %-4s | >=2 rule %-4s (%d of %d match) | holistic %-4s%s"
          % (cid, owner[cid], r["rule"], r["matches"], r["n"], r["holistic"],
             "" if owner[cid] == r["rule"] else "   <-- DISAGREE"))
print("agreement: >=2 rule %d/%d, holistic %d/%d" % (a, len(ids), h, len(ids)))
