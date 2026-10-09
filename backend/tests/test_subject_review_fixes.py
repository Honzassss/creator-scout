"""Review fixes for subject mode (round 2): no-data checks are gaps, identity texts, API anchors,
goal-aware outreach / why texts, look-alike split, competitor subject, news cross-checks, English logs."""

from __future__ import annotations

import httpx
import pytest

from app import main
from app.models import Brief
from app.presets import preset_brief


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
    await main.wait_idle(r.json()["run_id"], timeout=120)
    return r.json()["run_id"]


async def report(client, run_id: str) -> tuple[dict, dict]:
    run = (await client.get(f"/api/runs/{run_id}")).json()
    cid = run["subject"]["candidate_id"]
    return run, run["candidates"][cid]["report"]


def ids(rep: dict) -> dict[str, dict]:
    return {f["id"]: f for f in rep["findings"]} | {c["id"]: c for c in rep["claims"]}


async def test_private_account_collab_checks_are_gaps_not_passes(client):
    rid = await start(client, {"subject": "@anicka_doma", "anchor": {"city": "Brno"}, "preset": "bakery", "lang": "en"})
    _, rep = await report(client, rid)
    f = ids(rep)
    assert "f:check:no_competitor_collab" not in f and "f:check:discloses_ads" not in f
    assert "posts not available" in f["g:check:no_competitor_collab"]["text"]["en"]
    assert "posts not available" in f["g:check:discloses_ads"]["text"]["en"]
    assert not any("even though" in q["en"] for q in rep["questions"])      # topics unknown: no claim about them


async def test_identity_texts_name_the_missing_anchor_and_canonical_city(client):
    rid = await start(client, {"subject": "@fit_peci_s_klarou", "anchor": {"website": "other.example"},
                               "preset": "bakery", "lang": "en"})
    _, rep = await report(client, rid)
    v = rep["identity_verdict"]
    assert v["status"] == "uncertain" and "contradict" not in v["text"]["en"]
    assert "nothing on the profile matches the anchor (website other.example)" in v["text"]["en"]
    rid = await start(client, {"subject": "@kuba.jidlo.brno", "anchor": {"city": "Praha"}, "preset": "bakery", "lang": "en"})
    _, rep = await report(client, rid)
    assert "names Brno, not Praha" in rep["identity_verdict"]["text"]["en"]
    assert "Brnem" not in rep["identity_verdict"]["text"]["en"] and "Brně" not in rep["identity_verdict"]["text"]["en"]
    f = ids(rep)
    look = [k for k in f if k.startswith("i:lookalike:")]
    assert look and f[look[0]]["kind"] == "inference" and f[look[0]]["based_on"]
    assert "not the creator's account" not in f[f[look[0]]["based_on"][0]]["text"]["en"]


async def test_api_anchor_string_bad_company_id_and_trailing_dot(client):
    r = await client.post("/api/subject", json={"subject": "@kuba.jidlo.brno", "anchor": {"company_id": "abc"}, "preset": "bakery"})
    assert r.status_code == 422 and "6-8 digits" in r.json()["detail"]
    r = await client.post("/api/subject", json={"subject": "Jakub Horák", "anchor": {"city": "Brno"}, "preset": "bakery"})
    assert r.status_code == 422 and "namesakes" in r.json()["detail"]
    rid = await start(client, {"subject": "@kuba.jidlo.brno.", "anchor": "Brno", "preset": "bakery", "lang": "en"})
    run, _ = await report(client, rid)
    assert run["subject"]["handle"] == "kuba.jidlo.brno" and run["subject"]["anchor"]["city"] == "Brno"
    from app.compute.subject import classify_anchor

    assert classify_anchor("12345678").company_id == "12345678"
    assert classify_anchor("fitpeceni.example").website == "fitpeceni.example"


async def test_goal_switch_rewrites_outreach_and_claim_why(client):
    rid = await start(client, {"subject": "@toman_ochutnava", "anchor": {"city": "Brno"}, "preset": "fitness", "lang": "en"})
    _, rep = await report(client, rid)
    assert "fits us well" not in rep["outreach_draft"]["en"] and "longer videos" not in rep["outreach_draft"]["en"]
    rid = await start(client, {"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"}, "preset": "bakery", "lang": "en"})
    r = await client.post(f"/api/runs/{rid}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    _, rep = await report(client, rid)
    whys = [(c.get("why_it_matters") or {}).get("en", "") for c in rep["claims"]]
    assert whys and not any("FitZone" in w or "ProteoMax" in w for w in whys)


def test_custom_brief_on_a_preset_gets_its_own_why_texts():
    b = Brief(business_type="coffee roastery", city="Brno", audience="", goal="", budget_hint=None,
              competitors=[{"name": "Pražírna Hrudka", "handles": ["prazirna_hrudka"]}], lang="en")
    cs = main._criteria_from_preset("bakery", b, None)
    text = " ".join(c.why["en"] for c in cs.criteria)
    assert "Pekárna B" not in text and "pastry" not in text and "The bakery" not in text
    assert "Pražírna Hrudka" in text
    same = main._criteria_from_preset("bakery", preset_brief("bakery", "en"), None)
    assert any("Pekárna B" in c.why["en"] for c in same.criteria)


async def test_competitor_subject_gets_no_outreach(client):
    rid = await start(client, {"subject": "@pekarna_b", "preset": "bakery", "lang": "en"})
    _, rep = await report(client, rid)
    f = ids(rep)
    assert "f:subject_competitor" in f and f["f:subject_competitor"]["tier"] == "key"
    assert rep["outreach_draft"]["en"].startswith("No outreach draft")


async def test_news_naming_a_competitor_is_key_and_feeds_the_competitor_inference(client):
    rid = await start(client, {"subject": "@trener_marek_brno", "anchor": {"city": "Brno"}, "preset": "fitness", "lang": "en"})
    _, rep = await report(client, rid)
    f = ids(rep)
    news = [k for k, v in f.items() if k.startswith("f:news:") and "FitZone" in v["text"]["en"]]
    assert news and f[news[0]]["tier"] == "key"
    assert news[0] in f["i:competitor"]["based_on"]


async def test_english_run_log_is_english(client):
    rid = await start(client, {"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"}, "preset": "bakery", "lang": "en"})
    run, _ = await report(client, rid)
    text = " ".join(e["text"] for e in run["log"])
    for cz in ("komentářů", "postů od", "možný profil", "záznamy", "články"):
        assert cz not in text


async def test_vet_while_the_subject_check_runs_is_busy_not_not_found(client):
    r = await client.post("/api/subject", json={"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"}, "preset": "bakery"})
    rid = r.json()["run_id"]
    v = await client.post(f"/api/runs/{rid}/vet", json={"candidate_ids": []})
    assert v.status_code == 409
    await main.wait_idle(rid, timeout=120)
