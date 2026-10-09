"""Small text helpers shared by the LLM layer (deterministic, no I/O)."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def fold(text: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace: "Věřící  Tvůrci" -> "verici tvurci"."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return _WS.sub(" ", t.lower()).strip()


def compile_patterns(patterns: list[str] | tuple[str, ...]) -> re.Pattern[str]:
    """One alternation regex over folded text (patterns are written for folded text)."""
    return re.compile("|".join(f"(?:{p})" for p in patterns))


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def fmt_date(dt, lang: str = "cs") -> str:
    if dt is None:
        return "?" if lang == "cs" else "?"
    return f"{dt.day}. {dt.month}. {dt.year}" if lang == "cs" else dt.strftime("%Y-%m-%d")


def fmt_int(n: int | float | None, lang: str = "cs") -> str:
    if n is None:
        return "?"
    s = f"{int(round(n)):,}"
    return s.replace(",", " ") if lang == "cs" else s


def fmt_pct(x: float | None, lang: str = "cs") -> str:
    if x is None:
        return "?"
    v = round(x * 100, 1)
    s = f"{v:g}"
    return (s.replace(".", ",") + " %") if lang == "cs" else s + "%"


# Plain-language topic names (TOPICS keys) for chat and drafts.
TOPIC_LABELS: dict[str, dict[str, str]] = {
    "food": {"cs": "jídlo", "en": "food"},
    "recipes": {"cs": "recepty", "en": "recipes"},
    "restaurants_cafes": {"cs": "kavárny a restaurace", "en": "cafés and restaurants"},
    "local_tips": {"cs": "tipy ve městě", "en": "local tips"},
    "family": {"cs": "rodina", "en": "family"},
    "lifestyle": {"cs": "životní styl", "en": "lifestyle"},
    "fitness": {"cs": "fitness", "en": "fitness"},
    "sport": {"cs": "sport", "en": "sport"},
    "fashion": {"cs": "móda", "en": "fashion"},
    "beauty": {"cs": "krása a kosmetika", "en": "beauty"},
    "travel": {"cs": "cestování", "en": "travel"},
    "tech": {"cs": "technologie", "en": "tech"},
    "gaming": {"cs": "hry", "en": "gaming"},
    "music": {"cs": "hudba", "en": "music"},
    "humor": {"cs": "humor", "en": "humour"},
    "education": {"cs": "vzdělávání", "en": "education"},
    "other": {"cs": "ostatní", "en": "other"},
}

# "o čem tvoří" (Czech locative) for drafts.
TOPIC_ABOUT_CS: dict[str, str] = {
    "food": "o jídle", "recipes": "o receptech", "restaurants_cafes": "o kavárnách a restauracích",
    "local_tips": "o místech ve městě", "family": "o rodině", "lifestyle": "o životním stylu",
    "fitness": "o cvičení", "sport": "o sportu", "fashion": "o módě", "beauty": "o kosmetice",
    "travel": "o cestování", "tech": "o technologiích", "gaming": "o hrách", "music": "o hudbě",
    "humor": "s humorem", "education": "o tom, jak věci fungují",
}

FORMAT_LABELS: dict[str, dict[str, str]] = {
    "reel": {"cs": "krátká videa", "en": "short videos"},
    "video": {"cs": "videa", "en": "videos"},   # no duration is fetched: never "longer"
    "photo": {"cs": "fotky", "en": "photos"},
    "carousel": {"cs": "série fotek", "en": "carousels"},
    "other": {"cs": "jiné formáty", "en": "other formats"},
}

_CS_LOCATIVE = {
    "brno": "v Brně", "praha": "v Praze", "ostrava": "v Ostravě", "plzen": "v Plzni",
    "olomouc": "v Olomouci", "liberec": "v Liberci", "zlin": "ve Zlíně", "pardubice": "v Pardubicích",
    "jihlava": "v Jihlavě", "hradec kralove": "v Hradci Králové", "ceske budejovice": "v Českých Budějovicích",
    "usti nad labem": "v Ústí nad Labem", "opava": "v Opavě", "kladno": "v Kladně", "karlovy vary": "v Karlových Varech",
}

# Known Czech city forms (folded) -> canonical name, for parsing owner answers.
CITY_FORMS: dict[str, str] = {
    "brno": "Brno", "brne": "Brno", "brna": "Brno", "praha": "Praha", "praze": "Praha", "prahy": "Praha",
    "prague": "Praha", "ostrava": "Ostrava", "ostrave": "Ostrava", "ostravy": "Ostrava", "plzen": "Plzeň",
    "plzni": "Plzeň", "olomouc": "Olomouc", "olomouci": "Olomouc", "liberec": "Liberec", "liberci": "Liberec",
    "zlin": "Zlín", "zline": "Zlín", "pardubice": "Pardubice", "pardubicich": "Pardubice", "jihlava": "Jihlava",
    "jihlave": "Jihlava", "opava": "Opava", "opave": "Opava", "kladno": "Kladno", "kladne": "Kladno",
}


def cs_locative(city: str | None) -> str:
    if not city:
        return ""
    return _CS_LOCATIVE.get(fold(city), f"ve městě {city}")


def find_city(text: str) -> str | None:
    import re as _re

    for tok in _re.findall(r"[a-z]+", fold(text)):
        if tok in CITY_FORMS:
            return CITY_FORMS[tok]
    return None


BUSINESS_EN: dict[str, str] = {
    "pekarna": "bakery", "cukrarna": "pastry shop", "kavarna": "café", "restaurace": "restaurant",
    "bistro": "bistro", "fitness studio": "fitness studio", "posilovna": "gym", "fitness": "fitness studio",
    "kadernictvi": "hair salon", "kvetinarstvi": "flower shop", "knihkupectvi": "bookshop",
}


def business_en(business_type: str) -> str:
    f = fold(business_type)
    for k, v in BUSINESS_EN.items():
        if k in f:
            return v
    return business_type
