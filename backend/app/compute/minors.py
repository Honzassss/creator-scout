"""Minor detection beyond the provider flag (hard line: minors are dropped without storage).

Instagram never exposes an age, so ``Profile.is_under_18`` is usually None on live data. The plan
(brand-fit-cz §10) also requires dropping a creator whose bio states an age under 18. This module
only answers "does the bio state an explicit age under 18?"; it never estimates an age and nothing it
matches is stored (the caller drops the candidate and logs a count).

Patterns are deliberately narrow so "Pečeme už 15 let" / "10 let v oboru" do not drop an adult
baker: an age must stand on its own ("14 let 🎂 | ráda peču", "16yo", "je mi 15", "ročník 2011").
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from app.models import Profile, utcnow

_AGE = r"(?P<n>[1-9]|1[0-7])"
_SEP_BEFORE = r"(?:^|[|•·,;/\n(]\s*)"
_AGE_PATTERNS = (
    # "14 let 🎂 | ráda peču", "15 let, Brno", "13 years old"
    re.compile(_SEP_BEFORE + _AGE + r"\s*(?:let|y\.?o\.?|yo|years? old|yrs? old)(?=\s*(?:$|[|•·,;/\n)!🎂🎉]|a\s|and\s))"),
    re.compile(r"\b" + _AGE + r"\s*(?:yo|y/o)\b"),                        # "16yo", "15 y/o"
    re.compile(r"\bje mi " + _AGE + r"\b(?!\s*(?:tis|k\b|%))"),             # "je mi 15"
    re.compile(r"\b(?:i'?m|i am) " + _AGE + r"(?: years? old| y/?o)?\b"
               r"(?!\s*(?:k\b|%|tis|min|minut|km|followers|minutes?|hours?|days?))"),
    re.compile(r"\b" + _AGE + r"\s*🎂"),                                    # "14 🎂"
)
_BIRTH_YEAR = re.compile(r"\b(?:rocnik|born(?: in)?|narozen[aiy]?|nar\.)\s*(?P<y>(?:19|20)\d\d)\b")


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def bio_states_minor(bio: str | None, now: datetime | None = None) -> bool:
    """True when the bio states an explicit age under 18 (or a birth year that implies one)."""
    text = _fold(bio or "")
    if not text.strip():
        return False
    for rx in _AGE_PATTERNS:
        if rx.search(text):
            return True
    m = _BIRTH_YEAR.search(text)
    if m:
        year = int(m.group("y"))
        if year > (now or utcnow()).year - 18:
            return True
    return False


def is_minor(profile: Profile, now: datetime | None = None) -> bool:
    """Provider flag OR an explicit under-18 age in the bio."""
    return bool(profile.is_under_18) or bio_states_minor(profile.bio, now)
