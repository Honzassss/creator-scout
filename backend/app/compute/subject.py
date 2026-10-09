"""Subject mode input parsing (pure): which creator the owner named, and the anchor that pins them down.

``parse_subject`` turns "@x", "x", an instagram.com / tiktok.com profile link into (platform, handle).
``normalize_anchor`` cleans the anchor (city / website / company ID); ``anchor_text`` renders it for
logs and the report. The company ID is only ever matched as TEXT in public data (no registry lookup).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models import Anchor, Platform

_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}$")
_IG_NON_PROFILE = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct"}
_IG_HOSTS = {"instagram.com", "instagr.am"}
_TT_HOSTS = {"tiktok.com", "vm.tiktok.com"}


def _host(netloc: str) -> str:
    h = (netloc or "").lower().split("@")[-1].split(":")[0]
    for pre in ("www.", "m.", "mobile."):
        if h.startswith(pre):
            h = h[len(pre):]
    return h


def _clean_handle(h: str) -> str | None:
    h = (h or "").strip().lstrip("@").lower().rstrip(".")  # "@x." at the end of a sentence; handles never end with "."
    return h if _HANDLE_RE.match(h) else None


def parse_subject(text: str, platform: str | None = None) -> tuple[Platform | None, str] | None:
    """-> (platform or None, normalized handle) or None if not a profile reference.
    "@x" / "x" -> (platform arg or None, "x"); instagram.com/<h>[/...] -> ("instagram", h);
    tiktok.com/@<h>[/...] -> ("tiktok", h). Rejects IG non-profile paths (p, reel, reels, tv, stories,
    explore, accounts, direct) and TikTok video-only links without @handle. Handle charset [a-z0-9._],
    1-30 chars; lowercase; strips query/fragment. A URL platform conflicting with `platform` -> URL wins."""
    raw = (text or "").strip()
    if not raw:
        return None
    plat: Platform | None = platform if platform in ("instagram", "tiktok") else None  # type: ignore[assignment]
    looks_url = "://" in raw or re.match(r"^(?:www\.|m\.)?(?:instagram\.com|instagr\.am|tiktok\.com)(?:/|$)", raw, re.I)
    if looks_url:
        u = raw if "://" in raw else "https://" + raw
        try:
            p = urlparse(u)
        except ValueError:
            return None
        host = _host(p.netloc)
        parts = [x for x in p.path.split("/") if x]
        if host in _IG_HOSTS:
            if not parts or parts[0].lower() in _IG_NON_PROFILE:
                return None
            h = _clean_handle(parts[0])
            return ("instagram", h) if h else None
        if host in _TT_HOSTS or host.endswith(".tiktok.com"):
            if not parts or not parts[0].startswith("@"):
                return None
            h = _clean_handle(parts[0][1:])
            return ("tiktok", h) if h else None
        return None
    if any(c.isspace() for c in raw) or "/" in raw:
        return None
    h = _clean_handle(raw)
    if not h:
        return None
    return (plat, h)


def _website_host(raw: str) -> str | None:
    w = (raw or "").strip()
    if not w:
        return None
    u = w if "://" in w else "https://" + w
    try:
        host = _host(urlparse(u).netloc)
    except ValueError:
        return None
    host = host.strip(".")
    # a domain: labels of letters / digits / hyphens with at least one dot ("not a site" is no website)
    if not re.fullmatch(r"(?:[a-z0-9\u00c0-\u024f](?:[a-z0-9\u00c0-\u024f-]{0,61}[a-z0-9\u00c0-\u024f])?\.)+[a-z\u00c0-\u024f]{2,24}", host):
        return None
    return host or None


# "skip", "none", "don't know", "nevím" in the anchor field mean: no anchor (as in the chat flow).
_NO_ANCHOR = re.compile(
    r"(?i)^\s*(?:-+|\?+|n/?a|none|no|nope|skip|skip it|no anchor|unknown|not sure|i don'?t know|don'?t know|dont know|"
    r"no idea|nevim|nevím|nevime|nevíme|nic|zadna|žádná|zadne|žádné|zadny|žádný|preskocit|přeskočit|bez kotvy|netusim|netuším)"
    r"\s*[.!]*\s*$"
)


def is_no_anchor(text: str | None) -> bool:
    return bool(_NO_ANCHOR.match(text or ""))


def _company_id(raw: str) -> str | None:
    s = (raw or "").strip().upper()
    if s.startswith("CZ"):
        s = s[2:]
    digits = re.sub(r"\D", "", s)
    if not (6 <= len(digits) <= 8):
        return None
    return digits.zfill(8)


def classify_anchor(text: str) -> Anchor:
    """A plain-string anchor -> Anchor: digits (optionally "CZ", spaces) = company ID, a dot = website,
    otherwise a city. Not normalized (``normalize_anchor`` does that)."""
    t = (text or "").strip()
    if is_no_anchor(t):
        return Anchor()
    if re.fullmatch(r"(?i)(?:i[čc]o\s*:?\s*)?(?:cz)?[\d\s]+", t):
        return Anchor(company_id=re.sub(r"(?i)^i[čc]o\s*:?\s*", "", t))
    if "." in t and " " not in t:
        return Anchor(website=t)
    return Anchor(city=t)


def normalize_anchor(raw: Anchor | dict | None) -> Anchor | None:
    """Strip; website -> host lowercase without scheme / www. / path; company_id -> digits only (drops a
    leading "CZ"); 6-8 digits zero-padded to 8; city stripped. Empty -> None."""
    if raw is None:
        return None
    d = raw.model_dump() if isinstance(raw, Anchor) else dict(raw)
    city = (d.get("city") or "").strip() or None
    if city:
        city = re.sub(r"\s+", " ", city)
        if is_no_anchor(city):
            city = None
    website = _website_host(d.get("website") or "")
    company_id = _company_id(str(d.get("company_id") or ""))
    if not (city or website or company_id):
        return None
    return Anchor(city=city, website=website, company_id=company_id)


def anchor_text(anchor: Anchor | None, lang: str) -> str:
    """"city Brno, website fitpeceni.example" / "město Brno, web fitpeceni.example"; "" for None."""
    if anchor is None:
        return ""
    cs = lang != "en"
    parts: list[str] = []
    if anchor.city:
        parts.append(f"město {anchor.city}" if cs else f"city {anchor.city}")
    if anchor.website:
        parts.append(f"web {anchor.website}" if cs else f"website {anchor.website}")
    if anchor.company_id:
        parts.append(f"IČO {anchor.company_id}" if cs else f"company ID {anchor.company_id}")
    return ", ".join(parts)
