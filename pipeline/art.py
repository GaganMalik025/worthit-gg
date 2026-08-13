"""Cover art for a title, resolved in three tiers.

WHY THIS EXISTS. The site hardcoded one URL pattern -
`cdn.cloudflare.steamstatic.com/steam/apps/<appid>/library_600x900.jpg` - and
Steam has been migrating store art to a content-hash path
(`.../store_item_assets/steam/apps/<appid>/<hash>/...`). Measured over the full
411-title manifest on 2026-08-13: 12 titles 404 on BOTH legacy stages and render
artless, 5 more lose only the portrait, and one (Battlefield 6) returns HTTP 200
with a 1,655-byte BLANK placeholder - which no onError fallback can ever catch,
because the request succeeded.

NOTHING ABOUT THE NEW URL IS CONSTRUCTIBLE. Measured, not assumed: the host
varies (akamai/fastly), the hash differs per asset within one appid, and sibling
filenames 404 - from PEAK's real header base, `library_600x900.jpg`,
`capsule_616x353.jpg` AND `header.jpg` all 404, because its canonical file is
`header_alt_assets_3.jpg`. The URL has to be captured verbatim; any scheme that
rebuilds it from a pattern will break again.

THE TIERS
  1. Steam appdetails `header_image` / `capsule_image`. Official Valve art, on a
     request the pipeline ALREADY MAKES (resolve_game_name) and already throws
     away. Free.
  2. SteamGridDB grids, portrait, by steam appid. FAN ART - see the OG rule.
  3. The legacy CDN pattern, unchanged, as the last resort.

THE OG RULE, AND WHY IT IS IN CODE AND NOT JUST IN A COMMENT.
Tier 2 is COMMUNITY-UPLOADED art. It may go in a grid tile, where it reads as a
thumbnail. It may NEVER go in an OpenGraph/unfurl image, where it would travel
into a Reddit or Twitter card beside our verdict and be read as Valve's own -
a trust claim this product cannot make. `og_art()` therefore cannot reach tier 2
by construction: it is a separate function over a separate tier list, not a flag
on a shared one, because a flag is one bad default away from shipping fan art
into an unfurl.

SAFETY. Tier 2 entries carry `nsfw` and `humor` flags, and invariant 8 (QR-4) is
a launch gate. The query pins `nsfw=false&humor=false` server-side AND the
response is re-filtered here, because a query parameter is a request and a check
is a guarantee.
"""
import json
import os
import pathlib
import re
import time
import urllib.parse

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data/cache"

LEGACY_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"
SGDB_BASE = "https://www.steamgriddb.com/api/v2"

# Cloudflare fingerprints the client: a bare urllib/requests UA gets a 403 with
# Cloudflare error 1010 on every call, key or no key. This is not our ban and
# not a bad key - it is the default UA. Measured 2026-08-13.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Portrait only, static only, and never NSFW or joke art.
SGDB_QUERY = {"nsfw": "false", "humor": "false",
              "dimensions": "600x900", "types": "static"}

SGDB_TIMEOUT = 20
SGDB_ATTEMPTS = 3


def _key():
    """The SteamGridDB key, or None. Never logged, never returned to a caller."""
    key = os.environ.get("STEAMGRIDDB_API_KEY")
    if key:
        return key.strip()
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^STEAMGRIDDB_API_KEY\s*=\s*(.*)$", line.strip())
        if m:
            return m.group(1).strip().strip('"').strip("'") or None
    return None


# ---------------------------------------------------------------- tier 1
def steam_art(appid, details=None):
    """{header_image, capsule_image} from Steam's own appdetails, or {}.

    `details` is the parsed appdetails `data` block when a caller already has
    it - fetch_reviews does, on the request it makes to resolve the name, so
    the common path costs no extra call.
    """
    if details is None:
        path = CACHE_DIR / str(appid) / "appdetails.json"
        if path.exists():
            try:
                details = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                details = {}
        else:
            details = {}
    out = {}
    for field in ("header_image", "capsule_image"):
        val = (details or {}).get(field)
        if isinstance(val, str) and val.startswith("http"):
            out[field] = val
    return out


# ---------------------------------------------------------------- tier 2
def _sgdb_cache_path(appid):
    return CACHE_DIR / str(appid) / "steamgriddb.json"


def sgdb_grid(appid, refresh=False):
    """Portrait fan-art URL from SteamGridDB, or None. Cached forever.

    NEVER call this for an OG image - see the module docstring.

    Cached permanently on purpose: a title's art does not churn, and the cache
    records misses as well as hits, so an obscure title is asked about once and
    never again. Any non-success outcome - 404 "Game not found", a 429, a
    timeout, a missing key - returns None so the caller falls through to
    tier 3. It never retries past the attempt budget: art is decoration, and a
    batch night must not stall on a decoration service.
    """
    path = _sgdb_cache_path(appid)
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("url")
        except (ValueError, OSError):
            pass

    key = _key()
    if not key:
        return None

    url = "%s/grids/steam/%s?%s" % (SGDB_BASE, appid,
                                    urllib.parse.urlencode(SGDB_QUERY))
    headers = {"Authorization": "Bearer %s" % key, "User-Agent": UA}

    picked, reason = None, "unknown"
    for attempt in range(SGDB_ATTEMPTS):
        try:
            r = requests.get(url, headers=headers, timeout=SGDB_TIMEOUT)
        except requests.RequestException as exc:
            reason = "request_failed: %s" % type(exc).__name__
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            # The documented miss, verified 2026-08-13 against appid 999999999:
            # {"success":false,"status":404,"errors":["Game not found"]}.
            # A miss is an ANSWER, not a failure - cache it and stop asking.
            reason = "not_found"
            break
        if r.status_code == 429:
            # Fall through to tier 3 rather than retrying. SteamGridDB
            # publishes no rate limit, so the only safe reading of a 429 is
            # "stop", not "wait and try again".
            reason = "rate_limited"
            break
        if r.status_code != 200:
            reason = "http_%d" % r.status_code
            time.sleep(2 ** attempt)
            continue
        try:
            blob = r.json()
        except ValueError:
            reason = "bad_json"
            break
        if not blob.get("success"):
            reason = "unsuccessful: %s" % ",".join(blob.get("errors") or [])
            break
        # Re-filter locally. The query already pins nsfw/humor, but invariant 8
        # is a launch gate and a request is not a guarantee.
        for row in blob.get("data") or []:
            if row.get("nsfw") or row.get("humor"):
                continue
            if not isinstance(row.get("url"), str):
                continue
            picked, reason = row["url"], "ok"
            break
        else:
            reason = "no_clean_candidate"
        break

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"appid": appid, "url": picked,
                                "reason": reason, "source": "steamgriddb"},
                               ensure_ascii=False), encoding="utf-8")
    return picked


# ---------------------------------------------------------------- tier 3
def legacy(appid):
    """The original hardcoded pattern. Correct for ~97% of titles; kept last."""
    return {"portrait": "%s/%s/library_600x900.jpg" % (LEGACY_CDN, appid),
            "landscape": "%s/%s/header.jpg" % (LEGACY_CDN, appid)}


# ---------------------------------------------------------------- assembly
def art_block(appid, details=None, allow_sgdb=True):
    """The `art` block for a verdict JSON: tiers 1 and 2, resolved once.

    Tier 3 is NOT stored - it is a pattern the site can always rebuild from the
    appid, and writing it into 221 files would bake today's CDN hostname into
    every artifact.
    """
    block = dict(steam_art(appid, details))
    if allow_sgdb:
        grid = sgdb_grid(appid)
        if grid:
            block["grid"] = grid           # tier 2: TILES ONLY, never OG
    return block


def og_art(verdict, appid):
    """The unfurl image URL. Tier 1 -> tier 3. CANNOT REACH TIER 2.

    Mirrors site/lib/site.ts. Kept here so the rule is testable on the Python
    side too, and so there is a second place it is written down that a reviewer
    will actually read.
    """
    header = ((verdict or {}).get("art") or {}).get("header_image")
    return header or legacy(appid)["landscape"]
