"""
Does GetAppReviews describe the same games as the retired appreviews endpoint?

Two questions, kept apart because time passing and the API changing look identical:

  A. SAME WINDOW. For each seed, ask the new endpoint for the recent reviews inside
     the date window of the pages cached from the old one. Time is held fixed, so
     any gap is the API: what share of the old review ids come back?
  B. TODAY. Run the real sweep and selection, then compare pool rates and the
     computed verdict word against the committed pool and the published verdict.
     This mixes the API with three months of new reviews, and says so.

Zero Gemini cost. Steam only, about 180 requests at 1/s. Never writes to data/:
fetch_reviews' page cache is pointed at a temp dir, because data/cache holds the
only copy of the old pages. Prints counts and ids only, no review text.

    .venv/bin/python -B evals/compare_review_pools_2026-11-03.py
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

SEEDS = fr.SEED_GAMES
CFG = {"heart_density": 0.02, "min_words": 5, "funny_floor": 2, "alpha_ratio": 0.6,
       "repeat_ratio": 0.35}
terms = flt.load_terms(flt.WORDLIST_DIR / "block_en.txt")
blocked = flt.block_pattern(terms)
soft = flt.soft_pattern(flt.load_terms(flt.WORDLIST_DIR / "ldnoobw_en.txt"), set(terms))


def window_overlap(appid):
    old = {}
    for p in sorted(glob.glob("data/cache/%s/recent_*.json" % appid)):
        for r in (json.load(open(p, encoding="utf-8")).get("response") or {}).get("reviews") or []:
            old[r["recommendationid"]] = r
    if not old:
        return None
    ts = [r["timestamp_created"] for r in old.values()]
    lo, hi = min(ts), max(ts)
    seen, cursor, pages = {}, "*", 0
    while pages < 30:
        q = {"appid": int(appid), "cursor": cursor, "num_per_page": 100,
             "languages": ["english"], "purchase_type": 1, "review_type": 0,
             "filter": 1, "date_range_start": lo, "date_range_end": hi}
        d = fr._get_with_backoff(fr.ENDPOINT, {"input_json": json.dumps(q)},
                                 follow_redirects=False).json()["response"]
        pages += 1
        batch = d.get("reviews") or []
        if not batch:
            break
        for r in batch:
            seen[r["recommendationid"]] = r
        if not d.get("cursor") or d["cursor"] == cursor:
            break
        cursor = d["cursor"]
        time.sleep(1.0)
    shared = set(old) & set(seen)
    moved = sum(1 for i in shared
                if (old[i]["author"].get("playtime_at_review"), old[i]["voted_up"])
                != (seen[i]["author"].get("playtime_at_review"), seen[i]["voted_up"]))
    return {"old_ids": len(old), "new_ids": len(seen), "shared": len(shared),
            "pct_old_returned": round(100.0 * len(shared) / len(old), 1),
            "new_only": len(set(seen) - set(old)),
            "shared_with_changed_playtime_or_vote": moved, "pages": pages}


def today(appid, cache_dir):
    fr.CACHE_DIR = Path(cache_dir)
    reviews, summary, stats = fr.fetch_reviews(appid, target=400)
    pool = stats["pool"]
    kept = {}
    for r in reviews:
        reason, _ = flt.classify(r, CFG, blocked, soft)
        kept.setdefault(r["bucket"], 0)
        if not reason:
            kept[r["bucket"]] += 1
    cohorts = [{"bucket": b, "pool_n": pool["buckets"][b]["pool_n"],
                "pct_positive": pool["buckets"][b]["pct_positive"],
                "muted": kept.get(b, 0) < flt.MIN_COHORT}
               for b in pool["buckets"] if b != "unknown"]
    mean = sy.post_refund_mean(cohorts)
    return pool, cohorts, mean, sy.verdict_for_mean(mean), stats


print("A. SAME DATE WINDOW AS THE CACHED OLD PAGES (recent filter)")
for appid in SEEDS:
    print("  %-8s %s" % (appid, json.dumps(window_overlap(appid))), flush=True)

print("\nB. TODAY vs THE COMMITTED POOL AND PUBLISHED VERDICT")
print("   (mixes the API with ~3 months of new reviews)")
flips = 0
with tempfile.TemporaryDirectory() as d:
    for appid in SEEDS:
        raw = json.load(open("data/raw/%s.json" % appid, encoding="utf-8"))
        pub = json.load(open("site/public/verdicts/%s.json" % appid, encoding="utf-8"))
        real_stdout, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            pool, cohorts, mean, word, stats = today(appid, d)
        finally:
            sys.stdout = real_stdout
        old_cohorts = [{"bucket": c["bucket"], "pool_n": c["pool_n"],
                        "pct_positive": c["pct_positive"], "muted": c["muted"]}
                       for c in pub["cohorts"]]
        old_mean = sy.post_refund_mean(old_cohorts)
        print("\n  %s %s  pool %s -> %s  pages %s  steam_pct %s -> %s"
              % (appid, raw["game_name"], raw["pool"]["pool_n"], pool["pool_n"],
                 stats["pages_fetched"], raw["pool"]["steam_pct_positive"],
                 pool["steam_pct_positive"]))
        for c in cohorts:
            o = raw["pool"]["buckets"].get(c["bucket"], {})
            print("    %-14s n %5s -> %-5s pct %6s -> %-6s muted=%s"
                  % (c["bucket"], o.get("pool_n"), c["pool_n"],
                     o.get("pct_positive"), c["pct_positive"], c["muted"]))
        same = word == pub["verdict"]["word"]
        flips += not same
        print("    post-refund mean %.1f -> %.1f   word %s -> %s%s"
              % (old_mean or 0, mean or 0, pub["verdict"]["word"], word,
                 "" if same else "   <-- FLIPPED"), flush=True)
print("\nverdict words changed: %d of %d" % (flips, len(SEEDS)))
