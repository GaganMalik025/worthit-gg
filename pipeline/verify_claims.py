"""
WorthIt.gg - meaning check on extracted claims, one call per cohort (owner, 2026-11-16).

The lexical grounding check (ground_check.py) matches words, so a second review that
shares a word with a claim passes it. A catalog sample found 72 of 300 published claims
with only one citation really supporting them (RESULTS 2026-11-06), and Civilization
VII's offline claim was carried by the word "state", taken from the claim's own
"Reviewers state that". This reads meaning instead.

For each claim it asks which cited reviews actually convey it, then code decides:

    2 or more  -> a claim (invariant 3), keeping only the reviews that convey it
    exactly 1  -> a ONE-REVIEWER POINT, rewritten in the singular, shown in its own
                  section and never fed to synthesis, the fit lists or the verdict
    0          -> dropped

Code, not the model, enforces each of those. The model's ids are intersected with the
claim's own citations, the rewrite must start "One reviewer" and pass the prevalence
guard, and a response that does not cover every claim fails the cohort: unverified
claims are never published as verified.

One call per cohort rather than per claim (owner, 2026-11-16): about 4 calls a title
instead of about 17. Judged against the per-claim judge on the pilot before it is
trusted catalog-wide.
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prevalence_guard  # noqa: E402

MAX_REVIEW_CHARS = 1500
TAG = "verify-v1"

SYSTEM = """\
You check claims extracted from Steam reviews of one game, against the reviews each \
claim cites. A reader must be able to trust that every review shown under a claim says \
what the claim says.

For EACH claim, list in supported_by the ids of the reviews, from that claim's own \
citations only, that state or clearly convey what the claim asserts. Judge meaning, not \
shared words: reviewers paraphrase. A review that only mentions the subject without \
saying what the claim says about it does not count. A review that conveys only part of \
a claim that joins several points does not count. Ignore tone and ignore whether the \
reviewer liked the game.

If exactly one review supports a claim, also write one_reviewer_text: the same point as \
that one reviewer made it, starting with "One reviewer", for example "One reviewer says \
the normal jump feels too short early in the game." Say only what that review says. \
Never state how many or what share of players hold a view. Otherwise leave \
one_reviewer_text empty.

Return every claim id you were given, exactly once.
"""

SCHEMA = {"type": "object", "required": ["claims"], "properties": {
    "claims": {"type": "array", "items": {
        "type": "object", "required": ["claim_id", "supported_by"],
        "properties": {"claim_id": {"type": "string"},
                       "supported_by": {"type": "array", "items": {"type": "string"}},
                       "one_reviewer_text": {"type": "string"}}}}}}


class VerifyError(RuntimeError):
    """The cohort could not be verified. Its claims must not publish as verified."""


def build_prompt(game, bucket, claims, corpus):
    cited = []
    for c in claims:
        for rid in c["supporting_ids"]:
            if rid not in cited:
                cited.append(rid)
    reviews = []
    for rid in cited:
        text = " ".join((corpus[rid].get("review_text") or "").split())
        if len(text) > MAX_REVIEW_CHARS:
            text = text[:MAX_REVIEW_CHARS] + " ...[truncated]"
        reviews.append("[%s] %s" % (rid, text))
    lines = ["Game: %s" % game, "Cohort: %s" % bucket, "", "REVIEWS", ""] + reviews
    lines += ["", "CLAIMS", ""]
    for c in claims:
        lines.append("[%s] %s  (cites: %s)"
                     % (c["claim_id"], c["claim"], ", ".join(c["supporting_ids"])))
    return "\n".join(lines)


def point_id(text):
    return "one-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def decide(claims, parsed):
    """Code's half: (main claims, one-reviewer points, report). Raises VerifyError."""
    rows = {}
    for row in (parsed or {}).get("claims") or []:
        cid = str(row.get("claim_id"))
        if cid in rows:
            raise VerifyError("claim %s answered twice" % cid)
        rows[cid] = row
    missing = [c["claim_id"] for c in claims if c["claim_id"] not in rows]
    if missing:
        raise VerifyError("no answer for %s" % ", ".join(missing))

    main, singles, report = [], [], {"kept": 0, "one_reviewer": 0, "dropped": 0,
                                     "rewrite_rejected": 0, "citations_removed": 0,
                                     "decisions": []}
    for c in claims:
        row = rows[c["claim_id"]]
        cited = c["supporting_ids"]
        backed = [rid for rid in cited if rid in {str(x) for x in row.get("supported_by") or []}]
        if len(backed) >= 2:
            report["citations_removed"] += len(cited) - len(backed)
            main.append({**c, "supporting_ids": backed, "verified": True})
            outcome = "kept"
        elif len(backed) == 1:
            text = " ".join((row.get("one_reviewer_text") or "").split())
            if not text.startswith("One reviewer") or prevalence_guard.check_claim(text):
                outcome = "rewrite_rejected"
            else:
                singles.append({"point_id": point_id(text), "text": text,
                                "theme": c.get("theme"), "supporting_id": backed[0],
                                "from_claim": c["claim"]})
                outcome = "one_reviewer"
        else:
            outcome = "dropped"
        report[outcome] += 1
        # diagnostics for the pilot comparison; never rendered
        report["decisions"].append({"claim_id": c["claim_id"], "cited": list(cited),
                                    "backed": backed, "outcome": outcome})
    return main, singles, report


def verify_cohort(call, cache_path, game, appid, bucket, claims, corpus, attempts=2):
    """Verify one cohort's claims. `call(system, user, schema) -> text`.

    `cache_path(system, user, tag) -> Path`. Only attempt 0 reads the cache, so a retry
    always sends a fresh request (the synthesis lesson, BACKLOG 2026-08-18).
    """
    if not claims:
        return [], [], {"kept": 0, "one_reviewer": 0, "dropped": 0,
                        "rewrite_rejected": 0, "citations_removed": 0, "calls": 0}
    user = build_prompt(game, bucket, claims, corpus)
    last = None
    for attempt in range(attempts):
        path = cache_path(SYSTEM, user, "%s-attempt%d" % (TAG, attempt))
        if attempt == 0 and path.exists():
            text = json.loads(path.read_text("utf-8"))["text"]
        else:
            text = call(SYSTEM, user, SCHEMA)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": text}, ensure_ascii=False), "utf-8")
        try:
            main, singles, report = decide(claims, json.loads(text))
            report["attempts"] = attempt + 1
            return main, singles, report
        except (ValueError, VerifyError) as exc:
            last = exc
    raise VerifyError("%s/%s could not be verified: %s" % (appid, bucket, last))
