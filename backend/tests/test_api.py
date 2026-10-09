"""API, run store and event bus tests (httpx ASGI transport; temp DATA_DIR from conftest).

Two layers:
- Tests marked "fake engine" swap ``app.main._engine`` / ``_provider`` for a tiny deterministic fake,
  so the API plumbing (tasks, SSE, diff publishing, persistence, chat tools) is tested on its own.
- Tests marked "real" drive the real engine + MockProvider with the bakery brief (fixtures/ must
  exist; an unimplemented module is a failure).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import main, store as store_mod
from app.config import get_settings
from app.events import EventBus, format_sse, get_bus
from app.models import (
    Brief,
    Candidate,
    CandidateRef,
    CriteriaSet,
    CriterionResult,
    Elimination,
    Profile,
    Report,
    candidate_id,
    i18n,
    make_source_ref,
    utcnow,
)
from app.presets import get_preset
from app.store import RunStore, get_store, minimize_eliminated, new_run_id, purge_all

FORBIDDEN_KEYS = {"score", "overall_score", "rank", "ranking", "best", "risk", "risk_level",
                  "age", "gender", "ethnicity", "religion", "politics"}


# =============================================================================================
# helpers
# =============================================================================================


def parse_sse(text: str) -> list[tuple[str | None, str, dict]]:
    """[(id, event, data)] from an SSE body; comments / retry lines ignored."""
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev_id, event, data = None, None, []
        for line in block.split("\n"):
            if line.startswith("id: "):
                ev_id = line[4:]
            elif line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data.append(line[6:])
        if event:
            out.append((ev_id, event, json.loads("\n".join(data)) if data else {}))
    return out


def ref(url: str):
    return make_source_ref(url=url, platform="instagram", mode="mock", actor="mock/test")


def make_candidate(handle: str, status: str = "active", *, minor: bool = False, eliminated_by: str | None = None,
                   round_no: int = 2) -> Candidate:
    url = f"https://instagram.example/{handle}"
    cand = Candidate(
        id=candidate_id("instagram", handle),
        ref=CandidateRef(handle=handle, platform="instagram", found_via=["hashtag:brnofood"], source=ref(url)),
        profile=Profile(handle=handle, platform="instagram", url=url, followers=12000, is_under_18=minor or None,
                        source=ref(url)),
        status=status,
    )
    if eliminated_by:
        cand.status = "eliminated"
        cand.elimination = Elimination(round=round_no, criterion_id=eliminated_by,
                                       reason=i18n("jen 2 z 24 postů o jídle", "only 2 of 24 posts about food"),
                                       sources=[ref(url + "/p/1")])
        cand.results = [CriterionResult(criterion_id=eliminated_by, status="fail", value="2/24", threshold=">= 40 %",
                                        sources=[ref(url + "/p/1")])]
    return cand


def empty_report(cid: str) -> Report:
    return Report(candidate_id=cid, findings=[], claims=[], collab_timeline=[], news=[], identity=[], questions=[],
                  outreach_draft=None, not_checked=[], skeptic_notes=[], sensitive_filtered=0)


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, f"{path}.{k}"
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


def bakery_criteria() -> tuple[CriteriaSet, str]:
    """Bakery criteria from fixtures/briefs.json when present (a few plausible layouts), else preset."""
    path = get_settings().fixtures_dir / "briefs.json"
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        cand = None
        if isinstance(raw, dict):
            cand = raw.get("bakery") or raw.get("pekarna")
        elif isinstance(raw, list):
            cand = next((x for x in raw if isinstance(x, dict) and x.get("name") in ("bakery", "pekarna")), None)
        for item in (cand, (cand or {}).get("criteria") if isinstance(cand, dict) else None,
                     (cand or {}).get("criteria_set") if isinstance(cand, dict) else None):
            if isinstance(item, dict):
                try:
                    return CriteriaSet.model_validate(item), "fixtures/briefs.json"
                except Exception:
                    continue
    return get_preset("bakery"), "presets.bakery"


def fixtures_present() -> bool:
    d = get_settings().fixtures_dir
    return d.is_dir() and any(d.glob("*.json"))


class FakeEngine:
    """Deterministic stand-in for app.rounds.engine (same signatures)."""

    def __init__(self) -> None:
        self.gate: asyncio.Event | None = None
        self.fail: BaseException | None = None
        self.filled = 0

    async def run_funnel(self, run, provider, emit, *, up_to=3, now=None):
        await emit("run.started", {"run_id": run.id})
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        await emit("log", {"text": "Instagram: 4 účty", "actor": "mock/discover", "mode": "mock",
                           "ts": utcnow().isoformat()})
        await emit("round.started", {"round": 0})
        cands = [make_candidate("anna_pece", "finalist"), make_candidate("bob_fit", "finalist"),
                 make_candidate("cyril_travel", eliminated_by="topic_share"),
                 make_candidate("dana_minor", "finalist", minor=True)]
        for c in cands:
            run.candidates[c.id] = c
            await emit("candidate.added", {"candidate": c})
            if c.elimination is not None:
                await emit("candidate.eliminated", {"id": c.id, "elimination": c.elimination})
        run.rounds = [{"round": 0, "entered": 4, "remaining": 4}, {"round": 1, "entered": 4, "remaining": 3},
                      {"round": 2, "entered": 3, "remaining": 2}, {"round": 3, "entered": 2, "remaining": 2}]
        run.mode_summary = {"live": 0, "cache": 0, "mock": 4}
        await emit("round.finished", {"round": 3, "entered": 2, "remaining": 2})
        await emit("run.finished", {"run_id": run.id})
        return run

    async def run_vetting(self, run, candidate_ids, provider, emit):
        for cid in candidate_ids:
            await emit("vetting.progress", {"candidate_id": cid, "step": "posts"})
            run.candidates[cid].report = empty_report(cid)
            await emit("report.ready", {"candidate_id": cid})
        return run

    def _entry(self, c, before, after, elim, needs_fetch=False):
        return {"candidate_id": c.id, "handle": c.ref.handle, "platform": c.ref.platform, "before": before,
                "after": after, "elimination": elim.model_dump(mode="json") if elim else None,
                "needs_fetch": needs_fetch}

    def recompute(self, run, criteria, *, now=None):
        run.criteria = criteria
        enabled = {c.id: c for c in criteria.criteria if c.enabled}
        dropped, returned = [], []
        for c in run.candidates.values():
            if c.status == "eliminated" and c.elimination and c.elimination.criterion_id not in enabled:
                prev = c.elimination
                c.status, c.elimination = "finalist", None
                returned.append(self._entry(c, "eliminated", "finalist", prev))
            elif c.status == "finalist" and "local_signal" in enabled and \
                    enabled["local_signal"].params.get("min_count", 1) > 50:
                c.status = "eliminated"
                c.elimination = Elimination(round=3, criterion_id="local_signal", reason=i18n("málo", "few"),
                                            sources=[])
                dropped.append(self._entry(c, "finalist", "eliminated", c.elimination))
        return {"dropped": dropped, "returned": returned}

    def restore(self, run, cid, criterion_id, *, now=None):
        c = run.candidates[cid]
        prev = c.elimination
        for r in c.results:
            if r.criterion_id == criterion_id:
                r.waived = True
        c.restored, c.status, c.elimination = True, "finalist", None
        return {"dropped": [], "returned": [self._entry(c, "eliminated", "finalist", prev, needs_fetch=True)]}

    async def fill_missing(self, run, provider, emit):
        self.filled += 1
        return {"dropped": [], "returned": []}

    def compare(self, run, sort_criterion_id=None):
        rows = [{"candidate_id": c.id, "handle": c.ref.handle, "platform": c.ref.platform, "status": c.status,
                 "results": {}, "sort_value": c.profile.followers if c.profile else None}
                for c in run.candidates.values() if c.status == "finalist"]
        return {"sort": sort_criterion_id, "criteria": run.criteria.criteria, "rows": rows}


# =============================================================================================
# fixtures
# =============================================================================================


@pytest.fixture
async def client():
    await main.reset_runtime_state()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as c:
        yield c
    await main.reset_runtime_state()


@pytest.fixture
def fake_engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(main, "_engine", lambda: fake)
    monkeypatch.setattr(main, "_provider", lambda: object())
    return fake


async def start_fake_run(client) -> str:
    r = await client.post("/api/runs", json={"preset": "bakery"})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    await main.wait_idle(run_id)
    return run_id


# =============================================================================================
# basics
# =============================================================================================


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    from app.sources.factory import apify_available

    body = r.json()
    expected = {"source_mode": "mock", "llm_mode": "fallback", "llm_provider": None, "llm_model": None,
                "llm_models_used": {}, "apify_configured": False,
                "apify_provider_implemented": apify_available()}
    assert {k: body.get(k) for k in expected} == expected
    # LLM budget snapshot (llm.budget.usage_snapshot) rides along
    assert body["llm_requests_used"] == 0 and "llm_budget" in body and "llm_budget_left" in body


async def test_cors_allows_vite_dev_server(client):
    r = await client.options("/api/health", headers={"Origin": "http://127.0.0.1:5173",
                                                     "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    r = await client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_no_endpoint_sends_outreach():
    """Hard line: outreach is a draft only; no route can send anything."""
    paths = [getattr(r, "path", "") for r in main.app.routes]
    assert not [p for p in paths if any(w in p.lower() for w in ("send", "outreach", "email", "message", "dm"))]


async def test_presets_endpoint(client):
    r = await client.get("/api/presets")
    assert r.status_code == 200
    data = r.json()
    assert CriteriaSet.model_validate(data["bakery"]).brief.business_type == "pekárna"
    assert CriteriaSet.model_validate(data["fitness"])


async def test_unknown_run_is_404(client):
    for method, url in [("GET", "/api/runs/r_nope"), ("GET", "/api/runs/r_nope/events"),
                        ("GET", "/api/runs/r_nope/compare"), ("POST", "/api/runs/r_nope/vet"),
                        ("GET", "/api/runs/..%2F..%2Fetc"), ("GET", "/api/runs/r_nope/status")]:
        r = await client.request(method, url, json={} if method == "POST" else None)
        assert r.status_code == 404, (url, r.status_code, r.text)


async def test_create_run_requires_criteria_or_preset(client):
    r = await client.post("/api/runs", json={})
    assert r.status_code == 422
    cs = get_preset("bakery").model_dump(mode="json")
    cs["criteria"].append(dict(cs["criteria"][0]))  # duplicate id
    r = await client.post("/api/runs", json={"criteria": cs})
    assert r.status_code == 422


# =============================================================================================
# event bus + SSE
# =============================================================================================


def test_format_sse_single_line_json():
    msg = format_sse("log", {"text": "řádek 1\nřádek 2", "when": utcnow()}, id=7)
    lines = msg.split("\n")
    assert lines[0] == "id: 7" and lines[1] == "event: log" and lines[2].startswith("data: {")
    assert msg.endswith("\n\n") and msg.count("\n") == 4
    assert json.loads(lines[2][6:])["text"] == "řádek 1\nřádek 2"


async def test_bus_replay_then_live_then_close():
    bus = EventBus()
    await bus.publish("r1", "run.started", {"run_id": "r1"})
    await bus.publish("r1", "candidate.added", {"candidate": make_candidate("anna")})
    bus.open("r1")
    got: list[str] = []

    async def consume():
        async for ev, data in bus.subscribe("r1"):
            got.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await bus.publish("r1", "round.finished", {"round": 1, "entered": 1, "remaining": 1})
    await bus.publish("r1", "run.finished", {"run_id": "r1"})
    bus.close("r1")
    await asyncio.wait_for(task, 2)
    assert got == ["run.started", "candidate.added", "round.finished", "run.finished"]
    # pydantic models were converted to JSON-able data at publish time
    assert isinstance(bus.history("r1")[1][1]["candidate"], dict)
    assert bus.subscriber_count("r1") == 0


async def test_bus_follow_survives_close_and_clear_ends_it():
    bus = EventBus()
    got: list[tuple[int, str]] = []

    async def consume():
        async for item in bus.stream("r2", follow=True, heartbeat=0.01):
            if item is not None:
                got.append((item[0], item[1]))

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.03)  # heartbeats while idle, nothing yielded to got
    await bus.publish("r2", "run.finished", {})
    bus.close("r2")
    await bus.publish("r2", "diff", {"dropped": [], "returned": []})
    await asyncio.sleep(0.01)
    assert not task.done()
    bus.clear("r2")
    await asyncio.wait_for(task, 2)
    assert got == [(1, "run.finished"), (2, "diff")]
    assert bus.history("r2") == []


async def test_bus_heartbeat_and_resume():
    bus = EventBus()
    for i in range(5):
        await bus.publish("r3", "log", {"text": str(i)})
    items = [x async for x in bus.stream("r3", after=3)]
    assert [(i, d["text"]) for i, _, d in items] == [(4, "3"), (5, "4")]
    bus.open("r3")
    beats = []
    async for x in bus.stream("r3", replay=False, heartbeat=0.01):
        beats.append(x)
        if len(beats) == 2:
            break
    assert beats == [None, None]


async def test_sse_endpoint_replays_and_resumes(client):
    run = get_store().create(get_preset("bakery"))
    bus = get_bus()
    await bus.publish(run.id, "run.started", {"run_id": run.id})
    await bus.publish(run.id, "candidate.added", {"candidate": make_candidate("anna")})
    await bus.publish(run.id, "run.finished", {"run_id": run.id})
    r = await client.get(f"/api/runs/{run.id}/events", params={"follow": "false"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.startswith("retry: ")
    evs = parse_sse(r.text)
    assert [(i, e) for i, e, _ in evs] == [("1", "run.started"), ("2", "candidate.added"), ("3", "run.finished")]
    assert evs[1][2]["candidate"]["ref"]["handle"] == "anna"
    r = await client.get(f"/api/runs/{run.id}/events", params={"follow": "false"}, headers={"Last-Event-ID": "2"})
    assert [e for _, e, _ in parse_sse(r.text)] == ["run.finished"]


async def test_sse_after_restart_is_synthesized_from_snapshot(client):
    run = get_store().create(get_preset("bakery"))
    run.candidates = {c.id: c for c in [make_candidate("anna", "finalist"),
                                        make_candidate("cyril", eliminated_by="topic_share")]}
    run.rounds = [{"round": 1, "entered": 2, "remaining": 1}]
    run.log = [{"ts": utcnow().isoformat(), "text": "Instagram: 2 účty", "actor": "mock/discover", "mode": "mock"}]
    get_store().save(run)
    # simulate a restart: fresh store (loads from disk), empty bus
    store_mod._store = None
    get_bus().clear()
    assert get_store().get(run.id) is not None
    r = await client.get(f"/api/runs/{run.id}/events", params={"follow": "false"})
    names = [e for _, e, _ in parse_sse(r.text)]
    assert names[0] == "run.started" and names[-1] == "run.finished"
    assert names.count("candidate.added") == 2 and "candidate.eliminated" in names and "log" in names


# =============================================================================================
# run store
# =============================================================================================


def test_store_roundtrip_restart_minors_and_ids(tmp_path):
    runs_dir = tmp_path / "runs"
    s1 = RunStore(runs_dir)
    run = s1.create(get_preset("bakery"))
    assert run.id.startswith("r_") and run.mode_summary == {"live": 0, "cache": 0, "mock": 0}
    run.candidates = {c.id: c for c in [make_candidate("anna"), make_candidate("kid", minor=True)]}
    s1.save(run)
    assert "instagram:kid" not in run.candidates  # hard line: minors dropped before storage
    assert "kid" not in (runs_dir / f"{run.id}.json").read_text()
    assert not list(runs_dir.glob("*.tmp")) and not list(runs_dir.glob(".*"))
    s2 = RunStore(runs_dir)  # "restart"
    assert s2.list_ids() == [run.id]
    assert s2.load_all() == 1
    again = s2.get(run.id)
    assert again is not None and list(again.candidates) == ["instagram:anna"]
    assert again.model_dump() == run.model_dump()
    assert s2.get("../../etc/passwd") is None and s2.get("nope") is None
    assert s2.delete(run.id) and s2.get(run.id) is None and not s2.delete(run.id)
    assert new_run_id() != new_run_id()


def test_store_uses_settings_data_dir():
    s = get_store()
    assert s.runs_dir == get_settings().runs_dir
    assert str(s.runs_dir).startswith(str(get_settings().data_dir))
    assert "creator-scout/data" not in str(s.runs_dir)  # never the real data dir in tests


def test_minimize_eliminated():
    run = get_store().create(get_preset("bakery"))
    run.candidates = {c.id: c for c in [make_candidate("anna", "finalist"),
                                        make_candidate("cyril", eliminated_by="topic_share")]}
    assert minimize_eliminated(run) == 1
    cyril = run.candidates["instagram:cyril"]
    assert cyril.profile is None and cyril.metrics is None and cyril.elimination is not None and cyril.results
    assert run.candidates["instagram:anna"].profile is not None
    assert minimize_eliminated(run) == 0


# =============================================================================================
# purge
# =============================================================================================


async def test_purge_deletes_cache_runs_llm_and_memory(client):
    s = get_settings()
    for d, n in ((s.cache_dir, 3), (s.llm_dir, 2)):
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (d / f"x{i}.json").write_text("{}")
    run = get_store().create(get_preset("bakery"))
    await get_bus().publish(run.id, "run.started", {"run_id": run.id})
    assert (s.runs_dir / f"{run.id}.json").exists()
    r = await client.post("/api/purge")
    assert r.status_code == 200
    assert r.json()["deleted"] == {"cache": 3, "runs": 1, "llm": 2}
    assert not s.cache_dir.exists() and not s.llm_dir.exists() and not s.runs_dir.exists()
    assert get_store().list_ids() == [] and get_bus().history(run.id) == []
    assert (await client.get(f"/api/runs/{run.id}")).status_code == 404
    assert purge_all() == {"cache": 0, "runs": 0, "llm": 0}


# =============================================================================================
# fake engine: API plumbing
# =============================================================================================


async def test_create_run_persists_and_streams(client, fake_engine):
    run_id = await start_fake_run(client)
    r = await client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert set(data["candidates"]) == {"instagram:anna_pece", "instagram:bob_fit", "instagram:cyril_travel"}
    assert data["log"] and data["log"][0]["text"] == "Instagram: 4 účty"  # log events mirrored into run.log
    path = get_settings().runs_dir / f"{run_id}.json"
    assert path.exists() and "dana_minor" not in path.read_text()
    evs = parse_sse((await client.get(f"/api/runs/{run_id}/events", params={"follow": "false"})).text)
    names = [e for _, e, _ in evs]
    assert names[0] == "run.started" and names[-1] == "run.finished"
    assert [i for i, _, _ in evs] == [str(n) for n in range(1, len(evs) + 1)]
    st = (await client.get(f"/api/runs/{run_id}/status")).json()
    assert st["busy"] is False and st["error"] is None and st["counts"] == {"finalist": 2, "eliminated": 1}
    listed = (await client.get("/api/runs")).json()
    assert [x["run_id"] for x in listed] == [run_id]


async def test_task_error_becomes_error_event(client, fake_engine):
    fake_engine.fail = RuntimeError("actor exploded")
    run_id = await start_fake_run(client)
    hist = get_bus().history(run_id)
    assert hist[-1][0] == "error" and "actor exploded" in hist[-1][1]["message"]
    assert (await client.get(f"/api/runs/{run_id}/status")).json()["error"]
    fake_engine.fail = NotImplementedError()
    r = await client.post("/api/runs", json={"preset": "bakery"})
    rid = r.json()["run_id"]
    await main.wait_idle(rid)
    assert "not implemented" in get_bus().history(rid)[-1][1]["message"]


async def test_busy_run_rejects_mutations_and_follow_false_waits(client, fake_engine):
    fake_engine.gate = asyncio.Event()
    r = await client.post("/api/runs", json={"preset": "bakery"})
    run_id = r.json()["run_id"]
    await asyncio.sleep(0)
    crit = get_preset("bakery").model_dump(mode="json")
    assert (await client.post(f"/api/runs/{run_id}/criteria", json={"criteria": crit})).status_code == 409
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})).status_code == 409
    sse = asyncio.create_task(client.get(f"/api/runs/{run_id}/events", params={"follow": "false"}))
    await asyncio.sleep(0.05)
    assert not sse.done()  # stream stays open while the run works
    fake_engine.gate.set()
    resp = await asyncio.wait_for(sse, 5)
    assert [e for _, e, _ in parse_sse(resp.text)][-1] == "run.finished"


async def test_criteria_recompute_returns_and_publishes_diff(client, fake_engine):
    run_id = await start_fake_run(client)
    n_before = len(get_bus().history(run_id))
    cs = get_preset("bakery")
    for c in cs.criteria:
        if c.id == "topic_share":
            c.enabled = False
    r = await client.post(f"/api/runs/{run_id}/criteria", json={"criteria": cs.model_dump(mode="json")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["handle"] for e in body["returned"]] == ["cyril_travel"] and body["dropped"] == []
    assert body["returned"][0]["elimination"]["criterion_id"] == "topic_share"
    assert body["fill_missing_started"] is False
    new = get_bus().history(run_id)[n_before:]
    names = [e for e, _ in new]
    assert names[-1] == "diff" and names.count("candidate.updated") == 1  # only the changed candidate
    assert new[-1][1]["returned"][0]["candidate_id"] == "instagram:cyril_travel"
    on_disk = json.loads((get_settings().runs_dir / f"{run_id}.json").read_text())
    assert on_disk["candidates"]["instagram:cyril_travel"]["status"] == "finalist"


async def test_restore_and_fill_missing(client, fake_engine):
    run_id = await start_fake_run(client)
    r = await client.post(f"/api/runs/{run_id}/restore",
                          json={"candidate_id": "@cyril_travel", "criterion_id": "topic_share"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["returned"][0]["candidate_id"] == "instagram:cyril_travel" and body["fill_missing_started"] is True
    await main.wait_idle(run_id)
    assert fake_engine.filled == 1
    run = get_store().get(run_id)
    assert run.candidates["instagram:cyril_travel"].restored is True
    assert [e for e, _ in get_bus().history(run_id)].count("diff") == 2  # restore + fill
    bad = await client.post(f"/api/runs/{run_id}/restore", json={"candidate_id": "nobody", "criterion_id": "topic_share"})
    assert bad.status_code == 404
    bad = await client.post(f"/api/runs/{run_id}/restore", json={"candidate_id": "bob_fit", "criterion_id": "nope"})
    assert bad.status_code == 400


async def test_vet_validation_and_reports(client, fake_engine):
    run_id = await start_fake_run(client)
    r = await client.post(f"/api/runs/{run_id}/vet", json={"candidate_ids": ["instagram:cyril_travel"]})
    assert r.status_code == 400 and "finalists" in r.json()["detail"]
    r = await client.post(f"/api/runs/{run_id}/vet", json={"candidate_ids": ["ghost"]})
    assert r.status_code == 404
    r = await client.post(f"/api/runs/{run_id}/vet", json={"candidate_ids": ["anna_pece", "instagram:bob_fit"]})
    assert r.status_code == 200 and r.json()["candidate_ids"] == ["instagram:anna_pece", "instagram:bob_fit"]
    await main.wait_idle(run_id)
    names = [e for e, _ in get_bus().history(run_id)]
    assert names.count("report.ready") == 2
    assert get_store().get(run_id).candidates["instagram:anna_pece"].report is not None


async def test_goal_change(client, fake_engine):
    run_id = await start_fake_run(client)
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["criteria_source"] == "preset:fitness"
    assert body["previous_brief"]["business_type"] == "pekárna"
    assert "fitness" in body["criteria"]["brief"]["business_type"].lower()
    assert "dropped" in body and "returned" in body
    brief = Brief(business_type="fitness studio", city="Brno", audience="lidé z Brna", goal="noví členové",
                  budget_hint=None, competitors=[{"name": "FitZone", "handles": ["fitzone_brno"]}])
    r = await client.post(f"/api/runs/{run_id}/goal", json={"brief": brief.model_dump(mode="json")})
    assert r.json()["criteria_source"] == "preset:fitness"
    assert r.json()["criteria"]["brief"]["competitors"][0]["handles"] == ["fitzone_brno"]
    other = brief.model_copy(update={"business_type": "květinářství", "city": "Olomouc"})
    r = await client.post(f"/api/runs/{run_id}/goal", json={"brief": other.model_dump(mode="json")})
    body = r.json()
    assert body["criteria_source"] == "kept_current"  # no key -> no agent; deterministic
    local = [c for c in body["criteria"]["criteria"] if c["kind"] == "local_signal"]
    assert local and local[0]["params"]["city"] == "Olomouc"


async def test_compare(client, fake_engine):
    run_id = await start_fake_run(client)
    r = await client.get(f"/api/runs/{run_id}/compare", params={"sort": "followers_range"})
    assert r.status_code == 200 and r.json()["sort"] == "followers_range" and len(r.json()["rows"]) == 2
    assert (await client.get(f"/api/runs/{run_id}/compare", params={"sort": "nope"})).status_code == 400


async def test_run_json_has_no_score_like_keys(client, fake_engine):
    run_id = await start_fake_run(client)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    bad = [p for k, p in walk_keys(data) if k in FORBIDDEN_KEYS and ".params" not in p]
    assert not bad, bad


# =============================================================================================
# chat
# =============================================================================================


async def test_chat_stream_always_ends_with_done(client):
    r = await client.post("/api/chat", json={"message": "Dobrý den, mám pekárnu v Brně.", "lang": "cs"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = parse_sse(r.text)
    assert evs and evs[-1][1] == "done" and [e for _, e, _ in evs].count("done") == 1
    chat_id = evs[-1][2]["chat_id"]
    assert chat_id == r.headers["x-chat-id"]
    assert all(e in ("chat.delta", "chat.tool", "criteria.updated", "error", "done") for _, e, _ in evs)
    errors = [d["message"] for _, e, d in evs if e == "error"]
    assert not errors, errors
    assert evs[-1][2]["llm_mode"] == "fallback"
    assert any(e == "chat.delta" for _, e, _ in evs)
    # same session continues (history kept)
    r2 = await client.post("/api/chat", json={"message": "Rodiny a mladí lidé.", "lang": "cs", "chat_id": chat_id})
    assert parse_sse(r2.text)[-1][2]["chat_id"] == chat_id


async def test_session_resolution(client):
    s1 = main._resolve_session(None, None, False)
    assert main._resolve_session(None, None, False) is s1          # most recent session
    assert main._resolve_session(s1.id, None, False) is s1
    s2 = main._resolve_session(None, None, True)                    # reset -> new
    assert s2 is not s1
    run = get_store().create(get_preset("bakery"))
    s3 = main._resolve_session(None, run.id, False)
    assert s3.run_id == run.id and main._resolve_session(None, run.id, False) is s3
    s4 = main._resolve_session(None, "r_unknown", False)
    assert s4.run_id in (None, run.id)                              # unknown run ids are ignored


async def test_chat_context_tools(client, fake_engine, monkeypatch):
    events: list[tuple[str, dict]] = []

    async def emit(event, data):
        events.append((event, data))

    session = main._resolve_session(None, None, True)
    ctx = main.ApiChatContext(session, "cs", emit)
    assert ctx.current_run() is None and ctx.current_criteria() is None
    assert (await ctx.run_rounds(3))["ok"] is False                  # no criteria yet
    out = await ctx.propose_criteria(get_preset("bakery"))
    assert out["ok"] and events[-1][0] == "criteria.updated"
    out = await ctx.update_criterion("followers_range", {"min": 3000, "evil": 1, "max": "lots"})
    assert out["ok"] and out["criterion"]["params"]["min"] == 3000 and set(out["ignored_params"]) == {"evil", "max"}
    assert (await ctx.run_rounds(4))["ok"] is False                  # round 4 needs explicit vetting
    out = await ctx.run_rounds(3)
    assert out["ok"] and out["status"] == "finished" and len(out["finalists"]) == 2
    assert out["eliminated_by"] == [{"round": 2, "criterion_id": "topic_share", "label": "Podíl relevantních témat",
                                     "count": 1}]
    assert ctx.current_run() is not None and session.run_id == out["run_id"]
    assert not [p for k, p in walk_keys(out) if k in FORBIDDEN_KEYS]
    ex = await ctx.explain_elimination("@cyril_travel")
    assert ex["ok"] and ex["elimination"]["criterion_id"] == "topic_share" and ex["elimination"]["sources"]
    assert (await ctx.explain_elimination("ghost"))["ok"] is False
    out = await ctx.update_criterion("topic_share", enabled=False)  # recompute on the live run
    assert out["applied_to_run"] and out["diff"]["returned_count"] == 1
    vet = await ctx.start_deep_vetting(["anna_pece"])
    assert vet["ok"] and vet["candidates"][0]["report_ready"] is True
    assert (await ctx.start_deep_vetting(["a", "b", "c", "d", "e", "f"]))["ok"] is False

    async def fake_outreach(brief, candidate):
        return i18n("Dobrý den, ...", "Hello, ...")

    from app.llm import vetting
    monkeypatch.setattr(vetting, "outreach", fake_outreach)
    d = await ctx.draft_outreach("bob_fit")
    assert d["ok"] and d["sent"] is False and d["status"] == "draft_not_sent" and d["draft"]["cs"]
    goal = await ctx.change_goal(Brief(business_type="fitness studio", city="Brno", audience="x", goal="y",
                                       budget_hint=None, competitors=[]))
    assert goal["ok"] and goal["criteria_source"] == "preset:fitness" and goal["applied_to_run"]
    assert events[-1][0] == "criteria.updated"


# =============================================================================================
# real engine + MockProvider
# =============================================================================================


def _xfail_if_unimplemented(messages: list[str]) -> None:
    """All modules are implemented now (integration): an unimplemented stub is a failure, not an xfail."""
    for m in messages:
        assert "not implemented" not in m, m


async def real_run(client) -> str:
    assert fixtures_present(), "fixtures/ missing"
    criteria, _src = bakery_criteria()
    r = await client.post("/api/runs", json={"criteria": criteria.model_dump(mode="json")})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    await main.wait_idle(run_id, timeout=120)
    errors = [d.get("message", "") for e, d in get_bus().history(run_id) if e == "error"]
    _xfail_if_unimplemented(errors)
    assert not errors, errors
    return run_id


async def test_real_bakery_run_end_to_end(client):
    run_id = await real_run(client)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["candidates"], "discovery found nobody"
    assert {r["round"] for r in data["rounds"]} >= {1, 2, 3}
    statuses = {c["status"] for c in data["candidates"].values()}
    assert "finalist" in statuses and "eliminated" in statuses
    for c in data["candidates"].values():
        if c["status"] == "eliminated":
            assert c["elimination"]["reason"]["cs"] and c["elimination"]["criterion_id"]
    assert data["mode_summary"].get("mock", 0) > 0 and not data["mode_summary"].get("live")
    bad = [p for k, p in walk_keys(data) if k in FORBIDDEN_KEYS and ".params" not in p]
    assert not bad, bad
    assert (get_settings().runs_dir / f"{run_id}.json").exists()


async def test_real_sse_replay(client):
    run_id = await real_run(client)
    evs = parse_sse((await client.get(f"/api/runs/{run_id}/events", params={"follow": "false"})).text)
    names = [e for _, e, _ in evs]
    assert names[0] == "run.started" and names[-1] == "run.finished"
    assert "candidate.added" in names and "round.finished" in names


async def test_real_criteria_recompute_diff(client):
    run_id = await real_run(client)
    cs = CriteriaSet.model_validate((await client.get(f"/api/runs/{run_id}")).json()["criteria"])
    for c in cs.criteria:
        if c.round in (2, 3):
            c.enabled = False
    r = await client.post(f"/api/runs/{run_id}/criteria", json={"criteria": cs.model_dump(mode="json")})
    assert r.status_code == 200, r.text
    assert r.json()["returned"], "disabling rounds 2-3 should bring someone back"
    assert get_bus().history(run_id)[-1][0] == "diff"


async def test_real_restore(client):
    run_id = await real_run(client)
    run = get_store().get(run_id)
    victim = next(c for c in run.candidates.values() if c.status == "eliminated" and c.elimination.round >= 2)
    r = await client.post(f"/api/runs/{run_id}/restore",
                          json={"candidate_id": victim.id, "criterion_id": victim.elimination.criterion_id})
    assert r.status_code == 200, r.text
    await main.wait_idle(run_id, timeout=60)
    c = get_store().get(run_id).candidates[victim.id]
    assert c.restored is True
    assert any(res.waived for res in c.results)


async def test_real_goal_change_changes_finalists(client):
    run_id = await real_run(client)
    before = {cid for cid, c in get_store().get(run_id).candidates.items() if c.status == "finalist"}
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    await main.wait_idle(run_id, timeout=60)
    after = {cid for cid, c in get_store().get(run_id).candidates.items() if c.status == "finalist"}
    body = r.json()
    assert body["dropped"] or body["returned"]
    assert before != after


async def test_real_compare(client):
    run_id = await real_run(client)
    r = await client.get(f"/api/runs/{run_id}/compare", params={"sort": "min_engagement"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows and all("score" not in row for row in rows)
    vals = [row["sort_value"] for row in rows if row["sort_value"] is not None]
    assert vals == sorted(vals, reverse=True)


async def test_real_goal_change_publishes_combined_final_diff(client):
    """A goal change that needs fill_missing publishes a provisional diff (pending_fetch) and then
    one final diff against the pre-change state (replaces_pending), matching the designed fitness outcome."""
    run_id = await real_run(client)
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fill_missing_started"] is True and body["pending_fetch"] is True
    await main.wait_idle(run_id, timeout=60)
    diffs = [d for e, d in get_bus().history(run_id) if e == "diff"]
    assert diffs[-1].get("final") and diffs[-1].get("replaces_pending")
    final = diffs[-1]
    returned = {e["candidate_id"] for e in final["returned"]}
    dropped = {e["candidate_id"] for e in final["dropped"]}
    assert returned == {"instagram:trener_marek_brno", "tiktok:pavla_hybe_brnem", "tiktok:jogina_lucie",
                        "instagram:kalisthenika_brno_tom"}
    assert dropped == {"instagram:kuba.jidlo.brno", "instagram:verca_pece", "instagram:brnenska_snidane",
                       "tiktok:toman_ochutnava"}
    rounds = {e["round"]: (e["entered"], e["remaining"]) for e in get_store().get(run_id).rounds}
    # fixtures/README.md oracle, goal `fitness`: 48 -> 31 -> 10 -> 5
    assert rounds[1] == (48, 31) and rounds[2] == (31, 10) and rounds[3] == (10, 5)


async def test_real_vetting_counts_sensitive_items_once(client):
    """Round 4 re-fetches the latest posts: an item round 1 already filtered must not be counted again,
    and vetting the same finalist twice must not add up."""
    run_id = await real_run(client)
    fin = sorted(cid for cid, c in get_store().get(run_id).candidates.items() if c.status == "finalist")
    for _ in range(2):
        r = await client.post(f"/api/runs/{run_id}/vet", json={"candidate_ids": fin})
        assert r.status_code == 200, r.text
        await main.wait_idle(run_id, timeout=60)
    run = get_store().get(run_id)
    got = {cid: c.sensitive_filtered for cid, c in run.candidates.items() if cid in fin}
    assert got == {"instagram:kuba.jidlo.brno": 2, "instagram:verca_pece": 0, "instagram:brnenska_snidane": 1,
                   "tiktok:toman_ochutnava": 0, "instagram:fit_peci_s_klarou": 1}
    assert all(run.candidates[cid].report.sensitive_filtered == n for cid, n in got.items())


async def test_real_discovery_goal_change_rerenders_vetted_reports(client):
    """Discovery runs get goal-conditioned reports too: a goal change re-renders every vetted report
    from its stored vetting data (no fetch, no LLM) and publishes report.diff + report.ready."""
    run_id = await real_run(client)
    r = await client.post(f"/api/runs/{run_id}/vet", json={"candidate_ids": ["instagram:fit_peci_s_klarou"]})
    assert r.status_code == 200, r.text
    await main.wait_idle(run_id, timeout=60)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    cand = data["candidates"]["instagram:fit_peci_s_klarou"]
    assert "vetting_data" not in cand and cand["report"]["rendered_for"]["business_type"] == "pekárna"
    assert cand["report"]["identity_verdict"]["status"] in ("likely", "uncertain")   # no anchor in discovery
    n = len(get_bus().history(run_id))
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    rds = r.json()["report_diffs"]
    assert [d["candidate_id"] for d in rds] == ["instagram:fit_peci_s_klarou"] and "i:competitor" in rds[0]["added"]
    new = [e for e, _ in get_bus().history(run_id)[n:]]
    assert "report.diff" in new and "report.ready" in new and "vetting.progress" not in new
    await main.wait_idle(run_id, timeout=60)
    rep = get_store().get(run_id).candidates["instagram:fit_peci_s_klarou"].report
    assert rep.rendered_for["business_type"] == "fitness studio" and rep.vetted_for == "pekárna"
