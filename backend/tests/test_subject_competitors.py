"""Subject mode: the owner's own competitors (the subject form's optional field) replace the presets'
sample competitors, and survive a one-click switch between the two preset goals."""

from __future__ import annotations

import httpx
import pytest

from app import main
from app.presets import preset_brief

OWN = [{"name": "Lidl", "handles": []}, {"name": "albert_cz", "handles": ["albert_cz"]}]


@pytest.fixture
async def client():
    await main.reset_runtime_state()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        yield c
    await main.reset_runtime_state()


def names(brief: dict) -> list[str]:
    return [c["name"] for c in brief["competitors"]]


async def start(client, competitors: list[dict] | None) -> str:
    brief = preset_brief("bakery", "en").model_dump(mode="json")
    if competitors is not None:
        brief["competitors"] = competitors
    r = await client.post("/api/subject", json={"subject": "@fit_peci_s_klarou", "anchor": {"website": "fitpeceni.example"},
                                                "brief": brief, "preset": "bakery", "lang": "en"})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    await main.wait_idle(run_id, timeout=120)
    return run_id


async def brief_of(client, run_id: str) -> dict:
    return (await client.get(f"/api/runs/{run_id}")).json()["criteria"]["brief"]


async def test_own_competitors_kept_by_subject_and_goal_switch(client):
    run_id = await start(client, OWN)
    assert names(await brief_of(client, run_id)) == ["Lidl", "albert_cz"]
    # the one-click switch sends the other preset's brief (with its sample competitors) and the preset name
    sample = preset_brief("fitness", "en").model_dump(mode="json")
    r = await client.post(f"/api/runs/{run_id}/goal", json={"brief": sample, "preset": "fitness"})
    assert r.status_code == 200, r.text
    b = await brief_of(client, run_id)
    # another kind of business: the owner's grocery rivals do not carry over to a fitness studio
    assert b["business_type"] == "fitness studio" and "Lidl" not in names(b)
    # back to the bakery (preset name only): the owner's own list for the bakery comes back
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"preset": "bakery"})).status_code == 200
    assert names(await brief_of(client, run_id)) == ["Lidl", "albert_cz"]
    # competitors the owner changes in the same request win
    edited = {**preset_brief("fitness", "en").model_dump(mode="json"), "competitors": [{"name": "Kaufland", "handles": []}]}
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"brief": edited})).status_code == 200
    assert names(await brief_of(client, run_id)) == ["Kaufland"]


async def test_without_own_competitors_the_presets_switch_as_before(client):
    run_id = await start(client, None)
    assert names(await brief_of(client, run_id)) == ["Pekárna B", "Chlebárna Vlnka"]
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})).status_code == 200
    assert names(await brief_of(client, run_id)) == ["FitZone Brno", "ProteoMax"]


async def test_chat_subject_takes_the_owners_competitors():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @kamvbrne (based in Brno) for my bakery in Brno, my competitors are Lidl and @albert_cz")
    (_, subject, anchor, brief, preset), = calls(ctx, "research_subject")
    assert subject == "@kamvbrne" and preset == "bakery"
    assert sorted(c["name"] for c in brief.competitors) == ["Lidl", "albert_cz"]   # never the subject's own @handle
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @kamvbrne (based in Brno) for my bakery in Brno")
    (_, _, _, brief, _), = calls(ctx, "research_subject")
    # no competitors named: none are invented (the preset's samples are not the owner's rivals)
    assert brief.competitors == []


async def test_an_empty_list_brings_back_the_owners_list_for_that_business(client):
    """The chat and the form send competitors: [] for a business the owner named no rivals for; going
    back to the first business brings the owner's own list back."""
    run_id = await start(client, OWN)
    fit = {**preset_brief("fitness", "en").model_dump(mode="json"), "competitors": []}
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"brief": fit, "preset": "fitness"})).status_code == 200
    assert names(await brief_of(client, run_id)) == []
    bak = {**preset_brief("bakery", "en").model_dump(mode="json"), "competitors": []}
    assert (await client.post(f"/api/runs/{run_id}/goal", json={"brief": bak, "preset": "bakery"})).status_code == 200
    assert names(await brief_of(client, run_id)) == ["Lidl", "albert_cz"]
