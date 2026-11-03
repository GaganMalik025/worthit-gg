"""
Break-then-confirm for the methodology page. Each mutation edits a real file and must
fail a NAMED test. STATE-CHANGING WHILE RUNNING: it edits site/ in place, restoring by
sha. No network, no quota.

    .venv/bin/python -B evals/mutate_methodology_2026-11-03.py
"""
import hashlib, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAGE = "app/methodology/page.tsx"
CASES = [
    ("QR-1 figure inflated", PAGE, "47 of 70 fully, 23 partly", "60 of 70 fully, 10 partly", "QR-1 is the committed judge run"),
    ("two-reviews figure inflated", PAGE, '"59 of 70"', '"69 of 70"', "the two-reviews check"),
    ("citation count stale", PAGE, "0 in 28,331 citations", "0 in 30,000 citations", "the citation count"),
    ("the bad round quietly dropped", PAGE, "agreed on only 3 of 10", "agreed less", "the disappointing results"),
    ("Death Stranding rate wrong", PAGE, ">95.3%<", ">99.3%<", "the Death Stranding example"),
    ("verdict footer link gone", "components/VerdictPage.tsx", '<a href="/methodology">how this works &rarr;</a>', "how this works", "every verdict footer"),
    ("home footer back to plain text", "components/Home.tsx", '<a href="/methodology">how this works &rarr;</a>', "how this works &rarr;", "the home footer"),
    ("left out of the sitemap", "app/sitemap.ts", "    { url: `${SITE_URL}/methodology` },\n", "", "the sitemap lists it"),
]
def run():
    p = subprocess.run([str(SITE / "node_modules/.bin/vitest"), "run",
                        "lib/__tests__/methodology.contract.test.tsx", "--reporter=verbose"],
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
