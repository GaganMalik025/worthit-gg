"""Mutation proof for the 2026-08-21 guard changes.

Three changes landed together, and each one LOOSENS a guard. That is the
direction where a green run proves least: a guard that has been widened too far
passes every test written to check that it stopped blocking something. So every
case below comes in pairs - the pre-fix behaviour reproduced as a CONTROL, and
the post-fix behaviour - plus cases pinning what must STILL be rejected.

  1. prevalence_guard.py  event-frequency words freed, population words kept
  2. synthesize.py        invariant 13 narrowed to allow platform/version names
  3. filter_reviews.py    a zero-survivor cohort mutes instead of failing

Controls are the point. Without g01/g06/g09 a guard that always returns "clean"
scores green on g02/g05/g07/g10, and a filter that publishes everything scores
green on g10.

Zero Gemini cost: nothing here builds a client or sends a request. The filter
cases run the real filter over a fabricated raw file in a temp dir.

Run:  .venv/bin/python evals/mutate_guard_split_2026-08-21.py
Logs: evals/mutation-logs/g01..g10.log - same NN-description.log shape as
      mutate_reconciliation.py (01-11), mutate_pacer_diagnosis.py (p01-p03),
      mutate_sourcing.py (s01-s10) and mutate_retry_cache.py (m01-m03).
"""
import hashlib
import importlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path(__file__).resolve().parent / "mutation-logs"
PY = str(ROOT / ".venv/bin/python")
sys.path.insert(0, str(ROOT / "pipeline"))

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


# ---------------------------------------------------------------------------
# 1. the prevalence split
# ---------------------------------------------------------------------------
print("\nprevalence_guard.py - event frequency freed, population kept")

import prevalence_guard  # noqa: E402

# g01 CONTROL: reconstruct the pre-fix guard by compiling the freed patterns
# back in, and require it to reject what the batch actually failed on. This is
# the bug as it behaved on 2026-08-21, reproduced rather than described.
pre_fix = [(re.compile(p, re.IGNORECASE), lab) for p, lab in
           prevalence_guard.PATTERNS + prevalence_guard.FREED_FREQUENCY_PATTERNS]


def check_pre_fix(text):
    return [(m.group(0).strip(), lab)
            for rx, lab in pre_fix for m in rx.finditer(text or "")]


RUNESCAPE = "Long-term players face subscription walls, cluttered interfaces, and occasional crashes."
INSURGENCY = "Lethal tactical combat meets persistent startup crashes on modern systems."

hits = check_pre_fix(RUNESCAPE)
record("g01", "CONTROL pre-fix guard rejects RuneScape's veteran summary",
       any(t.lower() == "occasional" for t, _ in hits),
       "text: %s\nhits: %r" % (RUNESCAPE, hits))

hits = prevalence_guard.check_claim(RUNESCAPE)
record("g02", "post-fix guard passes the same summary", not hits,
       "text: %s\nhits: %r" % (RUNESCAPE, hits))

hits = prevalence_guard.check_claim(INSURGENCY)
record("g02b", "post-fix guard passes Insurgency's 'persistent' tagline", not hits,
       "text: %s\nhits: %r" % (INSURGENCY, hits))

# g03/g04: what must STILL be rejected. A split that freed these would have
# gutted invariant 11 rather than narrowed it.
still = {
    "most players refund early": "most",
    "the majority of reviewers agree": "majority",
    "all players hit this wall": "all players",
    "free access to all content": "all",
    "40% of buyers report crashes": "40%",
    "three out of five reviewers say so": "three out of five",
    "a third of reviewers bounce": "third of",
    "countless players complain": "countless",
    "the consensus is that it runs badly": "consensus",
}
missed = {t: prevalence_guard.check_claim(t) for t in still
          if not prevalence_guard.check_claim(t)}
record("g03", "post-fix guard STILL rejects all %d population phrasings" % len(still),
       not missed,
       "\n".join("%-42s -> %r" % (t, prevalence_guard.check_claim(t)) for t in still)
       + ("\n\nMISSED: %r" % missed if missed else ""))

freed_ok = ["occasional crashes", "frequent updates", "persistent stutter",
            "the game repeatedly crashes", "loading is often slow",
            "widespread performance issues", "commonly reported bugs"]
bad = {t: prevalence_guard.check_claim(t) for t in freed_ok
       if prevalence_guard.check_claim(t)}
record("g04", "post-fix guard passes all %d event-frequency phrasings" % len(freed_ok),
       not bad, "\n".join("%-42s -> clean" % t for t in freed_ok if t not in bad)
       + ("\n\nSTILL REJECTED: %r" % bad if bad else ""))

# g05: the prompt must move with the rule. This is the mechanism that produced
# "Windows eleven" - a model told to avoid a word spells around it.
words = prevalence_guard.banned_words()
record("g05", "banned_words() keeps 'most', drops 'occasional'/'frequent'",
       "most" in words and "occasional" not in words and "frequent" not in words,
       "banned_words() = %r" % (words,))

# ---------------------------------------------------------------------------
# 2. the digit allowlist
# ---------------------------------------------------------------------------
print("\nsynthesize.py - invariant 13 narrowed to platform/version names")

import synthesize  # noqa: E402

WINDOWS = "you run Windows 11 with startup crashes"

record("g06", "CONTROL pre-fix digit rule rejects 'Windows 11'",
       bool(synthesize.DIGIT.search(WINDOWS)),
       "the pre-fix rule is a bare \\d over the same prose:\n  %s" % WINDOWS)

allowed = ["you run Windows 11 with startup crashes", "needs DirectX 12",
           "an RTX 4090 barely holds sixty", "a PS5 port", "Core i7 required"]
wrong = [t for t in allowed if synthesize.has_bare_digit(t)]
record("g07", "post-fix rule allows %d platform/version names" % len(allowed),
       not wrong, "allowed: %r\nwrongly rejected: %r" % (allowed, wrong))

quantities = ["about 20 hours in", "6 players co-op", "3 of 5 missions crash",
              "roughly 40% of the map", "ref-e18e82 backs this"]
leaked = [t for t in quantities if not synthesize.has_bare_digit(t)]
record("g08", "post-fix rule STILL rejects %d quantities" % len(quantities),
       not leaked, "must reject: %r\nleaked through: %r" % (quantities, leaked))

# ---------------------------------------------------------------------------
# 3. zero-survivor cohorts mute instead of failing the title
# ---------------------------------------------------------------------------
print("\nfilter_reviews.py - a zero-survivor cohort mutes")

TARGET = ROOT / "pipeline/filter_reviews.py"
sha_before = sha(TARGET)

# The pre-fix gate appeared TWICE, at two indent levels - once inside the
# dry-run branch and once at the end of filter_one(). Both are restored for the
# control, and each is matched with its own indentation. That detail is not
# pedantry: replacing them with one indentation-blind substring is what broke
# filter_one() on 2026-08-21, moving the dry-run return out to function level so
# every write below it became unreachable.
FIXED_DRYRUN = '''        # Zero survivors no longer fails the title (2026-08-21) - see the return
        # at the end of this function and the MIN_COHORT note above.
        return True'''
BROKEN_DRYRUN = '''        return all(st["kept"] > 0 or st.get("zero_cohort_exception")
               for st in by_bucket.values())'''

FIXED_FINAL = '''    # A zero-survivor cohort no longer fails the title (2026-08-21). It mutes,
    # exactly as invariant 12 already mutes an under-20 cohort - see the
    # MIN_COHORT note above. Nothing here can fail a title any more, so this
    # returns True unconditionally rather than pretending to compute something.
    return True'''
BROKEN_FINAL = '''    return all(st["kept"] > 0 or st.get("zero_cohort_exception")
               for st in by_bucket.values())'''


def fabricate(raw_dir):
    """One title: three healthy cohorts, and a veteran cohort of a single
    review so short the low-information heuristic drops it. That is A Way Out
    and A Plague Tale's exact shape.

    Written in the NORMALIZED schema data/raw/ actually holds - review_text,
    hours_at_review, and a bucket already assigned at ingestion (invariant 1
    converts minutes to hours exactly once, upstream of here).
    """
    reviews, rid = [], 100000
    body = ("The campaign is well paced and the level design keeps introducing "
            "new mechanics right up to the final chapter, which is more than "
            "games of this length usually manage with their systems. ")
    counts = {"refund_window": 30, "early": 30, "mid": 30}
    hours = {"refund_window": 1.0, "early": 10.0, "mid": 50.0}
    for bucket, n in counts.items():
        for _ in range(n):
            rid += 1
            reviews.append({
                "recommendationid": str(rid), "appid": 999999,
                "review_text": body * 2, "voted_up": True,
                "hours_at_review": hours[bucket], "bucket": bucket,
                "votes_up": 3, "votes_funny": 0,
                "created_ts": 1750000000, "updated_ts": 1750000000,
            })
    rid += 1
    reviews.append({                       # the single veteran, low-information
        "recommendationid": str(rid), "appid": 999999,
        "review_text": "good", "voted_up": True,
        "hours_at_review": 150.0, "bucket": "veteran",
        "votes_up": 0, "votes_funny": 0,
        "created_ts": 1750000000, "updated_ts": 1750000000,
    })
    pool = {"basis": "fixture", "pool_n": len(reviews), "buckets": {
        b: {"pool_n": n, "share_of_pool_pct": round(100 * n / len(reviews), 1),
            "pct_positive": 100.0}
        for b, n in list(counts.items()) + [("veteran", 1)]}}
    (raw_dir / "999999.json").write_text(json.dumps({
        "appid": 999999, "game_name": "Mutation Fixture", "pool": pool,
        "query_summary": {"total_reviews": len(reviews),
                          "total_positive": len(reviews)},
        "reviews": reviews,
    }), encoding="utf-8")


def run_filter():
    """Run the REAL filter over the fixture.

    Returns (rc, output, written) where `written` is the PARSED CONTENT of
    data/filtered/999999.json, or None if the file was never created.

    Returning the artifact rather than just the console is the whole point.
    The first version of this driver asserted on rc and on a printed line, and
    it PASSED against a filter_one() that had been broken so badly it returned
    before writing anything at all - a real bug, shipped and caught in review on
    2026-08-21, in the harness written to catch exactly that. A report is not
    evidence that the work behind it happened.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        raw, out = tmp / "raw", tmp / "filtered"
        raw.mkdir(), out.mkdir()
        fabricate(raw)
        pr = subprocess.run(
            [PY, str(TARGET), "999999", "--src", str(raw),
             "--out", str(out)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=180)
        path = out / "999999.json"
        written = json.loads(path.read_text()) if path.exists() else None
        if written is not None:
            written["_dropped_txt_written"] = (out / "999999.dropped.txt").exists()
        return pr.returncode, pr.stdout + pr.stderr, written


try:
    src = TARGET.read_text()
    assert src.count(FIXED_DRYRUN) == 1, "fixed dry-run gate not found"
    assert src.count(FIXED_FINAL) == 1, "fixed final gate not found"
    TARGET.write_text(src.replace(FIXED_DRYRUN, BROKEN_DRYRUN)
                         .replace(FIXED_FINAL, BROKEN_FINAL))
    rc, out, written = run_filter()
    record("g09", "CONTROL pre-fix filter FAILS the title on a zero cohort",
           rc != 0 and "zero survivors" in out.lower(),
           "rc=%s  wrote_file=%s\n\n%s" % (rc, written is not None, out))
finally:
    TARGET.write_text(src)
    sha_after = sha(TARGET)

record("g09b", "filter_reviews.py restored byte-identical",
       sha_before == sha_after,
       "sha before=%s after=%s" % (sha_before, sha_after))

rc, out, written = run_filter()
record("g10", "post-fix filter reports the veteran cohort muted",
       rc == 0 and "invariant 12: veteran has n=0" in out,
       "rc=%s\n\n%s" % (rc, out))

# g11 is g10's missing half. g10 reads the CONSOLE; this reads the FILE the
# console claims was written, because those are different claims and only the
# second one is what the next stage consumes.
if written is None:
    detail = "data/filtered/999999.json was NEVER WRITTEN - the filter " \
             "returned before its write path. rc was %s and the report " \
             "printed normally, which is why g10 alone cannot see this." % rc
    ok = False
else:
    vet = written["filter_report"]["by_bucket"]["veteran"]
    kept = {b: sum(1 for r in written["reviews"] if r["bucket"] == b)
            for b in ("refund_window", "early", "mid", "veteran")}
    ok = (vet["kept"] == 0 and vet["muted"] is True
          and kept["veteran"] == 0 and kept["early"] == 30
          and len(written["reviews"]) == 90
          and bool(written.get("filtered_at"))
          and written["_dropped_txt_written"])
    detail = ("filtered_at   : %s\nveteran       : in=%s kept=%s muted=%s\n"
              "survivors     : %d  %r\ndropped.txt   : %s"
              % (written.get("filtered_at"), vet["in"], vet["kept"],
                 vet["muted"], len(written["reviews"]), kept,
                 written["_dropped_txt_written"]))
record("g11", "...and the FILE on disk carries it (survivors + dropped.txt)",
       ok, detail)

# ---------------------------------------------------------------------------
print("\n%d/%d cases as expected" % (sum(1 for _, _, ok in results if ok),
                                     len(results)))
failed = [t for t, _, ok in results if not ok]
if failed:
    print("FAILED: %s   (see evals/mutation-logs/)" % ", ".join(failed))
    sys.exit(1)
print("logs: evals/mutation-logs/%s" % ", ".join(t for t, _, _ in results))
