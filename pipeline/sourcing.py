"""
WorthIt.gg - per-cohort sourcing provenance (the B2 disclosure).

THE PROBLEM THIS DISCLOSES
--------------------------
A cohort section prints a pool recommend rate, then a claim list built from the
handful of reviews that said something specific. Those two do not have to agree,
and catalog-wide they usually do not. Measured 2026-08-17 over all 306 published
verdicts (`evals/source_delta_report.py`):

    1,077 unmuted cohort sections with claims
    cited-vs-pool delta   mean -22.6   median -20.2   p10 -53.1   min -97.1
    231 of 1,077 (21.4%) diverge by more than 40 points from the rate above them
    exactly 1 of 1,077 diverges by +40 the other way

So divergence is the NORMAL STATE, not the exception. That is why tier 1 below
is unconditional: a note that appeared only on the tail would tell a reader,
by its silence, that every other claim list was drawn representatively. It is
not.

WHAT THIS EMITS, AND WHAT RENDERS
---------------------------------
This module emits FACTS, not prose. The site owns the wording (DESIGN.md), the
same way it owns every other string on the page. Two fields drive rendering:

    level     "baseline" (tier 1, every unmuted cohort with claims)
              "escalated" (tier 2, one of the measured rules below fired)
    triggers  which rule(s) fired: "thin", "divergent"

INVARIANT 13, AND WHY THIS BLOCK CARRIES NUMBERS THAT NEVER RENDER
------------------------------------------------------------------
The disclosure is deliberately NUMBERLESS on the page (owner decision,
2026-08-17). DESIGN.md:238 calls the per-claim receipts tag "the one sanctioned
non-pool number on the page", and a cohort-level count would be a second one -
which needs an explicit DESIGN.md amendment as its own decision, not a
ride-along on this feature. Two further hazards it dodges by construction:
adjacency (a cited count printed under "based on 439 reviews" invites the
reader to compute 6/439, a prevalence inference from sample counts, which
invariant 11 forbids) and arithmetic (77.3% of cohorts cite some review from
more than one claim - 15,736 citation instances over 11,882 distinct
review-cohort pairs - so a distinct count is NOT the sum of the receipts tags
above it and cannot be described as one).

`cited_reviews`, `cited_recommend` and `divergence_p` are therefore PIPELINE
DIAGNOSTICS in the shipped JSON, on the same footing as every other post-filter
count invariant 13 keeps off the page. They exist so the contract test can
recompute them and so the thresholds stay auditable. **Nothing may render
them**, as a count, a rate, or a share. The `basis` string says so inside the
artifact itself.

THE TWO RULES, AND WHY THEY ARE TWO
-----------------------------------
thin       n distinct cited reviews <= 4. The p10 of the measured distribution
           (median 10, min 2). Fires on 11.0% of sections.

divergent  binomial lower tail P(X <= k) for k recommending reviews out of n
           cited, against the cohort's POOL rate - the number actually printed
           above the list - below ALPHA. Fires on 6.6%.

They overlap on exactly ONE section of 1,077 (thin-only 118, divergent-only 70).
That is not redundancy to collapse: a 4-review sample can almost never be
statistically extreme, and an extreme sample is usually well populated. One
rule would miss whichever half it was not built for. Union: 189 of 1,077
(17.5%), touching 140 of 306 titles.

THE NULL IS A DELIBERATE FICTION - read this before changing ALPHA.
Extraction does not sample randomly; it reaches for reviews that say something
specific and falsifiable. So this is not a hypothesis test with a meaningful
null, and no p-value here should ever be reported as evidence about the game.
It is a size-aware way of putting divergence and sample size on ONE scale, so
that Subnautica veteran (0 of 2 cited against a 97.1% pool) and Total War:
WARHAMMER III early (3 of 25 against 71.9%) are ranked by how hard they are to
explain rather than by raw delta, which calls them -97 and -60 in the wrong
order.
"""

import math

# 0.05 Bonferroni-corrected over the family of cohort sections that actually
# render: 1,077, measured across all 306 published verdicts on 2026-08-17.
#
# FROZEN ON PURPOSE - do not recompute this from the live catalog. A dynamic
# denominator would make one title's disclosure depend on how many OTHER titles
# exist, so publishing an unrelated batch would silently change what a
# already-published page says about itself. Re-derive it deliberately, with a
# fresh measurement and a RESULTS.md entry, the same way the verdict bands were.
FAMILY_SIZE = 1077
ALPHA = 0.05 / FAMILY_SIZE          # 4.6425e-05

# p10 of the measured distinct-cited-reviews distribution (median 10, min 2).
THIN_MAX_REVIEWS = 4

BASIS = ("pipeline diagnostic - counts of cited reviews, never rendered; "
         "see invariant 13")


def cited_reviews(cohort):
    """(distinct cited reviews, how many of them recommend the game).

    DISTINCT recommendationids, not citation instances: a review cited by three
    claims is one reviewer, and 77.3% of cohorts reuse at least one. Reads the
    assembled cohort section, so the pipeline, the backfill and the contract
    test all count the same thing the same way.
    """
    seen = {}
    for theme in cohort.get("themes") or []:
        for claim in theme.get("claims") or []:
            for cit in claim.get("citations") or []:
                seen[cit.get("recommendationid")] = bool(cit.get("voted_up"))
    return len(seen), sum(1 for up in seen.values() if up)


def divergence_p(k, n, pool_pct):
    """P(X <= k), X ~ Bin(n, pool_pct/100). Exact, no approximation.

    n is at most ~70 across the catalog, so the exact sum is cheap and avoids a
    normal approximation that would be worst exactly where it matters - small n
    against a pool rate near 1.

    Returns None when it cannot be computed rather than a sentinel number: no
    cited reviews, or a cohort with no pool rate. A None here means the
    divergent rule does not fire, never that it passed.
    """
    if not n or pool_pct is None:
        return None
    p = pool_pct / 100.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    return min(1.0, sum(math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
                        for i in range(0, k + 1)))


def sourcing_block(cohort):
    """The per-cohort sourcing block, or None if the cohort renders no claims.

    None for a muted cohort (invariant 12 - it carries no claims and already
    renders its own n= label) and None for an unmuted cohort whose claims all
    dropped: 32 of 1,109 unmuted sections have zero claims, and tier 1's
    "the points below" would be a lie under an empty section.
    """
    if cohort.get("muted"):
        return None
    n_claims = sum(len(t.get("claims") or [])
                   for t in (cohort.get("themes") or []))
    if not n_claims:
        return None

    n, k = cited_reviews(cohort)
    if not n:
        return None
    p = divergence_p(k, n, cohort.get("pct_positive"))

    triggers = []
    if n <= THIN_MAX_REVIEWS:
        triggers.append("thin")
    if p is not None and p < ALPHA:
        triggers.append("divergent")

    return {
        "level": "escalated" if triggers else "baseline",
        "triggers": triggers,
        "cited_reviews": n,
        "cited_recommend": k,
        "divergence_p": None if p is None else float("%.3g" % p),
        "basis": BASIS,
    }
