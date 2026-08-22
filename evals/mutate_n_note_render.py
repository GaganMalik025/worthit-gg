"""Mutation proof for the n_note render guard (BACKLOG 2026-08-17).

The entry names the exact future mistake it is worried about: "wiring
`{c.n_note}` into the muted branch instead of rebuilding the string". So the
mutation is not an invented perturbation - it is that edit, applied to the real
VerdictPage.tsx, and the guard must go RED and NAME the leak rather than merely
failing somewhere.

n02 is the case that matters most and is easy to leave out. The guard's
assertions are all `not.toContain`, which a component rendering nothing at all
would satisfy, and the fixture only helps if it genuinely has a muted cohort.
So n02 removes the muted cohort from the fixture and requires the guard's own
vacuity checks to catch it. A guard that cannot tell "nothing leaked" from
"nothing was tested" is not yet a guard.

Zero Gemini cost: this runs vitest over committed JSON. Nothing builds a client.

Run:  .venv/bin/python evals/mutate_n_note_render.py
Logs: evals/mutation-logs/n01..n03.log
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
SITE = ROOT / "site"
PAGE = SITE / "components/VerdictPage.tsx"
TEST = SITE / "lib/__tests__/n-note-never-renders.contract.test.tsx"
SPEC = "lib/__tests__/n-note-never-renders.contract.test.tsx"

LOGS.mkdir(exist_ok=True)
results = []


def record(tag, desc, ok, detail):
    results.append((tag, desc, ok))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, "PASS" if ok else "FAIL", detail),
        encoding="utf-8")
    print("  %-4s %-58s %s" % (tag, desc[:58], "ok" if ok else "** FAILED **"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def vitest():
    pr = subprocess.run(["npx", "vitest", "run", SPEC],
                        capture_output=True, text=True, cwd=str(SITE),
                        timeout=600)
    return pr.returncode, pr.stdout + pr.stderr


# The real muted label, verbatim from VerdictPage.tsx.
GOOD = '''                {b.muted
                  ? `${b.pool_n} reviews · too few to call`
                  : `· based on ${b.pool_n} reviews`}'''
# The entry's predicted mistake: read the preformatted diagnostic instead.
LEAK = '''                {b.muted
                  ? (v.cohorts.find((c) => c.bucket === b.bucket)?.n_note ?? "")
                  : `· based on ${b.pool_n} reviews`}'''

page_src = PAGE.read_text()
test_src = TEST.read_text()
sha_page, sha_test = sha(PAGE), sha(TEST)

print("\nn_note render guard")

# --- control: green before anything is touched
rc, out = vitest()
record("n00", "control: the guard is green on the real tree", rc == 0,
       out[-1500:])

try:
    # --- n01: wire the diagnostic into the muted branch
    assert page_src.count(GOOD) == 1, "muted label not found verbatim"
    PAGE.write_text(page_src.replace(GOOD, LEAK))
    rc, out = vitest()
    # Require the LEAK ASSERTION by name, not merely a red run or the sentinel
    # appearing somewhere in a diff dump. Under this mutation the canary and the
    # pool-figure check also fail - because the label they look for was replaced
    # - and either of those alone would turn the suite red while proving nothing
    # about whether the diagnostic reached the page.
    leak_named = "no part of n_note reaches the markup" in out
    sentinel_shown = ("N-NOTE-SENTINEL-DO-NOT-RENDER" in out) or ("8675309" in out)
    record("n01", "leaking {c.n_note} into the muted branch is CAUGHT and NAMED",
           rc != 0 and leak_named and sentinel_shown,
           "rc=%s\nleak assertion named: %s\nsentinel visible in output: %s\n\n%s"
           % (rc, leak_named, sentinel_shown, out[-2500:]))
    PAGE.write_text(page_src)

    # --- n02: the vacuity case. Strip the muted cohort from the fixture and
    # require the guard's own checks to notice it has nothing to test.
    stripped = test_src.replace(
        "    if (c.muted) {",
        "    if (c.muted && false) {   // mutation: nothing is muted any more",
        1)
    assert stripped != test_src, "muted branch not found in the test"
    TEST.write_text(stripped)
    rc, out = vitest()
    caught = "vacuous" in out or "muted" in out.lower()
    record("n02", "a fixture with no muted cohort is caught as vacuous",
           rc != 0 and caught,
           "rc=%s\n\n%s" % (rc, out[-2500:]))
    TEST.write_text(test_src)

    # --- n03: the canary. A page that renders nothing satisfies every
    # not.toContain, so the guard has to prove its searches can hit.
    gutted = page_src.replace("      <main className=\"main-col\">",
                              "      <main className=\"main-col\">{null && (", 1)
    if gutted != page_src:
        gutted = gutted.replace("      </main>", ")}</main>", 1)
        PAGE.write_text(gutted)
        rc, out = vitest()
        record("n03", "a page that renders nothing fails the canary", rc != 0,
               "rc=%s\n\n%s" % (rc, out[-2000:]))
        PAGE.write_text(page_src)
    else:
        record("n03", "a page that renders nothing fails the canary", False,
               "could not locate <main className=\"main-col\"> to gut")
finally:
    PAGE.write_text(page_src)
    TEST.write_text(test_src)

record("n04", "VerdictPage.tsx and the test restored byte-identical",
       sha(PAGE) == sha_page and sha(TEST) == sha_test,
       "page %s -> %s\ntest %s -> %s"
       % (sha_page, sha(PAGE), sha_test, sha(TEST)))

rc, out = vitest()
record("n05", "guard green again after every mutation", rc == 0, out[-800:])

print("\n%d/%d cases as expected" % (sum(1 for _, _, ok in results if ok),
                                     len(results)))
failed = [t for t, _, ok in results if not ok]
if failed:
    print("FAILED: %s   (see evals/mutation-logs/)" % ", ".join(failed))
    sys.exit(1)
