"""Collaboration evidence from posts -> CollabEvidence (deterministic, no LLM).

Per post, emit evidence for: coauthors (kind "coauthor"), brand mentions (@handle in caption/mentions,
kind "mention"), tagged_users ("tag"), ad hashtags ("ad_hashtag"), discount codes ("discount_code"),
paid_partnership True ("paid_label"), affiliate links in caption ("affiliate_link").
disclosed: True if the post has paid_partnership True OR an ad hashtag OR an ad phrase in the
caption ("reklama", "spolupráce", "placená spolupráce", "#ad", "sponsored"); False if the post carries
a commercial signal (brand coauthor, discount code, affiliate link, or the brand is one the record
already shows a paid relationship with: an ad-labeled post or a Meta branded-content record) and none
of those markers is found AND paid_partnership is False; None otherwise: platform label unknown, or a
plain @mention / tag with no commercial signal at all (an organic or even critical mention of a brand
is not an unlabeled ad).
id = f"collab:{post_id}:{kind}:{brand}". source = post.source with a quote of the matching text.
Creator's own handle and plain friend mentions are not brands. A mentioned / tagged handle counts as
a brand only when it is explainable: it is a competitor, a coauthor, appears in a post that carries
an ad marker (paid label, ad hashtag, ad phrase, discount code, affiliate link), or its handle looks
like a business (shop, store, bakery, cafe, studio, official, ".cz" ...).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from app.models import CollabEvidence, Post, SourceRef, norm_handle

AD_HASHTAGS: frozenset[str] = frozenset({
    "reklama", "spoluprace", "spolupráce", "placenaspoluprace", "ad", "ads", "sponsored", "sponzorovano",
    "partnerstvi", "partnership", "advertisement", "affiliate", "collab",
})

# CollabEvidence.brand when a post is labeled as an ad but names no brand (UI shows "brand not named").
UNKNOWN_BRAND = "unknown"

# Caption phrases that label a post as advertising.
_AD_PHRASE_RE = re.compile(r"(?<![\w])(?:reklama|placen[aá] spolupr[aá]ce|spolupr[aá]ce s|ve spolupr[aá]ci s|"
                           r"sponzorov[aá]n[oý]|paid partnership|sponsored|advertisement|"
                           r"in partnership with|#ad\b|\(ad\)|\[ad\])", re.IGNORECASE)

_NEGATION_RE = re.compile(r"\b(?:nen[ií]|nejde o|[zž][aá]dn[aáý]|not|no|isn'?t|neni to)\W{0,3}\w{0,6}\W{0,3}$", re.IGNORECASE)

_CODE_TRIGGER = (
    r"(?:use\s+(?:the\s+|my\s+)?)?(?:(?:discount|promo|coupon|slevov\w*)\s+)?"
    r"(?:k[oó]d(?:em|u|y)?|code|coupon|kup[oó]n(?:em|u)?|voucher(?:em|u)?)"
)
_CODE_RE = re.compile(
    rf"(?<![\w])(?:{_CODE_TRIGGER})\s*[:\-–]?\s*[\"'„“‚‘»«]?([A-Za-z0-9][A-Za-z0-9_\-]{{2,24}})",
    re.IGNORECASE,
)
_CODE_STOPWORDS = {
    "na", "pro", "se", "ve", "the", "for", "this", "my", "our", "your", "code", "kod", "kód", "and",
    "sleva", "slevu", "slevou", "nakup", "nákup", "eshop", "web", "link", "bio", "here", "zde",
}

_AFFILIATE_RE = re.compile(
    r"https?://\S*(?:[?&](?:ref|aff|affid|aff_id|affiliate|partner|a_aid|utm_medium=affiliate|"
    r"utm_source=(?:influencer|affiliate))[=&]?\S*|/aff/\S*|/ref/\S*|dognet\.\S*|ehub\.\S*|awin1\.\S*)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# "(?<![\w.])@": an "@" right after a word character or a dot is an e-mail address
# ("brnenskamama@gmail.com"), not a mention of @gmail.com.
_MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_.]{2,30})")
_EMAIL_DOMAIN_RE = re.compile(r"(?<=[\w.])@([A-Za-z0-9_.\-]{2,60})")

_BRANDISH_RE = re.compile(
    r"(shop|store|eshop|official|oficial|brand|bakery|pekarn|kavarn|cafe|coffee|bistro|restaur|"
    r"cukrar|studio|gym|fitness|club|klub|market|_cz$|\.cz$|_sk$|cz_|_eu$|\.eu$|_com$|\.com$|_shop|"
    r"supplements|nutrition|wear$|cosmetics|kosmetik|beauty$)",
    re.IGNORECASE,
)


def _strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_brand(name: str) -> str:
    """Lowercase, strip '@', diacritics and separators: "Pekárna B" -> "pekarnab"."""
    t = _strip_diacritics(norm_handle(name or ""))
    return re.sub(r"[^a-z0-9]", "", t.lower())


_AD_HASHTAG_KEYS = frozenset(normalize_brand(x) for x in AD_HASHTAGS)


def find_discount_codes(text: str) -> list[str]:
    """Codes like "kód ANNA20", "se slevovým kódem X", "code X10"; returns the codes.
    A token counts only if it contains a digit or is written in capitals (avoids "kód na slevu")."""
    out: list[str] = []
    for m in _CODE_RE.finditer(text or ""):
        code = m.group(1).strip("-_")
        if len(code) < 3 or code.lower() in _CODE_STOPWORDS:
            continue
        has_digit = any(c.isdigit() for c in code)
        is_caps = code.isupper() and len(code) >= 4
        if not (has_digit or is_caps):
            continue
        if code not in out:
            out.append(code)
    return out


def find_affiliate_links(text: str) -> list[str]:
    return [m.group(0).rstrip(").,!?") for m in _AFFILIATE_RE.finditer(text or "")]


def ad_markers(post: Post) -> list[str]:
    """Disclosure markers found on the post: paid label, ad hashtags, ad phrases in the caption."""
    markers: list[str] = []
    if post.paid_partnership is True:
        markers.append("paid_label")
    for h in post.hashtags:
        if is_ad_hashtag(h):
            markers.append(f"#{h}")
    caption = post.caption or ""
    for m in _AD_PHRASE_RE.finditer(caption):
        if _NEGATION_RE.search(caption[max(0, m.start() - 16): m.start()]):
            continue  # "není to reklama", "not sponsored"
        markers.append(m.group(0).strip().lower())
        break
    return markers


def is_ad_hashtag(tag: str) -> bool:
    return normalize_brand(tag) in _AD_HASHTAG_KEYS


def disclosed_state(post: Post) -> bool | None:
    """True = labeled; False = no caption marker and the platform says no paid label; None = unknown."""
    if ad_markers(post):
        return True
    if post.paid_partnership is False:
        return False
    return None


def competitor_keys(competitors: list[dict]) -> set[str]:
    """Brief.competitors [{"name", "handles"}] -> normalized names + handles."""
    keys: set[str] = set()
    for c in competitors or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if isinstance(name, str) and normalize_brand(name):
            keys.add(normalize_brand(name))
        handles = c.get("handles") or []
        if isinstance(handles, str):
            handles = [handles]
        for h in handles:
            if isinstance(h, str) and normalize_brand(h):
                keys.add(normalize_brand(h))
    return keys


def _is_competitor(brand: str, brand_handle: str | None, keys: set[str]) -> bool:
    if not keys:
        return False
    return normalize_brand(brand) in keys or (brand_handle is not None and normalize_brand(brand_handle) in keys)


def _quote(text: str, needle: str, width: int = 140) -> str:
    """Snippet of ``text`` around ``needle`` (case-insensitive); whole text clipped if not found."""
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return needle
    i = text.lower().find(needle.lower()) if needle else -1
    if i < 0:
        return text[:width]
    start = max(0, i - width // 3)
    end = min(len(text), start + width)
    snippet = text[start:end]
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def _caption_mentions(post: Post) -> list[str]:
    found = [norm_handle(m) for m in _MENTION_RE.findall(post.caption or "")]
    return [h.rstrip(".") for h in found if h]


def _post_mentions(post: Post) -> list[str]:
    """``post.mentions`` without e-mail domains: a provider that parses "@x" out of the caption turns
    "jana@gmail.com" into a mention of "gmail.com". A handle that occurs in the caption only after
    "<word>@" (never as a real "@handle") is dropped."""
    if not post.mentions:
        return []
    caption = post.caption or ""
    domains = {norm_handle(m).rstrip(".") for m in _EMAIL_DOMAIN_RE.findall(caption)}
    if not domains:
        return list(post.mentions)
    real = set(_caption_mentions(post))
    return [h for h in post.mentions if norm_handle(h).rstrip(".") not in domains or norm_handle(h).rstrip(".") in real]


def extract_collabs(
    posts: list[Post],
    *,
    own_handle: str | None = None,
    competitors: list[dict] | None = None,
    paid_brands: set[str] | None = None,
) -> list[CollabEvidence]:
    """Evidence from posts, is_competitor set from competitors. ``paid_brands`` (normalized names /
    handles, e.g. from Meta branded-content records) are brands with a known paid relationship."""
    own = normalize_brand(own_handle) if own_handle else None
    keys = competitor_keys(competitors or [])

    # Handles that count as brands across the whole post set (explainable rule, see module doc).
    ad_posts: set[str] = set()
    brandish: set[str] = set()
    for p in posts:
        caption = p.caption or ""
        if ad_markers(p) or find_discount_codes(caption) or find_affiliate_links(caption):
            ad_posts.add(p.id)
            brandish.update(_post_mentions(p))
            brandish.update(p.tagged_users)
            brandish.update(_caption_mentions(p))
        brandish.update(p.coauthors)
    for p in posts:
        for h in [*_post_mentions(p), *p.tagged_users, *_caption_mentions(p)]:
            if normalize_brand(h) in keys or _BRANDISH_RE.search(h):
                brandish.add(h)

    def is_brand(h: str) -> bool:
        return bool(h) and normalize_brand(h) != own and h in brandish

    # Brands with a known paid relationship: named in an ad-marked post, or given by the caller.
    known_paid: set[str] = {normalize_brand(b) for b in (paid_brands or set()) if b}
    for p in posts:
        if p.id in ad_posts:
            for h in [*p.coauthors, *_post_mentions(p), *p.tagged_users, *_caption_mentions(p)]:
                if is_brand(h):
                    known_paid.add(normalize_brand(h))

    out: list[CollabEvidence] = []
    seen: set[str] = set()

    def add(post: Post, kind: str, brand: str, brand_handle: str | None, needle: str, disclosed: bool | None) -> None:
        brand_key = normalize_brand(brand) or UNKNOWN_BRAND
        eid = f"collab:{post.id}:{kind}:{brand_key}"
        if eid in seen:
            return
        seen.add(eid)
        quote = _quote(post.caption, needle) if needle else (post.caption or "")[:140] or None
        source: SourceRef = post.source.model_copy(update={"quote": quote})
        out.append(CollabEvidence(
            id=eid,
            brand=brand,
            brand_handle=brand_handle,
            kind=kind,  # type: ignore[arg-type]
            disclosed=disclosed,
            date=post.created_at,
            post_id=post.id,
            is_competitor=_is_competitor(brand, brand_handle, keys),
            source=source,
        ))

    for p in posts:
        caption = p.caption or ""
        disclosed = disclosed_state(p)
        commercial = bool(
            any(is_brand(h) for h in p.coauthors) or find_discount_codes(caption) or find_affiliate_links(caption)
            or p.paid_partnership is True or ad_markers(p)
        )
        # A plain mention / tag without any commercial signal: we cannot say it is an unlabeled ad.
        mention_disclosed = disclosed if (commercial or disclosed is True) else None

        def mention_state(h: str) -> bool | None:
            if mention_disclosed is None and disclosed is False and normalize_brand(h) in known_paid:
                return False  # unlabeled post for a brand the record shows a paid relationship with
            return mention_disclosed
        brands_in_post: list[str] = []
        for h in p.coauthors:
            if is_brand(h):
                brands_in_post.append(h)
                add(p, "coauthor", h, h, f"@{h}", disclosed)
        for h in [*_post_mentions(p), *_caption_mentions(p)]:
            if is_brand(h) and h not in p.coauthors:
                if h not in brands_in_post:
                    brands_in_post.append(h)
                add(p, "mention", h, h, f"@{h}", mention_state(h))
        for h in p.tagged_users:
            if is_brand(h) and h not in p.coauthors:
                if h not in brands_in_post:
                    brands_in_post.append(h)
                add(p, "tag", h, h, f"@{h}", mention_state(h))

        main_brand = brands_in_post[0] if brands_in_post else None
        brand_name = main_brand or UNKNOWN_BRAND

        ad_tags = [h for h in p.hashtags if is_ad_hashtag(h)]
        if ad_tags:
            add(p, "ad_hashtag", brand_name, main_brand, f"#{ad_tags[0]}", True)
        for code in find_discount_codes(caption):
            add(p, "discount_code", main_brand or code, main_brand, code, disclosed)
        if p.paid_partnership is True:
            add(p, "paid_label", brand_name, main_brand, "", True)
        for link in find_affiliate_links(caption):
            add(p, "affiliate_link", main_brand or _link_domain(link), main_brand, link, disclosed)
    return out


def _link_domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/?#]+)", url, re.IGNORECASE)
    return m.group(1).lower() if m else url


def mark_competitors(evidence: list[CollabEvidence], competitors: list[dict]) -> list[CollabEvidence]:
    """Return copies with is_competitor recomputed (goal change may change competitors)."""
    keys = competitor_keys(competitors or [])
    return [e.model_copy(update={"is_competitor": _is_competitor(e.brand, e.brand_handle, keys)}) for e in evidence]


def merge_timeline(*sources: list[CollabEvidence]) -> list[CollabEvidence]:
    """Merge post-derived + provider evidence (meta_branded), dedupe by id, sort by date desc (None last)."""
    by_id: dict[str, CollabEvidence] = {}
    for src in sources:
        for e in src or []:
            if e.id not in by_id:
                by_id[e.id] = e
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(by_id.values(), key=lambda e: (e.date is not None, e.date or floor), reverse=True)


def undisclosed_posts(evidence: list[CollabEvidence]) -> list[CollabEvidence]:
    """One evidence item per post (or per evidence without a post) whose disclosure is False."""
    seen: set[str] = set()
    out: list[CollabEvidence] = []
    for e in evidence:
        if e.disclosed is not False:
            continue
        key = e.post_id or e.id
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


# Evidence kinds that indicate an actual collaboration (not just a mention).
COLLAB_KINDS = frozenset({"coauthor", "paid_label", "meta_branded", "ad_hashtag", "discount_code", "affiliate_link"})


def collaboration_evidence(evidence: list[CollabEvidence]) -> list[CollabEvidence]:
    """Evidence that shows a collaboration: a commercial kind, a mention / tag whose disclosure is
    known (True = labeled ad, False = commercial signal without a label), or one on a post that
    carries a commercial kind. Plain mentions / tags (disclosed None) are left out."""
    commercial_posts = {e.post_id for e in evidence if e.post_id and (e.kind in COLLAB_KINDS or e.disclosed is not None)}
    return [e for e in evidence
            if e.kind in COLLAB_KINDS or e.disclosed is not None or (e.post_id is not None and e.post_id in commercial_posts)]
