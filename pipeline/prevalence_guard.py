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
    (r"\b(?:all|every|everyone|nobody|no\s+one|none)\s*" + CROWD + r"?\b(?!\s+(?:mission|level|run))",
     "absolute quantifier"),

    # Frequency words that stand in for a rate. Unconditional by design: how
    # often a bug fires is as unknowable from a quota sample as how many players
    # hit it, so "frequently fail" is treated exactly like "frequently attacked".
    # The rephrase is always available - "reviewers report pathfinding failures"
    # keeps the whole claim and cites the same reviews.
    (r"\b(?:commonly|frequently|typically|generally|usually|often|rarely|seldom)\b",
     "frequency adverb"),
    # ...and the adjective/noun forms of the same idea, which the adverb-only
    # list used to wave through ("frequent crashes" passed while "frequently
    # fail" was caught).
    (r"\b(?:frequent|infrequent|occasional|widespread|prevalent|commonplace)\b",
     "frequency adjective"),
    # NOT included: bare "common" and "rare". In game reviews those are usually
    # loot-rarity tiers ("rare materials are hard to farm"), not frequency
    # claims. "commonly" stays banned above.
    (r"\b(?:widely|universally|unanimously|overwhelmingly)\b", "frequency adverb"),
    (r"\bconsensus\b|\bunanimous\b", "consensus language"),

    # explicit comparisons of group size
    (r"\bmore\s+" + CROWD + r"\s+(?:than|report|say|complain)", "group comparison"),
    (r"\b(?:vast|large|small)\s+(?:number|proportion|share|chunk)\b", "proportion"),
]

COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in PATTERNS]


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
