"""
WorthIt.gg - drop superseded artifacts from the `verdicts` branch.

WHY THIS EXISTS, AND WHY IT IS SMALL
------------------------------------
Correctness is already handled: select_publishable.py compares generated_at, so
a stale branch copy can never overwrite a newer one on main. This is about the
LOG. The nightly publish prints one SKIP line per superseded artifact - on
purpose, because a stale copy vanishing quietly is the failure that script
exists to make visible - and there are now ~133 of them. A hundred lines of
expected output is how a real warning gets missed.

So this is cosmetic. Nothing breaks if it is never run, and it is deliberately
NOT part of the nightly workflow: an unattended job that deletes files to tidy a
log is a bad trade in a project that has already been bitten twice by unattended
automation (the blind `git checkout verdicts --`, the silently no-op
`gh variable set`).

"OLDER THAN MAIN" IS NOT ENOUGH ON ITS OWN
------------------------------------------
site/app/verdict/[appid]/page.tsx tries the static file IN THE DEPLOYED BUILD
first and falls back to the branch only when that throws. So:

    publish commit lands on main  -> branch copy is instantly "older than main"
    Vercel build starts           -> the PREVIOUS build is still serving
                                  -> the new title 404s statically
                                  -> IT IS SERVED FROM THE BRANCH
    deploy goes live              -> static file exists, branch copy unused

A file becomes prunable-by-timestamp at the very moment it starts being
load-bearing. Hence the second term: the title must have been ON MAIN for longer
than GRACE_HOURS.

The clock is the title's FIRST appearance on main - see promoted_at(). Not
generated_at, which says when a verdict was made rather than when it was
promoted, and not the age of main's current bytes: the fallback fires on a
MISSING file, so a regeneration that replaces bytes already being served
statically cannot reopen the window.

NOTHING IS LOST. Deleting from the branch tip does not remove anything from
history; every artifact stays reachable with `git log`/`git show` on the branch.

Usage:
    .venv/bin/python pipeline/prune_verdicts.py                 # dry run
    .venv/bin/python pipeline/prune_verdicts.py --apply
    .venv/bin/python pipeline/prune_verdicts.py --grace-hours 72
"""

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import select_publishable as sp   # noqa: E402  (one definition of "superseded")

# How long main's copy must have been on main before its branch twin is
# droppable. A Vercel build is minutes; 48 hours is not a tuned number, it is
# deliberately far past the window so the deploy race cannot be reached by
# clock skew, a slow build, or a queued deployment.
GRACE_HOURS = 48

BRANCH = "origin/verdicts"


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)


def promoted_at(path, into_ref="HEAD"):
    """When this title FIRST appeared on main, or None if it never did.

    THE EARLIEST COMMIT, not the latest, and the difference is the whole
    predicate. The deploy race exists only while a title has NO file in the
    deployed build: page.tsx's load() falls back to the branch when
    loadVerdictStatic THROWS, which happens on a missing file. Stale bytes do
    not throw - they serve an older verdict until the next deploy - so once a
    title has been promoted and deployed even once, the static route never 404s
    again and the branch copy is never read, however many times it is later
    regenerated.

    The first implementation used `git log -1`, i.e. the age of main's CURRENT
    bytes. That protects a title whose verdict was rewritten this morning even
    though it has been served statically for a week, and on 2026-08-10 it
    protected all 133 - the header rollout had rewritten every one that day.
    Wrong clock, not a tighter one.

    `git log` prints newest first, so the earliest commit is the last line.
    """
    r = _git("log", "--format=%cI", into_ref, "--", path)
    dates = [d for d in r.stdout.split() if d]
    if r.returncode != 0 or not dates:
        return None
    return datetime.fromisoformat(dates[-1])


def prunable(from_ref=BRANCH, into_ref="HEAD", grace_hours=GRACE_HOURS,
             now=None):
    """(prune, keep) - every branch entry, with the reason it was decided.

    Selection reuses select_publishable.select() rather than reimplementing the
    comparison, so "superseded" has exactly one definition in this repo.
    """
    now = now or datetime.now(timezone.utc)
    take, skip = sp.select(from_ref, into_ref)
    prune, keep = [], []

    # Anything publishable is, by definition, the only good copy of that title:
    # either newer than main or absent from it. The branch is what serves it.
    for t in take:
        keep.append({**t, "keep_because": "publishable:%s" % t["why"]})

    for s in skip:
        if s["why"] != "older_than_main":
            # ties (identical, or divergent for a reason this cannot judge) and
            # unreadable files (possibly half-written by a run in flight). The
            # publisher refuses both; so does this.
            keep.append({**s, "keep_because": s["why"]})
            continue
        at = promoted_at(s["path"], into_ref)
        if at is None:
            keep.append({**s, "keep_because": "no_promotion_date_on_main"})
            continue
        age = (now - at).total_seconds() / 3600.0
        if age < grace_hours:
            keep.append({**s, "keep_because": "inside_deploy_window",
                         "age_hours": round(age, 1)})
        else:
            prune.append({**s, "age_hours": round(age, 1)})
    return prune, keep


def _refuse(msg):
    print("\nREFUSED: %s\n  Nothing was changed." % msg, file=sys.stderr)
    return 2


def apply_prune(prune, from_ref, message):
    """Delete the selected paths on the branch, in a throwaway worktree.

    A DETACHED WORKTREE FROM THE REMOTE REF, never a checkout of the local
    `verdicts` branch: that branch is stale on a dev machine (and on this one it
    is checked out in an abandoned worktree, which makes `git fetch
    origin verdicts:verdicts` fail outright). Building the commit from
    origin/verdicts means the local ref's state cannot matter.
    """
    with tempfile.TemporaryDirectory() as d:
        wt = Path(d) / "verdicts-wt"
        r = _git("worktree", "add", "--detach", str(wt), from_ref)
        if r.returncode != 0:
            return _refuse("could not create a worktree at %s:\n  %s"
                           % (wt, r.stderr.strip()))
        try:
            rm = _git("rm", "-q", "--", *[p["path"] for p in prune], cwd=str(wt))
            if rm.returncode != 0:
                return _refuse("git rm failed:\n  %s" % rm.stderr.strip())
            for k, v in (("user.name", "worthit-bot"), ("user.email", "bot@worthit.gg")):
                _git("config", k, v, cwd=str(wt))
            c = _git("commit", "-q", "-m", message, cwd=str(wt))
            if c.returncode != 0:
                return _refuse("commit failed:\n  %s" % c.stderr.strip())
            # NO FORCE, and no rebase-and-retry. If the remote moved, the set was
            # derived against a ref that no longer exists and the honest answer
            # is to re-derive it - the same lesson as the wholesale checkout.
            p = _git("push", "origin", "HEAD:verdicts", cwd=str(wt))
            if p.returncode != 0:
                return _refuse(
                    "push rejected - the branch moved while this ran (a live "
                    "generation, most likely).\n  %s\n  Re-run: the selection "
                    "must be derived against the current branch, not merged "
                    "into it." % p.stderr.strip())
            print(p.stderr.strip() or p.stdout.strip())
        finally:
            _git("worktree", "remove", "--force", str(wt))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Prune superseded verdict artifacts")
    ap.add_argument("--from", dest="from_ref", default=BRANCH)
    ap.add_argument("--into", dest="into_ref", default="HEAD")
    ap.add_argument("--grace-hours", type=float, default=GRACE_HOURS)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete and push (default is a dry run)")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--force-publishable-present", action="store_true",
                    help="prune even though the branch holds unpublished work")
    args = ap.parse_args()

    # The ref must be remote-tracking. A dev machine's local `verdicts` is
    # whatever it last fetched - here it is 2 files behind origin - and
    # select_publishable.py defaults to that name, which is the footgun this
    # tool must not inherit.
    full = _git("rev-parse", "--symbolic-full-name", args.from_ref).stdout.strip()
    if not full.startswith("refs/remotes/"):
        return _refuse("--from must be a remote-tracking ref (got %r -> %r). A "
                       "local branch may be stale, and pruning against a stale "
                       "view would delete files that are still the only copy."
                       % (args.from_ref, full or "unknown"))
    if not args.no_fetch:
        f = _git("fetch", "origin", "verdicts")
        if f.returncode != 0:
            return _refuse("fetch failed:\n  %s" % f.stderr.strip())

    prune, keep = prunable(args.from_ref, args.into_ref, args.grace_hours)
    pending = [k for k in keep if k["keep_because"].startswith("publishable")]

    for k in keep:
        print("  KEEP    %-9s %-22s branch=%s main=%s"
              % (k["appid"], k["keep_because"], k["incoming"] or "?",
                 k["current"] or "absent"))
    for p in prune:
        print("  prune   %-9s superseded %5.0fh ago  branch=%s main=%s"
              % (p["appid"], p["age_hours"], p["incoming"], p["current"]))

    print("\nprunable: %d    keeping: %d    (grace %.0fh)"
          % (len(prune), len(keep), args.grace_hours))
    if pending and not args.force_publishable_present:
        print("%d branch cop%s not yet published. Publish before tidying, or "
              "pass --force-publishable-present."
              % (len(pending), "y is" if len(pending) == 1 else "ies are"))
        if args.apply:
            return _refuse("unpublished work is on the branch")
    if not prune:
        print("nothing to do")
        return 0
    if not args.apply:
        print("dry run - nothing changed. Re-run with --apply to delete these.")
        return 0

    msg = ("prune: drop %d superseded verdict artifact(s)\n\n"
           "Every one of these is older than main's copy of the same title, and "
           "the title has been on main - and therefore in the deployed build - "
           "for more than %.0f hours, long past any window in which the branch "
           "was still serving it.\n\n"
           "Nothing is lost: this deletes from the branch tip only. Every "
           "artifact remains reachable in this branch's history.\n\n"
           "Selected by pipeline/prune_verdicts.py, which reuses "
           "select_publishable.select() so \"superseded\" has one definition."
           % (len(prune), args.grace_hours))
    return apply_prune(prune, args.from_ref, msg)


if __name__ == "__main__":
    sys.exit(main())
