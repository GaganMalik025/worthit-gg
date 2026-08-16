"""Break-then-confirm campaign for the cohort sourcing disclosure.

    .venv/bin/python evals/mutate_sourcing.py

Run from the repo root. Exits 1 if ANY mutation goes uncaught.
Logs are written to evals/mutation-logs/, one per mutation, kept.

Same shape as evals/mutate_reconciliation.py, and for the same reason: a guard
that has only ever been seen to pass is not yet known to be a guard. Every
mutation below is a defect the design argues against - a rounded threshold, an
off-by-one tail, a count that reaches the page - applied to the real file, with
the suite that is supposed to catch it run for real and its output kept.

Two of them are worth naming here because they are the ones the owner asked to
be proved specifically:

  * the BINOMIAL THRESHOLD LOGIC - 01, 02, 03, 05. ALPHA and THIN_MAX_REVIEWS
    are frozen measured constants, and the failure mode is nobody noticing they
    moved: the page keeps rendering, just about different sections.
  * the CONTRACT TEST's staleness detection - 07. It mutates a published
    verdict rather than any code, which is the real-world case (a re-extraction
    that leaves a block describing claims that no longer exist).
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

PY = [".venv/bin/python", "pipeline/test_sourcing_contract.py"]
TS = ["npx", "vitest", "run", "lib/__tests__/sourcing-disclosure.contract.test.tsx"]

MUTATIONS = [
    # ---- the frozen thresholds -------------------------------------------
    dict(
        name="alpha-rounded-off",
        why="4.64e-05 'is basically' 5e-05 - reclassifies sections silently",
        file="pipeline/sourcing.py",
        old="ALPHA = 0.05 / FAMILY_SIZE          # 4.6425e-05",
        new="ALPHA = 5e-05                       # 4.6425e-05",
        cmd=PY, cwd=".",
    ),
    dict(
        name="alpha-uncorrected",
        why="dropping Bonferroni: a bare .05 would escalate 43% of all sections",
        file="pipeline/sourcing.py",
        old="ALPHA = 0.05 / FAMILY_SIZE          # 4.6425e-05",
        new="ALPHA = 0.05                        # 4.6425e-05",
        cmd=PY, cwd=".",
    ),
    dict(
        name="thin-threshold-off-by-one",
        why="p10 is 4 distinct reviews; 5 is a tidier number and the wrong one",
        file="pipeline/sourcing.py",
        old="THIN_MAX_REVIEWS = 4",
        new="THIN_MAX_REVIEWS = 5",
        cmd=PY, cwd=".",
    ),
    # ---- the tail itself --------------------------------------------------
    dict(
        name="binomial-tail-off-by-one",
        why="P(X<k) instead of P(X<=k): every k=0 cohort becomes p=0, always escalated",
        file="pipeline/sourcing.py",
        old="for i in range(0, k + 1)))",
        new="for i in range(0, k)))",
        cmd=PY, cwd=".",
    ),
    dict(
        name="divergence-goes-two-sided",
        why="the copy says 'leaning more negative'; an upper-tail fire makes it false",
        file="pipeline/sourcing.py",
        old="    if p is not None and p < ALPHA:\n        triggers.append(\"divergent\")",
        new="    if p is not None and (p < ALPHA or p > 1.0 - ALPHA):\n        triggers.append(\"divergent\")",
        cmd=PY, cwd=".",
    ),
    # ---- what gets counted -------------------------------------------------
    dict(
        name="count-citations-not-reviewers",
        why="one reviewer cited by three claims would read as three - 77.3% of cohorts reuse",
        file="pipeline/sourcing.py",
        old="                seen[cit.get(\"recommendationid\")] = bool(cit.get(\"voted_up\"))",
        new="                seen[len(seen)] = bool(cit.get(\"voted_up\"))",
        cmd=PY, cwd=".",
    ),
    # ---- the staleness contract, mutated on DISK, not in code -------------
    dict(
        name="published-block-goes-stale",
        why="a re-extraction leaves a block describing claims that no longer exist",
        file="site/public/verdicts/233860.json",
        old="        \"level\": \"baseline\",",
        new="        \"level\": \"escalated\",",
        cmd=PY, cwd=".",
    ),
    # ---- the numberless rule, on the render side --------------------------
    dict(
        name="render-the-cited-count",
        why="B1 by the back door: a second non-pool number, next to pool_n",
        file="site/components/VerdictPage.tsx",
        old="  if (thin) return `${base} — here, an unusually small set of them.`;",
        new="  if (thin) return `${base} — here, only ${s.cited_reviews} of them.`;",
        cmd=TS, cwd="site",
    ),
    dict(
        name="tier-1-only-on-escalation",
        why="silence would then certify the other 82% of sections as representative",
        file="site/components/VerdictPage.tsx",
        old="  return `${base}.`;",
        new="  return s.level === \"escalated\" ? `${base}.` : null;",
        cmd=TS, cwd="site",
    ),
    dict(
        name="escalation-replaces-the-baseline-sentence",
        why="the escalated case would lose the sentence that explains the rest",
        file="site/components/VerdictPage.tsx",
        old="  if (thin) return `${base} — here, an unusually small set of them.`;",
        new="  if (thin) return `An unusually small set of reviews.`;",
        cmd=TS, cwd="site",
    ),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_one(m, i):
    path = ROOT / m["file"]
    before = path.read_text(encoding="utf-8")
    digest = sha(path)
    log = LOGS / ("s%02d-%s.log" % (i, m["name"]))

    if m["old"] not in before:
        return dict(name=m["name"], status="ANCHOR-MISSING", failed=[],
                    log=str(log), why=m["why"])

    path.write_text(before.replace(m["old"], m["new"], 1), encoding="utf-8")
    try:
        if sha(path) == digest:
            return dict(name=m["name"], status="NO-OP-EDIT", failed=[],
                        log=str(log), why=m["why"])
        # STALE BYTECODE IS NOT HYPOTHETICAL HERE - the first run of this
        # campaign was wrong because of it. CPython invalidates a .pyc on
        # (source mtime, source size), mtime at ONE SECOND resolution. The
        # three ALPHA mutations are all exactly 48 bytes (the comment is
        # aligned), and each test run finishes in well under a second, so
        # mutations 2 and 3 imported mutation 1's cached module: both reported
        # CAUGHT while mutation 3's own thin-boundary assertions printed `ok`.
        # A mutation caught by the previous mutation's leftovers is not
        # evidence about anything. Belt and braces: drop the cache, and forbid
        # writing a new one.
        for cache in ROOT.glob("*/__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(m["cmd"], cwd=str(ROOT / m["cwd"]), env=env,
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
    print("MUTATION CAMPAIGN - cohort sourcing disclosure")
    print("=" * 74)
    for r in results:
        print("\n%-38s %s" % (r["name"], r["status"]))
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
