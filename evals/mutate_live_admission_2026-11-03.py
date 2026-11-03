"""
Break-then-confirm for the 2026-11-03 Phase 1-2 work: zero-pool render, appid
validation, the sweep's day filter, /api/generate admission, ledger failures, and
IP hashing. Each mutation edits the REAL file, must apply exactly once, and must
fail a NAMED test. No network, no token, no Gemini quota.

    .venv/bin/python -B evals/mutate_live_admission_2026-11-03.py        # unit cases
    .venv/bin/python -B evals/mutate_live_admission_2026-11-03.py --build

--build adds the two slow cases: a real `next build` with a zero-pool verdict in
place, once with the fix (must pass) and once without (must fail).

Verify-the-verifier rules: a run with no vitest summary line reports SUITE DID NOT
RUN rather than "caught", the failure must carry the expected test name rather than
merely being red, and every touched file is restored and checked by sha.

STATE-CHANGING WHILE RUNNING: it edits site/ files in place. Do not run it to read
its usage, and do not run two at once.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LOGS = ROOT / "evals/mutation-logs"
VITEST = str(SITE / "node_modules/.bin/vitest")

CASES = [
    ("la02", "bar percentage guard removed", "components/VerdictPage.tsx",
     """{b.pct_positive === null || b.pct_positive === undefined
                ? null
                : `${b.pct_positive.toFixed(1)}%`}""",
     "{`${b.pct_positive!.toFixed(1)}%`}",
     "renders on the static path and the proxied path"),
    ("la03", "cohort stats guard removed", "components/VerdictPage.tsx",
     """{c.pct_positive === null || c.pct_positive === undefined
              ? "no reviews in this cohort"
              : `${c.pct_positive.toFixed(1)}% positive, based on ${c.pool_n} reviews`}""",
     "{`${c.pct_positive!.toFixed(1)}% positive, based on ${c.pool_n} reviews`}",
     "renders on the static path and the proxied path"),
    ("la04", "isAppid accepts anything", "lib/verdict.ts",
     r"/^[1-9]\d{0,9}$/.test(String(v))", "/.*/.test(String(v))",
     "rejects everything that could build a path"),
    ("la05", "sweep day filter removed", "lib/github.ts",
     "quotaDay(r.created_at) === state.date &&", "",
     "does not credit a run from an earlier quota day"),
    ("la06", "sweep day keyed on UTC", "lib/quota.ts",
     """new Date(iso).toLocaleDateString("en-CA", { timeZone: PACIFIC });""",
     """new Date(iso).toLocaleDateString("en-CA", { timeZone: "UTC" });""",
     "the day boundary is Pacific"),
    ("la07", "existing verdict not refused", "lib/admission.ts",
     "if (exists.found) {", "if (false as boolean) {",
     "a title deployed on main"),
    ("la08", "unknown title not refused", "lib/admission.ts",
     "if (!known) {", "if (false as boolean) {",
     "a title outside the search index"),
    ("la09", "running title not joined", "lib/admission.ts",
     "if (alreadyRunning(appid, read, runs)) {", "if (false as boolean) {",
     "a title already running joins"),
    ("la10", "failed ledger write ignored", "lib/admission.ts",
     'return fallback("ledger_unwritable");', "",
     "a failed ledger write stops the dispatch"),
    ("la11", "corrupt ledger reads as empty", "lib/github.ts",
     "const parsed: unknown = JSON.parse(value);",
     "let parsed: unknown = {}; try { parsed = JSON.parse(value); } catch {}",
     "corrupt JSON throws"),
    ("la12", "rejected PATCH falls through", "lib/github.ts",
     "if (patch.status !== 404) throw new Error(`quota write: ${patch.status}`);",
     "", "a rejected PATCH throws"),
    ("la13", "GitHub failure reads as absent", "lib/github.ts",
     "if (res.status !== 404) throw new Error(`verdict lookup: ${res.status}`);",
     "", "a GitHub failure is unknown"),
    ("la14", "strict run list goes soft", "lib/github.ts",
     "if (strict) throw new Error(`run list: ${res.status}`);", "",
     "strict throws"),
    ("la15", "client hash is the raw address", "lib/admission.ts",
     'return createHmac("sha256", key).update(ip).digest("hex").slice(0, 16);',
     "return ip;", "no raw address reaches"),
    ("la16", "address back in the dispatch payload", "lib/github.ts",
     "client_payload: { appid: String(appid), quota: snapshot },",
     'client_payload: { appid: String(appid), ip: "x", quota: snapshot },',
     "sends no client address"),
    ("la17", "a lost dispatch still blocks retries", "lib/admission.ts",
     "if (!at || dispatchLost(state, appid, now)) return false;",
     "if (!at) return false;", "past its grace window"),
    ("la18", "a finished run still blocks retries", "lib/admission.ts",
     "return !mine.some(", "return true || !mine.some(", "a fast failure"),
    ("la19", "/api/status guard removed", "app/api/status/route.ts",
     'if (!isAppid(appid)) return NextResponse.json({ error: "appid required" }, { status: 400 });',
     'if (!appid) return NextResponse.json({ error: "appid required" }, { status: 400 });',
     "app/api/status/route.ts"),
    ("la20", "verdict page guard removed", "app/verdict/[appid]/page.tsx",
     "if (!isAppid(appid)) return null;", "", "app/verdict/[appid]/page.tsx"),
]

results = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def run_suite():
    p = subprocess.run([VITEST, "run", "--reporter=verbose"], cwd=str(SITE),
                       capture_output=True, text=True, timeout=300)
    return p.returncode, re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)


def record(tag, desc, verdict, detail):
    results.append((tag, verdict))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, verdict, detail), encoding="utf-8")
    print("  %-5s %-16s %s" % (tag, verdict, desc), flush=True)


def summary(out):
    m = re.search(r"^\s*Tests\s+(.*)$", out, re.M)
    return m.group(1).strip() if m else None


def unit_cases():
    rc, out = run_suite()
    s = summary(out)
    record("la01", "CONTROL: nothing mutated, suite green",
           "PASS" if rc == 0 and s and "failed" not in s else "CONTROL FAILED",
           s or out[-800:])
    for tag, desc, rel, old, new, expect in CASES:
        path = SITE / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            record(tag, desc, "MUTATION DID NOT APPLY",
                   "%d occurrences in %s" % (text.count(old), rel))
            continue
        try:
            path.write_text(text.replace(old, new), encoding="utf-8")
            rc, out = run_suite()
        finally:
            path.write_bytes(original)
        s = summary(out)
        failed = [ln.strip() for ln in out.splitlines()
                  if "FAIL" in ln or ln.strip().startswith("×")]
        named = [ln for ln in failed if expect in ln]
        if s is None:
            verdict = "SUITE DID NOT RUN"
        elif rc == 0:
            verdict = "NOTHING FAILED"
        elif not named:
            verdict = "RED, WRONG NAME"
        else:
            verdict = "CAUGHT+NAMED"
        record(tag, desc, verdict,
               "expected name: %s\nsummary: %s\n%s"
               % (expect, s, "\n".join(failed[:12])))


def build_cases():
    fixture = SITE / "public/verdicts/999999901.json"
    raw = json.loads((SITE / "public/verdicts/219150.json").read_text("utf-8"))
    raw["appid"] = "999999901"
    for row in raw["split_bar"] + raw["cohorts"]:
        if row["bucket"] == "veteran":
            row["pool_n"], row["pct_positive"] = 0, None
    page = SITE / "components/VerdictPage.tsx"
    original = page.read_bytes()
    old = """{b.pct_positive === null || b.pct_positive === undefined
                ? null
                : `${b.pct_positive.toFixed(1)}%`}"""
    new = "{`${b.pct_positive!.toFixed(1)}%`}"

    def build():
        p = subprocess.run(["npm", "run", "build"], cwd=str(SITE),
                           capture_output=True, text=True, timeout=600)
        return p.returncode, re.sub(r"\x1b\[[0-9;]*m", "", p.stdout + p.stderr)

    try:
        fixture.write_text(json.dumps(raw), encoding="utf-8")
        rc, out = build()
        record("la21", "next build, zero-pool verdict present, WITH the fix",
               "PASS" if rc == 0 else "BUILD FAILED", "rc=%d\n%s" % (rc, out[-600:]))
        text = original.decode("utf-8")
        assert text.count(old) == 1
        page.write_text(text.replace(old, new), encoding="utf-8")
        rc, out = build()
        crash = "toFixed" in out
        record("la22", "next build, zero-pool verdict present, WITHOUT the fix",
               "CAUGHT+NAMED" if rc != 0 and crash else
               ("RED, WRONG NAME" if rc != 0 else "NOTHING FAILED"),
               "rc=%d\n%s" % (rc, "\n".join(
                   ln for ln in out.splitlines()
                   if "toFixed" in ln or "Error occurred prerendering" in ln)[:800]))
    finally:
        page.write_bytes(original)
        fixture.unlink(missing_ok=True)


files = sorted({SITE / c[2] for c in CASES} | {SITE / "components/VerdictPage.tsx"})
before = {f: sha(f) for f in files}
print("unit cases", flush=True)
unit_cases()
if "--build" in sys.argv:
    print("build cases", flush=True)
    build_cases()

changed = [str(f) for f in files if sha(f) != before[f]]
print("\nfiles restored byte-identical: %s" % ("NO %s" % changed if changed else "yes"))
good = {"PASS", "CAUGHT+NAMED"}
bad = [t for t, v in results if v not in good]
print("%d/%d as expected%s" % (len(results) - len(bad), len(results),
                               ("; NOT: %s" % ", ".join(bad)) if bad else ""))
sys.exit(1 if bad or changed else 0)
