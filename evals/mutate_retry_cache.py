"""Mutation proof for test_a_retry_never_replays_a_cached_rejection.

BACKLOG 2026-08-18 (Insurgency, 222880): the synthesis retry loop replayed three
cached rejections every night, so no retry could ever return a different answer.
The fix is option (c) - only attempt 0 may READ the cache.

A test that passes proves nothing about a fix it cannot see fail. This driver
puts the OLD line back, runs the guard suite, and requires the new test to go
red and to NAME the deadlock rather than merely failing somewhere. It then
restores synthesize.py and checks the file is byte-identical to what it started
as, because a mutation harness that leaves the tree dirty is worse than none.

Run:  .venv/bin/python evals/mutate_retry_cache.py
Logs: evals/mutation-logs/, one per mutation, kept - same directory and the same
      NN-description.log shape as mutate_reconciliation.py (01-11),
      mutate_pacer_diagnosis.py (p01-p03) and mutate_sourcing.py (s01-s10).
      A log written anywhere else is not findable by whoever checks the claim.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
TARGET = ROOT / "pipeline/synthesize.py"
PY = str(ROOT / ".venv/bin/python")
SUITE = str(ROOT / "pipeline/test_batch_guards.py")

FIXED = "        if cpath.exists() and not args.force and attempt == 0:"
BROKEN = "        if cpath.exists() and not args.force:"

# What a real failure has to say. Merely turning the suite red is not enough:
# the 2026-08-12 entry's lesson is that a test whose output does not identify
# the failure is not yet a test.
MUST_NAME = [
    "attempt 1 is NOT served from cache",
    "second run still sends a request for each retry",
]


def run_suite():
    p = subprocess.run([PY, SUITE], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def failed_checks(out):
    return [l.strip() for l in out.splitlines() if l.rstrip().endswith("FAIL")]


def main():
    LOGS.mkdir(exist_ok=True)
    original = TARGET.read_text(encoding="utf-8")
    digest = hashlib.sha256(original.encode()).hexdigest()[:12]
    if FIXED not in original:
        sys.exit("the fixed line is not present - nothing to mutate")

    results = []
    # m01: the control. The suite must be green before a mutation means anything.
    rc, out = run_suite()
    (LOGS / "m01-control-fix-in-place.log").write_text(out, encoding="utf-8")
    results.append(("m01 control, fix in place", rc == 0,
                    "rc=%d %s" % (rc, failed_checks(out) or "green")))

    # m02: the mutation - the pre-fix line, restoring the Insurgency deadlock.
    try:
        TARGET.write_text(original.replace(FIXED, BROKEN), encoding="utf-8")
        rc, out = run_suite()
        (LOGS / "m02-old-unconditional-cache-read.log").write_text(out, encoding="utf-8")
        named = [m for m in MUST_NAME if any(m in f for f in failed_checks(out))]
        results.append(("m02 old unconditional read -> suite red", rc != 0,
                        "rc=%d" % rc))
        results.append(("m02 failure NAMES the replayed retry", len(named) == len(MUST_NAME),
                        "named %d/%d: %s" % (len(named), len(MUST_NAME), named)))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # m03: restoration is byte-identical, and the suite is green again.
    back = hashlib.sha256(TARGET.read_text(encoding="utf-8").encode()).hexdigest()[:12]
    results.append(("m03 synthesize.py restored byte-identical", back == digest,
                    "%s -> %s" % (digest, back)))
    rc, out = run_suite()
    (LOGS / "m03-restored-byte-identical.log").write_text(out, encoding="utf-8")
    results.append(("m03 suite green after restore", rc == 0,
                    "rc=%d %s" % (rc, failed_checks(out) or "green")))

    print("\nmutation proof: retry cache read (BACKLOG 2026-08-18, option c)")
    for name, ok, detail in results:
        print("  %-46s %-6s %s" % (name, "CAUGHT" if ok else "MISSED", detail))
    bad = [r for r in results if not r[1]]
    print("\n%d/%d" % (len(results) - len(bad), len(results)),
          "- all mutations caught" if not bad else "- UNCAUGHT: %s" % [b[0] for b in bad])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
