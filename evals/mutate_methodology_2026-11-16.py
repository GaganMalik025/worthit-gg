"""
Break-then-confirm for the methodology page's 2026-11-16 update: each mutation edits
site/app/methodology/page.tsx once and must fail a NAMED check in
site/lib/__tests__/methodology.contract.test.tsx. Offline.

    .venv/bin/python -B evals/mutate_methodology_2026-11-16.py --run

Edits the page in place and restores it by sha. Without --run it prints this and
exits 2. Output: evals/mutate-methodology-2026-11-16.txt.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

if "--run" not in sys.argv[1:]:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site/app/methodology/page.tsx"
SUITE = "lib/__tests__/methodology.contract.test.tsx"
OUT = ROOT / "evals/mutate-methodology-2026-11-16.txt"

CASES = [
    ("mt02", "the QR-4 figure stays at the old 3 November count",
     "0 in 28,073 citations", "0 in 28,331 citations",
     "the citation count is the committed QR-4 run"),
    ("mt03", "the pilot figure is overstated",
     '<span className="mono">5</span> of the', '<span className="mono">4</span> of the',
     "the meaning-check pilot figure is the committed comparison"),
    ("mt04", "the page claims the catalog is fully regenerated",
     "Pages are being regenerated with it over the coming weeks.",
     "Every page has been regenerated with it.",
     "it says the catalog is still being regenerated"),
    ("mt05", "the judge-vs-person QR-1 figure is understated",
     "they agreed on all 10 for the first check", "they agreed on 9 of 10 for the first check",
     "the judge-vs-person figures are the committed 10-case comparison"),
]


def run():
    p = subprocess.run(["npx", "vitest", "run", SUITE], cwd=str(ROOT / "site"),
                       capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


sha = lambda: hashlib.sha256(PAGE.read_bytes()).hexdigest()[:12]  # noqa: E731
before, lines, bad = sha(), [], []
rc, out = run()
ok = rc == 0 and "Tests " in out
lines.append("  mt01  %-16s CONTROL: suite green, unmutated" % ("PASS" if ok else "CONTROL FAILED"))
bad += [] if ok else ["mt01"]
for tag, desc, old, new, expect in CASES:
    original = PAGE.read_bytes()
    text = original.decode("utf-8")
    if text.count(old) != 1:
        lines.append("  %s  %-16s %s" % (tag, "DID NOT APPLY", desc))
        bad.append(tag)
        continue
    try:
        PAGE.write_text(text.replace(old, new), encoding="utf-8")
        rc, out = run()
    finally:
        PAGE.write_bytes(original)
    failed = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("FAIL", "×"))]
    named = [ln for ln in failed if expect in ln]
    verdict = ("SUITE DID NOT RUN" if "Tests " not in out else "NOTHING FAILED" if rc == 0
               else "CAUGHT+NAMED" if named else "RED, WRONG NAME")
    if verdict != "CAUGHT+NAMED":
        bad.append(tag)
    lines.append("  %s  %-16s %s" % (tag, verdict, desc))
same = sha() == before
lines += ["", "page restored byte-identical: %s (%s)" % (same, before),
          "%d/%d as expected%s" % (len(CASES) + 1 - len(bad), len(CASES) + 1,
                                   ("; NOT: %s" % ", ".join(bad)) if bad else "")]
print("\n".join(lines))
OUT.write_text("mutate_methodology_2026-11-16.py --run\n\n" + "\n".join(lines) + "\n",
               encoding="utf-8")
sys.exit(0 if not bad and same else 1)
