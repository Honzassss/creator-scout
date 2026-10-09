"""FastAPI app: routes (architecture.md section 7), background run tasks, SSE, chat context.

Routes
  GET  /api/health                  {source_mode, llm_mode, llm_provider, llm_model, llm_models_used,
                                    apify_configured, apify_provider_implemented}
  GET  /api/presets                 {"bakery": CriteriaSet, "fitness": CriteriaSet} (demo briefs)
  POST /api/chat                    {message, lang, run_id?, chat_id?, reset?} -> SSE chat events
  GET  /api/runs                    [{run_id, busy, business_type, candidates, rounds}]
  POST /api/runs                    {criteria} | {preset} (+ up_to<=3) -> {run_id}; rounds 0..3 start
  GET  /api/runs/{id}               Run snapshot (JSON)
  GET  /api/runs/{id}/status        {run_id, busy, error, rounds, mode_summary, llm_modes, counts}
  GET  /api/runs/{id}/events        SSE run events; replays history on connect. ?follow=true
                                    (default) keeps streaming across phases; ?follow=false ends when
                                    the run is idle. ?after=N or Last-Event-ID resumes.
  POST /api/runs/{id}/vet           {candidate_ids} -> round 4 starts (finalists only, max 5)
  POST /api/runs/{id}/criteria      {criteria} -> recompute rounds 1..3 -> {dropped, returned, ...}
  POST /api/runs/{id}/restore       {candidate_id, criterion_id} -> {dropped, returned, ...}
  POST /api/runs/{id}/goal          {brief} | {preset} | {criteria} -> new criteria, recompute, diff
                                    (+ report_diffs: vetted reports re-rendered for the goal, no fetch / LLM)
  POST /api/subject                 {subject, platform?, anchor?, brief|preset|criteria, lang} -> one named
                                    creator checked against the goal (subject mode, nothing eliminated)
  GET  /api/runs/{id}/compare       ?sort=<criterion_id>; no default ranking
  POST /api/purge                   deletes data/cache, data/runs, data/llm, in-memory runs/events/chats

There is deliberately NO endpoint that sends outreach: drafts are copy-only (hard line).

Background work (funnel, vetting, fill_missing) runs in one asyncio task per run at a time; another
mutating request on a busy run gets 409. Any exception in a task becomes an ``error`` event and the
partial run is saved. Every recompute / restore / fill publishes ``candidate.updated`` for changed
candidates, ``round.finished`` with the new counts and one ``diff`` event on the run stream.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
import itertools
import logging
import re
import secrets
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from app.config import get_settings
from app.events import Emit, format_heartbeat, format_sse, get_bus, sse_run_stream, HEARTBEAT_S
from app.llm.text import business_en
from typing import Literal

from app.models import (
    CRITERION_DEFAULT_PARAMS,
    Anchor,
    Brief,
    Candidate,
    CriteriaSet,
    DiscoveryQuery,
    Lang,
    Run,
    SubjectSpec,
    i18n,
    norm_handle,
    utcnow,
)
from app.presets import PresetName, get_preset
from app.store import get_store, purge_all, valid_run_id

log = logging.getLogger("creator_scout.api")

CHAT_TOOL_WAIT = 90.0      # seconds a chat tool waits for a background task before answering "running"
GOAL_AGENT_TIMEOUT = 120.0  # seconds the chat agent may take to propose criteria for a new goal
RUN_LOG_MAX = 5000          # run.log entries kept (oldest dropped)
DEFAULT_MAX_FINALISTS = 5

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


# =============================================================================================
# Lazy access to modules implemented in parallel (keeps /api/health alive if one is broken)
# =============================================================================================


def _engine():
    from app.rounds import engine

    return engine


def _provider():
    from app.sources.factory import get_provider

    return get_provider()


def _llm_available() -> bool:
    try:
        from app.llm.client import llm_available

        return llm_available()
    except Exception:
        return get_settings().llm_mode == "llm"


def _max_finalists() -> int:
    try:
        from app.rounds.r4_vetting import MAX_FINALISTS

        return int(MAX_FINALISTS)
    except Exception:
        return DEFAULT_MAX_FINALISTS


# =============================================================================================
# Errors
# =============================================================================================


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _where(exc: BaseException) -> str:
    """'app/rounds/engine.py:run_funnel' for the innermost frame (helps the integrator)."""
    tb = traceback.extract_tb(exc.__traceback__)
    if not tb:
        return type(exc).__name__
    fr = tb[-1]
    path = fr.filename.split("/backend/")[-1]
    return f"{path}:{fr.name}"


def _secret_safe(text: str) -> str:
    s = get_settings()
    for secret in (s.apify_token, s.anthropic_api_key, s.openrouter_api_key):
        if secret:
            text = text.replace(secret, "***")
    return text


def _get_run(run_id: str) -> Run:
    run = get_store().get(run_id) if valid_run_id(run_id) else None
    if run is None:
        raise ApiError(404, f"run {run_id!r} not found")
    return run


def _check_criteria(cs: CriteriaSet) -> CriteriaSet:
    """Validate + normalize a CriteriaSet from any writer (REST body, chat tool, goal change): unique
    ids, then chat.normalize_criteria_set (brief / label / why / city guard -> refused, params coerced
    per kind, unknown keys stripped). Returns the normalized set; 422 on uncoercible params."""
    from app.llm import chat

    ids = [c.id for c in cs.criteria]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ApiError(422, f"duplicate criterion ids: {', '.join(dupes)}")
    try:
        return chat.normalize_criteria_set(cs)
    except chat.CriteriaRejected as e:
        raise ApiError(422, str(e)) from e


# =============================================================================================
# Background tasks
# =============================================================================================

_tasks: dict[str, asyncio.Task] = {}
_task_errors: dict[str, str] = {}

Job = Callable[[Run, Any, Emit], Awaitable[Any]]


def is_busy(run_id: str) -> bool:
    t = _tasks.get(run_id)
    return t is not None and not t.done()


def _append_log(run_id: str, data: dict) -> None:
    run = get_store().get(run_id)
    if run is None or not isinstance(data, dict):
        return
    entry = {k: data[k] for k in ("ts", "text", "actor", "mode") if data.get(k) is not None}
    entry.setdefault("ts", utcnow().isoformat())
    if not (run.log and run.log[-1] == entry):  # the engine may append the same line itself
        run.log.append(entry)
    if len(run.log) > RUN_LOG_MAX:  # trim in both cases (the engine's own appends never trim)
        del run.log[: len(run.log) - RUN_LOG_MAX]


def run_emitter(run_id: str) -> Emit:
    """Emit passed to the engine: publishes on the run's bus and mirrors ``log`` into run.log."""
    bus = get_bus()

    async def emit(event: str, data: dict) -> None:
        if event == "log":
            _append_log(run_id, data)
        elif event == "error" and isinstance(data, dict):
            # The engine catches a failing round itself and only emits ``error``; record it so
            # /status and the chat tools report the failure (first error of the task wins).
            _task_errors.setdefault(run_id, _secret_safe(str(data.get("message") or "error")))
        await bus.publish(run_id, event, data)

    return emit


async def _safe_emit(emit: Emit, event: str, data: dict) -> None:
    try:
        await emit(event, data)
    except Exception:
        log.exception("emit %s failed", event)


# A run that is working has a marker file next to its snapshot. If the process dies (kill -9, a
# crash, a restart during the shutdown), the marker survives: the next process reports that run as
# interrupted instead of showing "running" forever.
_shutting_down = False


def _busy_marker(run_id: str) -> Path:
    return get_store().runs_dir / ".busy" / run_id


def _mark_busy(run_id: str, label: str) -> None:
    with contextlib.suppress(Exception):
        p = _busy_marker(run_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(label, encoding="utf-8")


def _clear_busy(run_id: str) -> None:
    with contextlib.suppress(Exception):
        _busy_marker(run_id).unlink(missing_ok=True)


_STEP_NAMES = {"funnel": ("hledání a kola 1–3", "search and rounds 1–3"), "vetting": ("hloubková prověrka", "deep vetting"),
               "subject": ("prověrka tvůrce", "the creator check"), "fill_missing": ("doplnění dat", "the data fill")}


def interrupted_step(run: Run) -> str | None:
    """The step label of a run whose work stopped with the process (marker left, no task now)."""
    if is_busy(run.id):
        return None
    try:
        p = _busy_marker(run.id)
        return (p.read_text(encoding="utf-8").strip() or "work") if p.exists() else None
    except Exception:
        return None


def _resolve_interrupted(run: Run) -> str | None:
    """Once per interrupted run: log it, keep the error for /status and the chat tools, drop the marker.
    Returns the error text (also for later calls, from _task_errors)."""
    step = interrupted_step(run)
    if step is None:
        msg = _task_errors.get(run.id)
        return msg if msg and msg.startswith("interrupted") else None
    cs_step, en_step = _STEP_NAMES.get(step.split(":")[0], (step, step))
    lang = run.criteria.brief.lang if run.criteria and run.criteria.brief else "cs"
    text = (f"Přerušeno: server se zastavil během kroku {cs_step}. Výsledek není úplný; spusťte to prosím znovu."
            if lang != "en" else
            f"Interrupted: the server stopped during {en_step}. The result is incomplete; please start it again.")
    run.log.append({"ts": utcnow().isoformat(), "text": text, "actor": "server"})
    get_store().save(run)
    _task_errors[run.id] = f"interrupted: {en_step}"
    _clear_busy(run.id)
    return _task_errors[run.id]


def _start_task(run_id: str, label: str, job: Job) -> asyncio.Task:
    if is_busy(run_id):
        raise ApiError(409, "run is busy (another step is still running); try again when it finishes")
    _task_errors.pop(run_id, None)
    _clear_busy(run_id)
    get_bus().open(run_id)
    task = asyncio.create_task(_run_job(run_id, label, job), name=f"{label}:{run_id}")
    _tasks[run_id] = task
    _mark_busy(run_id, label)
    return task


async def _run_job(run_id: str, label: str, job: Job) -> None:
    emit = run_emitter(run_id)
    store = get_store()
    cancelled = False
    try:
        run = store.get(run_id)
        if run is None:
            raise RuntimeError(f"run {run_id} not found")
        result = await job(run, _provider(), emit)
        if isinstance(result, Run) and result is not run:
            store.save(result)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except NotImplementedError as exc:
        msg = f"{label}: not implemented yet ({_where(exc)})"
        log.warning(msg)
        _task_errors[run_id] = msg
        await _safe_emit(emit, "error", {"message": msg})
    except Exception as exc:  # never crash silently: error event + partial run saved
        log.exception("%s failed for run %s", label, run_id)
        msg = _secret_safe(f"{label} failed: {type(exc).__name__}: {exc}")
        _task_errors[run_id] = msg
        await _safe_emit(emit, "error", {"message": msg})
    finally:
        if not cancelled:
            with contextlib.suppress(Exception):
                run = store.get(run_id)
                if run is not None:
                    store.save(run)
        if not (cancelled and _shutting_down):
            # a shutdown that cancels the job leaves the marker: the next process reports it interrupted
            _clear_busy(run_id)
        get_bus().close(run_id)
        if _tasks.get(run_id) is asyncio.current_task():
            _tasks.pop(run_id, None)


async def wait_idle(run_id: str | None = None, timeout: float = 60.0) -> None:
    """Wait for background work on one run (or all runs). Used by tests and the chat tools."""
    tasks = [t for rid, t in list(_tasks.items()) if (run_id is None or rid == run_id) and not t.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)


async def _cancel_all_tasks(timeout: float = 5.0) -> None:
    tasks = [t for t in _tasks.values() if not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
    _tasks.clear()


async def _wait_task(run_id: str, task: asyncio.Task | None, timeout: float) -> str:
    if task is not None and not task.done():
        await asyncio.wait({task}, timeout=timeout)
    if task is not None and not task.done():
        return "running"
    if task is not None and task.cancelled():
        return "cancelled"
    return "error" if run_id in _task_errors else "finished"


def _funnel_job(up_to: int) -> Job:
    async def job(run: Run, provider: Any, emit: Emit) -> Any:
        return await _engine().run_funnel(run, provider, emit, up_to=up_to)

    return job


def _vet_job(candidate_ids: list[str]) -> Job:
    async def job(run: Run, provider: Any, emit: Emit) -> Any:
        return await _engine().run_vetting(run, candidate_ids, provider, emit)

    return job


def _subject_job() -> Job:
    async def job(run: Run, provider: Any, emit: Emit) -> Any:
        return await _engine().run_subject(run, provider, emit)

    return job


def _revet_job() -> Job:
    async def job(run: Run, provider: Any, emit: Emit) -> Any:
        return await _engine().revet_subject(run, provider, emit)

    return job


def _is_subject(run: Run | None) -> bool:
    return run is not None and getattr(run, "mode", "discovery") == "subject"


def _fill_job(baseline: dict | None = None, carry: dict | None = None) -> Job:
    """fill_missing after a recompute / restore / goal change. With ``baseline`` (candidate states
    from before that mutation) the published diff is the COMBINED one (mutation + fill), flagged
    ``final`` + ``replaces_pending`` so the UI swaps it for the provisional diff it already shows."""

    async def job(run: Run, provider: Any, emit: Emit) -> Any:
        before = _fingerprints(run)
        diff = await _engine().fill_missing(run, provider, emit)
        diff_since = getattr(_engine(), "diff_since", None)
        if baseline is not None and diff_since is not None:
            d = _diff_json(diff_since(run, baseline))
            d.update(pending_fetch=False, final=True, replaces_pending=True)
            d.update(carry or {})  # e.g. waivers_dropped of the mutation this fill completes
        else:
            d = _diff_json(diff)
        await _publish_changes(run, d, emit, before)
        return run

    return job


# =============================================================================================
# Shared operations (REST + chat tools)
# =============================================================================================


def _fingerprints(run: Run) -> dict[str, int]:
    return {cid: hash(c.model_dump_json(exclude={"ref"})) for cid, c in run.candidates.items()}


async def _publish_changes(run: Run, diff: Any, emit: Emit, before: dict[str, int]) -> None:
    """After recompute / restore / fill: changed candidates, new round counts, one diff event."""
    after = _fingerprints(run)
    for cid, cand in run.candidates.items():
        if before.get(cid) != after.get(cid):
            await emit("candidate.updated", {"candidate": cand})
    for r in run.rounds:
        if isinstance(r, dict) and r.get("round") in (1, 2, 3, 4):
            await emit("round.finished", r)
    d = _diff_json(diff)
    await emit("diff", d)
    for rd in d.get("report_diffs") or []:   # re-rendered reports (goal / criteria change)
        cid = rd.get("candidate_id") if isinstance(rd, dict) else None
        if cid:
            await emit("report.diff", {"candidate_id": cid, "diff": rd})
            await emit("report.ready", {"candidate_id": cid})


def _baseline(run: Run) -> dict | None:
    snap = getattr(_engine(), "snapshot_states", None)
    return snap(run) if snap is not None else None


_DIFF_FLAGS = ("pending_fetch", "final", "replaces_pending")


def _diff_json(diff: Any) -> dict:
    """{dropped, returned} plus the optional flags: pending_fetch (a fill_missing follows and will
    publish the final diff), final + replaces_pending (that final, combined diff)."""
    d = to_jsonable_python(diff) if diff is not None else {}
    if not isinstance(d, dict):
        d = {}
    out = {"dropped": list(d.get("dropped") or []), "returned": list(d.get("returned") or [])}
    for k in _DIFF_FLAGS:
        if k in d:
            out[k] = bool(d[k])
    if d.get("waivers_dropped"):
        out["waivers_dropped"] = list(d["waivers_dropped"])
    if d.get("report_diffs"):
        out["report_diffs"] = list(d["report_diffs"])
    return out


def _needs_fetch(diff: dict) -> bool:
    return any(e.get("needs_fetch") for e in diff["dropped"] + diff["returned"] if isinstance(e, dict))


def _create_run(criteria: CriteriaSet, up_to: int = 3) -> Run:
    criteria = _check_criteria(criteria)
    run = get_store().create(criteria)
    _start_task(run.id, "funnel", _funnel_job(max(0, min(3, int(up_to)))))
    return run


def _sync_engine_call(run: Run, label: str, fn: Callable[[], Any], *, mutates: bool = True) -> Any:
    """Run a synchronous engine call; if it fails, restore the run as it was and raise ApiError."""
    backup = run.model_copy(deep=True) if mutates else None
    try:
        return fn()
    except ApiError:
        raise
    except Exception as exc:
        if backup is not None:
            for name in type(run).model_fields:
                setattr(run, name, getattr(backup, name))
        if isinstance(exc, NotImplementedError):
            raise ApiError(501, f"{label}: not implemented yet ({_where(exc)})") from exc
        if isinstance(exc, (KeyError, ValueError)):
            raise ApiError(400, f"{label}: {exc}") from exc
        log.exception("%s failed for run %s", label, run.id)
        raise ApiError(500, _secret_safe(f"{label} failed: {type(exc).__name__}: {exc}")) from exc


def _rd_goal_changed(rd: dict) -> bool:
    fg = rd.get("from_goal") if isinstance(rd.get("from_goal"), dict) else {}
    tg = rd.get("to_goal") if isinstance(rd.get("to_goal"), dict) else {}
    return fg.get("brief_key") != tg.get("brief_key")


_RD_CHANGE_KEYS = ("added", "removed", "moved_up", "moved_down", "collapsed", "claims_changed", "checks_changed",
                   "questions_added", "questions_removed", "left_key", "skeptic_added", "skeptic_removed", "text_changed")


def _rd_empty(rd: dict) -> bool:
    return not rd.get("outreach_changed") and not any(rd.get(k) for k in _RD_CHANGE_KEYS)


def _rerender_log_text(run: Run, rd: dict) -> str:
    """Run-log line for a re-rendered report, so the owner sees the change fetched nothing."""
    cand = run.candidates.get(str(rd.get("candidate_id") or ""))
    who = f"@{cand.ref.handle}" if cand is not None else str(rd.get("candidate_id") or "?")
    summary = rd.get("summary") if isinstance(rd.get("summary"), dict) else {}
    goal = _rd_goal_changed(rd)
    if run.criteria.brief.lang == "en":
        why = "for the new goal" if goal else "after the criteria change"
        return f"Report for {who} re-rendered {why} from the data already fetched (no new fetch). {summary.get('en') or ''}".strip()
    why = "pro nový cíl" if goal else "po změně kritérií"
    return f"Report pro {who} přepočítán {why} z už stažených dat (nic nového se nestahovalo). {summary.get('cs') or ''}".strip()


async def _after_mutation(run: Run, diff: Any, before: dict[str, int], baseline: dict | None = None) -> tuple[dict, bool]:
    d = _diff_json(diff)
    if d.get("report_diffs") and not _is_subject(run):
        # Discovery: a criteria edit that leaves a vetted report as it was is not news (no notice,
        # no "the report is the same" panel per finalist); a goal change still reports every one.
        kept = [rd for rd in d["report_diffs"] if isinstance(rd, dict) and (_rd_goal_changed(rd) or not _rd_empty(rd))]
        if kept:
            d["report_diffs"] = kept
        else:
            d.pop("report_diffs", None)
    for rd in d.get("report_diffs") or []:
        if isinstance(rd, dict):
            await _safe_emit(run_emitter(run.id), "log", {"text": _rerender_log_text(run, rd), "actor": "report",
                                                          "ts": utcnow().isoformat()})
    get_store().save(run)
    fill = _needs_fetch(d) and not is_busy(run.id)
    d["pending_fetch"] = fill
    await _publish_changes(run, d, run_emitter(run.id), before)
    if fill:
        carry = {"waivers_dropped": d["waivers_dropped"]} if d.get("waivers_dropped") else None
        _start_task(run.id, "fill_missing", _fill_job(baseline, carry))
    return d, fill


async def _apply_criteria(run: Run, criteria: CriteriaSet) -> tuple[dict, bool]:
    """Recompute rounds 1..3 with new criteria (no fetch, no LLM); publish; maybe fill_missing."""
    if is_busy(run.id):
        raise ApiError(409, "run is busy (another step is still running); try again when it finishes")
    criteria = _check_criteria(criteria)
    before = _fingerprints(run)
    baseline = _baseline(run)
    old_brief = run.criteria.brief.model_copy(deep=True)
    diff = _sync_engine_call(run, "recompute", lambda: _engine().recompute(run, criteria))
    with contextlib.suppress(Exception):
        await _log_recompute(run, old_brief)
    return await _after_mutation(run, diff, before, baseline)


async def _log_recompute(run: Run, old_brief: Brief) -> None:
    """Run log: what the recompute did (goal changed or criteria edited) and the recomputed funnel."""
    new = run.criteria.brief
    en = new.lang == "en"
    goal_changed = (old_brief.business_type, old_brief.city, old_brief.goal) != (new.business_type, new.city, new.goal)
    lines: list[str] = []
    if goal_changed:
        o_bt = business_en(old_brief.business_type) if en else old_brief.business_type
        n_bt = business_en(new.business_type) if en else new.business_type
        where = f" ({new.city})" if new.city else ""
        lines.append(f"Goal changed: {o_bt} → {n_bt}{where}." if en else f"Cíl změněn: {o_bt} → {n_bt}{where}.")
    elif not _is_subject(run):
        lines.append("Criteria changed." if en else "Kritéria změněna.")
    if not _is_subject(run):
        counts = [r for r in run.rounds if isinstance(r, dict) and r.get("round") in (1, 2, 3)]
        if counts:
            rs = "; ".join((f"Round {r['round']}: entered {r.get('entered')} → remaining {r.get('remaining')}" if en
                            else f"Kolo {r['round']}: vstoupilo {r.get('entered')} → zůstalo {r.get('remaining')}")
                           for r in sorted(counts, key=lambda r: r["round"]))
            lines.append(("Rounds 1–3 recomputed from the data already fetched: " if en
                          else "Kola 1–3 přepočítána z už stažených dat: ") + rs + ".")
    if lines:
        await _safe_emit(run_emitter(run.id), "log", {"text": " ".join(lines), "actor": "engine",
                                                      "ts": utcnow().isoformat()})


async def _restore(run: Run, candidate_ref: str, criterion_id: str) -> tuple[dict, bool]:
    if _is_subject(run):
        raise ApiError(400, "subject runs do not eliminate: there is nothing to restore")
    if is_busy(run.id):
        raise ApiError(409, "run is busy (another step is still running); try again when it finishes")
    cid = _resolve_candidate(run, candidate_ref)
    if cid is None:
        raise ApiError(404, f"candidate {candidate_ref!r} not found in run {run.id}")
    if criterion_id not in {c.id for c in run.criteria.criteria}:
        raise ApiError(400, f"unknown criterion {criterion_id!r}")
    before = _fingerprints(run)
    baseline = _baseline(run)
    diff = _sync_engine_call(run, "restore", lambda: _engine().restore(run, cid, criterion_id))
    return await _after_mutation(run, diff, before, baseline)


_PLATFORMS = ("instagram", "tiktok", "youtube", "news", "meta_branded", "web")


def _resolve_candidate(run: Run, ref: str) -> str | None:
    """Accept a candidate id ("instagram:x"), "@x" or "x". An explicit platform prefix must match
    exactly (a "tiktok:x" request never acts on "instagram:x", which may be another person); a bare
    handle resolves only when exactly one candidate has it."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    ref = ref.strip()
    if ref in run.candidates:
        return ref
    if ":" in ref:
        platform, _, handle = ref.partition(":")
        if platform.strip().lower() in _PLATFORMS:
            cid = f"{platform.strip().lower()}:{norm_handle(handle)}"
            return cid if cid in run.candidates else None
    handle = norm_handle(ref.split(":")[-1])
    hits = [cid for cid, c in run.candidates.items() if norm_handle(c.ref.handle) == handle]
    return hits[0] if len(hits) == 1 else None


def _start_vetting(run: Run, candidate_refs: list[str]) -> list[str]:
    if _is_subject(run):   # re-vet the named creator (fetches again)
        if is_busy(run.id):
            raise ApiError(409, "run is busy (the subject check is still running); try again when it finishes")
        ids = [cid for cid, c in run.candidates.items() if c.profile is not None]
        if not ids:
            if run.subject is not None and run.subject.status == "not_found":
                raise ApiError(400, "the subject was not found; start a new subject check")
            raise ApiError(409, "the subject check has no profile yet; try again when it finishes")
        _start_task(run.id, "vetting", _revet_job())
        return ids
    max_n = _max_finalists()
    finalists = [cid for cid, c in run.candidates.items() if c.status == "finalist"]
    if not candidate_refs:
        if not finalists:
            raise ApiError(400, "no finalists to vet yet (run rounds 1-3 first)")
        candidate_refs = finalists[:max_n]
    ids: list[str] = []
    unknown: list[str] = []
    for ref in candidate_refs:
        cid = _resolve_candidate(run, ref)
        if cid is None:
            unknown.append(str(ref))
        elif cid not in ids:
            ids.append(cid)
    if unknown:
        raise ApiError(404, f"unknown candidates: {', '.join(unknown)}")
    not_final = [cid for cid in ids if run.candidates[cid].status != "finalist"]
    if not_final:
        raise ApiError(400, f"only finalists can be vetted (round 4); not finalists: {', '.join(not_final)}")
    if len(ids) > max_n:
        raise ApiError(400, f"at most {max_n} finalists can be vetted at once (got {len(ids)})")
    _start_task(run.id, "vetting", _vet_job(ids))
    return ids


# -- goal change ----------------------------------------------------------------------------------

def _preset_for_brief(brief: Brief) -> PresetName | None:
    """Keyword match on business_type (lists live in rounds/report.py, shared with the report)."""
    from app.rounds.report import preset_for_brief

    return preset_for_brief(brief)  # type: ignore[return-value]


def _set_city(cs: CriteriaSet, city: str | None) -> None:
    if not city:
        return
    for c in cs.criteria:
        if c.kind == "local_signal":
            c.params["city"] = city


_OWNER_COMPETITORS: dict[str, dict[str, list[dict]]] = {}  # run id -> business type -> owner's own list


def _keep_owner_competitors(name: PresetName, brief: Brief | None, run: Run | None, lang: Lang) -> Brief | None:
    """Subject mode: a switch to a preset goal keeps the competitors the owner named for that kind of
    business (the presets carry sample competitors). A different business gets its own list back if the
    owner named one earlier in this run, else the preset's; a bakery's rivals do not compete with a gym.
    Competitors the owner edits in the same request always win."""
    from app.presets import preset_brief

    if not _is_subject(run):
        return brief
    def key(cs: list[dict] | None) -> set[str]:
        return {str(c.get("name") or "").strip().lower() for c in cs or [] if isinstance(c, dict)}
    samples = [key(preset_brief(p, "cs").competitors) for p in ("bakery", "fitness")]  # type: ignore[arg-type]
    own = run.criteria.brief.competitors  # type: ignore[union-attr]
    old_type = (run.criteria.brief.business_type or "").strip().lower()  # type: ignore[union-attr]
    memory = _OWNER_COMPETITORS.setdefault(run.id, {})  # type: ignore[union-attr]
    if key(own) and key(own) not in samples:
        memory[old_type] = [dict(c) for c in own]
    if brief is not None and key(brief.competitors) and key(brief.competitors) not in samples:
        return brief   # the owner's own list in this request
    # no list of the owner's in the request (none, empty or the preset's samples): the list the owner
    # named earlier in this run for this business comes back
    base = brief if brief is not None else preset_brief(name, lang)
    new_type = (base.business_type or "").strip().lower()
    remembered = memory.get(new_type)
    if not remembered:
        return brief
    return base.model_copy(update={"competitors": [dict(c) for c in remembered]})


def _criteria_from_preset(name: PresetName, brief: Brief | None, run: Run | None, lang: Lang | None = None) -> CriteriaSet:
    lang = lang or (brief.lang if brief is not None else None) or (run.criteria.brief.lang if run is not None else "cs")
    brief = _keep_owner_competitors(name, brief, run, lang)
    cs = get_preset(name, lang)
    if brief is not None:
        cs.brief = brief.model_copy(deep=True)
        _set_city(cs, brief.city)
        if not brief.city:  # no city: the local criterion is off (never a silent default city)
            for c in cs.criteria:
                if c.kind == "local_signal":
                    c.enabled = False
                    c.params["city"] = None
                    c.why = i18n("Město jste neuvedli, proto je lokální kritérium vypnuté.",
                                 "No city given, so the local criterion is off.")
        from app.presets import overlay_why

        overlay_why(cs, name, cs.brief)  # no preset business / competitor names in a custom brief's why texts
    if run is not None:  # "Změnit cíl" keeps the candidate list: same discovery
        cs.discovery = run.criteria.discovery.model_copy(deep=True)
    return cs


def _criteria_keep_current(current: CriteriaSet, brief: Brief) -> CriteriaSet:
    cs = current.model_copy(deep=True)
    cs.brief = brief.model_copy(deep=True)
    _set_city(cs, brief.city)
    return cs


class _GoalCaptureContext:
    """ChatContext for asking the chat agent for criteria for a new goal: only propose_criteria works."""

    def __init__(self, base: CriteriaSet, lang: Lang) -> None:
        self.lang = lang
        self.history: list[dict] = []
        self.base = base
        self.captured: CriteriaSet | None = None

    def current_run(self) -> Run | None:
        return None

    def current_criteria(self) -> CriteriaSet | None:
        return self.base

    async def propose_criteria(self, criteria: CriteriaSet) -> dict:
        self.captured = CriteriaSet.model_validate(to_jsonable_python(criteria))
        return {"ok": True}

    async def _unavailable(self, *args: Any, **kwargs: Any) -> dict:
        return {"ok": False, "error": "not available during a goal change; call propose_criteria"}

    update_criterion = run_rounds = explain_elimination = start_deep_vetting = draft_outreach = _unavailable
    research_subject = _unavailable

    async def change_goal(self, brief: Brief) -> dict:
        return {"ok": True, "note": "goal recorded; now call propose_criteria with criteria for it"}


async def _agent_criteria(brief: Brief, base: CriteriaSet) -> CriteriaSet | None:
    try:
        from app.events import noop_emit
        from app.llm import chat

        ctx = _GoalCaptureContext(base.model_copy(update={"brief": brief}), brief.lang)
        msg = {
            "cs": "Cíl se mění. Nové zadání: {b}. Navrhni kritéria pro tento cíl nástrojem propose_criteria.",
            "en": "The goal changes. New brief: {b}. Propose criteria for this goal with propose_criteria.",
        }[brief.lang].format(b=brief.model_dump_json())
        await asyncio.wait_for(chat.chat_turn(msg, ctx, noop_emit), GOAL_AGENT_TIMEOUT)
        return ctx.captured
    except Exception as exc:
        log.warning("chat agent could not propose criteria for the new goal: %s", exc)
        return None


async def _criteria_for_brief(brief: Brief, base: CriteriaSet, run: Run | None, *, use_agent: bool) -> tuple[CriteriaSet, str]:
    """Deterministic first (the two demo presets the fixtures are tuned for), then the chat agent
    (when a key is set), else the current criteria with the new brief."""
    name = _preset_for_brief(brief)
    if name is not None:
        return _criteria_from_preset(name, brief, run), f"preset:{name}"
    if use_agent and _llm_available() and _chat_llm_enabled():
        cs = await _agent_criteria(brief, base)
        if cs is not None:
            cs.brief = brief.model_copy(deep=True)
            if run is not None:
                cs.discovery = run.criteria.discovery.model_copy(deep=True)
            return cs, "chat_agent"
    if _is_subject(run):
        # A subject run has no pool to keep: a new non-preset goal gets its own deterministic criteria.
        from app.llm import chat

        cs = chat.criteria_for_brief(brief)
        cs.brief = brief.model_copy(deep=True)
        cs.discovery = DiscoveryQuery(city=brief.city)
        return cs, "generic"
    return _criteria_keep_current(base, brief), "kept_current"


def _chat_llm_enabled() -> bool:
    """LLM budget gate for the goal-change agent (budget.llm_task_enabled("chat"))."""
    try:
        from app.llm import budget

        return budget.llm_task_enabled("chat")
    except Exception:
        return True


def _usage_snapshot() -> dict:
    try:
        from app.llm import budget

        return budget.usage_snapshot()
    except Exception:
        return {}


# =============================================================================================
# Summaries for chat tool results (compact; no score, no ranking)
# =============================================================================================


def _src(ref: Any) -> dict:
    d = to_jsonable_python(ref)
    return {k: d.get(k) for k in ("id", "url", "mode", "quote") if d.get(k) is not None}


def _label(run: Run, criterion_id: str, lang: Lang) -> str:
    for c in run.criteria.criteria:
        if c.id == criterion_id:
            return c.label.get(lang) or c.label.get("cs") or criterion_id
    return criterion_id


def _diff_summary(diff: dict, lang: Lang, limit: int = 15) -> dict:
    def entry(e: dict) -> dict:
        elim = e.get("elimination") or {}
        reason = elim.get("reason") or {}
        return {
            "candidate_id": e.get("candidate_id"), "handle": e.get("handle"),
            "before": e.get("before"), "after": e.get("after"),
            "criterion_id": elim.get("criterion_id"), "reason": reason.get(lang) or reason.get("cs"),
            "needs_fetch": e.get("needs_fetch", False),
        }

    return {
        "dropped_count": len(diff["dropped"]), "returned_count": len(diff["returned"]),
        "dropped": [entry(e) for e in diff["dropped"][:limit]],
        "returned": [entry(e) for e in diff["returned"][:limit]],
    }


def _criteria_summary(cs: CriteriaSet, lang: Lang) -> dict:
    return {
        "brief": {"business_type": cs.brief.business_type, "city": cs.brief.city, "goal": cs.brief.goal},
        "criteria": [
            {"id": c.id, "kind": c.kind, "round": c.round, "enabled": c.enabled, "params": c.params,
             "label": c.label.get(lang) or c.label.get("cs")}
            for c in cs.criteria
        ],
        "refused": [{"text": r.text, "reason": r.reason.get(lang) or r.reason.get("cs")} for r in cs.refused],
    }


def _run_summary(run: Run, lang: Lang) -> dict:
    eliminated: dict[tuple[int, str], int] = {}
    for c in run.candidates.values():
        if c.status == "eliminated" and c.elimination is not None:
            key = (c.elimination.round, c.elimination.criterion_id)
            eliminated[key] = eliminated.get(key, 0) + 1
    finalists = [c for c in run.candidates.values() if c.status == "finalist"]
    return {
        "run_id": run.id,
        "rounds": run.rounds,
        "candidates": len(run.candidates),
        "active": sum(1 for c in run.candidates.values() if c.status == "active"),
        "finalists": [{"candidate_id": c.id, "handle": c.ref.handle, "platform": c.ref.platform} for c in finalists],
        "eliminated_by": [
            {"round": r, "criterion_id": cid, "label": _label(run, cid, lang), "count": n}
            for (r, cid), n in sorted(eliminated.items())
        ],
        "sensitive_filtered": sum(c.sensitive_filtered for c in run.candidates.values()),
        "mode_summary": run.mode_summary,
        "llm_modes": run.llm_modes,
        "error": _task_errors.get(run.id),
    }


def _report_summary(c: Candidate, lang: Lang, r4_ids: set[str]) -> dict:
    out: dict[str, Any] = {"candidate_id": c.id, "handle": c.ref.handle, "report_ready": c.report is not None}
    r = c.report
    if r is not None:
        kinds: dict[str, int] = {}
        for f in r.findings:
            kinds[f.kind] = kinds.get(f.kind, 0) + 1
        claims: dict[str, int] = {}
        for cl in r.claims:
            claims[cl.status] = claims.get(cl.status, 0) + 1
        news: dict[str, int] = {}
        for n in r.news:
            news[n.label] = news.get(n.label, 0) + 1
        out.update({
            "findings": kinds, "claims": claims, "news": news,
            "collabs": len(r.collab_timeline),
            "competitor_collabs": sum(1 for e in r.collab_timeline if e.is_competitor),
            "undisclosed_collabs": sum(1 for e in r.collab_timeline if e.disclosed is False),
            "questions": [q.get(lang) or q.get("cs") for q in r.questions][:5],
            "sensitive_filtered": r.sensitive_filtered,
        })
    out["round4_results"] = [
        {"criterion_id": res.criterion_id, "status": res.status, "value": res.value, "waived": res.waived}
        for res in c.results if res.criterion_id in r4_ids
    ]
    return out


def _key_items(rep: Any) -> list[Any]:
    """Key findings, one per aspect (the topic check and the goal-fit fact say the same thing)."""
    out, seen = [], set()
    for f in rep.findings:
        if f.tier != "key":
            continue
        asp = f.aspect or f.id
        if asp in seen:
            continue
        seen.add(asp)
        out.append(f)
    return out


def _key_texts(c: Candidate, lang: Lang, limit: int) -> list[str]:
    r = c.report
    if r is None:
        return []
    return [f.text.get(lang) or f.text.get("cs", "") for f in _key_items(r)[:limit]]


def _report_diffs_summary(run: Run, diffs: list, lang: Lang) -> list[dict]:
    """Compact report diffs for chat tool results (texts in the chat language)."""
    out = []
    for rd in diffs or []:
        d = to_jsonable_python(rd)
        if not isinstance(d, dict):
            continue
        c = run.candidates.get(d.get("candidate_id", ""))
        summary = d.get("summary") or {}
        out.append({
            "candidate_id": d.get("candidate_id"), "handle": c.ref.handle if c else None,
            "summary": summary.get(lang) or summary.get("en") or summary.get("cs"),
            "added": len(d.get("added") or []), "removed": len(d.get("removed") or []),
            "moved_up": len(d.get("moved_up") or []), "moved_down": len(d.get("moved_down") or []),
            "claims_changed": len(d.get("claims_changed") or []), "questions_added": len(d.get("questions_added") or []),
            "outreach_changed": bool(d.get("outreach_changed")),
            "key_findings": _key_texts(c, lang, 3) if c else [],
        })
    return out


_SUBJECT_NOTE = {"cs": "Prověrka jednoho tvůrce: nic se nevyřazuje a není žádné skóre.",
                 "en": "Subject check: nothing is eliminated and there is no score."}


def _subject_summary(run: Run, status: str, criteria_source: str, lang: Lang) -> dict:
    """research_subject result (docs/subject-mode.md 8.1); texts in ``lang``."""
    sub = run.subject
    sub_d = {"raw": sub.raw, "platform": sub.platform, "handle": sub.handle, "candidate_id": sub.candidate_id,
             "status": sub.status} if sub else None
    anchor = sub.anchor.model_dump() if sub else {"city": None, "website": None, "company_id": None}
    out: dict[str, Any] = {"ok": status != "error", "run_id": run.id, "status": status, "subject": sub_d,
                           "anchor": anchor, "criteria_source": criteria_source, "note": _SUBJECT_NOTE[lang]}
    if status == "error":
        out["error"] = _task_errors.get(run.id)
    c = run.candidates.get(sub.candidate_id) if sub and sub.candidate_id else None
    rep = c.report if c is not None else None
    if sub is not None and sub.status == "not_found":
        from app.compute.identity import identity_verdict

        v = identity_verdict(None, None, [], [], [], [], lang=lang, handle=sub.handle,
                             tried=[sub.platform] if sub.platform else ["instagram", "tiktok"])
        text = v.text.get(lang)
        with contextlib.suppress(Exception):
            from app.rounds.engine import not_found_reason

            prov = _provider()
            if getattr(prov, "read_only", False) or str(getattr(prov, "name", "")).startswith("mock"):
                text = not_found_reason(sub.handle, prov).get(lang) or text
        out["identity"] = {"status": "not_found", "text": text}
    elif rep is not None and rep.identity_verdict is not None:
        out["identity"] = {"status": rep.identity_verdict.status, "text": rep.identity_verdict.text.get(lang)}
    else:
        out["identity"] = None
    if c is not None:
        counts = {"pass": 0, "fail": 0, "unknown": 0}
        items = []
        for r in c.results:
            st = "pass" if r.waived else r.status
            counts[st] = counts.get(st, 0) + 1
            items.append({"criterion_id": r.criterion_id, "label": _label(run, r.criterion_id, lang), "status": st,
                          "value": r.value, "threshold": r.threshold})
        order = {"fail": 0, "unknown": 1, "pass": 2}
        items.sort(key=lambda x: order.get(x["status"], 3))
        out["checks"] = {**counts, "items": items[:8]}
    else:
        out["checks"] = {"pass": 0, "fail": 0, "unknown": 0, "items": []}
    if rep is not None:
        out["key_findings"] = [
            {"id": f.id, "kind": f.kind, "text": f.text.get(lang) or f.text.get("cs"), "confidence": f.confidence,
             "why": (f.why_it_matters or {}).get(lang)}
            for f in _key_items(rep)][:5]
        out["less_relevant"] = len(rep.less_relevant)
        out["claims"] = [{"claim": cl.claim, "status": cl.status, "confidence": cl.confidence} for cl in rep.claims[:3]]
        out["questions"] = [q.get(lang) or q.get("cs") for q in rep.questions[:3]]
        out["outreach_draft_ready"] = bool(rep.outreach_draft)
        if rep.summary:
            out["summary"] = rep.summary.get(lang)
    else:
        out.update({"key_findings": [], "less_relevant": 0, "claims": [], "questions": [], "outreach_draft_ready": False})
    return out


def _subject_criteria(brief: Any, preset: str | None, criteria: CriteriaSet | None, lang: Lang | None,
                      session_criteria: CriteriaSet | None = None) -> tuple[CriteriaSet, str]:
    """Criteria for a subject check: explicit criteria > preset (name or a preset-like brief, with the
    brief overlaid) > chat.criteria_for_brief(brief) > the session's criteria. ApiError 422 if none."""
    from app.llm import chat

    if isinstance(brief, str):
        name = brief.strip().lower()
        if name not in ("bakery", "fitness"):
            raise ApiError(422, "brief must be a Brief object or 'bakery' / 'fitness'")
        preset, brief = preset or name, None
    if isinstance(brief, dict):
        try:
            brief = Brief.model_validate(brief)
        except Exception as e:
            raise ApiError(422, f"invalid brief: {e}") from e
    if brief is not None and lang:
        brief = brief.model_copy(update={"lang": lang})
    if criteria is not None:
        cs, source = criteria.model_copy(deep=True), "request"
        if lang:
            cs.brief = cs.brief.model_copy(update={"lang": lang})
    elif preset is not None:
        if preset not in ("bakery", "fitness"):
            raise ApiError(422, "preset must be 'bakery' or 'fitness'")
        cs, source = _criteria_from_preset(preset, brief, None, lang or "en"), f"preset:{preset}"  # type: ignore[arg-type]
    elif brief is not None:
        name = _preset_for_brief(brief)
        if name is not None:
            cs, source = _criteria_from_preset(name, brief, None, brief.lang), f"preset:{name}"
        else:
            cs, source = chat.criteria_for_brief(brief), "generic"
            cs.brief = brief.model_copy(deep=True)
    elif session_criteria is not None:
        cs, source = session_criteria.model_copy(deep=True), "session"
        if lang:
            cs.brief = cs.brief.model_copy(update={"lang": lang})
    else:
        raise ApiError(422, "send criteria, brief or preset (the goal the creator is checked for)")
    # The anchor city is where the CREATOR is; the local criterion stays the business city (brief.city).
    cs.discovery = DiscoveryQuery(city=cs.brief.city)
    return cs, source


def start_subject_run(subject: SubjectSpec, criteria: CriteriaSet) -> Run:
    """Create + save a subject-mode run and start its task (POST /api/subject, chat research_subject)."""
    criteria = _check_criteria(criteria)
    run = get_store().create(criteria)
    run.mode = "subject"
    run.subject = subject
    get_store().save(run)
    _start_task(run.id, "subject", _subject_job())
    return run


def _anchor_or_422(raw: Anchor | str | None) -> Anchor:
    """The owner's anchor, normalized. A plain string is classified (digits = company ID, contains a
    dot = website, else city). A field the owner filled in that does not normalize -> 422 (never a
    silent "no anchor was given")."""
    from app.compute.subject import classify_anchor, normalize_anchor

    if raw is None:
        return Anchor()
    if isinstance(raw, str):
        if not raw.strip():
            return Anchor()
        raw = classify_anchor(raw)
    norm = normalize_anchor(raw) or Anchor()
    if (raw.company_id or "").strip() and not norm.company_id:
        raise ApiError(422, "company ID must be 6-8 digits (Czech IČO)")
    if (raw.website or "").strip() and not norm.website:
        raise ApiError(422, "website must be a domain such as example.cz")
    return norm


def _parse_subject_or_422(text: str, platform: str | None) -> tuple[str | None, str]:
    from app.compute.subject import parse_subject

    raw = (text or "").strip()
    parsed = parse_subject(raw, platform)
    if parsed is None:
        low = raw.lower()
        if ("instagram.com/" in low and any(f"/{x}/" in low for x in ("p", "reel", "reels", "tv", "stories"))) or (
                "tiktok.com/" in low and "/video/" in low and "/@" not in low):
            raise ApiError(422, "this is a post link; send the profile link (instagram.com/<handle> or tiktok.com/@<handle>) or the @handle")
        if re.search(r"\s", raw) and not re.search(r"[@/]", raw):
            raise ApiError(422, "a name alone can match namesakes: send the person's or organization's Instagram / "
                                "TikTok @handle or profile link (the anchor is where they are based, their website or IČO)")
        raise ApiError(422, "subject must be an @handle or an instagram.com / tiktok.com profile link")
    return parsed


# =============================================================================================
# Chat sessions + ChatContext
# =============================================================================================

_counter = itertools.count()


@dataclass
class ChatSession:
    id: str
    history: list[dict] = field(default_factory=list)
    criteria: CriteriaSet | None = None
    run_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: int = 0
    inflight: list[str] = field(default_factory=list)   # messages accepted, turn not finished (double-send guard)
    last_lang: str | None = None       # the language of the guide's last answer (done.lang)
    lang_override: str | None = None   # the owner switched the UI language after that answer


_sessions: dict[str, ChatSession] = {}
_chat_tasks: set[asyncio.Task] = set()


def _resolve_session(chat_id: str | None, run_id: str | None, reset: bool) -> ChatSession:
    """chat_id -> that session; else the session bound to run_id; else (no chat_id and no run_id)
    the most recent session (single-user demo); reset -> always a new one. A known run_id is bound
    to the session. A run_id that no session is bound to (a reload, a second tab, a run created on
    the board, a backend restart) gets a NEW session: it never joins another tab's interview, which
    would answer in that tab's language and later overwrite this run with that tab's brief."""
    s: ChatSession | None = None
    if not reset:
        if chat_id:
            s = _sessions.get(chat_id)
        if s is None and run_id:
            bound = [x for x in _sessions.values() if x.run_id == run_id]
            s = max(bound, key=lambda x: x.touched) if bound else None
        if s is None and not chat_id and not run_id and _sessions:
            s = max(_sessions.values(), key=lambda x: x.touched)
    if s is None:
        sid = chat_id if chat_id and valid_run_id(chat_id) and chat_id not in _sessions else "c_" + secrets.token_hex(5)
        s = ChatSession(id=sid)
        _sessions[sid] = s
    if run_id and get_store().get(run_id) is not None:
        s.run_id = run_id
    elif s.run_id and get_store().get(s.run_id) is None:  # run was purged
        s.run_id = None
    s.touched = next(_counter)
    return s


def _board_criteria_to_session(session: ChatSession, criteria: CriteriaSet) -> None:
    """Criteria edited on the board before the run: the chat session (and a run that has fetched
    nothing yet) take them, so the chat's run_rounds starts with the edited values."""
    run = get_store().get(session.run_id) if session.run_id else None
    if run is not None and (run.candidates or run.rounds or is_busy(run.id) or _is_subject(run)):
        return   # a run with data changes criteria through PUT /criteria (recompute + diff)
    cs = _check_criteria(criteria)
    if session.criteria is not None:
        # keep the refusals the chat recorded (the board copy may predate the last one)
        texts = {r.text for r in cs.refused}
        cs.refused = list(cs.refused) + [r for r in session.criteria.refused if r.text not in texts]
    session.criteria = cs
    if run is not None:
        run.criteria = cs
        get_store().save(run)


class ApiChatContext:
    """ChatContext (app.llm.chat) backed by the run store, the engine and the event bus.
    Tool callbacks never raise: problems come back as {"ok": False, "error": ...} for the model."""

    def __init__(self, session: ChatSession, lang: Lang, emit: Emit) -> None:
        self.session = session
        self.lang: Lang = lang
        self.history: list[dict] = session.history
        self._emit = emit
        self.lang_override: str | None = None

    # -- state ---------------------------------------------------------------------------------

    def current_run(self) -> Run | None:
        rid = self.session.run_id
        return get_store().get(rid) if rid else None

    def current_criteria(self) -> CriteriaSet | None:
        run = self.current_run()
        return run.criteria if run is not None else self.session.criteria

    async def _criteria_changed(self, cs: CriteriaSet) -> None:
        self.session.criteria = cs
        data: dict[str, Any] = {"criteria": cs}
        if self.session.run_id:
            data["run_id"] = self.session.run_id
        await self._emit("criteria.updated", data)

    async def _set_criteria(self, cs: CriteriaSet) -> dict:
        """Store criteria for the session; if a run with candidates exists, recompute it."""
        cs = _check_criteria(cs)
        run = self.current_run()
        out: dict[str, Any] = {"ok": True}
        if run is not None and is_busy(run.id):
            # Like the other chat tools: wait for the running step instead of failing with "busy".
            await _wait_task(run.id, _tasks.get(run.id), CHAT_TOOL_WAIT)
            run = self.current_run()
        if run is not None and _only_refused_changed(run.criteria, cs):
            # A refused (unsupported) request changes nothing that is measured: store it on the run
            # without a recompute, so no fake re-render, report diff or "what changed" panel appears.
            run.criteria.refused = list(cs.refused)
            get_store().save(run)
            out.update({"run_id": run.id, "refused_only": True})
            await self._criteria_changed(run.criteria)
            return out
        if run is not None and (run.candidates or is_busy(run.id)):
            diff, fill = await _apply_criteria(run, cs)
            out.update({"run_id": run.id, "applied_to_run": True, "diff": _diff_summary(diff, self.lang),
                        "fill_missing_started": fill})
            if diff.get("report_diffs"):
                out["report_diffs"] = _report_diffs_summary(run, diff["report_diffs"], self.lang)
            if _is_subject(run):
                out["mode"] = "subject"
                out["note"] = _SUBJECT_NOTE[self.lang]
            await self._criteria_changed(run.criteria)
        else:
            if run is not None:  # run exists but nothing fetched yet
                run.criteria = cs
                get_store().save(run)
            await self._criteria_changed(cs)
        return out

    # -- tools ---------------------------------------------------------------------------------

    async def propose_criteria(self, criteria: CriteriaSet) -> dict:
        try:
            cs = CriteriaSet.model_validate(to_jsonable_python(criteria))
            out = await self._set_criteria(cs)
            out["criteria"] = _criteria_summary(cs, self.lang)
            if not out.get("applied_to_run"):
                out["next"] = "ask the owner to confirm, then call run_rounds(up_to=3)"
            return out
        except ApiError as e:
            return {"ok": False, "error": e.message}
        except Exception as e:
            return {"ok": False, "error": f"invalid criteria: {e}"}

    async def update_criterion(self, criterion_id: str, params: dict | None = None, enabled: bool | None = None) -> dict:
        try:
            current = self.current_criteria()
            if current is None:
                return {"ok": False, "error": "no criteria yet; call propose_criteria first"}
            cs = current.model_copy(deep=True)
            crit = next((c for c in cs.criteria if c.id == criterion_id), None) or next(
                (c for c in cs.criteria if c.kind == criterion_id), None)
            if crit is None:
                return {"ok": False, "error": f"unknown criterion {criterion_id!r}",
                        "criterion_ids": [c.id for c in cs.criteria]}
            ignored: list[str] = []
            defaults = CRITERION_DEFAULT_PARAMS.get(crit.kind, {})
            for key, value in (params or {}).items():
                city_ok = key == "city" and isinstance(value, str) and bool(value.strip())
                if key in defaults and (_param_ok(defaults[key], value) or city_ok):
                    crit.params[key] = value
                else:
                    ignored.append(key)
            if enabled is not None:
                crit.enabled = bool(enabled)
            cs = CriteriaSet.model_validate(cs.model_dump())
            out = await self._set_criteria(cs)
            new = next(c for c in cs.criteria if c.id == crit.id)
            out["criterion"] = {"id": new.id, "kind": new.kind, "enabled": new.enabled, "params": new.params}
            if ignored:
                out["ignored_params"] = ignored
                out["allowed_params"] = sorted(defaults)
            return out
        except ApiError as e:
            return {"ok": False, "error": e.message}
        except Exception as e:
            return {"ok": False, "error": f"cannot update criterion: {e}"}

    async def run_rounds(self, up_to: int) -> dict:
        try:
            up_to = int(up_to)
            if up_to >= 4:
                return {"ok": False, "error": "round 4 (deep vetting) needs the owner's confirmation; "
                                              "use start_deep_vetting with up to 5 finalists"}
            up_to = max(0, up_to)
            run = self.current_run()
            if _is_subject(run):
                return {"ok": False, "error": "this run checks one subject; use research_subject for another "
                                              "creator or change_goal for another goal"}
            if run is None:
                if self.session.criteria is None:
                    return {"ok": False, "error": "no criteria yet; call propose_criteria first"}
                run = _create_run(self.session.criteria, up_to)
                self.session.run_id = run.id
            elif not is_busy(run.id):
                done = max((r.get("round", -1) for r in run.rounds if isinstance(r, dict)), default=-1)
                if not (run.candidates and done >= up_to):
                    _start_task(run.id, "funnel", _funnel_job(up_to))
            status = await _wait_task(run.id, _tasks.get(run.id), CHAT_TOOL_WAIT)
            return {"ok": status != "error", "status": status, **_run_summary(run, self.lang)}
        except ApiError as e:
            return {"ok": False, "error": e.message}
        except Exception as e:
            return {"ok": False, "error": f"cannot run rounds: {e}"}

    async def explain_elimination(self, candidate_id: str) -> dict:
        run = self.current_run()
        if run is None:
            return {"ok": False, "error": "no run yet"}
        cid = _resolve_candidate(run, candidate_id)
        if cid is None:
            return {"ok": False, "error": f"unknown candidate {candidate_id!r}"}
        c = run.candidates[cid]
        lang = self.lang
        elim = None
        if c.elimination is not None:
            e = c.elimination
            elim = {"round": e.round, "criterion_id": e.criterion_id, "label": _label(run, e.criterion_id, lang),
                    "reason": e.reason.get(lang) or e.reason.get("cs"), "sources": [_src(s) for s in e.sources[:3]]}
        return {
            "ok": True, "candidate_id": c.id, "handle": c.ref.handle, "platform": c.ref.platform,
            "status": c.status, "restored": c.restored, "elimination": elim,
            "results": [
                {"criterion_id": r.criterion_id, "label": _label(run, r.criterion_id, lang), "status": r.status,
                 "value": r.value, "threshold": r.threshold, "waived": r.waived,
                 "sources": [_src(s) for s in r.sources[:2]]}
                for r in c.results
            ],
            "note": "the owner can restore the candidate on the board if this criterion does not apply to them",
        }

    async def start_deep_vetting(self, candidate_ids: list[str]) -> dict:
        run = self.current_run()
        if run is None:
            return {"ok": False, "error": "no run yet"}
        if is_busy(run.id):
            # e.g. fill_missing after a criterion edit: wait for it, then vet (instead of "run is busy")
            await _wait_task(run.id, _tasks.get(run.id), CHAT_TOOL_WAIT)
            run = self.current_run() or run
        try:
            ids = _start_vetting(run, list(candidate_ids or []))
        except ApiError as e:
            return {"ok": False, "error": e.message}
        status = await _wait_task(run.id, _tasks.get(run.id), CHAT_TOOL_WAIT)
        if _is_subject(run):
            fresh = get_store().get(run.id) or run
            return _subject_summary(fresh, status, "current", self.lang)
        r4_ids = {c.id for c in run.criteria.criteria if c.round == 4}
        return {"ok": status != "error", "status": status, "run_id": run.id, "error": _task_errors.get(run.id),
                "candidates": [_report_summary(run.candidates[i], self.lang, r4_ids) for i in ids if i in run.candidates]}

    async def change_goal(self, brief: Brief) -> dict:
        try:
            brief = Brief.model_validate(to_jsonable_python(brief))
            run = self.current_run()
            base = run.criteria if run is not None else self.session.criteria
            if base is None:
                name = _preset_for_brief(brief)
                if name is None:
                    return {"ok": True, "note": "no criteria yet; call propose_criteria for this brief"}
                cs, source = _criteria_from_preset(name, brief, None), f"preset:{name}"
            else:
                # use_agent=False: we are already inside the chat agent
                cs, source = await _criteria_for_brief(brief, base, run, use_agent=False)
            out = await self._set_criteria(cs)
            out.update({"criteria_source": source, "criteria": _criteria_summary(cs, self.lang)})
            if source == "kept_current":
                out["next"] = "the criteria still fit the old goal; call propose_criteria with criteria for the new goal"
            return out
        except ApiError as e:
            return {"ok": False, "error": e.message}
        except Exception as e:
            return {"ok": False, "error": f"cannot change goal: {e}"}

    async def research_subject(self, subject: str, anchor: dict | None = None, brief: Brief | None = None,
                               preset: str | None = None) -> dict:
        """Check ONE named creator for the owner's goal (subject mode). Never raises."""
        try:
            from app.compute.subject import normalize_anchor

            if not isinstance(subject, str) or not subject.strip():
                return {"ok": False, "error": "no subject: an @handle or an Instagram / TikTok profile link",
                        "missing": ["subject"]}
            try:
                platform, handle = _parse_subject_or_422(subject, None)
            except ApiError as e:
                return {"ok": False, "error": e.message, "missing": ["subject"]}
            if brief is not None and not isinstance(brief, (Brief, dict)):
                brief = None
            if brief is None and preset is None and self.session.criteria is None:
                return {"ok": False, "error": "no goal yet: ask the owner for the business and what the creator "
                                              "should help with", "missing": ["brief"]}
            try:
                criteria, source = _subject_criteria(brief, preset, None, self.lang, self.session.criteria)
            except ApiError as e:
                return {"ok": False, "error": e.message, "missing": ["brief"]}
            try:
                anc = normalize_anchor(anchor if isinstance(anchor, (dict, Anchor)) else None)
            except Exception:
                anc = None
            spec = SubjectSpec(raw=subject.strip()[:300], handle=handle, platform=platform, anchor=anc or Anchor())  # type: ignore[arg-type]
            run = start_subject_run(spec, criteria)
            self.session.run_id = run.id
            self.session.criteria = run.criteria
            await self._emit("criteria.updated", {"criteria": run.criteria, "run_id": run.id})
            status = await _wait_task(run.id, _tasks.get(run.id), CHAT_TOOL_WAIT)
            fresh = get_store().get(run.id) or run
            return _subject_summary(fresh, status, source, self.lang)
        except ApiError as e:
            return {"ok": False, "error": e.message}
        except Exception as e:
            log.exception("research_subject failed")
            return {"ok": False, "error": _secret_safe(f"cannot check the subject: {type(e).__name__}: {e}")}

    async def draft_outreach(self, candidate_id: str) -> dict:
        run = self.current_run()
        if run is None:
            return {"ok": False, "error": "no run yet"}
        cid = _resolve_candidate(run, candidate_id)
        if cid is None:
            return {"ok": False, "error": f"unknown candidate {candidate_id!r}"}
        c = run.candidates[cid]
        draft = c.report.outreach_draft if c.report is not None else None
        if not draft:
            try:
                from app.llm import vetting
                from app.llm.client import bind_llm_modes

                with bind_llm_modes(run.llm_modes):
                    draft = await vetting.outreach(run.criteria.brief, c)
            except Exception as e:
                return {"ok": False, "error": f"cannot draft outreach: {type(e).__name__}"}
            if c.report is not None:
                c.report.outreach_draft = draft
                get_store().save(run)
        note = i18n("NEODESLÁNO: jen koncept ke zkopírování, nic se neposílá.",
                    "NOT SENT: a draft to copy, nothing is sent.")
        return {"ok": True, "candidate_id": c.id, "handle": c.ref.handle, "draft": draft, "sent": False,
                "status": "draft_not_sent", "note": note[self.lang]}


def _only_refused_changed(old: CriteriaSet | None, new: CriteriaSet) -> bool:
    """True when ``new`` differs from ``old`` only in the refused list (and that list did change)."""
    if old is None:
        return False
    a = old.model_dump(mode="json", exclude={"refused"})
    b = new.model_dump(mode="json", exclude={"refused"})
    return a == b and [r.text for r in old.refused] != [r.text for r in new.refused]


def _param_ok(default: Any, value: Any) -> bool:
    """Light type check of a criterion param against its default (whitelisted keys only)."""
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)) or default is None:
        return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if isinstance(default, str):
        return isinstance(value, str)
    return True


# =============================================================================================
# App
# =============================================================================================


_loop: asyncio.AbstractEventLoop | None = None


def _on_server_exit() -> None:
    """Ctrl+C / SIGTERM: uvicorn waits for open connections before the lifespan shutdown, and a
    following /events stream never closes by itself. End the streams so the server can stop, and
    let the shutdown keep the busy markers of runs it cancels (they are reported as interrupted)."""
    global _shutting_down
    _shutting_down = True
    loop = _loop
    if loop is not None and not loop.is_closed():
        with contextlib.suppress(Exception):
            loop.call_soon_threadsafe(get_bus().end_streams)


def _hook_uvicorn_exit() -> None:
    try:
        from uvicorn.server import Server
    except Exception:  # pragma: no cover - uvicorn is how the app runs, but tests do not need it
        return
    orig = Server.handle_exit
    if getattr(orig, "_creator_scout", False):
        return

    def handle_exit(self, sig, frame):  # type: ignore[no-untyped-def]
        _on_server_exit()
        return orig(self, sig, frame)

    handle_exit._creator_scout = True  # type: ignore[attr-defined]
    Server.handle_exit = handle_exit  # type: ignore[method-assign]


_hook_uvicorn_exit()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    try:
        n = get_store().load_all()
        if n:
            log.info("loaded %d run snapshot(s)", n)
    except Exception:
        log.exception("cannot load run snapshots")
    yield
    global _shutting_down
    _shutting_down = True
    try:
        await _cancel_all_tasks()
    finally:
        _shutting_down = False


app = FastAPI(title="Creator Scout", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Chat-Id"],
)


@app.exception_handler(ApiError)
async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


def _json(obj: Any) -> JSONResponse:
    return JSONResponse(to_jsonable_python(obj))


# -- request bodies ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    lang: Lang = "cs"
    run_id: str | None = None
    chat_id: str | None = None
    reset: bool = False
    # The criteria as the board shows them (the owner may have edited a proposal before any run
    # exists). Applied to the chat session when no run has fetched anything yet, so "yes, start"
    # in the chat runs exactly what the board shows.
    criteria: CriteriaSet | None = None


class CreateRunRequest(BaseModel):
    criteria: CriteriaSet | None = None
    preset: PresetName | None = None
    up_to: int = Field(3, ge=0, le=3)


class VetRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)


class CriteriaRequest(BaseModel):
    criteria: CriteriaSet


class RestoreRequest(BaseModel):
    candidate_id: str
    criterion_id: str


class GoalRequest(BaseModel):
    brief: Brief | None = None
    preset: PresetName | None = None
    criteria: CriteriaSet | None = None


class SubjectRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    platform: Literal["instagram", "tiktok"] | None = None
    anchor: Anchor | str | None = None      # a plain string is classified: digits = company ID, a dot = website, else city
    brief: Brief | str | None = None
    preset: PresetName | None = None
    criteria: CriteriaSet | None = None
    lang: Lang = "en"


# -- routes -----------------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    return {
        "source_mode": s.source_mode,
        "llm_mode": s.llm_mode,
        "llm_provider": s.llm_provider,            # "anthropic" | "openrouter" | null (fallback)
        "llm_model": s.llm_model,                  # configured chat model of that provider
        "llm_models_used": _llm_models_used(),     # {task: model that actually answered} (OpenRouter routes)
        "apify_configured": s.apify_configured,
        "apify_provider_implemented": _apify_implemented(),
        **_usage_snapshot(),                       # llm_requests_used / llm_budget / ... (llm.budget)
    }


def _llm_models_used() -> dict[str, str]:
    try:
        from app.llm.client import models_used

        return models_used()
    except Exception:
        return {}


def _apify_implemented() -> bool:
    try:
        from app.sources.factory import apify_available

        return apify_available()
    except Exception:
        return False


@app.get("/api/presets")
async def presets() -> JSONResponse:
    return _json({"bakery": get_preset("bakery"), "fitness": get_preset("fitness")})


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest) -> StreamingResponse:
    session = _resolve_session(req.chat_id, req.run_id, req.reset)
    queue: asyncio.Queue = asyncio.Queue()
    end = object()

    if req.message.strip() in session.inflight:
        # The same message sent twice in one tick (double submit): answer it once.
        async def dup_stream():
            yield format_sse("done", {"chat_id": session.id, "run_id": session.run_id, "duplicate": True,
                                      "llm_mode": "llm" if _llm_available() else "fallback"})

        return StreamingResponse(dup_stream(), media_type="text/event-stream",
                                 headers={**SSE_HEADERS, "X-Chat-Id": session.id})

    if req.criteria is not None:
        try:
            _board_criteria_to_session(session, req.criteria)
        except ApiError as e:
            log.info("chat: board criteria not applied: %s", e.message)

    turn_llm_mode: dict[str, str] = {}
    turn_llm_model: dict[str, str] = {}
    turn_lang: dict[str, str] = {}

    async def emit(event: str, data: dict) -> None:
        if event == "done":  # exactly one done, always last (sent by the worker below)
            if isinstance(data, dict) and isinstance(data.get("llm_mode"), str):
                turn_llm_mode["v"] = data["llm_mode"]  # "llm" | "fallback" as reported by chat.py
            if isinstance(data, dict) and isinstance(data.get("llm_model"), str):
                turn_llm_model["v"] = data["llm_model"]  # OpenRouter: the model that answered
            if isinstance(data, dict) and data.get("lang") in ("cs", "en"):
                turn_lang["v"] = data["lang"]  # effective chat language decided by chat.py
            return
        queue.put_nowait((event, to_jsonable_python(data if data is not None else {})))

    if session.last_lang in ("cs", "en") and req.lang != session.last_lang:
        # The UI follows the guide's language after every answer, so a different UI language now is
        # the owner's own choice (the EN / CS switch): answer in it from here on.
        session.lang_override = req.lang
    ctx = ApiChatContext(session, req.lang, emit)
    ctx.lang_override = session.lang_override  # type: ignore[attr-defined]
    session.inflight.append(req.message.strip())

    async def worker() -> None:
        try:
            from app.llm import chat

            async with session.lock:
                if _llm_available():
                    await chat.chat_turn(req.message, ctx, emit)
                else:
                    await chat.fallback_turn(req.message, ctx, emit)
        except NotImplementedError as exc:
            await emit("error", {"message": f"chat is not implemented yet ({_where(exc)})"})
        except Exception as exc:
            log.exception("chat turn failed")
            await emit("error", {"message": _secret_safe(f"chat failed: {type(exc).__name__}: {exc}")})
        finally:
            if req.message.strip() in session.inflight:
                session.inflight.remove(req.message.strip())
            mode = turn_llm_mode.get("v") or ("llm" if _llm_available() else "fallback")
            done = {"chat_id": session.id, "run_id": session.run_id, "llm_mode": mode}
            if "v" in turn_llm_model:
                done["llm_model"] = turn_llm_model["v"]
            if "v" in turn_lang:
                done["lang"] = turn_lang["v"]
                session.last_lang = turn_lang["v"]
            queue.put_nowait(("done", done))
            queue.put_nowait(end)

    # The turn keeps running if the client disconnects, so the history stays consistent.
    task = asyncio.create_task(worker(), name=f"chat:{session.id}")
    _chat_tasks.add(task)
    task.add_done_callback(_chat_tasks.discard)

    async def stream():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), HEARTBEAT_S)
            except TimeoutError:
                yield format_heartbeat()
                continue
            if item is end:
                return
            event, data = item
            yield format_sse(event, data)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={**SSE_HEADERS, "X-Chat-Id": session.id})


@app.get("/api/runs")
async def list_runs() -> JSONResponse:
    store = get_store()
    out = []
    for rid in store.list_ids():
        run = store.get(rid)
        if run is None:
            continue
        out.append({"run_id": run.id, "busy": is_busy(run.id), "business_type": run.criteria.brief.business_type,
                    "candidates": len(run.candidates), "rounds": run.rounds, "mode": run.mode,
                    "subject": run.subject.handle if run.subject is not None else None})
    return _json(out)


@app.post("/api/runs")
async def create_run(req: CreateRunRequest) -> dict:
    if req.criteria is not None:
        criteria = req.criteria
    elif req.preset is not None:
        criteria = get_preset(req.preset)
    else:
        raise ApiError(422, "send {criteria: CriteriaSet} or {preset: 'bakery' | 'fitness'}")
    run = _create_run(criteria, req.up_to)
    return {"run_id": run.id}


RUN_PUBLIC_EXCLUDE = {"candidates": {"__all__": {"vetting_data"}}}


def run_public_json(run: Run) -> dict:
    """Run JSON for clients: candidates' raw vetting data (vetting_data) stays server-side."""
    return run.model_dump(mode="json", exclude=RUN_PUBLIC_EXCLUDE)


@app.post("/api/subject")
async def create_subject_run(req: SubjectRequest) -> dict:
    """Subject mode: one named creator, one anchor, one goal -> a sourced, goal-conditioned report."""
    platform, handle = _parse_subject_or_422(req.subject, req.platform)
    criteria, _source = _subject_criteria(req.brief, req.preset, req.criteria, req.lang)
    anchor = _anchor_or_422(req.anchor)
    spec = SubjectSpec(raw=req.subject.strip(), handle=handle, platform=platform, anchor=anchor)  # type: ignore[arg-type]
    run = start_subject_run(spec, criteria)
    return {"run_id": run.id, "mode": "subject",
            "subject": {"raw": spec.raw, "handle": spec.handle, "platform": spec.platform}, "status": "started"}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    run = _get_run(run_id)
    _resolve_interrupted(run)
    return JSONResponse(run_public_json(run))


@app.get("/api/runs/{run_id}/chat")
async def run_chat(run_id: str) -> JSONResponse:
    """The chat bound to this run (the newest session), so a reload or a second tab on ?run= can show
    the conversation and continue it with this chat_id. Text only: no tool payloads."""
    from app.llm.chat import _is_owner_msg, _msg_text

    run = _get_run(run_id)
    bound = [x for x in _sessions.values() if x.run_id == run.id]
    if not bound:
        return _json({"run_id": run.id, "chat_id": None, "messages": []})
    s = max(bound, key=lambda x: x.touched)
    msgs: list[dict[str, str]] = []
    for m in s.history:
        role = m.get("role")
        if role == "user" and not _is_owner_msg(m):
            continue   # tool results
        text = _msg_text(m).strip()
        if role in ("user", "assistant") and text:
            msgs.append({"role": role, "text": text})
    return _json({"run_id": run.id, "chat_id": s.id, "lang": s.last_lang, "messages": msgs})


@app.get("/api/runs/{run_id}/status")
async def run_status(run_id: str) -> JSONResponse:
    run = _get_run(run_id)
    interrupted = _resolve_interrupted(run)
    counts: dict[str, int] = {}
    for c in run.candidates.values():
        counts[c.status] = counts.get(c.status, 0) + 1
    snap = _usage_snapshot()
    return _json({"run_id": run.id, "busy": is_busy(run.id), "error": _task_errors.get(run.id),
                  "interrupted": bool(interrupted),
                  "rounds": run.rounds, "mode_summary": run.mode_summary, "llm_modes": run.llm_modes,
                  "counts": counts, "mode": run.mode,
                  "subject": run.subject.model_dump(mode="json") if run.subject is not None else None,
                  "llm_requests_used": run.llm_usage.get("total", 0),
                  "llm_usage": run.llm_usage,
                  "llm_budget": snap.get("llm_budget"), "llm_budget_left": snap.get("llm_budget_left")})


def _seed_history(run: Run, interrupted: str | None = None) -> None:
    """After a restart the bus has no history: synthesize one from the snapshot so a client that
    connects to /events still rebuilds the board. An interrupted run ends with an ``error`` event
    ({"interrupted": true}) instead of ``run.finished``: its work never finished."""
    bus = get_bus()
    bus.publish_nowait(run.id, "run.started", {"run_id": run.id, "from_snapshot": True})
    for entry in run.log:
        bus.publish_nowait(run.id, "log", entry)
    for c in run.candidates.values():
        bus.publish_nowait(run.id, "candidate.added", {"candidate": c})
        if c.status == "eliminated" and c.elimination is not None:
            bus.publish_nowait(run.id, "candidate.eliminated", {"id": c.id, "elimination": c.elimination})
    for r in run.rounds:
        if isinstance(r, dict):
            bus.publish_nowait(run.id, "round.finished", r)
    for c in run.candidates.values():
        if c.report is not None:
            bus.publish_nowait(run.id, "report.ready", {"candidate_id": c.id})
    if interrupted:
        lang = run.criteria.brief.lang if run.criteria and run.criteria.brief else "cs"
        msg = ("Server se zastavil uprostřed práce na tomto běhu; výsledek není úplný. Spusťte to prosím znovu."
               if lang != "en" else "The server stopped while this run was working; the result is incomplete. "
                                    "Please start it again.")
        bus.publish_nowait(run.id, "error", {"message": msg, "interrupted": True, "run_id": run.id})
        return
    bus.publish_nowait(run.id, "run.finished", {"run_id": run.id, "from_snapshot": True})


@app.get("/api/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    follow: bool = Query(True, description="keep streaming after the run goes idle"),
    after: int = Query(0, ge=0, description="skip the first N events (resume)"),
) -> StreamingResponse:
    run = _get_run(run_id)
    bus = get_bus()
    interrupted = _resolve_interrupted(run)
    if not bus.has_history(run.id) and not is_busy(run.id) and (run.candidates or run.rounds or interrupted):
        _seed_history(run, interrupted=interrupted)
    last = (request.headers.get("last-event-id") or "").strip()
    if last.isdigit():
        after = max(after, int(last))
    return StreamingResponse(sse_run_stream(bus, run.id, after=after, follow=follow),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/runs/{run_id}/vet")
async def vet(run_id: str, req: VetRequest) -> dict:
    run = _get_run(run_id)
    ids = _start_vetting(run, req.candidate_ids)
    return {"run_id": run.id, "candidate_ids": ids, "status": "started"}


@app.post("/api/runs/{run_id}/criteria")
async def update_criteria(run_id: str, req: CriteriaRequest) -> JSONResponse:
    run = _get_run(run_id)
    diff, fill = await _apply_criteria(run, req.criteria)
    return _json({**diff, "fill_missing_started": fill})


@app.post("/api/runs/{run_id}/restore")
async def restore(run_id: str, req: RestoreRequest) -> JSONResponse:
    run = _get_run(run_id)
    diff, fill = await _restore(run, req.candidate_id, req.criterion_id)
    return _json({**diff, "fill_missing_started": fill})


@app.post("/api/runs/{run_id}/goal")
async def change_goal(run_id: str, req: GoalRequest) -> JSONResponse:
    run = _get_run(run_id)
    if is_busy(run.id):
        raise ApiError(409, "run is busy (another step is still running); try again when it finishes")
    previous = run.criteria.brief.model_copy(deep=True)
    if req.criteria is not None:
        cs, source = req.criteria, "request"
    elif req.preset is not None:
        cs, source = _criteria_from_preset(req.preset, req.brief, run), f"preset:{req.preset}"
    elif req.brief is not None:
        # A subject run uses the deterministic criteria (as the chat's change_goal does): a goal switch
        # costs 0 LLM requests there.
        cs, source = await _criteria_for_brief(req.brief, run.criteria, run, use_agent=not _is_subject(run))
    else:
        raise ApiError(422, "send {brief}, {preset} or {criteria}")
    # Requests refused earlier stay visible after a goal change (gray chips under "NEKONTROLUJEME").
    cs = cs.model_copy(update={"refused": list(run.criteria.refused) + list(cs.refused)})
    diff, fill = await _apply_criteria(run, cs)
    for s in _sessions.values():  # keep chat sessions on this run in sync
        if s.run_id == run.id:
            s.criteria = run.criteria
    return _json({"criteria": run.criteria, "criteria_source": source, "previous_brief": previous,
                  **diff, "fill_missing_started": fill})


@app.get("/api/runs/{run_id}/compare")
async def compare(run_id: str, sort: str | None = None) -> JSONResponse:
    run = _get_run(run_id)
    if sort and sort not in {c.id for c in run.criteria.criteria}:
        raise ApiError(400, f"unknown criterion {sort!r}")
    result = _sync_engine_call(run, "compare", lambda: _engine().compare(run, sort or None), mutates=False)
    return _json(result)


@app.post("/api/purge")
async def purge() -> dict:
    await _cancel_all_tasks()
    deleted = purge_all()
    _task_errors.clear()
    _sessions.clear()
    return {"ok": True, "deleted": deleted}


async def reset_runtime_state() -> None:
    """Tests: cancel background work and forget sessions / errors (store + bus are per DATA_DIR)."""
    await _cancel_all_tasks()
    _task_errors.clear()
    _sessions.clear()
    get_bus().clear()
