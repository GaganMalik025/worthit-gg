"""
WorthIt.gg - cross-process rate pacing for Gemini calls

WHY THIS EXISTS SEPARATELY FROM THE BACKOFF ALREADY IN call_model
-----------------------------------------------------------------
extract_claims.call_model already retries on 429/RESOURCE_EXHAUSTED. That is
REACTIVE: it recovers after the limit has been hit, and hitting it still costs
wall clock and, on a bad day, a failed generation. The binding constraint on the
free tier is requests per MINUTE, not the daily cap - so a batch running several
titles at once needs a limit that stops the request before it is sent.

It cannot live in a Python object. The batch runs each stage as a SUBPROCESS
(generate_one.run_stage), so extraction and synthesis for different titles are
different interpreter processes with no shared memory. A token bucket in a
module-level variable would let N workers each believe they had the whole
budget. The state therefore lives in a file, guarded by an OS-level lock.

WHAT IT GUARANTEES
------------------
  * no more than RPM requests start in any rolling 60 seconds, across every
    process on this machine
  * jitter on release, so workers that pile up on a lock do not then fire in a
    synchronised burst the instant it frees
  * a running count of requests this minute AND this QUOTA day (midnight
    Pacific, per quota_day.py - NOT midnight UTC), written to disk,
    so a run resumed after an interruption READS its position instead of
    assuming it starts from zero
  * a real 429 permanently narrows the ceiling for the rest of the run
    (narrow()) - if the configured rate was wrong, stop re-testing it

WHAT IT DOES NOT DO
-------------------
It is not the quota ledger. It limits the RATE; live_quota.py limits the DAILY
TOTAL and keeps the live reserve separate from batch spend. Both are consulted:
the pacer decides when a call may go, the ledger decides whether it may go at
all.

Usage:
    from model_pacer import pace
    with pace("extract"):            # blocks until a token is free
        resp = client.models.generate_content(...)

    .venv/bin/python pipeline/model_pacer.py --status
"""

import argparse
import json
import os
import random
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quota_day  # noqa: E402  (one definition of the quota day boundary)

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data/model_pacer.json"

# Free-tier ceiling is 15 RPM. 12 leaves headroom rather than treating the
# limit as a target - the difference between the two is what absorbs a slow
# response, a clock skew, or a retry firing alongside a fresh call.
DEFAULT_RPM = 12
WINDOW = 60.0
JITTER = 0.3          # +/- seconds, so releases do not align into a burst
LOCK_TIMEOUT = 120.0  # a stuck holder must not deadlock the whole batch


def _today(clock=None):
    """The quota day, keyed on midnight PACIFIC - see pipeline/quota_day.py."""
    return quota_day.today(clock)


@contextmanager
def _locked(path, timeout=LOCK_TIMEOUT):
    """An exclusive lock via atomic directory creation.

    mkdir is atomic on every filesystem we care about and needs no third-party
    dependency (budget rule: no new services, no new packages). A stale lock
    left by a killed process is broken after `timeout`, because the batch
    running unattended overnight must not be able to wedge itself permanently.
    """
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            age = time.time() - lock.stat().st_mtime if lock.exists() else 0
            if age > timeout:
                print("  pacer: breaking a stale lock (%.0fs old)" % age)
                try:
                    lock.rmdir()
                except OSError:
                    pass
                continue
            if time.time() - start > timeout:
                raise TimeoutError("pacer lock held for over %.0fs" % timeout)
            time.sleep(0.05 + random.uniform(0, 0.05))
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def _load(path):
    p = Path(path)
    state = {}
    if p.exists():
        try:
            state = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            state = {}          # a corrupt pacer file must not stop a batch
    if state.get("date") != _today():
        state = {"date": _today(), "recent": [], "today": 0, "rpm": None}
    state.setdefault("recent", [])
    state.setdefault("today", 0)
    state.setdefault("rpm", None)
    state.setdefault("by_appid", {})
    return state


def _save(path, state):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state), encoding="utf-8")


def _acquire(path, rpm, now=None):
    """Reserve one slot. Returns (wait_seconds, used_this_minute, today).

    Also tallies the call against WORTHIT_APPID. This is the ONLY place every
    Gemini request passes through, which is what makes it the only place a
    per-title count can be correct: it increments BEFORE the request is sent, so
    a call that 429s, times out, or raises is counted exactly like one that
    succeeds. The previous counter scraped stdout for "RAW MODEL OUTPUT" and
    therefore missed every failed call - it reported 21 where 37 had been spent.

    Records the timestamp BEFORE sleeping, so a concurrent worker sees the
    reservation immediately and cannot hand out the same slot twice.
    """
    now = time.time() if now is None else now
    with _locked(path):
        state = _load(path)
        ceiling = state.get("rpm") or rpm
        recent = [t for t in state["recent"] if now - t < WINDOW]
        if len(recent) < ceiling:
            wait = 0.0
            stamp = now
        else:
            # the oldest call in the window leaves it at recent[0] + WINDOW
            wait = max(0.0, recent[0] + WINDOW - now) + random.uniform(0, JITTER)
            stamp = now + wait
        recent.append(stamp)
        state["recent"] = recent[-(ceiling * 3):]
        state["today"] = state.get("today", 0) + 1
        key = os.environ.get("WORTHIT_APPID") or "-"
        by = state.setdefault("by_appid", {})
        by[key] = by.get(key, 0) + 1
        _save(path, state)
        return wait, len(recent), state["today"]


def calls_for(appid, path=STATE_PATH):
    """Gemini requests charged to this appid today. Attempts, not successes."""
    return _load(path).get("by_appid", {}).get(str(appid), 0)


def narrow(new_rpm, path=STATE_PATH):
    """Permanently lower the ceiling for the rest of the day.

    Called when a 429 arrives despite pacing: the configured rate was wrong, so
    stop re-testing it. Only ever lowers.
    """
    with _locked(path):
        state = _load(path)
        cur = state.get("rpm") or DEFAULT_RPM
        state["rpm"] = min(cur, max(1, int(new_rpm)))
        _save(path, state)
        return state["rpm"]


@contextmanager
def pace(label="call", rpm=DEFAULT_RPM, path=STATE_PATH, quiet=False):
    """Block until a request slot is free, then run the body."""
    wait, used, today = _acquire(path, rpm)
    if wait > 0:
        if not quiet:
            print("    pacer: %s waiting %.1fs (rpm %d/%d, today %d)"
                  % (label, wait, used, rpm, today), flush=True)
        time.sleep(wait)
    elif not quiet:
        print("    pacer: %s go (rpm %d/%d, today %d)"
              % (label, used, rpm, today), flush=True)
    yield


def status(path=STATE_PATH, rpm=DEFAULT_RPM):
    now = time.time()
    state = _load(path)
    recent = [t for t in state["recent"] if now - t < WINDOW]
    return {
        "date": state.get("date"),
        "ceiling_rpm": state.get("rpm") or rpm,
        "configured_rpm": rpm,
        "narrowed": state.get("rpm") is not None,
        "in_flight_this_minute": len(recent),
        "requests_today": state.get("today", 0),
        "state_file": str(path),
    }


def main():
    ap = argparse.ArgumentParser(description="Gemini request pacer")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset", action="store_true", help="clear today's counters")
    ap.add_argument("--narrow", type=int, metavar="RPM")
    ap.add_argument("--rpm", type=int, default=DEFAULT_RPM)
    args = ap.parse_args()

    if args.reset:
        Path(STATE_PATH).unlink(missing_ok=True)
        print("pacer state cleared")
    if args.narrow:
        print("ceiling narrowed to %d rpm" % narrow(args.narrow))
    print(json.dumps(status(rpm=args.rpm), indent=2))


if __name__ == "__main__":
    main()
