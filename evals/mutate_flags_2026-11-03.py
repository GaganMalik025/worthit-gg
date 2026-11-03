"""
Break-then-confirm for the flag strip and BBCode stripping. Each mutation edits a real
file, must apply once, and must fail a NAMED test. STATE-CHANGING WHILE RUNNING: it
edits site/ files in place, restoring them by sha. No network, no quota.

    .venv/bin/python -B evals/mutate_flags_2026-11-03.py
"""
import hashlib, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TEST = "lib/__tests__/flags-and-fonts.contract.test.tsx"
CASES = [
    ("flags never rendered, the original defect", "components/VerdictPage.tsx",
     "{v.distortion_flags.map((f) => <FlagStrip key={f.flag_id} flag={f} />)}", "",
     "a segmentation flag shows its sentence"),
    ("evidence open by default", "components/VerdictPage.tsx",
     "<details>\n        <summary className=\"toggle\">", "<details open>\n        <summary className=\"toggle\">",
     "evidence is closed by default"),
    ("a flag with no sentence still renders", "components/VerdictPage.tsx",
     "if (!flag.sentence || rows.length === 0) return null;", "if (rows.length === 0) return null;",
     "no sentence, no strip"),
    ("a flag with no figures still renders", "components/VerdictPage.tsx",
     "if (!flag.sentence || rows.length === 0) return null;", "if (!flag.sentence) return null;",
     "no figures, no strip"),
    ("a rate loses its denominator", "lib/verdict.ts",
     "`${pct.toFixed(1)}% positive, based on ${n(count)} reviews`;", "`${pct.toFixed(1)}% positive${count ? \"\" : \"\"}`;",
     "also has its count"),
    ("a raw field name in the markup", "components/VerdictPage.tsx",
     "<dt>{label}</dt>", "<dt>{label} pool_n</dt>", "no raw field name"),
    ("BBCode shown raw again", "components/Receipts.tsx",
     "{stripBBCode(cit.review_text)}", "{cit.review_text}", "the page uses it"),
    ("BBCode pattern eats a reviewer's brackets", "lib/verdict.ts",
     "|\\*)\\]/gi;", "|\\*|[^\\]]*)\\]/gi;", "leaves a reviewer's own brackets"),
    ("mono font not used", "app/globals.css",
     ".mono{font-family:var(--font-mono),", ".mono{font-family:", "the layout loads all three faces"),
]
def run():
    p = subprocess.run([str(SITE / "node_modules/.bin/vitest"), "run", TEST, "--reporter=verbose"],
                       cwd=str(SITE), capture_output=True, text=True, timeout=120)
    return p.returncode, re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()[:12]
files = {SITE / c[1] for c in CASES}
before = {f: sha(f) for f in files}
rc, out = run()
ok = rc == 0 and re.search(r"Tests\s+\d+ passed", out) and "failed" not in out
print("CONTROL  %s" % ("PASS" if ok else "FAILED")); bad = 0 if ok else 1
for desc, rel, old, new, expect in CASES:
    path = SITE / rel; orig = path.read_bytes(); text = orig.decode()
    if text.count(old) != 1:
        print("NOT APPLIED  %s (%d)" % (desc, text.count(old))); bad += 1; continue
    try:
        path.write_text(text.replace(old, new)); rc, out = run()
    finally:
        path.write_bytes(orig)
    failed = [l for l in out.splitlines() if "FAIL" in l or l.strip().startswith("×")]
    if not re.search(r"^\s*Tests\s", out, re.M): v = "SUITE DID NOT RUN"
    elif rc == 0: v = "NOTHING FAILED"
    elif any(expect in l for l in failed): v = "CAUGHT+NAMED"
    else: v = "RED, WRONG NAME"
    bad += v != "CAUGHT+NAMED"
    print("%-16s %s" % (v, desc), flush=True)
same = all(sha(f) == before[f] for f in files)
print("restored byte-identical: %s" % same)
sys.exit(1 if bad or not same else 0)
