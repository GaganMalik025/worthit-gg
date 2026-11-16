"""
Break-then-confirm for the home-page redesign (owner, 2026-11-16).

Each mutation edits ONE real source file, must apply exactly once per replacement,
and must fail a NAMED check in the suite that guards it:
  site/lib/__tests__/home-sections.contract.test.tsx   (layout, rows, browse pages)
  pipeline/test_genres.py                               (the membership rule)
A suite that crashes before printing its own output is SUITE DID NOT RUN, never
caught. Offline, no quota.

    .venv/bin/python -B evals/mutate_home_sections_2026-11-16.py --run

STATE-CHANGING WHILE RUNNING: it edits sources in place and restores each by sha.
Without --run it prints this and exits 2.
Output: evals/mutate-home-sections-2026-11-16.txt, one log per case in
evals/mutation-logs/hs*.log.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

if "--run" not in sys.argv[1:]:
    print(__doc__)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LOGS = ROOT / "evals/mutation-logs"
OUT = ROOT / "evals/mutate-home-sections-2026-11-16.txt"
PY = str(ROOT / ".venv/bin/python")

SITE_SUITE = ("site", "lib/__tests__/home-sections.contract.test.tsx", "Tests ")
PY_SUITE = ("py", "pipeline/test_genres.py", "membership: a section tag")

GEN = "site/lib/genres.ts"
SHELL = "site/components/SiteShell.tsx"
ROW = "site/components/SectionRow.tsx"
BROWSE = "site/components/BrowseSection.tsx"
ROUTE = "site/app/browse/[slug]/page.tsx"
CSS = "site/app/globals.css"
BG = "pipeline/build_genres.py"

CASES = [
    ("hs02", "a section shows 31 games", GEN,
     [("export const ROW_LIMIT = 30;", "export const ROW_LIMIT = 31;")],
     SITE_SUITE, "caps a section at 30 games"),
    ("hs03", "a section is not capped at all", GEN,
     [("sectionGames(entries, genres, s.slug).slice(0, ROW_LIMIT)",
       "sectionGames(entries, genres, s.slug)")],
     SITE_SUITE, "caps a section at 30 games"),
    ("hs04", "least popular first", GEN,
     [("return b.steam_total_reviews - a.steam_total_reviews || a.appid - b.appid;",
       "return a.steam_total_reviews - b.steam_total_reviews || a.appid - b.appid;")],
     SITE_SUITE, "orders most popular first"),
    ("hs05", "popularity ties keep file order", GEN,
     [("return b.steam_total_reviews - a.steam_total_reviews || a.appid - b.appid;",
       "return b.steam_total_reviews - a.steam_total_reviews;")],
     SITE_SUITE, "breaks popularity ties by appid"),
    ("hs06", "an empty section is rendered", GEN,
     [("    .filter((s) => s.games.length > 0);\n", ";\n")],
     SITE_SUITE, "drops a section with no games"),
    ("hs07", "the Show all games wall is removed", ROW,
     [('        <a className="shelf-wall" href={`/browse/${slug}`}>\n'
       '          Show all games <span aria-hidden="true">&rarr;</span>\n'
       '        </a>\n', "")],
     SITE_SUITE, "then the wall"),
    ("hs08", "the promise leaves the header", SHELL,
     [('          <span className="promise">Should you buy it? The verdict, with receipts.</span>\n',
       "")],
     SITE_SUITE, "puts the wordmark and promise top left"),
    ("hs09", "posters back at the old 232px", CSS,
     [("grid-auto-columns:174px", "grid-auto-columns:232px")],
     SITE_SUITE, "posters are 174px wide"),
    ("hs10", "the browse page has 3 columns", CSS,
     [("grid-template-columns:repeat(5,174px)", "grid-template-columns:repeat(3,174px)")],
     SITE_SUITE, "posters are 174px wide"),
    ("hs11", "a browse page shows only 30", BROWSE,
     [("{games.map((e) => (", "{games.slice(0, 30).map((e) => (")],
     SITE_SUITE, "a browse page lists every game"),
    ("hs12", "unknown sections render on demand", ROUTE,
     [("export const dynamicParams = false;", "export const dynamicParams = true;")],
     SITE_SUITE, "prerenders exactly the sections"),
    ("hs13", "a browse page keeps the wordmark as its h1", BROWSE,
     [("<SiteShell entries={entries} brandIsHeading={false}>", "<SiteShell entries={entries}>")],
     SITE_SUITE, "a browse page lists every game"),
    ("hs14", "membership reads the top 11 tags", BG,
     [("TOP_N = 10", "TOP_N = 11")],
     PY_SUITE, "the 11th tag does not"),
    ("hs15", "membership is any tag, not the top 10", BG,
     [("        top = set(top_tags(tags))\n", "        top = set(tags)\n")],
     PY_SUITE, "the 11th tag does not"),
    ("hs16", "a tagged title uses the fallback too", BG,
     [("    if tags:\n        top = set(top_tags(tags))\n",
       "    if tags and not fallback:\n        top = set(top_tags(tags))\n")],
     PY_SUITE, "a tagged title ignores the fallback"),
    ("hs17", "tag ties depend on dict order", BG,
     [("key=lambda kv: (-kv[1], kv[0])", "key=lambda kv: -kv[1]")],
     PY_SUITE, "ties break by name"),
]


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12]


def run_suite(suite):
    kind, path, _ = suite
    if kind == "py":
        shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
        p = subprocess.run([PY, "-B", path], cwd=str(ROOT), capture_output=True, text=True,
                           timeout=600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    else:
        p = subprocess.run(["npx", "vitest", "run", path], cwd=str(SITE),
                           capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def failed_lines(kind, out):
    if kind == "py":
        return [ln.strip() for ln in out.splitlines() if ln.rstrip().endswith("FAIL")]
    return [ln.strip() for ln in out.splitlines()
            if ln.strip().startswith(("FAIL", "×", "✗"))]


results, lines = [], []


def record(tag, desc, verdict, detail):
    results.append((tag, verdict))
    (LOGS / ("%s.log" % tag)).write_text("%s\n%s\n\n%s\n%s\n" % (tag, desc, verdict, detail),
                                         encoding="utf-8")
    line = "  %-5s %-16s %s" % (tag, verdict, desc)
    lines.append(line)
    print(line, flush=True)


LOGS.mkdir(parents=True, exist_ok=True)
files = sorted({c[2] for c in CASES})
before = {f: sha(f) for f in files}

for tag, suite in (("hs01a", SITE_SUITE), ("hs01b", PY_SUITE)):
    rc, out = run_suite(suite)
    record(tag, "CONTROL: %s green, unmutated" % suite[1],
           "PASS" if rc == 0 and suite[2] in out else "CONTROL FAILED", out[-600:])

for tag, desc, rel, edits, suite, expect in CASES:
    target = ROOT / rel
    original = target.read_bytes()
    text = original.decode("utf-8")
    bad = [old for old, _ in edits if text.count(old) != 1]
    if bad:
        record(tag, desc, "MUTATION DID NOT APPLY",
               "\n".join("%d occurrences of %r" % (text.count(o), o[:80]) for o in bad))
        continue
    mutated = text
    for old, new in edits:
        mutated = mutated.replace(old, new)
    try:
        target.write_text(mutated, encoding="utf-8")
        rc, out = run_suite(suite)
    finally:
        target.write_bytes(original)
    failed = failed_lines(suite[0], out)
    named = [ln for ln in failed if expect in ln]
    if suite[2] not in out:
        verdict = "SUITE DID NOT RUN"
    elif rc == 0:
        verdict = "NOTHING FAILED"
    elif named:
        verdict = "CAUGHT+NAMED"
    else:
        verdict = "RED, WRONG NAME"
    record(tag, desc, verdict, "file: %s\nexpected: %s\n%s\n%s"
           % (rel, expect, "\n".join(failed[:12]), out[-800:] if not named else ""))

shutil.rmtree(ROOT / "pipeline/__pycache__", ignore_errors=True)
restored = {f: sha(f) == before[f] for f in files}
summary = ["", "restored byte-identical:"] + [
    "  %-40s %s (%s)" % (f, restored[f], before[f]) for f in files]
bad = [t for t, v in results if v not in ("PASS", "CAUGHT+NAMED")]
summary.append("%d/%d as expected%s" % (len(results) - len(bad), len(results),
                                         ("; NOT: %s" % ", ".join(bad)) if bad else ""))
print("\n".join(summary))
OUT.write_text("mutate_home_sections_2026-11-16.py --run\n\n" + "\n".join(lines + summary) + "\n",
               encoding="utf-8")
sys.exit(0 if not bad and all(restored.values()) else 1)
