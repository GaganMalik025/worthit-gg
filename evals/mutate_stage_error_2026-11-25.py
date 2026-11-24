"""
Break-then-confirm for keeping a failed stage's error (run_batch.py, 2026-11-25).

Night 5 lost 16 titles with no record of why: run_title dropped the stderr generate()
returned. It is now kept, redacted, because data/batch_state.json is committed. Each
mutation edits ONE real source file, must apply exactly once, and must fail a NAMED
check in pipeline/test_refresh.py. A crash before the suite prints its own output is
SUITE DID NOT RUN, never caught. Offline: the suite stubs the ledger and every call.

    .venv/bin/python -B evals/mutate_stage_error_2026-11-25.py --run

STATE-CHANGING WHILE RUNNING: it edits pipeline/run_batch.py in place and restores it
by sha, and restores the real ledger and batch state after every case. Without --run
it prints this and exits 2.
Output: evals/mutate-stage-error-2026-11-25.txt, one log per case in
evals/mutation-logs/se*.log.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

if "--run" not in sys.argv[1:]:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "evals/mutation-logs"
OUT = ROOT / "evals/mutate-stage-error-2026-11-25.txt"
PY = str(ROOT / ".venv/bin/python")
SUITE = "pipeline/test_refresh.py"
DONE = "all refresh tests passed"
MARKER = "run_title: a refusal is never recorded"

RB = "pipeline/run_batch.py"

CASES = [
    ("se02", "the error is not stored", RB,
     [('        entry["stderr"] = redact(result["stderr"])[-STDERR_KEEP:]\n', "        pass\n")],
     "a stage failure keeps its error in the record"),
    ("se03", "key-shaped tokens are not redacted", RB,
     [('    return _KEY_SHAPES.sub("[REDACTED]", text)\n', "    return text\n")],
     "a key-shaped string is redacted from the record"),
    ("se04", "exact secrets are not redacted", RB,
     [('        text = text.replace(value, "[REDACTED]")\n', "        pass\n")],
     "an exact secret from .env is redacted"),
    ("se05", "the raw stderr is stored", RB,
     [('entry["stderr"] = redact(result["stderr"])[-STDERR_KEEP:]',
       'entry["stderr"] = result["stderr"][-STDERR_KEEP:]')],
     "a key-shaped string is redacted from the record"),
    ("se06", "the log line omits the error", RB,
     [('    if entry.get("stderr"):\n        print(', '    if False:\n        print(')],
     "the log line shows the stage and the error"),
    ("se07", "the log line prints the raw stderr", RB,
     [('last_error_line(entry["stderr"])[:200]', 'result["stderr"]')],
     "the log line never carries the key"),
    ("se08", "the secrets list ignores .env", RB,
     [("    pairs = list(generate_one._dotenv().items()) + list(os.environ.items())\n",
       "    pairs = list(os.environ.items())\n")],
     "the secrets to redact include the .env key"),
    ("se09", "every .env value is treated as a secret", RB,
     [('            if v and len(v) >= 8 and any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET"))]\n',
       '            if v and len(v) >= 8]\n')],
     "but not a .env value whose name is not"),
]


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12]


def run_suite():
    shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
    p = subprocess.run([PY, "-B", SUITE], cwd=str(ROOT), capture_output=True, text=True,
                       timeout=600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return p.returncode, p.stdout + p.stderr


results, lines = [], []


def record(tag, desc, verdict, detail):
    results.append((tag, verdict))
    (LOGS / ("%s.log" % tag)).write_text("%s\n%s\n\n%s\n%s\n" % (tag, desc, verdict, detail),
                                         encoding="utf-8")
    line = "  %-5s %-16s %s" % (tag, verdict, desc)
    lines.append(line)
    print(line, flush=True)


LOGS.mkdir(parents=True, exist_ok=True)
files = sorted({c[2] for c in CASES})
before = {f: sha(f) for f in files}
ledger = ROOT / "data/live_quota.json"
state = ROOT / "data/batch_state.json"
real_state = {p: p.read_bytes() for p in (ledger, state) if p.exists()}

rc, out = run_suite()
record("se01", "CONTROL: %s green, unmutated" % SUITE,
       "PASS" if rc == 0 and DONE in out else "CONTROL FAILED", out[-600:])

for tag, desc, rel, edits, expect in CASES:
    target = ROOT / rel
    original = target.read_bytes()
    text = original.decode("utf-8")
    bad = [old for old, _ in edits if text.count(old) != 1]
    if bad:
        record(tag, desc, "MUTATION DID NOT APPLY",
               "\n".join("%d occurrences of %r" % (text.count(o), o[:80]) for o in bad))
        continue
    mutated = text
    for old, new in edits:
        mutated = mutated.replace(old, new)
    try:
        target.write_text(mutated, encoding="utf-8")
        rc, out = run_suite()
    finally:
        target.write_bytes(original)
        # restore, not just compare: the first run of this driver let ir05 write
        # the real batch_state.json, and only reported it afterwards
        for path, data in real_state.items():
            if path.read_bytes() != data:
                lines.append("  !! %s rewritten during %s - restored" % (path.name, tag))
                print(lines[-1], flush=True)
                path.write_bytes(data)
    failed = [ln.strip() for ln in out.splitlines() if ln.rstrip().endswith("FAIL")]
    named = [ln for ln in failed if expect in ln]
    if MARKER not in out:
        verdict = "SUITE DID NOT RUN"
    elif rc == 0:
        verdict = "NOTHING FAILED"
    elif named:
        verdict = "CAUGHT+NAMED"
    else:
        verdict = "RED, WRONG NAME"
    record(tag, desc, verdict, "file: %s\nexpected: %s\n%s\n%s"
           % (rel, expect, "\n".join(failed[:12]), out[-800:] if not named else ""))

shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
restored = {f: sha(f) == before[f] for f in files}
# a mutation that disabled a stub could reach the real ledger or batch state
untouched = {p.name: p.read_bytes() == b for p, b in real_state.items()}
reached = [ln for ln in lines if ln.startswith("  !! ")]
summary = ["", "restored byte-identical:"] + [
    "  %-30s %s (%s)" % (f, restored[f], before[f]) for f in files]
summary += ["real state untouched: %s" % ", ".join("%s %s" % kv for kv in untouched.items())]
bad = [t for t, v in results if v not in ("PASS", "CAUGHT+NAMED")]
summary.append("%d/%d as expected%s" % (len(results) - len(bad), len(results),
                                         ("; NOT: %s" % ", ".join(bad)) if bad else ""))
print("\n".join(summary))
OUT.write_text("mutate_stage_error_2026-11-25.py --run\n\n" + "\n".join(lines + summary) + "\n",
               encoding="utf-8")
ok = not bad and not reached and all(restored.values()) and all(untouched.values())
sys.exit(0 if ok else 1)
