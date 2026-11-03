"""
Offline measurements behind the 2026-11-03 full codebase analysis.

Zero Gemini cost, no network, writes nothing outside a temp dir. Reads the
committed verdicts, the local page cache (data/cache, gitignored, so that section
reports what is on THIS machine) and the batch logs. Prints COUNTS and ids only:
no review text and no wordlist term ever reaches the output.

    .venv/bin/python -B evals/measure_codebase_analysis_2026-11-03.py
"""

import collections
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "pipeline"))

import model_pacer  # noqa: E402
import prevalence_guard  # noqa: E402
from filter_reviews import (WORDLIST_DIR, block_pattern, load_terms,  # noqa: E402
                            normalize_for_match, soft_pattern)

block_terms = load_terms(WORDLIST_DIR / "block_en.txt")
blocked = block_pattern(block_terms)
soft = soft_pattern(load_terms(WORDLIST_DIR / "ldnoobw_en.txt"), set(block_terms))
BBCODE = re.compile(r"\[/?[a-zA-Z][^\]]{0,40}\]")

c = collections.Counter()
words = collections.Counter()
dense = []
soft_titles = set()
for f in sorted(glob.glob("site/public/verdicts/*.json")):
    v = json.load(open(f, encoding="utf-8"))
    c["verdicts"] += 1
    words[v["verdict"]["word"]] += 1
    if v.get("distortion_flags"):
        c["verdicts_with_flags"] += 1
        c["flags"] += len(v["distortion_flags"])
    c["null_pct_bars"] += sum(1 for b in v["split_bar"]
                              if b.get("pct_positive") is None)
    prose = [v["verdict"].get("tagline")] + v["verdict"]["for_you_if"] \
        + v["verdict"]["not_for_you_if"] \
        + [fl.get("sentence") for fl in v.get("distortion_flags") or []]
    n_claims = 0
    for co in v["cohorts"]:
        prose.append(co.get("summary"))
        cohort_claims = 0
        if not co["muted"] and not co.get("summary"):
            c["unmuted_cohorts_no_summary"] += 1
        for t in co["themes"]:
            for cl in t["claims"]:
                cohort_claims += 1
                c["claims"] += 1
                prose.append(cl["claim"])
                if re.search(r"\d", cl["claim"]):
                    c["claims_with_a_digit"] += 1
                for ci in cl["citations"]:
                    c["citations"] += 1
                    txt = ci.get("review_text") or ""
                    if BBCODE.search(txt):
                        c["citations_with_raw_bbcode"] += 1
                    if "♥" in txt:
                        c["citations_with_hearts"] += 1
                    if soft.search(normalize_for_match(txt)):
                        c["citations_matching_annotate_only_list"] += 1
                        soft_titles.add(v["appid"])
                    h = txt.count("♥")
                    if h >= 3 and h / len(txt) >= 0.02:
                        dense.append((v["appid"], ci["recommendationid"],
                                      bool(ci.get("truncated"))))
        n_claims += cohort_claims
        if not co["muted"] and cohort_claims == 0:
            c["unmuted_cohorts_no_claims"] += 1
    if n_claims == 0:
        c["verdicts_with_zero_claims"] += 1
    for text in filter(None, prose):
        if blocked.search(normalize_for_match(text)):
            c["model_prose_hitting_blocklist"] += 1
        if prevalence_guard.check_claim(text):
            c["model_prose_hitting_prevalence_guard"] += 1

print("== committed verdicts")
for k in sorted(c):
    print("  %-42s %d" % (k, c[k]))
print("  %-42s %d" % ("titles_with_annotate_only_match", len(soft_titles)))
print("  word mix: %s" % dict(words))
print("  citations over the filter's heart-density rule (appid, id, truncated): %s"
      % dense)

print("\n== playtime_at_review in cached raw pages (this machine)")
total = missing = zero = 0
for d in glob.glob("data/cache/[0-9]*"):
    seen = set()
    for p in glob.glob(d + "/*_*.json"):
        try:
            blob = json.load(open(p, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for r in (blob.get("response") or {}).get("reviews") or []:
            rid = r.get("recommendationid")
            if rid in seen:
                continue
            seen.add(rid)
            total += 1
            m = (r.get("author") or {}).get("playtime_at_review")
            missing += m is None
            zero += m == 0
print("  reviews %d, field missing %d, explicit zero %d" % (total, missing, zero))
print("  (fetch_reviews.normalize's `or 0` would bucket a missing value as "
      "refund_window; it does not occur in this corpus)")

print("\n== model_pacer: documented guarantee vs N simultaneous waiters, rpm=12")
for n in (2, 4, 30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "pacer.json")
        stamps = []
        for i in range(12):
            model_pacer._acquire(path, 12, now=1000.0, model="m", ledger="batch")
            stamps.append(1000.0)
        for i in range(n):
            w, _, _ = model_pacer._acquire(path, 12, now=1001.0, model="m",
                                           ledger="batch")
            stamps.append(1001.0 + w)
        stamps.sort()
        best = max(sum(1 for t in stamps if s <= t < s + 60) for s in stamps)
        print("  12 at t=0, then %2d waiters: max starts in any rolling 60s = %d"
              % (n, best))

print("\n== run_batch.py main-loop budget stop vs what the logs recorded")
for log in sorted(glob.glob("evals/batch-2026-*.txt")):
    text = open(log, encoding="utf-8").read()
    summary = re.search(r"^\d+ attempted in .*$", text, re.M)
    print("  %-30s BUDGET STOP lines %d | %s"
          % (os.path.basename(log), text.count("BUDGET STOP"),
             summary.group(0) if summary else "(no summary line)"))
