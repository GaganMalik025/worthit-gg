"""
WorthIt.gg - the Phase 4 catalog manifest

Decides WHICH titles the overnight batch generates, and writes the decision to
data/catalog.json before a single Gemini call is made. The manifest is an
artifact, not a runtime choice: it is reviewable, diffable, and a resumed run
reads the same list it started with.

THE SELECTION RULE
------------------
Review count stays the primary signal - it is the best available proxy for what
people will actually search for, and a catalog that misses the games people look
up is a catalog that fails on contact with users.

But raw review rank over-represents live-service titles at exactly the top,
where the product thesis has least to say. Measured over 20 ingested titles
(2026-08-01), pool share landing in the veteran bucket:

    free-to-play              n=10    median 50.4%
    paid live-service         n=4     median 47.7%
    paid, not live-service    n=6     median 32.9%

When most of the pool is veteran, "different cohorts describe different
products" compresses toward one cohort describing the product. So live-service
titles are CAPPED, not excluded - they are searched, and "the veterans are the
game" is a true verdict worth publishing.

The cap is deliberately not a price check. See pipeline/data/live_service.txt:
free-to-play and paid-live-service are indistinguishable on the measurement,
and price alone would demote Team Fortress 2 (36.5% veteran) while keeping Rust
(57.5%). Classification is therefore free-to-play OR the audited list, and the
audited list carries the part price cannot see.

THE GATE THIS RULE DOES NOT REPLACE
-----------------------------------
Selection is a guess made before any data is fetched. The measured check lives
in run_batch.py, AFTER ingestion and BEFORE extraction - ingestion is Steam-only
and costs no Gemini quota, so a title whose real cohort structure turns out to
be degenerate can be dropped having spent nothing. This file decides what to
try; that gate decides what to pay for.

Usage:
    .venv/bin/python pipeline/build_catalog.py --dry-run
    .venv/bin/python pipeline/build_catalog.py --target 150 --cap 20
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_search_index as bsi  # noqa: E402  (one parser for store rows)

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data/catalog.json"
LIVE_SERVICE_PATH = Path(__file__).resolve().parent / "data/live_service.txt"
EXEMPT_PATH = Path(__file__).resolve().parent / "data/free_not_live_service.txt"
EXTRA_PATH = Path(__file__).resolve().parent / "data/extra_appids.txt"

TARGET = 150            # total catalog size, including what we already hold
LIVE_SERVICE_CAP = 20   # slots a live-service title may occupy
NIGHT_1 = 120           # titles attempted on night 1; the rest roll to night 2

# Reading free-to-play off a store row needs BOTH the rendered price text and
# the data-price-final attribute, because each one lies on its own:
#
#   Counter-Strike 2      data-price-final="137000"  text "Free"      -> free
#   Rainbow Six Siege     data-price-final="139900"  text "Free"      -> free
#     (the attribute carries a paid edition's price)
#   Horizon Zero Dawn     data-price-final="0"       text "₹2,999.00" -> PAID
#     (the attribute is 0 on a title that plainly costs money)
#   Call of Duty          data-price-final="0"       text ""          -> free
#
# So: the word "free" wins, then a rendered currency amount wins, and the
# attribute is consulted only when the cell renders nothing at all.
RE_PRICE_SEG = re.compile(r"search_price_discount_combined.*", re.S)
RE_PRICE_FINAL = re.compile(r'data-price-final="(-?\d+)"')
RE_TAG = re.compile(r"<[^>]+>")
RE_HAS_AMOUNT = re.compile(r"\d")


def parse_free_flags():
    """{appid: is_free} read from the SAME cached store pages as the index.

    Zero network requests. Returns free-to-play status only - not a judgment
    about live-service, which price cannot see (see the module docstring).
    """
    flags = {}
    for path in sorted(bsi.CACHE_DIR.glob("start_*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        html = blob.get("results_html") or ""
        for chunk in bsi.RE_ROW.split(html):
            if "search_result_row" not in chunk:
                continue
            key = bsi.RE_ITEMKEY.search(chunk)
            if not key:
                continue
            seg = RE_PRICE_SEG.search(chunk)
            raw = seg.group(0) if seg else ""
            # strip the attributes before reading the cell's rendered text, so
            # data-price-final's digits cannot be mistaken for a price amount
            text = RE_TAG.sub(" ", raw.split(">", 1)[1] if ">" in raw else "")
            final = RE_PRICE_FINAL.search(raw)
            if "free" in text.lower():
                is_free = True
            elif RE_HAS_AMOUNT.search(text):
                is_free = False
            else:
                is_free = bool(final and final.group(1) == "0")
            flags[int(key.group(1))] = is_free
    return flags


def read_appid_list(path):
    """appid -> comment, from a '<appid>  # note' file. Missing file is fine."""
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        appid, _, note = line.partition("#")
        appid = appid.strip()
        if appid.isdigit():
            out[int(appid)] = note.strip()
    return out


def existing_verdicts():
    """Everything we already hold, on main AND on the verdicts branch.

    The verdicts branch matters: a title generated live is published and served
    through the proxy, so regenerating it in the batch would spend quota to
    produce a file we already have.
    """
    have = {int(p.stem) for p in (ROOT / "site/public/verdicts").glob("*.json")}
    try:
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "origin/verdicts"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        for line in out.stdout.splitlines():
            m = re.search(r"verdicts/(\d+)\.json$", line)
            if m:
                have.add(int(m.group(1)))
    except Exception as exc:  # noqa: BLE001 - offline is not a failure here
        print("  note: could not read origin/verdicts (%s); using local only"
              % exc)
    return have


def select(entries, free, live_list, exempt, have, target, cap):
    """Walk the ranking, filling slots, capping live-service representation.

    The free-to-play flag is wrong in both directions and both corrections are
    audited files: live_list adds PAID live-service titles price cannot see,
    exempt removes FREE single-player titles price wrongly demotes.
    """
    chosen, skipped, n_live = [], [], 0
    for rank, (appid, title, reviews) in enumerate(entries, 1):
        if len(chosen) >= target:
            break
        if appid in have:
            continue
        is_free = bool(free.get(appid)) and appid not in exempt
        is_live = is_free or appid in live_list
        if appid in exempt:
            basis = "free, audited as single-player: %s" % exempt[appid]
        elif is_free:
            basis = "free-to-play"
        elif appid in live_list:
            basis = "audited: %s" % live_list[appid]
        else:
            basis = "priced, not on the live-service list"
        row = {
            "appid": appid,
            "title": title,
            "review_count": reviews,
            "rank": rank,
            "class": ("live_service" if is_live else "premium"),
            "basis": basis,
        }
        if is_live and n_live >= cap:
            row["skipped"] = "live_service_cap"
            skipped.append(row)
            continue
        if is_live:
            n_live += 1
        chosen.append(row)
    return chosen, skipped


def main():
    ap = argparse.ArgumentParser(description="Build the Phase 4 catalog manifest")
    ap.add_argument("--target", type=int, default=TARGET,
                    help="new titles to generate (default %d)" % TARGET)
    ap.add_argument("--cap", type=int, default=LIVE_SERVICE_CAP,
                    help="max live-service titles (default %d)" % LIVE_SERVICE_CAP)
    ap.add_argument("--night-1", type=int, default=NIGHT_1)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("reading the store cache (no network)...")
    by_id, pages, cached, stats = bsi.walk()
    bsi.merge_verdicts(by_id)
    entries, _, _ = bsi.build(by_id, bsi.MIN_REVIEWS, bsi.CORE_MIN)
    free = parse_free_flags()
    live_list = read_appid_list(LIVE_SERVICE_PATH)
    exempt = read_appid_list(EXEMPT_PATH)
    extra = read_appid_list(EXTRA_PATH)
    have = existing_verdicts()

    print("  %s ranked titles | %s free-to-play | %d on the audited "
          "live-service list | %d free titles exempted | %d already generated"
          % (f"{len(entries):,}", f"{sum(1 for v in free.values() if v):,}",
             len(live_list), len(exempt), len(have)))

    chosen, skipped = select(entries, free, live_list, exempt, have,
                             args.target, args.cap)

    # Delisted titles the store walk cannot see. merge_verdicts covers the ones
    # we already hold a verdict for; this covers the rest, and there is no
    # keyless way to discover them - hence an audited file.
    known = {r["appid"] for r in chosen}
    for appid, note in extra.items():
        if appid in known or appid in have:
            continue
        chosen.append({"appid": appid, "title": note or str(appid),
                       "review_count": None, "rank": None, "class": "premium",
                       "basis": "audited allowlist (absent from store search)"})

    for i, row in enumerate(chosen):
        row["night"] = 1 if i < args.night_1 else 2

    n_live = sum(1 for r in chosen if r["class"] == "live_service")
    deepest = max((r["rank"] or 0) for r in chosen)
    manifest = {
        "v": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": {
            "primary_sort": "steam review count, descending",
            "target": args.target,
            "live_service_cap": args.cap,
            "live_service_definition": "(free-to-play, detected from cached "
                                       "store rows, minus pipeline/data/"
                                       "free_not_live_service.txt) OR "
                                       "pipeline/data/live_service.txt",
            "why_not_price_alone": "measured 2026-08-01 over 20 ingested "
                                   "titles: free and paid-live-service have "
                                   "indistinguishable veteran shares (50.4% vs "
                                   "47.7% median) against 32.9% for paid "
                                   "non-live-service; price alone would demote "
                                   "Team Fortress 2 and keep Rust",
            "measured_gate": "run_batch.py drops a title after ingestion and "
                             "before extraction if its real cohort structure "
                             "is degenerate - ingestion costs no Gemini quota",
        },
        "counts": {
            "selected": len(chosen),
            "premium": len(chosen) - n_live,
            "live_service": n_live,
            "skipped_by_cap": len(skipped),
            "already_held": len(have),
            "deepest_rank_reached": deepest,
            "night_1": sum(1 for r in chosen if r["night"] == 1),
            "night_2": sum(1 for r in chosen if r["night"] == 2),
        },
        "already_held": sorted(have),
        "titles": chosen,
        "skipped_by_cap": skipped[:60],
    }

    print("\nselected %d titles: %d premium, %d live-service (cap %d)"
          % (len(chosen), len(chosen) - n_live, n_live, args.cap))
    print("  reaches rank %d of the ranking (raw top-%d would have been "
          "%d live-service)"
          % (deepest, args.target,
             sum(1 for a, _, _ in entries[:args.target]
                 if free.get(a) or a in live_list)))
    print("  %d live-service titles skipped by the cap" % len(skipped))
    print("  night 1: %d | night 2: %d"
          % (manifest["counts"]["night_1"], manifest["counts"]["night_2"]))

    if args.dry_run:
        print("\n(dry run - nothing written)")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print("\nwrote %s" % OUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
