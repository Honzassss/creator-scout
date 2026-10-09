"""CachedProvider(inner): hash(method, args) -> data/cache/<hash>.json; mode "cache" on hit.

- Key: ``cache_key(method, args, provider_name)`` = sha256 of canonical JSON
  {"provider", "method", "args"}: dict keys sorted, string lists sorted + deduplicated, handles
  normalized, datetimes reduced to the UTC date, pydantic models dumped. The canonical form is
  idempotent, so a key can be recomputed from a file's meta.
- Granularity: ``profiles`` is cached per handle and ``comments`` per post URL (a batch call reads
  what it can and fetches only the missing handles / URLs in ONE inner call); other methods per call.
- ``posts`` is keyed by handle + platform + limit, WITHOUT ``since`` (Brno run 9. 10. 2026: the UTC date
  of since=now-180d was in the key, so round 4 missed the cache the next day). A miss asks the inner
  provider for the full list (since POSTS_FULL_SINCE; the post-scraper costs the same, it never sends a
  date) and every read filters ``created_at >= since``. An entry stored with a ``meta.since`` floor
  (imported or legacy since-keyed files) serves only requests from that day on. Legacy since-keyed
  files are still found (by their meta) for offline replays of old caches.
- Inner providers whose ``cache_variant(method)`` returns a string (a config switch that changes the
  answer, e.g. Apify collabs with APIFY_META_BRANDED off, discover with a non-default search switch) get it
  added to that method's key (collabs, discover).
- Inner providers with ``cache_hit(method, items)`` get every hit passed through it before it is returned
  (Apify: pinned posts inferred on IG profiles cached before that rule existed).
- File: ``{"meta": {"provider", "method", "args", "actor", "fetched_at", "count"[, "empty", "since"]},
  "items": [...]}``.
- Miss: call inner, write the JSON-dumped result and return the inner objects unchanged (mode stays
  "live"/"mock"). An EMPTY result is written (``meta.empty = true``) only for EMPTY_IS_ANSWER methods
  and only when the inner provider confirmed the call complete (``answer_is_complete()``: no failed,
  skipped, capped or error-only run); otherwise an empty answer may be a failed fetch and must not poison
  the cache. Brno run 9. 10. 2026: replays logged "not in cache: cross-platform/collabs @x" because the
  real [] answers were never stored. An empty entry of any other method is read as a miss.
- Hit: validate into the method's model, drop minors, set EVERY nested SourceRef.mode = "cache"
  (actor and fetched_at keep the original fetch), emit_log(..., mode="cache"). An empty entry is a hit.
- ``read_only=True`` (alias ``offline=True``, SOURCE_MODE=cache without a token): never calls
  inner and never writes; a miss returns [] and logs it.
- Never raises into the funnel (corrupt file -> miss; inner error -> [] + log).
- ``import_cache_dir(src)`` imports a directory of cache files (e.g. Kryštof's live run), splitting
  batch files per handle / URL and re-keying them from their meta. CLI:
  ``python -m app.sources.cache import <dir>`` / ``python -m app.sources.cache purge``.

Note: the cache holds provider output validated into the models (no commenter identities, no
minors) but BEFORE the sensitive filter, which the rounds apply right after every fetch, before
anything is stored in a run. So data/cache can hold captions the run itself never stores until
``purge_cache`` / POST /api/purge ("Smazat data") deletes it. It is runtime data in DATA_DIR (gitignored).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.events import emit_log
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
from app.compute.minors import is_minor
from app.sources.base import SourceProvider

MODEL_FOR: dict[str, type[BaseModel]] = {
    "discover": CandidateRef,
    "profiles": Profile,
    "posts": Post,
    "comments": Comment,
    "collabs": CollabEvidence,
    "news": NewsItem,
    "find_cross_platform": Profile,
}
DEFAULT_IMPORT_PROVIDER = "apify"   # Kryštof's files come from CachedProvider(ApifyProvider())
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
# Methods whose confirmed-complete [] is a real answer worth caching (no comments, no collabs, no news, no linked
# account). Not discover (an empty discovery is a failure to look into), not profiles (a missing handle is cached
# by its absence: renamed or temporarily unavailable accounts must be retried) and not posts: the entry is the
# full list, kept without a date in its key, and an empty full list is almost always a block or a gap (one
# would hide the creator's posts until a purge); an invalid handle starts no run, so retrying it costs nothing.
EMPTY_IS_ANSWER = frozenset({"comments", "collabs", "news", "find_cross_platform"})
# ``since`` of the full-list posts call a miss makes (the inner provider filters nothing).
POSTS_FULL_SINCE = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------
# "This answer is complete" (inner provider -> CachedProvider)
# ---------------------------------------------------------------------------------------------


class _FetchOutcome:
    __slots__ = ("complete",)

    def __init__(self) -> None:
        self.complete = False


_OUTCOME: ContextVar[_FetchOutcome | None] = ContextVar("cache_fetch_outcome", default=None)


def answer_is_complete() -> None:
    """Called by an inner provider inside a method call that finished without a failed, skipped or partial
    fetch: its result, even [], is the real answer, so CachedProvider may cache an empty list (EMPTY_IS_ANSWER
    methods only). A no-op outside CachedProvider. Providers that never call it never get an empty entry."""
    o = _OUTCOME.get()
    if o is not None:
        o.complete = True


# ---------------------------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------------------------


def _canon(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return _canon(v.model_dump(mode="json"))
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple, set, frozenset)):
        items = [_canon(x) for x in v]
        if items and all(isinstance(x, str) for x in items):
            return sorted(set(items))
        return items
    return v


def cache_key(method: str, args: dict[str, Any], provider_name: str = "") -> str:
    payload = {"provider": provider_name, "method": method, "args": _canon(args)}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _url_key(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _profiles_args(handle: str, platform: str) -> dict:
    return {"handles": [norm_handle(handle)], "platform": platform}


def _comments_args(url: str, per_post: int) -> dict:
    return {"post_urls": [_url_key(url)], "per_post": int(per_post)}


def _posts_args(handle: str, platform: str, limit: int) -> dict:
    return {"handle": norm_handle(handle), "platform": platform, "limit": int(limit)}


def _utc(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _since_floor(meta: dict) -> date | None:
    """The first day a posts entry is complete for (None = the full list)."""
    v = meta.get("since") if isinstance(meta, dict) else None
    if not isinstance(v, str) or not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return date.max   # unreadable floor: never trust the entry for any since


def _posts_since(items: list, since: datetime, limit: int) -> list:
    """Stored full list -> what posts(since, limit) returns: created_at >= since, newest first, at most limit."""
    s = _utc(since)
    keep = [p for p in items if isinstance(p, Post) and p.created_at >= s]
    return sorted(keep, key=lambda p: p.created_at, reverse=True)[: max(0, int(limit))]


# ---------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


def _validate_items(method: str, raw_items: Any) -> tuple[list[BaseModel], int]:
    """-> (valid models without minors, number of invalid items)."""
    model = MODEL_FOR[method]
    out: list[BaseModel] = []
    bad = 0
    for x in raw_items if isinstance(raw_items, list) else []:
        try:
            m = model.model_validate(x)
        except ValidationError:
            bad += 1
            continue
        if isinstance(m, Profile) and is_minor(m):
            continue  # hard line: minors (flag or an explicit age under 18 in the bio) never leave the provider layer
        out.append(m)
    return out, bad


def purge_cache(cache_dir: Path | None = None) -> int:
    """Delete all cached source files; return number deleted. Default dir get_settings().cache_dir."""
    d = Path(cache_dir) if cache_dir else get_settings().cache_dir
    if not d.exists():
        return 0
    n = 0
    for f in list(d.glob("*.json")) + list(d.glob(".*.tmp")):
        try:
            f.unlink()
            n += f.suffix == ".json"
        except OSError:
            pass
    return n


# ---------------------------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------------------------


class CachedProvider:
    name: str  # f"cache({inner.name})"

    def __init__(self, inner: SourceProvider, cache_dir: Path | None = None, read_only: bool = False, *,
                 offline: bool | None = None, data_dir: Path | None = None, key_name: str | None = None) -> None:
        """``cache_dir`` defaults to get_settings().cache_dir (resolved at call time); ``data_dir``
        is an alternative (uses data_dir/cache). ``offline`` is an alias of ``read_only``.
        ``key_name`` fixes the cache namespace independently of the inner provider's display name
        (a stand-in for a provider that cannot be built must still read that provider's entries)."""
        self.inner = inner
        self.inner_name = getattr(inner, "name", type(inner).__name__)
        self.key_name = key_name or self.inner_name
        self.name = f"cache({self.inner_name})"
        if cache_dir is None and data_dir is not None:
            cache_dir = Path(data_dir) / "cache"
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self.read_only = bool(offline) if offline is not None else bool(read_only)
        self.stats = {"hits": 0, "misses": 0, "writes": 0, "errors": 0}
        self._legacy_posts: dict[tuple[str, str, int], list[tuple[date, Path]]] | None = None

    @property
    def offline(self) -> bool:
        return self.read_only

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or get_settings().cache_dir

    def path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    # ------------------------------------------------------------------ primitives

    def _read_path(self, method: str, path: Path) -> tuple[list[BaseModel], dict] | None:
        """File -> (items passed through the inner ``cache_hit`` hook, relabeled "cache", meta); missing / corrupt
        -> None, and so is an empty entry of a method outside EMPTY_IS_ANSWER (e.g. posts [] written before
        empty posts stopped being an answer). No stats."""
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text("utf-8"))
            items_raw = raw["items"] if isinstance(raw, dict) else raw
            meta = raw.get("meta", {}) if isinstance(raw, dict) else {}
            items, bad = _validate_items(method, items_raw)
        except (OSError, ValueError, KeyError, TypeError):
            self.stats["errors"] += 1
            return None
        if bad and not items:
            self.stats["errors"] += 1
            return None
        if not items and method not in EMPTY_IS_ANSWER:
            return None
        items = self._hit_fixup(method, items)
        for item in items:
            for ref in iter_source_refs(item):
                ref.mode = "cache"
        return items, meta if isinstance(meta, dict) else {}

    def _hit_fixup(self, method: str, items: list[BaseModel]) -> list[BaseModel]:
        """inner.cache_hit(method, items) when the inner provider has one (see the module docstring)."""
        fn = getattr(self.inner, "cache_hit", None)
        if not callable(fn) or not items:
            return items
        try:
            out = fn(method, items)
        except Exception:
            return items
        if asyncio.iscoroutine(out):   # a wrapper that turns every attribute into a coroutine (test spies)
            out.close()
            return items
        return list(out) if isinstance(out, list) else items

    def _read(self, method: str, args: dict) -> tuple[list[BaseModel], dict] | None:
        """Hit -> (items relabeled "cache", meta); miss / corrupt -> None. An empty entry is a hit."""
        hit = self._read_path(method, self.path_for(cache_key(method, args, self.key_name)))
        if hit is not None:
            self.stats["hits"] += 1
        return hit

    def _write(self, method: str, args: dict, items: list[BaseModel], *, empty_ok: bool = False,
               extra_meta: dict | None = None) -> None:
        """Write an entry. [] only with ``empty_ok`` (a confirmed real answer, meta.empty = true); never in
        read-only mode."""
        if self.read_only or (not items and not (empty_ok and method in EMPTY_IS_ANSWER)):
            return
        actor = None
        for ref in iter_source_refs(items[0]) if items else ():
            actor = ref.actor
            break
        meta: dict[str, Any] = {
            "provider": self.key_name,
            "method": method,
            "args": _canon(args),
            "actor": actor or f"{self.inner_name}:{method}",
            "fetched_at": utcnow().isoformat(),
            "count": len(items),
        }
        if not items:
            meta["empty"] = True
        meta.update(extra_meta or {})
        payload = {"meta": meta, "items": [m.model_dump(mode="json") for m in items]}
        try:
            _write_atomic(self.path_for(cache_key(method, args, self.key_name)), payload)
            self.stats["writes"] += 1
        except OSError:  # a read-only / full disk must not break the funnel
            self.stats["errors"] += 1

    def _variant(self, method: str) -> str | None:
        """inner.cache_variant(method) when the inner provider has one (see the module docstring)."""
        fn = getattr(self.inner, "cache_variant", None)
        if not callable(fn):
            return None
        try:
            v = fn(method)
        except Exception:
            return None
        if asyncio.iscoroutine(v):   # a wrapper that turns every attribute into a coroutine (test spies)
            v.close()
            return None
        return v if isinstance(v, str) and v else None

    async def _log(self, text: str, *, actor: str | None = None, mode: str | None = "cache") -> None:
        await emit_log(text, actor=actor or f"cache:{self.inner_name}", mode=mode)  # type: ignore[arg-type]

    async def _fetch_checked(self, method: str, call: Callable[[], Awaitable[list]]) -> tuple[list, bool]:
        """-> (items, complete): complete when the inner provider called answer_is_complete() during the call."""
        outcome = _FetchOutcome()
        token = _OUTCOME.set(outcome)
        try:
            result = await call()
            return list(result or []), outcome.complete
        except Exception as e:  # inner providers should not raise, but never trust that
            self.stats["errors"] += 1
            await self._log(f"{self.inner_name} {method}: chyba {type(e).__name__}, vracím []", mode=None)
            return [], False
        finally:
            _OUTCOME.reset(token)

    async def _fetch(self, method: str, call: Callable[[], Awaitable[list]]) -> list:
        return (await self._fetch_checked(method, call))[0]

    @staticmethod
    def _hit_text(label: str, items: list, meta: dict) -> str:
        return f"z cache: {label} ({len(items)}{', prázdná odpověď' if meta.get('empty') else ''})"

    async def _cached(self, method: str, args: dict, call: Callable[[], Awaitable[list]], label: str) -> list:
        try:
            hit = self._read(method, args)
        except Exception:
            hit = None
        if hit is not None:
            items, meta = hit
            await self._log(self._hit_text(label, items, meta), actor=meta.get("actor"))
            return items
        self.stats["misses"] += 1
        if self.read_only:
            await self._log(f"není v cache: {label}; offline režim nic nestahuje")
            return []
        items, complete = await self._fetch_checked(method, call)
        try:
            self._write(method, args, items, empty_ok=complete)
        except Exception:
            self.stats["errors"] += 1
        return items

    # ------------------------------------------------------------------ SourceProvider

    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]:
        args: dict[str, Any] = {"q": q}
        variant = self._variant("discover")
        if variant:
            args["variant"] = variant
        return await self._cached("discover", args, lambda: self.inner.discover(q), "discover")

    async def profiles(self, handles: list[str], platform: Platform) -> list[Profile]:
        try:
            wanted = list(dict.fromkeys(h for h in (norm_handle(x) for x in handles) if h))
            found: dict[str, Profile] = {}
            actors: set[str] = set()
            for h in wanted:
                hit = self._read("profiles", _profiles_args(h, platform))
                if hit and hit[0]:
                    found[h] = hit[0][0]  # type: ignore[assignment]
                    actors.add(hit[1].get("actor") or "")
            if found:
                await self._log(f"z cache: profiles {platform} ({len(found)}/{len(wanted)})",
                                actor=next(iter(a for a in actors if a), None))
            missing = [h for h in wanted if h not in found]
            if missing:
                self.stats["misses"] += len(missing)
                if self.read_only:
                    await self._log(f"není v cache: profiles {platform} ({len(missing)}); offline režim nic nestahuje")
                else:
                    fetched = await self._fetch("profiles", lambda: self.inner.profiles(missing, platform))
                    for p in fetched:
                        if not isinstance(p, Profile) or is_minor(p):
                            continue
                        keys = [p.handle] + [h for h in missing if h in p.former_handles]
                        for k in keys:
                            if k in missing and k not in found:
                                found[k] = p
                                self._write("profiles", _profiles_args(k, platform), [p])
            return [found[h] for h in wanted if h in found]
        except Exception as e:
            self.stats["errors"] += 1
            await self._log(f"cache profiles: chyba {type(e).__name__}, vracím []", mode=None)
            return []

    def _legacy_posts_index(self) -> dict[tuple[str, str, int], list[tuple[date, Path]]]:
        """Posts files of the old key layout (``since`` in the key), found by their meta; built once."""
        if self._legacy_posts is None:
            idx: dict[tuple[str, str, int], list[tuple[date, Path]]] = {}
            d = self.cache_dir
            for f in sorted(d.glob("*.json")) if d.exists() else []:
                try:
                    text = f.read_text("utf-8")
                    if '"posts"' not in text:
                        continue
                    raw = json.loads(text)
                    meta = raw.get("meta") if isinstance(raw, dict) else None
                    args = meta.get("args") if isinstance(meta, dict) else None
                    if meta.get("method") != "posts" or not isinstance(args, dict) or not args.get("since"):
                        continue
                    if meta.get("provider") not in (None, self.key_name):
                        continue
                    k = (norm_handle(str(args.get("handle") or "")), str(args.get("platform")), int(args.get("limit")))
                    day = date.fromisoformat(str(args["since"])[:10])
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
                idx.setdefault(k, []).append((day, f))
            self._legacy_posts = idx
        return self._legacy_posts

    def _read_legacy_posts(self, handle: str, platform: str, limit: int, since: datetime
                           ) -> tuple[list[BaseModel], dict] | None:
        """A since-keyed entry is complete for any since from its day on (it was filtered with that day's since)."""
        day = _utc(since).date()
        cands = [(d, f) for d, f in self._legacy_posts_index().get((handle, platform, int(limit)), []) if d <= day]
        for d, f in sorted(cands, key=lambda x: x[0], reverse=True):
            hit = self._read_path("posts", f)
            if hit is not None:
                return hit[0], {**hit[1], "since": d.isoformat(), "legacy_file": f.name}
        return None

    async def posts(self, handle: str, platform: Platform, since: datetime, limit: int = 50) -> list[Post]:
        h = norm_handle(handle)
        label = f"posts @{h}"
        try:
            since = _utc(since)
            args = _posts_args(h, platform, limit)
            hit = self._read_path("posts", self.path_for(cache_key("posts", args, self.key_name)))
            if hit is not None:
                floor = _since_floor(hit[1])
                if floor is not None and since.date() < floor:
                    hit = None   # stored only from a later day on: incomplete for this since
            if hit is None:
                hit = self._read_legacy_posts(h, platform, limit, since)   # read in place, never rewritten
            if hit is not None:
                self.stats["hits"] += 1
                items, meta = hit
                out = _posts_since(items, since, limit)
                empty = ", prázdná odpověď" if meta.get("empty") else ""
                await self._log(f"z cache: {label} od {since.date().isoformat()} ({len(out)} z {len(items)}{empty})",
                                actor=meta.get("actor"))
                return out
            self.stats["misses"] += 1
            if self.read_only:
                await self._log(f"není v cache: {label}; offline režim nic nestahuje")
                return []
            # The full list (the post-scraper never sends a date, so it costs the same); filtered on every read.
            items, complete = await self._fetch_checked(
                "posts", lambda: self.inner.posts(handle, platform, POSTS_FULL_SINCE, limit))
            try:
                self._write("posts", args, items, empty_ok=complete)
            except Exception:
                self.stats["errors"] += 1
            return _posts_since(items, since, limit)
        except Exception as e:
            self.stats["errors"] += 1
            await self._log(f"cache posts: chyba {type(e).__name__}, vracím []", mode=None)
            return []

    async def comments(self, post_urls: list[str], per_post: int = 15) -> list[Comment]:
        try:
            urls = list(dict.fromkeys(_url_key(u) for u in post_urls if u))
            originals = {_url_key(u): u for u in post_urls if u}
            found: dict[str, list[Comment]] = {}
            actor = None
            for u in urls:
                hit = self._read("comments", _comments_args(u, per_post))
                if hit is not None:
                    found[u] = hit[0]  # type: ignore[assignment]
                    actor = actor or hit[1].get("actor")
            if found:
                await self._log(f"z cache: comments ({sum(map(len, found.values()))} z {len(found)} postů)", actor=actor)
            missing = [u for u in urls if u not in found]
            if missing:
                self.stats["misses"] += len(missing)
                if self.read_only:
                    await self._log(f"není v cache: comments pro {len(missing)} postů; offline režim nic nestahuje")
                else:
                    req = [originals.get(u, u) for u in missing]
                    fetched, complete = await self._fetch_checked("comments", lambda: self.inner.comments(req, per_post))
                    groups: dict[str, list[Comment]] = {}
                    for c in fetched:
                        groups.setdefault(_url_key(c.post_url), []).append(c)
                    for u, lst in groups.items():
                        found[u] = lst
                        self._write("comments", _comments_args(u, per_post), lst)
                    if complete:   # a post without comment texts is an answer too
                        for u in missing:
                            if u not in groups:
                                found[u] = []
                                self._write("comments", _comments_args(u, per_post), [], empty_ok=True)
            out: list[Comment] = []
            seen = set()
            for u in urls + [u for u in found if u not in urls]:
                if u in found and u not in seen:
                    seen.add(u)
                    out.extend(found[u])
            return out
        except Exception as e:
            self.stats["errors"] += 1
            await self._log(f"cache comments: chyba {type(e).__name__}, vracím []", mode=None)
            return []

    async def collabs(self, handle: str, platform: Platform) -> list[CollabEvidence]:
        args: dict[str, Any] = {"handle": norm_handle(handle), "platform": platform}
        variant = self._variant("collabs")
        if variant:
            args["variant"] = variant
        return await self._cached("collabs", args, lambda: self.inner.collabs(handle, platform),
                                  f"collabs @{norm_handle(handle)}")

    async def news(self, query: str, lang: str = "cs", region: str = "CZ", limit: int = 10) -> list[NewsItem]:
        args = {"query": " ".join(query.split()).lower(), "lang": lang, "region": region, "limit": int(limit)}
        return await self._cached("news", args, lambda: self.inner.news(query, lang, region, limit), f"news „{query}“")

    async def find_cross_platform(self, profile: Profile) -> list[Profile]:
        args = {"handle": profile.handle, "platform": profile.platform}
        return await self._cached("find_cross_platform", args, lambda: self.inner.find_cross_platform(profile),
                                  f"cross-platform @{profile.handle}")


# ---------------------------------------------------------------------------------------------
# Import (Kryštof's cache directory -> data/cache)
# ---------------------------------------------------------------------------------------------


def _split(method: str, args: dict, items: list[BaseModel]) -> list[tuple[dict, list[BaseModel], dict]]:
    """Batch entries -> the per-handle / per-URL entries CachedProvider reads, with extra meta.
    A since-keyed posts entry (old layout) is re-keyed by handle + platform + limit with ``meta.since`` = that
    day: it is complete only for requests from that day on."""
    if method == "profiles":
        platform = args.get("platform") or (items[0].platform if items else None)  # type: ignore[attr-defined]
        return [(_profiles_args(p.handle, platform), [p], {}) for p in items]  # type: ignore[attr-defined]
    if method == "comments":
        per_post = int(args.get("per_post", 15))
        if not items:   # a confirmed empty answer: one empty entry per requested URL
            return [(_comments_args(u, per_post), [], {}) for u in args.get("post_urls") or [] if isinstance(u, str)]
        groups: dict[str, list[BaseModel]] = {}
        for c in items:
            groups.setdefault(_url_key(c.post_url), []).append(c)  # type: ignore[attr-defined]
        return [(_comments_args(u, per_post), lst, {}) for u, lst in groups.items()]
    if method == "posts" and "handle" in args and "platform" in args:
        extra = {"since": str(_canon(args["since"]))[:10]} if args.get("since") else {}
        return [(_posts_args(str(args["handle"]), str(args["platform"]), int(args.get("limit", 50))), items, extra)]
    return [(args, items, {})]


def _infer_method(items_raw: list) -> str | None:
    """Method whose model every item validates as (key-named files without meta)."""
    if not items_raw:
        return None
    for method in ("comments", "news", "collabs", "posts", "profiles", "discover"):
        model = MODEL_FOR[method]
        try:
            for x in items_raw:
                model.model_validate(x)
        except ValidationError:
            continue
        return method
    return None


def import_cache_dir(src: Path | str, cache_dir: Path | None = None, *, overwrite: bool = False,
                     provider_name: str | None = None) -> dict[str, int]:
    """Import every ``*.json`` under ``src`` into ``cache_dir`` (default get_settings().cache_dir).

    Accepted files: ``{"meta": {"method", "args", "provider"?}, "items": [...]}`` (re-keyed from meta,
    items validated, minors dropped, batch profiles/comments split per handle/URL), or a file named
    ``<64-hex key>.json`` holding such an object or a bare item list (kept under the same key, items
    validated against the model of meta.method or the one they all fit; extra fields such as
    commenter identities are stripped and minors dropped; a raw payload is never copied).
    Returns counts: files_seen, entries_written, items, skipped_existing, invalid, unknown.
    """
    src = Path(src)
    dest = Path(cache_dir) if cache_dir else get_settings().cache_dir
    stats = {"files_seen": 0, "entries_written": 0, "items": 0, "skipped_existing": 0, "invalid": 0, "unknown": 0}
    for f in sorted(src.rglob("*.json")):
        stats["files_seen"] += 1
        try:
            raw = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            stats["invalid"] += 1
            continue
        meta = raw.get("meta") if isinstance(raw, dict) else None
        method = meta.get("method") if isinstance(meta, dict) else None
        args = meta.get("args") if isinstance(meta, dict) else None
        if method in MODEL_FOR and isinstance(args, dict) and isinstance(raw, dict):
            items, bad = _validate_items(method, raw.get("items"))
            if not items and not (not bad and meta.get("empty") is True and method in EMPTY_IS_ANSWER):
                stats["invalid" if bad else "unknown"] += 1
                continue
            prov = meta.get("provider") or provider_name or DEFAULT_IMPORT_PROVIDER
            for sub_args, sub_items, sub_meta in _split(method, args, items):
                path = dest / f"{cache_key(method, sub_args, prov)}.json"
                if path.exists() and not overwrite:
                    stats["skipped_existing"] += 1
                    continue
                payload = {"meta": {**meta, "provider": prov, "method": method, "args": _canon(sub_args),
                                    "count": len(sub_items), "imported_from": f.name, **sub_meta},
                           "items": [m.model_dump(mode="json") for m in sub_items]}
                _write_atomic(path, payload)
                stats["entries_written"] += 1
                stats["items"] += len(sub_items)
            continue
        if _KEY_RE.match(f.stem) and isinstance(raw, (dict, list)):
            items_raw = raw.get("items") if isinstance(raw, dict) else raw
            if not isinstance(items_raw, list):
                stats["invalid"] += 1
                continue
            # Never copy a raw payload: validate the items into the model they fit (from meta.method,
            # else the first model every item validates as), which strips extra fields such as
            # commenter usernames / avatars, and drop minors. Unknown shape -> not imported.
            k_method = method if method in MODEL_FOR else _infer_method(items_raw)
            if k_method is None:
                stats["unknown"] += 1
                continue
            items, bad = _validate_items(k_method, items_raw)
            if not items and not (not bad and isinstance(meta, dict) and meta.get("empty") is True
                                  and k_method in EMPTY_IS_ANSWER):
                stats["invalid" if bad else "unknown"] += 1
                continue
            path = dest / f.name
            if path.exists() and not overwrite:
                stats["skipped_existing"] += 1
                continue
            meta_out = {k: v for k, v in (meta or {}).items()
                        if k in ("provider", "method", "args", "actor", "fetched_at", "empty", "since")}
            payload = {"meta": {**meta_out, "method": k_method, "count": len(items), "imported_from": f.name},
                       "items": [m.model_dump(mode="json") for m in items]}
            _write_atomic(path, payload)
            stats["entries_written"] += 1
            stats["items"] += len(items)
            continue
        stats["unknown"] += 1
    return stats


def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.sources.cache", description="Source cache tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import a directory of cache files (e.g. from Kryštof)")
    imp.add_argument("src", type=Path)
    imp.add_argument("--cache-dir", type=Path, default=None)
    imp.add_argument("--overwrite", action="store_true")
    imp.add_argument("--provider", default=None, help=f"provider name for files without meta.provider "
                                                     f"(default {DEFAULT_IMPORT_PROVIDER})")
    pg = sub.add_parser("purge", help="delete all cached source files")
    pg.add_argument("--cache-dir", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "import":
        print(json.dumps(import_cache_dir(a.src, a.cache_dir, overwrite=a.overwrite, provider_name=a.provider)))
    else:
        print(json.dumps({"deleted": purge_cache(a.cache_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
