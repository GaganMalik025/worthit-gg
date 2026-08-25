"""Mutation proof for direction B of test_prompt_names_every_word_the_guard_rejects.

The test guarded the prompt/guard wiring in ONE direction:

    missing = [w for w in prevalence_guard.banned_words() if w not in prompt]

That is direction A - banned_words() subset-of prompt. It catches a word the
guard REJECTS but the prompt never NAMES. It is blind to the mirror: a word the
prompt NAMES that the guard does not actually reject. Since the 2026-08-21
frequency split FREED words in the guard, that is a live hazard - a model told to
avoid a word it is allowed to use spells around it rather than dropping the fact
(222880 shipped "Windows eleven" for exactly this reason, in the sibling guard).

Direction B, added 2026-08-25, parses the prompt's banned list out of the prompt
TEXT and asserts every word in it is genuinely rejected by check_claim().

WHY FOUR CONTROLS
-----------------
  pb01 baseline: both directions pass on the file as committed. Recorded so a
       later red run has something to be red against.

  pb02 direction B has teeth: name a FREED word in the prompt. B must fail AND
       name the word. A must still pass - if A also failed, B would be
       redundant rather than complementary.

  pb03 vacuity: break the "BANNED WORDS:" marker. B's word loop would iterate an
       empty list and pass while checking nothing. The anti-vacuity check must
       fire instead. Without this control, pb02 alone cannot tell a working
       check from one that happens to have words to look at.

  pb04 direction A is still live: drop a word from the prompt. A must fail AND
       name it, while B passes. The mirror of pb02, proving the two directions
       are independent and neither was replaced by the other.

KNOWN GAP, NOT FIXED HERE
-------------------------
banned_words()' extraction misses everyone/nobody/no one - the guard rejects them
but they never reach the prompt (BACKLOG 2026-08-25, pending its own decision;
fixing it invalidates 1,009 cached prompts). NEITHER direction can see that: A
reads a list that already omits the word, B never encounters it. pb01 records the
gap rather than routing around it.

Run:  .venv/bin/python evals/mutate_prompt_banned_direction_2026-08-25.py
Logs: evals/mutation-logs/pb01..pb04.log
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
TARGET = ROOT / "pipeline/synthesize.py"

LOGS.mkdir(exist_ok=True)
results = []

# Run the ONE test function, not the whole suite: importing test_batch_guards has
# no side effects (module level is imports plus two constants), and FAILURES
# carries the failing check names and their detail verbatim.
PROBE = r'''
import io, json, sys, contextlib
sys.path.insert(0, %(pipeline)r)
import test_batch_guards as t
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    t.test_prompt_names_every_word_the_guard_rejects()
print("PROBE_JSON " + json.dumps({"failures": t.FAILURES, "out": buf.getvalue()}))
'''


def probe():
    src = PROBE % {"pipeline": str(ROOT / "pipeline")}
    r = subprocess.run([PY, "-c", src], capture_output=True, text=True,
                       cwd=str(ROOT))
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE_JSON ")]
    if not line:
        return {"error": (r.stdout + r.stderr)[-1500:], "failures": [], "out": ""}
    return json.loads(line[0][len("PROBE_JSON "):])


def failed(r, prefix):
    """The FAILURES entries whose check name starts with prefix."""
    return [f for f in r["failures"] if f.startswith(prefix)]


def record(tag, desc, ok, detail):
    results.append((tag, desc, ok))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n\n%s\n" % (tag, desc, "PASS" if ok else "FAIL", detail),
        encoding="utf-8")
    print("  %-4s %-58s %s" % (tag, desc[:58], "ok" if ok else "** FAILED **"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def swap(original, find, replace, expect=1):
    if original.count(find) != expect:
        raise SystemExit("anchor x%d, expected %d: %r"
                         % (original.count(find), expect, find[:70]))
    TARGET.write_text(original.replace(find, replace), encoding="utf-8")


JOIN = '''    "banned": ", ".join(prevalence_guard.banned_words())}'''
# "occasional" is the deliberate choice: it is the word from the ORIGINAL drift
# and a word the 2026-08-21 split freed. Naming it in today's prompt is exactly
# the named-but-unenforced regression, not a contrived string.
JOIN_ADD = '''    "banned": ", ".join(prevalence_guard.banned_words() + ["occasional"])}'''
JOIN_DROP = '''    "banned": ", ".join(prevalence_guard.banned_words()[1:])}'''
MARKER = "BANNED WORDS: %(banned)s."
MARKER_BROKEN = "Avoid these: %(banned)s."


def main():
    before, original = sha(TARGET), TARGET.read_text(encoding="utf-8")
    print("mutate_prompt_banned_direction_2026-08-25  "
          "(synthesize.py sha %s)\n" % before)

    # ---- pb01 BASELINE: the file as committed ---------------------------
    r = probe()
    b_fail = failed(r, "B:")
    a_fail = failed(r, "A:")
    record("pb01", "BASELINE: directions A and B both pass as committed",
           not r.get("error") and not a_fail and not b_fail,
           "A failures: %s\nB failures: %s\n\nKNOWN GAP (invisible to both, by "
           "design of banned_words()' extraction; BACKLOG 2026-08-25):\n"
           "  everyone / nobody / no one are rejected by the guard and never "
           "reach the prompt.\n\nfull output:\n%s"
           % (a_fail, b_fail, r.get("out") or r.get("error")))

    # ---- pb02 DIRECTION B HAS TEETH -------------------------------------
    try:
        swap(original, JOIN, JOIN_ADD)
        r2 = probe()
        b2, a2 = failed(r2, "B: every word"), failed(r2, "A:")
        record("pb02",
               "B TEETH: naming freed 'occasional' fails B by name; A unaffected",
               bool(b2) and "occasional" in " ".join(b2) and not a2,
               "B failures (must name 'occasional'): %s\n"
               "A failures (must be empty - the directions are independent): %s\n"
               "\nfull output:\n%s" % (b2, a2, r2.get("out") or r2.get("error")))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # ---- pb03 VACUITY ---------------------------------------------------
    try:
        swap(original, MARKER, MARKER_BROKEN)
        r3 = probe()
        vac = failed(r3, "B: the prompt's banned list parses")
        record("pb03",
               "VACUITY: an unparseable list trips the anti-vacuity check",
               bool(vac),
               "anti-vacuity failures (must be non-empty): %s\n"
               "Without this check B would iterate [] and report ok.\n"
               "\nfull output:\n%s" % (vac, r3.get("out") or r3.get("error")))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # ---- pb04 DIRECTION A IS STILL LIVE ---------------------------------
    try:
        swap(original, JOIN, JOIN_DROP)
        r4 = probe()
        a4, b4 = failed(r4, "A:"), failed(r4, "B:")
        record("pb04",
               "A TEETH: dropping a word fails A by name; B unaffected",
               bool(a4) and "consensus" in " ".join(a4) and not b4,
               "A failures (must name the dropped word 'consensus'): %s\n"
               "B failures (must be empty): %s\n"
               "\nfull output:\n%s" % (a4, b4, r4.get("out") or r4.get("error")))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    after = sha(TARGET)
    record("pb05", "synthesize.py restored byte-identical", after == before,
           "before %s / after %s" % (before, after))

    bad = [t for t, _, ok in results if not ok]
    print("\n%s" % ("all controls held"
                    if not bad else "FAILED: %s" % ", ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
