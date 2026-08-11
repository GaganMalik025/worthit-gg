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

WHERE IT READS THE BRANCH FROM
------------------------------
`origin/verdicts`, fetched by this script before it decides anything. Both
halves matter. It used to default to `verdicts` - the LOCAL branch, i.e.
whatever that machine last fetched - and on a dev machine that ref sat two files
behind origin and could not be refreshed at all, because an abandoned worktree
had the branch checked out and `git fetch origin verdicts:verdicts` refused. The
run reported a publish decision derived from a stale view and looked exactly
like a correct one. A remote-tracking default alone would not have fixed that:
origin/verdicts is only as current as the last fetch.

AND IT REFUSES RATHER THAN REPORTING ZERO
-----------------------------------------
A missing or unreadable ref used to return ([], []), which is indistinguishable
from "nothing to publish" - `--from no-such-ref` printed `publishable: 0
skipped: 0` and exited 0. The nightly workflow ran the fetch as
`git fetch origin verdicts:verdicts || echo "no verdicts branch yet"`, so a
fetch failure was swallowed and the publish promoted nothing while reporting
success. That is the `gh variable set` shape: the signal that the guard is
broken looks identical to the guard working. Now a fetch failure and an
unreadable ref are hard errors, and only a genuinely absent branch - confirmed
by a fetch that SUCCEEDED - is a quiet, explicit exit 0.

Usage:
    .venv/bin/python pipeline/select_publishable.py                 # report
    .venv/bin/python pipeline/select_publishable.py --apply         # write them
    .venv/bin/python pipeline/select_publishable.py --from REF --into REF
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

VERDICT_DIR = "site/public/verdicts"
DEFAULT_FROM = "origin/verdicts"


class RefProblem(RuntimeError):
    """The branch could not be read. NOT the same as having nothing to publish."""


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


def ref_exists(ref):
    return _git("rev-parse", "--verify", "--quiet", "%s^{commit}" % ref).returncode == 0


def select(from_ref=DEFAULT_FROM, into_ref="HEAD"):
    """(take, skip) - lists of dicts describing each decision.

    Raises RefProblem when the branch cannot be read. It used to return ([], [])
    there, which the caller could not tell apart from an empty branch - and the
    nightly publish read that as "nothing to do" and reported success.
    """
    if not ref_exists(from_ref):
        raise RefProblem("%s does not exist" % from_ref)
    listing = _git("ls-tree", "-r", "--name-only", from_ref, VERDICT_DIR + "/")
    if listing.returncode != 0:
        raise RefProblem("could not read %s:%s/ - %s"
                         % (from_ref, VERDICT_DIR, listing.stderr.strip()))
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


def _refuse(msg):
    print("\nREFUSED: %s\n  Nothing was selected." % msg, file=sys.stderr)
    return 2


def main():
    ap = argparse.ArgumentParser(description="Which verdicts may be published")
    ap.add_argument("--from", dest="from_ref", default=DEFAULT_FROM)
    ap.add_argument("--into", dest="into_ref", default="HEAD")
    ap.add_argument("--apply", action="store_true",
                    help="write the publishable files into the working tree")
    ap.add_argument("--no-fetch", action="store_true",
                    help="trust the ref as it stands (CI already fetched)")
    ap.add_argument("--allow-local-ref", action="store_true",
                    help="permit a non-remote --from, accepting that it may be stale")
    ap.add_argument("--github-output", default=None)
    args = ap.parse_args()

    # Remoteness is decided by NAME AGAINST THE CONFIGURED REMOTES, not by
    # whether the ref resolves. `origin/verdicts` on a machine that has never
    # fetched it resolves to nothing, and reading that as "local" refused the
    # very default this change installs - which is how the legitimate
    # no-branch-yet case first came out as a refusal.
    full = _git("rev-parse", "--symbolic-full-name", args.from_ref).stdout.strip()
    remotes = set(_git("remote").stdout.split())
    head, _, rest = args.from_ref.partition("/")
    is_remote = full.startswith("refs/remotes/") or bool(rest and head in remotes)
    if not is_remote and not args.allow_local_ref:
        return _refuse(
            "--from %r resolves to %r, which is not a remote-tracking ref.\n"
            "  A local branch is whatever this machine last fetched, and a "
            "publish decision\n  derived from a stale view looks exactly like a "
            "correct one. Use %s,\n  or pass --allow-local-ref if you really "
            "mean this ref." % (args.from_ref, full or "nothing", DEFAULT_FROM))
    if not is_remote:
        print("  ! --from %s is a local ref; it may be behind origin" % args.from_ref)

    fetched = False
    if is_remote and not args.no_fetch:
        remote, _, branch = args.from_ref.partition("/")
        # ASK THE REMOTE FIRST, because `git fetch origin verdicts` fails when
        # the branch does not exist there - and "no branch yet" is a legitimate
        # state, not an error. Probing separates the two; fetching alone cannot,
        # which is how the first version of this made the legitimate case
        # unreachable.
        probe = _git("ls-remote", "--exit-code", "--heads", remote, branch)
        if probe.returncode == 2:
            print("no %s branch on %s yet - nothing to publish" % (branch, remote))
            if args.github_output:
                with open(args.github_output, "a", encoding="utf-8") as fh:
                    fh.write("n=0\nskipped=0\n")
            return 0
        if probe.returncode != 0:
            return _refuse("could not reach %s to check for %s:\n  %s"
                           % (remote, branch, probe.stderr.strip()))
        f = _git("fetch", remote, branch)
        if f.returncode != 0:
            # NEVER fall through to an empty selection here. This is the exact
            # step the workflow used to run as `... || echo`, which turned a
            # fetch failure into a successful publish of nothing.
            return _refuse("could not fetch %s from %s:\n  %s"
                           % (branch, remote, f.stderr.strip()))
        fetched = True

    try:
        take, skip = select(args.from_ref, args.into_ref)
    except RefProblem as exc:
        if fetched and not ref_exists(args.from_ref):
            # Fetched successfully and the ref still is not here: the remote had
            # the branch a moment ago and does not now. Rare, but legitimate and
            # said out loud rather than rendered as a zero.
            print("%s vanished between the probe and the fetch - nothing to "
                  "publish" % args.from_ref)
            if args.github_output:
                with open(args.github_output, "a", encoding="utf-8") as fh:
                    fh.write("n=0\nskipped=0\n")
            return 0
        return _refuse(str(exc))

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
