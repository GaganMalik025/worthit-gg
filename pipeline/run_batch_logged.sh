#!/usr/bin/env bash
#
# Nightly batch wrapper. Its only job beyond running run_batch.py is to put the
# batch's REAL exit code into the batch log, where a later reader can cite it.
#
# Why this exists
# ---------------
# run_batch.py:323 is
#
#     sys.exit(1 if any(d["outcome"] == "stage_failed" for d in done) else 0)
#
# so a night with any stage failure returns 1 - and run_batch.py never PRINTS
# that value. Its output ends at the summary block. So a log alone cannot tell
# you what the run returned, and "exit 0" written from a clean-looking summary
# is an inference, not an observation. That is exactly what happened in the
# 2026-08-18 and 2026-08-19 RESULTS.md entries; see BACKLOG, 2026-08-20.
#
# The trap that makes it worse: in
#
#     python pipeline/run_batch.py 2>&1 | tee log ; echo $?
#
# $? is TEE's status, not python's. tee returns 0 whenever it can write the
# file, so the recorded code is 0 no matter what the batch did. Measured in
# this repo's shell (zsh 5.9) rather than assumed:
#
#     with pipefail:     ( exit 7 ) | tee /dev/null ; rc=7
#     without pipefail:  ( exit 7 ) | tee /dev/null ; rc=0
#
# Both guards below are therefore deliberate, and are belt-and-braces on
# purpose: `set -o pipefail` makes the pipeline itself carry the failure, and
# PIPESTATUS[0] reads the batch's own status directly regardless. The shebang
# pins bash because PIPESTATUS is 0-indexed in bash and $pipestatus is
# 1-indexed in zsh - this script is wrong under zsh, so it does not run there.
#
# Usage:  pipeline/run_batch_logged.sh [any run_batch.py flags]
# Exits with run_batch.py's own code.

set -o pipefail

cd "$(dirname "$0")/.." || exit 2

DATE="$(date +%Y-%m-%d)"
LOG="evals/batch-${DATE}.txt"

# Append rather than truncate: a second invocation on the same date must not
# destroy the first run's raw output, which is evidence.
{
  echo "=== run_batch.py $* | started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
} >>"$LOG"

.venv/bin/python -u pipeline/run_batch.py "$@" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}

echo "EXIT_RC=${rc}  (run_batch.py, captured under pipefail + PIPESTATUS)" \
  | tee -a "$LOG"

exit "$rc"
