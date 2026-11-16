#!/usr/bin/env bash
# Pilot for the meaning check + one-reviewer section (owner, 2026-11-16).
#
# Regenerates 4 titles end to end from FRESH Steam reviews, in a working dir inside
# evals/, so the repo's data/raw, data/cache, data/filtered, data/claims and
# site/public/verdicts are not touched. Nothing is published. The owner reads the
# pages before the catalog runs.
#
#   bash evals/pilot_one_reviewer_2026-11-16.sh --spend
#
# STATE-CHANGING: SPENDS GEMINI QUOTA (about 15 calls a title, booked to the batch
# ledger) and calls Steam. Without --spend it prints this and exits 2, so reading
# its usage costs nothing. It refuses to start if the batch budget cannot cover the
# estimate. The API key is read from .env into the environment and never printed.
#
# Output (evals/pilot-one-reviewer-2026-11-16/):
#   pilot.log                 per-title stage exit codes, calls charged, QR-4, EXIT_RC
#   <appid>/*.log             each stage's own output
#   <appid>/out/<appid>.json  the regenerated verdict
#   <appid>/data/             working data (gitignored)
set -u
set -o pipefail
if [ "${1:-}" != "--spend" ]; then sed -n 2,22p "$0"; exit 2; fi

R="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R/.venv/bin/python"
W="$R/evals/pilot-one-reviewer-2026-11-16"
APPIDS="1295660 387290 311690 613100"   # Civ VII, Ori, Enter the Gungeon, House Flipper
EST=60                                  # 4 titles x ~15 calls, before measurement
mkdir -p "$W"
LOG="$W/pilot.log"
: > "$LOG"
say() { echo "$*" | tee -a "$LOG"; }

quota() { "$PY" -B -c "
import sys; sys.path.insert(0, '$R/pipeline')
import live_quota as q
s = q.load(); ok, why, d = q.can_batch(s, est=$EST)
print('%s %s batch_used=%s date=%s' % ('OK' if ok else 'REFUSED', why, s.get('batch_used'), s.get('date')))
sys.exit(0 if ok else 1)"; }
used() { "$PY" -B -c "
import sys; sys.path.insert(0, '$R/pipeline')
import live_quota as q; print(q.load().get('batch_used', 0))"; }
charged() { "$PY" -B -c "
import sys; sys.path.insert(0, '$R/pipeline')
import model_pacer as p; print(p.calls_for('$1'))"; }

say "pilot start $(date -u +%Y-%m-%dT%H:%M:%SZ)"
q="$(quota)"; qrc=$?
say "quota preflight (est $EST): $q"
if [ $qrc -ne 0 ]; then say "EXIT_RC=3"; exit 3; fi

export GEMINI_API_KEY="$("$PY" -B -c "
import re
for l in open('$R/.env', encoding='utf-8'):
    m = re.match(r'^\s*GEMINI_API_KEY\s*=\s*(.*)$', l)
    if m: print(m.group(1).strip().strip('\"\''))")"
if [ -z "$GEMINI_API_KEY" ]; then say "GEMINI_API_KEY missing from .env"; say "EXIT_RC=4"; exit 4; fi
export WORTHIT_LEDGER=batch PYTHONDONTWRITEBYTECODE=1

worst=0
for A in $APPIDS; do
  D="$W/$A"; mkdir -p "$D"; cd "$D" || exit 9
  export WORTHIT_APPID=$A
  u0=$(used); c0=$(charged "$A")
  "$PY" -B "$R/pipeline/fetch_reviews.py" "$A" > fetch.log 2>&1; f=$?
  "$PY" -B "$R/pipeline/filter_reviews.py" "$A" > filter.log 2>&1; fl=$?
  e=-; s=-; g=-
  if [ $f -eq 0 ] && [ $fl -eq 0 ]; then
    "$PY" -B "$R/pipeline/extract_claims.py" "$A" > extract.log 2>&1; e=$?
    if [ "$e" -eq 0 ]; then
      "$PY" -B "$R/pipeline/synthesize.py" "$A" --force-lite --out "$D/out" > synth.log 2>&1; s=$?
    fi
  fi
  if [ -f "$D/out/$A.json" ]; then
    "$PY" -B "$R/pipeline/qr4_gate.py" "$D/out/$A.json" > qr4.log 2>&1; g=$?
  fi
  u1=$(used); c1=$(charged "$A")
  say "$A fetch=$f filter=$fl extract=$e synth=$s qr4=$g batch_ledger=+$((u1-u0)) pacer_calls=+$((c1-c0))"
  for rc in $f $fl $e $s $g; do
    if [ "$rc" != "0" ] && [ "$rc" != "-" ]; then worst=1; fi
    if [ "$rc" = "-" ]; then worst=1; fi
  done
  cd "$R" || exit 9
done
say "pilot end $(date -u +%Y-%m-%dT%H:%M:%SZ) batch_used=$(used)"
say "EXIT_RC=$worst"
exit $worst
