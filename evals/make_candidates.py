"""
WorthIt.gg - eval test-case candidates (build plan 2.1)

Joins the committed pipeline output into a fixed test set: each case is one
claim, the recommendationids it cites, and the FULL text of those reviews, so
QR-1 (faithfulness) and QR-2 (segment attribution) can be hand-scored without
opening the pipeline.

No network, no model, no cost. This is a join, not a generation step, and it is
deterministic: games in SEED_GAMES order, cohorts in BUCKETS order, claims in
the order extraction emitted them. Re-running produces a byte-identical file.

Contains NO rubric text, NO score fields and NO judge prompt. QR-1..4 wording is
authored by the owner at 2.2; even an empty scores placeholder here would
prejudge that schema.

Usage:
    .venv/bin/python evals/make_candidates.py --dry-run
    .venv/bin/python evals/make_candidates.py --print 3
    .venv/bin/python evals/make_candidates.py
"""

import argparse
import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from fetch_reviews import BUCKETS, SEED_GAMES        # noqa: E402  (invariant 2)
from synthesize import COHORT_LABELS, HOURS_RANGE    # noqa: E402

CLAIMS_DIR = ROOT / "data/claims"
FILTERED_DIR = ROOT / "data/filtered"
OUT_PATH = ROOT / "evals/candidates.json"


def build_cases(claims_dir, filtered_dir):
    cases, problems = [], []
    per_game_meta = {}

    for appid in SEED_GAMES:
        claims_path = Path(claims_dir) / ("%s.json" % appid)
        filtered_path = Path(filtered_dir) / ("%s.json" % appid)
        if not claims_path.exists():
            problems.append("missing claims file: %s" % claims_path)
            continue
        claims_blob = json.loads(claims_path.read_text(encoding="utf-8"))
        filtered = json.loads(filtered_path.read_text(encoding="utf-8"))
        corpus = {str(r["recommendationid"]): r for r in filtered.get("reviews", [])}
        muted = {b for b, st in
                 ((filtered.get("filter_report") or {}).get("by_bucket") or {}).items()
                 if st.get("muted")}
        game = claims_blob.get("game_name") or appid
        per_game_meta[appid] = {
            "game_name": game,
            "extraction_model": claims_blob.get("model"),
            "grounding": claims_blob.get("grounding"),
        }

        for bucket, _, _ in BUCKETS:
            bucket_claims = (claims_blob.get("claims_by_bucket") or {}).get(bucket) or []
            if bucket in muted and bucket_claims:
                # invariant 12: a muted cohort must carry no claims at all
                problems.append("%s/%s is muted but carries %d claims"
                                % (game, bucket, len(bucket_claims)))
            for claim in bucket_claims:
                citations = []
                for rid in claim.get("supporting_ids") or []:
                    rid = str(rid)
                    review = corpus.get(rid)
                    if review is None:
                        problems.append("%s/%s claim %s cites %s, absent from the "
                                        "filtered corpus"
                                        % (game, bucket, claim.get("claim_id"), rid))
                        continue
                    if review.get("bucket") != bucket:
                        # QR-2 in code: cited review must belong to the claimed cohort
                        problems.append("%s claim %s cites %s from cohort %s, not %s"
                                        % (game, claim.get("claim_id"), rid,
                                           review.get("bucket"), bucket))
                    created = review.get("created_ts")
                    citations.append(OrderedDict([
                        ("recommendationid", rid),
                        ("bucket", review.get("bucket")),
                        ("hours_at_review", review.get("hours_at_review")),
                        ("voted_up", review.get("voted_up")),
                        ("date", datetime.fromtimestamp(created, timezone.utc)
                            .strftime("%Y-%m-%d") if created else None),
                        ("annotations", review.get("annotations") or []),
                        ("review_text", review.get("review_text") or ""),
                    ]))

                if len(citations) < 2:
                    # invariant 3
                    problems.append("%s claim %s has %d resolvable citations"
                                    % (game, claim.get("claim_id"), len(citations)))

                cases.append(OrderedDict([
                    ("case_id", "%s-%s" % (appid, claim.get("claim_id"))),
                    ("appid", appid),
                    ("game_name", game),
                    ("cohort", bucket),
                    ("cohort_label", COHORT_LABELS.get(bucket, bucket)),
                    ("cohort_hours", HOURS_RANGE.get(bucket, bucket)),
                    ("claim_id", claim.get("claim_id")),
                    ("claim", claim.get("claim")),
                    ("theme", claim.get("theme")),
                    ("citation_verdict", claim.get("citation_verdict")),
                    ("citation_split", claim.get("citation_split")),
                    ("citations", citations),
                ]))

    ids = [c["case_id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        problems.append("duplicate case ids: %s" % ", ".join(sorted(dupes)))

    return cases, per_game_meta, problems


def distribution(cases):
    by_game, by_cohort, by_theme = OrderedDict(), OrderedDict(), OrderedDict()
    for c in cases:
        by_game[c["game_name"]] = by_game.get(c["game_name"], 0) + 1
        by_cohort[c["cohort"]] = by_cohort.get(c["cohort"], 0) + 1
        by_theme[c["theme"]] = by_theme.get(c["theme"], 0) + 1
    return {"by_game": by_game, "by_cohort": by_cohort, "by_theme": by_theme}


def print_report(cases, dist):
    total_cites = sum(len(c["citations"]) for c in cases)
    print("%d cases, %d citations (mean %.1f per case)"
          % (len(cases), total_cites, total_cites / len(cases) if cases else 0))

    print("\nby game:")
    for game, n in dist["by_game"].items():
        cohorts = OrderedDict()
        for c in cases:
            if c["game_name"] == game:
                cohorts[c["cohort"]] = cohorts.get(c["cohort"], 0) + 1
        print("  %-18s %3d  %4.1f%%   %s"
              % (game[:18], n, 100.0 * n / len(cases),
                 " ".join("%s:%d" % (b[:3], k) for b, k in cohorts.items())))
    print("\nby cohort: %s" % "  ".join("%s:%d" % kv for kv in dist["by_cohort"].items()))
    print("by theme : %s" % "  ".join("%s:%d" % kv for kv in dist["by_theme"].items()))


def print_cases(cases, n):
    for c in cases[:n]:
        print("\n" + "=" * 78)
        print("%s  [%s / %s]" % (c["case_id"], c["game_name"], c["cohort_label"]))
        print("theme=%s  cited reviewers: %d recommend / %d do not"
              % (c["theme"], c["citation_split"]["positive"],
                 c["citation_split"]["negative"]))
        print("\nCLAIM: %s" % c["claim"])
        for cit in c["citations"]:
            print("\n  --- %s | %s | %.1fh | %s | %s%s"
                  % (cit["recommendationid"], cit["bucket"],
                     cit["hours_at_review"] or 0.0,
                     "recommends" if cit["voted_up"] else "does not recommend",
                     cit["date"],
                     ("  [%s]" % ",".join(cit["annotations"]))
                     if cit["annotations"] else ""))
            print("  %s" % " ".join((cit["review_text"] or "").split()))


def main():
    ap = argparse.ArgumentParser(description="Build eval candidates (2.1)")
    ap.add_argument("--claims", default=str(CLAIMS_DIR))
    ap.add_argument("--filtered", default=str(FILTERED_DIR))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--print", dest="show", type=int, default=0,
                    help="print N cases as readable text")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases, meta, problems = build_cases(args.claims, args.filtered)
    dist = distribution(cases)
    print_report(cases, dist)

    if problems:
        print("\nINTEGRITY FAILURES (%d):" % len(problems))
        for p in problems:
            print("  ! %s" % p)
        print("\nnothing written - fix the pipeline output first")
        sys.exit(1)
    print("\nintegrity: all citations resolve, all in-cohort, all cases >=2 "
          "citations, no muted-cohort cases, ids unique")

    if args.show:
        print_cases(cases, args.show)

    if args.dry_run:
        print("\n(dry run - nothing written)")
        return

    models = sorted({m["extraction_model"] for m in meta.values() if m["extraction_model"]})
    grounding = next((m["grounding"] for m in meta.values() if m["grounding"]), None)
    payload = OrderedDict([
        ("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("n_cases", len(cases)),
        ("n_citations", sum(len(c["citations"]) for c in cases)),
        ("selection", "all claims surviving the 1.4 grounding check; no sampling"),
        ("source", OrderedDict([
            ("claims_dir", str(Path(args.claims).relative_to(ROOT)
                               if Path(args.claims).is_absolute() else args.claims)),
            ("filtered_dir", str(Path(args.filtered).relative_to(ROOT)
                                 if Path(args.filtered).is_absolute() else args.filtered)),
            ("extraction_model", models[0] if len(models) == 1 else models),
            ("grounding", grounding),
        ])),
        ("distribution", dist),
        ("cases", cases),
    ])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("\nwrote %d cases -> %s (%.0f KB)"
          % (len(cases), out, out.stat().st_size / 1024))


if __name__ == "__main__":
    main()
