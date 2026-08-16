"""Break-then-confirm campaign for the EST_COST reconciliation work.

    .venv/bin/python evals/mutate_reconciliation.py

Run from the repo root. Exits 1 if ANY mutation goes uncaught.
Logs are written to evals/mutation-logs/, one per mutation, kept.


Each mutation is a real defect the design argues against. For every one:
  1. checksum the file, apply the mutation, assert the file actually changed
  2. run the suite that is supposed to catch it, KEEPING the output in a file
     (BACKLOG 2026-08-13: a suite redirected to /dev/null cannot be debugged)
  3. record the exit code and which named tests failed
  4. restore from the byte-for-byte backup and verify the checksum matches

A mutation whose suite stays green is reported as NOT CAUGHT - that is the
finding, not an error to be smoothed over.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

# Derived from this file's own location, never hardcoded: the first cut of this
# script lived at an absolute session temp path and cited itself as if it were
# repo-relative, which is the exact defect RESULTS.md's 2026-08-16 incident
# follow-up is about - a citation the reader cannot open is not verifiable.
ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
LOGS.mkdir(exist_ok=True)

TS = ["npx", "vitest", "run"]

MUTATIONS = [
    # ---- the one the design turns on -------------------------------------
    dict(
        name="clamp-the-correction-term-at-zero",
        why="a 14-call run would stop charging the 1 it overran: under-count",
        file="site/lib/quota.ts",
        old="      typeof actual === \"number\" ? acc + (EST_COST - actual) : acc,",
        new="      typeof actual === \"number\" ? acc + Math.max(0, EST_COST - actual) : acc,",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    # ---- the sweep's attribution rules ------------------------------------
    dict(
        name="key-by-appid-alone",
        why="a retry's cost would stand in for the failed run it replaced",
        file="site/lib/quota.ts",
        old="export const reconcileKey = (appid: number | string, runId: number | string) =>\n  `${appid}|${runId}`;",
        new="export const reconcileKey = (appid: number | string, _runId: number | string) =>\n  `${appid}`;",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    dict(
        name="read-the-artifact-for-failed-runs",
        why="a failed run would be credited with a later run's committed cost",
        file="site/lib/github.ts",
        old="    if (outcome !== \"published\") {\n      found[reconcileKey(appid, run.id)] = null;    // cost gone for good\n      continue;\n    }",
        new="    if (outcome !== \"published\") {\n      // MUTATION\n    }",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    dict(
        name="sweep-runs-that-are-still-active",
        why="an in-flight run would be reconciled from a partial artifact",
        file="site/lib/github.ts",
        old="        !isActive(r) &&",
        new="",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    dict(
        name="drop-the-sweep-cap",
        why="an unbounded sweep puts N artifact fetches in front of a dispatch",
        file="site/lib/github.ts",
        old="    .slice(0, limit);",
        new="    .slice(0);",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    # ---- the admission path actually reading the derived figure -----------
    dict(
        name="admission-reads-the-raw-counter",
        why="the correction would be computed and then ignored by the one "
            "decision it exists for - the shape of the 573a1d6 bug",
        file="site/lib/quota.ts",
        old="  return Math.max(0, reserve - effectiveLiveUsed(s));",
        new="  return Math.max(0, reserve - (s.live_used ?? 0));",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    dict(
        name="rollday-keeps-yesterdays-facts",
        why="stale corrections would refund against today's fresh counter",
        file="site/lib/quota.ts",
        old="             outcomes: s.outcomes ?? {}, dispatched: {}, reconciled: {} };",
        new="             outcomes: s.outcomes ?? {}, dispatched: {} };",
        cmd=TS + ["lib/__tests__/reconciliation.test.ts"],
        cwd="site",
    ),
    # ---- invariant 13: the field must never reach a reader ----------------
    dict(
        name="render-the-cost-field",
        why="a pipeline diagnostic on the page - invariant 13",
        file="site/components/VerdictPage.tsx",
        old="        {v.generated_at.slice(0, 10)}",
        new="        {v.generated_at.slice(0, 10)}{\" \"}\n        {(v as unknown as {cost?: {model_calls: number}}).cost?.model_calls}",
        cmd=TS + ["lib/__tests__/cost-never-renders.contract.test.tsx"],
        cwd="site",
    ),
    # ---- the mirror ------------------------------------------------------
    dict(
        name="est-cost-drift",
        why="the constant the whole correction is measured against, drifting",
        file="site/lib/quota.ts",
        old="export const EST_COST = 13;",
        new="export const EST_COST = 14;",
        cmd=TS + ["lib/__tests__/quota-mirror.contract.test.ts"],
        cwd="site",
    ),
    # ---- the python side --------------------------------------------------
    dict(
        name="cost-is-a-constant",
        why="a hardcoded figure refunds a number nobody measured",
        file="pipeline/synthesize.py",
        old="        \"model_calls\": model_pacer.calls_for(appid),",
        new="        \"model_calls\": 9,",
        cmd=[".venv/bin/python", "pipeline/test_verdict_cost.py"],
        cwd=".",
    ),
    dict(
        name="basis-loses-the-caveat",
        why="the number gets read as a clean per-run cost on the batch path",
        file="pipeline/synthesize.py",
        old="        \"basis\": (\"gemini requests charged to this appid on this quota day, on \"",
        new="        \"basis\": (\"model calls for this run. \" + (\"\"",
        cmd=[".venv/bin/python", "pipeline/test_verdict_cost.py"],
        cwd=".",
    ),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_one(m, i):
    path = ROOT / m["file"]
    before = path.read_text(encoding="utf-8")
    digest = sha(path)
    log = LOGS / ("%02d-%s.log" % (i, m["name"]))

    if m["old"] not in before:
        return dict(name=m["name"], status="ANCHOR-MISSING", failed=[], log=str(log))

    path.write_text(before.replace(m["old"], m["new"], 1), encoding="utf-8")
    try:
        if sha(path) == digest:
            return dict(name=m["name"], status="NO-OP-EDIT", failed=[], log=str(log))
        proc = subprocess.run(m["cmd"], cwd=str(ROOT / m["cwd"]),
                              capture_output=True, text=True, timeout=600)
        out = (proc.stdout or "") + (proc.stderr or "")
        log.write_text("$ %s   (cwd=%s)\nexit=%d\n\n%s"
                       % (" ".join(m["cmd"]), m["cwd"], proc.returncode, out),
                       encoding="utf-8")
        failed = [ln.strip() for ln in out.splitlines()
                  if ln.strip().startswith(("×", "FAIL ", "  FAIL"))]
        status = "CAUGHT" if proc.returncode != 0 else "NOT CAUGHT"
    finally:
        path.write_text(before, encoding="utf-8")
        assert sha(path) == digest, "RESTORE FAILED for %s" % m["file"]

    return dict(name=m["name"], status=status, failed=failed[:6],
                log=str(log), why=m["why"])


def main():
    results = []
    for i, m in enumerate(MUTATIONS, 1):
        print("[%d/%d] %s ..." % (i, len(MUTATIONS), m["name"]), flush=True)
        r = run_one(m, i)
        results.append(r)
        print("      %s" % r["status"], flush=True)

    print("\n" + "=" * 74)
    print("MUTATION CAMPAIGN")
    print("=" * 74)
    for r in results:
        print("\n%-34s %s" % (r["name"], r["status"]))
        if r.get("why"):
            print("  defect: %s" % r["why"])
        for f in r["failed"]:
            print("  %s" % f[:110])
    bad = [r for r in results if r["status"] != "CAUGHT"]
    print("\n%d/%d mutations caught" % (len(results) - len(bad), len(results)))
    if bad:
        print("NOT CAUGHT: %s" % ", ".join(r["name"] for r in bad))
    print("logs kept in %s" % LOGS)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
