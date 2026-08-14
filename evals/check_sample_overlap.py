"""Audit-sample self-checks: distinctness within a round, independence across.

Was an ad-hoc one-liner until 2026-08-14, when it under-reported a round's id
count and the discrepancy - not the underlying defect - is what surfaced the
real duplicate. A check used to decide whether sampling is sound has to be as
trustworthy as the thing it checks, so it lives here and is re-runnable.

    .venv/bin/python evals/check_sample_overlap.py evals/audit-4.4-*.md

Exits non-zero if any round repeats a review or two rounds share one.
"""
import pathlib
import re
import sys

# Parse by POSITION IN THE LINE, never by how many digits an id has. The old
# pattern was \d{6,}, which silently dropped appid 3590 (Trove) - Steam appids
# run from 3 digits up, so any width-based rule is wrong for some real title.
RE_VERDICT = re.compile(r"^- \[[ x]\] \*\*(.+?)\*\* \(`(\d+)`", re.M)
RE_CITATION = re.compile(r"^\s*\d+\. \[[ x]\] (.+?) / (\w+) / `(\d+)`", re.M)


def parse(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    return (
        [(m.group(2), m.group(1)) for m in RE_VERDICT.finditer(text)],
        [(m.group(3), m.group(1), m.group(2)) for m in RE_CITATION.finditer(text)],
    )


def main(paths):
    if not paths:
        sys.exit("usage: check_sample_overlap.py <audit .md> [...]")
    rounds, problems = {}, []
    for p in sorted(paths):
        verdicts, citations = parse(p)
        rids = [c[0] for c in citations]
        rounds[p] = set(rids)
        dupes = sorted({r for r in rids if rids.count(r) > 1})
        print(f"{pathlib.Path(p).name}")
        print(f"   verdicts  : {len(verdicts):>3} listed, {len({v[0] for v in verdicts}):>3} unique")
        print(f"   citations : {len(rids):>3} listed, {len(set(rids)):>3} unique")
        if not verdicts or not rids:
            problems.append(f"{p}: parsed 0 rows - the file format changed and "
                            f"this check is now blind")
        if dupes:
            problems.append(f"{p}: repeats {', '.join(dupes)} - the round audits "
                            f"fewer distinct reviews than it presents slots")
    names = sorted(rounds)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = rounds[a] & rounds[b]
            tag = "ok" if not shared else f"SHARED {len(shared)}: {sorted(shared)}"
            print(f"overlap {pathlib.Path(a).stem[-5:]} x {pathlib.Path(b).stem[-5:]}: {tag}")
            if shared:
                problems.append(f"{a} and {b} share {len(shared)} review(s)")

    if problems:
        print("\nPROBLEMS (%d):" % len(problems))
        for p in problems:
            print("  ! %s" % p)
        return 1
    print("\nall rounds: distinct within, independent across")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
