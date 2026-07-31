"""
WorthIt.gg - automated QR-4 gate for live generation (CLAUDE.md invariant 8)

Invariant 8 makes QR-4 a launch gate: zero NSFW/slur-bearing reviews surfaced in
any citation, any failure blocks deploy. For the precomputed catalog that gate is
a human reading citations before a batch ships (BUILD_PLAN 4.4). Live generation
has no human in the loop, so the gate has to run in code, in-pipeline, BEFORE
anything renders.

The contract, from CLAUDE.md's guarded-live-generation section:

    If any citation fails, the verdict is NOT PUBLISHED. The title falls back to
    the request queue for manual audit and the user sees the queue copy. Nothing
    reaches a user that this gate has not passed.

WHY THIS IS NOT REDUNDANT WITH THE 1.2 CONTENT FILTER
-----------------------------------------------------
filter_reviews.py runs BEFORE extraction and drops unsafe reviews from the pool
the model reads. This runs AFTER synthesis, on the citations that will actually
render. They are different populations and the second one is the one a user sees.
A filter bug, a wordlist gap, or a future change to what synthesis carries
through would all be invisible to the pre-filter and caught here. Checking the
rendered artifact is the only check that speaks to what invariant 8 promises.

Deliberately conservative: this gate only ever REJECTS. It never edits, redacts
or truncates a citation to make it pass - a verdict is publishable as generated
or it is not publishable at all.

Usage:
    .venv/bin/python pipeline/qr4_gate.py site/public/verdicts/233860.json
    .venv/bin/python pipeline/qr4_gate.py --all
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from filter_reviews import (  # noqa: E402  (single source for the wordlists)
    WORDLIST_DIR,
    block_pattern,
    load_terms,
    normalize_for_match,
    soft_pattern,
)

ROOT = Path(__file__).resolve().parent.parent


def _patterns():
    blocked = load_terms(WORDLIST_DIR / "block_en.txt")
    soft = load_terms(WORDLIST_DIR / "ldnoobw_en.txt")
    return block_pattern(blocked), soft_pattern(soft, blocked)


def iter_citations(verdict):
    """Every citation that will render, with enough context to name it."""
    for cohort in verdict.get("cohorts") or []:
        for theme in cohort.get("themes") or []:
            for claim in theme.get("claims") or []:
                for cit in claim.get("citations") or []:
                    yield cohort.get("bucket"), claim.get("claim_id"), cit


def check_verdict(verdict, blocked_re=None):
    """(passed, failures, n_checked). A single failing citation fails the gate."""
    if blocked_re is None:
        blocked_re, _ = _patterns()

    failures, n = [], 0
    for bucket, claim_id, cit in iter_citations(verdict):
        n += 1
        text = cit.get("review_text") or ""
        hit = blocked_re.search(normalize_for_match(text))
        if hit:
            failures.append({
                "recommendationid": cit.get("recommendationid"),
                "bucket": bucket,
                "claim_id": claim_id,
                "term": hit.group(0),
            })
    return (not failures), failures, n


def gate(verdict, game_name=None):
    """Publish decision for one verdict. Returns (publish, report)."""
    passed, failures, n = check_verdict(verdict)
    report = {
        "gate": "QR-4",
        "citations_checked": n,
        "passed": passed,
        "failures": failures,
        "action": "publish" if passed else "withhold_and_queue",
        "reason": (
            "no citation matched the blocking wordlist"
            if passed else
            "%d citation(s) matched the blocking wordlist; the verdict is not "
            "published and the title is queued for manual audit" % len(failures)
        ),
    }
    if game_name:
        report["game_name"] = game_name
    return passed, report


def main():
    ap = argparse.ArgumentParser(description="Automated QR-4 gate (invariant 8)")
    ap.add_argument("paths", nargs="*", help="verdict JSON paths")
    ap.add_argument("--all", action="store_true",
                    help="every verdict in site/public/verdicts/")
    args = ap.parse_args()

    paths = [Path(p) for p in args.paths]
    if args.all:
        paths = sorted((ROOT / "site/public/verdicts").glob("*.json"))
    if not paths:
        ap.error("give verdict paths or --all")

    blocked_re, _ = _patterns()
    any_fail, total = False, 0
    for p in paths:
        v = json.loads(p.read_text(encoding="utf-8"))
        passed, failures, n = check_verdict(v, blocked_re)
        total += n
        any_fail |= not passed
        print("%-28s %4d citations  %s"
              % (v.get("game_name", p.stem), n, "PASS" if passed else "FAIL"))
        for f in failures:
            print("    ! %s (%s/%s) matched %r"
                  % (f["recommendationid"], f["bucket"], f["claim_id"], f["term"]))

    print("\n%d citations checked across %d verdicts -> %s"
          % (total, len(paths), "FAIL" if any_fail else "PASS"))
    if any_fail:
        print("invariant 8: failing verdicts must not publish")
        sys.exit(1)


if __name__ == "__main__":
    main()
