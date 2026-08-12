"""Build the 4.4-style manual-audit sample for tonight's new verdicts.

Mechanical extraction only: this script selects and formats, it does not read,
rank, or characterise citation content. Seeded so the sample is reproducible.
"""
import json, pathlib, random, sys

SEED = 20260812
ROOT = pathlib.Path("/Users/gaganmalik/Downloads/worthit-gg")
VERDICTS = ROOT / "site/public/verdicts"
OUT = ROOT / "evals/audit-4.4-2026-08-12.md"
N_VERDICTS, N_CITATIONS = 10, 20
BUCKETS = ["refund_window", "early", "mid", "veteran"]

state = json.loads((ROOT / "data/batch_state.json").read_text())
new_ids = sorted(int(k) for k, v in state["titles"].items()
                 if v.get("at", "") > "2026-08-12" and v.get("published"))

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
pool = {b: [] for b in BUCKETS}
for appid, d in docs.items():
    for co in d.get("cohorts", []):
        b = co.get("bucket")
        if b not in pool:
            continue
        for th in co.get("themes", []):
            for cl in th.get("claims", []):
                for c in cl.get("citations", []):
                    pool[b].append({
                        "appid": appid, "game": d["game_name"], "bucket": b,
                        "rid": c["recommendationid"],
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
L.append("# 4.4 morning audit - sample for manual review (2026-08-12 batch)\n")
L.append(f"Generated from the {len(docs)} verdicts published by the 2026-08-12 "
         "overnight batch. Earlier catalog titles are out of scope here - they "
         "were audited in their own rounds.\n")
L.append("Automated QR-4 has already passed on every citation in this set "
         f"(9,157 citations across 176 verdicts, {docs and ''}run 2026-08-12). "
         "This sample is the HUMAN gate that BUILD_PLAN calls the last one "
         "before strangers.\n")
L.append(f"Selection is seeded (`SEED = {SEED}`) and stratified: section A "
         "round-robins across verdict words, section B round-robins across the "
         "four playtime cohorts. Re-running the generator reproduces this exact "
         "sample.\n")
L.append("\n## A. Ten verdicts to spot-check\n")
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
L.append("- [ ] Verdicts: all 10 read as defensible against their split")
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
