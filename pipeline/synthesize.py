"""
WorthIt.gg - synthesis pass (build plan 1.5)

Turns grounded claims into the verdict JSON the static site serves:
site/public/verdicts/<appid>.json.

The model's job is deliberately tiny. It writes the three-part header (a tagline
about the game, then the "for you if" and "not for you if" clause lists), one
sentence per cohort and one per detected flag, and orders the claims. Everything
else - the VERDICT WORD, every number, which flags fire, theme grouping,
citations, muted sections - is computed in code.

The header used to be a single for-whom sentence doing all three jobs at once,
which is why material friction kept coming out as a purchase condition
("suits players willing to tolerate the launcher") no matter how the rule was
worded: a sentence that must name an audience has nowhere neutral to put a
requirement. Splitting it gives the condition a heading that admits it is one.

The verdict word used to be the exception, and it was the bug: decided by prose
instruction, it swung the whole catalog whenever that prose was rewritten. It is
now verdict_for_mean(post_refund_mean(cohorts)) and the model is told the answer
rather than asked for it.

It never sees review text at this stage, only claims. That is the two-pass
separation (PRD D3), and it is what makes invariant 4 enforceable: the model can
reference a claim id or it can reference nothing.

Enforced in code after the response:
  invariant 4  - unknown claim id rejected; a claim id may only appear under the
                 cohort that produced it
  invariant 11 - prevalence guard over every sentence the model wrote
  invariant 12 - a muted cohort carries no claims and no summary
  invariant 13 - any digit in model prose is rejected; code renders all numbers

Usage:
    .venv/bin/python pipeline/synthesize.py 233860
    .venv/bin/python pipeline/synthesize.py --seeds
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import art as art_mod                                  # noqa: E402  (cover art tiers)
import flags as flags_mod                              # noqa: E402
import live_quota                                      # noqa: E402  (flash daily cap)
import model_pacer                                     # noqa: E402
import prevalence_guard                                # noqa: E402
from extract_claims import (CACHE_DIR, PACE_SECONDS, call_model,  # noqa: E402
                            cache_path, load_env, response_text)
from fetch_reviews import BUCKETS, SEED_GAMES          # noqa: E402

CLAIMS_DIR = Path("data/claims")
FILTERED_DIR = Path("data/filtered")
OUT_DIR = Path("site/public/verdicts")
# flash-lite, not flash. gemini-3.5-flash carries a free-tier limit of 20
# requests PER PROJECT PER DAY (quotaId GenerateRequestsPerDayPerProjectPerModel
# -FreeTier), and one synthesis call is one verdict - so it capped the whole
# product at ~20 verdicts a day and killed night 1 of the catalog batch at title
# 17. flash-lite has its own, far larger, daily bucket.
#
# thinking_level stays "medium" here. Extraction pins "minimal" per CLAUDE.md
# invariant 6; synthesis is the stage that actually reasons - it picks which
# claims survive and writes the header prose - so it keeps the higher level.
# The discipline that carries over from extraction is the part that matters:
# pinned model id, structured output schema, explicit thinking_level, and no
# sampling parameters.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Titles listed in pipeline/data/flash_tier.txt are synthesized with flash
# instead - the scarce, 20/day model, spent on the highest-reach titles. See
# that file for the schedule and the cutoff.
FLASH_MODEL = "gemini-3.5-flash"
FLASH_TIER_PATH = Path(__file__).resolve().parent / "data/flash_tier.txt"
MAX_CITATION_CHARS = 2000

# DESIGN.md Split Bar labels
COHORT_LABELS = OrderedDict([
    ("refund_window", "<2h refund window"),
    ("early", "2-20h"),
    ("mid", "20-100h"),
    ("veteran", "100h+"),
])
HOURS_RANGE = OrderedDict([
    ("refund_window", "under 2 hours"),
    ("early", "2-20 hours"),
    ("mid", "20-100 hours"),
    ("veteran", "over 100 hours"),
])

# The three parts of the header, and the bounds they are held to. The counts and
# the clause length are enforced in check_response, NOT by minItems/maxItems in
# the schema: rule 7 already demonstrated what happens when a shape lives only in
# words the model reads, and the structured-output subset's array bounds are not
# something a launch-blocking shape should rest on.
FIT_MIN, FIT_MAX = 2, 4
CLAUSE_MAX_CHARS = 80
# The tagline sits beside the stamp chip, so its length is a layout constraint,
# not a style preference: measured in the approved mockup, ~70 characters holds
# one line at the 680px reading column and 90 is the point past which it starts
# pushing the stamp around. The first A/B run produced a 108-character tagline
# that wrapped to three lines - hence a cap, enforced the same way as the clause
# cap rather than asked for in the prompt.
TAGLINE_MAX_CHARS = 90

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["tagline", "for_you_if", "not_for_you_if", "cohorts"],
    "properties": {
        "tagline": {"type": "string"},
        "for_you_if": {"type": "array", "items": {"type": "string"}},
        "not_for_you_if": {"type": "array", "items": {"type": "string"}},
        "cohorts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["bucket", "summary", "claim_ids"],
                "properties": {
                    "bucket": {"type": "string",
                               "enum": list(COHORT_LABELS)},
                    "summary": {"type": "string"},
                    "claim_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "flag_sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["flag_id", "sentence"],
                "properties": {"flag_id": {"type": "string"},
                               "sentence": {"type": "string"}},
            },
        },
    },
}

_SYSTEM_TEMPLATE = """\
You write the verdict for a game-buying advice product. A reader has two \
minutes and one question: should I buy this game?

You are given claims already extracted from Steam reviews and grouped by how \
long the reviewer had played. Each claim has an id. You may reference claims by \
id. You may not write new ones.

RULES

1. Use ONLY the claim ids given to you, and only under the cohort they came \
from. Inventing an id, or moving a claim to a different cohort, is the one \
unrecoverable error here.
1b. Claim ids go in the claim_ids array and NOWHERE ELSE. Never write an id \
into a summary, the tagline, a fit clause or a flag sentence. A reader cannot \
see ids, \
and an id in prose is rejected automatically because it contains digits. \
WRONG: "Players praise the freedom ref-e18e82, ear-6b753e." \
RIGHT: "Players praise the freedom." with those ids listed in claim_ids.
2. Write NO numbers of any kind in prose. No digits, no percentages, no \
counts, no "two thirds", no "half", and never an hour boundary - write "within \
the refund window", not the hours behind it. The interface renders every figure \
itself from verified data. Any digit in prose is rejected.
3. Never state how many or what proportion of players hold a view, and never \
state how OFTEN something happens. You are looking at a deliberately \
non-representative sample: thin cohorts are over-sampled on purpose, so \
counting anything here says nothing about the playerbase, and a rate is as \
unknowable as a proportion. Simply drop the word - "veterans praise the combat" \
is stronger than "most veterans praise the combat", and "reviewers report \
crashes" says everything "occasional crashes" was trying to say. \
BANNED WORDS: %(banned)s. \
Also banned: percentages, "N out of N", "a third of", "half the players".
4. Each claim shows what its citing reviewers thought of the GAME overall. That \
is not the same as whether the claim is good or bad news: a complaint from \
people who recommend the game anyway is a real and useful pattern. Say so \
plainly instead of resolving it into agreement.
5. Cohorts that disagree must be LEFT DISAGREEING. Flattening them into one \
agreed view is the exact failure this product exists to correct. If people who \
bounced early and people who stayed describe different games, say that.
6. A cohort marked MUTED gets no summary and no claims. Skip it entirely.
7. YOU WRITE THREE THINGS UNDER THE VERDICT STAMP AND THEY DO DIFFERENT JOBS. \
Never make one of them do another's. \
(a) tagline - ONE short line about the GAME, a dozen words at most: it sits \
beside the verdict stamp and a longer one wraps and shoves the stamp around. \
This is the only line on the page allowed some character, so give it some. It \
names no audience, sets no condition, and asks nothing of the reader. \
RIGHT: "Great heroes, rough machine - the fights look better than they run." \
WRONG: "For patient players who can tolerate rough performance." - that is an \
audience and a condition, and both belong below, not here. \
(b) for_you_if - between two and four SHORT clauses, second person, one idea \
each, naming the reader this suits: "you play in a stack that can absorb a bad \
match". \
(c) not_for_you_if - the same, for the reader it does not suit. \
These are CLAUSES, NOT SENTENCES: no full stop, nothing over about a dozen \
words. A clause the reader has to read twice has already failed.
7b. MATERIAL FRICTION GOES IN not_for_you_if, AS A CLAUSE. A mandatory \
third-party launcher, a required account or sign-in, an always-online \
requirement, heavy storage, technical instability, a punishing learning curve: \
"you will not install a third-party launcher", "you need stable frame rates on \
release hardware", "you are short on storage space". Under this heading a \
condition is honest, because the heading itself says it is a condition. \
IT MAY NOT MOVE INTO THE TAGLINE. The tagline never says "willing to tolerate", \
"willing to overlook", "can tolerate", "if you can overlook", "provided you \
accept", "must put up with" or any relative of those. Those turn the verdict \
into a test the reader has to sit, and the verdict is already settled by the \
cohort data - asking them to weigh whether they can put up with something is \
asking them to re-decide it.
8. Flag sentences describe WHAT the pattern is, never WHY it happened. Do not \
speculate about controversies, publishers, patches or review campaigns.
9. THE VERDICT WORD IS GIVEN TO YOU, in the turn below. It is computed from the cohort rates before you are called, and it is not yours to choose, argue with, or soften. The tagline must read naturally under that word. \
BOTH LISTS ARE WRITTEN ON EVERY VERDICT, SKIP INCLUDED. A Skip still has people \
it would suit, and saying who they are is this product's entire thesis - it is \
not an endorsement and never phrases itself as one. Never write "buy it anyway" \
under a Skip, or "skip it" under a Buy; not_for_you_if is an audience carve-out, \
never a rebuttal of the word. \
You are not being asked whether the word is right. A claim list can look grim under a Buy and encouraging under a Wait - rule 4 already told you those coexist - and that is not a contradiction to resolve.
"""

# Filled from prevalence_guard so the prompt cannot drift behind the rule it
# explains. It drifted once: the guard rejected the frequency ADJECTIVES
# (frequent, occasional, widespread) while the prompt named only the adverbs,
# so synthesis failed on "occasional technical crashes" - a word nothing had
# told the model to avoid. Both models were exposed; flash-lite reached for it
# more often, which is how it surfaced.
SYSTEM_INSTRUCTION = _SYSTEM_TEMPLATE % {
    "banned": ", ".join(prevalence_guard.banned_words())}



def flash_tier():
    """{appid: scheduled day} for titles that get flash. Missing file -> {}.

    The DAY matters and used to be ignored. flash_tier.txt carried the schedule
    in its comments while model_for() only checked membership, so the batch
    routed all 74 tier titles to flash on the first run, burned the 20/day
    allowance in minutes, and then failed every remaining tier title with a 429.
    A schedule that lives only in comments is documentation, not a schedule.
    """
    out = {}
    if not FLASH_TIER_PATH.exists():
        return out
    for line in FLASH_TIER_PATH.read_text(encoding="utf-8").splitlines():
        head, _, comment = line.partition("#")
        head = head.strip()
        if not head.isdigit():
            continue
        day = re.search(r"day (\d+)", comment)
        out[int(head)] = int(day.group(1)) if day else 1
    return out


def model_for(appid, override=None, force_lite=False, flash_day=None):
    """Which synthesis model this title gets.

    FLASH IS OPT-IN, and that default is the fix for the failure above. flash is
    used only when the caller names the day it is spending (flash_day) AND this
    title is scheduled for exactly that day. Every other path - the catalog
    batch, live generation, a bare CLI run - gets flash-lite, so nothing can
    reach the 20/day model by accident.

    force_lite additionally hard-wires the live path: a user waiting on a cache
    miss must never wait for tomorrow's allowance, and a live request landing on
    a tier title would burn a slot the batch reserved.
    """
    if override:
        return override
    if force_lite or flash_day is None:
        return DEFAULT_MODEL
    return (FLASH_MODEL if flash_tier().get(int(appid)) == int(flash_day)
            else DEFAULT_MODEL)


def _bucket_order(name):
    order = list(COHORT_LABELS)
    return order.index(name) if name in order else len(order)


def build_user_turn(game, pool, cohorts, detected, verdict_word):
    lines = ["Game: %s" % game, ""]
    # The word is stated FIRST and as settled fact. It is computed from the
    # rates below, so the model is being told the conclusion and asked only to
    # write prose that sits under it.
    lines.append("VERDICT (already decided from the cohort rates - write the "
                 "header to suit it, do not argue with it): %s"
                 % verdict_word)
    lines.append("")
    lines.append("COHORTS (rates are context for your wording - never repeat "
                 "them as text):")
    for c in cohorts:
        if c["muted"]:
            lines.append("\n[%s] %s - MUTED: too few surviving reviews. "
                         "No summary, no claims." % (c["bucket"], c["hours_range"]))
            continue
        lines.append("\n[%s] %s - this cohort's reviews run %s%% positive"
                     % (c["bucket"], c["hours_range"], c["pct_positive"]))
        for cl in c["claims"]:
            s = cl["citation_split"]
            lines.append("   %s (%s) %s"
                         % (cl["claim_id"], cl["theme"], cl["claim"]))
            lines.append("        cited reviewers: %d recommend / %d do not"
                         % (s["positive"], s["negative"]))
    if detected:
        lines.append("\nDETECTED PATTERNS - write one sentence for each, "
                     "describing what it is, never why:")
        for f in detected:
            lines.append("   flag_id=%s  %s" % (f["flag_id"], flags_mod.describe(f)))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# enforcement
# --------------------------------------------------------------------------

DIGIT = re.compile(r"\d")

# --------------------------------------------------------------------------
# THE VERDICT WORD IS COMPUTED HERE, NOT CHOSEN BY THE MODEL
#
# It was the last high-stakes output decided by prose instruction, against this
# module's own docstring. Two rewrites of rule 9 proved a sentence cannot hold
# it: the first produced Skip for a title whose post-refund cohorts all sat
# above four in five, and the rewrite that fixed that produced Wait for one
# below three in five with four in five of its claims negatively sourced. Each
# fix installed the opposite bias, because a prompt can only lean.
#
# An earlier attempt (forbidden_verdicts) had the code REJECT clearly-wrong
# words and leave the rest to the model. That is gone: it still let claim
# severity decide inside the permitted band, which is the same bug wearing a
# smaller coat.
POST_REFUND = ("early", "mid", "veteran")

# A cohort's rate must be well measured before it steers a verdict. This is the
# same floor QR-3 already uses for flag evidence, and it is deliberately a POOL
# figure: the survivor-based mute (invariant 12) answers "may we attribute
# claims to this cohort", which is a different question from "is this rate solid
# enough to decide a verdict". Judging admission by one number and the rate by
# another is how a 27-review cohort came to outvote a 560-review one.
MIN_POOL_FOR_MEAN = 30

# Derived from the catalog's own distribution, not chosen for roundness.
# Buy/Wait error bottoms out at 89 (Buy p10 89.2 against Wait p90 93.9 - a real
# overlap, so the boundary is a judgement the data only narrows). Skip/Wait error
# bottoms out at 64, and the populations barely touch there (Skip p90 68.5,
# Wait p10 69.8). Lower thresholds were tested and rejected: at Buy>=75 titles
# like Squad and The Isle took an unqualified Buy on 77-81% negatively-sourced
# evidence, and at Skip<50 no title in the catalog could ever be a Skip.
BUY_AT = 89.0
SKIP_BELOW = 64.0


def post_refund_mean(cohorts):
    """Pool-weighted positive rate across the post-refund cohorts, or None.

    WEIGHTED BY pool_n, because an unweighted mean let a 27-review veteran
    cohort count as much as a 560-review early one - and with the verdict word
    now computed from this number, that thin cohort WAS the verdict.

    Three exclusions, each for its own reason:
      refund_window   - by definition the cohort that bounced; counting it
                        would penalise every title twice for one fact.
      muted           - invariant 12: a cohort we refuse to attribute claims to.
      pool_n < 30     - the rate itself is too noisy to decide anything.

    None means we cannot measure this title, and the caller must not invent a
    verdict for it.
    """
    live = [c for c in cohorts
            if c["bucket"] in POST_REFUND and not c.get("muted")
            and (c.get("pool_n") or 0) >= MIN_POOL_FOR_MEAN]
    total = sum(c["pool_n"] for c in live)
    if not total:
        return None
    return sum(c["pct_positive"] * c["pool_n"] for c in live) / total


def verdict_for_mean(mean):
    """The verdict word, from the cohort data alone. None if unmeasurable.

    Claim content does not appear here and must not: friction a reader should
    know about belongs in not_for_you_if as a clause under a heading that says
    it is a condition (rule 7b), never as a condition that quietly softens the
    word.
    """
    if mean is None:
        return None
    if mean >= BUY_AT:
        return "Buy"
    if mean < SKIP_BELOW:
        return "Skip"
    return "Wait"


def check_response(parsed, cohorts, detected, verdict_word):
    """Return a list of failure strings. Empty means the response is usable.

    verdict_word is COMPUTED and passed in - the model does not return one, so
    there is nothing here to validate it against. What remains is checking that
    the prose the model did write agrees with it.
    """
    failures = []
    by_bucket = {c["bucket"]: c for c in cohorts}
    valid_ids = {cl["claim_id"]: c["bucket"] for c in cohorts for cl in c["claims"]}

    # Completeness first. Without this an empty or wrong-shaped response passes
    # every other gate by containing nothing to object to - which is exactly how
    # a synthesis call answered with extraction-shaped claims and still "passed".
    if not (parsed.get("tagline") or "").strip():
        failures.append("missing_tagline")
    elif len(parsed["tagline"]) > TAGLINE_MAX_CHARS:
        failures.append("tagline_too_long:%d" % len(parsed["tagline"]))
    fit = {}
    for field in ("for_you_if", "not_for_you_if"):
        items = [s for s in (parsed.get(field) or []) if isinstance(s, str)]
        fit[field] = items
        if not FIT_MIN <= len(items) <= FIT_MAX:
            failures.append("%s_out_of_bounds:%d" % (field, len(items)))
        for s in items:
            if not s.strip():
                failures.append("empty_fit_clause:%s" % field)
            elif len(s) > CLAUSE_MAX_CHARS:
                failures.append("fit_clause_too_long:%s:%d" % (field, len(s)))
    # The same clause on both sides is not nuance, it is a contradiction the
    # reader has to resolve themselves.
    both = ({s.strip().lower().rstrip(".") for s in fit["for_you_if"]}
            & {s.strip().lower().rstrip(".") for s in fit["not_for_you_if"]})
    for s in sorted(both):
        failures.append("duplicate_fit_clause:%s" % s[:40])

    answered = {c.get("bucket") for c in (parsed.get("cohorts") or [])}
    for c in cohorts:
        if c["muted"] or not c["claims"]:
            continue
        if c["bucket"] not in answered:
            failures.append("cohort_not_answered:%s" % c["bucket"])
    for f in detected:
        if f["flag_id"] not in {s.get("flag_id")
                                for s in (parsed.get("flag_sentences") or [])}:
            failures.append("flag_not_described:%s" % f["flag_id"])

    # Nothing in the header may argue with the stamp above it.
    #
    # IN CODE, NOT ONLY IN THE PROMPT, for the usual reason: rule 7 said this in
    # words and the model broke it on the very next run, answering Buy with
    # "...but skip it if you are a newcomer". The reader sees the stamp and this
    # block together, so a contradiction reads as a bug in the product rather
    # than as nuance.
    #
    # Narrow-audience carve-outs are still wanted, which is why this matches the
    # DIRECTIVE forms ("should buy", "buy it/this") and not every mention of a
    # word.
    tagline = parsed.get("tagline") or ""
    banned_for = {
        "Buy":  (r"\b(?:should\s+skip|skip\s+(?:it|this)|avoid\s+(?:it|this)|"
                 r"should\s+avoid|steer\s+clear)\b", "skip/avoid language"),
        "Skip": (r"\b(?:should\s+buy|buy\s+(?:it|this|in)|pick\s+(?:it|this)\s+up|"
                 r"worth\s+buying)\b", "buy language"),
    }
    if verdict_word in banned_for:
        pattern, what = banned_for[verdict_word]
        if re.search(pattern, tagline, re.I):
            failures.append("tagline_contradicts_verdict:%s:%s"
                            % (verdict_word, what))

    # The lists get the OPPOSITE side's pattern, and only that side.
    #
    # This is the whole reason the split works. Under a Skip, for_you_if exists
    # to say who the game would still suit - a clause is fine, "you should buy
    # it anyway" is the model overturning a computed verdict inside a bullet.
    # Under a Buy the mirror holds for not_for_you_if. Applying both patterns to
    # both lists would ban the sections' own purpose.
    for field, word in (("for_you_if", "Skip"), ("not_for_you_if", "Buy")):
        if verdict_word != word:
            continue
        pattern, what = banned_for[word]
        for s in fit[field]:
            if re.search(pattern, s, re.I):
                failures.append("fit_list_contradicts_verdict:%s:%s:%s"
                                % (field, word, what))

    # Friction stated as a test the reader must pass (rule 7b), IN CODE because
    # the prompt version of this rule half-held: the directive form ("buy only
    # if...") disappeared, and the same condition reappeared inside the audience
    # description instead - "suits players willing to tolerate the launcher".
    #
    # TAGLINE ONLY, and that is the point of this design. A condition in
    # not_for_you_if is honest, because the heading above it says it is a
    # condition; the same words in the tagline are a test smuggled in beside the
    # verdict word. Same sentence, different contract with the reader.
    FRICTION_VERBS = (r"tolerate|overlook|navigate|manage|troubleshoot|weather|"
                      r"endure|put\s+up\s+with")
    if re.search(r"\b(?:(?:willing|prepared|happy)\s+to\s+(?:%s)|"
                 # the obligation form is the same condition in the imperative:
                 # "though you must tolerate the launcher" asks exactly what
                 # "willing to tolerate the launcher" asks.
                 r"(?:must|have\s+to|need\s+to)\s+(?:%s|accept)|"
                 r"can\s+tolerate|if\s+you\s+can\s+overlook|"
                 r"provided\s+you\s+(?:accept|can))\b"
                 % (FRICTION_VERBS, FRICTION_VERBS), tagline, re.I):
        failures.append("tagline_frames_friction_as_a_condition")

    # The prose sweep below is invariant 11 and 13's only coverage, so EVERY
    # field the model writes has to be in it. Splitting one for-whom line into
    # three fields is exactly how a surface loses its guard silently: the checks
    # keep passing, on prose nobody sends them any more.
    prose = [("tagline", tagline)]
    for field in ("for_you_if", "not_for_you_if"):
        for i, s in enumerate(fit[field]):
            prose.append(("%s[%d]" % (field, i), s))
    for c in parsed.get("cohorts") or []:
        prose.append(("summary[%s]" % c.get("bucket"), c.get("summary") or ""))
    for f in parsed.get("flag_sentences") or []:
        prose.append(("flag[%s]" % f.get("flag_id"), f.get("sentence") or ""))

    for label, text in prose:
        if DIGIT.search(text):
            failures.append("digit_in_prose:%s" % label)          # invariant 13
        hits = prevalence_guard.check_claim(text)
        if hits:
            failures.append("prevalence:%s:%s"
                            % (label, ",".join(sorted({h[0] for h in hits}))))

    seen = set()
    for c in parsed.get("cohorts") or []:
        bucket = c.get("bucket")
        target = by_bucket.get(bucket)
        if target is None:
            failures.append("unknown_bucket:%s" % bucket)
            continue
        if target["muted"]:                                        # invariant 12
            if (c.get("claim_ids") or []) or (c.get("summary") or "").strip():
                failures.append("muted_cohort_has_content:%s" % bucket)
            continue
        for cid in c.get("claim_ids") or []:
            if cid not in valid_ids:                               # invariant 4
                failures.append("unknown_claim_id:%s" % cid)
            elif valid_ids[cid] != bucket:
                failures.append("claim_moved_cohort:%s(from %s to %s)"
                                % (cid, valid_ids[cid], bucket))
            elif cid in seen:
                failures.append("claim_reused:%s" % cid)
            seen.add(cid)

    known_flags = {f["flag_id"] for f in detected}
    for f in parsed.get("flag_sentences") or []:
        if f.get("flag_id") not in known_flags:
            failures.append("unknown_flag_id:%s" % f.get("flag_id"))

    return failures


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def load_inputs(appid, claims_dir, filtered_dir):
    claims_blob = json.loads((Path(claims_dir) / ("%s.json" % appid))
                             .read_text(encoding="utf-8"))
    filtered = json.loads((Path(filtered_dir) / ("%s.json" % appid))
                          .read_text(encoding="utf-8"))
    corpus = {str(r["recommendationid"]): r for r in filtered.get("reviews", [])}
    report = (filtered.get("filter_report") or {}).get("by_bucket") or {}

    # Read the pool from data/raw, which owns it. filtered/ and claims/ carry
    # copies made when they ran, and a copy made before the temporal block
    # existed silently cost Cyberpunk and Death Stranding their recency flags.
    pool = claims_blob.get("pool") or {}
    raw_path = Path("data/raw") / ("%s.json" % appid)
    if raw_path.exists():
        raw_pool = json.loads(raw_path.read_text(encoding="utf-8")).get("pool")
        if raw_pool:
            pool = raw_pool

    cohorts = []
    for name, _, _ in BUCKETS:
        st = report.get(name) or {}
        pool_st = (pool.get("buckets") or {}).get(name) or {}
        cohorts.append({
            "bucket": name,
            "label": COHORT_LABELS.get(name, name),
            "hours_range": HOURS_RANGE.get(name, name),
            "pool_n": pool_st.get("pool_n"),
            "pct_positive": pool_st.get("pct_positive"),
            "muted": bool(st.get("muted")),
            "surviving_reviews": st.get("kept"),
            "claims": claims_blob.get("claims_by_bucket", {}).get(name, []),
        })
    return claims_blob, corpus, pool, cohorts


def build_citation(rid, corpus):
    r = corpus.get(rid) or {}
    text = r.get("review_text") or ""
    truncated = len(text) > MAX_CITATION_CHARS
    created = r.get("created_ts")
    return {
        "recommendationid": rid,
        "hours_at_review": r.get("hours_at_review"),
        "voted_up": r.get("voted_up"),
        "date": (datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
                 if created else None),
        "review_text": (text[:MAX_CITATION_CHARS] + "…") if truncated else text,
        "truncated": truncated,
    }


def assemble(appid, claims_blob, corpus, pool, cohorts, detected, parsed,
             model, verdict_word):
    by_bucket = {c.get("bucket"): c for c in (parsed.get("cohorts") or [])}
    sentences = {f.get("flag_id"): f.get("sentence")
                 for f in (parsed.get("flag_sentences") or [])}

    split_bar, out_cohorts = [], []
    for c in sorted(cohorts, key=lambda x: _bucket_order(x["bucket"])):
        split_bar.append({
            "bucket": c["bucket"], "label": c["label"],
            "pool_n": c["pool_n"], "pct_positive": c["pct_positive"],
            "muted": c["muted"],
        })
        model_c = by_bucket.get(c["bucket"]) or {}
        section = {
            "bucket": c["bucket"], "label": c["label"],
            "hours_range": c["hours_range"],
            "pool_n": c["pool_n"], "pct_positive": c["pct_positive"],
            "muted": c["muted"],
            # invariant 12: the muted section renders with an explicit n= label
            "n_note": ("n=%s - too few reviews to call"
                       % c["surviving_reviews"]) if c["muted"] else None,
            "summary": None if c["muted"] else (model_c.get("summary") or None),
            "themes": [],
        }
        if not c["muted"]:
            order = {cid: i for i, cid in enumerate(model_c.get("claim_ids") or [])}
            by_id = {cl["claim_id"]: cl for cl in c["claims"]}
            chosen = [by_id[cid] for cid in (model_c.get("claim_ids") or [])
                      if cid in by_id]
            # any claim the model left out still ships - it was grounded
            chosen += [cl for cl in c["claims"] if cl["claim_id"] not in order]
            themed = OrderedDict()
            for cl in chosen:
                themed.setdefault(cl["theme"], []).append({
                    "claim_id": cl["claim_id"],
                    "claim": cl["claim"],
                    "citation_verdict": cl["citation_verdict"],
                    "citation_split": cl["citation_split"],
                    "citations": [build_citation(rid, corpus)
                                  for rid in cl["supporting_ids"]],
                })
            section["themes"] = [{"theme": t, "claims": cs}
                                 for t, cs in themed.items()]
        out_cohorts.append(section)

    out_flags = []
    for f in detected:
        out_flags.append({
            "flag_id": f["flag_id"], "type": f["type"],
            # recency carries a direction (improved/declined); segmentation
            # carries a shape across the whole cohort sequence. Exactly one is
            # set, and the UI should read the one that is present.
            "direction": f.get("direction"),
            "shape": f.get("shape"),
            "sentence": sentences.get(f["flag_id"]),
            "evidence": f["evidence"],
        })

    # Second lock on the null-name bug (the first is in fetch_reviews). A
    # verdict with no game name is unpublishable by definition: it renders an
    # empty heading and unfurls as "null: Skip". Refusing here means a raw file
    # that predates that guard cannot quietly reach the site either.
    if not claims_blob.get("game_name"):
        raise SystemExit(
            "\nREFUSED: appid %s has no game_name.\n"
            "  Re-run ingestion for it - the store lookup failed and the name\n"
            "  never made it into data/raw. Nothing was written." % appid)

    # Cover art, resolved once at generation time (pipeline/art.py). Tier 1 is
    # free - it reads the appdetails response ingestion already cached. Tier 2
    # is one SteamGridDB lookup, cached forever, and is TILES ONLY: `grid` must
    # never reach an OG image. Absent keys mean the site falls back to the
    # legacy pattern, which is still correct for ~97% of titles.
    art = art_mod.art_block(appid)

    # WHAT THIS GENERATION COST, written by the last stage that spends a call.
    #
    # It exists so the live path can give budget back. /api/generate reserves
    # EST_COST=13 up front, because the check and the spend cannot be atomic
    # across a repository_dispatch boundary and a burst must not oversubscribe
    # the reserve. The true median is 9 (measured over 295 published titles in
    # data/batch_state.json: p25 7, median 9, p90 12, max 14), so ~34% of every
    # reservation is budget nobody spent. The runner cannot hand the real figure
    # back - its GITHUB_TOKEN cannot write repository variables - so the figure
    # travels in the one artifact the runner DOES commit: this file.
    #
    # READ THE BASIS STRING BEFORE USING THIS NUMBER. It is calls_for(appid),
    # which the pacer keys per appid PER QUOTA DAY PER MACHINE, not per run.
    # On a CI runner those coincide exactly - data/model_pacer.json is
    # gitignored, so the runner starts empty, generates one title, and exits -
    # which is why the live reconciler may trust it. On a dev machine a title
    # regenerated the same day accumulates across both attempts. Anything that
    # starts treating this as a clean per-run cost on the batch path is wrong,
    # and the basis string is here so that cannot happen by accident.
    #
    # It is a PIPELINE DIAGNOSTIC and never renders (invariant 13). Pinned by
    # site/lib/__tests__/cost-never-renders.contract.test.tsx.
    cost = {
        "model_calls": model_pacer.calls_for(appid),
        "basis": ("gemini requests charged to this appid on this quota day, on "
                  "the machine that generated it. equals this run's cost on a "
                  "fresh CI runner; a same-day regeneration on a dev machine "
                  "accumulates. pipeline diagnostic - never rendered."),
    }

    return {
        "appid": appid,
        "game_name": claims_blob.get("game_name"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "art": art,
        "model": {"extraction": claims_blob.get("model"), "synthesis": model},
        "cost": cost,
        # word: computed, never model-chosen - see verdict_for_mean()
        # tagline/lists: the model's three-part header, bounded by rule 7
        "verdict": {"word": verdict_word,
                    "tagline": parsed.get("tagline"),
                    "for_you_if": list(parsed.get("for_you_if") or []),
                    "not_for_you_if": list(parsed.get("not_for_you_if") or [])},
        "split_bar": split_bar,
        "distortion_flags": out_flags,
        "cohorts": out_cohorts,
        "footer": {
            "pool_n": pool.get("pool_n"),
            "steam_total_reviews": pool.get("steam_total_reviews"),
            "cohort_count": sum(1 for c in out_cohorts if not c["muted"]),
            "basis": pool.get("basis"),
        },
    }


# --------------------------------------------------------------------------

def synthesize_one(client, args, appid):
    # the flash tier is per TITLE, not per run: one batch mixes both models
    args.model = model_for(appid, args.model_override, args.force_lite,
                           args.flash_day)

    # THE FLASH CAP, ENFORCED. model_for() decides which model this title should
    # get; the ledger decides whether that is still affordable. Both are needed:
    # the schedule was already correct when the routing bug spent the allowance,
    # because nothing checked the remaining balance before spending it.
    if args.model == FLASH_MODEL:
        allowed, reason, detail = live_quota.can_flash(live_quota.load())
        if not allowed:
            if args.flash_fallback:
                print("  flash cap reached (%s) - falling back to %s"
                      % (json.dumps(detail), DEFAULT_MODEL))
                args.model = DEFAULT_MODEL
            else:
                raise SystemExit(
                    "\nREFUSED: %s wanted gemini-3.5-flash, but the daily cap "
                    "is spent.\n  %s\n  Nothing was sent. Re-run after the "
                    "reset, or pass --flash-fallback to synthesize this title "
                    "on flash-lite instead."
                    % (appid, json.dumps(detail)))
    claims_blob, corpus, pool, cohorts = load_inputs(appid, args.claims, args.filtered)
    game = claims_blob.get("game_name") or appid
    detected = flags_mod.detect(pool)

    print("\n=== %s (%s) ===" % (game, appid))
    for f in detected:
        print("  flag: %s" % flags_mod.describe(f))
    for c in cohorts:
        print("  %-14s pool_n=%-5s %5s%% positive  claims=%-3d%s"
              % (c["bucket"], c["pool_n"], c["pct_positive"], len(c["claims"]),
                 "  MUTED" if c["muted"] else ""))

    system = SYSTEM_INSTRUCTION
    mean = post_refund_mean(cohorts)
    verdict_word = verdict_for_mean(mean)
    if verdict_word is None:
        print("  REFUSED: no post-refund cohort clears the evidence floor "
              "(pool_n >= %d), so there is no measurable sentiment to compute a "
              "verdict from. Nothing written for %s." % (MIN_POOL_FOR_MEAN, appid))
        return None
    print("  verdict computed from cohort data: %s (post-refund mean %.1f%%)"
          % (verdict_word, mean))
    user = build_user_turn(game, pool, cohorts, detected, verdict_word)
    if args.show_prompt or args.dry_run:
        print("\n--- user turn ---\n%s" % user)
    if args.dry_run:
        return None

    parsed, failures = None, ["not attempted"]
    for attempt in range(args.retries + 1):
        prompt = user if attempt == 0 else (
            user + "\n\nYour previous answer was rejected for these reasons:\n"
            + "\n".join("  - %s" % f for f in failures)
            + "\nProduce a corrected answer obeying every rule.")
        # The attempt number is part of the cache key, and it has to be.
        # The retry prompt embeds the failure list, so when a retry fails the
        # SAME WAY the next prompt is byte-identical to the last one - identical
        # key, and the cache replays the very answer that was just rejected.
        # Stardew Valley burned all three attempts that way: attempt 2 was
        # served from cache and "failed" without a request ever being sent.
        cpath = cache_path(appid, "synthesis", args.model, system, prompt,
                           tag="verdict-v1-attempt%d" % attempt)
        if cpath.exists() and not args.force:
            text = json.loads(cpath.read_text(encoding="utf-8"))["text"]
            print("  [cached] attempt %d" % attempt)
        else:
            # Per CALL, not per title: a retry is another flash request, and a
            # title with two retries could otherwise cross the cap mid-title.
            # Check then charge, so the 21st call is refused before it is sent
            # rather than discovered afterwards in a 429.
            if args.model == FLASH_MODEL:
                ok_flash, why, detail = live_quota.can_flash(live_quota.load())
                if not ok_flash:
                    if args.flash_fallback:
                        print("  flash cap reached mid-title - remaining "
                              "attempts use %s" % DEFAULT_MODEL)
                        args.model = DEFAULT_MODEL
                    else:
                        raise SystemExit(
                            "\nREFUSED mid-title: the daily gemini-3.5-flash "
                            "cap is spent.\n  %s\n  Nothing was sent."
                            % json.dumps(detail))
                else:
                    live_quota.charge(1, ledger="flash")
            resp = call_model(client, args.model, system, prompt,
                              schema=VERDICT_SCHEMA, thinking_level="medium")
            text, _ = response_text(resp)
            usage = getattr(resp, "usage_metadata", None)
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(
                {"model": args.model, "text": text,
                 "usage": {"total": getattr(usage, "total_token_count", None)}},
                ensure_ascii=False, indent=2), encoding="utf-8")
            import time
            time.sleep(PACE_SECONDS)

        try:
            candidate = json.loads(text)
        except ValueError as exc:
            failures = ["invalid_json:%s" % exc]
            print("  attempt %d rejected: %s" % (attempt, failures[0]))
            continue

        failures = check_response(candidate, cohorts, detected, verdict_word)
        if not failures:
            parsed = candidate
            break
        print("  attempt %d rejected:" % attempt)
        for f in failures:
            print("     ! %s" % f)

    if parsed is None:
        print("  FAILED after %d attempts - no verdict written for %s"
              % (args.retries + 1, appid))
        return None

    verdict = assemble(appid, claims_blob, corpus, pool, cohorts, detected,
                       parsed, args.model, verdict_word)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s.json" % appid)
    path.write_text(json.dumps(verdict, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print("  -> %s  [%s] %s" % (path, verdict["verdict"]["word"],
                                verdict["verdict"]["tagline"]))
    for field, glyph in (("for_you_if", "+"), ("not_for_you_if", "-")):
        for s in verdict["verdict"][field]:
            print("       %s %s" % (glyph, s))
    return verdict


def main():
    ap = argparse.ArgumentParser(description="WorthIt.gg synthesis pass (1.5)")
    ap.add_argument("appids", nargs="*")
    ap.add_argument("--seeds", action="store_true")
    ap.add_argument("--model", default=None,
                    help="override; default resolves via flash_tier.txt")
    ap.add_argument("--force-lite", action="store_true",
                    help="live-generation path: always flash-lite")
    ap.add_argument("--flash-day", type=int, default=None,
                    help="spend flash on titles scheduled for this tier day")
    ap.add_argument("--flash-fallback", action="store_true",
                    help="if the flash cap is spent, use flash-lite instead of "
                         "refusing")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--claims", default=str(CLAIMS_DIR))
    ap.add_argument("--filtered", default=str(FILTERED_DIR))
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    args.model_override = args.model
    os.environ.setdefault("WORTHIT_APPID", str(args.appids[0]) if getattr(args, "appids", None) else "-")

    appids = list(args.appids)
    if args.seeds:
        appids = SEED_GAMES + [a for a in appids if a not in SEED_GAMES]
    if not appids:
        ap.error("give at least one appid, or --seeds")

    client = None
    if not args.dry_run:
        load_env()
        from google import genai
        client = genai.Client(api_key=__import__("os").environ["GEMINI_API_KEY"])

    print("synthesis model resolves per title via flash_tier.txt%s"
          % (" (overridden: %s)" % args.model if args.model else
             " (forced flash-lite)" if args.force_lite else ""))
    failed = [a for a in appids if synthesize_one(client, args, a) is None
              and not args.dry_run]
    if failed:
        print("\nFAILED: %s" % ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
