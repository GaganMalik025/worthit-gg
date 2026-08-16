"""
WorthIt.gg - per-cohort source delta, measured against what the PAGE shows.

`pipeline/measure_claim_balance.py` answers the extraction question: did the
model cite its cohort as it found it? Its baseline is `available%` - the
filtered survivors extraction could read.

This script answers the READER's question, which is a different one. Invariant
13 says every user-facing rate is a POOL figure, so the number printed above a
claim list is the cohort's `pct_positive` over `pool_n`, not the survivor rate.
The divergence a reader can actually see is therefore

    delta_pool = cited% - pct_positive        (page coherence)

and the sourcing skew that causes most of it is

    delta_avail = cited% - available%         (the 08-08 metric, reproduced)

Both are reported so the two are never confused. Citations are counted two
ways: instances (what measure_claim_balance counts) and DISTINCT
recommendationids (what "built from N reviews" means to a reader).

Counts SOURCES, never claims - invariant 13 forbids a per-claim valence.

Usage:
    .venv/bin/python evals/source_delta_report.py
    .venv/bin/python evals/source_delta_report.py --json out.json
"""

import argparse
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILTERED = ROOT / "data/filtered"
VERDICTS = ROOT / "site/public/verdicts"
BUCKETS = ("refund_window", "early", "mid", "veteran")


def cohort_rows(appid):
    fp, vp = FILTERED / ("%s.json" % appid), VERDICTS / ("%s.json" % appid)
    if not (fp.exists() and vp.exists()):
        return []
    filtered = json.loads(fp.read_text(encoding="utf-8"))
    verdict = json.loads(vp.read_text(encoding="utf-8"))

    avail = {}
    for r in filtered.get("reviews") or []:
        avail.setdefault(r.get("bucket"), []).append(bool(r.get("voted_up")))

    rows = []
    for cohort in verdict.get("cohorts") or []:
        b = cohort.get("bucket")
        seen, inst = {}, []
        n_claims = 0
        for theme in cohort.get("themes") or []:
            for claim in theme.get("claims") or []:
                n_claims += 1
                for c in claim.get("citations") or []:
                    up = bool(c.get("voted_up"))
                    inst.append(up)
                    seen[c.get("recommendationid")] = up
        a = avail.get(b, [])
        row = {
            "appid": str(appid),
            "game_name": verdict.get("game_name"),
            "word": (verdict.get("verdict") or {}).get("word"),
            "bucket": b,
            "muted": bool(cohort.get("muted")),
            "n_claims": n_claims,
            "pool_n": cohort.get("pool_n"),
            "pool_pct": cohort.get("pct_positive"),
            "n_available": len(a),
            "available_pct": round(100.0 * sum(a) / len(a), 1) if a else None,
            "n_cited_distinct": len(seen),
            "n_cited_instances": len(inst),
            "cited_pct": (round(100.0 * sum(seen.values()) / len(seen), 1)
                          if seen else None),
            "cited_pct_instances": (round(100.0 * sum(inst) / len(inst), 1)
                                    if inst else None),
        }
        if row["cited_pct"] is not None and row["pool_pct"] is not None:
            row["delta_pool"] = round(row["cited_pct"] - row["pool_pct"], 1)
        else:
            row["delta_pool"] = None
        if row["cited_pct"] is not None and row["available_pct"] is not None:
            row["delta_avail"] = round(
                row["cited_pct"] - row["available_pct"], 1)
        else:
            row["delta_avail"] = None
        rows.append(row)
    return rows


def summarise(vals, label):
    if not vals:
        print("%-22s (none)" % label)
        return
    print("%-22s n=%-4d mean %+6.1f  median %+6.1f  p10 %+6.1f  min %+6.1f"
          % (label, len(vals), st.mean(vals), st.median(vals),
             st.quantiles(vals, n=10)[0] if len(vals) > 1 else vals[0],
             min(vals)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    ids = sorted(p.stem for p in VERDICTS.glob("*.json"))
    rows = [r for a in ids for r in cohort_rows(a)]
    live = [r for r in rows if not r["muted"] and r["delta_pool"] is not None]

    print("verdicts read        : %d" % len(ids))
    print("cohort sections      : %d  (muted %d, unmuted-with-claims %d)"
          % (len(rows), sum(1 for r in rows if r["muted"]), len(live)))
    print()
    summarise([r["delta_pool"] for r in live], "delta vs pool")
    summarise([r["delta_avail"] for r in live
               if r["delta_avail"] is not None], "delta vs available")
    print()
    for t in (-40, -50, -60):
        n = sum(1 for r in live if r["delta_pool"] <= t)
        print("cohorts with delta_pool <= %d : %3d of %d (%.1f%%)"
              % (t, n, len(live), 100.0 * n / len(live)))
    print()
    print("distinct reviews behind a cohort's claim list:")
    ds = sorted(r["n_cited_distinct"] for r in live)
    print("  min %d  p10 %d  median %d  mean %.1f  max %d"
          % (ds[0], ds[max(0, len(ds) // 10)], st.median(ds),
             st.mean(ds), ds[-1]))
    for t in (5, 8, 10, 12):
        n = sum(1 for x in ds if x <= t)
        print("  <= %2d distinct reviews : %3d of %d (%.1f%%)"
              % (t, n, len(ds), 100.0 * n / len(ds)))

    print("\nworst %d cohorts by delta vs pool:" % args.top)
    print("%-9s %-34s %-13s %8s %8s %8s %7s %6s"
          % ("appid", "title", "cohort", "pool%", "cited%", "delta", "cited_n",
             "pool_n"))
    for r in sorted(live, key=lambda x: x["delta_pool"])[:args.top]:
        print("%-9s %-34s %-13s %7.1f%% %7.1f%% %+8.1f %7d %6d"
              % (r["appid"], (r["game_name"] or "?")[:34], r["bucket"],
                 r["pool_pct"], r["cited_pct"], r["delta_pool"],
                 r["n_cited_distinct"], r["pool_n"]))

    if args.json:
        Path(args.json).write_text(
            json.dumps({"cohorts": rows}, indent=2), encoding="utf-8")
        print("\nwrote %s" % args.json)


if __name__ == "__main__":
    main()
