"""Pure, deterministic metric computations (no I/O, no LLM). Inputs are already sensitive-filtered.

Definitions (architecture.md section 4):
- engagement_rate = median over posts with known likes of (likes + (comments or 0)) / followers;
  None if followers is None/0 or no post has likes.
- posts_per_week: (n - 1) posts per created_at span of the analyzed posts in weeks (needs >= 2 posts,
  else None); the span is at least one day. Pinned posts are left out (``activity_posts``).
- last_post_at: newest created_at among the non-pinned posts. A pinned post can be years old (or the
  only recent-looking one), so it says nothing about current activity. Pinned = ``is_pinned`` True, or,
  when the provider did not say (None), one of up to 3 leading posts that are older than the newest-first
  list that follows them (Instagram and TikTok show pinned posts first).
- commercial_share: share of posts where ``is_commercial(post)``; None if no posts.
- local_signals: SourceRefs of posts whose location_name or caption / hashtags mention the city
  (diacritics-insensitive, e.g. "Brno"/"brněnský"/"#brnofood"), plus the profile source when the bio
  mentions it; quote = the matching snippet.
- engagement_spikes: ids of posts with likes+comments > factor * median interactions.
- cs_comment_share: share of Czech among comments with a detectable language (emoji-only and
  one-word comments are too short to detect and drop out); None when fewer than 3 such comments.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import datetime

from app.compute import collabs as _collabs
from app.compute import language as _language
from app.models import TOPICS, Comment, Metrics, Post, Profile, SourceRef

MIN_COMMENTS_FOR_LANGUAGE = 3


def median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    if n % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def interactions(post: Post) -> int | None:
    """likes + comments, None when likes are hidden / unknown."""
    if post.likes is None:
        return None
    return post.likes + (post.comments or 0)


def engagement_rate(posts: list[Post], followers: int | None) -> float | None:
    if not followers:
        return None
    rates = [i / followers for i in (interactions(p) for p in posts) if i is not None]
    return median(rates)


MAX_PINNED = 3   # Instagram and TikTok both allow up to 3 pinned posts


def pinned_post_ids(posts: list[Post]) -> set[str]:
    """Ids of pinned posts, in the provider's order (newest first apart from the pinned ones).

    ``is_pinned`` True counts; False never counts. For None, a post counts when it is one of the
    first ``MAX_PINNED`` posts, the rest of the list after the leading block is in newest-first order,
    and the post is older than the first post of that rest (a leading out-of-order post). A list in
    any other order (oldest first, shuffled) gets no heuristic: only explicit flags count there."""
    ids = {p.id for p in posts if p.is_pinned is True}
    n = len(posts)
    for k in range(1, min(MAX_PINNED, n - 2) + 1):
        rest = posts[k:]
        if all(rest[i].created_at >= rest[i + 1].created_at for i in range(len(rest) - 1)):
            head = rest[0].created_at
            ids.update(p.id for p in posts[:k] if p.is_pinned is None and p.created_at < head)
            break
    return ids


def activity_posts(posts: list[Post]) -> list[Post]:
    """Posts that show current activity: everything except pinned posts."""
    pinned = pinned_post_ids(posts)
    return [p for p in posts if p.id not in pinned] if pinned else list(posts)


def last_post_at(posts: list[Post]) -> datetime | None:
    return max((p.created_at for p in activity_posts(posts)), default=None)


def posts_per_week(posts: list[Post]) -> float | None:
    posts = activity_posts(posts)
    if len(posts) < 2:
        return None
    dates = sorted(p.created_at for p in posts)
    span_days = max((dates[-1] - dates[0]).total_seconds() / 86400.0, 1.0)
    return (len(posts) - 1) / (span_days / 7.0)


def format_counts(posts: list[Post]) -> dict[str, int]:
    """media_type -> count."""
    return dict(Counter(p.media_type for p in posts))


def is_commercial(post: Post) -> bool:
    """paid_partnership True, or an ad hashtag / ad phrase (collabs.AD_HASHTAGS), or a discount code
    or affiliate link in the caption."""
    if post.paid_partnership is True:
        return True
    if _collabs.ad_markers(post):
        return True
    caption = post.caption or ""
    return bool(_collabs.find_discount_codes(caption) or _collabs.find_affiliate_links(caption))


def commercial_posts(posts: list[Post]) -> list[Post]:
    return [p for p in posts if is_commercial(p)]


def commercial_share(posts: list[Post]) -> float | None:
    if not posts:
        return None
    return len(commercial_posts(posts)) / len(posts)


# ---------------------------------------------------------------------------------------------
# Local signals
# ---------------------------------------------------------------------------------------------

def _fold(text: str) -> str:
    """Lowercase, no diacritics."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# Czech declension changes some stems ("Praha" -> "v Praze"); extra stems for common cities. Stems are
# for prefix checks (identity.py); matching in text uses city_pattern(), which for Praha lists the
# declined forms explicitly so "prázdniny" / "prázdný" / "práh" are not Praha.
_CITY_STEMS: dict[str, tuple[str, ...]] = {
    "praha": ("praha", "prahy", "prahu", "prahou", "praze", "prazsk", "prazak", "prazan", "prague"),
    "brno": ("brn",),
    "plzen": ("plzen", "plzn"),
    "ostrava": ("ostrav",),
    "olomouc": ("olomouc",),
    "liberec": ("liberec", "liberc"),
    "hradec kralove": ("hradec", "hradc"),
    "ceske budejovice": ("budejovic", "budejck"),
    "usti nad labem": ("usti nad labem", "ustec"),
    "zlin": ("zlin",),
    "pardubice": ("pardubic", "pardubick"),
    "jihlava": ("jihlav",),
}

# Full regexes (over folded text) where a prefix would hit ordinary words.
_CITY_REGEX: dict[str, str] = {
    "praha": r"prah(?:a|y|u|ou)\b|praze\b|prazsk[a-z]*|prazak[a-z]*|prazac[a-z]*|prazan[a-z]*|prague[a-z]*",
}


def _word_stem(w: str) -> str:
    return w[:-1] if len(w) >= 5 and w[-1] in "aeiouy" else w


def city_stems(city: str) -> tuple[str, ...]:
    c = _fold(city).strip()
    if not c:
        return ()
    if c in _CITY_STEMS:
        return _CITY_STEMS[c]
    return (" ".join(_word_stem(w) for w in c.split()),)


def city_pattern(city: str) -> re.Pattern[str] | None:
    c = _fold(city).strip()
    if not c:
        return None
    if c in _CITY_REGEX:
        return re.compile(r"(?<![a-z0-9])(?:" + _CITY_REGEX[c] + r")", re.IGNORECASE)
    if c in _CITY_STEMS:
        return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(st) for st in _CITY_STEMS[c]) + r")[a-z]*", re.IGNORECASE)
    # Generic: every word declines ("Mladá Boleslav" -> "v Mladé Boleslavi"): stem + any ending, per word.
    words = [w for w in re.split(r"\W+", c) if w]
    if not words:
        return None
    body = r"\W+".join(re.escape(_word_stem(w)) + r"[a-z]*" for w in words)
    return re.compile(r"(?<![a-z0-9])" + body, re.IGNORECASE)


def _snippet(text: str, start: int, end: int, width: int = 120) -> str:
    text = text.replace("\n", " ")
    a = max(0, start - width // 3)
    b = min(len(text), max(end, a + width))
    return ("…" if a > 0 else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def local_signals(profile: Profile, posts: list[Post], city: str | None) -> list[SourceRef]:
    """[] when city is None."""
    if not city:
        return []
    pat = city_pattern(city)
    if pat is None:
        return []
    out: list[SourceRef] = []
    bio = profile.bio or ""
    m = pat.search(_fold(bio))
    if m:
        out.append(profile.source.model_copy(update={"quote": _snippet(bio, m.start(), m.end())}))
    seen: set[str] = set()
    for p in posts:
        quote: str | None = None
        if p.location_name and pat.search(_fold(p.location_name)):
            quote = f"📍 {p.location_name}"
        else:
            caption = p.caption or ""
            m = pat.search(_fold(caption))
            if m:
                quote = _snippet(caption, m.start(), m.end())
            else:
                tag = next((h for h in p.hashtags if pat.search(_fold(h))), None)
                if tag:
                    quote = f"#{tag}"
        if quote is None:
            continue
        key = p.source.id or p.id
        if key in seen:
            continue
        seen.add(key)
        out.append(p.source.model_copy(update={"quote": quote}))
    return out


# ---------------------------------------------------------------------------------------------
# Spikes, topics, comments
# ---------------------------------------------------------------------------------------------

def engagement_spikes(posts: list[Post], factor: float = 3.0) -> list[str]:
    pairs = [(p.id, interactions(p)) for p in posts]
    values = [v for _, v in pairs if v is not None]
    if len(values) < 3:
        return []
    med = median([float(v) for v in values])
    if not med:
        return []
    return [pid for pid, v in pairs if v is not None and v > factor * med]


def topic_counts(topic_labels: dict[str, str]) -> dict[str, int]:
    """{post_id: topic} -> {topic: count}. Unknown labels count as "other"; the fallback's
    "unclassified" stays its own key (callers leave it out of shares)."""
    c: Counter[str] = Counter()
    for topic in topic_labels.values():
        c[topic if (topic in TOPICS or topic == UNCLASSIFIED) else "other"] += 1
    return dict(c)


UNCLASSIFIED = "unclassified"   # == llm.topics.UNCLASSIFIED


def classified_total(counts: dict[str, int]) -> int:
    return sum(n for t, n in counts.items() if t != UNCLASSIFIED)


def comment_stats(comments: list[Comment]) -> tuple[float | None, float | None, int]:
    """(cs_comment_share, generic_comment_share, comments_analyzed) from comment texts."""
    texts = [c.text for c in comments if c.text and c.text.strip()]
    if not texts:
        return None, None, 0
    cs_share = _language.language_share(texts, "cs", min_texts=MIN_COMMENTS_FOR_LANGUAGE)
    return cs_share, _language.generic_share(texts), len(texts)


def compute_metrics(
    profile: Profile,
    posts: list[Post],
    *,
    city: str | None = None,
    topic_labels: dict[str, str] | None = None,
    comments: list[Comment] | None = None,
    now: datetime | None = None,
) -> Metrics:
    """Full Metrics for one candidate. topic_labels None -> topic_counts {}; comments None ->
    cs_comment_share / generic_comment_share None and comments_analyzed 0 (via compute.language)."""
    likes = [float(p.likes) for p in posts if p.likes is not None]
    ncomments = [float(p.comments) for p in posts if p.comments is not None]
    if comments is None:
        cs_share, gen_share, n_comments = None, None, 0
    else:
        cs_share, gen_share, n_comments = comment_stats(comments)
    return Metrics(
        posts_analyzed=len(posts),
        median_likes=median(likes),
        median_comments=median(ncomments),
        engagement_rate=engagement_rate(posts, profile.followers),
        posts_per_week=posts_per_week(posts),
        last_post_at=last_post_at(posts),
        formats=format_counts(posts),
        commercial_share=commercial_share(posts),
        topic_counts=topic_counts(topic_labels) if topic_labels else {},
        cs_comment_share=cs_share,
        comments_analyzed=n_comments,
        generic_comment_share=gen_share,
        local_signals=local_signals(profile, posts, city),
        engagement_spikes=engagement_spikes(posts),
    )
