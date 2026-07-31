"""
WorthIt.gg - static search index for the home typeahead

Builds the list of Steam titles the search box can offer. Decoupled from
site/public/verdicts/: the index covers the whole store above a review floor, while
verdicts cover only what we have generated. A title in the index without a
verdict is a cache miss, which is a valid destination (live generation or the
request queue), not an error.

WHY NOT ISteamApps/GetAppList
-----------------------------
It no longer exists. Verified 2026-07-31:

    ISteamApps/GetAppList/v2|v1|v0002  -> 404 "Method 'GetAppList' not found"
    IStoreService/GetAppList/v1        -> 403 (needs a Steam Web API key)
    GetSupportedAPIList                -> ISteamApps exposes only GetSDRConfig,
                                          GetServersAtAddress, UpToDateCheck

The keyless store search replaces it and is strictly better here, because each
result row already carries its review count in a tooltip. Reading counts off the
search page costs ~690 requests; probing appreviews per title costs one request
each - measured at 1.6 req/s, that is ~29 hours for the catalog. Same data,
three orders of magnitude cheaper.

sort_by=Reviews_DESC sorts by review SCORE, not count, so it cannot be used to
stop early - the walk has to cover every page. It is still the right sort: it
narrows the base to games carrying a review score at all (~68.5k) rather than
every store entry (~167k).

SHAPE
-----
Two shards, so the box is usable before the whole catalog has downloaded:

    site/public/search-index-core.json   >= CORE_MIN reviews  (fetched on focus)
    site/public/search-index-tail.json   floor .. CORE_MIN-1  (fetched right after)

Capsule URLs are DERIVED from appid at render time, never stored - storing them
costs ~105 bytes per entry and buys nothing. Entries are sorted by review count
descending, so array position is popularity rank: ranking for free, no stored
score.

Usage:
    .venv/bin/python pipeline/build_search_index.py --dry-run --limit 5
    .venv/bin/python pipeline/build_search_index.py
"""

import argparse
import gzip
import html as html_mod
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_reviews import _get_with_backoff  # noqa: E402  (shared 429 discipline)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data/cache/searchindex"
CORE_PATH = ROOT / "site/public/search-index-core.json"
TAIL_PATH = ROOT / "site/public/search-index-tail.json"

SEARCH_URL = ("https://store.steampowered.com/search/results/"
              "?query&start=%d&count=100&dynamic_data=&sort_by=Reviews_DESC"
              "&infinite=1&category1=998")
CAPSULE = "https://cdn.cloudflare.steamstatic.com/steam/apps/%d/capsule_231x87.jpg"

MIN_REVIEWS = 70            # the floor for appearing in search at all
CORE_MIN = 1000             # core/tail shard boundary
PAGE = 100
PACE_SECONDS = 0.6

SEED_APPIDS = [233860, 553850, 1091500, 413150, 1190460]

RE_APPID = re.compile(r'data-ds-appid="(\d+)"')
RE_TITLE = re.compile(r'<span class="title">([^<]*)</span>')
RE_TIP = re.compile(r'data-tooltip-html="([^"]*)"')
RE_COUNT = re.compile(r'([\d,]+)\s+user reviews')


def parse_page(blob):
    """(appid, title, review_count) per row, skipping rows with no count.

    Steam emits appids, titles and tooltips as three parallel runs in the same
    order. A row with no review tooltip (unreleased, or too few reviews to have
    a score) has no count and is dropped - it cannot clear the floor anyway.
    """
    h = blob.get("results_html") or ""
    ids = RE_APPID.findall(h)
    titles = [html_mod.unescape(t).strip() for t in RE_TITLE.findall(h)]
    tips = RE_TIP.findall(h)
    rows = []
    for i, tip in enumerate(tips):
        if i >= len(ids) or i >= len(titles):
            break
        m = RE_COUNT.search(html_mod.unescape(tip))
        if not m:
            continue
        title = titles[i]
        if not title:
            continue
        rows.append((int(ids[i]), title, int(m.group(1).replace(",", ""))))
    return rows, blob.get("total_count") or 0


def fetch_page(start, force=False):
    cpath = CACHE_DIR / ("start_%06d.json" % start)
    if cpath.exists() and not force:
        return json.loads(cpath.read_text(encoding="utf-8")), True
    resp = _get_with_backoff(SEARCH_URL % start, None)
    blob = resp.json()
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps(blob), encoding="utf-8")
    time.sleep(PACE_SECONDS)
    return blob, False


def walk(limit=0, force=False):
    """Every page of the catalog. Stops when a page returns no rows."""
    by_id, start, total, pages, cached = {}, 0, None, 0, 0
    while True:
        blob, was_cached = fetch_page(start, force)
        rows, tc = parse_page(blob)
        if total is None and tc:
            total = tc
            print("catalog reports %s scored games (~%d pages)"
                  % (f"{total:,}", -(-total // PAGE)))
        pages += 1
        cached += 1 if was_cached else 0
        if not rows and not RE_APPID.search(blob.get("results_html") or ""):
            break
        for appid, title, n in rows:
            prev = by_id.get(appid)
            if prev is None or n > prev[1]:
                by_id[appid] = (title, n)
        if pages % 25 == 0 or start == 0:
            print("  page %-4d start=%-6d unique=%-6s kept>=%d=%s"
                  % (pages, start, f"{len(by_id):,}", MIN_REVIEWS,
                     f"{sum(1 for _, n in by_id.values() if n >= MIN_REVIEWS):,}"))
        start += PAGE
        if limit and pages >= limit:
            break
        if total and start >= total:
            break
    return by_id, pages, cached


def merge_verdicts(by_id, verdicts_dir=None):
    """Force every title we hold a verdict for into the index.

    The store walk does NOT cover everything we can have a verdict for.
    Death Stranding (1190460) is the proof: 79,157 reviews, live store page,
    type "game" - and absent from all 686 pages, because the base game is
    delisted in favour of the Director's Cut and delisted titles do not appear
    in store search. Its reviews are still there, and we already hold a verdict
    for it.

    A verdict a user cannot search for is a verdict we paid to generate and then
    hid, so the union is not a nicety - it is the difference between the search
    box covering our catalog and merely covering Steam's storefront. Ranking uses
    the verdict's own steam_total_reviews, already carried in the footer.
    """
    d = Path(verdicts_dir or (ROOT / "site/public/verdicts"))
    added = []
    for p in sorted(d.glob("*.json")):
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        appid = int(v.get("appid") or p.stem)
        if appid in by_id:
            continue
        name = (v.get("game_name") or "").strip()
        if not name:
            continue
        n = int((v.get("footer") or {}).get("steam_total_reviews") or 0)
        by_id[appid] = (name, n)
        added.append((appid, name, n))
    return added


def build(by_id, min_reviews, core_min):
    entries = sorted(((a, t, n) for a, (t, n) in by_id.items() if n >= min_reviews),
                     key=lambda r: (-r[2], r[0]))
    core = [(a, t) for a, t, n in entries if n >= core_min]
    tail = [(a, t) for a, t, n in entries if n < core_min]
    return entries, core, tail


def payload(rows, min_reviews, max_reviews=None):
    return {
        "v": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "store.steampowered.com/search (keyless); counts read from "
                  "each row's review tooltip",
        "min_reviews": min_reviews,
        "max_reviews": max_reviews,
        "capsule_url": CAPSULE.replace("%d", "{appid}"),
        "order": "review count descending; array position is popularity rank",
        "n": len(rows),
        "t": [[a, t] for a, t in rows],
    }


def verify(entries, core, tail, min_reviews, core_min):
    problems = []
    ids = [a for a, _, _ in entries]
    if len(set(ids)) != len(ids):
        problems.append("duplicate appids in the index")
    if any(n < min_reviews for _, _, n in entries):
        problems.append("an entry is below the %d-review floor" % min_reviews)
    counts = [n for _, _, n in entries]
    if counts != sorted(counts, reverse=True):
        problems.append("entries are not sorted by review count descending")
    if len(core) + len(tail) != len(entries):
        problems.append("shards do not partition the index")
    if any(n < core_min for _, _, n in entries[:len(core)]):
        problems.append("a core entry is below the core boundary")
    present = set(ids)
    missing = [a for a in SEED_APPIDS if a not in present]
    if missing:
        problems.append("seed appids missing from the index: %s" % missing)
    return problems


def main():
    ap = argparse.ArgumentParser(description="Build the static search index")
    ap.add_argument("--min-reviews", type=int, default=MIN_REVIEWS)
    ap.add_argument("--core-min", type=int, default=CORE_MIN)
    ap.add_argument("--limit", type=int, default=0, help="stop after N pages")
    ap.add_argument("--force", action="store_true", help="ignore the page cache")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    args = ap.parse_args()

    t0 = time.time()
    print("walking the Steam catalog (keyless store search, %d/page)..." % PAGE)
    by_id, pages, cached = walk(args.limit, args.force)
    added = merge_verdicts(by_id)
    for appid, name, n in added:
        print("  + %s (%d) not in store search - added from site/public/verdicts/ "
              "(%s reviews)" % (name, appid, f"{n:,}"))
    entries, core, tail = build(by_id, args.min_reviews, args.core_min)
    dt = time.time() - t0

    print("\n%d pages (%d from cache) in %.1f min" % (pages, cached, dt / 60))
    print("%s unique games seen, %s clear the %d-review floor"
          % (f"{len(by_id):,}", f"{len(entries):,}", args.min_reviews))
    print("  core (>=%s reviews): %s" % (f"{args.core_min:,}", f"{len(core):,}"))
    print("  tail (%d-%s)       : %s"
          % (args.min_reviews, f"{args.core_min - 1:,}", f"{len(tail):,}"))

    problems = verify(entries, core, tail, args.min_reviews, args.core_min)
    if problems:
        print("\nINTEGRITY FAILURES (%d):" % len(problems))
        for p in problems:
            print("  ! %s" % p)
        if not args.limit:
            print("\nnothing written")
            sys.exit(1)
        print("  (--limit run: partial walk, failures expected)")
    else:
        print("\nintegrity: ids unique, all >= floor, sorted by count desc, "
              "shards partition, all 5 seed appids present")

    if args.dry_run:
        print("\nsample rows: %s" % [(a, t) for a, t in core[:3]])
        print("capsule for %d -> %s" % (core[0][0], CAPSULE % core[0][0]))
        print("(dry run - nothing written)")
        return

    for path, rows, lo, hi in ((CORE_PATH, core, args.core_min, None),
                               (TAIL_PATH, tail, args.min_reviews,
                                args.core_min - 1)):
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload(rows, lo, hi), separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
        path.write_bytes(blob)
        print("wrote %-34s %s rows  %6.0f KB raw  %6.0f KB gzipped"
              % (path.relative_to(ROOT), f"{len(rows):,}", len(blob) / 1024,
                 len(gzip.compress(blob, 9)) / 1024))


if __name__ == "__main__":
    main()
