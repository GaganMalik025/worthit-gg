"""
WorthIt.gg - extraction pass (build plan 1.3)

Reads data/filtered/<appid>.json and turns each playtime cohort into discrete,
cited claims using Gemini 3.5 Flash-Lite with a structured output schema.

One request per cohort. The cohort is the unit of analysis - the product thesis
is that cohorts describe different games - and batching this way makes cohort
attribution *structural*: a claim can only cite ids that were in its own bucket's
prompt, so it cannot silently borrow evidence from veterans to describe refunders.

Model configuration (verified against current Gemini docs, July 2026):
  * thinking_level="minimal"  - the default for 3.5 Flash-Lite; set explicitly so
    the pinned config is reproducible rather than inherited.
  * NO temperature / top_p / top_k. Gemini 3.x deprecates and ignores them, and
    future generations return HTTP 400 if they are supplied (CLAUDE.md inv. 6).
  * No prefilled model turn: contents is a single user turn and the rules live in
    system_instruction. A trailing model turn is a 400 on this model generation.
  * No tools are declared, so the FunctionResponse id/name requirement does not
    apply to this pass.

Enforced in code, never merely requested in the prompt:
  * invariant 3  - >=2 distinct SURVIVING supporting ids per claim
  * invariant 11 - countless schema + prevalence-language guard on claim prose
  * invariant 12 - cohorts under the floor are never sent to the model at all

Usage:
    .venv/bin/python pipeline/extract_claims.py 233860 --dry-run
    .venv/bin/python pipeline/extract_claims.py 233860
"""

import argparse
import hashlib
import json
import os
import pathlib
import random
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_reviews import BUCKETS                      # noqa: E402  (invariant 2, single source)
from filter_reviews import MIN_COHORT                  # noqa: E402  (invariant 12)
import prevalence_guard                                # noqa: E402
import ground_check                                    # noqa: E402  (1.4)
import model_pacer                                     # noqa: E402  (4.1 RPM pacing)

IN_DIR = Path("data/filtered")
OUT_DIR = Path("data/claims")
CACHE_DIR = Path("data/cache/extract")
DEFAULT_MODEL = "gemini-3.5-flash-lite"

MAX_REVIEW_CHARS = 1500
MAX_ATTEMPTS = 5
BACKOFF_BASE = 2.0
PACE_SECONDS = 1.0          # keeps us under the 15 RPM free-tier ceiling

# Grouping headers for the claim list (DESIGN.md). These were a bare enum with
# no definition anywhere in the prompt, so the model had five words and had to
# guess what they meant - and there was no bucket at all for DRM, launchers,
# account requirements or always-online. Those claims went to "monetization",
# the nearest storefront-adjacent word: 11 claims across 8 published titles,
# including "the game requires a Microsoft account to play" filed under
# monetization. That is a taxonomy gap, not a model slip, so the fix is a bucket
# that fits plus definitions in the prompt (see RULE 7 in SYSTEM_INSTRUCTION).
THEMES = ["performance", "content", "difficulty", "access", "monetization",
          "other"]

# Countless by construction: no count, no frequency, no "how many" field exists
# for the model to fill. The only way prevalence can leak is prose, which is
# what prevalence_guard catches.
CLAIM_SCHEMA = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                # No sentiment field: we hold ground truth for it. Every cited
                # review carries voted_up, so sentiment is computed in code from
                # the citations rather than inferred by a model reading tone.
                # Kenshi is why - the model read community culture and tagged
                # "characters start weak, frequent defeats, limb loss" positive.
                "required": ["claim", "theme", "supporting_ids"],
                "properties": {
                    "claim": {"type": "string"},
                    "theme": {"type": "string", "enum": THEMES},
                    "supporting_ids": {"type": "array", "minItems": 2,
                                       "items": {"type": "string"}},
                },
            },
        }
    },
}

SYSTEM_INSTRUCTION = """\
You extract discrete, checkable claims from Steam reviews for a game-buying \
advice product. A reader must be able to open the cited reviews and verify each \
claim you write.

You are reading ONE cohort of reviewers, grouped by how long they had played \
when they wrote the review: {cohort_label} ({cohort_range}).

RULES

1. Every claim must be supported by at least TWO of the reviews below, and you \
must list their recommendationids verbatim in supporting_ids. Copy the ids \
exactly as given. Never invent an id, never cite an id that is not in this list.
2. A claim states something specific and falsifiable about the game as this \
cohort experienced it: what breaks, what is hard, what is missing, what works. \
"The game is good" is not a claim. "Reviewers describe the opening hours as \
unguided, with no tutorial explaining core systems" is a claim.
3. NEVER state how many or what proportion of players hold a view. You are \
reading a deliberately non-representative sample: cohorts were quota-sampled, \
thin cohorts were over-sampled on purpose, and low-information reviews were \
filtered out. You cannot see how common anything is, so you may not say.
   BANNED: most, majority, minority, many players, few players, half, a third, \
commonly, widely, usually, typically, generally, often, everyone, nobody, \
percentages, "X out of Y".
   Write "reviewers describe X" or "this cohort reports X".
   Do NOT write "most players find X" or "many reviewers say X".
4. Do not merge unrelated complaints into one claim. Prefer several precise \
claims over one broad one.
5. Say only what the review text supports. No outside knowledge about this game, \
no inference about the developer's intent, no speculation about patches.
5b. Do not judge whether reviewers liked the game, and do not soften or \
harden a claim to match a tone you infer. Report what they describe; whether \
each cited review was a thumbs-up or thumbs-down is already known and is not \
your call.
6. If fewer than two reviews support an observation, omit it entirely. Returning \
an empty list is a valid and correct answer.
7. Pick the theme that matches what the claim is ABOUT. These are grouping \
headers a reader sees, so a wrong one is visible:
   performance  - how it runs: frame rate, stutter, crashes, bugs, load times, \
hardware behaviour, technical instability.
   content      - what is in the game: story, missions, world, characters, \
art, audio, features present or missing, cut or changed from an earlier version.
   difficulty   - how hard it is to play or learn: challenge, balance, \
grind, tutorials, controls, accessibility of the systems themselves.
   access       - what stands between owning it and playing it: third-party \
launchers, mandatory accounts or sign-ins, always-online or internet \
requirements, DRM, region or platform restrictions. Use this even when the \
barrier belongs to a publisher's store - it is about ACCESS, not money.
   monetization - money: price, value for money, microtransactions, paid DLC, \
season passes, subscriptions, in-game stores.
   other        - none of the above genuinely fits. Prefer a real theme.
A claim about a launcher or a required account is ALWAYS access, never \
monetization, even if the launcher also sells things - in that case write the \
selling as a separate monetization claim if the reviews support one.
"""

USER_PREAMBLE = """\
Reviews from the {cohort_label} cohort ({cohort_range}) of {game}.
Each line is: [recommendationid] (hours played at time of review, verdict) text

{reviews}
"""


RETRY_PREAMBLE = """\
Your previous response contained claims that could not be verified. Produce a \
corrected set of claims for the SAME cohort and the SAME reviews, listed again \
below.

Problems found:

{problems}

How to fix them:
- If a claim could not be verified against its citations, the citations are the \
problem, not the wording. Either cite the reviews that genuinely support the \
claim, or drop the claim entirely. Do NOT reword a claim to echo the reviews' \
vocabulary - copying their phrasing does not make a claim better supported.
- If a claim stated how common something is, restate it without any frequency, \
proportion or quantity language, or drop it.
- Dropping a claim is always acceptable. Returning fewer, well-cited claims is \
better than returning the same number.

Return the complete corrected list, including the claims that were fine.

{reviews_block}
"""


def cohort_range_hours(bucket):
    """Bucket bounds in HOURS. Invariant 1: raw minutes never reach a prompt."""
    for name, lo, hi in BUCKETS:
        if name != bucket:
            continue
        lo_h = lo / 60.0
        if hi == float("inf"):
            return "%g+ hours played" % lo_h
        return "%g-%g hours played" % (lo_h, hi / 60.0)
    return "unknown playtime"


COHORT_LABEL = {
    "refund_window": "refund-window",
    "early": "early",
    "mid": "mid",
    "veteran": "veteran",
}


# A retry is told to return the complete corrected list, so it re-emits claims
# that were already fine - sometimes reworded. Exact-text dedupe misses those,
# and the Kenshi early cohort produced two wordings of "the interface feels
# dated" at 0.67 token overlap. Merge on meaning, keeping the better-cited one.
DEDUPE_OVERLAP = 0.5


def _merge_dedup(accepted, candidates):
    """Add candidates to accepted, collapsing near-duplicates.

    Ties break toward more supporting citations: same claim, more receipts.
    """
    merged, dropped = list(accepted), []
    for cand in candidates:
        ct = ground_check.tokens(cand["claim"])
        replaced = False
        for i, existing in enumerate(merged):
            et = ground_check.tokens(existing["claim"])
            if not ct or not et:
                continue
            overlap = len(ground_check.fuzzy_hits(ct, et)) / max(len(ct), len(et))
            if overlap < DEDUPE_OVERLAP:
                continue
            if len(cand["supporting_ids"]) > len(existing["supporting_ids"]):
                dropped.append((existing["claim"], "superseded"))
                merged[i] = cand
            else:
                dropped.append((cand["claim"], "duplicate"))
            replaced = True
            break
        if not replaced:
            merged.append(cand)
    return merged, dropped


def _problem_line(result):
    """Plain-language reason, deliberately free of overlap-speak.

    Never says "your claim did not share enough words with the reviews" - that
    teaches the model to parrot review text, which games the grounding check
    while making claims worse.
    """
    reasons = []
    for f in result["failures"]:
        if f.startswith("prevalence_language"):
            terms = f.split(":", 1)[1]
            reasons.append("states how common something is (%s)" % terms)
        elif f.startswith("low_union_coverage"):
            reasons.append("could not be verified against the reviews it cites")
        elif f.startswith("only_"):
            reasons.append("only one cited review actually supports it; two are "
                           "required")
        elif f.startswith("cited_outside_bucket"):
            reasons.append("cites a review from a different cohort")
        elif f.startswith("ids_not_in_corpus"):
            reasons.append("cites a review id that does not exist")
    return "- \"%s\"\n    problem: %s" % (result["claim"], "; ".join(reasons))


def build_retry_prompt(game, bucket, reviews, failures):
    _, reviews_block = build_prompts(game, bucket, reviews)
    problems = "\n".join(_problem_line(f) for f in failures)
    return RETRY_PREAMBLE.format(problems=problems, reviews_block=reviews_block)


def build_prompts(game, bucket, reviews):
    lines = []
    for r in reviews:
        text = " ".join((r.get("review_text") or "").split())
        if len(text) > MAX_REVIEW_CHARS:
            text = text[:MAX_REVIEW_CHARS] + " ...[truncated]"
        verdict = "recommends" if r.get("voted_up") else "does not recommend"
        lines.append("[%s] (%.1fh, %s) %s"
                     % (r.get("recommendationid"), r.get("hours_at_review") or 0.0,
                        verdict, text))
    label, rng = COHORT_LABEL.get(bucket, bucket), cohort_range_hours(bucket)
    system = SYSTEM_INSTRUCTION.format(cohort_label=label, cohort_range=rng)
    user = USER_PREAMBLE.format(cohort_label=label, cohort_range=rng, game=game,
                                reviews="\n\n".join(lines))
    return system, user


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def load_env(path=".env"):
    p = pathlib.Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def cache_path(appid, bucket, model, system, user, tag="extract-v1"):
    # tag participates in the key so a response produced under a different
    # output schema can never be replayed for a different stage
    digest = hashlib.sha256(("%s\x00%s\x00%s\x00%s" % (tag, model, system, user))
                            .encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / str(appid) / ("%s_%s.json" % (bucket, digest))


def response_text(resp):
    """Pull the answer text out of the response, explicitly.

    Gemini 3.x returns a thought_signature alongside the answer, and thinking
    parts can appear as separate parts. Reading `.text` blindly would either
    concatenate a thought into the JSON or trip over a part with no text at all,
    so walk the parts and take only non-thought text. Returns (text, census).
    """
    census = {"parts": 0, "text_parts": 0, "thought_parts": 0,
              "thought_signatures": 0, "used": "parts"}
    chunks = []
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates[:1]:
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            census["parts"] += 1
            if getattr(part, "thought_signature", None):
                census["thought_signatures"] += 1
            if getattr(part, "thought", False):
                census["thought_parts"] += 1
                continue          # reasoning, never the payload
            if getattr(part, "text", None):
                census["text_parts"] += 1
                chunks.append(part.text)
    if not chunks:                # nothing walked cleanly - fall back
        census["used"] = "resp.text"
        return (getattr(resp, "text", "") or ""), census
    return "".join(chunks), census


def call_model(client, model, system, user, schema=None, thinking_level="minimal"):
    """One structured-output call, with backoff on quota/transient errors.

    schema is a parameter, not a constant: synthesis reuses this transport with
    the verdict schema. Hardcoding CLAIM_SCHEMA here once made the synthesis
    pass return extraction-shaped claims that passed every check by being the
    wrong thing entirely.
    """
    from google.genai import types
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema if schema is not None else CLAIM_SCHEMA,
        # extraction pins minimal (this model's default); synthesis reasons more
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
        # NO temperature / top_p / top_k - deprecated and ignored on Gemini 3.x
    )
    for attempt in range(MAX_ATTEMPTS):
        try:
            # Proactive rate pacing, shared across processes. The batch runs
            # stages as subprocesses, so this is the only place a per-minute
            # limit can be enforced for every title at once. Synthesis reuses
            # this transport, so it is paced by the same bucket.
            with model_pacer.pace(model.split("/")[-1]):
                resp = client.models.generate_content(
                    model=model, contents=user, config=config)
            return resp
        except Exception as exc:  # noqa: BLE001 - SDK raises a family of these
            msg = str(exc)
            if "401" in msg or "UNAUTHENTICATED" in msg or "PERMISSION_DENIED" in msg:
                raise SystemExit(
                    "\nGEMINI_API_KEY was rejected (401 UNAUTHENTICATED).\n"
                    "  The key in .env is an 'AQ.' auth key, which is the current\n"
                    "  AI Studio format - the format is fine, the credential is not\n"
                    "  being accepted for generativelanguage.googleapis.com.\n"
                    "  Check in AI Studio that the key is active and that its bound\n"
                    "  service account has the Gemini API enabled, or issue a new key.\n"
                    "  Nothing was spent; no quota consumed.")
            transient = any(s in msg for s in
                            ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                             "500", "INTERNAL", "504", "DEADLINE"))
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                # A 429 is TWO different failures wearing one status code, and
                # treating them alike is what collapsed night 1 and then the
                # second batch:
                #
                #   PerMinute -> a real rate problem. Lowering the ceiling helps.
                #   PerDay    -> the daily allowance is gone. Lowering the rate
                #                cannot help; it just makes every remaining call
                #                wait 60s to fail. The flash daily exhaustion
                #                narrowed this SHARED pacer to 1 rpm and
                #                throttled flash-lite along with it.
                #
                # The quota id says which. Only a rate limit narrows the rate.
                if "PerDay" in msg:
                    print("    daily quota exhausted for this model - the pacer "
                          "is not narrowed (a rate cut cannot buy back a day)")
                else:
                    ceiling = model_pacer.narrow(
                        model_pacer.status()["ceiling_rpm"] - 2)
                    print("    pacer: per-minute 429 despite pacing - ceiling "
                          "now %d rpm" % ceiling)
            if not transient or attempt == MAX_ATTEMPTS - 1:
                raise
            wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
            print("    %s - backing off %.1fs (attempt %d/%d)"
                  % (msg.split("{")[0][:60].strip(), wait, attempt + 1, MAX_ATTEMPTS))
            time.sleep(wait)


# --------------------------------------------------------------------------
# enforcement (invariants 3 and 11)
# --------------------------------------------------------------------------

def derive_citation_verdict(ids, voted_up_by_id):
    """What the CITING REVIEWERS thought of the GAME - not of this claim.

    Read this field's meaning carefully before using it anywhere:

      citation_verdict = the aggregate Steam recommendation (voted_up) of the
      reviews cited by this claim, for the game overall.

      It is NOT the valence of the claim. Kenshi's veteran cohort produces
      "the game features frequent bugs, crashes and technical jank" at 4u/1d -
      a complaint, cited by reviewers who recommend the game anyway. Treating
      that as claim sentiment would render "Veterans - positive: the game has
      frequent crashes", which is incoherent.

    Ground truth, not inference: every cited review already carries voted_up.
    Asking a model to infer tone invites the failure this replaced, where a
    community that celebrates brutality made "characters start weak, frequent
    defeats, limb loss" read as praise.

    Two-thirds agreement to be called; below that it is genuinely contested and
    says so. The raw split travels with it - a count of citations on one claim,
    which invariant 13 permits as evidence, never to be rendered as a rate.

    Claim grouping stays theme-based (DESIGN.md); cohort sentiment stays
    pool-rate-derived (invariant 13). Nothing downstream consumes this as
    claim valence.
    """
    pos = sum(1 for i in ids if voted_up_by_id.get(i) is True)
    neg = sum(1 for i in ids if voted_up_by_id.get(i) is False)
    total = pos + neg
    if not total:
        label = "unknown"
    elif pos / total >= 2 / 3:
        label = "positive"
    elif neg / total >= 2 / 3:
        label = "negative"
    else:
        label = "mixed"
    return label, {"positive": pos, "negative": neg}


def enforce(raw_claims, valid_ids, voted_up_by_id=None, bucket=None):
    """Filter model output down to what the evidence actually supports.

    Order matters: unknown ids are stripped BEFORE the >=2 rule is applied, so a
    claim citing three ids of which two are hallucinated is correctly rejected as
    a one-review claim. The schema's minItems cannot see that.
    """
    kept, rejected = [], []
    for c in raw_claims or []:
        text = (c.get("claim") or "").strip()
        ids = c.get("supporting_ids") or []
        seen, clean, unknown = set(), [], []
        for rid in ids:
            rid = str(rid).strip()
            if rid in seen:
                continue
            seen.add(rid)
            (clean if rid in valid_ids else unknown).append(rid)

        if unknown and not clean:
            rejected.append({"claim": text, "reason": "all_ids_unknown",
                             "unknown_ids": unknown})
            continue
        if len(clean) < 2:
            rejected.append({"claim": text,
                             "reason": "under_two_supporting_reviews",
                             "kept_ids": clean, "unknown_ids": unknown})
            continue

        verdict, split = derive_citation_verdict(clean, voted_up_by_id or {})
        # Content-derived so it survives regeneration of identical text and eval
        # cases can cite it. Invariant 4 rejects any id synthesis did not get
        # from here.
        claim_id = "%s-%s" % (
            (bucket or "x")[:3],
            hashlib.sha1(text.encode("utf-8")).hexdigest()[:6])
        entry = {"claim_id": claim_id,
                 "claim": text, "theme": c.get("theme") or "other",
                 # see derive_citation_verdict: the citing reviewers' verdict on
                 # the GAME, not the valence of this claim
                 "citation_verdict": verdict, "citation_split": split,
                 "supporting_ids": clean}
        if c.get("sentiment"):
            # only present if an older cached response still carries the field
            entry["model_sentiment_ignored"] = c["sentiment"]
        if unknown:
            # survived on its real citations; note what was invented
            entry["dropped_unknown_ids"] = unknown
        kept.append(entry)
    return kept, rejected


# --------------------------------------------------------------------------

def extract_bucket(client, args, game, appid, bucket, reviews):
    valid_ids = {str(r.get("recommendationid")) for r in reviews}
    system, user = build_prompts(game, bucket, reviews)

    print("\n=== %s / %s (n=%d, %s) ===" % (game, bucket, len(reviews),
                                            cohort_range_hours(bucket)))
    if args.show_prompt or args.dry_run:
        print("--- system_instruction ---\n%s" % system)
        print("--- user turn (first 1200 chars of %d) ---\n%s\n..."
              % (len(user), user[:1200]))
    if args.dry_run:
        print("(dry run - no request made)")
        return None

    cfg = {"min_coverage": args.min_coverage,
           "min_citation_coverage": args.min_citation_coverage,
           "min_supporting": args.min_supporting}
    corpus = {str(r["recommendationid"]): r for r in reviews}
    voted_up_by_id = {str(r.get("recommendationid")): r.get("voted_up")
                      for r in reviews}

    accepted, attempts, dropped = [], [], []
    prompt = user
    for attempt in range(args.ground_retries + 1):
        text = _generate(client, args, appid, bucket, system, prompt, attempt)
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            print("  !! response was not valid JSON: %s" % exc)
            attempts.append({"attempt": attempt, "error": "invalid_json"})
            break

        raw_claims = parsed.get("claims") or []
        kept, rejected = enforce(raw_claims, set(corpus), voted_up_by_id, bucket)

        # 1.4: deterministic grounding, before anything downstream sees a claim
        if args.no_ground:
            passed, failed = kept, []
        else:
            passed, failed, _ = ground_check.check_bucket(kept, bucket, corpus, cfg)

        accepted, deduped = _merge_dedup(accepted, passed)
        for claim_text, why in deduped:
            print("     [dedupe/%s] %s" % (why, claim_text[:80]))
        attempts.append({"attempt": attempt, "returned": len(raw_claims),
                         "deduped": len(deduped),
                         "enforce_rejected": len(rejected),
                         "grounding_rejected": len(failed),
                         "accepted_running_total": len(accepted)})

        print("\n--- attempt %d: model returned %d, enforce rejected %d, "
              "grounding rejected %d, accepted %d ---"
              % (attempt, len(raw_claims), len(rejected), len(failed), len(passed)))
        for r in rejected:
            print("     [enforce/%s] %s" % (r["reason"], r["claim"][:80]))
        for f in failed:
            print("     [grounding] %s" % f["claim"][:80])
            for reason in f["failures"]:
                print("          ! %s" % reason)

        dropped = failed
        if not failed or attempt == args.ground_retries:
            break
        print("\n  regenerating %s (attempt %d of %d)..."
              % (bucket, attempt + 1, args.ground_retries))
        prompt = build_retry_prompt(game, bucket, reviews, failed)

    print("\n--- %s final: %d grounded claims, %d dropped ---"
          % (bucket, len(accepted), len(dropped)))
    for c in accepted:
        s = c["citation_split"]
        print("     (%s | cited reviewers %s %du/%dd) %s"
              % (c["theme"], c["citation_verdict"], s["positive"], s["negative"],
                 c["claim"]))
        print("        ids: %s" % ", ".join(c["supporting_ids"]))

    return {
        "bucket": bucket,
        "n_reviews": len(reviews),
        "kept": len(accepted),
        "claims": accepted,
        "attempts": attempts,
        "dropped_after_retries": [
            {"claim": f["claim"], "failures": f["failures"],
             "union_coverage": f["union_coverage"]} for f in dropped],
    }


def _generate(client, args, appid, bucket, system, user, attempt):
    """One call, served from cache when the identical prompt has run before."""
    cpath = cache_path(appid, bucket, args.model, system, user)
    if cpath.exists() and not args.force:
        payload = json.loads(cpath.read_text(encoding="utf-8"))
        text, cached = payload["text"], True
    else:
        resp = call_model(client, args.model, system, user)
        text, census = response_text(resp)
        cached = False
        print("  response parts: %d (%d text, %d thought, %d carrying "
              "thought_signature) via %s"
              % (census["parts"], census["text_parts"], census["thought_parts"],
                 census["thought_signatures"], census["used"]))
        usage = getattr(resp, "usage_metadata", None)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps({
            "model": args.model, "text": text,
            "usage": {"prompt": getattr(usage, "prompt_token_count", None),
                      "total": getattr(usage, "total_token_count", None)},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(PACE_SECONDS)

    print("--- RAW MODEL OUTPUT (attempt %d)%s ---"
          % (attempt, " [cached]" if cached else ""))
    print(text)
    return text


def main():
    ap = argparse.ArgumentParser(description="WorthIt.gg extraction pass (1.3)")
    ap.add_argument("appid")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--bucket", default=None, help="run one bucket only")
    ap.add_argument("--force", action="store_true", help="ignore the response cache")
    ap.add_argument("--dry-run", action="store_true", help="print prompts, call nothing")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--ground-retries", type=int, default=2,
                    help="regeneration attempts when grounding fails (default 2)")
    ap.add_argument("--min-coverage", type=float,
                    default=ground_check.MIN_UNION_COVERAGE)
    ap.add_argument("--min-citation-coverage", type=float,
                    default=ground_check.MIN_CITATION_COVERAGE)
    ap.add_argument("--min-supporting", type=int,
                    default=ground_check.MIN_SUPPORTING_CITATIONS)
    ap.add_argument("--no-ground", action="store_true",
                    help="skip the grounding check (diagnostics only)")
    ap.add_argument("--src", default=str(IN_DIR))
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    src = Path(args.src) / ("%s.json" % args.appid)
    if not src.exists():
        print("no %s - run filter_reviews.py first" % src)
        sys.exit(1)
    blob = json.loads(src.read_text(encoding="utf-8"))
    game = blob.get("game_name") or args.appid

    by_bucket = OrderedDict()
    for r in blob.get("reviews", []):
        by_bucket.setdefault(r.get("bucket"), []).append(r)

    client = None
    if not args.dry_run:
        load_env()
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            print("GEMINI_API_KEY missing from .env")
            sys.exit(1)
        from google import genai
        client = genai.Client(api_key=key)

    print("extracting %s (%s) with %s" % (game, args.appid, args.model))
    results, skipped = [], []
    for bucket, _, _ in BUCKETS:
        reviews = by_bucket.get(bucket) or []
        if args.bucket and bucket != args.bucket:
            continue
        if not reviews:
            continue
        # invariant 12: a muted cohort never reaches the model, and costs nothing
        if len(reviews) < MIN_COHORT:
            print("\n=== %s / %s (n=%d) - SKIPPED, below the %d-review cohort "
                  "floor (invariant 12). No claims, no request."
                  % (game, bucket, len(reviews), MIN_COHORT))
            skipped.append({"bucket": bucket, "n_reviews": len(reviews),
                            "skipped": "below_cohort_floor"})
            continue
        out = extract_bucket(client, args, game, args.appid, bucket, reviews)
        if out:
            results.append(out)

    if args.dry_run:
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("%s.json" % args.appid)
    out_path.write_text(json.dumps({
        "appid": args.appid,
        "game_name": blob.get("game_name"),
        "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": args.model,
        "thinking_level": "minimal",
        # carried through untouched - the only sanctioned prevalence source
        "pool": blob.get("pool"),
        "grounding": {
            "checked": not args.no_ground,
            "min_coverage": args.min_coverage,
            "min_citation_coverage": args.min_citation_coverage,
            "min_supporting": args.min_supporting,
            "retries_allowed": args.ground_retries,
        },
        "extraction_report": {"buckets": results, "skipped": skipped},
        "claims_by_bucket": {r["bucket"]: r["claims"] for r in results},
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(r["kept"] for r in results)
    print("\nwrote %d claims across %d cohorts -> %s" % (total, len(results), out_path))


if __name__ == "__main__":
    main()
