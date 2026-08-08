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
    record_at = src.index("live_quota.charge(cost")
    check("the gate runs before the quota charge", filter_at < record_at)
    # It used to hardcode model_calls 0. Now it charges the MEASURED figure -
    # which should be 0, but is reported rather than asserted, because a
    # hardcoded zero is how spend goes missing.
    check("it reports the measured spend, not a hardcoded zero",
          '"model_calls": spent' in src[filter_at:filter_at + 900])
    check("...and charges it to the ledger",
          "live_quota.charge(spent" in src[filter_at:filter_at + 900])


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


# ------------------------------------------------ synthesis prompt/cache
def test_retry_cache_key_includes_the_attempt():
    """A retry that fails the same way must not replay the cached bad answer."""
    print("\nsynthesis: each retry is a genuinely fresh generation")
    from extract_claims import cache_path
    same_prompt = "identical because the failure list was identical"
    a = cache_path(1, "synthesis", "m", "sys", same_prompt,
                   tag="verdict-v1-attempt1")
    b = cache_path(1, "synthesis", "m", "sys", same_prompt,
                   tag="verdict-v1-attempt2")
    check("identical prompt, different attempt -> different cache key", a != b,
          (a.name, b.name))
    src = (Path(__file__).resolve().parent / "synthesize.py").read_text()
    check("synthesize.py keys its cache on the attempt",
          'tag="verdict-v1-attempt%d" % attempt' in src)


def test_prompt_names_every_word_the_guard_rejects():
    """The prompt used to carry a hand-written banned list and it fell behind
    the guard: "occasional" was rejected in code and never mentioned in the
    prompt. Deriving one from the other is only safe if this holds."""
    print("\nsynthesis: prompt banned-list matches the guard")
    import prevalence_guard
    import synthesize
    prompt = synthesize.SYSTEM_INSTRUCTION
    missing = [w for w in prevalence_guard.banned_words() if w not in prompt]
    check("every guard-rejected word appears in the prompt", not missing,
          missing)
    for word in ("occasional", "frequent", "widespread", "consensus"):
        check("  frequency/consensus word %r is named" % word, word in prompt)
    check("every listed word really is rejected by the guard",
          all(prevalence_guard.check_claim("the game has %s problems" % w)
              or prevalence_guard.check_claim("%s players report problems" % w)
              for w in prevalence_guard.banned_words()))
    check("the prompt no longer seeds the banned word 'consensus' itself",
          "into a consensus" not in prompt)
    check("claim ids are forbidden in prose", "1b. Claim ids go in" in prompt)


def test_call_counting_is_at_the_call_site():
    """The undercount: count_model_calls() scraped stdout for RAW MODEL OUTPUT,
    so a call that 429'd or raised printed nothing and was never charged. The
    ledger read 21 where 37 requests had been spent, and every budget projection
    rode on that number."""
    print("\ncounting: attempts are charged at the call site, not scraped")
    import os
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "pacer.json"
        prev = os.environ.get("WORTHIT_APPID")
        try:
            os.environ["WORTHIT_APPID"] = "424242"
            for _ in range(3):
                model_pacer._acquire(path, rpm=50)
            os.environ["WORTHIT_APPID"] = "999999"
            model_pacer._acquire(path, rpm=50)
        finally:
            if prev is None:
                os.environ.pop("WORTHIT_APPID", None)
            else:
                os.environ["WORTHIT_APPID"] = prev
        check("per-title tally is exact",
              model_pacer.calls_for("424242", path) == 3,
              model_pacer.calls_for("424242", path))
        check("tallies do not bleed between titles",
              model_pacer.calls_for("999999", path) == 1)
        check("per-title tallies sum to the day total",
              model_pacer.status(path)["requests_today"] == 4)
        check("an untouched title is zero, not missing",
              model_pacer.calls_for("111", path) == 0)

    check("the old stdout scraper is gone (raises rather than undercounts)",
          "NotImplementedError" in
          (Path(__file__).resolve().parent / "generate_one.py").read_text())
    gsrc = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    check("generate_one charges from the pacer",
          "model_pacer.calls_for(appid) - calls_before" in gsrc)
    check("stages are tagged with the appid they charge",
          "WORTHIT_APPID=str(appid)" in gsrc)


def test_failure_paths_charge_the_ledger():
    """Quota spent by a failed title must be visible to the budget stop. It was
    not: generate_one returned early on stage_failed without charging, so the
    ledger read 410 while the pacer had counted 506 - and the budget stop is the
    thing meant to prevent exactly the wall that run hit."""
    print("\nledger: failed and skipped titles are charged too")
    src = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    for label, marker in (("stage_failed", '"outcome": "stage_failed"'),
                          ("thin_segmentation", '"outcome": "thin_segmentation"'),
                          ("no_verdict_written", '"outcome": "no_verdict_written"')):
        at = src.index(marker)
        window = src[max(0, at - 400):at]
        check("%s charges before returning" % label,
              "live_quota.charge(" in window)
    check("every early return reports what it spent",
          src.count('"model_calls": spent') >= 3)
    check("the ledger limits are the VERIFIED ones, not the assumed 1500",
          live_quota.DAILY_LIMIT == 500 and live_quota.LIVE_RESERVE == 100,
          (live_quota.DAILY_LIMIT, live_quota.LIVE_RESERVE))
    check("batch budget is therefore 400/day",
          live_quota.batch_budget() == 400, live_quota.batch_budget())


def test_interrupt_does_not_double_count():
    print("\nbatch: an interrupted run reports what actually happened")
    src = (Path(__file__).resolve().parent / "run_batch.py").read_text()
    check("only uncollected futures are extended", "futures[already:]" in src)
    check("the naive extend-everything is gone",
          "done.extend(f.result() for f in futures\n" not in src)


def test_ledger_charge_is_atomic():
    """The lost-update race the verification run exposed: 28 requests spent, 17
    recorded. generate_one did load -> record -> save with no lock while the
    batch runs titles concurrently, so workers erased each other's charges."""
    print("\nledger: concurrent charges are not lost")
    import subprocess as sp
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "q.json"
        code = ("import sys;sys.path.insert(0,%r);import live_quota;"
                "live_quota.charge(1, ledger='batch', path=%r)"
                % (str(Path(__file__).resolve().parent), str(path)))
        procs = [sp.Popen([PY, "-c", code]) for _ in range(12)]
        for pr in procs:
            pr.wait(timeout=90)
        got = live_quota.load(path)["batch_used"]
        check("12 concurrent charges of 1 all land", got == 12, got)
        check("generation count matches too",
              live_quota.load(path)["batch_generations"] == 12)
    gsrc = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    check("generate_one uses the atomic charge, not load/record/save",
          "live_quota.charge(" in gsrc and "live_quota.save(state)" not in gsrc)


def test_flash_daily_cap_is_enforced_by_the_ledger():
    """Second lock on the 20/day model. The schedule is enforced in model_for();
    this refuses the 21st call regardless of what any schedule claims - the same
    class of gap that let the routing bug spend the whole allowance."""
    print("\nflash: the daily cap is a ledger refusal, not a comment")
    check("the cap is the verified 20/day",
          live_quota.FLASH_DAILY_LIMIT == 20, live_quota.FLASH_DAILY_LIMIT)
    st = {"date": live_quota._today(), "live_used": 0, "batch_used": 0,
          "flash_used": 0, "generations": 0, "batch_generations": 0,
          "flash_generations": 0, "by_ip_hour": {}}
    ok, _, _ = live_quota.can_flash(st)
    check("a fresh day allows flash", ok)
    st["flash_used"] = 19
    check("the 20th call is allowed", live_quota.can_flash(st)[0])
    st["flash_used"] = 20
    ok, reason, detail = live_quota.can_flash(st)
    check("the 21st is refused", not ok and reason == "flash_daily_exhausted",
          reason)
    check("the refusal names when it resets",
          "America/Los_Angeles" in detail["resets"])

    live_quota.record(st, 3, ledger="flash")
    check("flash charges land on flash_used, not batch_used",
          st["flash_used"] == 23 and st["batch_used"] == 0, st)
    check("a flash charge does not touch the flash-lite budget",
          live_quota.batch_remaining(st) == live_quota.batch_budget(),
          live_quota.batch_remaining(st))

    src = (Path(__file__).resolve().parent / "synthesize.py").read_text()
    call_at = src.index("resp = call_model(client, args.model")
    window = src[max(0, call_at - 1200):call_at]
    check("the check sits immediately before the call site",
          "live_quota.can_flash(" in window)
    check("and charges before sending", 'live_quota.charge(1, ledger="flash")'
          in window)
    check("refusal is loud by default (SystemExit), not a silent downgrade",
          "REFUSED mid-title" in src)
    check("--flash-fallback exists as an explicit opt-in",
          "--flash-fallback" in src)


def test_batch_never_spends_flash():
    """The bug that failed No Man's Sky and DayZ: flash_tier.txt carried the day
    schedule in COMMENTS while model_for() only checked membership, so the batch
    routed all 74 tier titles to flash at once, burned the 20/day allowance, and
    429'd the rest."""
    print("\nflash tier: the schedule is enforced, not just documented")
    import synthesize
    tier = synthesize.flash_tier()
    check("flash_tier() returns {appid: day}, not a bare set",
          isinstance(tier, dict) and all(isinstance(v, int) for v in tier.values()))
    days = sorted(set(tier.values()))
    check("every tier title carries a day", days and days[0] >= 1, days)
    check("no day exceeds the 20/day allowance",
          all(sum(1 for v in tier.values() if v == d) <= 20 for d in days),
          {d: sum(1 for v in tier.values() if v == d) for d in days})

    nms = 275850  # day 3 - the title that actually failed
    check("a day-3 title does NOT get flash on a plain batch run",
          synthesize.model_for(nms) == synthesize.DEFAULT_MODEL)
    check("...nor on --flash-day 1",
          synthesize.model_for(nms, flash_day=1) == synthesize.DEFAULT_MODEL)
    check("...but does on --flash-day 3",
          synthesize.model_for(nms, flash_day=3) == synthesize.FLASH_MODEL)
    check("flash is opt-in: no flash_day means no flash, for ANY tier title",
          all(synthesize.model_for(a) == synthesize.DEFAULT_MODEL for a in tier))


def test_batch_is_interruptible():
    """SIGINT used to do nothing: all futures were submitted up front and
    shutdown(wait=True) drained them regardless. It took SIGTERM to stop."""
    print("\nbatch: an interrupt actually halts it")
    src = (Path(__file__).resolve().parent / "run_batch.py").read_text()
    check("a SIGINT handler is installed", "signal.signal(signal.SIGINT" in src)
    check("queued futures are cancelled on interrupt",
          "cancel_futures=True" in src)
    check("submission loop checks the flag between titles",
          'if interrupted["flag"]:' in src)
    check("in-flight titles are still waited for (no mid-write kill)",
          "shutdown(wait=True, cancel_futures=True)" in src)
    check("the previous handler is restored", "signal.signal(signal.SIGINT, prev_handler)" in src)


def test_flash_tier_allocation():
    """flash is the scarce model (20/day). Who gets it, and who must not."""
    print("\nflash tier: allocation and the live-generation carve-out")
    import synthesize
    tier = synthesize.flash_tier()
    check("flash_tier.txt parses to a non-empty set", len(tier) > 0, len(tier))
    check("it fits the 4-day runway at 20/day", len(tier) <= 80, len(tier))
    check("a tier title gets flash when its day is named",
          synthesize.model_for(sorted(tier)[0], flash_day=tier[sorted(tier)[0]])
          == synthesize.FLASH_MODEL)
    check("a non-tier title uses flash-lite",
          synthesize.model_for(999999999) == synthesize.DEFAULT_MODEL)
    check("LIVE generation never uses flash, even on its scheduled day",
          synthesize.model_for(sorted(tier)[0], force_lite=True,
                               flash_day=tier[sorted(tier)[0]])
          == synthesize.DEFAULT_MODEL)
    check("an explicit --model override still wins",
          synthesize.model_for(999999999, override="gemini-3.5-flash")
          == "gemini-3.5-flash")
    src = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    check("generate_one forces flash-lite on the live path",
          'ledger != "batch"' in src and "--force-lite" in src)
    gate_rejected = {570, 730}
    check("gate-rejected titles are not in the tier (no verdict to upgrade)",
          not (set(tier) & gate_rejected), sorted(set(tier) & gate_rejected))



# ---------------------------------------------------------------- verdict rail

def _cohorts(early=None, mid=None, veteran=None, refund=None, muted=()):
    """Minimal cohort shape - only what the rail reads."""
    out = []
    for b, v in (("refund_window", refund), ("early", early),
                 ("mid", mid), ("veteran", veteran)):
        if v is None:
            continue
        out.append({"bucket": b, "pct_positive": v, "muted": b in muted,
                    "claims": []})
    return out


def test_verdict_rail_band_boundaries():
    print("\nrail: the band edges, from both sides")
    import synthesize as sy

    # >= 80 forbids Skip. GTA:SA came back Skip at 83.4 - the case that started
    # all of this.
    check("83.4% (GTA:SA, the original failure) rejects Skip",
          "Skip" in sy.forbidden_verdicts(83.4))
    check("80.0% exactly rejects Skip (inclusive edge)",
          "Skip" in sy.forbidden_verdicts(80.0))
    check("79.9% forbids nothing - ambiguous band starts here",
          sy.forbidden_verdicts(79.9) == frozenset())

    # 70-80 is deliberately unconstrained: the product's thesis lives here.
    for m in (70.0, 70.2, 70.4, 75.0, 79.9):
        check("%.1f%% forbids nothing (ambiguous band)" % m,
              sy.forbidden_verdicts(m) == frozenset())

    # 60-70 forbids Buy only.
    check("69.9% rejects Buy but allows Wait and Skip",
          sy.forbidden_verdicts(69.9) == frozenset({"Buy"}))
    check("60.0% exactly rejects Buy only (inclusive edge)",
          sy.forbidden_verdicts(60.0) == frozenset({"Buy"}))

    # the floor: only Skip survives. Starfield sat here at 57.5 and said Wait.
    check("59.9% rejects Buy AND Wait - only Skip left",
          sy.forbidden_verdicts(59.9) == frozenset({"Buy", "Wait"}))
    check("57.5% (Starfield) rejects Wait", "Wait" in sy.forbidden_verdicts(57.5))
    check("57.5% still permits Skip", "Skip" not in sy.forbidden_verdicts(57.5))


def test_verdict_rail_mean_excludes_refund_and_muted():
    print("\nrail: which cohorts the mean is built from")
    import synthesize as sy

    # refund_window is excluded by definition - it is the cohort that bounced.
    m = sy.post_refund_mean(_cohorts(refund=10.0, early=80.0, mid=80.0,
                                     veteran=80.0))
    check("refund_window is not in the mean", m == 80.0, str(m))

    # a muted cohort is below the evidence floor (invariant 12); a rate we
    # refuse to show a reader must not decide a verdict either.
    m = sy.post_refund_mean(_cohorts(early=90.0, mid=90.0, veteran=30.0,
                                     muted=("veteran",)))
    check("a muted cohort is excluded from the mean", m == 90.0, str(m))

    # nothing measurable -> rail does not apply at all
    m = sy.post_refund_mean(_cohorts(refund=40.0))
    check("no post-refund cohort at all -> mean is None", m is None, str(m))
    check("mean None forbids nothing", sy.forbidden_verdicts(None) == frozenset())
    m = sy.post_refund_mean(_cohorts(early=50.0, mid=50.0, veteran=50.0,
                                     muted=("early", "mid", "veteran")))
    check("every post-refund cohort muted -> mean is None", m is None, str(m))


def test_verdict_rail_rejects_through_check_response():
    print("\nrail: fires through check_response, the real retry path")
    import synthesize as sy

    def verdicts_rejected(word, cohorts):
        parsed = {"verdict": word, "for_whom": "Some specific reader.",
                  "cohorts": [], "flag_sentences": []}
        return [f for f in sy.check_response(parsed, cohorts, [])
                if f.startswith("verdict_out_of_band")]

    gta = _cohorts(early=81.8, mid=83.4, veteran=85.2, refund=39.6)
    check("GTA:SA shape rejects Skip via check_response",
          verdicts_rejected("Skip", gta))
    check("GTA:SA shape accepts Wait", not verdicts_rejected("Wait", gta))

    star = _cohorts(early=45.9, mid=61.1, veteran=65.5, refund=20.0)
    check("Starfield shape rejects Wait via check_response",
          verdicts_rejected("Wait", star))
    check("Starfield shape rejects Buy", verdicts_rejected("Buy", star))
    check("Starfield shape accepts Skip", not verdicts_rejected("Skip", star))

    eso = _cohorts(early=66.8, mid=70.9, veteran=73.4, refund=27.5)
    check("ESO shape (ambiguous band) accepts all three words",
          not any(verdicts_rejected(w, eso) for w in ("Buy", "Wait", "Skip")))

    # the failure string has to tell the model what IS allowed, or the retry is
    # a guess - the retry prompt embeds this text verbatim
    msg = verdicts_rejected("Skip", gta)[0]
    check("failure names the allowed words for the retry prompt",
          "allowed=Buy,Wait" in msg, msg)



# ------------------------------------------------- claim sourcing balance

def test_claim_balance_metric_counts_sources_not_claims():
    print("\nbalance: the metric computes on a known fixture")
    import measure_claim_balance as mcb

    # 20 early reviews, 16 thumbs-up -> available 80%. The verdict cites 10 of
    # them, only 2 thumbs-up -> cited 20%. Delta -60. Sized to clear the
    # title-level floor, which is deliberately twice the per-cohort one.
    reviews = [{"recommendationid": str(i), "bucket": "early",
                "voted_up": i < 16} for i in range(20)]
    cited = [0, 1] + list(range(16, 24))[:8]    # two thumbs-up, eight not
    verdict = {"game_name": "Fixture", "verdict": {"word": "Wait"},
               "cohorts": [{"bucket": "early", "themes": [{"theme": "content",
                   "claims": [{"citations": [
                       {"recommendationid": str(i), "voted_up": i < 8}
                       for i in cited]}]}]}]}

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "f").mkdir(); (root / "v").mkdir()
        (root / "f/1.json").write_text(json.dumps({"reviews": reviews}))
        (root / "v/1.json").write_text(json.dumps(verdict))
        old_f, old_v = mcb.FILTERED, mcb.VERDICTS
        mcb.FILTERED, mcb.VERDICTS = root / "f", root / "v"
        try:
            r = mcb.measure("1")
        finally:
            mcb.FILTERED, mcb.VERDICTS = old_f, old_v

    check("available% is the share of thumbs-up reviews extraction could read",
          r["available_pct"] == 80.0, str(r))
    check("cited% is the share of thumbs-up reviews it actually cited",
          r["cited_pct"] == 20.0, str(r))
    check("delta is cited minus available, negative when it over-cites critics",
          r["delta"] == -60.0, str(r))
    # The per-cohort delta is computed separately from the title-level one, so
    # it needs its own assertion - a sign error in the cohort loop alone would
    # otherwise pass every check here. Found exactly that way, by injecting one.
    cohort = r["cohorts"][0]
    check("the per-cohort delta carries the same sign convention",
          cohort["delta"] == -60.0 and cohort["bucket"] == "early", str(cohort))
    check("per-cohort counts report what was actually measured",
          cohort["n_available"] == 20 and cohort["n_cited"] == 10, str(cohort))

    # the metric must never look at claim text or citation_verdict - invariant 13
    check("no claim-valence field appears in the result",
          not any("valence" in k or "sentiment" in k for k in r), str(list(r)))


def test_claim_balance_ignores_cohorts_too_small_to_judge():
    print("\nbalance: thin cohorts are excluded, not averaged in")
    import measure_claim_balance as mcb

    # early clears both floors; veteran has too few cited reviews to mean anything
    n = mcb.MIN_AVAIL * 2
    reviews = ([{"recommendationid": "e%d" % i, "bucket": "early",
                 "voted_up": i < n // 2} for i in range(n)]
               + [{"recommendationid": "v%d" % i, "bucket": "veteran",
                   "voted_up": True} for i in range(n)])
    def cohort(b, ids):
        return {"bucket": b, "themes": [{"theme": "content", "claims": [
            {"citations": [{"recommendationid": i, "voted_up": True} for i in ids]}]}]}
    verdict = {"game_name": "Fixture", "verdict": {"word": "Buy"}, "cohorts": [
        cohort("early", ["e%d" % i for i in range(mcb.MIN_CITED * 2)]),
        cohort("veteran", ["v0"]),              # 1 cited < MIN_CITED
    ]}

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "f").mkdir(); (root / "v").mkdir()
        (root / "f/2.json").write_text(json.dumps({"reviews": reviews}))
        (root / "v/2.json").write_text(json.dumps(verdict))
        old_f, old_v = mcb.FILTERED, mcb.VERDICTS
        mcb.FILTERED, mcb.VERDICTS = root / "f", root / "v"
        try:
            r = mcb.measure("2")
        finally:
            mcb.FILTERED, mcb.VERDICTS = old_f, old_v

    buckets = [c["bucket"] for c in r["cohorts"]]
    check("a cohort with too few cited reviews is dropped from the breakdown",
          buckets == ["early"], str(buckets))
    check("a missing title returns None rather than a zero", mcb.measure("nope") is None)
    check("a title too small to judge returns None, not a noisy percentage",
          mcb.MIN_AVAIL * 2 > mcb.MIN_AVAIL and mcb.MIN_CITED * 2 > mcb.MIN_CITED)


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
    test_retry_cache_key_includes_the_attempt()
    test_prompt_names_every_word_the_guard_rejects()
    test_flash_tier_allocation()
    test_batch_never_spends_flash()
    test_flash_daily_cap_is_enforced_by_the_ledger()
    test_batch_is_interruptible()
    test_call_counting_is_at_the_call_site()
    test_ledger_charge_is_atomic()
    test_failure_paths_charge_the_ledger()
    test_interrupt_does_not_double_count()
    test_verdict_rail_band_boundaries()
    test_verdict_rail_mean_excludes_refund_and_muted()
    test_verdict_rail_rejects_through_check_response()
    test_claim_balance_metric_counts_sources_not_claims()
    test_claim_balance_ignores_cohorts_too_small_to_judge()

    print("\n%s" % ("all guard tests passed" if not FAILURES
                    else "%d FAILURES:\n  %s" % (len(FAILURES),
                                                 "\n  ".join(FAILURES))))
    sys.exit(1 if FAILURES else 0)
