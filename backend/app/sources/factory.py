"""Provider factory used by the API layer. Implemented here (contract glue).

  SOURCE_MODE=mock  -> MockProvider()
  SOURCE_MODE=cache -> CachedProvider(ApifyProvider(), read_only unless CACHE_FILL_MISSES=1 and a token)
                       (replays a cache dir from Kryštof; misses go live only with that opt-in)
  SOURCE_MODE=apify -> CachedProvider(ApifyProvider())   (live, write-through cache so
                       recompute / reruns never refetch)

If ApifyProvider cannot be constructed, the factory substitutes ``UnavailableProvider``: every
method logs why and returns ``[]``. Without APIFY_TOKEN the provider itself returns ``[]`` with a
log line, so cache mode still replays a cache dir and apify mode fails visibly in the live log.
Neither ever confirms an answer as complete, so their ``[]`` is never cached as an empty answer.

``default_discovery_query(city)`` is the recommended food discovery query (Brno run of 9. 10. 2026:
keywords "brno food", "brno foodie", "foodblog brno", hashtags brnofood / foodbrno). It is a starting
point for the caller; the DiscoveryQuery handed to ``discover()`` stays the source of truth.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

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
    SourceMode,
)
from app.sources.base import SourceProvider

CACHE_NAMESPACE = "apify"   # == cache.DEFAULT_IMPORT_PROVIDER and ApifyProvider.name
_WHY = "Apify provider zatím není implementovaný (apify_provider.py, Kryštof); živá data nejsou k dispozici"


class UnavailableProvider:
    """Stand-in for a provider that cannot be constructed. Never raises; logs and returns []."""

    name: str = "apify-unavailable"

    def __init__(self, why: str = _WHY) -> None:
        self.why = why

    async def _no(self, method: str) -> list:
        await emit_log(f"{method}: {self.why}", actor="apify", mode="live")
        return []

    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]:
        return await self._no("discover")

    async def profiles(self, handles: list[str], platform: Platform) -> list[Profile]:
        return await self._no("profiles")

    async def posts(self, handle: str, platform: Platform, since: datetime, limit: int = 50) -> list[Post]:
        return await self._no("posts")

    async def comments(self, post_urls: list[str], per_post: int = 15) -> list[Comment]:
        return await self._no("comments")

    async def collabs(self, handle: str, platform: Platform) -> list[CollabEvidence]:
        return await self._no("collabs")

    async def news(self, query: str, lang: str = "cs", region: str = "CZ", limit: int = 10) -> list[NewsItem]:
        return await self._no("news")

    async def find_cross_platform(self, profile: Profile) -> list[Profile]:
        return await self._no("find_cross_platform")


def default_discovery_query(city: str = "Brno", **overrides: Any) -> DiscoveryQuery:
    """Recommended discovery inputs (see the module docstring); ``overrides`` are DiscoveryQuery fields.
    Lazy import: building a query must not need the Apify client."""
    from app.sources.apify_provider import default_discovery_query as _default

    return _default(city, **overrides)


def apify_available() -> bool:
    """True when ApifyProvider can be constructed (i.e. Kryštof's module is implemented)."""
    try:
        from app.sources.apify_provider import ApifyProvider

        ApifyProvider()
        return True
    except NotImplementedError:
        return False
    except Exception:
        return False


def _inner_live() -> SourceProvider:
    try:
        from app.sources.apify_provider import ApifyProvider

        return ApifyProvider()
    except NotImplementedError:
        return UnavailableProvider()
    except Exception as exc:  # never crash a run on provider construction
        return UnavailableProvider(f"Apify provider nejde vytvořit: {type(exc).__name__}: {exc}")


def get_provider(source_mode: SourceMode | None = None) -> SourceProvider:
    s = get_settings()
    mode = source_mode or s.source_mode
    if mode == "mock":
        from app.sources.mock_provider import MockProvider

        return MockProvider()
    from app.sources.cache import CachedProvider

    inner = _inner_live()
    # Fixed cache namespace "apify": the stand-in's display name ("apify-unavailable") must not change
    # the keys, or an imported cache could never be replayed while the live provider is missing.
    if mode == "cache":
        # Replay is read only unless the operator opts in (CACHE_FILL_MISSES=1): a token picked up from
        # .env must never turn a cache miss into a paid live actor run.
        fill = os.environ.get("CACHE_FILL_MISSES", "").strip().lower() in ("1", "true", "yes")
        read_only = not (fill and s.apify_configured) or isinstance(inner, UnavailableProvider)
        return CachedProvider(inner, read_only=read_only, key_name=CACHE_NAMESPACE)
    return CachedProvider(inner, key_name=CACHE_NAMESPACE)
