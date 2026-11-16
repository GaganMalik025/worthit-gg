"""
WorthIt.gg - the home page's genre sections (owner, 2026-11-16).

Writes site/public/genres.json: which of the 12 home sections each published title
belongs to. The site reads it at build time, so no visitor's request ever reaches a
third party.

SOURCE. Steam's official genres are too coarse for this: Kenshi is "Action, Indie, RPG,
Simulation, Strategy". The sections are play styles players name themselves ("Story
Rich", "Souls-like", "Survival"), which are Steam USER TAGS. SteamSpy's public
appdetails endpoint returns those tags with their vote counts (no key, about 1 request
a second). Verified live 2026-11-16: 494 of 543 titles carry tags. The rest are mostly
very recent releases SteamSpy has not indexed (Silksong, Borderlands 4, ARC Raiders).

MEMBERSHIP RULE. A title is in a section when one of the section's tags is among the
title's TOP_N most-voted tags. Rank, not presence: almost every big game carries
dozens of tags with a few stray votes each, so presence would put Counter-Strike in
"Relaxing & cozy". A title can sit in several sections.

FALLBACK, for a title with no SteamSpy tags only: Steam's own appdetails genres and
categories, mapped where the match is unambiguous (RPG, Strategy, Free to Play, the
co-op categories). Anything else leaves the title in no section. It is still
searchable, and it gains sections when SteamSpy indexes it.

Usage:
    .venv/bin/python pipeline/build_genres.py             # fetch what is missing, write
    .venv/bin/python pipeline/build_genres.py --offline   # cache only, no network
Run after a batch, next to build_search_index.py, so new titles join their sections.
"""

import argparse
import glob
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "site/public/verdicts"
OUT = ROOT / "site/public/genres.json"
CACHE = ROOT / "data/cache/genres"
TOP_N = 10
UA = {"User-Agent": "catalog-genres/1.0"}

# (slug, display name, SteamSpy tags, Steam-genre/category fallback). Order is the
# order on the home page (owner, 2026-11-16).
SECTIONS = [
    ("story-driven", "Story-driven",
     ["Story Rich", "Choices Matter", "Narrative", "Multiple Endings",
      "Interactive Fiction", "Visual Novel"], []),
    ("open-world", "Open world", ["Open World"], []),
    ("co-op", "Play with friends (co-op)", ["Co-op", "Online Co-Op", "Local Co-Op"],
     ["Co-op", "Online Co-op", "LAN Co-op", "Shared/Split Screen Co-op"]),
    ("shooters", "Shooters",
     ["FPS", "Shooter", "Third-Person Shooter", "Looter Shooter", "Hero Shooter"], []),
    ("rpgs", "RPGs", ["RPG", "Action RPG", "JRPG", "CRPG", "Party-Based RPG"], ["RPG"]),
    ("survival-crafting", "Survival & crafting",
     ["Survival", "Open World Survival Craft", "Crafting"], []),
    ("strategy-management", "Strategy & management",
     ["Strategy", "Management", "RTS", "Grand Strategy", "Turn-Based Strategy",
      "City Builder", "4X", "Tactical"], ["Strategy"]),
    ("building-sandbox", "Building & sandbox", ["Building", "Base-Building", "Sandbox"], []),
    ("horror", "Horror", ["Horror", "Survival Horror", "Psychological Horror"], []),
    ("hard-soulslike", "Hard & Souls-like", ["Souls-like", "Difficult", "Soulslike"], []),
    ("relaxing-cozy", "Relaxing & cozy",
     ["Relaxing", "Cozy", "Casual", "Cute", "Wholesome", "Family Friendly"], []),
    ("free-to-play", "Free to play", ["Free to Play"], ["Free to Play"]),
]


def top_tags(tags, n=TOP_N):
    """The n most-voted tag names. Ties break by name so the result is stable."""
    if not isinstance(tags, dict):
        return []
    return [t for t, _ in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def classify(tags, fallback=()):
    """Section slugs for one title, in home-page order.

    `tags` is SteamSpy's {tag: votes}; `fallback` is Steam's genre and category
    descriptions, used ONLY when there are no tags at all.
    """
    if tags:
        top = set(top_tags(tags))
        return [slug for slug, _, wanted, _ in SECTIONS if top & set(wanted)]
    have = set(fallback or ())
    return [slug for slug, _, _, fb in SECTIONS if fb and have & set(fb)]


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def steamspy(appid, offline):
    path = CACHE / "steamspy" / ("%s.json" % appid)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if offline:
        return None
    d = _get("https://steamspy.com/api.php?request=appdetails&appid=%s" % appid)
    out = {"name": d.get("name"),
           "tags": d.get("tags") if isinstance(d.get("tags"), dict) else {},
           "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    time.sleep(1.1)
    return out


def steam_fallback(appid, offline):
    path = CACHE / "steam" / ("%s.json" % appid)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if offline:
        return None
    d = _get("https://store.steampowered.com/api/appdetails?appids=%s"
             "&filters=genres,categories" % appid)
    data = (d.get(str(appid)) or {}).get("data") or {}
    out = [g["description"] for g in data.get("genres") or []] + \
          [c["description"] for c in data.get("categories") or []]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    time.sleep(1.5)
    return out


def build(appids, offline=False):
    members, untagged, fell_back = {}, [], []
    for appid in appids:
        spy = steamspy(appid, offline) or {}
        tags = spy.get("tags") or {}
        fb = [] if tags else (steam_fallback(appid, offline) or [])
        slugs = classify(tags, fb)
        if not tags:
            (fell_back if slugs else untagged).append(appid)
        if slugs:
            members[str(appid)] = slugs
    return {
        "v": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "SteamSpy user tags (top %d by votes); Steam appdetails genres and "
                  "categories for titles SteamSpy has no tags for" % TOP_N,
        "sections": [{"slug": s, "name": n} for s, n, _, _ in SECTIONS],
        "members": members,
        "fell_back": sorted(fell_back),
        "in_no_section": sorted(untagged + [a for a in appids
                                            if str(a) not in members and a not in untagged]),
    }


def main():
    ap = argparse.ArgumentParser(description="Home page genre sections")
    ap.add_argument("--offline", action="store_true", help="cache only, no network")
    args = ap.parse_args()
    appids = sorted({int(json.loads(Path(p).read_text(encoding="utf-8"))["appid"])
                     for p in glob.glob(str(VERDICTS / "*.json"))})
    out = build(appids, offline=args.offline)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    counts = {s["slug"]: 0 for s in out["sections"]}
    for slugs in out["members"].values():
        for s in slugs:
            counts[s] += 1
    print("titles %d | in a section %d | via Steam fallback %d | in no section %d"
          % (len(appids), len(out["members"]), len(out["fell_back"]),
             len(out["in_no_section"])))
    for s in out["sections"]:
        print("  %-22s %4d" % (s["slug"], counts[s["slug"]]))
    print("wrote %s" % OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
