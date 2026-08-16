"""
WorthIt.gg - add the sourcing block to already-published verdicts.

ZERO GEMINI COST, and not by luck: every input `pipeline/sourcing.py` needs is
already inside the published JSON. The citations ship with `voted_up` (verified:
0 of 15,736 missing), the pool rate ships as `pct_positive`, and the claim list
ships in full. Nothing is re-extracted, re-synthesised or re-fetched - no model
is called and no review is re-read. This rewrites files in place from their own
contents.

Deliberately NOT a one-off: run it again after any change to the thresholds in
sourcing.py, and `--check` is what the contract test and CI use to assert that
what shipped still matches what the module computes today.

Usage:
    .venv/bin/python pipeline/backfill_sourcing.py --check     # report only
    .venv/bin/python pipeline/backfill_sourcing.py --write
    .venv/bin/python pipeline/backfill_sourcing.py --write --appids 813780
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sourcing as sourcing_mod                        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "site/public/verdicts"


def recompute(verdict):
    """[(bucket, stored, computed)] for every cohort in the file."""
    out = []
    for cohort in verdict.get("cohorts") or []:
        out.append((cohort.get("bucket"), cohort.get("sourcing"),
                    sourcing_mod.sourcing_block(cohort)))
    return out


def main():
    ap = argparse.ArgumentParser(description="Backfill cohort sourcing blocks")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true",
                   help="report drift, write nothing, exit 1 if any")
    g.add_argument("--write", action="store_true")
    ap.add_argument("--appids", nargs="*", default=None)
    args = ap.parse_args()

    paths = ([VERDICTS / ("%s.json" % a) for a in args.appids] if args.appids
             else sorted(VERDICTS.glob("*.json")))

    changed, drift, levels, triggers = [], [], Counter(), Counter()
    for p in paths:
        verdict = json.loads(p.read_text(encoding="utf-8"))
        dirty = False
        for bucket, stored, computed in recompute(verdict):
            if computed is not None:
                levels[computed["level"]] += 1
                for t in computed["triggers"]:
                    triggers[t] += 1
            if stored != computed:
                dirty = True
                drift.append("%s %s" % (p.stem, bucket))
        if not dirty:
            continue
        changed.append(p.stem)
        if args.write:
            for cohort in verdict.get("cohorts") or []:
                block = sourcing_mod.sourcing_block(cohort)
                if block is None:
                    cohort.pop("sourcing", None)
                else:
                    cohort["sourcing"] = block
            # Byte-for-byte the writer in synthesize.py:872 - 2-space indent,
            # unicode kept, NO trailing newline. A formatting-only diff across
            # 306 files would bury the real change and make the next
            # regeneration of any title look like a revert.
            p.write_text(json.dumps(verdict, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    print("verdicts read      : %d" % len(paths))
    print("cohorts with block : %d  (baseline %d, escalated %d)"
          % (sum(levels.values()), levels["baseline"], levels["escalated"]))
    print("escalation triggers: thin %d, divergent %d"
          % (triggers["thin"], triggers["divergent"]))
    print("files %s : %d" % ("written" if args.write else "needing a write",
                             len(changed)))
    if args.check and drift:
        print("\nDRIFT - stored block does not match what sourcing.py computes:")
        for d in drift[:20]:
            print("  %s" % d)
        if len(drift) > 20:
            print("  ... and %d more" % (len(drift) - 20))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
