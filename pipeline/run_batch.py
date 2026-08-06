"""
WorthIt.gg - the overnight catalog batch (BUILD_PLAN 4.3)

Reads data/catalog.json and generates the titles on it, one worker per slot,
paced and budgeted so an unattended overnight run cannot overspend, cannot
starve live generation, and cannot lose its place.

IT DOES NOT REIMPLEMENT THE PIPELINE. Every title goes through
generate_one.generate(), which is the same code path live generation uses. That
is deliberate and it is what closes BUILD_PLAN 2.6: the QR-4 gate, the
artifact-removal-on-failure, and the quota charge are inherited rather than
copied, so there is no second ordering of the stages to keep in sync. A change
to the gate applies to both paths or to neither.

FOUR THINGS PROTECT AN UNATTENDED RUN
-------------------------------------
1. Budget stop. Before each title, live_quota.can_batch() is asked whether the
   worst case (EST_COST) still fits in the daily budget MINUS the live reserve.
   When it does not, the run stops cleanly with the remainder still on the
   manifest. Title counts are a guess; the counter is not.
2. Rate pacing. model_pacer enforces a shared per-minute ceiling across every
   worker process (see that module for why it cannot be in-process).
3. Resumability. A title with a verdict on disk is skipped. Below that,
   extraction responses are cached per exact prompt, so an interrupted title
   resumes from its finished cohorts at zero Gemini cost.
4. The measured segmentation gate, applied after the free ingest stage and
   before the first paid one - so a title whose real cohort structure cannot
   support a split costs nothing to reject.

Usage:
    .venv/bin/python pipeline/run_batch.py --dry-run
    .venv/bin/python pipeline/run_batch.py --limit 3          # the dry run
    .venv/bin/python pipeline/run_batch.py --night 1 --concurrency 2
"""

import argparse
import json
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_one  # noqa: E402
import live_quota    # noqa: E402
import model_pacer   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data/catalog.json"
STATE = ROOT / "data/batch_state.json"
VERDICTS = ROOT / "site/public/verdicts"

_lock = threading.Lock()


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"runs": [], "titles": {}}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                     encoding="utf-8")


def record(state, appid, entry):
    with _lock:
        state["titles"][str(appid)] = entry
        save_state(state)


def pending(catalog, state, night, limit, skip_flash_tier=False):
    """Titles still to do, in manifest order.

    A title already generated is skipped rather than regenerated - the point of
    a resumed run is to cost nothing for work already paid for. Terminal
    non-success outcomes are also skipped: a title the segmentation gate
    rejected does not get re-litigated on every restart.
    """
    TERMINAL = {"ok", "thin_segmentation", "qr4_failed"}
    # Flash-tier titles are held back so they are generated ONCE, on flash, on
    # their scheduled day. Generating them on flash-lite today and re-synthesing
    # tomorrow would spend a call to produce a verdict we then overwrite.
    tier = generate_one.flash_tier_ids() if skip_flash_tier else set()
    out = []
    for row in catalog["titles"]:
        if night and row.get("night") != night:
            continue
        appid = row["appid"]
        if appid in tier:
            continue
        if (VERDICTS / ("%d.json" % appid)).exists():
            continue
        prev = state["titles"].get(str(appid))
        if prev and prev.get("outcome") in TERMINAL:
            continue
        out.append(row)
        if limit and len(out) >= limit:
            break
    return out


def run_title(row, state, args):
    appid, title = row["appid"], row["title"]
    t0 = time.time()
    published, result = generate_one.generate(
        appid, reserve=args.reserve, quiet=True,
        ledger="batch", segmentation_gate=not args.no_gate)
    entry = {
        "title": title,
        "outcome": result.get("outcome"),
        "published": published,
        "model_calls": result.get("model_calls", 0),
        "seconds": round(time.time() - t0, 1),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for key in ("reason", "structure", "stage", "detail"):
        if key in result:
            entry[key] = result[key]
    record(state, appid, entry)

    mark = {"ok": "ok  ", "thin_segmentation": "thin", "qr4_failed": "QR4!",
            "stage_failed": "FAIL"}.get(result.get("outcome"), "----")
    print("  [%s] %-38s %5.0fs  %2d calls  %s"
          % (mark, title[:38], entry["seconds"], entry["model_calls"],
             entry.get("reason", "")[:44]), flush=True)
    return entry


def main():
    ap = argparse.ArgumentParser(description="Overnight catalog batch")
    ap.add_argument("--night", type=int, default=0, help="1, 2, or 0 for all")
    ap.add_argument("--limit", type=int, default=0, help="stop after N titles")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--reserve", type=int, default=live_quota.LIVE_RESERVE)
    ap.add_argument("--skip-flash-tier", action="store_true",
                    help="hold back titles scheduled for a flash day")
    ap.add_argument("--no-gate", action="store_true",
                    help="disable the measured segmentation gate")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would run, spend nothing")
    args = ap.parse_args()

    if not CATALOG.exists():
        sys.exit("no data/catalog.json - run pipeline/build_catalog.py first")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    state = load_state()
    todo = pending(catalog, state, args.night, args.limit,
                   args.skip_flash_tier)

    q = live_quota.load()
    budget = live_quota.batch_remaining(q, args.reserve)
    print("catalog %s | night %s | %d titles pending"
          % (catalog["generated_at"], args.night or "all", len(todo)))
    print("batch budget %d of %d remaining (live reserve %d untouched, "
          "live used %d today)"
          % (budget, live_quota.batch_budget(args.reserve), args.reserve,
             q.get("live_used", 0)))
    print("pacer %s" % json.dumps(model_pacer.status()))
    print("worst-case fit: %d titles at %d calls each"
          % (budget // live_quota.EST_COST, live_quota.EST_COST))

    if args.dry_run:
        for row in todo[:20]:
            print("  would run  %-9d %-42s (%s)"
                  % (row["appid"], row["title"][:42], row["class"]))
        if len(todo) > 20:
            print("  ... and %d more" % (len(todo) - 20))
        print("\n(dry run - nothing spent)")
        return

    state["runs"].append({
        "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "night": args.night, "pending": len(todo),
        "concurrency": args.concurrency})
    save_state(state)

    t0, done, stopped = time.time(), [], None

    # SIGINT must actually stop this. It did not: every future was submitted up
    # front, and `with ThreadPoolExecutor(...)` calls shutdown(wait=True) on the
    # way out, so KeyboardInterrupt landed in the main thread and the pool then
    # calmly drained all 131 queued titles anyway. Stopping the run took SIGTERM.
    #
    # Now a handler sets a flag, queued futures are cancelled, and only the
    # titles already in flight are allowed to finish - which is what keeps state
    # consistent, because run_title records each title AFTER its verdict is
    # written. Cancelling a queued title loses nothing; killing an in-flight one
    # mid-write is what we are avoiding.
    interrupted = {"flag": False}

    def _on_interrupt(signum, _frame):
        if interrupted["flag"]:                     # second Ctrl-C: give up now
            print("\nsecond interrupt - exiting immediately", flush=True)
            raise KeyboardInterrupt
        interrupted["flag"] = True
        print("\ninterrupt received: cancelling queued titles. Titles already "
              "running will finish and record, then this exits.", flush=True)

    prev_handler = signal.signal(signal.SIGINT, _on_interrupt)
    pool = ThreadPoolExecutor(max_workers=args.concurrency)
    try:
        futures = []
        for row in todo:
            if interrupted["flag"]:
                stopped = ("interrupted", {"submitted": len(futures)})
                break
            allowed, reason, detail = live_quota.can_batch(
                live_quota.load(), reserve=args.reserve)
            if not allowed:
                stopped = (reason, detail)
                print("\nBUDGET STOP: %s\n  %s" % (reason, json.dumps(detail)))
                break
            futures.append(pool.submit(run_title, row, state, args))
        for f in futures:
            if interrupted["flag"]:
                break
            try:
                done.append(f.result())
            except Exception as exc:  # noqa: BLE001 - one title must not end the run
                print("  [ERR ] %s" % exc, flush=True)
        if interrupted["flag"]:
            # cancel what has not started; wait only for the in-flight titles
            pool.shutdown(wait=True, cancel_futures=True)
            # Collect ONLY futures not already collected above. Extending with
            # every finished future re-added the ones the loop had already
            # appended, so an interrupted run reported more titles attempted
            # than exist and more calls than the day had - 112 titles and 614
            # calls against 104 titles and 506 requests.
            already = len(done)
            remaining = [f for f in futures[already:]
                         if f.done() and not f.cancelled() and not f.exception()]
            done.extend(f.result() for f in remaining)
            if stopped is None:
                stopped = ("interrupted", {"submitted": len(futures)})
            print("stopped: %d titles recorded, %d cancelled before starting"
                  % (len(done), sum(1 for f in futures if f.cancelled())))
        else:
            pool.shutdown(wait=True)
    finally:
        signal.signal(signal.SIGINT, prev_handler)

    wall = time.time() - t0
    ok = sum(1 for d in done if d["published"])
    calls = sum(d["model_calls"] for d in done)
    by = {}
    for d in done:
        by[d["outcome"]] = by.get(d["outcome"], 0) + 1

    print("\n%d attempted in %.1f min: %s" % (len(done), wall / 60, json.dumps(by)))
    print("  published     : %d" % ok)
    print("  model calls   : %d (mean %.1f per attempted title)"
          % (calls, calls / max(1, len(done))))
    print("  wall clock    : %.1fs mean per title" % (wall / max(1, len(done))))
    if done:
        rate = calls / (wall / 60) if wall else 0
        print("  effective rate: %.1f requests/min" % rate)
    q = live_quota.load()
    print("  batch budget  : %d of %d left, live reserve %d untouched"
          % (live_quota.batch_remaining(q, args.reserve),
             live_quota.batch_budget(args.reserve), args.reserve))
    if stopped:
        print("\nremaining titles stay on the manifest; rerun to continue")
    sys.exit(1 if any(d["outcome"] == "stage_failed" for d in done) else 0)


if __name__ == "__main__":
    main()
