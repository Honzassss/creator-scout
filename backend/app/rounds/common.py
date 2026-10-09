"""Shared helpers for the round modules and the engine: bilingual outcomes, number / date
formatting (cs + en), logging into run.log, fetched-object mode counting, safe store saves.

Every round module exposes ``assess(criterion, candidate, brief, now) -> Outcome`` (pure) next to the
contract's ``evaluate(...) -> CriterionResult``. ``Outcome`` keeps both languages so the engine can
build an ``Elimination.reason`` in cs and en, while ``CriterionResult.value`` / ``threshold`` are
single strings in ``brief.lang``.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.events import Emit
from app.models import (
    CRITERION_DEFAULT_PARAMS,
    Candidate,
    Criterion,
    CriterionResult,
    Elimination,
    Post,
    Run,
    SourceRef,
    i18n,
    utcnow,
)

logger = logging.getLogger("creator_scout.rounds")

Status = Literal["pass", "fail", "unknown"]


@dataclass
class Outcome:
    status: Status
    value: dict[str, str]
    threshold: dict[str, str]
    sources: list[SourceRef] = field(default_factory=list)
    reason: dict[str, str] | None = None   # elimination phrase, e.g. "jen 2 z 24 postů je o jídle"

    def result(self, criterion_id: str, lang: str = "cs") -> CriterionResult:
        lang = lang if lang in ("cs", "en") else "cs"
        return CriterionResult(
            criterion_id=criterion_id,
            status=self.status,
            value=self.value.get(lang) or self.value.get("cs", ""),
            threshold=self.threshold.get(lang) or self.threshold.get("cs", ""),
            sources=dedupe_refs(self.sources),
        )


def param(criterion: Criterion, key: str) -> Any:
    """criterion.params[key], else the CRITERION_DEFAULT_PARAMS default. An explicit None is kept
    (e.g. followers_range {"max": None} = no upper bound)."""
    params = criterion.params if isinstance(criterion.params, dict) else {}
    if key in params:
        return params[key]
    return CRITERION_DEFAULT_PARAMS.get(criterion.kind, {}).get(key)


def unknown(cs: str, en: str, threshold: dict[str, str], sources: list[SourceRef] | None = None) -> Outcome:
    return Outcome("unknown", i18n(cs, en), threshold, list(sources or []))


def elimination_for(round_no: int, criterion: Criterion, outcome: Outcome) -> Elimination:
    """'Kolo 2: jen 2 z 24 postů je o jídle (kritérium aspoň 40 %)' in cs and en."""
    phrase = outcome.reason or outcome.value
    return Elimination(
        round=round_no,
        criterion_id=criterion.id,
        reason=i18n(
            f"Kolo {round_no}: {phrase['cs']} (kritérium {outcome.threshold['cs']})",
            f"Round {round_no}: {phrase['en']} (criterion: {outcome.threshold['en']})",
        ),
        sources=dedupe_refs(outcome.sources),
    )


# ---------------------------------------------------------------------------------------------
# Formatting (cs uses a no-break space as thousands separator and before %, decimal comma)
# ---------------------------------------------------------------------------------------------

NBSP = " "


def fmt_int(n: int | float, lang: str) -> str:
    n = int(round(n))
    s = f"{n:,}"
    return s.replace(",", NBSP) if lang == "cs" else s


def fmt_num(x: float, lang: str, digits: int = 1) -> str:
    if abs(x - round(x)) < 0.05 and digits <= 1:
        return fmt_int(x, lang)
    s = f"{x:.{digits}f}"
    return s.replace(".", ",") if lang == "cs" else s


def fmt_pct(x: float, lang: str, digits: int | None = None) -> str:
    """0.4 -> '40 %' (cs) / '40%' (en). Small values get one decimal ('1,2 %')."""
    v = x * 100.0
    if digits is None:
        digits = 1 if (v < 10 and abs(v - round(v)) >= 0.05) else 0
    s = f"{v:.{digits}f}"
    if lang == "cs":
        return s.replace(".", ",") + NBSP + "%"
    return s + "%"


def fmt_k(n: int | float, lang: str) -> str:
    """5000 -> '5 tis.' / '5k'; 1_200_000 -> '1,2 mil.' / '1.2M'."""
    if n >= 1_000_000:
        return f"{fmt_num(n / 1_000_000, lang)}{NBSP}mil." if lang == "cs" else f"{fmt_num(n / 1_000_000, lang)}M"
    if n >= 1000:
        return f"{fmt_num(n / 1000, lang)}{NBSP}tis." if lang == "cs" else f"{fmt_num(n / 1000, lang)}k"
    return fmt_int(n, lang)


def fmt_k_range(lo: int | float, hi: int | float, lang: str) -> str:
    """5000, 50000 -> '5–50 tis.' / '5k–50k'."""
    if lang == "cs" and 1000 <= lo < 1_000_000 and 1000 <= hi < 1_000_000:
        return f"{fmt_num(lo / 1000, lang)}–{fmt_num(hi / 1000, lang)}{NBSP}tis."
    return f"{fmt_k(lo, lang)}–{fmt_k(hi, lang)}"


LANG_NAMES_CS = {"cs": "čeština", "sk": "slovenština", "en": "angličtina", "de": "němčina", "pl": "polština",
                 "uk": "ukrajinština"}
LANG_NAMES_EN = {"cs": "Czech", "sk": "Slovak", "en": "English", "de": "German", "pl": "Polish", "uk": "Ukrainian"}


def fmt_date(d: datetime | None, lang: str) -> str:
    if d is None:
        return "?"
    if lang == "cs":
        return f"{d.day}.{NBSP}{d.month}.{NBSP}{d.year}"
    return f"{d.day} {d.strftime('%b')} {d.year}"


def cs_plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def cs_posts_gen(n: int) -> str:
    """Genitive after 'z N': 'z 1 postu', 'z 24 postů'."""
    return "postu" if n == 1 else "postů"


def en_plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def cs_days_ago(days: int) -> str:
    if days <= 0:
        return "dnes"
    if days == 1:
        return "včera"
    return f"před {days} dny"


def en_days_ago(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def join_cs(items: list[str], last: str = "nebo") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def join_en(items: list[str], last: str = "or") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


TOPIC_CS_LOC: dict[str, str] = {   # "o ..." (locative)
    "food": "jídle", "recipes": "receptech", "restaurants_cafes": "restauracích a kavárnách",
    "local_tips": "lokálních tipech", "family": "rodině", "lifestyle": "lifestylu", "fitness": "fitness",
    "sport": "sportu", "fashion": "módě", "beauty": "kosmetice a kráse", "travel": "cestování",
    "tech": "technologiích", "gaming": "hrách", "music": "hudbě", "humor": "humoru",
    "education": "vzdělávání", "other": "jiných tématech",
}
TOPIC_EN: dict[str, str] = {
    "food": "food", "recipes": "recipes", "restaurants_cafes": "restaurants and cafes", "local_tips": "local tips",
    "family": "family", "lifestyle": "lifestyle", "fitness": "fitness", "sport": "sport", "fashion": "fashion",
    "beauty": "beauty", "travel": "travel", "tech": "tech", "gaming": "gaming", "music": "music",
    "humor": "humor", "education": "education", "other": "other topics",
}
FORMAT_CS: dict[str, str] = {"reel": "reels", "video": "videa", "photo": "fotky", "carousel": "karusely", "other": "jiné"}
FORMAT_EN: dict[str, str] = {"reel": "reels", "video": "videos", "photo": "photos", "carousel": "carousels", "other": "other"}


def lang_of(run: Run) -> str:
    try:
        return run.criteria.brief.lang
    except Exception:
        return "cs"


def tr(run: Run, cs: str, en: str) -> str:
    return en if lang_of(run) == "en" else cs


# ---------------------------------------------------------------------------------------------
# Posts / sources helpers
# ---------------------------------------------------------------------------------------------

def posts_of(candidate: Candidate) -> list[Post]:
    return list(candidate.profile.latest_posts) if candidate.profile else []


def newest_first(posts: Iterable[Post]) -> list[Post]:
    return sorted(posts, key=lambda p: p.created_at, reverse=True)


def _caption_excerpt(caption: str, n: int = 140) -> str | None:
    """The caption's start, cut at a word boundary with an ellipsis (never mid-word, never "...ře”")."""
    t = " ".join((caption or "").split())
    if not t:
        return None
    if len(t) <= n:
        return t
    cut = t[: n - 1]
    sp = cut.rfind(" ")
    if sp > n // 2:
        cut = cut[:sp]
    return cut.rstrip(" ,;:—-") + "…"


def post_ref(post: Post, quote: str | None = None) -> SourceRef:
    q = quote if quote is not None else _caption_excerpt(post.caption or "")
    return post.source.model_copy(update={"quote": q})


def profile_refs(candidate: Candidate) -> list[SourceRef]:
    return [candidate.profile.source] if candidate.profile else [candidate.ref.source]


def dedupe_refs(refs: Iterable[SourceRef], limit: int | None = None) -> list[SourceRef]:
    out: list[SourceRef] = []
    seen: set[str] = set()
    for r in refs:
        key = f"{r.id}|{r.url}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if limit is not None and len(out) >= limit:
            break
    return out


def city_for(run: Run, criterion_params: dict | None = None) -> str | None:
    if criterion_params and criterion_params.get("city"):
        return str(criterion_params["city"])
    brief_city = run.criteria.brief.city
    if brief_city:
        return brief_city
    return run.criteria.discovery.city


def brief_city(brief: Any, discovery: Any | None = None) -> str | None:
    return getattr(brief, "city", None) or (getattr(discovery, "city", None) if discovery is not None else None)


# ---------------------------------------------------------------------------------------------
# Run bookkeeping: log, modes, save
# ---------------------------------------------------------------------------------------------

def _log_entry(text: str, actor: str | None, mode: str | None, ts: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"ts": ts or utcnow().isoformat(), "text": text}
    if actor:
        entry["actor"] = actor
    if mode:
        entry["mode"] = mode
    return entry


async def log(run: Run, emit: Emit, text: str, *, actor: str | None = None, mode: str | None = None) -> None:
    """Append to run.log and emit a ``log`` event. Never raises."""
    entry = _log_entry(text, actor, mode)
    run.log.append(entry)
    try:
        await emit("log", {"text": text, "actor": actor, "mode": mode, "ts": entry["ts"]})
    except Exception:  # pragma: no cover - logging must not break the funnel
        logger.exception("emit log failed")


def recording_emit(run: Run, emit: Emit) -> Emit:
    """Emit wrapper that also records ``log`` events (e.g. from providers via emit_log) in run.log."""

    async def rec(event: str, data: dict) -> None:
        if event == "log" and isinstance(data, dict):
            run.log.append(_log_entry(str(data.get("text", "")), data.get("actor"), data.get("mode"), data.get("ts")))
        await emit(event, data)

    return rec


def count_modes(run: Run, objs: Iterable[Any]) -> Counter[str]:
    """Add the source modes of freshly fetched objects to run.mode_summary; returns this batch."""
    c: Counter[str] = Counter()
    for o in objs:
        src = getattr(o, "source", None)
        mode = getattr(src, "mode", None)
        if mode:
            c[mode] += 1
    for mode, n in c.items():
        run.mode_summary[mode] = run.mode_summary.get(mode, 0) + n
    return c


def describe_modes(c: Counter[str]) -> tuple[str | None, str]:
    """(dominant mode, ' (cache 40, live 8)' suffix when mixed)."""
    if not c:
        return None, ""
    dominant = c.most_common(1)[0][0]
    if len(c) == 1:
        return dominant, ""
    return dominant, " (" + ", ".join(f"{m} {n}" for m, n in c.most_common()) + ")"


def actor_of(objs: Iterable[Any], default: str | None = None) -> str | None:
    for o in objs:
        src = getattr(o, "source", None)
        if src is not None and getattr(src, "actor", None):
            return src.actor
    return default


async def add_sensitive(run: Run, candidate: Candidate, emit: Emit, dropped: int) -> None:
    """Count-only bookkeeping for the sensitive filter; emits sensitive.filtered when > 0.
    Payload: {"candidate_id", "count": dropped now, "total": candidate total}."""
    if dropped <= 0:
        return
    candidate.sensitive_filtered += dropped
    try:
        await emit("sensitive.filtered", {"candidate_id": candidate.id, "count": dropped,
                                          "total": candidate.sensitive_filtered})
    except Exception:  # pragma: no cover
        logger.exception("emit sensitive.filtered failed")


def save_run(run: Run) -> None:
    """Persist via the store when it is available; never raises into the funnel."""
    try:
        from app.store import get_store

        get_store().save(run)
    except NotImplementedError:
        pass
    except Exception:  # pragma: no cover - persistence problems must not stop the funnel
        logger.exception("saving run %s failed", run.id)


def llm_actor(run: Any, task: str) -> str:
    """Log actor for an LLM-backed step that may have run on rules: "llm:topics", "rules:topics" or
    "llm+rules:topics" from run.llm_modes, so a keyless run never shows "llm:" on a rule step."""
    mode = (getattr(run, "llm_modes", None) or {}).get(task)
    prefix = {"llm": "llm", "fallback": "rules", "mixed": "llm+rules"}.get(str(mode or ""), "rules")
    return f"{prefix}:{task}"

