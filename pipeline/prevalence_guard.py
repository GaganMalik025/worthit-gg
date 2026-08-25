"""
WorthIt.gg - prevalence-language guard (wired into the 1.4 grounding check)

Invariant 11 says prevalence may only come from the pool block. A countless
output schema stops the model returning "count: 47", but it cannot stop prose:
"most players bounce off the tutorial" is a prevalence claim with no number in
it, and the sample it was drawn from is deliberately non-representative.

This is a deterministic lexical check - no LLM, runs on every generation.

Two hazards it deliberately does NOT flag:
  superlatives   "the most polished mech shooter"   - not a proportion
  durations      "a few hours in", "half an hour"   - not a proportion

Usage:
    from prevalence_guard import check_claim
    hits = check_claim("Most players refund inside two hours")
    # -> [('most', 'quantifier over people')]
"""

import re
import sys

# Nouns that turn a quantifier into a claim about how many *people*.
CROWD = r"(?:players?|people|reviewers?|users?|buyers?|gamers?|everyone|" \
        r"the community|folks|fans?)"

PATTERNS = [
    # bare percentages and ratios - a claim should never carry either
    (r"\d+\s?%", "percentage"),
    (r"\b\d+\s+(?:out\s+of|in)\s+\d+\b", "ratio"),
    (r"\b(?:one|two|three|four|nine)[- ](?:in|out\s+of)[- ]\w+\b", "ratio in words"),

    # quantifiers over people. "most" only when it is not a superlative:
    # "the most polished" is fine, "most players" is not.
    (r"(?<!the )\bmost\b(?!\s+(?:polished|fun|important|common\s+complaint))", "quantifier over people"),
    (r"\bmajority\b", "quantifier over people"),
    (r"\bminority\b", "quantifier over people"),
    (r"\bmany\s+" + CROWD, "quantifier over people"),
    (r"\bfew\s+" + CROWD, "quantifier over people"),
    (r"\bvery\s+few\b", "quantifier over people"),
    (r"\bsome\s+" + CROWD, "quantifier over people"),
    (r"\bseveral\s+" + CROWD, "quantifier over people"),
    (r"\bnumerous\b|\bcountless\b|\bplenty\s+of\s+" + CROWD, "quantifier over people"),
    (r"\bhalf\s+(?:of\s+)?(?:the\s+)?" + CROWD, "proportion"),
    (r"\b(?:a\s+)?(?:third|quarter|fifth)\s+of\b", "proportion"),
    # Absolute quantifiers, split 2026-08-25 on content-vs-population. The old
    # single rule made CROWD optional, so "all" fired with no crowd noun at all
    # and rejected "you expect free access to all content" - the game's content,
    # not a share of players. Same shape as the 2026-08-21 frequency split: the
    # word is not the violation, the referent is.
    #
    # The rule it replaced also carried a (?!\s+(?:mission|level|run)) carve-out
    # that NEVER FIRED - \s* backtracks over the space and the lookahead is
    # evaluated past it, so "every mission" matched anyway. Requiring CROWD
    # covers those properly instead of by denylist, so it is not reinstated.
    (r"\ball\s+" + CROWD, "absolute quantifier"),
    (r"\bevery\s+" + CROWD, "absolute quantifier"),
    (r"\bnone\s+of\s+(?:the\s+)?" + CROWD, "absolute quantifier"),
    # Bare "none" names no referent, and the elided one in this register is
    # people: "none recommend the sequel". "none of X" states its referent and
    # is judged by X, above. Without this the split would have NARROWED the
    # guard - bare population claims would pass unflagged.
    (r"\bnone\b(?!\s+of\b)", "absolute quantifier"),
    # These are about people whatever follows them, so they need no crowd noun.
    # SPLIT 2026-08-26, for the extractor rather than for the rule. As one
    # group, `no\s+one`'s backslash falls outside banned_words()' [a-z|\s]
    # class, which fails the WHOLE group - so `everyone` and `nobody` were
    # rejected in code and never named in the prompt either (BACKLOG
    # 2026-08-25, defect 2). Same alternatives, same \b anchors, same matches.
    (r"\b(?:everyone|nobody)\b", "absolute quantifier"),
    # "no one" stays rejected and stays UNNAMEABLE, and that is a property of
    # the extractor, not of this line: A discards any alternative containing a
    # space by design, B cannot read across \s+. No way of writing this pattern
    # makes it quotable, so nothing here tries. It is the same limit that keeps
    # "many players" and "few players" out of the prompt - a phrase mechanism
    # invented for this one case would be a second convention, not a fix.
    (r"\bno\s+one\b", "absolute quantifier"),

    # Consensus language: a claim that everyone agrees IS a claim about how many
    # people. Kept banned, and deliberately NOT part of the 2026-08-21 frequency
    # split below - see the KNOWN SEAM note there.
    (r"\bconsensus\b|\bunanimous\b", "consensus language"),

    # explicit comparisons of group size
    (r"\bmore\s+" + CROWD + r"\s+(?:than|report|say|complain)", "group comparison"),
    (r"\b(?:vast|large|small)\s+(?:number|proportion|share|chunk)\b", "proportion"),
]

# ---------------------------------------------------------------------------
# FREED 2026-08-21 - event frequency is not prevalence (owner decision)
# ---------------------------------------------------------------------------
# These patterns are DELIBERATELY NOT CHECKED. They are kept here, uncompiled,
# so the history is readable and a reversal is one line.
#
# Why they were freed. Invariant 11 exists to stop a non-representative sample
# being read as HOW MANY PLAYERS. These words say how often an EVENT happens -
# "occasional crashes" is a property of the bug, not a proportion of people -
# and enforcing them cost real output:
#
#   RuneScape (1343400), 2026-08-21: three synthesis attempts, 9 calls, nothing
#   published. Rejected on "occasional crashes" twice, then, having dropped the
#   adjective, on "free access to all content".
#   Insurgency (222880), 2026-08-18: three attempts deadlocked on "persistent",
#   describing a startup crash that genuinely persists.
#
# The argument this replaces is the one the deleted comment made: that how often
# a bug fires is as unknowable from a quota sample as how many players hit it.
# That is true of a RATE ("crashes 40% of the time") and the structural patterns
# above still reject rates. It is not true of an unquantified adjective, and
# treating the two the same rejected claims no reader would call prevalence.
#
# SCOPE, recorded because it is wider than the examples. Both categories are
# freed IN FULL, including the extent words - commonly, widespread, prevalent,
# commonplace, widely, universally, unanimously, overwhelmingly. That reverses
# the "commonly" example in the instruction that requested this split, on an
# explicit later decision. "widely praised" does lean on how many people, so
# this is the loosest reading of the split rather than the tightest.
#
# KNOWN SEAM, not resolved here: "unanimously" is freed below while "unanimous"
# and "consensus" stay banned above under `consensus language`, a category that
# was not part of this decision. See BACKLOG 2026-08-21.
FREED_FREQUENCY_PATTERNS = [
    (r"\b(?:commonly|frequently|typically|generally|usually|often|rarely|seldom)\b",
     "frequency adverb"),
    (r"\b(?:frequent|infrequent|occasional|widespread|prevalent|commonplace)\b",
     "frequency adjective"),
    (r"\b(?:constant|constantly|repeated|repeatedly|persistent|persistently|"
     r"continual|continually|regularly|routinely|ongoing)\b",
     "frequency adjective"),
    (r"\b(?:widely|universally|unanimously|overwhelmingly)\b", "frequency adverb"),
]

COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in PATTERNS]


def banned_words():
    """Every literal word the patterns above reject, for the prompt to quote.

    The synthesis prompt used to carry its own hand-written banned list, and it
    drifted: the guard rejected the frequency ADJECTIVES (frequent, occasional,
    widespread...) while the prompt only ever named the adverbs. Synthesis then
    failed on "occasional technical crashes" - a word the model was never told
    to avoid.

    Deriving the list from PATTERNS means the prompt cannot fall behind the rule
    it is meant to explain. test_batch_guards asserts the two stay in step.

    That derivation is what makes the 2026-08-21 split safe in BOTH directions.
    Reading FREED_FREQUENCY_PATTERNS here would tell the model to avoid words the
    guard no longer rejects, and a model told to avoid "Windows 11" spells it
    "Windows eleven" rather than dropping the fact - the exact defect shipped on
    222880. A word is either rejected and named in the prompt, or neither.
    """
    words = set()
    for pattern, _ in PATTERNS:
        # literal alternations only - the structural patterns (percentages,
        # ratios, "X of the Y") are explained in prose in the prompt instead
        for group in re.findall(r"\(\?:([a-z|\s]+)\)", pattern):
            for word in group.split("|"):
                word = word.strip()
                if word and " " not in word:
                    words.add(word)
        for bare in re.findall(r"\\b([a-z]+)\\b", pattern):
            words.add(bare)
    # Keep only words this module actually rejects on their own. The regexes
    # also contain fragments of multi-word rules ("a third of", "vast number"),
    # and listing "third" as a banned word would be false - the prompt explains
    # those structurally instead. Verifying against check_claim rather than
    # curating a second list is what keeps this honest.
    standalone = []
    for word in sorted(words):
        if check_claim("the game has %s problems" % word) or \
           check_claim("%s players report problems" % word):
            standalone.append(word)
    return standalone


def check_claim(text):
    """Return [(matched_text, reason)] - empty means the claim is clean."""
    hits = []
    for rx, label in COMPILED:
        for m in rx.finditer(text or ""):
            hits.append((m.group(0).strip(), label))
    return hits


def check_claims(claims, text_key="claim"):
    """Screen a list of claim dicts. Returns [(index, claim_text, hits)]."""
    flagged = []
    for i, c in enumerate(claims):
        text = c.get(text_key) if isinstance(c, dict) else str(c)
        hits = check_claim(text)
        if hits:
            flagged.append((i, text, hits))
    return flagged


def report(flagged, total, hard_fail=False):
    """Print findings. 1.3 warns; 1.4 turns this into a rejection."""
    if not flagged:
        print("  prevalence guard: clean (%d claims)" % total)
        return True
    print("  prevalence guard: %d of %d claims carry prevalence language"
          % (len(flagged), total))
    for i, text, hits in flagged:
        terms = ", ".join("%s (%s)" % (t, why) for t, why in hits)
        print("    [%d] %s" % (i, text))
        print("         ^ %s" % terms)
    if hard_fail:
        print("  REJECTED - claims must not state how common anything is "
              "(invariant 11); prevalence comes from the pool block.")
    return False


if __name__ == "__main__":
    for line in (sys.argv[1:] or [l.rstrip("\n") for l in sys.stdin]):
        hits = check_claim(line)
        print("%-6s %s%s" % ("FLAG" if hits else "ok", line,
                             ("   <- " + ", ".join(h[0] for h in hits)) if hits else ""))
