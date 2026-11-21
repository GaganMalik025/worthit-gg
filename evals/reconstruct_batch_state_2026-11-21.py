"""
Rebuild data/batch_state.json after the 2026-11-21 mutation run destroyed it.

What happened: evals/mutate_inflight_reservation_2026-11-21.py case ir05 skipped
the admission check, so a test's stub title reached run_batch.record(), and the
test had not redirected run_batch.STATE. save_state() wrote a one-record dict over
the real file, which held refresh night 4's 32 records, UNCOMMITTED. No backup
existed (no snapshot, no editor history). BACKLOG 2026-11-21.

Sources, all on disk:
  - HEAD:data/batch_state.json      every record and run through night 3, byte-exact
  - evals/batch-2026-11-21.txt      night 4's per-title line: title, seconds (whole
                                    seconds - the original kept one decimal), calls
  - site/public/verdicts/<id>.json  appid + game_name; its mtime is the moment the
                                    candidate was written, ~1 s before run_title
                                    stamped `at` (QR-4 runs in between)

Every rebuilt night-4 record carries "reconstructed": true. The night-4 run entry
takes its `started` from the wrapper's header line, which precedes the original
by the remote-ledger read (seconds).

Cross-check, required: the model_calls sequence of the night-4 records in file
order must equal the one read from the REAL file minutes before it was lost.

    .venv/bin/python -B evals/reconstruct_batch_state_2026-11-21.py --run

Run ONCE, before the Far Cry 5 refresh was reverted (owner decision A, same day).
Afterwards only 31 verdict files differ from HEAD, so a rerun stops at its 32-file
assertion instead of rewriting the state. That is intended.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if "--run" not in sys.argv[1:]:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data/batch_state.json"
LOG = ROOT / "evals/batch-2026-11-21.txt"
VERDICTS = ROOT / "site/public/verdicts"

# read from the real file with jq at 2026-11-21 ~04:3xZ, before it was overwritten
REAL_SEQUENCE = [11, 12, 13, 18, 14, 14, 12, 7, 15, 12, 11, 8, 15, 14, 10, 11,
                 11, 17, 16, 16, 13, 14, 11, 16, 11, 8, 9, 10, 14, 13, 13, 15]

head = json.loads(subprocess.run(["git", "show", "HEAD:data/batch_state.json"],
                                 cwd=ROOT, capture_output=True, text=True,
                                 check=True).stdout)

text = LOG.read_text(encoding="utf-8")
started = re.search(r"started (\S+Z) ===", text).group(1)
pending = int(re.search(r"\| (\d+) titles pending", text).group(1))
lines = re.findall(r"^  \[ok  \] (.{38}) +(\d+)s +(\d+) calls", text, re.M)
assert len(lines) == 32, len(lines)

changed = subprocess.run(["git", "diff", "--name-only", "HEAD", "--",
                          "site/public/verdicts"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
by_prefix = {}
for rel in changed:
    v = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    by_prefix.setdefault(v["game_name"][:38].rstrip(), []).append((v, ROOT / rel))
assert len(changed) == 32, len(changed)

state = json.loads(json.dumps(head))
seen, new_keys = set(), 0
for name, secs, calls in lines:
    hits = by_prefix.get(name.rstrip(), [])
    assert len(hits) == 1, (name, len(hits))
    v, path = hits[0]
    appid = str(v["appid"])
    # a title with no earlier record (never batch-generated) becomes a new key,
    # appended in completion order - which is what record() did
    assert appid not in seen, appid
    new_keys += appid not in state["titles"]
    seen.add(appid)
    at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    state["titles"][appid] = {
        "title": v["game_name"], "outcome": "ok", "published": True,
        "model_calls": int(calls), "seconds": float(secs),
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "refresh": True,
        "reconstructed": True}

last = dict(head["runs"][-1])
last.update(started=started, pending=pending)
state["runs"].append(last)

seq = [e["model_calls"] for e in state["titles"].values()
       if e.get("reconstructed")]
print("records rebuilt: %d (%d new keys), calls %d, runs %d -> %d"
      % (len(seen), new_keys, sum(seq), len(head["runs"]), len(state["runs"])))
print("sequence matches the real file's: %s" % (seq == REAL_SEQUENCE))
if seq != REAL_SEQUENCE:
    print("  rebuilt: %s" % seq)
    sys.exit(1)
STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
print("written: %s" % STATE.relative_to(ROOT))
