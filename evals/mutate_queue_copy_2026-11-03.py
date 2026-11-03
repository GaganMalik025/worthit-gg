"""
Break-then-confirm for the queue fallback copy. Puts each old false string back into
the real component, and the named test must fail. STATE-CHANGING WHILE RUNNING: it
edits GenerationProgress.tsx in place, restoring it by sha.

    .venv/bin/python -B evals/mutate_queue_copy_2026-11-03.py
"""
import hashlib, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
T = ROOT / "site/components/GenerationProgress.tsx"
CASES = [
    ("the 48-hour promise back", "We can&rsquo;t generate this one right now. Try again tomorrow.",
     "Request it and it&rsquo;ll be here within 48 hours."),
    ("the 'I want this one' label gone", "I want this one", "Request verdict"),
]
sha = lambda: hashlib.sha256(T.read_bytes()).hexdigest()[:12]
def run():
    p = subprocess.run([str(ROOT / "site/node_modules/.bin/vitest"), "run",
                        "lib/__tests__/queue-copy.contract.test.tsx"],
                       cwd=str(ROOT / "site"), capture_output=True, text=True, timeout=120)
    return p.returncode, re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)
before, bad = sha(), 0
rc, out = run()
ok = rc == 0 and re.search(r"Tests\s+2 passed", out)
print("CONTROL  %s" % ("PASS" if ok else "FAILED")); bad += not ok
for name, old, new in CASES:
    orig = T.read_bytes(); text = orig.decode()
    assert text.count(old) == 1, name
    try:
        T.write_text(text.replace(old, new)); rc, out = run()
    finally:
        T.write_bytes(orig)
    ok = rc != 0 and re.search(r"Tests\s+.*failed", out) and "the queue fallback copy" in out
    print("%-14s %s" % ("CAUGHT+NAMED" if ok else "NOT CAUGHT", name)); bad += not ok
print("restored byte-identical: %s" % (sha() == before))
sys.exit(1 if bad or sha() != before else 0)
