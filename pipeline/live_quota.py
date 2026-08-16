"""
WorthIt.gg - global daily reserve for live generation (CLAUDE.md guard 1)

WHY GLOBAL AND NOT PER-IP
-------------------------
Per-IP throttling cannot protect a global quota, because the number of IPs is
not bounded by anything we control. "5 generations per IP per hour" permits
unlimited total generations given enough clients - which is precisely the shape
of the traffic a launch is trying to attract. The daily Gemini free-tier ceiling
(~1,500 requests) is a GLOBAL resource, so the limit that protects it has to be
global too.

Per-IP survives here only as a SECONDARY guard: it stops one client burning the
whole shared reserve, which is a different failure and a real one. It is never
the thing standing between a traffic spike and an exhausted quota.

WHAT THE RESERVE IS
-------------------
The pipeline's own batch work (Phase 4 catalog runs, regeneration) and live
generation draw on the same daily budget. LIVE_RESERVE carves out the tail of
that budget for live generation only, so a batch run cannot silently consume the
capacity that keeps the search box working - and, symmetrically, live traffic
cannot eat the batch capacity the catalog depends on.

When the reserve is spent, live generation switches OFF for the rest of the
quota day and cache misses fall back to the request queue. The quota day ends at
MIDNIGHT PACIFIC, which is when Google resets RPD - not at midnight UTC. See
pipeline/quota_day.py. Cached verdicts are static
files on a CDN and are never affected by any of this.

State is a small JSON file, committed by the generation workflow. No database:
the counter is the same kind of artifact as everything else here.

Usage:
    .venv/bin/python pipeline/live_quota.py --status
    .venv/bin/python pipeline/live_quota.py --check --ip 1.2.3.4
    .venv/bin/python pipeline/live_quota.py --record 7 --ip 1.2.3.4
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quota_day   # noqa: E402  (one definition of the quota day boundary)
import model_pacer  # noqa: E402  (reuses its cross-process file lock)

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data/live_quota.json"

# Gemini free tier, requests/day PER MODEL. VERIFIED from the 429 body, not
# assumed: gemini-3.5-flash-lite is 500/day and gemini-3.5-flash is 20/day
# (quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier, 2026-08-02).
#
# PER PROJECT, per that quotaId - so these ceilings are only WorthIt.gg's if
# nothing else bills to the same project. Confirmed by the owner on 2026-08-17
# that it is single-purpose: the console display name "Review Summariser" is an
# earlier working name for THIS project, not a separate one sharing the key. No
# other work draws from these two buckets, so a batch night can plan against
# the whole 500 without an invisible competitor. See .env.example for the
# longer note, and the 2026-08-13 BACKLOG entry for why this was unanswerable
# from a checkout (an `AQ.` key does not self-describe its project).
#
# This was 1500 - the figure in CLAUDE.md - and it was wrong by 3x. Every budget
# projection built on it was wrong by the same factor, including "1,050 calls
# fits in 1,200", which is how a batch walked into a wall the budget stop was
# supposed to prevent. The number here is now the one the API actually enforces.
#
# Synthesis titles on the flash tier draw the separate 20/day flash bucket, so
# they do not consume this one.
DAILY_LIMIT = 500
# Tail of the daily budget reserved for live generation (guard 1). 100 of 500
# leaves 400/day for the catalog batch. The old 300 was chosen against a 1500
# ceiling; carried over unchanged it would have left the batch only 200.
LIVE_RESERVE = 100

# gemini-3.5-flash has its own, much smaller, daily bucket. It is NOT part of
# DAILY_LIMIT - the two models are metered separately by the API - so it needs
# its own counter and its own refusal.
#
# This exists because a schedule written in comments is not a schedule.
# flash_tier.txt named a day per title, model_for() ignored the day, and the
# batch spent the whole allowance in minutes and then 429'd every remaining tier
# title. The day check is now enforced in model_for(); this is the second lock:
# even a correctly scheduled run cannot exceed the cap, because the ledger
# refuses the 21st call regardless of what any schedule says.
FLASH_DAILY_LIMIT = 20
# Secondary guard only - see the module docstring.
IP_LIMIT_PER_HOUR = 5

# Worst case for one generation: 4 cohorts x (1 extraction + 2 grounding
# retries) + 1 synthesis. Charged up front so a burst cannot oversubscribe the
# reserve between check and record; the true cost is reconciled by record().
EST_COST = 13


def _today(clock=None):
    """The quota day, keyed on midnight PACIFIC - see pipeline/quota_day.py.

    Not UTC. Google resets RPD quotas at midnight Pacific, and keying this on
    UTC zeroed the ledger seven hours early, in exactly the window an overnight
    batch runs in.
    """
    return quota_day.today(clock)


def _hour(clock=None):
    return quota_day.hour(clock)


def load(path=STATE_PATH):
    p = Path(path)
    if p.exists():
        state = json.loads(p.read_text(encoding="utf-8"))
    else:
        state = {}
    # a new QUOTA day resets everything (midnight Pacific, not UTC - the
    # boundary Google actually resets on); stale hours are dropped on write
    if state.get("date") != _today():
        state = {"date": _today(), "live_used": 0, "batch_used": 0,
                 "flash_used": 0, "generations": 0, "batch_generations": 0,
                 "flash_generations": 0, "by_ip_hour": {}}
    state.setdefault("live_used", 0)
    state.setdefault("batch_used", 0)
    state.setdefault("flash_used", 0)
    state.setdefault("flash_generations", 0)
    state.setdefault("generations", 0)
    state.setdefault("batch_generations", 0)
    state.setdefault("by_ip_hour", {})
    return state


def save(state, path=STATE_PATH):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    hour = _hour()
    state["by_ip_hour"] = {k: v for k, v in state["by_ip_hour"].items()
                           if k.endswith(hour)}
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state


def remaining(state, reserve=LIVE_RESERVE):
    return max(0, reserve - state.get("live_used", 0))


def can_generate(state, ip=None, reserve=LIVE_RESERVE, est=EST_COST,
                 ip_limit=IP_LIMIT_PER_HOUR):
    """(allowed, reason, detail). Reason is a machine key; the UI maps it to copy.

    Order matters: the global reserve is checked FIRST, so a rejection is
    attributed to the limit that actually protects the quota rather than to the
    secondary guard.
    """
    left = remaining(state, reserve)
    if left < est:
        return False, "reserve_exhausted", {
            "live_used": state.get("live_used", 0), "reserve": reserve,
            "remaining": left, "needed": est,
            "resets": "00:00 America/Los_Angeles"}

    if ip:
        key = "%s|%s" % (ip, _hour())
        used = state["by_ip_hour"].get(key, 0)
        if used >= ip_limit:
            return False, "ip_limited", {"ip_generations_this_hour": used,
                                         "ip_limit": ip_limit}

    return True, "ok", {"remaining": left, "generations_left_approx": left // est}


def batch_budget(reserve=LIVE_RESERVE, daily=DAILY_LIMIT):
    """What the batch may spend: the daily budget MINUS the live reserve.

    The symmetry this module's docstring promises, finally implemented in both
    directions. The reserve belongs to live generation and the batch cannot
    touch it, so an overnight catalog run can never be the reason a visitor's
    search box falls back to the queue in the morning.
    """
    return max(0, daily - reserve)


def batch_remaining(state, reserve=LIVE_RESERVE, daily=DAILY_LIMIT):
    """Batch headroom, charged against EVERYTHING spent today.

    Live spend counts here on purpose: the two ledgers are separate claims on
    one shared daily ceiling, so live generation eats batch headroom even though
    the reverse is forbidden. Asymmetric by design - the reserve is a floor
    under live generation, not a wall around it.
    """
    used = state.get("batch_used", 0) + state.get("live_used", 0)
    return max(0, batch_budget(reserve, daily) - used)


def can_batch(state, est=EST_COST, reserve=LIVE_RESERVE, daily=DAILY_LIMIT):
    """(allowed, reason, detail) for one batch title."""
    left = batch_remaining(state, reserve, daily)
    if left < est:
        return False, "batch_budget_exhausted", {
            "batch_used": state.get("batch_used", 0),
            "live_used": state.get("live_used", 0),
            "batch_budget": batch_budget(reserve, daily),
            "remaining": left, "needed": est,
            "reserve_untouched": reserve,
            "resets": "00:00 America/Los_Angeles"}
    return True, "ok", {"remaining": left, "titles_left_approx": left // est}


# --------------------------------------------------------------------------
# remote reconciliation (read-only, once per batch run)
# --------------------------------------------------------------------------
#
# THE GAP THIS CLOSES, and why it is one-directional.
#
# batch_remaining() already charges live spend against batch headroom. What it
# cannot do is LEARN that spend: the live path writes the LIVE_QUOTA repository
# variable from the Vercel function, this file writes data/live_quota.json, and
# nothing carries one into the other. So the batch reads its own live_used - a
# number the live path never updates - and believes headroom it may not have.
#
# Only that direction is dangerous. Batch spend never needs to reach LIVE_QUOTA,
# because can_generate() measures live generation against the reserve alone and
# never consults batch_used, so a batch night cannot consume the live path's
# floor no matter how much it spends. One read at startup is therefore the whole
# fix, not half of a sync.
#
# The read replaces a manual `gh variable get LIVE_QUOTA` that was being run by
# hand before every batch night.

REPO = "GaganMalik025/worthit-gg"


class RemoteQuotaUnavailable(RuntimeError):
    """The remote ledger could not be read. NEVER treat this as live_used=0."""


def _gh_runner(cmd, timeout=20):
    """Default runner: (returncode, stdout, stderr). Injected in tests."""
    import subprocess
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "gh not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "gh timed out after %ss" % timeout


def fetch_remote_live_used(repo=REPO, runner=None, clock=None):
    """live_used from the LIVE_QUOTA repo variable, for TODAY's quota day.

    Returns (live_used, detail). Raises RemoteQuotaUnavailable if the variable
    cannot be read or parsed - the caller must not paper over that with 0.

    A remote ledger dated to an EARLIER quota day reports 0, not its stale
    figure: the live path zeroes on date mismatch exactly as load() does here,
    so yesterday's 13 is not today's spend. That is day semantics, not
    under-counting - the alternative would tax every future night with a number
    that already expired.
    """
    runner = runner or _gh_runner
    cmd = ["gh", "variable", "get", "LIVE_QUOTA", "--repo", repo]
    rc, out, err = runner(cmd)
    if rc != 0:
        raise RemoteQuotaUnavailable(
            "gh exited %s: %s" % (rc, (err or out or "").strip()[:200]))
    try:
        blob = json.loads(out)
    except ValueError as exc:
        raise RemoteQuotaUnavailable("LIVE_QUOTA is not JSON: %s" % exc)
    if not isinstance(blob, dict):
        raise RemoteQuotaUnavailable("LIVE_QUOTA is not an object")

    remote_day = blob.get("date")
    if not remote_day:
        # An undated ledger cannot be aged. Refuse rather than guess.
        raise RemoteQuotaUnavailable("LIVE_QUOTA has no date field")
    today = _today(clock)
    if remote_day != today:
        return 0, {"remote_date": remote_day, "today": today,
                   "raw_live_used": blob.get("live_used", 0),
                   "note": "remote ledger is from another quota day - counts 0"}
    used = blob.get("live_used", 0)
    if not isinstance(used, int) or used < 0:
        raise RemoteQuotaUnavailable("live_used is not a non-negative int: %r" % used)
    return used, {"remote_date": remote_day, "today": today, "raw_live_used": used}


def reconcile_live_used(state, remote_live_used):
    """State copy whose live_used is the MAX of local and remote.

    Max, not remote: the two ledgers count different things (the local file also
    carries live generations run from this machine), and the safe error is to
    over-count. Under-counting is what hands the batch headroom that is not
    there and ends the night on 429s.
    """
    merged = dict(state)
    merged["live_used"] = max(state.get("live_used", 0) or 0,
                              int(remote_live_used or 0))
    return merged


def sync_live_used(remote_live_used, path=STATE_PATH):
    """PERSIST the reconciled live_used to the local ledger. Returns the state.

    Reconciling in memory is not enough and the first cut of this got it wrong:
    run_batch's per-title stop calls `can_batch(live_quota.load(), ...)`, which
    re-reads this file every iteration, so an in-memory merge reached the
    startup banner and nothing else - the actual budget stop stayed unprotected.

    Writing it once, here, means every later load() in the loop carries the
    reconciled figure without any state object being threaded through by hand.
    Locked and max()-based like the rest of this module, so it is safe to call
    alongside live charges and idempotent if run twice.
    """
    with model_pacer._locked(path):
        state = load(path)
        merged = max(state.get("live_used", 0) or 0, int(remote_live_used or 0))
        if merged != state.get("live_used", 0):
            state["live_used"] = merged
            save(state, path)
        return state


def flash_remaining(state, limit=FLASH_DAILY_LIMIT):
    return max(0, limit - state.get("flash_used", 0))


def can_flash(state, est=1, limit=FLASH_DAILY_LIMIT):
    """(allowed, reason, detail) for one gemini-3.5-flash request."""
    left = flash_remaining(state, limit)
    if left < est:
        return False, "flash_daily_exhausted", {
            "flash_used": state.get("flash_used", 0), "flash_limit": limit,
            "remaining": left, "needed": est,
            "resets": "00:00 America/Los_Angeles"}
    return True, "ok", {"remaining": left}


def record(state, cost, ip=None, ledger="live", count_generation=True):
    """Charge Gemini requests to one ledger.

    count_generation separates the two things this used to conflate. Usage is
    now charged PER REQUEST, from model_pacer._acquire - the one place every
    request passes through - so incrementing a generation counter there would
    make "generations_today" count requests instead of titles. The generation
    counters are bumped once, by the caller that knows a title finished
    (note_generation), and the per-IP tally rides with them because it counts
    generations per client, not requests.
    """
    n = int(cost)
    if ledger == "flash":
        state["flash_used"] = state.get("flash_used", 0) + n
        if count_generation:
            state["flash_generations"] = state.get("flash_generations", 0) + 1
        return state
    if ledger == "batch":
        state["batch_used"] = state.get("batch_used", 0) + n
        if count_generation:
            state["batch_generations"] = state.get("batch_generations", 0) + 1
        return state
    state["live_used"] = state.get("live_used", 0) + n
    if count_generation:
        state["generations"] = state.get("generations", 0) + 1
        if ip:
            key = "%s|%s" % (ip, _hour())
            state["by_ip_hour"][key] = state["by_ip_hour"].get(key, 0) + 1
    return state


def note_generation(ledger="live", ip=None, path=STATE_PATH):
    """One title finished. Counts the generation, charges no usage.

    Usage arrives per request from the pacer; this is only the "how many titles"
    half, kept so status() can still say generations_today.
    """
    return charge(0, ip, ledger=ledger, path=path, count_generation=True)


def charge(cost, ip=None, ledger="live", path=STATE_PATH, count_generation=True):
    """Atomically load -> record -> save. Returns the updated state.

    The read-modify-write MUST be locked. It was not, and the batch runs titles
    concurrently: two workers each loaded the ledger, each added their own cost,
    and whichever saved last erased the other. A verification run spent 28
    requests and the ledger recorded 17 - a lost-update race, not a counting
    error. The per-title figures were exact the whole time; the aggregation was
    dropping them.

    Uses the pacer's lock helper so the guarantee holds across processes too,
    not just across threads in one interpreter.
    """
    with model_pacer._locked(path):
        state = load(path)
        record(state, cost, ip, ledger=ledger, count_generation=count_generation)
        save(state, path)
        return state


def status(state, reserve=LIVE_RESERVE, est=EST_COST):
    left = remaining(state, reserve)
    bleft = batch_remaining(state, reserve)
    return {
        "date": state.get("date"),
        "daily_limit": DAILY_LIMIT,
        "live_reserve": reserve,
        "live_used": state.get("live_used", 0),
        "remaining": left,
        "generations_today": state.get("generations", 0),
        "generations_left_approx": left // est,
        "live_generation": "on" if left >= est else "off_falls_back_to_queue",
        "batch_budget": batch_budget(reserve),
        "batch_used": state.get("batch_used", 0),
        "batch_remaining": bleft,
        "batch_generations_today": state.get("batch_generations", 0),
        "batch_titles_left_approx": bleft // est,
        "flash_daily_limit": FLASH_DAILY_LIMIT,
        "flash_used": state.get("flash_used", 0),
        "flash_remaining": flash_remaining(state),
        "flash_generations_today": state.get("flash_generations", 0),
    }


def main():
    ap = argparse.ArgumentParser(description="Live-generation quota reserve")
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--record", type=int, metavar="COST")
    ap.add_argument("--ip", default=None)
    ap.add_argument("--reserve", type=int, default=LIVE_RESERVE)
    args = ap.parse_args()

    state = load(args.state)

    if args.check:
        allowed, reason, detail = can_generate(state, args.ip, args.reserve)
        print(json.dumps({"allowed": allowed, "reason": reason, **detail}, indent=2))
        raise SystemExit(0 if allowed else 2)

    if args.record is not None:
        record(state, args.record, args.ip)
        save(state, args.state)

    print(json.dumps(status(state, args.reserve), indent=2))


if __name__ == "__main__":
    main()
