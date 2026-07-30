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

# cohort divergence: spread across the cohort sequence
DIVERGENCE_MIN_GAP = 25.0
DIVERGENCE_MIN_POOL_N = 30
# steps smaller than this are flat, not a trend
SHAPE_TOLERANCE = 3.0

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


def classify_shape(sequence):
    """Shape of sentiment across the cohort sequence, from every point in it.

    Reporting the widest pair as a trend is wrong and was actively misleading:
    Helldivers 2 runs 50 -> 88 -> 85 -> 66, so its widest pair (refund vs early)
    reads as "improves with playtime" while the actual finding is the opposite -
    it peaks early and falls away, with veterans nearly the unhappiest cohort.
    That inverted shape is the whole point of segmenting, so it gets named.

    Steps inside +/-TOLERANCE are treated as flat, so a 0.5-point wobble does
    not turn a consensus title into a trend.
    """
    rates = [pct for _, pct, _ in sequence]
    steps = [round(b - a, 1) for a, b in zip(rates, rates[1:])]
    ups = [s for s in steps if s > SHAPE_TOLERANCE]
    downs = [s for s in steps if s < -SHAPE_TOLERANCE]

    if not ups and not downs:
        return "flat", {}
    if ups and not downs:
        return "monotonic_increase", {}
    if downs and not ups:
        return "monotonic_decrease", {}

    i_peak = max(range(len(rates)), key=lambda i: rates[i])
    i_trough = min(range(len(rates)), key=lambda i: rates[i])
    detail = {}
    if 0 < i_peak < len(rates) - 1:
        shape = "rise_then_fall"
        after = min(range(i_peak, len(rates)), key=lambda i: rates[i])
        detail = {
            "peak_cohort": sequence[i_peak][0],
            "peak_pct_positive": rates[i_peak],
            "post_peak_low_cohort": sequence[after][0],
            "post_peak_low_pct_positive": rates[after],
            "drop_after_peak_pts": round(rates[i_peak] - rates[after], 1),
        }
    elif 0 < i_trough < len(rates) - 1:
        shape = "fall_then_rise"
        detail = {"trough_cohort": sequence[i_trough][0],
                  "trough_pct_positive": rates[i_trough]}
    else:
        shape = "mixed"
    return shape, detail


def _cohort_divergence(pool):
    buckets = pool.get("buckets") or {}
    # cohort order, not dict order - the sequence is the finding
    sequence = [(name, buckets[name]["pct_positive"], buckets[name]["pool_n"])
                for name in COHORT_LABELS
                if name in buckets
                and (buckets[name].get("pool_n") or 0) >= DIVERGENCE_MIN_POOL_N
                and buckets[name].get("pct_positive") is not None]
    if len(sequence) < 2:
        return None

    rates = [pct for _, pct, _ in sequence]
    gap = round(max(rates) - min(rates), 1)
    if gap < DIVERGENCE_MIN_GAP:
        return None

    shape, detail = classify_shape(sequence)
    i_low, i_high = rates.index(min(rates)), rates.index(max(rates))
    evidence = {
        "sequence": [{"cohort": n, "label": COHORT_LABELS.get(n, n),
                      "pct_positive": p, "pool_n": pn} for n, p, pn in sequence],
        "shape": shape,
        "low_cohort": sequence[i_low][0],
        "low_cohort_label": COHORT_LABELS.get(sequence[i_low][0]),
        "low_pct_positive": rates[i_low], "low_pool_n": sequence[i_low][2],
        "high_cohort": sequence[i_high][0],
        "high_cohort_label": COHORT_LABELS.get(sequence[i_high][0]),
        "high_pct_positive": rates[i_high], "high_pool_n": sequence[i_high][2],
        "gap_pts": gap,
    }
    evidence.update(detail)

    return {"flag_id": "cohort_divergence", "type": "segmentation",
            "shape": shape, "evidence": evidence}


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
    seq = " -> ".join("%s %.1f%% (pool_n %d)"
                      % (s["label"], s["pct_positive"], s["pool_n"])
                      for s in e["sequence"])
    head = "segmentation [%s], spread %.1f pts: %s" % (e["shape"], e["gap_pts"], seq)
    if e["shape"] == "rise_then_fall":
        head += ("; peaks at %s and falls %.1f pts to %s"
                 % (COHORT_LABELS.get(e["peak_cohort"], e["peak_cohort"]),
                    e["drop_after_peak_pts"],
                    COHORT_LABELS.get(e["post_peak_low_cohort"],
                                      e["post_peak_low_cohort"])))
    elif e["shape"] == "fall_then_rise":
        head += ("; troughs at %s"
                 % COHORT_LABELS.get(e["trough_cohort"], e["trough_cohort"]))
    return head


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
