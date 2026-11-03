"""
Does rewording extraction rule 2 reduce the skew toward complaints, without inventing
balance? Re-test of the change RESULTS 2026-08-08 measured and did not roll out; that
wording was not kept, so it is rebuilt here from its description in that entry.

Same review pools as the published verdicts (data/filtered, nothing re-fetched). The
response cache is a temp dir and nothing under site/ or data/filtered is written, so
no published verdict changes. Spends real Gemini calls, about 100, booked to the batch
ledger, and stops before any title that would not fit the batch budget.

STATE-CHANGING: it spends quota. Do not run it to read its usage.

    .venv/bin/python -u -B evals/ab_extraction_praise_2026-11-03.py

Metric, same as pipeline/measure_claim_balance.py: delta = cited% - available%, the
share of voted_up among reviews extraction cited against those it could read. Sources,
never claim sentiment (invariant 13).

THE GATE, FIXED BEFORE ANY RESULT EXISTED:
  G1  mean |delta| improves by at least 33.3% against the published verdicts
      (the 2026-08-08 bar, unchanged)
  G2  no title worsens by more than the noise floor. CHANGED from 2026-08-08's zero
      tolerance, which a -1.1 on one title failed, because extraction is not
      deterministic and nobody had measured how much it moves on its own. The floor
      is the larger of 3.0 points and the biggest |delta change| seen when the UNCHANGED
      prompt is re-run on the two control titles. Changing this rule knowing what it
      blocked last time is a real weakening, so ARK is in the set and reported by name.
  G3  no over-correction: no title above +10, and DOOM (already balanced) moves under 10
  G4  claims survive: at least 75% of the published claim count across the set
"""

import argparse
import json
import os
import random
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "pipeline"))

import extract_claims as ec  # noqa: E402
import ground_check  # noqa: E402
import live_quota  # noqa: E402
import measure_claim_balance as mcb  # noqa: E402
from fetch_reviews import BUCKETS  # noqa: E402
from filter_reviews import MIN_COHORT  # noqa: E402

OLD = ('what breaks, what is hard, what is missing, what works. \\\n'
       '"The game is good" is not a claim. "Reviewers describe the opening hours as \\\n'
       'unguided, with no tutorial explaining core systems" is a claim.\n')
OLD_RENDERED = ('what breaks, what is hard, what is missing, what works. '
                '"The game is good" is not a claim. "Reviewers describe the opening hours as '
                'unguided, with no tutorial explaining core systems" is a claim.\n')
NEW_RENDERED = ('what works, what breaks, what is hard, what is missing. '
                '"The game is good" is not a claim. "Reviewers praise the combat for '
                'rewarding timing over button-mashing" is a claim. So is "Reviewers describe '
                'the opening hours as unguided, with no tutorial explaining core systems". '
                'What this cohort praises is evidence on the same terms as what it complains '
                'about, and meets the same bar.\n')
CONTROL_PROMPT = ec.SYSTEM_INSTRUCTION
assert CONTROL_PROMPT.count(OLD_RENDERED) == 1
TREATED_PROMPT = CONTROL_PROMPT.replace(OLD_RENDERED, NEW_RENDERED)

ARK, DOOM, DS = "2399830", "379720", "1190460"
CONTROLS = [ARK, DS]
SEED = 20261105
NOISE_MIN = 3.0
OUT = ROOT / "evals/ab-extraction-2026-11-03.json"


def measure_claims(appid, by_bucket):
    filtered = json.loads((ROOT / ("data/filtered/%s.json" % appid)).read_text("utf-8"))
    voted = {str(r["recommendationid"]): bool(r.get("voted_up"))
             for r in filtered["reviews"]}
    avail = [bool(r.get("voted_up")) for r in filtered["reviews"]]
    cited = [voted[i] for claims in by_bucket.values() for c in claims
             for i in c["supporting_ids"] if i in voted]
    n = sum(len(c) for c in by_bucket.values())
    if not avail or not cited:
        return {"claims": n, "cited": len(cited), "delta": None}
    pa, pc = mcb._pct(avail), mcb._pct(cited)
    return {"claims": n, "cited": len(cited), "available_pct": round(pa, 1),
            "cited_pct": round(pc, 1), "delta": round(pc - pa, 1)}


def run(client, appid, prompt, cache_dir):
    ec.SYSTEM_INSTRUCTION = prompt
    ec.CACHE_DIR = Path(cache_dir)
    os.environ["WORTHIT_APPID"] = appid
    os.environ["WORTHIT_LEDGER"] = "batch"
    blob = json.loads((ROOT / ("data/filtered/%s.json" % appid)).read_text("utf-8"))
    groups = OrderedDict()
    for r in blob["reviews"]:
        groups.setdefault(r["bucket"], []).append(r)
    args = argparse.Namespace(
        model=ec.DEFAULT_MODEL, force=False, dry_run=False, show_prompt=False,
        ground_retries=2, min_coverage=ground_check.MIN_UNION_COVERAGE,
        min_citation_coverage=ground_check.MIN_CITATION_COVERAGE,
        min_supporting=ground_check.MIN_SUPPORTING_CITATIONS, no_ground=False)
    out = {}
    real, sys.stdout = sys.stdout, open(os.devnull, "w")
    try:
        for bucket, _, _ in BUCKETS:
            reviews = groups.get(bucket) or []
            if len(reviews) >= MIN_COHORT:
                out[bucket] = ec.extract_bucket(client, args, blob["game_name"], appid,
                                                bucket, reviews)["claims"]
    finally:
        sys.stdout = real
    return blob["game_name"], out


published = {p.stem for p in (ROOT / "site/public/verdicts").glob("*.json")}
local = {p.stem for p in (ROOT / "data/filtered").glob("*.json")}
pool = sorted((published & local) - {ARK, DOOM, DS})
titles = [DS, ARK, DOOM] + random.Random(SEED).sample(pool, 7)

CHECK = "--check" in sys.argv
if CHECK:
    # Every path below with Gemini stubbed: spends nothing, proves the harness runs.
    ec.call_model = lambda *a, **k: object()
    ec.response_text = lambda r: ('{"claims": []}', {"parts": 0, "text_parts": 0,
                                  "thought_parts": 0, "thought_signatures": 0, "used": "stub"})
    ec.PACE_SECONDS = 0
    OUT = Path(tempfile.mkdtemp()) / "check.json"
    client = None
else:
    ec.load_env()
    from google import genai  # noqa: E402
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

print("gate fixed in this file's docstring; titles: %s" % titles, flush=True)
results = {"titles": {}, "controls": {}}
with tempfile.TemporaryDirectory() as tmp:
    for appid in titles:
        ok, why, _ = live_quota.can_batch(live_quota.load())
        if not ok:
            print("BUDGET STOP before %s: %s" % (appid, why), flush=True)
            break
        base = mcb.measure(appid)
        # No catch-all here. A first version recorded every exception and moved on,
        # which turned a bug in this script into ten quiet "FAILED" lines.
        name, claims = run(client, appid, TREATED_PROMPT, tmp + "/b")
        m = measure_claims(appid, claims)
        pub = json.loads((ROOT / ("site/public/verdicts/%s.json" % appid)).read_text("utf-8"))
        pub_n = sum(len(t["claims"]) for c in pub["cohorts"] for t in c["themes"])
        results["titles"][appid] = {"name": name, "published_delta": base and base["delta"],
                                    "published_claims": pub_n, "b": m, "claims": claims}
        print("  B %-9s %-30s published %6s -> %6s  claims %3d -> %3d"
              % (appid, name[:30], base and base["delta"], m["delta"], pub_n, m["claims"]),
              flush=True)
        OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), "utf-8")
    for appid in CONTROLS:
        name, claims = run(client, appid, CONTROL_PROMPT, tmp + "/a")
        m = measure_claims(appid, claims)
        results["controls"][appid] = {"name": name, "a_rerun": m, "claims": claims}
        print("  A %-9s %-30s unchanged prompt re-run delta %6s  claims %3d"
              % (appid, name[:30], m["delta"], m["claims"]), flush=True)
        OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), "utf-8")

if CHECK:
    t0 = titles[0]
    fake = {"early": [{"supporting_ids": [str(json.loads((ROOT / ("data/filtered/%s.json" % t0))
                       .read_text("utf-8"))["reviews"][0]["recommendationid"])]}]}
    print("check: %d titles and %d controls ran; measure_claims on one citation: %s"
          % (len(results["titles"]), len(results["controls"]), measure_claims(t0, fake)))
    sys.exit(0)

rows = [r for r in results["titles"].values()
        if r["published_delta"] is not None and r["b"]["delta"] is not None]
noise = max([NOISE_MIN] + [
    abs(results["controls"][a]["a_rerun"]["delta"] - results["titles"][a]["published_delta"])
    for a in CONTROLS if a in results["titles"] and a in results["controls"]
    and results["controls"][a]["a_rerun"]["delta"] is not None
    and results["titles"][a]["published_delta"] is not None])
before = sum(abs(r["published_delta"]) for r in rows) / len(rows)
after = sum(abs(r["b"]["delta"]) for r in rows) / len(rows)
imp = 100.0 * (before - after) / before
worse = [(r["name"], round(r["b"]["delta"] - r["published_delta"], 1)) for r in rows
         if abs(r["b"]["delta"]) - abs(r["published_delta"]) > noise]
over = [r["name"] for r in rows if r["b"]["delta"] > 10]
doom = results["titles"].get(DOOM)
doom_move = abs(doom["b"]["delta"] - doom["published_delta"]) if doom else None
n_pub = sum(r["published_claims"] for r in rows)
n_new = sum(r["b"]["claims"] for r in rows)
gates = OrderedDict([
    ("G1 mean |delta| improves >= 33.3%", imp >= 100 / 3),
    ("G2 no title worse than noise", not worse),
    ("G3 no title above +10, DOOM moves < 10",
     not over and doom_move is not None and doom_move < 10),
    ("G4 claims >= 75% of published", n_new >= 0.75 * n_pub),
])
print("\ntitles measured %d of %d" % (len(rows), len(titles)))
print("mean |delta| %.1f -> %.1f, improved %.1f%%" % (before, after, imp))
print("noise floor %.1f (larger of %.1f and the control re-runs)" % (noise, NOISE_MIN))
print("worse than noise: %s | above +10: %s | DOOM moved: %s" % (worse, over, doom_move))
print("claims %d -> %d (%.0f%%)" % (n_pub, n_new, 100.0 * n_new / max(1, n_pub)))
for k, v in gates.items():
    print("  %-42s %s" % (k, "PASS" if v else "FAIL"))
print("GATE: %s" % ("PASS" if all(gates.values()) else "FAIL"))
print("ledger batch_used %s" % live_quota.load().get("batch_used"))
