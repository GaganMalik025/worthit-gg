"""
Pilot comparison: the per-cohort meaning check against the per-claim judge.

verify_claims.py reads a whole cohort's claims in ONE call (owner, 2026-11-16, chosen
for cost: about 4 calls a title instead of about 17). Before it is trusted
catalog-wide it is compared with the per-claim judge that measured the problem
(evals/sample_thin_claims_2026-11-04.py: same question, same wording, one claim per
call). Every claim extraction produced on the pilot titles is judged, BEFORE the
meaning check touched it (`pre_verify` in the claims file), so both readers see the
same claim with the same citations.

Reported, per claim: how many citations each reader says support it, as 0 / 1 / 2+,
in a 3x3 table. The cells that matter:
    verify 2+, judge <2   the check kept a claim the judge would still call thin
    verify <2, judge 2+   the check demoted or dropped a claim the judge would keep
plus per-citation agreement. The judge is not ground truth (validated 6 of 6 against
the owner on QR-1, n=6), so disagreement is a reason for the owner to read those
claims, not a score.

    .venv/bin/python -B evals/pilot_compare_2026-11-16.py --check    stub judge, spends nothing
    .venv/bin/python -u -B evals/pilot_compare_2026-11-16.py --spend   one call per claim, batch ledger

Without a flag it prints this and exits 2. Resumable: answers are saved after each
claim, and a re-run skips them.
Output: evals/pilot-compare-2026-11-16.json and .txt
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

MODE = next((a for a in sys.argv[1:] if a in ("--check", "--spend")), None)
if MODE is None:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import extract_claims as ec  # noqa: E402
import live_quota  # noqa: E402

APPIDS = ["1295660", "387290", "311690", "613100"]
WORK = ROOT / "evals/pilot-one-reviewer-2026-11-16"
OUT_JSON = ROOT / "evals/pilot-compare-2026-11-16.json"
OUT_TXT = ROOT / "evals/pilot-compare-2026-11-16.txt"
OVERLOAD_WAITS = [120, 300, 600, 900]

# Verbatim from evals/sample_thin_claims_2026-11-04.py, so this is the same judge.
SYSTEM = """\
You check one claim from a game review summary against the reviews cited for it.

For EACH citation answer one question: does this review state or clearly convey what \
the claim asserts? Answer "yes" or "no". Judge meaning, not shared vocabulary: reviewers \
paraphrase. Answer "no" if the review only mentions the subject without saying what the \
claim says about it. Ignore tone, ignore whether the reviewer liked the game, and ignore \
anything the claim leaves out. Give one short sentence of reasoning for each citation.
"""
SCHEMA = {"type": "object", "required": ["citations"], "properties": {
    "citations": {"type": "array", "items": {
        "type": "object", "required": ["recommendationid", "supports", "reasoning"],
        "properties": {"recommendationid": {"type": "string"},
                       "supports": {"type": "string", "enum": ["yes", "no"]},
                       "reasoning": {"type": "string"}}}}}}


def cls(n):
    return "2+" if n >= 2 else str(n)


def items(work, appid):
    """(key, game, bucket, claim, decision, corpus) for every pre-verify claim."""
    claims = json.loads((work / appid / "data/claims" / ("%s.json" % appid)).read_text("utf-8"))
    filt = json.loads((work / appid / "data/filtered" / ("%s.json" % appid)).read_text("utf-8"))
    corpus = {str(r["recommendationid"]): r for r in filt["reviews"]}
    game = claims.get("game_name") or appid
    for b in claims["extraction_report"]["buckets"]:
        if "pre_verify" not in b:
            raise SystemExit("%s/%s has no pre_verify claims: extracted before the "
                             "meaning check, or with --no-verify" % (appid, b["bucket"]))
        decisions = {d["claim_id"]: d for d in b["verification"]["decisions"]}
        for c in b["pre_verify"]:
            yield ("%s|%s|%s" % (appid, b["bucket"], c["claim_id"]), game, b["bucket"], c,
                   decisions[c["claim_id"]], corpus)


def judge_prompt(game, claim, corpus):
    return "Game: %s\nCLAIM: %s\n\n%s" % (game, claim["claim"], "\n".join(
        "--- CITATION ---\nrecommendationid: %s\n%s\n" % (rid, corpus[rid]["review_text"])
        for rid in claim["supporting_ids"]))


def run(work, call, answers, out_json):
    stopped = None
    for appid in APPIDS:
        for key, game, bucket, claim, decision, corpus in items(work, appid):
            if key in answers:
                continue
            if MODE == "--spend":
                ok, why, _ = live_quota.can_batch(live_quota.load(), est=1)
                if not ok:
                    stopped = "BUDGET STOP: %s. Re-run after the reset to resume." % why
                    break
                os.environ["WORTHIT_APPID"] = appid
            parsed = None
            for wait in OVERLOAD_WAITS + [None]:
                try:
                    parsed = call(SYSTEM, judge_prompt(game, claim, corpus),
                                  claim["supporting_ids"])
                    break
                except Exception as exc:  # noqa: BLE001 - re-raised unless overload
                    if not ("503" in str(exc) or "UNAVAILABLE" in str(exc)) or wait is None:
                        raise
                    print("  overloaded at %s; waiting %ds" % (key, wait), flush=True)
                    time.sleep(wait)
            cited = set(claim["supporting_ids"])
            yes = sorted({str(x["recommendationid"]) for x in parsed["citations"]
                          if x.get("supports") == "yes"} & cited)
            answers[key] = {"appid": appid, "game": game, "bucket": bucket,
                            "claim": claim["claim"], "cited": claim["supporting_ids"],
                            "verify_backed": decision["backed"],
                            "verify_outcome": decision["outcome"], "judge_yes": yes,
                            "judge": parsed["citations"]}
            out_json.write_text(json.dumps(answers, indent=1, ensure_ascii=False), "utf-8")
        if stopped:
            break
    return stopped


def report(answers, stopped):
    rows = list(answers.values())
    lines = ["pilot_compare_2026-11-16.py %s" % MODE, "",
             "claims compared: %d%s" % (len(rows), " (STOPPED: %s)" % stopped if stopped else "")]
    grid = {(v, j): 0 for v in ("0", "1", "2+") for j in ("0", "1", "2+")}
    agree = total = 0
    for a in rows:
        grid[(cls(len(a["verify_backed"])), cls(len(a["judge_yes"])))] += 1
        for rid in a["cited"]:
            total += 1
            agree += (rid in a["verify_backed"]) == (rid in a["judge_yes"])
    lines += ["", "rows = meaning check, columns = per-claim judge (supporting citations)",
              "            judge 0  judge 1  judge 2+"]
    for v in ("0", "1", "2+"):
        lines.append("verify %-3s  %7d  %7d  %8d" % (v, grid[(v, "0")], grid[(v, "1")],
                                                     grid[(v, "2+")]))
    kept_thin = [a for a in rows if len(a["verify_backed"]) >= 2 and len(a["judge_yes"]) < 2]
    strict = [a for a in rows if len(a["verify_backed"]) < 2 and len(a["judge_yes"]) >= 2]
    lines += ["",
              "same class: %d of %d" % (sum(grid[(k, k)] for k in ("0", "1", "2+")), len(rows)),
              "per-citation agreement: %d of %d" % (agree, total),
              "kept by the check, thin to the judge: %d" % len(kept_thin),
              "demoted or dropped by the check, kept by the judge: %d" % len(strict),
              "outcomes: %s" % ", ".join("%s %d" % (k, sum(a["verify_outcome"] == k for a in rows))
                                         for k in ("kept", "one_reviewer", "dropped",
                                                   "rewrite_rejected"))]
    for title, group in (("KEPT BY THE CHECK, THIN TO THE JUDGE", kept_thin),
                         ("DEMOTED OR DROPPED BY THE CHECK, KEPT BY THE JUDGE", strict)):
        if group:
            lines += ["", title]
            lines += ["  %s %s  verify %s / judge %s  %s" % (a["appid"], a["bucket"],
                      ",".join(a["verify_backed"]) or "-", ",".join(a["judge_yes"]) or "-",
                      a["claim"]) for a in group]
    if MODE == "--spend":
        lines.append("\nledger batch_used %s" % live_quota.load().get("batch_used"))
    return "\n".join(lines) + "\n"


if MODE == "--check":
    # A synthetic work dir: two claims, one the stub judge splits from the check, so
    # both off-diagonal lists and the grid are exercised. Nothing is sent or written
    # outside the temp dir.
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        for appid in APPIDS:
            for sub in ("claims", "filtered"):
                (work / appid / "data" / sub).mkdir(parents=True)
            (work / appid / "data/filtered" / ("%s.json" % appid)).write_text(json.dumps(
                {"reviews": [{"recommendationid": i, "review_text": "text %s" % i}
                             for i in ("1", "2", "3")]}))
            pre = [{"claim_id": "a", "claim": "Reviewers say A.", "supporting_ids": ["1", "2"]},
                   {"claim_id": "b", "claim": "Reviewers say B.", "supporting_ids": ["2", "3"]}]
            (work / appid / "data/claims" / ("%s.json" % appid)).write_text(json.dumps({
                "game_name": "G%s" % appid, "extraction_report": {"buckets": [{
                    "bucket": "mid", "pre_verify": pre, "verification": {"decisions": [
                        {"claim_id": "a", "backed": ["1", "2"], "outcome": "kept"},
                        {"claim_id": "b", "backed": ["3"], "outcome": "one_reviewer"}]}}]}}))

        def stub(system, user, ids):
            yes = ids if "Reviewers say B." in user else ids[:1]
            return {"citations": [{"recommendationid": i,
                                   "supports": "yes" if i in yes else "no",
                                   "reasoning": "stub"} for i in ids]}
        answers = {}
        stopped = run(work, stub, answers, Path(d) / "answers.json")
        text = report(answers, stopped)
        print(text)
        assert len(answers) == 8, len(answers)
        assert "kept by the check, thin to the judge: 4" in text, text
        assert "demoted or dropped by the check, kept by the judge: 4" in text, text
        print("check passed: nothing sent, nothing written outside a temp dir")
    sys.exit(0)

ec.load_env(str(ROOT / ".env"))
from google import genai  # noqa: E402
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
os.environ["WORTHIT_LEDGER"] = "batch"


def call(system, user, ids):
    resp = ec.call_model(client, ec.DEFAULT_MODEL, system, user, schema=SCHEMA,
                         thinking_level="low")
    return json.loads(ec.response_text(resp)[0])


answers = json.loads(OUT_JSON.read_text("utf-8")) if OUT_JSON.exists() else {}
stopped = run(WORK, call, answers, OUT_JSON)
text = report(answers, stopped)
OUT_TXT.write_text(text, "utf-8")
print(text)
sys.exit(1 if stopped else 0)
