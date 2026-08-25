"""Mutation proof: a SteamGridDB request_failed must not freeze into a permanent miss.

BACKLOG 2026-08-25. `art.sgdb_grid()` ended in an UNCONDITIONAL
`path.write_text(...)`, so every outcome was cached forever - including
`request_failed`, which is not an answer about the game but a request that never
completed. Four titles from the 2026-08-21 batch (32370, 367500, 239820, 954850)
were frozen that way for four days: their cache read
`{"reason": "request_failed: ConnectTimeout", "url": null}`, `art_block()` calls
`sgdb_grid()` WITHOUT refresh, and `backfill_art.py --broken` worked off a
hardcoded list that could not know about them. Nothing would ever have asked
again.

WHY A CONTROL IS THE LOAD-BEARING HALF
--------------------------------------
"The fix stops caching a timeout" is trivially satisfied by code that caches
NOTHING - and that would silently destroy the property the module was built for:
the docstring's promise that "an obscure title is asked about once and never
again". So the campaign is symmetric. a01 puts the PRE-FIX body back into the
real file and proves the poison is real. a05 is the opposite control: an
over-broad mutation that caches nothing at all, which must turn a03 RED. A
campaign that only proved the timeout is no longer cached would pass on both the
correct fix and a fix that broke the cache entirely.

The network is never touched. `requests.get` is replaced inside a child process
with a scripted sequence, so the ConnectTimeout comes from the same exception
class the real failure produced (`type(exc).__name__ == "ConnectTimeout"`, which
is what art.py formats into the reason string).

Run:  .venv/bin/python evals/mutate_art_cache_2026-08-25.py
Logs: evals/mutation-logs/a01..a05.log
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
TARGET = ROOT / "pipeline/art.py"

LOGS.mkdir(exist_ok=True)
results = []


def record(tag, desc, ok, detail):
    results.append((tag, desc, ok))
    (LOGS / ("%s.log" % tag)).write_text(
        "%s\n%s\n\n%s\n%s\n" % (tag, desc, "PASS" if ok else "FAIL", detail),
        encoding="utf-8")
    print("  %-4s %-58s %s" % (tag, desc[:58], "ok" if ok else "** FAILED **"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


PROBE = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, %(pipeline)r)
import requests
import art

art.CACHE_DIR = Path(%(cache)r)
art._key = lambda: "probe-key-not-a-real-credential"
time.sleep = lambda *a, **k: None          # collapse the exponential backoff

MODE, APPID = %(mode)r, "999001"
calls = {"n": 0}


class Resp:
    def __init__(self, code, payload):
        self.status_code, self._p = code, payload
    def json(self):
        return self._p


GOOD = {"success": True,
        "data": [{"url": "https://cdn2.steamgriddb.com/grid/PROBE.png",
                  "nsfw": False, "humor": False}]}


def fake_get(url, headers=None, timeout=None):
    calls["n"] += 1
    if MODE == "timeout_always":
        raise requests.exceptions.ConnectTimeout("probe")
    if MODE == "timeout_then_ok":
        # art.SGDB_ATTEMPTS attempts fail, i.e. the whole of call 1; anything
        # after that is call 2, which succeeds.
        if calls["n"] <= art.SGDB_ATTEMPTS:
            raise requests.exceptions.ConnectTimeout("probe")
        return Resp(200, GOOD)
    if MODE == "not_found":
        return Resp(404, {})
    return Resp(200, GOOD)


art.requests.get = fake_get

out = {"returns": [], "calls_after": []}
for _ in range(%(times)d):
    out["returns"].append(art.sgdb_grid(APPID))
    out["calls_after"].append(calls["n"])

p = Path(%(cache)r) / APPID / "steamgriddb.json"
out["cache_exists"] = p.exists()
out["cache_reason"] = json.loads(p.read_text())["reason"] if p.exists() else None
out["cache_url"] = json.loads(p.read_text())["url"] if p.exists() else None
print("PROBE_JSON " + json.dumps(out))
'''


def probe(mode, times):
    with tempfile.TemporaryDirectory() as tmp:
        src = PROBE % {"pipeline": str(ROOT / "pipeline"), "cache": tmp,
                       "mode": mode, "times": times}
        r = subprocess.run([PY, "-c", src], capture_output=True, text=True)
        line = [l for l in r.stdout.splitlines() if l.startswith("PROBE_JSON ")]
        if not line:
            return {"error": (r.stdout + r.stderr)[-1500:]}
        return json.loads(line[0][len("PROBE_JSON "):])


# --------------------------------------------------------------------------
# The pre-fix body, matched at its own indent level. The 2026-08-21 filter bug
# (RESULTS.md) came from an indentation-blind substring match that rewrote the
# wrong copy of a duplicated line; these anchors carry their leading spaces.
# --------------------------------------------------------------------------
FIXED_GUARD = """    if not _is_cacheable(reason):
"""
# guard never fires  -> every outcome is written: the pre-fix body exactly
PRE_FIX = """    if False:
"""
# guard always fires -> nothing is ever written: the over-broad "fix"
NEVER_CACHE = """    if True:
"""


def mutate(find, replace, expect=1):
    s = TARGET.read_text(encoding="utf-8")
    if s.count(find) != expect:
        raise SystemExit("anchor appears %d times, expected %d:\n%r"
                         % (s.count(find), expect, find))
    TARGET.write_text(s.replace(find, replace), encoding="utf-8")


def main():
    before = sha(TARGET)
    print("mutate_art_cache_2026-08-25  (art.py sha %s)\n" % before)
    original = TARGET.read_text(encoding="utf-8")

    # ---- the fixed file, as committed -----------------------------------
    r = probe("timeout_then_ok", 2)
    ok = (r["returns"][0] is None and r["calls_after"][0] == 3
          and r["returns"][1] == "https://cdn2.steamgriddb.com/grid/PROBE.png"
          and r["calls_after"][1] == 4
          and r["cache_exists"] and r["cache_reason"] == "ok")
    record("a02", "FIXED: a timeout is not cached, and the next run self-heals",
           ok, json.dumps(r, indent=1))

    r = probe("not_found", 2)
    ok = (r["returns"] == [None, None] and r["calls_after"] == [1, 1]
          and r["cache_exists"] and r["cache_reason"] == "not_found")
    record("a03", "FIXED: a real 404 IS still cached - asked once, never again",
           ok, json.dumps(r, indent=1))

    r = probe("ok", 2)
    ok = (r["calls_after"] == [1, 1] and r["cache_reason"] == "ok"
          and r["returns"][0] == r["returns"][1] ==
          "https://cdn2.steamgriddb.com/grid/PROBE.png")
    record("a04", "FIXED: a hit is cached and replayed without a second request",
           ok, json.dumps(r, indent=1))

    # ---- CONTROL: put the pre-fix body back and watch it poison ----------
    try:
        mutate(FIXED_GUARD, PRE_FIX)
        r = probe("timeout_then_ok", 2)
        ok = (r["returns"] == [None, None] and r["calls_after"] == [3, 3]
              and r["cache_exists"]
              and r["cache_reason"] == "request_failed: ConnectTimeout")
        record("a01", "CONTROL pre-fix: timeout cached, call 2 never asks again",
               ok, json.dumps(r, indent=1))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    # ---- VACUITY CONTROL: cache nothing at all; a03 must go RED ----------
    try:
        mutate(FIXED_GUARD, NEVER_CACHE)
        r = probe("not_found", 2)
        broke_a03 = not (r["cache_exists"] and r["calls_after"] == [1, 1])
        record("a05", "VACUITY: caching nothing breaks a03 (asked twice)",
               broke_a03, json.dumps(r, indent=1))
    finally:
        TARGET.write_text(original, encoding="utf-8")

    after = sha(TARGET)
    record("a06", "art.py restored byte-identical (sha %s)" % after,
           after == before and TARGET.read_text(encoding="utf-8") == original,
           "before=%s after=%s" % (before, after))

    bad = [t for t, _, o in results if not o]
    print("\n%d/%d cases passed%s"
          % (len(results) - len(bad), len(results),
             "" if not bad else "  ** FAILED: %s **" % ", ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
