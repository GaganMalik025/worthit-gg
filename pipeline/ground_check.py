"""
WorthIt.gg - deterministic grounding check (build plan 1.4)

Runs on every generation, before any LLM judge sees it. No network, no model,
no cost (PRD D6). Four checks per claim:

    1. ids_exist            every cited id resolves in the filtered corpus
    2. bucket_match         every cited review belongs to the claimed cohort
    3. lexical overlap      the claim's words appear in the reviews it cites
    4. prevalence           claim prose states no rate, share or frequency

Checks 1 and 2 are already structurally true coming out of extract_claims,
because a bucket's prompt only ever contains its own ids. They are re-verified
here from the corpus rather than on extraction's word: claims files also arrive
from regenerations, overnight batches and hand edits, and this is the last gate
before the eval harness.

WHAT THIS CHECK CANNOT DO
-------------------------
Lexical overlap cannot tell rich paraphrase from hallucination. Measured on the
18 real Kenshi claims, "reviewers describe the early game as extremely punishing
... repeatedly defeated, beaten up, or enslaved" scores 0.09 against citations
reading "Get your ass beat 1 million times, lose your limbs to cannibals" and
"completely demolished ... captured by slavers ... gobbled up alive". The claim
is true and well supported; demolished/mugged/gobbled are simply not defeated.

So a failure here means UNVERIFIABLE, never "hallucinated". The response is to
regenerate and then drop, which costs one true claim occasionally and never
ships an unverifiable one.

Usage:
    python3 ground_check.py data/claims/233860.json
    python3 ground_check.py data/claims/233860.json --min-coverage 0.3 --verbose
"""

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prevalence_guard  # noqa: E402

FILTERED_DIR = Path("data/filtered")

# Defaults measured against the Kenshi claim set: fuzzy union coverage runs
# min 0.09 / p25 0.40 / median 0.54, so 0.25 sits under the healthy mass and
# above the two genuinely weak claims. Tune by reading rejects, not by feel.
MIN_UNION_COVERAGE = 0.25
MIN_CITATION_COVERAGE = 0.10
MIN_SUPPORTING_CITATIONS = 2

STOPWORDS = set("""
a an the and or but if then than that this these those is are was were be been being am
of in on at to for with from by as it its into about over under out up down off not no nor
so such can could will would should may might must do does did done have has had having
you your yours they them their there here what which who whom when where why how
i we he she his her hers our ours us me my mine your just also even still very too
one two three first second next last other others another same own each both all any some
game games gaming player players playing play plays played review reviews reviewer reviewers
steam hour hours get gets got getting make makes made making like likes liked really much
many lot lots thing things time times way ways bit really pretty good bad great
""".split())

MIN_TOKEN_LEN = 4          # tokens shorter than this carry little signal
MIN_FUZZY_LEN = 4          # below this, only exact matches count


def tokens(text):
    """Content tokens: lowercased, stopped, lightly stemmed."""
    out = set()
    for w in re.split(r"[^a-z0-9']+", (text or "").lower()):
        if len(w) < MIN_TOKEN_LEN or w in STOPWORDS:
            continue
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("es"):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        if len(w) > 5 and w.endswith("ing"):
            w = w[:-3]
        elif len(w) > 5 and w.endswith("ed"):
            w = w[:-2]
        if len(w) >= MIN_TOKEN_LEN and w not in STOPWORDS:
            out.add(w)
    return out


def fuzzy_hits(claim_tokens, review_tokens):
    """Claim tokens found in the review, tolerating morphology.

    Exact, shared 4-char prefix, or containment - so beaten/beat, punish/
    punishing and defeat/defeated all match. Genuine synonymy still will not.
    """
    hits = set()
    for c in claim_tokens:
        for r in review_tokens:
            if c == r:
                hits.add(c)
                break
            if len(c) >= MIN_FUZZY_LEN and len(r) >= MIN_FUZZY_LEN:
                if c[:4] == r[:4] or c in r or r in c:
                    hits.add(c)
                    break
    return hits


def coverage(claim_tokens, review_tokens):
    if not claim_tokens:
        return 0.0
    return len(fuzzy_hits(claim_tokens, review_tokens)) / len(claim_tokens)


def check_claim(claim, bucket, corpus, cfg=None):
    """Verify one claim against the filtered corpus. Returns a result dict."""
    cfg = cfg or {}
    min_union = cfg.get("min_coverage", MIN_UNION_COVERAGE)
    min_cit = cfg.get("min_citation_coverage", MIN_CITATION_COVERAGE)
    min_support = cfg.get("min_supporting", MIN_SUPPORTING_CITATIONS)

    text = claim.get("claim") or ""
    ids = [str(i) for i in (claim.get("supporting_ids") or [])]
    ct = tokens(text)
    failures, per_citation = [], OrderedDict()

    # 1. ids exist
    missing = [i for i in ids if i not in corpus]
    if missing:
        failures.append("ids_not_in_corpus:%s" % ",".join(missing))

    resolved = [i for i in ids if i in corpus]

    # 2. cited reviews belong to the claimed cohort
    wrong_bucket = [i for i in resolved if corpus[i].get("bucket") != bucket]
    if wrong_bucket:
        failures.append("cited_outside_bucket:%s" % ",".join(wrong_bucket))

    # 3. lexical overlap - per citation and against the union
    union = set()
    for i in resolved:
        rt = tokens(corpus[i].get("review_text"))
        union |= rt
        per_citation[i] = round(coverage(ct, rt), 3)
    union_cov = round(coverage(ct, union), 3)

    supporting = [i for i, c in per_citation.items() if c >= min_cit]
    if union_cov < min_union:
        failures.append("low_union_coverage:%.2f<%.2f" % (union_cov, min_union))
    if len(supporting) < min_support:
        # upgrades invariant 3 from "two ids cited" to "two reviews that
        # demonstrably mention this"
        failures.append("only_%d_supporting_citations(need_%d_at_%.2f)"
                        % (len(supporting), min_support, min_cit))

    # 4. prevalence language - a hard reject at this stage
    prevalence = prevalence_guard.check_claim(text)
    if prevalence:
        failures.append("prevalence_language:%s"
                        % ",".join(sorted({t for t, _ in prevalence})))

    return {
        "claim": text,
        "bucket": bucket,
        "supporting_ids": ids,
        "union_coverage": union_cov,
        "per_citation": per_citation,
        "supporting_citations": len(supporting),
        "prevalence_terms": [t for t, _ in prevalence],
        "passed": not failures,
        "failures": failures,
    }


def check_bucket(claims, bucket, corpus, cfg=None):
    results = [check_claim(c, bucket, corpus, cfg) for c in claims]
    passed = [c for c, r in zip(claims, results) if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    return passed, failed, results


def load_corpus(appid, src=FILTERED_DIR):
    path = Path(src) / ("%s.json" % appid)
    blob = json.loads(path.read_text(encoding="utf-8"))
    return {str(r["recommendationid"]): r for r in blob.get("reviews", [])}


def print_results(bucket, results, verbose=False):
    print("\n[%s] %d claims" % (bucket, len(results)))
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print("  %s  cov=%.2f  support=%d  %s"
              % (mark, r["union_coverage"], r["supporting_citations"],
                 r["claim"][:66]))
        if not r["passed"]:
            for f in r["failures"]:
                print("        ! %s" % f)
        if verbose:
            for rid, c in r["per_citation"].items():
                print("          %s  %.2f" % (rid, c))


def main():
    ap = argparse.ArgumentParser(
        description="Deterministic grounding check for a claims file (1.4)")
    ap.add_argument("claims_file")
    ap.add_argument("--filtered", default=str(FILTERED_DIR))
    ap.add_argument("--min-coverage", type=float, default=MIN_UNION_COVERAGE)
    ap.add_argument("--min-citation-coverage", type=float,
                    default=MIN_CITATION_COVERAGE)
    ap.add_argument("--min-supporting", type=int, default=MIN_SUPPORTING_CITATIONS)
    ap.add_argument("--verbose", action="store_true",
                    help="show per-citation coverage")
    args = ap.parse_args()

    blob = json.loads(Path(args.claims_file).read_text(encoding="utf-8"))
    corpus = load_corpus(blob["appid"], args.filtered)
    cfg = {"min_coverage": args.min_coverage,
           "min_citation_coverage": args.min_citation_coverage,
           "min_supporting": args.min_supporting}

    print("grounding %s (%s)  thresholds: union>=%.2f, %d citations >=%.2f"
          % (blob.get("game_name"), blob["appid"], args.min_coverage,
             args.min_supporting, args.min_citation_coverage))

    total, failed_total = 0, 0
    for bucket, claims in (blob.get("claims_by_bucket") or {}).items():
        _, failed, results = check_bucket(claims, bucket, corpus, cfg)
        print_results(bucket, results, args.verbose)
        total += len(results)
        failed_total += len(failed)

    print("\n%d/%d claims grounded, %d rejected" %
          (total - failed_total, total, failed_total))
    sys.exit(1 if failed_total else 0)


if __name__ == "__main__":
    main()
