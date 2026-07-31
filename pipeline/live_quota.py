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

When the reserve is spent, live generation switches OFF for the rest of the UTC
day and cache misses fall back to the request queue. Cached verdicts are static
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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data/live_quota.json"

# Gemini free tier, requests/day. The ceiling this whole module exists to defend.
DAILY_LIMIT = 1500
# Tail of the daily budget reserved for live generation (guard 1).
LIVE_RESERVE = 300
# Secondary guard only - see the module docstring.
IP_LIMIT_PER_HOUR = 5

# Worst case for one generation: 4 cohorts x (1 extraction + 2 grounding
# retries) + 1 synthesis. Charged up front so a burst cannot oversubscribe the
# reserve between check and record; the true cost is reconciled by record().
EST_COST = 13


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hour():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


def load(path=STATE_PATH):
    p = Path(path)
    if p.exists():
        state = json.loads(p.read_text(encoding="utf-8"))
    else:
        state = {}
    # a new UTC day resets everything; stale hours are dropped on write
    if state.get("date") != _today():
        state = {"date": _today(), "live_used": 0, "generations": 0,
                 "by_ip_hour": {}}
    state.setdefault("live_used", 0)
    state.setdefault("generations", 0)
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
            "remaining": left, "needed": est, "resets": "00:00 UTC"}

    if ip:
        key = "%s|%s" % (ip, _hour())
        used = state["by_ip_hour"].get(key, 0)
        if used >= ip_limit:
            return False, "ip_limited", {"ip_generations_this_hour": used,
                                         "ip_limit": ip_limit}

    return True, "ok", {"remaining": left, "generations_left_approx": left // est}


def record(state, cost, ip=None):
    """Charge actual Gemini requests used by one generation."""
    state["live_used"] = state.get("live_used", 0) + int(cost)
    state["generations"] = state.get("generations", 0) + 1
    if ip:
        key = "%s|%s" % (ip, _hour())
        state["by_ip_hour"][key] = state["by_ip_hour"].get(key, 0) + 1
    return state


def status(state, reserve=LIVE_RESERVE, est=EST_COST):
    left = remaining(state, reserve)
    return {
        "date": state.get("date"),
        "daily_limit": DAILY_LIMIT,
        "live_reserve": reserve,
        "live_used": state.get("live_used", 0),
        "remaining": left,
        "generations_today": state.get("generations", 0),
        "generations_left_approx": left // est,
        "live_generation": "on" if left >= est else "off_falls_back_to_queue",
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
