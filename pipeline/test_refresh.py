"""
Offline tests for the catalog refresh (run_batch.py --refresh, 2026-11-16).

A refresh regenerates titles that are ALREADY LIVE. So the property that matters
most is the one a normal batch never needed: whatever goes wrong, the page readers
have stays up. Pinned here:

  1. selection     - only verdicts without the meaning-check marker, seeds skipped,
                     terminal refresh failures not retried, oldest first
  2. live page     - replaced only by a candidate that passed QR-4; left untouched
                     on a QR-4 failure, a stage failure, or a stale candidate
  3. fresh reviews - every stage runs in the work dir, never ROOT, so the stored
                     July reviews are never read
  4. budget stop   - a refresh run stops before any title when the budget is spent,
                     and a title starts only if it and every running title fit
  5. the marker    - synthesis writes claims_verified from the claims file

No network, no Gemini, no quota: run_stage, the gate and the ledger are stubs, and
every file it writes is in a temp dir.

Run:  .venv/bin/python pipeline/test_refresh.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_one  # noqa: E402
import live_quota  # noqa: E402
import model_pacer  # noqa: E402
import qr4_gate  # noqa: E402
import run_batch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAILURES = []


def check(name, cond, detail=""):
    print("  %-66s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        FAILURES.append("%s %s" % (name, detail))


@contextlib.contextmanager
def patched(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def verdict(appid, at, verified=None):
    v = {"appid": appid, "game_name": "G%d" % appid, "generated_at": at}
    if verified is not None:
        v["claims_verified"] = verified
    return v


def test_selection():
    print("\nselection: which published titles a refresh picks")
    with tempfile.TemporaryDirectory() as d:
        vd = Path(d)
        for v in (verdict(10, "2026-08-03"), verdict(11, "2026-08-01"),
                  verdict(12, "2026-08-02", verified=True), verdict(233860, "2026-07-01"),
                  verdict(13, "2026-07-15"), verdict(14, "2026-07-20", verified=False),
                  verdict(15, "2026-08-05")):
            (vd / ("%d.json" % v["appid"])).write_text(json.dumps(v))
        (vd / "broken.json").write_text("{")
        state = {"titles": {"13": {"refresh": True, "outcome": "qr4_failed"},
                            "14": {"refresh": True, "outcome": "stage_failed"},
                            "15": {"refresh": True, "outcome": "thin_segmentation"}}}
        ids = [r["appid"] for r in run_batch.refresh_pending(state, 0, verdicts=vd)]
        check("a verified verdict is not refreshed", 12 not in ids, ids)
        check("a seed game is skipped by default", 233860 not in ids, ids)
        check("a refresh that failed the gate is not retried nightly", 13 not in ids, ids)
        check("a refresh that hit a stage failure is retried", 14 in ids, ids)
        check("a refresh the segmentation gate dropped is retried (the gate is skipped now)",
              15 in ids, ids)
        check("oldest generated_at first", ids == [14, 11, 10, 15], ids)
        check("--limit caps it",
              [r["appid"] for r in run_batch.refresh_pending(state, 2, verdicts=vd)] == [14, 11])
        check("--include-seeds brings the seed back",
              233860 in [r["appid"] for r in run_batch.refresh_pending(
                  state, 0, include_seeds=True, verdicts=vd)])
        check("--appids restricts it",
              [r["appid"] for r in run_batch.refresh_pending(
                  state, 0, only={10}, verdicts=vd)] == [10])


def content(p):
    """A verdict file's JSON, or None if it is gone - a test must report a
    deleted live page as a failure, not crash on it."""
    return json.loads(p.read_text()) if p.exists() else None


def _generate(tmp, gate_passes=True, fail_stage=None, write_candidate=True,
              stale_candidate=False, thin_ingest=False):
    """Drive the REAL generate() in refresh mode with every outside call stubbed."""
    live_dir = tmp / "live"
    live_dir.mkdir(exist_ok=True)
    live = live_dir / "77.json"
    live.write_text('{"old": true}')
    wd = tmp / "work"
    cand_dir = wd / "site/public/verdicts"
    if stale_candidate:
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "77.json").write_text('{"stale": true}')
    seen = []

    def fake_run_stage(script, appid, timeout=900, extra=(), ledger=None, cwd=None):
        seen.append({"script": script[0], "cwd": cwd, "extra": list(extra)})
        rc = 1 if fail_stage and fail_stage in script[0] else 0
        # never fall back to ROOT: with no work dir this stub writes nothing, and
        # the cwd check below reports it
        if "fetch_reviews" in script[0] and thin_ingest and cwd is not None:
            # a fresh ingest with one usable cohort, written where a real fetch
            # in the work dir would write it
            raw = Path(cwd) / "data/raw"
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "77.json").write_text(json.dumps({"pool": {"pool_n": 100, "buckets": {
                "early": {"pool_n": 100}}}}))
        if "synthesize" in script[0] and write_candidate and not rc:
            out = Path(list(extra)[list(extra).index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "77.json").write_text('{"new": true}')
        return 0.0, SimpleNamespace(returncode=rc, stdout="", stderr="")

    with patched(generate_one, run_stage=fake_run_stage, VERDICTS=live_dir), \
         patched(live_quota, load=lambda *a, **k: {},
                 can_batch=lambda *a, **k: (True, "ok", {}),
                 note_generation=lambda *a, **k: None), \
         patched(model_pacer, calls_for=lambda *a, **k: 0), \
         patched(qr4_gate, gate=lambda v, n=None: (gate_passes, {})):
        published, result = generate_one.generate(77, quiet=True, ledger="batch",
                                                  workdir=wd,
                                                  segmentation_gate=thin_ingest)
    return published, result, live, cand_dir / "77.json", seen, wd


def test_live_page_survives_every_failure():
    print("\nlive page: replaced only by a candidate that passed QR-4")
    with tempfile.TemporaryDirectory() as d:
        pub, res, live, cand, seen, wd = _generate(Path(d))
        check("a gated candidate replaces the live page",
              pub and content(live) == {"new": True}, content(live))
        check("  and no temp file is left beside it",
              not list(live.parent.glob("*.refresh-tmp")))
    with tempfile.TemporaryDirectory() as d:
        pub, res, live, cand, seen, wd = _generate(Path(d), gate_passes=False)
        check("a QR-4 failure leaves the live page untouched",
              not pub and content(live) == {"old": True}, content(live))
        check("  and removes the candidate, not the page", not cand.exists() and live.exists())
        check("  and reports qr4_failed", res["outcome"] == "qr4_failed", res)
    with tempfile.TemporaryDirectory() as d:
        pub, res, live, cand, seen, wd = _generate(Path(d), fail_stage="extract_claims")
        check("a stage failure leaves the live page untouched",
              not pub and content(live) == {"old": True})
        check("  and reports stage_failed", res["outcome"] == "stage_failed", res)
    with tempfile.TemporaryDirectory() as d:
        pub, res, live, cand, seen, wd = _generate(Path(d), write_candidate=False,
                                                   stale_candidate=True)
        check("a stale candidate from an earlier attempt is never published",
              not pub and content(live) == {"old": True}, res)
    with tempfile.TemporaryDirectory() as d:
        pub, res, live, cand, seen, wd = _generate(Path(d), thin_ingest=True)
        check("the segmentation gate judges the work dir's fresh ingest",
              res["outcome"] == "thin_segmentation", res)
        check("  and a thin fresh pool leaves the live page untouched",
              not pub and content(live) == {"old": True})


def test_stages_run_in_the_work_dir():
    print("\nfresh reviews: every stage runs in the work dir, not ROOT")
    with tempfile.TemporaryDirectory() as d:
        pub, res, live, cand, seen, wd = _generate(Path(d))
        check("all four stages ran", len(seen) == 4, seen)
        check("every stage's cwd is the work dir", all(s["cwd"] == wd for s in seen), seen)
        syn = [s for s in seen if "synthesize" in s["script"]]
        check("synthesis writes its candidate into the work dir",
              bool(syn) and "--out" in syn[0]["extra"]
              and syn[0]["extra"][syn[0]["extra"].index("--out") + 1]
              == str(wd / "site/public/verdicts"), syn)

    # run_stage itself: the real subprocess call, captured
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    saved_key = os.environ.pop("GEMINI_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as d:
            env_file = Path(d) / ".env"
            env_file.write_text('GEMINI_API_KEY="stub-key-for-test"\n')
            with patched(generate_one, DOTENV=env_file), \
                 patched(generate_one.subprocess, run=fake_run):
                generate_one.run_stage(["pipeline/fetch_reviews.py"], 77, cwd=Path(d))
                generate_one.run_stage(["pipeline/fetch_reviews.py"], 77)
        (argv_w, kw_w), (argv_r, kw_r) = calls
        check("a work-dir stage runs with cwd = the work dir", kw_w["cwd"] == d, kw_w["cwd"])
        check("  with the script by absolute path",
              argv_w[1] == str(ROOT / "pipeline/fetch_reviews.py"), argv_w)
        check("  and the key from the repo .env in its environment",
              kw_w["env"].get("GEMINI_API_KEY") == "stub-key-for-test")
        check("a normal stage still runs in ROOT", kw_r["cwd"] == str(ROOT), kw_r["cwd"])
        check("  and gets no .env merged in", "GEMINI_API_KEY" not in kw_r["env"])
    finally:
        if saved_key is not None:
            os.environ["GEMINI_API_KEY"] = saved_key

    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "data/raw"
        raw.mkdir(parents=True)
        (raw / "77.json").write_text(json.dumps({"pool": {"pool_n": 321, "buckets": {
            "veteran": {"pool_n": 21}, "early": {"pool_n": 300}}}}))
        s = generate_one.cohort_structure(77, root=Path(d))
        check("the segmentation gate reads the fresh ingest in the work dir",
              s is not None and s["pool_n"] == 321, s)


def test_run_title_records_only_what_ran():
    print("\nrun_title: a refusal is never recorded, and a refresh skips the segmentation gate")
    calls = []

    def fake_generate(appid, **kw):
        calls.append(kw)
        return fake_generate.result

    args = SimpleNamespace(reserve=100, no_gate=False, refresh=True)
    with tempfile.TemporaryDirectory() as d:
        state_path = Path(d) / "state.json"
        state = {"runs": [], "titles": {"77": {"outcome": "ok", "model_calls": 9,
                                               "at": "2026-08-12T00:00:00Z"}}}
        with patched(run_batch, STATE=state_path, REFRESH_DIR=Path(d) / "refresh"), \
             patched(generate_one, generate=fake_generate), \
             patched(live_quota, load=lambda *a, **k: {}), \
             patched(model_pacer, calls_for=lambda *a, **k: 0):
            fake_generate.result = (False, {"published": False,
                                            "outcome": "batch_budget_exhausted",
                                            "refused": True, "model_calls": 0})
            entry = run_batch.run_title({"appid": 77, "title": "G"}, state, args)
            check("a refusal leaves the title's history untouched",
                  state["titles"]["77"] == {"outcome": "ok", "model_calls": 9,
                                            "at": "2026-08-12T00:00:00Z"}, state["titles"])
            check("  and writes nothing to the state file", not state_path.exists())
            check("  and is counted as refused", entry.get("refused") is True, entry)
            check("a refresh calls generate() with the segmentation gate off",
                  calls[-1].get("segmentation_gate") is False, calls[-1])

            fake_generate.result = (True, {"published": True, "outcome": "ok",
                                           "model_calls": 12})
            run_batch.run_title({"appid": 77, "title": "G"}, state, args)
            check("a title that ran is recorded",
                  state["titles"]["77"]["model_calls"] == 12, state["titles"]["77"])

            run_batch.run_title({"appid": 78, "title": "N"}, state,
                                SimpleNamespace(reserve=100, no_gate=False, refresh=False))
            check("a normal batch title keeps the segmentation gate on",
                  calls[-1].get("segmentation_gate") is True, calls[-1])

    # the flag run_title relies on comes from generate() itself
    with patched(live_quota, load=lambda *a, **k: {},
                 can_batch=lambda *a, **k: (False, "batch_budget_exhausted", {})), \
         patched(model_pacer, calls_for=lambda *a, **k: 0):
        pub, res = generate_one.generate(77, quiet=True, ledger="batch")
    check("generate() marks a budget refusal as refused, at 0 calls",
          not pub and res.get("refused") is True and res.get("model_calls") == 0, res)


def test_inflight_reservation():
    print("\nreservation: a title starts only if it and every running title still fit")
    fits, R = run_batch.fits, run_batch.TITLE_RESERVE
    check("the reservation is the measured maximum, 18", R == 18, R)
    check("one title alone fits on exactly 18 left", fits(18, []))
    check("one title alone does not fit on 17 left", not fits(17, []))
    # night 4's last start: 16 left on the ledger, the other worker 3 calls in
    check("night 4: 16 left with a title 3 calls in refuses the next title",
          not fits(16, [3]))
    check("two fresh titles need 36 left, not 35", fits(36, [0]) and not fits(35, [0]))
    check("30 left with a title 3 calls in refuses the next (15 still owed)",
          not fits(30, [3]))
    check("a running title past 18 owes nothing more", fits(18, [25]))

    # replay night 4's real costs at concurrency 2, one call per step per worker
    # (data/batch_state.json, the 32 refresh records dated 2026-11-21; sum 404)
    costs = [11, 12, 13, 18, 14, 14, 12, 7, 15, 12, 11, 8, 15, 14, 10, 11,
             11, 17, 16, 16, 13, 14, 11, 16, 11, 8, 9, 10, 14, 13, 13, 15]
    check("the replayed costs are night 4's 404 calls", sum(costs) == 404, sum(costs))
    for cap in (400, 37, 36, 35, 18, 17):
        queue, used, running = list(costs), 0, []   # running: [cost, spent]
        while queue or running:
            while queue and len(running) < 2 and fits(cap - used, [s for _, s in running]):
                running.append([queue.pop(0), 0])
            if not running:
                break
            for r in running:
                r[1] += 1
                used += 1
            running = [r for r in running if r[1] < r[0]]
        check("night 4's costs never spend past a budget of %d" % cap, used <= cap,
              "used %d" % used)

    led = {"n": 0}
    with patched(live_quota, load=lambda *a, **k: {},
                 batch_remaining=lambda *a, **k: led["left"]), \
         patched(model_pacer, calls_for=lambda a, *x, **k: led.get(a, 0)):
        run_batch._inflight.clear()
        led.update(left=30, A=10)       # A already spent 10 earlier today
        check("first title admitted on 30", run_batch.admit("A", 100) is None)
        check("A's earlier calls today are not counted as progress (B refused on 30)",
              run_batch.admit("B", 100) is not None)
        led.update(left=36)
        check("B admitted on 36", run_batch.admit("B", 100) is None)
        check("a third is refused while both run", run_batch.admit("C", 100) is not None)
        run_batch.release("A")
        check("releasing a title frees its slot", run_batch.admit("C", 100) is None)
        run_batch._inflight.clear()

        args = SimpleNamespace(reserve=100, no_gate=False, refresh=False)
        led.update(left=17)
        ran = []
        # STATE redirected: under a mutation that skips admission, the stub title
        # reaches record(). Once it did, and overwrote the real batch state.
        tmp = Path(tempfile.mkdtemp())
        with patched(generate_one, generate=lambda *a, **k: ran.append(a) or (True, {})), \
             patched(run_batch, STATE=tmp / "state.json"):
            entry = run_batch.run_title({"appid": 9, "title": "T"}, {"titles": {}}, args)
        check("a title that does not fit never reaches generate()",
              not ran and entry.get("refused") is True and entry.get("model_calls") == 0, entry)

        led.update(left=400)

        def boom(*a, **k):
            raise RuntimeError("stage blew up")
        with patched(generate_one, generate=boom), \
             patched(run_batch, STATE=tmp / "state.json"):
            try:
                run_batch.run_title({"appid": 9, "title": "T"}, {"titles": {}}, args)
            except RuntimeError:
                pass
        check("a title that raises still releases its reservation",
              9 not in run_batch._inflight, dict(run_batch._inflight))
        run_batch._inflight.clear()


def test_budget_stop_holds_for_a_refresh():
    print("\nbudget: a refresh run stops before any title when the budget is spent")
    for allowed, want in ((False, 0), (True, 1)):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "catalog.json").write_text(json.dumps({"generated_at": "x", "titles": []}))
            vd = tmp / "verdicts"
            vd.mkdir()
            (vd / "77.json").write_text(json.dumps(verdict(77, "2026-08-01")))
            ran, out = [], io.StringIO()
            argv = sys.argv
            sys.argv = ["run_batch.py", "--refresh", "--concurrency", "1"]
            try:
                with patched(run_batch, CATALOG=tmp / "catalog.json",
                             STATE=tmp / "state.json", VERDICTS=vd,
                             run_title=lambda row, st, a: ran.append(row) or {
                                 "published": True, "outcome": "ok", "model_calls": 0}), \
                     patched(live_quota, load=lambda *a, **k: {},
                             fetch_remote_live_used=lambda *a, **k: (0, {}),
                             sync_live_used=lambda *a, **k: {},
                             can_batch=lambda *a, **k: (allowed, "batch_budget_exhausted", {})), \
                     patched(model_pacer, status=lambda *a, **k: {}), \
                     contextlib.redirect_stdout(out):
                    try:
                        run_batch.main()
                    except SystemExit:
                        pass
            finally:
                sys.argv = argv
            if allowed:
                check("control: with budget, the refresh title runs",
                      [r["appid"] for r in ran] == [77], ran)
            else:
                check("with no budget, no title runs", ran == [], ran)
                check("  and it says BUDGET STOP", "BUDGET STOP" in out.getvalue(),
                      out.getvalue()[-300:])


def test_synthesis_writes_the_marker():
    print("\nmarker: synthesis records whether the claims were meaning-checked")
    import flags as flags_mod
    import synthesize
    appid = "233860"
    claims_blob, corpus, pool, cohorts = synthesize.load_inputs(
        appid, str(ROOT / "data/claims"), str(ROOT / "data/filtered"))
    word = synthesize.verdict_for_mean(synthesize.post_refund_mean(cohorts))
    parsed = {"tagline": "x", "for_you_if": ["a"], "not_for_you_if": ["b"]}
    with patched(model_pacer, calls_for=lambda *a, **k: 9):
        for flag in (True, False):
            v = synthesize.assemble(appid, {**claims_blob, "verified": flag}, corpus, pool,
                                    cohorts, flags_mod.detect(pool), parsed,
                                    "gemini-3.5-flash-lite", word)
            check("claims_verified is %s when the claims file says %s" % (flag, flag),
                  v.get("claims_verified") is flag, v.get("claims_verified"))


if __name__ == "__main__":
    test_selection()
    test_live_page_survives_every_failure()
    test_stages_run_in_the_work_dir()
    test_run_title_records_only_what_ran()
    test_inflight_reservation()
    test_budget_stop_holds_for_a_refresh()
    test_synthesis_writes_the_marker()
    if FAILURES:
        print("\n%d FAILURES:" % len(FAILURES))
        for f in FAILURES:
            print("  %s" % f)
        sys.exit(1)
    print("\nall refresh tests passed")
