"""
WorthIt.gg - ingestion (hardened, build plan 1.1)

Pulls Steam reviews for one or more appids, converts playtime to hours, buckets
by playtime-at-review, and dumps normalized JSON to disk.

What 1.1 added over v0:
  * per-bucket quotas instead of "first N reviews Steam felt like showing us"
  * merges filter=recent + filter=all, deduped on recommendationid
  * every raw API page cached to disk; finished games are skipped entirely
  * exponential backoff on 429 / 5xx / network blips

No API key required. Steam's appreviews endpoint is public.

Usage:
    python3 fetch_reviews.py --seeds
    python3 fetch_reviews.py 1091500 --target 400
    python3 fetch_reviews.py 1091500 413150 --force --filters recent,all
"""

import argparse
import json
import random
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import requests

ENDPOINT = "https://store.steampowered.com/appreviews/{appid}"
DETAILS_ENDPOINT = "https://store.steampowered.com/api/appdetails"
OUT_DIR = Path("data/raw")
CACHE_DIR = Path("data/cache")
USER_AGENT = "worthit.gg/0.1 (student project)"

# Eval seed set. Each appid verified from its store URL
# (store.steampowered.com/app/<appid>/) before first fetch.
SEED_GAMES = [
    "553850",   # HELLDIVERS 2        - review-bombed
    "1091500",  # Cyberpunk 2077      - launch disaster, since patched
    "233860",   # Kenshi              - good but niche
    "413150",   # Stardew Valley      - near-universal acclaim
    "1190460",  # DEATH STRANDING     - genuinely divisive (original, not the Director's Cut)
]

# Playtime-at-review buckets, in MINUTES (Steam's native unit).
# 120 min = Steam's refund window. Do not change without re-running evals.
BUCKETS = [
    ("refund_window", 0, 120),        # <2h  - the cohort that bounced
    ("early", 120, 1200),             # 2-20h
    ("mid", 1200, 6000),              # 20-100h
    ("veteran", 6000, float("inf")),  # 100h+
]

BUCKET_NAMES = [name for name, _, _ in BUCKETS] + ["unknown"]

# backoff: Steam has no published rate limit, so assume it has one.
MAX_ATTEMPTS = 5
BACKOFF_BASE = 2.0


def bucket_for(minutes):
    for name, lo, hi in BUCKETS:
        if lo <= minutes < hi:
            return name
    return "unknown"


# --------------------------------------------------------------------------
# transport: backoff + page cache
# --------------------------------------------------------------------------

def _get_with_backoff(url, params, timeout=20):
    """GET with exponential backoff on 429 / 5xx / network errors."""
    for attempt in range(MAX_ATTEMPTS):
        wait = None
        try:
            r = requests.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
            reason = type(exc).__name__
        else:
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else None
                except ValueError:
                    wait = None
                if wait is None:
                    wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
                reason = "HTTP %s" % r.status_code
            else:
                r.raise_for_status()
                return r

        if attempt == MAX_ATTEMPTS - 1:
            raise RuntimeError(
                "gave up after %d attempts (%s)" % (MAX_ATTEMPTS, reason)
            )
        print("    %s - backing off %.1fs (attempt %d/%d)"
              % (reason, wait, attempt + 1, MAX_ATTEMPTS))
        time.sleep(wait)


class CacheMiss(Exception):
    """Raised when a cache-only replay runs past the end of what we have."""


def cache_path(appid, review_filter, page_idx):
    return CACHE_DIR / str(appid) / ("%s_%02d.json" % (review_filter, page_idx))


def load_cached_page(appid, review_filter, page_idx, cursor):
    """Return the cached response for this page, or None on a miss.

    A page is only a hit if it was fetched from the same cursor, so replaying a
    sweep in order is deterministic.
    """
    path = cache_path(appid, review_filter, page_idx)
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if blob.get("cursor") != cursor:
        return None
    return blob.get("response")


def save_cached_page(appid, review_filter, page_idx, cursor, data):
    path = cache_path(appid, review_filter, page_idx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cursor": cursor, "response": data}, ensure_ascii=False),
        encoding="utf-8",
    )


def fetch_page(appid, cursor, params, page_idx=0, use_cache=True, sleep=0.0,
               cache_only=False):
    """One page of reviews. Served from disk when we already have it."""
    review_filter = params.get("filter", "recent")

    if use_cache:
        cached = load_cached_page(appid, review_filter, page_idx, cursor)
        if cached is not None:
            return cached, True

    if cache_only:
        # --restats replays what is on disk and must never touch the network
        raise CacheMiss("%s page %d not cached" % (review_filter, page_idx))

    q = {
        "json": 1,
        "cursor": cursor,
        "num_per_page": 100,
        "language": "english",
        "purchase_type": "all",
        "review_type": "all",
        **params,
    }
    if sleep:
        time.sleep(sleep)  # be polite; Steam will throttle you otherwise
    r = _get_with_backoff(ENDPOINT.format(appid=appid), q)
    data = r.json()
    if data.get("success") != 1:
        raise RuntimeError("Steam returned success=%s" % data.get("success"))

    save_cached_page(appid, review_filter, page_idx, cursor, data)
    return data, False


def resolve_game_name(appid, use_cache=True):
    """Store title for the appid. Makes 'verify the appid' a mechanical check."""
    path = CACHE_DIR / str(appid) / "appdetails.json"
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("name")
        except (ValueError, OSError):
            pass
    try:
        r = _get_with_backoff(
            DETAILS_ENDPOINT, {"appids": appid, "filters": "basic"}, timeout=15
        )
        entry = r.json().get(str(appid)) or {}
        if not entry.get("success"):
            return None
        name = (entry.get("data") or {}).get("name")
    except (RuntimeError, ValueError, requests.RequestException):
        return None
    if name:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8")
    return name


# --------------------------------------------------------------------------
# normalization  (invariant 1 lives here - do not move the /60)
# --------------------------------------------------------------------------

def normalize(review, appid):
    """Flatten to the fields the pipeline actually uses. Minutes -> hours ONCE, here."""
    author = review.get("author", {}) or {}
    at_review_min = author.get("playtime_at_review") or 0
    hardware = review.get("hardware") or {}

    return {
        # citation key - every downstream claim must reference this
        "recommendationid": review.get("recommendationid"),
        "appid": appid,
        "review_text": review.get("review", ""),
        "voted_up": review.get("voted_up"),
        # playtime: stored in HOURS. never hand raw minutes to the model.
        "hours_at_review": round(at_review_min / 60, 1),
        "hours_total_now": round((author.get("playtime_forever") or 0) / 60, 1),
        "hours_last_two_weeks": round((author.get("playtime_last_two_weeks") or 0) / 60, 1),
        "bucket": bucket_for(at_review_min),
        # temporal - powers pre/post-patch splits
        "created_ts": review.get("timestamp_created"),
        "updated_ts": review.get("timestamp_updated"),
        # distortion / context flags
        "refunded": review.get("refunded"),
        "early_access": review.get("written_during_early_access"),
        "steam_purchase": review.get("steam_purchase"),
        "received_for_free": review.get("received_for_free"),
        "steam_deck": review.get("primarily_steam_deck"),
        # helpfulness
        "votes_up": review.get("votes_up"),
        "votes_funny": review.get("votes_funny"),
        "weighted_vote_score": float(review.get("weighted_vote_score") or 0),
        # optional enrichment - present on SOME reviews only
        "gpu": hardware.get("adapter_description"),
        "cpu": hardware.get("cpu_name"),
        "ram_mb": hardware.get("system_ram"),
        "os": hardware.get("os"),
    }


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def _pool_bucket_counts(pool):
    counts = OrderedDict((name, 0) for name in BUCKET_NAMES)
    for rec in pool.values():
        counts[rec["review"]["bucket"]] += 1
    return counts


def _quotas_met(pool, quota):
    counts = _pool_bucket_counts(pool)
    return all(counts[name] >= quota for name, _, _ in BUCKETS)


def sweep(appid, review_filter, pool, quota, max_pages, min_pages, sleep, use_cache,
          cache_only=False):
    """Paginate one filter into the shared pool. Returns (query_summary, pages, live_calls).

    Nothing is discarded here - selection happens later, once both filters have
    contributed. Steam's ordering decides what we *see*, never what we *keep*.
    """
    cursor, summary, pages, live = "*", None, 0, 0

    while pages < max_pages:
        try:
            data, from_cache = fetch_page(
                appid, cursor, {"filter": review_filter},
                page_idx=pages, use_cache=use_cache,
                sleep=(0.0 if pages == 0 else sleep), cache_only=cache_only,
            )
        except CacheMiss:
            print("  [%s] end of cache at page %d" % (review_filter, pages + 1))
            break
        if not from_cache:
            live += 1
        if summary is None:
            summary = data.get("query_summary", {})

        batch = data.get("reviews", [])
        if not batch:
            print("  [%s] no more reviews returned; stopping" % review_filter)
            break

        new = 0
        for rv in batch:
            rid = rv.get("recommendationid")
            if rid is None:
                continue
            if rid in pool:
                # same review seen through the other filter - record the overlap
                if review_filter not in pool[rid]["source_filters"]:
                    pool[rid]["source_filters"].append(review_filter)
                continue
            pool[rid] = {
                "review": normalize(rv, appid),
                "source_filters": [review_filter],
                "seq": len(pool),
            }
            new += 1

        pages += 1
        print("  [%s] page %d: +%d new (pool %d)%s"
              % (review_filter, pages, new, len(pool), " [cached]" if from_cache else ""))

        if pages >= min_pages and _quotas_met(pool, quota):
            print("  [%s] every bucket has >= %d; stopping sweep" % (review_filter, quota))
            break

        next_cursor = data.get("cursor")
        if not next_cursor or next_cursor == cursor:
            print("  [%s] cursor exhausted; stopping" % review_filter)
            break
        cursor = next_cursor

    return summary, pages, live


def pool_stats(pool, summary):
    """Rates over the full PRE-QUOTA pool (invariant 11).

    Deliberately called "pool", not "population": this is every review we swept,
    not every review that exists. Helldivers 2's pool is 1,930 of 815,955 - a
    sample, just an unbiased-by-us one. Every rate here ships with the pool_n it
    was computed from so no figure can be quoted bare.

    Prevalence may only ever be read from this block, never from counting the
    reviews the quota kept or the filter spared.
    """
    total = len(pool)
    buckets = OrderedDict()
    for name in BUCKET_NAMES:
        subset = [rec["review"] for rec in pool.values()
                  if rec["review"]["bucket"] == name]
        if name == "unknown" and not subset:
            continue
        pos = sum(1 for r in subset if r["voted_up"])
        buckets[name] = {
            "pool_n": len(subset),
            "share_of_pool_pct": round(100.0 * len(subset) / total, 1) if total else None,
            "pct_positive": round(100.0 * pos / len(subset), 1) if subset else None,
        }
    steam_total = summary.get("total_reviews") or 0
    steam_pos = summary.get("total_positive") or 0
    return {
        "basis": "pre-quota pool swept at ingestion (a sample of Steam, not a census)",
        "pool_n": total,
        "buckets": buckets,
        "steam_total_reviews": steam_total or None,
        "steam_pct_positive": round(100.0 * steam_pos / steam_total, 1) if steam_total else None,
    }


def _round_robin(queues, limit):
    """Take up to `limit` items, alternating across queues. Returns (taken, remaining)."""
    queues = [list(q) for q in queues if q]
    taken = []
    while queues and len(taken) < limit:
        still = []
        for q in queues:
            if len(taken) < limit:
                taken.append(q.pop(0))
            if q:
                still.append(q)
        queues = still
    remaining = [item for q in queues for item in q]
    return taken, remaining


def select_by_quota(pool, target, quota, filters):
    """Per-bucket quotas, then backfill.

    `quota` is a cap, not a floor: a bucket that only has 60 reviews in the
    whole pool contributes 60, and the shortfall is backfilled round-robin from
    the buckets that have depth. Total stays ~= target, and a thin cohort (the
    refund window, usually) can never be crowded out by veterans - which is the
    entire point of the sampling change.
    """
    by_bucket = OrderedDict((name, OrderedDict()) for name in BUCKET_NAMES)
    for rec in sorted(pool.values(), key=lambda r: r["seq"]):
        primary = rec["source_filters"][0]
        by_bucket[rec["review"]["bucket"]].setdefault(primary, []).append(rec)

    chosen, leftovers = [], []
    for name in BUCKET_NAMES:
        # alternate across filters so no bucket ends up single-source
        queues = [by_bucket[name][f] for f in filters if f in by_bucket[name]]
        queues += [v for k, v in by_bucket[name].items() if k not in filters]
        picked, rest = _round_robin(queues, quota)
        chosen.extend(picked)
        leftovers.append(rest)

    if len(chosen) < target:
        extra, _ = _round_robin(leftovers, target - len(chosen))
        chosen.extend(extra)

    chosen.sort(key=lambda r: r["seq"])
    return chosen[:target]


def fetch_reviews(appid, target=400, filters=("recent", "all"), quota=None,
                  max_pages=12, min_pages=3, sleep=1.0, use_cache=True):
    """Sweep every filter into one pool, then select against per-bucket quotas."""
    if quota is None:
        quota = max(1, target // len(BUCKETS))

    pool, summary, pages_by_filter, live_calls = OrderedDict(), None, OrderedDict(), 0
    for review_filter in filters:
        s, pages, live = sweep(
            appid, review_filter, pool, quota, max_pages, min_pages, sleep, use_cache
        )
        pages_by_filter[review_filter] = pages
        live_calls += live
        if summary is None:
            summary = s

    selected = select_by_quota(pool, target, quota, list(filters))

    reviews = []
    for rec in selected:
        row = dict(rec["review"])
        row["source_filters"] = list(rec["source_filters"])
        reviews.append(row)

    stats = {
        "target": target,
        "quota": quota,
        "filters": list(filters),
        "pages_fetched": dict(pages_by_filter),
        "live_requests": live_calls,
        "pool_size": len(pool),
        "pool_by_bucket": dict(_pool_bucket_counts(pool)),
        # invariant 11: the only sanctioned source of prevalence downstream
        "pool": pool_stats(pool, summary or {}),
    }
    return reviews, (summary or {}), stats


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def report(reviews, summary, stats=None):
    """Print the distribution. Returns False if the refund cohort is empty."""
    stats = stats or {}
    pool_by_bucket = stats.get("pool_by_bucket", {})

    print("\n--- aggregate (Steam's own) ---")
    print("  score label   : %s" % summary.get("review_score_desc"))
    print("  total reviews : %s" % summary.get("total_reviews"))
    print("  positive      : %s" % summary.get("total_positive"))
    print("  negative      : %s" % summary.get("total_negative"))

    print("\n--- bucket distribution (playtime at review) ---")
    print("  %-14s %5s %7s %10s" % ("bucket", "kept", "of pool", "positive"))
    for name, _, _ in BUCKETS:
        subset = [r for r in reviews if r["bucket"] == name]
        pool_n = pool_by_bucket.get(name, "-")
        if not subset:
            print("  %-14s %5d %7s %10s" % (name, 0, pool_n, "-"))
            continue
        pos = sum(1 for r in subset if r["voted_up"])
        print("  %-14s %5d %7s %9d%%"
              % (name, len(subset), pool_n, round(100 * pos / len(subset))))
    print("  %-14s %5d" % ("TOTAL", len(reviews)))

    # sample vs Steam: this delta is what the methodology page publishes
    total_pos = summary.get("total_positive") or 0
    total_all = summary.get("total_reviews") or 0
    if total_all and reviews:
        steam_pct = round(100 * total_pos / total_all)
        ours_pct = round(100 * sum(1 for r in reviews if r["voted_up"]) / len(reviews))
        print("\n  positive rate : sample %d%%  vs  Steam overall %d%%  (delta %+d)"
              % (ours_pct, steam_pct, ours_pct - steam_pct))

    if reviews and "source_filters" in reviews[0]:
        counts = OrderedDict()
        for r in reviews:
            key = "+".join(r.get("source_filters") or ["?"])
            counts[key] = counts.get(key, 0) + 1
        print("  sources       : " + ", ".join("%s=%d" % kv for kv in counts.items()))
    if stats:
        print("  pages fetched : %s   (live requests: %s, pool: %s)"
              % (stats.get("pages_fetched"), stats.get("live_requests"), stats.get("pool_size")))

    n_hw = sum(1 for r in reviews if r["gpu"])
    n_ref = sum(1 for r in reviews if r["refunded"])
    n_ea = sum(1 for r in reviews if r["early_access"])
    print("\n  hardware data : %d/%d reviews" % (n_hw, len(reviews)))
    print("  refunded      : %d" % n_ref)
    print("  early access  : %d" % n_ea)

    # 1.1 DoD: refund cohort must be non-empty, or the sampling is still biased
    n_refund_bucket = sum(1 for r in reviews if r["bucket"] == "refund_window")
    if n_refund_bucket:
        print("\n  refund cohort : PASS (%d reviews)" % n_refund_bucket)
        return True
    print("\n  refund cohort : FAIL - zero refund-window reviews.")
    print("  Sampling is still biased. Raise --max-pages or check --filters.")
    return False


def sample_report(reviews, stats):
    """The distribution block, as data, for the output file + methodology page."""
    out = OrderedDict()
    for name, _, _ in BUCKETS:
        subset = [r for r in reviews if r["bucket"] == name]
        pos = sum(1 for r in subset if r["voted_up"])
        out[name] = {
            "kept": len(subset),
            "in_pool": stats.get("pool_by_bucket", {}).get(name, 0),
            "pct_positive": round(100 * pos / len(subset)) if subset else None,
        }
    return out


def print_pool(pool):
    """The block downstream is allowed to quote. Sample counts are not."""
    if not pool:
        return
    print("\n--- pool rates (pre-quota, pool_n=%s) - invariant 11 source of truth ---"
          % pool.get("pool_n"))
    for name, st in (pool.get("buckets") or {}).items():
        print("  %-14s pool_n=%-5d %5.1f%% of pool   %5.1f%% positive"
              % (name, st["pool_n"], st["share_of_pool_pct"] or 0, st["pct_positive"] or 0))
    if pool.get("steam_pct_positive") is not None:
        print("  %-14s pool_n=%-5s of %s on Steam, %.1f%% positive there"
              % ("steam overall", pool.get("pool_n"), pool["steam_total_reviews"],
                 pool["steam_pct_positive"]))


def restats_one(appid, args):
    """Recompute the pool block from cached pages only. Zero requests."""
    path = Path(args.out) / ("%s.json" % appid)
    blob = load_existing(path)
    if not blob:
        print("== %s - no %s to restat; run the fetch first ==" % (appid, path))
        return False

    params = blob.get("params") or {}
    filters = params.get("filters") or ["recent", "all"]
    print("== %s (%s) - recomputing pool rates from cache ==" % (appid, blob.get("game_name")))

    pool, summary = OrderedDict(), None
    for review_filter in filters:
        s, _, live = sweep(
            appid, review_filter, pool, quota=10 ** 9,
            max_pages=10 ** 6, min_pages=10 ** 6, sleep=0.0,
            use_cache=True, cache_only=True,
        )
        if live:  # cache_only should make this impossible
            raise RuntimeError("restats made %d live request(s)" % live)
        if summary is None:
            summary = s

    if not pool:
        print("   no cached pages found for %s" % appid)
        return False

    blob.pop("population", None)  # pre-rename key
    blob["pool"] = pool_stats(pool, summary or blob.get("query_summary") or {})
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")
    print_pool(blob["pool"])
    print("\nupdated pool block -> %s" % path)
    return True


def load_existing(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


# --------------------------------------------------------------------------

def run_one(appid, args):
    path = Path(args.out) / ("%s.json" % appid)

    if path.exists() and not args.force:
        blob = load_existing(path)
        if blob:
            print("== %s (%s) - cached, not refetching ==="
                  % (appid, blob.get("game_name") or "?"))
            print("   %s   (--force to refetch)" % path)
            return report(blob.get("reviews", []), blob.get("query_summary", {}),
                          {"pool_by_bucket": {k: v.get("in_pool") for k, v
                                              in (blob.get("sample_report") or {}).items()}})
        print("== %s - existing file unreadable, refetching ==" % appid)

    name = resolve_game_name(appid, use_cache=not args.no_cache)
    print("== %s (%s) ==" % (appid, name or "name lookup failed"))
    print("   target=%d quota=%s filters=%s max_pages=%d"
          % (args.target, args.quota or args.target // len(BUCKETS),
             ",".join(args.filters), args.max_pages))

    reviews, summary, stats = fetch_reviews(
        appid,
        target=args.target,
        filters=tuple(args.filters),
        quota=args.quota,
        max_pages=args.max_pages,
        min_pages=args.min_pages,
        sleep=args.sleep,
        use_cache=not args.no_cache,
    )
    if not reviews:
        print("nothing fetched - check the appid")
        return False

    ok = report(reviews, summary, stats)
    pool = stats.pop("pool", None)
    print_pool(pool)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "appid": appid,
        "game_name": name,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": stats,
        "pool": pool,
        "query_summary": summary,
        "sample_report": sample_report(reviews, stats),
        "reviews": reviews,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nwrote %d reviews -> %s" % (len(reviews), path))
    return ok


def main():
    ap = argparse.ArgumentParser(description="WorthIt.gg Steam review ingestion")
    ap.add_argument("appids", nargs="*", help="one or more Steam appids")
    ap.add_argument("--seeds", action="store_true", help="fetch the 5 eval seed games")
    ap.add_argument("--target", type=int, default=400, help="reviews kept per game")
    ap.add_argument("--quota", type=int, default=None,
                    help="per-bucket cap (default target/4)")
    ap.add_argument("--filters", default="recent,all",
                    help="comma-separated sweeps to merge (recent,updated,all)")
    ap.add_argument("--max-pages", type=int, default=12, help="page cap per filter")
    ap.add_argument("--min-pages", type=int, default=3,
                    help="pages fetched per filter even once quotas are met")
    ap.add_argument("--sleep", type=float, default=1.0, help="delay between live requests")
    ap.add_argument("--restats", action="store_true",
                    help="recompute the pool-rate block from cache only (no network)")
    ap.add_argument("--force", action="store_true", help="refetch even if output exists")
    ap.add_argument("--no-cache", action="store_true", help="ignore the raw page cache")
    ap.add_argument("--out", default=str(OUT_DIR), help="output dir (default data/raw)")
    args = ap.parse_args()

    appids = list(args.appids)
    if args.seeds:
        appids = SEED_GAMES + [a for a in appids if a not in SEED_GAMES]
    if not appids:
        ap.error("give at least one appid, or --seeds")

    args.filters = [f.strip() for f in args.filters.split(",") if f.strip()]
    valid = {"recent", "updated", "all"}
    bad = [f for f in args.filters if f not in valid]
    if bad:
        ap.error("unknown filter(s): %s" % ", ".join(bad))

    failures = []
    for i, appid in enumerate(appids):
        if i:
            print("")
        ok = restats_one(appid, args) if args.restats else run_one(appid, args)
        if not ok:
            failures.append(appid)

    if failures:
        print("\nFAILED (empty refund cohort or no data): %s" % ", ".join(failures))
        sys.exit(1)
    print("\nall %d game(s) OK" % len(appids))


if __name__ == "__main__":
    main()
