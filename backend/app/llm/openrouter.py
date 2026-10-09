"""OpenRouter provider: OpenAI-compatible ``/chat/completions`` over plain httpx (no extra dependency).

Active when ``get_settings().llm_provider == "openrouter"`` (LLM_PROVIDER=openrouter, or auto with only
OPENROUTER_API_KEY set). Used by ``client.structured()`` (bulk tasks) and ``chat.chat_turn()`` (tool loop).

- Every request: ``model`` + ``models`` (primary + OPENROUTER_FALLBACK_MODELS, OpenRouter tries them in
  order), ``provider.require_parameters`` (only providers that support tools / response_format) and
  ``provider.data_collection`` from OPENROUTER_DATA_COLLECTION.
- Structured output: ``response_format`` json_schema (strict) built from the pydantic model, plus the
  schema in the system prompt; the reply is parsed (code fences / think tags stripped) and validated
  with pydantic. Anything wrong raises ``OpenRouterError`` / ``ValueError``; callers fall back.
- One shared sliding-window rate limiter (18 requests per 60 s, below the free tier's ~20/min). A call
  that would wait longer than its ``max_wait`` raises instead of stalling the funnel.
- A daily-cap 429 (free-models-per-day), 401 or 402 blocks further calls until the reset time
  (header ``X-RateLimit-Reset``) or a short cool-down, so every later task falls back immediately.
- Request budget (``budget.py``): ``stream_chat`` spends one "chat" request before taking a rate-limit
  slot and raises ``OpenRouterError(kind="budget")`` when the budget is used up. ``complete_json`` does
  not spend: its caller ``client.structured()`` already did.
- ``_transport`` lets tests plug in ``httpx.MockTransport``; no test talks to the network.

Never logs the API key. Prompts carry real public creator data: see OPENROUTER_DATA_COLLECTION.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.llm import budget

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)

RATE_LIMIT_PER_MIN = 18          # free tier allows ~20 requests/minute; keep a margin
STRUCTURED_MAX_WAIT = 60.0       # seconds a bulk task may queue for a rate-limit slot before falling back
CHAT_MAX_WAIT = 30.0             # the owner is watching the chat: give up sooner
MAX_MODELS = 3                   # primary + 2 fallbacks
STRUCTURED_TIMEOUT = 120.0
CHAT_TIMEOUT = 120.0             # per read between SSE chunks (OpenRouter sends keep-alive comments)
CHAT_MAX_TOKENS = 8000
_MIN_STRUCTURED_TOKENS = 8000    # reasoning models spend output tokens on thinking before the JSON

# Tests: httpx.MockTransport. None = real network.
_transport: httpx.AsyncBaseTransport | None = None


class OpenRouterError(Exception):
    """A failed OpenRouter call. ``reason`` is the short label for the fallback log line."""

    def __init__(self, reason: str, *, status: int | None = None, kind: str = "error",
                 reset_at: float | None = None, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.kind = kind          # daily | minute | upstream | auth | credits | policy | queue | blocked | budget | error
        self.reset_at = reset_at  # epoch seconds (daily cap)
        self.detail = detail


# --------------------------------------------------------------------------------------------
# Rate limiter + circuit breaker
# --------------------------------------------------------------------------------------------


class RateLimiter:
    """Sliding window: at most ``max_calls`` request starts in any ``period`` seconds.

    Slots are reserved synchronously (no await between check and reserve), so concurrent tasks on one
    event loop never oversubscribe and no lock is needed. ``clock`` / ``sleep`` are injectable (tests)."""

    def __init__(self, max_calls: int, period: float = 60.0, *,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        self.max_calls = max(1, int(max_calls))
        self.period = float(period)
        self.clock = clock
        self.sleep = sleep
        self._stamps: deque[float] = deque()   # reserved start times, non-decreasing

    def reserve(self, max_wait: float | None = None) -> float | None:
        """Reserve the next slot; -> seconds to wait, or None if that is longer than ``max_wait``."""
        now = self.clock()
        while self._stamps and self._stamps[0] <= now - self.period:
            self._stamps.popleft()
        if len(self._stamps) < self.max_calls:
            at = now
        else:
            at = max(now, self._stamps[-self.max_calls] + self.period)
        delay = at - now
        if max_wait is not None and delay > max_wait:
            return None
        self._stamps.append(at)
        return delay

    async def acquire(self, max_wait: float | None = None) -> float:
        delay = self.reserve(max_wait)
        if delay is None:
            raise OpenRouterError(f"OpenRouter: fronta přes limit {self.max_calls} dotazů/min", kind="queue")
        if delay > 0:
            await self.sleep(delay)
        return delay


limiter = RateLimiter(RATE_LIMIT_PER_MIN, 60.0)

# (api key, blocked until epoch seconds, reason)
_blocked: tuple[str, float, str] | None = None


def reset() -> None:
    """Fresh limiter, no block, real network (tests)."""
    global limiter, _blocked, _transport
    limiter = RateLimiter(RATE_LIMIT_PER_MIN, 60.0)
    _blocked = None
    _transport = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route every OpenRouter request through ``transport`` (tests: httpx.MockTransport)."""
    global _transport
    _transport = transport


def check_blocked() -> None:
    """Raise when a previous daily-cap / auth / credit error still blocks calls with this key."""
    global _blocked
    if _blocked is None:
        return
    key, until, reason = _blocked
    if key != (get_settings().openrouter_api_key or "") or time.time() >= until:
        _blocked = None
        return
    raise OpenRouterError(reason, kind="blocked")


def _remember(err: OpenRouterError) -> OpenRouterError:
    """Block further calls after errors that will not go away by retrying right now."""
    global _blocked
    now = time.time()
    until = None
    if err.kind == "daily":
        until = err.reset_at if err.reset_at and err.reset_at > now else now + 3600
        until = min(until, now + 24 * 3600)
    elif err.kind == "auth":
        until = now + 3600
    elif err.kind == "credits":
        until = now + 600
    if until is not None:
        _blocked = (get_settings().openrouter_api_key or "", until, err.reason)
        log.warning("OpenRouter blocked for %.0f s: %s (%s)", until - now, err.reason, err.detail[:200])
    return err


# --------------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------------


def _reset_epoch(meta: dict, headers: Any) -> float | None:
    raw = None
    h = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    for k, v in h.items():
        if str(k).lower() == "x-ratelimit-reset":
            raw = v
    if raw is None and headers is not None:
        raw = headers.get("x-ratelimit-reset")
        if raw is None and headers.get("retry-after"):
            try:
                return time.time() + float(headers.get("retry-after"))
            except (TypeError, ValueError):
                return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val / 1000.0 if val > 1e11 else val   # OpenRouter sends epoch milliseconds


def classify_error(status: int, body: Any, headers: Any = None) -> OpenRouterError:
    """HTTP status + OpenRouter error body -> OpenRouterError with a short Czech reason."""
    data: Any = body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            data = json.loads(body)
        except ValueError:
            data = {"error": {"message": body}}
    err = data.get("error") if isinstance(data, dict) else None
    err = err if isinstance(err, dict) else {}
    msg = str(err.get("message") or "")
    meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
    low = (msg + " " + json.dumps(meta, ensure_ascii=False, default=str)).lower()

    def e(reason: str, kind: str = "error", reset_at: float | None = None) -> OpenRouterError:
        return OpenRouterError(reason, status=status, kind=kind, reset_at=reset_at, detail=msg)

    if status == 429:
        if "per-day" in low or "per day" in low or "daily" in low:
            return e("OpenRouter: denní limit free modelů", "daily", _reset_epoch(meta, headers))
        if "per-min" in low or "per minute" in low:
            return e("OpenRouter: limit free modelů za minutu", "minute")
        if "upstream" in low:
            return e("OpenRouter: provider free modelu je přetížený (429)", "upstream")
        return e("OpenRouter: rate limit (429)", "minute")
    if status == 401:
        return e("OpenRouter: neplatný API klíč (401)", "auth")
    if status == 402:
        return e("OpenRouter: nedostatek kreditu (402)", "credits")
    if status == 403:
        return e("OpenRouter: požadavek zablokovala moderace (403)")
    if status == 404 and ("data policy" in low or "privacy" in low or "data_collection" in low):
        return e("OpenRouter: žádný provider nesplňuje data policy (OPENROUTER_DATA_COLLECTION)", "policy")
    if status == 404:
        return e("OpenRouter: žádný provider pro model a parametry (404)")
    if status == 408:
        return e("OpenRouter: timeout (408)")
    if status == 400:
        # live 9. 10. 2026: the claims step (the largest prompt) failed once with a bare 400; the provider's own
        # message (context length, unsupported parameter, schema) goes into the log so the cause is visible
        log.warning("OpenRouter 400: %s %s", msg[:500], json.dumps(meta, ensure_ascii=False, default=str)[:500])
        hint = " ".join((str(meta.get("raw") or "") if not msg or msg == "Provider returned error" else msg).split())[:160]
        hint = hint.replace('"', "'")   # quoted: the log's phrase table never touches it
        return e("OpenRouter: chybný požadavek (400)" + (f': "{hint}"' if hint else ""))
    if status >= 500:
        return e(f"OpenRouter: chyba serveru {status}")
    return e(f"OpenRouter: HTTP {status}")


# --------------------------------------------------------------------------------------------
# Request plumbing
# --------------------------------------------------------------------------------------------


def models_for(primary: str) -> list[str]:
    """Primary model first, then the configured fallbacks, deduplicated, at most MAX_MODELS."""
    out: list[str] = []
    for m in (primary, *get_settings().openrouter_fallback_models):
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out[:MAX_MODELS]


def request_body(model: str, messages: list[dict], *, max_tokens: int, stream: bool = False) -> dict[str, Any]:
    models = models_for(model)
    body: dict[str, Any] = {
        "model": models[0],
        "messages": messages,
        "max_tokens": int(max_tokens),
        "provider": {"require_parameters": True, "data_collection": get_settings().openrouter_data_collection},
    }
    if len(models) > 1:
        body["models"] = models
    if stream:
        body["stream"] = True
    return body


def _headers() -> dict[str, str]:
    key = get_settings().openrouter_api_key
    if not key:
        raise OpenRouterError("OpenRouter: chybí OPENROUTER_API_KEY", kind="auth")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Creator Scout"}


def _http(read_timeout: float) -> httpx.AsyncClient:
    # A fresh client per call: no connection pool bound to an old event loop, trivial next to LLM latency.
    return httpx.AsyncClient(
        base_url=get_settings().openrouter_base_url,
        timeout=httpx.Timeout(read_timeout, connect=10.0),
        transport=_transport,
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


# --------------------------------------------------------------------------------------------
# Structured output
# --------------------------------------------------------------------------------------------

# discriminator: its mapping points into $defs, which are inlined and removed here.
_DROP_KEYS = {"title", "default", "examples", "$schema", "discriminator"}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema -> strict-mode compatible schema: $refs inlined, titles/defaults dropped,
    every object ``additionalProperties: false`` with all its properties required."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {}) or {}

    def fix(node: Any, depth: int = 0) -> Any:
        if depth > 32:
            raise ValueError("schema too deep (recursive model?)")
        if isinstance(node, list):
            return [fix(n, depth + 1) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            merged = {**defs.get(name, {}), **{k: v for k, v in node.items() if k != "$ref"}}
            return fix(merged, depth + 1)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _DROP_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {name: fix(sub, depth + 1) for name, sub in v.items()}
            elif k in ("items", "additionalProperties", "not") and isinstance(v, dict):
                out[k] = fix(v, depth + 1)
            elif k == "oneOf" and isinstance(v, list):
                out["anyOf"] = [fix(s, depth + 1) for s in v]   # strict mode supports anyOf, not oneOf
            elif k in ("anyOf", "allOf", "prefixItems") and isinstance(v, list):
                out[k] = [fix(s, depth + 1) for s in v]
            else:
                out[k] = v
        if "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        elif out.get("type") == "object" and not isinstance(out.get("additionalProperties"), dict):
            out["additionalProperties"] = False
        return out

    return fix(raw)


def _schema_name(model: type[BaseModel]) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", model.__name__).strip("_") or "output"
    return name[:64]


def json_instruction(schema: dict[str, Any]) -> str:
    return (
        "\n\nOutput format: reply with exactly one JSON object and nothing else (no prose, no Markdown code "
        "fences). It must match this JSON schema:\n" + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )


_RX_THINK = re.compile(r"(?is)^\s*<think>.*?</think>\s*")
_RX_FENCE = re.compile(r"(?s)^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?\s*```$")


def parse_json_text(text: str) -> Any:
    """Model text -> JSON value. Strips <think> blocks and ``` fences; as a last resort takes the
    outermost {...}. Raises ValueError (json.JSONDecodeError) when nothing parses."""
    t = _RX_THINK.sub("", text or "").strip()
    m = _RX_FENCE.match(t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if 0 <= start < end:
            return json.loads(t[start:end + 1])
        raise


async def complete_json(
    schema: type[T], *, system: str, user: str, model: str, max_tokens: int,
) -> tuple[T, str]:
    """One structured call. -> (validated output, model that answered). Raises OpenRouterError,
    pydantic.ValidationError or ValueError; never returns partial data."""
    check_blocked()
    js = strict_schema(schema)            # before taking a rate-limit slot: a bad schema costs no request
    await limiter.acquire(STRUCTURED_MAX_WAIT)
    check_blocked()                       # a daily cap may have been hit while this call was queued
    messages = [{"role": "system", "content": system + json_instruction(js)}, {"role": "user", "content": user}]
    body = request_body(model, messages, max_tokens=max(int(max_tokens), _MIN_STRUCTURED_TOKENS))
    body["response_format"] = {"type": "json_schema", "json_schema": {"name": _schema_name(schema), "strict": True, "schema": js}}
    try:
        async with _http(STRUCTURED_TIMEOUT) as http:
            resp = await http.post("/chat/completions", json=body, headers=_headers())
    except httpx.TimeoutException as e:
        raise OpenRouterError("OpenRouter: timeout") from e
    except httpx.HTTPError as e:
        raise OpenRouterError("OpenRouter: chyba spojení") from e
    if resp.status_code != 200:
        raise _remember(classify_error(resp.status_code, resp.content, resp.headers))
    try:
        data = resp.json()
    except ValueError as e:
        raise OpenRouterError("OpenRouter: odpověď není JSON") from e
    if not isinstance(data, dict):
        raise OpenRouterError("OpenRouter: neočekávaná odpověď")
    if data.get("error"):
        code = data["error"].get("code") if isinstance(data["error"], dict) else None
        raise _remember(classify_error(code if isinstance(code, int) else 502, data, resp.headers))
    choices = data.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    finish = choice.get("finish_reason")
    msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = _content_text(msg.get("content"))
    if finish == "length":
        raise OpenRouterError("truncated")
    if finish == "content_filter" or msg.get("refusal"):
        raise OpenRouterError("refusal")
    if finish == "error":
        raise OpenRouterError("OpenRouter: chyba providera")
    if not text.strip():
        raise OpenRouterError("OpenRouter: prázdná odpověď")
    value = parse_json_text(text)
    out = schema.model_validate(value)
    return out, str(data.get("model") or body["model"])


# --------------------------------------------------------------------------------------------
# Chat: tools, history translation, SSE streaming
# --------------------------------------------------------------------------------------------


def openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tool definitions -> OpenAI function tools (same names, descriptions, schemas)."""
    return [
        {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                          "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
        for t in tools
    ]


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def to_openai_messages(system: str, history: list[dict]) -> list[dict[str, Any]]:
    """Our chat history (Anthropic Messages format, the canonical store) -> OpenAI chat messages.

    text blocks -> content strings; tool_use -> assistant tool_calls; tool_result -> role "tool";
    thinking blocks dropped; mid-conversation system notes -> "[server note]" user text. Consecutive
    user texts are merged; every tool call gets exactly one tool message (a missing one is filled)."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    pending: list[str] = []       # tool_call ids of the last assistant message still without a result

    def close_pending() -> None:
        for cid in pending:
            out.append({"role": "tool", "tool_call_id": cid, "content": "(no result)"})
        pending.clear()

    def user_text(text: str) -> None:
        if not text:
            return
        close_pending()
        if out[-1]["role"] == "user" and isinstance(out[-1].get("content"), str):
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": "user", "content": text})

    for m in history:
        role, content = m.get("role"), m.get("content")
        if role == "system":
            user_text(f"[server note] {_block_text(content)}")
        elif role == "user":
            if isinstance(content, str):
                user_text(content)
                continue
            texts: list[str] = []
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    cid = str(b.get("tool_use_id") or "")
                    if cid not in pending:
                        continue          # orphan result: its call is gone, drop it
                    pending.remove(cid)
                    c = b.get("content")
                    out.append({"role": "tool", "tool_call_id": cid,
                                "content": c if isinstance(c, str) else _block_text(c) or json.dumps(c, ensure_ascii=False, default=str)})
                elif b.get("type") == "text":
                    texts.append(str(b.get("text") or ""))
            user_text("\n\n".join(t for t in texts if t))
        elif role == "assistant":
            close_pending()
            if isinstance(content, str):
                if content:
                    out.append({"role": "assistant", "content": content})
                continue
            texts, calls = [], []
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    texts.append(str(b["text"]))
                elif b.get("type") == "tool_use":
                    calls.append({"id": str(b.get("id")), "type": "function",
                                  "function": {"name": str(b.get("name")),
                                               "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
            if not texts and not calls:
                continue
            msg: dict[str, Any] = {"role": "assistant", "content": "".join(texts) if texts else None}
            if calls:
                msg["tool_calls"] = calls
                pending.extend(c["id"] for c in calls)
            out.append(msg)
    close_pending()
    return out


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str
    input: dict | None = None     # None: arguments were not a JSON object


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    model: str = ""


def _is_json_object(raw: str) -> bool:
    try:
        return bool(raw.strip()) and isinstance(json.loads(raw), dict)
    except ValueError:
        return False


def _finish_calls(acc: dict[int, dict[str, Any]]) -> list[ToolCall]:
    calls = []
    for n, idx in enumerate(sorted(acc)):
        a = acc[idx]
        if not a["name"]:
            continue
        raw = a["args"]
        parsed: dict | None
        try:
            v = json.loads(raw) if raw.strip() else {}
            parsed = v if isinstance(v, dict) else None
        except ValueError:
            parsed = None
        calls.append(ToolCall(id=a["id"] or f"call_{n}_{int(time.time() * 1000)}", name=a["name"], arguments=raw, input=parsed))
    return calls


async def stream_chat(
    messages: list[dict[str, Any]], *, tools: list[dict[str, Any]], model: str,
    on_text: Callable[[str], Awaitable[None]], max_tokens: int = CHAT_MAX_TOKENS,
) -> ChatResult:
    """One streamed chat/completions call (SSE). Text deltas go to ``on_text`` as they arrive; tool
    call fragments are accumulated by index. Raises OpenRouterError on HTTP / stream errors, and with
    kind "budget" when the LLM request budget is used up (nothing is sent)."""
    check_blocked()
    if not await budget.spend("chat"):
        raise OpenRouterError(budget.EXHAUSTED_REASON, kind="budget")
    await limiter.acquire(CHAT_MAX_WAIT)
    check_blocked()                       # a daily cap may have been hit while this call was queued
    body = request_body(model, messages, max_tokens=max_tokens, stream=True)
    body["tools"] = tools
    res = ChatResult(model=body["model"])
    acc: dict[int, dict[str, Any]] = {}
    try:
        async with _http(CHAT_TIMEOUT) as http:
            async with http.stream("POST", "/chat/completions", json=body, headers=_headers()) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    raise _remember(classify_error(resp.status_code, raw, resp.headers))
                async for line in resp.aiter_lines():
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue          # blank separators and ": OPENROUTER PROCESSING" keep-alives
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        err = chunk["error"] if isinstance(chunk["error"], dict) else {"message": str(chunk["error"])}
                        code = err.get("code")
                        raise _remember(classify_error(code if isinstance(code, int) else 502, {"error": err}))
                    if chunk.get("model"):
                        res.model = str(chunk["model"])
                    for choice in chunk.get("choices") or []:
                        if not isinstance(choice, dict):
                            continue
                        delta = choice.get("delta") or {}
                        text = delta.get("content")
                        if isinstance(text, str) and text:
                            res.text += text
                            await on_text(text)
                        for tc in delta.get("tool_calls") or []:
                            if not isinstance(tc, dict):
                                continue
                            idx = tc.get("index")
                            if not isinstance(idx, int):
                                # No index (some providers): a fragment with a new id, or a name while the
                                # last call already has a different name or complete arguments (the same
                                # tool called twice), starts a new call; anything else continues it.
                                last = acc[max(acc)] if acc else None
                                fn0 = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                                tid = str(tc.get("id") or "")
                                starts = last is None or (tid and tid != last["id"]) or (
                                    not tid and bool(fn0.get("name")) and bool(last["name"])
                                    and (fn0.get("name") != last["name"] or _is_json_object(last["args"])))
                                idx = (max(acc) + 1 if acc else 0) if starts else max(acc)
                            a = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                            if tc.get("id"):
                                a["id"] = str(tc["id"])
                            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                            name = fn.get("name")
                            if name and name != a["name"]:
                                a["name"] += str(name)
                            args = fn.get("arguments")
                            if isinstance(args, dict):
                                a["args"] = json.dumps(args, ensure_ascii=False)
                            elif isinstance(args, str):
                                a["args"] += args
                        if choice.get("finish_reason"):
                            res.finish_reason = str(choice["finish_reason"])
    except httpx.TimeoutException as e:
        raise OpenRouterError("OpenRouter: timeout") from e
    except httpx.HTTPError as e:
        raise OpenRouterError("OpenRouter: chyba spojení") from e
    if res.finish_reason == "error":
        raise OpenRouterError("OpenRouter: chyba providera během streamu")
    res.tool_calls = _finish_calls(acc)
    return res
