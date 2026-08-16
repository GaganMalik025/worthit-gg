"""
WorthIt.gg - the cohort sourcing block: thresholds, and freshness on disk

WHY IT EXISTS. `pipeline/sourcing.py` decides, per cohort, whether the page
says "the points below come from the reviews that described something specific"
or adds an escalation clause on top. Two ways that goes wrong silently:

  * THE THRESHOLDS DRIFT. ALPHA is a frozen Bonferroni constant (0.05/1077,
    the family of cohort sections measured on 2026-08-17) and THIN_MAX_REVIEWS
    is the p10 of the measured distribution. Both are the kind of number a
    later reader rounds off - 5e-5 "is basically the same", 5 reviews "is
    tidier" - and nothing about the page would look broken afterwards. The
    boundary tests below straddle each threshold, so a moved constant fails
    rather than quietly reclassifying sections.

  * THE BLOCK GOES STALE. It is computed once, at assemble time, from the
    citations in that verdict. Re-extract a title and its claims change, its
    citations change, and a block written before that re-extraction now
    describes a claim list that no longer exists - while still rendering with
    total confidence. Backfills have the same hazard in reverse. So the last
    test recomputes every block from the citations in its OWN file and demands
    they agree; there is no way for the shipped artifact to disagree with its
    own contents and stay green.

The disclosure being numberless is pinned on the render side, where the risk
actually lives: site/lib/__tests__/sourcing-disclosure.contract.test.tsx.

Offline: committed artifacts only, no Steam, no Gemini, no quota.

    .venv/bin/python pipeline/test_sourcing_contract.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backfill_sourcing              # noqa: E402
import sourcing as sourcing_mod       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "site/public/verdicts"

PASSED = []
FAILED = []


def check(label, cond, detail=""):
    (PASSED if cond else FAILED).append(label)
    print("  %s %s%s" % ("ok  " if cond else "FAIL", label,
                         "" if cond else "  <- %s" % detail))


def cohort(pool_pct, citations, muted=False, claims=None):
    """A cohort section shaped exactly as assemble() builds it.

    `citations` is a list of (recommendationid, voted_up) placed on one claim
    unless `claims` splits them across several.
    """
    if claims is None:
        claims = [citations]
    return {
        "bucket": "veteran", "label": "100h+", "hours_range": "100+ hours",
        "pool_n": 400, "pct_positive": pool_pct, "muted": muted,
        "n_note": None, "summary": None,
        "themes": [{"theme": "content", "claims": [
            {"claim_id": "v-%d" % i, "claim": "a claim",
             "citation_verdict": "mixed",
             "citation_split": {"positive": 0, "negative": 0},
             "citations": [{"recommendationid": rid, "voted_up": up,
                            "hours_at_review": 120.0, "date": "2026-01-01",
                            "review_text": "text", "truncated": False}
                           for rid, up in cits]}
            for i, cits in enumerate(claims)]}],
    }


def test_constants_are_the_measured_ones():
    print("\nthe thresholds are the ones that were measured")
    check("ALPHA is 0.05 Bonferroni-corrected over the 1,077-section family",
          sourcing_mod.ALPHA == 0.05 / 1077 and sourcing_mod.FAMILY_SIZE == 1077,
          "alpha=%r family=%r" % (sourcing_mod.ALPHA, sourcing_mod.FAMILY_SIZE))
    check("THIN_MAX_REVIEWS is the p10 of the measured distribution (4)",
          sourcing_mod.THIN_MAX_REVIEWS == 4,
          "got %r" % sourcing_mod.THIN_MAX_REVIEWS)


def test_binomial_is_exact():
    print("\nthe binomial tail is exact and hand-checkable")
    p = sourcing_mod.divergence_p
    # 0 of 2 recommend against a 97.1% pool: 0.029^2.
    check("P(X<=0 | n=2, p=.971) == 0.029^2",
          abs(p(0, 2, 97.1) - 0.029 ** 2) < 1e-12,
          "got %r" % p(0, 2, 97.1))
    check("P(X<=n | n, p) == 1", abs(p(5, 5, 80.0) - 1.0) < 1e-12)
    check("the tail grows with k",
          p(0, 10, 90.0) < p(1, 10, 90.0) < p(2, 10, 90.0))
    check("no cited reviews yields None, never a number",
          p(0, 0, 90.0) is None)
    check("no pool rate yields None", p(0, 5, None) is None)
    check("a 100% pool makes any dissent impossible, not merely unlikely",
          p(0, 3, 100.0) == 0.0)


def test_thin_boundary():
    print("\nthin fires at 4 distinct reviews and not at 5")
    # Every citation recommends, so the lower tail sits at ~1 on both sides and
    # the divergent rule cannot fire and confound the boundary being tested.
    at = sourcing_mod.sourcing_block(
        cohort(90.0, [("r%d" % i, True) for i in range(4)]))
    above = sourcing_mod.sourcing_block(
        cohort(90.0, [("r%d" % i, True) for i in range(5)]))
    check("4 distinct cited reviews is thin",
          at["triggers"] == ["thin"] and at["level"] == "escalated",
          "got %r" % at)
    check("5 distinct cited reviews is not",
          above["triggers"] == [] and above["level"] == "baseline",
          "got %r" % above)


def test_divergent_boundary():
    print("\ndivergent straddles ALPHA, on a pair 1.3e-5 apart")
    # 0 of 7 recommend. n=7 keeps the thin rule out of it entirely.
    #   pool 76.0 -> 0.240^7 = 4.5865e-05  <  ALPHA = 4.6425e-05   fires
    #   pool 75.0 -> 0.250^7 = 6.1035e-05  >  ALPHA                does not
    cits = [("r%d" % i, False) for i in range(7)]
    below = sourcing_mod.sourcing_block(cohort(76.0, cits))
    above = sourcing_mod.sourcing_block(cohort(75.0, cits))
    check("just inside ALPHA escalates",
          below["triggers"] == ["divergent"] and below["level"] == "escalated",
          "p=%r triggers=%r" % (below["divergence_p"], below["triggers"]))
    check("just outside ALPHA does not",
          above["triggers"] == [] and above["level"] == "baseline",
          "p=%r triggers=%r" % (above["divergence_p"], above["triggers"]))
    check("and the pair really does straddle the constant",
          sourcing_mod.divergence_p(0, 7, 76.0) < sourcing_mod.ALPHA
          < sourcing_mod.divergence_p(0, 7, 75.0))


def test_divergence_is_one_sided():
    print("\nonly the negative direction escalates - the copy depends on it")
    # 12 of 12 cited reviews recommend, against a 30% pool: as extreme as the
    # catalog gets in the OTHER direction. The page says "leaning more
    # negative" whenever `divergent` fires, so this rule must never fire here.
    block = sourcing_mod.sourcing_block(
        cohort(30.0, [("r%d" % i, True) for i in range(12)]))
    check("an overwhelmingly positive cited sample never escalates",
          "divergent" not in block["triggers"],
          "got %r" % block)
    check("...and its tail probability is at the top of the range, not the bottom",
          block["divergence_p"] > 0.99, "got %r" % block["divergence_p"])


def test_counts_distinct_reviewers():
    print("\na reviewer cited by three claims is one reviewer")
    # 77.3% of real cohorts reuse a citation across claims, so this is the
    # normal case, not an edge one. 3 claims, same 4 reviews on each: 12
    # citation instances, 4 people -> thin.
    same = [("r%d" % i, False) for i in range(4)]
    block = sourcing_mod.sourcing_block(cohort(90.0, None, claims=[same, same, same]))
    check("12 citation instances over 4 reviewers counts 4",
          block["cited_reviews"] == 4, "got %r" % block["cited_reviews"])
    check("and is therefore thin", "thin" in block["triggers"])


def test_nothing_below_means_no_note():
    print("\nno block where nothing renders beneath the heading")
    muted = sourcing_mod.sourcing_block(
        cohort(90.0, [("r1", True), ("r2", True)], muted=True))
    empty = dict(cohort(90.0, [("r1", True)]))
    empty["themes"] = []
    check("a muted cohort gets no block (invariant 12 owns that section)",
          muted is None)
    check("an unmuted cohort whose claims all dropped gets no block",
          sourcing_mod.sourcing_block(empty) is None)


def test_published_verdicts_match_their_own_citations():
    print("\nevery published block still describes the claims in its own file")
    files = sorted(VERDICTS.glob("*.json"))
    stale, blocks = [], 0
    for path in files:
        verdict = json.loads(path.read_text(encoding="utf-8"))
        for bucket, stored, computed in backfill_sourcing.recompute(verdict):
            if computed is not None:
                blocks += 1
            if stored != computed:
                stale.append("%s/%s" % (path.stem, bucket))
    check("%d verdicts read, %d cohort blocks recomputed" % (len(files), blocks),
          len(files) > 0 and blocks > 0)
    check("no block disagrees with the citations beneath it",
          not stale, "stale: %s%s" % (", ".join(stale[:5]),
                                      " (+%d)" % (len(stale) - 5)
                                      if len(stale) > 5 else ""))


def main():
    print("=" * 68)
    print("cohort sourcing block - offline, committed artifacts only")
    print("=" * 68)
    test_constants_are_the_measured_ones()
    test_binomial_is_exact()
    test_thin_boundary()
    test_divergent_boundary()
    test_divergence_is_one_sided()
    test_counts_distinct_reviewers()
    test_nothing_below_means_no_note()
    test_published_verdicts_match_their_own_citations()
    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED: %s" % ", ".join(FAILED))
        return 1
    print("all sourcing contract tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
