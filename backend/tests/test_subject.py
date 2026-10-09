"""Subject mode (docs/subject-mode.md): one named creator + one anchor + a goal -> a sourced,
goal-conditioned report. Runs the real engine + MockProvider through the API (fixtures/ must exist);
no LLM keys (deterministic fallbacks), temp DATA_DIR from conftest.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import main
from app.compute.subject import anchor_text, normalize_anchor, parse_subject
from app.events import get_bus
from app.models import Anchor, Run
from app.presets import get_preset, preset_brief
from app.store import get_store

FORBIDDEN_KEYS = {"score", "overall_score", "rank", "ranking", "best", "risk", "risk_level", "trustworthy",
                  "trust_score", "personality"}


@pytest.fixture
async def client():
    await main.reset_runtime_state()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        yield c
    await main.reset_runtime_state()


async def start(client, body: dict) -> str:
    r = await client.post("/api/subject", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "subject" and d["status"] == "started"
    await main.wait_idle(d["run_id"], timeout=120)
    return d["run_id"]


def events(run_id: str) -> list[tuple[str, dict]]:
    return get_bus().history(run_id)


def names(run_id: str) -> list[str]:
    return [e for e, _ in events(run_id)]


def keys_of(obj) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= keys_of(v)
    elif isinstance(obj, list):
        for x in obj:
            out |= keys_of(x)
    return out


def report_of(run_json: dict) -> dict:
    cid = run_json["subject"]["candidate_id"]
    return run_json["candidates"][cid]["report"]


def by_id(rep: dict) -> dict[str, dict]:
    return {f["id"]: f for f in rep["findings"]} | {c["id"]: c for c in rep["claims"]}


# ---------------------------------------------------------------------------------------------
# Parsing (pure)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text,platform,expected", [
    ("@Fit_Peci_s_Klarou", None, (None, "fit_peci_s_klarou")),
    ("fit_peci_s_klarou", "tiktok", ("tiktok", "fit_peci_s_klarou")),
    ("https://www.instagram.com/kuba.jidlo.brno/", None, ("instagram", "kuba.jidlo.brno")),
    ("instagram.com/kuba.jidlo.brno?igsh=abc#x", None, ("instagram", "kuba.jidlo.brno")),
    ("https://m.instagram.com/kuba.jidlo.brno/reels/", None, ("instagram", "kuba.jidlo.brno")),
    ("https://www.tiktok.com/@toman_ochutnava/video/123", None, ("tiktok", "toman_ochutnava")),
    ("https://www.instagram.com/x_y/", "tiktok", ("instagram", "x_y")),    # URL wins over the platform arg
    ("https://www.instagram.com/p/Cxyz/", None, None),                     # a post, not a profile
    ("https://www.instagram.com/reel/Cxyz/", None, None),
    ("https://www.tiktok.com/video/123", None, None),                      # video without @handle
    ("https://example.com/kuba", None, None),
    ("two words", None, None),
    ("@" + "a" * 31, None, None),
    ("", None, None),
])
def test_parse_subject(text, platform, expected):
    assert parse_subject(text, platform) == expected


def test_normalize_anchor_and_text():
    a = normalize_anchor({"city": "  Brno ", "website": "https://www.FitPeceni.example/o-nas?x=1", "company_id": "CZ 123456"})
    assert a == Anchor(city="Brno", website="fitpeceni.example", company_id="00123456")
    assert normalize_anchor({"company_id": "12 345 678"}).company_id == "12345678"
    assert normalize_anchor({"company_id": "123"}) is None          # too short: not an IČO
    assert normalize_anchor({}) is None and normalize_anchor(None) is None
    assert normalize_anchor(Anchor(website="m.example.org")) == Anchor(website="example.org")
    assert anchor_text(a, "en") == "city Brno, website fitpeceni.example, company ID 00123456"
    assert anchor_text(a, "cs") == "město Brno, web fitpeceni.example, IČO 00123456"
    assert anchor_text(None, "en") == ""


def test_presets_in_english():
    b = preset_brief("bakery", "en")
    assert (b.business_type, b.city, b.lang) == ("bakery", "Brno", "en")
    assert b.audience == "families and young people in Brno" and b.budget_hint == "up to CZK 20,000"
    f = get_preset("fitness", "en")
    assert f.brief.business_type == "fitness studio" and f.brief.goal == "more sign-ups for a trial class"
    assert f.brief.competitors == get_preset("fitness").brief.competitors
    # Czech default unchanged; criteria identical in both languages
    assert get_preset("bakery").brief.business_type == "pekárna"
    assert [c.model_dump() for c in get_preset("bakery", "en").criteria] == [c.model_dump() for c in get_preset("bakery").criteria]


# ---------------------------------------------------------------------------------------------
# Acceptance scenario 1 + 2: confirmed identity, goal switch re-renders without fetch / LLM
# ---------------------------------------------------------------------------------------------


async def test_subject_fit_peci_bakery_then_fitness(client):
    run_id = await start(client, {"subject": "@fit_peci_s_klarou", "anchor": {"website": "https://fitpeceni.example/"},
                                  "brief": "bakery", "lang": "en"})
    ev = names(run_id)
    assert "subject.resolved" in ev and "report.ready" in ev and ev[-1] == "run.finished"
    assert "error" not in ev and "candidate.eliminated" not in ev
    resolved = next(d for e, d in events(run_id) if e == "subject.resolved")
    assert resolved == {"candidate_id": "instagram:fit_peci_s_klarou", "platform": "instagram", "handle": "fit_peci_s_klarou"}
    finished = [d for e, d in events(run_id) if e == "round.finished"]
    assert [d["round"] for d in finished] == [1, 2, 3, 4]
    assert all(d["entered"] == 1 and d["remaining"] == 1 for d in finished)
    assert "vetting.progress" in ev

    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert run["mode"] == "subject" and run["subject"]["status"] == "resolved"
    assert run["subject"]["anchor"] == {"city": None, "website": "fitpeceni.example", "company_id": None}
    cand = run["candidates"]["instagram:fit_peci_s_klarou"]
    assert cand["status"] == "finalist" and cand["elimination"] is None
    assert "vetting_data" not in cand                                   # stays server-side
    rep = cand["report"]
    v = rep["identity_verdict"]
    assert v["status"] == "confirmed"
    assert v["text"]["en"].startswith("We are confident @fit_peci_s_klarou is the creator you mean because")
    assert "fitpeceni.example" in v["text"]["en"] and "TikTok @fit_peci_s_klarou links back" in v["text"]["en"]
    assert v["text"]["cs"].startswith("Jsme si jistí, že @fit_peci_s_klarou")
    assert all(s["source"] for s in v["supporting"])
    # every finding / claim: confidence + basis + tier + why; facts cite sources
    for f in rep["findings"]:
        assert f["confidence"] in ("high", "medium", "low") and f["confidence_basis"]["en"], f["id"]
        assert f["tier"] in ("key", "related", "less") and f["why_it_matters"]["en"] and f["aspect"], f["id"]
        if f["kind"] == "fact":
            assert f["sources"], f["id"]
    for c in rep["claims"]:
        assert c["confidence_basis"]["en"] and c["tier"]
    items = by_id(rep)
    collab = [f for f in rep["findings"] if f["id"].startswith("f:collab:") and "ProteoMax" in f["text"]["en"]]
    assert collab and all(f["tier"] == "less" for f in collab)            # labeled, not a bakery competitor
    assert "i:competitor" not in items
    assert items["f:fit:topics"]["tier"] == "key" and "bakery" in items["f:fit:topics"]["text"]["en"]
    assert any("bakery" in q["en"] for q in rep["questions"])            # questions speak to this goal
    assert "bakery" in rep["outreach_draft"]["en"]
    assert rep["rendered_for"]["business_type"] == "bakery" and rep["last_diff"] is None
    assert rep["sections"][0]["id"] == "identity" and rep["sections"][1]["id"] == "goal"
    assert set(rep["less_relevant"]) == {i for s in rep["sections"] for i in s["less_ids"]}
    assert rep["method"] and any("no new requests" in m["en"] for m in rep["method"])
    assert rep["text_source"]["claims"] == "rules" and rep["text_source"]["outreach"] == "template"
    assert not (keys_of(run) & FORBIDDEN_KEYS)
    # the store snapshot keeps the raw round-4 inputs (re-rendering needs no fetch)
    snap = json.loads(get_store().path_for(run_id).read_text())
    assert snap["candidates"]["instagram:fit_peci_s_klarou"]["vetting_data"]["posts"]
    # SSE payloads never carry vetting_data
    for e, d in events(run_id):
        if e.startswith("candidate."):
            assert "vetting_data" not in (d.get("candidate") or {})

    st = (await client.get(f"/api/runs/{run_id}/status")).json()
    assert st["mode"] == "subject" and st["llm_requests_used"] == 0 and "llm_budget" in st and "llm_budget_left" in st
    rows = (await client.get("/api/runs")).json()
    assert {"run_id": run_id, "mode": "subject", "subject": "fit_peci_s_klarou"}.items() <= next(
        r for r in rows if r["run_id"] == run_id).items()

    # --- goal switch: no fetch, no LLM; ProteoMax becomes a competitor
    n_before = len(events(run_id))
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dropped"] == [] and d["returned"] == [] and d["fill_missing_started"] is False
    assert d["criteria"]["brief"]["lang"] == "en" and d["criteria"]["brief"]["business_type"] == "fitness studio"
    rd = d["report_diffs"][0]
    assert rd["candidate_id"] == "instagram:fit_peci_s_klarou"
    assert "i:competitor" in rd["added"]
    assert any(i in rd["moved_up"] for i in (f["id"] for f in collab))
    assert rd["questions_added"] and rd["outreach_changed"] is True
    assert rd["summary"]["en"].startswith("Goal changed from bakery to fitness studio:")
    assert "ProteoMax is now a competitor" in rd["summary"]["en"]
    new = events(run_id)[n_before:]
    new_names = [e for e, _ in new]
    assert "report.diff" in new_names and "report.ready" in new_names
    assert new_names.index("report.diff") < new_names.index("report.ready")
    assert "vetting.progress" not in new_names and "round.started" not in new_names   # no fetch
    st2 = (await client.get(f"/api/runs/{run_id}/status")).json()
    assert st2["llm_requests_used"] == st["llm_requests_used"]

    run2 = (await client.get(f"/api/runs/{run_id}")).json()
    rep2 = report_of(run2)
    items2 = by_id(rep2)
    assert items2["i:competitor"]["tier"] == "key"
    assert all(items2[f["id"]]["tier"] == "key" for f in collab)
    assert "competitor" in items2[collab[0]["id"]]["why_it_matters"]["en"]
    assert "fitness" in items2["f:fit:topics"]["text"]["en"] and "fitness studio" in items2["f:fit:topics"]["text"]["en"]
    assert rep2["questions"] != rep["questions"] and rep2["outreach_draft"] != rep["outreach_draft"]
    assert rep2["last_diff"]["summary"] == rd["summary"]
    assert rep2["vetted_for"] == rep["vetted_for"] == "bakery"
    comp = next(x for x in run2["candidates"]["instagram:fit_peci_s_klarou"]["results"] if x["criterion_id"] == "no_competitor_collab")
    assert comp["status"] == "fail"                                      # round 4 re-evaluated on the new timeline
    assert run2["candidates"]["instagram:fit_peci_s_klarou"]["status"] == "finalist"   # nothing eliminated
    # the run log says what happened and shows no provider call for the goal switch
    new_log = run2["log"][len(run["log"]):]
    assert any(e["text"].startswith("Report for @fit_peci_s_klarou re-rendered for the new goal") for e in new_log)
    assert not [e for e in new_log if str(e.get("actor") or "").startswith(("mock:", "apify:"))]

    # restore makes no sense here; vet re-vets the subject
    r = await client.post(f"/api/runs/{run_id}/restore", json={"candidate_id": "instagram:fit_peci_s_klarou",
                                                               "criterion_id": "topic_share"})
    assert r.status_code == 400 and "subject" in r.json()["detail"]
    r = await client.post(f"/api/runs/{run_id}/vet", json={})
    assert r.status_code == 200 and r.json()["candidate_ids"] == ["instagram:fit_peci_s_klarou"]
    await main.wait_idle(run_id, timeout=60)
    run3 = (await client.get(f"/api/runs/{run_id}")).json()
    assert report_of(run3)["rendered_for"]["business_type"] == "fitness studio"


async def test_goal_change_back_restores_the_first_render(client):
    run_id = await start(client, {"subject": "@fit_peci_s_klarou", "anchor": {"website": "fitpeceni.example"},
                                  "preset": "bakery", "lang": "en"})
    first = report_of((await client.get(f"/api/runs/{run_id}")).json())
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})).status_code == 200
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "bakery"})
    assert r.status_code == 200
    back = report_of((await client.get(f"/api/runs/{run_id}")).json())
    for k in ("findings", "claims", "questions", "outreach_draft", "sections", "summary", "identity_verdict", "method"):
        assert back[k] == first[k], k
    assert back["last_diff"]["summary"]["en"].startswith("Goal changed from fitness studio to bakery")


# ---------------------------------------------------------------------------------------------
# Acceptance scenarios 3-6: look-alikes, namesakes, fan accounts, not found
# ---------------------------------------------------------------------------------------------


async def test_subject_look_alike_and_exclusivity_conflict(client):
    run_id = await start(client, {"subject": "https://www.instagram.com/kuba.jidlo.brno/", "anchor": {"city": "Brno"},
                                  "brief": "bakery", "lang": "en"})
    rep = report_of((await client.get(f"/api/runs/{run_id}")).json())
    v = rep["identity_verdict"]
    sa = {s["ref"]: s for s in v["set_aside"]}
    assert sa["tiktok:kuba_jidlo"]["kind"] == "look_alike"
    assert "Bratislava" in sa["tiktok:kuba_jidlo"]["reason"]["en"]
    assert "TikTok @kuba_jidlo" in v["text"]["en"] and "set aside" in v["text"]["en"]
    assert v["status"] in ("likely", "confirmed")
    claim = next(c for c in rep["claims"] if "exkluzivní ambasador @pekarna_a" in c["claim"])
    assert claim["status"] == "conflicts_with_record" and claim["tier"] == "key"
    assert "no_competitor_collab" in claim["relevance"]


async def test_subject_namesake_article_set_aside(client):
    run_id = await start(client, {"subject": "@toman_ochutnava", "platform": "tiktok", "anchor": {"city": "Brno"},
                                  "brief": "bakery"})
    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert run["subject"]["platform"] == "tiktok"
    rep = report_of(run)
    v = rep["identity_verdict"]
    ns = [s for s in v["set_aside"] if s["kind"] == "namesake"]
    assert len(ns) == 1 and "Zlínský kurýr" in ns[0]["label"] and "Ondřej Toman" in ns[0]["label"]
    assert "namesake" in v["text"]["en"] and "Zlínský kurýr" in v["text"]["en"]
    # the headline of the article about someone else is not repeated in the verdict
    assert "dluží" not in json.dumps(v, ensure_ascii=False)
    assert all("Zlín" not in n["item"]["outlet"] for n in rep["news"])


async def test_subject_fan_account_set_aside(client):
    run_id = await start(client, {"subject": "@brnenska_snidane", "anchor": {"city": "Brno"}, "brief": "bakery"})
    v = report_of((await client.get(f"/api/runs/{run_id}")).json())["identity_verdict"]
    sa = {s["ref"]: s for s in v["set_aside"]}
    assert sa["tiktok:brnenska_snidane_fans"]["kind"] == "fan_account"


async def test_subject_not_found(client):
    run_id = await start(client, {"subject": "@nobody_here_xyz", "anchor": {"city": "Brno"}, "brief": "bakery"})
    ev = events(run_id)
    nf = [d for e, d in ev if e == "subject.not_found"]
    assert nf and nf[0]["subject"] == "@nobody_here_xyz" and nf[0]["tried"] == ["instagram", "tiktok"]
    assert nf[0]["reason"]["en"]
    assert "error" not in [e for e, _ in ev] and ev[-1][0] == "run.finished"
    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert run["subject"]["status"] == "not_found" and run["candidates"] == {}


async def test_subject_request_errors(client):
    r = await client.post("/api/subject", json={"subject": "https://www.instagram.com/p/Cxyz/", "brief": "bakery"})
    assert r.status_code == 422 and "profile link" in r.json()["detail"]
    r = await client.post("/api/subject", json={"subject": "not a handle!", "brief": "bakery"})
    assert r.status_code == 422
    r = await client.post("/api/subject", json={"subject": "@fit_peci_s_klarou"})
    assert r.status_code == 422 and "brief" in r.json()["detail"]
    r = await client.post("/api/subject", json={"subject": "@fit_peci_s_klarou", "brief": "dentist"})
    assert r.status_code == 422


async def test_subject_generic_brief_and_criteria(client):
    # a non-preset brief: deterministic criteria for it; the anchor city never becomes the business city
    brief = {"business_type": "flower shop", "city": "Praha", "audience": "people in Prague", "goal": "more orders",
             "budget_hint": None, "competitors": []}
    run_id = await start(client, {"subject": "@fit_peci_s_klarou", "anchor": {"city": "Brno"}, "brief": brief, "lang": "en"})
    run = get_store().get(run_id)
    assert run.criteria.brief.city == "Praha" and run.criteria.brief.lang == "en"
    assert run.criteria.discovery.city == "Praha"
    rep = run.candidates["instagram:fit_peci_s_klarou"].report
    assert rep is not None and rep.identity_verdict is not None
    assert rep.rendered_for["business_type"] == "flower shop"


# ---------------------------------------------------------------------------------------------
# Chat context (A's side of research_subject; B's fallback drives it)
# ---------------------------------------------------------------------------------------------


class Rec:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def __call__(self, event: str, data: dict) -> None:
        self.items.append((event, data))


async def test_chat_context_research_subject_and_goal_switch(client):
    rec = Rec()
    session = main._resolve_session(None, None, True)
    ctx = main.ApiChatContext(session, "en", rec)
    out = await ctx.research_subject("@fit_peci_s_klarou", {"website": "fitpeceni.example"}, None, "bakery")
    assert out["ok"] is True and out["status"] == "finished", out
    assert out["subject"]["status"] == "resolved" and out["subject"]["platform"] == "instagram"
    assert out["criteria_source"] == "preset:bakery" and out["anchor"]["website"] == "fitpeceni.example"
    assert out["identity"]["status"] == "confirmed" and out["identity"]["text"].startswith("We are confident")
    assert out["checks"]["pass"] + out["checks"]["fail"] + out["checks"]["unknown"] == 15
    assert len(out["checks"]["items"]) <= 8 and len(out["key_findings"]) <= 5
    assert all({"id", "kind", "text", "confidence", "why"} <= set(k) for k in out["key_findings"])
    assert len(out["claims"]) <= 3 and len(out["questions"]) <= 3 and out["outreach_draft_ready"] is True
    assert out["note"] == "Subject check: nothing is eliminated and there is no score."
    upd = [d for e, d in rec.items if e == "criteria.updated"]
    assert upd and upd[0]["run_id"] == out["run_id"]
    assert session.run_id == out["run_id"]

    # discovery-only tools refuse on a subject run
    rr = await ctx.run_rounds(3)
    assert rr["ok"] is False and "research_subject" in rr["error"]

    g = await ctx.change_goal(preset_brief("fitness", "en"))
    assert g["ok"] is True and g["report_diffs"], g
    d0 = g["report_diffs"][0]
    assert d0["handle"] == "fit_peci_s_klarou" and d0["summary"].startswith("Goal changed from bakery to fitness studio")
    assert d0["added"] >= 1 and d0["outreach_changed"] is True and d0["key_findings"]

    bad = await ctx.research_subject("https://www.instagram.com/p/xyz/", None, None, "bakery")
    assert bad["ok"] is False and bad["missing"] == ["subject"]


async def test_chat_context_research_subject_needs_a_goal(client):
    session = main._resolve_session(None, None, True)
    ctx = main.ApiChatContext(session, "en", Rec())
    out = await ctx.research_subject("@fit_peci_s_klarou", None, None, None)
    assert out["ok"] is False and out["missing"] == ["brief"]


async def test_chat_context_research_subject_not_found(client):
    session = main._resolve_session(None, None, True)
    ctx = main.ApiChatContext(session, "en", Rec())
    out = await ctx.research_subject("@nobody_here_xyz", {"city": "Brno"}, None, "bakery")
    assert out["ok"] is True and out["subject"]["status"] == "not_found"
    assert out["identity"]["status"] == "not_found" and "nobody_here_xyz" in out["identity"]["text"]


def test_run_model_defaults_load_old_snapshots():
    old = {"id": "r_old", "criteria": json.loads(get_preset("bakery").model_dump_json()), "candidates": {},
           "rounds": [], "log": [], "mode_summary": {}}
    run = Run.model_validate(old)
    assert run.mode == "discovery" and run.subject is None and run.llm_usage == {}


async def test_private_account_gets_unknown_checks_and_a_report(client):
    run_id = await start(client, {"subject": "@anicka_doma", "anchor": {"city": "Brno"}, "brief": "bakery", "lang": "en"})
    run = (await client.get(f"/api/runs/{run_id}")).json()
    cand = run["candidates"]["instagram:anicka_doma"]
    assert cand["status"] == "finalist" and cand["report"] is not None
    assert "error" not in names(run_id)
    assert any(r["status"] == "unknown" for r in cand["results"])


async def test_minor_is_not_processed(client):
    run_id = await start(client, {"subject": "@nikolka_pece", "anchor": {"city": "Brno"}, "brief": "bakery"})
    run = get_store().get(run_id)
    assert run.subject.status == "not_found" and run.candidates == {}
    snap = get_store().path_for(run_id).read_text()
    assert '"latest_posts"' not in snap and '"bio"' not in snap
