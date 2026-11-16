"""
Break-then-confirm for the meaning check and the one-reviewer section (2026-11-16).

Each mutation edits ONE real source file, must apply exactly once per replacement,
and must fail a NAMED check in the suite that guards it. A crash before the suite
prints its own output is reported as SUITE DID NOT RUN, never as caught. No network,
no Gemini quota: every suite here is offline and its model calls are stubs.

    .venv/bin/python -B evals/mutate_one_reviewer_points_2026-11-16.py --run

STATE-CHANGING WHILE RUNNING: it edits pipeline/ and site/ sources in place and
restores each by sha. It refuses to run without --run, because a driver that runs on
any invocation has already rewritten committed logs once (memory, 2026-11).
Output: evals/mutate-one-reviewer-points-2026-11-16.txt, plus one log per case in
evals/mutation-logs/.
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

if "--run" not in sys.argv[1:]:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LOGS = ROOT / "evals/mutation-logs"
OUT = ROOT / "evals/mutate-one-reviewer-points-2026-11-16.txt"
PY = str(ROOT / ".venv/bin/python")

VERIFY = "pipeline/verify_claims.py"
EXTRACT = "pipeline/extract_claims.py"
SYNTH = "pipeline/synthesize.py"
QR4 = "pipeline/qr4_gate.py"
PAGE = "site/components/VerdictPage.tsx"
LIB = "site/lib/verdict.ts"

PY_VERIFY = ("py", "pipeline/test_claim_verification.py",
             "all claim verification tests passed", "verify: code sorts claims")
PY_GUARDS = ("py", "pipeline/test_batch_guards.py", None,
             "synthesis: unverified claims are refused")
SITE_TEST = ("site", "lib/__tests__/one-reviewer-points.contract.test.tsx", None, "Tests ")

# (tag, description, file, [(old, new), ...], suite, expected failing check name)
CASES = [
    ("or02", "one supporting review is enough for a claim", VERIFY,
     [("if len(backed) >= 2:", "if len(backed) >= 1:")],
     PY_VERIFY, "invariant 3"),
    ("or03", "the model's ids are not intersected with the claim's own", VERIFY,
     [('backed = [rid for rid in cited if rid in {str(x) for x in row.get("supported_by") or []}]',
       'backed = [str(x) for x in row.get("supported_by") or []]')],
     PY_VERIFY, "an invented id does not count"),
    ("or04", "the rewrite need not be singular", VERIFY,
     [('if not text.startswith("One reviewer") or prevalence_guard.check_claim(text):',
       "if not text or prevalence_guard.check_claim(text):")],
     PY_VERIFY, "a plural rewrite is rejected"),
    ("or05", "the rewrite skips the prevalence guard", VERIFY,
     [('if not text.startswith("One reviewer") or prevalence_guard.check_claim(text):',
       'if not text.startswith("One reviewer"):')],
     PY_VERIFY, "prevalence language is rejected"),
    ("or06", "a claim answered twice is accepted", VERIFY,
     [('raise VerifyError("claim %s answered twice" % cid)', "pass")],
     PY_VERIFY, "a claim answered twice raises"),
    ("or07", "a third attempt is allowed", VERIFY,
     [("corpus, attempts=2):", "corpus, attempts=3):")],
     PY_VERIFY, "after one retry, not more"),
    ("or08", "a retry may be served from cache", VERIFY,
     [("if attempt == 0 and path.exists():", "if path.exists():")],
     PY_VERIFY, "a retry after a cached rejection sends a real request"),
    ("or09", "extraction admits one-review claims again", EXTRACT,
     [("        if len(clean) < 2:\n", "        if not clean:\n")],
     PY_VERIFY, "a one-review claim is rejected at extraction"),
    ("or19", "the one-review prompt rule comes back", EXTRACT,
     [("1. Every claim must be supported by at least TWO of the reviews below",
       "1. A point only one review makes is allowed. Every claim must be supported by at least TWO of the reviews below")],
     PY_VERIFY, "the prompt asks for two reviews"),
    ("or10", "the QR-4 gate skips one-reviewer citations", QR4,
     [('            if point.get("citation"):\n', "            if False:\n")],
     PY_VERIFY, "the gate sees the one-reviewer citation"),
    ("or11", "unverified claims synthesize", SYNTH,
     [('if not claims_blob.get("verified") and not getattr(args, "allow_unverified", False):',
       "if False:")],
     PY_GUARDS, "an unverified claims file sends nothing"),
    ("or12", "the section summary carries a count", PAGE,
     [('POINTS MENTIONED IN ONLY SINGLE REVIEWS</span>',
       'POINTS MENTIONED IN ONLY SINGLE REVIEWS ({groups.length})</span>')],
     SITE_TEST, "carries no count"),
    ("or13", "the section renders open", PAGE,
     [('<details className="one-reviewer">', '<details className="one-reviewer" open>')],
     SITE_TEST, "is one closed section"),
    ("or14", "the section moves below the cohorts", PAGE,
     [("      <OneReviewerPoints v={v} />\n", ""),
      ("\n      </main>", "\n      <OneReviewerPoints v={v} />\n      </main>")],
     SITE_TEST, "above the first cohort"),
    ("or15", "points lose their cohort heading", PAGE,
     [("          <h3>{c.label}</h3>\n", "")],
     SITE_TEST, "groups each point"),
    ("or16", "review text rendered outside the receipts expand", PAGE,
     [("              <Receipts\n                appid={v.appid}\n"
       "                verdictWord={v.verdict.word}\n                bucket={c.bucket}\n"
       "                citations={[p.citation]}\n              />\n",
       '              <p className="body">{p.citation.review_text}</p>\n')],
     SITE_TEST, "keeps the review behind the receipts expand"),
    ("or17", "the section renders with no points", PAGE,
     [("  if (!groups.length) return null;\n", "")],
     SITE_TEST, "renders no section"),
    ("or18", "a muted cohort's points render", LIB,
     [("single_points: c.muted\n        ? []", "single_points: false\n        ? []")],
     SITE_TEST, "shows nothing for a muted cohort"),
]


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12]


def run_suite(suite):
    kind, path, done, marker = suite
    if kind == "py":
        shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
        p = subprocess.run([PY, "-B", path], cwd=str(ROOT), capture_output=True,
                           text=True, timeout=600,
                           env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
    else:
        p = subprocess.run(["npx", "vitest", "run", path], cwd=str(SITE),
                           capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def failed_lines(kind, out):
    if kind == "py":
        return [ln.strip() for ln in out.splitlines() if ln.rstrip().endswith("FAIL")]
    return [ln.strip() for ln in out.splitlines()
            if ln.strip().startswith(("FAIL", "×", "✗")) or " > " in ln and "FAIL" in ln]


results = []
lines = []


def record(tag, desc, verdict, detail):
    results.append((tag, verdict))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, verdict, detail), encoding="utf-8")
    line = "  %-5s %-16s %s" % (tag, verdict, desc)
    lines.append(line)
    print(line, flush=True)


LOGS.mkdir(parents=True, exist_ok=True)
files = sorted({c[2] for c in CASES})
before = {f: sha(f) for f in files}

# CONTROLS: every suite green with nothing mutated, and having printed its own output.
for tag, suite in (("or01a", PY_VERIFY), ("or01b", PY_GUARDS), ("or01c", SITE_TEST)):
    rc, out = run_suite(suite)
    ok = rc == 0 and suite[3] in out and (suite[2] is None or suite[2] in out)
    record(tag, "CONTROL: %s green, unmutated" % suite[1],
           "PASS" if ok else "CONTROL FAILED", out[-600:])

for tag, desc, rel, edits, suite, expect in CASES:
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
        rc, out = run_suite(suite)
    finally:
        target.write_bytes(original)
    failed = failed_lines(suite[0], out)
    named = [ln for ln in failed if expect in ln]
    if suite[3] not in out:
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
summary = ["", "restored byte-identical:"] + [
    "  %-40s %s (%s)" % (f, restored[f], before[f]) for f in files]
bad = [t for t, v in results if v not in ("PASS", "CAUGHT+NAMED")]
summary.append("%d/%d as expected%s" % (len(results) - len(bad), len(results),
                                         ("; NOT: %s" % ", ".join(bad)) if bad else ""))
print("\n".join(summary))
OUT.write_text("mutate_one_reviewer_points_2026-11-16.py --run\n\n"
               + "\n".join(lines + summary) + "\n", encoding="utf-8")
sys.exit(1 if bad or not all(restored.values()) else 0)
