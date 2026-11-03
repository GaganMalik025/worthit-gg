#!/usr/bin/env bash
# Fresh Helldivers 2 generation in a temp working dir. data/raw, data/cache,
# data/filtered and data/claims in the repo are not touched. Output to temp first.
set -u
R=/Users/gaganmalik/Downloads/worthit-gg
W=$1
mkdir -p "$W"; cd "$W" || exit 9
export WORTHIT_APPID=553850 WORTHIT_LEDGER=batch PYTHONDONTWRITEBYTECODE=1
export GEMINI_API_KEY="$("$R/.venv/bin/python" -B -c "
import re
for l in open('$R/.env',encoding='utf-8'):
    m=re.match(r'^\s*GEMINI_API_KEY\s*=\s*(.*)$',l)
    if m: print(m.group(1).strip().strip('\"\''))")"
PY="$R/.venv/bin/python"
"$PY" "$R/pipeline/fetch_reviews.py" 553850 > fetch.log 2>&1; echo "fetch rc=$?"
"$PY" "$R/pipeline/filter_reviews.py" 553850 > filter.log 2>&1; echo "filter rc=$?"
"$PY" "$R/pipeline/extract_claims.py" 553850 > extract.log 2>&1; echo "extract rc=$?"
"$PY" "$R/pipeline/synthesize.py" 553850 --force-lite --out "$W/out" > synth.log 2>&1; echo "synth rc=$?"
