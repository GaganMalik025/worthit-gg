"""
Offline tests for verify_claims.py, the meaning check that sorts claims from
one-reviewer points (2026-11-16). No network: the model is a stub returning a fixed
answer, so what is pinned here is code's half of every decision.

Run:  .venv/bin/python pipeline/test_claim_verification.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_claims as ec  # noqa: E402
import qr4_gate  # noqa: E402
import verify_claims as vc  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print("  %-64s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        FAILURES.append("%s %s" % (name, detail))


CORPUS = {i: {"review_text": "review %s text" % i} for i in ("1", "2", "3", "4")}
CLAIMS = [
    {"claim_id": "a", "claim": "Reviewers report crashes on launch.", "theme": "performance",
     "supporting_ids": ["1", "2", "3"]},
    {"claim_id": "b", "claim": "Reviewers note the jump feels short.", "theme": "difficulty",
     "supporting_ids": ["1", "4"]},
    {"claim_id": "c", "claim": "Reviewers praise the soundtrack.", "theme": "content",
     "supporting_ids": ["2", "3"]},
]


def run(rows, claims=CLAIMS):
    return vc.decide(claims, {"claims": rows})


def test_sorting():
    print("\nverify: code sorts claims by how many reviews really support them")
    main, singles, rep = run([
        {"claim_id": "a", "supported_by": ["1", "3"]},
        {"claim_id": "b", "supported_by": ["4"],
         "one_reviewer_text": "One reviewer says the normal jump feels too short."},
        {"claim_id": "c", "supported_by": []},
    ])
    check("two supporting reviews stay a claim", [c["claim_id"] for c in main] == ["a"], main)
    check("  and keep only the reviews that support it",
          bool(main) and main[0]["supporting_ids"] == ["1", "3"], main)
    check("  and count the padded citations removed", rep["citations_removed"] == 1, rep)
    check("one supporting review becomes a one-reviewer point",
          len(singles) == 1 and singles[0]["supporting_id"] == "4", singles)
    check("  carrying the singular rewrite, not the plural claim",
          bool(singles) and singles[0]["text"].startswith("One reviewer"), singles)
    check("none supporting is dropped", rep["dropped"] == 1, rep)


def test_ids_are_the_claims_own():
    print("\nverify: the model cannot add evidence")
    main, _, _ = run([
        {"claim_id": "a", "supported_by": ["1", "9"]},      # 9 is invented
        {"claim_id": "b", "supported_by": ["2", "3"]},      # not b's citations
        {"claim_id": "c", "supported_by": ["2", "3"]},
    ])
    ids = [c["claim_id"] for c in main]
    check("an invented id does not count toward two", "a" not in ids, ids)
    check("another claim's reviews do not count", "b" not in ids, ids)
    check("invariant 3: every published claim has two or more supporting ids",
          all(len(c["supporting_ids"]) >= 2 for c in main), main)


def test_rewrite_is_guarded():
    print("\nverify: the singular rewrite is held to the same rules as any prose")
    for name, text in (("a plural rewrite", "Reviewers say the jump feels short."),
                       ("an empty rewrite", ""),
                       ("prevalence language", "One reviewer says most players quit.")):
        _, singles, rep = run([
            {"claim_id": "a", "supported_by": ["1", "2"]},
            {"claim_id": "b", "supported_by": ["4"], "one_reviewer_text": text},
            {"claim_id": "c", "supported_by": ["2", "3"]},
        ])
        check("%s is rejected" % name, not singles and rep["rewrite_rejected"] == 1, singles)


def test_fails_closed():
    print("\nverify: an answer that does not cover every claim publishes nothing")
    for name, rows in (("a missing claim", [{"claim_id": "a", "supported_by": ["1", "2"]}]),
                       ("a claim answered twice",
                        [{"claim_id": "a", "supported_by": ["1", "2"]},
                         {"claim_id": "a", "supported_by": ["1", "2"]},
                         {"claim_id": "b", "supported_by": []},
                         {"claim_id": "c", "supported_by": []}])):
        try:
            run(rows)
            check("%s raises" % name, False)
        except vc.VerifyError:
            check("%s raises" % name, True)

    calls = []
    with tempfile.TemporaryDirectory() as d:
        def call(system, user, schema):
            calls.append(1)
            return "not json"
        try:
            vc.verify_cohort(call, lambda s, u, t: Path(d) / ("%s.json" % t), "G", "1",
                             "mid", CLAIMS, CORPUS)
            check("a cohort that never verifies raises", False)
        except vc.VerifyError:
            check("a cohort that never verifies raises", True)
        check("  after one retry, not more", len(calls) == 2, len(calls))


def test_cache_never_replays_a_retry():
    print("\nverify: only the first attempt may be served from cache")
    with tempfile.TemporaryDirectory() as d:
        good = json.dumps({"claims": [{"claim_id": c["claim_id"],
                                       "supported_by": ["1", "2", "3"]} for c in CLAIMS]})
        calls = []

        def call(system, user, schema):
            calls.append(1)
            return good

        def cache(s, u, t):
            return Path(d) / ("%s.json" % t)
        vc.verify_cohort(call, cache, "G", "1", "mid", CLAIMS, CORPUS)
        vc.verify_cohort(call, cache, "G", "1", "mid", CLAIMS, CORPUS)
        check("a repeated cohort costs one call, not two", len(calls) == 1, len(calls))

    # A retry exists to get a DIFFERENT answer. If attempt 1 could read its own
    # cache, a rejection cached on one night would replay on every later one at
    # zero calls - the synthesis deadlock (BACKLOG 2026-08-18).
    with tempfile.TemporaryDirectory() as d:
        user = vc.build_prompt("G", "mid", CLAIMS, CORPUS)

        def cache(s, u, t):
            return Path(d) / ("%s.json" % t)
        cache(vc.SYSTEM, user, "%s-attempt0" % vc.TAG).write_text(
            json.dumps({"text": "not json"}), "utf-8")
        cache(vc.SYSTEM, user, "%s-attempt1" % vc.TAG).write_text(
            json.dumps({"text": good}), "utf-8")
        calls = []
        vc.verify_cohort(call, cache, "G", "1", "mid", CLAIMS, CORPUS)
        check("a retry after a cached rejection sends a real request",
              len(calls) == 1, len(calls))


def test_prompt_shape():
    print("\nverify: what the model is shown")
    user = vc.build_prompt("G", "mid", CLAIMS, CORPUS)
    check("each cited review appears once", user.count("[1] review 1 text") == 1, user)
    check("every claim id is listed", all("[%s]" % c["claim_id"] in user for c in CLAIMS))
    check("no minutes reach the prompt (invariant 1)", "minutes" not in user.lower())


def test_extraction_admits_one_review():
    print("\nextraction: one id now reaches the meaning check")
    kept, rejected = ec.enforce([{"claim": "x", "theme": "other", "supporting_ids": ["1"]},
                                 {"claim": "y", "theme": "other", "supporting_ids": ["9"]}],
                                {"1"}, {"1": True}, "mid")
    check("a one-review claim is kept for verification", [k["claim"] for k in kept] == ["x"])
    check("a claim citing only unknown ids is still rejected",
          [r["claim"] for r in rejected] == ["y"])
    check("the schema allows one id",
          ec.CLAIM_SCHEMA["properties"]["claims"]["items"]["properties"]
          ["supporting_ids"]["minItems"] == 1)


def test_qr4_gates_one_reviewer_citations():
    print("\nqr4: one-reviewer citations are safety-checked like any other")
    verdict = {"cohorts": [{"bucket": "mid", "themes": [], "single_points": [
        {"point_id": "one-1", "text": "One reviewer says x.",
         "citation": {"recommendationid": "5", "review_text": "placeholder"}}]}]}
    check("the gate sees the one-reviewer citation",
          [cid for _, cid, _ in qr4_gate.iter_citations(verdict)] == ["one-1"])


def test_synthesis_refuses_unverified_claims():
    print("\nsynthesis: a claims file the meaning check never saw does not publish")
    src = (Path(__file__).resolve().parent / "synthesize.py").read_text("utf-8")
    check("the refusal is in synthesize_one",
          'if not claims_blob.get("verified") and not getattr(args, "allow_unverified"'
          in src)


if __name__ == "__main__":
    test_sorting()
    test_ids_are_the_claims_own()
    test_rewrite_is_guarded()
    test_fails_closed()
    test_cache_never_replays_a_retry()
    test_prompt_shape()
    test_extraction_admits_one_review()
    test_qr4_gates_one_reviewer_citations()
    test_synthesis_refuses_unverified_claims()
    if FAILURES:
        print("\n%d FAILURES:" % len(FAILURES))
        for f in FAILURES:
            print("  %s" % f)
        sys.exit(1)
    print("\nall claim verification tests passed")
