"""Break-then-confirm for the pacer cross-process test's DIAGNOSIS quality.

    .venv/bin/python evals/mutate_pacer_diagnosis.py

Run from the repo root. Logs kept in evals/mutation-logs/ (prefix `p`).

This one is unusual and the shape is the point. The 2026-08-12 BACKLOG entry
did not say `test_pacer_ceiling_across_processes` could pass while broken - it
said the opposite: it "already cannot pass silently", because a dead child
makes json.loads raise. The defect was that the failure NAMES THE WRONG THING.
So "caught" is not the bar here; both mutations below turn the suite red. The
bar is WHICH failure the runner reads, and that is what these two logs compare:

  p01  child dies, current (fixed) test   -> a named check: rc=3, stderr shown
  p02  child dies, PRE-FIX diagnosis      -> JSONDecodeError traceback, and the
                                             run aborts before any check reports

p02 restores the original three lines verbatim alongside the same dying child,
so the pair differs in exactly one thing: whether the exit codes are collected
before the parse. Without p02 the campaign would only show that the new checks
fire, not that they are an improvement on what was there.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
LOGS.mkdir(exist_ok=True)

SUITE = [".venv/bin/python", "pipeline/test_batch_guards.py"]

# The child that exits non-zero without printing anything - the exact failure
# mode the entry describes, forced deterministically instead of waited for.
DYING_CHILD_OLD = (
    "            \"w,u,t=model_pacer._acquire(%r,rpm=3);print(json.dumps([w,u,t]))\"")
DYING_CHILD_NEW = (
    "            \"w,u,t=model_pacer._acquire(%r,rpm=3);sys.exit(3)\"")

# The pre-fix body, verbatim from before this change, paired with a dying child.
PREFIX_BODY = """        results = []
        procs = [subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE,
                                  text=True) for _ in range(5)]
        for proc in procs:
            out, _ = proc.communicate(timeout=60)
            results.append(json.loads(out.strip()))
        waited = sum(1 for w, _, _ in results if w > 0)
        today = max(t for _, _, t in results)
        check("5 separate processes, 3-rpm ceiling -> 2 had to wait",
              waited == 2, results)
        check("the shared counter saw all 5", today == 5, results)"""

MUTATIONS = [
    dict(
        name="pacer-child-dies-current-diagnosis",
        why="a child exits 3 printing nothing: the fixed test must NAME that",
        file="pipeline/test_batch_guards.py",
        old=DYING_CHILD_OLD,
        new=DYING_CHILD_NEW,
        cmd=SUITE, cwd=".",
        expect_in_output="all 5 pacer processes exited 0",
    ),
    dict(
        name="pacer-child-dies-prefix-diagnosis",
        why="the same dead child before the fix: a JSONDecodeError at the parse",
        file="pipeline/test_batch_guards.py",
        # One replacement spanning both, so the pair differs only in the
        # diagnosis: dying child AND the original unchecked parse.
        old=None,      # filled in at runtime from the current file
        new=None,
        cmd=SUITE, cwd=".",
        expect_in_output="JSONDecodeError",
        prefix_revert=True,
    ),
    dict(
        # p01's child exits silently, so its stderr field is empty - which
        # proves the check fires but NOT that stderr capture works. This child
        # says something on the way out, the way a real import error or
        # traceback would, and the assertion is that the words reach the
        # failure line. Without this, "capture stderr" is untested code.
        name="pacer-child-dies-loudly-on-stderr",
        why="a dying child's stderr must reach the failure message, not vanish",
        file="pipeline/test_batch_guards.py",
        old=DYING_CHILD_OLD,
        new=("            \"w,u,t=model_pacer._acquire(%r,rpm=3);"
             "sys.stderr.write('PACER-CHILD-DIED-HERE');sys.exit(4)\""),
        cmd=SUITE, cwd=".",
        expect_in_output="PACER-CHILD-DIED-HERE",
    ),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def current_block(text):
    """The fixed block, from `procs = [` to the end of the else branch."""
    start = text.index("        procs = [subprocess.Popen([PY, \"-c\", code]")
    end = text.index("            check(\"the shared counter saw all 5\", False, detail)")
    return text[start:end + len(
        "            check(\"the shared counter saw all 5\", False, detail)")]


def run_one(m, i):
    path = ROOT / m["file"]
    before = path.read_text(encoding="utf-8")
    digest = sha(path)
    log = LOGS / ("p%02d-%s.log" % (i, m["name"]))

    if m.get("prefix_revert"):
        old = current_block(before)
        new = PREFIX_BODY
        mutated = before.replace(old, new, 1).replace(
            DYING_CHILD_OLD, DYING_CHILD_NEW, 1)
    else:
        if m["old"] not in before:
            return dict(name=m["name"], status="ANCHOR-MISSING", failed=[],
                        log=str(log), why=m["why"])
        mutated = before.replace(m["old"], m["new"], 1)

    path.write_text(mutated, encoding="utf-8")
    try:
        if sha(path) == digest:
            return dict(name=m["name"], status="NO-OP-EDIT", failed=[],
                        log=str(log), why=m["why"])
        # Same bytecode hazard the sourcing campaign hit: a same-size edit
        # inside one second reuses the cached module.
        for cache in ROOT.glob("*/__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(m["cmd"], cwd=str(ROOT / m["cwd"]), env=env,
                              capture_output=True, text=True, timeout=900)
        out = (proc.stdout or "") + (proc.stderr or "")
        log.write_text("$ %s   (cwd=%s)\nexit=%d\n\n%s"
                       % (" ".join(m["cmd"]), m["cwd"], proc.returncode, out),
                       encoding="utf-8")
        named = [ln.strip() for ln in out.splitlines()
                 if ln.strip().startswith("FAIL") or "Error" in ln]
        red = proc.returncode != 0
        # The real assertion of this campaign: the run is red AND the output
        # says the right thing. A red run with the wrong explanation is the
        # defect being fixed, not evidence against it.
        says_it = m["expect_in_output"] in out
        status = ("CAUGHT+NAMED" if red and says_it else
                  "RED-BUT-WRONG-NAME" if red else "NOT CAUGHT")
    finally:
        path.write_text(before, encoding="utf-8")
        assert sha(path) == digest, "RESTORE FAILED for %s" % m["file"]

    return dict(name=m["name"], status=status, failed=named[:6], log=str(log),
                why=m["why"], expect=m["expect_in_output"])


def main():
    results = []
    for i, m in enumerate(MUTATIONS, 1):
        print("[%d/%d] %s ..." % (i, len(MUTATIONS), m["name"]), flush=True)
        r = run_one(m, i)
        results.append(r)
        print("      %s" % r["status"], flush=True)

    print("\n" + "=" * 74)
    print("MUTATION CAMPAIGN - pacer cross-process diagnosis")
    print("=" * 74)
    for r in results:
        print("\n%-38s %s" % (r["name"], r["status"]))
        print("  defect: %s" % r["why"])
        print("  expected in output: %r" % r.get("expect"))
        for f in r["failed"]:
            print("  %s" % f[:120])
    bad = [r for r in results if r["status"] != "CAUGHT+NAMED"]
    print("\n%d/%d mutations caught AND correctly named"
          % (len(results) - len(bad), len(results)))
    if bad:
        print("NOT AS EXPECTED: %s" % ", ".join(r["name"] for r in bad))
    print("logs kept in %s" % LOGS)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
