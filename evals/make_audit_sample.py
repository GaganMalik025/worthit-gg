"""Build the 4.4-style manual-audit sample for a batch night's new verdicts.

Mechanical extraction only: this script selects and formats, it does not read,
rank, or characterise citation content. Seeded so the sample is reproducible:
re-running with the same --seed and --since reproduces the identical sample.

    .venv/bin/python evals/make_audit_sample.py --date 2026-08-13 --seed 20260813 \
        --gate-note "11,385 citations across 221 verdicts, run 2026-08-13"

Every round gets its OWN seed. Reusing a seed across nights would re-draw
correlated positions in each night's list rather than sampling independently.
"""
import argparse, json, pathlib, random

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "site/public/verdicts"
BUCKETS = ["refund_window", "early", "mid", "veteran"]

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--date", required=True,
                help="batch date, YYYY-MM-DD; scopes the sample to verdicts "
                     "published on or after it and names the output file")
ap.add_argument("--seed", type=int, required=True,
                help="new seed per round - never reuse a previous night's")
ap.add_argument("--appids", default=None,
                help="audit these appids instead of the --date batch scope "
                     "(comma/space list or a file path). For rounds whose "
                     "titles are not in batch_state.json at all - live "
                     "generated or pre-batch - which no --date value can reach.")
ap.add_argument("--gate-note", default="",
                help="the automated QR-4 result this sample sits on top of")
ap.add_argument("--verdicts", type=int, default=10)
ap.add_argument("--citations", type=int, default=20)
ap.add_argument("--out", default=None)
args = ap.parse_args()

SEED = args.seed
SINCE = args.date
OUT = pathlib.Path(args.out) if args.out else ROOT / f"evals/audit-4.4-{args.date}.md"
N_VERDICTS, N_CITATIONS = args.verdicts, args.citations

# Scope. --appids replaces the query and nothing else: the RNG, the
# verdict-word stratification, the per-review dedup and the draw below are
# identical either way. batch_state.json is not read at all on that path,
# which is the point - the titles it exists for are absent from that file
# (live-generated or pre-batch), so no --date value can reach them.
if args.appids:
    raw = pathlib.Path(args.appids).read_text() \
        if pathlib.Path(args.appids).exists() else args.appids
    new_ids = sorted({int(x) for x in raw.replace(",", " ").split()
                      if x.strip().isdigit()})
else:
    state = json.loads((ROOT / "data/batch_state.json").read_text())
    new_ids = sorted(int(k) for k, v in state["titles"].items()
                     if v.get("at", "") > SINCE and v.get("published"))

docs = {}
for appid in new_ids:
    p = VERDICTS / f"{appid}.json"
    if p.exists():
        docs[appid] = json.loads(p.read_text())

rng = random.Random(SEED)

# --- A: ten verdicts, stratified by verdict word so the sample is not all one
sample_a = []
by_word = {}
for appid, d in docs.items():
    by_word.setdefault(d["verdict"]["word"], []).append(appid)
for w in by_word:
    rng.shuffle(by_word[w])
words = sorted(by_word)
i = 0
while len(sample_a) < min(N_VERDICTS, len(docs)):
    w = words[i % len(words)]
    if by_word[w]:
        sample_a.append(by_word[w].pop())
    i += 1

# --- B: twenty citations, stratified evenly across the four cohorts
#
# ONE ENTRY PER REVIEW, not per (claim, citation) pair. A review that backs two
# claims used to sit in the pool twice and could be drawn twice - 2026-08-14
# sampled recommendationid 196900480 (Trove) at both #4 and #16, so that round
# audited 19 distinct reviews while presenting 20 slots. The audit reads REVIEW
# TEXT for QR-4; the same text twice costs a slot and buys nothing.
#
# Dedup runs before the shuffle and keeps first encounter, walking appids in
# sorted order, so the pool is a deterministic function of the inputs and the
# seed still reproduces a sample exactly.
pool = {b: [] for b in BUCKETS}
seen = set()
for appid, d in docs.items():
    for co in d.get("cohorts", []):
        b = co.get("bucket")
        if b not in pool:
            continue
        for th in co.get("themes", []):
            for cl in th.get("claims", []):
                for c in cl.get("citations", []):
                    rid = c["recommendationid"]
                    if rid in seen:
                        continue
                    seen.add(rid)
                    pool[b].append({
                        "appid": appid, "game": d["game_name"], "bucket": b,
                        "rid": rid,
                        "claim": cl["claim"], "text": c["review_text"],
                    })
for b in pool:
    rng.shuffle(pool[b])

sample_b, k = [], 0
while len(sample_b) < N_CITATIONS and any(pool[b] for b in BUCKETS):
    b = BUCKETS[k % len(BUCKETS)]
    if pool[b]:
        sample_b.append(pool[b].pop())
    k += 1
rng.shuffle(sample_b)


def line(s, n):
    return " ".join(str(s).split())[:n]


L = []
# The batch-night wording is false for an --appids round: nothing was
# "published by the {SINCE} batch". Conditioned rather than reworded for
# everyone, so a --date round renders byte-identical to before.
if args.appids:
    L.append(f"# 4.4 audit - sample for manual review ({SINCE}, "
             f"{len(docs)} named titles)\n")
    L.append(f"Generated from an explicit appid list, not a batch night: "
             f"{', '.join(str(a) for a in sorted(docs))}. These titles are not "
             "in data/batch_state.json, so no date-scoped round can reach "
             "them.\n")
else:
    L.append(f"# 4.4 morning audit - sample for manual review ({SINCE} batch)\n")
    L.append(f"Generated from the {len(docs)} verdicts published by the {SINCE} "
             "overnight batch. Earlier catalog titles are out of scope here - they "
             "were audited in their own rounds.\n")
L.append("Automated QR-4 has already passed on every citation in this set"
         + (f" ({args.gate_note})" if args.gate_note else "")
         + ". This sample is the HUMAN gate that BUILD_PLAN calls the last one "
           "before strangers.\n")
L.append(f"Selection is seeded (`SEED = {SEED}`) and stratified: section A "
         "round-robins across verdict words, section B round-robins across the "
         "four playtime cohorts. Re-running the generator reproduces this exact "
         "sample.\n")
# "Ten" was hardcoded and is right for every date-scoped round; an --appids
# round can hold fewer titles than N_VERDICTS, and a heading that overstates
# its own coverage is the defect this whole re-audit exists to repair.
L.append("\n## A. %s verdicts to spot-check\n"
         % ("Ten" if len(sample_a) == 10 else len(sample_a)))
for appid in sample_a:
    d = docs[appid]
    tier = d["model"]["synthesis"].replace("gemini-3.5-", "")
    rates = " -> ".join(f"{s['bucket'][:4]} {s['pct_positive']}%"
                        for s in d["split_bar"])
    L.append(f"- [ ] **{d['game_name']}** (`{appid}`, {tier}) - "
             f"**{d['verdict']['word']}**")
    L.append(f"      {rates}")
    L.append(f"      > {line(d['verdict']['tagline'], 200)}\n")

L.append("\n## B. Twenty citations to audit for QR-4 (invariant 8)\n")
L.append("Read each review text. Anything NSFW or slur-bearing blocks deploy.\n")
for n, c in enumerate(sample_b, 1):
    L.append(f"{n:2d}. [ ] {c['game']} / {c['bucket']} / `{c['rid']}`")
    L.append(f"       claim: {line(c['claim'], 110)}")
    L.append(f"       text : {line(c['text'], 260)}\n")

L.append("\n## Result\n")
L.append("- [ ] QR-4: all 20 citations clean (any failure blocks deploy)")
L.append("- [ ] Verdicts: all %d read as defensible against their split"
         % len(sample_a))
L.append("\nNotes:\n")

OUT.write_text("\n".join(L), encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}")
print(f"  verdicts in scope : {len(docs)}")
print(f"  section A         : {len(sample_a)} verdicts")
print(f"  section B         : {len(sample_b)} citations")
print("  cohort spread     : " + ", ".join(
    f"{b}={sum(1 for c in sample_b if c['bucket'] == b)}" for b in BUCKETS))
print("  citation pool     : " + ", ".join(
    f"{b}={len(pool[b]) + sum(1 for c in sample_b if c['bucket'] == b)}"
    for b in BUCKETS))
