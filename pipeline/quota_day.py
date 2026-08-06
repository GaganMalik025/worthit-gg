"""
WorthIt.gg - the quota day boundary, in one place

Google's free-tier daily quotas reset at MIDNIGHT PACIFIC, not midnight UTC:

    "Requests per day (RPD) quotas reset at midnight Pacific time."
    - https://ai.google.dev/gemini-api/docs/rate-limits

Both ledgers used to key their day on UTC. Between 00:00 and 07:00 UTC that is
simply wrong: the counters zero themselves while the API's counters are still on
yesterday's numbers. A batch scheduled to start "after midnight" would reset its
own accounting, believe it had a full budget, and then fail against a quota that
had not moved. That is precisely the window an overnight run lives in.

WHY A SHARED MODULE RATHER THAN THE SAME FIX TWICE
--------------------------------------------------
live_quota.py and model_pacer.py must agree on when the day turns. If they
disagree by even an hour, one of them resets first and the pair briefly disagree
about how much budget exists - which is the same class of bug as the one being
fixed here, just harder to see. One definition, imported by both.

WHY A NAMED ZONE AND NOT A FIXED OFFSET
---------------------------------------
Pacific is UTC-7 in summer (PDT) and UTC-8 in winter (PST). A hardcoded offset
is correct for about half the year and silently an hour wrong for the rest,
including across the two transition dates. ZoneInfo carries the rules.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    QUOTA_TZ = ZoneInfo("America/Los_Angeles")
except ZoneInfoNotFoundError as exc:  # pragma: no cover - environment problem
    raise SystemExit(
        "the IANA time zone database is not available (%s).\n"
        "  Quota accounting keys on midnight Pacific, so this cannot fall back\n"
        "  to UTC without reintroducing the bug it exists to prevent.\n"
        "  Fix: pip install tzdata" % exc)


def now(clock=None):
    """Current time in the quota's zone. `clock` is an aware datetime, for tests."""
    return (clock or datetime.now(QUOTA_TZ)).astimezone(QUOTA_TZ)


def today(clock=None):
    """The quota day key. Rolls at midnight Pacific."""
    return now(clock).strftime("%Y-%m-%d")


def hour(clock=None):
    """Hour key for the per-IP window.

    Pacific is a whole-hour offset from UTC, so the bucket BOUNDARIES are
    identical to the old UTC ones - only the label changes. Moved here anyway so
    there is exactly one clock in the quota code.
    """
    return now(clock).strftime("%Y-%m-%dT%H")
