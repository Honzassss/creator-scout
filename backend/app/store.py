"""Run state: in-memory dict + JSON snapshot in data/runs/<run_id>.json (atomic write: tmp + rename).

Never stores what the hard lines forbid: minors are removed before save, commenter identities never
exist in the models, sensitive items are filtered before they reach a Candidate. Paths come from
get_settings() at call time (tests use a temp DATA_DIR).

The in-memory Run returned by ``get`` is THE live object: the engine mutates it and calls ``save``
after each round; the API layer saves again when a background task ends. Snapshots on disk are
loaded lazily by ``get`` / ``list_ids`` and eagerly by ``load_all`` (app startup), so runs survive
a server restart.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
from pathlib import Path

from app.config import get_settings
from app.models import CriteriaSet, Run

log = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_run_id() -> str:
    """Short unique id, e.g. "r_" + 10 hex chars."""
    return "r_" + secrets.token_hex(5)


def valid_run_id(run_id: str) -> bool:
    """Run ids become file names: allow only [A-Za-z0-9_-] (no path traversal)."""
    return isinstance(run_id, str) and bool(_RUN_ID_RE.match(run_id))


def drop_minors(run: Run) -> int:
    """Hard line: remove every candidate whose profile says is_under_18 (nothing kept). Returns count."""
    minors = [cid for cid, c in run.candidates.items() if c.profile is not None and c.profile.is_under_18]
    for cid in minors:
        run.candidates.pop(cid, None)
    return len(minors)


class RunStore:
    def __init__(self, runs_dir: Path | None = None) -> None:
        """runs_dir default: get_settings().runs_dir (created on first save)."""
        self.runs_dir = Path(runs_dir) if runs_dir is not None else get_settings().runs_dir
        self._runs: dict[str, Run] = {}

    # -- paths --------------------------------------------------------------------------------

    def path_for(self, run_id: str) -> Path:
        if not valid_run_id(run_id):
            raise ValueError(f"invalid run id {run_id!r}")
        return self.runs_dir / f"{run_id}.json"

    # -- CRUD ---------------------------------------------------------------------------------

    def create(self, criteria: CriteriaSet, run_id: str | None = None) -> Run:
        """New Run(candidates={}, rounds=[], log=[], mode_summary={"live": 0, "cache": 0, "mock": 0}); saved."""
        rid = run_id or new_run_id()
        while run_id is None and (rid in self._runs or self.path_for(rid).exists()):
            rid = new_run_id()
        run = Run(
            id=rid,
            criteria=criteria.model_copy(deep=True),
            candidates={},
            rounds=[],
            log=[],
            mode_summary={"live": 0, "cache": 0, "mock": 0},
        )
        self.save(run)
        return run

    def get(self, run_id: str) -> Run | None:
        """Memory first, then disk; None if unknown (or the id is not a valid file name)."""
        if not valid_run_id(run_id):
            return None
        run = self._runs.get(run_id)
        if run is not None:
            return run
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        run = self._read(path)
        if run is not None:
            self._runs[run.id] = run
        return run

    def save(self, run: Run) -> None:
        """Keep ``run`` as the in-memory instance and write the JSON snapshot atomically."""
        path = self.path_for(run.id)
        drop_minors(run)
        self._runs[run.id] = run
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(run.model_dump_json(), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def list_ids(self) -> list[str]:
        ids = set(self._runs)
        if self.runs_dir.is_dir():
            ids.update(p.stem for p in self.runs_dir.glob("*.json") if valid_run_id(p.stem))
        return sorted(ids)

    def delete(self, run_id: str) -> bool:
        if not valid_run_id(run_id):
            return False
        existed = self._runs.pop(run_id, None) is not None
        path = self.path_for(run_id)
        if path.exists():
            path.unlink(missing_ok=True)
            existed = True
        return existed

    def clear(self) -> None:
        """Drop all runs from memory and disk."""
        self._runs.clear()
        if self.runs_dir.is_dir():
            shutil.rmtree(self.runs_dir, ignore_errors=True)

    def load_all(self) -> int:
        """Load every snapshot on disk into memory (app startup). Unreadable files are skipped."""
        n = 0
        if not self.runs_dir.is_dir():
            return 0
        for path in sorted(self.runs_dir.glob("*.json")):
            if not valid_run_id(path.stem) or path.stem in self._runs:
                continue
            run = self._read(path)
            if run is not None:
                self._runs[run.id] = run
                n += 1
        return n

    def in_memory(self) -> list[Run]:
        return list(self._runs.values())

    @staticmethod
    def _read(path: Path) -> Run | None:
        try:
            run = Run.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # corrupt / old-schema snapshot: skip, never crash the API
            log.warning("cannot load run snapshot %s: %s", path.name, exc)
            return None
        drop_minors(run)
        return run


_store: RunStore | None = None


def get_store() -> RunStore:
    """Process-wide singleton (re-created if get_settings().runs_dir changed, e.g. in tests)."""
    global _store
    runs_dir = get_settings().runs_dir
    if _store is None or _store.runs_dir != runs_dir:
        _store = RunStore(runs_dir)
    return _store


def minimize_eliminated(run: Run) -> int:
    """Data minimization after the run: for eliminated candidates keep only ref (handle, found_via),
    elimination and results; drop profile posts/metrics. Returns how many were minimized.
    (Do not call during an interactive session: recompute/restore need the data.)"""
    n = 0
    for cand in run.candidates.values():
        if cand.status != "eliminated":
            continue
        if cand.profile is None and cand.metrics is None and cand.report is None and cand.vetting_data is None:
            continue
        cand.profile = None
        cand.metrics = None
        cand.report = None
        cand.vetting_data = None   # raw round-4 inputs (posts, news, cross-platform profiles)
        n += 1
    return n


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for p in path.rglob("*") if p.is_file())


def _wipe(path: Path) -> int:
    n = _count_files(path)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)
    return n


def purge_all() -> dict[str, int]:
    """POST /api/purge: delete data/cache, data/runs, data/llm and in-memory runs + event history.
    Returns counts per area, e.g. {"cache": 12, "runs": 2, "llm": 30}."""
    from app.events import get_bus

    s = get_settings()
    store = get_store()
    run_ids = set(store.list_ids())
    counts = {
        "cache": _wipe(s.cache_dir),
        "runs": len(run_ids),
        "llm": _wipe(s.llm_dir),
    }
    store.clear()
    _wipe(s.runs_dir)
    get_bus().clear()
    return counts
