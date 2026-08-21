"""
Why did RuneScape (1343400) exhaust its three synthesis attempts on the
2026-08-21 batch?

The batch runs generate_one with quiet=True, so the per-attempt rejection
reasons never reached evals/batch-2026-08-21.txt - only the [FAIL] line did.
This replays synthesize.check_response() over the THREE CACHED RESPONSES the
run left in data/cache/extract/1343400/synthesis_*.json.

ZERO Gemini cost by construction: it never builds a client and never sends a
request. Every input is read from disk - the cached responses, the claims blob
and the filtered corpus - which is the same way the 2026-08-18 Insurgency
deadlock was diagnosed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import flags as flags_mod          # noqa: E402
import synthesize                  # noqa: E402

APPID = sys.argv[1] if len(sys.argv) > 1 else "1343400"

claims_blob, corpus, pool, cohorts = synthesize.load_inputs(
    APPID, ROOT / "data/claims", ROOT / "data/filtered")
detected = flags_mod.detect(pool)
mean = synthesize.post_refund_mean(cohorts)
verdict_word = synthesize.verdict_for_mean(mean)

print("=== %s (%s) ===" % (claims_blob.get("game_name"), APPID))
print("post-refund mean %.1f%% -> verdict word %s" % (mean, verdict_word))
for c in cohorts:
    print("  %-14s pool_n=%-5s %5s%% positive  claims=%-3d%s"
          % (c["bucket"], c["pool_n"], c["pct_positive"], len(c["claims"]),
             "  MUTED" if c["muted"] else ""))

def prose_fields(parsed):
    """label -> text, for every field check_response() sweeps for invariants
    11 and 13.

    This MIRRORS the prose list synthesize.check_response() builds, and the
    labels have to match it exactly, because the labels are what the failure
    codes are keyed on. If that function gains a field and this does not, the
    symptom is an `unresolved` line below rather than a wrong quote - which is
    the failure mode this helper is written to have.
    """
    fields = [("tagline", parsed.get("tagline") or "")]
    for name in ("for_you_if", "not_for_you_if"):
        for i, text in enumerate(parsed.get(name) or []):
            fields.append(("%s[%d]" % (name, i), text))
    for c in parsed.get("cohorts") or []:
        fields.append(("summary[%s]" % c.get("bucket"), c.get("summary") or ""))
    for f in parsed.get("flag_sentences") or []:
        fields.append(("flag[%s]" % f.get("flag_id"), f.get("sentence") or ""))
    return dict(fields)


def explain(code, fields):
    """Resolve one check_response() failure code back to the text that tripped
    it. Returns (label, words, text) with None where the code carries no field.

    Codes that name a prose field, from check_response():
        digit_in_prose:<label>
        prevalence:<label>:<word>[,<word>...]
    Everything else - unknown_claim_id, muted_cohort_has_content,
    tagline_frames_friction_as_a_condition and friends - is a structural
    failure with no single field behind it, and is reported as-is.
    """
    if code.startswith("digit_in_prose:"):
        label, words = code.split(":", 1)[1], None
    elif code.startswith("prevalence:"):
        rest = code.split(":", 1)[1]
        label, words = rest.rsplit(":", 1)      # a label never contains ":"
    else:
        return None, None, None
    return label, words, fields.get(label)


cache = sorted((ROOT / "data/cache/extract" / APPID).glob("synthesis_*.json"),
               key=lambda p: p.stat().st_mtime)
print("\n%d cached synthesis responses, oldest first:" % len(cache))
for path in cache:
    blob = json.loads(path.read_text())
    parsed = json.loads(blob["text"])
    failures = synthesize.check_response(parsed, cohorts, detected, verdict_word)
    fields = prose_fields(parsed)

    print("\n--- %s  (mtime %s)" % (path.name, path.stat().st_mtime))
    print("    tagline: %s" % parsed.get("tagline"))
    if not failures:
        print("    check_response -> PASS (no failures)")
        continue
    print("    check_response -> %d failure(s)" % len(failures))
    for code in failures:
        label, words, text = explain(code, fields)
        print("      %s" % code)
        if label is None:
            print("        (structural failure - no single prose field behind "
                  "it; see check_response())")
            continue
        if text is None:
            print("        UNRESOLVED: %r is not a field this script knows how "
                  "to rebuild - prose_fields() is out of step with "
                  "check_response()" % label)
            continue
        print("        %s: %s" % (label, text))
        # Self-check, not decoration: if the flagged word is absent from the
        # text printed above it, the resolution is WRONG and the quote must not
        # be trusted. Say so instead of printing a plausible-looking mismatch,
        # which is the exact defect this whole block exists to remove.
        if words:
            for w in words.split(","):
                where = "present" if w.lower() in text.lower() else \
                        "!! ABSENT - resolution is wrong, do not quote this"
                print("        flagged word %-14r %s" % (w, where))
