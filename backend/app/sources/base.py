"""SourceProvider protocol (architecture.md section 2) + re-export of DiscoveryQuery.

Rules for every provider:
- A method that cannot work returns ``[]`` and logs why via ``await emit_log(text, actor=..., mode=...)``
  (from app.events); it never raises into the funnel.
- Every returned object carries ``source.mode`` ("live" | "cache" | "mock") and ``source.actor``,
  including nested ``Profile.latest_posts[i].source``.
- Minors (``Profile.is_under_18 is True``) are dropped inside the provider before returning.
- Commenter identities are never part of the returned Comment objects.
- Only ``apify_provider.py`` may import ``apify_client``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.models import (
    CandidateRef,
    CollabEvidence,
    Comment,
    DiscoveryQuery,
    NewsItem,
    Platform,
    Post,
    Profile,
)

__all__ = ["SourceProvider", "DiscoveryQuery"]


@runtime_checkable
class SourceProvider(Protocol):
    name: str

    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]:
        """Accounts found via keywords / hashtags / places / related; found_via filled per path."""
        ...

    async def profiles(self, handles: list[str], platform: Platform) -> list[Profile]:
        """One batch; each Profile with ~12 latest_posts. Unknown handles are simply missing."""
        ...

    async def posts(self, handle: str, platform: Platform, since: datetime, limit: int = 50) -> list[Post]:
        """More posts for deep vetting (round 4), newest first, created_at >= since."""
        ...

    async def comments(self, post_urls: list[str], per_post: int = 15) -> list[Comment]:
        """Comment texts only (no commenter identity)."""
        ...

    async def collabs(self, handle: str, platform: Platform) -> list[CollabEvidence]:
        """Meta Branded Content etc.; [] if unsupported."""
        ...

    async def news(self, query: str, lang: str = "cs", region: str = "CZ", limit: int = 10) -> list[NewsItem]:
        ...

    async def find_cross_platform(self, profile: Profile) -> list[Profile]:
        """Same creator on TikTok/YouTube (candidates; identity.py decides); [] if unsupported."""
        ...
