"""
Break-then-confirm for the catalog refresh (run_batch.py --refresh, 2026-11-16).

Each mutation edits ONE real source file, must apply exactly once per replacement,
and must fail a NAMED check in pipeline/test_refresh.py. A crash before the suite
prints its own output is SUITE DID NOT RUN, never caught. Offline: the suite stubs
every model call, the gate and the ledger.

    .venv/bin/python -B evals/mutate_refresh_2026-11-16.py --run

STATE-CHANGING WHILE RUNNING: it edits pipeline/ sources in place and restores
each by sha. Without --run it prints this and exits 2.
Output: evals/mutate-refresh-2026-11-16.txt, one log per case in
evals/mutation-logs/rf*.log.
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
OUT = ROOT / "evals/mutate-refresh-2026-11-16.txt"
PY = str(ROOT / ".venv/bin/python")
SUITE = "pipeline/test_refresh.py"
DONE = "all refresh tests passed"
MARKER = "selection: which published titles"

RB = "pipeline/run_batch.py"
GO = "pipeline/generate_one.py"
SY = "pipeline/synthesize.py"

CASES = [
    ("rf02", "selection ignores the meaning-check marker", RB,
     [('        if v.get("claims_verified"):\n            continue\n', "")],
     "a verified verdict is not refreshed"),
    ("rf03", "seed games are refreshed by default", RB,
     [("if appid in SEED_APPIDS and not include_seeds:", "if False:")],
     "a seed game is skipped by default"),
    ("rf04", "a gate-failed refresh is retried every night", RB,
     [('if prev.get("refresh") and prev.get("outcome") in REFRESH_TERMINAL:', "if False:")],
     "not retried nightly"),
    ("rf05", "refresh order is by appid, not oldest first", RB,
     [('rows.sort(key=lambda r: (r["_at"], r["appid"]))',
       'rows.sort(key=lambda r: r["appid"])')],
     "oldest generated_at first"),
    ("rf06", "the candidate is written straight to the live directory", GO,
     [('out_dir = (wd / "site/public/verdicts") if wd else VERDICTS', "out_dir = VERDICTS")],
     "a QR-4 failure leaves the live page untouched"),
    ("rf07", "a gated candidate is never published", GO,
     [('        publish_candidate(out_path, VERDICTS / ("%s.json" % appid))\n',
       "        pass\n")],
     "a gated candidate replaces the live page"),
    ("rf08", "a stale candidate is not cleared", GO,
     [('        (out_dir / ("%s.json" % appid)).unlink(missing_ok=True)\n', "        pass\n")],
     "a stale candidate from an earlier attempt is never published"),
    ("rf09", "generate() runs the stages in ROOT", GO,
     [("run_stage(script, appid, extra=extra, ledger=ledger, cwd=wd)",
       "run_stage(script, appid, extra=extra, ledger=ledger)")],
     "every stage's cwd is the work dir"),
    ("rf10", "run_stage ignores its cwd", GO,
     [("cwd=str(cwd or ROOT), env=env,", "cwd=str(ROOT), env=env,")],
     "a work-dir stage runs with cwd = the work dir"),
    ("rf11", "the .env key is not passed to a work-dir stage", GO,
     [("            env.setdefault(k, v)\n", "            pass\n")],
     "the key from the repo .env"),
    ("rf12", "the segmentation gate reads ROOT's stored ingest", GO,
     [("struct = cohort_structure(appid, root=wd)", "struct = cohort_structure(appid)")],
     "the segmentation gate judges the work dir's fresh ingest"),
    ("rf13", "the marker is always True", SY,
     [('"claims_verified": bool(claims_blob.get("verified")),', '"claims_verified": True,')],
     "claims_verified is False when"),
    ("rf14", "the budget stop is bypassed", RB,
     [("            if not allowed:\n                stopped = (reason, detail)\n",
       "            if False:\n                stopped = (reason, detail)\n")],
     "with no budget, no title runs"),
    ("rf15", "a refusal is recorded as the title's outcome", RB,
     [('    if result.get("refused"):\n', "    if False:\n")],
     "a refusal leaves the title's history untouched"),
    ("rf16", "a refresh keeps the segmentation gate on", RB,
     [("segmentation_gate=not args.no_gate and not refresh,",
       "segmentation_gate=not args.no_gate,")],
     "a refresh calls generate() with the segmentation gate off"),
    ("rf17", "a gate-dropped refresh is terminal again", RB,
     [('REFRESH_TERMINAL = {"qr4_failed"}', 'REFRESH_TERMINAL = {"thin_segmentation", "qr4_failed"}')],
     "a refresh the segmentation gate dropped is retried"),
    ("rf18", "generate() stops marking a budget refusal", GO,
     [('"fallback": "queue", "refused": True, "model_calls": 0}', '"fallback": "queue"}')],
     "generate() marks a budget refusal as refused"),
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
record("rf01", "CONTROL: %s green, unmutated" % SUITE,
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
summary = ["", "restored byte-identical:"] + [
    "  %-30s %s (%s)" % (f, restored[f], before[f]) for f in files]
summary += ["real state untouched: %s" % ", ".join("%s %s" % kv for kv in untouched.items())]
bad = [t for t, v in results if v not in ("PASS", "CAUGHT+NAMED")]
summary.append("%d/%d as expected%s" % (len(results) - len(bad), len(results),
                                         ("; NOT: %s" % ", ".join(bad)) if bad else ""))
print("\n".join(summary))
OUT.write_text("mutate_refresh_2026-11-16.py --run\n\n" + "\n".join(lines + summary) + "\n",
               encoding="utf-8")
ok = not bad and all(restored.values()) and all(untouched.values())
sys.exit(0 if ok else 1)
