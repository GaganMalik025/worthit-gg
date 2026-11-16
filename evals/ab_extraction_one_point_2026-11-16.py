"""
Does an extraction rule of "one point per claim, every detail stated by two cited
reviews" cut thin claims? The catalog sample found 72 of 300 claims with one citation
fully supporting them, often because a claim joins two reviewers' points
(RESULTS 2026-11-06).

Same review pools as the published verdicts (data/filtered). The response cache is a
temp dir and nothing under site/ is written, so no published verdict changes. Spends
real Gemini calls, about 280, booked to the batch ledger, stopping before any step that
would not fit the batch budget.

STATE-CHANGING: it spends quota. Do not run it to read its usage. --check stubs Gemini.

    .venv/bin/python -u -B evals/ab_extraction_one_point_2026-11-16.py --check
    .venv/bin/python -u -B evals/ab_extraction_one_point_2026-11-16.py

Thin is measured with the catalog sample's judge, unchanged: a claim is thin when fewer
than two of its citations fully convey it. Both arms are judged by it, so its strictness
on composite claims applies equally to both.

THE GATE, FIXED BEFORE ANY RESULT EXISTED:
  G1  the thin share falls by at least a third against the published claims of the same
      titles, AND by more than the noise seen when the UNCHANGED prompt is re-run on the
      two control titles
  G2  claims survive: at least 75% of the published count. Splitting composites should
      not need to cost more than that; a rule that passes by dropping claims has not
      fixed anything
  G3  the skew toward complaints gets no worse: mean |delta| (measure_claim_balance's
      metric) rises by no more than 3.0 points
"""

import argparse
import json
import os
import random
import sys
import tempfile
import time
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

CHECK = "--check" in sys.argv
SEED, N_TITLES, N_CONTROL = 20261116, 6, 2
OUT = ROOT / "evals/ab-extraction-one-point-2026-11-16.json"
EXCLUDE = {"1190460", "2399830", "379720", "1794680", "200210", "1506830", "493340",
           "207610", "524220", "2995920"}          # used by the 2026-11-03 A/B

OLD_RULE = ('4. Do not merge unrelated complaints into one claim. Prefer several precise '
            'claims over one broad one.\n')
NEW_RULE = ('4. One point per claim. Do not merge unrelated complaints into one claim, and '
            'do not join points made by different reviews: every detail a claim states '
            'must be stated by at least two of the reviews it cites. If only one review '
            'mentions a detail, leave that detail out. Prefer several precise claims over '
            'one broad one.\n')
CONTROL_PROMPT = ec.SYSTEM_INSTRUCTION
assert CONTROL_PROMPT.count(OLD_RULE) == 1, "rule 4 text moved; the A/B would be wrong"
TREATED_PROMPT = CONTROL_PROMPT.replace(OLD_RULE, NEW_RULE)

# The catalog sample's judge, verbatim (evals/sample_thin_claims_2026-11-04.py).
JUDGE_SYSTEM = """\
You check one claim from a game review summary against the reviews cited for it.

For EACH citation answer one question: does this review state or clearly convey what \
the claim asserts? Answer "yes" or "no". Judge meaning, not shared vocabulary: reviewers \
paraphrase. Answer "no" if the review only mentions the subject without saying what the \
claim says about it. Ignore tone, ignore whether the reviewer liked the game, and ignore \
anything the claim leaves out. Give one short sentence of reasoning for each citation.
"""
JUDGE_SCHEMA = {"type": "object", "required": ["citations"], "properties": {
    "citations": {"type": "array", "items": {
        "type": "object", "required": ["recommendationid", "supports", "reasoning"],
        "properties": {"recommendationid": {"type": "string"},
                       "supports": {"type": "string", "enum": ["yes", "no"]},
                       "reasoning": {"type": "string"}}}}}}
OVERLOAD_WAITS = [120, 300, 600, 900]

if CHECK:
    ec.call_model = lambda *a, **k: object()
    ec.response_text = lambda r: ('{"claims": []}', {"parts": 0, "text_parts": 0,
                                  "thought_parts": 0, "thought_signatures": 0, "used": "stub"})
    ec.PACE_SECONDS = 0
    OUT = Path(tempfile.mkdtemp()) / "check.json"
    client = None
else:
    ec.load_env()
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
os.environ["WORTHIT_LEDGER"] = "batch"


def budget_ok(need=1):
    ok, why, _ = live_quota.can_batch(live_quota.load(), est=need)
    if not ok:
        print("BUDGET STOP: %s. Re-run after the reset to resume." % why, flush=True)
        save()
        sys.exit(3)


def with_overload_retry(fn):
    for wait in OVERLOAD_WAITS + [None]:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised unless it is overload
            if not ("503" in str(exc) or "UNAVAILABLE" in str(exc)) or wait is None:
                raise
            print("  overloaded; waiting %ds" % wait, flush=True)
            time.sleep(wait)


def judge(appid, game, claim, citations):
    """Number of citations that fully convey the claim. One call."""
    if CHECK:
        return len(citations)
    budget_ok()
    os.environ["WORTHIT_APPID"] = appid
    user = "Game: %s\nCLAIM: %s\n\n%s" % (game, claim, "\n".join(
        "--- CITATION ---\nrecommendationid: %s\n%s\n" % (rid, text)
        for rid, text in citations))

    def call():
        resp = ec.call_model(client, ec.DEFAULT_MODEL, JUDGE_SYSTEM, user,
                             schema=JUDGE_SCHEMA, thinking_level="low")
        return json.loads(ec.response_text(resp)[0])
    parsed = with_overload_retry(call)
    cited = {rid for rid, _ in citations}
    return len({x["recommendationid"] for x in parsed["citations"]
                if x.get("supports") == "yes"} & cited)


def extract(appid, prompt, cache_dir):
    ec.SYSTEM_INSTRUCTION = prompt
    ec.CACHE_DIR = Path(cache_dir)
    os.environ["WORTHIT_APPID"] = appid
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
    for bucket, _, _ in BUCKETS:
        reviews = groups.get(bucket) or []
        if len(reviews) >= MIN_COHORT:
            budget_ok(3)
            real, sys.stdout = sys.stdout, open(os.devnull, "w")
            try:
                out[bucket] = with_overload_retry(lambda: ec.extract_bucket(
                    client, args, blob["game_name"], appid, bucket, reviews))["claims"]
            finally:
                sys.stdout = real
    return blob, out


def text_for(blob):
    """Citation text exactly as a verdict would carry it (synthesize.build_citation)."""
    out = {}
    for r in blob["reviews"]:
        t = r.get("review_text") or ""
        out[str(r["recommendationid"])] = (t[:2000] + "…") if len(t) > 2000 else t
    return out


def balance(appid, by_bucket):
    filtered = json.loads((ROOT / ("data/filtered/%s.json" % appid)).read_text("utf-8"))
    voted = {str(r["recommendationid"]): bool(r.get("voted_up")) for r in filtered["reviews"]}
    avail = list(voted.values())
    cited = [voted[i] for cl in by_bucket.values() for c in cl
             for i in c["supporting_ids"] if i in voted]
    if not avail or not cited:
        return None
    return round(mcb._pct(cited) - mcb._pct(avail), 1)


def judge_arm(appid, game, claims_by_bucket, texts):
    rows = []
    for bucket, claims in claims_by_bucket.items():
        for c in claims:
            cits = [(i, texts[i]) for i in c["supporting_ids"] if i in texts]
            rows.append({"bucket": bucket, "claim": c["claim"], "n": len(cits),
                         "yes": judge(appid, game, c["claim"], cits)})
    return rows


results = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"titles": {}, "controls": {}}


def save():
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), "utf-8")


published = {p.stem for p in (ROOT / "site/public/verdicts").glob("*.json")}
local = {p.stem for p in (ROOT / "data/filtered").glob("*.json")}
pool = sorted((published & local) - EXCLUDE)
titles = random.Random(SEED).sample(pool, N_TITLES)
controls = titles[:N_CONTROL]
print("titles %s, controls %s" % (titles, controls), flush=True)

with tempfile.TemporaryDirectory() as tmp:
    for appid in titles:
        if appid in results["titles"]:
            continue
        pub = json.loads((ROOT / ("site/public/verdicts/%s.json" % appid)).read_text("utf-8"))
        old = {}
        for co in pub["cohorts"]:
            for t in co["themes"]:
                for cl in t["claims"]:
                    old.setdefault(co["bucket"], []).append(
                        {"claim": cl["claim"],
                         "supporting_ids": [c["recommendationid"] for c in cl["citations"]]})
        blob, new = extract(appid, TREATED_PROMPT, tmp + "/b")
        texts = text_for(blob)
        results["titles"][appid] = {
            "game": blob["game_name"],
            "published": judge_arm(appid, blob["game_name"], old, texts),
            "treated": judge_arm(appid, blob["game_name"], new, texts),
            "published_delta": balance(appid, old), "treated_delta": balance(appid, new)}
        save()
        r = results["titles"][appid]
        print("  %-9s %-28s thin published %d/%d -> treated %d/%d"
              % (appid, blob["game_name"][:28],
                 sum(x["yes"] < 2 for x in r["published"]), len(r["published"]),
                 sum(x["yes"] < 2 for x in r["treated"]), len(r["treated"])), flush=True)
    for appid in controls:
        if appid in results["controls"]:
            continue
        blob, rerun = extract(appid, CONTROL_PROMPT, tmp + "/a")
        results["controls"][appid] = {
            "rerun": judge_arm(appid, blob["game_name"], rerun, text_for(blob))}
        save()
        r = results["controls"][appid]["rerun"]
        print("  control %-9s unchanged prompt re-run thin %d/%d"
              % (appid, sum(x["yes"] < 2 for x in r), len(r)), flush=True)

if CHECK:
    print("check: %d titles and %d controls ran end to end, nothing spent"
          % (len(results["titles"]), len(results["controls"])))
    sys.exit(0)


def share(rows):
    return 100.0 * sum(r["yes"] < 2 for r in rows) / len(rows) if rows else 0.0


pub_rows = [x for t in results["titles"].values() for x in t["published"]]
new_rows = [x for t in results["titles"].values() for x in t["treated"]]
p, n = share(pub_rows), share(new_rows)
noise = max(abs(share(results["controls"][a]["rerun"]) - share(results["titles"][a]["published"]))
            for a in controls)
deltas = [(t["published_delta"], t["treated_delta"]) for t in results["titles"].values()
          if t["published_delta"] is not None and t["treated_delta"] is not None]
skew_before = sum(abs(a) for a, _ in deltas) / len(deltas)
skew_after = sum(abs(b) for _, b in deltas) / len(deltas)
gates = OrderedDict([
    ("G1 thin share falls by a third, beyond noise", n <= p * 2 / 3 and p - n > noise),
    ("G2 claims >= 75% of published", len(new_rows) >= 0.75 * len(pub_rows)),
    ("G3 skew no worse than +3.0", skew_after - skew_before <= 3.0),
])
print("\nthin share: published %.1f%% (%d claims) -> treated %.1f%% (%d claims)"
      % (p, len(pub_rows), n, len(new_rows)))
print("control noise (unchanged prompt re-run vs published): %.1f points" % noise)
print("skew mean |delta|: %.1f -> %.1f" % (skew_before, skew_after))
for k, v in gates.items():
    print("  %-46s %s" % (k, "PASS" if v else "FAIL"))
print("GATE: %s" % ("PASS" if all(gates.values()) else "FAIL"))
print("ledger batch_used %s" % live_quota.load().get("batch_used"))
