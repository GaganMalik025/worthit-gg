r"""What the 2026-08-26 banned_words() fix costs in cached synthesis prompts.

ANSWER, measured below and stated here because it is the opposite of what the
plan for this change assumed: the marginal cost is ZERO CALLS. Every cached
synthesis entry was already unreachable before today - the 2026-08-25 absolute-
quantifier split added `none` to banned_words() and moved every key then, and no
title has been synthesised since. The 1,009 figure is real; its cost today is
not. The run proves that rather than asserting it, by resolving the same entries
under the guard they were actually written with (--baseline-ref).

banned_words() goes 8 -> 10 (gaining everyone, nobody), so
`synthesize._SYSTEM_TEMPLATE % {"banned": ...}` changes, so `system` changes, so
every key `cache_path(appid, "synthesis", model, system, prompt,
tag="verdict-v1-attempt%d")` produces moves. 1,009 files across 537 titles.

But "1,009 invalidated" is not the cost, and this measures the difference rather
than repeating the headline:

  * synthesize.py reads the synthesis cache ONLY at attempt 0
    (`if cpath.exists() and not args.force and attempt == 0`). Retry entries are
    written but never replayed - deliberately, so a rejected answer cannot be
    served back (BACKLOG 2026-08-18, Insurgency). Invalidating one costs nothing.
  * So the repeat cost is at most one call per title, and only for titles whose
    attempt-0 entry is reachable TODAY. Entries written under an older prompt
    version are already unreachable and cost nothing either.

Rather than bound it, this rebuilds each title's real attempt-0 prompt: wrap
`synthesize.build_user_turn` to capture its return, call `synthesize_one` with
dry_run (which returns before any client use) and force_lite (which hard-wires
flash-lite in model_for, so the flash ledger is never touched), then compute the
key under the OLD banned list - read from git, not hardcoded - and the NEW one.

Free: reads data/ only. No network, no Gemini, no ledger.

Run:  .venv/bin/python evals/measure_banned_words_cache_cost_2026-08-26.py
"""
import argparse
import collections
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, "pipeline")
import extract_claims as ec          # noqa: E402
import synthesize                    # noqa: E402

CACHE_DIR = pathlib.Path("data/cache/extract")
MODEL = "gemini-3.5-flash-lite"


def banned_at_ref(ref):
    """banned_words() as of a git ref, so 'the old list' is not a hardcode."""
    src = subprocess.run(["git", "show", "%s:pipeline/prevalence_guard.py" % ref],
                         capture_output=True, text=True, check=True).stdout
    tmp = pathlib.Path(tempfile.mkdtemp()) / "prevalence_guard_at_ref.py"
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("pg_at_ref", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.banned_words()


def system_for(banned):
    return synthesize._SYSTEM_TEMPLATE % {"banned": ", ".join(banned)}


def dry_args():
    a = types.SimpleNamespace(
        claims="data/claims", filtered="data/filtered", out="site/public/verdicts",
        model=MODEL, model_override=None, force_lite=True, flash_day=None,
        flash_fallback=False, force=False, retries=2, dry_run=True,
        show_prompt=False, seeds=False, appids=None)
    return a


def attempt0_prompts(limit=None):
    """{appid: user turn} for every title whose inputs still build a prompt."""
    captured = {}
    real = synthesize.build_user_turn

    def spy(*args, **kwargs):
        out = real(*args, **kwargs)
        captured["user"] = out
        return out

    synthesize.build_user_turn = spy
    prompts, skipped = {}, collections.Counter()
    try:
        appids = sorted(p.stem for p in pathlib.Path("data/claims").glob("*.json"))
        if limit:
            appids = appids[:limit]
        for appid in appids:
            captured.clear()
            args = dry_args()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    synthesize.synthesize_one(None, args, appid)
            except FileNotFoundError:
                skipped["missing_inputs"] += 1
                continue
            except Exception as exc:                     # noqa: BLE001
                skipped[type(exc).__name__] += 1
                continue
            if "user" not in captured:
                # refused before the prompt: below the evidence floor, no
                # verdict word, nothing to synthesise. Never cached either.
                skipped["no_prompt_built"] += 1
                continue
            prompts[appid] = captured["user"]
    finally:
        synthesize.build_user_turn = real
    return prompts, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-ref", default="HEAD",
                    help="git ref holding the pre-fix guard (default HEAD)")
    ap.add_argument("--baseline-ref", default="0211b2b^",
                    help="git ref holding the guard the caches were WRITTEN "
                         "under; without this the run cannot tell 'my harness "
                         "is broken' from 'these entries were already dead'")
    ap.add_argument("--limit", type=int, help="only walk N titles (smoke test)")
    ap.add_argument("--out", help="write the report here as well as stdout")
    a = ap.parse_args()

    old_banned = banned_at_ref(a.old_ref)
    base_banned = banned_at_ref(a.baseline_ref)
    new_banned = __import__("prevalence_guard").banned_words()
    old_system, new_system = system_for(old_banned), system_for(new_banned)
    base_system = system_for(base_banned)
    if old_system == new_system:
        raise SystemExit("old and new SYSTEM_INSTRUCTION are identical - either "
                         "the fix is not applied, or --old-ref already has it")

    prompts, skipped = attempt0_prompts(a.limit)

    on_disk = collections.Counter()
    for d in CACHE_DIR.glob("*/"):
        on_disk[d.name] = len(list(d.glob("synthesis_*.json")))
    total_files = sum(on_disk.values())

    def key(appid, system, user):
        return ec.cache_path(appid, "synthesis", MODEL, system, user,
                             tag="verdict-v1-attempt0")

    rows = []
    for appid, user in sorted(prompts.items()):
        bk, ok, nk = (key(appid, base_system, user), key(appid, old_system, user),
                      key(appid, new_system, user))
        rows.append({"appid": appid,
                     "base_key": bk.name, "old_key": ok.name, "new_key": nk.name,
                     "base_reachable": bk.exists(),
                     "old_reachable": ok.exists(), "new_reachable": nk.exists(),
                     "moved": ok.name != nk.name,
                     "files_for_title": on_disk.get(appid, 0)})

    base = [r for r in rows if r["base_reachable"]]
    reach = [r for r in rows if r["old_reachable"]]
    lost = [r for r in reach if not r["new_reachable"]]

    buf = io.StringIO()
    w = buf.write
    w("Cost of the 2026-08-26 banned_words() fix, in cached synthesis prompts\n")
    w("driver: evals/measure_banned_words_cache_cost_2026-08-26.py"
      "   (disk only, 0 Gemini calls)\n")
    w("old banned list (%s, %d words): %s\n"
      % (a.old_ref, len(old_banned), ", ".join(old_banned)))
    w("new banned list (working tree, %d words): %s\n"
      % (len(new_banned), ", ".join(new_banned)))
    w("added: %s\n" % ", ".join(sorted(set(new_banned) - set(old_banned))))

    w("\nWHAT IS ON DISK\n")
    w("  synthesis cache files            : %d across %d titles\n"
      % (total_files, len([k for k, v in on_disk.items() if v])))
    w("  every one of their keys moves - `system` is hashed at "
      "synthesize.py:864\n")

    w("\nWHAT IS ACTUALLY READ\n")
    w("  synthesize.py:865 serves the cache only when attempt == 0, so retry\n"
      "  entries are written and never replayed. Only attempt-0 entries can\n"
      "  cost a repeat call.\n")
    w("  titles whose attempt-0 prompt rebuilds  : %d\n" % len(rows))
    w("\n  attempt-0 entries reachable, by guard version:\n")
    w("    %-26s (%2d words) : %d\n"
      % (a.baseline_ref, len(base_banned), len(base)))
    w("    %-26s (%2d words) : %d\n"
      % (a.old_ref + ", before today", len(old_banned), len(reach)))
    w("    %-26s (%2d words) : %d\n"
      % ("working tree, after today", len(new_banned),
         sum(1 for r in rows if r["new_reachable"])))
    w("\n  ** repeat cost of TODAY's change, in calls : %d **\n" % len(lost))
    w("  never-read residue of the %d files        : %d\n"
      % (total_files, total_files - len(reach)))
    if skipped:
        w("  titles that built no prompt               : %s\n" % dict(skipped))
    if not reach and base:
        w("\n  READ THIS BEFORE QUOTING THE ZERO. The harness is not broken -\n"
          "  it resolves %d attempt-0 entries under %s. Nothing is reachable\n"
          "  under %s because an EARLIER guard change already moved every key,\n"
          "  and no title has been synthesised since. Today's change therefore\n"
          "  invalidates entries that were already dead: the 1,009 figure is\n"
          "  real and its marginal cost is not.\n"
          % (len(base), a.baseline_ref, a.old_ref))

    moved = sum(1 for r in rows if r["moved"])
    w("\nSANITY\n")
    w("  attempt-0 keys that move (must equal titles rebuilt): %d of %d\n"
      % (moved, len(rows)))
    w("  titles reachable before but not after (must equal the repeat cost): "
      "%d\n" % len(lost))
    unreachable = [r for r in rows if not r["old_reachable"]]
    w("  titles whose attempt-0 entry was ALREADY unreachable: %d\n"
      % len(unreachable))
    w("    (an older guard or prompt version, or a title never synthesised from\n"
      "     these exact inputs - already costing a call before this change)\n")
    w("  ANTI-VACUITY: entries resolvable under %s (proves the rebuild is\n"
      "  faithful and a zero above is a fact, not a broken harness) : %d\n"
      % (a.baseline_ref, len(base)))

    out = buf.getvalue()
    print(out, end="")
    here = pathlib.Path(__file__).resolve().parent
    json.dump(rows, (here / "banned-words-cache-cost-2026-08-26.json").open("w"),
              indent=1)
    print("per-title detail -> %s"
          % (here / "banned-words-cache-cost-2026-08-26.json"))
    if a.out:
        pathlib.Path(a.out).write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
