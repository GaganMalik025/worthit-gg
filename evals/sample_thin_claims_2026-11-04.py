"""
How common are claims that cite two reviews with fewer than two really supporting them?

The seed set showed 11 of 70 (RESULTS 2026-11-03). This estimates it across the catalog
from a seeded random sample of published claims. One Gemini call per claim, booked to
the batch ledger, stopping before the batch budget runs out. Reads site/public/verdicts
only and changes no verdict.

STATE-CHANGING: it spends quota. Do not run it to read its usage. --check stubs Gemini
and spends nothing.

    .venv/bin/python -u -B evals/sample_thin_claims_2026-11-04.py --check
    .venv/bin/python -u -B evals/sample_thin_claims_2026-11-04.py

The judge rates each citation "yes" or "no" on one question, in the words of rubric
QR-1: does this review state or clearly convey what the claim asserts? A claim is thin
when fewer than two citations get a "yes". That is a judge's reading, lightly validated
against the owner (6 of 6 on QR-1, n=6), so the result is an estimate of how often this
judge finds it, reported with its interval and without a correction.

Resumable: answers are written after each claim and a re-run skips them, so a crash or
a budget stop costs nothing already paid for.
"""

import glob
import json
import math
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "pipeline"))

import extract_claims as ec  # noqa: E402
import live_quota  # noqa: E402

SEED, N = 20261104, 300
OVERLOAD_WAITS = [120, 300, 600, 900]
MODEL, THINKING = ec.DEFAULT_MODEL, "low"
CHECK = "--check" in sys.argv
OUT = ROOT / "evals/thin-claims-sample-2026-11-04.json"

SYSTEM = """\
You check one claim from a game review summary against the reviews cited for it.

For EACH citation answer one question: does this review state or clearly convey what \
the claim asserts? Answer "yes" or "no". Judge meaning, not shared vocabulary: reviewers \
paraphrase. Answer "no" if the review only mentions the subject without saying what the \
claim says about it. Ignore tone, ignore whether the reviewer liked the game, and ignore \
anything the claim leaves out. Give one short sentence of reasoning for each citation.
"""

SCHEMA = {"type": "object", "required": ["citations"], "properties": {
    "citations": {"type": "array", "items": {
        "type": "object", "required": ["recommendationid", "supports", "reasoning"],
        "properties": {"recommendationid": {"type": "string"},
                       "supports": {"type": "string", "enum": ["yes", "no"]},
                       "reasoning": {"type": "string"}}}}}}


def wilson(k, n, z=1.96):
    """95% interval for a proportion, sound at small counts."""
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


claims = []
for path in sorted(glob.glob("site/public/verdicts/*.json")):
    v = json.loads(Path(path).read_text("utf-8"))
    for co in v["cohorts"]:
        for th in co["themes"]:
            for cl in th["claims"]:
                claims.append({"appid": str(v["appid"]), "game": v["game_name"],
                               "bucket": co["bucket"], "theme": th["theme"], "claim": cl})
print("catalog: %d claims" % len(claims))
assert len({(c["appid"], c["bucket"], c["claim"]["claim_id"]) for c in claims}) == len(claims)
sample = random.Random(SEED).sample(claims, N)

if CHECK:
    answers = {}
    OUT = Path(os.devnull)
    client = None
    def call(system, user, cit_ids):
        return {"citations": [{"recommendationid": i, "supports": "yes", "reasoning": "stub"}
                              for i in cit_ids]}
else:
    answers = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    ec.load_env()
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    os.environ["WORTHIT_LEDGER"] = "batch"
    def call(system, user, cit_ids):
        resp = ec.call_model(client, MODEL, system, user, schema=SCHEMA,
                             thinking_level=THINKING)
        text, _ = ec.response_text(resp)
        return json.loads(text)

stopped = False
for i, c in enumerate(sample):
    key = "%s|%s|%s" % (c["appid"], c["bucket"], c["claim"]["claim_id"])
    if key in answers:
        continue
    ok, why, _ = live_quota.can_batch(live_quota.load(), est=1)
    if not ok:
        print("BUDGET STOP at %d of %d: %s. Re-run after the reset to resume." % (i, N, why))
        stopped = True
        break
    os.environ["WORTHIT_APPID"] = c["appid"]
    cits = c["claim"]["citations"]
    user = "Game: %s\nCLAIM: %s\n\n%s" % (c["game"], c["claim"]["claim"], "\n".join(
        "--- CITATION ---\nrecommendationid: %s\n%s\n"
        % (x["recommendationid"], x["review_text"]) for x in cits))
    # call_model's own backoff gives up after about 30s, and each attempt is charged.
    # Gemini's "high demand" 503s last longer than that (they ended the first run on
    # its first claim), so wait in minutes here, then stop cleanly: answers are saved,
    # and a re-run resumes. Anything other than overload still raises.
    parsed = None
    for wait in OVERLOAD_WAITS + [None]:
        try:
            parsed = call(SYSTEM, user, [x["recommendationid"] for x in cits])
            break
        except Exception as exc:  # noqa: BLE001 - re-raised unless it is overload
            if not ("503" in str(exc) or "UNAVAILABLE" in str(exc)):
                raise
            if wait is None:
                break
            print("  overloaded at claim %d; waiting %ds" % (i, wait), flush=True)
            time.sleep(wait)
    if parsed is None:
        print("OVERLOAD STOP at %d of %d. Re-run later to resume." % (i, N), flush=True)
        stopped = True
        break
    cited = {x["recommendationid"] for x in cits}
    yes = {x["recommendationid"] for x in parsed["citations"]
           if x.get("supports") == "yes"} & cited
    answers[key] = {"appid": c["appid"], "game": c["game"], "bucket": c["bucket"],
                    "theme": c["theme"], "claim": c["claim"]["claim"], "n": len(cits),
                    "yes": len(yes), "citations": parsed["citations"]}
    OUT.write_text(json.dumps(answers, indent=1, ensure_ascii=False), "utf-8")
    if (i + 1) % 25 == 0:
        print("  %d of %d" % (i + 1, N), flush=True)

done = len(answers)
thin = [a for a in answers.values() if a["yes"] < 2]
print("\nclaims judged: %d of %d%s" % (done, N, " (STOPPED EARLY)" if stopped else ""))
if done:
    lo, hi = wilson(len(thin), done)
    print("thin (fewer than 2 citations support it): %d = %.1f%%, 95%% interval %.1f-%.1f%%"
          % (len(thin), 100.0 * len(thin) / done, lo, hi))
    for field in ("bucket", "theme"):
        counts = {}
        for a in answers.values():
            t = counts.setdefault(a[field], [0, 0])
            t[0] += a["yes"] < 2
            t[1] += 1
        print("  by %s: %s" % (field, ", ".join(
            "%s %d/%d" % (k, *v) for k, v in sorted(counts.items()))))
print("distinct titles in the sample: %d" % len({c["appid"] for c in sample}))
print("ledger batch_used %s" % live_quota.load().get("batch_used"))
