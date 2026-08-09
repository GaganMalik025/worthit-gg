"""
WorthIt.gg - decide which verdicts on the `verdicts` branch may replace main's.

WHY THIS EXISTS
---------------
publish-verdicts.yml used to run:

    git checkout verdicts -- site/public/verdicts/

which is not a merge at all - it is a wholesale overwrite of main's copy with
whatever the branch happens to hold. Git reports no conflict, because nothing is
being merged, so the failure is completely silent.

On 2026-08-08 that replayed 68 verdicts generated 1-7 days earlier over 56 files
regenerated the same day, and reported "Automatic merge went well". The whole
day's work would have been gone with no warning in the log.

The `verdicts` branch is artifact storage that accumulates and is never pruned,
so it will always hold copies older than main. Age is therefore the thing to
check, not presence.

THE RULE
--------
A file on `verdicts` replaces main's copy only when it is strictly NEWER by
generated_at. Everything else is skipped and SAID SO in the log - the point is
that a mismatch is visible, not that it is quietly dropped.

Ties lose. If the timestamps are equal the content is either identical (nothing
to do) or divergent for a reason this script cannot judge, and the conservative
answer is to leave main alone and let a human look.

Usage:
    .venv/bin/python pipeline/select_publishable.py                 # report
    .venv/bin/python pipeline/select_publishable.py --apply         # write them
    .venv/bin/python pipeline/select_publishable.py --from BRANCH --into REF
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

VERDICT_DIR = "site/public/verdicts"


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _read(ref, path):
    """File content at a ref, or None if it does not exist there."""
    r = _git("show", "%s:%s" % (ref, path))
    return r.stdout if r.returncode == 0 else None


def _stamp(raw, path):
    """generated_at, or None if unreadable. Unreadable is not publishable."""
    if raw is None:
        return None
    try:
        return json.loads(raw).get("generated_at")
    except ValueError:
        print("  ! %s is not valid JSON; treating as unpublishable" % path)
        return None


def select(from_ref="verdicts", into_ref="HEAD"):
    """(take, skip) - lists of dicts describing each decision."""
    listing = _git("ls-tree", "-r", "--name-only", from_ref, VERDICT_DIR + "/")
    if listing.returncode != 0:
        return [], []
    take, skip = [], []
    for path in sorted(p for p in listing.stdout.split() if p.endswith(".json")):
        appid = Path(path).stem
        incoming_raw = _read(from_ref, path)
        current_raw = _read(into_ref, path)
        incoming = _stamp(incoming_raw, path)
        current = _stamp(current_raw, path)

        if incoming is None:
            skip.append({"appid": appid, "path": path, "why": "unreadable_on_branch",
                         "incoming": None, "current": current})
        elif current is None:
            take.append({"appid": appid, "path": path, "why": "new_title",
                         "incoming": incoming, "current": None, "raw": incoming_raw})
        elif incoming > current:
            take.append({"appid": appid, "path": path, "why": "newer",
                         "incoming": incoming, "current": current, "raw": incoming_raw})
        else:
            skip.append({"appid": appid, "path": path,
                         "why": "older_than_main" if incoming < current else "same_timestamp",
                         "incoming": incoming, "current": current})
    return take, skip


def main():
    ap = argparse.ArgumentParser(description="Which verdicts may be published")
    ap.add_argument("--from", dest="from_ref", default="verdicts")
    ap.add_argument("--into", dest="into_ref", default="HEAD")
    ap.add_argument("--apply", action="store_true",
                    help="write the publishable files into the working tree")
    ap.add_argument("--github-output", default=None)
    args = ap.parse_args()

    take, skip = select(args.from_ref, args.into_ref)

    for t in take:
        print("  publish %-9s %s  (%s -> %s)"
              % (t["appid"], t["why"], t["current"] or "absent", t["incoming"]))
    # Skips are the whole point of this script, so they are never summarised
    # away: a stale branch copy silently vanishing is the failure mode it exists
    # to make visible.
    for s in skip:
        print("  SKIP    %-9s %-16s branch=%s main=%s"
              % (s["appid"], s["why"], s["incoming"] or "?", s["current"] or "?"))

    print("\npublishable: %d    skipped: %d" % (len(take), len(skip)))
    stale = [s for s in skip if s["why"] == "older_than_main"]
    if stale:
        print("%d branch cop%s older than main and %s NOT published. The "
              "verdicts branch is append-only artifact storage, so this is "
              "expected, not an error."
              % (len(stale), "y is" if len(stale) == 1 else "ies are",
                 "was" if len(stale) == 1 else "were"))

    if args.apply:
        for t in take:
            p = Path(t["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(t["raw"], encoding="utf-8")
        print("wrote %d file(s) into the working tree" % len(take))

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write("n=%d\n" % len(take))
            fh.write("skipped=%d\n" % len(skip))
    return 0


if __name__ == "__main__":
    sys.exit(main())
