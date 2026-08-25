"""Mutation proof for test_retry_prose_does_not_move_with_the_guards_wordlist.

The test asserts that a prevalence rejection renders the same prose - and so the
same retry cache key - under two different guard wordlists. A test asserting
"these two strings are equal" is exactly the kind that passes for the wrong
reason: it also passes if the prose is empty, if the branch never fires, or if
the wordlist edit changed nothing. So each control breaks one thing and names
which check must go red.

WHY SIX CONTROLS
----------------
  rp01 BASELINE: the suite's one function passes on the file as committed.
       Recorded so a later red run has something to be red against.

  rp02 CONTROL - THE OLD CODE. Restores the pre-2026-08-25 rendering,
       `"states how common something is (%s)" % terms`, and nothing else. The
       SAME claim and the SAME freed word must now move both the problem line
       and the cache key, and the matched terms must be visible in the prose.
       This is the control the whole change rests on: it proves the bug was real
       and that the test can see it. The anti-vacuity check goes red here too -
       it is worded against the committed prose - so it is asserted in rp04/rp05
       instead, where the real prose is in place.

  rp03 VACUITY. Empties the prevalence prose. Stability becomes trivially true -
       an empty string is stable under any wordlist - so the two equality checks
       still pass and only the anti-vacuity check may fail. Without this control
       rp02 alone cannot tell a fix from a deletion.

  rp04 SCOPE. Rewords the untouched `only_` branch. The scope check must fail,
       proving the edit really was additive to one branch and that a future
       rewrite of _problem_line cannot silently take the others with it.

  rp05 FIXTURE TEETH. Points the test's in-memory wordlist edit at a word the
       guard does not carry, so the edit changes nothing. The fixture guard must
       fail rather than the test reporting perfect stability over a no-op.

  rp06 Both files restored byte-identical.

Each probe clears pipeline/__pycache__ - see probe() for why that is load-bearing
rather than tidiness.

Run:  .venv/bin/python evals/mutate_retry_prevalence_prose_2026-08-25.py
Logs: evals/mutation-logs/rp01..rp06.log
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
TARGET = ROOT / "pipeline/extract_claims.py"
SUITE = ROOT / "pipeline/test_batch_guards.py"

LOGS.mkdir(exist_ok=True)
results = []

PROBE = r'''
import io, json, sys, contextlib
sys.path.insert(0, %(pipeline)r)
import test_batch_guards as t
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    t.test_retry_prose_does_not_move_with_the_guards_wordlist()
print("PROBE_JSON " + json.dumps({"failures": t.FAILURES, "out": buf.getvalue()}))
'''


def probe():
    # Drop the bytecode cache first, and do not write a new one. rp05 swaps
    # "most" for "zzzz" - SAME LENGTH - and restores it within the same second,
    # so source size and mtime are both unchanged and CPython happily replays
    # the mutated .pyc into the NEXT probe. That is not hypothetical: it turned
    # rp01 red on a clean tree, which is a mutation harness reporting a result
    # from code that is no longer on disk. -B alone is not enough; it stops
    # writing, not reading.
    for stale in (ROOT / "pipeline/__pycache__").glob("*.pyc"):
        stale.unlink()
    r = subprocess.run([PY, "-B", "-c",
                        PROBE % {"pipeline": str(ROOT / "pipeline")}],
                       capture_output=True, text=True, cwd=str(ROOT))
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE_JSON ")]
    if not line:
        return {"error": (r.stdout + r.stderr)[-1500:], "failures": [], "out": ""}
    return json.loads(line[0][len("PROBE_JSON "):])


def failed(r, prefix):
    return [f for f in r["failures"] if f.startswith(prefix)]


def record(tag, desc, ok, detail):
    results.append((tag, desc, ok))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n\n%s\n" % (tag, desc, "PASS" if ok else "FAIL", detail),
        encoding="utf-8")
    print("  %-4s %-58s %s" % (tag, desc[:58], "ok" if ok else "** FAILED **"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def swap(path, original, find, replace, expect=1):
    if original.count(find) != expect:
        raise SystemExit("anchor x%d, expected %d in %s: %r"
                         % (original.count(find), expect, path.name, find[:70]))
    path.write_text(original.replace(find, replace), encoding="utf-8")


NEW_BRANCH = '''            reasons.append("states how many, how much, or what share of "
                           "something there is - a count or proportion this "
                           "sample cannot support; restate it without quantity "
                           "or population language, or drop it")'''
OLD_BRANCH = '''            terms = f.split(":", 1)[1]
            reasons.append("states how common something is (%s)" % terms)'''
EMPTY_BRANCH = '''            reasons.append("")'''
ONLY_BRANCH = '''            reasons.append("only one cited review actually supports it; two are "
                           "required")'''
ONLY_REWORDED = '''            reasons.append("needs a second citation")'''
FIXTURE = '''            (rx, lab) for rx, lab in saved if "most" not in rx.pattern]'''
FIXTURE_NOOP = '''            (rx, lab) for rx, lab in saved if "zzzz" not in rx.pattern]'''

STABILITY = ("the problem line is byte-identical", "the retry cache key does not")
VACUITY = "the prose still names the prevalence category"
SCOPE = "a mixed failure still carries its non-prevalence reason"
LEAK = "no matched term reaches the prose"
FIXTURE_CHECK = "fixture: the freed word changes what the guard matched"


def stability_failures(r):
    return [f for f in r["failures"] if f.startswith(STABILITY)]


def main():
    t_before, t_orig = sha(TARGET), TARGET.read_text(encoding="utf-8")
    s_before, s_orig = sha(SUITE), SUITE.read_text(encoding="utf-8")
    print("mutate_retry_prevalence_prose_2026-08-25  "
          "(extract_claims.py sha %s, test_batch_guards.py sha %s)\n"
          % (t_before, s_before))

    # ---- rp01 BASELINE --------------------------------------------------
    r = probe()
    record("rp01", "BASELINE: the test passes on the file as committed",
           not r.get("error") and not r["failures"],
           "failures: %s\n\nfull output:\n%s"
           % (r["failures"], r.get("out") or r.get("error")))

    # ---- rp02 CONTROL: the old code -------------------------------------
    try:
        swap(TARGET, t_orig, NEW_BRANCH, OLD_BRANCH)
        r2 = probe()
        st = stability_failures(r2)
        record("rp02",
               "CONTROL: old prose moves the line AND the key for the same word",
               len(st) == 2 and bool(failed(r2, LEAK))
               and not failed(r2, FIXTURE_CHECK),
               "stability failures (must be BOTH - line and key): %s\n"
               "leak failures (must be non-empty - the old prose quoted the "
               "matched terms): %s\n"
               "fixture guard (must be empty - the wordlist edit still bit): %s\n"
               "\nThe anti-vacuity check ALSO goes red here and that is "
               "correct, not a miss: it\nis phrased against the committed "
               "wording, which the old prose does not use. It is\nasserted "
               "green in rp04/rp05 instead, where the prose is the real one.\n"
               "  anti-vacuity: %s\n"
               "\nThis is the bug, reproduced: freeing one word from PATTERNS "
               "changes the retry prompt\nand therefore its sha256 cache key, "
               "while the grounding verdict is unchanged.\n\nfull output:\n%s"
               % (st, failed(r2, LEAK), failed(r2, FIXTURE_CHECK),
                  failed(r2, VACUITY), r2.get("out") or r2.get("error")))
    finally:
        TARGET.write_text(t_orig, encoding="utf-8")

    # ---- rp03 VACUITY ---------------------------------------------------
    try:
        swap(TARGET, t_orig, NEW_BRANCH, EMPTY_BRANCH)
        r3 = probe()
        vac = failed(r3, VACUITY)
        record("rp03", "VACUITY: empty prose is stable, and must still fail",
               bool(vac) and not stability_failures(r3),
               "anti-vacuity failures (must be non-empty): %s\n"
               "stability failures (must be EMPTY - an empty string is stable "
               "under any wordlist,\n  which is exactly why stability alone "
               "proves nothing): %s\n\nfull output:\n%s"
               % (vac, stability_failures(r3), r3.get("out") or r3.get("error")))
    finally:
        TARGET.write_text(t_orig, encoding="utf-8")

    # ---- rp04 SCOPE -----------------------------------------------------
    try:
        swap(TARGET, t_orig, ONLY_BRANCH, ONLY_REWORDED)
        r4 = probe()
        sc = failed(r4, SCOPE)
        record("rp04", "SCOPE: rewording the untouched only_ branch fails the "
                       "scope check",
               bool(sc) and not stability_failures(r4),
               "scope failures (must be non-empty): %s\n"
               "stability failures (must be empty - the prevalence prose did "
               "not move): %s\n\nfull output:\n%s"
               % (sc, stability_failures(r4), r4.get("out") or r4.get("error")))
    finally:
        TARGET.write_text(t_orig, encoding="utf-8")

    # ---- rp05 FIXTURE TEETH ---------------------------------------------
    try:
        swap(SUITE, s_orig, FIXTURE, FIXTURE_NOOP)
        r5 = probe()
        fx = failed(r5, FIXTURE_CHECK)
        record("rp05", "FIXTURE: a wordlist edit that changes nothing is caught",
               bool(fx) and not stability_failures(r5),
               "fixture failures (must be non-empty): %s\n"
               "stability failures (must be empty - unchanged inputs are "
               "trivially stable): %s\n\nfull output:\n%s"
               % (fx, stability_failures(r5), r5.get("out") or r5.get("error")))
    finally:
        SUITE.write_text(s_orig, encoding="utf-8")

    t_after, s_after = sha(TARGET), sha(SUITE)
    record("rp06", "both files restored byte-identical",
           t_after == t_before and s_after == s_before,
           "extract_claims.py  before %s / after %s\n"
           "test_batch_guards.py before %s / after %s"
           % (t_before, t_after, s_before, s_after))

    bad = [t for t, _, ok in results if not ok]
    print("\n%s" % ("all controls held"
                    if not bad else "FAILED: %s" % ", ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
