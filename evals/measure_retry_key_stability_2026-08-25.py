"""Does the 2026-08-25 retry-prose fix actually stop the next wordlist edit?

The 08-24 driver (evals/measure_retry_key_blast_2026-08-24.py) measured the
damage a PAST wordlist change did: 599 cached retries invalidated by the 08-21
frequency split. This one measures whether a FUTURE one still can, by simulating
the edit rather than waiting for it.

WHAT IS SIMULATED
    --free WORD drops every prevalence_guard pattern whose regex names WORD,
    IN MEMORY. Nothing on disk moves and prevalence_guard.py is not touched.
    PRE  = the guard as committed today.
    POST = the guard with that word freed.

WHAT IS COMPARED
    Four keys per retry step: {old prose, new prose} x {PRE, POST}.
      old prose = "states how common something is (frequent,persistent)"
                  - the committed rendering until 2026-08-25, reproduced here
                  by substituting ec._problem_line's output, so the OTHER
                  branches cannot drift from the real ones.
      new prose = ec._problem_line as committed now.
    old prose is also what walks the chain: the retry files on disk were written
    under it, so following the new prose would find nothing after attempt 0.

WHAT IS CLASSIFIED
    prevalence-only vs mixed-reason - the split the task asks for. A retry whose
      failures include only_1_supporting_citations alongside prevalence_language
      is "mixed"; its key can legitimately move for reasons this fix does not
      own.
    wording-only vs set-changing - the decomposition that actually predicts the
      fix's reach. Only a step where the same claims still fail for the same
      non-prevalence reasons, differing only in WHICH terms matched, can be
      stabilised at all. Where the freed word was a claim's only prevalence hit
      the claim stops failing prevalence, the reason leaves the block, and the
      key SHOULD move. RuneScape's own 08-21 case is in that second class.

Free: reads data/filtered/ and data/cache/extract/ only. No network, no Gemini.

Run:  .venv/bin/python evals/measure_retry_key_stability_2026-08-25.py --free most
      .venv/bin/python evals/measure_retry_key_stability_2026-08-25.py --free most --show 5
"""
import argparse
import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, "pipeline")
import extract_claims as ec          # noqa: E402
import ground_check                  # noqa: E402
import prevalence_guard as pg        # noqa: E402

MODEL = "gemini-3.5-flash-lite"
BUCKETS = ("refund_window", "early", "mid", "veteran")
CFG = {"min_coverage": ground_check.MIN_UNION_COVERAGE,
       "min_citation_coverage": ground_check.MIN_CITATION_COVERAGE,
       "min_supporting": ground_check.MIN_SUPPORTING_CITATIONS}

# The exact sentence the fix installed. Anchored here so that if it is ever
# reworded, this driver fails loudly rather than silently measuring nothing.
NEW_PROSE = ("states how many, how much, or what share of something there is - "
             "a count or proportion this sample cannot support; restate it "
             "without quantity or population language, or drop it")


# ---------------------------------------------------------------- prose

def old_problem_line(result):
    """The pre-2026-08-25 rendering of one failed claim.

    Built by substituting into ec._problem_line's output rather than
    reimplementing it, so the untouched branches (low_union_coverage, only_,
    cited_outside_bucket, ids_not_in_corpus) are the REAL ones by construction
    and this driver cannot quietly measure a stale copy of them.
    """
    line = ec._problem_line(result)
    terms = [f.split(":", 1)[1] for f in result["failures"]
             if f.startswith("prevalence_language:")]
    if not terms:
        return line                      # nothing to substitute; identical
    if NEW_PROSE not in line:
        raise SystemExit("NEW_PROSE anchor not found in _problem_line output - "
                         "the fix was reworded; update this driver.\n  %r" % line)
    return line.replace(NEW_PROSE, "states how common something is (%s)"
                        % terms[0])


def problems_block(failed, prose):
    render = ec._problem_line if prose == "new" else old_problem_line
    return "\n".join(render(f) for f in failed)


def retry_prompt(game, bucket, reviews, failed, prose):
    _, reviews_block = ec.build_prompts(game, bucket, reviews)
    return ec.RETRY_PREAMBLE.format(problems=problems_block(failed, prose),
                                    reviews_block=reviews_block)


# ---------------------------------------------------------------- guard

def compiled_without(word):
    """Today's guard minus every pattern that names `word`. In memory only."""
    kept, dropped = [], []
    for pattern, label in pg.PATTERNS:
        # substring, not \bword\b: the patterns embed their own \b escapes, so
        # "most" sits inside the literal text "\\bmost\\b" with no boundary in
        # front of it. Every dropped pattern is printed in the report, and the
        # behavioural self-check below is what actually proves the right thing
        # was freed.
        (dropped if word.lower() in pattern.lower() else kept).append(
            (pattern, label))
    if not dropped:
        raise SystemExit("no PATTERNS entry names %r - nothing would be "
                         "simulated" % word)
    compiled = [(re.compile(p, re.IGNORECASE), l) for p, l in kept]

    # SELF-CHECK: the simulation must actually free the word. Without this a
    # typo'd --free would drop an unrelated pattern and the whole run would
    # report perfect stability while changing nothing that matters.
    probes = ["the game has %s problems" % word, "%s players report problems" % word]
    saved = list(pg.COMPILED)
    try:
        before = [bool(pg.check_claim(t)) for t in probes]
        pg.COMPILED = compiled
        after = [bool(pg.check_claim(t)) for t in probes]
    finally:
        pg.COMPILED = saved
    if not any(before) or any(a and b for a, b in zip(after, before)):
        raise SystemExit("freeing %r did not change the guard's verdict on %r: "
                         "before=%s after=%s" % (word, probes, before, after))
    return compiled, [p for p, _ in dropped]


def patterns_from_ref(ref):
    """PATTERNS / FREED_FREQUENCY_PATTERNS as of a git ref.

    Needed to reconcile with the 08-24 figure: PATTERNS changed on 08-25 (the
    absolute-quantifier split), so replaying the 08-21 event against TODAY's
    guard cannot be expected to reproduce 599 exactly. Loading the guard as it
    stood that night turns "the difference is probably the 08-25 split" into a
    number that either reproduces or does not.

    The extracted module goes to a temp file, never into the repo.
    """
    import importlib.util
    import subprocess
    import tempfile
    src = subprocess.run(["git", "show", "%s:pipeline/prevalence_guard.py" % ref],
                         capture_output=True, text=True, check=True).stdout
    tmp = pathlib.Path(tempfile.mkdtemp()) / "prevalence_guard_at_ref.py"
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("pg_at_ref", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def guards(mode, word, ref=None):
    """(pre, post, description, patterns that differ) - both compiled, in memory.

    Two modes, because they answer different questions and the first one alone
    would flatter the fix:

    replay0821 REPLAYS THE REAL EVENT. PRE is the guard with the frequency
      patterns still enforced (the pre-2026-08-21 rule), POST is the guard as
      committed. This is exactly the comparison evals/measure_retry_key_blast_
      2026-08-24.py made to arrive at 599, so running it with both prose
      versions answers the only question that matters about the fix: how many of
      the 599 would it actually have saved.

    future FREES ONE STILL-BANNED WORD. Forward-looking, and much smaller by
      construction: the extraction prompt names every word banned_words()
      returns, so the model rarely emits them and few claims fail on them.
    """
    src = patterns_from_ref(ref) if ref else pg
    if mode == "replay0821":
        pre = [(re.compile(pt, re.IGNORECASE), l)
               for pt, l in src.PATTERNS + src.FREED_FREQUENCY_PATTERNS]
        post = [(re.compile(pt, re.IGNORECASE), l) for pt, l in src.PATTERNS]
        probe = "the game has frequent crashes"
        saved = list(pg.COMPILED)
        try:
            pg.COMPILED = pre
            before = bool(pg.check_claim(probe))
            pg.COMPILED = post
            after = bool(pg.check_claim(probe))
        finally:
            pg.COMPILED = saved
        if not before or after:
            raise SystemExit("replay0821 self-check failed on %r: pre=%s post=%s"
                             % (probe, before, after))
        return pre, post, ("the real 2026-08-21 frequency split "
                           "(PRE = guard + FREED_FREQUENCY_PATTERNS, "
                           "POST = guard) with PATTERNS taken from %s"
                           % (ref or "the working tree")), \
            [pt for pt, _ in src.FREED_FREQUENCY_PATTERNS]
    post, dropped = compiled_without(word)
    return list(pg.COMPILED), post, "a future edit freeing %r" % word, dropped


def failures_under(kept, bucket, corpus, compiled):
    pg.COMPILED = compiled
    _, failed, _ = ground_check.check_bucket(kept, bucket, corpus, CFG)
    return failed


def signature(failed):
    """(claim, non-prevalence reasons, does prevalence still fire) per claim.

    Two steps with the same signature differ only in WHICH terms matched, which
    is precisely the class the fix is meant to make invisible to the cache key.
    """
    return [(f["claim"],
             tuple(r for r in f["failures"]
                   if not r.startswith("prevalence_language")),
             any(r.startswith("prevalence_language") for r in f["failures"]))
            for f in failed]


def has_non_prevalence(failed):
    return any(not r.startswith("prevalence_language")
               for f in failed for r in f["failures"])


# ---------------------------------------------------------------- walk

def walk(mode, free_word, limit=None, ref=None):
    live_guard = list(pg.COMPILED)
    pre_compiled, post_compiled, desc, dropped_patterns = guards(mode, free_word,
                                                                ref)
    rows, err = [], 0
    files = sorted(pathlib.Path("data/filtered").glob("*.json"))
    if limit:
        files = files[:limit]
    for fp in files:
        appid = fp.stem
        try:
            blob = json.loads(fp.read_text())
        except Exception:
            err += 1
            continue
        game = blob.get("game_name") or appid
        by = collections.defaultdict(list)
        for r in blob.get("reviews", []):
            by[r.get("bucket")].append(r)
        for b in BUCKETS:
            rv = by.get(b) or []
            if len(rv) < ec.MIN_COHORT:
                continue
            corpus = {str(r["recommendationid"]): r for r in rv}
            voted = {str(r.get("recommendationid")): r.get("voted_up")
                     for r in rv}
            system, user = ec.build_prompts(game, b, rv)
            prompt, step = user, 0
            while step <= 2:
                p = ec.cache_path(appid, b, MODEL, system, prompt)
                if not p.exists():
                    break
                try:
                    claims = json.loads(
                        json.loads(p.read_text())["text"]).get("claims") or []
                    kept, _ = ec.enforce(claims, set(corpus), voted, b)
                except Exception:
                    err += 1
                    break
                f_pre = failures_under(kept, b, corpus, pre_compiled)
                if not f_pre or step == 2:
                    break
                f_post = failures_under(kept, b, corpus, post_compiled)

                keys = {}
                for prose in ("old", "new"):
                    for tag, fl in (("pre", f_pre), ("post", f_post)):
                        keys[(prose, tag)] = ec.cache_path(
                            appid, b, MODEL, system,
                            retry_prompt(game, b, rv, fl, prose)).name

                same_sig = signature(f_pre) == signature(f_post)
                rows.append({
                    "appid": appid, "game": game, "bucket": b, "step": step + 1,
                    "prevalence_only": not has_non_prevalence(f_pre),
                    # Under POST every claim passes, so no retry is ISSUED at
                    # all. The cached retry file goes unused, but nothing is
                    # re-paid - this is a saved call, not an invalidated one,
                    # and lumping it in with invalidation overstates the cost.
                    "post_no_retry": not f_post,
                    "guard_changed_something": [f["failures"] for f in f_pre]
                                               != [f["failures"] for f in f_post],
                    "wording_only": same_sig,
                    "old_key_moved": keys[("old", "pre")] != keys[("old", "post")],
                    "new_key_moved": keys[("new", "pre")] != keys[("new", "post")],
                    "on_disk": pathlib.Path("data/cache/extract", appid,
                                            keys[("old", "pre")]).exists(),
                    "terms_pre": sorted({t for f in f_pre
                                         for r_ in f["failures"]
                                         if r_.startswith("prevalence_language:")
                                         for t in r_.split(":", 1)[1].split(",")}),
                    "problems_old": problems_block(f_pre, "old"),
                    "problems_new": problems_block(f_pre, "new"),
                })
                prompt = retry_prompt(game, b, rv, f_pre, "old")
                step += 1
    pg.COMPILED = live_guard
    return rows, err, desc, dropped_patterns


# ---------------------------------------------------------------- report

def report(rows, err, desc, dropped_patterns, out):
    w = out.write
    w("Retry-key stability under a SIMULATED wordlist edit\n")
    w("driver: evals/measure_retry_key_stability_2026-08-25.py"
      "   (disk only, 0 Gemini calls)\n")
    w("simulating: %s\n" % desc)
    for p in dropped_patterns:
        w("  pattern that differs: %s\n" % p)
    w("\nCOMPARABLE FIGURE (the metric evals/retry-key-blast-2026-08-24.txt "
      "reported)\n")
    inv_old = [r for r in rows if r["old_key_moved"] and r["on_disk"]]
    inv_new = [r for r in inv_old if r["new_key_moved"]]
    w("  cached retry files invalidated, OLD prose : %d across %d titles\n"
      % (len(inv_old), len({r["appid"] for r in inv_old})))
    w("  cached retry files invalidated, NEW prose : %d across %d titles\n"
      % (len(inv_new), len({r["appid"] for r in inv_new})))
    w("  difference (what this fix would have saved): %d\n"
      % (len(inv_old) - len(inv_new)))
    w("  of the OLD-prose figure: %d need no retry at all, %d are wording-only,"
      "\n    %d are a genuinely different complaint\n"
      % (sum(1 for r in inv_old if r["post_no_retry"]),
         sum(1 for r in inv_old if r["wording_only"] and not r["post_no_retry"]),
         sum(1 for r in inv_old
             if not r["wording_only"] and not r["post_no_retry"])))
    w("  by cohort: %s\n" % dict(collections.Counter(r["bucket"]
                                                     for r in inv_old)))
    w("  by step  : %s\n" % dict(collections.Counter(r["step"]
                                                     for r in inv_old)))

    w("\nDENOMINATOR\n")
    w("  retry steps replayed                    : %d\n" % len(rows))
    w("  of which the retry file is on disk today: %d\n"
      % sum(1 for r in rows if r["on_disk"]))
    w("  parse/read errors                       : %d\n" % err)

    changed = [r for r in rows if r["guard_changed_something"]]
    gone = [r for r in changed if r["post_no_retry"]]
    live = [r for r in changed if not r["post_no_retry"]]
    w("  steps the edit actually changes         : %d"
      "   (the rest have nothing to stabilise)\n" % len(changed))
    w("    of which NO RETRY is issued at all    : %d"
      "   (all claims now pass - a saved call,\n"
      "%s                                             not an invalidated one)\n"
      % (len(gone), " " * 4))
    w("    still retried, so a key exists        : %d\n" % len(live))

    # Which words the guard actually matched across the replay. This is what
    # makes --free a measured choice rather than a guess: freeing a word that
    # never occurs would report perfect stability while proving nothing.
    on_disk_gone = [r for r in gone if r["on_disk"]]
    w("    (%d of the no-retry steps have a cached retry file on disk, which "
      "becomes\n     dead weight rather than a repeat cost)\n" % len(on_disk_gone))
    seen = collections.Counter(t for r in rows for t in r["terms_pre"])
    w("\nPREVALENCE TERMS THE GUARD MATCHED ACROSS THE REPLAY\n")
    w("  %s\n" % (dict(seen.most_common()) or "none"))

    def tally(sub):
        return (len(sub),
                sum(1 for r in sub if r["old_key_moved"]),
                sum(1 for r in sub if r["new_key_moved"]))

    w("\nSTABILITY, steps still retried under both guards"
      " (n / old prose moved / new prose moved)\n")
    rows_out = [
        ("prevalence-only", [r for r in live if r["prevalence_only"]]),
        ("mixed-reason", [r for r in live if not r["prevalence_only"]]),
        ("  wording-only  (the fix owns these)",
         [r for r in live if r["wording_only"]]),
        ("  set-changing  (legitimate movement)",
         [r for r in live if not r["wording_only"]]),
    ]
    w("  %-38s %7s %7s %7s\n" % ("class", "n", "old", "new"))
    for label, sub in rows_out:
        n, o, nw = tally(sub)
        w("  %-38s %7d %7d %7d\n" % (label, n, o, nw))

    w("\nCROSS-TAB, wording-only x prevalence-only (n / old moved / new moved)\n")
    for wo in (True, False):
        for po in (True, False):
            sub = [r for r in live
                   if r["wording_only"] is wo and r["prevalence_only"] is po]
            if not sub:
                continue
            n, o, nw = tally(sub)
            w("  %-14s %-16s %7d %7d %7d\n"
              % ("wording-only" if wo else "set-changing",
                 "prevalence-only" if po else "mixed-reason", n, o, nw))

    bad = [r for r in live if r["wording_only"] and r["new_key_moved"]]
    w("\nVERDICT\n")
    w("  wording-only steps still moving under the new prose: %d%s\n"
      % (len(bad), "" if bad else "   <- the property the fix claims"))
    for r in bad[:10]:
        w("    %s %s step %d\n" % (r["appid"], r["bucket"], r["step"]))
    on_disk_saved = [r for r in live if r["wording_only"] and r["old_key_moved"]
                     and not r["new_key_moved"] and r["on_disk"]]
    w("  cached retry files this edit would have invalidated and no longer "
      "does: %d\n" % len(on_disk_saved))
    w("  distinct titles                                                     "
      "  : %d\n" % len({r["appid"] for r in on_disk_saved}))
    w("  by cohort: %s\n"
      % dict(collections.Counter(r["bucket"] for r in on_disk_saved)))


def show_signal(rows, n, out):
    """Real reconstructed 'Problems found:' blocks, old vs new, for reading."""
    out.write("Retry prompt SIGNAL spot-check, old prose vs new\n")
    out.write("driver: evals/measure_retry_key_stability_2026-08-25.py --show\n")
    out.write("Only the 'Problems found:' block is shown - the reviews block is\n"
              "byte-identical on both sides and is thousands of lines.\n")
    picked, seen = [], set()
    for r in rows:
        if not r["guard_changed_something"] or r["bucket"] in seen:
            continue
        if "prevalence" not in r["problems_old"] and \
           "how common" not in r["problems_old"]:
            continue
        seen.add(r["bucket"])
        picked.append(r)
    for r in rows:
        if len(picked) >= n:
            break
        if r not in picked and "how common" in r["problems_old"]:
            picked.append(r)
    for r in picked[:n]:
        out.write("\n%s\n%s  [%s]  %s  step %d\n"
                  % ("=" * 74, r["appid"], r["bucket"], r["game"], r["step"]))
        out.write("\n--- OLD (named the matched words) ---\n%s\n"
                  % r["problems_old"])
        out.write("\n--- NEW (category only) ---\n%s\n" % r["problems_new"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="replay0821",
                    choices=["replay0821", "future"],
                    help="replay the real 08-21 split, or free one banned word")
    ap.add_argument("--free", default="numerous",
                    help="word to free from PATTERNS, in memory (default: most)")
    ap.add_argument("--patterns-ref",
                    help="load PATTERNS from this git ref instead of the "
                         "working tree (reconciliation control)")
    ap.add_argument("--limit", type=int,
                    help="only walk the first N filtered files (smoke test)")
    ap.add_argument("--show", type=int, default=0,
                    help="also write N real problem blocks, old vs new")
    ap.add_argument("--out", help="write the report here as well as stdout")
    ap.add_argument("--show-out", help="write the --show blocks here")
    a = ap.parse_args()

    rows, err, desc, dropped = walk(a.mode, a.free, a.limit, a.patterns_ref)
    here = pathlib.Path(__file__).resolve().parent
    detail = here / ("retry-key-stability-2026-08-25-%s%s.json"
                     % (a.mode if a.mode != "future" else "free-%s" % a.free,
                        "-at-%s" % re.sub(r"[^0-9A-Za-z]+", "-",
                                          a.patterns_ref)
                        if a.patterns_ref else ""))
    json.dump([{k: v for k, v in r.items() if not k.startswith("problems_")}
               for r in rows], detail.open("w"), indent=1)

    report(rows, err, desc, dropped, sys.stdout)
    print("\nper-step detail -> %s" % detail)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            report(rows, err, desc, dropped, fh)
    if a.show:
        with open(a.show_out or (here / "retry-prompt-signal-2026-08-25.txt"),
                  "w", encoding="utf-8") as fh:
            show_signal(rows, a.show, fh)


if __name__ == "__main__":
    main()
