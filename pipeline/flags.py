"""
WorthIt.gg - deterministic distortion flags (build plan 1.5)

Detection and every number are computed here, from the pool block. The model
only supplies a plain-language sentence, which is rendered beside these figures.
That keeps invariant 13 true by construction: a flag cannot cite a number the
model made up, because the model is never given one to repeat.

Flags describe the SHAPE of a distortion, never its cause. Naming why a game was
review-bombed is BACKLOG D8, deferred until interviews say it is worth the
accuracy risk.

WHY recency is measured against Steam's lifetime rate
-----------------------------------------------------
The obvious design - compare recent pool reviews against older pool reviews -
cannot work here, and the data says so plainly. Our pool is the newest ~1,200
reviews per filter, so its temporal reach is inversely proportional to the
game's review velocity:

    Cyberpunk 2077   2,078 pool reviews spanning 2026-06 .. 2026-07  (2 months)
    Stardew Valley   1,975                        2026-06 .. 2026-07
    Helldivers 2     1,930                        2026-06 .. 2026-07
    Kenshi           1,239                        2026-04 .. 2026-07
    Death Stranding  1,201                        2022-04 .. 2026-07  (4 years)

Four of five pools have no "older" side at all. So the comparison that carries
signal is our recent pool against Steam's lifetime score, which we already hold
from query_summary - and which is the one genuine population figure available.
Cyberpunk reads +8.7 points against its lifetime score: the patched-since story,
visible without ever sampling the launch era.

Within-pool corroboration is attached where the pool genuinely spans time
(Death Stranding), and omitted where it does not.
"""

# recency: pool-recent vs Steam lifetime
RECENCY_MIN_DELTA = 8.0
RECENCY_MIN_POOL_N = 150
# corroborating within-pool split only when there is a real older side
CORROBORATION_MIN_OLDER_N = 100

# cohort divergence: widest gap between two cohorts
DIVERGENCE_MIN_GAP = 25.0
DIVERGENCE_MIN_POOL_N = 30

COHORT_LABELS = {
    "refund_window": "under 2 hours",
    "early": "2-20 hours",
    "mid": "20-100 hours",
    "veteran": "over 100 hours",
}


def _recency_shift(pool):
    temporal = pool.get("temporal") or {}
    recent = temporal.get("recent") or {}
    steam_pct = pool.get("steam_pct_positive")
    recent_pct, recent_n = recent.get("pct_positive"), recent.get("pool_n") or 0

    if recent_pct is None or steam_pct is None or recent_n < RECENCY_MIN_POOL_N:
        return None
    delta = round(recent_pct - steam_pct, 1)
    if abs(delta) < RECENCY_MIN_DELTA:
        return None

    evidence = {
        "recent_pool_pct_positive": recent_pct,
        "recent_pool_n": recent_n,
        "recent_window_days": temporal.get("window_days"),
        "steam_lifetime_pct_positive": steam_pct,
        "steam_total_reviews": pool.get("steam_total_reviews"),
        "delta_pts": delta,
    }
    older = temporal.get("older") or {}
    if (older.get("pool_n") or 0) >= CORROBORATION_MIN_OLDER_N:
        evidence["within_pool_older_pct_positive"] = older.get("pct_positive")
        evidence["within_pool_older_n"] = older.get("pool_n")

    return {
        "flag_id": "recency_shift",
        "type": "recency",
        "direction": "improved" if delta > 0 else "declined",
        "evidence": evidence,
    }


def _cohort_divergence(pool):
    buckets = pool.get("buckets") or {}
    eligible = [(name, st) for name, st in buckets.items()
                if (st.get("pool_n") or 0) >= DIVERGENCE_MIN_POOL_N
                and st.get("pct_positive") is not None]
    if len(eligible) < 2:
        return None

    low = min(eligible, key=lambda kv: kv[1]["pct_positive"])
    high = max(eligible, key=lambda kv: kv[1]["pct_positive"])
    gap = round(high[1]["pct_positive"] - low[1]["pct_positive"], 1)
    if gap < DIVERGENCE_MIN_GAP:
        return None

    return {
        "flag_id": "cohort_divergence",
        "type": "segmentation",
        "direction": "widens_with_playtime"
                     if list(buckets).index(high[0]) > list(buckets).index(low[0])
                     else "narrows_with_playtime",
        "evidence": {
            "low_cohort": low[0], "low_cohort_label": COHORT_LABELS.get(low[0], low[0]),
            "low_pct_positive": low[1]["pct_positive"], "low_pool_n": low[1]["pool_n"],
            "high_cohort": high[0], "high_cohort_label": COHORT_LABELS.get(high[0], high[0]),
            "high_pct_positive": high[1]["pct_positive"], "high_pool_n": high[1]["pool_n"],
            "gap_pts": gap,
        },
    }


def detect(pool):
    """All flags that fire for this game, in display order."""
    return [f for f in (_cohort_divergence(pool), _recency_shift(pool)) if f]


def describe(flag):
    """One-line summary for pipeline output. The UI sentence comes from the model."""
    e = flag["evidence"]
    if flag["flag_id"] == "recency_shift":
        return ("recency: last %s days of the pool run %+.1f pts vs Steam lifetime "
                "(%.1f%% of %d pooled vs %.1f%% of %s lifetime)"
                % (e["recent_window_days"], e["delta_pts"],
                   e["recent_pool_pct_positive"], e["recent_pool_n"],
                   e["steam_lifetime_pct_positive"], e["steam_total_reviews"]))
    return ("segmentation: %s (%.1f%%, pool_n %d) vs %s (%.1f%%, pool_n %d), "
            "gap %.1f pts"
            % (e["low_cohort_label"], e["low_pct_positive"], e["low_pool_n"],
               e["high_cohort_label"], e["high_pct_positive"], e["high_pool_n"],
               e["gap_pts"]))


if __name__ == "__main__":
    import glob
    import json
    for path in sorted(glob.glob("data/raw/*.json")):
        blob = json.loads(open(path, encoding="utf-8").read())
        found = detect(blob.get("pool") or {})
        print("\n%s" % blob.get("game_name"))
        if not found:
            print("   no flags")
        for f in found:
            print("   %s" % describe(f))
