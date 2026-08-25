r"""Mutation proof for the 2026-08-26 banned_words() extraction fix.

`PATTERNS` carried `\b(?:everyone|nobody|no\s+one)\b` as ONE alternation.
banned_words()' extractor A is `re.findall(r"\(\?:([a-z|\s]+)\)", pattern)`, and
`no\s+one`'s backslash is outside `[a-z|\s]`, so the whole group failed to match
and `everyone` and `nobody` were lost with it - rejected by check_claim, never
named in synthesize.py's prompt. The fix splits the pattern in two. It is meant
to change WHAT IS NAMED and nothing else.

That "nothing else" is the part worth proving, so bw03 does it on real data
rather than on a battery someone wrote to pass.

WHY SIX CONTROLS
----------------
  bw01 BASELINE: the new test passes on the file as committed, and
       banned_words() is the 10-word list.

  bw02 CONTROL - THE OLD PATTERN. Restores the single group. The class-level
       test must FAIL naming everyone AND nobody, and banned_words() must fall
       back to 8. The defect, reproduced. Note the two directions of
       test_prompt_names_every_word_the_guard_rejects stay GREEN here: that is
       the point of the new test, not a flaw in the old ones.

  bw03 REJECTIONS UNCHANGED. check_claim's verdict on everyone / nobody /
       no one and on negative controls, asserted per phrase under both
       patterns, PLUS a differential sweep of every claim string in
       data/claims/*.json: the full (text -> matched terms) mapping must be
       identical. Thousands of real strings, so "only the naming changed" is
       measured rather than asserted.

  bw04 THE "no one" LIMIT IS REAL AND DELIBERATE. With the fix in place it is
       still rejected and still absent from banned_words(). Extractor A drops
       any alternative containing a space and B cannot read across \s+, so no
       way of writing the pattern makes it quotable - the same limit that keeps
       "many players" out of the prompt. Recorded as a control so a future
       reader sees a decision, not an oversight.

  bw05 THE NEW TEST IS NOT KEYED TO ONE WORD, OR TO ONE PATTERN SHAPE.
       Reintroduces the defect for `nobody` ALONE, and OUTSIDE an alternation
       group - `\bnobody\s*\b` still matches "nobody", and is still invisible
       to both extractors. The class-level check must fail naming nobody and
       NOT everyone. Two things had to be got right for this to go red, and
       both were wrong in a first draft: deleting the word instead of hiding it
       only stops the guard rejecting it (a silent check would then be
       CORRECT), and a reader that tokenises `\bmost\b` as "bmost" sees no
       bans anywhere and reports a clean sweep over nothing.

  bw06 prevalence_guard.py restored byte-identical.

Run:  .venv/bin/python evals/mutate_banned_words_extraction_2026-08-26.py
Logs: evals/mutation-logs/bw01..bw06.log
"""
import hashlib
import json
import pathlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
TARGET = ROOT / "pipeline/prevalence_guard.py"

LOGS.mkdir(exist_ok=True)
results = []

# Runs the ONE new test function plus a snapshot of banned_words() and of
# check_claim's verdicts, in a fresh interpreter so the mutated file is what is
# actually imported.
PROBE = r'''
import io, json, sys, contextlib
sys.path.insert(0, %(pipeline)r)
import test_batch_guards as t
import prevalence_guard as pg
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    t.test_banned_words_names_every_single_word_ban()
    t.test_prompt_names_every_word_the_guard_rejects()
probes = %(probes)r
print("PROBE_JSON " + json.dumps({
    "failures": t.FAILURES,
    "out": buf.getvalue(),
    "banned": pg.banned_words(),
    "verdicts": {p: sorted({h[0] for h in pg.check_claim(p)}) for p in probes},
}))
'''

# Real sentences, and negative controls that must stay clean on both sides.
PROBES = [
    "no one finishes the campaign",
    "nobody finishes the campaign",
    "everyone agrees the combat is good",
    "no  one finishes the campaign",          # \s+ matches two spaces
    "no\tone finishes the campaign",          # ...and a tab
    "noone finishes the campaign",            # must NOT match: no word break
    "the game has no online mode",            # must NOT match "no one"
    "reviewers describe a nobody protagonist",
    "you expect free access to all content",  # the 08-25 content carve-out
    "the most polished mech shooter",         # superlative, not a quantifier
]


def probe():
    for stale in (ROOT / "pipeline/__pycache__").glob("*.pyc"):
        stale.unlink()
    src = PROBE % {"pipeline": str(ROOT / "pipeline"), "probes": PROBES}
    r = subprocess.run([PY, "-B", "-c", src], capture_output=True, text=True,
                       cwd=str(ROOT))
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE_JSON ")]
    if not line:
        return {"error": (r.stdout + r.stderr)[-1500:], "failures": [],
                "out": "", "banned": [], "verdicts": {}}
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


def swap(original, find, replace, expect=1):
    if original.count(find) != expect:
        raise SystemExit("anchor x%d, expected %d: %r"
                         % (original.count(find), expect, find[:70]))
    TARGET.write_text(original.replace(find, replace), encoding="utf-8")


NEW = '''    (r"\\b(?:everyone|nobody)\\b", "absolute quantifier"),'''
NEW_NO_ONE = '''    (r"\\bno\\s+one\\b", "absolute quantifier"),'''
OLD_SINGLE = '''    (r"\\b(?:everyone|nobody|no\\s+one)\\b", "absolute quantifier"),'''
# Reintroduces the DEFECT for one word rather than removing the ban: `\s*`
# hides `nobody` from extractor B (which needs \b<letters>\b contiguous) and
# from A (no group), while `\bnobody\s*\b` still matches "nobody" exactly as
# before. Simply deleting the word would make the guard stop rejecting it, and
# then the class check would be RIGHT to stay silent - which is what the first
# draft of bw05 got wrong.
HIDE_NOBODY = '''    (r"\\b(?:everyone)\\b", "absolute quantifier"),
    (r"\\bnobody\\s*\\b", "absolute quantifier"),'''

CLASS_CHECK = "every single-word ban the guard carries is named"
PAIR_CHECK = "  including everyone and nobody"
NOONE_CHECK = "  'no one' is still rejected, and still cannot be named"
DIRECTIONS = ("A:", "B:")


def sweep_claims():
    """(claim text -> sorted matched terms) over every claim on disk.

    Imported in-process on purpose: it is called once per pattern version, and
    the caller reloads prevalence_guard between calls.
    """
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    import prevalence_guard
    importlib.reload(prevalence_guard)
    out, n = {}, 0
    for fp in sorted((ROOT / "data/claims").glob("*.json")):
        try:
            blob = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for claims in (blob.get("claims_by_bucket") or {}).values():
            for c in (claims or []):
                text = c.get("claim") or ""
                if not text:
                    continue
                n += 1
                hits = sorted({h[0] for h in prevalence_guard.check_claim(text)})
                if hits:
                    out[text] = hits
    return out, n


def main():
    before, original = sha(TARGET), TARGET.read_text(encoding="utf-8")
    print("mutate_banned_words_extraction_2026-08-26  "
          "(prevalence_guard.py sha %s)\n" % before)

    # ---- bw01 BASELINE ---------------------------------------------------
    r1 = probe()
    record("bw01", "BASELINE: the new test passes; banned_words() is 10 words",
           not r1.get("error") and not r1["failures"] and len(r1["banned"]) == 10
           and {"everyone", "nobody"} <= set(r1["banned"]),
           "banned_words() (%d): %s\nfailures: %s\n\nfull output:\n%s"
           % (len(r1["banned"]), r1["banned"], r1["failures"],
              r1.get("out") or r1.get("error")))

    # ---- bw02 CONTROL: the old single group -------------------------------
    try:
        swap(original, NEW + "\n", OLD_SINGLE + "\n")
        src = TARGET.read_text(encoding="utf-8")
        TARGET.write_text(src.replace(NEW_NO_ONE + "\n", ""), encoding="utf-8")
        r2 = probe()
        cls = failed(r2, CLASS_CHECK)
        named = " ".join(cls) + " " + " ".join(failed(r2, PAIR_CHECK))
        dirs = [f for f in r2["failures"] if f.startswith(DIRECTIONS)]
        record("bw02",
               "CONTROL: the old group loses everyone AND nobody from the prompt",
               bool(cls) and "everyone" in named and "nobody" in named
               and len(r2["banned"]) == 8 and not dirs,
               "banned_words() (%d, must be 8): %s\n"
               "class-check failures (must name everyone and nobody): %s\n"
               "direction A/B failures (must be EMPTY - neither direction can "
               "see this,\n  which is exactly why the class-level check "
               "exists): %s\n\nfull output:\n%s"
               % (len(r2["banned"]), r2["banned"], cls, dirs,
                  r2.get("out") or r2.get("error")))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # ---- bw03 REJECTIONS UNCHANGED ---------------------------------------
    new_sweep, n_claims = sweep_claims()
    new_verdicts = r1["verdicts"]
    try:
        swap(original, NEW + "\n", OLD_SINGLE + "\n")
        src = TARGET.read_text(encoding="utf-8")
        TARGET.write_text(src.replace(NEW_NO_ONE + "\n", ""), encoding="utf-8")
        r3 = probe()
        old_sweep, _ = sweep_claims()
    finally:
        TARGET.write_text(original, encoding="utf-8")
        sweep_claims()          # reload the real module back into this process
    phrase_diff = {p: (r3["verdicts"].get(p), new_verdicts.get(p))
                   for p in PROBES
                   if r3["verdicts"].get(p) != new_verdicts.get(p)}
    sweep_diff = {k: (old_sweep.get(k), new_sweep.get(k))
                  for k in set(old_sweep) | set(new_sweep)
                  if old_sweep.get(k) != new_sweep.get(k)}
    record("bw03",
           "REJECTIONS UNCHANGED: %d probes + %d real claims, byte-identical"
           % (len(PROBES), n_claims),
           not phrase_diff and not sweep_diff and n_claims > 100,
           "probe verdicts that differ (must be none): %s\n"
           "real claims whose matched terms differ (must be none): %s\n"
           "claims swept: %d, of which flagged: %d\n\n"
           "per-probe verdicts under the FIXED pattern:\n%s"
           % (phrase_diff, sweep_diff, n_claims, len(new_sweep),
              "\n".join("  %-46r -> %s" % (p, new_verdicts.get(p))
                        for p in PROBES)))

    # ---- bw04 THE "no one" LIMIT ------------------------------------------
    record("bw04",
           "LIMIT: 'no one' stays rejected and stays unnameable, deliberately",
           bool(new_verdicts.get("no one finishes the campaign"))
           and "no one" not in r1["banned"]
           and not [w for w in r1["banned"] if " " in w]
           and not failed(r1, NOONE_CHECK),
           "check_claim('no one finishes the campaign') -> %s\n"
           "'no one' in banned_words(): %s\n"
           "any multi-word entry in banned_words(): %s\n\n"
           "Extractor A drops every alternative containing a space "
           "(`\" \" not in word`)\nand extractor B cannot read across \\s+, so "
           "NO way of writing this pattern\nmakes it quotable. Same class as "
           "\"many players\"/\"few players\". Not worked around:\na phrase "
           "mechanism for one case would be a second convention, not a fix."
           % (new_verdicts.get("no one finishes the campaign"),
              "no one" in r1["banned"],
              [w for w in r1["banned"] if " " in w]))

    # ---- bw05 THE NEW TEST IS NOT KEYED TO ONE WORD -----------------------
    try:
        swap(original, NEW, HIDE_NOBODY)
        r5 = probe()
        cls5 = " ".join(failed(r5, CLASS_CHECK))
        still_rejects = bool(r5["verdicts"].get("nobody finishes the campaign"))
        record("bw05",
               "TEETH: hiding only 'nobody' fails the class check on nobody",
               bool(cls5) and "nobody" in cls5 and "everyone" not in cls5
               and "everyone" in r5["banned"] and "nobody" not in r5["banned"]
               and still_rejects,
               "class-check failures (must name nobody, must NOT name "
               "everyone): %s\n"
               "banned_words() (must hold everyone, not nobody): %s\n"
               "guard still rejects 'nobody finishes the campaign' (must be "
               "True - otherwise\n  the class check would be right to stay "
               "silent, and this control would prove nothing): %s\n\n"
               "full output:\n%s"
               % (failed(r5, CLASS_CHECK), r5["banned"], still_rejects,
                  r5.get("out") or r5.get("error")))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    after = sha(TARGET)
    record("bw06", "prevalence_guard.py restored byte-identical",
           after == before and TARGET.read_text(encoding="utf-8") == original,
           "before %s / after %s" % (before, after))

    bad = [t for t, _, ok in results if not ok]
    print("\n%s" % ("all controls held"
                    if not bad else "FAILED: %s" % ", ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
