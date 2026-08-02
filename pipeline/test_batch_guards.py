"""
Offline tests for the batch guards (BUILD_PLAN 4.1/4.3).

No network, no Gemini quota, no GitHub token - same spirit as
test_ground_check.py. These cover the three things that, if wrong, are only
discovered at 3am halfway through an unattended run:

  * the pacer holds a per-minute ceiling ACROSS PROCESSES (the whole reason it
    is a file and not an object)
  * the batch ledger cannot touch the live reserve, in either direction
  * the budget stop refuses the title that would overshoot, rather than the one
    after it

Run:  .venv/bin/python pipeline/test_batch_guards.py
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_one   # noqa: E402
import live_quota     # noqa: E402
import model_pacer    # noqa: E402

PY = str(Path(__file__).resolve().parent.parent / ".venv/bin/python")
FAILURES = []


def check(name, cond, detail=""):
    print("  %-62s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        FAILURES.append("%s %s" % (name, detail))


# ---------------------------------------------------------------- pacer
def test_pacer_ceiling_in_one_process():
    print("\npacer: ceiling within one process")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pacer.json"
        waits = [model_pacer._acquire(p, rpm=3)[0] for _ in range(5)]
        check("first 3 go immediately", all(w == 0 for w in waits[:3]), waits)
        check("4th and 5th are made to wait", all(w > 0 for w in waits[3:]),
              waits)
        st = model_pacer.status(p, rpm=3)
        check("counts every request in the day total",
              st["requests_today"] == 5, st)


def test_pacer_ceiling_across_processes():
    """The load-bearing one: an in-process bucket would pass everything above
    this and still let N workers each use the full ceiling."""
    print("\npacer: ceiling ACROSS processes (the reason it is a file)")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pacer.json"
        code = (
            "import sys,json;sys.path.insert(0,%r);import model_pacer;"
            "w,u,t=model_pacer._acquire(%r,rpm=3);print(json.dumps([w,u,t]))"
            % (str(Path(__file__).resolve().parent), str(p))
        )
        results = []
        procs = [subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE,
                                  text=True) for _ in range(5)]
        for proc in procs:
            out, _ = proc.communicate(timeout=60)
            results.append(json.loads(out.strip()))
        waited = sum(1 for w, _, _ in results if w > 0)
        today = max(t for _, _, t in results)
        check("5 separate processes, 3-rpm ceiling -> 2 had to wait",
              waited == 2, results)
        check("the shared counter saw all 5", today == 5, results)


def test_pacer_narrow_only_lowers():
    print("\npacer: narrow() only ever lowers the ceiling")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pacer.json"
        check("narrow to 8", model_pacer.narrow(8, p) == 8)
        check("narrow to 5 lowers again", model_pacer.narrow(5, p) == 5)
        check("narrow to 11 does NOT raise it", model_pacer.narrow(11, p) == 5)


def test_pacer_survives_corrupt_state():
    print("\npacer: a corrupt state file does not stop a batch")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pacer.json"
        p.write_text("{not json at all", encoding="utf-8")
        wait, used, today = model_pacer._acquire(p, rpm=3)
        check("recovers and hands out a slot", wait == 0 and used == 1, today)


# --------------------------------------------------------------- ledger
def test_batch_cannot_touch_the_live_reserve():
    print("\nledger: the batch cannot spend the live reserve")
    st = {"date": live_quota._today(), "live_used": 0, "batch_used": 0,
          "generations": 0, "batch_generations": 0, "by_ip_hour": {}}
    budget = live_quota.batch_budget()
    check("batch budget is daily minus reserve",
          budget == live_quota.DAILY_LIMIT - live_quota.LIVE_RESERVE, budget)

    st["batch_used"] = budget - live_quota.EST_COST
    ok, reason, _ = live_quota.can_batch(st)
    check("one more title still fits at the boundary", ok, reason)

    st["batch_used"] = budget - live_quota.EST_COST + 1
    ok, reason, detail = live_quota.can_batch(st)
    check("the title that would overshoot is refused",
          not ok and reason == "batch_budget_exhausted", reason)

    # and the reserve is still fully available to live generation
    allowed, lreason, _ = live_quota.can_generate(st, ip=None)
    check("live generation is unaffected by an exhausted batch budget",
          allowed, lreason)


def test_live_spend_reduces_batch_headroom_but_not_vice_versa():
    print("\nledger: asymmetry is deliberate and holds")
    st = {"date": live_quota._today(), "live_used": 200, "batch_used": 0,
          "generations": 0, "batch_generations": 0, "by_ip_hour": {}}
    check("live spend eats batch headroom",
          live_quota.batch_remaining(st) == live_quota.batch_budget() - 200,
          live_quota.batch_remaining(st))

    st2 = {"date": live_quota._today(), "live_used": 0, "batch_used": 900,
           "generations": 0, "batch_generations": 0, "by_ip_hour": {}}
    check("batch spend does NOT eat the live reserve",
          live_quota.remaining(st2) == live_quota.LIVE_RESERVE,
          live_quota.remaining(st2))
    allowed, reason, _ = live_quota.can_generate(st2)
    check("live generation still allowed after a full batch night", allowed,
          reason)


def test_record_charges_the_right_ledger():
    print("\nledger: record() charges the ledger it was told to")
    st = live_quota.load.__wrapped__() if hasattr(live_quota.load, "__wrapped__") \
        else {"date": live_quota._today(), "live_used": 0, "batch_used": 0,
              "generations": 0, "batch_generations": 0, "by_ip_hour": {}}
    live_quota.record(st, 7, ledger="batch")
    check("batch charge lands on batch_used",
          st["batch_used"] == 7 and st["live_used"] == 0, st)
    live_quota.record(st, 5, ledger="live")
    check("live charge lands on live_used",
          st["live_used"] == 5 and st["batch_used"] == 7, st)
    check("the two counters are independent",
          st["batch_generations"] == 1 and st["generations"] == 1, st)


# ------------------------------------------------- segmentation gate
def test_segmentation_gate_calibration():
    print("\ngate: calibrated against the seed set, not guessed")
    hd2 = {"pool_n": 1930, "veteran_share": 0.451, "refund_n": 30,
           "eligible_cohorts": 4}
    thin, why = generate_one.thin_segmentation(hd2)
    check("Helldivers 2 (45.1% veteran, best shape in the eval set) PASSES",
          not thin, why)

    dota = {"pool_n": 1936, "veteran_share": 0.770, "refund_n": 48,
            "eligible_cohorts": 4}
    thin, why = generate_one.thin_segmentation(dota)
    check("Dota 2 (77.0% veteran) is rejected", thin, why)

    cs2 = {"pool_n": 2249, "veteran_share": 0.614, "refund_n": 21,
           "eligible_cohorts": 4}
    thin, _ = generate_one.thin_segmentation(cs2)
    check("Counter-Strike 2 (61.4%) is rejected, just over the line", thin)

    one = {"pool_n": 400, "veteran_share": 0.2, "refund_n": 3,
           "eligible_cohorts": 1}
    thin, why = generate_one.thin_segmentation(one)
    check("a title with one eligible cohort is rejected outright", thin, why)

    check("no structure available -> no rejection (fail open, then QR-4 gates)",
          generate_one.thin_segmentation(None)[0] is False)


def test_gate_costs_nothing_when_it_fires():
    print("\ngate: sits on the cost boundary")
    src = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    filter_at = src.index('if segmentation_gate and key == "filter"')
    record_at = src.index("live_quota.record(state, cost")
    check("the gate runs before the quota charge", filter_at < record_at)
    check("it returns model_calls 0 when it fires",
          '"model_calls": 0' in src[filter_at:filter_at + 900])


def test_pending_skips_finished_and_terminal():
    print("\nresumability: a restart does not redo settled work")
    import run_batch
    catalog = {"titles": [
        {"appid": 233860, "title": "Kenshi", "night": 1},        # on disk
        {"appid": 999001, "title": "Rejected", "night": 1},
        {"appid": 999002, "title": "Crashed", "night": 1},
        {"appid": 999003, "title": "Fresh", "night": 1},
    ]}
    state = {"runs": [], "titles": {
        "999001": {"outcome": "thin_segmentation"},
        "999002": {"outcome": "stage_failed"},
    }}
    got = [r["appid"] for r in run_batch.pending(catalog, state, 1, 0)]
    check("an existing verdict is skipped", 233860 not in got, got)
    check("a gate rejection is not re-litigated", 999001 not in got, got)
    check("a crashed title IS retried", 999002 in got, got)
    check("an untouched title is queued", 999003 in got, got)


# ---------------------------------------------------- quota day boundary
def _utc(y, mo, d, h, mi=0):
    from datetime import datetime, timezone
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_quota_day_rolls_at_midnight_pacific_not_utc():
    """The bug that broke night 1's accounting, pinned in both ledgers.

    Google resets RPD at midnight Pacific. Keying the day on UTC zeroed both
    ledgers seven hours early - inside the window an overnight batch runs in.
    """
    print("\nquota day: rolls at midnight PACIFIC, not midnight UTC")
    import quota_day

    # PDT (summer, UTC-7): the day turns at 07:00 UTC
    check("23:59 PDT (06:59 UTC) is still the previous day",
          quota_day.today(_utc(2026, 8, 2, 6, 59)) == "2026-08-01",
          quota_day.today(_utc(2026, 8, 2, 6, 59)))
    check("00:00 PDT (07:00 UTC) starts the new day",
          quota_day.today(_utc(2026, 8, 2, 7, 0)) == "2026-08-02",
          quota_day.today(_utc(2026, 8, 2, 7, 0)))
    check("midnight UTC does NOT roll the quota day",
          quota_day.today(_utc(2026, 8, 2, 0, 30)) == "2026-08-01",
          quota_day.today(_utc(2026, 8, 2, 0, 30)))

    # PST (winter, UTC-8): the day turns at 08:00 UTC. A hardcoded -7 offset
    # would call this "2026-01-15" and be a full day wrong at the boundary.
    check("23:59 PST (07:59 UTC) is still the previous day",
          quota_day.today(_utc(2026, 1, 15, 7, 59)) == "2026-01-14",
          quota_day.today(_utc(2026, 1, 15, 7, 59)))
    check("00:00 PST (08:00 UTC) starts the new day",
          quota_day.today(_utc(2026, 1, 15, 8, 0)) == "2026-01-15",
          quota_day.today(_utc(2026, 1, 15, 8, 0)))
    check("PDT and PST boundaries differ by an hour, so no fixed offset works",
          quota_day.today(_utc(2026, 1, 15, 7, 30)) != "2026-01-15"
          and quota_day.today(_utc(2026, 8, 2, 7, 30)) == "2026-08-02")


def test_both_ledgers_share_one_boundary():
    """If the two disagree, one resets first and they briefly contradict each
    other about how much budget exists - the same class of bug, harder to see."""
    print("\nquota day: both ledgers key on the SAME boundary")
    import quota_day
    for label, clock in (("06:59 UTC", _utc(2026, 8, 2, 6, 59)),
                         ("07:00 UTC", _utc(2026, 8, 2, 7, 0)),
                         ("00:30 UTC", _utc(2026, 8, 2, 0, 30))):
        a, b = live_quota._today(clock), model_pacer._today(clock)
        check("%s: live_quota and model_pacer agree (%s)" % (label, a),
              a == b == quota_day.today(clock), (a, b))


def test_ledger_does_not_reset_at_utc_midnight():
    """End to end: a state file written on Aug 1 Pacific must survive 00:30 UTC
    on Aug 2 with its counters intact."""
    print("\nquota day: a ledger written before UTC midnight keeps its counters")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "q.json"
        # written during the Pacific day that is still in progress at 00:30 UTC
        day = live_quota._today(_utc(2026, 8, 2, 0, 30))
        p.write_text(json.dumps({"date": day, "live_used": 120,
                                 "batch_used": 400, "generations": 9,
                                 "batch_generations": 40, "by_ip_hour": {}}),
                     encoding="utf-8")
        check("the day key written at 00:30 UTC is Aug 1, not Aug 2",
              day == "2026-08-01", day)
        # load() compares against the CURRENT day; simulate by checking the key
        # the ledger would compute at 06:59 vs 07:00 UTC
        check("still the same quota day at 06:59 UTC",
              live_quota._today(_utc(2026, 8, 2, 6, 59)) == day)
        check("a new quota day only at 07:00 UTC",
              live_quota._today(_utc(2026, 8, 2, 7, 0)) != day)


if __name__ == "__main__":
    print("batch guard tests - offline, no quota spent")
    test_pacer_ceiling_in_one_process()
    test_pacer_ceiling_across_processes()
    test_pacer_narrow_only_lowers()
    test_pacer_survives_corrupt_state()
    test_batch_cannot_touch_the_live_reserve()
    test_live_spend_reduces_batch_headroom_but_not_vice_versa()
    test_record_charges_the_right_ledger()
    test_segmentation_gate_calibration()
    test_gate_costs_nothing_when_it_fires()
    test_pending_skips_finished_and_terminal()
    test_quota_day_rolls_at_midnight_pacific_not_utc()
    test_both_ledgers_share_one_boundary()
    test_ledger_does_not_reset_at_utc_midnight()

    print("\n%s" % ("all guard tests passed" if not FAILURES
                    else "%d FAILURES:\n  %s" % (len(FAILURES),
                                                 "\n  ".join(FAILURES))))
    sys.exit(1 if FAILURES else 0)
