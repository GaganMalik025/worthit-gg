#!/usr/bin/env bash
#
# Proves pipeline/run_batch_logged.sh actually captures run_batch.py's exit
# code into the batch log - and, just as importantly, proves the shape it
# replaces does NOT, so that a green result here means something.
#
# The bar is not "the wrapper runs". The bar is that the pre-fix shape is
# demonstrably wrong on the same input: a batch that exits 3 must be recorded
# as 3 by the wrapper and as 0 by the naive `| tee ; echo $?`. If both recorded
# 3, the wrapper would be decoration.
#
# Drives the REAL wrapper rather than a restatement of it: the file is copied
# byte-for-byte into a throwaway repo whose .venv/bin/python is a stub that
# exits with $STUB_RC. The wrapper cd's to $(dirname $0)/.., so it operates
# entirely inside that temp repo and never touches this one.
#
# Usage:  evals/verify_batch_rc_capture.sh
# Exits 0 only if every case below matches its expectation.

WRAPPER="$(cd "$(dirname "$0")/.." && pwd)/pipeline/run_batch_logged.sh"
fails=0

if [ ! -f "$WRAPPER" ]; then
  echo "FATAL: wrapper not found at $WRAPPER"
  exit 2
fi
echo "wrapper under test: $WRAPPER"
echo "sha256: $(shasum -a 256 "$WRAPPER" | cut -d' ' -f1)"
echo

# Build a throwaway repo: pipeline/<real wrapper>, a stub python, an evals dir.
make_repo() {
  local root; root="$(mktemp -d)"
  mkdir -p "$root/pipeline" "$root/.venv/bin" "$root/evals"
  cp "$WRAPPER" "$root/pipeline/run_batch_logged.sh"
  chmod +x "$root/pipeline/run_batch_logged.sh"
  cat >"$root/.venv/bin/python" <<'STUB'
#!/usr/bin/env bash
# Stands in for the real batch: prints a clean-looking summary block, then
# exits with STUB_RC. The clean summary is the point - it is what an inferred
# "exit 0" would have been read off.
echo "107 attempted in 38.2 min: {\"stage_failed\": 1, \"ok\": 45}"
echo "  published     : 45"
echo "  batch budget  : 1 of 400 left, live reserve 100 untouched"
exit "${STUB_RC:-0}"
STUB
  chmod +x "$root/.venv/bin/python"
  touch "$root/pipeline/run_batch.py"
  echo "$root"
}

log_of() { echo "$1/evals/batch-$(date +%Y-%m-%d).txt"; }

check() { # name expected actual
  if [ "$2" = "$3" ]; then
    echo "  PASS  $1: $3"
  else
    echo "  FAIL  $1: expected $2, got $3"
    fails=$((fails + 1))
  fi
}

# ---------------------------------------------------------------- case 1
# A batch that fails (stage_failed -> rc 1, or any non-zero) must be recorded
# as non-zero by the wrapper, in the log, and in the wrapper's own exit status.
echo "case 1: batch exits 3, via the wrapper"
r="$(make_repo)"
STUB_RC=3 "$r/pipeline/run_batch_logged.sh" >/dev/null 2>&1
check "wrapper exit status" "3" "$?"
check "EXIT_RC line in log" "EXIT_RC=3" \
  "$(grep -o 'EXIT_RC=[0-9]*' "$(log_of "$r")" | tail -1)"
check "summary block still logged" "1" \
  "$(grep -c 'published     : 45' "$(log_of "$r")")"
rm -rf "$r"
echo

# ---------------------------------------------------------------- case 2
# THE CONTROL. The shape being replaced, on the identical stub. If this
# records 3, the wrapper fixes nothing and case 1 proves nothing.
echo "case 2: CONTROL - same failing batch through the pre-fix shape"
r="$(make_repo)"
(
  cd "$r" || exit 2
  set +o pipefail
  STUB_RC=3 .venv/bin/python -u pipeline/run_batch.py 2>&1 \
    | tee -a "evals/batch-$(date +%Y-%m-%d).txt" >/dev/null
  echo "EXIT_RC=$?" >>"evals/batch-$(date +%Y-%m-%d).txt"
)
naive="$(grep -o 'EXIT_RC=[0-9]*' "$(log_of "$r")" | tail -1)"
check "pre-fix shape misreports as 0" "EXIT_RC=0" "$naive"
if [ "$naive" = "EXIT_RC=3" ]; then
  echo "  !! control did not reproduce the bug - case 1 proves nothing"
  fails=$((fails + 1))
fi
rm -rf "$r"
echo

# ---------------------------------------------------------------- case 3
# A genuinely clean night must still record 0 - the wrapper must not simply
# report failure always, which would pass cases 1 and 2 for the wrong reason.
echo "case 3: batch exits 0, via the wrapper"
r="$(make_repo)"
STUB_RC=0 "$r/pipeline/run_batch_logged.sh" >/dev/null 2>&1
check "wrapper exit status" "0" "$?"
check "EXIT_RC line in log" "EXIT_RC=0" \
  "$(grep -o 'EXIT_RC=[0-9]*' "$(log_of "$r")" | tail -1)"
rm -rf "$r"
echo

# ---------------------------------------------------------------- case 4
# Appending, not truncating: a second run on the same date must not destroy
# the first run's raw output.
echo "case 4: a second same-day run preserves the first run's log"
r="$(make_repo)"
STUB_RC=1 "$r/pipeline/run_batch_logged.sh" >/dev/null 2>&1
STUB_RC=0 "$r/pipeline/run_batch_logged.sh" >/dev/null 2>&1
check "both runs' codes present" "2" \
  "$(grep -c 'EXIT_RC=' "$(log_of "$r")")"
check "first run's code survives" "1" \
  "$(grep -c 'EXIT_RC=1' "$(log_of "$r")")"
rm -rf "$r"
echo

if [ "$fails" -eq 0 ]; then
  echo "ALL CASES PASSED - wrapper records the real code, pre-fix shape does not"
  exit 0
fi
echo "$fails CHECK(S) FAILED"
exit 1
