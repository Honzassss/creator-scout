"""Classify post captions (+ hashtags) into the fixed TOPICS taxonomy, one topic per post.

One LLM call per candidate (model_bulk, structured output: index -> topic constrained to TOPICS),
cached in data/llm/ by hash of sorted post ids. Unknown labels -> "other"; posts the model skipped
get the keyword label. Fallback: hashtag/keyword map (cs + en, diacritics-insensitive); a post with no
keyword hit is UNCLASSIFIED (not "other": the fallback cannot tell "another topic" from "a food post
it does not recognise", and an unrecognised post must not count against topic_share).
record_mode("topics", ...). Input posts are already sensitive-filtered.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from app.llm import client as llm_client
from app.llm import prompts
from app.llm.text import clip, fold
from app.models import TOPICS, Post, short_hash

# Fallback map: topic -> keyword stems (folded: lowercase, no diacritics). Stems of <= 4 chars must
# start a word in the caption; every stem also matches inside a hashtag ("brnofood" -> "food").
KEYWORD_TOPICS: dict[str, tuple[str, ...]] = {
    "food": (
        "jidl", "food", "chleb", "chleba", "pecivo", "kvasek", "kvask", "rohlik", "croissant", "dort",
        "cukrar", "pekar", "pekarn", "bakery", "bread", "pastry", "dezert", "dessert", "kolac", "buchty",
        "snidan", "breakfast", "brunch", "obed", "vecere", "dinner", "lunch", "mnam", "yummy", "foodie",
        "tasty", "chutn", "sladk", "cake", "pizza", "burger", "zmrzlin", "icecream", "polevk", "maso",
        "syr$", "syry", "jidelni", "ochutnav", "degustac", "streetfood", "makronk", "vino$", "pivo$",
    ),
    "recipes": (
        "recept", "recipe", "vareni", "varim", "peceni", "pecem", "upec", "uvar", "baking", "homemade",
        # not a bare "domácí" / "postup": a sports club's "domácí zápas" and "postup do finále" are not recipes
        "domaci recept", "domaci peceni", "domaci chleb", "domaci kvas", "domaci dort", "domaci kolac",
        "domaci jidl", "domaci limonad", "domaci testovin", "postup prip", "ingredien", "cooking", "cook$",
        "kucharsk", "navod na",
    ),
    "restaurants_cafes": (
        "restaurac", "restaurant", "kavarn", "cafe", "kafe", "kava$", "kavu$", "coffee", "bistro", "bar$",
        "bary", "podnik", "menu$", "espresso", "cappuccino", "flat white", "vinarn", "hospod", "pub$",
    ),
    # Tips about places, not every post that names a city: "Brno", "#brnofood", "lokální" or "otevřeno"
    # say where a post is, not what it is about (a sports club's match report is not a local tip).
    "local_tips": (
        "tip$", "tipy", "tipu", "tipem", "kam v", "kam zajit", "kam vyrazit", "kam na", "city guide",
        "objevuj", "novinka v", "vikend v", "akce v", "trh$", "trhy", "trhu", "festival v", "mistni tip",
        "where to", "hidden gem",
    ),
    "family": (
        "rodin", "deti", "dite", "detsk", "mamin", "tatin", "family", "kids", "child", "baby", "miminko",
        "materstv", "parenting", "syn$", "synem", "dcer", "mama$", "tata$",
    ),
    "lifestyle": (
        "lifestyle", "zivotni styl", "den se mnou", "day in my life", "rutin", "routine", "vlog", "domov",
        "home$", "interier", "interior", "wellness", "selfcare", "self-care", "motivac", "ranni", "pohoda",
        "minimalism",
    ),
    "fitness": (
        "fitness", "fit$", "fitko", "cvic", "trenink", "trenin", "workout", "gym", "posilov", "joga",
        "jog$", "jogging", "yoga", "pilates", "crossfit", "kardio", "cardio", "strecink", "stretching",
        "kondic", "hubn", "protein", "squat", "drep", "kliky", "lekce", "trener", "trainer", "hiit",
        "kettlebell",
    ),
    "sport": (
        "sport", "beh$", "behani", "behat", "run$", "running", "maraton", "marathon", "kolo$", "kole$",
        "cyklo", "bike$", "fotbal", "football", "hokej", "hockey", "tenis", "tennis", "plavani", "swim",
        "lyz", "ski$", "zavod", "horolez", "climbing", "lezeni", "turistik", "hiking", "zapas", "utkani",
        "turnaj", "florbal", "basketbal", "basket$", "volejbal", "hazen", "baseball", "extralig", "superlig",
    ),
    "fashion": (
        "moda", "fashion", "outfit", "ootd", "obleceni", "styl$", "stylu", "style$", "saty", "dress",
        "boty", "shoes", "kabelk", "streetwear", "vintage", "secondhand", "sekac", "kolekce",
    ),
    "beauty": (
        "beauty", "makeup", "make-up", "licen", "kosmetik", "skincare", "pletov", "vlasy", "hair$",
        "nehty", "nails", "parfem", "krasa", "rtenk", "lipstick",
    ),
    "travel": (
        "cestov", "travel", "dovolen", "vacation", "vylet", "trip$", "letadl", "flight", "hotel",
        "more$", "mori$", "beach", "plaz", "hory$", "mountains", "itali", "chorvat", "spanel", "thajsk",
        "bali", "pariz", "paris", "london", "roadtrip", "wanderlust", "letenk",
    ),
    "tech": (
        "tech", "technolog", "iphone", "android", "mobil", "notebook", "laptop", "pocitac", "computer",
        "gadget", "software", "aplikac", "unboxing", "elektronik",
    ),
    "gaming": (
        "gaming", "gamer", "hra$", "hry$", "hrani", "game$", "games", "playstation", "xbox", "nintendo",
        "steam", "twitch", "minecraft", "fortnite", "esport", "stream",
    ),
    "music": (
        "hudba", "hudeb", "music", "pisen", "pisnick", "song$", "koncert", "concert", "kytar", "guitar",
        "rap$", "dj$", "album", "singl", "zpev", "zpiv",
    ),
    "humor": (
        "humor", "vtip", "meme", "sranda", "funny", "lol$", "haha", "parodie", "skec", "comedy", "prank",
    ),
    "education": (
        "uceni", "skola", "school", "kurz", "course", "tutorial", "jak na", "how to", "vzdelav",
        "education", "learn", "vedeli jste", "did you know", "fakta", "vysvetl",
    ),
}

# A stem ending in "$" must be a whole word ("beh$" matches "běh", not "během"); other stems of
# <= 4 chars must start a word; longer stems match anywhere.


def _caption_part(stem: str) -> str:
    if stem.endswith("$"):
        return r"\b" + re.escape(stem[:-1]) + r"\b"
    return (r"\b" + re.escape(stem)) if len(stem) <= 4 else re.escape(stem)


_TOPIC_RE: dict[str, re.Pattern[str]] = {
    topic: re.compile("|".join(_caption_part(s) for s in stems)) for topic, stems in KEYWORD_TOPICS.items()
}
_TAG_STEMS: dict[str, tuple[str, ...]] = {
    topic: tuple(s.rstrip("$").replace(" ", "") for s in stems) for topic, stems in KEYWORD_TOPICS.items()
}


def _tag_hit(stem: str, tag: str) -> bool:
    # Short stems only match a whole hashtag (#bar, #gym); longer ones also inside (#brnofood).
    return tag == stem if len(stem) <= 3 else stem in tag


def _score_post(p: Post) -> dict[str, int]:
    caption = fold(p.caption)
    tags = [fold(h) for h in p.hashtags]
    scores: dict[str, int] = {}
    for topic, rx in _TOPIC_RE.items():
        n = len(rx.findall(caption))
        for t in tags:
            if any(_tag_hit(s, t) for s in _TAG_STEMS[topic]):
                n += 1
        if n:
            scores[topic] = n
    return scores


UNCLASSIFIED = "unclassified"   # not a TOPICS value; excluded from topic_share denominators

# Topics that say WHERE or for whom, not WHAT: they can sit in a topic_share list next to a subject
# ("food, recipes, cafés, local tips") but never carry the share alone. An account that is 70 % local
# tips and 0 % food must fail a food goal; a list of only supporting topics still counts them.
SUPPORTING_TOPICS: frozenset[str] = frozenset({"local_tips"})


def counted_topics(topics: list[str]) -> list[str]:
    """The topics whose posts count toward topic_share: the list without SUPPORTING_TOPICS, unless
    that would leave nothing (then the list as given)."""
    core = [t for t in topics if t not in SUPPORTING_TOPICS]
    return core or list(topics)


def fallback_topic(p: Post) -> str:
    scores = _score_post(p)
    if not scores:
        return UNCLASSIFIED
    best = max(scores.values())
    # Ties: earlier in TOPICS wins (deterministic).
    return next(t for t in TOPICS if scores.get(t) == best)


def fallback_classify(posts: list[Post]) -> dict[str, str]:
    return {p.id: fallback_topic(p) for p in posts}


TopicName = Literal[
    "food", "recipes", "restaurants_cafes", "local_tips", "family", "lifestyle", "fitness", "sport",
    "fashion", "beauty", "travel", "tech", "gaming", "music", "humor", "education", "other",
]


class _Label(BaseModel):
    i: int
    topic: TopicName


class _Labels(BaseModel):
    labels: list[_Label]


def _cache_key(posts: list[Post]) -> str:
    return short_hash("|".join(sorted(p.id for p in posts)), 16)


async def classify(posts: list[Post]) -> dict[str, str]:
    """-> {post_id: topic}, every topic in models.TOPICS, every post id present."""
    if not posts:
        return {}
    if not llm_client.llm_available():
        llm_client.record_mode("topics", "fallback")
        return fallback_classify(posts)

    key = _cache_key(posts)
    cached = llm_client.cache_get("topics", key)
    if isinstance(cached, dict) and all(p.id in cached for p in posts):
        llm_client.record_mode("topics", "llm")
        return {p.id: (cached[p.id] if cached[p.id] in TOPICS else "other") for p in posts}

    lines = []
    for i, p in enumerate(posts):
        tags = " ".join(f"#{h}" for h in p.hashtags[:15])
        cap = clip(p.caption, 500).replace("\n", " ")
        lines.append(f"[{i}] ({p.media_type}) {cap} {tags}".strip())
    user = (
        f"Posts by one creator ({len(posts)}). Label every index 0..{len(posts) - 1} with one topic.\n"
        "<posts>\n" + "\n".join(lines) + "\n</posts>"
    )
    out = await llm_client.structured(
        _Labels, system=prompts.TOPICS_SYSTEM, user=user, max_tokens=4000, effort="low", task="topics"
    )
    if out is None:
        llm_client.record_mode("topics", "fallback")
        return fallback_classify(posts)

    by_i = {lab.i: lab.topic for lab in out.labels if 0 <= lab.i < len(posts)}
    result: dict[str, str] = {}
    missing = False
    for i, p in enumerate(posts):
        t = by_i.get(i)
        if t is None:
            missing = True
            t = fallback_topic(p)
        result[p.id] = t if (t in TOPICS or t == UNCLASSIFIED) else "other"
    llm_client.record_mode("topics", "llm")
    if missing:
        llm_client.record_mode("topics", "fallback")  # -> "mixed"
    else:
        llm_client.cache_put("topics", key, result)
    return result
