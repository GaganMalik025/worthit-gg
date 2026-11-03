"""
Why do seed verdicts flip under GetAppReviews? Separates three causes that
compare_review_pools_2026-11-03.py could only report together.

  1. What the OLD `all` sweep actually held, read from the cached pages: how much of
     it overlapped `recent`, how far back it reached, how positive it was.
  2. What each NEW sweep holds on its own: recent, Helpful with no date limit, Updated.
  3. The verdict each combination computes. recent alone is the control: if it holds
     the published word, the second filter is what moved it, not three months of time.

Zero Gemini cost. Steam only, about 180 requests. Never writes to data/: the page
cache is a temp dir. Prints counts only, no review text.

    .venv/bin/python -B evals/decompose_review_pools_2026-11-03.py
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

# Pinned: this run measured the no-limit mapping, since rejected. Without this line
# a re-run would measure the shipped mapping and disagree with its recorded output.
fr.FILTER_PARAMS["all"] = {"filter": 0, "day_range": 0}

CFG = {"heart_density": 0.02, "min_words": 5, "funny_floor": 2, "alpha_ratio": 0.6,
       "repeat_ratio": 0.35}
terms = flt.load_terms(flt.WORDLIST_DIR / "block_en.txt")
blocked = flt.block_pattern(terms)
soft = flt.soft_pattern(flt.load_terms(flt.WORDLIST_DIR / "ldnoobw_en.txt"), set(terms))


def day(ts):
    return time.strftime("%Y-%m", time.gmtime(ts)) if ts else "-"


def describe(rows):
    if not rows:
        return "n=0"
    ts = [r["timestamp_created"] for r in rows]
    pos = sum(1 for r in rows if r["voted_up"])
    return "n=%-5d pos %5.1f%%  %s..%s" % (len(rows), 100.0 * pos / len(rows),
                                           day(min(ts)), day(max(ts)))


def cached(appid, name):
    out = {}
    for p in sorted(glob.glob("data/cache/%s/%s_*.json" % (appid, name))):
        for r in (json.load(open(p, encoding="utf-8")).get("response") or {}).get("reviews") or []:
            out[r["recommendationid"]] = r
    return out


def verdict_for(appid, filters):
    """The real sweep and selection, with the page cache kept in the temp dir."""
    real, sys.stdout = sys.stdout, open(os.devnull, "w")
    try:
        reviews, _, stats = fr.fetch_reviews(appid, target=400, filters=filters)
    finally:
        sys.stdout = real
    pool, kept = stats["pool"], {}
    for r in reviews:
        reason, _ = flt.classify(r, CFG, blocked, soft)
        kept[r["bucket"]] = kept.get(r["bucket"], 0) + (0 if reason else 1)
    cohorts = [{"bucket": b, "pool_n": st["pool_n"], "pct_positive": st["pct_positive"],
                "muted": kept.get(b, 0) < flt.MIN_COHORT}
               for b, st in pool["buckets"].items() if b != "unknown"]
    mean = sy.post_refund_mean(cohorts)
    return pool["pool_n"], mean, sy.verdict_for_mean(mean)


def sweep_rows(appid, name):
    seen, cursor = {}, "*"
    for page in range(12):
        data, _ = fr.fetch_page(appid, cursor, {"filter": name}, page_idx=page, sleep=1.0)
        for r in data.get("reviews") or []:
            seen[r["recommendationid"]] = r
        if not data.get("cursor") or data["cursor"] == cursor:
            break
        cursor = data["cursor"]
    return seen


flips = {}
with tempfile.TemporaryDirectory() as d:
    fr.CACHE_DIR = Path(d)
    for appid in fr.SEED_GAMES:
        pub = json.load(open("site/public/verdicts/%s.json" % appid, encoding="utf-8"))
        print("\n%s %s  published %s" % (appid, pub["game_name"], pub["verdict"]["word"]))
        old_recent, old_all = cached(appid, "recent"), cached(appid, "all")
        shared = len(set(old_recent) & set(old_all))
        print("  OLD recent  %s" % describe(list(old_recent.values())))
        print("  OLD all     %s  (%d of them also in old recent)"
              % (describe(list(old_all.values())), shared))
        rows = {n: sweep_rows(appid, n) for n in ("recent", "all", "updated")}
        print("  NEW recent  %s" % describe(list(rows["recent"].values())))
        print("  NEW Helpful %s  (%d also in new recent)"
              % (describe(list(rows["all"].values())),
                 len(set(rows["all"]) & set(rows["recent"]))))
        print("  NEW updated %s  (%d also in new recent)"
              % (describe(list(rows["updated"].values())),
                 len(set(rows["updated"]) & set(rows["recent"]))))
        for label, filters in (("recent only", ("recent",)),
                               ("recent+Helpful", ("recent", "all")),
                               ("recent+updated", ("recent", "updated"))):
            n, mean, word = verdict_for(appid, filters)
            same = word == pub["verdict"]["word"]
            flips[label] = flips.get(label, 0) + (not same)
            print("  %-15s pool %-5d post-refund mean %5.1f  %-5s%s"
                  % (label, n, mean or 0, word, "" if same else "  <-- FLIPPED"),
                  flush=True)

print("\nflips out of %d seeds: %s" % (len(fr.SEED_GAMES), json.dumps(flips)))
