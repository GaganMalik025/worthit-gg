"""
Offline tests for build_genres.py, the home page's section membership (2026-11-16).
No network: build() runs with offline=True against a temp cache.

Run:  .venv/bin/python pipeline/test_genres.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_genres as bg  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print("  %-62s %s" % (name, "ok" if cond else "FAIL"))
    if not cond:
        FAILURES.append("%s %s" % (name, detail))


def ranked(*names):
    """A SteamSpy tag dict whose vote order is the argument order."""
    return {t: 1000 - i for i, t in enumerate(names)}


FILLER = ["Action", "Adventure", "Singleplayer", "3D", "Atmospheric", "Great Soundtrack",
          "Exploration", "Fantasy", "Colorful", "Third Person"]


def test_membership_rule():
    print("\nmembership: a section tag must be among the title's top 10 by votes")
    check("a top tag puts the title in its section",
          bg.classify(ranked("Story Rich", *FILLER)) == ["story-driven"])
    check("the 10th tag still counts",
          "horror" in bg.classify(ranked(*FILLER[:9], "Horror")))
    check("the 11th tag does not",
          "horror" not in bg.classify(ranked(*FILLER, "Horror")), bg.classify(ranked(*FILLER, "Horror")))
    check("a title can sit in several sections",
          bg.classify(ranked("Open World", "Survival", "Co-op")) ==
          ["open-world", "co-op", "survival-crafting"], bg.classify(ranked("Open World", "Survival", "Co-op")))
    check("sections come back in home-page order",
          bg.classify(ranked("Free to Play", "Story Rich")) == ["story-driven", "free-to-play"])
    check("ties break by name, so the result never depends on dict order",
          bg.top_tags({"B": 5, "A": 5, "C": 9}, n=2) == ["C", "A"])


def test_fallback():
    print("\nfallback: Steam genres only when SteamSpy has no tags at all")
    check("an untagged RPG falls back to its Steam genre",
          bg.classify({}, ["Action", "RPG"]) == ["rpgs"])
    check("the co-op categories map to co-op",
          bg.classify({}, ["Online Co-op"]) == ["co-op"])
    check("an unmapped genre places the title nowhere", bg.classify({}, ["Action", "Indie"]) == [])
    check("a tagged title ignores the fallback",
          bg.classify(ranked("Story Rich"), ["RPG"]) == ["story-driven"])


def test_build_offline():
    print("\nbuild: the written shape, from cache only")
    with tempfile.TemporaryDirectory() as d:
        saved = bg.CACHE
        bg.CACHE = Path(d)
        try:
            (Path(d) / "steamspy").mkdir()
            (Path(d) / "steam").mkdir()
            (Path(d) / "steamspy" / "1.json").write_text(json.dumps({"tags": ranked("Horror")}))
            (Path(d) / "steamspy" / "2.json").write_text(json.dumps({"tags": {}}))
            (Path(d) / "steam" / "2.json").write_text(json.dumps(["Free to Play"]))
            (Path(d) / "steamspy" / "3.json").write_text(json.dumps({"tags": {}}))
            (Path(d) / "steam" / "3.json").write_text(json.dumps(["Action"]))
            out = bg.build([1, 2, 3, 4], offline=True)
        finally:
            bg.CACHE = saved
    check("members are keyed by appid string", out["members"].get("1") == ["horror"], out["members"])
    check("a fallback title is recorded as such", out["fell_back"] == [2], out["fell_back"])
    check("titles in no section are listed, uncached ones included",
          out["in_no_section"] == [3, 4], out["in_no_section"])
    check("all 12 sections are written in order",
          [s["slug"] for s in out["sections"]] == [s for s, _, _, _ in bg.SECTIONS])
    check("there are exactly 12", len(out["sections"]) == 12)


if __name__ == "__main__":
    test_membership_rule()
    test_fallback()
    test_build_offline()
    if FAILURES:
        print("\n%d FAILURES:" % len(FAILURES))
        for f in FAILURES:
            print("  %s" % f)
        sys.exit(1)
    print("\nall genre tests passed")
