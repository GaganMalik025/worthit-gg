"""
WorthIt.gg - content filter (build plan 1.2)

Runs BETWEEN ingestion and extraction. Reads data/raw/<appid>.json, drops
reviews that must never reach an LLM prompt or a citation, and writes the
survivors to data/filtered/<appid>.json.

Signals (invariant 7), evaluated in this order - first match wins, so every
dropped review carries exactly one reason:

    1. heart_density   Steam censors profanity into HHH runs. Density, never
                       count: a 6,200-char review with 4 hearts is one of the
                       best in the corpus; a 9-char review with 4 is not.
    2. blocked_term    curated high-severity wordlist (slurs, sexual violence,
                       explicit content). QR-4 is a launch gate.
    3. joke_review     votes_funny > votes_up AND votes_funny >= floor. The
                       floor matters: funny>up alone hits 19% of the refund
                       cohort, and inspection shows those are real bounce-outs.
    4. low_information nothing extractable - too short, ascii art, copypasta.

Nothing here re-samples. Ingestion exhausted the thin cohorts (kept == pool),
so a dropped review cannot be replaced. Thresholds are tuned for precision.

Usage:
    python3 filter_reviews.py --seeds --dry-run --sample 20
    python3 filter_reviews.py 233860 --min-words 8
"""

import argparse
import json
import random
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from fetch_reviews import BUCKETS, BUCKET_NAMES, SEED_GAMES

IN_DIR = Path("data/raw")
OUT_DIR = Path("data/filtered")
WORDLIST_DIR = Path(__file__).resolve().parent / "wordlists"

# invariant 12: below this many surviving reviews, a cohort carries no claims.
# ZERO IS INCLUDED, and is the default since 2026-08-21: a cohort that filters to
# no survivors mutes and renders its pool figure, exactly as an under-20 cohort
# does. It does NOT fail the title.
#
# What settled it: three titles in six nights - Hotline Miami (1 of 400 veteran
# reviews), A Way Out (2 of 400), A Plague Tale: Innocence (1 of 1,203) - all
# short finite games. `veteran` is 6000+ minutes, so for a game that ends at ten
# hours the cohort is undefined by construction rather than thin by sampling
# accident, and failing the whole title over it published nothing at all rather
# than three sound cohorts and one honest muted section. See BACKLOG 2026-08-16
# and its 2026-08-21 resolution.
MIN_COHORT = 20

# HISTORICAL. This file decided, per title, that an empty cohort should mute
# instead of failing - which is now the DEFAULT for every title, so no new appid
# needs a line here. The existing entry is kept for the record and still prints
# its note; it no longer changes any outcome.
ZERO_COHORT_PATH = Path(__file__).resolve().parent / "data/zero_cohort_exceptions.txt"


def load_zero_cohort_exceptions(path=ZERO_COHORT_PATH):
    """{appid: note} from a '<appid>  # note' file. Missing file means none."""
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        appid, _, note = line.partition("#")
        appid = appid.strip()
        if appid.isdigit():
            out[int(appid)] = note.strip()
    return out

# Sentiment-shift reporting. Short reviews skew positive (95% positive under 2
# words vs 68% over 100), so low_information pulls the surviving sample NEGATIVE.
# Measured on the seed set: -9.7pts on Helldivers 2's veteran bucket.
#
# The shift is only reported, never corrected. Correcting it means either
# re-admitting contentless praise ("democracy", "Epic", "kul") that can support
# no claim, or deleting claim-bearing negative reviews to make a ratio look
# right. Both are worse than the artifact. Prevalence comes from the pool block
# instead (invariant 11), which neither the quota nor the filter touches.
SHIFT_WARN_PTS = 3.0
# ...but only warn where the arithmetic can carry it. At n=12 a single review is
# 8 points, so an ungated warning is noise, not signal.
SHIFT_MIN_N = 30

REASONS = ["heart_density", "blocked_term", "joke_review", "low_information"]

BBCODE = re.compile(r"\[/?[a-zA-Z][^\]]{0,40}\]")
LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
# inflections the stems in block_en.txt should still catch
SUFFIX = r"(?:s|es|d|ed|ing|er|ers|y|ies)?"


# --------------------------------------------------------------------------
# wordlists
# --------------------------------------------------------------------------

def load_terms(path):
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            terms.append(line)
    return terms


def block_pattern(terms):
    """Word-boundary, repeat-tolerant matcher: 'raaape' hits, 'earrape' does not."""
    parts = []
    for t in terms:
        body = "".join(re.escape(c) + "+" if c.isalpha() else re.escape(c) for c in t)
        parts.append(body + SUFFIX)
    return re.compile(r"\b(?:%s)\b" % "|".join(parts), re.IGNORECASE)


def soft_pattern(terms, exclude):
    """Plain word-boundary matcher for the annotate-only list."""
    keep = [re.escape(t) for t in terms if t not in exclude]
    return re.compile(r"\b(?:%s)\b" % "|".join(keep), re.IGNORECASE)


def normalize_for_match(text):
    return "".join(LEET.get(c, c) for c in text.lower())


# --------------------------------------------------------------------------
# signals
# --------------------------------------------------------------------------

def heart_density(text):
    return text.count("♥") / len(text) if text else 0.0


def visible_words(text):
    """Word count with Steam BBCode stripped, so [h1]tags[/h1] aren't 'words'."""
    return BBCODE.sub(" ", text or "").split()


def alpha_ratio(text):
    if not text:
        return 0.0
    return sum(c.isalpha() or c.isspace() for c in text) / len(text)


def classify(review, cfg, blocked_re, soft_re):
    """Return (reason_or_None, annotations)."""
    text = review.get("review_text") or ""
    words = visible_words(text)
    funny = review.get("votes_funny") or 0
    up = review.get("votes_up") or 0
    hearts = text.count("♥")
    dens = heart_density(text)

    annotations = []
    if hearts:
        annotations.append("hearts_present")
    letters = sum(c.isalpha() for c in text)
    if len(text) > 30 and letters and sum(c.isupper() for c in text) / letters > 0.7:
        # NOT a drop: "DO NOT BUY" is refund-cohort signal, not noise
        annotations.append("all_caps")

    norm = normalize_for_match(text)
    if soft_re.search(norm):
        annotations.append("profanity_soft")

    # 1. censored-profanity density
    if hearts >= 3 and dens >= cfg["heart_density"]:
        return "heart_density", annotations
    # 2. high-severity wordlist
    if blocked_re.search(norm):
        annotations.append("blocked_term")
        return "blocked_term", annotations
    # 3. joke reviews / copypasta farming votes_funny
    if funny > up and funny >= cfg["funny_floor"]:
        return "joke_review", annotations
    # 4. nothing extractable
    if len(words) < cfg["min_words"]:
        return "low_information", annotations
    if len(text) > 20 and alpha_ratio(text) < cfg["alpha_ratio"]:
        return "low_information", annotations
    if len(words) >= 5 and len(set(w.lower() for w in words)) / len(words) < cfg["repeat_ratio"]:
        return "low_information", annotations

    return None, annotations


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def _pct_positive(rows):
    if not rows:
        return None
    return round(100.0 * sum(1 for r in rows if r["_review"].get("voted_up")) / len(rows), 1)


def sentiment_shift(rows):
    """Per bucket: does filtering move the sentiment mix, and by how much?

    Reported so the distortion is visible on every run and publishable on the
    methodology page. Not corrected - see the note on SHIFT_WARN_PTS.
    """
    out = OrderedDict()
    for name in BUCKET_NAMES:
        pre = [r for r in rows if r["_bucket"] == name]
        if not pre:
            continue
        post = [r for r in pre if r["_reason"] is None]
        dropped = [r for r in pre if r["_reason"]]
        lowinfo = [r for r in pre if r["_reason"] == "low_information"]
        p_pre, p_post = _pct_positive(pre), _pct_positive(post)
        delta = round(p_post - p_pre, 1) if (p_pre is not None and p_post is not None) else None
        # gate on the smaller of the two sides: a delta is only meaningful if
        # both the before and after have enough reviews to resolve 3 points
        n_basis = min(len(pre), len(post))
        out[name] = {
            "n_pre": len(pre), "pct_positive_pre": p_pre,
            "n_post": len(post), "pct_positive_post": p_post,
            "delta_pts": delta,
            "pct_positive_dropped": _pct_positive(dropped),
            "n_low_information": len(lowinfo),
            "pct_positive_low_information": _pct_positive(lowinfo),
            "warn": bool(delta is not None and abs(delta) > SHIFT_WARN_PTS
                         and n_basis >= SHIFT_MIN_N),
            "below_warn_n": n_basis < SHIFT_MIN_N,
        }
    return out


def print_sentiment_shift(shift):
    print("  %-18s %8s %8s %7s %10s" % ("", "pre pos%", "post pos%", "delta", "dropped pos%"))
    for name, st in shift.items():
        note = ""
        if st["warn"]:
            note = "  <-- SHIFT %+.1f pts" % st["delta_pts"]
        elif st["below_warn_n"]:
            note = "  (n<%d, not assessed)" % SHIFT_MIN_N
        print("  %-18s %7s%% %8s%% %+7.1f %9s%%%s"
              % (name,
                 "%.1f" % st["pct_positive_pre"] if st["pct_positive_pre"] is not None else "-",
                 "%.1f" % st["pct_positive_post"] if st["pct_positive_post"] is not None else "-",
                 st["delta_pts"] or 0.0,
                 "%.1f" % st["pct_positive_dropped"] if st["pct_positive_dropped"] is not None else "-",
                 note))
    print("  (sentiment shift is reported, never corrected - prevalence comes "
          "from the pool block)")


def build_report(rows, game_total_in, game_total_dropped):
    by_bucket = OrderedDict()
    overall_pct = (100.0 * game_total_dropped / game_total_in) if game_total_in else 0.0

    for name in BUCKET_NAMES:
        sub = [r for r in rows if r["_bucket"] == name]
        if not sub and name == "unknown":
            continue
        dropped = [r for r in sub if r["_reason"]]
        kept = len(sub) - len(dropped)
        counts = OrderedDict((reason, 0) for reason in REASONS)
        for r in dropped:
            counts[r["_reason"]] += 1
        drop_pct = (100.0 * len(dropped) / len(sub)) if sub else 0.0
        by_bucket[name] = {
            "in": len(sub),
            "kept": kept,
            "dropped": len(dropped),
            "drop_pct": round(drop_pct, 1),
            "dropped_by": dict(counts),
            # invariant 12
            "muted": kept < MIN_COHORT,
            "n": kept,
            # flagged when this bucket loses disproportionately more than the game
            "disproportionate": drop_pct - overall_pct > 10.0,
        }
    return by_bucket, round(overall_pct, 1)


def print_report(game_name, by_bucket, overall_pct, total_in, total_kept):
    print("\n%-20s %6s %7s %6s %5s %8s %7s %7s"
          % (game_name[:20], "in", "heart", "block", "joke", "lowinfo", "kept", "drop%"))
    for name, st in by_bucket.items():
        d = st["dropped_by"]
        flag = ""
        if st["disproportionate"]:
            ratio = (st["drop_pct"] / overall_pct) if overall_pct else 0
            flag = "  <-- %.1fx corpus rate" % ratio
        print("  %-18s %6d %7d %6d %5d %8d %7d %6.0f%%%s"
              % (name, st["in"], d["heart_density"], d["blocked_term"],
                 d["joke_review"], d["low_information"], st["kept"],
                 st["drop_pct"], flag))
    print("  %-18s %6d %7s %6s %5s %8s %7d %6.0f%%"
          % ("ALL", total_in, "", "", "", "", total_kept, overall_pct))

    for name, st in by_bucket.items():
        if st["kept"] == 0 and st.get("zero_cohort_exception"):
            print("  n=0: %s has 0 surviving reviews - muted (this appid also "
                  "carries a pre-2026-08-21 exception note, kept for the "
                  "record).\n      %s"
                  % (name, st.get("exception_note", "")))
        elif st["kept"] == 0:
            print("  invariant 12: %s has n=0 - renders muted, carries no claims."
                  % name)
        elif st["muted"]:
            print("  invariant 12: %s has n=%d (<%d) - renders muted, carries no claims."
                  % (name, st["kept"], MIN_COHORT))


def write_dropped_txt(path, game_name, dropped_rows):
    """The reviewable file. Grouped by reason so 20 of a kind is one scroll."""
    out = ["# dropped reviews - %s" % game_name,
           "# %d reviews, grouped by reason. Read a stretch of each before tuning.",
           ""]
    out[1] = out[1] % len(dropped_rows)
    for reason in REASONS:
        group = [r for r in dropped_rows if r["_reason"] == reason]
        if not group:
            continue
        out.append("=" * 72)
        out.append("reason: %s   (%d reviews)" % (reason, len(group)))
        out.append("=" * 72)
        out.append("")
        for r in group:
            rv = r["_review"]
            out.append("--- %s | %.1fh | voted_up=%s | funny=%s up=%s | rid=%s"
                       % (r["_bucket"], rv.get("hours_at_review") or 0,
                          rv.get("voted_up"), rv.get("votes_funny"),
                          rv.get("votes_up"), rv.get("recommendationid")))
            out.append((rv.get("review_text") or "").strip() or "(empty)")
            out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def print_sample(dropped_rows, n, reason, seed):
    pool = [r for r in dropped_rows if not reason or r["_reason"] == reason]
    if not pool:
        print("\n(no dropped reviews matching --sample-reason %s)" % reason)
        return
    picks = random.Random(seed).sample(pool, min(n, len(pool)))
    print("\n--- %d of %d dropped reviews (seed %d, stable across runs) ---"
          % (len(picks), len(pool), seed))
    for r in picks:
        rv = r["_review"]
        text = " ".join((rv.get("review_text") or "").split())
        print("\n  [%s | %s | %.1fh | funny=%s up=%s]"
              % (r["_reason"], r["_bucket"], rv.get("hours_at_review") or 0,
                 rv.get("votes_funny"), rv.get("votes_up")))
        print("  %s" % (text[:400] + ("..." if len(text) > 400 else "") or "(empty)"))


# --------------------------------------------------------------------------

def filter_one(appid, args, blocked_re, soft_re):
    src = Path(args.src) / ("%s.json" % appid)
    blob = None
    if src.exists():
        try:
            blob = json.loads(src.read_text(encoding="utf-8"))
        except ValueError:
            blob = None
    if not blob:
        print("== %s - no %s; run fetch_reviews.py first ==" % (appid, src))
        return False

    cfg = {
        "heart_density": args.heart_density,
        "min_words": args.min_words,
        "funny_floor": args.funny_floor,
        "alpha_ratio": args.alpha_ratio,
        "repeat_ratio": args.repeat_ratio,
    }
    game_name = blob.get("game_name") or str(appid)

    rows = []
    for rv in blob.get("reviews", []):
        reason, annotations = classify(rv, cfg, blocked_re, soft_re)
        rows.append({"_review": rv, "_bucket": rv.get("bucket"),
                     "_reason": reason, "_annotations": annotations})

    dropped_rows = [r for r in rows if r["_reason"]]
    kept_rows = [r for r in rows if not r["_reason"]]
    by_bucket, overall_pct = build_report(rows, len(rows), len(dropped_rows))
    # Scoped, per-title: an allowlisted appid mutes an empty cohort instead of
    # failing the title. Annotated here, before the report prints and before the
    # pass/fail is computed, so both read the same decision.
    note = load_zero_cohort_exceptions().get(int(appid))
    for st in by_bucket.values():
        st["zero_cohort_exception"] = bool(note) and st["kept"] == 0
        if st["zero_cohort_exception"]:
            st["exception_note"] = note
    shift = sentiment_shift(rows)

    print_report(game_name, by_bucket, overall_pct, len(rows), len(kept_rows))
    print_sentiment_shift(shift)
    if args.sample:
        print_sample(dropped_rows, args.sample, args.sample_reason, args.seed)

    if args.dry_run:
        print("  (dry run - nothing written)")
        # Zero survivors no longer fails the title (2026-08-21) - see the return
        # at the end of this function and the MIN_COHORT note above.
        return True

    survivors = []
    for r in kept_rows:
        row = dict(r["_review"])
        row["annotations"] = r["_annotations"]
        survivors.append(row)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("%s.json" % appid)
    out_path.write_text(json.dumps({
        "appid": appid,
        "game_name": blob.get("game_name"),
        "filtered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thresholds": cfg,
        # carried through: the ONLY sanctioned source of prevalence (invariant 11)
        "pool": blob.get("pool"),
        "query_summary": blob.get("query_summary"),
        "filter_report": {"by_bucket": by_bucket, "overall_drop_pct": overall_pct,
                          "in": len(rows), "kept": len(kept_rows),
                          "sentiment_shift": shift},
        "reviews": survivors,
        # ids and reasons only - dropped text never enters git
        "dropped": [{"recommendationid": r["_review"].get("recommendationid"),
                     "bucket": r["_bucket"], "reason": r["_reason"]}
                    for r in dropped_rows],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    txt_path = out_dir / ("%s.dropped.txt" % appid)
    write_dropped_txt(txt_path, game_name, dropped_rows)
    print("  wrote %d survivors -> %s" % (len(survivors), out_path))
    print("  wrote %d dropped   -> %s   <- read this" % (len(dropped_rows), txt_path))

    # A zero-survivor cohort no longer fails the title (2026-08-21). It mutes,
    # exactly as invariant 12 already mutes an under-20 cohort - see the
    # MIN_COHORT note above. Nothing here can fail a title any more, so this
    # returns True unconditionally rather than pretending to compute something.
    return True


def main():
    ap = argparse.ArgumentParser(description="WorthIt.gg content filter (pre-extraction)")
    ap.add_argument("appids", nargs="*")
    ap.add_argument("--seeds", action="store_true", help="filter the 5 eval seed games")
    ap.add_argument("--heart-density", type=float, default=0.02,
                    help="drop at/above this heart ratio (default 0.02)")
    ap.add_argument("--min-words", type=int, default=5,
                    help="low-information word floor (default 5)")
    ap.add_argument("--funny-floor", type=int, default=2,
                    help="min votes_funny for the joke rule (default 2)")
    ap.add_argument("--alpha-ratio", type=float, default=0.6,
                    help="ascii-art / emoji-spam floor (default 0.6)")
    ap.add_argument("--repeat-ratio", type=float, default=0.35,
                    help="copypasta unique/total word floor (default 0.35)")
    ap.add_argument("--sample", type=int, default=0,
                    help="print N random dropped reviews with reasons")
    ap.add_argument("--sample-reason", default=None, choices=REASONS,
                    help="restrict --sample to one reason")
    ap.add_argument("--seed", type=int, default=0, help="sample seed (default 0)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--src", default=str(IN_DIR), help="input dir (default data/raw)")
    ap.add_argument("--out", default=str(OUT_DIR), help="output dir (default data/filtered)")
    args = ap.parse_args()

    appids = list(args.appids)
    if args.seeds:
        appids = SEED_GAMES + [a for a in appids if a not in SEED_GAMES]
    if not appids:
        ap.error("give at least one appid, or --seeds")

    block_terms = load_terms(WORDLIST_DIR / "block_en.txt")
    soft_terms = load_terms(WORDLIST_DIR / "ldnoobw_en.txt")
    blocked_re = block_pattern(block_terms)
    soft_re = soft_pattern(soft_terms, set(block_terms))
    print("wordlists: %d blocking, %d annotate-only  (thresholds: hearts>=%.3f, "
          "words>=%d, funny>=%d)"
          % (len(block_terms), len(soft_terms), args.heart_density,
             args.min_words, args.funny_floor))

    failures = [a for a in appids if not filter_one(a, args, blocked_re, soft_re)]
    if failures:
        print("\nFAILED (a bucket has zero survivors): %s" % ", ".join(failures))
        sys.exit(1)
    print("\nall %d game(s) filtered" % len(appids))


if __name__ == "__main__":
    main()
