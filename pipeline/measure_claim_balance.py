"""
WorthIt.gg - is the claim list as positive as the cohort it describes?

A reader sees the Split Bar say a cohort is 72% positive, then reads a claim
list sourced overwhelmingly from people who did not recommend the game. Nothing
on the page reconciles those, and until this script existed nothing measured it.

THE METRIC, and why it is this one
----------------------------------
For each cohort, compare like with like:

    available%  share of the reviews EXTRACTION COULD READ that are voted_up
                (the filtered survivors for that cohort)
    cited%      share of the reviews IT ACTUALLY CITED that are voted_up

    delta = cited% - available%

A delta near zero means extraction drew on the cohort as it found it. A large
negative delta means it reached disproportionately for the people who did not
recommend the game.

This is deliberately NOT a measure of claim sentiment. Invariant 13 is explicit
that there is no per-claim valence and nothing should add one: `citation_verdict`
is what the citing reviewers thought of the GAME, not of the claim, which is why
Kenshi's "the game features frequent bugs and technical jank" ships at 4u/1d. So
this counts SOURCES, never claims. It answers "whose reviews did we build this
from", which is a sampling question, and says nothing about what any claim says.

Baseline before the rule-2 rebalance (129 titles, 2026-08-08):
    92% of titles cited more negatively than their pool; mean delta -20.3.

Usage:
    .venv/bin/python pipeline/measure_claim_balance.py
    .venv/bin/python pipeline/measure_claim_balance.py --appids 2767030 3405340
    .venv/bin/python pipeline/measure_claim_balance.py --json out.json
"""

import argparse
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILTERED = ROOT / "data/filtered"
VERDICTS = ROOT / "site/public/verdicts"

BUCKETS = ("refund_window", "early", "mid", "veteran")
# Below this many reviews on either side the percentage is noise, and a cohort
# whose rate we would not show a reader (invariant 12) should not steer a
# measurement either.
MIN_AVAIL = 10
MIN_CITED = 5


def _pct(flags):
    return 100.0 * sum(flags) / len(flags) if flags else None


def measure(appid):
    """Per-cohort and whole-title sourcing balance, or None if unmeasurable."""
    fp, vp = FILTERED / ("%s.json" % appid), VERDICTS / ("%s.json" % appid)
    if not (fp.exists() and vp.exists()):
        return None
    try:
        filtered = json.loads(fp.read_text(encoding="utf-8"))
        verdict = json.loads(vp.read_text(encoding="utf-8"))
    except ValueError:
        return None

    avail, cited = {}, {}
    for r in filtered.get("reviews") or []:
        avail.setdefault(r.get("bucket"), []).append(bool(r.get("voted_up")))
    for cohort in verdict.get("cohorts") or []:
        for theme in cohort.get("themes") or []:
            for claim in theme.get("claims") or []:
                for c in claim.get("citations") or []:
                    cited.setdefault(cohort["bucket"], []).append(
                        bool(c.get("voted_up")))

    cohorts = []
    for b in BUCKETS:
        a, c = avail.get(b, []), cited.get(b, [])
        if len(a) < MIN_AVAIL or len(c) < MIN_CITED:
            continue
        pa, pc = _pct(a), _pct(c)
        cohorts.append({"bucket": b, "available_pct": round(pa, 1),
                        "cited_pct": round(pc, 1), "delta": round(pc - pa, 1),
                        "n_available": len(a), "n_cited": len(c)})

    all_a = [x for b in BUCKETS for x in avail.get(b, [])]
    all_c = [x for b in BUCKETS for x in cited.get(b, [])]
    if len(all_a) < MIN_AVAIL * 2 or len(all_c) < MIN_CITED * 2:
        return None
    pa, pc = _pct(all_a), _pct(all_c)
    return {"appid": str(appid), "game_name": verdict.get("game_name"),
            "verdict": (verdict.get("verdict") or {}).get("word"),
            "available_pct": round(pa, 1), "cited_pct": round(pc, 1),
            "delta": round(pc - pa, 1), "cohorts": cohorts}


def main():
    ap = argparse.ArgumentParser(description="Claim sourcing balance")
    ap.add_argument("--appids", nargs="*", default=None)
    ap.add_argument("--json", default=None, help="write full results here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    ids = args.appids or sorted(p.stem for p in VERDICTS.glob("*.json"))
    rows = [r for r in (measure(a) for a in ids) if r]
    if not rows:
        raise SystemExit("nothing measurable - need data/filtered/ and "
                         "site/public/verdicts/ for the same appids")

    if not args.quiet:
        print("%-9s %-38s %-5s %9s %9s %8s"
              % ("appid", "title", "word", "avail%", "cited%", "delta"))
        for r in sorted(rows, key=lambda x: x["delta"]):
            print("%-9s %-38s %-5s %8.1f%% %8.1f%% %+8.1f"
                  % (r["appid"], (r["game_name"] or "?")[:38], r["verdict"] or "?",
                     r["available_pct"], r["cited_pct"], r["delta"]))

    d = [r["delta"] for r in rows]
    worse = sum(1 for x in d if x < 0)
    print("\ntitles measured : %d" % len(rows))
    print("delta           : mean %+.1f  median %+.1f  min %+.1f  max %+.1f"
          % (st.mean(d), st.median(d), min(d), max(d)))
    print("mean |delta|    : %.1f" % st.mean(abs(x) for x in d))
    print("cited more negatively than the pool: %d of %d (%.0f%%)"
          % (worse, len(rows), 100.0 * worse / len(rows)))

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"titles": rows,
             "summary": {"n": len(rows), "mean_delta": round(st.mean(d), 2),
                         "mean_abs_delta": round(st.mean(abs(x) for x in d), 2),
                         "median_delta": round(st.median(d), 2),
                         "negative_titles": worse}},
            indent=2), encoding="utf-8")
        print("wrote %s" % args.json)


if __name__ == "__main__":
    main()
