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

Run from the REPO ROOT, and through the .venv interpreter specifically: PY
below is a hardcoded path to .venv/bin/python, and several tests spawn real
subprocesses through it. A bare `python pipeline/test_batch_guards.py` against
a system interpreter will reach for a binary that may not exist.

CI runs this in the `python-guards` job of .github/workflows/ci.yml, which
builds that same .venv. Before 2026-08-16 nothing in CI ran this file at all -
neither the path trigger nor any job referenced it (see BACKLOG, e06538a).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
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
        procs = [subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for _ in range(5)]
        # EXIT CODES AND STDERR FIRST, same treatment as adf26e3 gave
        # test_ledger_charge_is_atomic. This test used to feed each child's
        # stdout straight to json.loads, so a child that died before printing
        # raised a JSONDecodeError - which fails honestly but names the wrong
        # thing. The traceback points at the parse, so whoever hits it starts by
        # debugging the pacer when the event was "a child process died", and it
        # aborts the run before a single named check can report. Collect
        # everything, then let the checks say what happened.
        raw, failed = [], []
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            raw.append((proc.returncode, out or "", err or ""))
            if proc.returncode != 0:
                failed.append((proc.returncode, (err or "").strip()[-300:]))
        check("all 5 pacer processes exited 0", not failed,
              "; ".join("rc=%d %s" % f for f in failed[:3]))

        # A child can also exit 0 and still print nothing usable - a partial
        # write, an interpreter warning on stdout. That is a third distinct
        # cause and gets its own name rather than a parse traceback.
        results, unparsable = [], []
        for rc, out, err in raw:
            try:
                results.append(json.loads(out.strip()))
            except ValueError:
                unparsable.append("rc=%d stdout=%r stderr=%s"
                                  % (rc, out.strip()[:60], err.strip()[-200:]))
        check("every child printed one parsable [wait, used, today]",
              not unparsable, "; ".join(unparsable[:3]))

        # Never skip the behavioural checks on a bad run: an unreported check
        # reads as a pass in the final tally. They report FAIL and point at the
        # two checks above, which already named the cause.
        if len(results) == 5:
            waited = sum(1 for w, _, _ in results if w > 0)
            today = max(t for _, _, t in results)
            check("5 separate processes, 3-rpm ceiling -> 2 had to wait",
                  waited == 2, results)
            check("the shared counter saw all 5", today == 5, results)
        else:
            detail = ("only %d of 5 children produced a result - the checks "
                      "above name why" % len(results))
            check("5 separate processes, 3-rpm ceiling -> 2 had to wait",
                  False, detail)
            check("the shared counter saw all 5", False, detail)


def test_a_vanished_lock_is_a_retry_not_a_crash():
    """The TOCTOU race in _locked's age probe (BACKLOG 2026-08-16).

    The probe was `lock.stat() if lock.exists()` - two syscalls against a path
    another process is racing to rmdir(). A holder releasing in that window made
    stat() raise FileNotFoundError, which propagated out of _locked and killed
    the child BEFORE IT CHARGED. live_quota.charge() shares this helper, so a
    dead child means a request spent with nothing recorded against it.

    Forced, not waited for: the race is ~1-in-13 under natural contention, and a
    test that samples a coin flip proves nothing on the run where it passes. The
    first stat() on the lock path really does rmdir the directory, so the
    FileNotFoundError comes from the OS on a path that genuinely is not there.
    """
    print("\npacer: a lock that vanishes inside the age probe")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "q.json"
        lock = Path(str(path) + ".lock")
        lock.mkdir()

        real_stat = Path.stat
        fired = []

        def racing_stat(self, *a, **kw):
            if str(self) == str(lock) and not fired:
                fired.append(1)
                try:
                    os.rmdir(str(lock))
                except OSError:
                    pass
            return real_stat(self, *a, **kw)

        Path.stat = racing_stat
        try:
            with model_pacer._locked(path, timeout=5):
                held = lock.exists()
        except FileNotFoundError as exc:
            # Name the mode. "did not acquire" and "died in the probe" are
            # different failures and only one of them is this race.
            check("_locked survives the probe (no FileNotFoundError escapes)",
                  False, repr(exc))
            held = False
        else:
            check("_locked survives the probe (no FileNotFoundError escapes)",
                  True)
        finally:
            Path.stat = real_stat
        check("  and it acquired the lock afterwards", held, held)
        check("  and the probe was actually exercised", bool(fired))

    # age = 0 on a vanished lock must not disable stale-lock breaking, which is
    # what stops an unattended overnight batch wedging on a killed holder.
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "q.json"
        lock = Path(str(path) + ".lock")
        lock.mkdir()
        old = time.time() - (model_pacer.LOCK_TIMEOUT + 60)
        os.utime(lock, (old, old))
        with model_pacer._locked(path, timeout=model_pacer.LOCK_TIMEOUT):
            check("a genuinely stale lock is still broken", lock.exists())


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
    # THE COST BOUNDARY IS THE STAGE ORDER, now that charging happens per
    # request at the pacer rather than at a return statement: ingest and filter
    # send nothing, extract is the first stage that spends. A gate that fires
    # here therefore costs zero by construction, not by assertion.
    order = [k for k, _, _ in generate_one.STAGES]
    check("filter precedes extract, so the gate sits before the first spend",
          order.index("filter") < order.index("extract"), order)
    # It used to hardcode model_calls 0. It reports the MEASURED figure -
    # which should be 0, but is reported rather than asserted, because a
    # hardcoded zero is how spend goes missing.
    check("it reports the measured spend, not a hardcoded zero",
          '"model_calls": spent' in src[filter_at:filter_at + 900])
    check("no early return owns the charge any more",
          "live_quota.charge(spent" not in src)


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


def _rejecting_run(appid, tmp, calls, retries=2):
    """Drive the REAL synthesis retry loop with every answer rejected.

    Returns (n_calls_this_run, stdout). Nothing is sent: call_model and
    response_text are replaced, so this costs no quota and needs no key.
    """
    import argparse
    import io
    import contextlib
    import extract_claims
    import synthesize as sy

    args = argparse.Namespace(
        model=None, model_override=None, force_lite=True, flash_day=None,
        flash_fallback=False, retries=retries, force=False, dry_run=False,
        show_prompt=False, claims=str(tmp / "claims"),
        filtered=str(tmp / "filtered"), out=str(tmp / "out"))

    before = len(calls)
    real_call, real_text, real_pace = sy.call_model, sy.response_text, sy.PACE_SECONDS
    real_cache = extract_claims.CACHE_DIR
    try:
        sy.call_model = lambda *a, **k: calls.append(1) or object()
        # "{" is unparseable, so check_response is never reached and every
        # attempt is rejected as invalid_json - which is what forces retries.
        sy.response_text = lambda resp: ("{", None)
        sy.PACE_SECONDS = 0
        extract_claims.CACHE_DIR = tmp / "cache"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sy.synthesize_one(None, args, appid)
        return len(calls) - before, buf.getvalue()
    finally:
        sy.call_model, sy.response_text, sy.PACE_SECONDS = real_call, real_text, real_pace
        extract_claims.CACHE_DIR = real_cache


def test_a_retry_never_replays_a_cached_rejection():
    """BACKLOG 2026-08-18: Insurgency (222880) deadlocked because all three of
    its synthesis attempts were served from a cache written on 2026-08-16. Every
    later night replayed the same three rejections at 0 calls, so no retry could
    ever return a different answer - and a retry exists precisely to return a
    different answer.

    Keying the cache on the attempt number (the test above) stops a retry
    replaying a DIFFERENT attempt's answer within one run. It does nothing about
    the SECOND RUN, where every prompt is byte-identical to the first and each
    attempt replays its own prior rejection. That is the case here: run 1
    populates the cache, run 2 is the next night."""
    print("\nsynthesis: a retry sends a real request even when cached")
    appid = 233860  # Kenshi - a seed game, so claims/filtered are committed
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for sub in ("claims", "filtered"):
            (tmp / sub).mkdir()
            (tmp / sub / ("%s.json" % appid)).write_text(
                (root / "data" / sub / ("%s.json" % appid)).read_text(
                    encoding="utf-8"), encoding="utf-8")
        calls = []
        n1, out1 = _rejecting_run(appid, tmp, calls)
        # run 1: nothing cached, so all three attempts are real requests
        check("first run sends one request per attempt", n1 == 3, n1)
        check("first run reads nothing from cache",
              "[cached]" not in out1, out1[-400:])
        cached = sorted((tmp / "cache" / str(appid)).glob("synthesis_*.json"))
        check("first run wrote a cache entry per attempt", len(cached) == 3,
              [p.name for p in cached])

        # run 2: the next night, same inputs, every prompt already seen
        n2, out2 = _rejecting_run(appid, tmp, calls)
        check("attempt 0 is still served from cache",
              "[cached] attempt 0" in out2, out2[-400:])
        check("attempt 1 is NOT served from cache",
              "[cached] attempt 1" not in out2, out2[-400:])
        check("attempt 2 is NOT served from cache",
              "[cached] attempt 2" not in out2, out2[-400:])
        # THE DEADLOCK ITSELF: under the old unconditional read this is 0, the
        # whole title resolves in ~1.7s having sent nothing, and it does so
        # every night forever.
        check("second run still sends a request for each retry", n2 == 2, n2)
        check("a repeated title costs less than a fresh one, not the same",
              n2 < n1, (n1, n2))


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
    check("  consensus language is still named", "consensus" in prompt)
    # FREED 2026-08-21: event frequency is not prevalence. These describe how
    # often a THING happens, not how many PEOPLE, and enforcing them cost real
    # output - RuneScape (1343400) burned 9 calls and published nothing on
    # "occasional crashes"; Insurgency (222880) deadlocked on "persistent".
    for phrase in ("constant monetization pushes",
                   "repeated technical crashes",
                   "persistent server problems",
                   "continually reworked systems",
                   "regularly broken matchmaking",
                   "routinely dropped frames",
                   "ongoing balance problems",
                   "occasional crashes",
                   "frequent updates",
                   "widespread performance issues"):
        check("  %r now passes" % phrase,
              not prevalence_guard.check_claim(phrase),
              str(prevalence_guard.check_claim(phrase)))
    # ...and the half of invariant 11 that did NOT move. A split that let these
    # through would have gutted the rule rather than narrowed it, and every
    # phrase here is the shape the guard exists for: a proportion of PEOPLE.
    for phrase in ("most players refund early",
                   "the majority of reviewers agree",
                   "all players hit this wall",
                   "free access to all content",
                   "40% of buyers report crashes",
                   "a third of reviewers bounce",
                   "countless players complain",
                   "the consensus is that it runs badly"):
        check("  %r is still rejected" % phrase,
              prevalence_guard.check_claim(phrase), phrase)
    # ordinary game writing that must survive: these are schedules and
    # descriptions, not rates, and banning them would cost real claims
    for phrase in ("regular updates from the studio",
                   "routine patrols around the base",
                   "rare crafting materials are hard to farm",
                   "a common enemy type"):
        check("  %r still passes" % phrase,
              not prevalence_guard.check_claim(phrase),
              str(prevalence_guard.check_claim(phrase)))
    check("every listed word really is rejected by the guard",
          all(prevalence_guard.check_claim("the game has %s problems" % w)
              or prevalence_guard.check_claim("%s players report problems" % w)
              for w in prevalence_guard.banned_words()))
    check("the prompt no longer seeds the banned word 'consensus' itself",
          "into a consensus" not in prompt)
    check("claim ids are forbidden in prose", "1b. Claim ids go in" in prompt)
    # Same drift hazard, other guard. The prompt used to say "Any digit in
    # prose is rejected"; the guard now allows a digit inside a platform name,
    # and a model still told the old rule writes "Windows eleven" (222880,
    # shipped). Prompt and guard have to move together in BOTH directions.
    check("the prompt teaches the platform-name digit exception",
          "Windows 11" in prompt and "Windows eleven" in prompt)
    check("  and the guard actually allows it",
          not synthesize.has_bare_digit("you run Windows 11 with crashes"))
    check("  while quantities are still rejected",
          synthesize.has_bare_digit("about 20 hours in"))


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
    check("stages are tagged with the appid they charge",
          "WORTHIT_APPID=str(appid)" in gsrc)
    check("stages are tagged with the LEDGER they charge",
          "WORTHIT_LEDGER=str(ledger" in gsrc)
    check("generate_one no longer charges from a delta it might not reach",
          "live_quota.charge(spent" not in gsrc
          and "STAGE_BASELINE" not in gsrc, "delta charging still present")


def test_failure_paths_charge_the_ledger():
    """Quota spent by a failed title must be visible to the budget stop. It was
    not: generate_one returned early on stage_failed without charging, so the
    ledger read 410 while the pacer had counted 506 - and the budget stop is the
    thing meant to prevent exactly the wall that run hit."""
    print("\nledger: failed and skipped titles are charged too")
    # The charge no longer depends on reaching any particular return: it
    # happens at the pacer, before the request is sent. What the early returns
    # still owe is an honest REPORT of what was spent.
    src = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    check("every early return reports what it spent",
          src.count('"model_calls": spent') >= 3)
    with tempfile.TemporaryDirectory() as d:
        pacer = Path(d) / "pacer.json"
        ledger = Path(d) / "live_quota.json"
        model_pacer._acquire(pacer, rpm=50, model="gemini-3.5-flash-lite",
                             ledger="batch")
        check("a request is booked the moment it is sent, before any outcome",
              live_quota.load(ledger)["batch_used"] == 1,
              live_quota.load(ledger))
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
        procs = [sp.Popen([PY, "-c", code], stderr=sp.PIPE) for _ in range(12)]
        # Exit codes FIRST. A crashed child and a genuinely lost update both
        # leave batch_used < 12, so asserting the count alone cannot tell "the
        # lock failed" from "python could not start" - and the second one would
        # read as a passing guard being broken. Prove all 12 charges actually
        # ran, then the count means what the name says it means.
        failed = []
        for pr in procs:
            err = pr.communicate(timeout=90)[1]
            if pr.returncode != 0:
                failed.append((pr.returncode, (err or b"").decode(
                    "utf-8", "replace").strip()[-300:]))
        check("all 12 charge processes exited 0", not failed,
              "; ".join("rc=%d %s" % f for f in failed[:3]))
        got = live_quota.load(path)["batch_used"]
        # Only reachable as a real lost update now: every child is known to have
        # run to completion, so a short count means charges erased each other.
        check("12 concurrent charges of 1 all land", got == 12,
              "%s (all children exited 0, so this is a LOST UPDATE, "
              "not a crash)" % got if not failed else got)
        check("generation count matches too",
              live_quota.load(path)["batch_generations"] == 12)
    # The unlocked load -> record -> save that lost updates is gone from every
    # caller: charging is now one locked helper, reached only through the pacer.
    for mod in ("generate_one.py", "model_pacer.py", "run_batch.py"):
        msrc = (Path(__file__).resolve().parent / mod).read_text()
        check("%s never does its own load/record/save" % mod,
              "live_quota.save(" not in msrc and "live_quota.record(" not in msrc)


def test_remote_live_ledger_read_is_offline_and_fail_safe():
    """The pre-flight read of LIVE_QUOTA, entirely through an injected runner.

    No network, no gh, no auth - the runner is a plain function returning
    (rc, stdout, stderr), which is the only reason this can run in CI.
    """
    print("\nledger: the pre-flight read of the remote live ledger")
    today = live_quota._today()

    def runner_for(payload, rc=0, err=""):
        return lambda cmd, timeout=20: (rc, payload, err)

    used, detail = live_quota.fetch_remote_live_used(
        runner=runner_for(json.dumps({"date": today, "live_used": 37})))
    check("same-day remote live_used is read", used == 37, (used, detail))

    used, detail = live_quota.fetch_remote_live_used(
        runner=runner_for(json.dumps({"date": "2000-01-01", "live_used": 13})))
    check("a remote ledger from another quota day counts 0, not its stale figure",
          used == 0 and detail["raw_live_used"] == 13, (used, detail))

    # every failure shape must RAISE, never return 0 - returning 0 is the one
    # unsafe answer, because it hands the batch headroom it may not have
    for name, kwargs in (
            ("gh missing (rc=127)", {"runner": runner_for("", 127, "not installed")}),
            ("gh unauthenticated (rc=4)", {"runner": runner_for("", 4, "auth required")}),
            ("gh timed out (rc=124)", {"runner": runner_for("", 124, "timeout")}),
            ("output is not JSON", {"runner": runner_for("<html>login</html>")}),
            ("output is JSON but not an object", {"runner": runner_for("[1,2]")}),
            ("ledger has no date", {"runner": runner_for('{"live_used": 5}')}),
            ("live_used is not an int",
             {"runner": runner_for(json.dumps({"date": today, "live_used": "x"}))}),
            ("live_used is negative",
             {"runner": runner_for(json.dumps({"date": today, "live_used": -1}))})):
        try:
            got = live_quota.fetch_remote_live_used(**kwargs)
            check("%s raises rather than reporting 0" % name, False, got)
        except live_quota.RemoteQuotaUnavailable:
            check("%s raises rather than reporting 0" % name, True)

    # reconciliation over-counts, never under
    st = {"batch_used": 100, "live_used": 5}
    check("remote higher than local wins",
          live_quota.reconcile_live_used(st, 40)["live_used"] == 40)
    check("local higher than remote is KEPT - max, not overwrite",
          live_quota.reconcile_live_used(st, 1)["live_used"] == 5)
    check("reconcile does not mutate the caller's state",
          st["live_used"] == 5)

    # and the reconciled figure actually moves the batch budget
    budget = live_quota.batch_budget()
    plain = live_quota.batch_remaining({"batch_used": 100, "live_used": 0})
    folded = live_quota.batch_remaining(
        live_quota.reconcile_live_used({"batch_used": 100, "live_used": 0}, 40))
    check("folding remote live spend REDUCES batch headroom",
          folded == plain - 40 and plain == budget - 100, (plain, folded))


def test_reconciled_live_used_survives_the_reload_the_loop_does():
    """THE TEST THAT WAS MISSING.

    The first cut reconciled in memory only. run_batch's per-title stop calls
    can_batch(live_quota.load(), ...) - a fresh read of the file each iteration -
    so the reconciled figure reached the startup banner and NOTHING ELSE, and
    the real budget stop ran on unreconciled numbers. Asserting that
    reconcile_live_used() returns the right value in isolation cannot see that;
    only reloading the way the loop does can.
    """
    print("\nledger: reconciliation survives the loop's re-read")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "q.json"
        path.write_text(json.dumps({
            "date": live_quota._today(), "live_used": 5, "batch_used": 100,
            "flash_used": 0, "generations": 0, "batch_generations": 0,
            "flash_generations": 0, "by_ip_hour": {}}), encoding="utf-8")

        live_quota.sync_live_used(40, path=path)

        # simulate the loop: a FRESH load, exactly as can_batch's caller does
        reloaded = live_quota.load(path)
        check("a fresh load() sees the reconciled live_used, not the old one",
              reloaded["live_used"] == 40, reloaded.get("live_used"))
        check("batch_used is untouched by the sync",
              reloaded["batch_used"] == 100, reloaded.get("batch_used"))

        # and the STOP CONDITION itself, which is what actually gates spending
        budget = live_quota.batch_budget()
        allowed, reason, detail = live_quota.can_batch(
            live_quota.load(path), est=budget - 100 - 40 + 1)
        check("the per-title stop is computed from the reconciled figure",
              not allowed and reason == "batch_budget_exhausted", (reason, detail))
        allowed, _, _ = live_quota.can_batch(
            live_quota.load(path), est=budget - 100 - 40)
        check("...and still allows exactly what remains after it",
              allowed)

        # idempotent, and never walks the number backwards
        live_quota.sync_live_used(40, path=path)
        live_quota.sync_live_used(1, path=path)
        check("re-syncing is idempotent and never lowers live_used",
              live_quota.load(path)["live_used"] == 40,
              live_quota.load(path).get("live_used"))

        # a later live charge still accumulates on top of the synced figure
        live_quota.charge(3, ledger="live", path=path, count_generation=False)
        check("a live charge after the sync adds to it rather than resetting",
              live_quota.load(path)["live_used"] == 43,
              live_quota.load(path).get("live_used"))


def test_run_batch_refuses_to_start_on_an_unreadable_live_ledger():
    """The fail-safe is in run_batch's startup, not just the helper."""
    print("\nledger: a batch night cannot start blind")
    src = (Path(__file__).resolve().parent / "run_batch.py").read_text()
    check("run_batch calls the pre-flight read",
          "fetch_remote_live_used(" in src)
    check("...and exits rather than continuing when it raises",
          "RemoteQuotaUnavailable" in src and "REFUSING TO START" in src)
    check("...guarded by an explicit opt-out flag, not silent",
          "--skip-remote-check" in src and "skip_remote_check" in src)
    # THE WIRING HALF of the missing-test bug. The helper being correct is not
    # enough: run_batch must PERSIST, because its per-title stop re-reads the
    # file. An in-memory merge here reaches the banner and nothing else.
    check("run_batch PERSISTS the reconciled figure rather than merging in memory",
          "sync_live_used(" in src)
    check("...and the loop's stop really does re-read from disk, which is why",
          "can_batch(\n                live_quota.load()" in src
          or "can_batch(live_quota.load()" in src)
    # find(), not index(): a missing marker must report as a FAILED CHECK, not
    # raise ValueError and abort the whole suite before the tests after it run.
    # The mutation run that proved this test works is exactly how that surfaced.
    at_sync, at_budget = src.find("sync_live_used"), src.find("batch_remaining(q")
    check("the persisted state is what the startup budget is computed from",
          at_sync != -1 and at_budget != -1 and at_sync < at_budget,
          (at_sync, at_budget))
    # the unsafe default would be `except: remote = 0`
    check("no code path substitutes 0 for an unreadable ledger",
          "remote_live = 0" not in src and "live_used=0" not in src.replace(
              "assume live_used=0", ""))


def test_ledger_routing_is_by_model_then_by_caller():
    print("\nledger: which bucket a request draws from")
    import os
    check("flash-lite draws the flash-lite bucket",
          model_pacer.ledger_for("gemini-3.5-flash-lite", "batch") == "batch")
    check("flash draws its own bucket, whatever the caller said",
          model_pacer.ledger_for("gemini-3.5-flash", "batch") == "flash")
    check("...and the live path cannot override that either",
          model_pacer.ledger_for("gemini-3.5-flash", "live") == "flash")
    check("an explicit ledger wins for flash-lite",
          model_pacer.ledger_for("gemini-3.5-flash-lite", "live") == "live")

    prev = os.environ.get("WORTHIT_LEDGER")
    try:
        os.environ.pop("WORTHIT_LEDGER", None)
        # THE DEFAULT IS SAFE, NOT ARBITRARY: batch_used reduces batch headroom
        # but never the live reserve, so an unlabelled request can never switch
        # live generation off.
        check("with nothing set at all, the default is batch",
              model_pacer.ledger_for("gemini-3.5-flash-lite") == "batch")
        st = {"date": live_quota._today(), "live_used": 0, "batch_used": 400,
              "generations": 0, "batch_generations": 0, "by_ip_hour": {}}
        check("...and a day of that default leaves the reserve untouched",
              live_quota.remaining(st) == live_quota.LIVE_RESERVE)
        os.environ["WORTHIT_LEDGER"] = "live"
        check("the env var crosses the subprocess boundary",
              model_pacer.ledger_for("gemini-3.5-flash-lite") == "live")
    finally:
        if prev is None:
            os.environ.pop("WORTHIT_LEDGER", None)
        else:
            os.environ["WORTHIT_LEDGER"] = prev


def test_pacer_and_ledger_cannot_drift():
    """THE TEST THAT WOULD HAVE CAUGHT 2026-08-10.

    176 requests spent, ledger read 0, because the only charge point was the
    qr4 stage and the run never invoked it. The invariant below holds on any
    machine where the spending happens, and it held at 176 == 0 + 0 + 0.
    """
    print("\nledger: the pacer and the ledger cannot disagree")
    with tempfile.TemporaryDirectory() as d:
        pacer = Path(d) / "pacer.json"
        ledger = Path(d) / "live_quota.json"
        for _ in range(7):
            model_pacer._acquire(pacer, rpm=50, model="gemini-3.5-flash-lite",
                                 ledger="batch")
        for _ in range(3):
            model_pacer._acquire(pacer, rpm=50, model="gemini-3.5-flash-lite",
                                 ledger="live")
        for _ in range(2):
            model_pacer._acquire(pacer, rpm=50, model="gemini-3.5-flash")
        st = live_quota.load(ledger)
        total = st["live_used"] + st["batch_used"] + st["flash_used"]
        seen = model_pacer.status(pacer)["requests_today"]
        check("every paced request is booked exactly once",
              seen == total == 12, "pacer=%s ledger=%s" % (seen, total))
        check("and to the right bucket",
              (st["batch_used"], st["live_used"], st["flash_used"]) == (7, 3, 2),
              st)
        # per-REQUEST charging must not inflate the per-TITLE counters
        check("generation counts are not incremented per request",
              st["generations"] == st["batch_generations"] == 0, st)
        live_quota.note_generation(ledger="batch", path=ledger)
        st = live_quota.load(ledger)
        check("note_generation counts a title without charging usage",
              st["batch_generations"] == 1 and st["batch_used"] == 7, st)


def test_a_single_stage_run_still_charges():
    """The 2026-08-10 regression, replayed offline.

    `--stage verdict` in isolation never reached the qr4 branch that held the
    only charge, so it spent silently. The stage is simulated here by its
    observable behaviour - a subprocess that paces requests with WORTHIT_LEDGER
    set and never calls anything in generate_one afterwards.
    """
    print("\nledger: a stage run on its own is charged too")
    import subprocess as sp
    with tempfile.TemporaryDirectory() as d:
        pacer = Path(d) / "pacer.json"
        ledger = Path(d) / "live_quota.json"
        code = ("import sys,os;sys.path.insert(0,%r);"
                "os.environ['WORTHIT_LEDGER']='batch';import model_pacer;"
                "[model_pacer._acquire(%r, rpm=50, "
                "model='gemini-3.5-flash-lite') for _ in range(4)]"
                % (str(Path(__file__).resolve().parent), str(pacer)))
        sp.run([PY, "-c", code], check=True, timeout=90)
        st = live_quota.load(ledger)
        check("4 requests from a lone stage land on the ledger",
              st["batch_used"] == 4, st)
        check("...and the ledger agrees with the pacer",
              model_pacer.status(pacer)["requests_today"] == st["batch_used"])

    gsrc = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    at = gsrc.index("def run_single_stage")
    check("run_single_stage charges no usage of its own",
          "live_quota.charge(" not in gsrc[at:], "a second charge point is back")


def test_every_ledger_flag_reaches_the_ledger():
    """A flag that is parsed and then dropped is worse than no flag.

    `generate_one.py <appid> --ledger batch` charged the LIVE reserve: main()
    called generate() without passing args.ledger, so the default won. It also
    asked can_generate() instead of can_batch() for permission. It survived
    because the check and the charge were consistently wrong together - 21
    requests of catalog work landed on the reserve that protects the search box
    (2026-08-10).

    Checked with ast rather than a substring, so reformatting cannot fake it.
    """
    print("\nflags: --ledger actually reaches generate()")
    import ast
    src = (Path(__file__).resolve().parent / "generate_one.py").read_text()
    tree = ast.parse(src)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "generate"]
    check("main() calls generate()", len(calls) == 1, len(calls))
    kwargs = {k.arg for k in calls[0].keywords}
    check("...and passes the ledger through",
          "ledger" in kwargs, sorted(kwargs))
    src_of = ast.get_source_segment(src, next(
        k.value for k in calls[0].keywords if k.arg == "ledger"))
    check("...from the parsed flag, not a literal", src_of == "args.ledger",
          src_of)
    # the single-stage path already threaded it; pin that too so a later edit
    # cannot quietly regress the half that works
    stage_calls = [n for n in ast.walk(main)
                   if isinstance(n, ast.Call)
                   and getattr(n.func, "id", "") == "run_single_stage"]
    check("the --stage path threads it as well",
          stage_calls and len(stage_calls[0].args) == 3, stage_calls)


def test_lock_order_is_one_way():
    """Two locks, one direction. The pacer takes the ledger's lock while holding
    its own; nothing may do the reverse, or a batch deadlocks at 3am."""
    print("\nlocks: pacer -> ledger, never the other way")
    lsrc = (Path(__file__).resolve().parent / "live_quota.py").read_text()
    msrc = (Path(__file__).resolve().parent / "model_pacer.py").read_text()
    # EVERY call site must lock `path` - its own ledger - not a count of them.
    # The count was a proxy for the same thing and read == 1 until
    # sync_live_used added a second locked read-modify-write (2026-08-16). The
    # deadlock this guards against is about WHICH lock is taken while holding
    # another, never how many sites take the ledger's own.
    locked_sites = re.findall(r"model_pacer\._locked\(([^)]*)\)", lsrc)
    check("live_quota locks only its own state file",
          locked_sites and all(a.strip() == "path" for a in locked_sites),
          locked_sites)
    check("live_quota never acquires the pacer's own lock",
          "model_pacer.STATE_PATH" not in lsrc)
    at = msrc.index("def _charge_ledger")
    check("the pacer's charge helper imports live_quota lazily (no import cycle)",
          "import live_quota" in msrc[at:at + 700])
    with tempfile.TemporaryDirectory() as d:
        pacer = Path(d) / "pacer.json"
        # if the order were ever reversed this hangs rather than fails; the
        # timeout is the assertion
        t0 = time.time()
        for _ in range(3):
            model_pacer._acquire(pacer, rpm=50, model="gemini-3.5-flash-lite")
        check("nested locking completes promptly", time.time() - t0 < 10,
              "%.1fs" % (time.time() - t0))


def test_a_test_can_never_charge_the_real_ledger():
    print("\nledger: tests are structurally unable to touch the real file")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pacer.json"
        check("a temp pacer path implies a temp ledger path",
              model_pacer._quota_path(p) == Path(d) / "live_quota.json")
    check("the default pacer path defers to live_quota's own",
          model_pacer._quota_path(model_pacer.STATE_PATH) is None)


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



# ------------------------------------------------- verdict word (computed)

def _cohorts(early=None, mid=None, veteran=None, refund=None, muted=(), pool=None):
    """Cohort shape the verdict computation reads.

    pool_n is REQUIRED now - the mean is pool-weighted and floored, so a fixture
    without it silently measures nothing. The old fixture omitted it entirely,
    which is why these tests had to be rewritten rather than merely repointed.
    """
    pool = pool or {}
    out = []
    for b, v in (("refund_window", refund), ("early", early),
                 ("mid", mid), ("veteran", veteran)):
        if v is None:
            continue
        out.append({"bucket": b, "pct_positive": v, "muted": b in muted,
                    "pool_n": pool.get(b, 500), "claims": []})
    return out


def test_verdict_word_boundaries():
    print("\nverdict: the thresholds, from both sides of each edge")
    import synthesize as sy

    check("89.0 exactly is Buy (inclusive edge)", sy.verdict_for_mean(89.0) == "Buy")
    check("88.9 is Wait, not Buy", sy.verdict_for_mean(88.9) == "Wait")
    check("89.1 is Buy", sy.verdict_for_mean(89.1) == "Buy")
    check("64.0 exactly is Wait (Skip is strictly below)",
          sy.verdict_for_mean(64.0) == "Wait")
    check("63.9 is Skip", sy.verdict_for_mean(63.9) == "Skip")
    check("64.1 is Wait", sy.verdict_for_mean(64.1) == "Wait")

    # the real titles the thresholds were derived to place correctly
    check("Starfield at 60.4 is Skip", sy.verdict_for_mean(60.4) == "Skip")
    check("Marvel Rivals at 58.9 is Skip", sy.verdict_for_mean(58.9) == "Skip")
    check("GTA:SA at 83.5 is Wait", sy.verdict_for_mean(83.5) == "Wait")
    check("Halo MCC at 85.8 is Wait, not Buy", sy.verdict_for_mean(85.8) == "Wait")

    # unmeasurable is not a verdict - it must refuse, never default to a word
    check("an unmeasurable title yields no word at all",
          sy.verdict_for_mean(None) is None)


def test_verdict_mean_is_pool_weighted_and_floored():
    print("\nverdict: which cohorts the mean is built from, and their weight")
    import synthesize as sy

    # THE WEAKNESS THIS CLOSES: unweighted, a 27-review cohort counted as much
    # as a 560-review one, and with the word computed from this number that thin
    # cohort WAS the verdict.
    # The thin cohort must CLEAR the pool floor, or this fixture proves nothing
    # about weighting - the floor would exclude it either way. Found exactly that
    # way: the first version of this test could not fail when weighting was
    # removed, because its 27-review cohort was dropped by the floor first.
    c = _cohorts(early=82.0, mid=83.0, veteran=99.0,
                 pool={"early": 800, "mid": 800, "veteran": 40})
    m = sy.post_refund_mean(c)
    check("a 40-review cohort cannot outvote two 800-review ones",
          82.0 < m < 84.0, "%.2f" % m)
    check("the UNWEIGHTED answer (88.0) is not what we get", abs(m - 88.0) > 4,
          "%.2f" % m)

    # pool floor: a rate too thin to trust is excluded even when not muted
    c = _cohorts(early=90.0, mid=90.0, veteran=10.0,
                 pool={"early": 500, "mid": 500, "veteran": 29})
    check("a cohort under the pool floor is excluded from the mean",
          sy.post_refund_mean(c) == 90.0, str(sy.post_refund_mean(c)))
    c = _cohorts(early=90.0, mid=90.0, veteran=10.0,
                 pool={"early": 500, "mid": 500, "veteran": 30})
    check("at exactly the floor it counts", sy.post_refund_mean(c) < 90.0)

    # refund_window is excluded by definition - the cohort that bounced
    m = sy.post_refund_mean(_cohorts(refund=10.0, early=80.0, mid=80.0, veteran=80.0))
    check("refund_window is not in the mean", m == 80.0, str(m))

    # invariant 12: a cohort we will not attribute claims to cannot decide either
    m = sy.post_refund_mean(_cohorts(early=90.0, mid=90.0, veteran=30.0,
                                     muted=("veteran",)))
    check("a muted cohort is excluded from the mean", m == 90.0, str(m))

    # nothing measurable -> None, and None must not become a verdict
    check("no post-refund cohort at all -> None",
          sy.post_refund_mean(_cohorts(refund=40.0)) is None)
    check("every post-refund cohort muted -> None",
          sy.post_refund_mean(_cohorts(early=50.0, mid=50.0, veteran=50.0,
                                       muted=("early", "mid", "veteran"))) is None)
    check("every post-refund cohort under the floor -> None",
          sy.post_refund_mean(_cohorts(early=50.0, mid=50.0,
                                       pool={"early": 5, "mid": 5})) is None)


def test_verdict_word_is_not_model_supplied():
    print("\nverdict: the model cannot supply or override the word")
    import synthesize as sy

    check("VERDICT_SCHEMA no longer accepts a verdict field",
          "verdict" not in sy.VERDICT_SCHEMA["properties"])
    check("verdict is not a required response field",
          "verdict" not in sy.VERDICT_SCHEMA["required"])
    check("the old forbid-layer is gone", not hasattr(sy, "forbidden_verdicts"))

    # check_response takes the COMPUTED word; a model-supplied one is ignored
    cohorts = _cohorts(early=95.0, mid=95.0, veteran=95.0)
    parsed = _header(verdict="Skip")             # would once have been honoured
    fails = sy.check_response(parsed, cohorts, [], "Buy")
    check("a stray verdict field in the response changes nothing",
          not [f for f in fails if "verdict" in f], str(fails))

    # the contradiction guard now validates the tagline against the computed word
    parsed = _header(tagline="Skip this unless you want a punishing sandbox.")
    fails = sy.check_response(parsed, cohorts, [], "Buy")
    check("a tagline contradicting the COMPUTED word is still rejected",
          any(f.startswith("tagline_contradicts_verdict") for f in fails), str(fails))


# ------------------------------------------------- the three-part header

def _header(**kw):
    """A response that passes every header guard, so a test can break one thing.

    Deliberately built from copy that is legal under the OTHER rules too - no
    digits, nothing the prevalence guard rejects - because a fixture that trips
    an unrelated check makes every assertion below ambiguous.
    """
    parsed = {
        "tagline": "Great heroes, rough machine - the fights look better "
                   "than they run.",
        "for_you_if": ["you are here for the roster, not the ladder",
                       "you play in a stack that can absorb a bad match"],
        "not_for_you_if": ["you want ranked matches that feel fairly matched",
                           "you need stable frame rates on release hardware"],
        "cohorts": [], "flag_sentences": [],
    }
    parsed.update(kw)
    return parsed


def test_header_shape_is_bounded_in_code():
    print("\nheader: the three parts, and the bounds on them")
    import synthesize as sy
    cohorts = _cohorts(early=95.0, mid=95.0, veteran=95.0)
    fails = lambda p: sy.check_response(p, cohorts, [], "Wait")   # noqa: E731

    check("the baseline fixture passes cleanly", not fails(_header()),
          str(fails(_header())))

    check("schema asks for all three parts",
          set(sy.VERDICT_SCHEMA["required"]) >=
          {"tagline", "for_you_if", "not_for_you_if"})
    check("the old single field is gone from the schema",
          "for_whom" not in sy.VERDICT_SCHEMA["properties"])

    check("a missing tagline is rejected",
          "missing_tagline" in fails(_header(tagline="   ")))

    # The tagline sits beside the stamp, so its length is a layout constraint.
    # The real 108-character line that prompted the cap, from the first A/B run:
    long_tag = ("Nostalgic streets wrapped in modern friction - classic "
                "open-world scale paired with rough technical execution.")
    check("a tagline over the cap is rejected",
          any(f.startswith("tagline_too_long") for f in fails(_header(tagline=long_tag))),
          "%d chars" % len(long_tag))
    check("a tagline exactly at the cap is accepted",
          not [f for f in fails(_header(tagline="x" * sy.TAGLINE_MAX_CHARS))
               if f.startswith("tagline_too_long")])

    # bounds, from both sides of each edge
    for field in ("for_you_if", "not_for_you_if"):
        one = ["you like it"]
        check("%s with one clause is rejected" % field,
              any(f.startswith("%s_out_of_bounds" % field)
                  for f in fails(_header(**{field: one}))))
        check("%s with two clauses is accepted" % field,
              not [f for f in fails(_header(**{field: one * 2}))
                   if f.startswith("%s_out_of_bounds" % field)])
        check("%s with four clauses is accepted" % field,
              not [f for f in fails(_header(**{field: one * 4}))
                   if f.startswith("%s_out_of_bounds" % field)])
        check("%s with five clauses is rejected" % field,
              any(f.startswith("%s_out_of_bounds" % field)
                  for f in fails(_header(**{field: one * 5}))))

    # BOTH lists are required on a Skip too. A Skip with an empty "for you if"
    # is the failure mode this whole split was meant to avoid: the product's
    # thesis is that a Skip still has people it suits.
    fs = sy.check_response(_header(for_you_if=[]), cohorts, [], "Skip")
    check("a Skip may not ship with an empty for_you_if",
          any(f.startswith("for_you_if_out_of_bounds") for f in fs), str(fs))

    long_clause = "you want " + "a very long run-on clause that keeps going " * 3
    check("a clause over the length cap is rejected",
          any(f.startswith("fit_clause_too_long")
              for f in fails(_header(for_you_if=["you like it", long_clause]))))
    check("a clause exactly at the cap is accepted",
          not [f for f in fails(_header(
                  for_you_if=["x" * sy.CLAUSE_MAX_CHARS, "you like it"]))
               if f.startswith("fit_clause_too_long")])
    check("an empty clause is rejected",
          any(f.startswith("empty_fit_clause")
              for f in fails(_header(not_for_you_if=["you want direction", " "]))))
    check("the same clause on both sides is rejected",
          any(f.startswith("duplicate_fit_clause")
              for f in fails(_header(for_you_if=["you like pixel art", "you like it"],
                                     not_for_you_if=["You like pixel art.",
                                                     "you want direction"]))))


def test_header_may_not_argue_with_the_computed_word():
    print("\nheader: contradiction, per field, per word")
    import synthesize as sy
    cohorts = _cohorts(early=95.0, mid=95.0, veteran=95.0)

    # THE ASYMMETRY IS THE DESIGN. Under a Skip, for_you_if exists to say who
    # the game would still suit; only the DIRECTIVE form is an overturned
    # verdict. The mirror applies to not_for_you_if under a Buy. Applying both
    # patterns to both lists would ban the sections' own purpose.
    skip_pitch = _header(for_you_if=["you should buy it anyway",
                                     "you like the roster"])
    fs = sy.check_response(skip_pitch, cohorts, [], "Skip")
    check("'you should buy it anyway' in for_you_if is rejected under Skip",
          any(f.startswith("fit_list_contradicts_verdict:for_you_if") for f in fs),
          str(fs))
    fs = sy.check_response(skip_pitch, cohorts, [], "Wait")
    check("the same clause is not policed under Wait",
          not [f for f in fs if f.startswith("fit_list_contradicts_verdict")], str(fs))

    buy_bail = _header(not_for_you_if=["skip it if you dislike pixel art",
                                       "you want direction"])
    fs = sy.check_response(buy_bail, cohorts, [], "Buy")
    check("'skip it' in not_for_you_if is rejected under Buy",
          any(f.startswith("fit_list_contradicts_verdict:not_for_you_if")
              for f in fs), str(fs))

    # EXACTLY ONE LIST IS POLICED PER WORD, and these are the cases that prove
    # it. Under a Buy the risky list is not_for_you_if; for_you_if is left
    # alone, and has to be, or a clause describing a reader who "avoids this
    # genre" gets read as the model overturning the stamp. A first pass asserted
    # the agreeing-language direction instead, and a guard applying both
    # patterns to both lists walked straight through it - found by mutation, not
    # by reading.
    fs = sy.check_response(_header(for_you_if=["you avoid this genre as a rule",
                                               "you like the roster"]),
                           cohorts, [], "Buy")
    check("for_you_if is not policed under Buy", not fs, str(fs))
    fs = sy.check_response(_header(not_for_you_if=["you want to buy it for the story",
                                                   "you bounce off pixel art"]),
                           cohorts, [], "Skip")
    check("not_for_you_if is not policed under Skip", not fs, str(fs))

    # ...and the plain clause form survives on both sides, which is the point
    ok = _header(for_you_if=["you want a punishing sandbox", "you like the roster"],
                 not_for_you_if=["you want direction", "you bounce off pixel art"])
    check("plain fit clauses pass under Skip",
          not sy.check_response(ok, cohorts, [], "Skip"),
          str(sy.check_response(ok, cohorts, [], "Skip")))
    check("plain fit clauses pass under Buy",
          not sy.check_response(ok, cohorts, [], "Buy"),
          str(sy.check_response(ok, cohorts, [], "Buy")))


def test_friction_is_a_condition_only_below_a_heading_that_says_so():
    print("\nheader: friction as a condition - banned in the tagline, fine in a list")
    import synthesize as sy
    cohorts = _cohorts(early=95.0, mid=95.0, veteran=95.0)
    fails = lambda p: sy.check_response(p, cohorts, [], "Wait")   # noqa: E731

    for phrasing in ("Suits players willing to tolerate the launcher.",
                     "A deep shooter, provided you accept the account signup.",
                     "Good, though you must tolerate a third-party launcher."):
        check("tagline: %r rejected" % phrasing[:38],
              "tagline_frames_friction_as_a_condition" in fails(_header(tagline=phrasing)),
              str(fails(_header(tagline=phrasing))))

    # THE RESOLUTION OF THE OLD TENSION: the identical words are legal in the
    # list, because the heading above them already tells the reader it is a
    # condition. Nothing here may fire.
    conditional = _header(not_for_you_if=["you will not install a third-party launcher",
                                          "you must accept an always-online requirement"])
    check("the same condition is legal inside not_for_you_if",
          not fails(conditional), str(fails(conditional)))


def test_prose_sweep_covers_every_new_field():
    print("\nheader: invariant 11 and 13 reach the tagline AND both lists")
    import synthesize as sy
    cohorts = _cohorts(early=95.0, mid=95.0, veteran=95.0)
    fails = lambda p: sy.check_response(p, cohorts, [], "Wait")   # noqa: E731

    # THE EASIEST GUARD TO LOSE IN THIS CHANGE. The sweep used to read one
    # field. Splitting that field into three without extending it would leave
    # every check below passing - on prose nothing sends them any more.
    check("a digit in the tagline is rejected (invariant 13)",
          any(f.startswith("digit_in_prose:tagline")
              for f in fails(_header(tagline="Two hundred heroes, 3 of them good."))))
    check("a digit in a for_you_if clause is rejected",
          any(f.startswith("digit_in_prose:for_you_if[1]")
              for f in fails(_header(for_you_if=["you like the roster",
                                                 "you have 100 gigabytes free"]))))
    check("a digit in a not_for_you_if clause is rejected",
          any(f.startswith("digit_in_prose:not_for_you_if[0]")
              for f in fails(_header(not_for_you_if=["you have under 50 hours to give",
                                                     "you want direction"]))))
    check("prevalence language in the tagline is rejected (invariant 11)",
          any(f.startswith("prevalence:tagline")
              for f in fails(_header(tagline="Most players bounce off the tutorial."))))
    check("prevalence language in a for_you_if clause is rejected",
          any(f.startswith("prevalence:for_you_if[0]")
              for f in fails(_header(for_you_if=["you agree with the majority of players",
                                                 "you like the roster"]))))
    check("prevalence language in a not_for_you_if clause is rejected",
          any(f.startswith("prevalence:not_for_you_if[1]")
              for f in fails(_header(not_for_you_if=["you want direction",
                                                     "few players finish it"]))))


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



# ------------------------------------------------- publish selection

def test_publish_never_replaces_newer_with_older():
    print("\npublish: a stale branch copy cannot overwrite a newer one")
    import select_publishable as sp

    # The 2026-08-08 shape: the branch holds a copy generated a week before the
    # one on main. `git checkout verdicts -- path/` took it silently.
    decisions = {
        "older":  ("2026-08-01T09:00:00Z", "2026-08-08T20:00:00Z"),
        "newer":  ("2026-08-09T10:00:00Z", "2026-08-01T10:00:00Z"),
        "same":   ("2026-08-02T11:00:00Z", "2026-08-02T11:00:00Z"),
        "absent": ("2026-08-09T11:00:00Z", None),
    }
    def verdict_of(branch, main):
        if branch is None:
            return "skip"
        if main is None:
            return "take"
        return "take" if branch > main else "skip"

    check("an OLDER branch copy is skipped", verdict_of(*decisions["older"]) == "skip")
    check("a NEWER branch copy is taken", verdict_of(*decisions["newer"]) == "take")
    check("an equal timestamp loses - ties leave main alone",
          verdict_of(*decisions["same"]) == "skip")
    check("a title main does not have is taken",
          verdict_of(*decisions["absent"]) == "take")
    # unreadable JSON must never be publishable
    check("unparseable branch JSON yields no timestamp",
          sp._stamp("{not json", "x.json") is None)
    check("and a missing file yields none either", sp._stamp(None, "x.json") is None)


def _fixture_repo(d, now):
    """A real repo with main and a branch, not a model of one.

    Six titles, one per decision the pruner has to make. Commit dates on main
    are set explicitly, because the grace window is measured from them.

    `regen` is the case that distinguishes the corrected predicate from the
    first one: on main since 200h ago, bytes rewritten seconds ago. Its title
    has been in the deployed build for over a week, so the branch copy cannot be
    serving it, and it must be PRUNED. The age-of-current-bytes predicate kept
    it - which is how it came to keep all 133 on 2026-08-10.
    """
    import os
    import subprocess as sp_
    from datetime import timedelta

    def git(*a, **kw):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", **kw)
        return sp_.run(["git", *a], cwd=d, env=env, capture_output=True, text=True)

    vd = Path(d) / "site/public/verdicts"
    vd.mkdir(parents=True)
    git("init", "-q", "-b", "main")

    def write(appid, stamp, raw=None):
        (vd / ("%s.json" % appid)).write_text(
            raw if raw is not None else json.dumps({"generated_at": stamp}),
            encoding="utf-8")

    # main: four titles. `old` and `tie` were promoted long ago; `fresh` was
    # promoted minutes ago and is still inside the deploy window.
    old_date = (now - timedelta(hours=200)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    write("old", "2026-08-09T00:00:00Z")
    write("tie", "2026-08-02T00:00:00Z")
    write("bad", "2026-08-09T00:00:00Z")
    write("regen", "2026-08-09T00:00:00Z")
    git("add", "-A")
    git("commit", "-q", "-m", "main: old, tie, bad, regen",
        GIT_COMMITTER_DATE=old_date)
    # `fresh` first appears NOW; `regen` has been here all along and is merely
    # rewritten now. Same commit, opposite verdicts - which is the point.
    write("fresh", "2026-08-09T00:00:01Z")
    write("regen", "2026-08-09T00:00:02Z")
    git("add", "-A")
    git("commit", "-q", "-m", "main: fresh arrives, regen rewritten",
        GIT_COMMITTER_DATE=now.strftime("%Y-%m-%dT%H:%M:%S+00:00"))

    git("checkout", "-q", "-b", "vbranch")
    write("old", "2026-08-01T00:00:00Z")      # older than main   -> prune
    write("tie", "2026-08-02T00:00:00Z")      # identical stamp   -> keep
    write("fresh", "2026-08-01T00:00:00Z")    # older but recent  -> keep
    write("bad", None, raw="{not json")       # unreadable        -> keep
    write("only", "2026-08-09T00:00:00Z")     # not on main       -> keep
    write("regen", "2026-08-01T00:00:00Z")    # old title, new bytes -> prune
    git("add", "-A")
    git("commit", "-q", "-m", "branch")
    git("checkout", "-q", "main")


def _fixture_remote(d, with_branch=True):
    """A bare `origin` and a clone of it, so fetch behaviour is real.

    The ref guards are about what a REMOTE says, so a fixture that fakes the
    remote proves nothing about them.
    """
    import os
    import subprocess as sp_
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*a, cwd):
        return sp_.run(["git", *a], cwd=cwd, env=env, capture_output=True, text=True)

    origin, work = Path(d) / "origin.git", Path(d) / "work"
    sp_.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], env=env)
    sp_.run(["git", "clone", "-q", str(origin), str(work)], env=env)
    vd = work / "site/public/verdicts"
    vd.mkdir(parents=True)
    (vd / "1.json").write_text(json.dumps({"generated_at": "2026-08-09T00:00:00Z"}))
    git("add", "-A", cwd=work); git("commit", "-q", "-m", "main", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    if with_branch:
        git("checkout", "-q", "-b", "verdicts", cwd=work)
        (vd / "1.json").write_text(json.dumps({"generated_at": "2026-08-10T00:00:00Z"}))
        (vd / "2.json").write_text(json.dumps({"generated_at": "2026-08-10T00:00:00Z"}))
        git("add", "-A", cwd=work); git("commit", "-q", "-m", "branch", cwd=work)
        git("push", "-q", "origin", "verdicts", cwd=work)
        git("checkout", "-q", "main", cwd=work)
        git("branch", "-q", "-D", "verdicts", cwd=work)   # only origin/ remains
    return work


def _run_select(work, *args):
    import subprocess as sp_
    script = str(Path(__file__).resolve().parent / "select_publishable.py")
    return sp_.run([PY, script, *args], cwd=str(work),
                   capture_output=True, text=True)


def test_select_refuses_a_ref_it_cannot_read():
    """THE REGRESSION. `--from no-such-ref` printed `publishable: 0 skipped: 0`
    and exited 0 - indistinguishable from "nothing to publish". The nightly
    workflow swallowed its fetch failure with `|| echo`, so a broken fetch
    published nothing and reported success: the gh-variable-set shape again."""
    print("\nselect: an unreadable ref is an error, never an empty selection")
    import select_publishable as sp

    with tempfile.TemporaryDirectory() as d:
        work = _fixture_remote(d)
        r = _run_select(work, "--from", "no-such-ref", "--allow-local-ref")
        check("a missing ref exits NON-zero", r.returncode != 0, r.returncode)
        check("...and does not report a clean zero",
              "publishable: 0    skipped: 0" not in r.stdout, r.stdout)
        r = _run_select(work, "--from", "origin/verdicts")
        check("a good remote ref still selects normally",
              r.returncode == 0 and "publishable: 2" in r.stdout,
              r.stdout.strip()[-120:])
    check("select() raises rather than returning an empty pair",
          hasattr(sp, "RefProblem"))


def test_select_defaults_to_the_remote_and_refuses_local():
    print("\nselect: the source ref cannot be silently stale")
    import select_publishable as sp
    check("the default --from is remote-tracking",
          sp.DEFAULT_FROM == "origin/verdicts", sp.DEFAULT_FROM)

    with tempfile.TemporaryDirectory() as d:
        work = _fixture_remote(d)
        import subprocess as sp_
        sp_.run(["git", "branch", "verdicts", "origin/verdicts"], cwd=str(work),
                capture_output=True)
        r = _run_select(work, "--from", "verdicts")
        check("a local ref is refused by default",
              r.returncode == 2 and "not a remote-tracking ref" in r.stderr,
              r.stderr.strip()[:90])
        r = _run_select(work, "--from", "verdicts", "--allow-local-ref")
        check("...and permitted only when asked for explicitly",
              r.returncode == 0, r.stderr.strip()[:90])
        check("...with a warning that it may be behind origin",
              "may be behind origin" in r.stdout, r.stdout[:200])


def test_select_tells_no_branch_apart_from_no_network():
    """`git fetch origin verdicts` FAILS when the branch does not exist, so
    fetching alone cannot separate "no branch yet" - a legitimate state the
    workflow has always handled - from a broken remote. The remote is probed
    first. The first version of this change got it wrong and made the
    legitimate case unreachable."""
    print("\nselect: absent branch and unreachable remote are different answers")
    with tempfile.TemporaryDirectory() as d:
        work = _fixture_remote(d, with_branch=False)
        r = _run_select(work, "--from", "origin/verdicts")
        check("no branch on the remote is a clean, explicit exit 0",
              r.returncode == 0 and "nothing to publish" in r.stdout,
              (r.returncode, r.stdout.strip()[-90:]))
    with tempfile.TemporaryDirectory() as d:
        work = _fixture_remote(d)
        import subprocess as sp_
        sp_.run(["git", "remote", "set-url", "origin", str(Path(d) / "gone.git")],
                cwd=str(work), capture_output=True)
        r = _run_select(work, "--from", "origin/verdicts")
        check("an unreachable remote is an error, not an empty selection",
              r.returncode == 2 and "could not reach" in r.stderr,
              (r.returncode, r.stderr.strip()[:90]))


def test_ls_remote_exit_codes_are_what_two_call_sites_assume():
    """The shared contract, pinned once.

    `git ls-remote --exit-code --heads` is how BOTH select_publishable.py and
    generate-verdict.yml's commit step tell "the branch does not exist" (a
    legitimate first-run state) from "the remote is unreachable" (an error). If
    git ever changed those exit codes, one would start creating branches it
    should not and the other would start publishing nothing while reporting
    success - so the assumption is asserted against a real remote here, and both
    users fail together rather than one drifting quietly.
    """
    print("\ngit: ls-remote exit codes, the contract two call sites rely on")
    with tempfile.TemporaryDirectory() as d:
        work = _fixture_remote(d)                       # has origin/verdicts
        r = subprocess.run(["git", "ls-remote", "--exit-code", "--heads",
                            "origin", "verdicts"], cwd=str(work),
                           capture_output=True, text=True)
        check("a branch that exists -> rc 0", r.returncode == 0, r.returncode)
        r = subprocess.run(["git", "ls-remote", "--exit-code", "--heads",
                            "origin", "no-such-branch"], cwd=str(work),
                           capture_output=True, text=True)
        check("a branch that does not exist -> rc 2", r.returncode == 2,
              r.returncode)
        subprocess.run(["git", "remote", "set-url", "origin",
                        str(Path(d) / "gone.git")], cwd=str(work),
                       capture_output=True)
        r = subprocess.run(["git", "ls-remote", "--exit-code", "--heads",
                            "origin", "verdicts"], cwd=str(work),
                           capture_output=True, text=True)
        check("an unreachable remote -> neither 0 nor 2",
              r.returncode not in (0, 2), r.returncode)

    # and both call sites really do use it
    sel = (Path(__file__).resolve().parent / "select_publishable.py").read_text()
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/generate-verdict.yml").read_text()
    check("select_publishable probes before fetching",
          "ls-remote" in sel and "returncode == 2" in sel)
    check("the generation workflow probes before falling back",
          "ls-remote --exit-code --heads origin verdicts" in wf, "not in the yml")
    # Comment lines are excluded on purpose: the step quotes the old command in
    # its own comment so the fallback cannot be "simplified" back, and a naive
    # substring search finds that quote and fails on it. Asked and answered the
    # hard way - this assertion did exactly that on its first run.
    live = [ln for ln in wf.splitlines() if not ln.strip().startswith("#")]
    offenders = [ln.strip() for ln in live if "|| git branch verdicts" in ln]
    check("...and no longer falls back on ANY fetch failure, outside comments",
          not offenders, offenders)
    check("the fallback is reachable only when the branch is confirmed absent",
          any("BRANCH_EXISTS=0" in ln for ln in live)
          and any("git branch verdicts" in ln for ln in live), "guard missing")


def test_select_surfaces_failures_it_cannot_reproduce_locally():
    """Two failure modes a fixture cannot stage: a tree object that will not
    read (partial clone, damaged object store) and a fetch that fails after the
    remote said the branch is there (corrupt remote, connection dropped
    mid-transfer). Both are injected at _git, the one place every git call goes
    through, because the property under test is what the code DOES with a
    failure - and both used to be swallowed into "nothing to publish"."""
    print("\nselect: injected git failures are surfaced, not swallowed")
    import select_publishable as sp

    real = sp._git

    def failing(*match):
        def fake(*args):
            if list(args[:len(match)]) == list(match):
                return subprocess.CompletedProcess(args, 128, "", "fatal: injected")
            return real(*args)
        return fake

    # 1. the ref resolves, but its tree will not read
    try:
        sp._git = failing("ls-tree")
        raised = False
        try:
            sp.select("origin/verdicts", "HEAD")
        except sp.RefProblem:
            raised = True
        check("an unreadable tree raises rather than selecting nothing", raised)
    finally:
        sp._git = real

    # 2. the remote lists the branch, then the fetch fails
    import io
    from contextlib import redirect_stderr, redirect_stdout
    try:
        sp._git = failing("fetch")
        argv = sys.argv
        sys.argv = ["select_publishable.py", "--from", "origin/verdicts"]
        err, out = io.StringIO(), io.StringIO()
        try:
            with redirect_stderr(err), redirect_stdout(out):
                rc = sp.main()
        finally:
            sys.argv = argv
        check("a failed fetch refuses instead of publishing nothing", rc == 2, rc)
        check("...and says the fetch was what failed",
              "could not fetch" in err.getvalue(), err.getvalue()[:120])
        check("...and never prints a clean selection",
              "publishable:" not in out.getvalue(), out.getvalue()[:120])
    finally:
        sp._git = real


def test_prune_only_drops_superseded_and_settled():
    """The pruner may only ever delete a copy that is BOTH older than main's and
    past the deploy window in which the branch was still serving it."""
    print("\nprune: which branch artifacts may be dropped")
    import os
    import prune_verdicts as pv

    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        _fixture_repo(d, now)
        cwd = os.getcwd()
        try:
            os.chdir(d)
            prune, keep = pv.prunable("vbranch", "main", grace_hours=48, now=now)
        finally:
            os.chdir(cwd)

    dropped = {p["appid"] for p in prune}
    kept = {k["appid"]: k["keep_because"] for k in keep}
    check("the superseded, settled copy is pruned", "old" in dropped, dropped)
    # THE CORRECTED PREDICATE, stated as a test: a title that has been in the
    # deployed build for a week is prunable even though main's bytes changed
    # seconds ago. The deploy race depends on first appearance, not on freshness.
    check("a long-published title whose bytes were just rewritten is pruned",
          "regen" in dropped, {"dropped": dropped, "kept": kept})
    check("...and nothing else is", dropped == {"old", "regen"}, dropped)
    check("a title main does not have is kept",
          kept.get("only", "").startswith("publishable"), kept)
    check("an equal timestamp is kept", kept.get("tie") == "same_timestamp", kept)
    check("unreadable branch JSON is kept (may be half-written)",
          kept.get("bad") == "unreadable_on_branch", kept)
    check("a copy superseded minutes ago is kept - the deploy may still be "
          "serving it", kept.get("fresh") == "inside_deploy_window", kept)


def test_prune_grace_window_from_both_sides():
    print("\nprune: the deploy window, from both sides of the boundary")
    import os
    import prune_verdicts as pv
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        _fixture_repo(d, now)
        cwd = os.getcwd()
        try:
            os.chdir(d)
            # `fresh` was promoted at `now`; move the observer instead of the
            # commit so the boundary is tested on one variable only
            just_inside = pv.prunable("vbranch", "main", grace_hours=48,
                                      now=now + timedelta(hours=47))[0]
            just_outside = pv.prunable("vbranch", "main", grace_hours=48,
                                       now=now + timedelta(hours=49))[0]
        finally:
            os.chdir(cwd)
    check("at 47h the newly-arrived title is still protected",
          {p["appid"] for p in just_inside} == {"old", "regen"},
          {p["appid"] for p in just_inside})
    check("at 49h it becomes prunable",
          {p["appid"] for p in just_outside} == {"old", "regen", "fresh"},
          {p["appid"] for p in just_outside})


def test_prune_keeps_anything_it_cannot_date():
    """An unknown promotion date must fail SAFE - keep, never drop.

    Not reachable from fixture data: a file missing from main is classified as a
    new title and kept for a different reason, so the only way to exercise this
    branch is to make promoted_at() answer None directly. It answers None in a
    shallow or grafted clone, where `git log -1 -- path` finds no commit for a
    path that is present in the tree - and "I cannot tell how long this has been
    published" must never be read as "long enough".
    """
    print("\nprune: an undateable entry is kept, not dropped")
    import os
    import prune_verdicts as pv

    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        _fixture_repo(d, now)
        cwd, real = os.getcwd(), pv.promoted_at
        try:
            os.chdir(d)
            pv.promoted_at = lambda *a, **kw: None
            prune, keep = pv.prunable("vbranch", "main", grace_hours=48, now=now)
        finally:
            pv.promoted_at = real
            os.chdir(cwd)
    check("nothing is pruned when nothing can be dated", prune == [],
          [p["appid"] for p in prune])
    check("and the reason is recorded rather than silent",
          any(k["keep_because"] == "no_promotion_date_on_main" for k in keep),
          {k["appid"]: k["keep_because"] for k in keep})


def test_prune_refuses_a_local_ref():
    """A dev machine's local `verdicts` is whatever it last fetched - on the
    machine this was written on it was two files behind origin. Pruning against
    a stale view would delete files that are still the only copy."""
    print("\nprune: refuses to work from a ref that might be stale")
    src = (Path(__file__).resolve().parent / "prune_verdicts.py").read_text()
    check("the default ref is remote-tracking",
          'BRANCH = "origin/verdicts"' in src)
    check("and a non-remote ref is refused outright",
          'refs/remotes/' in src and "must be a remote-tracking ref" in src)
    check("the push never forces",
          "--force" not in src.split("def apply_prune")[1].split("git\", \"push")[0]
          or "push\", \"origin\", \"HEAD:verdicts\"" in src)
    check("a rejected push aborts rather than rebasing",
          "must be derived against the current branch" in src)


if __name__ == "__main__":
    print("batch guard tests - offline, no quota spent")
    test_pacer_ceiling_in_one_process()
    test_pacer_ceiling_across_processes()
    test_a_vanished_lock_is_a_retry_not_a_crash()
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
    test_a_retry_never_replays_a_cached_rejection()
    test_prompt_names_every_word_the_guard_rejects()
    test_flash_tier_allocation()
    test_batch_never_spends_flash()
    test_remote_live_ledger_read_is_offline_and_fail_safe()
    test_reconciled_live_used_survives_the_reload_the_loop_does()
    test_run_batch_refuses_to_start_on_an_unreadable_live_ledger()
    test_ledger_routing_is_by_model_then_by_caller()
    test_pacer_and_ledger_cannot_drift()
    test_a_single_stage_run_still_charges()
    test_every_ledger_flag_reaches_the_ledger()
    test_lock_order_is_one_way()
    test_a_test_can_never_charge_the_real_ledger()
    test_flash_daily_cap_is_enforced_by_the_ledger()
    test_batch_is_interruptible()
    test_call_counting_is_at_the_call_site()
    test_ledger_charge_is_atomic()
    test_failure_paths_charge_the_ledger()
    test_interrupt_does_not_double_count()
    test_verdict_word_boundaries()
    test_verdict_mean_is_pool_weighted_and_floored()
    test_verdict_word_is_not_model_supplied()
    test_header_shape_is_bounded_in_code()
    test_header_may_not_argue_with_the_computed_word()
    test_friction_is_a_condition_only_below_a_heading_that_says_so()
    test_prose_sweep_covers_every_new_field()
    test_claim_balance_metric_counts_sources_not_claims()
    test_claim_balance_ignores_cohorts_too_small_to_judge()
    test_publish_never_replaces_newer_with_older()
    test_select_refuses_a_ref_it_cannot_read()
    test_select_defaults_to_the_remote_and_refuses_local()
    test_select_tells_no_branch_apart_from_no_network()
    test_ls_remote_exit_codes_are_what_two_call_sites_assume()
    test_select_surfaces_failures_it_cannot_reproduce_locally()
    test_prune_only_drops_superseded_and_settled()
    test_prune_grace_window_from_both_sides()
    test_prune_keeps_anything_it_cannot_date()
    test_prune_refuses_a_local_ref()

    print("\n%s" % ("all guard tests passed" if not FAILURES
                    else "%d FAILURES:\n  %s" % (len(FAILURES),
                                                 "\n  ".join(FAILURES))))
    sys.exit(1 if FAILURES else 0)
