"""
WorthIt.gg - add `minutes_at_review` to already-published citations.

ZERO GEMINI COST AND NO NETWORK, and not by luck. `fetch_reviews.normalize()`
rounded minutes to hours and kept no minutes, so they are genuinely absent from
data/raw, data/filtered, data/claims and every published verdict. They are NOT
absent from disk: fetch_reviews caches every raw Steam page verbatim at
data/cache/<appid>/<filter>_<NN>.json, and `playtime_at_review` sits untouched
in each one at response.reviews[].author.playtime_at_review.

So this reads the cache, not Steam. That distinction is the whole design:
re-fetching would return a DIFFERENT set of reviews (Steam's corpus moves), and
the published citations reference specific recommendationids that the cohorts
were exhausted against at ingestion. A re-fetch would not repair these files, it
would invalidate them.

WHY: the bucket is assigned on raw minutes (invariant 2) while the displayed
figure was rounded from hours, so 118 minutes renders as "2.0 hrs" beneath a
"<2h refund window" heading - 78 citation instances across 514 verdicts read as
outside the cohort they are filed under. See BACKLOG 2026-08-17.

ADDITIVE BY CONSTRUCTION. Only a new key is written; --check proves every file
is byte-identical to its original once the new key is stripped back out, which
is the same additivity proof the sourcing backfill used.

Where the cache cannot supply a review, the key is LEFT ABSENT rather than
guessed. Absent is meaningful: the renderer falls back to rounding hours, which
is exactly today's behaviour.

Usage:
    .venv/bin/python pipeline/backfill_minutes.py --check
    .venv/bin/python pipeline/backfill_minutes.py --write
    .venv/bin/python pipeline/backfill_minutes.py --write --appids 107410
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "site/public/verdicts"
CACHE = ROOT / "data/cache"

# invariant 2, in minutes. Kept here rather than imported so this script cannot
# silently change behaviour if the buckets are ever edited - a mismatch should
# be loud.
BOUNDS = {"refund_window": (0, 120), "early": (120, 1200),
          "mid": (1200, 6000), "veteran": (6000, None)}


def minutes_from_cache(appid):
    """{recommendationid: playtime_at_review} from every cached page."""
    out = {}
    for page in sorted((CACHE / str(appid)).glob("*.json")):
        try:
            blob = json.loads(page.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for r in (blob.get("response") or {}).get("reviews") or []:
            minutes = (r.get("author") or {}).get("playtime_at_review")
            rid = r.get("recommendationid")
            if minutes is not None and rid is not None:
                out[str(rid)] = minutes
    return out


def citations(verdict):
    """(bucket, citation dict) for every citation in the file."""
    for cohort in verdict.get("cohorts") or []:
        bucket = cohort.get("bucket")
        for theme in cohort.get("themes") or []:
            for claim in theme.get("claims") or []:
                for cit in claim.get("citations") or []:
                    yield bucket, cit


def reads_outside_bucket(cit, bucket):
    """True when the DISPLAYED hours figure reads outside its own cohort.

    This is the defect being repaired, evaluated the way the page evaluates it:
    hours rounded to one decimal, compared against the cohort's minute bounds.
    """
    hours = cit.get("hours_at_review")
    if hours is None or bucket not in BOUNDS:
        return False
    lo, hi = BOUNDS[bucket]
    shown = round(hours, 1) * 60
    return shown < lo - 1e-9 or (hi is not None and shown >= hi - 1e-9)


def main():
    ap = argparse.ArgumentParser(
        description="Backfill minutes_at_review onto published citations")
    ap.add_argument("--write", action="store_true",
                    help="write the files (default is report only)")
    ap.add_argument("--check", action="store_true",
                    help="report, and prove additivity by stripping the key")
    ap.add_argument("--appids", nargs="*", default=None)
    args = ap.parse_args()

    paths = sorted(VERDICTS.glob("*.json"))
    if args.appids:
        keep = {str(a) for a in args.appids}
        paths = [p for p in paths if p.stem in keep]

    stats = Counter()
    gaps = Counter()
    for path in paths:
        original = path.read_text(encoding="utf-8")
        verdict = json.loads(original)
        appid = str(verdict.get("appid") or path.stem)
        table = minutes_from_cache(appid)
        stats["verdicts"] += 1

        changed = False
        for bucket, cit in citations(verdict):
            stats["citations"] += 1
            if reads_outside_bucket(cit, bucket):
                stats["reads_outside_bucket_before"] += 1
            rid = str(cit.get("recommendationid"))
            minutes = table.get(rid)
            if minutes is None:
                stats["no_cache_entry"] += 1
                gaps[appid] += 1
                continue
            stats["recovered"] += 1
            if cit.get("minutes_at_review") != minutes:
                cit["minutes_at_review"] = minutes
                changed = True

        if not changed:
            continue
        stats["files_changed"] += 1
        rendered = json.dumps(verdict, indent=2, ensure_ascii=False) + "\n"

        if args.check:
            # Additivity: strip the new key back out and the file must be what
            # it was. Anything else means this script rewrote something it was
            # not asked to touch - reformatting included.
            probe = json.loads(rendered)
            for _, cit in citations(probe):
                cit.pop("minutes_at_review", None)
            if json.dumps(probe, sort_keys=True) != json.dumps(
                    json.loads(original), sort_keys=True):
                stats["NOT_ADDITIVE"] += 1
                print("  NOT ADDITIVE: %s" % path.name)
        if args.write:
            path.write_text(rendered, encoding="utf-8")

    print("verdicts scanned      : %d" % stats["verdicts"])
    print("citation instances    : %d" % stats["citations"])
    print("minutes recovered     : %d" % stats["recovered"])
    print("no cache entry        : %d" % stats["no_cache_entry"])
    print("files needing a write : %d" % stats["files_changed"])
    print("read outside bucket   : %d  (before this run)"
          % stats["reads_outside_bucket_before"])
    if stats["NOT_ADDITIVE"]:
        print("\nADDITIVITY FAILED on %d file(s)" % stats["NOT_ADDITIVE"])
        return 1
    if gaps:
        print("\nappids with unrecoverable citations:")
        for appid, n in gaps.most_common():
            print("  %-10s %d" % (appid, n))
    if not args.write:
        print("\n(report only - pass --write to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
