"""
Break-then-confirm for the GetAppReviews transport. Each mutation edits the real
pipeline/fetch_reviews.py, must apply exactly once, and must fail a NAMED check in
pipeline/test_review_transport.py. No network, no Gemini quota.

    .venv/bin/python -B evals/mutate_review_transport_2026-11-03.py

STATE-CHANGING WHILE RUNNING: it edits fetch_reviews.py in place, restoring it by
sha. Do not run it to read its usage, and do not run it during a batch.
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "pipeline/fetch_reviews.py"
SUITE = ROOT / "pipeline/test_review_transport.py"
LOGS = ROOT / "evals/mutation-logs"
PY = str(ROOT / ".venv/bin/python")
DONE = "all review transport tests passed"

CASES = [
    ("rt02", "plain query parameters, the silently ignored form",
     '{"input_json": json.dumps(q)}', "q", "nothing as a query parameter"),
    ("rt03", "the Steam-only purchase default",
     "PURCHASE_TYPE_ALL = 1", "PURCHASE_TYPE_ALL = 0", "every purchase type"),
    ("rt04", "recent mapped to Helpful",
     '"recent": {"filter": 1},', '"recent": {"filter": 0},', "recent is filter 1"),
    ("rt05", "Helpful with no date limit, the launch-era flip",
     '"all": {"filter": 0},', '"all": {"filter": 0, "day_range": 0},',
     "all keeps Steam's default window"),
    ("rt06", "off-topic review filter switched off",
     '"review_type": 0,\n',
     '"review_type": 0,\n        "filter_offtopic_activity": False,\n',
     "off-topic reviews stay filtered"),
    ("rt07", "redirects followed again",
     "follow_redirects=False)\n    # There is no", "follow_redirects=True)\n    # There is no",
     "redirects are not followed"),
    ("rt08", "a redirect no longer raises",
     "if not follow_redirects and 300 <= r.status_code < 400:",
     "if False:", "a 302 raises"),
    ("rt09", "the response wrapper left on",
     'data = r.json()["response"]', "data = r.json()", "no response key raises"),
    ("rt10", "minutes no longer bucket",
     '"bucket": bucket_for(at_review_min),',
     '"bucket": bucket_for(round(at_review_min / 60, 1)),',
     "minutes still decide the bucket"),
]


def sha():
    return hashlib.sha256(TARGET.read_bytes()).hexdigest()[:12]


def suite():
    shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
    p = subprocess.run([PY, "-B", str(SUITE)], cwd=str(ROOT), capture_output=True,
                       text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


results = []


def record(tag, desc, verdict, detail):
    results.append((tag, verdict))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, verdict, detail), encoding="utf-8")
    print("  %-5s %-16s %s" % (tag, verdict, desc), flush=True)


before = sha()
rc, out = suite()
record("rt01", "CONTROL: nothing mutated, suite green",
       "PASS" if rc == 0 and DONE in out else "CONTROL FAILED", out[-400:])

for tag, desc, old, new, expect in CASES:
    original = TARGET.read_bytes()
    text = original.decode("utf-8")
    if text.count(old) != 1:
        record(tag, desc, "MUTATION DID NOT APPLY", "%d occurrences" % text.count(old))
        continue
    try:
        TARGET.write_text(text.replace(old, new), encoding="utf-8")
        rc, out = suite()
    finally:
        TARGET.write_bytes(original)
    # A crash before the checks ran is not a caught mutation: require the suite to
    # have reached its own named output, and the expected check to read FAIL.
    failed = [ln.strip() for ln in out.splitlines() if ln.rstrip().endswith("FAIL")]
    named = [ln for ln in failed if expect in ln]
    if "transport:" not in out:
        verdict = "SUITE DID NOT RUN"
    elif rc == 0:
        verdict = "NOTHING FAILED"
    elif named:
        verdict = "CAUGHT+NAMED"
    else:
        verdict = "RED, WRONG NAME"
    record(tag, desc, verdict, "expected: %s\n%s\n%s"
           % (expect, "\n".join(failed[:10]), out[-500:] if not failed else ""))

shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
same = sha() == before
print("\nfetch_reviews.py restored byte-identical: %s (%s)" % (same, before))
bad = [t for t, v in results if v not in ("PASS", "CAUGHT+NAMED")]
print("%d/%d as expected%s" % (len(results) - len(bad), len(results),
                               ("; NOT: %s" % ", ".join(bad)) if bad else ""))
sys.exit(1 if bad or not same else 0)
