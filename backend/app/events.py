"""SSE event bus per run + the ``emit`` callable contract.

``Emit`` is ``async def emit(event: str, data: dict) -> None``. Event names and payloads
(architecture.md section 7). ``data`` may contain pydantic models; ``EventBus.publish`` converts
it with ``pydantic_core.to_jsonable_python`` before storing / sending, so emitters need not dump.

Run events:
  run.started          {"run_id": str}
  log                  {"text": str, "actor": str | None, "mode": "live"|"cache"|"mock"|None, "ts": iso str}
  round.started        {"round": int}
  candidate.added      {"candidate": Candidate}
  candidate.updated    {"candidate": Candidate}
  candidate.eliminated {"id": str, "elimination": Elimination}
  round.finished       {"round": int, "entered": int, "remaining": int}
  sensitive.filtered   {"candidate_id": str, "count": int}
  vetting.progress     {"candidate_id": str, "step": str}
  report.ready         {"candidate_id": str}
  diff                 {"dropped": [DiffEntry], "returned": [DiffEntry]}   (see rounds/engine.py)
  run.finished         {"run_id": str}
  error                {"message": str}
Chat events (POST /api/chat SSE):
  chat.delta {"text": str} · chat.tool {"name": str, "input": dict, "result": dict}
  criteria.updated {"criteria": CriteriaSet} · done {"chat_id": str, "run_id": str | None}
  error {"message": str}  (chat failed; ``done`` still follows and is always the last event)

SSE wire format (``format_sse``): ``id: <n>`` (run streams only; 1-based position in the run's
history, so EventSource resumes via Last-Event-ID), ``event: <name>``, ``data: <one-line JSON>``,
blank line. ``: keepalive`` comment every 15 s of silence.

Providers and other deep code log through ``emit_log(...)``, which uses the ``current_emit``
context variable. The engine binds it at the start of run_funnel / run_vetting
(``with bind_emit(emit): ...``); asyncio tasks created inside inherit it.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextvars import ContextVar
from typing import Any

from pydantic_core import to_jsonable_python

from app.models import Mode, utcnow

Emit = Callable[[str, dict], Awaitable[None]]

RUN_EVENTS: tuple[str, ...] = (
    "run.started", "log", "round.started", "candidate.added", "candidate.updated",
    "candidate.eliminated", "round.finished", "sensitive.filtered", "vetting.progress",
    "report.ready", "diff", "run.finished", "error",
)
CHAT_EVENTS: tuple[str, ...] = ("chat.delta", "chat.tool", "criteria.updated", "done")

current_emit: ContextVar[Emit | None] = ContextVar("current_emit", default=None)
# the run's language (brief.lang): an English run gets English log lines (see _log_text)
current_lang: ContextVar[str | None] = ContextVar("current_lang", default=None)


async def noop_emit(event: str, data: dict) -> None:
    """Emit that drops everything (tests, offline scripts)."""
    return None


@contextlib.contextmanager
def bind_emit(emit: Emit, lang: str | None = None) -> Iterator[None]:
    """Bind ``emit`` as the current context's emitter for ``emit_log`` (and the run's language)."""
    token = current_emit.set(emit)
    ltoken = current_lang.set(lang) if lang is not None else None
    try:
        yield
    finally:
        if ltoken is not None:
            current_lang.reset(ltoken)
        current_emit.reset(token)


# Provider / LLM-client log lines are written in Czech (one string per call site, many in the Apify
# provider). For an English run they go through this phrase table, longest phrases first, so the live
# log the jury reads is English. Unknown words stay as they are (handles, numbers, actor ids).
_EN_PHRASES: list[tuple[str, str]] = [
    (r"\(jen text, bez jmen komentujících\)", "(text only, no commenter names)"),
    (r"dotaz v MOCK datech nic nenašel, vracím celý MOCK seznam", "the MOCK query found nothing, returning the whole MOCK list"),
    (r"mladší 18 let vynecháno", "under 18 left out"),
    (r"\(nic se neukládá\)", "(nothing is stored)"),
    (r"nic se neukládá", "nothing is stored"),
    (r"účet mladší 18 let", "account under 18"),
    (r"účet v MOCK datech není", "account not in the MOCK data"),
    (r"soukromý účet, posty nejsou vidět", "private account, posts not visible"),
    (r"Meta Branded Content jen pro Instagram/Facebook", "Meta Branded Content covers Instagram/Facebook only"),
    (r"v Meta Branded Content", "in Meta Branded Content"),
    (r"stejného tvůrce", "of the same creator"),
    (r"v bio ani odkazech není jiný profil", "no other profile in the bio or links"),
    (r"offline režim nic nestahuje", "offline mode fetches nothing"),
    (r"není v cache", "not in cache"),
    (r"z cache", "from cache"),
    (r"deterministická záloha", "deterministic fallback"),
    (r"odpověděl model", "answered by model"),
    (r"fronta přes limit (\d+) dotazů/min", r"queue over the limit of \1 requests/min"),
    (r"denní limit free modelů", "daily free-model limit"),
    (r"limit free modelů za minutu", "free-model per-minute limit"),
    (r"provider free modelu je přetížený", "the free model's provider is overloaded"),
    (r"neplatný API klíč", "invalid API key"),
    (r"nedostatek kreditu", "not enough credit"),
    (r"požadavek zablokovala moderace", "request blocked by moderation"),
    (r"žádný provider nesplňuje data policy", "no provider meets the data policy"),
    (r"žádný provider pro model a parametry", "no provider for the model and parameters"),
    (r"chybný požadavek", "bad request"),
    (r"chyba serveru", "server error"),
    (r"chyba spojení", "connection error"),
    (r"odpověď není JSON", "the reply is not JSON"),
    (r"neočekávaná odpověď", "unexpected reply"),
    (r"chyba providera během streamu", "provider error during the stream"),
    (r"chyba providera", "provider error"),
    (r"prázdná odpověď", "empty reply"),
    (r"chybí OPENROUTER_API_KEY", "OPENROUTER_API_KEY missing"),
    (r"chyba v MOCK datech", "error in the MOCK data"),
    (r"APIFY_TOKEN není nastavený \(APIFY_TOKEN not set\), živá data nejsou", "APIFY_TOKEN not set, no live data"),
    (r"strop MAX_USD_PER_RUN", "cap MAX_USD_PER_RUN"),
    (r"běh přeskočen", "run skipped"),
    (r"strop běhu", "run cap"),
    (r"běh selhal", "run failed"),
    (r"běh FAILED bez dat; zkouším znovu", "run FAILED without data; retrying"),
    (r"dílčí běh selhal", "partial run failed"),
    (r"VÝSLEDEK NEÚPLNÝ, dílčí běhy selhané, přeskočené nebo předčasně ukončené", "RESULT INCOMPLETE, partial runs failed, skipped or ended early"),
    (r"platforma (\w+) není podporovaná", r"platform \1 is not supported"),
    (r"bez pole username, handle vzat z", "without a username field, handle taken from"),
    (r"nevyřazujeme", "not eliminated"),
    (r"bez locationId nešlo přiřadit k místu, vynecháno", "without locationId could not be matched to a place, left out"),
    (r"\bspouštím\b", "starting"),
    (r"\bodhad\b", "estimate"),
    (r"\bživě\b", "live"),
    (r"\bvracím\b", "returning"),
    (r"\bnenalezeno\b", "not found"),
    (r"\bnalezeno\b", "found"),
    (r"\bstaženo\b", "fetched"),
    (r"\bhledání\b", "search"),
    (r"\bhashtagy\b", "hashtags"),
    (r"\bmísta\b", "places"),
    (r"\bs místem\b", "with a place"),
    (r"\bposty z míst\b", "posts from places"),
    (r"\bprofily\b", "profiles"),
    (r"\bposty\b", "posts"),
    (r"\bmožných profilů\b|\bmožné profily\b|\bmožný profil\b", "possible profile(s)"),
    (r"\bkomentářů\b|\bkomentáře\b|\bkomentář\b", "comments"),
    (r"\bpostů\b|\bpost\b", "posts"),
    (r"\bčlánků\b|\bčlánky\b|\bčlánek\b", "articles"),
    (r"\bzáznamů\b|\bzáznamy\b|\bzáznam\b", "records"),
    (r"\bnálezů\b|\bnálezy\b|\bnález\b", "hits"),
    (r"\búčtů\b|\búčty\b|\búčet\b", "accounts"),
    (r"\bkandidátů\b|\bkandidáti\b|\bkandidát\b", "candidates"),
    (r"\bodkazů\b", "links"),
    (r"\bchyba\b", "error"),
    (r"\bod\b", "since"),
    (r"(?<=\d) z (?=\d)", " of "),
    (r"\bz\b", "from"),
    (r"\bv\b", "in"),
    (r"\bbez\b", "without"),
    (r"\bjen\b", "only"),
    (r"\ba\b", "and"),
]
_EN_RX = [(re.compile(a), b) for a, b in _EN_PHRASES]
_CS_CHARS = re.compile(r"[ěščřžýáíéůúťďňĚŠČŘŽÝÁÍÉŮÚŤĎŇ]")


# Data inside a log line (a quoted news query, a handle, a hashtag, a URL) is never translated.
_QUOTED = re.compile(r"„[^“”\n]*[“”]|“[^”\n]*”|\"[^\"\n]*\"|[@#][\w.]+|https?://\S+")


class _Localized(str):
    """A log line already in the run's language (built by ``tr``): ``emit_log`` passes it through as it is."""
    __slots__ = ()


def tr(cs: str, en: str) -> str:
    """Pick the log text at the source by the run's language (``current_lang``): ``en`` for an English run,
    ``cs`` otherwise. Bilingual call sites use this instead of the phrase table below, so an English run
    reads whole English sentences and quoted data (a news query like „Kam v Brně“) stays untouched."""
    return _Localized(en) if current_lang.get() == "en" else cs


def _en_words(seg: str) -> str:
    if not _CS_CHARS.search(seg) and not re.search(r"\b(od|z|v|bez|jen|posty)\b", seg):
        return seg
    for rx, repl in _EN_RX:
        seg = rx.sub(repl, seg)
    return seg


def to_en(text: str) -> str:
    """The phrase table applied to ``text`` (whatever the run's language), with quoted data, handles and URLs
    left as they are. For a Czech fragment inside an English ``tr`` line (e.g. an OpenRouter error reason)."""
    out: list[str] = []
    last = 0
    for m in _QUOTED.finditer(text):
        out.append(_en_words(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_en_words(text[last:]))
    return "".join(out)


def _log_text(text: str) -> str:
    """The log line in the run's language: a ``tr`` line is already right; other Czech lines get the phrase
    table for an English run (fallback)."""
    if isinstance(text, _Localized):
        return str(text)
    if current_lang.get() != "en" or not text:
        return text
    return to_en(text)


async def emit_log(text: str, *, actor: str | None = None, mode: Mode | None = None) -> None:
    """Emit a ``log`` event via the bound emitter; no-op when none is bound. Never raises."""
    emit = current_emit.get()
    if emit is None:
        return
    try:
        await emit("log", {"text": _log_text(text), "actor": actor, "mode": mode, "ts": utcnow().isoformat()})
    except Exception:  # logging must never break the funnel
        pass


# --------------------------------------------------------------------------------------------
# Event bus + SSE formatting
# --------------------------------------------------------------------------------------------

HEARTBEAT_S = 15.0          # SSE comment line every 15 s keeps proxies / browsers from timing out
SSE_RETRY_MS = 3000         # EventSource reconnect delay sent once at the start of every stream

_IDLE = object()            # queue marker: the run's stream went idle (closed)
_GONE = object()            # queue marker: history cleared (purge); every subscriber ends


_PRIVATE_CANDIDATE_KEYS = ("vetting_data",)


def _strip_private(payload: dict) -> None:
    """Candidates' raw round-4 inputs (``vetting_data``) stay server-side: drop them from event payloads
    (``candidate.*`` events carry {"candidate": Candidate}; snapshots may carry {"candidates": {...}})."""
    cand = payload.get("candidate")
    if isinstance(cand, dict):
        for k in _PRIVATE_CANDIDATE_KEYS:
            cand.pop(k, None)
    cands = payload.get("candidates")
    if isinstance(cands, dict):
        for c in cands.values():
            if isinstance(c, dict):
                for k in _PRIVATE_CANDIDATE_KEYS:
                    c.pop(k, None)


class EventBus:
    """In-process pub/sub keyed by run_id, with full per-run history for replay.

    - ``publish`` appends (event, jsonable data) to the run's history and fans out to live
      subscribers (one asyncio.Queue per subscriber). Event ids are 1-based positions in the
      history, sent as the SSE ``id:`` so a reconnecting EventSource resumes via Last-Event-ID.
    - A run's stream is *open* while a background task works on it (``open`` / ``close``, called
      by the API layer around run_funnel / run_vetting / fill_missing). Unknown runs are closed.
    - ``subscribe`` yields the history first (when ``replay``), then live events. With the default
      ``follow=False`` it ends once the run is closed and drained (after ``run.finished`` /
      ``error``); with ``follow=True`` it keeps streaming across phases (vetting, diffs) until the
      consumer stops or the history is cleared.
    """

    def __init__(self) -> None:
        self._history: dict[str, list[tuple[str, dict]]] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._open: set[str] = set()

    # -- publishing ---------------------------------------------------------------------------

    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        """Convert data with to_jsonable_python, append to history, push to subscribers."""
        self.publish_nowait(run_id, event, data)

    def publish_nowait(self, run_id: str, event: str, data: dict[str, Any]) -> int:
        """Synchronous publish (same semantics); returns the event id."""
        payload = to_jsonable_python(data if data is not None else {})
        if not isinstance(payload, dict):
            payload = {"value": payload}
        _strip_private(payload)
        hist = self._history.setdefault(run_id, [])
        hist.append((event, payload))
        idx = len(hist)
        for q in list(self._subs.get(run_id, ())):
            q.put_nowait((idx, event, payload))
        return idx

    def emitter(self, run_id: str) -> Emit:
        """Return ``emit(event, data)`` bound to run_id (what the API passes to the engine)."""

        async def emit(event: str, data: dict) -> None:
            await self.publish(run_id, event, data)

        return emit

    # -- lifecycle ----------------------------------------------------------------------------

    def open(self, run_id: str) -> None:
        """Mark a phase as running: non-following subscribers wait for ``close``."""
        self._open.add(run_id)

    def is_open(self, run_id: str) -> bool:
        return run_id in self._open

    def close(self, run_id: str) -> None:
        """Mark the run's stream finished; live (non-following) subscribers end after draining."""
        self._open.discard(run_id)
        for q in list(self._subs.get(run_id, ())):
            q.put_nowait(_IDLE)

    def history(self, run_id: str) -> list[tuple[str, dict]]:
        return list(self._history.get(run_id, ()))

    def has_history(self, run_id: str) -> bool:
        return bool(self._history.get(run_id))

    def end_streams(self) -> None:
        """Server shutdown: end every subscriber (following SSE streams included); history stays."""
        for subs in list(self._subs.values()):
            for q in list(subs):
                q.put_nowait(_GONE)

    def clear(self, run_id: str | None = None) -> None:
        """Drop history for one run or all runs (used by purge). Every affected subscriber ends."""
        ids = [run_id] if run_id is not None else list(set(self._history) | set(self._subs))
        for rid in ids:
            self._history.pop(rid, None)
            self._open.discard(rid)
            for q in list(self._subs.get(rid, ())):
                q.put_nowait(_GONE)

    # -- consuming ----------------------------------------------------------------------------

    def subscribe(
        self, run_id: str, replay: bool = True, *, after: int = 0, follow: bool = False,
    ) -> AsyncIterator[tuple[str, dict]]:
        """Async iterator of (event, data): history first if replay, then live events.
        ``after`` skips the first N history entries (Last-Event-ID resume)."""

        async def gen() -> AsyncIterator[tuple[str, dict]]:
            async for item in self.stream(run_id, replay=replay, after=after, follow=follow):
                if item is not None:
                    yield item[1], item[2]

        return gen()

    async def stream(
        self,
        run_id: str,
        *,
        replay: bool = True,
        after: int = 0,
        follow: bool = False,
        heartbeat: float | None = None,
    ) -> AsyncIterator[tuple[int, str, dict] | None]:
        """Core iterator: yields (event_id, event, data); yields None every ``heartbeat`` seconds
        of silence (when set). Snapshot + registration happen without an await in between, so no
        event is lost or duplicated between replay and live streaming."""
        hist = self._history.get(run_id, [])
        start = max(0, int(after)) if replay else len(hist)
        backlog = [(i + 1, ev, data) for i, (ev, data) in enumerate(hist) if i >= start]
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(run_id, set()).add(q)
        if run_id not in self._open:
            q.put_nowait(_IDLE)
        try:
            for item in backlog:
                yield item
            while True:
                if heartbeat:
                    try:
                        item = await asyncio.wait_for(q.get(), heartbeat)
                    except TimeoutError:
                        yield None
                        continue
                else:
                    item = await q.get()
                if item is _GONE:
                    return
                if item is _IDLE:
                    if follow:
                        continue
                    return
                yield item
        finally:
            subs = self._subs.get(run_id)
            if subs is not None:
                subs.discard(q)
                if not subs:
                    self._subs.pop(run_id, None)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subs.get(run_id, ()))


def format_sse(event: str, data: Any, *, id: int | str | None = None) -> str:
    """One SSE message: optional ``id:``, ``event: <name>``, ``data: <json on one line>``."""
    payload = json.dumps(to_jsonable_python(data), ensure_ascii=False, separators=(",", ":"))
    lines = []
    if id is not None:
        lines.append(f"id: {id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def format_heartbeat() -> str:
    """SSE comment line (ignored by EventSource, keeps the connection alive)."""
    return ": keepalive\n\n"


async def sse_run_stream(
    bus: EventBus,
    run_id: str,
    *,
    after: int = 0,
    follow: bool = True,
    heartbeat: float = HEARTBEAT_S,
) -> AsyncIterator[str]:
    """SSE text stream of a run: retry hint, replayed history, then live events + heartbeats."""
    yield f"retry: {SSE_RETRY_MS}\n\n"
    async for item in bus.stream(run_id, after=after, follow=follow, heartbeat=heartbeat):
        if item is None:
            yield format_heartbeat()
        else:
            idx, event, data = item
            yield format_sse(event, data, id=idx)


_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Process-wide singleton EventBus."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
