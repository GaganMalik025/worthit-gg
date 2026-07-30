"""
1.4 definition of done: deliberately corrupted claims must be rejected.

Offline - no network, no model, no API key. Run it before trusting a claims file:

    python3 pipeline/test_ground_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ground_check import check_claim, tokens, fuzzy_hits  # noqa: E402

# A miniature corpus standing in for data/filtered/<appid>.json
CORPUS = {
    "aaa": {"recommendationid": "aaa", "bucket": "refund_window", "voted_up": False,
            "review_text": "There is no tutorial at all. The game drops you in with "
                           "no explanation of the controls and no guidance."},
    "bbb": {"recommendationid": "bbb", "bucket": "refund_window", "voted_up": False,
            "review_text": "Zero onboarding. No tutorial, no explanation, I had no "
                           "idea what the controls did or where to go."},
    "ccc": {"recommendationid": "ccc", "bucket": "veteran", "voted_up": True,
            "review_text": "After 400 hours the base building economy still holds up "
                           "and the mod scene keeps it fresh."},
    "ddd": {"recommendationid": "ddd", "bucket": "refund_window", "voted_up": False,
            "review_text": "Crashed twice on startup before I could even reach the "
                           "main menu. Refunded."},
}

FAILS = 0


def expect(label, condition, detail=""):
    global FAILS
    if condition:
        print("  PASS  %s" % label)
    else:
        FAILS += 1
        print("  FAIL  %s %s" % (label, detail))


def has(result, prefix):
    return any(f.startswith(prefix) for f in result["failures"])


print("grounding check - 1.4 DoD\n")

# ---------------------------------------------------------------- known good
good = {"claim": "Reviewers report there is no tutorial and no explanation of the "
                 "controls, leaving them without guidance.",
        "supporting_ids": ["aaa", "bbb"]}
r = check_claim(good, "refund_window", CORPUS)
expect("well-grounded claim passes", r["passed"], r["failures"])
expect("  ...with high coverage", r["union_coverage"] >= 0.5, r["union_coverage"])
expect("  ...and two supporting citations", r["supporting_citations"] == 2)

# ------------------------------------------------------------- corrupted id
bad_id = {"claim": good["claim"], "supporting_ids": ["aaa", "zzz9999"]}
r = check_claim(bad_id, "refund_window", CORPUS)
expect("hallucinated id is rejected", not r["passed"] and has(r, "ids_not_in_corpus"),
       r["failures"])

# ---------------------------------------------------------- wrong-bucket cite
cross = {"claim": good["claim"], "supporting_ids": ["aaa", "ccc"]}
r = check_claim(cross, "refund_window", CORPUS)
expect("out-of-bucket citation is rejected",
       not r["passed"] and has(r, "cited_outside_bucket"), r["failures"])

# ------------------------------------------------------- text/citation swap
swapped = {"claim": "Reviewers praise the base building economy and the depth of "
                    "the crafting supply chain.",
           "supporting_ids": ["aaa", "bbb"]}
r = check_claim(swapped, "refund_window", CORPUS)
expect("claim unrelated to its citations is rejected",
       not r["passed"] and has(r, "low_union_coverage"),
       "%s cov=%.2f" % (r["failures"], r["union_coverage"]))

# ------------------------------------------------------------ one-sided cite
# 'ddd' is a crash review; it cannot support a tutorial claim, so only one
# citation genuinely supports and invariant 3 fails in substance
one_sided = {"claim": "Reviewers report there is no tutorial explaining the controls.",
             "supporting_ids": ["aaa", "ddd"]}
r = check_claim(one_sided, "refund_window", CORPUS)
expect("claim with only one supporting citation is rejected",
       not r["passed"] and has(r, "only_1_supporting_citations"),
       "%s per_citation=%s" % (r["failures"], r["per_citation"]))

# ------------------------------------------------------------- prevalence
prev = {"claim": "Most players report there is no tutorial and no explanation of "
                 "the controls, leaving them without guidance.",
        "supporting_ids": ["aaa", "bbb"]}
r = check_claim(prev, "refund_window", CORPUS)
expect("prevalence language is a hard reject",
       not r["passed"] and has(r, "prevalence_language"), r["failures"])
expect("  ...and names the offending term",
       "Most" in r["prevalence_terms"] or "most" in
       [t.lower() for t in r["prevalence_terms"]], r["prevalence_terms"])

# ------------------------------------------------------- morphology tolerance
expect("beaten/beat matches", "beaten" in fuzzy_hits({"beaten"}, {"beat"}))
expect("punish/punishing matches", "punish" in fuzzy_hits({"punish"}, {"punishing"}))
expect("unrelated words do not match", not fuzzy_hits({"tutorial"}, {"economy"}))
expect("stopwords are dropped", not (tokens("the game is very good") & {"game", "good"}))

print("\n%s" % ("all checks passed" if not FAILS else "%d CHECK(S) FAILED" % FAILS))
sys.exit(1 if FAILS else 0)
