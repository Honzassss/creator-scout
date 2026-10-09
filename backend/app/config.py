"""Environment configuration.

Always read settings at call time via ``get_settings()`` (never cache values at import time), so
tests can point DATA_DIR at a temp dir with ``monkeypatch.setenv(...)`` + ``reload_settings()``.

Env vars (see /.env.example):
  SOURCE_MODE        mock | cache | apify   (default mock)
  DATA_DIR           runtime data dir        (default <repo>/data); holds cache/, runs/, llm/
  FIXTURES_DIR       mock dataset dir        (default <repo>/fixtures)
  LLM_PROVIDER       auto | anthropic | openrouter (default auto: Anthropic if ANTHROPIC_API_KEY, else
                     OpenRouter if OPENROUTER_API_KEY, else every LLM task uses its deterministic fallback)
  ANTHROPIC_API_KEY  Claude API key
  LLM_BASE_URL       Claude API base URL (default https://api.anthropic.com). Always passed explicitly,
                     so a stray ANTHROPIC_BASE_URL in the shell cannot redirect our calls.
  MODEL_CHAT         Claude chat model, default claude-opus-5-5
  MODEL_BULK         Claude bulk model, default claude-sonnet-5-5
  OPENROUTER_API_KEY            OpenRouter key (OpenAI-compatible API, free ":free" models)
  OPENROUTER_MODEL_CHAT         default dots-studio/dots-3-note-preview:free
  OPENROUTER_MODEL_BULK         default dots-studio/dots-3-note-preview:free
  OPENROUTER_FALLBACK_MODELS    comma list tried by OpenRouter when the primary fails
                                (default apodex/apodex-1.1-mini:free,openrouter/free)
                                nvidia/nemotron-3-super-120b-a12b:free is only served with data_collection "allow"
                                (its free endpoint may train on prompts; checked live 2026-10-09).
  OPENROUTER_DATA_COLLECTION    deny | allow (default deny). "allow" admits providers that may log or
                                train on prompts; we send real public creator data, so only switch it
                                when no free provider is available under "deny".
  OPENROUTER_TASKS              comma list of task groups OpenRouter may serve (default chat,vetting,news).
                                Groups: chat, vetting (claims, skeptic, questions, outreach), news (news
                                labels), topics, sensitive. "all" = every group, "none" = no LLM task (every
                                task uses its labeled deterministic fallback). Empty = the default. Anthropic
                                ignores it and serves every task.
  OPENROUTER_BULK_TASKS         deprecated. "1" with OPENROUTER_TASKS unset = "all"; "0" is ignored (the
                                default above applies). Either logs one warning.
  LLM_REQUEST_BUDGET            max LLM HTTP requests per process (llm/budget.py). Unset: 40 with OpenRouter
                                (the free daily cap is small), unlimited with Anthropic. An integer N >= 0
                                applies to either provider (0 = no LLM requests); "unlimited" / "off" / "-1" =
                                no cap. Cached answers cost nothing; a goal switch re-renders without requests.
  OPENROUTER_BASE_URL           default https://openrouter.ai/api/v1
  APIFY_TOKEN        empty -> ApifyProvider unavailable
  MOCK_LATENCY       seconds of fake latency per MockProvider call (default 0.15)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from app.models import LLMMode, SourceMode

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# Loaded once at import; never overrides variables already set in the environment.
load_dotenv(REPO_DIR / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=False)

_SOURCE_MODES = ("mock", "cache", "apify")
_LLM_PROVIDERS = ("auto", "anthropic", "openrouter")

ANTHROPIC_BASE_URL_DEFAULT = "https://api.anthropic.com"
OPENROUTER_BASE_URL_DEFAULT = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_DEFAULT = "dots-studio/dots-3-note-preview:free"   # works under data_collection "deny"
OPENROUTER_FALLBACKS_DEFAULT = "apodex/apodex-1.1-mini:free,openrouter/free"

LLMProvider = Literal["anthropic", "openrouter"]

# Task groups OPENROUTER_TASKS can name (llm/budget.py maps task names to these).
LLM_TASK_GROUPS: tuple[str, ...] = ("chat", "vetting", "news", "topics", "sensitive")
OPENROUTER_TASKS_DEFAULT: frozenset[str] = frozenset({"chat", "vetting", "news"})
OPENROUTER_REQUEST_BUDGET_DEFAULT = 40      # free tier: ~50 requests/day without credits
_UNLIMITED = ("unlimited", "off", "-1")
_BULK_ALL = frozenset(LLM_TASK_GROUPS) - {"chat"}

log = logging.getLogger(__name__)
_warned_env: set[str] = set()              # once-per-process config warnings


def _warn_once(key: str, msg: str, *args: object) -> None:
    if key in _warned_env:
        return
    _warned_env.add(key)
    log.warning(msg, *args)


@dataclass(frozen=True)
class Settings:
    source_mode: SourceMode
    data_dir: Path
    fixtures_dir: Path
    anthropic_api_key: str | None
    apify_token: str | None
    model_chat: str
    model_bulk: str
    mock_latency: float
    llm_provider_setting: str = "auto"            # LLM_PROVIDER as configured (auto | anthropic | openrouter)
    llm_base_url: str = ANTHROPIC_BASE_URL_DEFAULT
    openrouter_api_key: str | None = None
    openrouter_base_url: str = OPENROUTER_BASE_URL_DEFAULT
    openrouter_model_chat: str = OPENROUTER_MODEL_DEFAULT
    openrouter_model_bulk: str = OPENROUTER_MODEL_DEFAULT
    openrouter_fallback_models: tuple[str, ...] = tuple(OPENROUTER_FALLBACKS_DEFAULT.split(","))
    openrouter_data_collection: str = "deny"      # deny | allow (OpenRouter provider.data_collection)
    openrouter_tasks: frozenset[str] = OPENROUTER_TASKS_DEFAULT   # task groups OpenRouter serves
    llm_request_budget_raw: str | None = None     # LLM_REQUEST_BUDGET as configured (None = default)

    @property
    def cache_dir(self) -> Path:
        """Source cache: data/cache/<hash>.json (CachedProvider)."""
        return self.data_dir / "cache"

    @property
    def runs_dir(self) -> Path:
        """Run snapshots: data/runs/<run_id>.json (store.py)."""
        return self.data_dir / "runs"

    @property
    def llm_dir(self) -> Path:
        """Cached LLM outputs (topic labels etc.): data/llm/<hash>.json."""
        return self.data_dir / "llm"

    @property
    def llm_provider(self) -> LLMProvider | None:
        """Provider the LLM tasks use, or None (deterministic fallback). An explicit LLM_PROVIDER
        without its key means fallback, never the other provider."""
        pref = self.llm_provider_setting
        if pref == "anthropic":
            return "anthropic" if self.anthropic_api_key else None
        if pref == "openrouter":
            return "openrouter" if self.openrouter_api_key else None
        if self.anthropic_api_key:
            return "anthropic"
        if self.openrouter_api_key:
            return "openrouter"
        return None

    @property
    def llm_mode(self) -> LLMMode:
        return "llm" if self.llm_provider else "fallback"

    @property
    def llm_model(self) -> str | None:
        """Configured chat model of the active provider (None in fallback)."""
        p = self.llm_provider
        if p == "anthropic":
            return self.model_chat
        if p == "openrouter":
            return self.openrouter_model_chat
        return None

    @property
    def llm_model_bulk(self) -> str | None:
        """Configured model for bulk structured tasks of the active provider (None in fallback)."""
        p = self.llm_provider
        if p == "anthropic":
            return self.model_bulk
        if p == "openrouter":
            return self.openrouter_model_bulk
        return None

    @property
    def openrouter_bulk_tasks(self) -> bool:
        """Deprecated (old OPENROUTER_BULK_TASKS=1): True when OpenRouter serves every bulk group."""
        return _BULK_ALL <= self.openrouter_tasks

    @property
    def llm_request_budget(self) -> int | None:
        """Max LLM requests per process, None = unlimited. Default: 40 with OpenRouter, unlimited with
        Anthropic (and without a provider, where nothing is sent anyway)."""
        raw = (self.llm_request_budget_raw or "").strip().lower()
        if raw in _UNLIMITED:
            return None
        if raw:
            try:
                n = int(raw)
            except ValueError:
                _warn_once(f"budget:{raw}", "LLM_REQUEST_BUDGET=%r is not an integer; using the default", raw)
            else:
                return None if n < 0 else n
        return OPENROUTER_REQUEST_BUDGET_DEFAULT if self.llm_provider == "openrouter" else None

    @property
    def apify_configured(self) -> bool:
        return bool(self.apify_token)


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def _openrouter_tasks() -> frozenset[str]:
    """OPENROUTER_TASKS (+ the deprecated OPENROUTER_BULK_TASKS) -> enabled task groups."""
    raw = _env("OPENROUTER_TASKS")
    bulk = _env("OPENROUTER_BULK_TASKS")
    if bulk is not None:
        on = bulk.lower() in ("1", "true", "yes", "on")
        if on and raw is None:
            _warn_once("bulk1", "OPENROUTER_BULK_TASKS is deprecated: treating =%s as OPENROUTER_TASKS=all", bulk)
            return frozenset(LLM_TASK_GROUPS)
        _warn_once(f"bulk:{on}:{raw is None}", "OPENROUTER_BULK_TASKS is deprecated and ignored; OPENROUTER_TASKS=%s applies",
                   raw if raw is not None else ",".join(g for g in LLM_TASK_GROUPS if g in OPENROUTER_TASKS_DEFAULT))
    if raw is None:
        return OPENROUTER_TASKS_DEFAULT
    out: set[str] = set()
    for part in raw.lower().replace(";", ",").split(","):
        name = part.strip()
        if not name:
            continue
        if name == "all":
            out.update(LLM_TASK_GROUPS)
        elif name == "none":
            continue
        elif name in LLM_TASK_GROUPS:
            out.add(name)
        else:
            _warn_once(f"task:{name}", "OPENROUTER_TASKS: unknown task group %r ignored (groups: %s)",
                       name, ", ".join(LLM_TASK_GROUPS))
    return frozenset(out)


def _load() -> Settings:
    mode = (_env("SOURCE_MODE") or "mock").lower()
    if mode not in _SOURCE_MODES:
        raise ValueError(f"SOURCE_MODE must be one of {_SOURCE_MODES}, got {mode!r}")
    try:
        latency = float(_env("MOCK_LATENCY") or 0.15)
    except ValueError:
        latency = 0.15
    provider = (_env("LLM_PROVIDER") or "auto").lower()
    if provider not in _LLM_PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {_LLM_PROVIDERS}, got {provider!r}")
    fallbacks = _env("OPENROUTER_FALLBACK_MODELS")
    fallbacks = OPENROUTER_FALLBACKS_DEFAULT if fallbacks is None else fallbacks
    data_collection = (_env("OPENROUTER_DATA_COLLECTION") or "deny").lower()
    return Settings(
        source_mode=mode,  # type: ignore[arg-type]
        data_dir=Path(_env("DATA_DIR") or REPO_DIR / "data").expanduser(),
        fixtures_dir=Path(_env("FIXTURES_DIR") or REPO_DIR / "fixtures").expanduser(),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        apify_token=_env("APIFY_TOKEN"),
        model_chat=_env("MODEL_CHAT") or "claude-opus-5-5",
        model_bulk=_env("MODEL_BULK") or "claude-sonnet-5-5",
        mock_latency=max(0.0, latency),
        llm_provider_setting=provider,
        llm_base_url=(_env("LLM_BASE_URL") or ANTHROPIC_BASE_URL_DEFAULT).rstrip("/"),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_base_url=(_env("OPENROUTER_BASE_URL") or OPENROUTER_BASE_URL_DEFAULT).rstrip("/"),
        openrouter_model_chat=_env("OPENROUTER_MODEL_CHAT") or OPENROUTER_MODEL_DEFAULT,
        openrouter_model_bulk=_env("OPENROUTER_MODEL_BULK") or OPENROUTER_MODEL_DEFAULT,
        openrouter_fallback_models=tuple(m.strip() for m in fallbacks.split(",") if m.strip()),
        openrouter_data_collection=data_collection if data_collection in ("deny", "allow") else "deny",
        openrouter_tasks=_openrouter_tasks(),
        llm_request_budget_raw=_env("LLM_REQUEST_BUDGET"),
    )


settings: Settings = _load()


def get_settings() -> Settings:
    return settings


def reload_settings() -> Settings:
    """Re-read os.environ (not .env). Tests call this after monkeypatching env vars."""
    global settings
    settings = _load()
    return settings
