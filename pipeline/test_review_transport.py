"""
Offline tests for the GetAppReviews transport in fetch_reviews.py.

No network: requests.get is stubbed and every request is inspected. This endpoint
fails quietly - plain query parameters return 200 and are ignored, and a default
filter or purchase_type returns real reviews, just the wrong ones - so nothing
downstream can notice a wrong parameter. What is asked for has to be pinned here.

Run:  .venv/bin/python pipeline/test_review_transport.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_reviews as fr  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print("  %-62s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        FAILURES.append("%s %s" % (name, detail))


class Resp:
    def __init__(self, status=200, body=None, text=None, headers=None):
        self.status_code = status
        self._body, self._text = body, text
        self.headers = headers or {}

    def json(self):
        if self._text is not None:
            return json.loads(self._text)
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fr.requests.HTTPError("HTTP %s" % self.status_code)


def stubbed(responses):
    """Patch requests.get; returns the list of recorded (url, params, kwargs)."""
    calls = []

    def fake(url, params=None, **kw):
        calls.append((url, params, kw))
        return responses.pop(0) if isinstance(responses, list) else responses

    fr.requests.get = fake
    return calls


PAGE = {"response": {"query_summary": {"num_reviews": 1, "total_reviews": 9,
                                       "total_positive": 8},
                     "cursor": "next",
                     "reviews": [{"recommendationid": "1", "review": "x",
                                  "voted_up": True, "votes_up": 0,
                                  "votes_funny": 0, "weighted_vote_score": 0.5,
                                  "timestamp_created": 1,
                                  "author": {"playtime_at_review": 130}}]}}


def sent_for(review_filter):
    calls = stubbed(Resp(body=PAGE))
    fr.fetch_page(413150, "*", {"filter": review_filter}, use_cache=False)
    return calls[0]


_real_get = fr.requests.get


def test_what_is_asked_for():
    print("\ntransport: what is asked for")
    url, params, kw = sent_for("recent")
    check("calls GetAppReviews on api.steampowered.com",
          url == "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/",
          url)
    check("everything travels in input_json, nothing as a query parameter",
          list(params) == ["input_json"], params)
    q = json.loads(params["input_json"])
    check("appid is a number", q["appid"] == 413150, q)
    check("recent is filter 1", q["filter"] == 1, q)
    check("recent carries no day_range", "day_range" not in q, q)
    check("every purchase type, not the Steam-only default",
          q["purchase_type"] == 1, q)
    check("english only (non-goal: other languages)",
          q["languages"] == ["english"], q)
    check("all review types", q["review_type"] == 0, q)
    check("full pages", q["num_per_page"] == 100, q)
    check("the first page's cursor is *", q["cursor"] == "*", q)
    check("off-topic reviews stay filtered: the flag is left at its default",
          "filter_offtopic_activity" not in q, q)

    q = json.loads(sent_for("all")[1]["input_json"])
    check("all is Helpful", q["filter"] == 0, q)
    check("all keeps Steam's default window, never reaching back to launch",
          "day_range" not in q, q)
    q = json.loads(sent_for("updated")[1]["input_json"])
    check("updated is filter 2", q["filter"] == 2, q)


def test_redirects_are_failures():
    print("\ntransport: a redirect is a failure, not a page")
    calls = stubbed(Resp(302, headers={"Location": "https://store.steampowered.com/"}))
    try:
        fr.fetch_page(413150, "*", {"filter": "recent"}, use_cache=False)
        check("a 302 raises", False)
    except RuntimeError as exc:
        check("a 302 raises and names where it went",
              "redirected" in str(exc) and "store.steampowered.com" in str(exc),
              exc)
    check("redirects are not followed", calls[0][2].get("allow_redirects") is False,
          calls[0][2])
    check("a redirect is not retried", len(calls) == 1, len(calls))

    calls = stubbed(Resp(body={}))
    fr._get_with_backoff("https://x", None)
    check("other callers still follow redirects (appdetails, store search)",
          calls[0][2].get("allow_redirects") is True, calls[0][2])


def test_bad_bodies():
    print("\ntransport: a body that is not an answer")
    for name, resp in (("HTML", Resp(text="<html>")),
                       ("no response key", Resp(body={"success": 1})),
                       ("a non-object response", Resp(body={"response": []}))):
        stubbed(resp)
        try:
            fr.fetch_page(413150, "*", {"filter": "recent"}, use_cache=False)
            check("%s raises a named error" % name, False)
        except RuntimeError as exc:
            check("%s raises a named error" % name, "GetAppReviews" in str(exc), exc)


def test_shape_and_cache():
    print("\ntransport: what comes back, and the page cache")
    with tempfile.TemporaryDirectory() as d:
        fr.CACHE_DIR = Path(d)
        calls = stubbed(Resp(body=PAGE))
        data, cached = fr.fetch_page(413150, "*", {"filter": "recent"})
        check("the response wrapper is unwrapped",
              data["reviews"][0]["recommendationid"] == "1", data)
        check("a live page is not reported as cached", cached is False)
        data2, cached2 = fr.fetch_page(413150, "*", {"filter": "recent"})
        check("the second read comes from disk",
              cached2 and len(calls) == 1, len(calls))
        check("the cached body is the unwrapped shape",
              data2 == PAGE["response"], data2)

        # the shape every page cached from the old endpoint has on disk
        old = {"success": 1, "cursor": "old", "reviews": [],
               "query_summary": {"total_reviews": 3}}
        fr.save_cached_page(1, "all", 0, "*", old)
        data3, cached3 = fr.fetch_page(1, "*", {"filter": "all"})
        check("a page cached from the old endpoint still replays",
              cached3 and data3 == old, data3)

        # an appid with no reviews answers {"response": {}}
        stubbed(Resp(body={"response": {}}))
        pool = {}
        _, pages, _ = fr.sweep(999, "recent", pool, 100, 12, 3, 0.0, True)
        check("an empty response ends the sweep cleanly",
              not pool and pages == 0, (pool, pages))

        row = fr.normalize(PAGE["response"]["reviews"][0], 413150)
        check("a numeric weighted_vote_score normalizes",
              row["weighted_vote_score"] == 0.5, row)
        check("minutes still become hours once (invariant 1)",
              row["minutes_at_review"] == 130
              and row["hours_at_review"] == 2.2, row)
        check("minutes still decide the bucket (invariant 2)",
              row["bucket"] == "early", row)


if __name__ == "__main__":
    # THE WHOLE RUN WRITES TO A TEMP DIR, set before the first test. fetch_page saves
    # every live page, and the stub answers count as live. An earlier version of this
    # file swapped save_cached_page per test, got it wrong, and overwrote three real
    # pages under data/cache/413150, which is the only copy (BACKLOG 2026-11-03).
    with tempfile.TemporaryDirectory() as run_dir:
        fr.CACHE_DIR = Path(run_dir)
        test_what_is_asked_for()
        test_redirects_are_failures()
        test_bad_bodies()
        fr.CACHE_DIR = Path(run_dir)
        test_shape_and_cache()
    fr.requests.get = _real_get
    if FAILURES:
        print("\n%d FAILURES:" % len(FAILURES))
        for f in FAILURES:
            print("  %s" % f)
        sys.exit(1)
    print("\nall review transport tests passed")
