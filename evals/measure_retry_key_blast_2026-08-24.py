"""Blast radius of the 2026-08-21 guard split on cached RETRY prompts.

Free: reads data/filtered/ and data/cache/extract/ only. No network, no Gemini.
The retry PROMPT is not stored on disk (cache holds model/text/usage), so each
chain's failure lists are reconstructed by replaying enforce + ground_check over
the cached responses, following the on-disk keys.
"""
import json, pathlib, re, sys, collections
sys.path.insert(0, "pipeline")
import extract_claims as ec, ground_check, prevalence_guard as pg

MODEL = "gemini-3.5-flash-lite"
BUCKETS = ("refund_window", "early", "mid", "veteran")
CFG = {"min_coverage": ground_check.MIN_UNION_COVERAGE,
       "min_citation_coverage": ground_check.MIN_CITATION_COVERAGE,
       "min_supporting": ground_check.MIN_SUPPORTING_CITATIONS}
POST = list(pg.COMPILED)
PRE = [(re.compile(p, re.IGNORECASE), l)
       for p, l in pg.PATTERNS + pg.FREED_FREQUENCY_PATTERNS]
FREED = {w for p, _ in pg.FREED_FREQUENCY_PATTERNS
         for w in re.findall(r"[a-z]{3,}", p) if w not in ("re", "b")}

def failures(kept, bucket, corpus, compiled):
    pg.COMPILED = compiled
    _, failed, _ = ground_check.check_bucket(kept, bucket, corpus, CFG)
    return failed

def terms(failed):
    out = set()
    for f in failed:
        for r in f["failures"]:
            if r.startswith("prevalence_language:"):
                out |= set(r.split(":", 1)[1].split(","))
    return out

rows, err = [], 0
for fp in sorted(pathlib.Path("data/filtered").glob("*.json")):
    appid = fp.stem
    try:
        blob = json.loads(fp.read_text())
    except Exception:
        err += 1; continue
    game = blob.get("game_name") or appid
    by = collections.defaultdict(list)
    for r in blob.get("reviews", []):
        by[r.get("bucket")].append(r)
    for b in BUCKETS:
        rv = by.get(b) or []
        if len(rv) < ec.MIN_COHORT:
            continue
        corpus = {str(r["recommendationid"]): r for r in rv}
        voted = {str(r.get("recommendationid")): r.get("voted_up") for r in rv}
        system, user = ec.build_prompts(game, b, rv)
        prompt, step = user, 0
        while step <= 2:
            p = ec.cache_path(appid, b, MODEL, system, prompt)
            if not p.exists():
                break
            try:
                kept, _ = ec.enforce(json.loads(json.loads(p.read_text())["text"]).get("claims") or [],
                                     set(corpus), voted, b)
            except Exception:
                err += 1; break
            f_pre = failures(kept, b, corpus, PRE)
            if not f_pre or step == 2:
                break
            # this response drove a retry: does its failure list name a freed term?
            f_post = failures(kept, b, corpus, POST)
            t_pre, t_post = terms(f_pre), terms(f_post)
            k_pre = ec.cache_path(appid, b, MODEL, system,
                                  ec.build_retry_prompt(game, b, rv, f_pre)).name
            k_post = ec.cache_path(appid, b, MODEL, system,
                                   ec.build_retry_prompt(game, b, rv, f_post)).name
            rows.append({"appid": appid, "game": game, "bucket": b, "step": step + 1,
                         "freed_named": sorted(t_pre - t_post),
                         "key_changed": k_pre != k_post,
                         "on_disk": pathlib.Path("data/cache/extract", appid, k_pre).exists()})
            prompt = ec.build_retry_prompt(game, b, rv, f_pre)
            step += 1

pg.COMPILED = POST
OUT = pathlib.Path(__file__).with_name("retry-key-blast-2026-08-24.json")
json.dump(rows, OUT.open("w"), indent=1)
print("per-step detail -> %s" % OUT)
aff = [r for r in rows if r["key_changed"]]
print("freed words tracked : %d  %s" % (len(FREED), ", ".join(sorted(FREED))))
print("retry steps replayed: %d   (parse/read errors: %d)" % (len(rows), err))
print("  of which the 08-21 split CHANGES the retry key: %d" % len(aff))
print("  distinct titles affected                      : %d" % len({r["appid"] for r in aff}))
print("  by cohort:", dict(collections.Counter(r["bucket"] for r in aff)))
print("  freed terms responsible:",
      dict(collections.Counter(w for r in aff for w in r["freed_named"]).most_common()))
