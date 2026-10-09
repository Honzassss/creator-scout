"""LLM request budget and task groups (app/llm/budget.py): config parsing, provider gating, the
per-process counter, run usage binding, the structured answer cache and the chat stream guard.
Every HTTP call goes to an httpx.MockTransport or a fake Anthropic client; no keys, no network."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from app import config
from app.events import bind_emit
from app.llm import budget, openrouter
from app.llm import client as llm_client

PRIMARY = "dots-studio/dots-3-note-preview:free"


class _Out(BaseModel):
    answer: str


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "gen-1", "model": PRIMARY, "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    })


class _Recorder:
    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.script.pop(0)
        return item(request) if callable(item) else item


def _install(*script) -> _Recorder:
    rec = _Recorder(*script)
    openrouter.use_transport(httpx.MockTransport(rec))
    return rec


def _env(monkeypatch, **values: str) -> config.Settings:
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    return config.reload_settings()


def _openrouter(monkeypatch, **values: str) -> config.Settings:
    return _env(monkeypatch, OPENROUTER_API_KEY="sk-or-test-not-real", LLM_PROVIDER="openrouter", **values)


def _anthropic(monkeypatch, **values: str) -> config.Settings:
    return _env(monkeypatch, ANTHROPIC_API_KEY="sk-ant-test", LLM_PROVIDER="anthropic", **values)


@pytest.fixture(autouse=True)
def _fresh(_isolated_settings):
    llm_client.reset_client()
    yield
    llm_client.reset_client()


async def _ask(task: str = "claims", user: str = "x", logs: list | None = None) -> _Out | None:
    async def emit(event, data):
        if logs is not None and event == "log":
            logs.append(data.get("text", ""))

    with bind_emit(emit):
        return await llm_client.structured(_Out, system="Answer.", user=user, task=task)


# --------------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------------


def test_budget_defaults_per_provider(monkeypatch):
    assert config.get_settings().llm_request_budget is None            # no provider: nothing is sent anyway
    assert _openrouter(monkeypatch).llm_request_budget == 40           # free tier
    assert budget.request_budget() == 40 and budget.budget_left() == 40
    assert _anthropic(monkeypatch).llm_request_budget is None          # unlimited
    assert budget.budget_left() is None
    # an explicit integer applies to either provider
    assert _anthropic(monkeypatch, LLM_REQUEST_BUDGET="7").llm_request_budget == 7
    assert _openrouter(monkeypatch, LLM_REQUEST_BUDGET="0").llm_request_budget == 0
    for raw in ("unlimited", "off", "-1", "OFF"):
        assert _openrouter(monkeypatch, LLM_REQUEST_BUDGET=raw).llm_request_budget is None
    # garbage -> the default; empty (conftest, a blank .env line) -> the default
    assert _openrouter(monkeypatch, LLM_REQUEST_BUDGET="lots").llm_request_budget == 40
    assert _openrouter(monkeypatch, LLM_REQUEST_BUDGET="").llm_request_budget == 40


def test_openrouter_tasks_parsing(monkeypatch, caplog):
    assert config.get_settings().openrouter_tasks == frozenset({"chat", "vetting", "news"})   # default
    assert config.LLM_TASK_GROUPS == budget.ALL_GROUPS
    assert _env(monkeypatch, OPENROUTER_TASKS="all").openrouter_tasks == frozenset(budget.ALL_GROUPS)
    assert _env(monkeypatch, OPENROUTER_TASKS="none").openrouter_tasks == frozenset()
    assert _env(monkeypatch, OPENROUTER_TASKS=" Chat , topics ").openrouter_tasks == frozenset({"chat", "topics"})
    assert _env(monkeypatch, OPENROUTER_TASKS="").openrouter_tasks == frozenset({"chat", "vetting", "news"})
    caplog.set_level(logging.WARNING)
    assert _env(monkeypatch, OPENROUTER_TASKS="chat,bogus_group").openrouter_tasks == frozenset({"chat"})
    assert "bogus_group" in caplog.text


def test_deprecated_bulk_tasks_flag(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    config._warned_env.clear()
    s = _env(monkeypatch, OPENROUTER_BULK_TASKS="1")
    assert s.openrouter_tasks == frozenset(budget.ALL_GROUPS) and s.openrouter_bulk_tasks is True
    # "1" with OPENROUTER_TASKS set: the task list wins
    s = _env(monkeypatch, OPENROUTER_BULK_TASKS="1", OPENROUTER_TASKS="chat")
    assert s.openrouter_tasks == frozenset({"chat"}) and s.openrouter_bulk_tasks is False
    # "0" is ignored (new default) with exactly one warning line, however often settings reload
    monkeypatch.setenv("OPENROUTER_TASKS", "")
    caplog.clear()
    for _ in range(3):
        s = _env(monkeypatch, OPENROUTER_BULK_TASKS="0")
        assert s.openrouter_tasks == frozenset({"chat", "vetting", "news"})
    assert sum("OPENROUTER_BULK_TASKS" in r.getMessage() for r in caplog.records) == 1


def test_task_groups_and_enabled_per_provider(monkeypatch):
    assert budget.task_group("claims") == "vetting"
    assert {budget.task_group(t) for t in ("skeptic", "questions", "outreach", "vetting")} == {"vetting"}
    assert budget.task_group("news") == "news" and budget.task_group("chat") == "chat"
    assert budget.task_group("topics") == "topics" and budget.task_group("sensitive") == "sensitive"
    assert budget.task_group("something_new") == "something_new"
    assert set(budget.TASK_GROUPS.values()) == set(budget.ALL_GROUPS)

    # no provider: nothing is enabled
    assert not any(budget.llm_task_enabled(t) for t in ("chat", "claims", "news", "topics", "sensitive"))
    # Anthropic: every task, OPENROUTER_TASKS ignored
    _anthropic(monkeypatch, OPENROUTER_TASKS="none")
    assert all(budget.llm_task_enabled(t) for t in ("chat", "claims", "news", "topics", "sensitive", "llm"))
    # OpenRouter default: chat, vetting, news
    _openrouter(monkeypatch, OPENROUTER_TASKS="")
    assert [t for t in ("chat", "claims", "outreach", "news", "topics", "sensitive", "llm")
            if budget.llm_task_enabled(t)] == ["chat", "claims", "outreach", "news"]
    # OpenRouter "all" also admits a task outside the known groups (old OPENROUTER_BULK_TASKS=1)
    _openrouter(monkeypatch, OPENROUTER_TASKS="all")
    assert budget.llm_task_enabled("topics") and budget.llm_task_enabled("llm")


# --------------------------------------------------------------------------------------------
# counter
# --------------------------------------------------------------------------------------------


async def test_spend_counts_and_bind_llm_usage(monkeypatch):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="5")
    run_usage: dict[str, int] = {}
    with budget.bind_llm_usage(run_usage):
        assert await budget.spend("claims") and await budget.spend("skeptic") and await budget.spend("chat")
    assert await budget.spend("news")                                   # unbound: process only
    assert run_usage == {"total": 3, "vetting": 2, "chat": 1}
    assert budget.requests_used() == 4 and budget.budget_left() == 1

    other: dict[str, int] = {"total": 10, "chat": 10}                   # an earlier count is kept
    with budget.bind_llm_usage(other):
        assert await budget.spend("chat")
        assert not await budget.spend("chat")                           # 5/5 used
    assert other == {"total": 11, "chat": 11}


async def test_usage_snapshot_shape(monkeypatch):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="2")
    snap = budget.usage_snapshot()
    assert snap == {"llm_requests_used": 0, "llm_budget": 2, "llm_budget_left": 2, "llm_budget_exhausted": False,
                    "llm_tasks": ["chat", "vetting", "news"], "llm_requests_by_task": {}}
    await budget.spend("claims")
    await budget.spend("chat")
    snap = budget.usage_snapshot()
    assert snap["llm_requests_used"] == 2 and snap["llm_budget_left"] == 0 and snap["llm_budget_exhausted"] is True
    assert snap["llm_requests_by_task"] == {"vetting": 1, "chat": 1}
    json.dumps(snap)                                                    # JSON-serializable for /api/health

    _anthropic(monkeypatch, LLM_REQUEST_BUDGET="")
    snap = budget.usage_snapshot()
    assert snap["llm_budget"] is None and snap["llm_budget_left"] is None and snap["llm_budget_exhausted"] is False
    assert snap["llm_tasks"] == list(budget.ALL_GROUPS)
    _env(monkeypatch, ANTHROPIC_API_KEY="", OPENROUTER_API_KEY="", LLM_PROVIDER="")
    assert budget.usage_snapshot()["llm_tasks"] == []

    budget.reset_budget()
    assert budget.usage_snapshot()["llm_requests_used"] == 0 and budget.usage_snapshot()["llm_requests_by_task"] == {}


async def test_spend_is_atomic_under_concurrency(monkeypatch):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="5")
    results = await asyncio.gather(*(budget.spend("claims") for _ in range(12)))
    assert sum(results) == 5 and budget.requests_used() == 5


async def test_reset_client_resets_budget(monkeypatch):
    _openrouter(monkeypatch)
    await budget.spend("chat")
    assert budget.requests_used() == 1
    llm_client.reset_client()
    assert budget.requests_used() == 0


# --------------------------------------------------------------------------------------------
# structured(): gating, exhaustion, cache
# --------------------------------------------------------------------------------------------


async def test_structured_exhaustion_falls_back_and_logs_once(monkeypatch, caplog):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="1")
    rec = _install(_completion('{"answer": "a"}'))
    caplog.set_level(logging.WARNING)
    logs: list[str] = []
    usage: dict[str, int] = {}
    with budget.bind_llm_usage(usage):
        assert (await _ask("claims", "one", logs)).answer == "a"
        assert await _ask("claims", "two", logs) is None                # budget used up: no request
        assert await _ask("skeptic", "three", logs) is None             # same group: no second log line
    assert len(rec.requests) == 1 and usage == {"total": 1, "vetting": 1}
    exhausted = [t for t in logs if "LLM budget exhausted" in t]
    assert exhausted == ["LLM budget exhausted (1/1): vetting uses the deterministic fallback"]
    assert sum("LLM budget exhausted" in r.getMessage() for r in caplog.records) == 1
    # another group logs its own line, once
    assert await _ask("news", "four", logs) is None
    assert await _ask("news", "five", logs) is None
    assert [t for t in logs if "LLM budget exhausted" in t][1:] == [
        "LLM budget exhausted (1/1): news uses the deterministic fallback"]


async def test_structured_budget_zero_sends_nothing(monkeypatch):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="0")
    rec = _install()
    assert await _ask() is None and rec.requests == []


async def test_disabled_task_is_silent_and_free(monkeypatch, caplog):
    _openrouter(monkeypatch)                                           # default: topics not served
    rec = _install()
    caplog.set_level(logging.INFO)
    logs: list[str] = []
    assert await _ask("topics", "a", logs) is None
    assert await _ask("topics", "b", logs) is None
    assert rec.requests == [] and logs == [] and budget.requests_used() == 0
    assert sum("'topics' is not enabled" in r.getMessage() for r in caplog.records) == 1


async def test_structured_cache_hit_costs_nothing(monkeypatch):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="2")
    rec = _install(
        httpx.Response(503, json={"error": {"code": 503, "message": "No available providers"}}),
        _completion('{"answer": "cached"}'),
        _completion('{"answer": "other"}'),
    )
    assert await _ask("claims", "same") is None                        # failures are not cached
    assert (await _ask("claims", "same")).answer == "cached"
    assert budget.requests_used() == 2 and budget.budget_left() == 0
    for _ in range(3):                                                 # replay: 0 requests, even with no budget left
        assert (await _ask("claims", "same")).answer == "cached"
    assert len(rec.requests) == 2 and budget.requests_used() == 2
    files = list(config.get_settings().llm_dir.glob("structured-*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text()) == {"answer": "cached"}
    # the key covers provider, task, schema, system and user
    k = llm_client.structured_cache_key
    base = k(_Out, system="s", user="u", task="claims", provider_name="openrouter")
    assert base == k(_Out, system="s", user="u", task="claims", provider_name="openrouter")
    assert len({base, k(_Out, system="s", user="u", task="claims", provider_name="anthropic"),
                k(_Out, system="s", user="u", task="news", provider_name="openrouter"),
                k(_Out, system="s2", user="u", task="claims", provider_name="openrouter"),
                k(_Out, system="s", user="u2", task="claims", provider_name="openrouter")}) == 5


async def test_structured_stale_cache_entry_is_ignored(monkeypatch):
    _openrouter(monkeypatch)
    key = llm_client.structured_cache_key(_Out, system="Answer.", user="x", task="claims")
    llm_client.cache_put("structured", key, {"wrong_field": 1})
    rec = _install(_completion('{"answer": "fresh"}'))
    assert (await _ask("claims", "x")).answer == "fresh" and len(rec.requests) == 1
    assert llm_client.cache_get("structured", key) == {"answer": "fresh"}


async def test_blocked_openrouter_key_costs_no_budget(monkeypatch):
    _openrouter(monkeypatch)
    rec = _install(httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}}))
    assert await _ask("claims", "a") is None
    assert await _ask("claims", "b") is None                           # blocked: no HTTP request
    assert len(rec.requests) == 1 and budget.requests_used() == 1


# --------------------------------------------------------------------------------------------
# Anthropic path (fake client)
# --------------------------------------------------------------------------------------------


class _FakeAnthropic:
    """client.beta.messages.parse / client.messages.parse, scripted."""

    def __init__(self, *, beta_error: Exception | None = None):
        self.calls: list[str] = []
        self.beta_error = beta_error
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._beta_parse))
        self.messages = SimpleNamespace(parse=self._parse)

    async def _beta_parse(self, **kw):
        self.calls.append("beta")
        if self.beta_error is not None:
            raise self.beta_error
        return SimpleNamespace(stop_reason="end_turn", parsed_output=_Out(answer="beta"))

    async def _parse(self, **kw):
        self.calls.append("plain")
        return SimpleNamespace(stop_reason="end_turn", parsed_output=_Out(answer="plain"))


def _bad_request() -> Exception:
    import anthropic

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError("beta not allowed", response=httpx.Response(400, request=req), body=None)


async def test_anthropic_spends_per_attempt_and_caches(monkeypatch):
    _anthropic(monkeypatch)
    fake = _FakeAnthropic(beta_error=_bad_request())
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    usage: dict[str, int] = {}
    with budget.bind_llm_usage(usage):
        assert (await _ask("claims", "a")).answer == "plain"
    assert fake.calls == ["beta", "plain"] and usage == {"total": 2, "vetting": 2}   # the retry is a 2nd request
    assert (await _ask("claims", "a")).answer == "plain" and len(fake.calls) == 2    # cached
    assert budget.request_budget() is None and budget.requests_used() == 2


async def test_anthropic_budget_stops_the_retry_and_the_call(monkeypatch):
    _anthropic(monkeypatch, LLM_REQUEST_BUDGET="1")
    fake = _FakeAnthropic(beta_error=_bad_request())
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    logs: list[str] = []
    assert await _ask("claims", "a", logs) is None                     # beta failed, the retry is over budget
    assert fake.calls == ["beta"] and budget.requests_used() == 1
    assert await _ask("claims", "b", logs) is None and fake.calls == ["beta"]
    assert [t for t in logs if "LLM budget exhausted" in t] == [
        "LLM budget exhausted (1/1): vetting uses the deterministic fallback"]


# --------------------------------------------------------------------------------------------
# chat stream
# --------------------------------------------------------------------------------------------


async def test_stream_chat_spends_and_raises_budget_error(monkeypatch):
    _openrouter(monkeypatch, LLM_REQUEST_BUDGET="1")
    sse = "\n".join([f"data: {json.dumps({'model': PRIMARY, 'choices': [{'index': 0, 'delta': {'content': 'Hi'}, 'finish_reason': 'stop'}]})}",
                     "", "data: [DONE]", ""])
    rec = _install(httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode()))

    async def on_text(_t: str) -> None:
        return None

    usage: dict[str, int] = {}
    with budget.bind_llm_usage(usage):
        res = await openrouter.stream_chat([{"role": "user", "content": "x"}], tools=[], model=PRIMARY, on_text=on_text)
        assert res.text == "Hi"
        with pytest.raises(openrouter.OpenRouterError) as e:
            await openrouter.stream_chat([{"role": "user", "content": "x"}], tools=[], model=PRIMARY, on_text=on_text)
    assert e.value.kind == "budget" and e.value.reason == "LLM budget exhausted"
    assert len(rec.requests) == 1 and usage == {"total": 1, "chat": 1}
    assert budget.usage_snapshot()["llm_requests_by_task"] == {"chat": 1}


def test_budget_exhausted_exception():
    err = budget.BudgetExhausted("claims")
    assert err.task == "claims" and err.reason == "LLM budget exhausted" and "vetting" in str(err)
