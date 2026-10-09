"""Language detection (lingua-language-detector) and generic / emoji-only comment detection.

The lingua detector is built once (lazily) and restricted to cs, sk, en, de, pl, uk: the languages
that realistically show up under Czech creators' posts. Restricting the set makes detection fast and
keeps Czech vs. Slovak apart. URLs, @mentions, #hashtags and emoji are stripped first; texts with
fewer than 2 words / 8 letters, or a top confidence under 0.4, return None (too short to tell). A diacritics rule corrects Czech vs.
Slovak on short texts (ř/ů/ě only exist in Czech; ä/ô/ľ/ĺ/ŕ only in Slovak); diacritics-free text that
lingua calls Slovak counts as Czech when its Czech confidence is still >= 0.3.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

_LANG_CODES = ("cs", "sk", "en", "de", "pl", "uk")
_MIN_LETTERS = 8
_MIN_WORDS = 2
_MIN_CONFIDENCE = 0.4   # below this the text is ambiguous (e.g. "to je super" cs/sk/en)
_CS_ASCII_MIN = 0.3     # Czech confidence that wins over "sk" for diacritics-free text

_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
_TAG_RE = re.compile(r"[@#][\w.\-]+", re.UNICODE)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

_CS_ONLY = set("řůěŘŮĚ")
_SK_ONLY = set("äôľĺŕÄÔĽĹŔ")

_detector: Any = None


def _get_detector() -> Any:
    global _detector
    if _detector is None:
        from lingua import Language, LanguageDetectorBuilder

        _detector = LanguageDetectorBuilder.from_languages(
            Language.CZECH, Language.SLOVAK, Language.ENGLISH,
            Language.GERMAN, Language.POLISH, Language.UKRAINIAN,
        ).build()
    return _detector


def _clean(text: str) -> str:
    text = _URL_RE.sub(" ", text or "")
    text = _TAG_RE.sub(" ", text)
    return " ".join(_WORD_RE.findall(text))


@lru_cache(maxsize=50_000)
def detect_language(text: str) -> str | None:
    """ISO 639-1 code ("cs", "en", ...) or None if too short / not confident."""
    cleaned = _clean(text)
    words = cleaned.split()
    if len(words) < _MIN_WORDS or sum(len(w) for w in words) < _MIN_LETTERS:
        return None
    detector = _get_detector()
    try:
        values = detector.compute_language_confidence_values(cleaned)
    except Exception:
        return None
    if not values or values[0].value < _MIN_CONFIDENCE:
        return None
    code = values[0].language.iso_code_639_1.name.lower()
    if code not in _LANG_CODES:
        return None
    chars = set(cleaned)
    has_cs, has_sk = bool(chars & _CS_ONLY), bool(chars & _SK_ONLY)
    if code == "sk" and has_cs and not has_sk:
        return "cs"
    if code == "cs" and has_sk and not has_cs:
        return "sk"
    if code == "sk" and not has_sk and cleaned.isascii():
        # Czech typed without diacritics ("Diky za tip, urcite zajdu") looks Slovak to lingua; real
        # Slovak without diacritics keeps a low Czech confidence (<= ~0.22), Czech stays >= ~0.3.
        cs_conf = next((v.value for v in values if v.language.iso_code_639_1.name.lower() == "cs"), 0.0)
        if cs_conf >= _CS_ASCII_MIN:
            return "cs"
    return code


def language_share(texts: list[str], lang: str = "cs", min_texts: int = 1) -> float | None:
    """Share of texts detected as ``lang`` among texts with a detected language.
    None when fewer than ``min_texts`` texts have a detected language.
    language_cs criterion: language_share(captions, "cs", min_texts=3)."""
    detected = [d for d in (detect_language(t) for t in texts if t) if d is not None]
    if len(detected) < max(1, min_texts):
        return None
    return sum(1 for d in detected if d == lang) / len(detected)


def language_counts(texts: list[str]) -> tuple[int, int]:
    """(texts detected as Czech, texts with any detected language). For readable value strings."""
    detected = [d for d in (detect_language(t) for t in texts if t) if d is not None]
    return sum(1 for d in detected if d == "cs"), len(detected)


# ---------------------------------------------------------------------------------------------
# Generic / emoji-only comments
# ---------------------------------------------------------------------------------------------

_IGNORABLE_CATS = {"So", "Sk", "Mn", "Me", "Cf", "Po", "Pd", "Ps", "Pe", "Pi", "Pf", "Sm", "Zs"}


def is_emoji_only(text: str) -> bool:
    """True when the text has at least one emoji / pictograph and nothing else but punctuation."""
    if not text or not text.strip():
        return False
    has_symbol = False
    for ch in text:
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat == "So":
            has_symbol = True
        elif cat in _IGNORABLE_CATS or ch in "‍️":
            continue
        else:
            return False
    return has_symbol


def _strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


_GENERIC_WORDS = frozenset("""
super suprove supr wow waw nice krasa krasne krasny krasna krasota top topovka cool love loveit lovely
amazing awesome great beautiful perfect perfektni perfektne bomba bombovy bombove paradni parada mnam
mnamka mnamky mnami mnamina skvele skvely skvela uzasne uzasny uzasna boze joo jo ano yes yess omg lol
haha hahaha hehe hezky hezke hezka pekne peknej dekuji dekuju diky dik thanks thank thx cute wonderful
gorgeous fire lit goals yummy yum delicious tasty fajn wau wauu bravo brava gratuluji gratulace
congrats nadhera nadherne nadherny nadherna luxus luxusni boss queen king stunning pretty sweet
miluju ok oki okay dobry dobre dobra wooow cudo cudne fantasticke fantastic fab legend
legendarni respekt respect insane epic wild sick slay geil toll lecker ladne
""".split())

_FILLER_WORDS = frozenset("""
so very moc fakt to je this it is the a jsi you are uplne hrozne tak really such post pic photo foto
fotka fotky picture video videjko reel looks look vypada vypadaji jak how what co and i me my muj moje
too taky tez also omg ty vole jeee jej ach oh ah wow just simply proste naprosto totalne totally
absolutely most best nej nejvic hodne mega ultra hyper extra
""".split())

_REPEAT_RE = re.compile(r"(.)\1{2,}")


def _generic_words(text: str) -> list[str]:
    t = _strip_diacritics(text.lower())
    t = _URL_RE.sub(" ", t)
    t = _REPEAT_RE.sub(r"\1", t)
    return _WORD_RE.findall(t)


def is_generic_comment(text: str) -> bool:
    """Emoji-only, or a short generic phrase ("super", "wow", "nice", "krása", "❤️ top") with no
    specific content (cs + en lists)."""
    if not text or not text.strip():
        return False
    if is_emoji_only(text):
        return True
    if _TAG_RE.sub("", text).strip() == "":   # only @mentions / #tags (tagging friends)
        return True
    words = _generic_words(_TAG_RE.sub(" ", text))
    if not words or len(words) > 5:
        return False
    if not any(w in _GENERIC_WORDS for w in words):
        return False
    return all(w in _GENERIC_WORDS or w in _FILLER_WORDS for w in words)


def generic_share(texts: list[str]) -> float | None:
    """Share of generic comments; None if no texts."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return None
    return sum(1 for t in texts if is_generic_comment(t)) / len(texts)
