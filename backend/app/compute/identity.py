"""Identity resolution: same creator across platforms, fan accounts, namesakes in news.

Signals (each an IdentitySignal with a source when possible): bio links to the other handle, same
external URL / website, same display name, other profile links back, handle similarity,
fan-account markers ("fan", "fanpage", "not affiliated") -> supports=False.
Status: matched = >= 2 supporting signals incl. a link (bio link / same website / backlink) and no
contradicting signal; uncertain = some support but not enough (e.g. only name / handle similarity);
rejected = a contradicting signal (fan account, different region) or no supporting signal at all.
No confidence percentages anywhere (they would be invented numbers); signals + status only.

News: ``news_subject`` decides whether an article is about this creator. ``match_news`` turns a
same-named article in another context into a "rejected" IdentityMatch (namesake) for the identity
panel, so the report can say "this article is about a different person" instead of hiding it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal
from urllib.parse import urlparse

from app.compute.metrics import city_pattern, city_stems
from app.models import (
    Anchor,
    IdentityMatch,
    IdentitySignal,
    IdentityVerdict,
    NewsItem,
    Post,
    Profile,
    SetAside,
    SourceRef,
    norm_handle,
    person_name,
)

_PLATFORM_CS = {"instagram": "Instagramu", "tiktok": "TikToku", "youtube": "YouTube", "web": "webu"}  # "na X" (locative)
_PLATFORM_CS_ACC = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "web": "web"}
_PLATFORM_EN = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "web": "the web"}

_FAN_TEXT_RE = re.compile(
    r"(fan\s*page|fan\s*account|fan\s*[uú][cč]et|fanou[sš]kovsk\w*|not affiliated|unofficial|"
    r"neofici[aá]ln\w*|fan\s*club|fanclub|stan account|\bfp\b|repost\w* (?:of|from)|reupload)",
    re.IGNORECASE,
)
_FAN_HANDLE_RE = re.compile(r"(^fan[_.]|[_.]fan$|[_.]?fans$|fanpage|[_.]fp$|^fp[_.]|fanclub)", re.IGNORECASE)


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(text))


def _norm_url(url: str) -> str:
    """'https://www.Anna-Peče.cz/' -> 'anna-pece.cz'; keeps the path for link-in-bio services."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    try:
        p = urlparse(u)
    except ValueError:
        return _fold(url)
    host = _fold(p.netloc).removeprefix("www.")
    path = p.path.rstrip("/")
    if host in {"linktr.ee", "linktree.com", "lnk.bio", "beacons.ai", "instagram.com", "tiktok.com",
                "youtube.com", "m.youtube.com", "bio.link", "taplink.cc",
                "instagram.mock.invalid", "tiktok.mock.invalid", "youtube.mock.invalid"}:
        return f"{host}{_fold(path)}"
    return host


def _profile_text(p: Profile) -> str:
    return " ".join([p.bio or "", *p.external_urls])


def _links_to(src: Profile, target: Profile) -> str | None:
    """Return the matching text when ``src`` bio / links / related handles point at ``target``."""
    h = norm_handle(target.handle)
    if not h:
        return None
    text = _profile_text(src)
    folded = text.lower()
    platform_hosts = {"instagram": ("instagram.com/", "instagram.mock.invalid/"),
                      "tiktok": ("tiktok.com/@", "tiktok.mock.invalid/@"),
                      "youtube": ("youtube.com/@", "youtube.mock.invalid/@")}
    for host in platform_hosts.get(target.platform, ()):
        if f"{host}{h}" in folded:
            return f"{host}{h}"
    if target.url and target.url.lower().rstrip("/") in folded:
        return target.url
    pat = re.compile(rf"(?<![\w.])@{re.escape(h)}(?![\w.])", re.IGNORECASE)
    m = pat.search(text)
    if m:
        # "@handle" in bio: counts as a link when the bio names the other platform nearby or the
        # handles differ (an IG bio saying "@anna" next to "TikTok").
        window = folded[max(0, m.start() - 30): m.end() + 30]
        plat_words = {"tiktok": ("tiktok", "tik tok", "tt:"), "instagram": ("instagram", "insta", "ig:"),
                      "youtube": ("youtube", "yt:")}.get(target.platform, ())
        if any(w in window for w in plat_words) or src.platform != target.platform:
            return m.group(0)
    if h in src.related_handles:
        return f"@{h}"
    return None


def _fan_marker(other: Profile) -> str | None:
    m = _FAN_HANDLE_RE.search(other.handle or "")
    if m:
        return f"@{other.handle}"
    for text in (other.display_name, other.bio):
        m = _FAN_TEXT_RE.search(text or "")
        if m:
            return m.group(0).strip()
    return None


def is_fan_account(primary: Profile, other: Profile) -> bool:
    if norm_handle(primary.handle) == norm_handle(other.handle) and primary.platform == other.platform:
        return False
    return _fan_marker(other) is not None


def identity_signals(primary: Profile, other: Profile, *, lang: str = "cs",
                     home_region: str | None = None) -> list[IdentitySignal]:
    return [s for _, s in _signals(primary, other, lang=lang, home_region=home_region)]


def _signals(primary: Profile, other: Profile, *, lang: str = "cs",
             home_region: str | None = None) -> list[tuple[str, IdentitySignal]]:
    """(kind, signal) pairs; kind in link | backlink | website | name | handle | fan | region.
    ``home_region`` (e.g. "CZ", the market we search in) stands in for primary.region when the
    primary platform does not expose one (Instagram)."""
    cs = lang != "en"
    plat = (_PLATFORM_CS if cs else _PLATFORM_EN).get(other.platform, other.platform)
    plat_acc = (_PLATFORM_CS_ACC if cs else _PLATFORM_EN).get(other.platform, other.platform)
    pplat = (_PLATFORM_CS if cs else _PLATFORM_EN).get(primary.platform, primary.platform)
    sig: list[tuple[str, IdentitySignal]] = []

    def add(kind: str, signal: IdentitySignal) -> None:
        sig.append((kind, signal))

    def quoted(src: SourceRef, quote: str | None) -> SourceRef:
        return src.model_copy(update={"quote": quote}) if quote else src

    hit = _links_to(primary, other)
    if hit:
        add("link", IdentitySignal(
            signal=(f"bio na {pplat} odkazuje na {plat_acc} @{other.handle}" if cs
                    else f"{pplat} bio links to {plat} @{other.handle}"),
            supports=True, source=quoted(primary.source, hit)))
    back = _links_to(other, primary)
    if back:
        add("backlink", IdentitySignal(
            signal=(f"profil na {plat} odkazuje zpět na @{primary.handle}" if cs
                    else f"{plat} profile links back to @{primary.handle}"),
            supports=True, source=quoted(other.source, back)))

    p_urls = {_norm_url(u) for u in primary.external_urls if _norm_url(u)}
    o_urls = {_norm_url(u) for u in other.external_urls if _norm_url(u)}
    common = sorted(p_urls & o_urls)
    if common:
        add("website", IdentitySignal(
            signal=f"stejný web {common[0]}" if cs else f"same website {common[0]}",
            supports=True, source=quoted(other.source, common[0])))

    pn, on = _alnum(primary.display_name), _alnum(other.display_name)
    if pn and on and len(pn) >= 4 and pn == on:
        add("name", IdentitySignal(
            signal=(f"stejné zobrazované jméno „{other.display_name}“" if cs
                    else f"same display name \"{other.display_name}\""),
            supports=True, source=quoted(other.source, other.display_name)))

    ph, oh = _alnum(primary.handle), _alnum(other.handle)
    if ph and oh and (ph == oh or (min(len(ph), len(oh)) >= 5 and (ph in oh or oh in ph))):
        add("handle", IdentitySignal(
            signal=(f"podobné uživatelské jméno @{other.handle}" if cs
                    else f"similar handle @{other.handle}"),
            supports=True, source=quoted(other.source, f"@{other.handle}")))

    marker = _fan_marker(other) if is_fan_account(primary, other) else None
    if marker:
        add("fan", IdentitySignal(
            signal=(f"znaky fanouškovského účtu („{marker}“)" if cs else f"fan-account markers (\"{marker}\")"),
            supports=False, source=quoted(other.source, marker)))

    ref_region = primary.region or home_region
    has_link = any(k in _LINK_KINDS for k, _ in sig)
    if ref_region and other.region and ref_region.upper() != other.region.upper() and not has_link:
        add("region", IdentitySignal(
            signal=(f"jiný region účtu ({other.region.upper()} vs. {ref_region.upper()})" if cs
                    else f"different account region ({other.region.upper()} vs. {ref_region.upper()})"),
            supports=False, source=quoted(other.source, f"region {other.region.upper()}")))
    return sig


_LINK_KINDS = {"link", "backlink", "website"}


def identity_status(kinds_signals: list[tuple[str, IdentitySignal]]) -> Literal["matched", "uncertain", "rejected"]:
    if any(not s.supports for _, s in kinds_signals):
        return "rejected"
    support = [k for k, s in kinds_signals if s.supports]
    if not support:
        return "rejected"
    if len(support) >= 2 and any(k in _LINK_KINDS for k in support):
        return "matched"
    return "uncertain"


def match_identity(primary: Profile, others: list[Profile], *, lang: str = "cs",
                   home_region: str | None = None, anchor: Anchor | None = None) -> list[IdentityMatch]:
    """``anchor`` (subject mode): an account without a link to the primary whose bio names another
    city than the anchor city gets a contradicting signal (look-alike in another city)."""
    out: list[IdentityMatch] = []
    seen: set[tuple[str, str]] = set()
    for o in others:
        key = (o.platform, norm_handle(o.handle))
        if key in seen or (o.platform == primary.platform and norm_handle(o.handle) == norm_handle(primary.handle)):
            continue
        seen.add(key)
        pairs = _signals(primary, o, lang=lang, home_region=home_region)
        if anchor is not None and not any(k in _LINK_KINDS for k, _ in pairs):
            pairs += [("other_city", sig) for sig in look_alike_signals(o, anchor, lang=lang)]
        out.append(IdentityMatch(handle=o.handle, platform=o.platform, status=identity_status(pairs),
                                 signals=[s for _, s in pairs]))
    return out


# ---------------------------------------------------------------------------------------------
# News subject (namesakes)
# ---------------------------------------------------------------------------------------------

_CREATOR_CONTEXT = (
    "instagram", "tiktok", "youtube", "youtuber", "influencer", "influencerk", "tvurce", "tvurkyn",
    "bloger", "blogger", "blogerk", "socialni sit", "socialnich siti", "sledujici", "followers",
    "creator", "content", "reels", "videa", "recept", "foodblog",
)
# Context that clearly places a same-named person elsewhere (another job / role).
_OTHER_CONTEXT = (
    "starost", "zastupitel", "poslan", "senator", "politik", "ministr", "hejtman", "radni",
    "fotbalist", "hokejist", "trener", "rozhodci", "lekar", "primar", "soudce", "advokat", "notar",
    "reditel", "jednatel", "podnikatel", "profesor", "docent", "vedec", "farar", "knez", "hasic",
    "policist", "zemedelec", "mayor", "councillor", "footballer", "surgeon", "judge", "professor",
)
_CITIES = (
    "praha", "praze", "prahy", "brno", "brne", "brna", "ostrav", "plzen", "plzn", "liberec", "liberc",
    "olomouc", "budejovic", "hradec", "hradci", "usti nad", "pardubic", "zlin", "havirov", "kladn",
    "most", "opav", "frydek", "karvin", "jihlav", "teplic", "decin", "karlovy vary", "karlovych var",
    "chomutov", "jablonec", "mlada boleslav", "prostejov", "prerov", "trebic", "znojm", "kolin",
    "bratislav", "kosic", "vieden", "wien", "vienna",
)
# canonical city name per stem in _CITIES: an English text says "Brno", never the inflected "Brnem"
_CITY_NAME = {
    "praha": "Praha", "praze": "Praha", "prahy": "Praha", "brno": "Brno", "brne": "Brno", "brna": "Brno",
    "ostrav": "Ostrava", "plzen": "Plzeň", "plzn": "Plzeň", "liberec": "Liberec", "liberc": "Liberec",
    "olomouc": "Olomouc", "budejovic": "České Budějovice", "hradec": "Hradec Králové", "hradci": "Hradec Králové",
    "usti nad": "Ústí nad Labem", "pardubic": "Pardubice", "zlin": "Zlín", "havirov": "Havířov", "kladn": "Kladno",
    "most": "Most", "opav": "Opava", "frydek": "Frýdek-Místek", "karvin": "Karviná", "jihlav": "Jihlava",
    "teplic": "Teplice", "decin": "Děčín", "karlovy vary": "Karlovy Vary", "karlovych var": "Karlovy Vary",
    "chomutov": "Chomutov", "jablonec": "Jablonec nad Nisou", "mlada boleslav": "Mladá Boleslav",
    "prostejov": "Prostějov", "prerov": "Přerov", "trebic": "Třebíč", "znojm": "Znojmo", "kolin": "Kolín",
    "bratislav": "Bratislava", "kosic": "Košice", "vieden": "Vienna", "wien": "Vienna", "vienna": "Vienna",
}
_AGE_RE = re.compile(r"\(\s*\d{2}\s*\)")


def _item_text(item: NewsItem) -> str:
    return f"{item.title} {item.snippet}"


def _name_in(profile: Profile, text_folded: str) -> bool:
    name = _fold(person_name(profile.display_name)).strip()
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t for t in name.split() if len(t) >= 2]
    if len(tokens) < 2:  # single-word names ("Anna") are too common to mean anything
        return False
    pat = r"\b" + r"\W+".join(re.escape(t) for t in tokens) + r"\w{0,3}\b"
    return re.search(pat, text_folded) is not None


def _handle_in(profile: Profile, text: str) -> bool:
    h = norm_handle(profile.handle)
    folded = text.lower()
    if h and re.search(rf"(?<![\w.])@{re.escape(h)}(?![\w.])", folded):
        return True
    if h and len(h) >= 5 and re.search(rf"(?<![\w.]){re.escape(h)}(?![\w])", folded) and ("_" in h or "." in h or any(c.isdigit() for c in h)):
        return True
    url = (profile.url or "").lower().rstrip("/").removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return bool(url) and url in folded


def name_mentioned(profile: Profile, item: NewsItem) -> bool:
    return _name_in(profile, _fold(_item_text(item)))


def other_context(profile: Profile, item: NewsItem, city: str | None = None) -> str | None:
    """A phrase that places a same-named person in another context (other job, other city, age in
    parentheses), when nothing in the text ties the article to the creator. None otherwise."""
    raw = _item_text(item)
    text = _fold(raw)
    if any(w in text for w in _CREATOR_CONTEXT):
        return None
    # An occupation the creator names in their own bio / category ("Trenérka v Brně") does not place
    # the article elsewhere; and when the article mentions the creator's own city, an occupation alone
    # is not enough to call it a namesake (stays "uncertain", which the skeptic flags).
    own = _fold(f"{profile.bio or ''} {profile.business_category or ''}")
    city_rx = city_pattern(city) if city else None
    own_city = city_rx is not None and city_rx.search(text) is not None
    if not own_city:
        for w in _OTHER_CONTEXT:
            if w in own:
                continue
            m = re.search(rf"\w*{re.escape(w)}\w*", text)
            if m:
                word = raw[m.start():m.end()] if len(raw) == len(text) else m.group(0)
                return word
    if _AGE_RE.search(_item_text(item)):
        return _AGE_RE.search(_item_text(item)).group(0)  # type: ignore[union-attr]
    if city:
        own = city_stems(city)
        for c in _CITIES:
            if re.search(rf"\b{re.escape(c)}", text) and not any(c.startswith(st) or st.startswith(c) for st in own):
                return c
    return None


def news_subject(profile: Profile, item: NewsItem, city: str | None = None) -> Literal["matched", "uncertain", "rejected"]:
    """Is the news item about this creator? Handle or profile URL in title/snippet -> matched;
    only the display name -> uncertain (namesake risk, skeptic must flag it), except when the
    article clearly places that name in another context (other job / city, see ``other_context``)
    -> rejected (namesake); neither -> rejected."""
    text = _item_text(item)
    if _handle_in(profile, text):
        return "matched"
    if name_mentioned(profile, item):
        return "rejected" if other_context(profile, item, city) else "uncertain"
    return "rejected"


def match_news(profile: Profile, items: list[NewsItem], *, city: str | None = None, lang: str = "cs") -> list[IdentityMatch]:
    """Identity-panel entries for same-named articles about someone else (status "rejected")."""
    cs = lang != "en"
    out: list[IdentityMatch] = []
    for item in items:
        if not name_mentioned(profile, item) or _handle_in(profile, _item_text(item)):
            continue
        ctx = other_context(profile, item, city)
        if not ctx:
            continue
        name = person_name(profile.display_name)
        ctx = _ctx_label(ctx, lang)
        signal = (f"stejné jméno „{name}“, ale jiný kontext ({ctx}) v článku {item.outlet}" if cs
                  else f"same name \"{name}\" but another context ({ctx}) in {item.outlet}")
        # Data minimisation: the article is about someone else, so its headline (possibly an
        # allegation about a private person) is not kept; outlet, date, URL and the context word are.
        out.append(IdentityMatch(
            handle=item.id,
            platform="news",
            status="rejected",
            signals=[IdentitySignal(signal=signal, supports=False,
                                    source=item.source.model_copy(update={"quote": None}))],
        ))
    return out


# ---------------------------------------------------------------------------------------------
# Anchor (subject mode): city / website / company ID the owner gave to pin the creator down
# ---------------------------------------------------------------------------------------------

_PLATFORM_NAME = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "web": "web", "news": "news"}


def _other_city(text: str, anchor_city: str | None) -> str | None:
    """The canonical name ("Brno", not "Brnem") of the first other city in ``text`` (see _other_city_raw)."""
    hit = _other_city_raw(text, anchor_city)
    return hit[0] if hit else None


def _other_city_raw(text: str, anchor_city: str | None) -> tuple[str, str] | None:
    """First city from _CITIES named in ``text`` (word-start match on folded text) that is not the
    anchor city -> (canonical name, the word as written). "most" is skipped (an English word)."""
    if not text:
        return None
    folded = _fold(text)
    own = city_stems(anchor_city) if anchor_city else ()
    for c in _CITIES:
        if c == "most":
            continue
        if any(c.startswith(st) or st.startswith(c) for st in own):
            continue
        m = re.search(rf"(?<![a-z0-9]){re.escape(c)}", folded)
        if m:
            a = m.start()
            b = a
            while b < len(folded) and (folded[b].isalnum() or (folded[b] == " " and " " in c and b < m.end())):
                b += 1
            word = text[a:b] if len(text) == len(folded) else folded[a:b]
            return _CITY_NAME.get(c, (word.strip() or c)), (word.strip() or c)
    return None


def _host_of(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    try:
        host = urlparse(u).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    for pre in ("www.", "m."):
        host = host.removeprefix(pre)
    return host


def _site_match(host: str, url: str) -> bool:
    h = _host_of(url)
    return bool(h) and (h == host or h.endswith("." + host))


def _quoted(src: SourceRef, quote: str | None) -> SourceRef:
    return src.model_copy(update={"quote": quote}) if quote else src


def _snip(text: str, start: int, end: int, width: int = 120) -> str:
    text = (text or "").replace("\n", " ")
    a = max(0, start - width // 3)
    b = min(len(text), max(end, a + width))
    return ("…" if a > 0 else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def anchor_signals(profile: Profile, posts: list[Post], anchor: Anchor | None, *, cross: list[Profile] = (),
                   lang: str = "cs") -> list[tuple[str, IdentitySignal]]:
    """kinds: anchor_website | anchor_company_id | anchor_city_bio | anchor_city_posts (supports=True)
    and anchor_city_other (supports=False: bio / location names another city from identity._CITIES and no
    anchor-city signal). Website: normalized host found in profile.external_urls or bio, or in a MATCHED
    cross profile's external_urls. company_id: digits found in bio / external URLs / captions. City:
    metrics.city_pattern (handles Czech cases: "Brnem", "v Brně"). "Another city" uses identity._CITIES
    with word-start matching on folded text and skips the ambiguous stem "most" (an English word).
    Every signal carries a SourceRef with a quote."""
    if anchor is None:
        return []
    cs = lang != "en"
    out: list[tuple[str, IdentitySignal]] = []

    # website -------------------------------------------------------------------------------
    host = (anchor.website or "").strip().lower()
    if host:
        hit = next((u for u in profile.external_urls if _site_match(host, u)), None)
        if hit is None and host in (profile.bio or "").lower():
            hit = host
        if hit is not None:
            out.append(("anchor_website", IdentitySignal(
                signal=(f"web {host} je přímo na profilu" if cs else f"the website {host} is on the profile"),
                supports=True, source=_quoted(profile.source, hit))))
        else:
            for o in cross:
                ohit = next((u for u in o.external_urls if _site_match(host, u)), None)
                if ohit:
                    name = f"{_PLATFORM_NAME.get(o.platform, o.platform)} @{o.handle}"
                    out.append(("anchor_website", IdentitySignal(
                        signal=(f"web {host} je na propojeném profilu {name}" if cs
                                else f"the website {host} is on the linked profile {name}"),
                        supports=True, source=_quoted(o.source, ohit))))
                    break

    # company ID (text match in public data only; no registry lookup) ------------------------
    cid = (anchor.company_id or "").strip()
    if cid:
        core = cid.lstrip("0") or "0"
        rx = re.compile(rf"(?<!\d)0*{re.escape(core)}(?!\d)")
        found: tuple[str, SourceRef, str] | None = None
        for text, src, where_cs, where_en in [(profile.bio or "", profile.source, "v biu", "in the bio"),
                                              (" ".join(profile.external_urls), profile.source, "v odkazu na profilu", "in a profile link")]:
            m = rx.search(text)
            if m:
                found = (_snip(text, m.start(), m.end()), src, where_cs if cs else where_en)
                break
        if found is None:
            for p in posts:
                m = rx.search(p.caption or "")
                if m:
                    found = (_snip(p.caption, m.start(), m.end()), p.source,
                             "v popisku postu" if cs else "in a post caption")
                    break
        if found is not None:
            quote, src, where = found
            out.append(("anchor_company_id", IdentitySignal(
                signal=(f"IČO {cid} je uvedené {where}" if cs else f"company ID {cid} appears {where}"),
                supports=True, source=_quoted(src, quote))))

    # city ------------------------------------------------------------------------------------
    city = (anchor.city or "").strip()
    if city:
        rx_city = city_pattern(city)
        bio = profile.bio or ""
        m = rx_city.search(_fold(bio)) if rx_city else None
        if m:
            out.append(("anchor_city_bio", IdentitySignal(
                signal=(f"bio uvádí {city}" if cs else f"the bio names {city}"),
                supports=True, source=_quoted(profile.source, _snip(bio, m.start(), m.end())))))
        hits: list[tuple[Post, str]] = []
        if rx_city:
            for p in posts:
                for text in (p.location_name or "", p.caption or ""):
                    mm = rx_city.search(_fold(text))
                    if mm:
                        hits.append((p, _snip(text, mm.start(), mm.end())))
                        break
        if hits:
            n = len(hits)
            out.append(("anchor_city_posts", IdentitySignal(
                signal=(f"{n} {'post' if n == 1 else ('posty' if n < 5 else 'postů')} s místem nebo popiskem {city}" if cs
                        else f"{n} {'post' if n == 1 else 'posts'} located in or mentioning {city}"),
                supports=True, source=_quoted(hits[0][0].source, hits[0][1]))))
        if not m:
            # A bio that names another city contradicts the anchor even when a few posts mention the
            # anchor city (a Brno guide with 3 posts about Praha is not "the Praha creator").
            hit = _other_city_raw(bio, city)
            if hit:
                out.append(("anchor_city_other", IdentitySignal(
                    signal=(f"profil uvádí {hit[0]}, ne {city}" if cs else f"the profile names {hit[0]}, not {city}"),
                    supports=False, source=_quoted(profile.source, hit[1]))))
            else:
                # Post locations: another city that clearly dominates the anchor city's posts.
                per_city: dict[str, list[Post]] = {}
                for p in posts:
                    o = _other_city(p.location_name or "", city)
                    if o:
                        per_city.setdefault(o, []).append(p)
                if per_city:
                    other, ops = max(per_city.items(), key=lambda kv: len(kv[1]))
                    if not hits or (len(ops) >= 3 and len(ops) > 2 * len(hits)):
                        n = len(ops)
                        if hits:
                            sig = (f"{n} {'post' if n == 1 else ('posty' if n < 5 else 'postů')} má místo {other}, "
                                   f"{city} zmiňuje jen {len(hits)}" if cs
                                   else f"{n} {'post is' if n == 1 else 'posts are'} located in {other}, "
                                        f"only {len(hits)} mention {city}")
                        else:
                            sig = (f"profil uvádí {other}, ne {city}" if cs else f"the profile names {other}, not {city}")
                        out.append(("anchor_city_other", IdentitySignal(
                            signal=sig, supports=False, source=_quoted(ops[0].source, ops[0].location_name))))
    return out


def look_alike_signals(other: Profile, anchor: Anchor | None, *, lang: str) -> list[IdentitySignal]:
    """For a cross-platform profile: another city in its bio than anchor.city -> supports=False
    ("bio says Bratislava, the anchor is Brno"). Added to that IdentityMatch's signals before
    identity_status, so a same-name account in another city ends up rejected or uncertain."""
    if anchor is None or not (anchor.city or "").strip():
        return []
    city = anchor.city.strip()  # type: ignore[union-attr]
    bio = other.bio or ""
    rx = city_pattern(city)
    if rx is not None and rx.search(_fold(bio)):
        return []
    hit = _other_city_raw(bio, city)
    if not hit:
        return []
    found, raw = hit
    cs = lang != "en"
    return [IdentitySignal(
        signal=(f"bio uvádí {found}, kotva je {city}" if cs else f"bio says {found}, the anchor is {city}"),
        supports=False, source=_quoted(other.source, raw))]


# -- verdict ---------------------------------------------------------------------------------

_FAN_MARKS = ("fan-account markers", "fanouškovského účtu")
_REGION_MARKS = ("account region", "region účtu")
_BACKLINK_MARKS = ("links back", "odkazuje zpět")
_LINK_MARKS = ("bio links to", "odkazuje na")
_SITE_MARKS = ("same website", "stejný web")


def _has(sig: IdentitySignal, marks: tuple[str, ...]) -> bool:
    return any(mk in sig.signal for mk in marks)


def match_reason(m: IdentityMatch, lang: str) -> str:
    """Short reason a cross-platform account is the same creator ("TikTok @x links back to this profile")."""
    cs = lang != "en"
    name = f"{_PLATFORM_NAME.get(m.platform, m.platform)} @{m.handle}"
    sup = [s for s in m.signals if s.supports]
    if any(_has(s, _BACKLINK_MARKS) for s in sup):
        return f"{name} odkazuje zpět na tento profil" if cs else f"{name} links back to this profile"
    if any(_has(s, _LINK_MARKS) for s in sup):
        return f"bio odkazuje na {name}" if cs else f"the bio links to {name}"
    if any(_has(s, _SITE_MARKS) for s in sup):
        return f"{name} má stejný web" if cs else f"{name} has the same website"
    return f"{name}: {', '.join(s.signal for s in sup)}"


def _join(items: list[str], lang: str) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    last = " a " if lang != "en" else " and "
    return ", ".join(items[:-1]) + last + items[-1]


def _platforms_text(platforms: list[str], lang: str) -> str:
    names = [_PLATFORM_NAME.get(p, p) for p in platforms] or (["Instagramu", "TikToku"] if lang != "en" else ["Instagram", "TikTok"])
    if lang != "en":
        cs = {"Instagram": "Instagramu", "TikTok": "TikToku", "YouTube": "YouTube"}
        names = [cs.get(n, n) for n in names]
        return " ani na ".join(names) if len(names) > 1 else names[0]
    return " or ".join(names)


_CTX_RE = re.compile(r"(?:another context|jiný kontext) \(([^)]+)\)")
# context words of a namesake's article, for the English label (the Czech label keeps the word)
_CTX_EN = {
    "podnikatel": "businessman", "podnikatelka": "businesswoman", "hokejista": "ice-hockey player",
    "hokejistka": "ice-hockey player", "fotbalista": "footballer", "fotbalistka": "footballer",
    "politik": "politician", "politicka": "politician", "poslanec": "MP", "poslankyne": "MP",
    "starosta": "mayor", "starostka": "mayor", "zpevak": "singer", "zpevacka": "singer", "herec": "actor",
    "herecka": "actress", "lekar": "doctor", "lekarka": "doctor", "ucitel": "teacher", "ucitelka": "teacher",
    "sportovec": "athlete", "sportovkyne": "athlete", "kuchar": "chef", "kucharka": "chef", "trener": "coach",
    "trenerka": "coach", "student": "student", "studentka": "student", "soudce": "judge", "policista": "police officer",
}


def _ctx_label(ctx: str, lang: str) -> str:
    """The context word of a namesake's article for the reader: an English gloss in English
    ("podnikatel" -> "businessman"), a city by its proper name ("zlin" -> "Zlín" / "in Zlín")."""
    f = _fold(ctx).strip()
    if f in _CITY_NAME:
        return _CITY_NAME[f] if lang != "en" else f"in {_CITY_NAME[f]}"
    if lang != "en":
        return ctx
    if f in _CTX_EN:
        return _CTX_EN[f]
    keys = sorted(_CTX_EN, key=len, reverse=True)
    for k in keys:   # an inflected form ("podnikatele", "hokejistou")
        if f.startswith(k[:-1]) and len(f) - len(k) <= 3:
            return _CTX_EN[k]
    return ctx


def _set_aside(identity: list[IdentityMatch], namesakes: list[IdentityMatch], news_items: list[NewsItem],
               lang: str, name: str = "") -> list[SetAside]:
    cs = lang != "en"
    out: list[SetAside] = []
    for m in identity:
        if m.platform == "news" or m.status == "matched":
            continue
        name = f"{_PLATFORM_NAME.get(m.platform, m.platform)} @{m.handle}"
        src = next((s.source for s in m.signals if s.source is not None), None)
        if m.status == "rejected":
            fan = any(_has(s, _FAN_MARKS) for s in m.signals if not s.supports)
            against = [s.signal for s in m.signals if not s.supports] or (
                ["žádný společný znak s profilem"] if cs else ["nothing links it to the profile"])
            no_link = not any(s.supports and (_has(s, _BACKLINK_MARKS) or _has(s, _LINK_MARKS) or _has(s, _SITE_MARKS))
                              for s in m.signals)
            if no_link and not fan:
                against = against + (["žádný odkaz mezi účty"] if cs else ["no link between the accounts"])
            reason = "; ".join(against)
            out.append(SetAside(ref=f"{m.platform}:{m.handle}", label=name, kind="fan_account" if fan else "look_alike",
                                reason={"cs": reason, "en": reason}, source=src))
        else:  # uncertain
            sup = "; ".join(s.signal for s in m.signals if s.supports)
            reason = (f"jen podobné jméno ({sup}); žádný odkaz mezi účty" if cs
                      else f"only a similar name ({sup}); no link between the accounts")
            out.append(SetAside(ref=f"{m.platform}:{m.handle}", label=name, kind="look_alike",
                                reason={"cs": reason, "en": reason}, source=src))
    by_id = {it.id: it for it in news_items}
    for m in namesakes:
        it = by_id.get(m.handle)
        s = m.signals[0] if m.signals else None
        outlet = it.outlet if it else "news"
        date = it.published_at.date().isoformat() if it and it.published_at else ""
        # Data minimisation: the headline of an article about someone else is not repeated; the label
        # names the outlet, the shared name and the context word that tells them apart.
        ctx_m = _CTX_RE.search(s.signal) if s else None
        ctx_word = ctx_m.group(1) if ctx_m else ""
        # the signal already carries the context in this language (match_news -> _ctx_label)
        ctx = f" ({ctx_word})" if ctx_word else ""
        if name:
            label = (f"článek {outlet} o jiném člověku jménem {name}{ctx}" if cs
                     else f"{outlet} article about another {name}{ctx}")
        else:
            label = (f"článek {outlet}" if cs else f"{outlet} article") + (f" ({date})" if date else "")
        reason = s.signal if s else ("jiný člověk se stejným jménem" if cs else "another person with the same name")
        out.append(SetAside(ref=m.handle, label=label, kind="namesake", reason={"cs": reason, "en": reason},
                            source=s.source if s else None))
    return out


def identity_verdict(profile: Profile | None, anchor: Anchor | None, anchor_sigs: list[tuple[str, IdentitySignal]],
                     identity: list[IdentityMatch], namesakes: list[IdentityMatch], news_items: list[NewsItem],
                     *, lang: str = "cs", handle: str | None = None, tried: list[str] | None = None) -> IdentityVerdict:
    """Deterministic verdict: is this the account the owner means (never "trustworthy").
    Signal texts are in ``lang``; the text is filled for both keys from them (the report renders the
    verdict once per language and merges, so each language reads naturally)."""
    h = (profile.handle if profile is not None else norm_handle(handle or "")) or "?"
    texts: dict[str, str] = {}
    if profile is None:
        for lg in ("cs", "en"):
            plats = _platforms_text(tried or [], lg)
            texts[lg] = (f"Veřejný profil @{h} jsme na {plats} nenašli." if lg == "cs"
                         else f"We found no public profile @{h} on {plats}.")
        return IdentityVerdict(status="not_found", text=texts, anchor=anchor)

    kinds = {k for k, _ in anchor_sigs}
    hard = bool(kinds & {"anchor_website", "anchor_company_id"})
    city_bio = "anchor_city_bio" in kinds
    city_any = city_bio or "anchor_city_posts" in kinds
    city_other = "anchor_city_other" in kinds
    cross = [m for m in identity if m.platform != "news"]
    matched = [m for m in cross if m.status == "matched"]
    has_anchor = anchor is not None and any((anchor.city, anchor.website, anchor.company_id))

    if (hard or (city_bio and matched)) and not city_other:
        status = "confirmed"
    elif not city_other and (city_any or (not has_anchor and matched)):
        status = "likely"
    else:
        status = "uncertain"

    supporting = [s for _, s in anchor_sigs if s.supports]
    contradicting = [s for _, s in anchor_sigs if not s.supports]
    for m in matched:
        supporting.extend(s for s in m.signals if s.supports)
    set_aside = _set_aside(identity, namesakes, news_items, lang, person_name(profile.display_name))

    for lg in ("cs", "en"):
        cs = lg == "cs"
        reasons = [s.signal for _, s in anchor_sigs if s.supports] + [match_reason(m, lang) for m in matched]
        reason_txt = _join_and(reasons, lg)
        if status == "confirmed":
            t = (f"Jsme si jistí, že @{h} je tvůrce, kterého myslíte: {reason_txt}." if cs
                 else f"We are confident @{h} is the creator you mean because {reason_txt}.")
        elif status == "likely":
            missing_site = anchor is not None and (anchor.website or anchor.company_id) and not hard
            if missing_site:
                what = (f"web {anchor.website}" if anchor.website else f"IČO {anchor.company_id}") if cs else (
                    f"the website {anchor.website}" if anchor.website else f"company ID {anchor.company_id}")
                missing = (f"{what[0].upper() + what[1:]} jsme na profilu nenašli." if cs
                           else f"{what[0].upper() + what[1:]} was not found on the profile.")
            elif not has_anchor:
                missing = ("Bez kotvy (město, web nebo IČO) to jistě potvrdit nejde." if cs
                           else "Without an anchor (city, website or company ID) we cannot confirm it.")
            else:
                missing = ("Jistotu by dal jejich web nebo IČO." if cs
                           else "Their website or company ID would confirm it.")
            t = (f"@{h} je nejspíš tvůrce, kterého myslíte: {reason_txt}. {missing}" if cs
                 else f"@{h} is probably the creator you mean: {reason_txt}. {missing}")
        else:
            problems = [s.signal for s in contradicting]
            if has_anchor and not any(s.supports for _, s in anchor_sigs):
                at = _anchor_text(anchor, lg)
                if matched:
                    names = ", ".join(f"{_PLATFORM_NAME.get(m.platform, m.platform)} @{m.handle}" for m in matched[:2])
                    problems.append(f"nic na profilu neodpovídá kotvě ({at}), i když na něj odkazuje účet na jiné síti ({names})"
                                    if cs else f"nothing on the profile matches the anchor ({at}), although an account on "
                                               f"another platform links to it ({names})")
                else:
                    problems.append(f"nic na profilu neodpovídá kotvě ({at})" if cs
                                    else f"nothing on the profile matches the anchor ({at})")
                if anchor is not None and anchor.company_id:
                    problems.append("IČO hledáme jen ve veřejném profilu, obchodní rejstřík nedotazujeme" if cs
                                    else "we look for the company ID only on the public profile and do not query the "
                                         "business register")
            if not has_anchor and not matched:
                problems.append("kotvu jste nezadali a žádný účet na jiné síti na profil neodkazuje" if cs
                                else "no anchor was given and no account on another platform links to it")
            if not problems:
                problems.append("signály si odporují" if cs else "the signals contradict each other")
            t = (f"Nepodařilo se potvrdit, že @{h} je tvůrce, kterého myslíte: {'; '.join(problems)}. "
                 "Zkontrolujte uživatelské jméno nebo zadejte jinou kotvu (město, web nebo IČO)." if cs
                 else f"We could not confirm @{h} is the creator you mean: {'; '.join(problems)}. "
                      "Check the handle or give another anchor (city, website or company ID).")
        if set_aside:
            n = len(set_aside)
            labels = ", ".join(sa.label for sa in set_aside)
            if cs:
                if n == 1:
                    t += f" Stranou jsme dali 1 zdroj, který jen vypadá podobně nebo patří jmenovci: {labels}."
                else:
                    word = "zdroje" if n < 5 else "zdrojů"
                    t += f" Stranou jsme dali {n} {word}, které jen vypadají podobně nebo patří jmenovcům: {labels}."
            else:
                t += f" We set aside {n} look-alike or namesake {'source' if n == 1 else 'sources'}: {labels}."
        texts[lg] = t
    return IdentityVerdict(status=status, text=texts, supporting=supporting, contradicting=contradicting,
                           set_aside=set_aside, anchor=anchor)


def _join_and(items: list[str], lang: str) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" a " if lang == "cs" else " and ") + items[-1]


def _anchor_text(anchor: Anchor | None, lang: str) -> str:
    from app.compute.subject import anchor_text

    return anchor_text(anchor, lang)
