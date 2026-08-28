"""Break-then-confirm driver for site/lib/__tests__/home-link.contract.test.tsx.

A green suite is not evidence the suite works. This mutates VerdictPage.tsx in
the three ways the home link could realistically regress and asserts the
contract test FAILS on each, then restores the file byte-for-byte and asserts it
passes again.

    .venv/bin/python evals/mutate_home_link_2026_08_28.py

Writes nothing but its own stdout; the captured run lives in
evals/home-link-mutations-2026-08-28.txt.
"""
import hashlib
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "site/components/VerdictPage.tsx"
TESTFILE = "lib/__tests__/home-link.contract.test.tsx"

LINK = '''      <a className="site-home" href="/">
        WorthIt.gg
      </a>
'''


def run_test():
    p = subprocess.run(
        ["npm", "test", "--", TESTFILE],
        cwd=ROOT / "site", capture_output=True, text=True)
    tail = [l for l in p.stdout.splitlines()
            if re.search(r"Tests\s+|Test Files\s+|✓|×|FAIL", l)]
    return p.returncode, tail


MUTATIONS = {
    "M1 link deleted entirely": lambda s: s.replace(LINK, ""),
    "M2 link moved inside the case column": lambda s: (
        s.replace(LINK, "").replace(
            '      <div className="case-col">\n',
            '      <div className="case-col">\n' + LINK)),
    "M3 anchor emptied (icon-only, no accessible name)": lambda s: s.replace(
        LINK,
        '      <a className="site-home" href="/">\n      </a>\n'),
    "M4 href changed to a non-home route": lambda s: s.replace(
        'className="site-home" href="/"',
        'className="site-home" href="/methodology"'),
}


def main():
    original = TARGET.read_text(encoding="utf-8")
    digest = hashlib.sha256(original.encode()).hexdigest()
    print("target      : %s" % TARGET.relative_to(ROOT))
    print("sha256 before: %s\n" % digest)

    rc, tail = run_test()
    print("=== UNMUTATED (must PASS) -> rc=%d" % rc)
    for l in tail:
        print("   " + l.strip())
    if rc != 0:
        print("\nABORT: the suite is not green before mutating.")
        return 1
    print()

    failures = 0
    for name, mutate in MUTATIONS.items():
        mutated = mutate(original)
        if mutated == original:
            print("=== %s -> MUTATION DID NOT APPLY (driver bug)" % name)
            failures += 1
            continue
        TARGET.write_text(mutated, encoding="utf-8")
        try:
            rc, tail = run_test()
        finally:
            TARGET.write_text(original, encoding="utf-8")
        verdict = "CAUGHT (test failed, as required)" if rc != 0 else \
                  "NOT CAUGHT -- THE TEST IS BLIND TO THIS"
        print("=== %s -> rc=%d  %s" % (name, rc, verdict))
        for l in tail:
            print("   " + l.strip())
        print()
        if rc == 0:
            failures += 1

    after = hashlib.sha256(TARGET.read_text(encoding="utf-8").encode()).hexdigest()
    print("sha256 after : %s  (restored: %s)" % (after, after == digest))
    rc, tail = run_test()
    print("=== RESTORED (must PASS again) -> rc=%d" % rc)
    for l in tail:
        print("   " + l.strip())
    if rc != 0 or after != digest:
        failures += 1

    print("\n%s" % ("ALL MUTATIONS CAUGHT" if failures == 0
                    else "%d PROBLEM(S)" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
