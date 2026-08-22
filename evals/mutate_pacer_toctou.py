"""Reproduction + mutation proof for the TOCTOU race in model_pacer._locked.

BACKLOG 2026-08-16. The pre-fix probe is

    age = time.time() - lock.stat().st_mtime if lock.exists() else 0

two syscalls against a path another process is racing to rmdir(). When the
holder releases in that window, stat() raises FileNotFoundError, it propagates
out of _locked, and the child dies BEFORE CHARGING. live_quota.charge() uses
this same helper (live_quota.py:397), so the blast radius is every Gemini charge
in the project, not just the pacer.

WHY THE WINDOW IS FORCED RATHER THAN WAITED FOR
-----------------------------------------------
The entry measured the race at roughly 1-in-13 with the 12-process fixture. A
1-in-13 gamble is not a reproduction: a green run tells you nothing, and a red
one arrives without the evidence. So `Path.stat` is patched, for the lock path
only, to ACTUALLY rmdir the directory on first call and then delegate to the
real stat. The FileNotFoundError therefore comes from the operating system, on a
directory that genuinely is not there - not from an injected raise - and the
interleaving is exactly "the holder released inside the probe".

That injection is also agnostic to which syscall the code uses. It fires on the
pre-fix code (after exists() returns True) and on the fixed code (which calls
stat directly), so one harness exercises both sides of the change.

t05 asserts the LEDGER COUNT, not an exit code and not a console line. A process
that dies before charging exits non-zero and prints a traceback; a process that
charges twice exits zero. Only the number in the file distinguishes them, and
reading the artifact rather than the report is the lesson from g10/g11
(BACKLOG 2026-08-21) applied here.

Run:  .venv/bin/python evals/mutate_pacer_toctou.py
Logs: evals/mutation-logs/t01..t05.log
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
TARGET = ROOT / "pipeline/model_pacer.py"
CAPTURE = Path(__file__).resolve().parent / "pacer-toctou-2026-08-22.txt"

sys.path.insert(0, str(ROOT / "pipeline"))
LOGS.mkdir(exist_ok=True)
results = []


def record(tag, desc, ok, detail):
    results.append((tag, desc, ok))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, "PASS" if ok else "FAIL", detail),
        encoding="utf-8")
    print("  %-4s %-56s %s" % (tag, desc[:56], "ok" if ok else "** FAILED **"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# The injection, run in a child process so the patch cannot leak into this one
# and so the pre-fix and post-fix bodies are exercised by a fresh interpreter.
# ---------------------------------------------------------------------------
PROBE = r'''
import json, os, sys, time, traceback
from pathlib import Path
sys.path.insert(0, %(pipeline)r)
import model_pacer

target = Path(%(path)r + ".lock")
mode = %(mode)r

if mode in ("vanish", "stale", "held"):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()                       # a holder owns the lock

if mode == "stale":
    old = time.time() - (model_pacer.LOCK_TIMEOUT + 60)
    os.utime(target, (old, old))         # ...and abandoned it long ago

if mode == "vanish":
    # THE RACE, forced. The first stat() on the lock path removes the directory
    # for real and then calls the real stat() on it, so the OS raises
    # FileNotFoundError on a path that genuinely no longer exists - precisely
    # what a holder releasing mid-probe produces.
    real_stat = Path.stat
    fired = []
    def racing_stat(self, *a, **kw):
        if str(self) == str(target) and not fired:
            fired.append(1)
            try:
                os.rmdir(str(target))
            except OSError:
                pass
        return real_stat(self, *a, **kw)
    Path.stat = racing_stat

if mode == "held":
    import threading
    def release():
        time.sleep(0.4)
        try:
            os.rmdir(str(target))
        except OSError:
            pass
    threading.Thread(target=release, daemon=True).start()

t0 = time.time()
try:
    with model_pacer._locked(%(path)r, timeout=%(timeout)s):
        held = target.exists()
    print(json.dumps({"ok": True, "acquired": held,
                      "seconds": round(time.time() - t0, 2)}))
except BaseException:
    print(json.dumps({"ok": False, "traceback": traceback.format_exc()}))
'''


def probe(mode, timeout=5.0):
    """Run one _locked() attempt in a child. Returns the parsed result dict."""
    import json
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "q.json")
        code = PROBE % {"pipeline": str(ROOT / "pipeline"), "path": path,
                        "mode": mode, "timeout": timeout}
        pr = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                            timeout=120)
        out = (pr.stdout or "").strip().splitlines()
        payload = json.loads(out[-1]) if out else {
            "ok": False, "traceback": "no output; stderr=%s" % pr.stderr}
        payload["_rc"] = pr.returncode
        payload["_stderr"] = pr.stderr
        return payload


def charge_race(n=12):
    """n concurrent live_quota.charge(1) children. Returns (ledger, failures).

    The ledger figure is the point. A child that dies in the lock exits
    non-zero AND leaves the count short, and only the second of those is what
    the production failure actually costs.
    """
    import json
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "q.json"
        code = ("import sys;sys.path.insert(0,%r);import live_quota;"
                "live_quota.charge(1, ledger='batch', path=%r)"
                % (str(ROOT / "pipeline"), str(path)))
        procs = [subprocess.Popen([PY, "-c", code], stderr=subprocess.PIPE)
                 for _ in range(n)]
        failures = []
        for pr in procs:
            err = pr.communicate(timeout=120)[1]
            if pr.returncode != 0:
                failures.append((pr.returncode,
                                 (err or b"").decode("utf-8", "replace")))
        import live_quota
        ledger = live_quota.load(str(path))["batch_used"]
        return ledger, failures


# ---------------------------------------------------------------------------
FIXED = '''            # ONE syscall, guarded. This was `lock.stat() if lock.exists()`
            # - two syscalls against a path another process is racing to
            # rmdir(), so a holder releasing in that window made stat() raise
            # FileNotFoundError, which propagated out of _locked and killed the
            # child BEFORE IT CHARGED. live_quota.charge() shares this helper,
            # so that cost a real request with nothing recorded against it.
            # Captured in CI run 31956075631; see BACKLOG 2026-08-16.
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                # The holder released between our mkdir and this probe, so
                # there is no lock left to age. Not stale - just gone. Fall
                # through rather than `continue`, so the overall timeout below
                # is still checked on every pass.
                age = 0'''
BROKEN = '''            age = time.time() - lock.stat().st_mtime if lock.exists() else 0'''

src = TARGET.read_text()
sha_before = sha(TARGET)
patched = FIXED in src

print("\nmodel_pacer._locked - the lock vanishing inside the age probe")
print("  target carries the %s probe" % ("FIXED" if patched else "PRE-FIX"))


def with_body(body_is_fixed):
    """Put the requested probe body into the REAL file."""
    cur = TARGET.read_text()
    want, other = (FIXED, BROKEN) if body_is_fixed else (BROKEN, FIXED)
    if want in cur:
        return
    assert other in cur, "neither probe body found in model_pacer.py"
    TARGET.write_text(cur.replace(other, want))


try:
    # --- t01 CONTROL: the pre-fix body must die, and we keep the traceback
    with_body(False)
    res = probe("vanish")
    tb = res.get("traceback", "")
    hit = (not res["ok"]) and "FileNotFoundError" in tb and "_locked" in tb
    CAPTURE.write_text(
        "Captured %s, evals/mutate_pacer_toctou.py case t01.\n"
        "PRE-FIX model_pacer._locked, lock removed inside the age probe.\n"
        "This traceback is from this run, not copied from BACKLOG.\n\n%s"
        % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tb or res),
        encoding="utf-8")
    record("t01", "CONTROL pre-fix probe dies on a vanished lock", hit,
           "rc=%s\n\n%s" % (res.get("_rc"), tb or res))

    # --- OBSERVATION, deliberately not a case. Running the 12-process charge
    # race against the pre-fix body samples a ~1-in-13 event, so it lands 12/12
    # most nights. Asserting on it would be a coin flip, and hardcoding it True
    # would be a case that cannot fail - the exact vacuity this file exists to
    # avoid. t01 is the control that actually proves the defect; this only
    # records what one sample of the production shape looked like.
    pre_ledger, pre_failures = charge_race()
    (LOGS / "t05-prefix-observation.log").write_text(
        "OBSERVATION (not a pass/fail case)\n"
        "pre-fix body, 12 concurrent live_quota.charge(1)\n\n"
        "ledger=%d of 12, %d child(ren) died\n\n%s"
        % (pre_ledger, len(pre_failures),
           (pre_failures[0][1][-600:] if pre_failures
            else "(the race did not fire in this sample - expected at ~1-in-13)")),
        encoding="utf-8")
    print("  --   observation: pre-fix charge race landed %d of 12, %d died"
          % (pre_ledger, len(pre_failures)))

    # --- fixed body from here on
    with_body(True)

    res = probe("vanish")
    record("t02", "post-fix acquires instead of raising",
           res["ok"] and res.get("acquired") is True,
           "rc=%s  %s" % (res.get("_rc"), res.get("traceback") or res))

    res = probe("stale")
    record("t03", "post-fix STILL breaks a genuinely stale lock",
           res["ok"] and res.get("acquired") is True,
           "age=0 on a vanished lock must not disable stale-breaking\n%s"
           % (res.get("traceback") or res))

    res = probe("held")
    record("t04", "post-fix still BLOCKS on a live holder, then acquires",
           res["ok"] and res.get("acquired") is True
           and res.get("seconds", 0) >= 0.3,
           "waited %ss for a holder releasing at 0.4s\n%s"
           % (res.get("seconds"), res.get("traceback") or res))

    ledger, failures = charge_race()
    record("t05", "post-fix: 12 concurrent charges all land in the LEDGER",
           ledger == 12 and not failures,
           "ledger=%d of 12 (this is the file, not an exit code)\n"
           "children that died: %d\n\n%s"
           % (ledger, len(failures),
              (failures[0][1][-600:] if failures else "(none)")))
finally:
    TARGET.write_text(src)
    sha_after = sha(TARGET)

record("t06", "model_pacer.py restored byte-identical",
       sha_before == sha_after,
       "sha before=%s after=%s" % (sha_before, sha_after))

print("\n%d/%d cases as expected" % (sum(1 for _, _, ok in results if ok),
                                     len(results)))
print("captured traceback: %s" % CAPTURE.relative_to(ROOT))
failed = [t for t, _, ok in results if not ok]
if failed:
    print("FAILED: %s   (see evals/mutation-logs/)" % ", ".join(failed))
    sys.exit(1)
