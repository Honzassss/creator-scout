# =============================================================================================
# OWNED BY KRYŠTOF. See docs/apify-pro-krystofa.md (section "Datový kontrakt s aplikací").
# This is the ONLY module in the app that may import apify_client. It maps real Apify actor
# output to the normalized models in app/models.py, with source.mode = "live" and
# source.actor = "<actor id>" on every object (including Profile.latest_posts[i].source).
# Other agents: do not edit; code against the SourceProvider protocol (app/sources/base.py).
# =============================================================================================
"""ApifyProvider: real actors -> normalized models, mode "live".

Written without a token, then checked against live runs on 9. 10. 2026 (T1-T12 of
docs/apify-pro-krystofa.md except T7, Free plan; section "Výsledky živých testů 9. 10. 2026").
Answered spots carry ``# VERIFIED LIVE 2026-10-09:``; the few still open keep ``# VERIFY LIVE:``
(grep for both). Where a shape is still unproven both variants are read and the default is None.

Layout:
- ``*_input()``  one small pure function per actor that builds the run input (explicit limits and
  the cost-trap settings from the handoff).
- ``map_*()``    pure mappers raw dataset item -> normalized model (unit-tested without a token,
  tests/test_apify_mappers.py with hand-made samples in tests/apify_samples/, shaped like live items).
- ``ApifyProvider`` orchestration: runs actors (async client; sync client in a thread as fallback),
  cost guard, minors, error items, logging. Never raises into the funnel.

Contract (sources/base.py): methods never raise; on failure return [] and
``await emit_log(why, actor=..., mode="live")``; drop minors before returning; never return
commenter identities; set Post.paid_partnership only when the actor exposes the label (else None).

Env (read at call time):
  APIFY_TOKEN            required for live calls (config.get_settings().apify_token)
  MAX_USD_PER_RUN        cost cap per actor run in USD (default 3): worst-case estimate above it -> run
                         skipped. Apify gets max_total_charge_usd = 2x that estimate + 0.05, never above
                         this cap, never below the actor minimum (tiktok-scraper 0.50)
  APIFY_PLACES           discover() also searches IG places and takes the authors of their posts (T2 + T4);
                         default ON since the Brno run of 9. 10. 2026 (a first-class path), 0 turns it off
  APIFY_IG_SEARCH        nonlive (default since the Brno run of 9. 10. 2026: full items with bio and post places)
                         | live (Instagram's own search: thin items, matches names, so Brno-named organisations)
                         | both (both sources, twice the search cost; offline replay of the saved items: live found
                         name-matched creators the non-live index did not, and vice versa)
  APIFY_TIKTOK_SEARCH    1 -> discover() runs the TikTok /user search; default OFF (Brno run 9. 10.: ~0.52 USD per
                         run, 0 survivors, non-Brno accounts and an invalid handle). TikTok profile lookups for
                         cross-platform identity (find_cross_platform) stay on.
  APIFY_POST_DETAIL      detailedData (default) | basicData   (post-scraper; basicData if music-data is charged)
  APIFY_COMMENTS_SOURCE  latest (default since T6, post-scraper latestComments, ~14x cheaper) | comments
                         (comment-scraper)
  APIFY_TIKTOK_PROXY     CZ (default, paid add-on) | None    (A/B test T9)
  APIFY_META_BRANDED     1 -> collabs() runs Meta Branded Content; default off (T8: Czech accounts give no_items)

Code constants (edit this file, they are NOT env switches): TRUST_IG_FALSE_LABEL (T6),
TRUST_TIKTOK_FALSE_LABEL (T9), TRUST_TIKTOK_REGION (T10), CITY_BBOX (T2), BRAND_WINDOW (T8).
Recommended discovery inputs: DEFAULT_KEYWORDS / DEFAULT_HASHTAGS / default_discovery_query(); the DiscoveryQuery
passed to discover() stays the source of truth (nothing is added to it silently).
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import os
import re
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.compute.minors import bio_states_minor, is_minor
from app.config import get_settings
from app.events import emit_log, tr
from app.models import (
    CandidateRef,
    CollabEvidence,
    Comment,
    DiscoveryQuery,
    NewsItem,
    Platform,
    Post,
    Profile,
    SourceRef,
    norm_handle,
    short_hash,
    utcnow,
)
from app.sources.cache import answer_is_complete, cache_key

try:  # apify-client >= 1.x ships both; 3.x is installed in backend/.venv
    from apify_client import ApifyClientAsync as _AsyncClient
except Exception:  # pragma: no cover - depends on the installed client
    _AsyncClient = None
try:
    from apify_client import ApifyClient as _SyncClient
except Exception:  # pragma: no cover
    _SyncClient = None

log = logging.getLogger("creator_scout.apify")

# ---------------------------------------------------------------------------------------------
# Actors, prices, caps
# ---------------------------------------------------------------------------------------------

ACT_IG_SEARCH = "apify/instagram-search-scraper"
ACT_IG_HASHTAG = "apify/instagram-hashtag-scraper"
ACT_IG_SCRAPER = "apify/instagram-scraper"
ACT_IG_PROFILE = "apify/instagram-profile-scraper"
ACT_IG_POST = "apify/instagram-post-scraper"
ACT_IG_COMMENT = "apify/instagram-comment-scraper"
ACT_TT = "clockworks/tiktok-scraper"
ACT_TT_PROFILE = "clockworks/tiktok-profile-scraper"
ACT_TT_COMMENTS = "clockworks/tiktok-comments-scraper"
ACT_BRAND = "apify/brand-collaboration-scraper"
ACT_NEWS = "data_xplorer/google-news-scraper-fast"
ACT_YT = "streamers/youtube-scraper"

# USD per charged unit on the FREE tier (handoff, 8. 10. 2026; Starter is 12-33 % cheaper, so these
# estimates are conservative). VERIFIED LIVE 2026-10-09: every price below matched the charged events.
PRICE_USD: dict[str, float] = {
    ACT_IG_SEARCH: 0.0027,       # per result (also liveSearch)
    ACT_IG_HASHTAG: 0.0026,      # per result
    ACT_IG_SCRAPER: 0.0027,      # per result of any type
    ACT_IG_PROFILE: 0.0026,      # per profile
    ACT_IG_POST: 0.0027,         # event post 0.0017 + post-details 0.001 (detailedData)
    ACT_IG_COMMENT: 0.0026,      # per comment
    ACT_TT: 0.0037,              # per result
    ACT_TT_PROFILE: 0.003,       # per result (video)
    ACT_TT_COMMENTS: 0.00125,    # per comment
    ACT_BRAND: 0.0058,           # per item
    ACT_NEWS: 0.004,             # per article
    ACT_YT: 0.004,               # per video (event "result"; the channel page itself is free, live T12b)
}
PRICE_IG_POST_BASIC = 0.0017     # dataDetailLevel basicData (no post-details event)
# Since 7. 10. 2026 per photo/carousel with music; the trigger is undocumented, so the worst case (every post)
# goes into the cost guard and the charge cap of every post-scraper run.
# VERIFIED LIVE 2026-10-09: 0 music-data on 24 detailedData posts (12 reels with music, 11 carousels, 1 photo).
# VERIFY LIVE: what does trigger it, and whether basicData is charged it too (not tested).
PRICE_IG_MUSIC_DATA = 0.007
PRICE_TT_PROXY_CZ = 0.0013       # proxyCountryCode CZ add-on (event scrape-as-in-country), per result
START_FEE_USD: dict[str, float] = {ACT_TT: 0.001}
# minimalMaxTotalChargeUsd. VERIFIED LIVE 2026-10-09 (GET /v2/acts): tiktok-scraper 0.50, brand-collab 0.0058,
# IG scrapers 0.0026-0.0027, none for tiktok-profile / news / youtube; our caps (>= 0.05) are always above.
MIN_CHARGE_CAP_USD: dict[str, float] = {ACT_TT: 0.50}
CHARGE_CAP_FACTOR = 2.0          # max_total_charge_usd = factor x worst-case estimate + headroom, <= MAX_USD_PER_RUN
CHARGE_CAP_HEADROOM_USD = 0.05

# Item caps (explicit everywhere: several actors have dangerous defaults).
IG_SEARCH_PER_QUERY = 25         # searchLimit (1..250)
IG_PLACE_SEARCH_PER_QUERY = 30
MAX_KEYWORDS = 4
IG_HASHTAG_PER_TAG = 50          # resultsLimit per hashtag (Free returns only the first page)
MAX_HASHTAGS = 10
MAX_LOCATION_RESOLVE = 40        # distinct locationIds resolved to coordinates per discover()
MAX_PLACES_FOR_POSTS = 10        # Brno places whose posts we read (APIFY_PLACES, default on)
PLACE_POST_MAX_AGE_DAYS = 365    # place feeds are "top" posts: 78 % of 492 nested posts in live T2 were older
# Live T1 favoured liveSearch (15/20 hits named Brno, non-live 11/40), but the Brno run of 9. 10. 2026 showed what
# those hits are: Brno-NAMED organisations (sports teams, a party, a student union, cafés), because a live item is
# thin ({username, fullName, ...}, no bio, no posts) and only the name can match the city. The non-live search costs
# the same, returns the full profile (biography, latestPosts with locationName) and lets search_user_in_city check
# the city where creators write it: in the bio and in their posts' places. Default of APIFY_IG_SEARCH.
IG_SEARCH_MODE_DEFAULT = "nonlive"
# A non-live search hit counts as in the city when at least this many of its latestPosts name the city in
# locationName ("Brno, Czech Republic", "Brno-Královo Pole"); saved T5-seed items: 9/12 and 11/11 for two Brno
# food accounts whose name and bio never say Brno.
CITY_POST_LOCATIONS_MIN = 2
TT_SEARCH_MAX_QUERIES = 3
TT_SEARCH_PROFILES = 10          # maxProfilesPerQuery
TT_SEARCH_PER_PAGE = 3           # resultsPerPage (default 1)
PROFILE_BATCH = 50               # usernames per profile-scraper run
TT_PROFILE_BATCH = 20
TT_PROFILE_VIDEOS = 12           # resultsPerPage (default 100 = 18 USD for 60 profiles!)
POSTS_MAX = 50
COMMENT_POSTS_MAX = 40
COMMENTS_PER_POST_MAX = 15       # Free returns the 15 newest anyway
BRAND_RESULTS = 20
BRAND_WINDOW = "12 months"       # VERIFIED LIVE 2026-10-09: accepted (schema pattern + nike run, 3 rows)
NEWS_MAX = 20
NEWS_TIMEFRAME = "1y"            # default 1h finds nothing
MAX_CONCURRENT_RUNS = 3
# Free plan: 5 concurrent runs per ACCOUNT (live 9. 10. 2026, parallel jobs hit "exceed your limit of 5
# concurrent Actor runs", a 4xx). apify-client 3.x retries such a start for this long instead of failing.
WAIT_FOR_RESOURCES_S = 120

RUN_TIMEOUT_S = 300
PROFILE_RUN_TIMEOUT_S = 420      # one restricted profile is retried ~10x and stalls the batch

# Brno bounding box from the handoff ("náš odhad, dolaď").
# VERIFIED LIVE 2026-10-09: T2 41 coordinate pairs, 0 false positives / 0 false negatives; unchanged.
CITY_BBOX: dict[str, tuple[float, float, float, float]] = {"brno": (49.10, 49.30, 16.45, 16.75)}

# VERIFIED LIVE 2026-10-09: authorMeta has no `region` and no `isUnderAge18` key at all (tiktok-scraper /user and
# tiktok-profile-scraper, Czech and foreign accounts, 50/50 items). Region stays out of the model; age is a gap.
TRUST_TIKTOK_REGION = False

# Paid-partnership label FALSE. compute/collabs.py turns Post.paid_partnership False into "undisclosed ad",
# so False must be a real "no label", not a field that is simply not filled. True is always kept.
# VERIFIED LIVE 2026-10-09 (T6): paidPartnership True on 3/3 Meta-branded reels, False on 21/21 Czech posts (9 with
# a caption-only #spoluprace/reklama); no Czech post WITH the label was available, so False stays unproven -> None.
# VERIFY LIVE: one Czech post with "Placené partnerství"; if it comes back True, set this True (then co-author
# posts with businesses and no caption marker, 7/12 on one Brno media account, become "undisclosed").
TRUST_IG_FALSE_LABEL = False
# VERIFIED LIVE 2026-10-09 (T9/T10): isSponsored is a bool on 46/46 videos and false on all of them; no labelled
# Czech video was seen, so a false is unproven and would turn into an undisclosed ad -> None (was True).
# VERIFY LIVE: one labelled Czech TikTok video; if it comes back true, set this True again.
TRUST_TIKTOK_FALSE_LABEL = False

PATH_ORDER = ("search", "hashtag", "place", "related", "manual")

# Instagram lets an account pin up to three posts; they lead the grid (and latestPosts) whatever their date.
MAX_PINNED = 3
# A leading post counts as pinned only when it is MORE than this older than a later post of the grid: the regular
# grid is not strictly sorted (a post dated Oct 1 may sit before one dated Oct 5), a pin is months out of order.
PIN_ORDER_SLACK = timedelta(days=7)

# TikTok usernames: letters, digits, "_" and "." only, 2-24 characters. The Brno run of 9. 10. 2026 sent "@jídlo"
# (from a /user search) to the profile scraper and paid for an INVALID_URLS item; nothing else is sent now.
TT_HANDLE_OK = re.compile(r"^[A-Za-z0-9._]{2,24}$")

# Recommended discovery inputs for a food search (Brno run of 9. 10. 2026). DiscoveryQuery stays the source of
# truth: discover() never adds these on its own; the API / rounds can start from default_discovery_query().
DEFAULT_CITY = "Brno"
DEFAULT_KEYWORDS: tuple[str, ...] = ("brno food", "brno foodie", "foodblog brno")
DEFAULT_HASHTAGS: tuple[str, ...] = ("brnofood", "foodbrno")


def default_discovery_query(city: str = DEFAULT_CITY, **overrides: Any) -> DiscoveryQuery:
    """The recommended food query for ``city``: keywords "<city> food", "<city> foodie", "foodblog <city>",
    hashtags "<city>food", "food<city>" (= DEFAULT_KEYWORDS / DEFAULT_HASHTAGS for Brno). ``overrides`` are
    DiscoveryQuery fields (platforms, limit, keywords, ...)."""
    c = " ".join((city or DEFAULT_CITY).split())
    low = c.lower()
    tag = re.sub(r"[^a-z0-9]", "", _fold(c))
    fields: dict[str, Any] = {
        "keywords": [f"{low} food", f"{low} foodie", f"foodblog {low}"],
        "hashtags": [f"{tag}food", f"food{tag}"] if tag else [],
        "places": [c],
        "city": c,
    }
    fields.update(overrides)
    return DiscoveryQuery(**fields)


def max_usd_per_run() -> float:
    try:
        v = float((os.environ.get("MAX_USD_PER_RUN") or "").strip() or 3.0)
    except ValueError:
        v = 3.0
    return max(0.0, v)


def _env_flag(name: str, default: bool = False) -> bool:
    """1/true/yes/on -> True, 0/false/no/off -> False, unset or anything else -> ``default``."""
    v = (os.environ.get(name) or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def places_enabled() -> bool:
    """APIFY_PLACES, default on: the place-author path (search-scraper places -> posts[].user.username)."""
    return _env_flag("APIFY_PLACES", True)


def ig_search_live_modes() -> tuple[bool, ...]:
    """APIFY_IG_SEARCH: nonlive (default) -> (False,), live -> (True,), both -> (False, True)."""
    mode = _env_choice("APIFY_IG_SEARCH", ("nonlive", "live", "both"), IG_SEARCH_MODE_DEFAULT)
    return {"nonlive": (False,), "live": (True,), "both": (False, True)}[mode]


def tiktok_search_enabled() -> bool:
    """APIFY_TIKTOK_SEARCH, default off: the TikTok /user search in discover()."""
    return _env_flag("APIFY_TIKTOK_SEARCH", False)


def discover_variant() -> str | None:
    """The discovery switches that differ from their defaults, for discover()'s cache key ("ig_search=live,
    places=off"); None with all defaults, so default keys stay those of older caches."""
    parts = []
    mode = _env_choice("APIFY_IG_SEARCH", ("nonlive", "live", "both"), IG_SEARCH_MODE_DEFAULT)
    if mode != IG_SEARCH_MODE_DEFAULT:
        parts.append(f"ig_search={mode}")
    if not places_enabled():
        parts.append("places=off")
    if tiktok_search_enabled():
        parts.append("tiktok_search=on")
    return ",".join(parts) or None


def valid_tiktok_handle(handle: str | None) -> bool:
    return bool(handle) and bool(TT_HANDLE_OK.match(norm_handle(handle or "")))


def _env_choice(name: str, choices: tuple[str, ...], default: str) -> str:
    v = (os.environ.get(name) or "").strip()
    for c in choices:
        if v.lower() == c.lower():
            return c
    return default


def post_detail_level() -> str:
    return _env_choice("APIFY_POST_DETAIL", ("detailedData", "basicData"), "detailedData")


def comments_source() -> str:
    # VERIFIED LIVE 2026-10-09 (T6): latestComments carry `text` + `timestamp`, up to 15 per post (= the
    # comment-scraper's Free limit), so the post-scraper is the default; T7 (comment-scraper) was not needed.
    return _env_choice("APIFY_COMMENTS_SOURCE", ("comments", "latest"), "latest")


def tiktok_proxy() -> str:
    return _env_choice("APIFY_TIKTOK_PROXY", ("CZ", "None"), "CZ")


def estimate_usd(actor: str, units: int, *, per_unit: float | None = None) -> float:
    """Estimated charge: units x price (+ start fee). ``per_unit`` overrides the table price."""
    price = PRICE_USD.get(actor, 0.005) if per_unit is None else per_unit
    return round(max(0, units) * price + START_FEE_USD.get(actor, 0.0), 4)


def charge_cap_usd(actor: str, worst_usd: float, cap: float) -> float:
    """max_total_charge_usd sent to Apify: about twice the worst-case estimate (+0.05 USD), never above
    MAX_USD_PER_RUN, never below the actor's minimalMaxTotalChargeUsd (Apify refuses a lower cap)."""
    want = round(CHARGE_CAP_FACTOR * max(0.0, worst_usd) + CHARGE_CAP_HEADROOM_USD, 2)
    return round(max(min(cap, want), MIN_CHARGE_CAP_USD.get(actor, 0.0)), 2)


# ---------------------------------------------------------------------------------------------
# Run inputs (pure; exact parameter names from the handoff)
# ---------------------------------------------------------------------------------------------


def _clean_query(q: str) -> str:
    return " ".join((q or "").replace(",", " ").split())


def ig_search_input(queries: list[str], search_type: str, limit: int, *, live: bool = False) -> dict:
    """apify/instagram-search-scraper. ``search`` is ONE text, a comma separates queries; the
    default searchType is "place", so always set it. ``live`` (users only): Instagram's own search,
    items are {username, fullName, id, private, verified, url, profilePicUrl, latestMedia} only (no
    followers, bio, latestPosts, searchSource, searchTerm); event live-search-result, same 0.0027 USD.
    Live place items carry the location id in ``id``, not ``location_id`` (live T2), so never live for places."""
    out = {
        "search": ", ".join(_clean_query(q) for q in queries if _clean_query(q)),
        "searchType": search_type,
        "searchLimit": max(1, min(250, int(limit))),
        "enhanceUserSearchWithFacebookPage": False,   # hidden; adds business e-mails, keep off
    }
    if live and search_type == "user":
        out["liveSearch"] = True
    return out


def ig_hashtag_input(tags: list[str], limit: int) -> dict:
    """apify/instagram-hashtag-scraper: newest posts only; keywordSearch off (it adds latestComments)."""
    return {
        "hashtags": [norm_handle(t) for t in tags if norm_handle(t)],
        "resultsType": "posts",
        "resultsLimit": max(1, int(limit)),
        "keywordSearch": False,
    }


def ig_location_url(location_id: str) -> str:
    return f"https://www.instagram.com/explore/locations/{location_id}/"


def ig_location_input(location_ids: list[str], results_type: str, limit: int) -> dict:
    """apify/instagram-scraper with place URLs. Live T4: for "posts" and "details" alike a place URL
    returns ONE place item (location_id, name, lat, lng, location_address, location_city, ig_business,
    15-18 nested raw IG posts with user.username / taken_at), charged 1 result per place whatever
    resultsLimit says; never post items. inputUrl echoed the input in 7/7, still pair by location_id."""
    return {
        "directUrls": [ig_location_url(i) for i in location_ids],
        "resultsType": results_type,
        "resultsLimit": max(1, int(limit)),
    }


def ig_profile_input(handles: list[str]) -> dict:
    """apify/instagram-profile-scraper; includeAboutSection is paid-plan only (+0.006 USD)."""
    return {"usernames": [norm_handle(h) for h in handles if norm_handle(h)], "includeAboutSection": False}


def ig_post_input(targets: list[str], limit: int, detail: str = "detailedData", *, skip_pinned: bool = True) -> dict:
    """apify/instagram-post-scraper. dataDetailLevel defaults to detailedData in the API, so always
    set it. onlyPostsNewerThan is NOT sent (open bug: returns too few posts after a grid reorder);
    the date is filtered in code. ``skip_pinned`` False for direct post URLs (a pinned post we asked
    for must not be skipped)."""
    return {
        "username": list(targets),
        "resultsLimit": max(1, int(limit)),
        "skipPinnedPosts": bool(skip_pinned),
        "dataDetailLevel": detail,
    }


def ig_comment_input(post_urls: list[str], per_post: int) -> dict:
    """apify/instagram-comment-scraper (includeNestedComments is paid-only, not sent)."""
    return {"directUrls": list(post_urls), "resultsLimit": max(1, int(per_post))}


def tt_search_input(query: str, *, max_profiles: int = TT_SEARCH_PROFILES, per_page: int = TT_SEARCH_PER_PAGE,
                    proxy: str = "CZ") -> dict:
    """clockworks/tiktok-scraper user search. resultsPerPage defaults to 1, always set it."""
    out: dict[str, Any] = {
        "searchQueries": [_clean_query(query)],
        "searchSection": "/user",
        "maxProfilesPerQuery": max(1, int(max_profiles)),
        "resultsPerPage": max(1, int(per_page)),
    }
    if proxy and proxy != "None":
        out["proxyCountryCode"] = proxy   # paid add-on (+0.0013 USD per result on Free)
    return out


def tt_profile_input(handles: list[str], per_page: int = TT_PROFILE_VIDEOS) -> dict:
    """clockworks/tiktok-profile-scraper. resultsPerPage defaults to 100 (cost trap), set 12."""
    return {
        "profiles": [norm_handle(h) for h in handles if norm_handle(h)],
        "resultsPerPage": max(1, int(per_page)),
        "excludePinnedPosts": True,
    }


def tt_comments_input(post_urls: list[str], per_post: int) -> dict:
    """clockworks/tiktok-comments-scraper. commentsPerPost has no default in the schema."""
    return {"postURLs": list(post_urls), "commentsPerPost": max(1, int(per_post)), "maxRepliesPerComment": 0}


def ig_profile_url(handle: str) -> str:
    return f"https://www.instagram.com/{norm_handle(handle)}/"


def tt_profile_url(handle: str) -> str:
    return f"https://www.tiktok.com/@{norm_handle(handle)}"


def brand_collab_input(profile_url: str, limit: int = BRAND_RESULTS, window: str = BRAND_WINDOW) -> dict:
    """apify/brand-collaboration-scraper. resultsLimit empty = unlimited, always set; with a profile
    URL onlyPostsNewerThan is required by the schema."""
    return {"startUrls": [profile_url], "resultsLimit": max(1, int(limit)), "onlyPostsNewerThan": window}


def news_input(query: str, region: str = "CZ", lang: str = "cs", limit: int = 10) -> dict:
    """data_xplorer/google-news-scraper-fast. Defaults are traps: timeframe 1h, maxArticles 100,
    decodeUrls false, extractImages true."""
    return {
        "keywords": [" ".join((query or "").split())],
        "region_language": f"{(region or 'CZ').upper()}:{(lang or 'cs').lower()}",
        "timeframe": NEWS_TIMEFRAME,
        "maxArticles": max(1, min(NEWS_MAX, int(limit))),
        "decodeUrls": True,
        "extractImages": False,
    }


def yt_channel_input(handle: str, limit: int) -> dict:
    """streamers/youtube-scraper on a channel URL. Live T12b: isPaidContent (bool) and channelLocation are filled
    in channel mode (channelLocation is missing for /watch URLs); maxResults default 0 = everything, Shorts and
    streams off. 0.004 USD per video, nothing for the channel page."""
    return {"startUrls": [{"url": f"https://www.youtube.com/@{norm_handle(handle)}"}],
            "maxResults": max(1, int(limit)), "maxResultsShorts": 0, "maxResultStreams": 0}


# ---------------------------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------------------------


def _fold(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _get(d: Any, *path: str) -> Any:
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _str(v: Any) -> str | None:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return None


def _count(v: Any) -> int | None:
    """Non-negative int or None. Hidden likes come as null or -1 -> None (excluded from medians)."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def _float(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_ts(v: Any) -> datetime | None:
    """ISO string (with Z), YYYY-MM-DD, or epoch seconds / milliseconds -> aware UTC datetime."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{9,13}", v.strip())):
        try:
            x = float(v)
            if x > 1e12:
                x /= 1000.0
            return datetime.fromtimestamp(x, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


# Error items that ARE the answer (the account does not exist / is private). A run that returned nothing but OTHER
# error items (IG no_items "Empty or private data", TikTok PROFILE_EMPTY = gap or login wall, INVALID_URLS, ...)
# is a failed fetch: _run notes it, so CachedProvider never stores its [] as a real empty answer.
ANSWER_ERRORS = frozenset({"not_found", "PROFILE_PRIVATE"})


def error_of(item: Any) -> str | None:
    """Error items: IG ``error`` / ``errorDescription``, TikTok ``errorCode``, YouTube ``error``."""
    if not isinstance(item, dict):
        return "not an object"
    for k in ("errorCode", "error", "errorDescription"):
        v = item.get(k)
        if v:
            return str(v) if not isinstance(v, (dict, list)) else k
    return None


def _handles(values: Any, key: str = "username") -> list[str]:
    """List of strings or of objects with ``key`` -> handles."""
    out: list[str] = []
    if not isinstance(values, list):
        return out
    for v in values:
        h = v if isinstance(v, str) else (v.get(key) if isinstance(v, dict) else None)
        if isinstance(h, str) and norm_handle(h):
            out.append(norm_handle(h))
    return out


def _strings(values: Any) -> list[str]:
    return [v for v in values if isinstance(v, str) and v.strip()] if isinstance(values, list) else []


# Caption fallbacks. A hashtag has no "." on IG or TikTok ("#brno_food." -> "brno_food"); a handle may
# contain dots but never ends with one ("@anna.k." -> "anna.k"). A mention never follows a word character or a dot:
# "objednavky@sample-bistro.cz" is an e-mail address, not a mention of @sample-bistro.cz (Brno run 9. 10. 2026:
# the profile scraper sends mentions [] for such a caption, and the caption fallback used to invent the handle).
_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
_MENTION_RE = re.compile(r"(?<![\w.])@(\w(?:[\w.]*\w)?)", re.UNICODE)
_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", re.UNICODE)
# Masking comment texts (privacy, not mention detection): EVERY "@handle" left after the e-mail pass, with no
# lookbehind, so "díky@sample_jana" and "wow!!.@sample_petr" lose the handle too.
_MASK_AT_RE = re.compile(r"@(\w(?:[\w.]*\w)?)", re.UNICODE)
_IG_SHORTCODE_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)
_TT_VIDEO_RE = re.compile(r"tiktok\.com/@([\w.]+)/(?:video|photo)/(\d+)", re.I)
_TT_HANDLE_RE = re.compile(r"tiktok\.com/@([\w.]+)", re.I)
_IG_LINK_RE = re.compile(r"instagram\.com/((?:_u/|_n/)?[A-Za-z0-9._]{1,30})", re.I)
_YT_LINK_RE = re.compile(r"youtube\.com/@([A-Za-z0-9._-]{3,30})", re.I)
# "TikTok: @anna", "IG @anna", "YT: @anna" in a bio (a link without a URL). The platform word and the "@" must be
# separated (space or ":", "-", "|"): "ig@cafe.cz" / "yt@studio.cz" are e-mail addresses, not handles.
_PLATFORM_AT_RE = re.compile(
    r"(?<![\w])(tiktok|tik tok|tt|instagram|insta|ig|youtube|yt)(?:\s*[:\-–|]\s*|\s+)@([\w.]{2,30})", re.I)
_PLATFORM_WORD = {"tiktok": "tiktok", "tik tok": "tiktok", "tt": "tiktok", "instagram": "instagram", "insta": "instagram",
                  "ig": "instagram", "youtube": "youtube", "yt": "youtube"}
_IG_NON_PROFILE = {"p", "reel", "reels", "explore", "stories", "tv", "accounts", "direct", "about", "legal", "_u", "_n"}


def ig_shortcode(url: str | None) -> str | None:
    m = _IG_SHORTCODE_RE.search(url or "")
    return m.group(1) if m else None


def tt_video_ref(url: str | None) -> tuple[str, str] | None:
    """(handle, video_id) from a TikTok video URL."""
    m = _TT_VIDEO_RE.search(url or "")
    return (norm_handle(m.group(1)), m.group(2)) if m else None


def ig_handle_from_link(link: str | None) -> str | None:
    """Profile handle from an instagram.com link; strips /_u/ and /_n/, skips p / reel / explore."""
    m = _IG_LINK_RE.search(link or "")
    if not m:
        return None
    path = m.group(1)
    for pre in ("_u/", "_n/"):
        if path.lower().startswith(pre):
            path = path[len(pre):]
    h = norm_handle(path.strip("/."))
    return h if h and h not in _IG_NON_PROFILE else None


# Verified authorMeta texts that point at OTHER accounts as often as at the author (bio, bio link).
_TT_BIO_KEYS = frozenset({"signature", "bioLink"})


def _scan_tiktok_handle(item: Any) -> str | None:
    """The item's own TikTok handle: ``webVideoUrl``, then ``authorMeta.profileUrl`` / ``authorMeta.name``.
    VERIFIED LIVE 2026-10-09 (T9): /user items are the found profiles' VIDEOS (each with full authorMeta) plus one
    "note" item per profile without videos; authorMeta.profileUrl is https://www.tiktok.com/@<handle> and
    authorMeta.name the bare handle (44/44 resolved). Fallback for other shapes (error items): every other
    string value at the top level and in authorMeta is pattern-matched for tiktok.com/@handle, skipping the
    bio fields, and accepted only when exactly one distinct handle is found (a friend's link must not win)."""
    if not isinstance(item, dict):
        return None
    vid = tt_video_ref(_str(item.get("webVideoUrl")))
    if vid:
        return vid[0]
    meta = _tt_author_meta(item)
    m = _TT_HANDLE_RE.search(_str(meta.get("profileUrl")) or "")
    if m and norm_handle(m.group(1).rstrip(".")):
        return norm_handle(m.group(1).rstrip("."))
    if _str(meta.get("name")):
        return norm_handle(_str(meta.get("name")))
    found: set[str] = set()
    for d in (item, meta):
        for k, v in d.items():
            if k in _TT_BIO_KEYS or not isinstance(v, str):
                continue
            for m in _TT_HANDLE_RE.finditer(v):
                h = norm_handle(m.group(1).rstrip("."))
                if h:
                    found.add(h)
    return next(iter(found)) if len(found) == 1 else None


def _business_category(v: Any) -> str | None:
    """'None,Candy Store' -> 'Candy Store' (split on commas, drop 'None')."""
    if not isinstance(v, str):
        return None
    parts = [p.strip() for p in v.split(",") if p.strip() and p.strip().lower() != "none"]
    return ", ".join(dict.fromkeys(parts)) or None


_NAIVE_AT_RE = re.compile(r"@([\w.]+)", re.UNICODE)


def email_handle_lookalikes(text: str | None) -> set[str]:
    """What a naive "@handle" scan would take from the e-mail addresses in ``text``: the domain, what a
    word-character scan stops at ("info@sample-shop.cz" -> sample) and every dotted prefix of those
    ("info@sample.shop.cz" -> sample.shop.cz, sample.shop, sample)."""
    text = text or ""
    out: set[str] = set()
    for m in _EMAIL_RE.finditer(text):
        found = {m.group(1)}
        naive = _NAIVE_AT_RE.match(text, m.start(1) - 1)   # m.start(1) - 1 is the "@"
        if naive:
            found.add(naive.group(1))
        for f in found:
            labels = f.lower().strip(".").split(".")
            out.update(".".join(labels[:i]) for i in range(1, len(labels) + 1))
    return {norm_handle(x) for x in out if x}


def caption_mentions(caption: str | None, listed: Iterable[str] = ()) -> list[str]:
    """Mentions of a post: the actor's list when it has one, else the caption scan. Either way a handle that the
    caption only contains as part of an e-mail address is dropped (it is never a mention or a brand handle)."""
    text = caption or ""
    proper = [norm_handle(t) for t in _MENTION_RE.findall(text)]
    given = [norm_handle(h) for h in listed if norm_handle(h)]
    if not given:
        return list(dict.fromkeys(proper))
    fake = email_handle_lookalikes(text) - set(proper)
    return list(dict.fromkeys(h for h in given if h not in fake))


def mask_mentions(text: str) -> str:
    """Third-party @handles inside comment texts -> '@user' and e-mail addresses -> '[e-mail]' (identity never
    stored; a tag-only comment stays recognizably tag-only for compute.language)."""
    return _MASK_AT_RE.sub("@user", _EMAIL_RE.sub("[e-mail]", text or ""))


def mark_leading_pinned(posts: list[Post]) -> list[Post]:
    """Profile grid order -> pinned posts marked ``is_pinned=True`` where the actor gives no flag.

    Brno run of 9. 10. 2026: profile-scraper latestPosts carry isPinned only on pinned posts the account OWNS
    (absent otherwise); a pinned collab post owned by the partner comes without it, and Instagram lists pinned
    posts first, so an old one stretched the activity window (7 posts in 2 weeks scored 0.2 per week).
    Among the first MAX_PINNED posts (the scan stops at an explicit False): an unflagged post more than
    PIN_ORDER_SLACK older than some later post of the list is pinned. An in-order post does not end the scan, an
    old pin may sit behind a newer one (cached Brno profile: [2024-07, 2026-09, 2026-01, 2026-06, ...]). Pins are a
    prefix, so every unflagged post before the last pinned one (explicit or inferred) is pinned too. An explicit
    flag (True or False) is never changed; applying the rule twice gives the same result."""
    out = list(posts)
    head = min(MAX_PINNED, len(out))
    pinned = [p.is_pinned is True for p in out[:head]]
    for i in range(head):
        p = out[i]
        if p.is_pinned is False:
            break
        if p.is_pinned is None and any(q.created_at > p.created_at + PIN_ORDER_SLACK for q in out[i + 1:]):
            pinned[i] = True
    last = max((i for i in range(head) if pinned[i]), default=-1)
    for i in range(last + 1):
        if out[i].is_pinned is None:
            out[i] = out[i].model_copy(update={"is_pinned": True})
    return out


def in_city_bbox(city: str | None, lat: float | None, lng: float | None) -> bool | None:
    """True / False when the city has a known box and both coordinates exist, else None."""
    box = CITY_BBOX.get(_fold(city).strip()) if city else None
    if box is None or lat is None or lng is None:
        return None
    lat_min, lat_max, lng_min, lng_max = box
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


def city_text_match(city: str | None, text: str | None) -> bool:
    if not city or not text:
        return False
    from app.compute.metrics import city_pattern  # lazy: metrics pulls in the language module

    pat = city_pattern(city)
    return bool(pat and pat.search(_fold(text)))


def raw_minor(item: dict, platform: str) -> bool:
    """Minor rule from the handoff on a RAW item: explicit bio age under 18 (compute.minors) or
    TikTok authorMeta.isUnderAge18 true. Missing age = unknown, never a reason to keep or drop."""
    if platform == "tiktok":
        meta = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else item
        if _bool(meta.get("isUnderAge18")) is True:
            return True
        return bio_states_minor(_str(meta.get("signature")))
    return bio_states_minor(_str(item.get("biography")))


def _src(*, id: str, url: str, platform: Platform, actor: str, fetched_at: datetime, quote: str | None = None) -> SourceRef:
    return SourceRef(id=id, url=url, platform=platform, actor=actor, fetched_at=fetched_at, mode="live", quote=quote)


# ---------------------------------------------------------------------------------------------
# Mappers: Instagram (pure)
# ---------------------------------------------------------------------------------------------

_IG_TYPE = {"image": "photo", "photo": "photo", "graphimage": "photo", "video": "video", "graphvideo": "video",
            "sidecar": "carousel", "carousel": "carousel", "graphsidecar": "carousel"}


def _ig_media_type(item: dict) -> str:
    # productType "clips" = reel (verified); there is no isReel flag. For photos productType is missing.
    if _str(item.get("productType")) == "clips":
        return "reel"
    # VERIFIED LIVE 2026-10-09: type = Image / Video / Sidecar in all IG actors (hashtag-scraper too); productType
    # clips / carousel_container / carousel_item / feed / igtv or missing (T1 447, T3 36, T5 84, T6 24: all mapped).
    return _IG_TYPE.get(_fold(_str(item.get("type")) or "").replace("_", ""), "other")


def map_ig_post(item: dict, *, actor: str, fetched_at: datetime, default_author: str | None = None,
                trust_false_label: bool = False) -> Post | None:
    """IG post from the post-scraper, hashtag-scraper, profile-scraper latestPosts or instagram-scraper.

    paid_partnership: True is always taken, False only when ``trust_false_label`` (the provider passes
    post-scraper detailedData AND TRUST_IG_FALSE_LABEL); otherwise None (missing is not false). Live 9. 10.:
    post-scraper True on 3/3 labelled reels; hashtag-scraper False on 35/36 even under #spoluprace; profile
    latestPosts never carry it (0/84)."""
    if not isinstance(item, dict) or error_of(item):
        return None
    code = _str(item.get("shortCode")) or ig_shortcode(_str(item.get("url")))
    url = _str(item.get("url")) or (f"https://www.instagram.com/p/{code}/" if code else None)
    author = norm_handle(_str(item.get("ownerUsername")) or default_author or "")
    created = parse_ts(item.get("timestamp"))
    if not url or not author or created is None:
        return None
    pid = f"ig:post:{code}" if code else f"ig:post:{short_hash(url)}"
    caption = _str(item.get("caption")) or ""
    label = _bool(item.get("paidPartnership"))
    if label is False and not trust_false_label:
        label = None
    hashtags = _handles(item.get("hashtags")) or [norm_handle(t) for t in _HASHTAG_RE.findall(caption)]
    mentions = caption_mentions(caption, _handles(item.get("mentions")))   # never an e-mail domain
    return Post(
        id=pid,
        platform="instagram",
        url=url,
        author_handle=author,
        created_at=created,
        caption=caption,
        hashtags=hashtags,
        mentions=mentions,
        coauthors=_handles(item.get("coauthorProducers")),     # objects {id, username, is_verified, ...}
        # VERIFIED LIVE 2026-10-09: taggedUsers items are {username, full_name, id, is_verified, profile_pic_url}.
        tagged_users=_handles(item.get("taggedUsers")),
        media_type=_ig_media_type(item),  # type: ignore[arg-type]
        likes=_count(item.get("likesCount")),   # post-scraper username mode: -1 on 11/12 -> None (T6)
        comments=_count(item.get("commentsCount")),
        # VERIFIED LIVE 2026-10-09: profile-scraper latestPosts have videoViewCount on 52/52 reels; post-scraper 6/12
        # (null for URL inputs). videoPlayCount counts plays (2-6x higher), so it is not mixed in.
        views=_count(item.get("videoViewCount")),
        location_name=_str(item.get("locationName")),
        location_id=_str(item.get("locationId")),
        paid_partnership=label,
        # live: present only when true; map_ig_profile infers the unflagged pins from the grid order
        is_pinned=_bool(item.get("isPinned")),
        # VERIFIED LIVE 2026-10-09: sponsors (and affiliate) never appear, even on labelled posts: always [].
        sponsors=_handles(item.get("sponsors")),
        language=None,
        source=_src(id=pid, url=url, platform="instagram", actor=actor, fetched_at=fetched_at),
    )


def _external_urls(item: dict) -> list[str]:
    urls: list[str] = []
    one = _str(item.get("externalUrl"))
    if one:
        urls.append(one)
    for e in item.get("externalUrls") or []:
        u = _str(e.get("url")) if isinstance(e, dict) else _str(e)   # lynx_url is IG's redirect wrapper: skip
        if u:
            urls.append(u)
    return list(dict.fromkeys(urls))


def ig_profile_handle(item: dict, requested: Iterable[str] = ()) -> str | None:
    """Handle of a profile-scraper item.

    VERIFIED LIVE 2026-10-09 (T5, T1): ``username`` is on 9/9 profile-scraper items (error items included) and
    on every search-scraper item. The fallbacks stay as a guard: the most common ``latestPosts[].ownerUsername``,
    preferring one we asked for (a collab post can be owned by the partner, 6/84 live); only when no post names
    an owner, the requested handle if exactly one was requested."""
    h = norm_handle(_str(item.get("username")) or "")
    if h:
        return h
    wanted = list(dict.fromkeys(norm_handle(r) for r in requested if norm_handle(r)))
    owners = Counter(o for o in (norm_handle(_str(p.get("ownerUsername")) or "")
                                 for p in (item.get("latestPosts") or []) if isinstance(p, dict)) if o)
    for o, _ in owners.most_common():
        if o in wanted:
            return o
    if owners:
        return owners.most_common(1)[0][0]   # e.g. renamed: comes back under the new name, as with username
    return wanted[0] if len(wanted) == 1 else None


def map_ig_profile(item: dict, *, actor: str, fetched_at: datetime, requested: Iterable[str] = ()) -> Profile | None:
    """IG profile from the profile-scraper (also search-scraper user items: same field names).
    ``requested`` = the usernames of that run (handle fallback, see ig_profile_handle).
    is_under_18 stays None (Instagram exposes no age); the provider drops bio-stated minors."""
    if not isinstance(item, dict) or error_of(item):
        return None
    handle = ig_profile_handle(item, requested)
    if not handle:
        return None
    url = ig_profile_url(handle)
    bio = _str(item.get("biography")) or ""
    posts: list[Post] = []
    for x in item.get("latestPosts") or []:
        p = map_ig_post(x, actor=actor, fetched_at=fetched_at, default_author=handle) if isinstance(x, dict) else None
        if p is None:
            continue
        # Live T5: a collab post owned by the partner (ownerUsername != username, 6/84) sits in this profile's grid,
        # and latestPosts carry no coauthorProducers: record the profile as co-author so it reads as a collab.
        if p.author_handle != handle and handle not in p.coauthors:
            p = p.model_copy(update={"coauthors": [*p.coauthors, handle]})
        posts.append(p)
    posts = mark_leading_pinned(posts)   # latestPosts keep the grid order: pinned posts lead it
    about = item.get("about") if isinstance(item.get("about"), dict) else {}
    return Profile(
        handle=handle,
        platform="instagram",
        url=url,
        # VERIFIED LIVE 2026-10-09: fullName on 7/7 profile-scraper profiles and 40/40 search items; "" on 1/7.
        display_name=_str(item.get("fullName")) or "",
        bio=bio,
        followers=_count(item.get("followersCount")),
        following=_count(item.get("followsCount")),
        posts_count=_count(item.get("postsCount")),
        verified=_bool(item.get("verified")),
        private=_bool(item.get("private")),
        is_business=_bool(item.get("isBusinessAccount")),
        business_category=_business_category(item.get("businessCategoryName")),
        external_urls=_external_urls(item),
        related_handles=_handles(item.get("relatedProfiles")),    # snake_case items {username, full_name, ...}
        region=None,
        is_under_18=None,
        # VERIFY LIVE: renamed accounts (not tested on 9. 10.). If an item carries the requested username (e.g. an
        # input field), put it into former_handles so CachedProvider / round 1 can match the old handle.
        former_handles=[],
        former_handles_count=_count(about.get("former_usernames")),   # only with includeAboutSection (paid)
        latest_posts=posts,
        source=_src(id=f"ig:profile:{handle}", url=url, platform="instagram", actor=actor, fetched_at=fetched_at,
                    quote=bio[:200] or None),
    )


def map_ig_search_user(item: dict, *, query: str, actor: str, fetched_at: datetime) -> CandidateRef | None:
    """search-scraper searchType=user item -> CandidateRef found_via "search:<query>"."""
    if not isinstance(item, dict) or error_of(item):
        return None
    handle = norm_handle(_str(item.get("username")) or "")
    if not handle:
        return None
    via = f"search:{_clean_query(query)}"
    quote = via
    if _str(item.get("searchSource")):
        quote += f" ({item['searchSource']})"
    return CandidateRef(handle=handle, platform="instagram", found_via=[via],
                        source=_src(id=f"disc:ig:{handle}:search:{short_hash(via, 6)}", url=ig_profile_url(handle),
                                    platform="instagram", actor=actor, fetched_at=fetched_at, quote=quote))


def map_ig_related(item: dict, *, actor: str, fetched_at: datetime) -> list[CandidateRef]:
    """relatedProfiles of a found account -> CandidateRef found_via "related:@<source>" (public only).
    VERIFIED LIVE 2026-10-09: effectively dead for local accounts. [] on 38/40 + 27/27 search items and 7/7 + 18/18
    profiles (33 to 71.7k followers); only two off-topic mega accounts had 50 each (snake_case items, parsed, junk)."""
    if not isinstance(item, dict) or error_of(item):
        return []
    src_handle = norm_handle(_str(item.get("username")) or "")
    out: list[CandidateRef] = []
    for r in item.get("relatedProfiles") or []:
        if not isinstance(r, dict) or _bool(r.get("is_private")) is True:
            continue
        h = norm_handle(_str(r.get("username")) or "")
        if not h or h == src_handle:
            continue
        via = f"related:@{src_handle}"
        out.append(CandidateRef(handle=h, platform="instagram", found_via=[via],
                                source=_src(id=f"disc:ig:{h}:related:{src_handle}", url=ig_profile_url(h),
                                            platform="instagram", actor=actor, fetched_at=fetched_at, quote=via)))
    return out


def search_user_city_evidence(city: str | None, item: dict) -> str | None:
    """Why a search hit counts as in ``city``: "name" (username / fullName; "foodiesbrno" needs the substring),
    "bio" (biography), "posts" (at least CITY_POST_LOCATIONS_MIN latestPosts name the city in locationName;
    non-live items only), "no_city" (no city asked), or None. A liveSearch item has only username and fullName,
    so for it only "name" can match: that is why the Brno run kept Brno-named organisations and the non-live
    search is the default (APIFY_IG_SEARCH)."""
    if not city:
        return "no_city"
    names = " ".join(filter(None, (_str(item.get("username")), _str(item.get("fullName")))))
    if city_text_match(city, names) or _fold(city).strip() in _fold(_str(item.get("username"))):
        return "name"
    if city_text_match(city, _str(item.get("biography"))):
        return "bio"
    posts = item.get("latestPosts")
    if isinstance(posts, list):
        n = sum(1 for p in posts if isinstance(p, dict) and city_text_match(city, _str(p.get("locationName"))))
        if n >= CITY_POST_LOCATIONS_MIN:
            return "posts"
    return None


def search_user_in_city(city: str | None, item: dict) -> bool:
    """Live T1: the 29 google/threads hits for "cukrárna brno" / "brno food" were all off-topic (fuzzy
    "bruno", foreign accounts, two with 2.9M / 19M followers and 50 relatedProfiles each); every
    relevant hit names the city in username, fullName or biography, or tags its posts there
    (search_user_city_evidence)."""
    return search_user_city_evidence(city, item) is not None


@dataclass
class PlaceInfo:
    location_id: str
    name: str | None = None
    lat: float | None = None
    lng: float | None = None
    city: str | None = None
    authors: list[str] = field(default_factory=list)
    business_handle: str | None = None


def map_ig_place(item: dict, *, now: datetime | None = None) -> PlaceInfo | None:
    """Place item from search-scraper (searchType=place) or instagram-scraper (place URL).
    VERIFIED LIVE 2026-10-09 (T2, T4): both actors give the same shape {location_id, name, slug, lat, lng, category,
    location_address, location_city (4/42 filled), ig_business.profile.username (12/42), posts}; there is no
    `address` and no `city` key. ``posts`` is a list of raw IG media objects (author in user.username, time in
    taken_at, epoch s) or missing (9/42). liveSearch place items carry the id in ``id`` and a `city` (1/30 filled).
    "City directory" items (location_list, no location_id) and post-shaped items are NOT places: None.
    ``now``: drop nested posts older than PLACE_POST_MAX_AGE_DAYS (top posts, mostly stale). The venue's own
    account (ig_business) is not counted as an author."""
    if not isinstance(item, dict) or error_of(item):
        return None
    loc_id = _str(item.get("location_id"))
    if not loc_id and "lat" in item and not any(item.get(k) for k in ("ownerUsername", "shortCode", "username")):
        loc_id = _str(item.get("id"))   # liveSearch place item {id, name, lat, lng, city, address, shortName}
    if not loc_id:
        return None
    biz = _str(_get(item, "ig_business", "profile", "username"))
    biz_h = norm_handle(biz) if biz else None
    authors: list[str] = []
    nested = item.get("posts")
    cutoff = now - timedelta(days=PLACE_POST_MAX_AGE_DAYS) if now else None
    if isinstance(nested, list):
        for p in nested:
            if isinstance(p, dict):
                ts = parse_ts(p.get("taken_at")) or parse_ts(p.get("timestamp"))
                if cutoff and ts and ts < cutoff:
                    continue
                h = norm_handle(_str(_get(p, "user", "username")) or _str(p.get("username"))
                                or _str(p.get("ownerUsername")) or "")
                if h and h != biz_h and h not in authors:
                    authors.append(h)
    return PlaceInfo(
        location_id=loc_id,
        name=_str(item.get("name")),   # live: filled in 42/42 search-scraper and 7/7 instagram-scraper places
        lat=_float(item.get("lat")),
        lng=_float(item.get("lng")),
        city=_str(item.get("city")) or _str(item.get("location_city")),
        authors=authors,
        business_handle=biz_h,
    )


def place_verdict(*, city: str | None, location_id: str | None, location_name: str | None,
                  coords: dict[str, tuple[float | None, float | None]], city_location_ids: set[str]) -> str:
    """'in' | 'out' | 'unknown' for one post. Only coordinates can say 'out' (a business name such as
    "Café XY" does not contain the word Brno, so text can only confirm, never reject)."""
    if not city:
        return "unknown"
    if location_id and location_id in city_location_ids:
        return "in"
    if location_id and location_id in coords:
        inside = in_city_bbox(city, *coords[location_id])
        if inside is not None:
            return "in" if inside else "out"
    if city_text_match(city, location_name):
        return "in"
    return "unknown"


def map_ig_comment(item: dict, *, actor: str, fetched_at: datetime, index: int,
                   post_url: str | None = None) -> Comment | None:
    """comment-scraper item -> Comment. Reads ONLY text / timestamp / postUrl; ownerUsername, owner,
    ownerProfilePicUrl, id and commentUrl are never read (the SourceRef points at the post)."""
    if not isinstance(item, dict) or error_of(item):
        return None
    text = _str(item.get("text"))
    url = post_url or _str(item.get("postUrl"))
    if not text or not url:
        return None
    code = ig_shortcode(url) or short_hash(url)
    return Comment(post_url=url, text=mask_mentions(text), created_at=parse_ts(item.get("timestamp")),
                   source=_src(id=f"ig:comment:{code}:{index}", url=url, platform="instagram", actor=actor,
                               fetched_at=fetched_at))


def map_ig_latest_comments(post_item: dict, *, actor: str, fetched_at: datetime, per_post: int,
                           post_url: str | None = None) -> list[Comment]:
    """post-scraper detailedData ``latestComments`` (texts only) -> Comments of that post."""
    if not isinstance(post_item, dict) or error_of(post_item):
        return []
    url = post_url or _str(post_item.get("url"))
    if not url:
        return []
    out: list[Comment] = []
    for c in post_item.get("latestComments") or []:
        if len(out) >= per_post:
            break
        # VERIFIED LIVE 2026-10-09 (T6): items carry `text` (160/162) and `timestamp` (162/162) plus owner fields that
        # map_ig_comment never reads; at most 15 per post. A media-only comment (no text) is skipped.
        m = map_ig_comment(c, actor=actor, fetched_at=fetched_at, index=len(out) + 1, post_url=url) \
            if isinstance(c, dict) else None
        if m:
            out.append(m)
    return out


# ---------------------------------------------------------------------------------------------
# Mappers: TikTok (pure)
# ---------------------------------------------------------------------------------------------


def map_tt_video(item: dict, *, actor: str, fetched_at: datetime, default_author: str | None = None) -> Post | None:
    """tiktok-scraper / tiktok-profile-scraper video item -> Post (handle and id from webVideoUrl)."""
    if not isinstance(item, dict) or error_of(item):
        return None
    url = _str(item.get("webVideoUrl"))
    ref = tt_video_ref(url)
    created = parse_ts(item.get("createTimeISO"))
    if not url or not ref or created is None:
        return None
    handle, vid = ref
    # VERIFIED LIVE 2026-10-09 (T9/T10): the caption is `text` (46/46 videos, 5 empty).
    caption = _str(item.get("text")) or ""
    # VERIFIED LIVE 2026-10-09: hashtags[] are objects {id, name, title, cover}; mentions[] are "@handle" strings
    # (detailedMentions[] objects are never read). Strings are still accepted; the caption is the last fallback.
    hashtags = _strings(item.get("hashtags")) or _handles(item.get("hashtags"), key="name") or _HASHTAG_RE.findall(caption)
    mentions = caption_mentions(caption, _strings(item.get("mentions")))
    lang = _str(item.get("textLanguage"))
    meta_loc = item.get("locationMeta") if isinstance(item.get("locationMeta"), dict) else {}
    # VERIFIED LIVE 2026-10-09 (T9): only nested locationMeta {address, city, cityCode, countryCode, locationName,
    # locationId} (16/40 videos), never a top-level locationName (still read as a guard). city is "" on 5/16 while
    # address names the town, so location_name = "venue, town" and metrics' city match sees Brno on venue posts.
    # countryCode / cityCode are GeoNames ids (3077311 = CZ, 3078610 = Brno), not ISO codes.
    name = _str(meta_loc.get("locationName")) or _str(item.get("locationName"))
    town = _str(meta_loc.get("city")) or _str(meta_loc.get("address"))
    place = ", ".join(dict.fromkeys(x for x in (name, town) if x)) or None
    label = _bool(item.get("isSponsored"))   # the label; isAd is a promoted ad, not a collab
    if label is False and not TRUST_TIKTOK_FALSE_LABEL:
        label = None
    return Post(
        id=f"tt:video:{vid}",
        platform="tiktok",
        url=url,
        author_handle=handle or default_author or "",
        created_at=created,
        caption=caption,
        hashtags=[norm_handle(h) for h in hashtags],
        mentions=mentions,
        media_type="carousel" if _bool(item.get("isSlideshow")) else "video",   # live T9: 1/40 was a slideshow
        likes=_count(item.get("diggCount")),
        comments=_count(item.get("commentCount")),
        views=_count(item.get("playCount")),
        location_name=place,
        location_id=_str(meta_loc.get("locationId")),
        is_pinned=_bool(item.get("isPinned")),
        paid_partnership=label,
        language=None if (lang or "").lower() in ("", "un") else lang.lower(),  # caption language, not audio
        source=_src(id=f"tt:video:{vid}", url=url, platform="tiktok", actor=actor, fetched_at=fetched_at),
    )


def _tt_author_meta(item: dict) -> dict:
    meta = item.get("authorMeta")
    return meta if isinstance(meta, dict) else {}


def map_tt_profiles(items: list[dict], *, actor: str, fetched_at: datetime,
                    requested: Iterable[str] = ()) -> list[Profile]:
    """Video items (each with authorMeta) grouped per author -> Profiles with latest_posts.
    PROFILE_PRIVATE error items -> a private Profile when the handle can be identified;
    other error items (PROFILE_EMPTY = gap, NOT_FOUND, ...) are skipped."""
    wanted = [norm_handle(h) for h in requested if norm_handle(h)]
    groups: dict[str, list[dict]] = {}
    private: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        err = error_of(it)
        if err:
            if _str(it.get("errorCode")) == "PROFILE_PRIVATE":
                h = _scan_tiktok_handle(it)
                if h is None:
                    hits = [w for w in wanted if any(isinstance(v, str) and norm_handle(v.split("@")[-1].strip("/")) == w
                                                     for v in it.values())]
                    h = hits[0] if len(hits) == 1 else (wanted[0] if len(wanted) == 1 else None)
                if h and h not in private:
                    private.append(h)
            continue
        h = _scan_tiktok_handle(it)
        if h:
            groups.setdefault(h, []).append(it)
    out: list[Profile] = []
    for h, vids in groups.items():
        meta = _tt_author_meta(vids[0])
        bio = _str(meta.get("signature")) or ""
        link = meta.get("bioLink")
        ext = [link] if isinstance(link, str) and link.strip() else \
            [v for v in (link.values() if isinstance(link, dict) else []) if isinstance(v, str) and "." in v]
        posts = [p for p in (map_tt_video(v, actor=actor, fetched_at=fetched_at, default_author=h) for v in vids) if p]
        posts.sort(key=lambda p: p.created_at, reverse=True)
        url = tt_profile_url(h)
        region = _str(meta.get("region")) if TRUST_TIKTOK_REGION else None
        out.append(Profile(
            handle=h, platform="tiktok", url=url,
            # VERIFIED LIVE 2026-10-09 (T9/T10): authorMeta has 22 keys; display name = nickName, following =
            # following, video count = video (also heart, friends, digg, createTime, never read).
            display_name=_str(meta.get("nickName")) or "",
            bio=bio,
            followers=_count(meta.get("fans")),
            following=_count(meta.get("following")),
            posts_count=_count(meta.get("video")),
            verified=_bool(meta.get("verified")),
            private=_bool(meta.get("privateAccount")),
            external_urls=[e.strip() for e in ext],
            region=region.upper() if region else None,
            # VERIFIED LIVE 2026-10-09 (T10): isUnderAge18 is absent from authorMeta (50/50); only an explicit true counts.
            is_under_18=True if _bool(meta.get("isUnderAge18")) is True else None,
            latest_posts=posts,
            source=_src(id=f"tt:profile:{h}", url=url, platform="tiktok", actor=actor, fetched_at=fetched_at,
                        quote=bio[:200] or None),
        ))
    for h in private:
        if h not in groups:
            url = tt_profile_url(h)
            out.append(Profile(handle=h, platform="tiktok", url=url, private=True,
                               source=_src(id=f"tt:profile:{h}", url=url, platform="tiktok", actor=actor,
                                           fetched_at=fetched_at, quote="PROFILE_PRIVATE")))
    return out


def map_tt_search(items: list[dict], *, query: str, actor: str, fetched_at: datetime) -> list[CandidateRef]:
    """tiktok-scraper searchSection=/user -> one CandidateRef per author, found_via "search:<query>".
    VERIFIED LIVE 2026-10-09 (T9): items are up to resultsPerPage videos per found profile (handle from webVideoUrl)
    plus one charged "note" item per profile with no videos ("Profile has no videos (or is behind a login wall)",
    no errorCode); those profiles cannot be scored and are skipped. /user matches the word in names and
    nicknames, so it returns businesses rather than creators."""
    via = f"search:{_clean_query(query)}"
    seen: dict[str, CandidateRef] = {}
    for it in items:
        if not isinstance(it, dict) or error_of(it):
            continue
        h = _scan_tiktok_handle(it)
        if not h or h in seen or not valid_tiktok_handle(h):   # Brno run: "@jídlo" became a charged INVALID_URLS
            continue
        if it.get("note") and not it.get("webVideoUrl") and _count(_tt_author_meta(it).get("video")) == 0:
            continue   # T9: "Profile has no videos" note item (charged as a result), nothing to score
        seen[h] = CandidateRef(handle=h, platform="tiktok", found_via=[via],
                               source=_src(id=f"disc:tt:{h}:search:{short_hash(via, 6)}", url=tt_profile_url(h),
                                           platform="tiktok", actor=actor, fetched_at=fetched_at, quote=via))
    return list(seen.values())


def map_tt_comment(item: dict, *, actor: str, fetched_at: datetime, index: int,
                   post_url: str | None = None) -> Comment | None:
    """tiktok-comments-scraper item -> Comment. uid, uniqueId, avatarThumbnail, mentions and
    detailedMentions are never read."""
    if not isinstance(item, dict) or error_of(item):
        return None
    text = _str(item.get("text"))
    url = post_url or _str(item.get("videoWebUrl"))
    if not text or not url:
        return None
    vid = (tt_video_ref(url) or ("", short_hash(url)))[1]
    return Comment(post_url=url, text=mask_mentions(text), created_at=parse_ts(item.get("createTimeISO")),
                   source=_src(id=f"tt:comment:{vid}:{index}", url=url, platform="tiktok", actor=actor,
                               fetched_at=fetched_at))


# ---------------------------------------------------------------------------------------------
# Mappers: Meta Branded Content, news (pure)
# ---------------------------------------------------------------------------------------------


def map_brand_collab(item: dict, *, creator_handle: str, actor: str, fetched_at: datetime) -> list[CollabEvidence]:
    """brand-collaboration-scraper row -> one CollabEvidence per brand partner (kind meta_branded,
    disclosed True: the Branded Content library only holds labeled posts).

    Direction (Apify recipe): decided by which side the TARGET account is on, not by
    isBusinessAccount. A row whose creator link is an Instagram account other than ours is not our
    collab (our account on the brand side, or a row about two other accounts): []. A row whose
    creator link is not an Instagram profile (e.g. a Facebook page) is kept.

    VERIFIED LIVE 2026-10-09 (T8): rows are {id (numeric IG media id), dateCreated (YYYY-MM-DD), creator{name, link},
    brandPartners[{name, link}], type, link (post/reel URL), platform "Instagram"}; both names are IG HANDLES, links
    are instagram.com/_u/<handle>. post_id comes from the shortcode in `link` (dedupe with the post-scraper label)."""
    if not isinstance(item, dict) or error_of(item):
        return []
    target = norm_handle(creator_handle)
    creator_link = _str(_get(item, "creator", "link"))
    creator_h = ig_handle_from_link(creator_link)
    if creator_h and creator_h != target:
        return []
    partners = [p for p in (item.get("brandPartners") or []) if isinstance(p, dict)]
    partner_handles = [ig_handle_from_link(_str(p.get("link"))) for p in partners]
    rid = _str(item.get("id")) or short_hash(f"{creator_link}|{item.get('link')}|{item.get('dateCreated')}")
    link = _str(item.get("link")) or ig_profile_url(target)
    code = ig_shortcode(_str(item.get("link")))
    date = parse_ts(item.get("dateCreated"))     # YYYY-MM-DD
    out: list[CollabEvidence] = []
    for p, ph in zip(partners, partner_handles):
        if ph == target:
            continue
        brand = _str(p.get("name")) or ph
        if not brand:
            continue
        out.append(CollabEvidence(
            id=f"collab:meta:{rid}:{short_hash(brand, 6)}" if len(partners) > 1 else f"collab:meta:{rid}",
            brand=brand, brand_handle=ph, kind="meta_branded", disclosed=True, date=date,
            post_id=f"ig:post:{code}" if code else None,
            source=_src(id=f"meta:ad:{rid}", url=link, platform="meta_branded", actor=actor, fetched_at=fetched_at,
                        quote=f"Placené partnerství s {brand} (Meta Branded Content)"),
        ))
    return out


def map_news(item: dict, *, actor: str, fetched_at: datetime) -> NewsItem | None:
    """google-news-scraper-fast article -> NewsItem. url is the publisher URL only with decodeUrls."""
    if not isinstance(item, dict) or error_of(item):
        return None
    title = _str(item.get("title"))
    url = _str(item.get("url"))
    if not title or not url:
        return None
    src = item.get("source")
    # VERIFIED LIVE 2026-10-09 (T11): `source` is a plain string (10/10, e.g. the outlet name); the dict branch is a guard.
    outlet = _str(src) if not isinstance(src, dict) else (_str(src.get("name")) or _str(src.get("title")))
    # publishedAt is ISO with day precision only (time always 07:00/08:00 UTC); publishedTimestamp is epoch ms.
    published = parse_ts(item.get("publishedAt")) or parse_ts(item.get("publishedTimestamp"))
    nid = f"news:{short_hash(url)}"
    return NewsItem(id=nid, title=title, outlet=outlet or "", url=url, published_at=published,
                    # VERIFIED LIVE 2026-10-09: no `description` key without extractDescriptions -> "" (10/10)
                    snippet=(_str(item.get("description")) or "")[:500],
                    source=_src(id=nid, url=url, platform="news", actor=actor, fetched_at=fetched_at, quote=title[:200]))


_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")


def map_yt_video(item: dict, *, actor: str, fetched_at: datetime, default_author: str | None = None) -> Post | None:
    """youtube-scraper video -> Post (live T12/T12b, 5/5 mapped). isPaidContent: only True is evidence (a video
    with a sponsor link in its description returned false), so False maps to None. ``location`` and ``hashtags``
    were empty 5/5. Mentions stay empty: the caption regex would also catch e-mail domains."""
    if not isinstance(item, dict) or error_of(item):
        return None
    url = _str(item.get("url"))
    m = _YT_ID_RE.search(url or "")
    vid = _str(item.get("id")) or (m.group(1) if m else None)
    created = parse_ts(item.get("date"))
    author = norm_handle(_str(item.get("channelUsername")) or default_author or "")
    if not url or not vid or created is None or not author:
        return None
    caption = _str(item.get("text")) or ""
    tags = [norm_handle(t) for t in _strings(item.get("hashtags"))] or \
        [norm_handle(t) for t in _HASHTAG_RE.findall(caption)]
    pid = f"yt:video:{vid}"
    return Post(id=pid, platform="youtube", url=url, author_handle=author, created_at=created, caption=caption,
                hashtags=[t for t in tags if t], media_type="video", likes=_count(item.get("likes")),
                comments=_count(item.get("commentsCount")), views=_count(item.get("viewCount")),
                location_name=_str(item.get("location")),
                paid_partnership=True if item.get("isPaidContent") is True else None,
                source=_src(id=pid, url=url, platform="youtube", actor=actor, fetched_at=fetched_at,
                            quote=(_str(item.get("title")) or "")[:200] or None))


# ---------------------------------------------------------------------------------------------
# Cross-platform links (pure)
# ---------------------------------------------------------------------------------------------


def cross_platform_links(profile: Profile) -> list[tuple[str, str, str]]:
    """(platform, handle, url) of other-platform accounts linked from bio / external URLs."""
    text = " ".join([profile.bio or "", *profile.external_urls])
    out: list[tuple[str, str, str]] = []

    def add(platform: str, handle: str | None, url: str) -> None:
        h = norm_handle(handle or "")
        if not h or (platform == profile.platform and h == profile.handle):
            return
        if all((p, x) != (platform, h) for p, x, _ in out):
            out.append((platform, h, url))

    for m in _TT_HANDLE_RE.finditer(text):
        add("tiktok", m.group(1).rstrip("."), tt_profile_url(m.group(1).rstrip(".")))
    for m in _IG_LINK_RE.finditer(text):
        h = ig_handle_from_link(m.group(0))
        if h:
            add("instagram", h, ig_profile_url(h))
    for m in _YT_LINK_RE.finditer(text):
        add("youtube", m.group(1), f"https://www.youtube.com/@{m.group(1)}")
    for m in _PLATFORM_AT_RE.finditer(profile.bio or ""):
        platform, h = _PLATFORM_WORD[m.group(1).lower()], m.group(2).rstrip(".")
        url = {"tiktok": tt_profile_url, "instagram": ig_profile_url}.get(platform, lambda x: f"https://www.youtube.com/@{x}")(h)
        add(platform, h, url)
    return out


def link_only_profile(platform: str, handle: str, url: str, primary: Profile, fetched_at: datetime) -> Profile:
    """A linked account we did not fetch (YouTube: no profile call; posts(h, "youtube") reads the channel's
    videos with youtube-scraper, live T12). Carries only what the link proves; the SourceRef points at the
    primary profile's link."""
    return Profile(handle=handle, platform=platform, url=url,  # type: ignore[arg-type]
                   source=_src(id=f"link:{primary.platform}:{primary.handle}:{platform}:{norm_handle(handle)}",
                               url=primary.url, platform=primary.platform, actor=primary.source.actor or "apify",
                               fetched_at=fetched_at, quote=url))


def merge_refs(refs: list[CandidateRef]) -> list[CandidateRef]:
    """Dedupe by (platform, handle), merge found_via (unique, ordered), order by discovery path."""
    by_key: dict[tuple[str, str], CandidateRef] = {}
    for r in refs:
        key = (r.platform, r.handle)
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = r.model_copy(update={"found_via": list(dict.fromkeys(r.found_via))})
        else:
            prev.found_via = list(dict.fromkeys([*prev.found_via, *r.found_via]))
    order = {k: i for i, k in enumerate(PATH_ORDER)}

    def rank(r: CandidateRef) -> int:
        return min((order.get(v.partition(":")[0], len(order)) for v in r.found_via), default=len(order))

    return sorted(by_key.values(), key=rank)


# ---------------------------------------------------------------------------------------------
# Running actors
# ---------------------------------------------------------------------------------------------


@dataclass
class RunResult:
    items: list[dict]
    status: str | None = None
    usd: float | None = None
    events: dict | None = None
    run_id: str | None = None


# (actor, run_input, max_items=, max_usd=, timeout_s=) -> RunResult. Tests inject a fake one.
Runner = Callable[..., Awaitable[RunResult]]

# Sub-runs that failed, were skipped or ended early inside the current discover() call. A ContextVar so
# concurrent calls do not mix (asyncio tasks copy the context and share the list object).
_RUN_ISSUES: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("apify_run_issues", default=None)


def _note_issue(label: str, why: str) -> None:
    issues = _RUN_ISSUES.get()
    if issues is not None:
        issues.append(f"{label}: {why}")


def _client_error(e: BaseException) -> bool:
    """Apify API 4xx (invalid input, insufficient credit, charge cap too low): retrying cannot help.
    408 and 429 stay retryable. ApifyApiError.status_code exists in apify-client 1.x to 3.x."""
    code = getattr(e, "status_code", None)
    return isinstance(code, int) and 400 <= code < 500 and code not in (408, 429)


def _run_attr(run: Any, snake: str, camel: str) -> Any:
    """Run object: pydantic model in apify-client 3.x, dict in 1.x / 2.x."""
    if run is None:
        return None
    if isinstance(run, dict):
        return run.get(camel, run.get(snake))
    return getattr(run, snake, None)


def _status(run: Any) -> str | None:
    s = _run_attr(run, "status", "status")
    s = getattr(s, "value", s)
    return str(s) if s is not None else None


def call_kwargs(fn: Callable, *, run_input: dict, max_items: int, max_usd: float, timeout_s: int) -> dict:
    """Keyword args for ``actor.call`` that the installed client supports (3.x: run_timeout /
    wait_duration as timedelta; 1.x: timeout_secs / wait_secs). VERIFIED LIVE 2026-10-09: apify-client 3.3.0
    takes max_total_charge_usd (Decimal) and the platform echoed it as options.maxTotalChargeUsd on every run;
    an older client without it is logged and only our estimate guards the cost."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    kw: dict[str, Any] = {"run_input": run_input}
    if "max_items" in params:
        kw["max_items"] = int(max_items)
    if "max_total_charge_usd" in params:
        kw["max_total_charge_usd"] = Decimal(str(round(max_usd, 2)))
    if "run_timeout" in params:
        kw["run_timeout"] = timedelta(seconds=timeout_s)
    elif "timeout_secs" in params:
        kw["timeout_secs"] = int(timeout_s)
    if "wait_duration" in params:
        kw["wait_duration"] = timedelta(seconds=timeout_s + 60)
    elif "wait_secs" in params:
        kw["wait_secs"] = int(timeout_s + 60)
    if "logger" in params:
        kw["logger"] = None   # do not stream actor logs into our process
    if "wait_for_resources" in params:
        # 3.x retries a start rejected with concurrent-runs-limit-exceeded (Free: 5 runs per account) instead
        # of raising a 4xx that _run would not retry
        kw["wait_for_resources"] = timedelta(seconds=WAIT_FOR_RESOURCES_S)
    return kw


def _read_limit(max_items: int) -> int:
    return max(100, min(5000, int(max_items) * 2))


def _outer_timeout(timeout_s: int) -> int:
    """Client-side bound: waiting for a run slot + run_timeout + the wait_duration headroom + reading items."""
    return int(timeout_s) + WAIT_FOR_RESOURCES_S + 180


class _ClientRunner:
    """Default Runner over apify_client: async client when available, else the sync one in a thread."""

    def __init__(self, token: str) -> None:
        self.token = token
        self._client: Any = None
        self.charge_cap_supported: bool | None = None

    def _get(self) -> tuple[Any, bool]:
        if self._client is None:
            if _AsyncClient is not None:
                self._client = (_AsyncClient(token=self.token), True)
            elif _SyncClient is not None:
                self._client = (_SyncClient(token=self.token), False)
            else:
                raise RuntimeError("apify-client není nainstalovaný (pip install apify-client)")
        return self._client

    async def __call__(self, actor: str, run_input: dict, *, max_items: int, max_usd: float, timeout_s: int) -> RunResult:
        client, is_async = self._get()
        if is_async:
            act = client.actor(actor)
            kw = call_kwargs(act.call, run_input=run_input, max_items=max_items, max_usd=max_usd, timeout_s=timeout_s)
            self.charge_cap_supported = "max_total_charge_usd" in kw
            run = await asyncio.wait_for(act.call(**kw), timeout=_outer_timeout(timeout_s))
            status = _status(run)
            run_id = _run_attr(run, "id", "id")
            if status in ("READY", "RUNNING") and run_id:   # waited long enough: stop paying
                try:
                    await client.run(run_id).abort()
                except Exception:
                    pass
            items: list[dict] = []
            ds = _run_attr(run, "default_dataset_id", "defaultDatasetId")
            if ds:
                page = await client.dataset(ds).list_items(limit=_read_limit(max_items))
                items = list(getattr(page, "items", None) or [])
            # VERIFIED LIVE 2026-10-09: the settled usageTotalUsd == chargedEventCounts x FREE event price (all runs),
            # but the Run that call() returns is read before the charges settle (0.0 or partial in most runs, still
            # stale 2 s later, right after 5-15 s). _run therefore floors it with items x unit price.
            return RunResult(items=items, status=status, usd=_run_attr(run, "usage_total_usd", "usageTotalUsd"),
                             events=_run_attr(run, "charged_event_counts", "chargedEventCounts"), run_id=run_id)

        def work() -> RunResult:
            act = client.actor(actor)
            kw = call_kwargs(act.call, run_input=run_input, max_items=max_items, max_usd=max_usd, timeout_s=timeout_s)
            self.charge_cap_supported = "max_total_charge_usd" in kw
            run = act.call(**kw)
            status = _status(run)
            run_id = _run_attr(run, "id", "id")
            if status in ("READY", "RUNNING") and run_id:
                try:
                    client.run(run_id).abort()
                except Exception:
                    pass
            ds = _run_attr(run, "default_dataset_id", "defaultDatasetId")
            items = list(getattr(client.dataset(ds).list_items(limit=_read_limit(max_items)), "items", None) or []) if ds else []
            return RunResult(items=items, status=status, usd=_run_attr(run, "usage_total_usd", "usageTotalUsd"),
                             events=_run_attr(run, "charged_event_counts", "chargedEventCounts"), run_id=run_id)

        return await asyncio.wait_for(asyncio.to_thread(work), timeout=_outer_timeout(timeout_s))


class _NoToken(Exception):
    """Raised only if a run is attempted without a token (the _safe wrapper prevents it)."""


def _safe(method: str):
    """Never raise into the funnel; no token -> log + [].

    Every call collects its failed / skipped / early-ended actor runs (``_note_issue``). A call that finished with
    none tells CachedProvider so (``cache.answer_is_complete``): its result, even [], is the real answer and an
    empty one may be cached. No token, an exception or a noted issue never confirm (an empty list there is a gap)."""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self: "ApifyProvider", *args, **kwargs):
            if not self.token:
                await self._log(tr(f"{method}: APIFY_TOKEN není nastavený (APIFY_TOKEN not set), živá data nejsou; vracím []",
                                   f"{method}: APIFY_TOKEN not set, no live data; returning []"))
                return []
            issues: list[str] = []
            token = _RUN_ISSUES.set(issues)
            try:
                result = await fn(self, *args, **kwargs)
            except Exception as e:  # noqa: BLE001 - the contract is "never raise"
                log.exception("apify %s failed", method)
                await self._log(tr(f"{method}: chyba {type(e).__name__}: {str(e)[:200]}; vracím []",
                                   f"{method}: error {type(e).__name__}: {str(e)[:200]}; returning []"))
                return []
            finally:
                _RUN_ISSUES.reset(token)
            if not issues:
                answer_is_complete()
            return result

        return wrapper

    return deco


def _cs(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


def _usd(x: float | None) -> str:
    return "?" if x is None else f"{x:.3f}".replace(".", ",")


def _usd_en(x: float | None) -> str:
    return "?" if x is None else f"{x:.3f}"


def _en(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


# ---------------------------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------------------------


class ApifyProvider:
    name: str = "apify"   # == factory.CACHE_NAMESPACE == cache.DEFAULT_IMPORT_PROVIDER

    def __init__(self, token: str | None = None, *, runner: Runner | None = None) -> None:
        """token defaults to get_settings().apify_token. Must NOT raise when the token is missing:
        then every method logs "APIFY_TOKEN not set" and returns [] (cache mode relies on this).
        ``runner`` replaces the apify_client call (tests)."""
        tok = token if token is not None else get_settings().apify_token
        self.token: str | None = (tok or "").strip() or None
        self._runner: Runner | None = runner
        self._sem = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
        self.spent_estimate_usd = 0.0
        self.spent_reported_usd = 0.0   # sum of max(usageTotalUsd, items x unit price) per run (see _run)
        # Sub-runs of the last discover() that failed / were skipped / ended early ([] = complete). A
        # "partial" flag CachedProvider can check before it writes the result (cache.py does not yet).
        self.last_discover_incomplete: list[str] = []

    # ------------------------------------------------------------------ plumbing

    async def _log(self, text: str, actor: str | None = None) -> None:
        log.info("%s %s", actor or "apify", text)
        await emit_log(text, actor=actor or "apify", mode="live")

    def _get_runner(self) -> Runner:
        if self._runner is None:
            if not self.token:
                raise _NoToken()
            self._runner = _ClientRunner(self.token)
        return self._runner

    @staticmethod
    def _charged_usd(actor: str, result: RunResult, *, units: int, est: float) -> float:
        """What the run cost: max(usageTotalUsd, items x unit price + start fee). Live 9. 10. 2026: every dataset
        item is charged (error and "note" items too) and the settled charge equalled items x price in every run,
        while the usageTotalUsd returned by call() was often still 0.0 or partial. The unit price is taken from
        the run's own estimate, so the CZ proxy add-on and basicData are priced right (music-data is not)."""
        reported = float(result.usd) if isinstance(result.usd, (int, float)) and not isinstance(result.usd, bool) else 0.0
        start = START_FEE_USD.get(actor, 0.0)
        per_item = (est - start) / units if units > 0 else PRICE_USD.get(actor, 0.0)
        floor = len(result.items) * max(0.0, per_item) + (start if result.items else 0.0)
        return round(max(reported, floor), 4)

    async def _run(self, actor: str, run_input: dict, *, units: int, label: str, est_usd: float | None = None,
                   worst_usd: float | None = None, max_items: int | None = None,
                   timeout_s: int = RUN_TIMEOUT_S) -> list[dict]:
        """One actor run with the cost guard. Returns the raw items ([] when skipped or failed).
        Error items stay in the list (TikTok PROFILE_PRIVATE is data); they are counted in the log and
        every mapper skips them. Retries once on a failed run (search-scraper ~4.5 % FAILED in 30 days),
        but not on a client-side timeout or an Apify 4xx. ``worst_usd`` (e.g. post-scraper music-data)
        drives the cost guard and the charge cap when above the estimate. A skipped, failed or early-ended
        run, one that hit its charge cap and one that returned only error items other than ANSWER_ERRORS are
        noted (_note_issue): discover() reports them as partial and CachedProvider never caches the call's []."""
        est = estimate_usd(actor, units) if est_usd is None else round(est_usd, 4)
        worst = max(est, round(worst_usd, 4)) if worst_usd is not None else est
        cap = max_usd_per_run()
        if worst > cap:
            await self._log(tr(f"živě {label}: odhad {_usd(worst)} USD > strop MAX_USD_PER_RUN {_usd(cap)} USD, běh přeskočen",
                               f"live {label}: estimate {_usd_en(worst)} USD > cap MAX_USD_PER_RUN {_usd_en(cap)} USD, run skipped"),
                            actor)
            _note_issue(label, tr("přeskočeno (odhad nad stropem)", "skipped (estimate over the cap)"))
            return []
        charge_cap = charge_cap_usd(actor, worst, cap)
        worst_txt = f", nejhůř {_usd(worst)}" if worst > est else ""
        worst_en = f", worst case {_usd_en(worst)}" if worst > est else ""
        await self._log(tr(f"živě {label}: spouštím, odhad {_usd(est)} USD{worst_txt} (strop běhu {_usd(charge_cap)} USD)",
                           f"live {label}: starting, estimate {_usd_en(est)} USD{worst_en} (run cap {_usd_en(charge_cap)} USD)"),
                        actor)
        runner = self._get_runner()
        result: RunResult | None = None
        for attempt in (1, 2):
            self.spent_estimate_usd += est   # every attempt may be charged
            try:
                async with self._sem:
                    result = await runner(actor, run_input, max_items=int(max_items or units), max_usd=charge_cap,
                                          timeout_s=timeout_s)
            except Exception as e:  # noqa: BLE001
                # A client-side timeout may leave the run going on Apify (until run_timeout); an API 4xx
                # (invalid input, no credit, cap too low) fails the same way again: no retry for either.
                retry = attempt == 1 and not isinstance(e, (asyncio.TimeoutError, TimeoutError)) and not _client_error(e)
                log.warning("apify run %s failed (attempt %s): %s", actor, attempt, e)
                await self._log(tr(f"živě {label}: běh selhal ({type(e).__name__}: {str(e)[:150]})"
                                   + ("; zkouším znovu" if retry else ""),
                                   f"live {label}: run failed ({type(e).__name__}: {str(e)[:150]})"
                                   + ("; retrying" if retry else "")), actor)
                result = None
                if not retry:
                    break
                continue
            self.spent_reported_usd += self._charged_usd(actor, result, units=units, est=est)
            if result.status in ("FAILED",) and not result.items and attempt == 1:
                await self._log(tr(f"živě {label}: běh FAILED bez dat; zkouším znovu",
                                   f"live {label}: run FAILED without data; retrying"), actor)
                continue
            break
        if result is None:
            _note_issue(label, tr("běh selhal", "run failed"))
            return []
        if result.status and result.status != "SUCCEEDED":
            _note_issue(label, tr(f"stav {result.status}", f"status {result.status}"))
        good = [it for it in result.items if isinstance(it, dict) and not error_of(it)]
        errors = [error_of(it) for it in result.items if not isinstance(it, dict) or error_of(it)]
        if not good and any(e not in ANSWER_ERRORS for e in errors):
            _note_issue(label, tr("jen chybové položky", "error items only"))
        charged = self._charged_usd(actor, result, units=units, est=est)
        # VERIFIED LIVE 2026-10-09: settled usageTotalUsd is the charge, but call() returns it before it settles
        msg = (f"živě {label}: {_cs(len(good), 'položka', 'položky', 'položek')}, stav {result.status or '?'}, "
               f"účtováno asi {_usd(charged)} USD (usageTotalUsd {_usd(result.usd)}, může se opožďovat; "
               f"odhad {_usd(est)})")
        msg_en = (f"live {label}: {_en(len(good), 'item')}, status {result.status or '?'}, "
                  f"charged about {_usd_en(charged)} USD (usageTotalUsd {_usd_en(result.usd)}, may lag; "
                  f"estimate {_usd_en(est)})")
        if result.events:
            msg += f", eventy {dict(result.events)}"
            msg_en += f", events {dict(result.events)}"
            if any("music" in str(k) and (v or 0) > 0 for k, v in dict(result.events).items()):
                msg += " (pozor: music-data, zvaž APIFY_POST_DETAIL=basicData)"
                msg_en += " (note: music-data, consider APIFY_POST_DETAIL=basicData)"
        if charged >= 0.95 * charge_cap:
            # Apify stops a run at its charge cap: the items may be cut short, so this is a partial run (never
            # cached as a complete answer, e.g. comments of the posts it did not reach cached as "no comments")
            msg += f"; běh došel ke stropu {_usd(charge_cap)} USD, data můžou být neúplná"
            msg_en += f"; the run reached its cap of {_usd_en(charge_cap)} USD, the data may be incomplete"
            _note_issue(label, tr("došel ke stropu", "reached the cap"))
        if errors:
            kinds = sorted({str(e)[:40] for e in errors})
            msg += f"; chybové položky vynechány: {len(errors)} ({', '.join(kinds[:4])})"
            msg_en += f"; error items left out: {len(errors)} ({', '.join(kinds[:4])})"
        if isinstance(self._runner, _ClientRunner) and self._runner.charge_cap_supported is False:
            msg += "; klient nepodporuje max_total_charge_usd, strop hlídá jen odhad"
            msg_en += "; the client does not support max_total_charge_usd, only the estimate guards the cap"
        await self._log(tr(msg, msg_en), actor)
        return result.items   # callers map; mappers skip error items themselves (TikTok PROFILE_PRIVATE is data)

    async def _run_many(self, jobs: list[Callable[[], Awaitable[Any]]]) -> list[Any]:
        res = await asyncio.gather(*(j() for j in jobs), return_exceptions=True)
        out = []
        for r in res:
            if isinstance(r, BaseException):
                log.warning("apify sub-run failed: %s", r)
                await self._log(tr(f"dílčí běh selhal: {type(r).__name__}: {str(r)[:150]}",
                                   f"partial run failed: {type(r).__name__}: {str(r)[:150]}"))
                _note_issue(tr("dílčí běh", "partial run"), tr(f"výjimka {type(r).__name__}", f"exception {type(r).__name__}"))
                out.append(None)
            else:
                out.append(r)
        return out

    # ------------------------------------------------------------------ discover

    @_safe("discover")
    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]:
        """All discovery paths merged. About 18 sub-runs; one failing (search-scraper ~4.5 % FAILED) leaves
        the result partial, and CachedProvider writes any non-empty result. So incomplete sub-runs are
        counted, set on ``last_discover_incomplete`` and logged with the cache file to delete."""
        issues = _RUN_ISSUES.get()   # set per call by _safe; sub-runs append to it (asyncio tasks share the list)
        if issues is None:
            issues = []
        self.last_discover_incomplete = issues
        merged, n_refs = await self._discover(q)
        paths = Counter(v.partition(":")[0] for r in merged for v in dict.fromkeys(r.found_via))
        per_path = ", ".join(f"{k} {paths[k]}" for k in PATH_ORDER if paths.get(k))
        await self._log(tr(f"discover: {_cs(len(merged), 'kandidát', 'kandidáti', 'kandidátů')} "
                           f"({n_refs} nálezů{'; cesty: ' + per_path if per_path else ''}; "
                           f"odhad útraty zatím {_usd(self.spent_estimate_usd)} USD)",
                           f"discover: {_en(len(merged), 'candidate')} "
                           f"({_en(n_refs, 'hit')}{'; paths: ' + per_path if per_path else ''}; "
                           f"estimated spend so far {_usd_en(self.spent_estimate_usd)} USD)"))
        if issues:
            await self._log(tr(f"discover: VÝSLEDEK NEÚPLNÝ, dílčí běhy selhané, přeskočené nebo předčasně ukončené: "
                               f"{len(issues)} ({'; '.join(issues[:4])}{'; …' if len(issues) > 4 else ''}). "
                               f"Cache ho přesto uloží: {self._cache_hint(q)} a pusť discover znovu, než cache předáš týmu.",
                               f"discover: RESULT INCOMPLETE, partial runs failed, skipped or ended early: "
                               f"{len(issues)} ({'; '.join(issues[:4])}{'; …' if len(issues) > 4 else ''}). "
                               f"The cache stores it anyway: {self._cache_hint(q)} and run discover again before "
                               f"handing the cache to the team."))
        return merged

    def _cache_hint(self, q: DiscoveryQuery) -> str:
        """Which cache file holds this discover() result (CachedProvider keys it by {"q": q})."""
        try:
            return tr(f"smaž soubor {cache_key('discover', {'q': q}, self.name)}.json v adresáři cache",
                      f"delete {cache_key('discover', {'q': q}, self.name)}.json in the cache directory")
        except Exception:  # noqa: BLE001 - only a hint
            return tr("smaž ho (python -m app.sources.cache purge maže celou cache)",
                      "delete it (python -m app.sources.cache purge deletes the whole cache)")

    async def _discover(self, q: DiscoveryQuery) -> tuple[list[CandidateRef], int]:
        platforms = set(q.platforms or ["instagram", "tiktok"])
        city = q.city or (q.places[0] if q.places else None)
        keywords = [k for k in (_clean_query(k) for k in q.keywords) if k]
        if city:
            keywords = [k if city_text_match(city, k) else f"{k} {city}" for k in keywords]
        keywords = list(dict.fromkeys(keywords))[:MAX_KEYWORDS]
        tags = list(dict.fromkeys(norm_handle(t) for t in q.hashtags if norm_handle(t)))[:MAX_HASHTAGS]
        now = utcnow()
        jobs: list[Callable[[], Awaitable[Any]]] = []
        kinds: list[str] = []
        if not keywords and not tags:
            await self._log(tr("discover: dotaz nemá klíčová slova ani hashtagy, nic se nehledá (doporučené výchozí: "
                               f"{', '.join(DEFAULT_KEYWORDS)}; #{', #'.join(DEFAULT_HASHTAGS)}; default_discovery_query())",
                               "discover: the query has no keywords or hashtags, nothing is searched (suggested defaults: "
                               f"{', '.join(DEFAULT_KEYWORDS)}; #{', #'.join(DEFAULT_HASHTAGS)}; default_discovery_query())"))
        if "instagram" in platforms:
            for kw in keywords:
                for live in ig_search_live_modes():
                    jobs.append(functools.partial(self._ig_search_users, kw, now, city, live))
                    kinds.append("ig_search")
            for t in tags:
                jobs.append(functools.partial(self._run, ACT_IG_HASHTAG, ig_hashtag_input([t], IG_HASHTAG_PER_TAG),
                                              units=IG_HASHTAG_PER_TAG, label=f"hashtag #{t}"))
                kinds.append(f"tag:{t}")
            if places_enabled() and keywords and city:
                jobs.append(functools.partial(self._ig_places, keywords, city, now))
                kinds.append("ig_places")
        if "tiktok" in platforms and keywords:
            if tiktok_search_enabled():
                for kw in keywords[:TT_SEARCH_MAX_QUERIES]:
                    jobs.append(functools.partial(self._tt_search, kw, now))
                    kinds.append("tt_search")
            else:
                # Brno run 9. 10. 2026: ~0.52 USD per discover for 0 surviving creators (non-Brno accounts, an invalid
                # handle). TikTok accounts still come in through find_cross_platform (bio links, profile scraper).
                await self._log(tr("TikTok hledání vypnuto (APIFY_TIKTOK_SEARCH=1 zapne; v Brně 9. 10. stálo asi 0,52 USD "
                                   "za běh a nedalo žádného tvůrce); TikTok účty se dohledají přes odkazy v bio",
                                   "TikTok search off (APIFY_TIKTOK_SEARCH=1 turns it on; in Brno on 9 Oct it cost about "
                                   "0.52 USD per run and found no creator); TikTok accounts are found via bio links"), ACT_TT)
        results = await self._run_many(jobs)

        refs: list[CandidateRef] = []
        city_ids: set[str] = set()
        tagged: list[tuple[str, Post]] = []
        for kind, res in zip(kinds, results):
            if res is None:
                continue
            if kind.startswith("tag:"):
                tag = kind[4:]
                for it in res:
                    p = map_ig_post(it, actor=ACT_IG_HASHTAG, fetched_at=now) if isinstance(it, dict) else None
                    if p:
                        tagged.append((tag, p))
            elif kind == "ig_places":
                place_refs, ids = res
                refs.extend(place_refs)
                city_ids |= ids
            else:
                refs.extend(res)
        if tagged:
            refs.extend(await self._hashtag_refs(tagged, city, city_ids, now))
        return merge_refs(refs), len(refs)

    async def _ig_search_users(self, keyword: str, now: datetime, city: str | None = None,
                               live: bool = False) -> list[CandidateRef]:
        tag = f"„{keyword}“{' (live)' if live else ''}"
        items = await self._run(ACT_IG_SEARCH, ig_search_input([keyword], "user", IG_SEARCH_PER_QUERY, live=live),
                                units=IG_SEARCH_PER_QUERY, label=tr(f"hledání účtů {tag}", f"account search {tag}"))
        out: list[CandidateRef] = []
        minors = off_city = 0
        why: Counter[str] = Counter()
        for it in items:
            if not isinstance(it, dict) or error_of(it):
                continue
            if raw_minor(it, "instagram"):
                minors += 1
                continue
            evidence = search_user_city_evidence(city, it)
            if evidence is None:
                off_city += 1
                continue
            ref = map_ig_search_user(it, query=keyword, actor=ACT_IG_SEARCH, fetched_at=now)
            if ref:
                why[evidence] += 1
                out.append(ref)
                out.extend(map_ig_related(it, actor=ACT_IG_SEARCH, fetched_at=now))
        if minors:
            await self._log(tr(f"hledání {tag}: mladší 18 let vynecháno: {minors} (nic se neukládá)",
                               f"search {tag}: under 18 left out: {minors} (nothing is stored)"), ACT_IG_SEARCH)
        if city and why:
            await self._log(tr(f"hledání {tag}: {city} podle jména {why['name']}, bio {why['bio']}, "
                               f"míst postů {why['posts']}",
                               f"search {tag}: {city} by name {why['name']}, bio {why['bio']}, "
                               f"post locations {why['posts']}"), ACT_IG_SEARCH)
        if off_city:
            await self._log(tr(f"hledání {tag}: bez zmínky {city} v jménu, bio ani místech postů vynecháno: {off_city}",
                               f"search {tag}: left out without {city} in the name, bio or post locations: {off_city}"),
                            ACT_IG_SEARCH)
        return out

    async def _resolve_locations(self, location_ids: list[str]) -> dict[str, tuple[float | None, float | None]]:
        """locationId -> (lat, lng) via instagram-scraper place URLs (0.0027 USD per place, T4)."""
        if not location_ids:
            return {}
        items = await self._run(ACT_IG_SCRAPER, ig_location_input(location_ids, "details", 1),
                                units=len(location_ids), label=tr(f"souřadnice {len(location_ids)} míst",
                                                                  f"coordinates of {_en(len(location_ids), 'place')}"))
        coords: dict[str, tuple[float | None, float | None]] = {}
        for it in items:
            pl = map_ig_place(it) if isinstance(it, dict) else None
            if pl and (pl.lat is not None and pl.lng is not None):
                coords[pl.location_id] = (pl.lat, pl.lng)   # paired by location_id, never by inputUrl
        return coords

    async def _hashtag_refs(self, tagged: list[tuple[str, Post]], city: str | None, city_ids: set[str],
                            now: datetime) -> list[CandidateRef]:
        loc_ids: list[str] = []
        if city and _fold(city).strip() in CITY_BBOX:
            freq: dict[str, int] = {}
            for _, p in tagged:
                if p.location_id and p.location_id not in city_ids:
                    freq[p.location_id] = freq.get(p.location_id, 0) + 1
            loc_ids = sorted(freq, key=lambda k: -freq[k])[:MAX_LOCATION_RESOLVE]
        coords = await self._resolve_locations(loc_ids)
        out: list[CandidateRef] = []
        stats = {"in": 0, "out": 0, "unknown": 0, "with_loc": 0}
        for tag, p in tagged:
            if p.location_id or p.location_name:
                stats["with_loc"] += 1
            verdict = place_verdict(city=city, location_id=p.location_id, location_name=p.location_name,
                                    coords=coords, city_location_ids=city_ids)
            stats[verdict] += 1
            if verdict == "out":
                continue
            via = [f"hashtag:{tag}"]
            if verdict == "in" and p.location_name:
                via.append(f"place:{p.location_name}")
            out.append(CandidateRef(handle=p.author_handle, platform="instagram", found_via=via,
                                    source=_src(id=f"disc:ig:{p.author_handle}:hashtag:{tag}", url=p.url,
                                                platform="instagram", actor=ACT_IG_HASHTAG, fetched_at=now,
                                                quote=f"#{tag}")))
        if city:
            await self._log(tr(f"hashtagy: {len(tagged)} postů, s místem {stats['with_loc']}; v {city} {stats['in']}, "
                               f"mimo {stats['out']} (vyřazeno podle souřadnic), neznámo {stats['unknown']} "
                               f"(ponecháno, lokalitu řeší kolo 3)",
                               f"hashtags: {_en(len(tagged), 'post')}, with a place {stats['with_loc']}; in {city} {stats['in']}, "
                               f"outside {stats['out']} (eliminated by coordinates), unknown {stats['unknown']} "
                               f"(kept, round 3 checks the location)"), ACT_IG_HASHTAG)
        return out

    async def _ig_places(self, keywords: list[str], city: str, now: datetime) -> tuple[list[CandidateRef], set[str]]:
        """APIFY_PLACES (default on, 0 turns it off): places in the city (by coordinates) -> their posts' authors
        (T2 + T4)."""
        items = await self._run(ACT_IG_SEARCH, ig_search_input(keywords, "place", IG_PLACE_SEARCH_PER_QUERY),
                                units=IG_PLACE_SEARCH_PER_QUERY * len(keywords), label=tr(f"místa ({city})", f"places ({city})"))
        places = [p for p in (map_ig_place(it, now=now) for it in items if isinstance(it, dict)) if p]
        kept: list[PlaceInfo] = []
        for pl in places:
            inside = in_city_bbox(city, pl.lat, pl.lng)
            # pl.city: location_city (4/42 live) or liveSearch `city`, which we never send for places; the text
            # check rests mostly on pl.name.
            if inside is True or (inside is None and (city_text_match(city, pl.city) or city_text_match(city, pl.name))):
                kept.append(pl)
        ids = {p.location_id for p in kept}
        await self._log(tr(f"místa: {len(places)} nalezeno, v {city} {len(kept)}",
                           f"places: {len(places)} found, in {city} {len(kept)}"), ACT_IG_SEARCH)
        refs: list[CandidateRef] = []
        names = {p.location_id: (p.name or p.location_id) for p in kept}

        def ref(h: str, loc_id: str, actor: str, url: str) -> CandidateRef:
            via = f"place:{names.get(loc_id, loc_id)}"
            return CandidateRef(handle=h, platform="instagram", found_via=[via],
                                source=_src(id=f"disc:ig:{h}:place:{loc_id}", url=url, platform="instagram",
                                            actor=actor, fetched_at=now, quote=via))

        for pl in kept:
            for h in pl.authors:
                refs.append(ref(h, pl.location_id, ACT_IG_SEARCH, ig_location_url(pl.location_id)))
        # Search-scraper places already nest their posts (33/42 live); fetch only places without a posts list
        # (instagram-scraper returns the same top posts). VERIFIED LIVE 2026-10-09 (T4): a place URL returns ONE
        # place item with nested posts for resultsType "posts" and "details" alike, never post items, charged 1
        # result per place; several places per run pair safely by location_id (never by inputUrl).
        no_posts = {_str(it.get("location_id")) for it in items if isinstance(it, dict) and not isinstance(it.get("posts"), list)}
        top = [p.location_id for p in kept if p.location_id in no_posts][:MAX_PLACES_FOR_POSTS]
        if top:
            items = await self._run(ACT_IG_SCRAPER, ig_location_input(top, "details", 1),
                                    units=len(top), label=tr(f"posty z {len(top)} míst", f"posts from {_en(len(top), 'place')}"))
            for it in items:
                pl = map_ig_place(it, now=now) if isinstance(it, dict) else None
                if pl and pl.location_id in ids:
                    for h in pl.authors:
                        refs.append(ref(h, pl.location_id, ACT_IG_SCRAPER, ig_location_url(pl.location_id)))
        return refs, ids

    async def _tt_search(self, keyword: str, now: datetime) -> list[CandidateRef]:
        proxy = tiktok_proxy()
        units = TT_SEARCH_PROFILES * TT_SEARCH_PER_PAGE   # changelog: finds profiles, then their videos
        per_unit = PRICE_USD[ACT_TT] + (PRICE_TT_PROXY_CZ if proxy == "CZ" else 0.0)
        items = await self._run(ACT_TT, tt_search_input(keyword, proxy=proxy), units=units,
                                est_usd=units * per_unit + START_FEE_USD[ACT_TT], label=tr(f"TikTok hledání „{keyword}“", f"TikTok search „{keyword}“"))
        minor_items = [it for it in items if isinstance(it, dict) and not error_of(it) and raw_minor(it, "tiktok")]
        bad = {_scan_tiktok_handle(it) for it in minor_items}
        # drop the minor's items AND any other video of the same account
        refs = [r for r in map_tt_search([it for it in items if it not in minor_items], query=keyword, actor=ACT_TT,
                                         fetched_at=now) if r.handle not in bad]
        invalid = sorted({h for h in (_scan_tiktok_handle(it) for it in items if isinstance(it, dict) and not error_of(it))
                          if h and not valid_tiktok_handle(h)})
        if invalid:
            await self._log(tr(f"TikTok „{keyword}“: neplatný handle vynechán: {len(invalid)} "
                               f"({', '.join('@' + h for h in invalid[:3])})",
                               f"TikTok „{keyword}“: invalid handle left out: {len(invalid)} "
                               f"({', '.join('@' + h for h in invalid[:3])})"), ACT_TT)
        if minor_items:
            await self._log(tr(f"TikTok „{keyword}“: mladší 18 let vynecháno: {len(bad - {None}) or len(minor_items)} "
                               "(nic se neukládá)",
                               f"TikTok „{keyword}“: under 18 left out: {len(bad - {None}) or len(minor_items)} "
                               "(nothing is stored)"), ACT_TT)
        return refs

    # ------------------------------------------------------------------ profiles

    @_safe("profiles")
    async def profiles(self, handles: list[str], platform: Platform) -> list[Profile]:
        wanted = list(dict.fromkeys(h for h in (norm_handle(x) for x in handles) if h))
        if not wanted:
            return []
        now = utcnow()
        if platform == "instagram":
            found = await self._ig_profiles(wanted, now)
        elif platform == "tiktok":
            found = await self._tt_profiles(wanted, now)
        else:
            await self._log(tr(f"profiles: platforma {platform} není podporovaná; vracím []",
                               f"profiles: platform {platform} is not supported; returning []"))
            return []
        minors = [p for p in found.values() if is_minor(p)]
        out = [found[h] for h in wanted if h in found and not is_minor(found[h])]
        extra = [h for h, p in found.items() if h not in wanted and not is_minor(p)]
        missing = [h for h in wanted if h not in found]
        msg = f"profiles {platform}: {len(out)}/{len(wanted)}"
        msg_en = msg
        if missing:
            msg += f"; nenalezeno: {', '.join('@' + m for m in missing[:5])}" + ("…" if len(missing) > 5 else "")
            msg_en += f"; not found: {', '.join('@' + m for m in missing[:5])}" + ("…" if len(missing) > 5 else "")
        if extra:
            # VERIFY LIVE: renamed accounts (not tested on 9. 10.) come back under the new handle; without the
            # requested name in the item we cannot fill former_handles, so they are not returned. A missing
            # handle comes back as an error item {username, url, error "not_found"}, charged 0.0026 (T5).
            msg += f"; vráceno pod jiným jménem (nepárováno): {', '.join('@' + h for h in extra[:5])}"
            msg_en += f"; returned under another name (not paired): {', '.join('@' + h for h in extra[:5])}"
        if minors:
            msg += f"; mladší 18 let vynecháno: {len(minors)} (nic se neukládá)"
            msg_en += f"; under 18 left out: {len(minors)} (nothing is stored)"
        await self._log(tr(msg, msg_en), ACT_IG_PROFILE if platform == "instagram" else ACT_TT_PROFILE)
        return out

    async def _ig_profiles(self, wanted: list[str], now: datetime) -> dict[str, Profile]:
        found: dict[str, Profile] = {}
        for i in range(0, len(wanted), PROFILE_BATCH):
            chunk = wanted[i:i + PROFILE_BATCH]
            items = await self._run(ACT_IG_PROFILE, ig_profile_input(chunk), units=len(chunk),
                                    label=tr(f"profily IG ({len(chunk)})", f"Instagram profiles ({len(chunk)})"),
                                    timeout_s=PROFILE_RUN_TIMEOUT_S)
            await self._log_missing_username(items)
            for it in items:
                p = map_ig_profile(it, actor=ACT_IG_PROFILE, fetched_at=now, requested=chunk) \
                    if isinstance(it, dict) else None
                if p:
                    found.setdefault(p.handle, p)   # a handle fallback must never overwrite a matched profile
        # Open issue: a public profile sometimes comes back with empty latestPosts (run SUCCEEDED).
        # Retry those once; never eliminate for it.
        empty = [h for h, p in found.items()
                 if p.private is False and not p.latest_posts and (p.posts_count or 0) > 0 and not is_minor(p)]
        if empty:
            items = await self._run(ACT_IG_PROFILE, ig_profile_input(empty), units=len(empty),
                                    label=tr(f"profily IG bez postů, opakování ({len(empty)})",
                                             f"Instagram profiles without posts, retry ({len(empty)})"),
                                    timeout_s=PROFILE_RUN_TIMEOUT_S)
            for it in items:
                p = map_ig_profile(it, actor=ACT_IG_PROFILE, fetched_at=now, requested=empty) \
                    if isinstance(it, dict) else None
                if p and p.latest_posts:
                    found[p.handle] = p
        return found

    async def _log_missing_username(self, items: list) -> None:
        """Guard only: VERIFIED LIVE 2026-10-09 (T5) profile-scraper items carry `username` (9/9), so this stays silent."""
        n = sum(1 for it in items if isinstance(it, dict) and not error_of(it) and not _str(it.get("username")))
        if n:
            await self._log(tr(f"profily IG: {n} bez pole username, handle vzat z latestPosts[].ownerUsername "
                               "nebo z požadavku",
                               f"Instagram profiles: {n} without a username field, handle taken from "
                               "latestPosts[].ownerUsername or the request"), ACT_IG_PROFILE)

    async def _tt_profiles(self, wanted: list[str], now: datetime, per_page: int = TT_PROFILE_VIDEOS) -> dict[str, Profile]:
        found: dict[str, Profile] = {}
        invalid = [h for h in wanted if not valid_tiktok_handle(h)]
        if invalid:
            # an invalid username comes back as a charged INVALID_URLS item (Brno run 9. 10. 2026: "@jídlo")
            await self._log(tr(f"profily TikTok: neplatný handle (povoleno A-Z a-z 0-9 _ . a 2 až 24 znaků), "
                               f"nespouštím: {', '.join('@' + h for h in invalid[:5])}",
                               f"TikTok profiles: invalid handle (A-Z a-z 0-9 _ . and 2 to 24 characters allowed), "
                               f"not starting: {', '.join('@' + h for h in invalid[:5])}"), ACT_TT_PROFILE)
            wanted = [h for h in wanted if h not in invalid]
        for i in range(0, len(wanted), TT_PROFILE_BATCH):
            chunk = wanted[i:i + TT_PROFILE_BATCH]
            items = await self._run(ACT_TT_PROFILE, tt_profile_input(chunk, per_page), units=len(chunk) * per_page,
                                    label=tr(f"profily TikTok ({len(chunk)})", f"TikTok profiles ({len(chunk)})"),
                                    timeout_s=PROFILE_RUN_TIMEOUT_S)
            empty = [it for it in items if isinstance(it, dict) and _str(it.get("errorCode")) == "PROFILE_EMPTY"]
            if empty:
                await self._log(tr(f"profily TikTok: PROFILE_EMPTY u {len(empty)} (mezera, i login zeď; nevyřazujeme)",
                                   f"TikTok profiles: PROFILE_EMPTY for {len(empty)} (a gap, possibly a login wall; "
                                   "not eliminated)"), ACT_TT_PROFILE)
            for p in map_tt_profiles(items, actor=ACT_TT_PROFILE, fetched_at=now, requested=chunk):
                found[p.handle] = p
        return found

    # ------------------------------------------------------------------ posts

    @_safe("posts")
    async def posts(self, handle: str, platform: Platform, since: datetime, limit: int = 50) -> list[Post]:
        h = norm_handle(handle)
        lim = max(1, min(POSTS_MAX, int(limit)))
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        now = utcnow()
        if platform == "instagram":
            detail = post_detail_level()
            per = PRICE_USD[ACT_IG_POST] if detail == "detailedData" else PRICE_IG_POST_BASIC
            items = await self._run(ACT_IG_POST, ig_post_input([h], lim, detail), units=lim, est_usd=lim * per,
                                    worst_usd=lim * (per + PRICE_IG_MUSIC_DATA), label=tr(f"posty @{h} ({detail})", f"posts @{h} ({detail})"))
            trust_false = detail == "detailedData" and TRUST_IG_FALSE_LABEL
            posts = [map_ig_post(it, actor=ACT_IG_POST, fetched_at=now, default_author=h,
                                 trust_false_label=trust_false)
                     for it in items if isinstance(it, dict)]
        elif platform == "tiktok":
            if not valid_tiktok_handle(h):
                await self._log(tr(f"videa @{h}: neplatný TikTok handle, nespouštím (stál by účtovanou chybovou položku)",
                                   f"videos @{h}: invalid TikTok handle, not starting (it would cost a charged error item)"),
                                ACT_TT_PROFILE)
                return []
            items = await self._run(ACT_TT_PROFILE, tt_profile_input([h], lim), units=lim,
                                    label=tr(f"videa @{h}", f"videos @{h}"), timeout_s=PROFILE_RUN_TIMEOUT_S)
            if any(isinstance(it, dict) and raw_minor(it, "tiktok") for it in items):
                await self._log(tr(f"posty @{h}: účet mladší 18 let, nic se neukládá",
                                   f"posts @{h}: account under 18, nothing is stored"), ACT_TT_PROFILE)
                return []
            posts = [map_tt_video(it, actor=ACT_TT_PROFILE, fetched_at=now, default_author=h)
                     for it in items if isinstance(it, dict)]
        elif platform == "youtube":
            # live T12b: channel listing, newest first by `order` (the dataset is not in date order; sorted below)
            items = await self._run(ACT_YT, yt_channel_input(h, lim), units=lim, label=tr(f"videa YouTube @{h}", f"YouTube videos @{h}"))
            posts = [map_yt_video(it, actor=ACT_YT, fetched_at=now, default_author=h)
                     for it in items if isinstance(it, dict)]
        else:
            await self._log(tr(f"posts: platforma {platform} není podporovaná; vracím []",
                               f"posts: platform {platform} is not supported; returning []"))
            return []
        uniq: dict[str, Post] = {}
        for p in posts:   # basicData returns duplicates: dedupe by shortCode (= Post.id)
            if p is not None and p.id not in uniq:
                uniq[p.id] = p
        # onlyPostsNewerThan is buggy, so the date filter lives here
        out = sorted((p for p in uniq.values() if p.created_at >= since), key=lambda p: p.created_at, reverse=True)[:lim]
        # CachedProvider asks for the full list (since 1970) and filters by date when it reads the cache
        since_txt = f"od {since.date().isoformat()}" if since.year > 1970 else "bez filtru data (filtruje cache)"
        since_en = f"since {since.date().isoformat()}" if since.year > 1970 else "without a date filter (the cache filters)"
        await self._log(tr(f"posty @{h}: {len(out)} {since_txt} (staženo {len(uniq)})",
                           f"posts @{h}: {len(out)} {since_en} (fetched {len(uniq)})"),
                        {"instagram": ACT_IG_POST, "tiktok": ACT_TT_PROFILE}.get(platform, ACT_YT))
        return out

    # ------------------------------------------------------------------ comments

    @_safe("comments")
    async def comments(self, post_urls: list[str], per_post: int = 15) -> list[Comment]:
        per = max(1, min(COMMENTS_PER_POST_MAX, int(per_post)))
        urls = list(dict.fromkeys(u.strip() for u in post_urls if u and u.strip()))
        ig_all = [u for u in urls if "instagram." in u.lower()]
        tt_all = [u for u in urls if "tiktok." in u.lower() and "instagram." not in u.lower()]
        other = len(urls) - len(ig_all) - len(tt_all)
        ig, tt = ig_all[:COMMENT_POSTS_MAX], tt_all[:COMMENT_POSTS_MAX]
        over = len(ig_all) - len(ig) + len(tt_all) - len(tt)
        now = utcnow()
        out: list[Comment] = []
        if ig:
            out.extend(await self._ig_comments(ig, per, now))
        if tt:
            out.extend(await self._tt_comments(tt, per, now))
        msg = (f"komentáře: {_cs(len(out), 'komentář', 'komentáře', 'komentářů')} z {len(ig) + len(tt)} postů "
               "(jen text, bez jmen komentujících)")
        msg_en = (f"comments: {_en(len(out), 'comment')} from {_en(len(ig) + len(tt), 'post')} "
                  "(text only, no commenter names)")
        if other:
            msg += f"; nepodporované URL: {other}"
            msg_en += f"; unsupported URLs: {other}"
        if over:
            msg += f"; nad limit {COMMENT_POSTS_MAX} postů na platformu vynecháno: {over}"
            msg_en += f"; over the limit of {COMMENT_POSTS_MAX} posts per platform, left out: {over}"
            # not fetched: never cached as "no comments"
            _note_issue(tr("komentáře", "comments"), tr(f"nad limit vynecháno {over}", f"over the limit, left out {over}"))
        await self._log(tr(msg, msg_en), ACT_IG_COMMENT if ig else ACT_TT_COMMENTS)
        return out

    async def _ig_comments(self, urls: list[str], per: int, now: datetime) -> list[Comment]:
        by_code = {ig_shortcode(u): u for u in urls if ig_shortcode(u)}

        def requested(url: str | None) -> str | None:
            # CachedProvider keys comments by the REQUESTED URL; the actor may return another form
            # (/reel/ vs /p/, query string), so pair by shortcode.
            return by_code.get(ig_shortcode(url)) or (url if url in urls else None)

        counts: dict[str, int] = {}
        out: list[Comment] = []
        if comments_source() == "latest":
            detail_price = PRICE_USD[ACT_IG_POST]
            # skipPinnedPosts false: these are direct post URLs, a pinned one we asked for must come back
            items = await self._run(ACT_IG_POST, ig_post_input(urls, 1, "detailedData", skip_pinned=False),
                                    units=len(urls), est_usd=len(urls) * detail_price,
                                    worst_usd=len(urls) * (detail_price + PRICE_IG_MUSIC_DATA),
                                    label=tr(f"latestComments z {len(urls)} postů", f"latestComments from {_en(len(urls), 'post')}"))
            answered: set[str] = set()
            for it in items:
                if isinstance(it, dict):
                    url = requested(_str(it.get("url"))) or requested(f"https://www.instagram.com/p/{it.get('shortCode')}/")
                    if url:
                        if not error_of(it):
                            answered.add(url)
                        out.extend(map_ig_latest_comments(it, actor=ACT_IG_POST, fetched_at=now, per_post=per, post_url=url))
            gaps = [u for u in urls if u not in answered]
            if gaps:
                # one post item per URL comes back, even with no comments: a URL without one was not fetched
                # (deleted post, block, cut-off run), never cached as "no comments"
                _note_issue("latestComments", tr(f"bez položky postu: {len(gaps)}", f"no post item: {len(gaps)}"))
            return out
        items = await self._run(ACT_IG_COMMENT, ig_comment_input(urls, per), units=len(urls) * per,
                                label=tr(f"komentáře IG ({len(urls)} postů × {per})",
                                         f"Instagram comments ({_en(len(urls), 'post')} × {per})"))
        for it in items:
            if not isinstance(it, dict):
                continue
            url = requested(_str(it.get("postUrl"))) or (urls[0] if len(urls) == 1 else None)
            if not url or counts.get(url, 0) >= per:
                continue
            c = map_ig_comment(it, actor=ACT_IG_COMMENT, fetched_at=now, index=counts.get(url, 0) + 1, post_url=url)
            if c:
                counts[url] = counts.get(url, 0) + 1
                out.append(c)
        return out

    async def _tt_comments(self, urls: list[str], per: int, now: datetime) -> list[Comment]:
        by_vid = {tt_video_ref(u)[1]: u for u in urls if tt_video_ref(u)}
        items = await self._run(ACT_TT_COMMENTS, tt_comments_input(urls, per), units=len(urls) * per,
                                label=tr(f"komentáře TikTok ({len(urls)} videí × {per})",
                                         f"TikTok comments ({_en(len(urls), 'video')} × {per})"))
        counts: dict[str, int] = {}
        out: list[Comment] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            ref = tt_video_ref(_str(it.get("videoWebUrl")))
            url = (by_vid.get(ref[1]) if ref else None) or (urls[0] if len(urls) == 1 else None)
            if not url or counts.get(url, 0) >= per:
                continue
            c = map_tt_comment(it, actor=ACT_TT_COMMENTS, fetched_at=now, index=counts.get(url, 0) + 1, post_url=url)
            if c:
                counts[url] = counts.get(url, 0) + 1
                out.append(c)
        return out

    # ------------------------------------------------------------------ collabs, news

    @_safe("collabs")
    async def collabs(self, handle: str, platform: Platform) -> list[CollabEvidence]:
        h = norm_handle(handle)
        if platform != "instagram":
            await self._log(tr(f"collabs @{h}: Meta Branded Content jen pro Instagram/Facebook; vracím []",
                               f"collabs @{h}: Meta Branded Content covers Instagram/Facebook only; returning []"), ACT_BRAND)
            return []
        if not _env_flag("APIFY_META_BRANDED"):
            # live T8 (9. 10. 2026): rohlik.cz gave no_items (still charged 0.0058), nike 3 rows: Czech collabs are
            # not visible without a login, so the path is cut; spolupráce come from the posts' labels and captions.
            await self._log(tr(f"collabs @{h}: Meta Branded Content vypnuto (živý test T8: české účty bez přihlášení "
                               "nevracejí nic); zapni APIFY_META_BRANDED=1",
                               f"collabs @{h}: Meta Branded Content off (live test T8: Czech accounts return nothing "
                               "without a login); APIFY_META_BRANDED=1 turns it on"), ACT_BRAND)
            return []
        now = utcnow()
        items = await self._run(ACT_BRAND, brand_collab_input(ig_profile_url(h)), units=BRAND_RESULTS,
                                label=f"Meta Branded Content @{h}")
        out: list[CollabEvidence] = []
        skipped = 0
        for it in items:
            if not isinstance(it, dict) or error_of(it):
                continue
            ev = map_brand_collab(it, creator_handle=h, actor=ACT_BRAND, fetched_at=now)
            if not ev:
                skipped += 1
            out.extend(ev)
        msg = f"collabs @{h}: {_cs(len(out), 'záznam', 'záznamy', 'záznamů')} v Meta Branded Content"
        msg_en = f"collabs @{h}: {_en(len(out), 'record')} in Meta Branded Content"
        if not out:
            msg += " (nenalezeno v knihovně Meta = mezera, ne „nemá spolupráce“)"
            msg_en += " (not found in the Meta library = a gap, not \"has no collaborations\")"
        if skipped:
            msg += f"; řádky jiného tvůrce vynechány (účet na straně značky nebo cizí řádek): {skipped}"
            msg_en += f"; rows of another creator left out (the brand-side account or a foreign row): {skipped}"
        await self._log(tr(msg, msg_en), ACT_BRAND)
        return out

    @_safe("news")
    async def news(self, query: str, lang: str = "cs", region: str = "CZ", limit: int = 10) -> list[NewsItem]:
        q = " ".join((query or "").split())
        if not q:
            return []
        lim = max(1, min(NEWS_MAX, int(limit)))
        now = utcnow()
        items = await self._run(ACT_NEWS, news_input(q, region, lang, lim), units=lim, label=tr(f"zprávy „{q}“", f"news „{q}“"))
        out: list[NewsItem] = []
        seen: set[str] = set()
        google = 0
        for it in items:
            n = map_news(it, actor=ACT_NEWS, fetched_at=now) if isinstance(it, dict) else None
            if n and n.id not in seen:
                seen.add(n.id)
                google += "news.google." in n.url
                out.append(n)
        out = out[:lim]
        msg = f"zprávy „{q}“: {_cs(len(out), 'článek', 'články', 'článků')}"
        msg_en = f"news „{q}“: {_en(len(out), 'article')}"
        if google:
            msg += f"; {google} s URL Googlu (decodeUrls nezabral)"
            msg_en += f"; {google} with a Google URL (decodeUrls did not work)"
        await self._log(tr(msg, msg_en), ACT_NEWS)
        return out

    # ------------------------------------------------------------------ cross-platform

    @_safe("find_cross_platform")
    async def find_cross_platform(self, profile: Profile) -> list[Profile]:
        """Only accounts linked from bio / external URLs (no paid search). IG and TikTok links are
        fetched with the profile scrapers (one cheap call each); YouTube links come back link-only.
        A linked account that cannot be fetched (private, empty, dropped as a minor) is skipped."""
        links = [lk for lk in cross_platform_links(profile) if lk[0] != "tiktok" or valid_tiktok_handle(lk[1])][:3]
        if not links:
            await self._log(tr(f"cross-platform @{profile.handle}: v bio ani odkazech není jiný profil",
                               f"cross-platform @{profile.handle}: no other profile in the bio or links"))
            return []
        now = utcnow()
        out: list[Profile] = []
        for platform, h, url in links:
            if platform == "instagram":
                found = await self._ig_profiles([h], now)
            elif platform == "tiktok":
                found = await self._tt_profiles([h], now, per_page=6)
            else:
                out.append(link_only_profile(platform, h, url, profile, now))
                continue
            p = found.get(h)
            if p is not None and not is_minor(p):
                out.append(p)
        await self._log(tr(f"cross-platform @{profile.handle}: {len(out)} z {len(links)} odkazů "
                           f"({', '.join(f'{p}:@{h}' for p, h, _ in links)})",
                           f"cross-platform @{profile.handle}: {len(out)} of {_en(len(links), 'link')} "
                           f"({', '.join(f'{p}:@{h}' for p, h, _ in links)})"))
        return out

    # ------------------------------------------------------------------ cache hooks

    def cache_variant(self, method: str) -> str | None:
        """Read by CachedProvider: a config switch that changes this method's answer becomes part of its cache key.
        collabs() with APIFY_META_BRANDED off answers [] without a run; that empty answer is cached under its own
        key, so switching Meta Branded Content on later is a miss (a real fetch), never a stale []. discover():
        APIFY_IG_SEARCH / APIFY_PLACES / APIFY_TIKTOK_SEARCH when not at their defaults (discover_variant)."""
        if method == "collabs" and not _env_flag("APIFY_META_BRANDED"):
            return "meta_branded_off"
        if method == "discover":
            return discover_variant()
        return None

    def cache_hit(self, method: str, items: list) -> list:
        """Read by CachedProvider on every cache hit (offline replays too): re-applies mapper rules that are newer
        than the entry. Idempotent. IG profiles: mark_leading_pinned on latest_posts, so profiles cached before the
        Brno run of 9. 10. 2026 get their unflagged pins inferred (else the 0.2 posts per week case replays)."""
        if method not in ("profiles", "find_cross_platform"):
            return items
        out = []
        for p in items:
            if isinstance(p, Profile) and p.platform == "instagram" and p.latest_posts:
                marked = mark_leading_pinned(p.latest_posts)
                if [x.is_pinned for x in marked] != [x.is_pinned for x in p.latest_posts]:
                    p = p.model_copy(update={"latest_posts": marked})
            out.append(p)
        return out
