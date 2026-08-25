"""Mutation proof for the 2026-08-25 absolute-quantifier split (invariant 11).

BACKLOG 2026-08-21 left "free access to all content" as a known-open false
positive: RuneScape's synthesis attempt 2 was rejected on it. The old rule made
CROWD optional -

    \\b(?:all|every|everyone|nobody|no\\s+one|none)\\s*CROWD?\\b(?!\\s+(?:mission|level|run))

- so "all" fired with no crowd noun at all. The split requires CROWD for the
quantifiers that can scope CONTENT (all/every/none-of), and keeps the
people-inherent ones (everyone/nobody/no one) bare.

WHY THIS CAMPAIGN HAS TWO CONTROLS INSTEAD OF ONE
-------------------------------------------------
A guard change can fail in both directions and the tests for one direction are
blind to the other.

  q06 over-frees: delete the patterns entirely. Everything this file asserts
      about content PASSING still passes, so without q06 a fix that freed `all`
      completely would look identical to the correct one.

  q07 under-covers: delete ONLY the bare-"none" rule. This is not a
      hypothetical - the first draft of the plan had exactly this gap. Requiring
      "none of the CROWD" silently narrowed the guard, because the old optional
      CROWD had been catching bare "none recommend the sequel" and no test case
      in the draft used that form. It was caught in review, not by a test, so it
      now gets a control of its own.

Run:  .venv/bin/python evals/mutate_prevalence_all_2026-08-25.py
Logs: evals/mutation-logs/q01..q09.log
"""
import hashlib
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
TARGET = ROOT / "pipeline/prevalence_guard.py"

LOGS.mkdir(exist_ok=True)
results = []

POPULATION = [
    "all players recommend this",
    "every player hits this bug",
    "all reviewers mention the grind",
    "every gamer will bounce off it",
    "none of the players finish it",
    "none of the reviewers recommend it",
    "none recommend the sequel",          # bare - the q07 case
    "none finish the campaign",           # bare - the q07 case
    "everyone agrees the combat is good",
    "nobody finishes the campaign",
    "no one recommends the DLC",
]
CONTENT = [
    "you expect free access to all content",
    "all content is locked behind a subscription",
    "all achievements require a subscription",
    "the game unlocks all weapons early",
    "every mission ends the same way",
    "none of the DLC is worth it",
    "none of the levels are memorable",
]

PROBE = r'''
import json, sys
sys.path.insert(0, %(pipeline)r)
import prevalence_guard as pg
out = {"reject": {}, "banned": pg.banned_words()}
for t in %(phrases)r:
    hits = pg.check_claim(t)
    out["reject"][t] = [list(h) for h in hits]
print("PROBE_JSON " + json.dumps(out))
'''


def probe():
    src = PROBE % {"pipeline": str(ROOT / "pipeline"),
                   "phrases": POPULATION + CONTENT}
    r = subprocess.run([PY, "-c", src], capture_output=True, text=True)
    line = [l for l in r.stdout.splitlines() if l.startswith("PROBE_JSON ")]
    if not line:
        return {"error": (r.stdout + r.stderr)[-1200:]}
    import json
    return json.loads(line[0][len("PROBE_JSON "):])


def record(tag, desc, ok, detail):
    results.append((tag, desc, ok))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, "PASS" if ok else "FAIL", detail),
        encoding="utf-8")
    print("  %-4s %-58s %s" % (tag, desc[:58], "ok" if ok else "** FAILED **"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


# Anchors carry their own indentation. The 2026-08-21 filter bug (RESULTS.md)
# came from an indentation-blind match rewriting the wrong copy of a line.
# The whole replaced region, read out of the real file between two stable
# comment anchors rather than reassembled from the pattern lines - the lines are
# separated by explanatory comments, so a concatenated anchor is not contiguous.
def _block(text):
    a = text.index("    # Absolute quantifiers, split 2026-08-25")
    b = text.index("    # Consensus language:")
    return text[a:b]


BARE_NONE = '''    (r"\\bnone\\b(?!\\s+of\\b)", "absolute quantifier"),\n'''
OLD_RULE = '''    (r"\\b(?:all|every|everyone|nobody|no\\s+one|none)\\s*" + CROWD + r"?\\b(?!\\s+(?:mission|level|run))",
     "absolute quantifier"),

'''


def swap(original, find, replace, expect=1):
    if original.count(find) != expect:
        raise SystemExit("anchor x%d, expected %d: %r"
                         % (original.count(find), expect, find[:60]))
    TARGET.write_text(original.replace(find, replace), encoding="utf-8")


def named(r, phrases, want_reject):
    """Return (ok, per-phrase detail) asserting each phrase BY NAME."""
    lines, ok = [], True
    for t in phrases:
        got = bool(r["reject"].get(t))
        good = got == want_reject
        ok &= good
        lines.append("  %-8s %-46s %s" % ("REJECT" if got else "pass", t,
                                          "" if good else "<<< WRONG"))
    return ok, "\n".join(lines)


def main():
    before, original = sha(TARGET), TARGET.read_text(encoding="utf-8")
    print("mutate_prevalence_all_2026-08-25  (prevalence_guard.py sha %s)\n" % before)
    base_banned = None

    try:
        # ---- CONTROL: the pre-split rule, back in the real file -----------
        swap(original, _block(original), OLD_RULE)
        r = probe()
        hit = r["reject"].get("you expect free access to all content")
        record("q01", "CONTROL pre-split: 'all content' is still REJECTED",
               bool(hit), "hits: %s\n(this is RuneScape's real attempt-2 string)" % hit)
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # ---- the fixed file, as committed -----------------------------------
    r = probe()
    base_banned = r["banned"]
    record("q02", "FIXED: 'free access to all content' PASSES",
           not r["reject"].get("you expect free access to all content"),
           "hits: %s" % r["reject"].get("you expect free access to all content"))

    hits = r["reject"].get("all players recommend this")
    record("q03", "FIXED: 'all players recommend this' still REJECTED",
           bool(hits) and hits[0][1] == "absolute quantifier", "hits: %s" % hits)

    ok, detail = named(r, POPULATION, True)
    record("q04", "population battery (11) all REJECTED, asserted by name", ok, detail)

    ok, detail = named(r, CONTENT, False)
    record("q05", "content battery (7) all PASS - 'none of X' not swallowed", ok, detail)

    # ---- VACUITY: free everything; the population half must break --------
    try:
        swap(original, _block(original), "")
        r2 = probe()
        broke, detail = named(r2, POPULATION, True)
        record("q06", "VACUITY: deleting the rules turns the population battery RED",
               not broke, detail)
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # ---- NARROWING: drop ONLY bare-none; the two bare cases must break ----
    try:
        swap(original, BARE_NONE, "")
        r3 = probe()
        bare = ["none recommend the sequel", "none finish the campaign"]
        leaked = [t for t in bare if not r3["reject"].get(t)]
        still = [t for t in POPULATION if t not in bare and not r3["reject"].get(t)]
        record("q07",
               "NARROWING: dropping bare-'none' leaks exactly those 2, by name",
               leaked == bare and not still,
               "leaked: %s\nother population phrases still rejected: %s"
               % (leaked, not still))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    r4 = probe()
    expected = sorted(set(base_banned))
    record("q08", "banned_words() is prior set + {'none'}, nothing more",
           r4["banned"] == expected and "none" in r4["banned"],
           "banned_words(): %s" % r4["banned"])

    after = sha(TARGET)
    record("q09", "prevalence_guard.py restored byte-identical (sha %s)" % after,
           after == before and TARGET.read_text(encoding="utf-8") == original,
           "before=%s after=%s" % (before, after))

    bad = [t for t, _, o in results if not o]
    print("\n%d/%d cases passed%s"
          % (len(results) - len(bad), len(results),
             "" if not bad else "  ** FAILED: %s **" % ", ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
