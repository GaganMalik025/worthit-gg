"""
WorthIt.gg - LLM-as-judge runner (build plan 2.3)

Applies evals/rubric.md (authored, v1.0) to evals/candidates.json (70 fixed
cases) and writes evals/judge_scores.json for the hand-validation step at 2.4.

candidates.json is opened READ-ONLY and never rewritten.

The only real risk here is DRIFT - the judge scoring something adjacent to the
rubric rather than the rubric itself. Every choice below removes a surface where
that can happen, preferring structure over instruction:

  * The rubric is sent VERBATIM, the whole file, in system_instruction. A
    paraphrase would be a second source of truth that can silently diverge from
    the authored document. Its sha256 rides in the output and in every cache key,
    so editing the rubric invalidates every cached score (its own Versioning
    section demands exactly this).
  * citation_verdict and citation_split are OMITTED from the payload entirely,
    not accompanied by an instruction to ignore them. A field that never arrives
    cannot leak into a faithfulness score.
  * QR-2 is COMPUTED, never asked. The rubric says so in as many words: "a direct
    comparison rather than a judgment call. Score it mechanically and move on."
  * QR-1's case-level >=2 rule is COMPUTED from per-citation support levels,
    never trusted to arithmetic done in prose. The judge's own holistic score is
    kept beside it, and disagreements are flagged - those are the cases worth
    hand-scoring at 2.4.
  * Hard enums in the response schema; reasoning required on every check.

One request per case, not batched. Quota is not the constraint (~1k RPD free
tier, a median case is ~2.9k tokens), and independence buys more than it costs:
no anchoring against neighbours, the rubric's own per-case procedure preserved,
one malformed response loses one score, and cache granularity stays per case.

Model configuration (invariant 6): no temperature / top_p / top_k, single user
turn, no prefilled model turn. thinking_level defaults to "low" - a deliberate
departure from extraction's "minimal", recorded in the output metadata: invariant
6 pins EXTRACTION to minimal for a mechanical task; judging faithfulness against
a 200-line rubric is the reasoning-heavier job.

Usage:
    .venv/bin/python evals/run_judge.py --dry-run
    .venv/bin/python evals/run_judge.py --limit 3
    .venv/bin/python evals/run_judge.py
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import extract_claims                                   # noqa: E402  (transport reuse)

RUBRIC_PATH = ROOT / "evals/rubric.md"
CANDIDATES_PATH = ROOT / "evals/candidates.json"
OUT_PATH = ROOT / "evals/judge_scores.json"
CACHE_DIR = ROOT / "data/cache/judge"

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_THINKING = "low"
CACHE_TAG = "judge-v1"
PACE_SECONDS = 1.0

# Fields that must never reach the judge. Asserted against the built payload
# rather than trusted to the code above having omitted them.
WITHHELD_FIELDS = ("citation_verdict", "citation_split")


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------

# Routing only. Names which sections are operative and how the two QR-1 outputs
# map onto the rubric's own score sections - deliberately restates no threshold,
# no definition and no example, because a second wording of a rule is a second
# rule.
PREAMBLE = """\
You are applying a fixed scoring rubric to ONE test case. The complete rubric \
follows, reproduced verbatim from the document that defines this evaluation. It \
is the only standard. Do not apply any threshold, definition or consideration \
that is not written in it.

Operative for this case: "Scoring procedure", "QR-1 - Faithfulness", \
"QR-4 - Content safety", and "Out of scope".
Context only, not scored by you: "QR-2" (computed in code before this case \
reached you), "QR-3", "Aggregation and reporting", "Judge validation", \
"Versioning".

For QR-1 you report two things, and both are recorded:
  1. a support level for EACH citation individually - "full", "partial" or \
"none" - corresponding to what the rubric's Score 2, Score 1 and Score 0 \
sections describe when that reasoning is applied to a single citation;
  2. your own score for the case as a whole, 0, 1 or 2.

Write one sentence of reasoning for every field, including where the score is \
obvious.

--- BEGIN RUBRIC (evals/rubric.md) ---
{rubric}
--- END RUBRIC ---
"""

CASE_HEADER = """\
CASE {case_id}
Game: {game_name}
Cohort: {cohort_label} ({cohort_hours})

CLAIM: {claim}

{n} citations follow, each reproduced in full. Read every one before scoring.\
{annotated_note}
"""

CITATION_BLOCK = """\
--- CITATION {i} of {n} ---
recommendationid: {rid}
playtime when this review was written: {hours} hours
this reviewer's overall verdict on the game: {verdict}
date: {date}
filter annotations: {annotations}

{text}
"""

SUPPORT_LEVELS = ["full", "partial", "none"]

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["citation_support", "qr1", "qr1_reasoning", "qr4",
                 "qr4_reasoning"],
    "properties": {
        "citation_support": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["recommendationid", "level", "reasoning"],
                "properties": {
                    "recommendationid": {"type": "string"},
                    "level": {"type": "string", "enum": SUPPORT_LEVELS},
                    "reasoning": {"type": "string"},
                },
            },
        },
        # string enum, not integer: Gemini's schema only constrains enums on
        # STRING, and a hard enum is worth more here than a native int
        "qr1": {"type": "string", "enum": ["0", "1", "2"]},
        "qr1_reasoning": {"type": "string"},
        "qr4": {"type": "string", "enum": ["pass", "fail"]},
        "qr4_reasoning": {"type": "string"},
    },
}


def rubric_version(text):
    m = re.search(r"^\*\*Version:\*\*\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else "unknown"


def ordered_citations(case):
    """Annotated citations first - the rubric's QR-4 reading order.

    "citations carrying filter annotations get read in full first. These
    annotations prioritise attention; they do not decide the score." Ordering the
    payload is how that instruction is honoured rather than merely repeated.
    Stable within each group, so the ordering stays deterministic.
    """
    cits = case.get("citations") or []
    annotated = [c for c in cits if c.get("annotations")]
    plain = [c for c in cits if not c.get("annotations")]
    return annotated + plain


def build_user_turn(case):
    cits = ordered_citations(case)
    n_annotated = sum(1 for c in cits if c.get("annotations"))
    note = ""
    if n_annotated:
        note = ("\n%d of them carry filter annotations and are listed first."
                % n_annotated)

    blocks = [CASE_HEADER.format(
        case_id=case["case_id"], game_name=case["game_name"],
        cohort_label=case["cohort_label"], cohort_hours=case["cohort_hours"],
        claim=case["claim"], n=len(cits), annotated_note=note)]

    for i, c in enumerate(cits, 1):
        blocks.append(CITATION_BLOCK.format(
            i=i, n=len(cits), rid=c["recommendationid"],
            hours="%.1f" % (c.get("hours_at_review") or 0.0),
            verdict=("thumbs-up (recommends the game)" if c.get("voted_up")
                     else "thumbs-down (does not recommend the game)"),
            date=c.get("date") or "unknown",
            annotations=", ".join(c.get("annotations") or []) or "none",
            text=(c.get("review_text") or "").strip()))

    return "\n".join(blocks)


def build_prompts(case, rubric_text):
    return PREAMBLE.format(rubric=rubric_text), build_user_turn(case)


def assert_withheld(system, user, case):
    """The withheld fields must be absent from what is actually sent.

    Checked against the built strings, not against intent: this is the one
    invariant of the whole runner that a refactor could quietly break.
    """
    # The USER turn only. The rubric names citation_verdict twice, in "Out of
    # scope" and "Judge validation", and those mentions are the author's own
    # instruction NOT to consult it - they travel verbatim and are not a leak.
    # What must never arrive is the case's actual value, which lives here.
    for field in WITHHELD_FIELDS:
        if field in user:
            raise SystemExit("payload for %s contains withheld field %r - refusing "
                             "to send" % (case["case_id"], field))

    # The field NAME check above cannot catch a future edit that interpolates the
    # VALUE ("negative", "mixed") into the header. Scan the header with the claim
    # excised - the claim is authored prose and may legitimately contain any of
    # those words, while everything else in the header is assembled here.
    value = case.get("citation_verdict")
    header = user.split("--- CITATION", 1)[0].replace(case["claim"], "")
    if value and re.search(r"\b%s\b" % re.escape(value), header):
        raise SystemExit("payload header for %s leaks the citation_verdict value "
                         "%r" % (case["case_id"], value))
    # only the one form the split is ever rendered in ("4u/1d"). A looser pattern
    # matched the bare hours and citation counts already in the header.
    split = case.get("citation_split") or {}
    if split and re.search(r"\b%du/%dd\b" % (split.get("positive", -1),
                                             split.get("negative", -1)), header):
        raise SystemExit("payload header for %s leaks the citation split"
                         % case["case_id"])


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def score_qr2(case):
    """QR-2 in code. The rubric: "Score it mechanically and move on."

    NOTE for RESULTS.md: on this file QR-2 is 100% Y BY CONSTRUCTION.
    make_candidates.py asserts every citation is in-cohort and exits 1 otherwise,
    and 1.4's grounding check rejects out-of-bucket citations upstream. Measured
    today this is a regression guard, not a measurement, and reporting "QR-2:
    100%" without that sentence would overclaim.
    """
    cohort = case["cohort"]
    bad = [c["recommendationid"] for c in case.get("citations") or []
           if c.get("bucket") != cohort]
    if bad:
        return "N", ("computed: %d of %d citations recorded outside %s (%s)"
                     % (len(bad), len(case["citations"]), cohort,
                        ", ".join(bad))), bad
    return "Y", ("computed: all %d citations recorded in %s"
                 % (len(case["citations"]), cohort)), []


def derive_qr1(levels):
    """The rubric's case-level >=2 rule, applied as arithmetic rather than prose.

      "a claim scores at the level supported by at least two citations... If four
      citations fully support the claim and one doesn't, the case scores 2... If
      only one citation fully supports it, the case cannot score above 1."

    One case shape is NOT covered by rubric v1.0: exactly one partially
    supporting citation and no full support. Score 0 reads "the citations do not
    discuss the claim's subject", which is untrue of a partial citation; score 1
    reads "partially supported", which overstates a single thin citation. It
    scores 0 here and is FLAGGED rather than resolved - per the rubric's own
    instruction, ambiguity is a document problem for v1.1 to rule on.
    """
    full = sum(1 for lv in levels if lv == "full")
    partial = sum(1 for lv in levels if lv == "partial")
    if full >= 2:
        return 2, None
    if full == 1:
        return 1, None
    if partial >= 2:
        return 1, None
    if partial == 1:
        return 0, "single_partial_only"
    return 0, None


def score_case(case, parsed):
    """Fold one judge response into a scored record. No network, no model."""
    cits = ordered_citations(case)
    returned = {str(s.get("recommendationid")): s
                for s in parsed.get("citation_support") or []}

    support, anomalies = [], []
    for c in cits:
        rid = c["recommendationid"]
        entry = returned.pop(rid, None)
        if entry is None:
            # missing verdict counts as no support: silently treating it as
            # anything else would inflate QR-1 on a truncated response
            anomalies.append("no support level returned for %s" % rid)
            support.append(OrderedDict([("recommendationid", rid),
                                        ("level", "none"),
                                        ("reasoning", "MISSING from judge "
                                                      "response; scored none")]))
            continue
        support.append(OrderedDict([
            ("recommendationid", rid),
            ("level", entry.get("level") if entry.get("level") in SUPPORT_LEVELS
             else "none"),
            ("reasoning", (entry.get("reasoning") or "").strip()),
        ]))
        if entry.get("level") not in SUPPORT_LEVELS:
            anomalies.append("unparseable level %r for %s"
                             % (entry.get("level"), rid))
    for rid in returned:
        anomalies.append("support returned for %s, which is not cited by this "
                         "case" % rid)

    qr1, gap = derive_qr1([s["level"] for s in support])
    try:
        qr1_judge = int(str(parsed.get("qr1")).strip())
    except (TypeError, ValueError):
        qr1_judge = None
        anomalies.append("unparseable qr1 %r" % parsed.get("qr1"))

    qr2, qr2_reasoning, qr2_bad = score_qr2(case)
    qr4 = "fail" if str(parsed.get("qr4")).strip().lower() == "fail" else "pass"
    if str(parsed.get("qr4")).strip().lower() not in ("pass", "fail"):
        anomalies.append("unparseable qr4 %r" % parsed.get("qr4"))

    record = OrderedDict([
        ("case_id", case["case_id"]),
        ("game_name", case["game_name"]),
        ("cohort", case["cohort"]),
        ("theme", case.get("theme")),
        ("claim", case["claim"]),
        ("n_citations", len(cits)),
        ("qr1", qr1),
        ("qr1_judge", qr1_judge),
        ("qr1_rule_disagreement", qr1_judge is not None and qr1_judge != qr1),
        ("qr1_reasoning", (parsed.get("qr1_reasoning") or "").strip()),
        ("citation_support", support),
        ("qr2", qr2),
        ("qr2_reasoning", qr2_reasoning),
        ("qr4", qr4),
        ("qr4_reasoning", (parsed.get("qr4_reasoning") or "").strip()),
    ])
    if gap:
        record["rubric_gap"] = gap
    if qr2_bad:
        record["qr2_out_of_cohort_ids"] = qr2_bad
    if anomalies:
        record["anomalies"] = anomalies
    # carried for the 2.4 hand-validation sample ONLY; never sent to the judge,
    # never consulted by any score above (rubric: "Out of scope")
    record["_citation_verdict_not_judged"] = case.get("citation_verdict")
    return record


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def cache_path(case_id, model, thinking, rubric_hash, system, user, run=0):
    digest = hashlib.sha256(
        ("%s\x00%s\x00%s\x00%s\x00%s\x00%s\x00%d"
         % (CACHE_TAG, model, thinking, rubric_hash, system, user, run))
        .encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / ("%s_%s.json" % (case_id, digest))


def judge_once(client, args, case, rubric_text, rubric_hash, run=0):
    system, user = build_prompts(case, rubric_text)
    assert_withheld(system, user, case)

    cpath = cache_path(case["case_id"], args.model, args.thinking_level,
                       rubric_hash, system, user, run)
    if cpath.exists() and not args.force:
        text = json.loads(cpath.read_text(encoding="utf-8"))["text"]
        return json.loads(text), True

    resp = extract_claims.call_model(client, args.model, system, user,
                                     schema=JUDGE_SCHEMA,
                                     thinking_level=args.thinking_level)
    text, _census = extract_claims.response_text(resp)
    usage = getattr(resp, "usage_metadata", None)
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps({
        "model": args.model, "thinking_level": args.thinking_level,
        "rubric_sha256": rubric_hash, "run": run, "text": text,
        "usage": {"prompt": getattr(usage, "prompt_token_count", None),
                  "total": getattr(usage, "total_token_count", None)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(PACE_SECONDS)
    return json.loads(text), False


# --------------------------------------------------------------------------
# aggregation and reporting
# --------------------------------------------------------------------------

def aggregate(scores):
    """Follows the rubric's "Aggregation and reporting" table exactly."""
    n = len(scores) or 1
    dist = OrderedDict((str(k), sum(1 for s in scores if s["qr1"] == k))
                       for k in (0, 1, 2))
    qr2_failures = [s["case_id"] for s in scores if s["qr2"] == "N"]
    qr4_failures = [s["case_id"] for s in scores if s["qr4"] == "fail"]
    return OrderedDict([
        ("qr1", OrderedDict([
            ("pct_scoring_2", round(100.0 * dist["2"] / n, 1)),
            ("mean", round(sum(s["qr1"] for s in scores) / n, 2)),
            ("n_zero", dist["0"]),
            ("distribution", dist),
            ("zero_case_ids", [s["case_id"] for s in scores if s["qr1"] == 0]),
        ])),
        ("qr2", OrderedDict([
            ("pct_Y", round(100.0 * (len(scores) - len(qr2_failures)) / n, 1)),
            ("failures", [{"case_id": s["case_id"], "cohort": s["cohort"]}
                          for s in scores if s["qr2"] == "N"]),
            ("computed_not_judged", True),
            ("caveat", "100% Y by construction on this candidate set: "
                       "make_candidates.py asserts every citation is in-cohort "
                       "and exits 1 otherwise, and the 1.4 grounding check "
                       "rejects out-of-bucket citations upstream. This is a "
                       "regression guard, not a measurement - RESULTS.md must "
                       "say so."),
        ])),
        ("qr4", OrderedDict([
            ("result", "fail" if qr4_failures else "pass"),
            ("failing_case_ids", qr4_failures),
        ])),
        ("qr1_rule_disagreements",
         sum(1 for s in scores if s["qr1_rule_disagreement"])),
        ("rubric_gaps", [s["case_id"] for s in scores if s.get("rubric_gap")]),
        ("cases_with_anomalies", [s["case_id"] for s in scores
                                  if s.get("anomalies")]),
    ])


def print_report(scores, agg):
    q1, q2, q4 = agg["qr1"], agg["qr2"], agg["qr4"]
    print("\n" + "=" * 78)
    print("QR-1 faithfulness : %.1f%% scoring 2   mean %.2f   %d zeros"
          % (q1["pct_scoring_2"], q1["mean"], q1["n_zero"]))
    print("                    distribution  0:%s  1:%s  2:%s"
          % (q1["distribution"]["0"], q1["distribution"]["1"],
             q1["distribution"]["2"]))
    print("QR-2 segment      : %.1f%% Y  (computed, not judged)" % q2["pct_Y"])
    print("                    CAVEAT: 100% by construction on this set - "
          "regression guard, not a measurement")
    print("QR-4 safety       : %s%s"
          % (q4["result"].upper(),
             ("  " + ", ".join(q4["failing_case_ids"])) if q4["failing_case_ids"]
             else ""))
    print("\n>=2-rule vs judge's holistic score: %d disagreements"
          % agg["qr1_rule_disagreements"])
    if agg["rubric_gaps"]:
        print("rubric v1.0 gap (single_partial_only), %d cases: %s"
              % (len(agg["rubric_gaps"]), ", ".join(agg["rubric_gaps"])))
    if agg["cases_with_anomalies"]:
        print("response anomalies in %d cases: %s"
              % (len(agg["cases_with_anomalies"]),
                 ", ".join(agg["cases_with_anomalies"])))

    print("\nby game:")
    games = OrderedDict()
    for s in scores:
        g = games.setdefault(s["game_name"], [])
        g.append(s["qr1"])
    for game, vals in games.items():
        print("  %-20s n=%-3d mean %.2f   2s %d  1s %d  0s %d"
              % (game[:20], len(vals), sum(vals) / len(vals),
                 vals.count(2), vals.count(1), vals.count(0)))
    print("by cohort:")
    cohorts = OrderedDict()
    for s in scores:
        cohorts.setdefault(s["cohort"], []).append(s["qr1"])
    for cohort, vals in cohorts.items():
        print("  %-20s n=%-3d mean %.2f   2s %d  1s %d  0s %d"
              % (cohort, len(vals), sum(vals) / len(vals),
                 vals.count(2), vals.count(1), vals.count(0)))


def print_validation_shortlist(scores):
    """The cases worth spending the 10 hand-scores on at 2.4.

    The rubric asks for 2-3 cases with a split citation_verdict specifically,
    since that is where human and judge readings diverge most. Selection reads
    citation_verdict; no score did.
    """
    def line(s, why):
        print("  %-24s %-2s  %s  %s"
              % (s["case_id"], s["qr1"], why, s["claim"][:64]))

    print("\n" + "=" * 78)
    print("SHORTLIST for 2.4 hand-validation (10 cases, scored against the "
          "rubric by hand)")
    picked = OrderedDict()
    for s in scores:
        if s["qr1_rule_disagreement"]:
            picked.setdefault(s["case_id"], (s, ">=2-rule vs judge disagree"))
    for s in scores:
        if s["qr1"] == 0:
            picked.setdefault(s["case_id"], (s, "QR-1 zero               "))
    for s in scores:
        if s.get("rubric_gap"):
            picked.setdefault(s["case_id"], (s, "rubric gap              "))
    split = [s for s in scores if s.get("_citation_verdict_not_judged") == "mixed"]
    for s in split[:3]:
        picked.setdefault(s["case_id"], (s, "split citation_verdict  "))
    if not picked:
        print("  (no disagreements, zeros or gaps - hand-score a random 10)")
    for s, why in picked.values():
        line(s, why)
    print("\n  %d flagged; the rubric asks for 10 total, so top up from the "
          "2s if short." % len(picked))


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="WorthIt.gg LLM-as-judge (2.3)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--thinking-level", default=DEFAULT_THINKING,
                    choices=["minimal", "low", "medium", "high"])
    ap.add_argument("--limit", type=int, default=0, help="score the first N cases")
    ap.add_argument("--case", default=None, help="score one case id")
    ap.add_argument("--double-run", action="store_true",
                    help="independent second pass; report disagreement rate")
    ap.add_argument("--force", action="store_true", help="ignore the response cache")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the exact prompt for one case, call nothing")
    ap.add_argument("--fail-on-qr4", action="store_true",
                    help="exit 1 on any QR-4 failure (launch gate, invariant 8)")
    ap.add_argument("--candidates", default=str(CANDIDATES_PATH))
    ap.add_argument("--rubric", default=str(RUBRIC_PATH))
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    rubric_text = Path(args.rubric).read_text(encoding="utf-8")
    rubric_hash = hashlib.sha256(rubric_text.encode("utf-8")).hexdigest()
    version = rubric_version(rubric_text)

    blob = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    cases = blob["cases"]
    if args.case:
        cases = [c for c in cases if c["case_id"] == args.case]
        if not cases:
            print("no case %s in %s" % (args.case, args.candidates))
            sys.exit(1)
    if args.limit:
        cases = cases[:args.limit]

    print("judging %d of %d cases against rubric v%s (%s...) with %s "
          "[thinking_level=%s]"
          % (len(cases), blob["n_cases"], version, rubric_hash[:12], args.model,
             args.thinking_level))

    if args.dry_run:
        system, user = build_prompts(cases[0], rubric_text)
        assert_withheld(system, user, cases[0])
        print("\n--- system_instruction (%d chars) ---\n%s" % (len(system), system))
        print("\n--- user turn (%d chars) ---\n%s" % (len(user), user))
        print("\n--- checks ---")
        print("  rubric verbatim in system: %s"
              % (rubric_text.strip() in system))
        for field in WITHHELD_FIELDS:
            print("  %-18s absent from the case payload: %-5s  "
                  "(in rubric text: %s, author's own 'do not consult' wording)"
                  % (field, field not in user, field in rubric_text))
        print("  citation_verdict VALUE (%r) absent from case payload: %s"
              % (cases[0].get("citation_verdict"),
                 cases[0].get("citation_verdict") not in
                 user.split("--- CITATION", 1)[0].replace(cases[0]["claim"], "")))
        print("  full review text present: %s"
              % all((c.get("review_text") or "").strip() in user
                    for c in cases[0]["citations"]))
        print("  contents: one user turn, no model turn")
        print("  sampling params: none (invariant 6)")
        print("\n(dry run - nothing sent)")
        return

    extract_claims.load_env()
    import os
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY missing from .env")
        sys.exit(1)
    from google import genai
    client = genai.Client(api_key=key)

    scores, second, hits = [], [], 0
    for i, case in enumerate(cases, 1):
        parsed, cached = judge_once(client, args, case, rubric_text, rubric_hash)
        hits += 1 if cached else 0
        rec = score_case(case, parsed)
        scores.append(rec)
        print("  [%2d/%2d]%s %-26s QR-1 %s (judge %s)  QR-2 %s  QR-4 %s  %s"
              % (i, len(cases), " c" if cached else "  ", rec["case_id"],
                 rec["qr1"], rec["qr1_judge"], rec["qr2"], rec["qr4"],
                 "!" if rec["qr1_rule_disagreement"] else ""))
        if args.double_run:
            p2, c2 = judge_once(client, args, case, rubric_text, rubric_hash, run=1)
            hits += 1 if c2 else 0
            second.append(score_case(case, p2))

    agg = aggregate(scores)
    print_report(scores, agg)

    consistency = None
    if second:
        by_id = {s["case_id"]: s for s in second}
        agree1 = sum(1 for s in scores if by_id[s["case_id"]]["qr1"] == s["qr1"])
        agree4 = sum(1 for s in scores if by_id[s["case_id"]]["qr4"] == s["qr4"])
        consistency = OrderedDict([
            ("n", len(scores)),
            ("qr1_agreement_pct", round(100.0 * agree1 / len(scores), 1)),
            ("qr4_agreement_pct", round(100.0 * agree4 / len(scores), 1)),
            ("qr1_disagreeing_case_ids",
             [s["case_id"] for s in scores
              if by_id[s["case_id"]]["qr1"] != s["qr1"]]),
        ])
        print("\ndouble-run self-consistency: QR-1 %.1f%%, QR-4 %.1f%%"
              % (consistency["qr1_agreement_pct"],
                 consistency["qr4_agreement_pct"]))

    print_validation_shortlist(scores)
    print("\ncache: %d of %d responses served from disk" % (hits, len(cases)))

    payload = OrderedDict([
        ("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("model", args.model),
        ("thinking_level", args.thinking_level),
        ("sampling", "none - temperature/top_p/top_k not sent (invariant 6)"),
        ("rubric", OrderedDict([("version", version), ("sha256", rubric_hash),
                                ("path", "evals/rubric.md"),
                                ("sent", "verbatim, whole file, in "
                                         "system_instruction")])),
        ("candidates", OrderedDict([
            ("path", "evals/candidates.json"),
            ("n_cases", blob["n_cases"]),
            ("n_scored", len(scores)),
            ("extraction_model", (blob.get("source") or {}).get("extraction_model")),
            ("grounding", (blob.get("source") or {}).get("grounding")),
        ])),
        ("scoring_notes", OrderedDict([
            ("qr1", "judged per citation (full/partial/none), then the rubric's "
                    ">=2 rule applied in code; the judge's holistic score is "
                    "kept as qr1_judge"),
            ("qr2", "computed in code, never judged"),
            ("qr4", "judged; annotated citations listed first per the rubric's "
                    "reading order"),
            ("withheld", "citation_verdict and citation_split are absent from "
                         "the payload entirely"),
        ])),
        ("aggregate", agg),
    ])
    if consistency:
        payload["self_consistency"] = consistency
    payload["scores"] = scores

    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("wrote %d scored cases -> %s" % (len(scores), out))
    print("(RESULTS.md is not written here - that is 2.5, and the row is yours)")

    if args.fail_on_qr4 and agg["qr4"]["result"] == "fail":
        print("\nQR-4 FAILED - launch gate, invariant 8. Deploy is blocked.")
        sys.exit(1)


if __name__ == "__main__":
    main()
