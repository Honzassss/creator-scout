#!/usr/bin/env python3
"""Live tests T1-T12 of the Apify actors (docs/apify-pro-krystofa.md, section "Prvních 45 minut").

Run from the repo root with the backend venv:

  backend/.venv/bin/python scripts/live_tests.py --dry-run              # plan + estimates, no token needed
  backend/.venv/bin/python scripts/live_tests.py                        # all tests, asks once before the first run
  backend/.venv/bin/python scripts/live_tests.py --only T1,T5 --yes     # selected tests, no question
  backend/.venv/bin/python scripts/live_tests.py --only T5 --rerun      # run a test again that already has data
  backend/.venv/bin/python scripts/live_tests.py --report-only          # rebuild report.md from the saved data
  backend/.venv/bin/python scripts/live_tests.py --purge                # delete data/live-tests/ after the hackathon

What it does
- One builder per test with the inputs copied from the handoff. Inputs the handoff leaves open come from the
  saved output of earlier tests (T4 <- T2/T3, T5 <- T1/T3, T6 <- T3/T5, T7 <- T5) or from CLI options. Paid
  add-ons without a schema default (TikTok comments and followers, etc.) are sent explicitly as 0 / false.
- Cost: only max_total_charge_usd bounds what a run can cost (live: a run with maxItems 40 was charged for 42
  results, so max_items is a hint, not a limit). The script refuses to start anything when the installed
  apify-client cannot send max_total_charge_usd. --budget (default 6 USD) is checked before each test and each
  run against the finished runs (max(usageTotalUsd, worst-case estimate, items x unit price); the run cap when
  the run raised) plus the caps of runs in flight. A run cap never exceeds the remaining budget.
- A run that raised is never started again (it may already be paid); only a FAILED run without items gets one
  more attempt. A test whose data this script already saved is skipped unless --rerun is given; --rerun
  moves the previous file to <T>.<UTC timestamp>.json before writing the new one.
- Saves the dataset items to data/live-tests/<T>.json (data/ is gitignored; --out may only point inside
  <DATA_DIR>/live-tests). Commenter and liker identity and tagged people's names are redacted and items of
  bio-stated minors are dropped before anything is written (handoff, "Společná pravidla").
- Writes data/live-tests/report.md: field statistics, pass/fail against the handoff criterion, the answered
  "# VERIFY LIVE" items, and an offline run of the provider's pure mappers on the saved items. The report
  holds counts, field names, enum values, URLs and the handles of tested public accounts only: no captions,
  comment texts, commenter names, display names or bios.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import math
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402  (importing it loads /.env)
from app.models import norm_handle  # noqa: E402
from app.sources import apify_provider as ap  # noqa: E402
from app.sources.apify_provider import (  # noqa: E402
    ACT_BRAND,
    ACT_IG_COMMENT,
    ACT_IG_HASHTAG,
    ACT_IG_POST,
    ACT_IG_PROFILE,
    ACT_IG_SCRAPER,
    ACT_IG_SEARCH,
    ACT_NEWS,
    ACT_TT,
    ACT_TT_PROFILE,
)

ACT_YT = "streamers/youtube-scraper"
PRICE_YT = 0.004                     # per video on Free (handoff, actor 13); the provider never calls YouTube
TEST_KEYS = tuple(f"T{i}" for i in range(1, 13))
DEPS: dict[str, tuple[str, ...]] = {"T4": ("T2", "T3"), "T5": ("T1", "T3"), "T6": ("T3", "T5"), "T7": ("T5", "T6")}
MAX_CONCURRENCY = 5                  # Apify Free: max 5 concurrent runs
DEFAULT_CREATOR = "kamvbrne"         # handoff T5/T6: Brno food media account, not a creator; replace via --creator
T4_FALLBACK_LOCATION = "270309914"   # handoff T4: Bakeshop Praha from the README, data-shape test only
BRNO_CENTER = (49.1951, 16.6068)
REDACTED = "[redacted]"
DEFAULT_T10 = ["apifytech", "khaby.lame"]
DEFAULT_T12 = ["https://www.youtube.com/watch?v=JsBZOcqZerk", "https://www.youtube.com/watch?v=1H20xp8Brnc"]
# clockworks TikTok actors (schema of 8. 10. 2026): these paid add-ons have no default, only a prefill of 0
# (follower-dataset-item is billed per follower). Handoff: limits always explicit.
TT_OFF = {"commentsPerPost": 0, "topLevelCommentsPerPost": 0, "maxRepliesPerComment": 0,
          "maxFollowersPerProfile": 0, "maxFollowingPerProfile": 0}

UNIT = {
    ACT_IG_SEARCH: "výsledků", ACT_IG_HASHTAG: "postů", ACT_IG_SCRAPER: "položek", ACT_IG_PROFILE: "profilů",
    ACT_IG_POST: "postů", ACT_IG_COMMENT: "komentářů", ACT_BRAND: "řádků", ACT_TT: "výsledků",
    ACT_TT_PROFILE: "videí", ACT_NEWS: "článků", ACT_YT: "videí",
}

# =============================================================================================
# Small helpers
# =============================================================================================

_MISSING = object()
SAFE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{0,48}")
SAFE_ENUM = re.compile(r"[\w .,:/&+()'\-]{1,40}", re.UNICODE)


def fold(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def s(v: Any) -> str | None:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return None


def nonempty(v: Any) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(str(v))
    except ValueError:
        return None


def csv_list(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def jsonable(x: Any) -> Any:
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    dump = getattr(x, "model_dump", None)
    if callable(dump):
        try:
            return jsonable(dump(mode="json"))
        except Exception:  # noqa: BLE001
            pass
    return str(x)


def usd(x: float | None, digits: int = 3) -> str:
    return "?" if x is None else f"{x:.{digits}f}"


def pct(a: int, b: int) -> str:
    return "–" if not b else f"{round(100 * a / b)} %"


def safe_text(v: Any, limit: int = 160) -> str:
    return " ".join(str(v or "").split())[:limit]


def enum_val(v: Any) -> str:
    """Render a value of a whitelisted enum-like field. Free text never passes (shown as <text>)."""
    if v is _MISSING:
        return "chybí"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        t = v.strip()
        if not t:
            return '""'
        if not SAFE_ENUM.fullmatch(t):
            return "<text>"
        return f'"{t}"' if "," in t else t
    if isinstance(v, list):
        return "<list>"
    if isinstance(v, dict):
        return "<object>"
    return "<?>"


def type_name(v: Any) -> str:
    if v is _MISSING:
        return "chybí"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "str" if v.strip() else "str (prázdný)"
    if isinstance(v, list):
        return "list" if v else "list (prázdný)"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def key_name(k: Any) -> str:
    k = str(k)
    return k if SAFE_KEY.fullmatch(k) else "<jiný klíč>"


def fmt_counter(c: Counter, top: int = 8) -> str:
    if not c:
        return "–"
    items = c.most_common()
    out = ", ".join(f"{k} {v}" for k, v in items[:top])
    return out + (f", … (+{len(items) - top} dalších)" if len(items) > top else "")


def length_stats(values: list[Any]) -> str:
    lens = [len(v) for v in values if isinstance(v, list)]
    other = len(values) - len(lens)
    if not lens:
        return f"n=0 (chybí nebo není pole: {other})" if other else "n=0"
    out = (f"n={len(lens)} · prázdné {sum(1 for x in lens if x == 0)} · min/medián/max "
           f"{min(lens)}/{statistics.median(lens):g}/{max(lens)}")
    return out + (f" · chybí nebo není pole {other}" if other else "")


def values_at(item: Any, path: str) -> list[Any]:
    """Values at a dotted path; ``a[].b`` walks the list ``a``. Missing -> [_MISSING] (top) or [] (in lists)."""
    if not isinstance(item, dict):
        return []
    if "[]." in path:
        head, tail = path.split("[].", 1)
        lst = item.get(head)
        out: list[Any] = []
        if isinstance(lst, list):
            for el in lst:
                if isinstance(el, dict):
                    out.extend(values_at(el, tail))
        return out
    cur: Any = item
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return [_MISSING]
        cur = cur[part]
    return [cur]


def str_at(item: Any, path: str) -> str | None:
    vals = values_at(item, path)
    return s(vals[0]) if vals else None


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def yt_id(u: str | None) -> str | None:
    if not u:
        return None
    p = urlparse(u)
    q = parse_qs(p.query).get("v")
    if q:
        return q[0]
    if "youtu.be" in p.netloc:
        return p.path.strip("/") or None
    m = re.search(r"/(?:shorts|embed|live)/([\w-]{6,})", p.path)
    return m.group(1) if m else None


def host_of(u: str | None) -> str:
    h = urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def post_url(item: dict) -> str | None:
    u = s(item.get("url"))
    if u:
        return u
    code = s(item.get("shortCode"))
    return f"https://www.instagram.com/p/{code}/" if code else None


def fmt_input(inp: Any, max_list: int = 3) -> str:
    """Compact JSON for the report; long lists are cut (first item + count)."""
    def cut(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: cut(v) for k, v in x.items()}
        if isinstance(x, list):
            if len(x) > max_list:
                return [cut(x[0]), f"… (+{len(x) - 1})"]
            return [cut(v) for v in x]
        return x
    return json.dumps(cut(inp), ensure_ascii=False)


# =============================================================================================
# Saved data
# =============================================================================================


OURS_MARK = b"scripts/live_tests.py"
REPORT_TITLE = "# Živé testy Apify: výsledky"


def is_ours(p: Path) -> bool:
    """A data file this script wrote (its "_note" names the script within the first bytes)."""
    try:
        with p.open("rb") as fh:
            head = fh.read(400)
    except OSError:
        return False
    return b'"_note"' in head and OURS_MARK in head


def saved_path(out_dir: Path, key: str) -> Path:
    """<T>.json, unless that name holds a file this script did not write (another session saves raw lists
    under the same names): then <T>.live_tests.json, so nothing foreign is ever overwritten or parsed."""
    main, alt = out_dir / f"{key}.json", out_dir / f"{key}.live_tests.json"
    if alt.exists() or (main.exists() and not is_ours(main)):
        return alt
    return main


def report_path(out_dir: Path) -> Path:
    main = out_dir / "report.md"
    try:
        foreign = main.exists() and not main.read_text("utf-8")[:len(REPORT_TITLE)] == REPORT_TITLE
    except (OSError, UnicodeDecodeError):
        foreign = True
    return out_dir / "report.live_tests.md" if foreign else main


def load_saved(out_dir: Path, key: str) -> dict | None:
    p = saved_path(out_dir, key)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("runs"), list) else None


def runs_of(d: dict | None) -> list[dict]:
    return [r for r in (d or {}).get("runs", []) if isinstance(r, dict)]


def ran(r: dict) -> bool:
    return r.get("status") != "SKIPPED"


def is_stub(it: Any) -> bool:
    return isinstance(it, dict) and "_redacted" in it


def good_items(r: dict) -> list[dict]:
    return [i for i in r.get("items") or [] if isinstance(i, dict) and not is_stub(i) and not ap.error_of(i)]


def error_items(r: dict) -> list[Any]:
    return [i for i in r.get("items") or [] if not is_stub(i) and (not isinstance(i, dict) or ap.error_of(i))]


def stub_count(r: dict) -> int:
    return sum(1 for i in r.get("items") or [] if is_stub(i))


def all_good(d: dict | None) -> list[dict]:
    return [i for r in runs_of(d) for i in good_items(r)]


def error_kind(it: Any) -> str:
    if not isinstance(it, dict):
        return "není objekt"
    for k in ("errorCode", "error"):
        v = it.get(k)
        if v:
            return enum_val(v) if isinstance(v, str) else type_name(v)
    return "errorDescription"


def error_kinds(r: dict) -> str:
    return fmt_counter(Counter(error_kind(i) for i in error_items(r)), 5)


# ---------------------------------------------------------------- redaction before writing

_COMMENT_ID_KEYS = frozenset({
    "ownerUsername", "owner", "ownerProfilePicUrl", "ownerId", "ownerFullName", "username", "full_name",
    "fullName", "profile_pic_url", "profilePicUrl", "id", "commentUrl", "uid", "uniqueId", "avatarThumbnail",
    "nickname", "nickName", "user", "pk",    # user / pk: commenter in Instagram's raw comment shape
})
# Lists of commenters (or likers: strangers too). preview_comments / *top_likers are Instagram's raw shape
# (place items of instagram-scraper, T2 / T4), null in every live item so far.
_COMMENT_LIST_KEYS = frozenset({"latestComments", "replies", "childComments", "preview_comments",
                                "facepile_top_likers", "top_likers"})
_TAGGED_ID_KEYS = frozenset({"full_name", "fullName", "profile_pic_url", "profilePicUrl"})


def _scrub_comment(c: Any) -> None:
    """Commenter identity -> [redacted]; the keys stay so the item shape is still visible (VERIFY LIVE 10)."""
    if not isinstance(c, dict):
        return
    for k in list(c):
        if k in _COMMENT_ID_KEYS and nonempty(c[k]):
            c[k] = REDACTED
        elif k in _COMMENT_LIST_KEYS and isinstance(c[k], list):
            for x in c[k]:
                _scrub_comment(x)


def _redact_tagged(u: dict) -> None:
    """Tagged person: the name and picture go, the handle stays (VERIFY LIVE 10 needs the key shape)."""
    for kk in _TAGGED_ID_KEYS:
        if nonempty(u.get(kk)):
            u[kk] = REDACTED


def _walk_scrub(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in _COMMENT_LIST_KEYS and isinstance(v, list):
                for c in v:
                    _scrub_comment(c)
            elif k == "firstComment" and nonempty(v):
                obj[k] = {kk: REDACTED for kk in v} if isinstance(v, dict) else REDACTED
            elif k == "taggedUsers" and isinstance(v, list):
                for t in v:
                    if isinstance(t, dict):
                        _redact_tagged(t)
            elif k == "usertags" and isinstance(v, dict):
                # Instagram's raw shape (T2 / T4): posts[].usertags.in[].user and
                # posts[].carousel_media[].usertags.in[].user hold tagged strangers
                for t in v.get("in") or []:
                    u = t.get("user") if isinstance(t, dict) else None
                    if isinstance(u, dict):
                        _redact_tagged(u)
            else:
                _walk_scrub(v)
    elif isinstance(obj, list):
        for x in obj:
            _walk_scrub(x)


def _is_minor(actor: str, it: dict) -> bool:
    try:
        if actor in (ACT_TT, ACT_TT_PROFILE):
            return isinstance(it.get("authorMeta"), dict) and ap.raw_minor(it, "tiktok")
        if "biography" in it:
            return ap.raw_minor(it, "instagram")
    except Exception:  # noqa: BLE001
        return False
    return False


def scrub_items(actor: str, items: list[Any]) -> list[Any]:
    """Handoff rule: commenter identity is removed on load, before any cache; minors are dropped."""
    out: list[Any] = []
    for it in items:
        it = jsonable(it)   # rebuilds dicts and lists: the runner's objects stay untouched
        if isinstance(it, dict):
            if _is_minor(actor, it):
                out.append({"_redacted": "minor (věk pod 18 podle bio nebo isUnderAge18)"})
                continue
            if actor == ACT_IG_COMMENT:
                _scrub_comment(it)
            _walk_scrub(it)
        out.append(it)
    return out


# =============================================================================================
# Run specs and budget
# =============================================================================================


@dataclass
class RunSpec:
    label: str
    actor: str
    input: dict
    units: int                       # expected charged units (the handoff's limits)
    note: str = ""
    worst_units: int | None = None   # upper bound when the item shape is unknown (T9 /user)
    addon: float = 0.0               # per-unit paid add-on (TikTok CZ proxy)
    music: float = 0.0               # per-unit worst-case add-on (post-scraper music-data)
    timeout_s: int = ap.RUN_TIMEOUT_S
    placeholder: bool = False        # input not resolved yet (plan only)

    @property
    def price(self) -> float:
        return PRICE_YT if self.actor == ACT_YT else ap.PRICE_USD.get(self.actor, 0.005)

    @property
    def start_fee(self) -> float:
        return ap.START_FEE_USD.get(self.actor, 0.0)

    @property
    def estimate(self) -> float:
        return round(self.units * (self.price + self.addon) + self.start_fee, 4)

    @property
    def worst(self) -> float:
        n = self.worst_units or self.units
        return round(n * (self.price + self.addon + self.music) + self.start_fee, 4)

    @property
    def max_items(self) -> int:
        return max(1, self.worst_units or self.units)

    def plan_cap(self) -> float:
        return ap.charge_cap_usd(self.actor, self.worst, ap.max_usd_per_run())


@dataclass
class Built:
    runs: list[RunSpec]
    context: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    conditional: str = ""


@dataclass
class Skip:
    reason: str


class Budget:
    """Spent = finished runs (max(usageTotalUsd, worst estimate, items x unit price), or the run cap when usage
    is unknown);
    reserved = caps of runs in flight. A new run's cap is limited to what remains."""

    def __init__(self, limit: float) -> None:
        self.limit = float(limit)
        self.spent = 0.0
        self.reserved = 0.0
        self.reported = 0.0

    def remaining(self) -> float:
        return round(self.limit - self.spent - self.reserved, 4)

    def fits(self, amount: float) -> bool:
        return amount <= self.remaining() + 1e-9

    def reserve(self, spec: RunSpec) -> tuple[float | None, str]:
        rem = self.remaining()
        if spec.worst > rem + 1e-9:
            return None, f"rozpočet: běh potřebuje nejhůř {usd(spec.worst)} USD, zbývá {usd(rem)} USD"
        cap = ap.charge_cap_usd(spec.actor, spec.worst, min(ap.max_usd_per_run(), rem))
        cap = min(cap, math.floor(rem * 100) / 100)
        floor = max(ap.MIN_CHARGE_CAP_USD.get(spec.actor, 0.0), spec.estimate)
        if cap + 1e-9 < floor:
            return None, (f"rozpočet: zbývá {usd(rem)} USD, strop běhu by byl {usd(cap, 2)} USD, "
                          f"actor potřebuje aspoň {usd(floor, 2)} USD")
        self.reserved += cap
        return cap, ""

    def settle(self, cap: float, reported: float | None, spec: RunSpec, n_items: int = 0) -> None:
        """reported None = usage unknown (e.g. the run raised, yet may have been charged): the whole cap counts.
        Otherwise max(usageTotalUsd, worst estimate, items x worst unit price): the usageTotalUsd that call()
        returns is often read before the charges settle (0.0 or partial), and every dataset item is charged."""
        self.reserved = max(0.0, self.reserved - cap)
        if reported is None:
            self.spent += cap
            return
        per_item = n_items * (spec.price + spec.addon + spec.music) + (spec.start_fee if n_items else 0.0)
        self.spent += max(reported, spec.worst, per_item)
        self.reported += reported


# =============================================================================================
# Context and test inputs
# =============================================================================================


@dataclass
class Ctx:
    args: argparse.Namespace
    out_dir: Path
    interactive: bool = False

    def load(self, key: str) -> dict | None:
        return load_saved(self.out_dir, key)

    def ask(self, prompt: str) -> str:
        if not self.interactive:
            return ""
        try:
            return input(prompt).strip()
        except EOFError:
            return ""


def _queries(search: str) -> int:
    return len([q for q in search.split(",") if q.strip()])


def _mentions_brno(it: dict) -> bool:
    user = (s(it.get("username")) or "").replace("_", " ").replace(".", " ")
    text = " ".join(x for x in (user, s(it.get("fullName")), s(it.get("biography")),
                                s(it.get("businessCategoryName"))) if x)
    return ap.city_text_match("Brno", text)


def item_tags(item: dict, tags: list[str]) -> tuple[set[str], str]:
    """Which input hashtag(s) a hashtag-scraper item came from, and how we know."""
    tags = [norm_handle(t) for t in tags]
    for k in ("inputUrl", "query", "hashtag", "searchTerm", "input"):
        v = item.get(k)
        if isinstance(v, str):
            f = fold(v)
            hit = {t for t in tags if re.search(r"(?:tags/|#|^)" + re.escape(t) + r"(?:/|$|\b)", f)}
            if hit:
                return hit, k
    hs = {fold(h).lstrip("#") for h in item.get("hashtags") or [] if isinstance(h, str)}
    hit = {t for t in tags if t in hs}
    if hit:
        return hit, "hashtags"
    cap = fold(item.get("caption"))
    hit = {t for t in tags if f"#{t}" in cap}
    return (hit, "caption") if hit else (set(), "nepřiřazeno")


_AD_TAGS = {"spoluprace", "reklama", "ad", "sponzorovano", "placenapartnerstvi", "paidpartnership"}


def _looks_like_ad(p: dict) -> bool:
    hs = {fold(h).lstrip("#") for h in p.get("hashtags") or [] if isinstance(h, str)}
    if hs & _AD_TAGS:
        return True
    cap = fold(p.get("caption"))
    return any(m in cap for m in ("#spoluprac", "#reklam", "placene partnerstvi", "placena spoluprace"))


def pick_t2_location(t2: dict | None) -> tuple[str | None, str]:
    first = None
    for it in all_good(t2):
        loc = s(it.get("location_id"))
        if not loc:
            continue
        if ap.in_city_bbox("brno", num(it.get("lat")), num(it.get("lng"))):
            return loc, "T2 (první místo v CITY_BBOX Brna)"
        first = first or loc
    return (first, "T2 (první místo s location_id; žádné v CITY_BBOX)") if first else (None, "")


def pick_t3_location(t3: dict | None, exclude: str | None) -> str | None:
    c = Counter(s(i.get("locationId")) for i in all_good(t3) if s(i.get("locationId")))
    for loc, _ in c.most_common():
        if loc != exclude:
            return loc
    return None


def pick_t5_names(ctx: Ctx, exclude: set[str], n: int = 20) -> tuple[list[str], str]:
    t1, t3 = ctx.load("T1"), ctx.load("T3")
    a = [norm_handle(s(i.get("username")) or "") for i in all_good(t1) if i.get("private") is not True]
    b = [norm_handle(s(i.get("ownerUsername")) or "") for i in all_good(t3)]
    out: list[str] = []
    for x in (y for pair in zip_longest(a, b) for y in pair):
        if x and x not in exclude and x not in out:
            out.append(x)
        if len(out) >= n:
            break
    src = " + ".join(k for k, lst in (("T1", a), ("T3", b)) if any(x in out for x in lst))
    return out, src


def pick_t6_urls(ctx: Ctx, n: int = 5) -> tuple[list[str], str]:
    out: list[str] = []
    src: list[str] = []
    t3 = ctx.load("T3")
    if t3:
        tags = (runs_of(t3)[0].get("input") or {}).get("hashtags") or ["brnofood", "spoluprace"]
        spol = [i for i in all_good(t3) if "spoluprace" in item_tags(i, tags)[0]]
        spol.sort(key=lambda i: i.get("paidPartnership") is not True)    # labelled first
        for i in spol:
            u = post_url(i)
            if u and u not in out and ap.ig_shortcode(u):
                out.append(u)
        if out:
            src.append("T3")
    if len(out) < n:
        before = len(out)
        for prof in all_good(ctx.load("T5")):
            for p in prof.get("latestPosts") or []:
                if isinstance(p, dict) and _looks_like_ad(p):
                    u = post_url(p)
                    if u and u not in out and ap.ig_shortcode(u):
                        out.append(u)
        if len(out) > before:
            src.append("T5")
    return out[:n], "+".join(src) or "none"


def pick_t7_urls(ctx: Ctx, n: int = 3) -> list[str]:
    posts = []
    for prof in all_good(ctx.load("T5")):
        if prof.get("private") is True:
            continue
        for p in prof.get("latestPosts") or []:
            if isinstance(p, dict) and p.get("isPinned") is not True and ap.ig_shortcode(post_url(p)):
                posts.append(p)
    posts.sort(key=lambda p: num(p.get("commentsCount")) or 0, reverse=True)
    out: list[str] = []
    for p in posts:
        u = post_url(p)
        if u not in out:
            out.append(u)
        if len(out) >= n:
            break
    return out


def split_post_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    """(post URLs, the rest). A profile URL given to instagram-post-scraper pulls 12 posts instead of 1."""
    return [u for u in urls if ap.ig_shortcode(u)], [u for u in urls if not ap.ig_shortcode(u)]


def t6_has_latest_comments(t6: dict | None) -> bool:
    return any(nonempty(i.get("latestComments")) for i in all_good(t6))


# =============================================================================================
# Builders T1..T12 (inputs copied from the handoff, section "Prvních 45 minut")
# =============================================================================================


def b_t1(ctx: Ctx, live: bool) -> Built | Skip:
    base = {"search": "cukrárna brno, brno food", "searchType": "user", "searchLimit": 20,
            "enhanceUserSearchWithFacebookPage": False}
    n = _queries(base["search"]) * base["searchLimit"]
    return Built([RunSpec("T1a", ACT_IG_SEARCH, base, n, "searchType user"),
                  RunSpec("T1b", ACT_IG_SEARCH, {**base, "liveSearch": True}, n, "totéž s liveSearch")])


def b_t2(ctx: Ctx, live: bool) -> Built | Skip:
    base = {"search": "cukrárna brno, kavárna brno, pekárna brno", "searchType": "place", "searchLimit": 30,
            "enhanceUserSearchWithFacebookPage": False}
    n = _queries(base["search"]) * base["searchLimit"]
    return Built([RunSpec("T2a", ACT_IG_SEARCH, base, n, "searchType place"),
                  RunSpec("T2b", ACT_IG_SEARCH, {**base, "liveSearch": True}, n, "totéž s liveSearch (jen tam je city)")])


def b_t3(ctx: Ctx, live: bool) -> Built | Skip:
    inp = {"hashtags": ["brnofood", "spoluprace"], "resultsType": "posts", "resultsLimit": 50, "keywordSearch": False}
    return Built([RunSpec("T3", ACT_IG_HASHTAG, inp, len(inp["hashtags"]) * inp["resultsLimit"],
                          "posty z hashtagů; URL z #spoluprace jdou do T6")])


def b_t4(ctx: Ctx, live: bool) -> Built | Skip:
    notes: list[str] = []
    placeholder = False
    if ctx.args.t4_location_id:
        loc, src = ctx.args.t4_location_id, "--t4-location-id"
    else:
        loc, src = pick_t2_location(ctx.load("T2"))
    if not loc:
        if live:
            loc, src = T4_FALLBACK_LOCATION, "záloha z předávky (Bakeshop Praha z README, jen tvar dat)"
            notes.append("T2 nedal žádné location_id: T4a/T4b běží na místě z README (Praha), ne z Brna")
        else:
            loc, src, placeholder = "<ID z T2>", f"doplní se z T2 (bez T2 záloha {T4_FALLBACK_LOCATION} z README)", True
    url = f"https://www.instagram.com/explore/locations/{loc}/"
    runs = [RunSpec("T4a", ACT_IG_SCRAPER, {"directUrls": [url], "resultsType": "posts", "resultsLimit": 20}, 20,
                    "URL místa, resultsType posts", placeholder=placeholder),
            RunSpec("T4b", ACT_IG_SCRAPER, {"directUrls": [url], "resultsType": "details", "resultsLimit": 20}, 20,
                    "URL místa, resultsType details", placeholder=placeholder)]
    t3_loc = pick_t3_location(ctx.load("T3"), None if placeholder else loc)
    if t3_loc:
        u3 = f"https://www.instagram.com/explore/locations/{t3_loc}/"
        runs.append(RunSpec("T4c", ACT_IG_SCRAPER, {"directUrls": [u3], "resultsType": "details", "resultsLimit": 20},
                            20, "locationId z T3 (souřadnice), resultsType details"))
    elif not live:
        u3 = "https://www.instagram.com/explore/locations/<locationId z T3>/"
        runs.append(RunSpec("T4c", ACT_IG_SCRAPER, {"directUrls": [u3], "resultsType": "details", "resultsLimit": 20},
                            20, "locationId z T3; jen když T3 nějaké vrátí", placeholder=True))
    else:
        notes.append("T4c vynechán: T3 nemá žádné locationId (nebo T3 neběžel)")
    notes.insert(0, f"místo: {src}")
    return Built(runs, {"location_id": loc, "location_source": src, "t3_location_id": t3_loc}, notes)


def b_t5(ctx: Ctx, live: bool) -> Built | Skip:
    creator = norm_handle(ctx.args.creator or DEFAULT_CREATOR)
    placeholder = False
    if ctx.args.t5_usernames:
        names, src = [norm_handle(x) for x in csv_list(ctx.args.t5_usernames)][:50], "--t5-usernames"
    else:
        names, src = pick_t5_names(ctx, {creator})
    if not names:
        if not live:
            names, src, placeholder = ["<20 až 50 jmen z T1 a T3>"], "doplní se z T1 a T3 (nebo --t5-usernames)", True
        else:
            ans = ctx.ask("T5: T1 ani T3 nedaly žádná jména. Zadej 20 až 50 veřejných IG účtů oddělených čárkou "
                          "(Enter = přeskočit T5): ")
            names = [norm_handle(x) for x in csv_list(ans)][:50]
            if not names:
                return Skip("chybí jména pro dávku: spusť nejdřív T1 a T3, nebo zadej --t5-usernames")
            src = "zadáno ručně"
    usernames = [creator] + [n for n in names if n != creator]
    units = 21 if placeholder else len(usernames)
    notes = [f"jména: {src}"]
    if creator == DEFAULT_CREATOR:
        notes.append("kamvbrne je mediální účet z předávky; skutečného tvůrce dej přes --creator")
    return Built([RunSpec("T5", ACT_IG_PROFILE, {"usernames": usernames, "includeAboutSection": False}, units,
                          "profily v dávce", timeout_s=ap.PROFILE_RUN_TIMEOUT_S, placeholder=placeholder)],
                 {"creator": creator, "usernames_source": src}, notes)


def b_t6(ctx: Ctx, live: bool) -> Built | Skip:
    creator = norm_handle(ctx.args.creator or DEFAULT_CREATOR)
    placeholder = False
    notes: list[str] = []
    if ctx.args.t6_post_urls:
        urls, src = csv_list(ctx.args.t6_post_urls)[:5], "cli"
    else:
        urls, src = pick_t6_urls(ctx)
    if not urls:
        if not live:
            urls, placeholder = ["<5 URL postů z T3 #spoluprace>"], True
            src = "doplní se z T3 #spoluprace (nebo --t6-post-urls)"
        else:
            ans = ctx.ask("T6: zadej až 5 URL postů se štítkem „Placené partnerství“ oddělených čárkou "
                          f"(Enter = jen 12 postů @{creator}): ")
            urls, bad = split_post_urls(csv_list(ans))
            urls = urls[:5]
            if bad:
                notes.append(f"vynecháno {len(bad)} zadání, která nejsou URL postu (/p/, /reel/, /tv/)")
            src = "prompt" if urls else "none"
    if src not in ("cli", "prompt") and not placeholder:
        notes.append("URL postů nejsou ověřeně štítkované; pro jistý verdikt zadej --t6-post-urls "
                     "s posty, které mají na IG štítek Placené partnerství")
    if live and not urls:
        notes.append(f"bez URL postů: běží jen 12 postů @{creator}")
    inp = {"username": [*urls, creator], "resultsLimit": 12, "skipPinnedPosts": True, "dataDetailLevel": "detailedData"}
    units = (5 if placeholder else len(urls)) + inp["resultsLimit"]
    notes.insert(0, f"URL postů: {src}")
    return Built([RunSpec("T6", ACT_IG_POST, inp, units, "štítek placeného partnerství, detailedData",
                          music=ap.PRICE_IG_MUSIC_DATA, placeholder=placeholder)],
                 {"creator": creator, "urls_source": src, "post_urls": [] if placeholder else urls}, notes)


def b_t7(ctx: Ctx, live: bool) -> Built | Skip:
    cond = ""
    if not ctx.args.force_t7:
        t6 = ctx.load("T6")
        if t6 is None:
            if live:
                return Skip("T7 běží jen když T6 nevrátí latestComments a T6 nemá uložená data (vynutíš --force-t7)")
            cond = "jen když T6 nevrátí latestComments (vynutíš --force-t7)"
        elif t6_has_latest_comments(t6):
            return Skip("T6 vrátil latestComments, comment-scraper není potřeba (vynutíš --force-t7)")
    placeholder = False
    if ctx.args.t7_post_urls:
        urls, src = csv_list(ctx.args.t7_post_urls)[:3], "--t7-post-urls"
    else:
        urls, src = pick_t7_urls(ctx), "T5 (latestPosts s nejvíc komentáři)"
    if not urls:
        if not live:
            urls, placeholder, src = ["<3 URL z latestPosts v T5>"], True, "doplní se z T5 (nebo --t7-post-urls)"
        else:
            urls = split_post_urls(csv_list(ctx.ask("T7: zadej 3 URL veřejných IG postů s komentáři "
                                                    "(Enter = přeskočit): ")))[0][:3]
            if not urls:
                return Skip("chybí URL postů: spusť T5, nebo zadej --t7-post-urls")
            src = "zadáno ručně"
    inp = {"directUrls": urls, "resultsLimit": 15}
    units = (3 if placeholder else len(urls)) * inp["resultsLimit"]
    return Built([RunSpec("T7", ACT_IG_COMMENT, inp, units, "komentáře (Free: 15 nejnovějších)", placeholder=placeholder)],
                 {"urls_source": src}, [f"URL postů: {src}"], cond)


def b_t8(ctx: Ctx, live: bool) -> Built | Skip:
    a = {"startUrls": ["https://www.instagram.com/rohlik.cz/"], "resultsLimit": 10, "onlyPostsNewerThan": "6 months"}
    b = {"startUrls": ["https://www.instagram.com/nike/"], "resultsLimit": 3, "onlyPostsNewerThan": "6 months"}
    return Built([RunSpec("T8a", ACT_BRAND, a, a["resultsLimit"], "rohlik.cz"),
                  RunSpec("T8b", ACT_BRAND, b, b["resultsLimit"], "kontrola, že actor funguje: nike")])


def b_t9(ctx: Ctx, live: bool) -> Built | Skip:
    base = {"searchQueries": ["cukrárna brno"], "searchSection": "/user", "maxProfilesPerQuery": 10, "resultsPerPage": 3}
    units = base["maxProfilesPerQuery"] * base["resultsPerPage"]
    worst = units + base["maxProfilesPerQuery"]   # if /user also returns one item per profile (shape unknown)
    return Built([RunSpec("T9a", ACT_TT, {**base, "proxyCountryCode": "CZ", **TT_OFF}, units, "s proxyCountryCode CZ",
                          worst_units=worst, addon=ap.PRICE_TT_PROXY_CZ),
                  RunSpec("T9b", ACT_TT, {**base, "proxyCountryCode": "None", **TT_OFF}, units,
                          "bez CZ proxy (A/B; \"None\" je výchozí hodnota schématu)", worst_units=worst)],
                 notes=["strop běhu je aspoň 0,50 USD (minimalMaxTotalChargeUsd actoru)"])


def b_t10(ctx: Ctx, live: bool) -> Built | Skip:
    profiles = [norm_handle(x) for x in csv_list(ctx.args.t10_profiles)] if ctx.args.t10_profiles else list(DEFAULT_T10)
    inp = {"profiles": profiles, "resultsPerPage": 3, "excludePinnedPosts": True, **TT_OFF}
    notes = [f"zahraniční účet (region nesmí vyjít CZ): @{profiles[-1]}"]
    return Built([RunSpec("T10", ACT_TT_PROFILE, inp, len(profiles) * inp["resultsPerPage"], "region a věk")],
                 {"foreign": profiles[-1]}, notes)


def b_t11(ctx: Ctx, live: bool) -> Built | Skip:
    inp = {"keywords": ["cukrárna Brno"], "region_language": "CZ:cs", "timeframe": "1y", "maxArticles": 10,
           "decodeUrls": True, "extractImages": False, "extractDescriptions": False}
    return Built([RunSpec("T11", ACT_NEWS, inp, inp["maxArticles"], "zprávy")])


def b_t12(ctx: Ctx, live: bool) -> Built | Skip:
    urls = csv_list(ctx.args.t12_urls) if ctx.args.t12_urls else list(DEFAULT_T12)
    inp = {"startUrls": [{"url": u} for u in urls], "maxResults": 1, "maxResultsShorts": 0, "maxResultStreams": 0}
    return Built([RunSpec("T12", ACT_YT, inp, len(urls), "štítek Includes paid promotion")],
                 {"paid_url": urls[0], "unpaid_url": urls[1]},
                 ["1. video má mít štítek Includes paid promotion, 2. ne (z předávky; ověř na YouTube)"])


# =============================================================================================
# Verdicts (pass/fail against the handoff criterion) and VERIFY LIVE answers
# =============================================================================================


@dataclass
class Verdict:
    status: str = "BEZ DAT"         # PASS | FAIL | RUČNĚ | BEZ DAT
    summary: str = ""
    lines: list[str] = field(default_factory=list)
    verify: list[tuple[int, str]] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)


def _ran_runs(d: dict) -> list[dict]:
    return [r for r in runs_of(d) if ran(r) and r.get("status") is not None]


def _events(r: dict) -> str:
    ev = r.get("charged_event_counts")
    if isinstance(ev, dict) and ev:
        return ", ".join(f"{key_name(k)} {v}" for k, v in ev.items())
    return "–"


def j_t1(d: dict) -> Verdict:
    v = Verdict()
    per: dict[str, tuple[int, int, set[str], set[str]]] = {}
    for r in _ran_runs(d):
        items = good_items(r)
        n = len(items)
        lp = sum(1 for i in items if nonempty(i.get("latestPosts")))
        g = [i for i in items if i.get("searchSource") == "google"]
        glp = sum(1 for i in g if nonempty(i.get("latestPosts")))
        rel = sum(1 for i in items if nonempty(i.get("relatedProfiles")))
        brno = [i for i in items if _mentions_brno(i)]
        blp = sum(1 for i in brno if nonempty(i.get("latestPosts")))
        users = {norm_handle(s(i.get("username")) or "") for i in items} - {""}
        keys = {k for i in items for k in i}
        per[r["label"]] = (len(brno), blp, users, keys)
        v.lines.append(f"{r['label']}: {n} profilů · searchSource {fmt_counter(Counter(enum_val(i.get('searchSource', _MISSING)) for i in items))}"
                       f" · s latestPosts {lp}/{n} · zdroj google s latestPosts {glp}/{len(g)}"
                       f" · relatedProfiles neprázdné {rel}/{n} · Brno v účtu, jménu, bio nebo kategorii {len(brno)}"
                       f" (z nich s latestPosts {blp})")
        v.verify.append((5, f"{r['label']}: relatedProfiles neprázdné u {rel}/{n} profilů ze search-scraperu"))
    if "T1a" in per and "T1b" in per:
        a, b = per["T1a"], per["T1b"]
        v.lines.append(f"liveSearch: společných účtů {len(a[2] & b[2])}, jen bez liveSearch {len(a[2] - b[2])}, "
                       f"jen s liveSearch {len(b[2] - a[2])}; klíče jen bez liveSearch: "
                       f"{', '.join(sorted(map(key_name, a[3] - b[3]))) or '–'}; jen s liveSearch: "
                       f"{', '.join(sorted(map(key_name, b[3] - a[3]))) or '–'}")
    if not per:
        return v
    ok = [lab for lab, (nb, blp, _, _) in per.items() if nb >= 10 and blp * 2 > nb]
    v.status = "PASS" if ok else "FAIL"
    best = (ok[0], per[ok[0]]) if ok else max(per.items(), key=lambda kv: kv[1][0])
    v.summary = (f"{best[0]}: {best[1][0]} účtů se zmínkou Brna, s latestPosts {best[1][1]} "
                 "(heuristika; relevanci ověř ručně v T1.json)")
    if not ok:
        v.advice.append("T1: hledání účtů jen jako doplněk, hlavní zdroj hashtagy a seznam od majitele; "
                        "profily bez latestPosts do profile-scraperu.")
    return v


def j_t2(d: dict) -> Verdict:
    v = Verdict()
    best = -1
    for r in _ran_runs(d):
        places = [i for i in good_items(r) if s(i.get("location_id"))]
        coords = [(num(i.get("lat")), num(i.get("lng"))) for i in places]
        coords = [(a, b) for a, b in coords if a is not None and b is not None]
        inbox = sum(1 for a, b in coords if ap.in_city_bbox("brno", a, b))
        near = [(a, b) for a, b in coords if km((a, b), BRNO_CENTER) <= 30]
        near_out = [c for c in near if not ap.in_city_bbox("brno", *c)]
        posts_t = Counter(type_name(i.get("posts", _MISSING)) for i in places)
        posts_ne = sum(1 for i in places if isinstance(i.get("posts"), list) and i["posts"])
        biz = sum(1 for i in places if s(ap._get(i, "ig_business", "profile", "username")))
        name = sum(1 for i in places if s(i.get("name")))
        city = sum(1 for i in places if s(i.get("city")))
        lcity = sum(1 for i in places if s(i.get("location_city")))
        best = max(best, inbox)
        v.lines.append(f"{r['label']}: {len(places)} míst · se souřadnicemi {len(coords)} · v CITY_BBOX Brna {inbox}"
                       f" · do 30 km od centra, ale mimo box {len(near_out)} · location_city vyplněné {lcity}"
                       f" · city vyplněné {city} · posts: {fmt_counter(posts_t)} (neprázdné pole {posts_ne})"
                       f" · ig_business.profile.username {biz} · name {name}")
        v.verify.append((6, f"{r['label']}: posts {fmt_counter(posts_t)}; name vyplněné {name}/{len(places)}"))
        rng = ""
        if near:
            lats, lngs = [a for a, _ in near], [b for _, b in near]
            rng = f"; rozsah do 30 km: lat {min(lats):.2f}–{max(lats):.2f}, lng {min(lngs):.2f}–{max(lngs):.2f}"
        v.verify.append((8, f"{r['label']}: {inbox} míst v boxu, {len(near_out)} do 30 km mimo box{rng}"))
        if near_out:
            v.advice.append(f"T2: {len(near_out)} míst do 30 km od Brna leží mimo CITY_BBOX, zvaž rozšíření boxu{rng}.")
    if best < 0:
        return v
    v.status = "PASS" if best >= 15 else "FAIL"
    v.summary = f"nejvíc {best} míst v Brně podle souřadnic (potřeba 15)"
    if best < 15:
        v.advice.append("T2: cestu „posty z míst“ škrtáme; Brno jen z textu (bio, popisky, locationName).")
    return v


def j_t3(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    r = rr[0]
    tags = [norm_handle(t) for t in (r.get("input") or {}).get("hashtags") or []]
    items = good_items(r)
    per: dict[str, list[dict]] = {t: [] for t in tags}
    methods: Counter = Counter()
    for i in items:
        ts, m = item_tags(i, tags)
        methods[m] += 1
        for t in ts:
            per.setdefault(t, []).append(i)
    for t, its in per.items():
        n = len(its)
        loc = sum(1 for i in its if s(i.get("locationId")))
        ln = sum(1 for i in its if s(i.get("locationName")))
        pp = Counter(enum_val(i.get("paidPartnership", _MISSING)) for i in its)
        owners = len({s(i.get("ownerUsername")) for i in its} - {None})
        v.lines.append(f"#{t}: {n} postů · s locationId {loc} ({pct(loc, n)}) · s locationName {ln}"
                       f" · paidPartnership {fmt_counter(pp)} · různých autorů {owners}")
    no_loc = sum(1 for i in items if not s(i.get("locationId")))
    v.lines.append(f"Celkem {len(items)} postů, bez místa (bez locationId) {no_loc} ({pct(no_loc, len(items))})")
    exact = "inputUrl" in methods or "query" in methods or "hashtag" in methods
    v.lines.append(f"Přiřazení k hashtagu podle: {fmt_counter(methods)}"
                   + ("" if exact else " (nepřesné: post s oběma tagy se počítá u obou)"))
    types = Counter(enum_val(i.get("type", _MISSING)) for i in items)
    v.lines.append(f"type: {fmt_counter(types)} · productType: "
                   f"{fmt_counter(Counter(enum_val(i.get('productType', _MISSING)) for i in items))}")
    v.verify.append((3, f"type v hashtag-scraperu: {fmt_counter(types)}"))
    counts = {t: len(per.get(t, [])) for t in tags}
    ok = bool(tags) and all(c >= 20 for c in counts.values()) and no_loc < len(items)
    v.status = "PASS" if ok else "FAIL"
    v.summary = "Free vrátil " + ", ".join(f"#{t} {c}" for t, c in counts.items()) + \
        f"; s locationId {len(items) - no_loc}/{len(items)}"
    if any(c < 10 for c in counts.values()):
        v.advice.append("T3: méně než 10 postů na hashtag, hashtagy jen jako doplněk (na 300 postů by bylo potřeba 15 a víc hashtagů).")
    return v


NESTED_AUTHOR = ("username", "ownerUsername", "user.username", "owner.username")
NESTED_LOCATION = ("locationId", "location_id", "location.pk", "location.id")


def j_t4(d: dict) -> Verdict:
    v = Verdict()
    ctx = d.get("context") or {}
    authors = coords = False
    latlng_types: set[str] = set()
    rr = _ran_runs(d)
    for r in rr:
        rt = (r.get("input") or {}).get("resultsType")
        items = good_items(r)
        place = [i for i in items if s(i.get("location_id"))]
        posts = [i for i in items if s(i.get("ownerUsername"))]
        ll = [i for i in items if num(i.get("lat")) is not None and num(i.get("lng")) is not None]
        nested = [p for i in place for p in (i.get("posts") or []) if isinstance(p, dict)]
        auth = Counter(next((path for path in NESTED_AUTHOR if str_at(p, path)), "nic") for p in nested)
        nloc = Counter(next((path for path in NESTED_LOCATION if str_at(p, path)), "nic") for p in nested)
        n_user = sum(c for k, c in auth.items() if k != "nic")
        post_loc = sum(1 for p in posts if s(p.get("locationId")))
        v.lines.append(f"{r['label']} (resultsType {rt}): {len(items)} položek · tvar: {len(place)} míst, {len(posts)} postů"
                       f" · lat/lng {len(ll)} · vnořené posts[] {len(nested)}: autor v {fmt_counter(auth)}; místo v "
                       f"{fmt_counter(nloc)} · posty s locationId {post_loc}/{len(posts)} · eventy {_events(r)}")
        v.verify.append((7, f"{r['label']} ({rt}): {len(place)} položek místa, {len(posts)} postů, lat/lng {len(ll)}, "
                            f"vnořené posty s autorem {n_user}/{len(nested)} ({fmt_counter(auth)}), "
                            f"posty s locationId {post_loc}/{len(posts)}"))
        if r["label"] in ("T4a", "T4b"):
            authors = authors or bool(posts) or n_user > 0
            if ll:
                coords = True
                latlng_types.add(str(rt))
        if r["label"] == "T4c":
            v.lines.append(f"T4c: locationId z T3 → souřadnice {'ano' if ll else 'ne'}")
    if not rr:
        return v
    v.status = "PASS" if authors and coords else "FAIL"
    v.summary = (f"autoři z URL místa: {'ano' if authors else 'ne'}, souřadnice: {'ano' if coords else 'ne'}"
                 + (f" (lat/lng dává resultsType {', '.join(sorted(latlng_types))})" if latlng_types else ""))
    if str(ctx.get("location_source", "")).startswith("záloha"):
        v.summary += "; místo z README (Praha), ne z Brna"
    if v.status == "FAIL":
        v.advice.append("T4: cestu „posty z míst“ škrtáme; pro locationId z hashtagů nemáme souřadnice, Brno jen podle T2 a textu.")
    return v


def j_t5(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    r = rr[0]
    requested = [norm_handle(u) for u in (r.get("input") or {}).get("usernames") or []]
    items = good_items(r)
    errs = error_items(r)
    handles = [ap.ig_profile_handle(i, requested) for i in items]
    public = [(h, i) for h, i in zip(handles, items) if i.get("private") is not True]
    empty = [h or "?" for h, i in public if not nonempty(i.get("latestPosts"))]
    n_pub = len(public)
    share = (n_pub - len(empty)) / n_pub if n_pub else 0.0
    dur = num(r.get("duration_s"))
    v.lines.append(f"Vyžádáno {len(requested)} účtů, vráceno {len(items)} profilů, chybových položek {len(errs)}"
                   f" ({error_kinds(r)}), vyřazeno nezletilých {stub_count(r)}")
    v.lines.append(f"Doba běhu {usd(dur, 0)} s (limit 180 s)")
    v.lines.append(f"Veřejné profily s neprázdnými latestPosts: {n_pub - len(empty)}/{n_pub} ({pct(n_pub - len(empty), n_pub)})")
    if empty:
        v.lines.append(f"Veřejné profily s prázdnými latestPosts (zopakovat): {', '.join('@' + h for h in empty)}")
    lps = [p for i in items for p in (i.get("latestPosts") or []) if isinstance(p, dict)]
    v.lines.append(f"latestPosts na profil: {length_stats([i.get('latestPosts') for i in items])}")
    v.lines.append(f"latestPosts[].isPinned: {fmt_counter(Counter(enum_val(p.get('isPinned', _MISSING)) for p in lps))}"
                   f" · productType: {fmt_counter(Counter(enum_val(p.get('productType', _MISSING)) for p in lps))}")
    small = [i for i in items if (num(i.get("followersCount")) or 0) < 10000]
    small_rel = sum(1 for i in small if nonempty(i.get("relatedProfiles")))
    v.lines.append(f"relatedProfiles: {length_stats([i.get('relatedProfiles') for i in items])}; "
                   f"u malých účtů (pod 10 000 sledujících) neprázdné {small_rel}/{len(small)}")
    v.lines.append(f"fbid vyplněné {sum(1 for i in items if s(i.get('fbid')))}/{len(items)}")
    unames = sum(1 for i in items if s(i.get("username")))
    v.verify.append((1, f"username vyplněné u {unames}/{len(items)} profilů"))
    v.verify.append((2, f"fullName vyplněné u {sum(1 for i in items if s(i.get('fullName')))}/{len(items)} profilů"))
    v.verify.append((3, f"latestPosts[].type: {fmt_counter(Counter(enum_val(p.get('type', _MISSING)) for p in lps))}"))
    renamed = sum(1 for h in handles if h and h not in requested)
    v.verify.append((4, f"vrácený handle mimo vyžádaná jména: {renamed} (přejmenované účty?)"))
    v.verify.append((5, f"relatedProfiles u malých účtů neprázdné {small_rel}/{len(small)}"))
    ok = n_pub > 0 and share >= 0.9 and (dur is None or dur <= 180)
    v.status = ("RUČNĚ" if dur is None else "PASS") if ok else "FAIL"
    v.summary = f"{pct(n_pub - len(empty), n_pub)} veřejných profilů má latestPosts (potřeba 90 %), běh {usd(dur, 0)} s"
    if share < 0.9:
        v.advice.append("T5: dávky po 25, profily s prázdnými latestPosts stáhnout znovu (otevřené issue).")
    if small and small_rel == 0:
        v.advice.append("T5: relatedProfiles u malých účtů prázdné, cestu „podobné účty“ škrtáme.")
    return v


def _elem_shape(values: list[Any]) -> str:
    c: Counter = Counter()
    for lst in values:
        if isinstance(lst, list):
            for el in lst:
                c["object{" + ",".join(sorted(map(key_name, el))) + "}" if isinstance(el, dict) else type_name(el)] += 1
    return fmt_counter(c, 4)


def j_t6(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    r = rr[0]
    ctx = d.get("context") or {}
    items = good_items(r)
    pp = Counter(enum_val(i.get("paidPartnership", _MISSING)) for i in items)
    true_items = [i for i in items if i.get("paidPartnership") is True]
    false_n = sum(1 for i in items if i.get("paidPartnership") is False)
    by_code: dict[str, dict] = {}
    for i in items:
        code = s(i.get("shortCode")) or ap.ig_shortcode(s(i.get("url")))
        if code:
            by_code.setdefault(code, i)
    req = [u for u in (r.get("input") or {}).get("username") or [] if ap.ig_shortcode(u)]
    v.lines.append(f"{len(items)} postů (duplikátů podle shortCode {len(items) - len(by_code)}), chybových "
                   f"{len(error_items(r))} ({error_kinds(r)}) · paidPartnership {fmt_counter(pp)}")
    for u in req:
        it = by_code.get(ap.ig_shortcode(u) or "")
        v.lines.append(f"vstupní post {u}: " + (f"paidPartnership {enum_val(it.get('paidPartnership', _MISSING))}"
                                                 if it else "nevrácen"))
    for i in true_items[:5]:
        v.lines.append(f"paidPartnership true: {post_url(i)} (ověř štítek na IG)")
    lc = [i.get("latestComments") for i in items]
    comments = [c for x in lc if isinstance(x, list) for c in x if isinstance(c, dict)]
    with_text = sum(1 for c in comments if s(c.get("text")))
    v.lines.append(f"latestComments: {length_stats(lc)} · komentářů s text {with_text}/{len(comments)}")
    v.lines.append(f"sponsors neprázdné {sum(1 for i in items if nonempty(i.get('sponsors')))} · coauthorProducers neprázdné "
                   f"{sum(1 for i in items if nonempty(i.get('coauthorProducers')))} · locationName "
                   f"{sum(1 for i in items if s(i.get('locationName')))} · locationId "
                   f"{sum(1 for i in items if s(i.get('locationId')))} (z {len(items)})")
    ev = r.get("charged_event_counts") if isinstance(r.get("charged_event_counts"), dict) else {}
    music = {k: n for k, n in ev.items() if "music" in str(k).lower()}
    v.lines.append(f"Účtované eventy: {_events(r)}")
    v.verify.append((9, f"paidPartnership: {fmt_counter(pp)}"))
    v.verify.append((10, f"sponsors[]: {_elem_shape([i.get('sponsors') for i in items])}; latestComments[] klíče: "
                         f"{', '.join(sorted({key_name(k) for c in comments for k in c})) or '–'}; taggedUsers[]: "
                         f"{_elem_shape([i.get('taggedUsers') for i in items])}"))
    v.verify.append((11, "music-data účtováno: " + (", ".join(f"{key_name(k)} {n}" for k, n in music.items())
                                                    if music else "ne") + f" (eventy: {_events(r)})"))
    v.verify.append((3, f"type: {fmt_counter(Counter(enum_val(i.get('type', _MISSING)) for i in items))}"))
    labelled = ctx.get("urls_source") in ("cli", "prompt")
    if labelled and req:
        hits = [u for u in req if (by_code.get(ap.ig_shortcode(u) or "") or {}).get("paidPartnership") is True]
        v.status = "PASS" if hits else "FAIL"
        v.summary = f"true u {len(hits)}/{len(req)} zadaných štítkovaných postů"
    elif true_items:
        v.status = "PASS"
        v.summary = f"true u {len(true_items)} postů (vstupy nebyly ověřeně štítkované: ověř štítek na IG)"
    elif items:
        v.status = "RUČNĚ"
        v.summary = ("žádné true; vstupní posty nemusely mít štítek, zopakuj s --t6-post-urls "
                     "(posty se štítkem Placené partnerství)")
    if true_items and false_n:
        v.advice.append(f"T6: paidPartnership vrací true ({len(true_items)}) i false ({false_n}); když true vyšlo u "
                        "štítkovaných postů, nastav TRUST_IG_FALSE_LABEL = True v apify_provider.py.")
    if items and not true_items:
        v.advice.append("T6: bez true: kola 2 a 4 berou reklamu jen z popisků, druhý běh postů pro kola 2 a 3 škrtáme.")
    if with_text:
        v.advice.append(f"T6: latestComments chodí ({with_text} komentářů s textem): APIFY_COMMENTS_SOURCE=latest, T7 netřeba.")
    if music:
        v.advice.append("T6: účtuje se music-data: APIFY_POST_DETAIL=basicData nebo nižší strop.")
    return v


def j_t7(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    r = rr[0]
    req = (r.get("input") or {}).get("directUrls") or []
    per: dict[str, list[int]] = {}
    for i in good_items(r):
        key = ap.ig_shortcode(s(i.get("postUrl"))) or s(i.get("postUrl")) or "?"
        cnt = per.setdefault(key, [0, 0])
        cnt[0] += 1
        cnt[1] += 1 if s(i.get("text")) else 0
    oks = []
    for u in req:
        n, t = per.get(ap.ig_shortcode(u) or u, [0, 0])
        oks.append(t >= 10)
        v.lines.append(f"{u}: {n} komentářů, s textem {t}")
    v.lines.append(f"chybové položky: {len(error_items(r))} ({error_kinds(r)})")
    mx = max((n for n, _ in per.values()), default=0)
    v.status = "PASS" if oks and all(oks) else "FAIL"
    v.summary = f"{sum(oks)}/{len(req)} postů má aspoň 10 komentářů s textem (nejvíc {mx} na post)"
    if v.status == "FAIL":
        v.advice.append("T7: jazyk publika jen z latestComments, jinak kritérium „jazyk publika“ nejde ověřit.")
    return v


def j_t8(d: dict) -> Verdict:
    v = Verdict()
    rows: dict[str, int] = {}
    for r in _ran_runs(d):
        items = good_items(r)
        n = len(items)
        target = ap.ig_handle_from_link(((r.get("input") or {}).get("startUrls") or [""])[0]) or "?"
        rows[r["label"]] = n
        cn = sum(1 for i in items if s(ap._get(i, "creator", "name")))
        bp = sum(1 for i in items if any(isinstance(p, dict) and s(p.get("name")) for p in i.get("brandPartners") or []))
        v.lines.append(f"{r['label']} (@{target}): {n} řádků (chybových {len(error_items(r))}) · stav {r.get('status')}"
                       f" · creator.name {cn}/{n} · brandPartners[].name {bp}/{n} · link "
                       f"{sum(1 for i in items if s(i.get('link')))}/{n} · dateCreated "
                       f"{sum(1 for i in items if s(i.get('dateCreated')))}/{n} · type "
                       f"{fmt_counter(Counter(enum_val(i.get('type', _MISSING)) for i in items))}")
        v.verify.append((20, f"{r['label']}: onlyPostsNewerThan „6 months“ přijato (stav {r.get('status')}); "
                             "„12 months“ z BRAND_WINDOW tento test neověřuje"))
    if not rows:
        return v
    rohlik, nike = rows.get("T8a"), rows.get("T8b")
    v.status = "PASS" if (rohlik or 0) >= 1 else ("BEZ DAT" if rohlik is None else "FAIL")
    v.summary = f"rohlik.cz {rohlik if rohlik is not None else '–'} řádků, nike {nike if nike is not None else '–'}"
    if rohlik == 0 and nike:
        v.advice.append("T8: nike vrací a rohlik.cz 0, české spolupráce bez přihlášení nevidíme: Meta Branded Content škrtáme.")
    elif rohlik == 0 and nike == 0:
        v.advice.append("T8: obojí 0, actor nefunguje: Meta Branded Content škrtáme.")
    return v


def _tt_url_keys(items: list[dict]) -> str:
    c: Counter = Counter()
    for it in items:
        meta = it.get("authorMeta") if isinstance(it.get("authorMeta"), dict) else {}
        for prefix, dd in (("", it), ("authorMeta.", meta)):
            for k, val in dd.items():
                if isinstance(val, str) and "tiktok.com/@" in val:
                    c[prefix + key_name(k)] += 1
    return fmt_counter(c, 6)


def j_t9(d: dict) -> Verdict:
    v = Verdict()
    authors_by: dict[str, set[str]] = {}
    cs_by: dict[str, set[str]] = {}
    for r in _ran_runs(d):
        items = good_items(r)
        n = len(items)
        vids = [i for i in items if s(i.get("webVideoUrl"))]
        novid = [i for i in items if not s(i.get("webVideoUrl"))]
        authors: set[str] = set()
        cs: set[str] = set()
        for i in items:
            h = ap._scan_tiktok_handle(i)
            if h:
                authors.add(h)
                if (s(i.get("textLanguage")) or "").lower() in ("cs", "sk"):
                    cs.add(h)
        authors_by[r["label"]], cs_by[r["label"]] = authors, cs
        meta = [i.get("authorMeta") for i in items if isinstance(i.get("authorMeta"), dict)]
        v.lines.append(f"{r['label']}: {n} položek ({len(vids)} s webVideoUrl, {len(novid)} bez) · chybových "
                       f"{len(error_items(r))} ({error_kinds(r)}) · různých autorů {len(authors)} · autorů s popiskem "
                       f"cs/sk {len(cs)} · eventy {_events(r)}")
        dist = {p: fmt_counter(Counter(enum_val(x) for i in items for x in values_at(i, p)), 6)
                for p in ("textLanguage", "authorMeta.region", "authorMeta.isUnderAge18", "locationCreated",
                          "isSponsored", "isAd")}
        v.lines.append(f"{r['label']}: " + " · ".join(f"{p} {val}" for p, val in dist.items()))
        lm = [i.get("locationMeta") for i in items if isinstance(i.get("locationMeta"), dict) and i["locationMeta"]]
        v.verify.append((12, f"{r['label']}: text vyplněný u {sum(1 for i in items if s(i.get('text')))}/{n}"))
        v.verify.append((13, f"{r['label']}: hashtags[] {_elem_shape([i.get('hashtags') for i in items])}; "
                             f"mentions[] {_elem_shape([i.get('mentions') for i in items])}"))
        v.verify.append((14, f"{r['label']}: locationMeta u {len(lm)}/{n} (klíče "
                             f"{', '.join(sorted({key_name(k) for x in lm for k in x})) or '–'}); locationName nahoře u "
                             f"{sum(1 for i in items if s(i.get('locationName')))}/{n}"))
        v.verify.append((15, f"{r['label']}: klíče authorMeta: {', '.join(sorted({key_name(k) for m in meta for k in m})) or '–'}"))
        v.verify.append((16, f"{r['label']}: authorMeta.region {dist['authorMeta.region']}; isUnderAge18 {dist['authorMeta.isUnderAge18']}"))
        v.verify.append((17, f"{r['label']}: isSponsored {dist['isSponsored']}"))
        v.verify.append((18, f"{r['label']}: {len(vids)} položek s webVideoUrl, {len(novid)} bez; odkaz tiktok.com/@ "
                             f"v klíčích (položky bez videa): {_tt_url_keys(novid)}"))
    if not authors_by:
        return v
    if "T9a" in authors_by and "T9b" in authors_by:
        a, b = authors_by["T9a"], authors_by["T9b"]
        v.lines.append(f"CZ proxy vs bez: společných autorů {len(a & b)}, jen s CZ {len(a - b)}, jen bez {len(b - a)}")
        if a == b and a:
            v.advice.append("T9: proxyCountryCode CZ výsledky nemění: APIFY_TIKTOK_PROXY=None (úspora 0,0013 USD za výsledek).")
    key = "T9a" if "T9a" in cs_by else next(iter(cs_by))
    n_cs, n_all = len(cs_by[key]), len(authors_by[key])
    v.status = "PASS" if n_cs >= 5 else ("RUČNĚ" if n_all >= 5 else "FAIL")
    v.summary = (f"{key}: {n_all} autorů, z toho {n_cs} s českým nebo slovenským popiskem (potřeba 5 českých účtů "
                 "o jídle; jazyk popisku často chybí nebo je un, ověř ručně)")
    if n_all < 5:
        v.advice.append("T9: TikTok jen pro finalisty přes odkazy v bio.")
    return v


def j_t10(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    r = rr[0]
    ctx = d.get("context") or {}
    req = [norm_handle(h) for h in (r.get("input") or {}).get("profiles") or []]
    foreign = norm_handle(ctx.get("foreign") or (req[-1] if req else ""))
    groups: dict[str, list[dict]] = {}
    for i in good_items(r):
        h = ap._scan_tiktok_handle(i)
        if h:
            groups.setdefault(h, []).append(i)
    regions: dict[str, str | None] = {}
    u18_all: Counter = Counter()
    for h in req:
        vids = groups.get(h, [])
        reg = Counter(enum_val(x) for i in vids for x in values_at(i, "authorMeta.region"))
        u18 = Counter(enum_val(x) for i in vids for x in values_at(i, "authorMeta.isUnderAge18"))
        u18_all.update(u18)
        regions[h] = next((s(ap._get(i, "authorMeta", "region")) for i in vids if s(ap._get(i, "authorMeta", "region"))), None)
        locm = sum(1 for i in vids if nonempty(i.get("locationMeta")))
        v.lines.append(f"@{h}: {len(vids)} videí · authorMeta.region {fmt_counter(reg)} · isUnderAge18 "
                       f"{fmt_counter(u18)} · locationMeta {locm}/{len(vids)}")
    v.lines.append(f"chybové položky: {len(error_items(r))} ({error_kinds(r)})")
    v.verify.append((16, "region: " + ", ".join(f"@{h} {regions[h] or 'prázdný'}" for h in req)
                         + f"; isUnderAge18 {fmt_counter(u18_all)}"))
    filled = req and all(regions.get(h) for h in req)
    ok = bool(filled) and (regions.get(foreign) or "").upper() != "CZ"
    v.status = "PASS" if ok else "FAIL"
    v.summary = ", ".join(f"@{h} region {regions[h] or 'prázdný'}" for h in req) + f" (zahraniční: @{foreign})"
    if ok:
        v.advice.append("T10: region je vyplněný a u zahraničního účtu jiný než CZ: smí do kritéria lokality, "
                        "nastav TRUST_TIKTOK_REGION = True v apify_provider.py.")
    else:
        v.advice.append("T10: region prázdný nebo všude CZ: region nepoužívat (TRUST_TIKTOK_REGION zůstává False).")
    if not any(k == "true" for k in u18_all):
        v.advice.append("T10: isUnderAge18 nikde true: věk je mezera, nezletilé jen přes věk v bio a ověření majitelem.")
    return v


def j_t11(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    items = good_items(rr[0])
    hosts = Counter(host_of(s(i.get("url"))) or "?" for i in items)
    google = [i for i in items if "news.google." in host_of(s(i.get("url")))]
    pub_dated = [i for i in items if i not in google and s(i.get("url")) and nonempty(i.get("publishedAt"))]
    cz = [i for i in pub_dated if host_of(s(i.get("url"))).endswith(".cz")]
    n = len(items)
    v.lines.append(f"{n} článků · URL vydavatele {n - len(google)} · přesměrování Googlu {len(google)} · publishedAt "
                   f"{sum(1 for i in items if nonempty(i.get('publishedAt')))}/{n} · domény {fmt_counter(hosts, 10)}")
    v.verify.append((19, f"source: {fmt_counter(Counter(type_name(i.get('source', _MISSING)) for i in items))}"))
    if len(pub_dated) >= 3:
        v.status = "PASS" if len(cz) >= 3 else "RUČNĚ"
    else:
        v.status = "FAIL"
    v.summary = f"{len(pub_dated)} článků s URL vydavatele a datem, z toho {len(cz)} na doméně .cz (potřeba 3 české)"
    if v.status == "FAIL":
        v.advice.append("T11: záloha apify/google-search-scraper (sekce 15), jinak zprávy v kole 4 škrtáme.")
    return v


def j_t12(d: dict) -> Verdict:
    v = Verdict()
    rr = _ran_runs(d)
    if not rr:
        return v
    r = rr[0]
    ctx = d.get("context") or {}
    by_id: dict[str, dict] = {}
    for i in r.get("items") or []:
        if not isinstance(i, dict) or is_stub(i):
            continue
        for k in (s(i.get("id")), yt_id(s(i.get("url"))), yt_id(s(i.get("input")))):
            if k:
                by_id.setdefault(k, i)
    want = [(ctx.get("paid_url"), True), (ctx.get("unpaid_url"), False)]
    oks = []
    for u, expect in want:
        vid = yt_id(u)
        it = by_id.get(vid or "")
        got = it.get("isPaidContent", _MISSING) if it else _MISSING
        oks.append(it is not None and got is expect)
        extra = f", error {error_kind(it)}" if it and ap.error_of(it) else ""
        v.lines.append(f"{vid}: isPaidContent {enum_val(got) if it else 'nevráceno'} (čekáme {str(expect).lower()})"
                       f" · channelLocation {'vyplněné' if it and s(it.get('channelLocation')) else 'prázdné'}{extra}")
    v.status = "PASS" if oks and all(oks) else "FAIL"
    v.summary = " / ".join(ln.split(" · ")[0] for ln in v.lines[:2])
    if v.status == "FAIL":
        v.advice.append("T12: YouTube škrtáme (první v pořadí škrtů).")
    return v


# =============================================================================================
# Offline mapper analysis (app.sources.apify_provider pure mappers on the saved items)
# =============================================================================================


@dataclass
class MapStat:
    mapper: str
    model: str
    total: int
    ok: int = 0
    objects: int = 0
    fails: Counter = field(default_factory=Counter)
    empty: Counter = field(default_factory=Counter)
    lost: Counter = field(default_factory=Counter)      # "field ← rawPath": raw value present, mapped field empty
    expected: frozenset = frozenset()
    note: str = ""


EXPECTED_EMPTY: dict[str, set[str]] = {
    "map_ig_post": {"views", "language"},     # IG removed view counts; IG gives no language
    "map_ig_profile": {"region", "is_under_18", "former_handles", "former_handles_count"},
    "map_tt_video": {"location_id", "is_pinned", "sponsors", "coauthors", "tagged_users"},
    "map_tt_profiles": {"following", "posts_count", "is_business", "business_category", "related_handles",
                        "former_handles", "former_handles_count", "is_under_18"}
    | (set() if ap.TRUST_TIKTOK_REGION else {"region"}),
    "map_brand_collab": {"post_id", "is_competitor"},
}


# Normalized field -> raw paths it is read from (or could be: the TikTok authorMeta name / counts are
# candidates for VERIFY LIVE 15, IG view counts for Post.views). A raw value there with an empty mapped
# field means the mapper lost data: the most direct "fix the provider" signal.
SOURCE_PATHS: dict[str, dict[str, tuple[str, ...]]] = {
    "map_ig_post": {"caption": ("caption",), "likes": ("likesCount",), "comments": ("commentsCount",),
                    "views": ("videoViewCount", "videoPlayCount", "igPlayCount"), "location_name": ("locationName",),
                    "location_id": ("locationId",), "tagged_users": ("taggedUsers",),
                    "coauthors": ("coauthorProducers",), "sponsors": ("sponsors",), "is_pinned": ("isPinned",),
                    "hashtags": ("hashtags",), "mentions": ("mentions",), "paid_partnership": ("paidPartnership",)},
    "map_ig_profile": {"display_name": ("fullName", "full_name"), "bio": ("biography",),
                       "followers": ("followersCount",), "following": ("followsCount",), "posts_count": ("postsCount",),
                       "verified": ("verified",), "private": ("private",), "is_business": ("isBusinessAccount",),
                       "business_category": ("businessCategoryName",), "external_urls": ("externalUrl", "externalUrls"),
                       "related_handles": ("relatedProfiles",), "latest_posts": ("latestPosts",),
                       "former_handles_count": ("about.former_usernames",)},
    "map_ig_place": {"name": ("name", "title"), "lat": ("lat",), "lng": ("lng",), "city": ("city", "location_city"),
                     "authors": ("posts[].username", "posts[].ownerUsername", "posts[].user.username",
                                 "posts[].owner.username", "posts"),
                     "business_handle": ("ig_business.profile.username",)},
    "map_ig_comment": {"created_at": ("timestamp",)},
    "map_tt_video": {"caption": ("text", "desc", "description"), "likes": ("diggCount",), "comments": ("commentCount",),
                     "views": ("playCount",), "language": ("textLanguage",), "hashtags": ("hashtags",),
                     "mentions": ("mentions",), "paid_partnership": ("isSponsored",),
                     "location_name": ("locationMeta.locationName", "locationName", "locationMeta.city",
                                       "locationMeta.address")},
    "map_tt_profiles": {"display_name": ("authorMeta.nickName", "authorMeta.nickname", "authorMeta.name"),
                        "bio": ("authorMeta.signature",), "followers": ("authorMeta.fans",),
                        "following": ("authorMeta.following",), "posts_count": ("authorMeta.video",),
                        "verified": ("authorMeta.verified",), "private": ("authorMeta.privateAccount",),
                        "external_urls": ("authorMeta.bioLink",)}
    | ({"region": ("authorMeta.region",)} if ap.TRUST_TIKTOK_REGION else {}),
    "map_news": {"outlet": ("source",), "published_at": ("publishedAt", "publishedTimestamp"),
                 "snippet": ("description",)},
}


def raw_filled(item: Any, path: str) -> bool:
    """A raw value that should survive mapping: not missing / null / false / negative (hidden likes) /
    'None' / 'un' (unknown language) / empty."""
    for v in values_at(item, path):
        if v is _MISSING or v is None or v is False or v == [] or v == {}:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            continue
        if isinstance(v, str) and fold(v).strip(" ,") in ("", "none", "null", "un"):
            continue
        return True
    return False


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def lost_fields(mapper: str, raw: Any, obj: Any) -> list[str]:
    out = []
    for f, paths in SOURCE_PATHS.get(mapper.split(" ")[0], {}).items():
        val = getattr(obj, f, None) if not isinstance(obj, dict) else obj.get(f)
        if not _is_empty(val):
            continue
        hit = next((p for p in paths if raw_filled(raw, p)), None)
        if hit:
            out.append(f"{f} ← {hit}")
    return out


def exc_reason(e: BaseException) -> str:
    errs = getattr(e, "errors", None)
    if callable(errs):
        try:
            parts = sorted({".".join(str(x) for x in er.get("loc", ())) + ":" + str(er.get("type"))
                            for er in errs()})
            return f"výjimka {type(e).__name__} ({', '.join(parts[:3])})"
        except Exception:  # noqa: BLE001
            pass
    return f"výjimka {type(e).__name__}"


def empty_fields(objs: list[Any]) -> Counter:
    c: Counter = Counter()
    for o in objs:
        if dataclasses.is_dataclass(o):
            vals = dataclasses.asdict(o)
        else:
            vals = {f: getattr(o, f, None) for f in getattr(type(o), "model_fields", {})}
        for f, val in vals.items():
            if f == "source":
                continue
            if val is None or val == "" or val == [] or val == {}:
                c[f] += 1
            elif f == "author_handle" and not val:
                c[f] += 1
    return c


def map_each(mapper: str, model: str, items: list[Any], fn: Callable[[Any], Any], why: Callable[[Any], str],
             expected: set[str] | None = None, raw_of: Callable[[Any], Any] = lambda x: x) -> tuple[MapStat, list[Any]]:
    """Runs a per-item mapper. None or [] counts as not mapped, with the reason from ``why``. For a single
    mapped object, fields left empty although the raw item has their source value go to ``lost``."""
    st = MapStat(mapper, model, len(items), expected=frozenset(expected or EXPECTED_EMPTY.get(mapper.split(" ")[0], set())))
    objs: list[Any] = []
    for it in items:
        try:
            out = fn(it)
        except Exception as e:  # noqa: BLE001
            st.fails[exc_reason(e)] += 1
            continue
        if out is None or (isinstance(out, list) and not out):
            st.fails[why(it)] += 1
            continue
        st.ok += 1
        if isinstance(out, list):
            objs.extend(out)
        else:
            objs.append(out)
            st.lost.update(lost_fields(mapper, raw_of(it), out))
    st.objects = len(objs)
    st.empty = empty_fields(objs)
    return st, objs


def map_group(mapper: str, model: str, items: list[Any], fn: Callable[[list[Any]], list[Any]]) -> tuple[MapStat, list[Any]]:
    st = MapStat(mapper, model, len(items), expected=frozenset(EXPECTED_EMPTY.get(mapper.split(" ")[0], set())))
    try:
        objs = fn(items)
    except Exception as e:  # noqa: BLE001
        st.fails[exc_reason(e)] = len(items)
        return st, []
    errs = sum(1 for it in items if not isinstance(it, dict) or ap.error_of(it))
    no_h = sum(1 for it in items if isinstance(it, dict) and not ap.error_of(it) and not ap._scan_tiktok_handle(it))
    if errs:
        st.fails["chybová položka (PROFILE_PRIVATE dává soukromý profil)"] = errs
    if no_h:
        st.fails["nenalezen handle (webVideoUrl ani jediný odkaz tiktok.com/@ mimo bio)"] = no_h
    st.ok = len(items) - errs - no_h
    st.objects = len(objs)
    st.empty = empty_fields(objs)
    if mapper.split(" ")[0] == "map_tt_profiles":
        first: dict[str, dict] = {}
        for it in items:
            if isinstance(it, dict) and not ap.error_of(it):
                first.setdefault(ap._scan_tiktok_handle(it) or "", it)
        for p in objs:
            if getattr(p, "handle", None) in first:
                st.lost.update(lost_fields(mapper, first[p.handle], p))
    return st, objs


def _err_or(it: Any) -> str | None:
    if not isinstance(it, dict):
        return "není objekt"
    if ap.error_of(it):
        return "chybová položka"
    return None


def why_ig_post(it: Any, has_default: bool = False) -> str:
    e = _err_or(it)
    if e:
        return e
    code = s(it.get("shortCode")) or ap.ig_shortcode(s(it.get("url")))
    if not (s(it.get("url")) or code):
        return "chybí url i shortCode"
    if not s(it.get("ownerUsername")) and not has_default:
        return "chybí ownerUsername"
    if ap.parse_ts(it.get("timestamp")) is None:
        return "chybí nebo nečitelný timestamp"
    return "jiný důvod"


def why_ig_profile(it: Any) -> str:
    e = _err_or(it)
    if e:
        return e
    return "chybí username i latestPosts[].ownerUsername" if not s(it.get("username")) else "jiný důvod"


def why_search_user(it: Any) -> str:
    return _err_or(it) or ("chybí username" if not s(it.get("username")) else "jiný důvod")


def why_related(it: Any) -> str:
    return _err_or(it) or "relatedProfiles prázdné nebo jen soukromé"


def why_place(it: Any) -> str:
    e = _err_or(it)
    if e:
        return e
    if not s(it.get("location_id")):
        return "tvar postu, ne místa" if s(it.get("ownerUsername")) else "chybí location_id"
    return "jiný důvod"


def why_comment(it: Any) -> str:
    e = _err_or(it)
    if e:
        return e
    if not s(it.get("text")):
        return "chybí text"
    if not s(it.get("postUrl")):
        return "chybí postUrl"
    return "jiný důvod"


def why_latest(it: Any) -> str:
    e = _err_or(it)
    if e:
        return e
    if not s(it.get("url")):
        return "post bez url"
    if not nonempty(it.get("latestComments")):
        return "post bez latestComments"
    return "latestComments bez klíče text"


def why_tt_video(it: Any) -> str:
    e = _err_or(it)
    if e:
        return e
    url = s(it.get("webVideoUrl"))
    if not url:
        return "chybí webVideoUrl"
    if not ap.tt_video_ref(url):
        return "webVideoUrl není URL videa"
    if ap.parse_ts(it.get("createTimeISO")) is None:
        return "chybí nebo nečitelný createTimeISO"
    return "jiný důvod"


def why_news(it: Any) -> str:
    e = _err_or(it)
    if e:
        return e
    return "chybí title" if not s(it.get("title")) else ("chybí url" if not s(it.get("url")) else "jiný důvod")


def why_brand(target: str) -> Callable[[Any], str]:
    def f(it: Any) -> str:
        e = _err_or(it)
        if e:
            return e
        ch = ap.ig_handle_from_link(s(ap._get(it, "creator", "link")))
        if ch and ch != norm_handle(target):
            return "tvůrce je jiný účet (cílový účet je na straně značky)"
        if not nonempty(it.get("brandPartners")):
            return "chybí brandPartners"
        return "partner bez jména a odkazu"
    return f


def mapper_items(d: dict) -> list[Any]:
    return [i for r in runs_of(d) if ran(r) for i in r.get("items") or [] if not is_stub(i)]


def _first_input(d: dict) -> dict:
    rr = runs_of(d)
    return (rr[0].get("input") or {}) if rr else {}


def _fetched_at(d: dict) -> datetime:
    try:
        return datetime.fromisoformat(str(d.get("saved_at")).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _latest_posts_stat(items: list[Any], actor: str, fa: datetime, requested: list[str] = ()) -> MapStat:
    flat: list[tuple[dict, str | None]] = []
    for it in items:
        if not isinstance(it, dict) or ap.error_of(it):
            continue
        h = ap.ig_profile_handle(it, requested)
        flat.extend((p, h) for p in it.get("latestPosts") or [] if isinstance(p, dict))
    st, _ = map_each("map_ig_post (latestPosts[])", "Post", flat,
                     lambda ph: ap.map_ig_post(ph[0], actor=actor, fetched_at=fa, default_author=ph[1]),
                     lambda ph: why_ig_post(ph[0], has_default=bool(ph[1])), EXPECTED_EMPTY["map_ig_post"],
                     raw_of=lambda ph: ph[0])
    return st


def mappers_for(key: str, d: dict) -> tuple[list[MapStat], str]:
    items = mapper_items(d)
    fa = _fetched_at(d)
    inp = _first_input(d)
    st: list[MapStat] = []
    note = ""
    if key == "T1":
        q = str(inp.get("search") or "")
        st.append(map_each("map_ig_search_user", "CandidateRef", items,
                           lambda it: ap.map_ig_search_user(it, query=q, actor=ACT_IG_SEARCH, fetched_at=fa), why_search_user)[0])
        st.append(map_each("map_ig_profile", "Profile", items,
                           lambda it: ap.map_ig_profile(it, actor=ACT_IG_SEARCH, fetched_at=fa), why_ig_profile)[0])
        st.append(_latest_posts_stat(items, ACT_IG_SEARCH, fa))
        st.append(map_each("map_ig_related", "CandidateRef", items,
                           lambda it: ap.map_ig_related(it, actor=ACT_IG_SEARCH, fetched_at=fa), why_related)[0])
    elif key == "T2":
        st.append(map_each("map_ig_place", "PlaceInfo", items, ap.map_ig_place, why_place)[0])
    elif key == "T3":
        st.append(map_each("map_ig_post", "Post", items,
                           lambda it: ap.map_ig_post(it, actor=ACT_IG_HASHTAG, fetched_at=fa), why_ig_post)[0])
    elif key == "T4":
        places = [i for i in items if isinstance(i, dict) and s(i.get("location_id"))]
        posts = [i for i in items if i not in places]
        st.append(map_each("map_ig_place", "PlaceInfo", places, ap.map_ig_place, why_place)[0])
        st.append(map_each("map_ig_post", "Post", posts,
                           lambda it: ap.map_ig_post(it, actor=ACT_IG_SCRAPER, fetched_at=fa), why_ig_post)[0])
    elif key == "T5":
        req = [norm_handle(u) for u in inp.get("usernames") or []]
        st.append(map_each("map_ig_profile", "Profile", items,
                           lambda it: ap.map_ig_profile(it, actor=ACT_IG_PROFILE, fetched_at=fa, requested=req),
                           why_ig_profile)[0])
        st.append(_latest_posts_stat(items, ACT_IG_PROFILE, fa, req))
        st.append(map_each("map_ig_related", "CandidateRef", items,
                           lambda it: ap.map_ig_related(it, actor=ACT_IG_PROFILE, fetched_at=fa), why_related)[0])
    elif key == "T6":
        trust = ap.TRUST_IG_FALSE_LABEL and inp.get("dataDetailLevel") == "detailedData"
        m, posts = map_each("map_ig_post", "Post", items,
                            lambda it: ap.map_ig_post(it, actor=ACT_IG_POST, fetched_at=fa, trust_false_label=trust),
                            why_ig_post)
        st.append(m)
        note = (f"Post.paid_partnership po mapování: {fmt_counter(Counter(enum_val(p.paid_partnership) for p in posts))}"
                f" (TRUST_IG_FALSE_LABEL = {ap.TRUST_IG_FALSE_LABEL})")
        st.append(map_each("map_ig_latest_comments", "Comment", items,
                           lambda it: ap.map_ig_latest_comments(it, actor=ACT_IG_POST, fetched_at=fa,
                                                                per_post=ap.COMMENTS_PER_POST_MAX), why_latest)[0])
    elif key == "T7":
        st.append(map_each("map_ig_comment", "Comment", list(enumerate(items, 1)),
                           lambda p: ap.map_ig_comment(p[1], actor=ACT_IG_COMMENT, fetched_at=fa, index=p[0]),
                           lambda p: why_comment(p[1]), raw_of=lambda p: p[1])[0])
    elif key == "T8":
        for r in runs_of(d):
            if not ran(r):
                continue
            target = ap.ig_handle_from_link(((r.get("input") or {}).get("startUrls") or [""])[0]) or ""
            its = [i for i in r.get("items") or [] if not is_stub(i)]
            st.append(map_each(f"map_brand_collab ({r['label']}, cíl @{target})", "CollabEvidence", its,
                               lambda it, t=target: ap.map_brand_collab(it, creator_handle=t, actor=ACT_BRAND, fetched_at=fa),
                               why_brand(target), EXPECTED_EMPTY["map_brand_collab"])[0])
            st.append(map_each(f"map_brand_collab ({r['label']}, cíl = tvůrce řádku)", "CollabEvidence", its,
                               lambda it: ap.map_brand_collab(
                                   it, creator_handle=ap.ig_handle_from_link(s(ap._get(it, "creator", "link"))) or "",
                                   actor=ACT_BRAND, fetched_at=fa),
                               why_brand(""), EXPECTED_EMPTY["map_brand_collab"])[0])
        note = ("Provider volá collabs() s účtem tvůrce. U URL značky (rohlik.cz, nike) jsou řádky o cizích tvůrcích, "
                "proto je první řádek tabulky čekaně prázdný; druhý zkouší čtení polí s tvůrcem řádku.")
    elif key in ("T9", "T10"):
        actor = ACT_TT if key == "T9" else ACT_TT_PROFILE
        good = [i for i in items if isinstance(i, dict)]
        if key == "T9":
            for r in runs_of(d):
                if not ran(r):
                    continue
                its = [i for i in r.get("items") or [] if not is_stub(i)]
                q = ((r.get("input") or {}).get("searchQueries") or [""])[0]
                st.append(map_group(f"map_tt_search ({r['label']})", "CandidateRef", its,
                                    lambda xs, q=q: ap.map_tt_search(xs, query=q, actor=actor, fetched_at=fa))[0])
        req = [norm_handle(h) for h in inp.get("profiles") or []]
        st.append(map_group("map_tt_profiles", "Profile", good,
                            lambda xs: ap.map_tt_profiles(xs, actor=actor, fetched_at=fa, requested=req))[0])
        st.append(map_each("map_tt_video", "Post", good,
                           lambda it: ap.map_tt_video(it, actor=actor, fetched_at=fa), why_tt_video)[0])
    elif key == "T11":
        st.append(map_each("map_news", "NewsItem", items, lambda it: ap.map_news(it, actor=ACT_NEWS, fetched_at=fa),
                           why_news)[0])
    elif key == "T12":
        note = "Bez mapperu: provider YouTube nestahuje (find_cross_platform vrací jen odkaz)."
    return st, note


# =============================================================================================
# Tests registry
# =============================================================================================


@dataclass
class TestDef:
    key: str
    title: str
    actor: str
    build: Callable[[Ctx, bool], Built | Skip]
    judge: Callable[[dict], Verdict]
    verify: tuple[int, ...]
    criterion: str


TESTS: dict[str, TestDef] = {t.key: t for t in (
    TestDef("T1", "Hledání účtů na IG", ACT_IG_SEARCH, b_t1, j_t1, (5,),
            "aspoň 10 relevantních brněnských účtů a u většiny latestPosts"),
    TestDef("T2", "Místa v Brně", ACT_IG_SEARCH, b_t2, j_t2, (6, 8),
            "aspoň 15 míst, která podle souřadnic leží v Brně"),
    TestDef("T3", "Hashtagy", ACT_IG_HASHTAG, b_t3, j_t3, (3,),
            "aspoň 20 postů na hashtag a aspoň část s locationId"),
    TestDef("T4", "URL místa a souřadnice pro locationId", ACT_IG_SCRAPER, b_t4, j_t4, (7,),
            "z URL místa dostaneme autory i souřadnice"),
    TestDef("T5", "Profily v dávce", ACT_IG_PROFILE, b_t5, j_t5, (1, 2, 3, 4, 5),
            "aspoň 90 % veřejných profilů má neprázdné latestPosts a běh doběhne do 3 minut"),
    TestDef("T6", "Štítek placeného partnerství", ACT_IG_POST, b_t6, j_t6, (3, 9, 10, 11),
            "paidPartnership: true aspoň u jednoho postu, který má na Instagramu štítek „Placené partnerství“"),
    TestDef("T7", "Komentáře", ACT_IG_COMMENT, b_t7, j_t7, (),
            "aspoň 10 komentářů s textem na post (jen když T6 nevrátí latestComments)"),
    TestDef("T8", "Meta Branded Content", ACT_BRAND, b_t8, j_t8, (20,),
            "rohlik.cz vrátí aspoň 1 řádek"),
    TestDef("T9", "TikTok hledání", ACT_TT, b_t9, j_t9, (12, 13, 14, 15, 16, 17, 18, 22),
            "aspoň 5 českých účtů o jídle"),
    TestDef("T10", "TikTok region a věk", ACT_TT_PROFILE, b_t10, j_t10, (12, 13, 14, 15, 16),
            "region je vyplněný a u zahraničního účtu jiný než CZ"),
    TestDef("T11", "Zprávy", ACT_NEWS, b_t11, j_t11, (19,),
            "aspoň 3 české články s URL vydavatele"),
    TestDef("T12", "YouTube štítek", ACT_YT, b_t12, j_t12, (),
            "isPaidContent je true u prvního videa a false u druhého"),
)}


def build(t: TestDef, ctx: Ctx, live: bool) -> Built | Skip:
    try:
        return t.build(ctx, live)
    except Exception as e:  # noqa: BLE001
        return Skip(f"chyba při sestavení vstupu: {type(e).__name__}: {safe_text(e, 120)}")


# =============================================================================================
# Live execution
# =============================================================================================


def saved_skip(ctx: Ctx, key: str) -> Skip | None:
    """A test whose data this script already saved is not run (and paid for) again unless --rerun."""
    if getattr(ctx.args, "rerun", False):
        return None
    d = ctx.load(key)
    if d is None:
        return None
    return Skip(f"data už jsou uložená ({saved_path(ctx.out_dir, key).name}, {d.get('saved_at') or '?'}); "
                "znovu (a znovu zaplatit) jen s --rerun")


def archive_previous(out_dir: Path, key: str) -> Path | None:
    """--rerun: this script's previous file of the test moves to <T>.<UTC timestamp of its data>.json, so the
    new data take the usual name (report, dependent tests) and nothing earlier is overwritten."""
    p = saved_path(out_dir, key)
    if not p.is_file() or not is_ours(p):
        return None
    d = load_saved(out_dir, key) or {}
    try:
        when = datetime.fromisoformat(str(d.get("saved_at"))).astimezone(timezone.utc)
    except (TypeError, ValueError):
        when = datetime.now(timezone.utc)
    stem = f"{key}.{when.strftime('%Y%m%dT%H%M%SZ')}"
    dest, n = out_dir / f"{stem}.json", 1
    while dest.exists():
        n += 1
        dest = out_dir / f"{stem}-{n}.json"
    p.rename(dest)
    return dest


def run_record(spec: RunSpec) -> dict:
    return {"label": spec.label, "actor": spec.actor, "input": spec.input, "note": spec.note, "status": None,
            "run_id": None, "run_ids": [], "attempts": 0, "error": None, "skip_reason": None, "started_at": None,
            "duration_s": None, "estimate_usd": spec.estimate, "worst_usd": spec.worst,
            "max_total_charge_usd": None, "max_items": spec.max_items, "charge_cap_sent": None,
            "usage_total_usd": None, "charged_event_counts": None, "items_total": 0, "items": []}


async def execute_run(spec: RunSpec, runner: Any, budget: Budget, sem: asyncio.Semaphore) -> dict:
    rec = run_record(spec)
    if spec.placeholder:   # never send a placeholder input to Apify
        rec.update(status="SKIPPED", skip_reason="vstup není doplněný")
        return rec
    if spec.worst > ap.max_usd_per_run() + 1e-9:
        rec.update(status="SKIPPED", skip_reason=f"nejhorší odhad {usd(spec.worst)} USD > MAX_USD_PER_RUN {usd(ap.max_usd_per_run())} USD")
        print(f"   {spec.label}: přeskočeno, {rec['skip_reason']}")
        return rec
    result = None                     # the last attempt that returned (not raised)
    usages: list[float] = []          # every attempt's usageTotalUsd, so a retried run's cost is not lost
    events: Counter = Counter()
    run_ids: list[str] = []
    while rec["attempts"] < 2:
        cap, why = budget.reserve(spec)
        if cap is None:
            if rec["attempts"] == 0:
                rec.update(status="SKIPPED", skip_reason=why)
                print(f"   {spec.label}: přeskočeno, {why}")
                return rec
            print(f"   {spec.label}: druhý pokus vynechán, {why}")
            break
        rec["attempts"] += 1
        rec["max_total_charge_usd"] = cap
        rec["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"   {spec.label} živě {spec.actor}: odhad {usd(spec.estimate)} USD (nejhůř {usd(spec.worst)}), "
              f"strop běhu {usd(cap, 2)} USD, max_items {spec.max_items}" + (" (2. pokus)" if rec["attempts"] > 1 else ""),
              flush=True)
        t0 = time.monotonic()
        try:
            async with sem:
                res = await runner(spec.actor, spec.input, max_items=spec.max_items, max_usd=cap,
                                   timeout_s=spec.timeout_s)
        except Exception as e:  # noqa: BLE001
            # Never start it again: the error may come after the run started or finished (waiting for it,
            # reading the dataset), so a second run could pay twice. apify-client retries network errors and
            # 5xx itself (max_retries 4); a start refused with a 4xx is not worth repeating either.
            budget.settle(cap, None, spec)
            rec["duration_s"] = round(time.monotonic() - t0, 1)
            rec["error"] = f"{type(e).__name__}: {safe_text(e, 200)}"
            print(f"   {spec.label}: běh selhal ({rec['error']}). Znovu nespouštím: běh mohl už začít a být "
                  f"zaplacený (do rozpočtu započten celý strop {usd(cap, 2)} USD). Zkontroluj ho v Apify Console, "
                  "záložka Runs; test znovu jen vědomě s --rerun.")
            break
        result = res
        rec["duration_s"] = round(time.monotonic() - t0, 1)
        rec["error"] = None
        reported = num(getattr(res, "usd", None))
        if reported is not None:
            usages.append(reported)
        ev = getattr(res, "events", None)
        if isinstance(ev, dict):
            events.update({str(k): v for k, v in ev.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
        rid = getattr(res, "run_id", None)
        if rid:
            run_ids.append(str(rid))
        budget.settle(cap, reported, spec, len(getattr(res, "items", None) or []))
        if getattr(res, "status", None) == "FAILED" and not getattr(res, "items", None) and rec["attempts"] < 2:
            print(f"   {spec.label}: běh FAILED bez dat; zkouším znovu")
            continue
        break
    rec["charge_cap_sent"] = getattr(runner, "charge_cap_supported", None)
    rec["run_ids"] = run_ids
    if result is not None:
        items = scrub_items(spec.actor, list(getattr(result, "items", None) or []))
        rec.update(status=getattr(result, "status", None) or "?", run_id=getattr(result, "run_id", None),
                   usage_total_usd=round(sum(usages), 4) if usages else None,
                   charged_event_counts=dict(events) or jsonable(getattr(result, "events", None)),
                   items_total=len(items), items=items)
        if rec["error"]:              # the 2nd attempt raised after a FAILED 1st one
            rec["status"] = "ERROR"
        n_err = sum(1 for i in items if not is_stub(i) and (not isinstance(i, dict) or ap.error_of(i)))
        print(f"   {spec.label}: {rec['status']}, {len(items)} položek (chybových {n_err}, vyřazeno {sum(map(is_stub, items))}), "
              f"usageTotalUsd {usd(rec['usage_total_usd'])} USD, {rec['duration_s']} s")
    elif rec["status"] is None:
        rec["status"] = "ERROR"
    return rec


async def execute_test(t: TestDef, ctx: Ctx, runner: Any, budget: Budget, sem: asyncio.Semaphore) -> str:
    print(f"\n-> {t.key} {t.title} · {t.actor} (živě)")
    b = saved_skip(ctx, t.key) or build(t, ctx, live=True)
    if isinstance(b, Skip):
        print(f"   přeskočeno: {b.reason}")
        return f"přeskočeno: {b.reason}"
    for n in b.notes:
        print(f"   pozn.: {n}")
    need = round(sum(r.worst for r in b.runs), 4)
    if not budget.fits(need):
        why = f"rozpočet: test potřebuje nejhůř {usd(need)} USD, zbývá {usd(budget.remaining())} USD"
        print(f"   přeskočeno: {why}")
        return f"přeskočeno: {why}"
    records = [await execute_run(spec, runner, budget, sem) for spec in b.runs]
    if not any(r["status"] != "SKIPPED" for r in records):
        return "přeskočeno: " + "; ".join(r["skip_reason"] or "" for r in records)
    data = {
        "_note": ("Skutečná veřejná data z živého běhu Apify (scripts/live_tests.py). Identita komentujících a jména "
                  "označených lidí jsou nahrazena [redacted] a položky nezletilých vyřazeny ještě před uložením. Jen pro ladění; "
                  "po hackathonu smazat: backend/.venv/bin/python scripts/live_tests.py --purge"),
        "test": t.key, "title": t.title, "saved_at": datetime.now(timezone.utc).isoformat(),
        "context": b.context, "notes": b.notes, "runs": records,
    }
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    old = archive_previous(ctx.out_dir, t.key)
    if old is not None:
        print(f"   předchozí data přesunuta do {old.name}")
    saved_path(ctx.out_dir, t.key).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(f"   uloženo: {saved_path(ctx.out_dir, t.key)}")
    return "spuštěno"


async def run_live(ctx: Ctx, tests: list[TestDef], runner: Any, budget: Budget, concurrency: int) -> dict[str, str]:
    notes: dict[str, str] = {}
    sem = asyncio.Semaphore(concurrency)
    if concurrency <= 1:
        for t in tests:
            notes[t.key] = await execute_test(t, ctx, runner, budget, sem)
        return notes
    done = {t.key: asyncio.Event() for t in tests}

    async def one(t: TestDef) -> None:
        for dep in DEPS.get(t.key, ()):
            if dep in done:
                await done[dep].wait()
        try:
            notes[t.key] = await execute_test(t, ctx, runner, budget, sem)
        except Exception as e:  # noqa: BLE001
            notes[t.key] = f"chyba: {type(e).__name__}: {safe_text(e, 120)}"
        finally:
            done[t.key].set()

    await asyncio.gather(*(one(t) for t in tests))
    return notes


# =============================================================================================
# Plan printing
# =============================================================================================


def client_info() -> dict:
    info: dict[str, Any] = {"version": None, "max_total_charge_usd": None, "max_items": None}
    try:
        from importlib.metadata import version
        info["version"] = version("apify-client")
    except Exception:  # noqa: BLE001
        pass
    cls = getattr(ap, "_AsyncClient", None) or getattr(ap, "_SyncClient", None)
    if cls is not None:
        try:
            fn = cls(token="offline-introspection").actor("apify/x").call
            kw = ap.call_kwargs(fn, run_input={}, max_items=1, max_usd=1.0, timeout_s=60)
            info["max_total_charge_usd"] = "max_total_charge_usd" in kw
            info["max_items"] = "max_items" in kw
        except Exception:  # noqa: BLE001
            pass
    return info


def _yn(v: Any) -> str:
    return "ano" if v is True else ("ne" if v is False else "?")


def print_plan(plan: list[tuple[TestDef, Built | Skip]], args: argparse.Namespace, out_dir: Path,
               token: bool, client: dict) -> tuple[float, float, int]:
    print("Creator Scout · živé testy Apify (docs/apify-pro-krystofa.md, „Prvních 45 minut“)")
    print(f"Režim: {'DRY-RUN (nic se nespouští a neukládá)' if args.dry_run else 'ŽIVĚ'} · token: "
          f"{'nastavený' if token else 'chybí (APIFY_TOKEN v .env)'} · rozpočet {usd(args.budget, 2)} USD · "
          + ("běhy postupně" if args.concurrency <= 1 else f"souběžně až {args.concurrency} běhy"))
    print(f"apify-client {client.get('version') or '?'} · max_total_charge_usd: {_yn(client.get('max_total_charge_usd'))} · "
          f"max_items: {_yn(client.get('max_items'))} · MAX_USD_PER_RUN {usd(ap.max_usd_per_run(), 2)} USD")
    if client.get("max_total_charge_usd") is not True:
        print("POZOR: tento apify-client neumí poslat max_total_charge_usd, živý běh se proto nespustí")
    print(f"Výstup: {out_dir}" + (" · --rerun: testy s uloženými daty běží znovu, stará data -> <T>.<čas>.json"
                                  if getattr(args, "rerun", False) else ""))
    tot_est = tot_worst = tot_cap = cum = 0.0
    runnable = 0
    for t, b in plan:
        dep = DEPS.get(t.key)
        print(f"\n{t.key:<4}{t.title} · {t.actor}" + (f"   [navazuje na {', '.join(dep)}]" if dep else ""))
        print(f"      projde: {t.criterion}")
        if isinstance(b, Skip):
            print(f"      přeskočí se: {b.reason}")
            continue
        if b.conditional:
            print(f"      podmíněně: {b.conditional}")
        for r in b.runs:
            print(f"      {r.label:<4} {json.dumps(r.input, ensure_ascii=False)}")
            unit = f"{r.units} {UNIT.get(r.actor, 'jednotek')} × {r.price + r.addon:.4f}"
            if r.start_fee:
                unit += f" + start {r.start_fee:.3f}"
            worst = f", nejhůř {usd(r.worst)}" if r.worst > r.estimate else ""
            print(f"           {unit} = {usd(r.estimate)} USD{worst} · strop běhu {usd(r.plan_cap(), 2)} USD · max_items {r.max_items}")
        for n in b.notes:
            print(f"      pozn.: {n}")
        est = sum(r.estimate for r in b.runs)
        worst = sum(r.worst for r in b.runs)
        caps = sum(r.plan_cap() for r in b.runs)
        fits = cum + worst <= args.budget + 1e-9
        if fits:
            cum += worst
            tot_est += est
            tot_worst += worst
            tot_cap += caps
            runnable += 1
        print(f"      test: odhad {usd(est)} USD, nejhůř {usd(worst)} USD" + ("" if fits else "  -> NAD ROZPOČET, přeskočí se"))
    print(f"\nCelkem {runnable} testů: odhad {usd(tot_est)} USD, nejhůř {usd(tot_worst)} USD "
          f"(music-data u každého postu, TikTok profily navíc), součet stropů běhů {usd(tot_cap, 2)} USD, "
          f"rozpočet {usd(args.budget, 2)} USD")
    print("Rozpočet se hlídá před každým testem i během; strop běhu (max_total_charge_usd) nikdy nepřesáhne zbytek rozpočtu.")
    return tot_est, tot_worst, runnable


# =============================================================================================
# Report
# =============================================================================================

ENUM_PATHS: dict[str, tuple[str, ...]] = {
    "T1": ("searchSource", "private", "isBusinessAccount", "verified", "businessCategoryName",
           "latestPosts[].type", "latestPosts[].productType"),
    "T2": ("location_city", "city"),
    "T3": ("type", "productType", "paidPartnership", "isPinned"),
    "T4": ("type", "productType", "paidPartnership"),
    "T5": ("private", "isBusinessAccount", "verified", "isRestrictedProfile", "businessCategoryName",
           "latestPosts[].type", "latestPosts[].productType", "latestPosts[].isPinned", "latestPosts[].paidPartnership"),
    "T6": ("type", "productType", "paidPartnership", "isPinned"),
    "T7": (),
    "T8": ("type", "platform"),
    "T9": ("textLanguage", "isSponsored", "isAd", "locationCreated", "authorMeta.region", "authorMeta.isUnderAge18",
           "authorMeta.privateAccount", "authorMeta.verified"),
    "T10": ("textLanguage", "isSponsored", "isAd", "locationCreated", "authorMeta.region", "authorMeta.isUnderAge18",
            "authorMeta.privateAccount", "authorMeta.verified"),
    "T11": ("metadata.sourceType",),
    "T12": ("isPaidContent", "channelLocation", "type"),
}
TYPE_PATHS: dict[str, tuple[str, ...]] = {
    "T2": ("posts",), "T4": ("posts",), "T6": ("firstComment", "affiliate"),
    "T9": ("authorMeta.bioLink", "locationMeta"), "T10": ("authorMeta.bioLink", "locationMeta"), "T11": ("source",),
}
DEEP_KEYS = frozenset({"user", "owner", "location", "author"})
LENGTH_PATHS: dict[str, tuple[str, ...]] = {
    "T1": ("latestPosts", "relatedProfiles"), "T2": ("posts",), "T4": ("posts",),
    "T5": ("latestPosts", "relatedProfiles", "externalUrls"),
    "T6": ("latestComments", "sponsors", "taggedUsers", "coauthorProducers"), "T8": ("brandPartners",),
    "T9": ("hashtags", "mentions"), "T10": ("hashtags", "mentions"),
}
VERIFY_TEXT = {
    1: "username v profile-scraperu", 2: "fullName v profile-scraperu", 3: "hodnoty type u IG postů",
    4: "přejmenované účty", 5: "relatedProfiles u malých účtů", 6: "posts a name u míst ze search-scraperu",
    7: "URL místa v instagram-scraperu", 8: "CITY_BBOX pro Brno", 9: "paidPartnership false",
    10: "klíče sponsors[], latestComments[], taggedUsers[]", 11: "music-data", 12: "popisek TikToku (text)",
    13: "tvar hashtags/mentions na TikToku", 14: "locationName na TikToku", 15: "jméno a počty v authorMeta",
    16: "isUnderAge18 a region", 17: "isSponsored false", 18: "tvar /user", 19: "source u zpráv",
    20: "BRAND_WINDOW", 21: "max_total_charge_usd v klientovi", 22: "minimální strop ceny", 23: "usageTotalUsd",
}


def field_section(key: str, r: dict) -> list[str]:
    items = good_items(r)
    n = len(items)
    out = [f"- Položky: {n} dobrých, {len(error_items(r))} chybových ({error_kinds(r)}), "
           f"{stub_count(r)} vyřazeno před uložením (nezletilí)"]
    if not n:
        return out
    ne: Counter = Counter()
    present: Counter = Counter()
    nested: dict[str, Counter] = {}
    elems: dict[str, int] = {}
    elem_types: dict[str, Counter] = {}
    for i in items:
        for k, val in i.items():
            kn = key_name(k)
            present[kn] += 1
            if nonempty(val):
                ne[kn] += 1
            if isinstance(val, dict):
                nested.setdefault(f"{kn}.*", Counter()).update(key_name(x) for x in val)
                elems[f"{kn}.*"] = elems.get(f"{kn}.*", 0) + 1
            elif isinstance(val, list):
                for el in val:
                    if isinstance(el, dict):
                        nested.setdefault(f"{kn}[]", Counter()).update(key_name(x) for x in el)
                        elems[f"{kn}[]"] = elems.get(f"{kn}[]", 0) + 1
                        for sub in DEEP_KEYS & set(el):   # where authors / places hide in raw IG shapes
                            if isinstance(el[sub], dict):
                                nested.setdefault(f"{kn}[].{sub}.*", Counter()).update(key_name(x) for x in el[sub])
                                elems[f"{kn}[].{sub}.*"] = elems.get(f"{kn}[].{sub}.*", 0) + 1
                    else:
                        elem_types.setdefault(f"{kn}[]", Counter())[type_name(el)] += 1
    out.append(f"- Klíče (neprázdné z {n}): " + ", ".join(f"`{k}` {ne.get(k, 0)}" for k in sorted(present)))
    for k in sorted(nested):
        total = elems.get(k, 0)
        always = sorted(x for x, c in nested[k].items() if c == total)
        some = sorted((x, c) for x, c in nested[k].items() if c != total)
        txt = f"- `{k}` ({total}×) klíče"
        if always:
            txt += " ve všech: " + ", ".join(f"`{x}`" for x in always)
        if some:
            txt += ("; " if always else " ") + "jen v části: " + ", ".join(f"`{x}` {c}" for x, c in some)
        out.append(txt)
    for k in sorted(elem_types):
        out.append(f"- `{k}` typy prvků: {fmt_counter(elem_types[k])}")
    for p in ENUM_PATHS.get(key, ()):
        vals = [x for i in items for x in values_at(i, p)]
        if vals:
            out.append(f"- `{p}`: {fmt_counter(Counter(enum_val(x) for x in vals), 10)}")
    for p in TYPE_PATHS.get(key, ()):
        out.append(f"- typ `{p}`: {fmt_counter(Counter(type_name(x) for i in items for x in values_at(i, p)))}")
    for p in LENGTH_PATHS.get(key, ()):
        out.append(f"- délka `{p}`: {length_stats([i.get(p) for i in items])}")
    for p in ("locationId", "locationName"):
        if p in present:
            k = sum(1 for i in items if s(i.get(p)))
            out.append(f"- podíl s `{p}`: {k}/{n} ({pct(k, n)})")
    return out


def mapper_lines(stats: list[MapStat], note: str) -> list[str]:
    out = []
    for m in stats:
        fails = sum(m.fails.values())
        line = f"- `{m.mapper}` → {m.model}: {m.ok}/{m.total} položek namapováno ({m.objects} objektů)"
        if fails:
            line += f"; nenamapováno {fails}: {fmt_counter(m.fails, 6)}"
        if m.objects:
            top = [(f, c) for f, c in m.empty.most_common() if f not in m.expected]
            if top:
                line += "; nejčastěji prázdné: " + ", ".join(f"`{f}` {c}/{m.objects}" for f, c in top[:10])
            exp = sorted(f for f in m.expected if m.empty.get(f))
            if exp:
                line += f"; čekaně prázdné: {', '.join(exp)}"
        if m.lost:
            line += "; **ztraceno při mapování** (pole prázdné, v surových datech hodnota je): " + \
                ", ".join(f"`{k}` {c}×" for k, c in m.lost.most_common(10))
        out.append(line)
    if note:
        out.append(f"- {note}")
    return out or ["- (žádná data)"]


@dataclass
class Analysis:
    test: TestDef
    data: dict | None
    verdict: Verdict
    maps: list[MapStat]
    map_note: str


def analyze(out_dir: Path) -> list[Analysis]:
    out = []
    for k in TEST_KEYS:
        t = TESTS[k]
        d = load_saved(out_dir, k)
        if d is None:
            out.append(Analysis(t, None, Verdict(), [], ""))
            continue
        try:
            v = t.judge(d)
        except Exception as e:  # noqa: BLE001
            v = Verdict("BEZ DAT", f"vyhodnocení selhalo: {type(e).__name__}")
        try:
            maps, note = mappers_for(k, d)
        except Exception as e:  # noqa: BLE001
            maps, note = [], f"mapování selhalo: {type(e).__name__}"
        out.append(Analysis(t, d, v, maps, note))
    return out


def _totals(a: Analysis) -> tuple[int, int, float, float | None]:
    rr = [r for r in runs_of(a.data) if ran(r)]
    good = sum(len(good_items(r)) for r in rr)
    errs = sum(len(error_items(r)) for r in rr)
    est = sum(num(r.get("estimate_usd")) or 0 for r in rr)
    used = [num(r.get("usage_total_usd")) for r in rr]
    return good, errs, est, (sum(u for u in used if u is not None) if any(u is not None for u in used) else None)


def render_report(analyses: list[Analysis], session: dict[str, str], client: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [REPORT_TITLE, "",
         f"Vygenerováno {now} skriptem `scripts/live_tests.py`. Testy a kritéria: `docs/apify-pro-krystofa.md`, "
         "sekce „Prvních 45 minut“. Surová data: `data/live-tests/<T>.json` (skutečná veřejná data, gitignored; "
         "po hackathonu smazat: `backend/.venv/bin/python scripts/live_tests.py --purge`).",
         "",
         "Report obsahuje jen počty, jména polí, hodnoty výčtových polí, URL a handly testovaných veřejných účtů: "
         "žádné popisky, komentáře, bio ani jména komentujících.", "",
         f"apify-client {client.get('version') or '?'}: `max_total_charge_usd` {_yn(client.get('max_total_charge_usd'))}, "
         f"`max_items` {_yn(client.get('max_items'))} (VERIFY LIVE 21).", "",
         "## Souhrn", "",
         "| Test | Actor | Verdikt | Položky | Chybové | Odhad USD | usageTotalUsd | VERIFY LIVE |",
         "|---|---|---|---|---|---|---|---|"]
    tot_est = tot_used = 0.0
    any_used = False
    for a in analyses:
        if a.data is None:
            note = session.get(a.test.key, "nespuštěno")
            L.append(f"| {a.test.key} | `{a.test.actor}` | – ({note}) | – | – | – | – | "
                     f"{', '.join(map(str, a.test.verify)) or '–'} |")
            continue
        good, errs, est, used = _totals(a)
        tot_est += est
        if used is not None:
            tot_used += used
            any_used = True
        L.append(f"| {a.test.key} | `{a.test.actor}` | **{a.verdict.status}** | {good} | {errs} | {usd(est)} | "
                 f"{usd(used)} | {', '.join(map(str, a.test.verify)) or '–'} |")
    L += ["", f"Celkem: odhad {usd(tot_est)} USD, usageTotalUsd {usd(tot_used if any_used else None)} USD. "
          "Jestli je usageTotalUsd u pay-per-event actorů opravdu účtovaná částka, porovnej s Billing a s eventy "
          "níže (VERIFY LIVE 23).", ""]

    fixes: list[str] = []
    for a in analyses:
        fixes += a.verdict.advice
        for m in a.maps:
            real = {k: c for k, c in m.fails.items() if not k.startswith("chybová položka") and "jiný účet" not in k
                    and "relatedProfiles prázdné" not in k and "bez latestComments" not in k}
            if real:
                fixes.append(f"{a.test.key} `{m.mapper}`: nenamapováno {sum(real.values())} z {m.total} "
                             f"({fmt_counter(Counter(real), 4)})")
            for k, c in m.lost.most_common():
                f, _, path = k.partition(" ← ")
                fixes.append(f"{a.test.key} `{m.mapper}`: {m.model}.{f} zůstává prázdné, i když položka má `{path}` "
                             f"({c}× z {m.objects})")
    L += ["## Co z toho plyne pro provider", ""]
    L += [f"- {x}" for x in fixes] or ["- zatím nic (žádná data nebo vše v pořádku)"]
    L.append("")

    for a in analyses:
        t = a.test
        L += [f"## {t.key}. {t.title} · `{t.actor}`", ""]
        L.append(f"**Kritérium (předávka):** {t.criterion}")
        L.append("")
        if a.data is None:
            L += [f"Nespuštěno ({session.get(t.key, 'žádná uložená data')}).", ""]
            continue
        if t.key in session and session[t.key] != "spuštěno":
            L += [f"Tento běh skriptu: {session[t.key]}; níže jsou starší uložená data.", ""]
        v = a.verdict
        L.append(f"**Verdikt: {v.status}**" + (f": {v.summary}" if v.summary else ""))
        L.append("")
        L.append(f"Uloženo {a.data.get('saved_at', '?')}.")
        for n in a.data.get("notes") or []:
            L.append(f"- {safe_text(n, 300)}")
        L.append("")
        if v.lines:
            L += ["### Kontroly z předávky", ""] + [f"- {x}" for x in v.lines] + [""]
        if v.verify:
            L += ["### VERIFY LIVE", ""]
            L += [f"- **{num_}** ({VERIFY_TEXT.get(num_, '')}): {txt}" for num_, txt in v.verify]
            L.append("")
        L += ["### Běhy", "", "| Běh | Vstup | Stav | Položky | Doba s | Odhad / nejhůř | Strop běhu | usageTotalUsd | Eventy |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in runs_of(a.data):
            status = r.get("status") or "?"
            if r.get("skip_reason"):
                status += f" ({safe_text(r['skip_reason'], 120)})"
            if r.get("error"):
                status += f" (chyba: {safe_text(r['error'], 120)})"
            if r.get("attempts", 0) > 1:
                status += f", pokusů {r['attempts']}"
            L.append(f"| {r.get('label')} | `{fmt_input(r.get('input'))}` | {status} | {len(good_items(r))}/"
                     f"{r.get('items_total', 0)} | {usd(num(r.get('duration_s')), 0)} | {usd(num(r.get('estimate_usd')))} / "
                     f"{usd(num(r.get('worst_usd')))} | {usd(num(r.get('max_total_charge_usd')), 2)} "
                     f"(klient: {_yn(r.get('charge_cap_sent'))}) | {usd(num(r.get('usage_total_usd')))} | {_events(r)} |")
        L.append("")
        for r in runs_of(a.data):
            if not ran(r):
                continue
            L += [f"### Pole {r.get('label')}", ""] + field_section(t.key, r) + [""]
        L += ["### Mapper (offline, `app.sources.apify_provider`)", ""] + mapper_lines(a.maps, a.map_note) + [""]
    return "\n".join(L) + "\n"


def write_report(out_dir: Path, session: dict[str, str]) -> tuple[Path, list[Analysis]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    analyses = analyze(out_dir)
    p = report_path(out_dir)
    p.write_text(render_report(analyses, session, client_info()), "utf-8")
    return p, analyses


def print_summary(analyses: list[Analysis], session: dict[str, str], budget: Budget | None) -> None:
    print("\nSouhrn")
    for a in analyses:
        if a.data is None and a.test.key not in session:
            continue
        if a.data is None:
            print(f"  {a.test.key:<4} {session[a.test.key]}")
            continue
        good, errs, est, used = _totals(a)
        extra = f"  [{session[a.test.key]}]" if a.test.key in session and session[a.test.key] != "spuštěno" else ""
        print(f"  {a.test.key:<4} {a.verdict.status:<8} {good} položek ({errs} chybových) · odhad {usd(est)} · "
              f"usageTotalUsd {usd(used)} · {a.verdict.summary}{extra}")
    if budget is not None:
        print(f"\nTento běh: usageTotalUsd {usd(budget.reported)} USD, do rozpočtu započteno {usd(budget.spent)} "
              f"z {usd(budget.limit, 2)} USD (konzervativně: max(usageTotalUsd, nejhorší odhad, položky × cena); "
              "usageTotalUsd z call() bývá ještě před vyúčtováním, skutečnou cenu ukáže Apify Console)")


REMINDER = ("Pozor: uložená data v data/live-tests/ jsou skutečná veřejná data (gitignored, identita komentujících "
            "odstraněna). Po hackathonu je smaž: backend/.venv/bin/python scripts/live_tests.py --purge")


# =============================================================================================
# CLI
# =============================================================================================


def parse_only(v: str | None) -> list[str]:
    if not v:
        return list(TEST_KEYS)
    out = []
    for x in csv_list(v):
        k = x.upper() if x.upper().startswith("T") else f"T{x}"
        if k not in TESTS:
            raise ValueError(f"neznámý test {x!r}; povolené: {', '.join(TEST_KEYS)}")
        if k not in out:
            out.append(k)
    return sorted(out, key=TEST_KEYS.index)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="live_tests.py",
        description="Živé testy T1 až T12 actorů Apify podle docs/apify-pro-krystofa.md (sekce „Prvních 45 minut“).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Příklad: backend/.venv/bin/python scripts/live_tests.py --only T1,T3,T5 --budget 2")
    p.add_argument("--only", help="jen vybrané testy, např. T1,T5 (výchozí T1 až T12)")
    p.add_argument("--dry-run", action="store_true", help="jen plán a odhady; nic nespouští, funguje bez tokenu")
    p.add_argument("--budget", type=float, default=6.0, help="strop útraty celého skriptu v USD (výchozí 6)")
    p.add_argument("--yes", action="store_true", help="bez potvrzení a bez dotazů na chybějící vstupy")
    p.add_argument("--concurrency", type=int, default=1, help=f"souběžné běhy, 1 až {MAX_CONCURRENCY} (výchozí 1 = postupně)")
    p.add_argument("--out", type=Path, help="adresář pro data a report, jen uvnitř <DATA_DIR>/live-tests (výchozí ten)")
    p.add_argument("--rerun", action="store_true",
                   help="pustit (a zaplatit) i testy, které už mají uložená data; stará data se přesunou do <T>.<čas>.json")
    p.add_argument("--report-only", action="store_true", help="jen přepočítá report.md z uložených dat (bez tokenu)")
    p.add_argument("--purge", action="store_true", help="smaže uložená data a report (po hackathonu)")
    p.add_argument("--force-t7", action="store_true", help="pustit T7 i když T6 vrátil latestComments")
    p.add_argument("--creator", help=f"veřejný český účet tvůrce o jídle místo {DEFAULT_CREATOR} v T5 a T6")
    p.add_argument("--t4-location-id", help="brněnské location ID pro T4 (jinak z T2, záloha z README)")
    p.add_argument("--t5-usernames", help="20 až 50 účtů pro T5 oddělených čárkou (jinak z T1 a T3)")
    p.add_argument("--t6-post-urls", help="až 5 URL IG postů, které mají štítek „Placené partnerství“ (jinak z T3 #spoluprace)")
    p.add_argument("--t7-post-urls", help="3 URL IG postů s komentáři (jinak z latestPosts v T5)")
    p.add_argument("--t10-profiles", help="dva TikTok účty: český,zahraniční (výchozí apifytech,khaby.lame)")
    p.add_argument("--t12-urls", help="dvě URL videí YouTube: se štítkem Includes paid promotion,bez štítku")
    return p.parse_args(argv)


def resolve_out_dir(out: Path | None, data_dir: Path) -> Path | None:
    """--out only inside <DATA_DIR>/live-tests (gitignored): raw data must never land in tests/ or docs/."""
    base = (data_dir / "live-tests").expanduser().resolve()
    if out is None:
        return base
    p = out.expanduser().resolve()
    return p if p == base or base in p.parents else None


def _confirm(prompt: str) -> bool:
    try:
        ans = input(prompt)
    except EOFError:
        return False
    return ans.strip().lower() in ("a", "ano", "y", "yes")


def purge(out_dir: Path, yes: bool) -> int:
    """Deletes only what this script wrote (data files with its _note, its report); other files stay."""
    if not out_dir.is_dir():
        print(f"Nic ke smazání v {out_dir}.")
        return 0
    files = sorted(p for p in out_dir.glob("T*.json") if is_ours(p))
    for name in ("report.md", "report.live_tests.md"):
        p = out_dir / name
        if p.is_file() and p.read_text("utf-8", errors="replace").startswith(REPORT_TITLE):
            files.append(p)
    others = sorted(p.name for p in out_dir.iterdir() if p.is_file() and p not in files)
    if others:
        print(f"Soubory, které tento skript nezapsal, nechávám (smaž je ručně, pokud mají pryč): {', '.join(others)}")
    if not files:
        print(f"Nic z tohoto skriptu ke smazání v {out_dir}.")
        return 0
    print(f"Smažu {len(files)} souborů v {out_dir}: {', '.join(f.name for f in files)}")
    if not yes and not _confirm("Opravdu smazat? [a/N] "):
        print("Nic nesmazáno.")
        return 1
    for f in files:
        f.unlink()
    try:
        out_dir.rmdir()
    except OSError:
        pass
    print("Smazáno.")
    return 0


def main(argv: list[str] | None = None, *, runner: Any = None) -> int:
    args = parse_args(argv)
    try:
        selected = parse_only(args.only)
    except ValueError as e:
        print(f"Chyba: {e}", file=sys.stderr)
        return 2
    if args.t10_profiles and len(csv_list(args.t10_profiles)) != 2:
        print("Chyba: --t10-profiles chce přesně dva účty: český,zahraniční", file=sys.stderr)
        return 2
    if args.t12_urls and len(csv_list(args.t12_urls)) != 2:
        print("Chyba: --t12-urls chce přesně dvě URL: se štítkem,bez štítku", file=sys.stderr)
        return 2
    for opt, val in (("--t6-post-urls", args.t6_post_urls), ("--t7-post-urls", args.t7_post_urls)):
        bad = split_post_urls(csv_list(val))[1]
        if bad:
            print(f"Chyba: {opt} chce URL postů (instagram.com/p/…, /reel/… nebo /tv/…), ne profilů ani jiných "
                  f"stránek: {', '.join(bad)}", file=sys.stderr)
            return 2
    if args.t4_location_id and not args.t4_location_id.isdigit():
        print("Chyba: --t4-location-id je číselné ID místa", file=sys.stderr)
        return 2
    if args.budget <= 0:
        print("Chyba: --budget musí být kladný", file=sys.stderr)
        return 2
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        print(f"Pozn.: --concurrency omezeno na 1 až {MAX_CONCURRENCY} (Apify Free)", file=sys.stderr)
        args.concurrency = min(MAX_CONCURRENCY, max(1, args.concurrency))

    settings = get_settings()
    out_dir = resolve_out_dir(args.out, settings.data_dir)
    if out_dir is None:
        print(f"Chyba: --out musí ležet uvnitř {(settings.data_dir / 'live-tests').expanduser()} (surová data jinam "
              "nepatří; jiné místo nastavíš přes DATA_DIR)", file=sys.stderr)
        return 2
    if args.purge:
        return purge(out_dir, args.yes)
    if args.report_only:
        path, analyses = write_report(out_dir, {})
        print_summary(analyses, {}, None)
        print(f"\nReport: {path}\n{REMINDER}")
        return 0

    token = bool(settings.apify_token)
    client = client_info()
    ctx = Ctx(args, out_dir, interactive=not args.yes and sys.stdin.isatty())
    plan = [(TESTS[k], saved_skip(ctx, k) or build(TESTS[k], ctx, live=False)) for k in selected]
    if args.dry_run:
        print_plan(plan, args, out_dir, token, client)
        print("\nDRY-RUN: nic se nespustilo a nic se neuložilo.")
        return 0
    if not token:
        print("Chyba: APIFY_TOKEN není nastavený. Dej ho do .env v kořeni repa (APIFY_TOKEN=...) a pusť znovu; "
              "bez tokenu funguje jen --dry-run (a --report-only).", file=sys.stderr)
        return 2
    if client.get("max_total_charge_usd") is not True:
        print(f"Chyba: nainstalovaný apify-client ({client.get('version') or '?'}) neumí max_total_charge_usd, živě "
              "nespouštím: jen ten strop omezí cenu běhu (max_items ne). Použij backend/.venv (apify-client 3.x).",
              file=sys.stderr)
        return 2
    est, worst, runnable = print_plan(plan, args, out_dir, token, client)
    if not runnable:
        print("\nNic ke spuštění: všechny vybrané testy se přeskočí (viz výše). Report z uložených dat: --report-only")
        return 0
    if not args.yes and not _confirm(f"\nSpustit živě {runnable} testů? Odhad {usd(est)} USD, nejhůř {usd(worst)} USD, "
                                     f"rozpočet {usd(args.budget, 2)} USD. [a/N] "):
        print("Nic se nespustilo.")
        return 1
    runner = runner or ap._ClientRunner(settings.apify_token)
    budget = Budget(args.budget)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = asyncio.run(run_live(ctx, [TESTS[k] for k in selected], runner, budget, args.concurrency))
    path, analyses = write_report(out_dir, session)
    print_summary(analyses, session, budget)
    print(f"\nReport: {path}\n{REMINDER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
