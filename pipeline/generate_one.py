"""
WorthIt.gg - live generation of one verdict, end to end

The entry point behind a search-box cache miss, and the harness that MEASURES
what it costs. Both, deliberately: CLAUDE.md guard 3 says the wait copy is set
from real observed runs, so the thing that states the number and the thing that
does the work must be the same code path. If generation gets slower, --report
prints a different number and the copy changes.

Stage boundaries are the ones the UI shows, because a legible wait is guard 3:

    ingest    fetch_reviews    Steam only, no model calls
    filter    filter_reviews   content filter, no model calls
    extract   extract_claims   1 Gemini call per qualifying cohort (+ retries)
    verdict   synthesize       1 Gemini call, writes site/public/verdicts/<appid>.json
    qr4       qr4_gate         invariant 8, in-pipeline, before anything renders

ORDER IS THE POINT. The QR-4 gate runs AFTER synthesis and BEFORE the verdict is
allowed to be served. On failure the artifact is REMOVED, not served-with-a-
warning: the title falls back to the request queue for manual audit and the user
sees queue copy. A verdict is publishable as generated or not at all.

Usage:
    .venv/bin/python pipeline/generate_one.py 379720 --report
    .venv/bin/python pipeline/generate_one.py 379720 --ip 1.2.3.4
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_quota   # noqa: E402
import model_pacer  # noqa: E402
import qr4_gate     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Stages run under THE INTERPRETER ALREADY RUNNING THIS FILE, not a hardcoded
# path. This was `ROOT / ".venv/bin/python"`, which is correct on a laptop and
# does not exist anywhere else: .venv is gitignored, and the CI runner pip
# installs into system Python. The moment the workflow started routing stages
# through this module (so one place decides which model a path may use), every
# stage became a subprocess call to a missing binary and ingest died with
# FileNotFoundError in under a second - before touching Steam, before any model.
#
# sys.executable is right in both places by construction: locally it resolves to
# .venv/bin/python because that is what invoked us, and on the runner it
# resolves to the python that has requirements.txt installed.
PY = sys.executable
VERDICTS = ROOT / "site/public/verdicts"

STAGES = [
    ("ingest", "Reading Steam reviews", ["pipeline/fetch_reviews.py"]),
    ("filter", "Filtering out junk and unsafe reviews", ["pipeline/filter_reviews.py"]),
    ("extract", "Reading each playtime cohort", ["pipeline/extract_claims.py"]),
    ("verdict", "Writing the verdict", ["pipeline/synthesize.py"]),
]


def run_stage(script_args, appid, timeout=900, extra=(), ledger=None):
    """Run one stage as a subprocess, tagged with the title it is charging.

    WORTHIT_APPID is how the pacer attributes each request to a title, and
    WORTHIT_LEDGER is how it attributes the request to a daily claim. Both have
    to cross the process boundary because the stages are subprocesses, and both
    are set here rather than inside each script so no stage can forget - which
    is exactly what every stage but qr4 used to do.
    """
    import os
    env = dict(os.environ, WORTHIT_APPID=str(appid),
               WORTHIT_LEDGER=str(ledger or "batch"))
    t0 = time.time()
    proc = subprocess.run([PY] + script_args + [str(appid)] + list(extra),
                          cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=timeout)
    return time.time() - t0, proc


def count_model_calls(out):
    """DEPRECATED - kept only so an old caller cannot silently get zero.

    Counting by scraping stdout is what produced the undercount: a call that
    429s, times out or raises never prints "RAW MODEL OUTPUT", so every failed
    call was invisible. The ledger read 21 where 37 requests had been spent, and
    every budget projection rode on that number. Counting now happens at the
    call site - see model_pacer.calls_for().
    """
    raise NotImplementedError(
        "use model_pacer.calls_for(appid); stdout scraping misses failed calls")


def flash_tier_ids():
    """appids scheduled for a flash day, for callers that need to hold them back."""
    import synthesize
    return set(synthesize.flash_tier())


def cohort_structure(appid):
    """Veteran pool share and refund cohort size, read from the ingest output.

    Available for FREE after the ingest stage - ingestion talks only to Steam.
    That is what makes the thin-segmentation gate cheap: it sits between the
    free stage and the first stage that spends Gemini quota.
    """
    path = ROOT / "data/raw" / ("%s.json" % appid)
    if not path.exists():
        return None
    pool = json.loads(path.read_text(encoding="utf-8")).get("pool") or {}
    buckets, total = pool.get("buckets") or {}, pool.get("pool_n") or 0
    if not buckets or not total:
        return None
    return {
        "pool_n": total,
        "veteran_share": round(
            (buckets.get("veteran", {}).get("pool_n", 0)) / total, 3),
        "refund_n": buckets.get("refund_window", {}).get("pool_n", 0),
        "eligible_cohorts": sum(
            1 for b in buckets.values() if b.get("pool_n", 0) >= 20),
    }


def thin_segmentation(struct, max_veteran_share=0.60, min_cohorts=2):
    """(is_thin, reason). Applied AFTER ingest, BEFORE any model call.

    Deliberately conservative, calibrated against the seed set rather than
    guessed: Helldivers 2 sits at 45.1% veteran and produced the best verdict
    shape in the eval set, so a threshold anywhere near it would reject good
    titles. 0.60 rejects only the degenerate cases (Dota 2 measured 77.0%),
    where one cohort is so dominant that "different cohorts describe different
    products" has nothing left to compare.

    The cohort-count check is the harder floor: fewer than two cohorts clearing
    invariant 12's 20-review minimum means there is no split to show at all.
    """
    if struct is None:
        return False, None
    if struct["eligible_cohorts"] < min_cohorts:
        return True, ("only %d cohort(s) clear the 20-review floor - there is "
                      "no split to render" % struct["eligible_cohorts"])
    if struct["veteran_share"] > max_veteran_share:
        return True, ("%.1f%% of the pool is the veteran cohort (limit %.0f%%) "
                      "- the playtime split has nothing to contrast"
                      % (100 * struct["veteran_share"], 100 * max_veteran_share))
    return False, None


def generate(appid, ip=None, reserve=live_quota.LIVE_RESERVE, quiet=False,
             ledger="live", segmentation_gate=False):
    """Returns (published, result). Never leaves an ungated verdict on disk.

    ledger selects which claim on the daily budget this generation charges:
      "live"  - the reserve carved out for search-box cache misses (guard 1)
      "batch" - the daily budget MINUS that reserve, so an overnight catalog
                run can never exhaust the capacity live generation depends on

    segmentation_gate is a batch-only economy: it drops a title whose measured
    cohort structure cannot support a split, after the free ingest stage and
    before the first stage that costs quota. Live generation leaves it off - a
    user who asked for a specific title gets an honest verdict about it, thin
    cohorts and all, because invariant 12 already renders those muted.
    """
    state = live_quota.load()
    if ledger == "batch":
        allowed, reason, detail = live_quota.can_batch(state, reserve=reserve)
    else:
        allowed, reason, detail = live_quota.can_generate(state, ip, reserve)
    if not allowed:
        # guard 1: reserve spent (or the secondary IP guard) -> queue fallback
        return False, {"published": False, "outcome": reason, "detail": detail,
                       "fallback": "queue"}

    # Baseline for REPORTING what this title spent. The charging happens at the
    # choke point every request passes through (model_pacer._acquire), before
    # the request is sent, so failures are charged exactly like successes and no
    # early return can skip it.
    calls_before = model_pacer.calls_for(appid)
    timings, log = [], []
    for key, label, script in STAGES:
        if not quiet:
            print("  [%s] %s..." % (key, label), flush=True)
        # Live generation is ALWAYS flash-lite. flash is capped at 20/day and
        # its allowance belongs to the batch's flash tier; a cache miss must
        # never wait on tomorrow's quota, and a live hit on a tier title would
        # burn a slot the batch reserved.
        extra = ("--force-lite",) if (key == "verdict" and ledger != "batch") else ()
        dt, proc = run_stage(script, appid, extra=extra, ledger=ledger)
        timings.append({"stage": key, "label": label, "seconds": round(dt, 1)})
        log.append(proc.stdout[-4000:])
        if proc.returncode != 0:
            # Already charged: every request this title sent was booked by the
            # pacer before it went out, failures included. This figure is for
            # REPORTING only - the ledger does not depend on reaching this line,
            # which is the whole point of moving the charge to the choke point.
            spent = model_pacer.calls_for(appid) - calls_before
            return False, {"published": False, "outcome": "stage_failed",
                           "stage": key, "timings": timings, "model_calls": spent,
                           "stderr": proc.stderr[-1500:], "fallback": "queue"}

        # the measured gate, placed exactly on the cost boundary: ingest is
        # free, everything after "filter" spends quota
        if segmentation_gate and key == "filter":
            struct = cohort_structure(appid)
            thin, why = thin_segmentation(struct)
            if thin:
                # the gate fires before any model call, so this is normally 0 -
                # but report the measured figure rather than asserting it
                spent = model_pacer.calls_for(appid) - calls_before
                return False, {"published": False,
                               "outcome": "thin_segmentation",
                               "reason": why, "structure": struct,
                               "timings": timings, "model_calls": spent,
                               "fallback": "skip"}

    out_path = VERDICTS / ("%s.json" % appid)
    if not out_path.exists():
        spent = model_pacer.calls_for(appid) - calls_before
        return False, {"published": False, "outcome": "no_verdict_written",
                       "timings": timings, "model_calls": spent,
                       "fallback": "queue"}

    # guard 2: invariant 8, in-pipeline, before anything renders
    t0 = time.time()
    verdict = json.loads(out_path.read_text(encoding="utf-8"))
    passed, report = qr4_gate.gate(verdict, verdict.get("game_name"))
    timings.append({"stage": "qr4", "label": "Safety check",
                    "seconds": round(time.time() - t0, 1)})

    cost = model_pacer.calls_for(appid) - calls_before
    # Usage is already booked, request by request. This records that one TITLE
    # finished, so status() can still report generations_today.
    live_quota.note_generation(ledger=ledger, ip=ip)

    if not passed:
        # withheld, not served-with-a-warning. Remove the artifact so no static
        # route can pick it up, and queue the title for manual audit.
        out_path.unlink()
        return False, {"published": False, "outcome": "qr4_failed",
                       "qr4": report, "timings": timings,
                       "model_calls": cost, "fallback": "queue"}

    return True, {"published": True, "outcome": "ok", "appid": appid,
                  "game_name": verdict.get("game_name"), "qr4": report,
                  "timings": timings, "model_calls": cost,
                  "total_seconds": round(sum(t["seconds"] for t in timings), 1)}



def run_single_stage(appid, stage, ledger="live"):
    """Run exactly ONE stage, with the flags this ledger requires.

    The CI workflow needs five separately-named steps, because /api/status maps
    those step names to the progress feed the user watches - collapsing them
    into one generate_one call would leave the UI with nothing to show. But the
    workflow used to invoke the four stage scripts DIRECTLY, which meant the
    flag logic here never applied to the live path: --force-lite was never
    passed, and live generation asked for flash.

    So the stages stay separate and every one of them comes through here. One
    place decides which model a path may use.

    NOTHING HERE CHARGES THE LEDGER ANY MORE, and that is the fix rather than an
    omission. This used to charge in the qr4 branch only, as a delta from a
    baseline the ingest branch wrote - so a stage run on its own charged nothing
    and left no trace that it had not. The pacer books every request as it is
    sent, whichever stage sends it and whether or not a later stage ever runs.
    """
    for key, label, script in STAGES:
        if key != stage:
            continue
        extra = ("--force-lite",) if (key == "verdict" and ledger != "batch") else ()
        dt, proc = run_stage(script, appid, extra=extra, ledger=ledger)
        print(proc.stdout[-6000:])
        if proc.stderr:
            print(proc.stderr[-3000:], file=sys.stderr)
        print("[%s] %.1fs rc=%d" % (key, dt, proc.returncode))
        return proc.returncode

    if stage == "qr4":
        # invariant 8, at the end of the run. Usage was charged per request as
        # it went out; all that is recorded here is that a title completed.
        out_path = VERDICTS / ("%s.json" % appid)
        if not out_path.exists():
            print("no verdict written for %s" % appid, file=sys.stderr)
            return 1
        verdict = json.loads(out_path.read_text(encoding="utf-8"))
        passed, report = qr4_gate.gate(verdict, verdict.get("game_name"))
        print(json.dumps(report, indent=2))
        live_quota.note_generation(ledger=ledger)
        print("%s spent %d request(s), all booked to the %s ledger as they were "
              "sent" % (appid, model_pacer.calls_for(appid), ledger))
        if not passed:
            out_path.unlink()                      # withheld, never served
            return 1
        return 0

    print("unknown stage: %s" % stage, file=sys.stderr)
    return 2


def main():
    ap = argparse.ArgumentParser(description="Generate one verdict live")
    ap.add_argument("appid")
    ap.add_argument("--stage", default=None,
                    help="run one stage only (ingest|filter|extract|verdict|qr4)")
    ap.add_argument("--ledger", default="live", choices=("live", "batch"))
    ap.add_argument("--ip", default=None, help="secondary per-IP guard")
    ap.add_argument("--reserve", type=int, default=live_quota.LIVE_RESERVE)
    ap.add_argument("--report", action="store_true",
                    help="print the measured timing used to set the wait copy")
    args = ap.parse_args()

    if args.stage:
        sys.exit(run_single_stage(args.appid, args.stage, args.ledger))

    print("generating %s ..." % args.appid)
    t0 = time.time()
    # --ledger has to be THREADED, not just parsed. It was accepted by argparse
    # and then dropped here, so every full-run CLI invocation charged the live
    # reserve whatever the flag said - and asked can_generate() rather than
    # can_batch() for permission. Invisible until charging moved to the pacer,
    # because the check and the charge were consistently wrong together.
    published, result = generate(args.appid, args.ip, args.reserve,
                                 ledger=args.ledger)
    wall = time.time() - t0

    print("\n%s" % json.dumps({k: v for k, v in result.items()
                               if k not in ("timings",)}, indent=2)[:1200])
    for t in result.get("timings", []):
        print("  %-8s %6.1fs  %s" % (t["stage"], t["seconds"], t["label"]))
    print("  %-8s %6.1fs  TOTAL" % ("", wall))

    if args.report:
        mins = wall / 60.0
        print("\n--- copy calibration (CLAUDE.md guard 3) ---")
        print("  measured wall clock : %.1fs (%.1f min)" % (wall, mins))
        print("  model calls charged : %s" % result.get("model_calls"))
        band = ("under a minute" if wall < 55 else
                "a couple of minutes" if wall < 150 else
                "a few minutes" if wall < 330 else
                "around %d minutes" % round(mins))
        print("  honest copy         : \"This takes %s.\"" % band)
        print("  (measured %s; regenerate this number if the pipeline changes)"
              % datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    sys.exit(0 if published else 2)


if __name__ == "__main__":
    main()
