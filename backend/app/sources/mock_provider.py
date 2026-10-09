"""MockProvider: reads the fictional dataset in fixtures/ (see fixtures/README.md), mode "mock".

Fixture layout (written by fixtures/generate.py, every file in the normalized model shapes):
  fixtures/meta.json            {"anchor": iso, ...}  all fixture timestamps are relative to anchor
  fixtures/discovery.json       [CandidateRef]  one per (creator, discovery path)
  fixtures/profiles.json        [Profile] with latest_posts
  fixtures/posts.json           {"<platform>:<handle>": [Post]}  older posts (round 4)
  fixtures/comments.json        {post_url: [Comment]}
  fixtures/collabs.json         {"<platform>:<handle>": [CollabEvidence]}  (meta_branded)
  fixtures/news.json            [NewsItem]
  fixtures/cross_platform.json  {"<platform>:<handle>": [Profile]}

Behaviour:
- Dates are shifted at load by ``now - anchor`` so the dataset is always "fresh" (a creator who
  posted 1 day before the anchor posted 1 day before now). Reloaded when the data is > 6 h old.
- Every returned object (and every nested SourceRef) gets ``mode = "mock"``,
  ``actor = "mock:<method>"`` and ``fetched_at = now``. Objects are deep copies.
- Minors (``is_under_18``) are dropped in discover(), profiles() and find_cross_platform()
  before anything is returned; only a count is logged.
- ``await asyncio.sleep(latency)`` per call (MOCK_LATENCY). Every call logs one line via emit_log.
- Never raises: unknown handles / unsupported calls / broken fixtures -> [] plus a log line.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
    iter_source_refs,
    norm_handle,
    utcnow,
)

DATE_KEYS = frozenset({"created_at", "published_at", "date", "fetched_at"})
RELOAD_AFTER = timedelta(hours=6)
PATH_ORDER = ("search", "hashtag", "place", "related", "manual")

# Raw JSON per file, cached by (path, mtime) so every new MockProvider does not re-read 2 MB.
_RAW_CACHE: dict[str, tuple[int, Any]] = {}


def _read_json(path: Path) -> Any:
    key = str(path)
    mtime = path.stat().st_mtime_ns
    hit = _RAW_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    data = json.loads(path.read_text("utf-8"))
    _RAW_CACHE[key] = (mtime, data)
    return data


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def _words(s: str) -> list[str]:
    return [w.strip("._") for w in re.split(r"[^0-9a-z_.]+", _fold(s).replace("@", " ")) if w.strip("._")]


def _cs(n: int, one: str, few: str, many: str) -> str:
    """Czech plural: 1 článek, 2 články, 5 článků."""
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


def _en(n: int, one: str, many: str) -> str:
    """English plural: 1 article, 0 / 2 articles."""
    return f"{n} {one if n == 1 else many}"


def _parse_dt(v: str) -> datetime:
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _shift(obj: Any, delta: timedelta) -> Any:
    """Copy of raw JSON with every date field moved by delta."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in DATE_KEYS and isinstance(v, str):
                try:
                    out[k] = (_parse_dt(v) + delta).isoformat()
                except ValueError:
                    out[k] = v
            else:
                out[k] = _shift(v, delta)
        return out
    if isinstance(obj, list):
        return [_shift(x, delta) for x in obj]
    return obj


def _url_key(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _pkey(platform: str, handle: str) -> str:
    return f"{platform}:{norm_handle(handle)}"


class _Data:
    """Validated, date-shifted fixture data for one provider instance."""

    def __init__(self, fixtures_dir: Path, now: datetime) -> None:
        meta = _read_json(fixtures_dir / "meta.json")
        self.anchor = _parse_dt(meta["anchor"])
        self.loaded_at = now
        delta = now - self.anchor

        def load(name: str, default: Any) -> Any:
            path = fixtures_dir / name
            if not path.exists():
                return default
            return _shift(_read_json(path), delta)

        self.refs = [CandidateRef.model_validate(x) for x in load("discovery.json", [])]
        self.profiles: dict[str, Profile] = {}
        for x in load("profiles.json", []):
            p = Profile.model_validate(x)
            self.profiles[_pkey(p.platform, p.handle)] = p
        self.extra_posts = {k: [Post.model_validate(x) for x in v] for k, v in load("posts.json", {}).items()}
        self.comments = {_url_key(k): [Comment.model_validate(x) for x in v]
                         for k, v in load("comments.json", {}).items()}
        self.collabs = {k: [CollabEvidence.model_validate(x) for x in v] for k, v in load("collabs.json", {}).items()}
        self.news = [NewsItem.model_validate(x) for x in load("news.json", [])]
        self.cross = {k: [Profile.model_validate(x) for x in v] for k, v in load("cross_platform.json", {}).items()}

    def profile(self, platform: str, handle: str) -> Profile | None:
        p = self.profiles.get(_pkey(platform, handle))
        if p is not None:
            return p
        h = norm_handle(handle)  # renamed account: match a former handle
        for q in self.profiles.values():
            if q.platform == platform and h in q.former_handles:
                return q
        return None


def _safe(method: str):
    """Decorator: sleep latency, never raise (log + [])."""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self: "MockProvider", *args, **kwargs):
            try:
                if self.latency > 0:
                    await asyncio.sleep(self.latency)
                return await fn(self, *args, **kwargs)
            except Exception as e:  # never raise into the funnel
                await emit_log(f"mock {method}: chyba v MOCK datech ({type(e).__name__}: {e}); vracím []",
                               actor=f"mock:{method}", mode="mock")
                return []

        return wrapper

    return deco


class MockProvider:
    name: str = "mock"

    def __init__(self, fixtures_dir: Path | None = None, latency: float | None = None, *,
                 now: datetime | None = None) -> None:
        """Defaults: get_settings().fixtures_dir and get_settings().mock_latency. Loads lazily.
        ``now`` pins the clock (tests); otherwise utcnow() at load time anchors the date shift."""
        s = get_settings()
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else s.fixtures_dir
        self.latency = s.mock_latency if latency is None else max(0.0, float(latency))
        self._fixed_now = now
        self._data: _Data | None = None

    # ------------------------------------------------------------------ helpers

    def now(self) -> datetime:
        return self._fixed_now or utcnow()

    @property
    def data(self) -> _Data:
        now = self.now()
        if self._data is None or (self._fixed_now is None and now - self._data.loaded_at > RELOAD_AFTER):
            self._data = _Data(self.fixtures_dir, now)
        return self._data

    def _label(self, obj: Any, method: str) -> Any:
        """Deep copy with every nested SourceRef labeled mock / mock:<method> / now."""
        copy = obj.model_copy(deep=True)
        now = self.now()
        for ref in iter_source_refs(copy):
            ref.mode = "mock"
            ref.actor = f"mock:{method}"
            ref.fetched_at = now
        return copy

    async def _log(self, method: str, text: str) -> None:
        line = f"MOCK {text}"
        await emit_log(tr(line, line) if type(text) is not str else line, actor=f"mock:{method}", mode="mock")

    # ------------------------------------------------------------------ SourceProvider

    @_safe("discover")
    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]:
        d = self.data
        platforms = set(q.platforms or [])
        refs = [r for r in d.refs if not platforms or r.platform in platforms]
        keywords = {_fold(k) for k in q.keywords if k.strip()}
        hashtags = {norm_handle(t) for t in q.hashtags if t.strip()}
        places = {_fold(p) for p in [*q.places, q.city or ""] if p and p.strip()}
        city_words = {w for p in places for w in _words(p)}

        def kw_match(value: str) -> bool:
            v = _fold(value)
            if v in keywords:
                return True
            vw = [w for w in _words(v) if w not in city_words and len(w) >= 3]
            for k in keywords:
                kw = [w for w in _words(k) if w not in city_words and len(w) >= 3]
                if any(a[:5] == b[:5] for a in vw for b in kw):
                    return True
            return False

        def matches(path: str) -> bool:
            kind, _, value = path.partition(":")
            if kind == "hashtag":
                return norm_handle(value) in hashtags
            if kind == "search":
                return kw_match(value)
            if kind == "place":
                v = _fold(value)
                return any(p in v for p in places)
            return False

        kept: list[tuple[CandidateRef, str]] = []
        found: set[tuple[str, str]] = set()
        for r in refs:
            for path in r.found_via:
                if matches(path):
                    kept.append((r, path))
                    found.add((r.platform, r.handle))
        # "related:@x" paths count when @x itself was found (transitively)
        changed = True
        while changed:
            changed = False
            for r in refs:
                for path in r.found_via:
                    kind, _, value = path.partition(":")
                    if kind != "related" or (r, path) in kept:
                        continue
                    if (r.platform, norm_handle(value)) in found or any(
                            (pl, norm_handle(value)) in found for pl in ("instagram", "tiktok")):
                        kept.append((r, path))
                        found.add((r.platform, r.handle))
                        changed = True
        fallback = not kept
        if fallback:
            kept = [(r, p) for r in refs for p in r.found_via]

        # minors: drop before returning, count only
        minors = {(r.platform, r.handle) for r, _ in kept
                  if (p := d.profile(r.platform, r.handle)) is not None and p.is_under_18}
        order = {k: i for i, k in enumerate(PATH_ORDER)}
        kept.sort(key=lambda rp: order.get(rp[1].partition(":")[0], len(order)))
        out: list[CandidateRef] = []
        for r, path in kept:
            if (r.platform, r.handle) in minors:
                continue
            ref = self._label(r, "discover")
            ref.found_via = [path]
            out.append(ref)
        unique = len({(r.platform, r.handle) for r in out})
        msg_cs = f"hledání: {_cs(len(out), 'nález', 'nálezy', 'nálezů')}, {_cs(unique, 'účet', 'účty', 'účtů')}"
        msg_en = f"discover: {_en(len(out), 'hit', 'hits')}, {_en(unique, 'account', 'accounts')}"
        if fallback:
            msg_cs += " (dotaz v MOCK datech nic nenašel, vracím celý MOCK seznam)"
            msg_en += " (the MOCK query found nothing, returning the whole MOCK list)"
        if minors:
            msg_cs += f"; mladší 18 let vynecháno: {len(minors)} (nic se neukládá)"
            msg_en += f"; under 18 left out: {len(minors)} (nothing is stored)"
        await self._log("discover", tr(msg_cs, msg_en))
        return out

    @_safe("profiles")
    async def profiles(self, handles: list[str], platform: Platform) -> list[Profile]:
        d = self.data
        out: list[Profile] = []
        missing: list[str] = []
        minors = 0
        seen: set[str] = set()
        for h in handles:
            hn = norm_handle(h)
            if not hn or hn in seen:
                continue
            seen.add(hn)
            p = d.profile(platform, hn)
            if p is None:
                missing.append(hn)
                continue
            if p.is_under_18:
                minors += 1
                continue
            out.append(self._label(p, "profiles"))
        msg_cs = f"profily {platform}: {len(out)}/{len(seen)}"
        msg_en = f"profiles {platform}: {len(out)}/{len(seen)}"
        if missing:
            miss = ", ".join("@" + m for m in missing[:5]) + ("…" if len(missing) > 5 else "")
            msg_cs += f"; nenalezeno: {miss}"
            msg_en += f"; not found: {miss}"
        if minors:
            msg_cs += f"; mladší 18 let vynecháno: {minors} (nic se neukládá)"
            msg_en += f"; under 18 left out: {minors} (nothing is stored)"
        await self._log("profiles", tr(msg_cs, msg_en))
        return out

    @_safe("posts")
    async def posts(self, handle: str, platform: Platform, since: datetime, limit: int = 50) -> list[Post]:
        d = self.data
        p = d.profile(platform, handle)
        if p is None or p.is_under_18:
            await self._log("posts", tr(f"posty @{norm_handle(handle)}: účet v MOCK datech není",
                                        f"posts @{norm_handle(handle)}: account not in the MOCK data"))
            return []
        if p.private:
            await self._log("posts", tr(f"posty @{p.handle}: soukromý účet, posty nejsou vidět",
                                        f"posts @{p.handle}: private account, posts not visible"))
            return []
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        merged: dict[str, Post] = {}
        for post in [*p.latest_posts, *d.extra_posts.get(_pkey(p.platform, p.handle), [])]:
            merged.setdefault(post.id, post)
        posts = sorted((x for x in merged.values() if x.created_at >= since), key=lambda x: x.created_at, reverse=True)
        posts = posts[: max(0, int(limit))]
        await self._log("posts", tr(f"posty @{p.handle}: {_cs(len(posts), 'post', 'posty', 'postů')} od {since.date().isoformat()}",
                                    f"posts @{p.handle}: {_en(len(posts), 'post', 'posts')} since {since.date().isoformat()}"))
        return [self._label(x, "posts") for x in posts]

    @_safe("comments")
    async def comments(self, post_urls: list[str], per_post: int = 15) -> list[Comment]:
        d = self.data
        out: list[Comment] = []
        with_comments = 0
        keys = list(dict.fromkeys(_url_key(u) for u in post_urls if u))
        for key in keys:
            lst = d.comments.get(key, [])[: max(0, int(per_post))]
            if lst:
                with_comments += 1
            out.extend(self._label(c, "comments") for c in lst)
        await self._log("comments", tr(f"komentáře: {_cs(len(out), 'komentář', 'komentáře', 'komentářů')} z {with_comments}/{len(keys)} postů "
                                       "(jen text, bez jmen komentujících)",
                                       f"comments: {_en(len(out), 'comment', 'comments')} from {with_comments}/{len(keys)} posts "
                                       "(text only, no commenter names)"))
        return out

    @_safe("collabs")
    async def collabs(self, handle: str, platform: Platform) -> list[CollabEvidence]:
        d = self.data
        if platform not in ("instagram",):
            await self._log("collabs", tr(f"spolupráce @{norm_handle(handle)}: Meta Branded Content jen pro Instagram/Facebook",
                                          f"collabs @{norm_handle(handle)}: Meta Branded Content covers Instagram/Facebook only"))
            return []
        items = d.collabs.get(_pkey(platform, handle), [])
        await self._log("collabs", tr(f"spolupráce @{norm_handle(handle)}: {_cs(len(items), 'záznam', 'záznamy', 'záznamů')} v Meta Branded Content",
                                      f"collabs @{norm_handle(handle)}: {_en(len(items), 'record', 'records')} in Meta Branded Content"))
        return [self._label(x, "collabs") for x in items]

    @_safe("news")
    async def news(self, query: str, lang: str = "cs", region: str = "CZ", limit: int = 10) -> list[NewsItem]:
        d = self.data
        q = [w for w in _words(query.replace('"', " ")) if len(w.strip("._")) >= 2]
        if not q:
            return []
        need = min(2, len(q))
        out = []
        for item in d.news:
            words = _words(f"{item.title} {item.snippet}")
            hits = sum(1 for t in q if any(w == t or (len(t) >= 4 and w.startswith(t)) for w in words))
            if hits >= need:
                out.append(item)
        out.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        out = out[: max(0, int(limit))]
        await self._log("news", tr(f"zprávy „{query}“: {_cs(len(out), 'článek', 'články', 'článků')}",
                                   f"news \"{query}\": {_en(len(out), 'article', 'articles')}"))
        return [self._label(x, "news") for x in out]

    @_safe("find_cross_platform")
    async def find_cross_platform(self, profile: Profile) -> list[Profile]:
        d = self.data
        items = [p for p in d.cross.get(_pkey(profile.platform, profile.handle), []) if not p.is_under_18]
        await self._log("find_cross_platform", tr(
            f"jiné sítě @{profile.handle}: {_cs(len(items), 'možný profil', 'možné profily', 'možných profilů')} stejného tvůrce",
            f"cross-platform @{profile.handle}: {_en(len(items), 'possible profile', 'possible profiles')} of the same creator"))
        return [self._label(p, "find_cross_platform") for p in items]
