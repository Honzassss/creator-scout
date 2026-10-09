"""LLM client wrapper (Anthropic or OpenRouter) + deterministic-fallback plumbing.

- Provider: ``get_settings().llm_provider`` ("anthropic" | "openrouter" | None = fallback), chosen by
  LLM_PROVIDER (auto: Anthropic key first, then OpenRouter key). OpenRouter lives in ``openrouter.py``.
- One shared ``anthropic.AsyncAnthropic`` (SDK 1.x), created lazily per API key and base URL. The base
  URL is always passed explicitly (LLM_BASE_URL, default https://api.anthropic.com): the SDK would
  otherwise read ANTHROPIC_BASE_URL from the shell, which other tools on this machine set.
- ``structured()``: one structured-output call (``messages.parse`` + ``output_format=<pydantic>``)
  with server-side refusal fallback (``fallbacks="default"``, beta ``server-side-fallback-2026-07-01``);
  if the account rejects that beta the call is retried once without it and the choice is remembered.
  ``stop_reason`` "refusal" / "max_tokens", API errors and validation errors -> ``None`` (the caller
  then uses its deterministic fallback). Never raises.
- Models: get_settings().model_bulk for bulk tasks (sensitive, topics, vetting), model_chat for the
  chatbot. Claude Opus 5.5 / Sonnet 5.5: no budget_tokens, no forced tool_choice; effort is set
  explicitly ("low" for bulk classification).
- OpenRouter: ``structured()`` sends a strict json_schema response_format and validates with pydantic;
  429 / 402 / 5xx / invalid JSON -> None with the same fallback log line naming the reason. The model
  that actually answered is kept per task (``models_used()``, shown by GET /api/health).
- Budget and task groups (``budget.py``): ``structured()`` first asks ``budget.llm_task_enabled(task)``
  (OpenRouter serves only the groups in OPENROUTER_TASKS, default chat,vetting,news; Anthropic serves
  all), then its own answer cache, then ``await budget.spend(task)`` once per HTTP attempt (the
  Anthropic beta-less retry spends again). Disabled, exhausted or failed -> None, the caller's fallback.
- Structured answer cache: data/llm/structured-<sha1(provider|task|schema|system|user)>.json. Only
  validated answers are stored; a hit costs no request, so replaying a run costs 0 bulk requests.
- Every LLM task calls ``record_mode(task, "llm" | "fallback")``; the engine binds
  ``bind_llm_modes(run.llm_modes)`` so the run shows which tasks used the fallback ("mixed" if both).
- Cached outputs: data/llm/<task>-<key>.json (``cache_get`` / ``cache_put``), deleted by purge.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.events import emit_log, to_en, tr
from app.llm import budget
from app.models import LLMMode

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)

_llm_modes: ContextVar[dict[str, str] | None] = ContextVar("llm_modes", default=None)

# Server-side refusal fallback (Claude API only). Flipped off for the process if the API rejects it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_server_fallbacks_ok: bool = True

_client: Any = None
_client_sig: tuple[str, str] | None = None

# task -> model id that last answered it (OpenRouter reports the routed model in the response).
_answered: dict[str, str] = {}


def llm_available() -> bool:
    """True when an LLM provider is configured (Anthropic or OpenRouter key, see LLM_PROVIDER)."""
    return get_settings().llm_provider is not None


def provider() -> str | None:
    """"anthropic" | "openrouter" | None (deterministic fallback)."""
    return get_settings().llm_provider


def openrouter_active() -> bool:
    return get_settings().llm_provider == "openrouter"


def global_llm_mode() -> LLMMode:
    """"llm" if a provider is configured, else "fallback" (GET /api/health)."""
    return get_settings().llm_mode


def llm_mode() -> LLMMode:
    """Alias of global_llm_mode(): "llm" (live model) or "fallback" (deterministic, labeled)."""
    return global_llm_mode()


@contextlib.contextmanager
def bind_llm_modes(target: dict[str, str]) -> Iterator[None]:
    """Route record_mode() calls in this context into ``target`` (normally run.llm_modes)."""
    token = _llm_modes.set(target)
    try:
        yield
    finally:
        _llm_modes.reset(token)


def record_mode(task: str, mode: LLMMode) -> None:
    """Record which mode a task used; mixing both for one task yields "mixed". No-op if unbound."""
    target = _llm_modes.get()
    if target is None:
        return
    prev = target.get(task)
    target[task] = mode if prev in (None, mode) else "mixed"


def get_client() -> Any:
    """Shared ``anthropic.AsyncAnthropic`` (lazy), or None unless Anthropic is the active provider.

    api_key and base_url are passed explicitly, so ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN from the
    shell are never picked up implicitly by the SDK."""
    global _client, _client_sig
    s = get_settings()
    if s.llm_provider != "anthropic" or not s.anthropic_api_key:
        return None
    sig = (s.anthropic_api_key, s.llm_base_url)
    if _client is None or _client_sig != sig:
        try:
            import anthropic

            if os.environ.get("ANTHROPIC_CUSTOM_HEADERS"):
                log.warning("ANTHROPIC_CUSTOM_HEADERS is set in the environment; the Anthropic SDK adds those headers")
            _client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, base_url=s.llm_base_url, max_retries=2, timeout=120.0)
            _client_sig = sig
        except Exception as e:  # pragma: no cover - import / construction problems
            log.warning("cannot create Anthropic client: %s", e)
            return None
    return _client


def reset_client() -> None:
    """Drop the cached client, OpenRouter limiter / block, answered models and the request budget (tests)."""
    global _client, _client_sig, _server_fallbacks_ok
    _client = None
    _client_sig = None
    _server_fallbacks_ok = True
    _answered.clear()
    budget.reset_budget()
    from app.llm import openrouter

    openrouter.reset()


def models_used() -> dict[str, str]:
    """{task: model id that last answered it} (OpenRouter routes among models; GET /api/health)."""
    return dict(_answered)


async def note_model(task: str, model: str, actor: str = "openrouter") -> None:
    """Remember which model answered ``task`` and log it on the run stream (every step, not only on a change:
    a second run in the same process must name its models too)."""
    if not model:
        return
    _answered[task] = model
    await emit_log(tr(f"LLM {task}: odpověděl model {model}", f"LLM {task}: answered by model {model}"), actor=actor)


async def _log_fallback(task: str, reason: str, actor: str) -> None:
    log.info("structured(%s) -> fallback: %s", task, reason)
    await emit_log(tr(f"LLM {task}: deterministická záloha ({reason})", f"LLM {task}: deterministic fallback ({to_en(reason)})"),
                   actor=actor)


def cached_system(text: str) -> list[dict[str, Any]]:
    """System prompt as a cacheable block (stable prefix; volatile data goes in the user turn)."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


async def _parse_call(client: Any, schema: type[T], kwargs: dict[str, Any], task: str = "llm") -> Any:
    """messages.parse with server-side fallbacks when allowed; plain parse otherwise. The caller spent
    the first request; the beta-less retry is a second request and spends again (raises
    budget.BudgetExhausted when the budget is used up)."""
    global _server_fallbacks_ok
    import anthropic

    if _server_fallbacks_ok:
        try:
            return await client.beta.messages.parse(
                **kwargs, output_format=schema, betas=[FALLBACK_BETA], fallbacks="default"
            )
        except anthropic.BadRequestError as e:
            log.info("request with server-side fallbacks rejected (%s); retrying without", e)
            if not await budget.spend(task):
                raise budget.BudgetExhausted(task) from e
            resp = await client.messages.parse(**kwargs, output_format=schema)
            # The plain request worked where the beta one did not: the beta is the problem, stop sending it.
            _server_fallbacks_ok = False
            return resp
    return await client.messages.parse(**kwargs, output_format=schema)


def structured_cache_key(schema: type[BaseModel], *, system: str, user: str, task: str,
                         provider_name: str | None = None) -> str:
    """sha1(provider | task | schema name | system | user): the structured answer cache key."""
    p = provider_name if provider_name is not None else (get_settings().llm_provider or "")
    raw = "\x1f".join((p, task, schema.__name__, system, user))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _structured_cached(schema: type[T], key: str) -> T | None:
    cached = cache_get("structured", key)
    if cached is None:
        return None
    try:
        return schema.model_validate(cached)
    except (ValidationError, ValueError):
        return None   # the schema changed since this answer was stored: ask again


def _structured_store(key: str, out: BaseModel) -> None:
    try:
        cache_put("structured", key, out.model_dump(mode="json"))
    except Exception as e:  # cache is an optimization only
        log.info("structured cache_put failed: %s", e)


async def structured(
    schema: type[T],
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 16000,
    effort: str = "low",
    task: str = "llm",
) -> T | None:
    """One structured-output call validated into ``schema``. Returns None when there is no key, the
    task's group is not enabled for the provider (OPENROUTER_TASKS), the request budget is used up, or
    the call fails, is refused or truncated (caller then uses its fallback). A validated answer is
    cached (data/llm/structured-<key>.json) and served again without a request. model default: the
    active provider's bulk model (MODEL_BULK or OPENROUTER_MODEL_BULK)."""
    if not budget.llm_task_enabled(task):
        if get_settings().llm_provider is not None:
            budget.note_disabled(task)   # silent for the run stream; one INFO line per group per process
        return None
    key = structured_cache_key(schema, system=system, user=user, task=task)
    hit = _structured_cached(schema, key)
    if hit is not None:
        await emit_log(tr(f"LLM {task}: uložená odpověď z LLM cache (bez dotazu)",
                          f"LLM {task}: stored answer from the LLM cache (no request)"), actor="llm-cache")
        return hit
    if openrouter_active():
        out = await _structured_openrouter(schema, system=system, user=user, model=model, max_tokens=max_tokens, task=task)
        if out is not None:
            _structured_store(key, out)
        return out
    client = get_client()
    if client is None:
        return None
    if not await budget.spend(task):
        return None       # budget.spend logged it (once per group per process)
    import anthropic

    kwargs: dict[str, Any] = {
        "model": model or get_settings().model_bulk,
        "max_tokens": max_tokens,
        "system": cached_system(system),
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": effort},
    }
    reason = ""
    try:
        resp = await _parse_call(client, schema, kwargs, task)
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            reason = "refusal"
        elif stop == "max_tokens":
            reason = "truncated"
        else:
            out = resp.parsed_output
            if out is not None and not isinstance(out, schema):
                out = schema.model_validate(out)
            if out is not None:
                _structured_store(key, out)
                await note_model(task, str(getattr(resp, "model", "") or kwargs["model"]), actor="claude")
                return out
            reason = "no parsed output"
    except budget.BudgetExhausted:
        return None       # the beta-less retry hit the budget; budget.spend logged it
    except anthropic.RateLimitError:
        reason = "rate limited"
    except anthropic.APIStatusError as e:
        reason = f"API error {e.status_code}"
    except anthropic.APIConnectionError:
        reason = "connection error"
    except (ValidationError, ValueError) as e:
        reason = f"invalid output ({type(e).__name__})"
    except Exception as e:  # never raise into the funnel
        reason = f"{type(e).__name__}"
    await _log_fallback(task, reason, "claude")
    return None


async def _structured_openrouter(
    schema: type[T], *, system: str, user: str, model: str | None, max_tokens: int, task: str,
) -> T | None:
    from app.llm import openrouter

    # Callers may pass a Claude model id; OpenRouter ids always contain a "/".
    m = model if model and "/" in model else get_settings().openrouter_model_bulk
    try:
        # A key blocked by a daily cap / auth / credit error sends nothing, so it must not cost budget.
        openrouter.check_blocked()
        if not await budget.spend(task):
            return None   # budget.spend logged it (once per group per process)
        out, answered = await openrouter.complete_json(schema, system=system, user=user, model=m, max_tokens=max_tokens)
        await note_model(task, answered)
        return out
    except openrouter.OpenRouterError as e:
        reason = e.reason
    except ValidationError as e:
        reason = f"invalid output ({type(e).__name__})"
    except ValueError as e:  # JSON that does not parse
        reason = f"invalid JSON ({type(e).__name__})"
    except Exception as e:  # never raise into the funnel
        reason = f"{type(e).__name__}"
    await _log_fallback(task, reason, "openrouter")
    return None


# --------------------------------------------------------------------------------------------
# Small JSON cache for LLM outputs (data/llm/<task>-<key>.json)
# --------------------------------------------------------------------------------------------

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _cache_path(task: str, key: str):
    d = get_settings().llm_dir
    return d / f"{_SAFE.sub('_', task)}-{_SAFE.sub('_', key)}.json"


def cache_get(task: str, key: str) -> Any | None:
    """Read data/llm/<task>-<key>.json (JSON value) or None."""
    try:
        p = _cache_path(task, key)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def cache_put(task: str, key: str, value: Any) -> None:
    try:
        p = _cache_path(task, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{id(value)}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:  # cache is an optimization only
        log.info("cache_put(%s) failed: %s", task, e)
