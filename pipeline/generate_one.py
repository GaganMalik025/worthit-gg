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
    verdict   synthesize       1 Gemini call, writes public/verdicts/<appid>.json
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

import live_quota  # noqa: E402
import qr4_gate    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv/bin/python")
VERDICTS = ROOT / "public/verdicts"

STAGES = [
    ("ingest", "Reading Steam reviews", ["pipeline/fetch_reviews.py"]),
    ("filter", "Filtering out junk and unsafe reviews", ["pipeline/filter_reviews.py"]),
    ("extract", "Reading each playtime cohort", ["pipeline/extract_claims.py"]),
    ("verdict", "Writing the verdict", ["pipeline/synthesize.py"]),
]


def run_stage(script_args, appid, timeout=900):
    t0 = time.time()
    proc = subprocess.run([PY] + script_args + [str(appid)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=timeout)
    return time.time() - t0, proc


def count_model_calls(out):
    """Gemini requests actually issued, for honest quota accounting."""
    return out.count("RAW MODEL OUTPUT") - out.count("[cached]")


def generate(appid, ip=None, reserve=live_quota.LIVE_RESERVE, quiet=False):
    """Returns (published, result). Never leaves an ungated verdict on disk."""
    state = live_quota.load()
    allowed, reason, detail = live_quota.can_generate(state, ip, reserve)
    if not allowed:
        # guard 1: reserve spent (or the secondary IP guard) -> queue fallback
        return False, {"published": False, "outcome": reason, "detail": detail,
                       "fallback": "queue"}

    timings, cost, log = [], 0, []
    for key, label, script in STAGES:
        if not quiet:
            print("  [%s] %s..." % (key, label), flush=True)
        dt, proc = run_stage(script, appid)
        timings.append({"stage": key, "label": label, "seconds": round(dt, 1)})
        log.append(proc.stdout[-4000:])
        cost += count_model_calls(proc.stdout)
        if proc.returncode != 0:
            return False, {"published": False, "outcome": "stage_failed",
                           "stage": key, "timings": timings,
                           "stderr": proc.stderr[-1500:], "fallback": "queue"}

    out_path = VERDICTS / ("%s.json" % appid)
    if not out_path.exists():
        return False, {"published": False, "outcome": "no_verdict_written",
                       "timings": timings, "fallback": "queue"}

    # guard 2: invariant 8, in-pipeline, before anything renders
    t0 = time.time()
    verdict = json.loads(out_path.read_text(encoding="utf-8"))
    passed, report = qr4_gate.gate(verdict, verdict.get("game_name"))
    timings.append({"stage": "qr4", "label": "Safety check",
                    "seconds": round(time.time() - t0, 1)})

    live_quota.record(state, cost, ip)
    live_quota.save(state)

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


def main():
    ap = argparse.ArgumentParser(description="Generate one verdict live")
    ap.add_argument("appid")
    ap.add_argument("--ip", default=None, help="secondary per-IP guard")
    ap.add_argument("--reserve", type=int, default=live_quota.LIVE_RESERVE)
    ap.add_argument("--report", action="store_true",
                    help="print the measured timing used to set the wait copy")
    args = ap.parse_args()

    print("generating %s ..." % args.appid)
    t0 = time.time()
    published, result = generate(args.appid, args.ip, args.reserve)
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
