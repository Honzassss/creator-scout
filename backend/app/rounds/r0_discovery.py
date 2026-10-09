"""Round 0: discovery. provider.discover() -> dedupe by (platform, handle), merge found_via, interleave
the discovery paths round-robin (``round_robin``), cap at discovery.limit. Adds Candidate(id=candidate_id(platform, handle), ref=...) to run.candidates and emits
candidate.added; logs "Instagram: 48 účtů" style lines with actor + mode."""

from __future__ import annotations

from collections import Counter, defaultdict

from app.events import Emit
from app.llm import sensitive
from app.models import Candidate, CandidateRef, Run, candidate_id
from app.rounds.common import actor_of, count_modes, cs_plural, describe_modes, llm_actor, log, tr
from app.sources.base import SourceProvider

ROUND = 0

_PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube"}


def _merge_via(a: list[str], b: list[str]) -> list[str]:
    out = list(a)
    for v in b:
        if v not in out:
            out.append(v)
    return out


def dedupe(refs: list[CandidateRef], limit: int) -> list[CandidateRef]:
    """Dedupe by (platform, handle) keeping first-seen order; merge found_via (unique, ordered)."""
    by_key: dict[tuple[str, str], CandidateRef] = {}
    for ref in refs:
        key = (ref.platform, ref.handle)
        if key in by_key:
            prev = by_key[key]
            by_key[key] = prev.model_copy(update={"found_via": _merge_via(prev.found_via, ref.found_via)})
        else:
            by_key[key] = ref.model_copy(update={"found_via": _merge_via([], ref.found_via)})
    out = list(by_key.values())
    return out[: max(0, limit)] if limit is not None else out


def path_kind(found_via: str) -> str:
    """"hashtag:brnofood" -> "hashtag"; "manual" -> "manual"."""
    return found_via.partition(":")[0] or "other"


def _interleave(lists: list[list[CandidateRef]]) -> list[CandidateRef]:
    out: list[CandidateRef] = []
    for i in range(max((len(x) for x in lists), default=0)):
        out.extend(x[i] for x in lists if i < len(x))
    return out


def round_robin(refs: list[CandidateRef]) -> list[CandidateRef]:
    """Order refs so a cap at the discovery limit keeps every path represented.

    A provider may list one path first (the Apify provider puts all search hits before hashtag and
    place authors), and a plain cut at the limit then starves the later paths. Refs are grouped by
    (path kind, platform) of their first ``found_via`` entry, e.g. ("hashtag", "instagram"), and within
    a group by the exact path ("hashtag:brnofood"). Groups take turns, and inside a group the exact
    paths take turns; the provider's order is kept within one path. found_via is not changed."""
    groups: dict[tuple[str, str], dict[str, list[CandidateRef]]] = {}
    for r in refs:
        via = r.found_via[0] if r.found_via else "other"
        groups.setdefault((path_kind(via), r.platform), {}).setdefault(via, []).append(r)
    return _interleave([_interleave(list(paths.values())) for paths in groups.values()])


_PATH_NAMES = {"search": ("hledání", "search"), "hashtag": ("hashtagy", "hashtags"), "place": ("místa", "places"),
               "related": ("podobné účty", "related accounts"), "manual": ("ručně", "manual")}


async def discover(run: Run, provider: SourceProvider, emit: Emit) -> list[Candidate]:
    """Run discovery for run.criteria.discovery; add new candidates to run.candidates; return them."""
    added, _ = await discover_with_stats(run, provider, emit)
    return added


async def discover_with_stats(run: Run, provider: SourceProvider, emit: Emit) -> tuple[list[Candidate], int]:
    """discover() plus the raw hit count before dedupe (round 0 "entered")."""
    q = run.criteria.discovery
    refs = await provider.discover(q)
    refs = [r for r in refs if r.platform in (q.platforms or [r.platform])]
    run_raw = len(refs)
    room = max(0, q.limit - len(run.candidates))
    deduped = round_robin(dedupe(refs, len(refs)))
    # Sensitive filter on any caption snippet the discovery hit carries, before anything is stored.
    # The snippet is only blanked, not counted: it is usually one of the candidate's posts, which
    # round 1 filters and counts again (counting here too would double-count the same post).
    quoted = [i for i, r in enumerate(deduped) if r.source.quote]
    blanked: set[int] = set()
    if quoted:
        kept, _ = await sensitive.filter_texts([deduped[i].source.quote or "" for i in quoted])
        for i, k in zip(quoted, kept):
            if not k:
                r = deduped[i]
                deduped[i] = r.model_copy(update={"source": r.source.model_copy(update={"quote": None})})
                blanked.add(i)

    added: list[Candidate] = []
    for idx, ref in enumerate(deduped):
        cid = candidate_id(ref.platform, ref.handle)
        existing = run.candidates.get(cid)
        if existing is not None:
            existing.ref = existing.ref.model_copy(update={"found_via": _merge_via(existing.ref.found_via, ref.found_via)})
            continue
        if len(added) >= room:
            continue
        cand = Candidate(id=cid, ref=ref)
        run.candidates[cid] = cand
        added.append(cand)

    by_platform: dict[str, list[CandidateRef]] = defaultdict(list)
    for c in added:
        by_platform[c.ref.platform].append(c.ref)
    count_modes(run, [c.ref for c in added])
    for platform, prefs in by_platform.items():
        mode, suffix = describe_modes(Counter(r.source.mode for r in prefs))
        n = len(prefs)
        name = _PLATFORM_NAMES.get(platform, platform)
        await log(run, emit,
                  tr(run, f"{name}: {n} {cs_plural(n, 'účet', 'účty', 'účtů')}{suffix}",
                     f"{name}: {n} {'account' if n == 1 else 'accounts'}{suffix}"),
                  actor=actor_of(prefs, provider.name), mode=mode)
    if run_raw > len(deduped) or len(deduped) > len(added):
        await log(run, emit, tr(
            run,
            f"Hledání: {run_raw} nálezů, {len(added)} unikátních kandidátů (limit {q.limit}).",
            f"Discovery: {run_raw} hits, {len(added)} unique candidates (limit {q.limit}).",
        ), actor="engine")
    if len(deduped) > len(added) and added:
        # The cap cut some hits: say how the kept candidates split across the discovery paths.
        per_path = Counter(path_kind(c.ref.found_via[0]) if c.ref.found_via else "other" for c in added)
        names = [(_PATH_NAMES.get(k, (k, k)), n) for k, n in per_path.most_common()]
        await log(run, emit, tr(
            run,
            "Cesty hledání se střídají: " + ", ".join(f"{nm[0]} {n}" for nm, n in names) + ".",
            "Discovery paths take turns: " + ", ".join(f"{nm[1]} {n}" for nm, n in names) + ".",
        ), actor="engine")
    if blanked:
        await log(run, emit, tr(
            run,
            f"Citlivý filtr: {len(blanked)} {cs_plural(len(blanked), 'úryvek', 'úryvky', 'úryvků')} z hledání skryto (počítá se až u postu v kole 1).",
            f"Sensitive filter: {len(blanked)} discovery {'snippet' if len(blanked) == 1 else 'snippets'} hidden (counted with the post in round 1).",
        ), actor=llm_actor(run, "sensitive"))
    for c in added:
        await emit("candidate.added", {"candidate": c})
    return added, run_raw
