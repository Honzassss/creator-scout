"""LLM request budget and task groups (one counter per process).

Every LLM HTTP request that is about to leave the process is counted here first: whoever issues the
request calls ``await spend(task)`` once per attempt (``client.structured`` for bulk tasks, the chat
loop for Anthropic chat streams, ``openrouter.stream_chat`` for OpenRouter chat streams). When the
budget is used up, ``spend`` returns False and the caller takes its deterministic fallback, the same
path as "no key". Cached answers are not requests and cost nothing.

- Task groups: chat, vetting (claims, skeptic, questions, outreach), news (news labels), topics,
  sensitive. ``llm_task_enabled(task)`` says whether the active provider may serve a task:
  no provider -> False; Anthropic -> every task; OpenRouter -> only the groups in OPENROUTER_TASKS
  (default chat,vetting,news; see config.py).
- Budget: LLM_REQUEST_BUDGET requests per process (default 40 with OpenRouter, unlimited with
  Anthropic). Exhaustion logs one WARNING and one run-stream log line per task group per process.
- ``bind_llm_usage(run.llm_usage)`` (engine) makes ``spend`` also count into the run:
  ``{"total": n, "<group>": n}``.
- ``usage_snapshot()`` feeds GET /api/health and GET /api/runs/{id}/status.

The counter is per process: tests call ``reset_budget()`` (conftest autouse fixture; also
``client.reset_client()``).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar

from app.config import get_settings
from app.events import emit_log

log = logging.getLogger(__name__)

TASK_GROUPS: dict[str, str] = {
    "chat": "chat",
    "claims": "vetting",
    "skeptic": "vetting",
    "questions": "vetting",
    "outreach": "vetting",
    "vetting": "vetting",
    "news": "news",
    "topics": "topics",
    "sensitive": "sensitive",
}
ALL_GROUPS: tuple[str, ...] = ("chat", "vetting", "news", "topics", "sensitive")

EXHAUSTED_REASON = "LLM budget exhausted"


class BudgetExhausted(Exception):
    """Raised by callers that cannot return None (the chat stream) when ``spend`` says no."""

    def __init__(self, task: str):
        super().__init__(f"{EXHAUSTED_REASON} ({task_group(task)})")
        self.task = task
        self.reason = EXHAUSTED_REASON


_used: int = 0                         # requests counted in this process
_by_group: dict[str, int] = {}         # group -> requests
_warned: set[str] = set()              # groups whose exhaustion was already logged
_disabled_noted: set[str] = set()      # groups whose "not enabled" INFO line was already logged

_usage: ContextVar[dict[str, int] | None] = ContextVar("llm_usage", default=None)
# groups already warned about in the current binding (one run's task): every run logs its own
# "budget exhausted" line, so a later run never falls back without saying why
_warned_bound: ContextVar[set[str] | None] = ContextVar("llm_budget_warned", default=None)


def task_group(task: str) -> str:
    """Task name -> group ("claims" -> "vetting"); an unknown task is its own group."""
    return TASK_GROUPS.get(task, task)


def llm_task_enabled(task: str) -> bool:
    """May the active provider serve ``task``? No provider -> False; Anthropic -> True;
    OpenRouter -> its group is in OPENROUTER_TASKS (all groups enabled also admits unknown tasks)."""
    s = get_settings()
    provider = s.llm_provider
    if provider is None:
        return False
    if provider == "anthropic":
        return True
    tasks = s.openrouter_tasks
    group = task_group(task)
    if group in tasks:
        return True
    return group not in ALL_GROUPS and all(g in tasks for g in ALL_GROUPS)


def note_disabled(task: str) -> None:
    """One INFO line per group per process when a task is skipped because its group is off."""
    group = task_group(task)
    if group in _disabled_noted:
        return
    _disabled_noted.add(group)
    log.info("LLM task group %r is not enabled for provider %s (OPENROUTER_TASKS); deterministic fallback",
             group, get_settings().llm_provider)


def request_budget() -> int | None:
    """Max LLM requests per process, or None (unlimited). See config.Settings.llm_request_budget."""
    return get_settings().llm_request_budget


def requests_used() -> int:
    return _used


def budget_left() -> int | None:
    cap = request_budget()
    return None if cap is None else max(0, cap - _used)


async def spend(task: str) -> bool:
    """Count one HTTP request that is about to leave the process. True: go ahead (counted in the
    process total, per group and in the bound run usage). False: budget used up; the caller uses its
    deterministic fallback. Check and count happen without an await in between, so concurrent tasks on
    one event loop never overspend."""
    global _used
    group = task_group(task)
    cap = request_budget()
    if cap is not None and _used >= cap:
        warned = _warned_bound.get()
        if warned is None:
            warned = _warned
        if group not in warned:
            warned.add(group)
            text = f"LLM budget exhausted ({_used}/{cap}): {group} uses the deterministic fallback"
            log.warning(text)
            await emit_log(text, actor="llm")
        return False
    _used += 1
    _by_group[group] = _by_group.get(group, 0) + 1
    target = _usage.get()
    if target is not None:
        target["total"] = target.get("total", 0) + 1
        target[group] = target.get(group, 0) + 1
    return True


@contextlib.contextmanager
def bind_llm_usage(target: dict[str, int]) -> Iterator[None]:
    """Route ``spend`` counts in this context into ``target`` (normally run.llm_usage) as well."""
    token = _usage.set(target)
    wtoken = _warned_bound.set(set())
    try:
        yield
    finally:
        _warned_bound.reset(wtoken)
        _usage.reset(token)


def enabled_groups() -> list[str]:
    """Task groups the active provider serves (in ALL_GROUPS order)."""
    s = get_settings()
    if s.llm_provider is None:
        return []
    if s.llm_provider == "anthropic":
        return list(ALL_GROUPS)
    return [g for g in ALL_GROUPS if g in s.openrouter_tasks]


def usage_snapshot() -> dict:
    """Process-level usage for GET /api/health and run status."""
    cap = request_budget()
    return {
        "llm_requests_used": _used,
        "llm_budget": cap,
        "llm_budget_left": None if cap is None else max(0, cap - _used),
        "llm_budget_exhausted": cap is not None and _used >= cap,
        "llm_tasks": enabled_groups(),
        "llm_requests_by_task": dict(_by_group),
    }


def reset_budget() -> None:
    """Zero the process counter and the once-per-process log flags (tests; client.reset_client())."""
    global _used
    _used = 0
    _by_group.clear()
    _warned.clear()
    _disabled_noted.clear()
