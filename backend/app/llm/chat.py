"""Chatbot with tools (architecture.md section 6).

Live: get_settings().model_chat, streamed (``client.messages.stream``), system prompt
prompts.CHAT_SYSTEM, tools TOOLS (eager input streaming; every input is validated here). Tools map
1:1 to ChatContext callbacks, which the API layer implements.

Live over OpenRouter (LLM_PROVIDER=openrouter): the same system prompt, tools (as OpenAI function
tools), guards and MAX_TOOL_STEPS, via streamed chat/completions (``openrouter.stream_chat``). The
history stays in Anthropic Messages format and is translated per request; ``done`` also carries
``llm_model`` (the model OpenRouter actually routed to).

Server-side guards (code, not only prompt):
- ``validate_criteria``: only whitelisted CriterionKind values become criteria; unknown kinds and
  sensitive / scoring labels become ``Refused``; params are filtered to the keys each kind reads.
- ``sensitive.refusal_reason`` runs on every owner message BEFORE the model sees it. A sensitive
  request is answered with a deterministic refusal sentence, recorded as ``Refused`` (now, or when
  criteria are next proposed), and the model gets an operator note not to build a criterion for it.
- ``start_deep_vetting`` (round 4) only runs after the owner confirmed in the current message.
- No tool can send anything; outreach is a draft.

``chat_events(message, ctx)`` is the same turn as an async generator of (event, data).

Emits on ``emit``: chat.delta {"text"} for streamed text, chat.tool {"name", "input", "result"} per
tool call, criteria.updated {"criteria"} whenever criteria change, done {"llm_mode", "lang"} at the end
(``llm_mode`` "llm" or "fallback"; ``lang`` the session's effective language, which the UI follows).

Fallback (no key or API failure before anything was shown): ``fallback_turn``, a deterministic,
history-driven state machine (interview -> fixtures/briefs.json or app.presets bakery / fitness by
keywords, else a generic template -> run -> "Prověřit N finalistů do hloubky?" -> vetting; plus
"změnit cíl", "proč vypadl X?", outreach drafts, small criterion edits and the same refusals).
record_mode("chat", ...).

For the API layer: ``criteria_for_brief(brief)`` gives the deterministic CriteriaSet for a brief
(used by fallback goal changes; POST /goal can use it too).

Subject mode (docs/subject-mode.md section 8): the owner names ONE creator (@handle or an
Instagram / TikTok profile link). Live and fallback then skip the discovery interview, ask only for
what is missing (an anchor: city, website or company ID; and the goal), one question per turn, and
call ``research_subject``. On a subject run a goal switch ("what about my fitness studio?") calls
``change_goal`` and the reply summarises ``report_diffs``.

Language: the effective language of a session is the language of the owner's FIRST message when it
is detected confidently, else the UI ``lang``. ``ctx.lang`` is set to it at the start of every turn
(before any tool runs) and ``done`` carries it as ``lang``. The fallback is a complete scripted
interview in both languages.

LLM budget (``app.llm.budget``, optional at import time): the OpenRouter chat runs only when the
"chat" task group is enabled; every Anthropic stream spends one request first and a
``BudgetExhausted`` is handled like an OpenRouter failure (fallback if nothing was shown yet).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_core import to_jsonable_python

from app.config import get_settings
from app.events import Emit
from app.llm import budget as llm_budget
from app.llm import client as llm_client
from app.llm import openrouter, prompts
from app.llm import topics as topics_mod
from app.llm.sensitive import UNSUPPORTED_REASON, any_refusal, refusal_reason, sanitize_brief
from app.llm.text import (
    CITY_FORMS, FORMAT_LABELS, TOPIC_LABELS, clip, cs_locative, find_city, fmt_int, fmt_pct, fold,
)
from app.presets import preset_brief
from app.models import (
    CRITERION_DEFAULT_LABELS, CRITERION_DEFAULT_PARAMS, CRITERION_KINDS, TOPICS, Brief, Candidate, CriteriaSet, Criterion,
    DiscoveryQuery, Lang, Refused, Run, i18n, make_criterion, norm_handle,
)


class ChatContext(Protocol):
    """Provided by the API layer per chat request. Every tool callback returns a JSON-able dict that
    is passed back to the model as the tool result (and shown in chat.tool)."""

    lang: Lang
    history: list[dict]   # Anthropic Messages-format history; chat_turn appends to it in place

    def current_run(self) -> Run | None: ...
    def current_criteria(self) -> CriteriaSet | None: ...

    async def propose_criteria(self, criteria: CriteriaSet) -> dict: ...
    async def update_criterion(self, criterion_id: str, params: dict | None = None, enabled: bool | None = None) -> dict: ...
    async def run_rounds(self, up_to: int) -> dict: ...
    async def explain_elimination(self, candidate_id: str) -> dict: ...
    async def start_deep_vetting(self, candidate_ids: list[str]) -> dict: ...
    async def change_goal(self, brief: Brief) -> dict: ...
    async def draft_outreach(self, candidate_id: str) -> dict: ...
    async def research_subject(self, subject: str, anchor: dict | None = None, brief: Brief | None = None,
                               preset: str | None = None) -> dict: ...


MAX_FINALISTS = 5          # mirrors rounds.r4_vetting.MAX_FINALISTS
MAX_TOOL_STEPS = 8
MEDIA_TYPES = ("photo", "video", "reel", "carousel", "other")
ROUND_NAMES = {
    1: i18n("základ", "basics"), 2: i18n("obsah", "content"),
    3: i18n("publikum", "audience"), 4: i18n("hloubková prověrka", "deep vetting"),
}


def _t(lang: str, cs: str, en: str) -> str:
    return cs if lang == "cs" else en


# --------------------------------------------------------------------------------------------
# Tool definitions
# --------------------------------------------------------------------------------------------

_I18N_SCHEMA = {
    "type": "object",
    "properties": {"cs": {"type": "string"}, "en": {"type": "string"}},
    "required": ["cs", "en"],
    "additionalProperties": False,
}
_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "business_type": {"type": "string", "description": "What the owner sells, e.g. 'pekárna'."},
        "city": {"type": ["string", "null"]},
        "audience": {"type": "string", "description": "Owner's own words. Never used to infer demographics."},
        "goal": {"type": "string", "description": "What the campaign should achieve, owner's words."},
        "budget_hint": {"type": ["string", "null"]},
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "handles": {"type": "array", "items": {"type": "string"}}},
                "required": ["name", "handles"],
                "additionalProperties": False,
            },
        },
        "lang": {"type": "string", "enum": ["cs", "en"]},
    },
    "required": ["business_type", "city", "audience", "goal", "budget_hint", "competitors", "lang"],
    "additionalProperties": False,
}
_PARAMS_SCHEMA = {
    "type": "object",
    "description": "Only the keys the criterion kind reads (see the system prompt). Shares and rates are fractions 0..1.",
    "properties": {
        "min": {"type": ["integer", "null"]}, "max": {"type": ["integer", "null"]},
        "days": {"type": "integer"}, "min_share": {"type": "number"}, "max_share": {"type": "number"},
        "topics": {"type": "array", "items": {"type": "string", "enum": list(TOPICS)}},
        "formats": {"type": "array", "items": {"type": "string", "enum": list(MEDIA_TYPES)}},
        "min_per_week": {"type": "number"}, "min_rate": {"type": "number"}, "city": {"type": "string"},
        "min_count": {"type": "integer"}, "max_undisclosed": {"type": "integer"},
    },
    "additionalProperties": False,
}
_CRITERION_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(CRITERION_KINDS)},
        "params": _PARAMS_SCHEMA,
        "label": _I18N_SCHEMA,
        "why": _I18N_SCHEMA,
        "enabled": {"type": "boolean"},
    },
    "required": ["kind", "params", "label", "why"],
    "additionalProperties": False,
}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "propose_criteria",
        "Propose (or replace) the full set of criteria after the interview. Use only the listed criterion kinds; "
        "anything else, and any request about protected traits or an overall score, goes into `refused`. "
        "The server validates everything and returns what was accepted and what was refused.",
        {
            "brief": _BRIEF_SCHEMA,
            "criteria": {"type": "array", "items": _CRITERION_SCHEMA},
            "refused": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "reason": _I18N_SCHEMA},
                    "required": ["text", "reason"],
                    "additionalProperties": False,
                },
            },
            "discovery": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "places": {"type": "array", "items": {"type": "string"}},
                    "city": {"type": ["string", "null"]},
                },
                "required": ["keywords", "hashtags", "places", "city"],
                "additionalProperties": False,
            },
        },
        ["brief", "criteria", "refused"],
    ),
    _tool(
        "update_criterion",
        "Change one existing criterion: new params (only keys that kind reads) and/or enable/disable it.",
        {
            "criterion_id": {"type": "string"},
            "params": _PARAMS_SCHEMA,
            "enabled": {"type": "boolean"},
        },
        ["criterion_id"],
    ),
    _tool(
        "run_rounds",
        "Run the funnel up to the given round (0 discovery, 1 basics, 2 content, 3 audience). Round 4 is NOT "
        "run here; use start_deep_vetting after the owner confirms. Returns a summary with finalists.",
        {"up_to": {"type": "integer", "enum": [0, 1, 2, 3]}},
        ["up_to"],
    ),
    _tool(
        "explain_elimination",
        "Explain why a candidate was eliminated (round, criterion, reason, source). Accepts the candidate id "
        "('instagram:handle') or the @handle.",
        {"candidate_id": {"type": "string"}},
        ["candidate_id"],
    ),
    _tool(
        "start_deep_vetting",
        "Round 4 deep vetting of finalists (max 5). ONLY after the owner explicitly said yes to your question "
        "'Prověřit N finalistů do hloubky?'.",
        {"candidate_ids": {"type": "array", "items": {"type": "string"}}},
        ["candidate_ids"],
    ),
    _tool(
        "change_goal",
        "Switch to a different business or campaign goal. The same candidates are re-evaluated with criteria "
        "for the new brief and the board shows who dropped or returned and why. On a subject run (one creator "
        "checked with research_subject) the report is re-ordered and rewritten for the new goal from the data "
        "already fetched; the result carries report_diffs to summarise.",
        {"brief": _BRIEF_SCHEMA},
        ["brief"],
    ),
    _tool(
        "draft_outreach",
        "Write a first-contact DRAFT for a finalist. It is never sent; the owner can only copy it.",
        {"candidate_id": {"type": "string"}},
        ["candidate_id"],
    ),
    _tool(
        "research_subject",
        "Check ONE specific creator the owner named (an @handle or an Instagram/TikTok profile link) for the owner's "
        "goal. Fetches the public profile, posts, comments, other-platform accounts, collaborations and news, runs "
        "the goal's criteria as checks (nothing is eliminated, no score) and builds a sourced report. Before calling, "
        "get what is missing and nothing else: an anchor (city where the creator is based, their website, or a "
        "company ID such as the Czech IČO) and the goal (business type, city, what they want).",
        {
            "subject": {"type": "string", "description": "@handle or profile URL exactly as the owner wrote it"},
            "anchor": {
                "type": "object",
                "properties": {"city": {"type": "string"}, "website": {"type": "string"}, "company_id": {"type": "string"}},
                "additionalProperties": False,
            },
            "brief": _BRIEF_SCHEMA,
            "preset": {"type": "string", "enum": ["bakery", "fitness"]},
        },
        ["subject", "brief"],
    ),
]


# --------------------------------------------------------------------------------------------
# Validation (whitelist) helpers
# --------------------------------------------------------------------------------------------


def _i18n_or(v: Any) -> dict[str, str] | None:
    if isinstance(v, dict):
        cs, en = str(v.get("cs") or "").strip(), str(v.get("en") or "").strip()
        if cs or en:
            return i18n(clip(cs or en, 300), clip(en or cs, 300))
    if isinstance(v, str) and v.strip():
        return i18n(clip(v.strip(), 300), clip(v.strip(), 300))
    return None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(str(v).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return None


def _share(v: Any) -> float | None:
    x = _num(v)
    if x is None or x < 0:
        return None
    if x > 1:
        x = x / 100 if x <= 100 else None  # "40" means 40 %
    return None if x is None else round(min(1.0, x), 4)


def _clean_params(kind: str, raw: Any) -> dict[str, Any]:
    """Keep only the keys ``kind`` reads, coerced to sane types; drop the rest."""
    defaults = CRITERION_DEFAULT_PARAMS.get(kind, {})
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in defaults:
        if key not in raw:
            continue
        v = raw[key]
        if key in ("min", "max"):
            if v is None:
                out[key] = None
            else:
                x = _num(v)
                if x is not None and x >= 0:
                    out[key] = int(x)
        elif key == "days":
            x = _num(v)
            if x is not None and 1 <= x <= 730:
                out[key] = int(x)
        elif key in ("min_share", "max_share", "min_rate"):
            x = _share(v)
            if x is not None:
                out[key] = x
        elif key == "min_per_week":
            x = _num(v)
            if x is not None and 0 <= x <= 50:
                out[key] = round(x, 2)
        elif key in ("min_count", "max_undisclosed"):
            x = _num(v)
            if x is not None and 0 <= x <= 1000:
                out[key] = int(x)
        elif key == "topics":
            if isinstance(v, list):
                ts = list(dict.fromkeys(str(t) for t in v if str(t) in TOPICS))
                if ts:
                    out[key] = ts
        elif key == "formats":
            if isinstance(v, list):
                fs = list(dict.fromkeys(str(t) for t in v if str(t) in MEDIA_TYPES))
                if fs:
                    out[key] = fs
        elif key == "city":
            if isinstance(v, str) and v.strip() and not refusal_reason(v):
                out[key] = clip(v.strip(), 60)
    if kind == "followers_range":
        lo, hi = out.get("min", defaults.get("min")), out.get("max", defaults.get("max"))
        if lo is not None and hi is not None and lo > hi:
            out["min"], out["max"] = hi, lo
    return out


def _validate_brief(raw: Any, lang: str = "cs") -> Brief | None:
    if not isinstance(raw, dict):
        return None
    bt = str(raw.get("business_type") or "").strip()
    if not bt:
        return None
    comps: list[dict] = []
    for c in raw.get("competitors") or []:
        if isinstance(c, str) and c.strip():
            c = {"name": c.strip(), "handles": [c] if c.strip().startswith("@") else []}
        if not isinstance(c, dict):
            continue
        name = clip(str(c.get("name") or "").strip(), 60)
        handles = [norm_handle(str(h)) for h in (c.get("handles") or []) if str(h).strip()]
        if name or handles:
            comps.append({"name": name or handles[0], "handles": list(dict.fromkeys(handles))})
    city = raw.get("city")
    lang_v = raw.get("lang") if raw.get("lang") in ("cs", "en") else lang
    return Brief(
        business_type=clip(bt, 80),
        city=clip(str(city).strip(), 60) if isinstance(city, str) and city.strip() else None,
        audience=clip(str(raw.get("audience") or ""), 300),
        goal=clip(str(raw.get("goal") or ""), 300),
        budget_hint=clip(str(raw["budget_hint"]), 80) if raw.get("budget_hint") else None,
        competitors=comps,
        lang=lang_v,
    )


def _str_list(v: Any, n: int = 10, size: int = 60) -> list[str]:
    if not isinstance(v, list):
        return []
    out = [clip(str(x).strip(), size) for x in v if isinstance(x, (str, int)) and str(x).strip()]
    return [x for x in dict.fromkeys(out) if not refusal_reason(x)][:n]


def _city_slug(city: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(city))


def default_discovery(brief: Brief) -> DiscoveryQuery:
    """Brno -> the shared demo pool (both demo goals use it); otherwise a query built from the brief."""
    from app.presets import DEMO_DISCOVERY

    if brief.city and fold(brief.city) == "brno":
        return DEMO_DISCOVERY.model_copy(deep=True)
    city = brief.city or ""
    slug = _city_slug(city)
    bt = fold(brief.business_type)
    kws = [f"{bt} {fold(city)}".strip()] + ([f"{fold(city)} tipy"] if city else [])
    tags = [t for t in (slug, f"{slug}food" if slug else "", f"{slug}tipy" if slug else "") if t]
    return DiscoveryQuery(keywords=kws, hashtags=tags, places=[city] if city else [], city=city or None)


def _validate_discovery(raw: Any, brief: Brief) -> DiscoveryQuery:
    if isinstance(raw, dict):
        kws, tags, places = _str_list(raw.get("keywords")), _str_list(raw.get("hashtags")), _str_list(raw.get("places"))
        city = raw.get("city") if isinstance(raw.get("city"), str) and raw.get("city").strip() else brief.city
        if kws or tags or places:
            base = default_discovery(brief)
            return DiscoveryQuery(
                keywords=list(dict.fromkeys(kws + base.keywords))[:12],
                hashtags=list(dict.fromkeys(tags + base.hashtags))[:12],
                places=places or base.places, city=city or base.city,
                platforms=base.platforms, limit=base.limit,
            )
    return default_discovery(brief)


def _dedupe_refused(items: list[Refused]) -> list[Refused]:
    out: list[Refused] = []
    seen: set[str] = set()
    for r in items:
        k = fold(r.text) + "|" + str((r.reason or {}).get("en") or "")
        if fold(r.text) and k not in seen:
            seen.add(k)
            out.append(r)
    return out


_NO_CITY_WHY = i18n("Město jste neuvedli, proto je lokální kritérium vypnuté.", "No city given, so the local criterion is off.")


def _local_city(c: Criterion, brief: Brief | None) -> Criterion:
    """local_signal without an explicit city checks brief.city; with no city at all it is switched
    off (never a silent default city)."""
    if c.kind != "local_signal" or (c.params.get("city") or "").strip():
        return c
    city = brief.city if brief is not None else None
    if city:
        return c.model_copy(update={"params": {**c.params, "city": city}})
    return c.model_copy(update={"params": {**c.params, "city": None}, "enabled": False, "why": dict(_NO_CITY_WHY)})


class CriteriaRejected(ValueError):
    """normalize_criteria_set: params that cannot be coerced, or nothing usable left."""


def normalize_criteria_set(cs: CriteriaSet) -> CriteriaSet:
    """Server-side guard for CriteriaSets written directly through the API (POST /api/runs,
    /criteria, /goal {criteria}) and by chat tools: the same rules as ``validate_criteria`` without
    renaming ids or rebuilding discovery. Brief text fields, criterion labels / why texts and the
    city param go through the sensitive guard (a flagged criterion moves to ``refused``, a flagged
    why text is replaced by the default one); params are coerced per kind and unknown keys are
    stripped. Raises CriteriaRejected listing params whose values cannot be coerced (e.g. a
    non-numeric "max"), or when no criterion is left."""
    brief, refused = sanitize_brief(cs.brief)
    refused = list(cs.refused) + refused
    lang = brief.lang
    bad: list[str] = []
    criteria: list[Criterion] = []
    for c in cs.criteria:
        label = _i18n_or(c.label) or dict(CRITERION_DEFAULT_LABELS.get(c.kind, {"cs": c.kind, "en": c.kind}))
        raw_params = c.params if isinstance(c.params, dict) else {}
        smuggled = any_refusal([label.get("cs", ""), label.get("en", ""), str(raw_params.get("city") or "")])
        if smuggled:
            refused.append(Refused(text=clip(label.get(lang) or c.kind, 200), reason=smuggled))
            continue
        why = _i18n_or(c.why)
        if not why or any_refusal([why.get("cs", ""), why.get("en", "")]):
            why = _default_why(c.kind)
        defaults = CRITERION_DEFAULT_PARAMS.get(c.kind, {})
        clean = _clean_params(c.kind, raw_params)
        for key in raw_params:
            if key in defaults and key not in clean and not (key == "city" and raw_params[key] in (None, "")):
                bad.append(f"{c.id}.{key}={raw_params[key]!r}")
        params = {k: clean[k] for k in defaults if k in clean}
        if c.kind == "local_signal" and "city" not in params:
            params["city"] = None
        crit = Criterion(id=c.id, kind=c.kind, round=c.round, label=label, why=why, params=params, enabled=c.enabled)
        criteria.append(_local_city(crit, brief))
    if bad:
        raise CriteriaRejected("invalid criterion params: " + ", ".join(bad))
    if not criteria:
        raise CriteriaRejected("no usable criteria left (sensitive or unsupported requests are listed under refused)")
    d = cs.discovery
    discovery = d.model_copy(update={
        "keywords": [x for x in d.keywords if not refusal_reason(x)],
        "hashtags": [x for x in d.hashtags if not refusal_reason(x)],
        "places": [x for x in d.places if not refusal_reason(x)],
    })
    return CriteriaSet(brief=brief, criteria=criteria, refused=_dedupe_refused(refused), discovery=discovery)


def validate_criteria(raw: dict) -> tuple[CriteriaSet | None, list[Refused]]:
    """Validate a propose_criteria / change_goal tool input. Unknown kinds, sensitive or scoring
    requests -> Refused; returns (CriteriaSet or None if unusable, refused)."""
    refused: list[Refused] = []
    if not isinstance(raw, dict):
        return None, refused
    brief = _validate_brief(raw.get("brief"))
    if brief is not None:
        brief, brief_refused = sanitize_brief(brief)  # free-text brief fields are guarded too
        refused.extend(brief_refused)
    lang = brief.lang if brief else "cs"

    for r in raw.get("refused") or []:
        if not isinstance(r, dict):
            continue
        text = clip(str(r.get("text") or "").strip(), 200)
        if text:
            reason = refusal_reason(text) or _i18n_or(r.get("reason")) or dict(UNSUPPORTED_REASON)
            refused.append(Refused(text=text, reason=reason))

    criteria: list[Criterion] = []
    seen_ids: set[str] = set()
    for item in raw.get("criteria") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        label = _i18n_or(item.get("label"))
        desc = (label or {}).get(lang) or kind or "?"
        params_raw = item.get("params") if isinstance(item.get("params"), dict) else {}
        if kind not in CRITERION_KINDS:
            reason = any_refusal([desc, kind, json.dumps(params_raw, ensure_ascii=False)]) or dict(UNSUPPORTED_REASON)
            refused.append(Refused(text=clip(desc, 200), reason=reason))
            continue
        # A sensitive request smuggled through a whitelisted kind's label or params.
        smuggled = any_refusal([(label or {}).get("cs", ""), (label or {}).get("en", ""), str(params_raw.get("city") or "")])
        if smuggled:
            refused.append(Refused(text=clip(desc, 200), reason=smuggled))
            continue
        why = _i18n_or(item.get("why"))
        if why and any_refusal([why["cs"], why["en"]]):
            why = None  # neutralize, keep the (whitelisted) criterion
        cid = kind
        n = 2
        while cid in seen_ids:
            cid = f"{kind}_{n}"
            n += 1
        seen_ids.add(cid)
        crit = make_criterion(
            kind, _clean_params(kind, params_raw), id=cid, label=label, why=why or _default_why(kind),  # type: ignore[arg-type]
            enabled=item.get("enabled") is not False,
        )
        criteria.append(_local_city(crit, brief))

    refused = _dedupe_refused(refused)
    if brief is None or not criteria:
        return None, refused
    cs = CriteriaSet(brief=brief, criteria=criteria, refused=refused, discovery=_validate_discovery(raw.get("discovery"), brief))
    return cs, refused


# --------------------------------------------------------------------------------------------
# Deterministic criteria (presets / fixtures / generic template)
# --------------------------------------------------------------------------------------------

_GENERIC_WHY: dict[str, dict[str, str]] = {
    "public_account": i18n("Obsah soukromého účtu nevidíme, takže ho nejde prověřit.",
                           "We cannot see a private account's content, so it cannot be checked."),
    "followers_range": i18n("Velikost tvůrce odpovídá rozpočtu; menší tvůrci mívají bližší vztah s publikem.",
                            "Creator size matches the budget; smaller creators tend to have a closer audience."),
    "active_recently": i18n("Tvůrce, který měsíc nic nezveřejnil, kampaň nejspíš neodvede.",
                            "A creator with no post for a month is unlikely to deliver a campaign."),
    "not_brand_account": i18n("Hledáme tvůrce, ne jiné firmy.", "We are looking for creators, not other businesses."),
    "language_cs": i18n("Vaši zákazníci čtou česky.", "Your customers read Czech."),
    "topic_share": i18n("Spolupráce zapadne k tvůrci, který o vašem tématu mluví pravidelně.",
                        "A collaboration fits a creator who regularly talks about your topic."),
    "formats": i18n("Krátká videa ukážou produkt a místo nejlépe.", "Short videos show the product and the place best."),
    "post_frequency": i18n("Pravidelné posty drží publikum aktivní.", "Regular posting keeps the audience engaged."),
    "max_commercial_share": i18n("Když je reklama skoro každý post, lidé jí přestanou věřit.",
                                 "When almost every post is an ad, people stop trusting it."),
    "min_engagement": i18n("Sledující, kteří reagují, spíš přijdou i k vám.", "Followers who react are more likely to come to you."),
    "cs_comment_share": i18n("Lidé, kteří reagují, píšou česky; je to jazyk komentářů, ne demografie publika.",
                             "People who react write in Czech; this is the language of the comments, not a demographic estimate."),
    "local_signal": i18n("Lokální firma potřebuje lidi ze svého města.", "A local business needs people from its own city."),
    "max_generic_comments": i18n("Hodně komentářů jen z emoji může znamenat nakoupenou aktivitu.",
                                 "Many emoji-only comments can indicate bought engagement."),
    "no_competitor_collab": i18n("Tvůrce, který právě dělá reklamu konkurenci, by pro vás nebyl věrohodný.",
                                 "A creator currently promoting a competitor would not be credible for you."),
    "discloses_ads": i18n("Neoznačená reklama je problém i pro zadavatele.", "Undisclosed advertising is a problem for the advertiser too."),
}


def _default_why(kind: str) -> dict[str, str]:
    return dict(_GENERIC_WHY.get(kind, i18n("", "")))


_RX_BAKERY = re.compile(r"pekar|cukrar|kavar|pecivo|chleb|kolac|dort|bakery|pastry|croissant|\bcafe\b|kvas")
_RX_FITNESS = re.compile(r"fitness|posilovn|studio|\bgym\b|cvic|joga|yoga|pilates|crossfit|trenink|trener")


def pick_preset(text: str) -> str | None:
    """"bakery" / "fitness" / None by keywords (pekár/cukrár/kavár vs fitness/posilovn/studio)."""
    f = fold(text)
    if _RX_BAKERY.search(f):
        return "bakery"
    if _RX_FITNESS.search(f):
        return "fitness"
    return None


def load_preset(name: str) -> CriteriaSet:
    """CriteriaSet for a demo brief: fixtures/briefs.json when present and valid, else app.presets."""
    from app.presets import get_preset

    path = get_settings().fixtures_dir / "briefs.json"
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            entry: Any = None
            if isinstance(data, dict):
                entry = data.get(name)
                if entry is None and isinstance(data.get("briefs"), (list, dict)):
                    data = data["briefs"]
                    entry = data.get(name) if isinstance(data, dict) else None
            if entry is None and isinstance(data, list):
                entry = next((e for e in data if isinstance(e, dict) and name in (e.get("name"), e.get("id"), e.get("preset"))), None)
            if isinstance(entry, dict):
                for key in ("criteria_set", "criteriaSet", "criteria"):
                    if isinstance(entry.get(key), dict):
                        entry = entry[key]
                        break
                return CriteriaSet.model_validate(entry)
    except Exception:
        pass
    return get_preset(name)  # type: ignore[arg-type]


_RX_FOOD_BIZ = re.compile(r"pekar|cukrar|kavar|restaur|bistro|jidl|food|cafe|\bbar\b|vin|pivo|lahud|cokolad|zmrzlin")
_RX_FIT_BIZ = re.compile(r"fitness|posilovn|gym|cvic|joga|yoga|pilates|crossfit|sport")
_RX_BEAUTY_BIZ = re.compile(r"kosmet|kader|salon|beauty|nehty|masaz|barber")
_RX_FASHION_BIZ = re.compile(r"obleceni|moda|butik|fashion|boty|second")
_RX_KIDS_BIZ = re.compile(r"hrack|detsk|deti|kids|hernic")
_RX_TECH_BIZ = re.compile(r"elektro|pocitac|mobil|tech|servis")
_RX_TRAVEL_BIZ = re.compile(r"hotel|penzion|cestov|ubytov")
_RX_BOOK_BIZ = re.compile(r"knih|papirnic")


def _topics_for_business(bt: str) -> list[str]:
    f = fold(bt)
    for rx, topics in (
        (_RX_FOOD_BIZ, ["food", "recipes", "restaurants_cafes", "local_tips"]),
        (_RX_FIT_BIZ, ["fitness", "sport", "lifestyle"]),
        (_RX_BEAUTY_BIZ, ["beauty", "lifestyle", "fashion"]),
        (_RX_FASHION_BIZ, ["fashion", "lifestyle", "beauty"]),
        (_RX_KIDS_BIZ, ["family", "lifestyle", "education"]),
        (_RX_TECH_BIZ, ["tech", "education"]),
        (_RX_TRAVEL_BIZ, ["travel", "local_tips", "lifestyle"]),
        (_RX_BOOK_BIZ, ["education", "lifestyle", "family"]),
    ):
        if rx.search(f):
            return topics
    return ["local_tips", "lifestyle"]


_RX_THOUSANDS = re.compile(r"(?<=\d)[ ,.\u00a0\u202f](?=\d{3}(?!\d))")


def _ungroup(text: str) -> str:
    """"20,000" / "20 000" / "20.000" -> "20000" (thousands separators, not decimals)."""
    prev = None
    while prev != text:
        prev, text = text, _RX_THOUSANDS.sub("", text)
    return text


def _budget_czk(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(tis\w*|k\b|000)?", _ungroup(fold(text)))
    if not m:
        return None
    x = _num(m.group(1)) or 0.0
    if m.group(2) and m.group(2).startswith(("tis", "k")):
        x *= 1000
    return x


def _followers_for_budget(budget: str | None) -> dict[str, int]:
    x = _budget_czk(budget)
    if x is None:
        return {"min": 5000, "max": 50000}
    if x <= 10000:
        return {"min": 2000, "max": 20000}
    if x <= 30000:
        return {"min": 5000, "max": 50000}
    if x <= 100000:
        return {"min": 10000, "max": 150000}
    return {"min": 20000, "max": 300000}


def _competitor_why(brief: Brief) -> dict[str, str]:
    names = ", ".join(c.get("name") or (c.get("handles") or ["?"])[0] for c in brief.competitors)
    if not names:
        return i18n("Konkurenty jste neuvedli; kritérium hlídá jen ty, které doplníte.",
                    "No competitors given; this only checks the ones you add.")
    return i18n(f"Tvůrce, který dělá reklamu konkurenci ({names}), by pro vás nebyl věrohodný.",
                f"A creator promoting a competitor ({names}) would not be credible for you.")


def generic_criteria(brief: Brief) -> CriteriaSet:
    topics = _topics_for_business(brief.business_type)
    fr = _followers_for_budget(brief.budget_hint)
    city = brief.city
    spec: list[tuple[str, dict]] = [
        ("public_account", {}), ("followers_range", fr), ("active_recently", {"days": 30}),
        ("not_brand_account", {}), ("language_cs", {"min_share": 0.5}),
        ("topic_share", {"topics": topics, "min_share": 0.4}), ("formats", {"formats": ["reel", "video"], "min_share": 0.2}),
        ("post_frequency", {"min_per_week": 1.0}), ("max_commercial_share", {"max_share": 0.3}),
        ("min_engagement", {"min_rate": 0.015}), ("cs_comment_share", {"min_share": 0.5}),
        ("local_signal", {"city": city or "", "min_count": 1}), ("max_generic_comments", {"max_share": 0.5}),
        ("no_competitor_collab", {}), ("discloses_ads", {"max_undisclosed": 0}),
    ]
    crit = []
    for kind, params in spec:
        why = _competitor_why(brief) if kind == "no_competitor_collab" else _default_why(kind)
        enabled = not (kind == "local_signal" and not city)
        if kind == "local_signal" and not city:
            why = i18n("Město jste neuvedli, proto je lokální kritérium vypnuté.", "No city given, so the local criterion is off.")
        crit.append(make_criterion(kind, params, why=why, enabled=enabled))  # type: ignore[arg-type]
    return CriteriaSet(brief=brief, criteria=crit, refused=[], discovery=default_discovery(brief))


def _generic_whys(brief: Brief) -> dict[str, dict[str, str]]:
    """Criterion reasons that do not name a business type (for a business the preset was not made for)."""
    city = brief.city or ""
    loc = f" {cs_locative(city)}" if city else ""
    return {
        "language_cs": i18n(f"Vaši zákazníci{loc} čtou česky.", f"Your customers{(' in ' + city) if city else ''} read Czech."),
        "topic_share": i18n("Doporučení zapadne k tvůrci, který o těchto tématech mluví pravidelně.",
                            "A recommendation fits a creator who talks about these topics regularly."),
        "formats": i18n("Krátká videa nejlépe ukážou vaši nabídku a místo.", "Short videos show your offer and the place best."),
        "local_signal": i18n(f"Potřebujete lidi, kteří jsou{loc}, ne kdekoli v republice." if loc
                             else "Potřebujete lidi z okolí, ne z celé republiky.",
                             f"You need people from {city or 'your area'}, not the whole country."),
    }


def criteria_for_brief(brief: Brief, refused: list[Refused] | None = None) -> CriteriaSet:
    """Deterministic CriteriaSet for a brief: the bakery / fitness demo set (fixtures/briefs.json or
    app.presets) when the business matches by keywords, else a generic template. The given brief
    replaces the preset's brief; city-dependent params follow the brief's city. ``refused`` (e.g. the
    previous set's refused list, or ``history_refusals(history)``) is carried over; the preset's own
    example refusals are not."""
    name = pick_preset(f"{brief.business_type} {brief.goal}")
    if name is None:
        cs = generic_criteria(brief)
    else:
        base = load_preset(name)
        crit = [c.model_copy(deep=True) for c in base.criteria]
        same_city = (brief.city or "") and fold(brief.city or "") == fold(base.brief.city or "")
        for i, c in enumerate(crit):
            if c.kind == "local_signal":
                if brief.city and not same_city:
                    crit[i] = c.model_copy(update={"params": {**c.params, "city": brief.city}})
                elif not brief.city:
                    crit[i] = c.model_copy(update={"enabled": False, "why": i18n(
                        "Město jste neuvedli, proto je lokální kritérium vypnuté.", "No city given, so the local criterion is off.")})
            if c.kind == "no_competitor_collab" and brief.competitors != base.brief.competitors:
                crit[i] = c.model_copy(update={"why": _competitor_why(brief)})
        # the preset lends its criteria to another business ("kavárna" on the bakery set): reasons that
        # name the preset's business ("The bakery's customers ...") are said in neutral words instead
        own_types = {fold(preset_brief_for(name, lg).business_type) for lg in ("cs", "en")}
        if fold(brief.business_type or "") not in own_types:
            generic = _generic_whys(brief)
            for i, c in enumerate(crit):
                if c.kind in generic and c.why == base.criteria[i].why:
                    crit[i] = c.model_copy(update={"why": generic[c.kind]})
        discovery = base.discovery.model_copy(deep=True) if (same_city or not brief.city) else default_discovery(brief)
        # The preset's example refusals are NOT copied: Refused.text must be something this owner asked.
        cs = CriteriaSet(brief=brief, criteria=crit, refused=[], discovery=discovery)
    if refused:
        cs.refused = _dedupe_refused(list(refused))
    return cs


# --------------------------------------------------------------------------------------------
# Plain-language descriptions
# --------------------------------------------------------------------------------------------


def describe_params(c: Criterion, lang: str, brief: Brief | None = None) -> str:
    p = c.params
    k = c.kind
    if k == "public_account":
        return _t(lang, "jen veřejné účty", "public accounts only")
    if k == "followers_range":
        lo, hi = p.get("min"), p.get("max")
        if lo is not None and hi is not None:
            return _t(lang, f"{fmt_int(lo, 'cs')} až {fmt_int(hi, 'cs')} sledujících", f"{fmt_int(lo, 'en')} to {fmt_int(hi, 'en')} followers")
        if lo is not None:
            return _t(lang, f"aspoň {fmt_int(lo, 'cs')} sledujících", f"at least {fmt_int(lo, 'en')} followers")
        if hi is not None:
            return _t(lang, f"nejvýš {fmt_int(hi, 'cs')} sledujících", f"at most {fmt_int(hi, 'en')} followers")
        return _t(lang, "libovolná velikost", "any size")
    if k == "active_recently":
        return _t(lang, f"poslední post do {p.get('days')} dní", f"last post within {p.get('days')} days")
    if k == "not_brand_account":
        return _t(lang, "ne firemní účty", "no business accounts")
    if k == "language_cs":
        return _t(lang, f"aspoň {fmt_pct(p.get('min_share'), 'cs')} popisků česky", f"at least {fmt_pct(p.get('min_share'), 'en')} of captions in Czech")
    if k == "topic_share":
        # Only the counted topics carry the share (the same rule as the round-2 check); supporting
        # topics such as local tips are named separately so the proposal does not promise they count.
        all_t = [t for t in (p.get("topics") or []) if isinstance(t, str)]
        counted = topics_mod.counted_topics(all_t)
        names = ", ".join(TOPIC_LABELS.get(t, {}).get(lang, t) for t in counted)
        extra = [t for t in all_t if t not in counted]
        x_names = ", ".join(TOPIC_LABELS.get(t, {}).get(lang, t) for t in extra)
        x_cs = f" ({x_names} se do podílu nepočítají)" if extra else ""
        x_en = f" ({x_names} do not count toward the share)" if extra else ""
        return _t(lang, f"aspoň {fmt_pct(p.get('min_share'), 'cs')} postů: {names}{x_cs}", f"at least {fmt_pct(p.get('min_share'), 'en')} of posts: {names}{x_en}")
    if k == "formats":
        fl = [f for f in (p.get("formats") or []) if isinstance(f, str)]
        if "reel" in fl and "video" in fl:
            # Reels are videos too: "short videos, videos" reads as a duplicate.
            fl = ["video"] + [f for f in fl if f not in ("reel", "video")]
        names = ", ".join(FORMAT_LABELS.get(f, {}).get(lang, f) for f in fl)
        return _t(lang, f"aspoň {fmt_pct(p.get('min_share'), 'cs')} postů jako {names}", f"at least {fmt_pct(p.get('min_share'), 'en')} of posts as {names}")
    if k == "post_frequency":
        v = float(p.get("min_per_week") or 0)
        cs_v = f"{v:g}".replace(".", ",")
        return _t(lang, "aspoň 1 post týdně" if v == 1 else f"aspoň {cs_v} postu týdně", f"at least {v:g} post(s) a week")
    if k == "max_commercial_share":
        return _t(lang, f"nejvýš {fmt_pct(p.get('max_share'), 'cs')} reklamních postů", f"at most {fmt_pct(p.get('max_share'), 'en')} ad posts")
    if k == "min_engagement":
        return _t(lang, f"reakce aspoň {fmt_pct(p.get('min_rate'), 'cs')} sledujících na post", f"interactions of at least {fmt_pct(p.get('min_rate'), 'en')} of followers per post")
    if k == "cs_comment_share":
        return _t(lang, f"aspoň {fmt_pct(p.get('min_share'), 'cs')} komentářů česky", f"at least {fmt_pct(p.get('min_share'), 'en')} of comments in Czech")
    if k == "local_signal":
        return _t(lang, f"aspoň {p.get('min_count')} zmínka nebo místo z města {p.get('city') or '?'}", f"at least {p.get('min_count')} mention or place in {p.get('city') or '?'}")
    if k == "max_generic_comments":
        return _t(lang, f"nejvýš {fmt_pct(p.get('max_share'), 'cs')} komentářů jen z emoji nebo frází", f"at most {fmt_pct(p.get('max_share'), 'en')} emoji-only or generic comments")
    if k == "no_competitor_collab":
        names = ", ".join(c.get("name") or "?" for c in (brief.competitors if brief else []))
        return _t(lang, f"žádná spolupráce s: {names}" if names else "žádná spolupráce s konkurencí", f"no collaboration with: {names}" if names else "no competitor collaboration")
    if k == "discloses_ads":
        mx = p.get("max_undisclosed")
        if not mx:
            return _t(lang, "žádná neoznačená reklama", "no undisclosed ads")
        return _t(lang, f"nejvýš {mx} neoznačených reklam", f"at most {mx} undisclosed ads")
    return ""


def describe_criteria(cs: CriteriaSet, lang: str) -> str:
    lines: list[str] = []
    for rnd in (1, 2, 3, 4):
        items = [c for c in cs.criteria if c.round == rnd]
        if not items:
            continue
        lines.append(_t(lang, f"Kolo {rnd} – {ROUND_NAMES[rnd]['cs']}:", f"Round {rnd} – {ROUND_NAMES[rnd]['en']}:"))
        for c in items:
            off = "" if c.enabled else _t(lang, " (vypnuto)", " (off)")
            why = c.why.get(lang) or ""
            lines.append(f"• {c.label.get(lang, c.kind)}{off}: {describe_params(c, lang, cs.brief)}." + (f" {why}" if why else ""))
    if cs.refused:
        lines.append(_t(lang, "Nepoužiju:", "Not used:"))
        for r in cs.refused:
            lines.append(f"• „{clip(r.text, 80)}“ – {r.reason.get(lang, '')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# History helpers (shared by live and fallback)
# --------------------------------------------------------------------------------------------


def _msg_text(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _is_owner_msg(msg: dict) -> bool:
    if msg.get("role") != "user":
        return False
    c = msg.get("content")
    if isinstance(c, str):
        return True
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c)


def _owner_text(msg: dict) -> str:
    """Owner's own text in a user message (operator notes in extra text blocks are skipped)."""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text" and not str(b.get("text", "")).startswith("[server"):
                return str(b.get("text") or "")
    return ""


def history_refusals(history: list[dict], lang: str = "cs") -> list[Refused]:
    """Every sensitive owner request in the conversation, as Refused entries."""
    out: list[Refused] = []
    for m in history:
        if _is_owner_msg(m):
            text = _owner_text(m).strip()
            reason = refusal_reason(text)
            if reason:
                out.append(Refused(text=clip(text, 200), reason=reason))
    return _dedupe_refused(out)


async def _say(emit: Emit, text: str) -> None:
    parts = re.split(r"(\n\n)", text)
    for p in parts:
        if p:
            await emit("chat.delta", {"text": p})


def _jsonable(v: Any) -> Any:
    try:
        return to_jsonable_python(v)
    except Exception:
        return str(v)


async def _emit_tool(emit: Emit, name: str, inp: Any, result: Any) -> None:
    await emit("chat.tool", {"name": name, "input": _jsonable(inp), "result": _jsonable(result)})


async def _record_refusal(ctx: ChatContext, text: str, reason: dict[str, str], emit: Emit) -> None:
    """Add a Refused entry to the current criteria (if any); otherwise it is picked up from the
    history when criteria are proposed."""
    cs = ctx.current_criteria()
    if cs is None:
        return
    text = clip(text.strip(), 200)
    if _is_subject_run(ctx.current_run()):
        # A question about a sensitive trait of a NAMED creator ("is he gay?") is not stored word for
        # word next to that person's report; the reason says what was asked about and why it is not checked.
        lang = getattr(ctx, "lang", "cs")
        text = ("(otázka na citlivý údaj o tvůrci, neukládáme ji doslova)" if lang != "en"
                else "(a question about a sensitive trait of the creator, not stored word for word)")
        if any(fold(r.text) == fold(text) and r.reason == reason for r in cs.refused):
            return
    elif any(fold(r.text) == fold(text) for r in cs.refused):
        return
    new = cs.model_copy(deep=True)
    new.refused = _dedupe_refused(list(new.refused) + [Refused(text=text, reason=reason)])
    try:
        await ctx.propose_criteria(new)
    except Exception:
        pass
    await emit("criteria.updated", {"criteria": new})


def find_candidate(run: Run | None, ref: str) -> Candidate | None:
    """Resolve a candidate id ("instagram:anna") or handle ("@anna", "anna") in the run."""
    if run is None or not ref:
        return None
    ref = ref.strip()
    if ref in run.candidates:
        return run.candidates[ref]
    if ":" in ref:
        platform, _, handle = ref.partition(":")
        if platform.strip().lower() in ("instagram", "tiktok", "youtube", "news", "meta_branded", "web"):
            # explicit platform: exact id only ("tiktok:x" never resolves to "instagram:x")
            return run.candidates.get(f"{platform.strip().lower()}:{norm_handle(handle)}")
    h = norm_handle(ref.split(":", 1)[1] if ":" in ref else ref)
    if not h:
        return None
    exact = [c for c in run.candidates.values() if norm_handle(c.ref.handle) == h]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None  # same handle on two platforms: ambiguous, ask for the platform
    partial = [c for c in run.candidates.values() if h in norm_handle(c.ref.handle)]
    return partial[0] if len(partial) == 1 else None


def finalists(run: Run | None) -> list[Candidate]:
    if run is None:
        return []
    return [c for c in run.candidates.values() if c.status == "finalist"]


def _criterion_label(run: Run | None, criterion_id: str, lang: str) -> str:
    if run is not None:
        for c in run.criteria.criteria:
            if c.id == criterion_id:
                return c.label.get(lang, c.kind)
    return criterion_id


def explain_from_run(run: Run | None, cand: Candidate, lang: str) -> str:
    h = f"@{cand.ref.handle}"
    if cand.status == "eliminated" and cand.elimination is not None:
        e = cand.elimination
        src = next((s for s in e.sources if s.url), None)
        label = _criterion_label(run, e.criterion_id, lang)
        reason = e.reason.get(lang, "")
        cs = f"Účet {h} vypadl v {e.round}. kole na kritériu „{label}“: {reason}"
        en = f"Account {h} dropped out in round {e.round} on “{label}”: {reason}"
        if src is not None:
            # Platform + kind + mode instead of a raw URL (the URL names the account, which the
            # "blur eliminated" video mode must hide; the board's source chip opens it).
            d_cs, d_en = _source_label(src)
            cs += f" Zdroj: {d_cs} (otevřete ho přes zdroj na nástěnce)."
            en += f" Source: {d_en} (open it from the source chip on the board)."
        cs += " Pokud to u něj nechcete brát v úvahu, můžete ho na nástěnce vrátit."
        en += " If that should not count for this one, you can restore it on the board."
        return _t(lang, cs, en)
    if cand.status == "finalist":
        return _t(lang, f"Účet {h} nevypadl, je mezi finalisty.", f"Account {h} did not drop out; it is a finalist.")
    return _t(lang, f"Účet {h} zatím nevypadl.", f"Account {h} has not dropped out so far.")


_PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "news": "zprávy",
                   "meta_branded": "Meta knihovna reklam", "web": "web"}


def _source_label(src: Any) -> tuple[str, str]:
    sid = str(getattr(src, "id", "") or "")
    plat = str(getattr(src, "platform", "") or "")
    kind_cs, kind_en = ("profil", "profile") if ":profile:" in sid or ":channel:" in sid else (
        ("post", "post") if (":post:" in sid or ":video:" in sid) else ("záznam", "record"))
    mode = str(getattr(src, "mode", "") or "").upper()
    name = _PLATFORM_NAMES.get(plat, plat)
    name_en = {"news": "news", "meta_branded": "Meta ad library"}.get(plat, name)
    return f"{name}, {kind_cs}{', ' + mode if mode else ''}", f"{name_en}, {kind_en}{', ' + mode if mode else ''}"


def rounds_summary(run: Run | None, lang: str) -> str:
    if run is None or not run.rounds:
        return ""
    rs = sorted((r for r in run.rounds if isinstance(r, dict) and "round" in r), key=lambda r: r["round"])
    if not rs:
        return ""
    first = next((r for r in rs if r["round"] >= 1), rs[0])
    parts = [_t(lang, f"vstoupilo {first.get('entered', '?')}", f"{first.get('entered', '?')} entered")]
    for r in rs:
        if r["round"] >= 1:
            parts.append(_t(lang, f"po {r['round']}. kole {r.get('remaining', '?')}", f"after round {r['round']}: {r.get('remaining', '?')}"))
    return " → ".join(parts)


def _run_digest(run: Run | None) -> dict[str, Any]:
    if run is None:
        return {"run": None}
    fin = finalists(run)
    return {
        "run_id": run.id,
        "rounds": run.rounds,
        "finalists": [{"id": c.id, "handle": c.ref.handle, "has_report": c.report is not None} for c in fin],
        "eliminated": sum(1 for c in run.candidates.values() if c.status == "eliminated"),
        "active": sum(1 for c in run.candidates.values() if c.status == "active"),
    }


# --------------------------------------------------------------------------------------------
# Effective language (the owner's first message, else the UI language)
# --------------------------------------------------------------------------------------------

_EN_WORDS = frozenset(
    "the an and or for my our is are am was i we you what who how of in with about check please this that "
    "it have has run can could do does hello hi hey thanks thank shop want would like sell need help "
    "where which there their they she he his her your from at on be not no yes".split()
)
_CS_WORDS = frozenset(
    "je jsou se na ve ze pro mam mame chci chceme prosim ahoj dobry den co kdo jak ten ta ale jen nebo moje "
    "muj nas nase prover zkontroluj podivej dekuji diky jsem jsme by bych mi kde kolik jak tak take uz "
    "jeste ktery ktera ktere neni nemam proc ano jo taky protoze ktery mate muzete v z k".split()
)
_RX_JSON_BLOB = re.compile(r"\{.*\}", re.S)
_RX_URLISH = re.compile(r"(?i)(https?://\S+|www\.\S+|[@#][\w.]+|\b[\w-]+(?:\.[\w-]+)+\b)")
_RX_SENTENCE_END = re.compile(r"[.!?:;\n]\s*$")


def _content_words(text: str) -> list[str]:
    """Words of ``text`` without JSON blobs, URLs, @handles, domains and names: a capitalised word
    that does not start a sentence is a name or a place ("Jakub Horák", "Brno", "Pekárna Kubík")
    and says nothing about the owner's language (the jury types Czech names in English)."""
    t = _RX_URLISH.sub(" ", _RX_JSON_BLOB.sub(" ", text or ""))
    out: list[str] = []
    for m in re.finditer(r"[^\W\d_]+", t):
        w = m.group(0)
        before = t[: m.start()]
        initial = not before.strip() or bool(_RX_SENTENCE_END.search(before))
        if w[:1].isupper() and not initial:
            continue
        out.append(w)
    return out


def detect_owner_lang(text: str, *, stopwords_only: bool = False) -> str | None:
    """"cs" / "en" when the text is confidently one of them, else None. JSON blobs, URLs, @handles,
    domains and mid-sentence capitalised words (names, places) are ignored.

    ``stopwords_only`` (used when the UI already says cs / en): only a clear stopword majority counts,
    no lingua and no ř/ů/ě bonus, so a Czech name in an English sentence never flips the session."""
    words = _content_words(text)
    if not words:
        return None
    if not stopwords_only and len(words) >= 3:
        try:
            from app.compute.language import detect_language

            code = detect_language(" ".join(words))
        except Exception:
            code = None
        if code in ("cs", "sk"):
            return "cs"
        if code == "en":
            return "en"
    folded = [fold(w) for w in words]
    en = sum(1 for w in folded if w in _EN_WORDS)
    cs = sum(1 for w in folded if w in _CS_WORDS)
    if not stopwords_only and any(re.search(r"[řůěŘŮĚ]", w) for w in words):
        cs += 1
    if en >= 2 and en > 2 * cs:
        return "en"
    if cs >= 2 and cs > 2 * en:
        return "cs"
    return None


def _owner_lang_choice(ctx: Any) -> str | None:
    """A language the owner picked in the UI after the guide's last answer (ChatContext.lang_override):
    it wins over the language detected from the first message."""
    v = getattr(ctx, "lang_override", None)
    return v if v in ("cs", "en") else None


def effective_lang(history: list[dict], message: str, ui_lang: str) -> str:
    """The session language: the first owner message (history, then this one) whose language is
    clear, else the UI language. A greeting ("Hi", "Ahoj") or a bare @handle does not decide it, and
    once a message decided it stays (deterministic per session). With a cs / en UI only a clear
    stopword majority overrides it (a Czech name in an English sentence does not)."""
    ui = ui_lang if ui_lang in ("cs", "en") else None
    texts = [_owner_text(m) for m in history if _is_owner_msg(m) and _owner_text(m).strip()]
    texts.append(message or "")
    for t in texts:
        detected = detect_owner_lang(t, stopwords_only=ui is not None)
        if detected in ("cs", "en"):
            return detected
    return ui or "cs"


# --------------------------------------------------------------------------------------------
# LLM budget (app.llm.budget, section 9.2 of docs/subject-mode.md)
# --------------------------------------------------------------------------------------------


def _chat_task_enabled() -> bool:
    return llm_budget.llm_task_enabled("chat")


async def _spend_chat() -> None:
    """One Anthropic chat request is about to leave the process: count it, or raise BudgetExhausted."""
    if not await llm_budget.spend("chat"):
        raise llm_budget.BudgetExhausted("chat")


def preset_brief_for(name: str, lang: str) -> Brief:
    """The demo brief for ``name`` in ``lang``. City and competitors come from ``load_preset`` (the
    fixtures' briefs.json when present); in English the texts come from presets.preset_brief(name,
    "en"), so the English UI never shows "pekárna"."""
    base = load_preset(name).brief
    if lang != "en":
        return base.model_copy(deep=True, update={"lang": lang})
    en = preset_brief(name, "en")  # type: ignore[arg-type]
    texts = {"business_type": en.business_type, "audience": en.audience, "goal": en.goal,
             "budget_hint": en.budget_hint}
    return base.model_copy(deep=True, update={**{k: v for k, v in texts.items() if v}, "lang": "en"})


# --------------------------------------------------------------------------------------------
# Subject parsing (an @handle or an Instagram / TikTok profile link)
# --------------------------------------------------------------------------------------------

_IG_RESERVED = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct"}
_RX_PROFILE_URL = re.compile(
    r"(?i)(?<![\w@/])(?:https?://)?(?:www\.|m\.|vm\.)?(?:instagram\.com|tiktok\.com)/[^\s,;!?)\]\"'“”„]*"
)
_RX_AT_HANDLE = re.compile(r"(?<![\w.@/])@([A-Za-z0-9_.]{1,30})")
_RX_SOCIAL_HOST = re.compile(
    r"(?i)^(?:[\w-]+\.)*(?:instagram\.com|tiktok\.com|facebook\.com|fb\.com|youtube\.com|youtu\.be|x\.com|"
    r"twitter\.com|threads\.net|linktr\.ee|gmail\.com|seznam\.cz|email\.cz|centrum\.cz)$"
)


def _parse_subject_local(text: str, platform: str | None = None) -> tuple[str | None, str] | None:
    t = (text or "").strip().rstrip(".,;")
    m = re.match(r"(?i)^(?:https?://)?(?:www\.|m\.)?instagram\.com/([^/?#\s]+)", t)
    if m:
        h = m.group(1).lower()
        if h in _IG_RESERVED or not re.fullmatch(r"[a-z0-9._]{1,30}", h):
            return None
        return "instagram", h
    if re.match(r"(?i)^(?:https?://)?(?:www\.|m\.|vm\.)?tiktok\.com/", t):
        m = re.match(r"(?i)^(?:https?://)?(?:www\.|m\.)?tiktok\.com/@([^/?#\s]+)", t)
        if not m or not re.fullmatch(r"[a-z0-9._]{1,30}", m.group(1).lower()):
            return None
        return "tiktok", m.group(1).lower()
    m = re.fullmatch(r"@?([A-Za-z0-9._]{1,30})", t)
    if m:
        return platform, m.group(1).lower()  # type: ignore[return-value]
    return None


def parse_subject_text(text: str, platform: str | None = None) -> tuple[str | None, str] | None:
    """-> (platform or None, handle) via app.compute.subject.parse_subject (A), else a local parser
    with the same rules."""
    try:
        from app.compute.subject import parse_subject
    except ImportError:
        return _parse_subject_local(text, platform)
    try:
        return parse_subject(text, platform)  # type: ignore[arg-type]
    except Exception:
        return _parse_subject_local(text, platform)


@dataclass
class SubjectToken:
    raw: str                    # what is passed to research_subject (as written, or a profile URL for a hint)
    handle: str
    platform: str | None
    start: int = 0
    end: int = 0


def subject_token(text: str) -> SubjectToken | None:
    """The first profile reference in an owner message: a profile URL, else an @handle (not part of
    an e-mail address). "@x on TikTok" becomes the TikTok profile URL so the platform is kept."""
    for m in _RX_PROFILE_URL.finditer(text or ""):
        raw = m.group(0).rstrip(".,")
        p = parse_subject_text(raw)
        if p is not None:
            return SubjectToken(raw=raw, handle=p[1], platform=p[0], start=m.start(), end=m.end())
    for m in _RX_AT_HANDLE.finditer(text or ""):
        raw = "@" + m.group(1).rstrip(".")
        p = parse_subject_text(raw)
        if p is None:
            continue
        handle = p[1]
        platform = p[0]
        rest = fold((text[:m.start()] + " " + text[m.end():]))
        if platform is None and re.search(r"\btik ?tok\w*\b", rest) and not re.search(r"\binsta(gram)?\w*\b", rest):
            platform, raw = "tiktok", f"https://www.tiktok.com/@{handle}"
        elif platform is None and re.search(r"\binsta(gram)?\w*\b", rest) and not re.search(r"\btik ?tok\w*\b", rest):
            platform, raw = "instagram", f"https://www.instagram.com/{handle}/"
        return SubjectToken(raw=raw, handle=handle, platform=platform, start=m.start(), end=m.end())
    return bare_verb_handle(text)


_RX_TLD = re.compile(r"\.(?:cz|sk|com|eu|net|org|io|de|at|info|shop|cafe|example|app|co|uk|pl|hu|me|online|store|studio)$")
_RX_VERB_BARE = re.compile(
    r"(?i)\b(?:check|vet|research|look (?:at|into|up)|who is|who'?s|verify|investigate|background on|"
    r"prověř\w*|prover\w*|zkontroluj\w*|proklepn\w*|mrkni\w* na|podívej\w* se na|podivej\w* se na|kdo je)\s+"
    r"(?:(?:the |this )?(?:creator|account|handle|profile|účet|ucet|tvůrce|tvurce)\s+)?"
    r"([A-Za-z0-9_.]{2,30})(?![\w@/])"
)
_RX_REPLY_LEAD = re.compile(
    r"(?i)^\s*(?:(?:it'?s|it is|that'?s|the handle is|handle is|handle:|their handle is|account:|"
    r"je to|jmenuje se|účet je|ucet je|handle je|účet:|ucet:)\s*)"
)
_RX_REPLY_PLATFORM = re.compile(
    r"(?i)\s*(?:\(?\s*(?:on|at|na)\s+(tik ?tok\w*|insta(?:gram)?\w*)\s*\)?|\((tik ?tok|insta(?:gram)?)\))\s*[.!]?\s*$"
)


def _handle_like(raw: str, *, strict: bool) -> str | None:
    """``raw`` as a handle (folded, no dots at the ends) when it can be one; ``strict`` also needs an
    underscore, a digit or an inner dot, so plain words ("check Toman") never count."""
    t = raw.strip(".").lower()
    if not re.fullmatch(r"[a-z0-9_.]{2,30}", t) or ".." in t or _RX_TLD.search(t) or t.isdigit():
        return None
    if t in _NOT_NAMES or fold(t) in CITY_FORMS:
        return None
    if strict and not re.search(r"[_\d]|[a-z]\.[a-z]", t):
        return None
    return t


def _bare_token(raw_handle: str, rest: str, start: int, end: int) -> SubjectToken:
    platform: str | None = None
    raw = "@" + raw_handle
    f = fold(rest)
    if re.search(r"\btik ?tok\w*\b", f) and not re.search(r"\binsta(gram)?\w*\b", f):
        platform, raw = "tiktok", f"https://www.tiktok.com/@{raw_handle}"
    elif re.search(r"\binsta(gram)?\w*\b", f) and not re.search(r"\btik ?tok\w*\b", f):
        platform, raw = "instagram", f"https://www.instagram.com/{raw_handle}/"
    return SubjectToken(raw=raw, handle=raw_handle, platform=platform, start=start, end=end)


def bare_verb_handle(text: str) -> SubjectToken | None:
    """"Check toman_ochutnava for my bakery": a handle-like word (with _ / digit / inner dot) right
    after a check verb, written without @."""
    for m in _RX_VERB_BARE.finditer(text or ""):
        h = _handle_like(m.group(1), strict=True)
        if h:
            return _bare_token(h, text[:m.start(1)] + " " + text[m.end(1):], m.start(1), m.end(1))
    return None


def bare_reply_handle(text: str) -> SubjectToken | None:
    """The whole answer to "what is their @handle?" written without @: "toman_ochutnava",
    "toman_ochutnava on tiktok", "it's kamvbrne"."""
    t = (text or "").strip()
    t = _RX_REPLY_LEAD.sub("", t)
    plat = _RX_REPLY_PLATFORM.search(t)
    core = (t[:plat.start()] if plat else t).strip(" .!,")
    if not core or " " in core:
        return None
    strict = any(ch.isupper() for ch in core)   # "Toman" is a name, "toman_o" or "kamvbrne" a handle
    h = _handle_like(core, strict=strict)
    if not h:
        return None
    return _bare_token(h, plat.group(0) if plat else "", 0, len(text or ""))


def _post_link(text: str) -> bool:
    """An Instagram / TikTok link that is not a profile (a post, reel or video)."""
    return any(parse_subject_text(m.group(0).rstrip(".,")) is None for m in _RX_PROFILE_URL.finditer(text or ""))


_RX_CHECK_VERB = re.compile(
    r"\b(check\w*|vet|vetting|research\w*|look (at|into|up)|who is|who'?s|verify|investigate|background on|"
    r"prover\w*|zkontroluj\w*|proklepn\w*|podivej\w* se na|mrkni\w* na|kdo je)\b"
)


_RX_DISCOVERY_CTX = re.compile(
    r"konkuren|competit|rival|\b(?:like|jako|podobn\w*)\s+@|\bfind\b|\bnajd|\bnajit|\bhled|search for|looking for"
)


def is_subject_request(text: str, pending: str | None, first: bool, run: Run | None = None) -> SubjectToken | None:
    """An owner message naming one creator to check (section 8.2): it has a profile reference, it is
    the first owner message or has a check verb (or answers "what is their @handle?"), and it does not
    answer the competitor question. A first message without a check verb that names the handle as a
    competitor or as an example ("creators like @x", "find ...") starts the discovery interview.
    A handle that is already a candidate of the current discovery run is left to the existing flows."""
    if pending == "q5":
        return None
    tok = subject_token(text)
    if tok is None and pending == "sh":
        tok = bare_reply_handle(text)   # the answer to "what is their @handle?" written without @
    if tok is None:
        return None
    f = fold(text)
    verb = _RX_CHECK_VERB.search(f)
    if pending == "sh":
        return tok
    if not (first or verb):
        return None
    if not verb and _RX_DISCOVERY_CTX.search(f):
        return None
    if run is not None and getattr(run, "mode", "discovery") != "subject" and find_candidate(run, tok.handle) is not None:
        return None
    return tok


_UP = "A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"
_RX_NAME_REQUEST = re.compile(
    r"(?i)\b(?:check|research|look (?:up|into|at)|vet|verify|investigate|background on|who is|"
    r"prověř\w*|prover\w*|zkontroluj\w*|proklepn\w*|podívej\w* se na|podivej\w* se na|kdo je)\s+"
    r"(?:(?-i:the|a|an|this|that|creator|influencer|blogger|person|company|business|bakery|café|cafe|shop|studio|"
    r"tvůrce|tvurce|influencera|influencerku|blogera|blogerku|firmu|firma|pekárnu|pekarnu|kavárnu|kavarnu|"
    r"osobu)\s+)*"
    r"((?-i:[" + _UP + r"][\w'’.&-]*)(?:\s+(?-i:[" + _UP + r"][\w'’.&-]*)){0,3})"
)
_NOT_NAMES = {"instagram", "tiktok", "youtube", "facebook", "brno", "praha", "prague", "ico", "ičo"}


def subject_name(text: str) -> str | None:
    """A person / organization named without an @handle or profile link ("Check Jakub Horák from
    Brno for my bakery", "Prověř Pekárnu Kubík") -> the name, else None."""
    if subject_token(text) is not None or _post_link(text):
        return None
    m = _RX_NAME_REQUEST.search(text or "")
    if not m:
        return None
    name = m.group(1).strip(" .,'’")
    if not name or fold(name) in _NOT_NAMES or len(name) < 3:
        return None
    return name


def _ask_handle(out: _Reply, name: str) -> None:
    out.add(f"{name} rád prověřím, ale potřebuji konkrétní účet: podle samotného jména bych mohl zaměnit jmenovce. "
            f"{Q_TEXTS['sh']['cs']}{Q_HINTS['sh']['cs']}",
            f"I can check {name}, but I need the exact account: a name alone could match a namesake. "
            f"{Q_TEXTS['sh']['en']}{Q_HINTS['sh']['en']}")


# --------------------------------------------------------------------------------------------
# Anchor and goal extraction (subject flow)
# --------------------------------------------------------------------------------------------

_RX_SKIP = re.compile(
    r"^\s*(skip\w*|preskoc\w*|nevim|nevime|netusim|don'?t know|dont know|no idea|not sure|unknown|none|nothing|"
    r"nic|zadn\w*|zadne|no|ne|nope|n/?a|-)\s*[.!]?\s*$"
)
_RX_SKIP_LEAD = re.compile(r"^\s*(skip|preskoc\w*|nevim|don'?t know|dont know|no idea)\b")
_RX_DOMAIN = re.compile(r"(?i)(?<![@\w.-])(?:https?://)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(?=$|[/\s,;:!?)\]\"'“”]|\.(?:\s|$))")
_RX_COMPANY_ID_KW = re.compile(r"(?i)\b(?:i[čc]o|i[čc]|company\s*(?:id|number|no\.?|registration(?:\s*number)?)|reg(?:istration)?\.?\s*(?:no\.?|number))\s*[:#.]?\s*(?:cz)?\s*(\d[\d ]{4,10}\d)")
_RX_BARE_ID = re.compile(r"(?i)(?<![\d.,])(?:cz)?(\d{6,8})(?!\d|[.,]\d)")
# one word, plus a second one only when it is capitalized ("Hradec Králové"; not "Brno for my bakery")
_CITY_WORD = r"([^\s,.;:!?()\"“”„]+(?:\s+(?-i:[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])[^\s,.;:!?()\"“”„]*)?)"
_RX_ANCHOR_CITY = [
    re.compile(r"(?i)\b(?:based|located|living|lives|live|works|work|working)\s+(?:in|near|around)\s+" + _CITY_WORD),
    re.compile(r"(?i)(?:\b(?:is|are|she'?s|he'?s|they'?re|who'?s|creator|she|he|they|comes?|originally)|§S§)\s*,?\s*from\s+" + _CITY_WORD),
    re.compile(r"(?i)\b(?:je|jsou|pochazi|pochází|bydli|bydlí|sidli|sídlí|zije|žije|pusobi|působí|tvori|tvoří)\s+(?:z|ze)\s+" + _CITY_WORD),
    re.compile(r"(?i)\b(?:bydli|bydlí|sidli|sídlí|zije|žije|pusobi|působí|tvori|tvoří)\s+(?:v|ve)\s+" + _CITY_WORD),
    re.compile(r"(?i)§S§\s*,?\s*(?:z|ze)\s+" + _CITY_WORD),
]
_RX_ANSWER_CITY = re.compile(r"(?i)\b(?:in|from|z|ze|v|ve)\s+" + _CITY_WORD)


def _clean_city(raw: str) -> str | None:
    raw = raw.strip(" .,;:!?\"'“”„()")
    if not raw:
        return None
    known = find_city(raw)
    if known:
        return known
    words = raw.split()
    caps = [w for w in words if w[:1].isupper() and not re.search(r"\d", w)]
    if not caps or not words[0][:1].isupper():
        return None
    out = [words[0]] + ([words[1]] if len(words) > 1 and words[1][:1].isupper() else [])
    city = clip(" ".join(out), 60)
    return None if refusal_reason(city) else city


def _norm_website(raw: str) -> str | None:
    h = (raw or "").strip().lower()
    h = re.sub(r"^[a-z]+://", "", h)
    h = h.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].split(":", 1)[0]
    if h.startswith("www."):
        h = h[4:]
    h = h.strip(".")
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,24}", h) or _RX_SOCIAL_HOST.match(h):
        return None
    return h


def _norm_company_id(raw: str) -> str | None:
    d = re.sub(r"\D", "", re.sub(r"(?i)^\s*cz", "", raw or ""))
    if not 6 <= len(d) <= 8:
        return None
    return d.zfill(8)


def normalize_anchor_dict(raw: dict | None) -> dict[str, str] | None:
    """{"city"?, "website"?, "company_id"?} normalized like compute.subject.normalize_anchor (A's,
    when importable); empty -> None."""
    if not raw:
        return None
    try:
        from app.compute.subject import normalize_anchor

        a = normalize_anchor(dict(raw))
        if a is None:
            return None
        d = a.model_dump(exclude_none=True) if hasattr(a, "model_dump") else dict(a)
        d = {k: str(v) for k, v in d.items() if v not in (None, "")}
        return d or None
    except ImportError:
        pass
    except Exception:
        pass
    out: dict[str, str] = {}
    if raw.get("city") and str(raw["city"]).strip():
        out["city"] = clip(str(raw["city"]).strip(), 60)
    if raw.get("website"):
        w = _norm_website(str(raw["website"]))
        if w:
            out["website"] = w
    if raw.get("company_id"):
        c = _norm_company_id(str(raw["company_id"]))
        if c:
            out["company_id"] = c
    return out or None


def _blank_subjects(text: str) -> str:
    """Subject references (profile URLs, @handles) -> a placeholder, e-mail addresses -> blank."""
    t = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", " ", text or "")
    t = _RX_PROFILE_URL.sub(" §S§ ", t)
    return _RX_AT_HANDLE.sub(" §S§ ", t)


def extract_anchor(text: str, *, answer: bool = False) -> dict[str, str] | str | None:
    """Anchor fields named in an owner message. ``answer`` = the message answers the anchor question
    (then a bare city, domain or 6-8 digit number counts, and "skip" / "don't know" -> "skip").
    Outside an answer only explicit forms count ("based in X", "je z X", a website, "IČO 123..."), so
    the business's city ("for my bakery in Brno") is never taken as the creator's anchor."""
    if answer and _RX_SKIP.match(fold(text)):
        return "skip"
    t = _blank_subjects(text)
    out: dict[str, str] = {}
    m = _RX_COMPANY_ID_KW.search(t)
    cid = _norm_company_id(m.group(1)) if m else None
    if cid is None and answer:
        mm = _RX_BARE_ID.search(t)
        cid = _norm_company_id(mm.group(1)) if mm else None
    if cid:
        out["company_id"] = cid
    for mm in _RX_DOMAIN.finditer(t):
        w = _norm_website(mm.group(0))
        if w and not re.fullmatch(r"(?:e\.g|i\.e|atd|tzn|napr)", w):
            out["website"] = w
            break
    for rx in _RX_ANCHOR_CITY:
        mm = rx.search(t)
        if mm:
            city = _clean_city(mm.group(1))
            if city:
                out["city"] = city
                break
    # "I run a bakery in Brno" answers the anchor question with the BUSINESS: its city is not the anchor
    business_stmt = bool(_RX_I_RUN.search(t) or _RX_FOR_MY.search(t))
    if "city" not in out and answer and not business_stmt:
        mm = _RX_ANSWER_CITY.search(t)
        city = _clean_city(mm.group(1)) if mm else None
        if city is None:
            rest = _RX_DOMAIN.sub(" ", t)
            rest = re.sub(r"(?i)\b(i[čc]o|company id)\b.*", " ", rest)
            city = find_city(rest)
            if city is None:
                words = [w for w in re.findall(r"[^\W\d_]+", rest) if w != "S"]
                if 1 <= len(words) <= 3 and all(w[:1].isupper() for w in words) and "website" not in out:
                    city = _clean_city(" ".join(words))
        if city:
            out["city"] = city
    if not out and answer and _RX_SKIP_LEAD.match(fold(text)):
        return "skip"
    return out or None


_RX_FOR_MY = re.compile(
    r"(?i)\b(?:for|pro)\s+(?:my|our|a|an|the|moj[ie]|moji|mou|nasi|naši|naší|nase|naše|muj|můj|nas|náš)\s+([^,.;!?\n]+)"
)
_RX_I_RUN = re.compile(
    r"(?i)\b(?:i|we)\s+(?:run|own|have|manage|operate)\s+(?:an?\s+|the\s+|my\s+|our\s+)?([^,.;!?\n]+)|"
    r"\b(?:mám|mam|máme|mame|vedu|vedeme|provozuj\w*|vlastn\w*)\s+([^,.;!?\n]+)"
)


def extract_goal(text: str, lang: str, *, answer: bool = False) -> dict[str, Any] | None:
    """Business (and its city / goal words) named in an owner message of the subject flow:
    {"preset", "business", "city", "goal"} or None. ``answer`` = it answers the goal question, so the
    whole message is about the business."""
    t = _blank_subjects(text)
    # the anchor's own city phrase is about the creator, not the business
    for rx in _RX_ANCHOR_CITY:
        t = rx.sub(" ", t)
    t = _RX_DOMAIN.sub(" ", t).replace("§S§", " ")
    phrase = None
    m = _RX_FOR_MY.search(t) or _RX_I_RUN.search(t)
    if m:
        phrase = next((g for g in m.groups() if g), None)
    if phrase is None and answer and t.strip():
        phrase = t.strip()
    # Outside an answer the preset comes from the business phrase only: "@x, a fitness creator" says
    # what the creator does, not what the owner sells.
    preset = pick_preset(phrase) if phrase else None
    if preset is None and answer:
        preset = pick_preset(t)
    if preset is None and phrase is None:
        return None
    if preset is None and phrase is not None and not answer and not _looks_like_business(phrase) and not pick_preset(phrase):
        # "check @x for my friend" is not a business
        if not re.search(r"(?i)\b(shop|store|business|firm|company|studio|salon|cafe|caf\w|restaurant|bar|"
                         r"obchod|firm\w*|studi\w*|salon|kavarn\w*|restaurac\w*|provozovn\w*)\b", fold(phrase)):
            return None
    city = find_city(t)
    goal = ""
    if answer:
        parts = [p.strip() for p in re.split(r"[,;\n]|\s+-\s+|\s+–\s+", text) if p.strip()]
        if len(parts) > 1:
            goal = clip(", ".join(p for p in parts[1:] if not subject_token(p)), 300)
    business = _business_from(phrase or t, lang) if phrase else None
    return {"preset": preset, "business": business, "city": city, "goal": goal}


# --------------------------------------------------------------------------------------------
# research_subject input validation (live tool and fallback)
# --------------------------------------------------------------------------------------------


def validate_research_input(inp: Any, lang: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """-> (args for ctx.research_subject, None) or (None, {"ok": False, "error", "missing"?})."""
    if not isinstance(inp, dict):
        return None, {"ok": False, "error": "INVALID_JSON: tool input must be an object", "missing": ["subject", "brief"]}
    subj = inp.get("subject")
    if not isinstance(subj, str) or not subj.strip():
        return None, {"ok": False, "error": "subject is required: an @handle or an Instagram/TikTok profile link",
                      "missing": ["subject"]}
    subj = subj.strip()
    if len(subj) > 300:
        return None, {"ok": False, "error": "subject is too long (max 300 characters)", "missing": ["subject"]}
    if parse_subject_text(subj) is None:
        post = bool(_RX_PROFILE_URL.search(subj))
        return None, {"ok": False, "missing": ["subject"], "error": (
            "this is a link to a post or video, not a profile: ask the owner for the profile link or the @handle"
            if post else "not a profile reference: use an @handle or an instagram.com / tiktok.com profile link")}
    anchor: dict[str, str] | None = None
    raw_anchor = inp.get("anchor")
    if raw_anchor is not None:
        if not isinstance(raw_anchor, dict):
            return None, {"ok": False, "error": "anchor must be an object with city, website or company_id", "missing": ["anchor"]}
        clean: dict[str, str] = {}
        for k, v in raw_anchor.items():
            if k not in ("city", "website", "company_id"):
                return None, {"ok": False, "error": f"unknown anchor field {k!r} (allowed: city, website, company_id)"}
            if v is None:
                continue
            if not isinstance(v, str) or len(v) > 200:
                return None, {"ok": False, "error": f"anchor.{k} must be a string of at most 200 characters"}
            if v.strip():
                if refusal_reason(v):
                    return None, {"ok": False, "error": f"anchor.{k} is not usable"}
                clean[k] = v.strip()
        anchor = normalize_anchor_dict(clean)
    preset = inp.get("preset")
    if preset in ("", None):
        preset = None
    elif preset not in ("bakery", "fitness"):
        return None, {"ok": False, "error": "preset must be 'bakery' or 'fitness'"}
    brief = _validate_brief(inp.get("brief"), lang)
    if brief is None and preset:
        brief = preset_brief_for(preset, lang)
    if brief is None:
        return None, {"ok": False, "error": "a brief with business_type is required (the owner's business and goal)",
                      "missing": ["brief"]}
    brief, _refused = sanitize_brief(brief)
    brief = brief.model_copy(update={"lang": lang})
    return {"subject": subj, "anchor": anchor, "brief": brief, "preset": preset}, None


# --------------------------------------------------------------------------------------------
# Live chat (Claude with tools)
# --------------------------------------------------------------------------------------------

_SYSTEM_ROLE_MODELS = ("claude-opus-5", "claude-opus-4-8", "claude-fable-5", "claude-mythos-5", "claude-sonnet-5-5")
_RX_CONFIRM = re.compile(
    r"^\s*(ano|jo|jj|jasne|jasan|ok|okej|okay|yes|yep|yeah|sure|urcite|rozhodne|do toho|spust|proved|prover|go|"
    r"pojdme|pojd|prosim|please|klidne|muzes|muzete|let'?s|of course)\b|prover|proved\w* (hloubk|prover)|hloub|"
    r"\bdeep\b|\bvet|\bdo it\b"
)


@dataclass
class _TurnState:
    message: str
    lang: str
    tools_ran: int = 0
    text_emitted: bool = False
    model: str = ""          # OpenRouter: the model that answered
    # the last successful research_subject / change_goal / start_deep_vetting call (name, input,
    # result): rendered deterministically when the model's follow-up request fails
    last_tool: tuple[str, Any, Any] | None = None


_RESULT_TOOLS = ("research_subject", "change_goal", "start_deep_vetting")


def _note_tool(state: "_TurnState", name: str, inp: Any, result: Any, is_err: bool) -> None:
    if not is_err and name in _RESULT_TOOLS:
        state.last_tool = (name, inp, result)


def _operator_note(history: list[dict], text: str, model: str) -> None:
    """Operator note for this turn: a mid-conversation system message on models that support it,
    otherwise an extra text block on the owner's message."""
    if model.startswith(_SYSTEM_ROLE_MODELS):
        history.append({"role": "system", "content": text})
        return
    last = history[-1]
    content = last.get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
    blocks.append({"type": "text", "text": f"[server note] {text}"})
    last["content"] = blocks


def _board_state(ctx: ChatContext) -> str:
    cs = ctx.current_criteria()
    run = ctx.current_run()
    lang_name = "English" if ctx.lang == "en" else "Czech"
    parts = [f"Owner's language: {ctx.lang} (reply in {lang_name})."]
    if cs is None:
        parts.append("No criteria proposed yet.")
    else:
        parts.append(
            "Current criteria: " + "; ".join(f"{c.id}={json.dumps(c.params, ensure_ascii=False)}{'' if c.enabled else ' (off)'}" for c in cs.criteria)
            + f". Brief: {cs.brief.business_type}, {cs.brief.city or '-'}. Refused so far: {len(cs.refused)}."
        )
    if run is None:
        parts.append("No run yet.")
    else:
        d = _run_digest(run)
        mode = getattr(run, "mode", "discovery") or "discovery"
        if mode == "subject":
            subj = getattr(run, "subject", None)
            handle = getattr(subj, "handle", None) or _subject_handle(run) or "?"
            status = getattr(subj, "status", None) or "?"
            parts.append(
                f"Run {run.id} (mode=subject) checks ONE creator @{handle} (subject status {status}); nothing is "
                "eliminated. For another goal call change_goal (the report is re-rendered from the fetched data; "
                "summarise report_diffs). For another creator call research_subject. Never call run_rounds on this run."
            )
        else:
            parts.append(f"Run {run.id} (mode=discovery): rounds={json.dumps(run.rounds, ensure_ascii=False)}; "
                         f"finalists={[f['handle'] for f in d['finalists']]}.")
    return "[Board state, from the server] " + " ".join(parts)


def _repair_history(history: list[dict], start: int) -> None:
    """After a failed live turn: drop dangling tool_use turns and system notes that are not followed
    by an assistant turn, so the next request is valid."""
    while len(history) > start:
        last = history[-1]
        if last.get("role") == "assistant" and isinstance(last.get("content"), list) and any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in last["content"]
        ):
            history.pop()
            continue
        if last.get("role") == "system":
            history.pop()
            continue
        break
    i = start
    while i < len(history):
        if history[i].get("role") == "system" and (i + 1 >= len(history) or history[i + 1].get("role") != "assistant"):
            history.pop(i)
            continue
        i += 1


def _tool_result_json(result: Any) -> str:
    s = json.dumps(_jsonable(result), ensure_ascii=False, default=str)
    return s if len(s) <= 20000 else s[:20000] + "…"


async def _run_tool(name: str, inp: Any, ctx: ChatContext, emit: Emit, state: _TurnState) -> tuple[Any, bool]:
    """Validate a tool input against the whitelist and call the ChatContext. -> (result, is_error)."""
    lang = state.lang
    if not isinstance(inp, dict):
        return {"error": "INVALID_JSON: tool input must be an object"}, True
    try:
        if name == "propose_criteria":
            cs, refused = validate_criteria(inp)
            if cs is None:
                return {"error": "No usable criteria (brief and at least one whitelisted criterion are required).",
                        "refused": [r.model_dump() for r in refused]}, True
            cs.refused = _dedupe_refused(list(cs.refused) + history_refusals(ctx.history, lang))
            ctx_result = await ctx.propose_criteria(cs)
            await emit("criteria.updated", {"criteria": cs})
            result = {
                "accepted": [{"id": c.id, "kind": c.kind, "params": c.params, "enabled": c.enabled} for c in cs.criteria],
                "refused": [{"text": r.text, "reason": r.reason.get(lang)} for r in cs.refused],
                "context": ctx_result,
            }
            return result, False

        if name == "update_criterion":
            cs = ctx.current_criteria()
            cid = str(inp.get("criterion_id") or "")
            crit = next((c for c in (cs.criteria if cs else []) if c.id == cid), None)
            if crit is None:
                crit = next((c for c in (cs.criteria if cs else []) if c.kind == cid), None)
            if crit is None:
                return {"error": f"Unknown criterion id {cid!r}. Existing: {[c.id for c in (cs.criteria if cs else [])]}"}, True
            params = _clean_params(crit.kind, inp.get("params")) if isinstance(inp.get("params"), dict) else None
            enabled = inp.get("enabled") if isinstance(inp.get("enabled"), bool) else None
            if params is None and enabled is None:
                return {"error": "Nothing to change (params keys not valid for this kind, or no enabled flag)."}, True
            ctx_result = await ctx.update_criterion(crit.id, params or None, enabled)
            new_cs = ctx.current_criteria()
            if new_cs is not None:
                await emit("criteria.updated", {"criteria": new_cs})
            return {"updated": crit.id, "params": params, "enabled": enabled, "context": ctx_result}, False

        if name == "run_rounds":
            up_to = int(_num(inp.get("up_to")) or 3)
            up_to = max(0, min(3, up_to))
            if ctx.current_criteria() is None:
                return {"error": "Propose criteria first."}, True
            ctx_result = await ctx.run_rounds(up_to)
            return {"context": ctx_result, "summary": _run_digest(ctx.current_run())}, False

        if name == "explain_elimination":
            ref = str(inp.get("candidate_id") or "")
            run = ctx.current_run()
            cand = find_candidate(run, ref)
            if cand is None:
                return {"error": f"No candidate matches {ref!r} in the current run."}, True
            ctx_result = await ctx.explain_elimination(cand.id)
            return {"candidate_id": cand.id, "status": cand.status,
                    "elimination": _jsonable(cand.elimination), "explanation": explain_from_run(run, cand, lang),
                    "context": ctx_result}, False

        if name == "start_deep_vetting":
            if not _RX_CONFIRM.search(fold(state.message)):
                return {"error": "Not confirmed. Ask the owner first, e.g. 'Prověřit N finalistů do hloubky?', "
                                 "and call this only after they say yes."}, True
            run = ctx.current_run()
            ids = []
            for ref in inp.get("candidate_ids") or []:
                cand = find_candidate(run, str(ref))
                if cand is not None and cand.status == "finalist" and cand.id not in ids:
                    ids.append(cand.id)
            if not ids:
                ids = [c.id for c in finalists(run)]
            if not ids:
                return {"error": "There are no finalists yet. Run rounds 0-3 first."}, True
            ids = ids[:MAX_FINALISTS]
            ctx_result = await ctx.start_deep_vetting(ids)
            return {"vetting": ids, "context": ctx_result, "note": "Nothing is sent to anyone."}, False

        if name == "change_goal":
            brief = _validate_brief(inp.get("brief"), lang)
            if brief is None:
                return {"error": "A brief with business_type is required."}, True
            bad = any_refusal([brief.business_type, brief.goal])
            if bad:
                return {"error": "Refused", "reason": bad.get(lang)}, True
            ctx_result = await ctx.change_goal(brief)
            new_cs = ctx.current_criteria()
            if new_cs is not None:
                await emit("criteria.updated", {"criteria": new_cs})
            out = {"brief": brief.model_dump(), "context": ctx_result}
            if isinstance(ctx_result, dict) and isinstance(ctx_result.get("report_diffs"), list):
                out["report_diffs"] = ctx_result["report_diffs"]  # summarise these for the owner
            return out, False

        if name == "draft_outreach":
            run = ctx.current_run()
            cand = find_candidate(run, str(inp.get("candidate_id") or ""))
            if cand is None:
                return {"error": "No such candidate in the current run."}, True
            ctx_result = await ctx.draft_outreach(cand.id)
            return {"candidate_id": cand.id, "draft_only": True, "sent": False, "context": ctx_result}, False

        if name == "research_subject":
            fn = getattr(ctx, "research_subject", None)
            if fn is None:
                return {"ok": False, "error": "research_subject is not available here"}, True
            args, err = validate_research_input(inp, lang)
            if err is not None:
                return err, True
            ctx_result = await fn(args["subject"], args["anchor"], args["brief"], args["preset"])
            result = dict(ctx_result) if isinstance(ctx_result, dict) else {"ok": True, "context": ctx_result}
            if args["anchor"] is None:
                result.setdefault("anchor_note", "No anchor was given, so the identity verdict can be at most 'likely'. "
                                                 "Tell the owner that a city, website or company ID would confirm it.")
            result.setdefault("reply_order", "verdict text first; then up to 3 key findings, each tagged fact / inference / "
                                             "gap with its confidence; then the failing and unknown check counts; say nothing "
                                             "was eliminated and there is no score.")
            return result, result.get("ok") is False

        return {"error": f"Unknown tool {name!r}."}, True
    except Exception as e:  # a failing callback must not kill the turn
        return {"error": f"{type(e).__name__}: {e}"}, True


def _chat_effort() -> str:
    v = (os.environ.get("CHAT_EFFORT") or "").strip().lower()
    return v if v in ("low", "medium", "high", "xhigh", "max") else "medium"


async def _stream_once(client: Any, history: list[dict], emit: Emit, state: _TurnState) -> Any:
    model = get_settings().model_chat
    await _spend_chat()   # raises BudgetExhausted when the LLM request budget is used up
    async with client.messages.stream(
        model=model,
        max_tokens=32000,
        system=llm_client.cached_system(prompts.CHAT_SYSTEM),
        tools=TOOLS,
        messages=history,
        thinking={"type": "adaptive"},
        output_config={"effort": _chat_effort()},
        cache_control={"type": "ephemeral"},
    ) as stream:
        async for event in stream:
            if getattr(event, "type", None) == "text" and getattr(event, "text", ""):
                state.text_emitted = True
                await emit("chat.delta", {"text": event.text})
        return await stream.get_final_message()


def _blocks(content: list[Any]) -> list[dict]:
    out = []
    for b in content:
        if isinstance(b, dict):
            out.append(b)
        elif hasattr(b, "to_dict"):
            out.append(b.to_dict(mode="json", exclude_none=True))
        else:
            out.append(_jsonable(b))
    return out


async def _live_loop(client: Any, ctx: ChatContext, emit: Emit, state: _TurnState) -> bool:
    history = ctx.history
    json_retries = 0
    for _ in range(MAX_TOOL_STEPS):
        try:
            final = await _stream_once(client, history, emit, state)
        except ValueError as e:
            if isinstance(e, llm_budget.BudgetExhausted):
                raise
            # Tool-input JSON the SDK could not parse (eager input streaming): re-issue the turn.
            json_retries += 1
            if json_retries > 2:
                return False
            continue
        json_retries = 0
        stop = getattr(final, "stop_reason", None)
        if stop == "refusal":
            return False
        history.append({"role": "assistant", "content": _blocks(final.content)})
        if stop == "pause_turn":
            continue
        tool_uses = [b for b in final.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return True
        if stop == "max_tokens":
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                 "content": "Tool input was truncated; call it again with a shorter input."} for b in tool_uses
            ]})
            continue
        results = []
        for b in tool_uses:
            result, is_err = await _run_tool(b.name, b.input, ctx, emit, state)
            state.tools_ran += 1
            _note_tool(state, b.name, b.input, result, is_err)
            await _emit_tool(emit, b.name, b.input, result)
            item: dict[str, Any] = {"type": "tool_result", "tool_use_id": b.id, "content": _tool_result_json(result)}
            if is_err:
                item["is_error"] = True
            results.append(item)
        history.append({"role": "user", "content": results})
    return True


_INVALID_ARGS = {"error": "INVALID_JSON: the tool arguments were not a valid JSON object; call the tool again with valid JSON."}


async def _live_loop_openrouter(ctx: ChatContext, emit: Emit, state: _TurnState) -> bool:
    """The tool loop over OpenRouter chat/completions. Same tools, guards (``_run_tool``) and step
    limit as ``_live_loop``; history is appended in Anthropic format (tool_use / tool_result blocks)."""
    history = ctx.history
    tools = openrouter.openai_tools(TOOLS)
    model = get_settings().openrouter_model_chat

    async def on_text(text: str) -> None:
        state.text_emitted = True
        await emit("chat.delta", {"text": text})

    for _ in range(MAX_TOOL_STEPS):
        messages = openrouter.to_openai_messages(prompts.CHAT_SYSTEM, history)
        res = await openrouter.stream_chat(messages, tools=tools, model=model, on_text=on_text)
        state.model = res.model or state.model
        if res.finish_reason == "content_filter":
            return False
        if not res.text.strip() and not res.tool_calls:
            return False          # empty reply: treat as a failure (fallback if nothing was shown)
        content: list[dict[str, Any]] = []
        if res.text:
            content.append({"type": "text", "text": res.text})
        for call in res.tool_calls:
            content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.input or {}})
        history.append({"role": "assistant", "content": content})
        if not res.tool_calls:
            return True
        if res.finish_reason == "length":
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c.id, "is_error": True,
                 "content": "Tool input was truncated; call it again with a shorter input."} for c in res.tool_calls
            ]})
            continue
        results = []
        for call in res.tool_calls:
            if call.input is None:
                result, is_err = dict(_INVALID_ARGS), True
            else:
                result, is_err = await _run_tool(call.name, call.input, ctx, emit, state)
                state.tools_ran += 1
                _note_tool(state, call.name, call.input, result, is_err)
                await _emit_tool(emit, call.name, call.input, result)
            item: dict[str, Any] = {"type": "tool_result", "tool_use_id": call.id, "content": _tool_result_json(result)}
            if is_err:
                item["is_error"] = True
            results.append(item)
        history.append({"role": "user", "content": results})
    return True


async def chat_turn(message: str, ctx: ChatContext, emit: Emit) -> None:
    """One user message -> streamed assistant reply with tool loop; ends with emit("done", ...)."""
    lang = _owner_lang_choice(ctx) or effective_lang(ctx.history, message, ctx.lang)
    _set_ctx_lang(ctx, lang)   # before any tool runs, so tool results use the owner's language
    client = llm_client.get_client()
    use_openrouter = client is None and llm_client.openrouter_active()
    if client is None and not use_openrouter:
        await fallback_turn(message, ctx, emit)
        return
    # OpenRouter serves the chat only when the "chat" task group is enabled (OPENROUTER_TASKS);
    # Anthropic always is (budget.llm_task_enabled is True for it), so that check is skipped there.
    if use_openrouter and not _chat_task_enabled():
        await fallback_turn(message, ctx, emit)
        return
    history = ctx.history
    start = len(history)
    state = _TurnState(message=message, lang=lang)
    model = get_settings().openrouter_model_chat if use_openrouter else get_settings().model_chat

    history.append({"role": "user", "content": message})
    notes = [_board_state(ctx)]
    reason = refusal_reason(message)
    if reason:
        await _record_refusal(ctx, message, reason, emit)
        await _say(emit, reason[lang] + "\n\n")
        notes.append(
            "Server guard: the owner's last message asks to filter or judge people by a protected trait or by an "
            f"overall score. It is recorded as refused and the owner was already told: \"{reason[lang]}\" Do not "
            "create any criterion for it and do not repeat the refusal; continue with anything else in the message "
            "or with the next interview step."
        )
    _operator_note(history, "\n".join(notes), model)

    ok = False
    try:
        if use_openrouter:
            ok = await _live_loop_openrouter(ctx, emit, state)
        else:
            ok = await _live_loop(client, ctx, emit, state)
    except (openrouter.OpenRouterError, llm_budget.BudgetExhausted) as e:
        # WARNING: the app configures no logging, so INFO would never reach the console. Reason only.
        where = "openrouter" if use_openrouter else "anthropic"
        llm_client.log.warning("chat (%s) -> fallback: %s", where, getattr(e, "reason", type(e).__name__))
        ok = False
    except Exception as e:
        if use_openrouter:  # type only: exception text may quote prompt or creator data
            llm_client.log.warning("chat (openrouter) -> fallback: %s", type(e).__name__)
        ok = False
    if not ok:
        if state.tools_ran == 0 and not state.text_emitted:
            del history[start:]
            await fallback_turn(message, ctx, emit, _guard_done=bool(reason))
            return
        _repair_history(history, start)
        rendered = _render_last_tool(state, ctx, lang)
        if rendered:
            # The tool already ran (the report is built and stored): show its result with the
            # deterministic formatters instead of "try again", which would start a new run.
            await _say(emit, "\n\n" + rendered)
            history.append({"role": "assistant", "content": rendered})
            llm_client.record_mode("chat", "fallback")
            done: dict[str, Any] = {"llm_mode": "fallback", "lang": lang}
            if use_openrouter and state.model:
                done["llm_model"] = state.model
            await emit("done", done)
            return
        apology = _t(lang, "Omlouvám se, odpověď se nedokončila. Zkuste to prosím znovu.",
                     "Sorry, the reply did not finish. Please try again.")
        await _say(emit, "\n\n" + apology)
        history.append({"role": "assistant", "content": apology})
    llm_client.record_mode("chat", "llm")
    if use_openrouter and state.model:
        await llm_client.note_model("chat", state.model)
        await emit("done", {"llm_mode": "llm", "llm_model": state.model, "lang": lang})
        return
    await emit("done", {"llm_mode": "llm", "lang": lang})


def _render_last_tool(state: _TurnState, ctx: ChatContext, lang: str) -> str:
    """The deterministic reply for this turn's last successful result tool ("" when there is none)."""
    if state.last_tool is None:
        return ""
    name, inp, result = state.last_tool
    out = _Reply(lang)
    try:
        if name == "research_subject":
            args, err = validate_research_input(inp, lang)
            if err is not None or args is None:
                return ""
            tok = subject_token(str(args["subject"])) or SubjectToken(raw=str(args["subject"]),
                                                                      handle=str(args["subject"]).lstrip("@"), platform=None)
            brief = args["brief"]
            _subject_reply(out, result, tok, brief, args["anchor"] is None)
        elif name == "change_goal":
            brief = _validate_brief((inp or {}).get("brief") if isinstance(inp, dict) else None, lang)
            run = ctx.current_run()
            if brief is None:
                return ""
            if _is_subject_run(run):
                _subject_goal_reply(out, result, brief, run)
            else:
                out.add(f"Cíl změněn: {brief.business_type}. Stejné kandidáty teď posuzuji podle nových kritérií; rozdíl je na nástěnce.",
                        f"Goal changed: {brief.business_type}. The same candidates are re-evaluated with the new criteria; "
                        "the board shows the difference.")
                for line in _report_diff_lines(result, lang):
                    out.add(line)
        elif name == "start_deep_vetting":
            n = len(result.get("vetting") or []) if isinstance(result, dict) else 0
            out.add(f"Prověřuji do hloubky {n} finalistů; reporty se objeví na nástěnce. Nic se nikomu neposílá.",
                    f"Vetting {n} finalists in depth; the reports will appear on the board. Nothing is sent to anyone.")
    except Exception:
        return ""
    return out.text()


async def chat_events(message: str, ctx: ChatContext) -> AsyncIterator[tuple[str, dict]]:
    """Async-generator view of ``chat_turn``: yields (event, data) as they happen (chat.delta,
    chat.tool, criteria.updated) and ends after ``done``. Handy for the SSE endpoint."""
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def runner() -> None:
        try:
            await chat_turn(message, ctx, emit)
        except Exception as e:  # pragma: no cover - chat_turn handles its own errors
            await queue.put(("done", {"llm_mode": "fallback", "error": type(e).__name__}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while (item := await queue.get()) is not None:
            yield item
    finally:
        if not task.done():
            task.cancel()


# --------------------------------------------------------------------------------------------
# Offline fallback: deterministic, history-driven state machine
# --------------------------------------------------------------------------------------------

Q_TEXTS: dict[str, dict[str, str]] = {
    "q1": i18n("Co prodáváte a kde?", "What do you sell, and where?"),
    "q2": i18n("Komu chcete prodávat?", "Who do you want to sell to?"),
    "q3": i18n("Co má kampaň udělat?", "What should the campaign achieve?"),
    "q4": i18n("Kolik zhruba můžete dát a máte konkurenty, se kterými by tvůrce neměl spolupracovat?",
               "Roughly how much can you spend, and are there competitors the creator should not be working with?"),
    "run": i18n("Mám spustit hledání a první tři kola?", "Shall I start the search and the first three rounds?"),
    "vet": i18n("finalistů do hloubky?", "finalists in depth?"),
    "goal": i18n("Jaký je nový cíl?", "What is the new goal?"),
    # asked only when the q4 answer named no competitor and did not say "none"
    "q5": i18n("A konkurenti, se kterými by tvůrce neměl spolupracovat?", "Which competitors should the creator not be working with?"),
    # subject mode (one named creator): the anchor and the goal, one per turn. These are the fixed
    # markers; the full anchor question names the handle (see _ask_anchor).
    "sa": i18n("odkud tvůrce je (město), případně jaký má web nebo IČO?",
               "where is the creator based (city), or what is their website or company ID (IČO)?"),
    "sg": i18n("Jakou máte firmu a s čím vám má tvůrce pomoct?",
               "What is your business and what should the creator help with?"),
    # subject named without an account: ask for it (never search by a bare name)
    "sh": i18n("Jaký má účet na Instagramu nebo TikToku (@účet nebo odkaz na profil)?",
               "What is their Instagram or TikTok account (@handle or profile link)?"),
}
Q_HINTS: dict[str, dict[str, str]] = {
    "q1": i18n(" (Třeba „pekárna v Brně“.)", " (For example “a bakery in Brno”.)"),
    "q2": i18n(" Popište zákazníky svými slovy.", " Describe your customers in your own words."),
    "q3": i18n(" (Víc lidí v prodejně, nový produkt, přihlášky…)", " (More people in the shop, a new product, sign-ups…)"),
    "q4": i18n(" Rozpočet stačí orientačně, podle něj zvolím velikost tvůrců.",
               " A rough budget is enough; I use it to size the creators."),
    "goal": i18n(" Napište, co prodáváte a kde (např. „fitness studio v Brně“).",
                 " Tell me what you sell and where (e.g. “a fitness studio in Brno”)."),
    "q5": i18n(" Stačí jména nebo @účty, případně „žádní“.", " Names or @handles are enough, or “none”."),
    "sg": i18n(" Například: „moje pekárna v Brně, víc lidí v prodejně“.",
               " For example: “my bakery in Brno, more people in the shop”."),
    "sh": i18n(" Například @pekarna_kubik nebo instagram.com/pekarna_kubik.",
               " For example @pekarna_kubik or instagram.com/pekarna_kubik."),
}
_INTERVIEW = ("q1", "q2", "q3", "q4")
_INTERVIEW_ALL = _INTERVIEW + ("q5",)   # q5 = competitor follow-up (conditional)
_SUBJECT_Q = ("sa", "sg", "sh")         # subject mode: anchor, goal, the account of a named subject

# "What exactly do you check, and what not?" (a starter button): answered in fallback too.
_RX_WHAT_CHECK = re.compile(
    r"\bco (presne |vsechno |vlastne )?(kontrolujete|kontrolujes|overujete|proverujete|hlidate)|\bco nekontroluj|"
    r"\bwhat (exactly )?do you (check|verify|look at)|\bwhat do(n'?t| you not) (you )?check"
)


def _markers(text: str) -> list[tuple[int, str]]:
    found = []
    for qid, tx in Q_TEXTS.items():
        for v in tx.values():
            i = text.rfind(v)
            if i >= 0:
                found.append((i, qid))
    return sorted(found)


def _pending(msg: dict | None) -> str | None:
    if msg is None or msg.get("role") != "assistant":
        return None
    m = _markers(_msg_text(msg))
    return m[-1][1] if m else None


_RX_BUSINESS = re.compile(
    r"\b(mam|mame|vedu|vedeme|provozuj\w*|vlastn\w*|jsme|prodavam|prodavame|nabizim|nabizime)\b|"
    r"\b(we|i) (run|own|have|are|sell|make|bake|manage|operate)\b|\b(my|our) (shop|business|bakery|studio|cafe|store|gym|salon|restaurant)\b|"
    r"pekar|kavar|cukrar|fitness|studio|obchod|restaur|salon|e-?shop|bistro|\bshop\b|\bstore\b|bakery|\bcafe\b|\bgym\b|posilovn"
)


def _looks_like_business(text: str) -> bool:
    return bool(_RX_BUSINESS.search(fold(text)))


def _q1_from_refused(text: str) -> str | None:
    """The business (and city) of a message that also asked for something refused, as a clean first
    answer ("bakery Brno"); None when the message names no business."""
    if not _looks_like_business(text) or subject_token(text) is not None:
        return None
    bt = _business_from(text, "en")
    if not bt or len(bt) > 60:
        return None
    city = find_city(text)
    return f"{bt} {city}" if city else bt


def _interview_switch(answers: dict[str, str], pending: str | None, text: str) -> str | None:
    """A business switch while a later interview question is open -> the new first answer (keeping the
    earlier city when the switch names none); None for an ordinary answer."""
    if pending not in ("q2", "q3", "q4", "q5") or "q1" not in answers:
        return None
    f = fold(text)
    if not _RX_GOAL_SWITCH.search(f) or not (pick_preset(f) or _looks_like_business(text) or _is_business_text(f)):
        return None
    city = find_city(text) or find_city(answers.get("q1", ""))
    bt = _business_from(text, "en")
    return f"{bt} {city}" if city and not find_city(bt) else bt


def interview_state(history: list[dict]) -> tuple[dict[str, str], str | None, bool]:
    """Reconstruct (answers, pending question id, bot_has_spoken) from the history alone."""
    answers: dict[str, str] = {}
    pending: str | None = None
    spoke = False
    for m in history:
        role = m.get("role")
        if role == "assistant":
            spoke = True
            p = _pending(m)
            pending = p
        elif _is_owner_msg(m):
            text = _owner_text(m).strip()
            if text and refusal_reason(text):
                # "I run a bakery in Brno and want ... who are Catholic": the request is refused, but the
                # business in the same message still answers the first question (without the refused part)
                q1 = _q1_from_refused(text) if pending in (None, "q1") and not answers else None
                if q1:
                    answers["q1"] = q1
                continue
            if not text or _RX_WHAT_CHECK.search(fold(text)):
                continue
            sw = _interview_switch(answers, pending, text)
            if sw:
                answers["q1"] = sw   # "what about my fitness studio?" mid-interview: the business changes
                continue
            if pending in _INTERVIEW_ALL:
                answers[pending] = text
            elif pending is None and not answers and _looks_like_business(text) and subject_token(text) is None:
                answers["q1"] = text   # a "check @x for my bakery" message starts the subject flow instead
    return answers, pending, spoke


_RX_ACCUSATIVE = re.compile(r"\b(\w+?)(rnu|vnu|jnu|dnu|nu)\b")


_RX_GOAL_LEAD = re.compile(
    r"(?i)^\s*(?:(?:and|so|ok|okay|a|tak)\s*,?\s+)?(?:what about|how about|and for|for|změnit cíl na|zmenit cil na|změň cíl na|"
    r"zmen cil na|change (?:the |my )?goal to|switch (?:the )?goal to|new goal:?|nový cíl:?|novy cil:?|"
    r"(?:switch|go|change|move) back to|back to|přepni (?:zpět |zpátky )?na|prepni (?:zpet |zpatky )?na|zpátky na|zpět na|"
    r"a co (?:pro|třeba|treba)?|místo toho|misto toho)\s+"
)


def _business_from(a1: str, lang: str = "cs") -> str:
    t = a1.strip()
    t = re.sub(r"(?i)^\s*(dobr\w+ den|ahoj|zdrav\w*|hello|hi|hey|good (morning|afternoon|evening))[,!. ]*", "", t)
    t = _RX_GOAL_LEAD.sub("", t)
    t = re.sub(r"(?i)^\s*(?:actually|in fact|vlastně|vlastne|ve skutečnosti)\s*,?\s+", "", t)
    # "hledám influencera pro kavárnu", "looking for a creator for my café" -> the business only
    t = re.sub(r"(?i)^\s*(?:hledám|hledáme|hledam|hledame|sháním|shanim|chci najít|chci najit|(?:i am|i'm|we are|we're)?\s*looking for|"
               r"i want to find|we want to find|find me)\s+(?:an?\s+)?(?:\w+\s+){0,2}?(?:pro|for)\s+", "", t)
    t = re.sub(r"(?i)^\s*(mám|máme|mam|mame|vedu|vedeme|provozuj\w*|vlastn\w*|jsme|prodávám|prodáváme|we run|we own|we have|we are|"
               r"we'?ve got|we manage|we operate|we sell|i run|i own|i have|i am|i'm|i'?ve got|i manage|i operate|i sell)\s+(an?\s+)?", "", t)
    t = re.sub(r"(?i)^\s*(my|our|moje|moji|mou|můj|muj|naše|nase|naši|nasi|náš|nas|an?|the)\s+", "", t)
    t = re.split(r"(?i)\s+(v|ve|in|na)\s+|[,.;!?\n]", t)[0].strip()
    t = re.sub(r"(?i)\s+instead$", "", t).strip()
    if lang != "en":
        t = re.sub(r"(?i)\b(\w+)ou\b(?=\s+\w+nu\b)", lambda m: m.group(1) + "á", t)  # "malou kavárnu" -> "malá kavárnu"
        t = _RX_ACCUSATIVE.sub(lambda m: m.group(1) + m.group(2)[:-1] + "a", t)
        t = re.sub(r"(?i)\brestauraci\b", "restaurace", t)
    return clip(t, 60) or a1.strip()[:60]


_RX_NEGATIVE_COMP = re.compile(
    r"\b(nemam|nemame|zadn\w*|nevim|none|no competitors?|nikoho|nikdo|neni|nejsou|nobody|no one|"
    r"(do not|don'?t) have any|not really|(do not|don'?t) know|not sure|unsure|no idea|netusim|nejsem si jist\w*|"
    r"zatim nevim|nevime|dunno|idk|no clue|nah|n/?a)\b|^\s*(no|nope|ne|nic)\s*[.!]?\s*$"
)


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def _norm_brand(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(v))


def _brand_close(a: str, b: str) -> bool:
    """Is the owner's name ``a`` the known brand ``b`` (name or handle)? Typos count only for longer
    names, and never when a short distinguishing token differs ("Pekárna A" is not "Pekárna B")."""
    ka, kb = _norm_brand(a), _norm_brand(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if min(len(ka), len(kb)) < 6:
        return False
    short_a = {t for t in re.split(r"[^a-z0-9]+", fold(a)) if t and len(t) <= 2}
    short_b = {t for t in re.split(r"[^a-z0-9]+", fold(b)) if t and len(t) <= 2}
    if short_a != short_b:
        return False
    return _similar(ka, kb)


# Words that never occur in a brand name but do in a sentence ("do not want creators working with them",
# "budget is low", "what did I say?", "Instagram and TikTok").
_NOT_BRAND_WORDS = {
    "i", "we", "you", "they", "them", "he", "she", "it", "my", "our", "your", "do", "dont", "not", "want", "wants",
    "would", "should", "could", "working", "work", "works", "with", "about", "what", "did", "say", "said", "yet",
    "know", "sure", "idea", "budget", "low", "small", "high", "big", "maybe", "think", "creators", "creator",
    "influencers", "influencer", "please", "avoid", "any", "none", "no",
    "chci", "nechci", "chceme", "nechceme", "aby", "nimi", "jsem", "jsme", "mam", "mame", "rozpocet", "maly",
    "mal", "nizky", "zatim", "co", "rikal", "jsi", "tvurci", "tvurce", "spolupracovali", "spolupracuji", "nevim",
    "instagram", "tiktok", "youtube", "facebook", "insta",
}


def _brand_like(p: str) -> bool:
    words = [w for w in re.split(r"[^a-z0-9]+", fold(p)) if w]
    if not words or len(words) > 4:
        return False
    if any(w in _NOT_BRAND_WORDS for w in words):
        return False
    # a lone short lowercase fragment ("s", "sure yet") is not a name
    if len(_norm_brand(p)) < 2:
        return False
    return True


_RX_NAME_LEAD = re.compile(
    r"(?i)^(?:(?:i|we)\s+(?:would|want to|will|'d)\s+avoid|(?:please\s+)?avoid(?:ing)?|(?:i|we)\s+(?:do not|don'?t)\s+want|"
    r"nechci|nechceme|ne|bez|krome|kromě|hlavne|hlavně|treba|třeba|asi|not|except|mainly|maybe|"
    r"vyhnout se|vyhýbám se|vyhybam se)\s+"
)


_RX_COMP_LEAD = re.compile(r"(?i)^.*?\b(?:konkuren\w*|competitors?|competition)\b\s*(?:je|jsou|is|are|:|-|–)?\s*")


def _paired_names(text: str) -> list[tuple[str, str]]:
    """"Bakery B @pekarna_b", "Bakery B (@pekarna_b)" -> [("Bakery B", "pekarna_b")]: a name written
    right before a handle names that handle."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"@([A-Za-z0-9_.]+)", text):
        before = text[:m.start()].rstrip(" (")
        seg = re.split(r"[,;:\n()]|\s+(?:and|or|a|nebo)\s+|@[A-Za-z0-9_.]+", before)[-1]
        seg = _RX_COMP_LEAD.sub("", seg)
        seg = _RX_NAME_LEAD.sub("", seg.strip(" .!?\"'„“”()-–"))
        if seg and len(seg) <= 40 and re.search(r"[^\W\d_]", seg) and not re.search(r"\d", seg) \
                and not _RX_NEGATIVE_COMP.search(fold(seg)) and not re.search(r"(?i)\b(konkuren|competit)", seg) \
                and not _RX_CHECK_VERB.search(fold(seg)):
            out.append((seg, norm_handle(m.group(1).strip("."))))
    return out


def parse_competitors(text: str, known: list[dict] | None = None) -> list[dict]:
    """Owner's answer -> [{"name", "handles"}]; names close to a known competitor reuse its handles;
    a name written right before a handle ("Bakery B @pekarna_b") is that handle's name."""
    known = known or []
    f = fold(text)
    handles = [h.strip(".") for h in re.findall(r"@([A-Za-z0-9_.]+)", text)]
    if not handles and _RX_NEGATIVE_COMP.search(f) and not re.search(r"konkuren\w*\s*(je|jsou|:)", f):
        return []
    paired = _paired_names(text)
    paired_handles = {h for _, h in paired}
    paired_names = {_norm_brand(n) for n, _ in paired}
    handles = [h for h in handles if norm_handle(h) not in paired_handles]
    rest = re.sub(r"@[A-Za-z0-9_.]+", " ", text)
    m = re.search(r"(?i)(?:konkuren\w*|competitors?|competition)\s*(?:je|jsou|is|are|:|-|–)?\s*(.+)", rest)
    # "Nechci tvůrce, kteří spolupracují s Lidl." / "no creators who work with Lidl": the brand after it
    m = m or re.search(r"(?i)\b(?:spolupracuj\w*|spolupracoval\w*|propaguj\w*|work(?:s|ing|ed)? with|"
                       r"collaborat\w* with|partner\w* with|promot(?:e|es|ing))\s+(?:se?\s+|s\s+|pro\s+)?(.+)", rest)
    chunk = m.group(1) if m else ", ".join(s for s in re.split(r"[.;,\n]", rest) if s.strip() and not re.search(r"\d", s))
    names: list[str] = []
    for part in re.split(r",|;|\.|\s+a\s+|\s+and\s+|\s+nebo\s+|\s+or\s+", chunk):
        p = _RX_NAME_LEAD.sub("", part.strip(" .!?\"'„“”()"))
        p = p.strip(" .!?\"'„“”()")
        if p and len(p) <= 40 and not re.search(r"\d", p) and not _RX_NEGATIVE_COMP.search(fold(p)) and _brand_like(p):
            names.append(p)
    out: list[dict] = [{"name": n, "handles": [h]} for n, h in paired]
    out += [{"name": h, "handles": [norm_handle(h)]} for h in handles]
    names = [n for n in names if _norm_brand(n) not in paired_names]
    for n in names:
        key = _norm_brand(n)
        hit = next((k for k in known if _brand_close(n, k.get("name", ""))
                    or any(_brand_close(n, h) for h in k.get("handles") or [])), None)
        out.append(dict(hit) if hit else {"name": n, "handles": []})
    for i, c in enumerate(out):  # a bare @handle that is a known competitor gets its proper name
        hit = next((k for k in known if any(_norm_brand(h) == _norm_brand(c["name"]) for h in k.get("handles") or [])), None)
        if hit:
            out[i] = dict(hit)
    dedup: list[dict] = []
    seen: set[str] = set()
    for c in out:
        k = _norm_brand(c.get("name") or "")
        if k and k not in seen:
            seen.add(k)
            dedup.append({"name": c.get("name"), "handles": list(c.get("handles") or [])})
    return dedup


def _budget_from(text: str) -> str | None:
    for s in re.split(r"(?<!\d)[.;\n]|[.;\n](?!\d)|,\s*(?=konkuren|competit)", text):
        if re.search(r"\d", s):
            s = re.split(r",\s*(?!\d)", s)[0]   # "CZK 20,000, no competitors" -> "CZK 20,000"
            return clip(s.strip(), 80)
    f = fold(text)
    if re.search(r"\b(nevim|malo|skoro nic|nothing|not sure|nejsem si jist)\b", f):
        return clip(text.strip(), 80)
    return None


def needs_competitor_followup(answers: dict[str, str]) -> bool:
    """q4 bundles budget and competitors; when its answer names no competitor and does not say
    "none", ask separately (otherwise the competitor check would silently have nothing to check)."""
    if "q4" not in answers or "q5" in answers:
        return False
    a1 = answers.get("q1", "")
    name = pick_preset(a1) or pick_preset(" ".join(answers.get(q, "") for q in ("q1", "q2", "q3")))
    known = load_preset(name).brief.competitors if name else []
    a4 = answers["q4"]
    return not parse_competitors(a4, known) and not _RX_NEGATIVE_COMP.search(fold(a4))


def _names_preset_business(text: str, preset_bt: str) -> bool:
    """Does the owner's text name the preset's own business ("pekárnu" / "bakery" for "pekárna")?"""
    f = fold(text)
    # the first word carries the business ("fitness" in "fitness studio"; "studio" alone is no match)
    stems = [w[:5] for w in re.split(r"[^a-z0-9]+", fold(preset_bt)) if len(w) >= 4][:1]
    alias = {"pekar": ("bakery", "baker", "pekar"), "baker": ("bakery", "baker", "pekar"),
             "fitne": ("fitness", "gym", "posilov"), "kavar": ("kavar", "cafe", "coffee")}
    for st in stems:
        for a in alias.get(st, (st,)):
            if a in f:
                return True
    return False


def build_criteria_from_answers(answers: dict[str, str], lang: str, history: list[dict] | None = None) -> CriteriaSet:
    a1, a2, a3, a4 = (answers.get(q, "") for q in _INTERVIEW)
    a5 = answers.get("q5", "")
    all_text = " ".join([a1, a2, a3])
    name = pick_preset(a1) or pick_preset(all_text)
    city = find_city(a1) or find_city(all_text)
    known = load_preset(name).brief.competitors if name else []
    if name:
        bt = preset_brief_for(name, lang).business_type   # "bakery" in English, "pekárna" in Czech
        own = _business_from(a1, lang) if a1.strip() else ""
        if own and not _names_preset_business(a1, bt):
            # The preset only lends the criteria: a café owner's brief stays "kavárna", not "pekárna".
            bt = own
    else:
        bt = _business_from(a1, lang)
    competitors = parse_competitors(a4, known) or (parse_competitors(a5, known) if a5 else [])
    brief = Brief(
        business_type=bt, city=city, audience=clip(a2, 300), goal=clip(a3, 300),
        budget_hint=_budget_from(a4), competitors=competitors, lang=lang,  # type: ignore[arg-type]
    )
    brief, brief_refused = sanitize_brief(brief)
    return criteria_for_brief(brief, refused=history_refusals(history or [], lang) + brief_refused)


_RX_AFFIRM = re.compile(
    r"^\s*(ano|jo|jj|jasne|jasan|ok|okej|okay|yes|yep|sure|urcite|do toho|spust\w*|proved\w*|prover\w*|go|"
    r"pojdme|pojd|prosim|klidne|muzes|muzete|rozhodne|of course|please|let'?s)\b"
)
_RX_DENY = re.compile(r"^\s*(ne|nee|no|nope|zatim ne|pozdeji|later|not now|nechci)\b")
_RX_WHY = re.compile(r"\bproc\b|\bwhy\b")
_RX_WHY_DROP = re.compile(r"vypadl|vyrazen|vyradil|neprosel|nepostoupil|chybi|drop|eliminat|\bout\b|remov|fail|kicked")
_RX_GOAL = re.compile(r"zmen\w* cil|jiny cil|novy cil|zmenit cil|zmena cile|change (the |my )?goal|new goal|other goal|different goal|switch (the )?goal|misto (pekarny|fitness)")
_RX_VET = re.compile(r"prover|proved\w* (hloubk|prover)|hloubk|\bdeep\b|\bvet\b|\bvetting\b|\bkolo 4\b|round 4")
_RX_RUN = re.compile(r"\bspust|\bhledej|\bnajdi|\bzacni|\bstart\b|\brun\b|\bgo\b|\bsearch\b|kola? 1|rounds?\b")
_RX_OUTREACH = re.compile(r"osloven|\boslov|napis\w* (zprav|email|mail)|\bkoncept|\bdraft|outreach|write (a |the )?message|"
                          r"\bmessage (for|to)\b|first message|zprav\w* pro")
_RX_DISABLE = re.compile(r"\b(vypni|vypnout|zrus|zrusit|ignoruj|nepouzivej|disable|turn off|remove)\s+(.+)")
_RX_ENABLE = re.compile(r"\b(zapni|zapnout|enable|turn on)\s+(.+)")
_RX_FOLLOWERS = re.compile(r"sledujic|followers|fanousk")
_RX_BEST = re.compile(r"nejlepsi|\bbest\b|\bwinner\b|vitez")
_STOP = {"jsi", "je", "byl", "byla", "bylo", "ten", "ta", "to", "the", "he", "she", "it", "mi", "nam", "ucet", "account",
         "proc", "why", "was", "did", "is", "vypadl", "vypadla", "vypadlo", "vyrazen", "vyrazena", "kandidat",
         "in", "so", "many", "much", "were", "are", "they", "them", "others", "other", "all", "round", "rounds",
         "https", "http", "www", "kole", "kolo", "kolech", "tolik", "ostatni", "vsichni", "of", "at", "on", "v", "ve", "a",
         "an", "this", "that", "these", "those", "who", "kdo", "co", "what"}
_RX_AGGREGATE = re.compile(r"\b(so many|how many|the others|everyone|all of them|most of them|tolik|kolik|ostatni|vsichni|"
                           r"vetsina)\b|\b(?:round|kol[eo]|kolu)\s*\d|\b\d\.?\s*(?:round|kol[eo])\b")


def _handle_from(message: str, run: Run | None = None) -> str | None:
    m = re.search(r"@([A-Za-z0-9_.]+)", message)
    if m:
        return m.group(1).strip(".")
    tok = subject_token(message)   # a profile link ("why was https://www.instagram.com/x/ eliminated")
    if tok is not None:
        return tok.handle
    f = fold(message)
    if run is not None:
        # a display name ("why was Adam Bartoš eliminated?") -> that candidate's handle
        for c in run.candidates.values():
            dn = fold(c.profile.display_name) if c.profile is not None and c.profile.display_name else ""
            dn = re.sub(r"\s*\([^)]*\)\s*$", "", dn).strip()   # "Adam Bartoš (MOCK)" -> "adam bartos"
            if len(dn) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(dn)}(?![a-z0-9])", f):
                return c.ref.handle
    for rx in (
        r"(?:vypadl\w*|vyrazen\w*|vyradil\w*|neprosel\w*|nepostoupil\w*|dropped|eliminated|out|pro|for)\s+(?:je\s+|ucet\s+|account\s+)?([a-z0-9_.]+)",
        r"\bproc\s+(?:je\s+|byl\w*\s+)?([a-z0-9_.]+)\s+(?:vypadl|vyrazen|neprosel|nepostoupil)",
        r"\bwhy\s+(?:was|did|is)\s+([a-z0-9_.]+)",
    ):
        for mm in re.finditer(rx, f):
            h = mm.group(1).strip(".")
            if h and h not in _STOP and len(h) > 1:
                return h
    return None


def _followers_update(f: str) -> dict | None:
    if not _RX_FOLLOWERS.search(f):
        return None
    f = _ungroup(f)

    def val(num: str, unit: str | None) -> int:
        x = _num(num) or 0
        return int(x * 1000) if unit and (unit.startswith("tis") or unit == "k") else int(x)

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(tis\w*|k)?\s*(?:az|-|–|do|to)\s*(\d+(?:[.,]\d+)?)\s*(tis\w*|k)?", f)
    if m:
        hi_unit = m.group(4)
        lo_unit = m.group(2) or hi_unit
        return {"min": val(m.group(1), lo_unit), "max": val(m.group(3), hi_unit)}
    m = re.search(r"(max\w*|nejvys\w*|nanejvys|at most|up to|do)\s*(\d+(?:[.,]\d+)?)\s*(tis\w*|k)?", f)
    if m:
        return {"max": val(m.group(2), m.group(3))}
    m = re.search(r"(min\w*|aspon|alespon|at least|od)\s*(\d+(?:[.,]\d+)?)\s*(tis\w*|k)?", f)
    if m:
        return {"min": val(m.group(2), m.group(3))}
    return None


def _match_criterion(cs: CriteriaSet, target: str) -> Criterion | None:
    words = [w for w in re.findall(r"[a-z0-9_]+", fold(target)) if len(w) > 2]
    best, score = None, 0
    for c in cs.criteria:
        hay = fold(" ".join([c.id, c.kind.replace("_", " "), c.label.get("cs", ""), c.label.get("en", "")]))
        s = sum(1 for w in words if w[:5] in hay)
        if s > score:
            best, score = c, s
    return best


class _Reply:
    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.parts: list[str] = []

    def add(self, cs: str, en: str | None = None) -> None:
        self.parts.append(cs if (self.lang == "cs" or en is None) else en)

    def text(self) -> str:
        return "\n\n".join(p for p in self.parts if p)


async def fallback_turn(message: str, ctx: ChatContext, emit: Emit, *, _guard_done: bool = False) -> None:
    """Scripted, deterministic interview (no key). Same events as chat_turn."""
    lang = _owner_lang_choice(ctx) or effective_lang(ctx.history, message, ctx.lang)
    _set_ctx_lang(ctx, lang)
    history = ctx.history
    answers, pending, spoke = interview_state(history)
    history.append({"role": "user", "content": message})
    out = _Reply(lang)
    try:
        await _fallback_logic(message, ctx, emit, out, answers, pending, spoke, _guard_done)
    except Exception as e:  # never leave the owner without an answer
        out.add(f"Něco se nepovedlo ({type(e).__name__}). Zkuste to prosím znovu.",
                f"Something went wrong ({type(e).__name__}). Please try again.")
    text = out.text()
    if text:
        await _say(emit, text)
    history.append({"role": "assistant", "content": text or "…"})
    llm_client.record_mode("chat", "fallback")
    await emit("done", {"llm_mode": "fallback", "lang": lang})


def _ask(out: _Reply, qid: str) -> None:
    out.add(Q_TEXTS[qid]["cs"] + Q_HINTS.get(qid, {}).get("cs", ""), Q_TEXTS[qid]["en"] + Q_HINTS.get(qid, {}).get("en", ""))


def _reask(out: _Reply, qid: str) -> None:
    """Ask the pending question again after a detour (a refusal, "what do you check?")."""
    if qid == "sa":
        out.add("Zpátky k otázce: " + Q_TEXTS["sa"]["cs"] + " Můžete napsat i „přeskočit“.",
                "Back to the question: " + Q_TEXTS["sa"]["en"] + " You can also say “skip”.")
    else:
        _ask(out, qid)


def _set_ctx_lang(ctx: ChatContext, lang: str) -> None:
    try:
        ctx.lang = lang  # type: ignore[misc]
    except Exception:
        pass


async def _propose(ctx: ChatContext, emit: Emit, cs: CriteriaSet) -> Any:
    result = await ctx.propose_criteria(cs)
    await _emit_tool(emit, "propose_criteria", {"brief": cs.brief, "criteria": [c.id for c in cs.criteria]}, result)
    await emit("criteria.updated", {"criteria": cs})
    return result


async def _fallback_logic(
    message: str, ctx: ChatContext, emit: Emit, out: _Reply, answers: dict[str, str], pending: str | None,
    spoke: bool, guard_done: bool,
) -> None:
    lang = out.lang
    f = fold(message)
    cs = ctx.current_criteria()
    run_now = ctx.current_run()
    if pending == "run" and run_now is not None and (run_now.rounds or run_now.candidates):
        # the rounds were started from the board meanwhile: "shall I start?" is no longer open
        pending = None

    # 1. Sensitive / scoring request: refuse in one sentence, record, continue where we were.
    reason = refusal_reason(message)
    if reason:
        await _record_refusal(ctx, message, reason, emit)
        if not guard_done:
            out.add(reason["cs"], reason["en"])
        q1 = _q1_from_refused(message) if cs is None and not answers and pending in (None, "q1") else None
        if q1:
            # the rest of the message still counts: keep the business and go on with the interview
            bt = _business_from(q1, lang)
            city = find_city(q1)
            if city:  # "bakery Brno" + " in Brno" would name the city twice
                bt = re.sub(rf"(?i)\s*\b(?:in |v |ve )?{re.escape(city)}\b", "", bt).strip() or bt
            out.add(f"Ostatní beru: {bt}{(' ' + cs_locative(city)) if city else ''}.",
                    f"The rest I can use: {bt}{(' in ' + city) if city else ''}.")
            _ask(out, "q2")
        elif pending in _INTERVIEW_ALL or pending in _SUBJECT_Q:
            if pending == "sa":
                _reask(out, pending)
            else:
                out.add("Zpátky k otázce: " + Q_TEXTS[pending]["cs"], "Back to the question: " + Q_TEXTS[pending]["en"])
        elif cs is None and not answers:
            _ask(out, "q1")
        elif pending == "vet" and finalists(ctx.current_run()):
            n = min(len(finalists(ctx.current_run())), MAX_FINALISTS)
            out.add(f"Prověřit {n} {Q_TEXTS['vet']['cs']}", f"Vet {n} {Q_TEXTS['vet']['en']}")
        elif pending in ("run", "goal"):
            _ask(out, pending)
        elif _is_subject_run(ctx.current_run()):
            _subject_help(out, ctx.current_run())
        elif finalists(ctx.current_run()):
            out.add("Můžu ale porovnat finalisty podle jednoho kritéria, které vyberete, nebo vysvětlit, proč kdo vypadl.",
                    "I can compare the finalists by one criterion you pick, or explain why someone dropped out.")
        else:
            out.add("Můžu upravit kritéria nebo spustit hledání („spusť“).",
                    "I can adjust the criteria or start the search (“run”).")
        return

    # 1b. "What exactly do you check, and what not?": plain answer, then back to where we were.
    if _RX_WHAT_CHECK.search(f):
        if _is_subject_run(run_now) or pending in _SUBJECT_Q:
            _explain_scope_subject(out)
        else:
            _explain_scope(out)
        if pending in _INTERVIEW_ALL or pending in ("run", "goal") or pending in _SUBJECT_Q:
            _reask(out, pending)
        elif cs is None and not answers:
            if not spoke:
                out.add("Zeptám se na čtyři krátké věci.", "I will ask four short questions.")
            _ask(out, "q1")
        return

    # 2. Demo shortcut: "demo" / "demo fitness" -> preset criteria straight away.
    if re.match(r"^\s*demo\b", f):
        name = pick_preset(f) or "bakery"
        new = criteria_for_brief(preset_brief_for(name, lang), history_refusals(ctx.history, lang))
        await _propose(ctx, emit, new)
        out.add(f"Ukázkové zadání: {new.brief.business_type} {cs_locative(new.brief.city)}. Navrhuji tato kritéria:",
                f"Demo brief: {new.brief.business_type}, {new.brief.city}. I suggest these criteria:")
        out.add(describe_criteria(new, lang))
        _ask(out, "run")
        return

    # 2b. Subject mode: the owner names one creator to check (or answers the anchor / goal question).
    run0 = ctx.current_run()
    earlier = ctx.history[:-1]
    first = not any(_is_owner_msg(m) and _owner_text(m).strip() for m in earlier)
    tok = is_subject_request(message, pending, first, run0)
    thread = _subject_thread(earlier) if (tok is None or pending == "sh") else []
    if tok is None and thread and pending == "sa" and _anchor_detour(message):
        _anchor_detour_reply(out, message, subject_token(thread[0][0]))
        return
    if tok is None and not thread and pending not in ("q2", "q3", "q4", "q5") and subject_name(message):
        thread = [(message, pending)]
        await _fallback_subject(thread, ctx, emit, out, cs)
        return
    if tok is not None or thread:
        if tok is not None and pending == "sh" and thread:
            msgs = thread + [(message, pending)]
        else:
            msgs = [(message, pending)] if tok is not None else thread + [(message, pending)]
        await _fallback_subject(msgs, ctx, emit, out, cs)
        return
    if pending is None and _post_link(message) and (first or _RX_CHECK_VERB.search(f)):
        out.add("To je odkaz na příspěvek nebo video. Pošlete prosím odkaz na profil (instagram.com/… nebo tiktok.com/@…) nebo @handle.",
                "That is a link to a post or video. Please send the profile link (instagram.com/… or tiktok.com/@…) or the @handle.")
        return

    # 3. Interview (no criteria yet, or a question is pending).
    if cs is None or pending in _INTERVIEW_ALL:
        sw = _interview_switch(answers, pending, message)
        if sw:
            answers["q1"] = sw
            bt = _business_from(sw, lang)
            city = find_city(sw)
            out.add(f"Dobře, beru: {bt}{(' ' + cs_locative(city)) if city else ''}.",
                    f"OK, switching to: {bt}{(' in ' + city) if city else ''}.")
            _reask(out, pending)
            return
        if pending in _INTERVIEW_ALL:
            answers[pending] = message.strip()
        elif not answers and _looks_like_business(message):
            answers["q1"] = message.strip()
        nxt = next((q for q in _INTERVIEW if q not in answers), None)
        if nxt is None and needs_competitor_followup(answers):
            nxt = "q5"
        if not spoke:
            out.add("Dobrý den! Pomůžu vám najít tvůrce na sociálních sítích, kteří sedí k vaší firmě. Zeptám se na čtyři krátké věci.",
                    "Hello! I will help you find social-media creators who fit your business. I will ask four short questions.")
        if nxt is not None:
            if nxt == "q2" and "q1" in answers:
                bt = _business_from(answers["q1"], lang)
                city = find_city(answers["q1"])
                out.add(f"Rozumím: {bt}{(' ' + cs_locative(city)) if city else ''}.",
                        f"Got it: {bt}{(' in ' + city) if city else ''}.")
            elif pending in _INTERVIEW_ALL:
                out.add("Díky.", "Thanks.")
            _ask(out, nxt)
            return
        new = build_criteria_from_answers(answers, lang, ctx.history)
        await _propose(ctx, emit, new)
        b = new.brief
        loc = cs_locative(b.city)
        out.add(f"Díky, mám vše. Zadání: {b.business_type}{(' ' + loc) if loc else ''}. Navrhuji tato kritéria; každé můžete upravit nebo vypnout:",
                f"Thanks, that is everything. Brief: {b.business_type}{(', ' + b.city) if b.city else ''}. I suggest these criteria; you can edit or switch off any of them:")
        out.add(describe_criteria(new, lang))
        out.add("Věk, pohlaví ani původ publika neodhadujeme; jazyk komentářů a lokální zmínky jsou jen veřejné signály. Nejlepšího tvůrce nevybírám, rozhodujete vy.",
                "We do not estimate audience age, gender or origin; comment language and local mentions are public signals only. I do not pick a best creator; you decide.")
        _ask(out, "run")
        return

    run = ctx.current_run()

    # 4. Pending yes/no questions.
    if pending == "goal" and not _RX_DENY.search(f):
        await _fallback_goal(message, ctx, emit, out, cs)
        return
    if pending == "vet" and _RX_AFFIRM.search(f):
        await _fallback_vet(ctx, emit, out, run, message)
        return
    if pending == "run" and _RX_AFFIRM.search(f):
        await _fallback_run(ctx, emit, out)
        return
    if pending in ("run", "vet") and not _RX_AFFIRM.search(f) and not _RX_DENY.search(f):
        if await _fallback_competitors(message, ctx, emit, out, cs, pending):
            return
    if pending in ("vet", "run", "goal") and _RX_DENY.search(f):
        out.add("Dobře. Kdykoli napište, co dál: „spusť“, „prověř finalisty“, „proč vypadl @…?“ nebo „změnit cíl“.",
                "OK. Just tell me what next: “run”, “vet the finalists”, “why did @… drop out?” or “change goal”.")
        return

    # 5. Explicit intents.
    subject_run = _is_subject_run(run)
    if _RX_WHY.search(f) and (_RX_WHY_DROP.search(f) or "@" in message):
        await _fallback_explain(message, ctx, emit, out, run)
        return
    if _RX_GOAL.search(f):
        if pick_preset(f) or (_looks_like_business(message) and len(f) > 25):
            await _fallback_goal(message, ctx, emit, out, cs)
        else:
            _ask(out, "goal")
        return
    if _RX_GOAL_SWITCH.search(f) and (pick_preset(f) or _looks_like_business(message) or _is_business_text(f)):
        # "what about my fitness studio?", "a co pro moje fitness studio?", "for my café instead"
        await _fallback_goal(message, ctx, emit, out, cs)
        return
    if _RX_OUTREACH.search(f):
        await _fallback_outreach(message, ctx, emit, out, run, cs)
        return
    if _RX_VET.search(f):
        await _fallback_vet(ctx, emit, out, run, message)
        return
    fu = _followers_update(f)
    if fu:
        crit = next((c for c in cs.criteria if c.kind == "followers_range"), None)
        if crit is not None:
            params = _clean_params("followers_range", {**crit.params, **fu})
            result = await ctx.update_criterion(crit.id, params, None)
            await _emit_tool(emit, "update_criterion", {"criterion_id": crit.id, "params": params}, result)
            new_cs = ctx.current_criteria() or cs
            await emit("criteria.updated", {"criteria": new_cs})
            shown = crit.model_copy(update={"params": {**crit.params, **params}})
            out.add(f"Upraveno: {shown.label.get('cs')} – {describe_params(shown, 'cs', new_cs.brief)}.",
                    f"Updated: {shown.label.get('en')} – {describe_params(shown, 'en', new_cs.brief)}.")
            for line in _report_diff_lines(result, lang):
                out.add(line)
            return
    for rx, enabled in ((_RX_DISABLE, False), (_RX_ENABLE, True)):
        m = rx.search(f)
        if m:
            crit = _match_criterion(cs, m.group(2))
            if crit is None:
                out.add("Nevím, které kritérium myslíte. Napište třeba „vypni formát“.",
                        "I am not sure which criterion you mean. Try “turn off format”.")
                return
            result = await ctx.update_criterion(crit.id, None, enabled)
            await _emit_tool(emit, "update_criterion", {"criterion_id": crit.id, "enabled": enabled}, result)
            await emit("criteria.updated", {"criteria": ctx.current_criteria() or cs})
            out.add(f"Kritérium „{crit.label.get('cs')}“ je {'zapnuté' if enabled else 'vypnuté'}.",
                    f"Criterion “{crit.label.get('en')}” is {'on' if enabled else 'off'}.")
            line = _funnel_change_line(result, lang)
            if line:
                out.add(line)
            for line in _report_diff_lines(result, lang):
                out.add(line)
            return
    if _RX_BEST.search(f):
        out.add("Nejlepšího tvůrce nevybírám. U každého finalisty ukážu důkazy po kritériích a v porovnání je můžete seřadit podle jednoho kritéria, které vyberete.",
                "I do not pick a best creator. For each finalist I show the evidence per criterion; in the comparison you can sort by one criterion you pick.")
        return
    if subject_run:
        _subject_help(out, run)
        return
    tok = subject_token(message)
    if tok is not None and _RX_CHECK_VERB.search(f) and find_candidate(run, tok.handle) is not None:
        # "check @anna" for a candidate of this discovery run: where she stands and why
        await _fallback_explain(message, ctx, emit, out, run)
        return
    if _RX_RUN.search(f) or (_RX_AFFIRM.search(f) and run is None):
        await _fallback_run(ctx, emit, out)
        return
    out.add("Můžu: spustit kola („spusť“), vysvětlit vyřazení („proč vypadl @…?“), prověřit finalisty („prověř finalisty“), "
            "změnit cíl („změnit cíl na fitness studio“), upravit kritérium („max 30 tisíc sledujících“, „vypni formát“) "
            "nebo připravit koncept oslovení („oslovení pro @…“). Nejlepšího tvůrce nevybírám – rozhodujete vy podle důkazů.",
            "I can: run the rounds (“run”), explain an elimination (“why did @… drop out?”), vet the finalists (“vet the finalists”), "
            "change the goal (“change goal to a fitness studio”), edit a criterion (“max 30k followers”, “turn off format”) "
            "or prepare an outreach draft (“outreach for @…”). I do not pick a best creator – you decide based on the evidence.")


def _explain_scope(out: _Reply) -> None:
    from app.rounds.r4_vetting import NOT_CHECKED

    out.add(
        "Kontrolujeme jen veřejná data, ve čtyřech kolech:\n"
        "1. Základ: veřejný účet, velikost, aktivita, tvůrce vs. firma, čeština v popiscích.\n"
        "2. Obsah: témata, formáty, frekvence postů, podíl reklamy.\n"
        "3. Veřejné signály publika: interakce, jazyk komentářů, lokální zmínky, podíl obecných komentářů (ne demografie).\n"
        "4. Hloubková prověrka finalistů, jen po vašem souhlasu: spolupráce a konkurence, označování reklamy, tvrzení vs. záznam, zprávy, účty na jiných sítích.",
        "We check public data only, in four rounds:\n"
        "1. Basics: public account, size, activity, creator vs. company, Czech captions.\n"
        "2. Content: topics, formats, posting frequency, share of ads.\n"
        "3. Public audience signals: engagement, comment language, local mentions, share of generic comments (not demographics).\n"
        "4. Deep vetting of finalists, only after you confirm: collaborations and competitors, ad disclosure, claims vs. record, news, accounts on other networks.",
    )
    out.add("Co nekontrolujeme:\n" + "\n".join(f"– {x['cs']}" for x in NOT_CHECKED)
            + "\nNejlepšího tvůrce nevybíráme a nikomu nic neposíláme.",
            "What we do not check:\n" + "\n".join(f"– {x['en']}" for x in NOT_CHECKED)
            + "\nWe do not pick a best creator and nothing is ever sent.")


def _explain_scope_subject(out: _Reply) -> None:
    """How a single-creator report is built (subject mode)."""
    from app.rounds.r4_vetting import NOT_CHECKED

    out.add(
        "U jednoho tvůrce postupuji takto:\n"
        "1. Identita: je to účet, který myslíte? Porovnám ho s vaší kotvou (město, web nebo IČO) a s propojenými účty; "
        "jmenovce a podobné účty dám stranou a řeknu proč.\n"
        "2. Kontroly pro váš cíl: velikost, aktivita, témata, formáty, reklama, signály publika. Nic se nevyřazuje, "
        "každá kontrola ukáže hodnotu a zdroj.\n"
        "3. Prověrka: starší posty, spolupráce a konkurence, označování reklamy, tvrzení vs. záznam, zprávy.\n"
        "Každé zjištění je označené: fakt (se zdrojem), odvození (z čeho) nebo mezera (co nevíme). Skóre ani "
        "„dobrý/špatný“ tvůrce nedávám.",
        "For one creator I work like this:\n"
        "1. Identity: is this the account you mean? I compare it with your anchor (city, website or company ID) and "
        "linked accounts; namesakes and look-alikes are set aside with the reason.\n"
        "2. Checks for your goal: size, activity, topics, formats, ads, audience signals. Nothing is eliminated; "
        "every check shows its value and source.\n"
        "3. Vetting: older posts, collaborations and competitors, ad disclosure, claims vs. record, news.\n"
        "Every finding is tagged: fact (with a source), inference (from what) or gap (what we do not know). "
        "There is no score and no “good/bad creator” verdict.",
    )
    out.add("Co nekontrolujeme:\n" + "\n".join(f"– {x['cs']}" for x in NOT_CHECKED) + "\nNic nikomu neposílám.",
            "What we do not check:\n" + "\n".join(f"– {x['en']}" for x in NOT_CHECKED) + "\nNothing is ever sent.")


async def _fallback_competitors(message: str, ctx: ChatContext, emit: Emit, out: _Reply, cs: CriteriaSet,
                                pending: str | None) -> bool:
    """Competitor names after the criteria were proposed (e.g. the owner answered only the budget):
    add them to the brief so the competitor check has something to check. True when handled."""
    f = fold(message)
    if (_RX_CHECK_VERB.search(f) or _RX_WHY.search(f)) and not re.search(r"konkuren|competit", f):
        return False   # "check @x" / "why did @x drop out?" name a creator, not a competitor
    name = pick_preset(f"{cs.brief.business_type} {cs.brief.goal}")
    known = load_preset(name).brief.competitors if name else []
    comps = parse_competitors(message, known)
    if not comps:
        return False
    known_keys = {_norm_brand(k.get("name", "")) for k in known}
    if not (re.search(r"konkuren|competit", f) or "@" in message
            or all(_norm_brand(c.get("name", "")) in known_keys for c in comps)):
        return False
    merged = list(cs.brief.competitors)
    have = {_norm_brand(c.get("name", "")) for c in merged}
    added = [c for c in comps if _norm_brand(c.get("name", "")) not in have]
    if not added:
        return False
    merged += added
    new = cs.model_copy(deep=True)
    new.brief = new.brief.model_copy(update={"competitors": merged})
    for i, c in enumerate(new.criteria):
        if c.kind == "no_competitor_collab":
            new.criteria[i] = c.model_copy(update={"why": _competitor_why(new.brief)})
    await _propose(ctx, emit, new)
    names = ", ".join(c.get("name") or "?" for c in added)
    out.add(f"Doplněno do zadání – konkurence: {names}. Kritérium „Bez spolupráce s konkurencí“ je bude hlídat.",
            f"Added to the brief – competitors: {names}. The “No competitor collaboration” criterion will check them.")
    if pending == "run" and ctx.current_run() is None:
        _ask(out, "run")
    return True


async def _fallback_run(ctx: ChatContext, emit: Emit, out: _Reply) -> None:
    result = await ctx.run_rounds(3)
    await _emit_tool(emit, "run_rounds", {"up_to": 3}, result)
    run = ctx.current_run()
    summary = rounds_summary(run, out.lang)
    fin = finalists(run)
    done = run is not None and any(isinstance(r, dict) and r.get("round") == 3 for r in run.rounds)
    if done:
        out.add(f"Hotovo: {summary}. Každé vyřazení má na nástěnce kolo, důvod a zdroj.",
                f"Done: {summary}. Every elimination on the board shows the round, the reason and the source.")
        if fin:
            n = min(len(fin), MAX_FINALISTS)
            extra_cs = f" (najednou nejvýš {MAX_FINALISTS} z {len(fin)})" if len(fin) > MAX_FINALISTS else ""
            extra_en = f" (at most {MAX_FINALISTS} of {len(fin)} at once)" if len(fin) > MAX_FINALISTS else ""
            out.add(f"Zůstalo {len(fin)} finalistů. Hloubková prověrka projde starší posty, spolupráce, konkurenci, označování reklamy a zprávy{extra_cs}. "
                    f"Prověřit {n} {Q_TEXTS['vet']['cs']}",
                    f"{len(fin)} finalists remain. Deep vetting checks older posts, collaborations, competitors, ad disclosure and news{extra_en}. "
                    f"Vet {n} {Q_TEXTS['vet']['en']}")
        else:
            out.add("Kolem 3 neprošel nikdo. Zkuste kritéria zmírnit (např. „max 80 tisíc sledujících“ nebo „vypni formát“).",
                    "Nobody passed round 3. Try softer criteria (e.g. “max 80k followers” or “turn off format”).")
    else:
        out.add("Spustil jsem hledání a kola 1–3. Průběh vidíte na nástěnce; každé vyřazení má kolo, důvod a zdroj. "
                "Až kola doběhnou, napište „prověř finalisty“ a hloubkovou prověrku spustím po vašem potvrzení.",
                "I started the search and rounds 1–3. Watch the board; every elimination shows the round, the reason and the source. "
                "When the rounds finish, write “vet the finalists” and I will start deep vetting once you confirm.")


async def _fallback_vet(ctx: ChatContext, emit: Emit, out: _Reply, run: Run | None, message: str = "") -> None:
    fin = finalists(run)
    if not fin:
        out.add("Zatím nemám finalisty. Nejdřív spusťte kola 0–3 („spusť“).",
                "There are no finalists yet. Run rounds 0–3 first (“run”).")
        return
    named = {norm_handle(h) for h in re.findall(r"@([A-Za-z0-9._]{1,30})", message or "")}
    picked = [c for c in fin if norm_handle(c.ref.handle) in named]
    if picked:
        # "vet @x": only the named finalists (so the one left out by the cap can be vetted on request)
        fin = picked
    ids = [c.id for c in fin][:MAX_FINALISTS]
    result = await ctx.start_deep_vetting(ids)
    await _emit_tool(emit, "start_deep_vetting", {"candidate_ids": ids}, result)
    if isinstance(result, dict) and result.get("ok") is False:
        err = str(result.get("error") or "")
        if "busy" in err.lower():
            out.add("Prověrku teď nespustím: na běhu ještě pracuje jiný krok (např. doplnění dat po úpravě kritérií). "
                    "Zkuste to prosím za chvíli znovu („prověř finalisty“).",
                    "I could not start the vetting: another step is still running on this run (for example the data "
                    "fill after a criteria edit). Please try again in a moment (“vet the finalists”).")
        else:
            out.add(f"Prověrku se nepodařilo spustit: {err or 'neznámá chyba'}. Nic se neprověřilo.",
                    f"The vetting could not start: {err or 'unknown error'}. Nothing was vetted.")
        return
    handles = ", ".join(f"@{c.ref.handle}" for c in fin[:MAX_FINALISTS])
    out.add(f"Prověřuji do hloubky: {handles}. Starší posty, spolupráce a konkurence, označování reklamy, tvrzení vs. důkazy a zprávy. "
            "Reporty se objeví na nástěnce. Nic nikomu neposílám a nikoho nekontaktuji.",
            f"Deep vetting: {handles}. Older posts, collaborations and competitors, ad disclosure, claims vs. evidence and news. "
            "Reports will appear on the board. Nothing is sent and nobody is contacted.")
    left = fin[MAX_FINALISTS:]
    if left:
        lh = ", ".join(f"@{c.ref.handle}" for c in left)
        out.add(f"Prověřuji nejvýš {MAX_FINALISTS} finalistů najednou, takže {lh} zatím ne. Napište „prověř {lh.split(', ')[0]}“, "
                "pokud ho chcete prověřit také.",
                f"I vet at most {MAX_FINALISTS} finalists at a time, so {lh} {'is' if len(left) == 1 else 'are'} not included. "
                f"Write “vet {lh.split(', ')[0]}” if you want {'them' if len(left) > 1 else 'that one'} too.")


def _round_summary(run: Run, rnd: int | None, lang: str) -> str:
    """"Why were so many eliminated in round 2?": the round's counts and the criteria that removed them."""
    from collections import Counter

    rounds = {r.get("round"): r for r in run.rounds if isinstance(r, dict)}
    out_by: dict[int, Counter] = {}
    for c in run.candidates.values():
        e = c.elimination
        if c.status == "eliminated" and e is not None:
            out_by.setdefault(e.round, Counter())[e.criterion_id] += 1
    picks = [rnd] if rnd in (1, 2, 3) else sorted(k for k in out_by if k in (1, 2, 3))
    lines: list[str] = []
    for r in picks:
        info = rounds.get(r) or {}
        crit = out_by.get(r) or Counter()
        labels = {c.id: (c.label.get(lang) or c.kind) for c in run.criteria.criteria}
        why = ", ".join(f"{labels.get(cid, cid)} ({n})" for cid, n in crit.most_common(4))
        if lang == "en":
            lines.append(f"Round {r}: entered {info.get('entered', '?')} → remaining {info.get('remaining', '?')}"
                         + (f"; out because of: {why}" if why else "; nobody dropped out") + ".")
        else:
            lines.append(f"Kolo {r}: vstoupilo {info.get('entered', '?')} → zůstalo {info.get('remaining', '?')}"
                         + (f"; vypadli kvůli: {why}" if why else "; nikdo nevypadl") + ".")
    if not lines:
        return _t(lang, "Zatím nikdo nevypadl.", "Nobody has dropped out yet.")
    tail = _t(lang, "Proč vypadl konkrétní účet, řeknu po zadání @handle („proč vypadl @…?“).",
              "For one account, ask with its @handle (“why did @… drop out?”).")
    return "\n".join(lines + [tail])


async def _fallback_explain(message: str, ctx: ChatContext, emit: Emit, out: _Reply, run: Run | None) -> None:
    h = _handle_from(message, run)
    if not _is_subject_run(run) and run is not None and (h is None or find_candidate(run, h) is None) \
            and _RX_AGGREGATE.search(fold(message)):
        m = re.search(r"(?:round|kol[eou])\s*(\d)|(\d)\.?\s*(?:round|kol[eo])", fold(message))
        rnd = int(m.group(1) or m.group(2)) if m else None
        out.add(_round_summary(run, rnd, out.lang))
        return
    if _is_subject_run(run):
        sh = _subject_handle(run) or h or ""
        out.add(f"Při prověrce jednoho tvůrce nikdo nevypadává: report pro @{sh} ukazuje každou kontrolu se zdrojem, "
                "i ty nesplněné. Nic se nehodnotí skóre.",
                f"Nobody drops out in a single-creator check: the report for @{sh} shows every check with its source, "
                "including the ones that did not pass. There is no score.")
        return
    cand = find_candidate(run, h or "")
    if cand is None:
        if run is None:
            out.add("Zatím neběželo žádné kolo, takže nikdo nevypadl.", "No round has run yet, so nobody has dropped out.")
        else:
            out.add(f"Účet {('@' + h) if h else ''} mezi kandidáty nenacházím. Napište prosím přesný @handle.".replace("Účet  ", "Účet "),
                    f"I cannot find {('@' + h) if h else 'that account'} among the candidates. Please write the exact @handle.")
        return
    result = await ctx.explain_elimination(cand.id)
    await _emit_tool(emit, "explain_elimination", {"candidate_id": cand.id}, result)
    out.add(explain_from_run(run, cand, out.lang))


_RX_MY_BUSINESS = re.compile(
    r"(?i)\b(?:my|our|moj[ie]|moji|mou|můj|muj|naš[ei]|nase|nasi|náš|nas)\s+([^,.;!?\n]+)"
)


async def _fallback_goal(message: str, ctx: ChatContext, emit: Emit, out: _Reply, cs: CriteriaSet) -> None:
    lang = out.lang
    text = _blank_subjects(message).replace("§S§", " ")
    name = pick_preset(text)
    city = find_city(text) or (cs.brief.city if cs else None)
    # the owner's own words for the business ("my yoga studio"), and competitors named in this message
    m = _RX_MY_BUSINESS.search(text)
    own = _business_from(m.group(1), lang) if m else None
    if own is None and (_RX_GOAL_LEAD.search(text) or re.search(r"(?i)\b(?:i|we)\s+(?:actually\s+)?(?:run|have|own|manage)\b|"
                                                                r"\b(?:mám|mam|máme|mame|vedu|provozuju)\b", text)):
        # "change the goal to a café in Prague", "actually I run a yoga studio": the business named there
        own = _business_from(re.split(r"(?i)[,;]\s*(?:konkuren|competit|rival)", text)[0], lang) or None
    comp_m = re.search(r"(?i)\b(?:konkuren\w*|competitors?|competition|rival\w*)\b.*", message)
    named = parse_competitors(re.sub(r"(?i)^(?:konkuren\w*|competitors?|competition|rival\w*)\s*(?:are|is|je|jsou|:)?\s*", "",
                                     comp_m.group(0))) if comp_m else []
    if name:
        # the preset gives the criteria parameters; the business and competitors stay the owner's
        base = preset_brief_for(name, lang)
        if own and _names_preset_business(own, base.business_type):
            own = None   # "what about my bakery?" in English in a Czech session -> "pekárna"
        same = own is None and (city or base.city) == base.city
        brief = base.model_copy(update={"city": city or base.city, "lang": lang,
                                        "business_type": own or base.business_type,
                                        "competitors": named or ([] if own else base.competitors)})
        if not same or _is_subject_run(ctx.current_run()):
            # another business or another city, or a single-creator check (its brief holds only what the
            # owner said): the preset's sample audience / goal / budget are not the owner's
            brief = brief.model_copy(update={"audience": "", "goal": "", "budget_hint": None})
    else:
        # a business we have no preset for: nothing of the previous goal is carried over (no old
        # audience, goal or budget), so the report never states a goal the owner did not give
        brief = Brief(business_type=own or _business_from(text, lang), city=city, audience="", goal="",
                      budget_hint=None, competitors=named, lang=lang)  # type: ignore[arg-type]
    run_before = ctx.current_run()
    result = await ctx.change_goal(brief)
    await _emit_tool(emit, "change_goal", {"brief": brief}, result)
    new_cs = ctx.current_criteria()
    if new_cs is not None:
        await emit("criteria.updated", {"criteria": new_cs})
    loc = cs_locative(brief.city)
    if _is_subject_run(ctx.current_run() or run_before):
        _subject_goal_reply(out, result, brief, ctx.current_run() or run_before)
        return
    out.add(f"Cíl změněn: {brief.business_type}{(' ' + loc) if loc else ''}. Stejné kandidáty teď posuzuji podle nových kritérií; "
            "na nástěnce je rozdíl – kdo vypadl jen u jednoho cíle a proč.",
            f"Goal changed: {brief.business_type}{(' in ' + brief.city) if brief.city else ''}. The same candidates are re-evaluated "
            "with the new criteria; the board shows the difference – who dropped out for only one goal and why.")
    diff = result.get("diff") if isinstance(result, dict) and isinstance(result.get("diff"), dict) else result
    if isinstance(diff, dict) and isinstance(diff.get("dropped"), list) and isinstance(diff.get("returned"), list):
        nd, nr = len(diff["dropped"]), len(diff["returned"])
        drop_cs = ("nevypadl žádný účet" if nd == 0 else "vypadl 1 účet" if nd == 1
                   else f"vypadly {nd} účty" if nd <= 4 else f"vypadlo {nd} účtů")
        ret_cs = ("nevrátil se žádný" if nr == 0 else "vrátil se 1 účet" if nr == 1
                  else f"vrátily se {nr} účty" if nr <= 4 else f"vrátilo se {nr} účtů")
        out.add(f"Nově {drop_cs}, {ret_cs}.", f"{nd} newly dropped, {nr} returned.")
    for line in _report_diff_lines(result, lang):
        out.add(line)
    if new_cs is not None and new_cs.brief.business_type == brief.business_type:
        out.add(describe_criteria(new_cs, lang))


async def _fallback_outreach(message: str, ctx: ChatContext, emit: Emit, out: _Reply, run: Run | None, cs: CriteriaSet) -> None:
    h = _handle_from(message)
    cand = find_candidate(run, h) if h else None
    if cand is None and not h:
        fin = finalists(run)
        with_report = [c for c in fin if c.report is not None]
        cand = (with_report or fin or [None])[0]
    if cand is None:
        out.add("Pro koho? Napište třeba „oslovení pro @handle“ (jde o finalisty).",
                "For whom? Write e.g. “outreach for @handle” (finalists only).")
        return
    result = await ctx.draft_outreach(cand.id)
    await _emit_tool(emit, "draft_outreach", {"candidate_id": cand.id}, result)
    draft: Any = None
    if isinstance(result, dict):
        draft = result.get("outreach_draft") or result.get("draft")
        if draft is None and isinstance(result.get("report"), dict):
            draft = result["report"].get("outreach_draft")
    if not isinstance(draft, dict):
        fresh = (ctx.current_run() or run)
        c2 = fresh.candidates.get(cand.id) if fresh else None
        if c2 is not None and c2.report is not None and c2.report.outreach_draft:
            draft = c2.report.outreach_draft
    if not isinstance(draft, dict):
        from app.llm.vetting import outreach_template

        draft = outreach_template(cs.brief, cand)
    text = draft.get(out.lang) or draft.get("cs") or ""
    out.add(f"Koncept oslovení pro @{cand.ref.handle} – NEODESLÁNO, jen ke zkopírování:",
            f"Outreach draft for @{cand.ref.handle} – NOT SENT, copy only:")
    out.add(text)
    out.add("Nic jsem neposlal; jestli a komu napíšete, rozhodujete vy.", "I have not sent anything; whether and whom to contact is your call.")


# --------------------------------------------------------------------------------------------
# Fallback: subject mode (one named creator; docs/subject-mode.md section 8.2)
# --------------------------------------------------------------------------------------------

_RX_GOAL_SWITCH = re.compile(
    r"\b(?:switch|go|change|move) back to\b|\bback to (?:my|our|the)\b|\bactually,? (?:i|we) (?:run|have|own|manage|am|are)\b|"
    r"\b(?:i|we) (?:actually )?(?:run|have|own|manage) (?:a|an|my|our)\b|"
    r"\b(?:prepni|prepnete|zmen) (?:to )?(?:zpet |zpatky )?na\b|\bzpatky na\b|\bzpet na\b|\bvlastne (?:mam|mame|vedu|provozuju)\b|"
    r"\bwhat about (my|our|a|an)\b|\bhow about (my|our|a|an)\b|\bwhat if (i|we) (had|ran|run|have|owned)\b|"
    r"\bfor (my|our) .+ instead\b|\binstead,? (for )?(my|our)\b|"
    r"\ba co (pro |treba |kdyz )?(moj\w*|muj|mou|nas\w*)\b|\bmisto toho\b|\bpro (moj\w*|muj|nas\w*) .+ misto\b"
)
_RX_ANY_BIZ = (_RX_FOOD_BIZ, _RX_FIT_BIZ, _RX_BEAUTY_BIZ, _RX_FASHION_BIZ, _RX_KIDS_BIZ, _RX_TECH_BIZ,
               _RX_TRAVEL_BIZ, _RX_BOOK_BIZ)
_KIND_TAG = {"fact": ("fakt", "fact"), "inference": ("odvození", "inference"), "gap": ("mezera", "gap")}
_CONF_TAG = {"high": ("vysoká jistota", "high confidence"), "medium": ("střední jistota", "medium confidence"),
             "low": ("nízká jistota", "low confidence")}
_CLAIM_STATUS = {
    "conflicts_with_record": ("je v rozporu se záznamem", "conflicts with the record"),
    "supported": ("odpovídá záznamu", "is backed by the record"),
    "unsupported": ("záznam ho nepotvrzuje", "is not backed by the record"),
    "cannot_verify": ("nejde ověřit z veřejných dat", "cannot be verified from public data"),
}


def _is_business_text(f: str) -> bool:
    return any(rx.search(f) for rx in _RX_ANY_BIZ)


def _is_subject_run(run: Any) -> bool:
    return run is not None and getattr(run, "mode", "discovery") == "subject"


def _subject_handle(run: Any) -> str | None:
    subj = getattr(run, "subject", None) if run is not None else None
    h = getattr(subj, "handle", None) if subj is not None else None
    if h:
        return str(h)
    cands = list(getattr(run, "candidates", {}).values()) if run is not None else []
    return cands[0].ref.handle if cands else None


def _lang_text(v: Any, lang: str) -> str:
    if isinstance(v, dict):
        return str(v.get(lang) or v.get("en") or v.get("cs") or "")
    return str(v or "")


def _subject_thread(history: list[dict]) -> list[tuple[str, str | None]]:
    """Owner messages of a subject flow still in progress: the last subject request plus the answers
    to the anchor / goal questions after it, each with the question that was pending. [] when no
    subject question is pending at the end of ``history``."""
    thread: list[tuple[str, str | None]] = []
    pending: str | None = None
    first = True
    for m in history:
        if m.get("role") == "assistant":
            pending = _pending(m)
            continue
        if not _is_owner_msg(m):
            continue
        text = _owner_text(m).strip()
        if not text:
            continue
        if refusal_reason(text) or _RX_WHAT_CHECK.search(fold(text)) or (pending == "sa" and thread and _anchor_detour(text)):
            first = False
            continue  # a detour; the question stays pending
        tok = is_subject_request(text, pending, first)
        first = False
        if tok is not None and pending == "sh" and thread:
            thread.append((text, pending))
        elif tok is not None:
            thread = [(text, pending)]
        elif pending in _SUBJECT_Q and thread:
            thread.append((text, pending))
        elif pending not in ("q2", "q3", "q4", "q5") and subject_name(text):
            thread = [(text, pending)]
        else:
            thread = []
    return thread if pending in _SUBJECT_Q else []


_RX_SEND = re.compile(r"\b(send|e-?mail|message (him|her|them)|dm|contact|reach out|posli|poslete|napis|napiste|kontaktuj\w*|oslov\w*)\b")


_RX_BAD_ID = re.compile(r"\b(ico|ic|company id|company number)\b")


def _anchor_detour(text: str) -> bool:
    """A reply to the anchor question that is not an answer: a request to send / contact, a goal
    switch, or a question ("what is IČO?"). The anchor question stays pending."""
    f = fold(text)
    if isinstance(extract_anchor(text, answer=False), dict):
        return False
    if _RX_SEND.search(f) or _RX_OUTREACH.search(f) or _RX_BAD_ID.search(f):
        return True
    if _RX_GOAL_SWITCH.search(f) and (pick_preset(f) or _looks_like_business(text)):
        return False  # the business answer is read by _fallback_subject
    return text.strip().endswith("?") or bool(re.match(r"^\s*(what|why|how|who|which|co|proc|jak|kdo|ktery|ktera|k cemu)\b", f))


def _anchor_detour_reply(out: _Reply, text: str, tok: SubjectToken | None) -> None:
    f = fold(text)
    h = f"@{tok.handle}" if tok is not None else ""
    if _RX_BAD_ID.search(f) and not text.strip().endswith("?") and not re.match(r"^\s*(what|co)\b", f):
        out.add("IČO má 6 až 8 číslic; tohle jako IČO přečíst nejde.",
                "A company ID (Czech IČO) has 6-8 digits; I cannot read this one as a company ID.")
    elif _RX_SEND.search(f) or _RX_OUTREACH.search(f):
        out.add("Nic nikomu neposílám: odesílání tu vůbec není. Po prověrce připravím koncept oslovení, který si zkopírujete.",
                "I never send anything: there is no send function. After the check I prepare an outreach draft you can copy.")
    else:
        out.add("Kotva mi pomůže najít správný účet, ne jmenovce: město, kde tvůrce působí, jeho web, nebo IČO "
                "(identifikační číslo firmy z obchodního rejstříku, hledám ho jen ve veřejném profilu).",
                "The anchor helps me pick the right account and not a namesake: the city where the creator is based, "
                "their website, or a company ID (the Czech IČO business number; I only look for it on the public profile).")
    out.add(f"Zpátky k otázce{(' k ' + h) if h else ''}: {Q_TEXTS['sa']['cs']} Můžete napsat i „přeskočit“.",
            f"Back to the question{(' about ' + h) if h else ''}: {Q_TEXTS['sa']['en']} You can also say “skip”.")


def _ask_anchor(out: _Reply, handle: str) -> None:
    out.add(f"Abych prověřil správný účet @{handle}, a ne jmenovce nebo podobný účet: {Q_TEXTS['sa']['cs']} "
            "Můžete napsat i „přeskočit“.",
            f"To check the right @{handle} and not a namesake or look-alike account: {Q_TEXTS['sa']['en']} "
            "You can also say “skip”.")


async def _fallback_subject(msgs: list[tuple[str, str | None]], ctx: ChatContext, emit: Emit, out: _Reply,
                            cs: CriteriaSet | None) -> None:
    """One step of the subject flow: gather the subject, anchor and goal from the thread's messages,
    ask for the first missing one (one question per turn), or call research_subject and reply."""
    lang = out.lang
    tok = next((t for t in ((subject_token(m) or (bare_reply_handle(m) if pd == "sh" else None)) for m, pd in msgs)
                if t is not None), None)
    name = subject_name(msgs[0][0])
    if tok is None:
        if name is None:  # pragma: no cover - callers only pass threads that start with a subject request
            return
        if len(msgs) == 1:
            _ask_handle(out, name)
        else:
            out.add("Bez @účtu nebo odkazu na profil prověrku nespustím: podle samotného jména bych mohl zaměnit jmenovce. "
                    "Pošlete ho, až ho budete mít.",
                    "Without the @handle or a profile link I will not start the check: a name alone could match a "
                    "namesake. Send it when you have it.")
        return
    if name:
        # the name message's own anchor / goal ("Jakub Horák from Brno for my bakery"): the name is the subject
        msgs = [(m.replace(name, " §S§ ") if subject_token(m) is None else m, pd) for m, pd in msgs]
    anchor: dict[str, str] = {}
    anchor_done = skipped = False
    goal: dict[str, Any] | None = None
    goal_done = False
    sa_answers = 0
    for i, (text, pend) in enumerate(msgs):
        is_a = i > 0 and pend == "sa"
        is_g = i > 0 and pend == "sg"
        g = extract_goal(text, lang, answer=is_g)
        if g:
            goal = {**(goal or {}), **{k: v for k, v in g.items() if v}}
        if is_g:
            goal_done = True
        # the subject written without @ ("check kuba.jidlo.brno ...") is not a website anchor
        a_text = re.sub(r"(?i)(?<![\w.@/-])" + re.escape(tok.handle) + r"(?![\w-]|\.\w)", " §S§ ", text)
        a = extract_anchor(a_text, answer=is_a)
        if a == "skip":
            skipped = anchor_done = True
            anchor = {}
        elif isinstance(a, dict) and a:
            anchor.update(a)
            anchor_done, skipped = True, False
        elif is_a:
            sa_answers += 1
            # an answer we cannot read: go on without an anchor (and say so); an answer that only
            # named the business gets the anchor question once more. Requests to send, questions
            # ("what is IČO?") and goal switches are detours (_anchor_detour), not answers.
            if g is None or sa_answers >= 2:
                skipped = anchor_done = True
    if not anchor_done:
        if len(msgs) == 1 or (name and len(msgs) == 2):
            out.add(f"Prověřím @{tok.handle} pro váš cíl: veřejný profil, příspěvky, účty na jiných sítích, spolupráce a zprávy. "
                    "Každé tvrzení bude mít zdroj; nikoho nevyřazuji a nedávám skóre.",
                    f"I will check @{tok.handle} for your goal: the public profile, posts, accounts on other platforms, "
                    "collaborations and news. Every claim gets a source; nothing is eliminated and there is no score.")
        _ask_anchor(out, tok.handle)
        return
    if goal is None and not goal_done and cs is None:
        # the business from an interview started earlier in this chat ("I have a bakery in Brno")
        prior, _p, _s = interview_state([m for m in ctx.history[:-1]])
        if prior.get("q1"):
            g = extract_goal(prior["q1"], lang, answer=True)
            if g:
                goal = {k: v for k, v in g.items() if v}
                if prior.get("q3") and not goal.get("goal"):
                    goal["goal"] = clip(prior["q3"], 300)
    if goal is None and not goal_done and cs is None:
        _ask(out, "sg")
        return

    preset: str | None = None
    if goal and goal.get("preset"):
        preset = str(goal["preset"])
        base = preset_brief_for(preset, lang)
        bus = str(goal.get("business") or "")
        bt = base.business_type if (not bus or _names_preset_business(bus, base.business_type)) else clip(bus, 80)
        # The preset lends the criteria: the brief states what the owner said (business, city, goal
        # words); the preset's sample goal, audience and budget are not the owner's and are dropped. The
        # sample competitor list stays until the owner names their own (the competitor check needs one).
        brief = base.model_copy(update={"business_type": bt, "city": goal.get("city") or None, "audience": "",
                                        "goal": clip(str(goal.get("goal") or ""), 300), "budget_hint": None})
    elif goal and goal.get("business"):
        brief = Brief(business_type=clip(str(goal["business"]), 80), city=goal.get("city"), audience="",
                      goal=clip(str(goal.get("goal") or ""), 300), budget_hint=None, competitors=[], lang=lang)  # type: ignore[arg-type]
    elif cs is not None:
        # the goal from the criteria already agreed in this chat (an earlier interview or check);
        # the API picks the matching preset by keywords
        brief = cs.brief.model_copy(deep=True, update={"lang": lang})
    else:  # pragma: no cover - goal_done always yields a goal
        _ask(out, "sg")
        return
    # "my competitors are Lidl and @albert_cz": the owner's own list replaces the preset's sample one
    # (only the text after the keyword, so the subject's own @handle is never taken for a competitor)
    own = [c for m, _ in msgs for t in [re.search(r"(?i)\b(?:konkuren\w*|competitors?|competition)\b.*", m)] if t
           for c in parse_competitors(re.sub(r"(?i)\s+(?:and|or|a|nebo)\s+(?=@)", ", ", t.group(0)), brief.competitors)]
    if own:
        brief = brief.model_copy(update={"competitors": own})
    brief, _ = sanitize_brief(brief)
    anchor_arg = normalize_anchor_dict(anchor) if anchor else None

    fn = getattr(ctx, "research_subject", None)
    if fn is None:
        out.add("Prověrku jednoho tvůrce tady teď spustit nejde.", "Checking a single creator is not available here.")
        return
    result = await fn(tok.raw, anchor_arg, brief, preset)
    await _emit_tool(emit, "research_subject", {"subject": tok.raw, "anchor": anchor_arg, "brief": brief, "preset": preset}, result)
    _subject_reply(out, result, tok, brief, anchor_arg is None)


def _other_goal_hint(brief: Brief) -> tuple[str, str]:
    if pick_preset(f"{brief.business_type} {brief.goal}") == "fitness":
        return "a co pro moji pekárnu?", "what about my bakery?"
    return "a co pro moje fitness studio?", "what about my fitness studio?"


def _subject_reply(out: _Reply, result: Any, tok: SubjectToken, brief: Brief, no_anchor: bool) -> None:
    """Reply to a research_subject result: verdict, up to 3 key findings (tagged fact / inference /
    gap with confidence), check counts, the no-elimination line and the goal-switch hint."""
    lang = out.lang
    r = result if isinstance(result, dict) else {}
    subj = r.get("subject") if isinstance(r.get("subject"), dict) else {}
    h = str(subj.get("handle") or tok.handle)
    ident = r.get("identity") if isinstance(r.get("identity"), dict) else {}
    if not r or r.get("ok") is False:
        err = str(r.get("error") or "")
        out.add(f"Účet @{h} se nepodařilo prověřit{': ' + err if err else ''}.",
                f"I could not check @{h}{': ' + err if err else ''}.")
        out.add("Pošlete prosím přesný @handle nebo odkaz na profil (instagram.com/… nebo tiktok.com/@…).",
                "Please send the exact @handle or a profile link (instagram.com/… or tiktok.com/@…).")
        return
    if subj.get("status") == "not_found" or ident.get("status") == "not_found":
        out.add(_lang_text(ident.get("text"), lang) or _t(lang, f"Veřejný profil @{h} jsme nenašli.", f"We found no public profile @{h}."))
        out.add("Zkontrolujte prosím handle nebo pošlete odkaz na profil (instagram.com/… nebo tiktok.com/@…).",
                "Please check the handle or send a profile link (instagram.com/… or tiktok.com/@…).")
        return
    status = r.get("status")
    if status == "error":
        out.add(f"Prověrka @{h} skončila chybou. Zkuste to prosím znovu.", f"The check of @{h} failed. Please try again.")
        return
    if status == "running" or not ident:
        out.add(f"Prověřuji @{h}: veřejný profil, příspěvky, účty na jiných sítích, spolupráce a zprávy. "
                "Report se za chvíli objeví na nástěnce; nikoho nevyřazuji a nedávám skóre.",
                f"I am checking @{h} now: the public profile, posts, accounts on other platforms, collaborations and news. "
                "The report will appear on the board in a moment; nothing is eliminated and there is no score.")
        return

    if ident.get("text"):
        out.add(_lang_text(ident["text"], lang))
    if no_anchor and ident.get("status") == "likely":
        out.add("Bez kotvy (město, web nebo IČO) může být ověření totožnosti nanejvýš „pravděpodobné“; "
                "kotva by ho potvrdila.",
                "Without an anchor (city, website or company ID) the identity can be at most “likely”; "
                "an anchor would confirm it.")
    elif no_anchor and ident.get("status") == "uncertain":
        out.add("Kotva (město, web nebo IČO) by pomohla potvrdit, že jde o správný účet.",
                "An anchor (city, website or company ID) would help confirm it is the right account.")

    key = [k for k in (r.get("key_findings") or []) if isinstance(k, dict)][:3]
    if key:
        bt = brief.business_type
        lines = [_t(lang, f"Nejdůležitější pro váš cíl ({bt}):", f"Key for your {bt}:")]
        for k in key:
            kind = str(k.get("kind") or {"f": "fact", "i": "inference", "g": "gap"}.get(str(k.get("id") or "")[:1], "fact"))
            tag = _KIND_TAG.get(kind, (kind, kind))[0 if lang == "cs" else 1]
            conf = _CONF_TAG.get(str(k.get("confidence") or ""))
            tag += f", {conf[0 if lang == 'cs' else 1]}" if conf else ""
            why = _lang_text(k.get("why"), lang)
            lines.append(f"• [{tag}] {_lang_text(k.get('text'), lang)}" + (f" – {why}" if why else ""))
        out.add("\n".join(lines))

    conflicts = [c for c in (r.get("claims") or []) if isinstance(c, dict) and c.get("status") == "conflicts_with_record"][:2]
    for c in conflicts:
        st = _CLAIM_STATUS["conflicts_with_record"]
        out.add(f"Tvrzení vs. záznam: „{clip(_lang_text(c.get('claim'), lang), 120)}“ {st[0]}.",
                f"Claim vs. record: “{clip(_lang_text(c.get('claim'), lang), 120)}” {st[1]}.")

    checks = r.get("checks") if isinstance(r.get("checks"), dict) else {}
    if checks:
        items = [i for i in (checks.get("items") or []) if isinstance(i, dict)]
        fails = [str(i.get("label") or i.get("criterion_id")) for i in items if i.get("status") == "fail"][:3]
        unknown = [str(i.get("label") or i.get("criterion_id")) for i in items if i.get("status") == "unknown"][:3]
        nf, nu, np_ = int(checks.get("fail") or 0), int(checks.get("unknown") or 0), int(checks.get("pass") or 0)
        if nf == 0 and nu == 0:
            out.add(f"Kontroly pro váš cíl: všech {np_} splněno.", f"Checks for your goal: all {np_} passed.")
        else:
            p_cs, p_en = [], []
            if nf:
                p_cs.append(f"nesplněno {nf}" + (f" ({', '.join(fails)})" if fails else ""))
                p_en.append(f"{nf} did not pass" + (f" ({', '.join(fails)})" if fails else ""))
            if nu:
                p_cs.append(f"nešlo ověřit {nu}" + (f" ({', '.join(unknown)})" if unknown else ""))
                p_en.append(f"{nu} could not be checked" + (f" ({', '.join(unknown)})" if unknown else ""))
            p_cs.append(f"splněno {np_}")
            p_en.append(f"{np_} passed")
            out.add(f"Kontroly pro váš cíl: {', '.join(p_cs)}.", f"Checks for your goal: {', '.join(p_en)}.")
    less = r.get("less_relevant")
    if isinstance(less, int) and less > 0:
        out.add(f"Méně relevantní zjištění pro tento cíl ({less}) jsou v reportu sbalená.",
                f"{less} {'finding that matters' if less == 1 else 'findings that matter'} less for this goal "
                f"{'is' if less == 1 else 'are'} collapsed in the report.")
    out.add("Nikoho jsme nevyřadili a nedáváme skóre: jsou to kontroly se zdroji. Celý report se zdroji, otázky pro tvůrce "
            "a koncept oslovení (nikdy se neodesílá) jsou na nástěnce.",
            "Nothing was eliminated and there is no score: these are checks with sources. The full report with sources, "
            "questions for the creator and an outreach draft (never sent) are on the board.")
    hint_cs, hint_en = _other_goal_hint(brief)
    out.add(f"Zkuste „{hint_cs}“ a uvidíte, jak se report pro jiný cíl změní.",
            f"Try “{hint_en}” to see how the report changes for another goal.")


def _funnel_change_line(result: Any, lang: str) -> str | None:
    """"1 creator came back: @x" / "2 dropped out: @a, @b" after a criterion edit (diff in a tool result)."""
    d = result.get("diff") if isinstance(result, dict) else None
    if not isinstance(d, dict):
        return None
    ret = [str(e.get("handle") or "") for e in d.get("returned") or [] if isinstance(e, dict)]
    drop = [str(e.get("handle") or "") for e in d.get("dropped") or [] if isinstance(e, dict)]
    nr, nd = int(d.get("returned_count") or len(ret)), int(d.get("dropped_count") or len(drop))
    parts: list[str] = []
    if nr:
        hs = ", ".join(f"@{h}" for h in ret[:5] if h)
        parts.append(_t(lang, f"{'vrátil se 1 tvůrce' if nr == 1 else f'vrátili se {nr} tvůrci' if nr < 5 else f'vrátilo se {nr} tvůrců'}: {hs}",
                        f"{nr} {'creator' if nr == 1 else 'creators'} came back: {hs}"))
    if nd:
        hs = ", ".join(f"@{h}" for h in drop[:5] if h)
        parts.append(_t(lang, f"{'vypadl 1 tvůrce' if nd == 1 else f'vypadli {nd} tvůrci' if nd < 5 else f'vypadlo {nd} tvůrců'}: {hs}",
                        f"{nd} dropped out: {hs}"))
    if not parts:
        return None
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def _report_diff_lines(result: Any, lang: str) -> list[str]:
    """One line per re-rendered report after a goal / criteria change (report_diffs in a tool result)."""
    diffs = result.get("report_diffs") if isinstance(result, dict) else None
    if not isinstance(diffs, list):
        return []
    if len(diffs) == 1 and isinstance(diffs[0], dict):  # one report (a subject run): its summary line
        d = diffs[0]
        summary = _lang_text(d.get("summary"), lang)
        h = d.get("handle") or str(d.get("candidate_id") or "").split(":", 1)[-1]
        return [f"@{h}: {summary}" if h else summary] if summary else []
    # several finalists: the page lists each changed report once, with a link, in its own summary notice
    # right below the reply; the reply only counts them, so the chat does not repeat every line
    same = "The report is the same for this goal."
    n = sum(1 for d in diffs if isinstance(d, dict) and _lang_text(d.get("summary"), "en") not in ("", same))
    if not n:
        return []
    return [_t(lang, f"Přepsané reporty finalistů: {n} (přehled s odkazy je v souhrnu pod touto odpovědí).",
               f"Finalist reports rewritten: {n} (listed with links in the summary below this reply).")]


def _subject_goal_reply(out: _Reply, result: Any, brief: Brief, run: Any) -> None:
    """Goal switch on a subject run: what changed in the report (report_diffs[0])."""
    lang = out.lang
    h = _subject_handle(run) or ""
    where_cs = f" {cs_locative(brief.city)}" if brief.city else ""
    where_en = f", {brief.city}" if brief.city else ""
    if isinstance(result, dict) and result.get("ok") is False:
        err = str(result.get("error") or "")
        out.add(f"Cíl se nepodařilo změnit{': ' + err if err else ''}.", f"I could not change the goal{': ' + err if err else ''}.")
        return
    subj = getattr(run, "subject", None)
    if subj is not None and getattr(subj, "status", None) == "not_found":
        out.add(f"Cíl jsem zaznamenal: {brief.business_type}{where_cs}. Profil @{h} jsme nenašli, takže není co přepsat; "
                "zkontrolujte uživatelské jméno nebo zadejte jiného tvůrce.",
                f"Goal noted: {brief.business_type}{where_en}. We found no profile @{h}, so there is no report to rewrite; "
                "check the handle or name another creator.")
        return
    out.add(f"Cíl změněn: {brief.business_type}{where_cs}. Report pro @{h} jsem přeřadil a přepsal z už stažených dat, "
            "bez nových dotazů.",
            f"Goal changed: {brief.business_type}{where_en}. I re-ordered and rewrote the report for @{h} from the data "
            "already fetched: no new requests.")
    diffs = result.get("report_diffs") if isinstance(result, dict) else None
    d = next((x for x in (diffs or []) if isinstance(x, dict)), None)
    if d is None:
        out.add("Report se pro nový cíl přepíše, jakmile prověrka doběhne.",
                "The report will be rewritten for the new goal as soon as the check finishes.")
        return
    summary = _lang_text(d.get("summary"), lang)
    if summary:
        out.add(summary)
    key = [_lang_text(k, lang) for k in (d.get("key_findings") or [])][:3]
    key = [k for k in key if k]
    if key:
        from app.rounds.report import cs_accusative

        out.add(_t(lang, f"Teď nejdůležitější pro {cs_accusative(brief.business_type)}:", f"Now key for a {brief.business_type}:")
                + "\n" + "\n".join(f"• {k}" for k in key))
    out.add("Pořád nikoho nevyřazuji a nedávám skóre; mění se, co je pro váš cíl důležité.",
            "Still nothing is eliminated and there is no score; what changes is what matters for your goal.")


def _subject_help(out: _Reply, run: Any) -> None:
    h = _subject_handle(run) or "…"
    out.add(f"Tahle prověrka se týká jednoho tvůrce (@{h}); nikdo nevypadává. Můžu: změnit cíl („a co pro moje fitness studio?“), "
            "prověřit jiného tvůrce („prověř @handle“), připravit koncept oslovení („koncept oslovení“, nikdy se neodesílá) "
            "nebo vysvětlit, co kontrolujeme („co kontrolujete?“).",
            f"This check is about one creator (@{h}); nobody drops out. I can: switch the goal (“what about my fitness studio?”), "
            "check another creator (“check @handle”), draft a first message (“outreach draft”, never sent) "
            "or explain what we check (“what do you check?”).")
