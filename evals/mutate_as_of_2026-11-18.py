"""
Break-then-confirm for the "As of <date>" line on verdict pages (owner, 2026-11-18).
Each mutation edits one source file and must fail a NAMED check in
site/lib/__tests__/as-of-date.contract.test.tsx. Offline.

    .venv/bin/python -B evals/mutate_as_of_2026-11-18.py --run

Edits sources in place and restores them by sha. Without --run it prints this and
exits 2. Output: evals/mutate-as-of-2026-11-18.txt.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

if "--run" not in sys.argv[1:]:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SUITE = "lib/__tests__/as-of-date.contract.test.tsx"
OUT = ROOT / "evals/mutate-as-of-2026-11-18.txt"
PAGE = "site/components/VerdictPage.tsx"
LIB = "site/lib/verdict.ts"

BLOCK = ('      {asOfDate(v.generated_at) ? (\n'
         '        <p className="as-of mono">As of {asOfDate(v.generated_at)}</p>\n'
         '      ) : null}\n')

CASES = [
    ("ao02", "the line is removed", PAGE, [(BLOCK, "")],
     "shows the generated date, matching the footer"),
    ("ao03", "months are off by one", LIB,
     [("const month = MONTHS[Number(m[2]) - 1];", "const month = MONTHS[Number(m[2])];")],
     "formats the UTC date as D Mon YYYY"),
    ("ao04", "a malformed date still renders a line", PAGE,
     [("      {asOfDate(v.generated_at) ? (\n", "      {true ? (\n")],
     "renders nothing, not 'As of null'"),
    ("ao05", "a malformed date is not rejected", LIB,
     [("  if (!m) return null;\n", '  if (!m) return "null";\n')],
     "returns null for anything malformed"),
    ("ao06", "the line moves below the playtime bars", PAGE,
     [(BLOCK, ""),
      ("      </section>\n      </header>",
       '      </section>\n      <p className="as-of mono">As of {asOfDate(v.generated_at)}</p>\n'
       "      </header>")],
     "sits after the verdict stamp and before the playtime bars"),
]


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12]


def run():
    p = subprocess.run(["npx", "vitest", "run", SUITE], cwd=str(ROOT / "site"),
                       capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


files = sorted({c[2] for c in CASES})
before = {f: sha(f) for f in files}
lines, bad = [], []
rc, out = run()
ok = rc == 0 and "Tests " in out
lines.append("  ao01  %-16s CONTROL: suite green, unmutated" % ("PASS" if ok else "CONTROL FAILED"))
bad += [] if ok else ["ao01"]
for tag, desc, rel, edits, expect in CASES:
    target = ROOT / rel
    original = target.read_bytes()
    text = original.decode("utf-8")
    missing = [o for o, _ in edits if text.count(o) != 1]
    if missing:
        lines.append("  %s  %-16s %s" % (tag, "DID NOT APPLY", desc))
        bad.append(tag)
        continue
    for o, n in edits:
        text = text.replace(o, n)
    try:
        target.write_text(text, encoding="utf-8")
        rc, out = run()
    finally:
        target.write_bytes(original)
    failed = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("FAIL", "×"))]
    named = [ln for ln in failed if expect in ln]
    verdict = ("SUITE DID NOT RUN" if "Tests " not in out else "NOTHING FAILED" if rc == 0
               else "CAUGHT+NAMED" if named else "RED, WRONG NAME")
    if verdict != "CAUGHT+NAMED":
        bad.append(tag)
    lines.append("  %s  %-16s %s" % (tag, verdict, desc))
restored = {f: sha(f) == before[f] for f in files}
lines += ["", "restored byte-identical: " + ", ".join("%s %s" % kv for kv in restored.items()),
          "%d/%d as expected%s" % (len(CASES) + 1 - len(bad), len(CASES) + 1,
                                   ("; NOT: %s" % ", ".join(bad)) if bad else "")]
print("\n".join(lines))
OUT.write_text("mutate_as_of_2026-11-18.py --run\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
sys.exit(0 if not bad and all(restored.values()) else 1)
