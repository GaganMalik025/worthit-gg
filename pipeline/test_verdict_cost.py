"""
WorthIt.gg - the cost field synthesize.py writes into every verdict

WHY IT EXISTS. /api/generate charges EST_COST=13 before dispatching, because
the check and the spend cannot be atomic across a repository_dispatch boundary
and a burst must not oversubscribe the live reserve. The real median is 9 (295
published titles in data/batch_state.json: p25 7, median 9, p90 12, max 14), so
about a third of every reservation was budget nobody spent - and the ledger
could never learn otherwise, because the runner's GITHUB_TOKEN cannot write
repository variables. The figure therefore rides out in the one artifact the
runner does commit, and the site reads it back.

WHAT THIS PINS. Three things that would each silently break the reconciliation
without breaking anything visible:

  * the field is written at all, as a real integer, by the last stage that
    spends a call;
  * it comes from model_pacer.calls_for() rather than being a constant or a
    stdout scrape - the scrape is what undercounted 37 requests as 21, and a
    constant would refund a number nobody measured;
  * the basis string still says what the number actually is. It is per appid
    per QUOTA DAY per MACHINE, which equals one run's cost on a fresh CI runner
    and does NOT on a dev machine that regenerated the title the same day. A
    future reader treating it as a clean per-run figure on the batch path would
    be wrong, and the basis string is the only thing standing in the way.

Offline: committed seed artifacts only, no Steam, no Gemini, no quota.

    .venv/bin/python pipeline/test_verdict_cost.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flags as flags_mod      # noqa: E402
import model_pacer             # noqa: E402
import synthesize              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APPID = "233860"               # Kenshi - committed seed, real pipeline output

PASSED = []
FAILED = []


def check(label, cond, detail=""):
    (PASSED if cond else FAILED).append(label)
    print("  %s %s%s" % ("ok  " if cond else "FAIL", label,
                         "" if cond else "  <- %s" % detail))


def build(stub_calls):
    """Run assemble() end to end offline, with calls_for stubbed to a known value.

    Everything except the model's own three-part header is real: real claims,
    real filtered corpus, real pool, real flags, real computed verdict word.
    """
    claims_blob, corpus, pool, cohorts = synthesize.load_inputs(
        APPID, str(ROOT / "data/claims"), str(ROOT / "data/filtered"))
    detected = flags_mod.detect(pool)
    word = synthesize.verdict_for_mean(synthesize.post_refund_mean(cohorts))
    parsed = {"tagline": "A brutal sandbox that never explains itself.",
              "for_you_if": ["you like being left alone with a hostile world"],
              "not_for_you_if": ["you want a guided opening hour"]}

    real = model_pacer.calls_for
    model_pacer.calls_for = lambda appid, *a, **k: stub_calls
    try:
        return synthesize.assemble(APPID, claims_blob, corpus, pool, cohorts,
                                   detected, parsed, "gemini-3.5-flash-lite",
                                   word)
    finally:
        model_pacer.calls_for = real


def test_cost_block_shape():
    print("\ncost block shape")
    v = build(9)
    cost = v.get("cost")
    check("assemble() writes a cost block", isinstance(cost, dict),
          "got %r" % type(cost).__name__)
    if not isinstance(cost, dict):
        return
    check("model_calls is an int", isinstance(cost.get("model_calls"), int)
          and not isinstance(cost.get("model_calls"), bool),
          "got %r" % (cost.get("model_calls"),))
    check("basis is a non-empty string",
          isinstance(cost.get("basis"), str) and len(cost["basis"]) > 40,
          "got %r" % (cost.get("basis"),))
    check("the block carries nothing else",
          set(cost) == {"model_calls", "basis"}, "got %s" % sorted(cost))


def test_value_comes_from_the_pacer():
    """A constant, or a stale copy, would pass every shape check above."""
    print("\nthe number is the pacer's, not a constant")
    a, b = build(7), build(14)
    check("model_calls tracks calls_for (7)", a["cost"]["model_calls"] == 7,
          a["cost"]["model_calls"])
    check("model_calls tracks calls_for (14)", b["cost"]["model_calls"] == 14,
          b["cost"]["model_calls"])
    check("the two differ", a["cost"]["model_calls"] != b["cost"]["model_calls"])
    # 14 is not hypothetical: one of 295 published titles really spent it, which
    # is why the site's correction term is allowed to go negative.
    check("a run that overran EST_COST=13 is representable",
          b["cost"]["model_calls"] > 13)


def test_basis_states_the_caveat():
    print("\nthe basis string cannot quietly become a bare number")
    basis = build(9)["cost"]["basis"].lower()
    check("names the quota-day scope", "quota day" in basis, basis)
    check("names the machine scope", "machine" in basis, basis)
    check("warns about same-day regeneration",
          "same-day" in basis or "same day" in basis, basis)
    check("says it never renders", "never rendered" in basis, basis)


def test_real_pacer_round_trip():
    """The stub proves wiring; this proves calls_for itself still counts."""
    print("\nreal pacer attribution (temp state, no network)")
    import os
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "model_pacer.json"
        os.environ["WORTHIT_APPID"] = APPID
        os.environ["WORTHIT_LEDGER"] = "live"
        try:
            for _ in range(3):
                model_pacer._acquire(path, rpm=99, model="gemini-3.5-flash-lite")
            got = model_pacer.calls_for(APPID, path=path)
        finally:
            os.environ.pop("WORTHIT_APPID", None)
            os.environ.pop("WORTHIT_LEDGER", None)
    check("three requests count as three", got == 3, got)
    check("a different appid counts zero",
          model_pacer.calls_for("999999", path=path) == 0)


def test_cost_survives_a_json_round_trip():
    """The site reads this back out of committed JSON, not out of memory."""
    print("\nround trip through the committed artifact")
    v = build(11)
    reread = json.loads(json.dumps(v, ensure_ascii=False))
    check("model_calls survives serialization",
          reread.get("cost", {}).get("model_calls") == 11)
    check("the verdict still carries its own required keys",
          {"appid", "game_name", "verdict", "cohorts", "footer"} <= set(reread))


def main():
    print("=" * 68)
    print("verdict cost field - offline, committed seed artifacts only")
    print("=" * 68)
    test_cost_block_shape()
    test_value_comes_from_the_pacer()
    test_basis_states_the_caveat()
    test_real_pacer_round_trip()
    test_cost_survives_a_json_round_trip()
    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("FAILED: %s" % ", ".join(FAILED))
        return 1
    print("all cost-field tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
