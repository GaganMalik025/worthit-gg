"""Pool-positivity + matched-band analysis, from batch_state.json + verdict JSONs."""
import json, pathlib, statistics as stats
ROOT = pathlib.Path("/Users/gaganmalik/Downloads/worthit-gg")
NIGHTS = ["2026-08-12", "2026-08-13", "2026-08-14", "2026-08-16",
          "2026-08-17", "2026-08-18"]

st = json.loads((ROOT / "data/batch_state.json").read_text())
rows = {n: [] for n in NIGHTS}
skipped = 0
for appid, v in st["titles"].items():
    if not v.get("published"):
        continue
    night = next((n for n in NIGHTS if v.get("at", "").startswith(n)), None)
    if night is None:
        continue
    p = ROOT / f"site/public/verdicts/{appid}.json"
    if not p.exists():
        skipped += 1
        continue
    d = json.loads(p.read_text())
    sb = d.get("split_bar") or []
    tot = sum(s["pool_n"] for s in sb)
    if not tot:
        skipped += 1
        continue
    rows[night].append({
        "appid": int(appid),
        "word": d["verdict"]["word"],
        "wpos": sum(s["pool_n"] * s["pct_positive"] for s in sb) / tot,
        **{s["bucket"]: s["pct_positive"] for s in sb},
    })

print(f"titles loaded: {sum(len(r) for r in rows.values())}   skipped: {skipped}\n")
print(f"{'night':<12} {'n':>3} {'weighted pos%':>14} {'median':>8} {'buy%':>6}")
print("-" * 52)
for n in NIGHTS:
    r = rows[n]; w = [x["wpos"] for x in r]
    buy = sum(1 for x in r if x["word"] == "Buy") / len(r) * 100
    print(f"{n:<12} {len(r):>3} {stats.mean(w):>13.1f}% {stats.median(w):>7.1f}% {buy:>5.0f}%")

print("\nper-cohort mean pct_positive")
print(f"{'night':<12} {'refund':>8} {'early':>8} {'mid':>8} {'veteran':>8}")
print("-" * 46)
for n in NIGHTS:
    line = f"{n:<12}"
    for b in ("refund_window", "early", "mid", "veteran"):
        vals = [x[b] for x in rows[n] if b in x]
        line += f" {stats.mean(vals):>7.1f}%" if vals else f"{'-':>8}"
    print(line)

print("\nBuy rate within matched positivity bands")
BANDS = [(0, 80), (80, 86), (86, 90), (90, 101)]
hdr = f"{'band':<12}" + "".join(f"{n[-5:]:>12}" for n in NIGHTS)
print(hdr); print("-" * len(hdr))
for lo, hi in BANDS:
    line = f"{lo}-{hi}%".ljust(12)
    for n in NIGHTS:
        sel = [x["word"] for x in rows[n] if lo <= x["wpos"] < hi]
        line += (f"{sum(1 for w in sel if w=='Buy')/len(sel)*100:>9.0f}% ({len(sel)})"
                 if sel else f"{'-':>12}")
    print(line)

print("\ntitles per band per night")
for n in NIGHTS:
    d = [sum(1 for x in rows[n] if lo <= x["wpos"] < hi) for lo, hi in BANDS]
    print(f"  {n}: <80%={d[0]:>2}  80-86%={d[1]:>2}  86-90%={d[2]:>2}  90%+={d[3]:>2}")
