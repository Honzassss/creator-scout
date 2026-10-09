"""OpenRouter provider: config resolution, structured output, error handling, rate limiter, chat tool
loop and the Anthropic base-URL leak fix. Every HTTP call goes to an httpx.MockTransport; no keys,
no network."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app import config
from app.events import bind_emit
from app.llm import budget, chat, openrouter, prompts
from app.llm import client as llm_client
from app.llm.sensitive import _Flags
from app.presets import get_preset
from tests.test_llm import Events, FakeCtx, _raw_from

URL = "https://openrouter.ai/api/v1/chat/completions"
PRIMARY = "dots-studio/dots-3-note-preview:free"
ROUTED = "apodex/apodex-1.1-mini:free"


@pytest.fixture(autouse=True)
def _openrouter_env(_isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_TASKS", "all")     # structured() tests use the "sensitive" task
    config.reload_settings()
    llm_client.reset_client()
    yield
    llm_client.reset_client()


class Recorder:
    """httpx.MockTransport handler: replays ``script`` (Response objects or callables) in order."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.script.pop(0)
        return item(request) if callable(item) else item

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


def install(*script) -> Recorder:
    rec = Recorder(*script)
    openrouter.use_transport(httpx.MockTransport(rec))
    return rec


def completion(content: str, model: str = PRIMARY, finish: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={
        "id": "gen-1", "model": model, "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
    })


def sse(*chunks: dict, model: str = PRIMARY) -> httpx.Response:
    lines = [": OPENROUTER PROCESSING", ""]
    for c in chunks:
        lines += [f"data: {json.dumps({'model': model, **c}, ensure_ascii=False)}", ""]
    lines += ["data: [DONE]", ""]
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="\n".join(lines).encode())


def delta(finish: str | None = None, **d) -> dict:
    return {"choices": [{"index": 0, "delta": d, "finish_reason": finish}]}


FLAGS = {"flags": [{"i": 0, "sensitive": False}, {"i": 1, "sensitive": True}]}


async def call_flags(logs: list | None = None):
    async def emit(event, data):
        if logs is not None:
            logs.append(data.get("text", ""))

    with bind_emit(emit):
        return await llm_client.structured(_Flags, system="Flag sensitive texts.", user="[0] a\n[1] b", task="sensitive")


# --------------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------------


def test_provider_resolution(monkeypatch):
    s = config.get_settings()
    assert s.llm_provider == "openrouter" and s.llm_mode == "llm" and s.llm_model == PRIMARY
    assert s.openrouter_fallback_models == ("apodex/apodex-1.1-mini:free", "openrouter/free")
    assert s.openrouter_data_collection == "deny"

    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert config.reload_settings().llm_provider == "anthropic"          # auto: Anthropic key first
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert config.reload_settings().llm_provider == "openrouter"         # auto: then OpenRouter
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    s = config.reload_settings()
    assert s.llm_provider is None and s.llm_mode == "fallback"           # explicit provider without its key
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    config.reload_settings()
    assert llm_client.get_client() is None and llm_client.openrouter_active()
    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError):
        config.reload_settings()
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")   # teardown reloads settings before env is restored


def test_anthropic_client_ignores_stray_env(monkeypatch):
    """Another tool exports ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN in this shell; our client must
    not follow them."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://stray-proxy.invalid/v1")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stray-token")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    config.reload_settings()
    llm_client.reset_client()
    c = llm_client.get_client()
    assert str(c.base_url).rstrip("/") == "https://api.anthropic.com"
    assert c.auth_token is None and c.api_key == "sk-ant-test"

    monkeypatch.setenv("LLM_BASE_URL", "https://my-gateway.example/anthropic/")
    config.reload_settings()
    assert str(llm_client.get_client().base_url).rstrip("/") == "https://my-gateway.example/anthropic"


# --------------------------------------------------------------------------------------------
# structured()
# --------------------------------------------------------------------------------------------


async def test_structured_success_request_shape():
    rec = install(completion(json.dumps(FLAGS), model=ROUTED))
    logs: list[str] = []
    out = await call_flags(logs)
    assert isinstance(out, _Flags) and [f.sensitive for f in out.flags] == [False, True]

    req = rec.requests[0]
    assert str(req.url) == URL and req.method == "POST"
    assert req.headers["authorization"] == "Bearer sk-or-test-not-real"
    body = rec.body()
    assert body["model"] == PRIMARY
    assert body["models"] == [PRIMARY, ROUTED, "openrouter/free"]
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True and rf["json_schema"]["name"] == "Flags"
    schema = rf["json_schema"]["schema"]
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    assert schema["additionalProperties"] is False and schema["required"] == ["flags"]
    item = schema["properties"]["flags"]["items"]
    assert item["additionalProperties"] is False and item["required"] == ["i", "sensitive"]
    assert body["messages"][0]["role"] == "system" and "JSON schema" in body["messages"][0]["content"]
    assert body["max_tokens"] >= 4000 and "stream" not in body
    # the routed model is recorded for labeling
    assert llm_client.models_used() == {"sensitive": ROUTED}
    assert any(ROUTED in t for t in logs)


async def test_structured_fenced_json_and_think_tags():
    install(completion("<think>hmm</think>\n```json\n" + json.dumps(FLAGS) + "\n```"))
    out = await call_flags()
    assert out is not None and len(out.flags) == 2


async def test_structured_invalid_json_falls_back():
    install(completion("Sorry, I cannot produce JSON today."))
    logs: list[str] = []
    assert await call_flags(logs) is None
    assert any("deterministická záloha (invalid JSON" in t for t in logs)


async def test_structured_schema_mismatch_falls_back():
    install(completion(json.dumps({"flags": [{"i": "zero"}]})))
    logs: list[str] = []
    assert await call_flags(logs) is None
    assert any("invalid output (ValidationError)" in t for t in logs)


async def test_structured_daily_cap_429_blocks_later_calls():
    reset_ms = int((time.time() + 3600) * 1000)
    rec = install(httpx.Response(429, json={"error": {
        "code": 429, "message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day",
        "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_ms)}},
    }}))
    logs: list[str] = []
    assert await call_flags(logs) is None
    assert any("OpenRouter: denní limit free modelů" in t for t in logs)
    # the next task falls back immediately, without another request
    logs.clear()
    assert await call_flags(logs) is None
    assert len(rec.requests) == 1
    assert any("OpenRouter: denní limit free modelů" in t for t in logs)


async def test_structured_per_minute_429_and_5xx_do_not_block():
    rec = install(
        httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-min."}}),
        httpx.Response(503, json={"error": {"code": 503, "message": "No available providers"}}),
        completion(json.dumps(FLAGS)),
    )
    logs: list[str] = []
    assert await call_flags(logs) is None
    assert await call_flags(logs) is None
    assert await call_flags(logs) is not None
    assert len(rec.requests) == 3
    assert any("limit free modelů za minutu" in t for t in logs) and any("chyba serveru 503" in t for t in logs)


async def test_structured_truncated_and_policy_errors():
    install(
        completion('{"flags": [', finish="length"),
        httpx.Response(404, json={"error": {"code": 404, "message": "No endpoints found matching your data policy"}}),
    )
    logs: list[str] = []
    assert await call_flags(logs) is None
    assert await call_flags(logs) is None
    assert any("(truncated)" in t for t in logs)
    assert any("data policy" in t and "OPENROUTER_DATA_COLLECTION" in t for t in logs)


async def test_data_collection_allow_is_sent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_DATA_COLLECTION", "allow")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "")
    monkeypatch.setenv("OPENROUTER_MODEL_BULK", "nvidia/nemotron-3-super-120b-a12b:free")
    config.reload_settings()
    rec = install(completion(json.dumps(FLAGS)))
    assert await call_flags() is not None
    body = rec.body()
    assert body["provider"]["data_collection"] == "allow" and body["model"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert body["models"] == ["nvidia/nemotron-3-super-120b-a12b:free", "apodex/apodex-1.1-mini:free", "openrouter/free"]   # empty env var -> default fallbacks


async def test_default_task_list_skips_sensitive_and_topics(monkeypatch):
    monkeypatch.delenv("OPENROUTER_TASKS")            # default: chat, vetting, news
    s = config.reload_settings()
    assert s.openrouter_tasks == frozenset({"chat", "vetting", "news"})
    assert s.openrouter_bulk_tasks is False           # deprecated derived flag: not every bulk group
    rec = install()
    logs: list[str] = []
    assert await call_flags(logs) is None and rec.requests == [] and logs == []   # "sensitive": silent fallback
    assert llm_client.llm_available() and s.llm_mode == "llm"
    assert budget.requests_used() == 0

    # a vetting task is served by default and costs one request
    rec = install(completion(json.dumps(FLAGS)))
    with bind_emit(_noop):
        out = await llm_client.structured(_Flags, system="Claims.", user="x", task="claims")
    assert out is not None and len(rec.requests) == 1 and budget.requests_used() == 1


async def test_task_list_none_and_deprecated_bulk_flag(monkeypatch):
    monkeypatch.setenv("OPENROUTER_TASKS", "none")
    s = config.reload_settings()
    assert s.openrouter_tasks == frozenset() and not budget.llm_task_enabled("chat")
    rec = install()
    assert await call_flags() is None and rec.requests == []

    monkeypatch.delenv("OPENROUTER_TASKS")
    monkeypatch.setenv("OPENROUTER_BULK_TASKS", "1")   # deprecated: "1" without OPENROUTER_TASKS = all
    s = config.reload_settings()
    assert s.openrouter_tasks == frozenset(budget.ALL_GROUPS) and s.openrouter_bulk_tasks is True
    rec = install(completion(json.dumps(FLAGS)))
    assert await call_flags() is not None and len(rec.requests) == 1


async def _noop(event, data):
    return None


async def test_no_key_means_no_request(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    config.reload_settings()
    rec = install()
    assert await call_flags() is None and rec.requests == []


# --------------------------------------------------------------------------------------------
# rate limiter
# --------------------------------------------------------------------------------------------


async def test_rate_limiter_spacing_with_fast_clock():
    now = [1000.0]
    slept: list[float] = []

    async def fake_sleep(d: float) -> None:
        slept.append(d)
        now[0] += d

    lim = openrouter.RateLimiter(18, 60.0, clock=lambda: now[0], sleep=fake_sleep)
    for _ in range(18):
        assert await lim.acquire() == 0
    assert slept == []
    assert await lim.acquire() == pytest.approx(60.0)          # 19th waits for the window to slide
    assert now[0] == pytest.approx(1060.0)
    assert await lim.acquire() == 0                             # the 18 from t=1000 are out of the window
    # never more than 18 starts in any 60 s window, even when reservations queue up
    now[0] += 10
    delays = [lim.reserve() for _ in range(20)]
    assert delays == pytest.approx([0.0] * 16 + [50.0, 50.0, 60.0, 60.0])
    # a call that would queue longer than max_wait gives up instead of stalling
    with pytest.raises(openrouter.OpenRouterError) as e:
        await lim.acquire(max_wait=5.0)
    assert e.value.kind == "queue"


def test_rate_limiter_window_invariant():
    t = [0.0]
    lim = openrouter.RateLimiter(18, 60.0, clock=lambda: t[0])
    starts = []
    for i in range(100):
        t[0] = i * 0.7
        starts.append(t[0] + lim.reserve())
    starts.sort()
    for i in range(len(starts) - 18):
        assert starts[i + 18] - starts[i] >= 60.0 - 1e-9


# --------------------------------------------------------------------------------------------
# schema / history translation
# --------------------------------------------------------------------------------------------


def test_strict_schema_and_json_parsing():
    js = openrouter.strict_schema(_Flags)
    assert js["properties"]["flags"]["items"]["properties"]["i"] == {"type": "integer"}
    assert openrouter.parse_json_text('Here you go: {"a": 1} hope it helps') == {"a": 1}
    with pytest.raises(ValueError):
        openrouter.parse_json_text("no json")


def test_history_translation():
    history = [
        {"role": "user", "content": [{"type": "text", "text": "Ahoj"}, {"type": "text", "text": "[server note] board"}]},
        {"role": "system", "content": "Server guard: x"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "Dobře."},
                                          {"type": "tool_use", "id": "tu1", "name": "run_rounds", "input": {"up_to": 3}},
                                          {"type": "tool_use", "id": "tu2", "name": "run_rounds", "input": {"up_to": 1}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": '{"ok": true}'},
                                     {"type": "tool_result", "tool_use_id": "zz", "content": "orphan"}]},
        {"role": "assistant", "content": "Hotovo."},
    ]
    msgs = openrouter.to_openai_messages("SYS", history)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "tool", "assistant"]
    assert msgs[1]["content"] == "Ahoj\n\n[server note] board\n\n[server note] Server guard: x"
    assert msgs[2]["content"] == "Dobře." and msgs[2]["tool_calls"][0]["function"] == {"name": "run_rounds", "arguments": '{"up_to": 3}'}
    assert msgs[3] == {"role": "tool", "tool_call_id": "tu1", "content": '{"ok": true}'}
    assert msgs[4]["tool_call_id"] == "tu2"           # missing result filled, orphan dropped
    tools = openrouter.openai_tools(chat.TOOLS)
    assert [t["function"]["name"] for t in tools] == [t["name"] for t in chat.TOOLS]
    assert all(t["type"] == "function" and "eager_input_streaming" not in t["function"] for t in tools)


# --------------------------------------------------------------------------------------------
# chat tool loop
# --------------------------------------------------------------------------------------------


async def test_chat_loop_tool_call_then_text():
    raw = _raw_from(get_preset("bakery"))
    args = json.dumps(raw, ensure_ascii=False)
    half = len(args) // 2
    rec = install(
        sse(
            delta(content="Navrhuji kritéria. "),
            delta(tool_calls=[{"index": 0, "id": "call_1", "type": "function",
                               "function": {"name": "propose_criteria", "arguments": args[:half]}}]),
            delta(tool_calls=[{"index": 0, "function": {"arguments": args[half:]}}]),
            delta(finish="tool_calls"),
        ),
        sse(delta(content="Hotovo, "), delta(content="spustím kola?"), delta(finish="stop"),
            model=ROUTED),
    )
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Mám pekárnu v Brně.", ctx, ev)

    assert ev.text() == "Navrhuji kritéria. Hotovo, spustím kola?"
    assert [c[0] for c in ctx.calls] == ["propose_criteria"]
    assert len(ctx.criteria.criteria) == 15
    tool_ev = next(d for e, d in ev.items if e == "chat.tool")
    assert tool_ev["name"] == "propose_criteria" and "error" not in tool_ev["result"]
    assert ev.items[-1] == ("done", {"llm_mode": "llm", "llm_model": ROUTED, "lang": "cs"})

    first, second = rec.body(0), rec.body(1)
    assert first["stream"] is True and first["model"] == PRIMARY
    assert first["provider"]["require_parameters"] is True
    assert first["messages"][0] == {"role": "system", "content": prompts.CHAT_SYSTEM}   # identical prompt
    assert first["messages"][1]["role"] == "user" and "[server note]" in first["messages"][1]["content"]
    assert [t["function"]["name"] for t in first["tools"]] == [t["name"] for t in chat.TOOLS]
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["tool_calls"][0]["id"] == "call_1"
    assert second["messages"][3]["tool_call_id"] == "call_1"
    # canonical history stays in Anthropic format
    assert [m["role"] for m in ctx.history] == ["user", "assistant", "user", "assistant"]
    assert ctx.history[1]["content"][1] == {"type": "tool_use", "id": "call_1", "name": "propose_criteria", "input": raw}
    assert ctx.history[2]["content"][0]["type"] == "tool_result"
    assert llm_client.models_used()["chat"] == ROUTED


async def test_chat_guards_still_apply_over_openrouter():
    ctx, ev = FakeCtx("cs"), Events()
    from tests.test_llm import make_run

    ctx.criteria = get_preset("bakery")
    ctx.run = make_run(ctx.criteria)
    install(
        sse(delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "start_deep_vetting",
                                                                  "arguments": '{"candidate_ids": ["instagram:anna"]}'}}]),
            delta(finish="tool_calls")),
        sse(delta(content="Mám je prověřit?"), delta(finish="stop")),
    )
    await chat.chat_turn("Co dál?", ctx, ev)
    assert not any(c[0] == "start_deep_vetting" for c in ctx.calls)
    tool_ev = next(d for e, d in ev.items if e == "chat.tool")
    assert "Not confirmed" in tool_ev["result"]["error"]


async def test_chat_invalid_tool_arguments_get_error_result():
    rec = install(
        sse(delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "run_rounds", "arguments": "{up_to: 3"}}]),
            delta(finish="tool_calls")),
        sse(delta(content="Omlouvám se."), delta(finish="stop")),
    )
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Spusť to.", ctx, ev)
    assert ctx.calls == [] and ev.text() == "Omlouvám se."
    tool_msg = rec.body(1)["messages"][-1]
    assert tool_msg["role"] == "tool" and "INVALID_JSON" in tool_msg["content"]


async def test_chat_http_error_before_output_uses_scripted_fallback():
    install(httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-min."}}))
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Ahoj", ctx, ev)
    assert "Co prodáváte a kde?" in ev.text()
    assert ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "cs"})
    assert [m["role"] for m in ctx.history] == ["user", "assistant"]


async def test_chat_mid_stream_error_after_text_apologizes():
    install(sse(delta(content="Začínám… "),
                {"error": {"code": 502, "message": "provider died"}, "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}]}))
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Ahoj", ctx, ev)
    assert ev.text().startswith("Začínám… ") and "odpověď se nedokončila" in ev.text()
    assert ev.items[-1][0] == "done" and ev.items[-1][1]["llm_mode"] == "llm"


# --------------------------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------------------------


def test_health_reports_provider_and_model():
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).get("/api/health").json()
    assert r["llm_mode"] == "llm" and r["llm_provider"] == "openrouter" and r["llm_model"] == PRIMARY
    assert r["llm_models_used"] == {}


# --------------------------------------------------------------------------------------------
# review: strict schemas, failure modes, stream quirks
# --------------------------------------------------------------------------------------------

_STRICT_FORBIDDEN = {"default", "title", "$schema", "examples", "$ref", "$defs", "oneOf", "discriminator", "not",
                     "patternProperties", "propertyNames", "minProperties", "maxProperties", "if", "then", "else"}


def _strict_problems(node, path="$") -> list[str]:
    """OpenAI-style strict json_schema rules: no unsupported keywords, every object closed
    (additionalProperties false) with all of its properties required."""
    out: list[str] = []
    if isinstance(node, list):
        for i, n in enumerate(node):
            out += _strict_problems(n, f"{path}[{i}]")
        return out
    if not isinstance(node, dict):
        return out
    out += [f"{path}: {k}" for k in node if k in _STRICT_FORBIDDEN]
    if node.get("type") == "object" or "properties" in node:
        if node.get("additionalProperties") is not False:
            out.append(f"{path}: additionalProperties must be false")
        props = node.get("properties") or {}
        if sorted(node.get("required") or []) != sorted(props):
            out.append(f"{path}: every property must be required")
        for name, sub in props.items():
            out += _strict_problems(sub, f"{path}.{name}")
    if isinstance(node.get("items"), dict):
        out += _strict_problems(node["items"], f"{path}[]")
    for k in ("anyOf", "allOf"):
        if isinstance(node.get(k), list):
            out += _strict_problems(node[k], f"{path}.{k}")
    return out


def test_every_llm_schema_converts_to_strict_json_schema():
    """Every pydantic model the LLM layer sends to structured() must survive strict mode; a new
    dict-typed or otherwise open field would make OpenRouter providers reject the request."""
    from typing import Literal

    from pydantic import BaseModel, Field

    from app.llm import sensitive, topics, vetting

    used = [sensitive._Flags, topics._Labels, vetting._LLMClaims, vetting._NewsLabels, vetting._Skeptic,
            vetting._Questions, vetting._Draft]
    for model in used:
        js = openrouter.strict_schema(model)
        assert js["type"] == "object", model.__name__
        assert _strict_problems(js) == [], model.__name__
        json.dumps(js)

    class Cat(BaseModel):
        kind: Literal["cat"] = "cat"
        name: str = ""

    class Dog(BaseModel):
        kind: Literal["dog"] = "dog"

    class Pet(BaseModel):
        pet: Cat | Dog = Field(discriminator="kind")
        note: str | None = None

    js = openrouter.strict_schema(Pet)
    assert _strict_problems(js) == []
    assert "anyOf" in js["properties"]["pet"] and "#/$defs" not in json.dumps(js)


async def test_structured_connection_error_and_garbage_fall_back():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    install(boom, httpx.Response(200, content=b"<html>gateway</html>"),
            httpx.Response(200, json={"choices": []}))
    logs: list[str] = []
    assert await call_flags(logs) is None
    assert await call_flags(logs) is None
    assert await call_flags(logs) is None
    assert any("chyba spojení" in t for t in logs)
    assert any("odpověď není JSON" in t for t in logs)
    assert any("prázdná odpověď" in t for t in logs)


async def test_logs_never_contain_key_or_prompt(caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    install(httpx.Response(401, json={"error": {"code": 401, "message": "User not found."}}))
    logs: list[str] = []
    assert await call_flags(logs) is None
    text = caplog.text + "\n".join(logs)
    assert "sk-or-test-not-real" not in text and "[0] a" not in text
    assert "neplatný API klíč" in text


async def test_chat_tool_calls_without_index_are_reassembled():
    args = '{"up_to": 3}'
    install(
        sse(delta(tool_calls=[{"id": "c1", "type": "function", "function": {"name": "run_rounds", "arguments": args[:5]}}]),
            delta(tool_calls=[{"function": {"arguments": args[5:]}}]),
            delta(finish="tool_calls")),
        sse(delta(content="Hotovo."), delta(finish="stop")),
    )
    ctx, ev = FakeCtx("cs"), Events()
    ctx.criteria = get_preset("bakery")
    await chat.chat_turn("Spusť kola.", ctx, ev)
    assert [c[0] for c in ctx.calls] == ["run_rounds"]


async def test_stream_index_less_same_tool_twice_without_ids_is_two_calls():
    install(sse(
        delta(tool_calls=[{"function": {"name": "explain_elimination", "arguments": '{"candidate_id": '}}]),
        delta(tool_calls=[{"function": {"name": "explain_elimination", "arguments": '"a"}'}}]),
        delta(tool_calls=[{"function": {"name": "explain_elimination", "arguments": '{"candidate_id": "b"}'}}]),
        delta(finish="tool_calls")))

    async def on_text(_t: str) -> None:
        return None

    res = await openrouter.stream_chat([{"role": "user", "content": "x"}], tools=[], model="m/x:free", on_text=on_text)
    assert [(c.name, c.input) for c in res.tool_calls] == [
        ("explain_elimination", {"candidate_id": "a"}), ("explain_elimination", {"candidate_id": "b"})]
    assert len({c.id for c in res.tool_calls}) == 2


async def test_chat_unknown_tool_is_refused_and_nothing_is_sent():
    rec = install(
        sse(delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "send_email",
                                                                  "arguments": '{"to": "x@example.com"}'}}]),
            delta(finish="tool_calls")),
        sse(delta(content="To neumím."), delta(finish="stop")),
    )
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Pošli jim mail.", ctx, ev)
    assert ctx.calls == []
    assert "Unknown tool" in rec.body(1)["messages"][-1]["content"]


async def test_chat_step_cap_and_blocked_key(caplog):
    import logging

    loop = [sse(delta(tool_calls=[{"index": 0, "id": f"c{i}", "function": {"name": "explain_elimination",
                                                                          "arguments": '{"candidate_id": "nobody"}'}}]),
                delta(finish="tool_calls")) for i in range(chat.MAX_TOOL_STEPS + 2)]
    rec = install(*loop)
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Proč?", ctx, ev)
    assert len(rec.requests) == chat.MAX_TOOL_STEPS
    assert ev.items[-1][0] == "done"

    # a daily cap blocks the key: the next chat turn goes straight to the scripted fallback, with a log line
    caplog.set_level(logging.WARNING)
    rec = install(httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}}))
    ctx2, ev2 = FakeCtx("cs"), Events()
    await chat.chat_turn("Ahoj", ctx2, ev2)
    assert ev2.items[-1] == ("done", {"llm_mode": "fallback", "lang": "cs"})
    ctx3, ev3 = FakeCtx("cs"), Events()
    await chat.chat_turn("Ahoj", ctx3, ev3)
    assert ev3.items[-1] == ("done", {"llm_mode": "fallback", "lang": "cs"}) and len(rec.requests) == 1
    assert "denní limit free modelů" in caplog.text
