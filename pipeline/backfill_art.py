"""Add the `art` block to verdicts that were published before it existed.

Costs ZERO Gemini quota: this reads Steam's appdetails and (only where Steam has
no reachable portrait) SteamGridDB. Neither is metered against the daily budget
that pipeline/live_quota.py guards.

    .venv/bin/python pipeline/backfill_art.py --broken --dry-run
    .venv/bin/python pipeline/backfill_art.py --broken
    .venv/bin/python pipeline/backfill_art.py --all

--broken is the 13 titles measured on 2026-08-13 as having no working art on
the legacy CDN path: 12 that 404 on both stages and one (Battlefield 6) that
returns HTTP 200 with a 1,655-byte blank placeholder. --all re-resolves every
published verdict, which is the right call only if the legacy pattern starts
failing more widely.

One request at a time, on purpose. The whole job is a few dozen calls against
two free endpoints; there is nothing to gain from concurrency and a rate limit
SteamGridDB does not publish to lose.
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import art as art_mod                                  # noqa: E402
import fetch_reviews                                   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "site/public/verdicts"

# Measured 2026-08-13 over the full 411-title manifest. The first four are
# published; the rest are in the manifest and would break as they publish.
BROKEN = [3527290, 3354750, 3764200, 2623190, 2807960,
          4704690, 2483190, 3949040, 3513350, 3405690,
          1374490, 4128580, 3124540]

PAUSE = 1.0


def targets(args):
    published = sorted(int(p.stem) for p in VERDICTS.glob("*.json"))
    if args.all:
        return published
    if args.appid:
        return list(args.appid)
    return [a for a in BROKEN if a in published]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--broken", action="store_true",
                   help="the measured no-working-art list (default)")
    g.add_argument("--all", action="store_true",
                   help="every published verdict")
    g.add_argument("--appid", type=int, nargs="+", help="explicit appids")
    ap.add_argument("--no-sgdb", action="store_true",
                    help="Steam art only; skip the SteamGridDB tier")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ids = targets(args)
    print("backfilling art for %d verdict(s)%s\n"
          % (len(ids), " (dry run)" if args.dry_run else ""))

    changed = unchanged = failed = 0
    for appid in ids:
        path = VERDICTS / ("%d.json" % appid)
        if not path.exists():
            print("  [skip] %-9d no verdict on disk" % appid)
            continue
        verdict = json.loads(path.read_text(encoding="utf-8"))

        # Refresh the cached appdetails so a name-only entry written before art
        # capture cannot deny this title its tier 1.
        fetch_reviews.resolve_game_name(appid, use_cache=True)
        block = art_mod.art_block(appid, allow_sgdb=not args.no_sgdb)

        tiers = []
        if block.get("header_image"):
            tiers.append("steam")
        if block.get("grid"):
            tiers.append("sgdb")
        label = "+".join(tiers) or "NONE (falls back to legacy pattern)"

        if not block:
            failed += 1
        elif verdict.get("art") == block:
            unchanged += 1
        else:
            changed += 1
            if not args.dry_run:
                verdict["art"] = block
                path.write_text(json.dumps(verdict, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print("  [%-4s] %-9d %-34s %s"
              % ("dry" if args.dry_run else "ok", appid,
                 (verdict.get("game_name") or "?")[:32], label))
        time.sleep(PAUSE)

    print("\n%d changed, %d already current, %d with no art from any tier"
          % (changed, unchanged, failed))
    if args.dry_run:
        print("(dry run - nothing written)")


if __name__ == "__main__":
    main()
