"""Funnel engine (architecture.md section 5). Orchestrates round modules r0..r4.

Round module interface (r1_basics .. r4_vetting each expose):
    ROUND: int
    async def prepare(run, candidates, provider, emit) -> None   # fetch + compute; I/O and LLM allowed
    def evaluate(criterion, candidate, brief, now) -> CriterionResult   # pure; no I/O, no LLM
    def assess(criterion, candidate, brief, now) -> Outcome             # same, bilingual (for reasons)

Rules:
- Rounds run in order. For round r: emit round.started; prepare(active candidates); for every active
  candidate evaluate every ENABLED criterion with round == r (in CriteriaSet order), replace that
  round's results on the candidate, eliminate at the FIRST result with status "fail" and not waived
  (Elimination(round, criterion_id, reason, sources)); emit candidate.eliminated / candidate.updated;
  append {"round", "entered", "remaining"} to run.rounds (replace an existing entry for that round)
  and emit round.finished. ``unknown`` never eliminates; a waived result counts as pass.
- After round 3 the survivors get status "finalist".
- Round 4 never eliminates: results are recorded, failures shown, status stays "finalist".
- Bind ``events.bind_emit(emit)`` and ``llm.client.bind_llm_modes(run.llm_modes)`` for the whole
  run so providers / LLM tasks can log and label. Keep run.mode_summary updated (count SourceRef
  modes of fetched objects). Save via store after each round. Errors -> emit("error", {...}),
  never crash silently.
- Hard lines: minors removed from run.candidates with nothing stored; no overall score/rank.

Logging: round modules log through ``common.log`` (appends to run.log + emits); providers log through
``events.emit_log``, which the engine binds to a recording emitter so their lines land in run.log too.
Round modules therefore get the raw ``emit`` (never the recording one, or lines would be doubled).

Extra event (not in architecture.md): ``candidate.removed {"id"}`` when round 1 removes a candidate
whose profile was not returned (a minor dropped by the provider, or not found). Nothing is kept.
``run_funnel`` continues from the last round reached (a second call with a higher ``up_to`` runs only
the missing rounds). ``run_vetting`` emits round.started/finished for round 4 and ``run.finished``.
"""

from __future__ import annotations

import contextlib
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any, Literal, TypedDict

from app.events import Emit, bind_emit
from app.llm.client import bind_llm_modes
from app.models import (
    CRITERION_DEFAULT_LABELS,
    CRITERION_ROUND,
    Candidate,
    CriteriaSet,
    Criterion,
    CandidateRef,
    CriterionResult,
    Elimination,
    Run,
    i18n,
    make_source_ref,
    utcnow,
)
from app.rounds import r0_discovery, r1_basics, r2_content, r3_audience, r4_vetting
from app.rounds.common import (
    cs_plural,
    elimination_for,
    log,
    logger,
    recording_emit,
    save_run,
    tr,
)
from app.rounds.r2_content import needs_topics
from app.rounds.r3_audience import needs_comments
from app.sources.base import SourceProvider

ROUND_MODULES = {1: r1_basics, 2: r2_content, 3: r3_audience, 4: r4_vetting}
FUNNEL_ROUNDS = (1, 2, 3)


class DiffEntry(TypedDict):
    candidate_id: str
    handle: str
    platform: str
    before: Literal["active", "eliminated", "finalist"]
    after: Literal["active", "eliminated", "finalist"]
    elimination: dict | None   # Elimination (json): the NEW one for dropped, the PREVIOUS one for returned
    needs_fetch: bool          # returned candidate lacks data for a round it now enters (results "unknown")


class _DiffBase(TypedDict):
    dropped: list[DiffEntry]
    returned: list[DiffEntry]


class Diff(_DiffBase, total=False):
    # recompute only: restore waivers that no longer apply (goal changed, or that criterion's
    # kind / params changed): [{"candidate_id", "handle", "criterion_id"}]
    waivers_dropped: list[dict]
    # recompute only: one ReportDiff per re-rendered report (candidates with vetting_data)
    report_diffs: list


@contextlib.contextmanager
def _llm_usage(run: Run) -> Iterator[None]:
    """budget.bind_llm_usage(run.llm_usage) when the budget module is available."""
    try:
        from app.llm.budget import bind_llm_usage
    except Exception:  # pragma: no cover - budget module missing
        yield
        return
    with bind_llm_usage(run.llm_usage):
        yield


# ---------------------------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------------------------

def max_round_reached(run: Run) -> int:
    """Highest funnel round (0..3) recorded in run.rounds; -1 when nothing ran yet."""
    rounds = [int(e.get("round", -1)) for e in run.rounds if isinstance(e, dict) and int(e.get("round", -1)) <= 3]
    return max(rounds, default=-1)


def _upsert_round(run: Run, round_no: int, entered: int, remaining: int, **extra: int) -> None:
    entry = {"round": round_no, "entered": entered, "remaining": remaining, **extra}
    for i, e in enumerate(run.rounds):
        if isinstance(e, dict) and e.get("round") == round_no:
            run.rounds[i] = {**e, **entry}
            break
    else:
        run.rounds.append(entry)
    run.rounds.sort(key=lambda e: e.get("round", 0))


def refresh_round_counts(run: Run) -> None:
    """Recount entered / remaining for rounds 1..3 already in run.rounds from candidate states."""
    for e in run.rounds:
        r = e.get("round")
        if r not in FUNNEL_ROUNDS:
            continue
        entered = remaining = 0
        for c in run.candidates.values():
            out_round = c.elimination.round if (c.status == "eliminated" and c.elimination) else None
            if out_round is None or out_round >= r:
                entered += 1
            if out_round is None or out_round > r:
                remaining += 1
        # candidates removed in this round (minors / missing profiles) entered it but left no trace
        e["entered"], e["remaining"] = entered + int(e.get("removed", 0)), remaining
    for e in run.rounds:
        if e.get("round") == 4:
            e["entered"] = e["remaining"] = vetted_finalists(run)


def vetted_finalists(run: Run) -> int:
    """Round 4 count: current finalists that have a report. Round 4 never eliminates, so entered ==
    remaining; after a goal change it drops to the finalists vetted so far for the new goal's pool."""
    return sum(1 for c in run.candidates.values() if c.status == "finalist" and c.report is not None)


def _round_criteria(run: Run, round_no: int) -> list[Criterion]:
    return [c for c in run.criteria.criteria if c.enabled and c.round == round_no]


def _criterion_order(run: Run) -> dict[str, int]:
    return {c.id: i for i, c in enumerate(run.criteria.criteria)}


def _snapshot(run: Run) -> dict[str, tuple[str, Elimination | None]]:
    return {cid: (c.status, c.elimination) for cid, c in run.candidates.items()}


def snapshot_states(run: Run) -> dict[str, tuple[str, Elimination | None]]:
    """Public: (status, elimination) per candidate, a baseline for ``diff_since``."""
    return _snapshot(run)


def diff_since(run: Run, before: dict[str, tuple[str, Elimination | None]]) -> Diff:
    """Public: who dropped / returned since ``before`` (e.g. recompute + fill_missing combined)."""
    return _diff(run, before)


def candidate_needs_fetch(c: Candidate, reached: int) -> bool:
    """Active / finalist candidate lacking data for a round it has entered."""
    if c.status == "eliminated":
        return False
    if reached >= 1 and c.profile is None:
        return True
    if reached >= 2 and needs_topics(c):
        return True
    if reached >= 3 and needs_comments(c):
        return True
    return False


def _diff(run: Run, before: dict[str, tuple[str, Elimination | None]]) -> Diff:
    reached = max_round_reached(run)
    dropped: list[DiffEntry] = []
    returned: list[DiffEntry] = []
    for cid, c in run.candidates.items():
        if cid not in before:
            continue
        b_status, b_elim = before[cid]
        a_status = c.status
        was_out, is_out = b_status == "eliminated", a_status == "eliminated"
        if not was_out and is_out:
            dropped.append(DiffEntry(
                candidate_id=cid, handle=c.ref.handle, platform=c.ref.platform,
                before=b_status, after=a_status,  # type: ignore[typeddict-item]
                elimination=c.elimination.model_dump(mode="json") if c.elimination else None,
                needs_fetch=False,
            ))
        elif was_out and not is_out:
            returned.append(DiffEntry(
                candidate_id=cid, handle=c.ref.handle, platform=c.ref.platform,
                before=b_status, after=a_status,  # type: ignore[typeddict-item]
                elimination=b_elim.model_dump(mode="json") if b_elim else None,
                needs_fetch=candidate_needs_fetch(c, reached),
            ))
    return Diff(dropped=dropped, returned=returned)


# ---------------------------------------------------------------------------------------------
# Evaluation (pure: stored data only)
# ---------------------------------------------------------------------------------------------

def _evaluate_candidate_round(run: Run, c: Candidate, round_no: int, now: datetime) -> Elimination | None:
    """Replace round ``round_no`` results on ``c``; return the elimination (rounds 1-3) or None."""
    module = ROUND_MODULES[round_no]
    brief = run.criteria.brief
    crits = _round_criteria(run, round_no)
    round_ids = {cr.id for cr in run.criteria.criteria if cr.round == round_no}
    prev = {r.criterion_id: r for r in c.results}
    order = _criterion_order(run)

    new_results: list[CriterionResult] = []
    elimination: Elimination | None = None
    for cr in crits:
        outcome = module.assess(cr, c, brief, now)
        res = outcome.result(cr.id, brief.lang)
        if prev.get(cr.id) is not None and prev[cr.id].waived:
            res.waived = True
        new_results.append(res)
        if elimination is None and round_no in FUNNEL_ROUNDS and res.status == "fail" and not res.waived:
            elimination = elimination_for(round_no, cr, outcome)

    known = set(order)
    kept = [r for r in c.results if r.criterion_id not in round_ids and r.criterion_id in known]
    c.results = sorted(kept + new_results, key=lambda r: order.get(r.criterion_id, 10_000))
    return elimination


def evaluate_round(
    run: Run,
    round_no: int,
    *,
    now: datetime | None = None,
    candidate_ids: Iterable[str] | None = None,
) -> list[str]:
    """Evaluate round ``round_no`` (1..3) for the currently active candidates from stored data only.
    Updates results / status / elimination. Returns ids eliminated in this round. Shared by
    run_funnel, recompute and restore. Round 4: records results for vetted (reported) candidates
    that are not eliminated; never eliminates. ``candidate_ids`` limits the evaluation."""
    now = now or utcnow()
    only = set(candidate_ids) if candidate_ids is not None else None
    eliminated: list[str] = []
    for cid, c in run.candidates.items():
        if only is not None and cid not in only:
            continue
        if round_no == 4:
            if c.report is None or c.status == "eliminated":
                continue
            _evaluate_candidate_round(run, c, 4, now)
            continue
        if c.status != "active":
            continue
        elim = _evaluate_candidate_round(run, c, round_no, now)
        if elim is not None:
            c.status = "eliminated"
            c.elimination = elim
            eliminated.append(cid)
    return eliminated


def _promote_finalists(run: Run, candidate_ids: Iterable[str] | None = None) -> list[str]:
    only = set(candidate_ids) if candidate_ids is not None else None
    out = []
    for cid, c in run.candidates.items():
        if (only is None or cid in only) and c.status == "active":
            c.status = "finalist"
            out.append(cid)
    return out


def _evaluate_candidate_from(run: Run, c: Candidate, start_round: int, now: datetime) -> None:
    """Re-run rounds start_round..reached for one candidate (status reset to active first)."""
    reached = max_round_reached(run)
    c.status = "active"
    c.elimination = None
    for r in range(max(1, start_round), min(reached, 3) + 1):
        if evaluate_round(run, r, now=now, candidate_ids=[c.id]):
            break
    if c.status == "active" and reached >= 3:
        c.status = "finalist"
    if c.status == "finalist" and c.report is not None:
        evaluate_round(run, 4, now=now, candidate_ids=[c.id])


# ---------------------------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------------------------

def _elimination_summary(run: Run, ids: list[str]) -> str:
    labels = {c.id: c.label for c in run.criteria.criteria}
    lang = run.criteria.brief.lang
    counts = Counter(run.candidates[i].elimination.criterion_id for i in ids  # type: ignore[union-attr]
                     if i in run.candidates and run.candidates[i].elimination)
    parts = []
    for crit_id, n in counts.most_common():
        label = labels.get(crit_id) or CRITERION_DEFAULT_LABELS.get(crit_id) or {"cs": crit_id, "en": crit_id}
        parts.append(f"{label.get(lang) or label.get('cs')}: {n}")
    return ", ".join(parts)


async def _run_round(run: Run, round_no: int, provider: SourceProvider, emit: Emit, now: datetime) -> None:
    await emit("round.started", {"round": round_no})
    module = ROUND_MODULES[round_no]
    active = [c for c in run.candidates.values() if c.status == "active"]
    entered = len(active)
    before_ids = set(run.candidates)
    await module.prepare(run, active, provider, emit)
    removed = sorted(before_ids - set(run.candidates))
    for cid in removed:
        await emit("candidate.removed", {"id": cid})
    active_ids = [c.id for c in active if c.id in run.candidates]
    eliminated = evaluate_round(run, round_no, now=now, candidate_ids=active_ids)
    if round_no == 3:
        _promote_finalists(run, active_ids)
    for cid in active_ids:
        await emit("candidate.updated", {"candidate": run.candidates[cid]})
    for cid in eliminated:
        await emit("candidate.eliminated", {"id": cid, "elimination": run.candidates[cid].elimination})
    remaining = sum(1 for cid in active_ids if run.candidates[cid].status != "eliminated")
    if removed:
        _upsert_round(run, round_no, entered, remaining, removed=len(removed))
    else:
        _upsert_round(run, round_no, entered, remaining)
    n_out = len(eliminated)
    summary = _elimination_summary(run, eliminated)
    await log(run, emit, tr(
        run,
        f"Kolo {round_no}: vstoupilo {entered} → zůstalo {remaining}"
        + (f"; vyřazeno {n_out} ({summary})" if n_out else ""),
        f"Round {round_no}: entered {entered} → remaining {remaining}"
        + (f"; {n_out} out ({summary})" if n_out else ""),
    ), actor="engine")
    await emit("round.finished", {"round": round_no, "entered": entered, "remaining": remaining})
    save_run(run)


async def run_funnel(
    run: Run,
    provider: SourceProvider,
    emit: Emit,
    *,
    up_to: int = 3,
    now: datetime | None = None,
) -> Run:
    """Rounds 0..up_to (max 3). Emits run.started ... run.finished. Mutates and returns run.
    Continues from the last round reached; rounds already run are not repeated."""
    up_to = max(0, min(3, up_to))
    rec = recording_emit(run, emit)
    with bind_emit(rec, run.criteria.brief.lang), bind_llm_modes(run.llm_modes), _llm_usage(run):
        await emit("run.started", {"run_id": run.id})
        current = None
        try:
            start = max_round_reached(run) + 1
            if start == 0:
                current = 0
                await emit("round.started", {"round": 0})
                added, raw = await r0_discovery.discover_with_stats(run, provider, emit)
                _upsert_round(run, 0, raw, len(run.candidates))
                await log(run, emit, tr(run, f"Kolo 0: nalezeno {raw} → {len(run.candidates)} kandidátů",
                                        f"Round 0: found {raw} → {len(run.candidates)} candidates"), actor="engine")
                await emit("round.finished", {"round": 0, "entered": raw, "remaining": len(run.candidates)})
                save_run(run)
                start = 1
            for r in range(start, up_to + 1):
                current = r
                await _run_round(run, r, provider, emit, now or utcnow())
        except Exception as e:  # never crash silently
            logger.exception("run %s failed in round %s", run.id, current)
            await log(run, emit, tr(run, f"Chyba v kole {current}: {e}", f"Error in round {current}: {e}"), actor="engine")
            await emit("error", {"message": f"round {current}: {e}"})
            save_run(run)
            return run
        await emit("run.finished", {"run_id": run.id})
    return run


async def run_vetting(run: Run, candidate_ids: list[str], provider: SourceProvider, emit: Emit) -> Run:
    """Round 4 for the given finalists (max 5): r4_vetting.prepare + evaluate, report.ready per
    candidate. Never eliminates, never auto-picks. Eliminated candidates are skipped (restore first)."""
    rec = recording_emit(run, emit)
    with bind_emit(rec, run.criteria.brief.lang), bind_llm_modes(run.llm_modes), _llm_usage(run):
        try:
            await emit("round.started", {"round": 4})
            wanted = [cid for cid in dict.fromkeys(candidate_ids) if cid in run.candidates]
            skipped = [cid for cid in wanted if run.candidates[cid].status == "eliminated"]
            eligible = [run.candidates[cid] for cid in wanted if cid not in skipped]
            chosen = eligible[: r4_vetting.MAX_FINALISTS]
            if len(eligible) > len(chosen):
                await log(run, emit, tr(
                    run, f"Kolo 4: najednou nejvýš {r4_vetting.MAX_FINALISTS} finalistů; {len(eligible) - len(chosen)} počká na další běh",
                    f"Round 4: at most {r4_vetting.MAX_FINALISTS} finalists at once; {len(eligible) - len(chosen)} left for a next run"),
                    actor="engine")
            if skipped:
                await log(run, emit, tr(run, f"Kolo 4: přeskočeno {len(skipped)} vyřazených (nejdřív je vraťte)",
                                        f"Round 4: skipped {len(skipped)} eliminated (restore them first)"), actor="engine")
            n = len(chosen)
            await log(run, emit, tr(run, f"Kolo 4: hloubková prověrka {n} {cs_plural(n, 'finalisty', 'finalistů', 'finalistů')}",
                                    f"Round 4: deep vetting of {n} {'finalist' if n == 1 else 'finalists'}"), actor="engine")
            await r4_vetting.prepare(run, chosen, provider, emit)
            ids = [c.id for c in chosen]
            evaluate_round(run, 4, candidate_ids=ids)
            for cid in ids:
                await emit("candidate.updated", {"candidate": run.candidates[cid]})
            vetted = vetted_finalists(run)
            _upsert_round(run, 4, vetted, vetted)
            await emit("round.finished", {"round": 4, "entered": vetted, "remaining": vetted})
            save_run(run)
        except Exception as e:
            logger.exception("vetting failed for run %s", run.id)
            await log(run, emit, tr(run, f"Chyba v kole 4: {e}", f"Error in round 4: {e}"), actor="engine")
            await emit("error", {"message": f"round 4: {e}"})
            save_run(run)
            return run
        await emit("run.finished", {"run_id": run.id})
    return run


def _subject_text(run: Run) -> tuple[str, str]:
    from app.compute.subject import anchor_text

    sub = run.subject
    if sub is None:
        return "", ""
    a_cs, a_en = anchor_text(sub.anchor, "cs"), anchor_text(sub.anchor, "en")
    return (f"Prověřujeme @{sub.handle}" + (f" ({sub.platform})" if sub.platform else "")
            + (f"; kotva: {a_cs}" if a_cs else "; bez kotvy"),
            f"Checking @{sub.handle}" + (f" ({sub.platform})" if sub.platform else "")
            + (f"; anchor: {a_en}" if a_en else "; no anchor"))


async def _resolve_subject(run: Run, provider: SourceProvider, emit: Emit) -> Candidate | None:
    """Find the named profile: the given platform, else Instagram then TikTok. Uses round 1's
    prepare (fetch + minors guard + sensitive filter); a missing profile or a minor leaves nothing."""
    sub = run.subject
    assert sub is not None
    platforms = [sub.platform] if sub.platform else ["instagram", "tiktok"]
    tried: list[str] = []
    for platform in platforms:
        tried.append(platform)
        cid = f"{platform}:{sub.handle}"
        url = (f"https://www.instagram.com/{sub.handle}/" if platform == "instagram"
               else f"https://www.tiktok.com/@{sub.handle}" if platform == "tiktok" else sub.raw)
        ref = CandidateRef(handle=sub.handle, platform=platform, found_via=["manual"],  # type: ignore[arg-type]
                           source=make_source_ref(url=url, platform=platform, mode="mock", quote=sub.raw[:200]))  # type: ignore[arg-type]
        c = Candidate(id=cid, ref=ref)
        run.candidates[cid] = c
        await r1_basics.prepare(run, [c], provider, emit)
        if cid in run.candidates and run.candidates[cid].profile is not None:
            c = run.candidates[cid]
            c.ref = c.ref.model_copy(update={"source": c.profile.source})  # type: ignore[union-attr]
            sub.platform = platform  # type: ignore[assignment]
            sub.candidate_id = cid
            sub.status = "resolved"
            return c
        run.candidates.pop(cid, None)
    sub.status = "not_found"
    reason = not_found_reason(sub.handle, provider)
    await emit("subject.not_found", {"subject": sub.raw, "tried": tried, "reason": reason})
    await log(run, emit, tr(run, reason["cs"], reason["en"]), actor="engine")
    return None


def not_found_reason(handle: str, provider: Any) -> dict[str, str] | Any:
    """Why the subject has no profile. Offline replay and MOCK data never look anything up, so they
    must not state that the account does not exist."""
    name = str(getattr(provider, "name", "") or "")
    if getattr(provider, "read_only", False):
        return i18n(f"@{handle} v nahraných ani uložených datech není. Offline přehrávání nic nestahuje, takže jsme "
                    "neověřili, jestli takový profil existuje.",
                    f"@{handle} is not in the recorded or cached data. The offline replay fetches nothing, so we did "
                    "not check whether such a profile exists.")
    if name.startswith("mock"):
        return i18n(f"@{handle} v MOCK datech není. V MOCK režimu se nic nestahuje, takže jsme neověřili, jestli "
                    "takový profil existuje.",
                    f"@{handle} is not in the MOCK data. Mock mode fetches nothing, so we did not check whether such "
                    "a profile exists.")
    return i18n(f"Veřejný profil @{handle} jsme nenašli (nebo ho nelze zpracovat).",
                f"We found no public profile @{handle} (or it cannot be processed).")


async def run_subject(run: Run, provider: SourceProvider, emit: Emit, *, now: datetime | None = None) -> Run:
    """Subject mode (docs/subject-mode.md 4.3): resolve the named creator, run rounds 1-3 as CHECKS
    (nothing is eliminated, no score), vet it (round 4) and render the goal-conditioned report."""
    rec = recording_emit(run, emit)
    with bind_emit(rec, run.criteria.brief.lang), bind_llm_modes(run.llm_modes), _llm_usage(run):
        await emit("run.started", {"run_id": run.id})
        current: int | str = "resolve"
        try:
            cs_txt, en_txt = _subject_text(run)
            await log(run, emit, tr(run, cs_txt, en_txt), actor="engine")
            c = await _resolve_subject(run, provider, emit)
            save_run(run)
            if c is None:
                await emit("run.finished", {"run_id": run.id})
                return run
            await emit("candidate.added", {"candidate": c})
            await emit("subject.resolved", {"candidate_id": c.id, "platform": c.ref.platform, "handle": c.ref.handle})
            for r in FUNNEL_ROUNDS:
                current = r
                await emit("round.started", {"round": r})
                module = ROUND_MODULES[r]
                await module.prepare(run, [c], provider, emit)
                if c.id not in run.candidates:   # defensive: a round dropped it (minor detected later)
                    run.subject.status = "not_found"  # type: ignore[union-attr]
                    await emit("candidate.removed", {"id": c.id})
                    await emit("run.finished", {"run_id": run.id})
                    save_run(run)
                    return run
                _evaluate_candidate_round(run, c, r, now or utcnow())
                c.status = "active" if r < 3 else "finalist"
                c.elimination = None
                await emit("candidate.updated", {"candidate": c})
                _upsert_round(run, r, 1, 1)
                n_fail = sum(1 for x in c.results if x.status == "fail" and CRITERION_ROUND.get(_kind(run, x.criterion_id), 0) == r)
                await log(run, emit, tr(run, f"Kolo {r}: kontroly hotové ({n_fail} nesplněno; nic se nevyřazuje)",
                                        f"Round {r}: checks done ({n_fail} not met; nothing is eliminated)"), actor="engine")
                await emit("round.finished", {"round": r, "entered": 1, "remaining": 1})
                save_run(run)
            current = 4
            c.status = "finalist"
            await emit("round.started", {"round": 4})
            await log(run, emit, tr(run, "Kolo 4: hloubková prověrka", "Round 4: deep check"), actor="engine")
            await r4_vetting.prepare(run, [c], provider, emit)
            evaluate_round(run, 4, candidate_ids=[c.id])
            await emit("candidate.updated", {"candidate": c})
            _upsert_round(run, 4, 1, 1)
            await emit("round.finished", {"round": 4, "entered": 1, "remaining": 1})
            save_run(run)
        except Exception as e:  # never crash silently
            logger.exception("subject run %s failed in step %s", run.id, current)
            await log(run, emit, tr(run, f"Chyba v kroku {current}: {e}", f"Error in step {current}: {e}"), actor="engine")
            await emit("error", {"message": f"subject {current}: {e}"})
            save_run(run)
            return run
        await emit("run.finished", {"run_id": run.id})
    return run


def _kind(run: Run, criterion_id: str) -> str:
    return next((c.kind for c in run.criteria.criteria if c.id == criterion_id), "")


async def revet_subject(run: Run, provider: SourceProvider, emit: Emit) -> Run:
    """Subject mode: vet the subject again (fetches again; re-renders for the current goal)."""
    rec = recording_emit(run, emit)
    with bind_emit(rec, run.criteria.brief.lang), bind_llm_modes(run.llm_modes), _llm_usage(run):
        try:
            ids = [cid for cid, c in run.candidates.items() if c.profile is not None]
            await emit("round.started", {"round": 4})
            for cid in ids:
                run.candidates[cid].status = "finalist"
            await r4_vetting.prepare(run, [run.candidates[i] for i in ids], provider, emit)
            evaluate_round(run, 4, candidate_ids=ids)
            for cid in ids:
                await emit("candidate.updated", {"candidate": run.candidates[cid]})
            _upsert_round(run, 4, len(ids), len(ids))
            await emit("round.finished", {"round": 4, "entered": len(ids), "remaining": len(ids)})
            save_run(run)
        except Exception as e:
            logger.exception("re-vetting failed for run %s", run.id)
            await emit("error", {"message": f"round 4: {e}"})
            save_run(run)
            return run
        await emit("run.finished", {"run_id": run.id})
    return run


# ---------------------------------------------------------------------------------------------
# Recompute / restore / fill_missing
# ---------------------------------------------------------------------------------------------

def recompute(run: Run, criteria: CriteriaSet, *, now: datetime | None = None) -> Diff:
    """Set run.criteria = criteria, reset every candidate to active (keep a restore waiver only when
    the goal is unchanged and its criterion has the same kind and params; dropped waivers are listed
    in diff["waivers_dropped"]), re-run rounds 1..3 from stored data: no LLM, no fetch, < 2 s. On a
    goal change, vetted reports get their competitor marks, collab inferences and outreach draft
    rebuilt for the new brief (r4_vetting.refresh_for_brief).
    Missing data -> "unknown". Returns who dropped / returned vs. the previous state and why."""
    from app.compute.collabs import mark_competitors
    from app.compute.metrics import local_signals

    now = now or utcnow()
    before = _snapshot(run)
    old = run.criteria
    brief_changed = old.brief.model_dump(exclude={"lang"}) != criteria.brief.model_dump(exclude={"lang"})
    old_by_id = {c.id: c for c in old.criteria}
    new_by_id = {c.id: c for c in criteria.criteria}

    def waiver_still_applies(criterion_id: str) -> bool:
        # A waiver ("this criterion does not apply to this one") was given for one goal and one
        # criterion definition: a new goal, or a changed kind / params, makes it void.
        o, n = old_by_id.get(criterion_id), new_by_id.get(criterion_id)
        return (not brief_changed and o is not None and n is not None
                and o.kind == n.kind and o.params == n.params)

    run.criteria = criteria
    city = criteria.brief.city or criteria.discovery.city
    reached = max_round_reached(run)
    waivers_dropped: list[dict] = []
    from app.rounds.r4_vetting import refresh_for_brief, rerender

    if getattr(run, "mode", "discovery") == "subject":
        return _recompute_subject(run, now, city)

    for c in run.candidates.values():
        c.status = "active"
        c.elimination = None
        kept = []
        for r in c.results:
            if not r.waived:
                continue
            if waiver_still_applies(r.criterion_id):
                kept.append(r)
            else:
                waivers_dropped.append({"candidate_id": c.id, "handle": c.ref.handle, "criterion_id": r.criterion_id})
        c.results = kept
        if c.restored and not kept:
            c.restored = False
        if c.profile is not None and c.metrics is not None:
            c.metrics = c.metrics.model_copy(update={
                "local_signals": local_signals(c.profile, list(c.profile.latest_posts), city)})
        if c.report is not None and c.vetting_data is None:   # legacy report (old snapshot): patch it
            c.report.collab_timeline = mark_competitors(c.report.collab_timeline, criteria.brief.competitors)
            if brief_changed:
                refresh_for_brief(run, c)
    for r in range(1, min(reached, 3) + 1):
        evaluate_round(run, r, now=now)
    if reached >= 3:
        _promote_finalists(run)
    report_diffs = []
    for c in run.candidates.values():
        if c.report is not None and c.vetting_data is not None:
            d = rerender(run, c)    # goal-conditioned report for the new criteria: no fetch, no LLM
            if d is not None:
                report_diffs.append(d)
    if reached >= 3:
        evaluate_round(run, 4, now=now)
    refresh_round_counts(run)
    diff = _diff(run, before)
    if waivers_dropped:
        diff["waivers_dropped"] = waivers_dropped
    if report_diffs:
        diff["report_diffs"] = report_diffs
    return diff


def _evaluate_subject(run: Run, now: datetime) -> None:
    """Subject mode: every enabled criterion of rounds 1-3 is a CHECK; nothing is eliminated."""
    for c in run.candidates.values():
        for r in FUNNEL_ROUNDS:
            _evaluate_candidate_round(run, c, r, now)
        c.elimination = None
        c.status = "finalist"


def _recompute_subject(run: Run, now: datetime, city: str | None) -> Diff:
    from app.compute.metrics import local_signals
    from app.rounds.r4_vetting import rerender

    for c in run.candidates.values():
        c.results = []
        if c.profile is not None and c.metrics is not None:
            c.metrics = c.metrics.model_copy(update={
                "local_signals": local_signals(c.profile, list(c.profile.latest_posts), city)})
    _evaluate_subject(run, now)
    report_diffs = []
    for c in run.candidates.values():
        if c.report is not None and c.vetting_data is not None:
            d = rerender(run, c)
            if d is not None:
                report_diffs.append(d)
    evaluate_round(run, 4, now=now)
    diff = Diff(dropped=[], returned=[])
    diff["report_diffs"] = report_diffs
    return diff


def restore(run: Run, candidate_id: str, criterion_id: str, *, now: datetime | None = None) -> Diff:
    """Owner says "this criterion does not apply to this one": set waived=True on that result,
    restored=True, re-evaluate the candidate from that criterion's round onward. Returns a Diff.
    Raises KeyError for an unknown candidate or criterion."""
    now = now or utcnow()
    c = run.candidates[candidate_id]
    crit = next((cr for cr in run.criteria.criteria if cr.id == criterion_id), None)
    if crit is None:
        raise KeyError(criterion_id)
    before = _snapshot(run)
    res = next((r for r in c.results if r.criterion_id == criterion_id), None)
    if res is None:
        c.results.append(CriterionResult(criterion_id=criterion_id, status="unknown", value="", threshold="",
                                         sources=[], waived=True))
    else:
        res.waived = True
    c.restored = True
    if crit.round == 4:
        return _diff(run, before)
    if c.status == "eliminated" and c.elimination is not None and c.elimination.round < crit.round:
        return _diff(run, before)   # out in an earlier round; the waiver applies once it gets there
    _evaluate_candidate_from(run, c, crit.round, now)
    refresh_round_counts(run)
    return _diff(run, before)


async def fill_missing(run: Run, provider: SourceProvider, emit: Emit) -> Diff:
    """For active/finalist candidates lacking data for rounds they now reach (after recompute /
    restore / goal change), run the needed round prepare() and re-evaluate. Returns a Diff.
    Emits logs / sensitive.filtered / candidate.removed while fetching; like recompute and restore
    it does NOT emit ``diff`` / ``candidate.updated`` (the API publishes those once)."""
    if getattr(run, "mode", "discovery") == "subject":
        return Diff(dropped=[], returned=[])   # a subject run fetched everything it needs in run_subject
    rec = recording_emit(run, emit)
    with bind_emit(rec, run.criteria.brief.lang), bind_llm_modes(run.llm_modes), _llm_usage(run):
        reached = max_round_reached(run)
        before = _snapshot(run)
        targets = [c for c in run.candidates.values() if candidate_needs_fetch(c, reached)]
        if not targets:
            return Diff(dropped=[], returned=[])
        ids = [c.id for c in targets]
        try:
            await log(run, emit, tr(run, f"Doplňuji data pro {len(ids)} kandidátů",
                                    f"Fetching missing data for {len(ids)} candidates"), actor="engine")
            if reached >= 1:
                need = [c for c in targets if c.profile is None]
                if need:
                    before_ids = set(run.candidates)
                    await r1_basics.prepare(run, need, provider, emit)
                    for cid in sorted(before_ids - set(run.candidates)):
                        await emit("candidate.removed", {"id": cid})
            if reached >= 2:
                await r2_content.prepare(run, [c for c in targets if c.id in run.candidates], provider, emit)
            if reached >= 3:
                need = [c for c in targets if c.id in run.candidates and needs_comments(c)]
                if need:
                    await r3_audience.prepare(run, need, provider, emit)
            now = utcnow()
            for cid in ids:
                c = run.candidates.get(cid)
                if c is not None:
                    _evaluate_candidate_from(run, c, 1, now)
            refresh_round_counts(run)
            diff = _diff(run, before)
            save_run(run)
            return diff
        except Exception as e:
            logger.exception("fill_missing failed for run %s", run.id)
            await emit("error", {"message": f"fill_missing: {e}"})
            return _diff(run, before)


# ---------------------------------------------------------------------------------------------
# Compare (no score, no default ranking)
# ---------------------------------------------------------------------------------------------

def criterion_sort_value(criterion: Criterion, candidate: Candidate) -> float | None:
    """Numeric value behind a criterion for sorting (followers, topic share, engagement_rate, ...);
    None if unavailable or the kind has no numeric value."""
    from app.compute import language as lang_mod
    from app.compute.collabs import undisclosed_posts
    from app.compute.metrics import local_signals

    p, m = candidate.profile, candidate.metrics
    k = criterion.kind
    params = criterion.params or {}
    if k == "followers_range":
        return float(p.followers) if p and p.followers is not None else None
    if k == "active_recently":
        return m.last_post_at.timestamp() if m and m.last_post_at else None
    if k == "language_cs":
        if not p:
            return None
        return lang_mod.language_share([x.caption for x in p.latest_posts], "cs", min_texts=3)
    if k == "topic_share":
        if not m or not m.topic_counts:
            return None
        total = sum(n for t, n in m.topic_counts.items() if t != "unclassified")
        topics = params.get("topics") or []
        return sum(m.topic_counts.get(t, 0) for t in topics) / total if total else None
    if k == "formats":
        if not m or not m.posts_analyzed:
            return None
        fmts = params.get("formats") or []
        return sum(n for f, n in m.formats.items() if f in fmts) / m.posts_analyzed
    if k == "post_frequency":
        return m.posts_per_week if m else None
    if k == "max_commercial_share":
        return m.commercial_share if m else None
    if k == "min_engagement":
        return m.engagement_rate if m else None
    if k == "cs_comment_share":
        return m.cs_comment_share if m else None
    if k == "max_generic_comments":
        return m.generic_comment_share if m else None
    if k == "local_signal":
        if not p:
            return None
        city = params.get("city")
        if city:
            return float(len(local_signals(p, list(p.latest_posts), city)))
        return float(len(m.local_signals)) if m else None
    if k == "no_competitor_collab":
        if candidate.report is None:
            return None
        return float(sum(1 for e in candidate.report.collab_timeline if e.is_competitor))
    if k == "discloses_ads":
        if candidate.report is None:
            return None
        return float(len(undisclosed_posts(candidate.report.collab_timeline)))
    return None


def compare(run: Run, sort_criterion_id: str | None = None) -> dict:
    """Finalists side by side. No overall score, no default ranking.
    Returns {"sort": criterion_id | None,
             "criteria": [Criterion],
             "rows": [{"candidate_id", "handle", "platform", "status",
                       "results": {criterion_id: CriterionResult},
                       "sort_value": float | None}]}
    Rows keep run order unless sort_criterion_id is given (desc by sort_value, None last).
    An unknown sort_criterion_id is ignored (sort None)."""
    criteria = [c for c in run.criteria.criteria if c.enabled]
    by_id = {c.id: c for c in run.criteria.criteria}
    sort_crit = by_id.get(sort_criterion_id) if sort_criterion_id else None
    rows = []
    for cid, c in run.candidates.items():
        if c.status != "finalist":
            continue
        rows.append({
            "candidate_id": cid,
            "handle": c.ref.handle,
            "platform": c.ref.platform,
            "status": c.status,
            "results": {r.criterion_id: r for r in c.results},
            "sort_value": criterion_sort_value(sort_crit, c) if sort_crit else None,
        })
    if sort_crit is not None:
        with_v = [r for r in rows if r["sort_value"] is not None]
        without = [r for r in rows if r["sort_value"] is None]
        with_v.sort(key=lambda r: r["sort_value"], reverse=True)
        rows = with_v + without
    return {"sort": sort_crit.id if sort_crit else None, "criteria": criteria, "rows": rows}
