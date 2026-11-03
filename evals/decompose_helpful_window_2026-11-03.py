"""
Is Helpful with Steam's DEFAULT day_range the real equivalent of the old `all` sweep?

decompose_review_pools_2026-11-03.py showed the old sweep reaching back only months,
and Helpful with day_range 0 reaching back to launch. This measures the candidate:
same selection and verdict computation, with fetch_reviews' "all" mapping overridden
in memory for this process only. Nothing on disk changes.

Zero Gemini cost. Never writes to data/: the page cache is a temp dir. Counts only.

    .venv/bin/python -B evals/decompose_helpful_window_2026-11-03.py
"""

import glob
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "pipeline"))

import fetch_reviews as fr  # noqa: E402
import filter_reviews as flt  # noqa: E402
import synthesize as sy  # noqa: E402

CFG = {"heart_density": 0.02, "min_words": 5, "funny_floor": 2, "alpha_ratio": 0.6,
       "repeat_ratio": 0.35}
terms = flt.load_terms(flt.WORDLIST_DIR / "block_en.txt")
blocked = flt.block_pattern(terms)
soft = flt.soft_pattern(flt.load_terms(flt.WORDLIST_DIR / "ldnoobw_en.txt"), set(terms))

fr.FILTER_PARAMS["all"] = {"filter": 0}   # day_range left at Steam's default of 30


def span(rows):
    if not rows:
        return "n=0"
    ts = [r["timestamp_created"] for r in rows]
    return "n=%-5d pos %5.1f%%  %s..%s" % (
        len(rows), 100.0 * sum(1 for r in rows if r["voted_up"]) / len(rows),
        time.strftime("%Y-%m", time.gmtime(min(ts))),
        time.strftime("%Y-%m", time.gmtime(max(ts))))


def old_all(appid):
    out = {}
    for p in glob.glob("data/cache/%s/all_*.json" % appid):
        for r in (json.load(open(p, encoding="utf-8")).get("response") or {}).get("reviews") or []:
            out[r["recommendationid"]] = r
    return list(out.values())


flips = 0
with tempfile.TemporaryDirectory() as d:
    fr.CACHE_DIR = Path(d)
    for appid in fr.SEED_GAMES:
        pub = json.load(open("site/public/verdicts/%s.json" % appid, encoding="utf-8"))
        real, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            reviews, _, stats = fr.fetch_reviews(appid, target=400)
        finally:
            sys.stdout = real
        new_all, cursor = {}, "*"
        for page in range(stats["pages_fetched"]["all"]):
            data, _ = fr.fetch_page(appid, cursor, {"filter": "all"}, page_idx=page)
            for r in data.get("reviews") or []:
                new_all[r["recommendationid"]] = r
            cursor = data.get("cursor") or cursor
        pool, kept = stats["pool"], {}
        for r in reviews:
            reason, _ = flt.classify(r, CFG, blocked, soft)
            kept[r["bucket"]] = kept.get(r["bucket"], 0) + (0 if reason else 1)
        cohorts = [{"bucket": b, "pool_n": st["pool_n"],
                    "pct_positive": st["pct_positive"],
                    "muted": kept.get(b, 0) < flt.MIN_COHORT}
                   for b, st in pool["buckets"].items() if b != "unknown"]
        mean = sy.post_refund_mean(cohorts)
        word = sy.verdict_for_mean(mean)
        same = word == pub["verdict"]["word"]
        flips += not same
        print("%-8s %-16s published %-5s" % (appid, pub["game_name"][:16], pub["verdict"]["word"]))
        print("  OLD all             %s" % span(old_all(appid)))
        print("  NEW Helpful default %s" % span(list(new_all.values())))
        print("  recent+Helpful default: pool %-5d mean %5.1f  %-5s%s"
              % (pool["pool_n"], mean or 0, word, "" if same else "  <-- FLIPPED"),
              flush=True)
print("\nflips: %d of %d" % (flips, len(fr.SEED_GAMES)))
