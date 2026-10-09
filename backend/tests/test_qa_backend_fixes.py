"""QA pass before the freeze (9 Oct 2026): backend fixes for the discovery, subject, chat and
error-handling findings (topic share consistency, anchor-city contradiction, competitor parsing,
busy-run chat tools, refusal-only criteria changes, ...)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import main
from app.compute.identity import anchor_signals
from app.llm.chat import _business_from, build_criteria_from_answers, describe_params, parse_competitors
from app.models import Anchor, Post, Profile, make_criterion, make_source_ref

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def src(url: str, platform: str = "instagram", **kw):
    return make_source_ref(url=url, platform=platform, mode="cache", fetched_at=NOW, **kw)


def post(i: str, caption: str = "", *, location: str | None = None) -> Post:
    url = f"https://www.instagram.com/p/{i}/"
    return Post(id=i, platform="instagram", url=url, author_handle="kam", created_at=NOW - timedelta(days=1),
                caption=caption, location_name=location, source=src(url, id=f"ig:post:{i}"))


def profile(bio: str = "") -> Profile:
    url = "https://www.instagram.com/kam/"
    return Profile(handle="kam", platform="instagram", url=url, bio=bio, source=src(url, id="ig:profile:kam"))


@pytest.fixture
async def client():
    await main.reset_runtime_state()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        yield c
    await main.reset_runtime_state()


async def subject(client, body: dict) -> tuple[dict, dict]:
    r = await client.post("/api/subject", json=body)
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    await main.wait_idle(rid, timeout=120)
    run = (await client.get(f"/api/runs/{rid}")).json()
    cid = run["subject"]["candidate_id"]
    return run, run["candidates"][cid]


# --- topic share: the content finding counts what the round-2 check counts ----------------------

async def test_fit_topics_finding_matches_the_round2_check(client):
    _, cand = await subject(client, {"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"}, "preset": "bakery",
                                     "lang": "en"})
    crit = next(r for r in cand["results"] if r["criterion_id"].startswith("topic_share") or "topic" in r["criterion_id"])
    fit = next(f for f in cand["report"]["findings"] if f["id"] == "f:fit:topics")
    value = crit["value"]["en"] if isinstance(crit["value"], dict) else crit["value"]
    k_total = " ".join(value.split()[:3])            # "18 of 20"
    assert fit["text"]["en"].startswith(k_total), (value, fit["text"]["en"])
    assert "local tips" not in fit["text"]["en"]


def test_topic_proposal_says_local_tips_do_not_count():
    c = make_criterion("topic_share", {"topics": ["food", "recipes", "restaurants_cafes", "local_tips"], "min_share": 0.4})
    en = describe_params(c, "en")
    assert "do not count toward the share" in en and en.index("local") > en.index("(")


def test_format_and_ads_descriptions_read_naturally():
    f = make_criterion("formats", {"formats": ["reel", "video"], "min_share": 0.2})
    assert "krátká videa, videa" not in describe_params(f, "cs") and "short videos, videos" not in describe_params(f, "en")
    d = make_criterion("discloses_ads", {"max_undisclosed": 0})
    assert describe_params(d, "cs") == "žádná neoznačená reklama" and describe_params(d, "en") == "no undisclosed ads"


# --- identity: a bio in another city contradicts the anchor even with a few anchor-city posts ----

def test_bio_in_another_city_contradicts_despite_a_few_anchor_posts():
    prof = profile("Brno, jak ho (ne)znáš")
    posts = [post(f"b{i}", location="Brno, Czech Republic") for i in range(10)] + \
            [post("p1", "Výlet do Prahy"), post("p2", "Praha je krásná"), post("p3", "Zase Praha")]
    sigs = anchor_signals(prof, posts, Anchor(city="Praha"), lang="en")
    kinds = [k for k, _ in sigs]
    assert "anchor_city_posts" in kinds and "anchor_city_other" in kinds
    other = next(s for k, s in sigs if k == "anchor_city_other")
    assert not other.supports and "Brno" in other.signal


def test_post_locations_dominated_by_another_city_contradict():
    prof = profile("Jídlo a výlety")
    posts = [post(f"b{i}", location="Brno") for i in range(8)] + [post("p1", "Praha dnes")]
    kinds = [k for k, _ in anchor_signals(prof, posts, Anchor(city="Praha"), lang="en")]
    assert "anchor_city_other" in kinds
    # a balanced account is not contradicted
    posts = [post(f"b{i}", location="Brno") for i in range(2)] + [post(f"p{i}", "Praha dnes") for i in range(3)]
    kinds = [k for k, _ in anchor_signals(prof, posts, Anchor(city="Praha"), lang="en")]
    assert "anchor_city_other" not in kinds


# --- competitor parsing ------------------------------------------------------------------------

KNOWN = [{"name": "Pekárna B", "handles": ["pekarna_b"]}, {"name": "Chlebárna Vlnka", "handles": ["chlebarna_vlnka"]}]


@pytest.mark.parametrize("text, names", [
    ("About 20000 CZK. Competitor: Pekárna Kabát, do not want creators working with them.", ["Pekárna Kabát"]),
    ("About 15000 CZK, competitors are Pekárna A and Breadway", ["Pekárna A", "Breadway"]),
    ("about 15000 CZK, I would avoid Pekárna A", ["Pekárna A"]),
    ("Chlebárna Vlna", ["Chlebárna Vlnka"]),
    ("pekarna b", ["Pekárna B"]),
    ("no", []), ("I don't know yet", []), ("not sure yet", []), ("budget is low", []),
    ("small budget, no idea about competitors", []), ("what did I say?", []), ("Instagram and TikTok", []),
])
def test_parse_competitors(text, names):
    assert [c["name"] for c in parse_competitors(text, KNOWN)] == names


def test_cafe_brief_keeps_the_owners_business():
    cs = build_criteria_from_answers({"q1": "Mám kavárnu v Brně a chci víc hostů", "q2": "studenti", "q3": "víc hostů odpoledne",
                                      "q4": "do 15 tisíc", "q5": "žádné"}, "cs")
    assert cs.brief.business_type == "kavárna" and cs.brief.competitors == []
    cs = build_criteria_from_answers({"q1": "Mám pekárnu v Brně", "q2": "rodiny", "q3": "víc lidí", "q4": "10 tisíc, žádné"}, "cs")
    assert cs.brief.business_type == "pekárna"


def test_business_from_strips_the_search_lead():
    assert _business_from("Ahoj, hledám influencera pro kavárnu v Brně", "cs") == "kavárna"
    assert _business_from("actually I run a yoga studio, competitors are YogaMax", "en") == "yoga studio"


# --- chat: handles written without @ ---------------------------------------------------------

async def test_handle_reply_without_at_is_accepted():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check Ondřej Toman for my bakery in Brno")
    assert "@handle" in text or "account" in text
    text = await say(ctx, ev, "toman_ochutnava on tiktok")
    assert "Without the @handle" not in text
    assert "@toman_ochutnava" in text or calls(ctx, "research_subject")


async def test_opening_message_with_a_bare_handle_starts_the_subject_flow():
    from tests.test_chat_subject import Events, SubjectCtx, say

    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check toman_ochutnava for my bakery in Brno")
    assert "@toman_ochutnava" in text and "four short questions" not in text


# --- chat sessions: a run_id with no bound session never joins another tab's interview ----------

async def chat(client, body: dict) -> tuple[list, str]:
    from tests.test_api import parse_sse

    r = await client.post("/api/chat", json=body)
    evs = parse_sse(r.text)
    text = "".join(d["text"] for _, e, d in evs if e == "chat.delta")
    return evs, text


async def test_unbound_run_id_gets_its_own_chat_session(client):
    evs, _ = await chat(client, {"message": "Mám kavárnu v Brně a chci víc hostů", "lang": "cs", "reset": True})
    tab_a = evs[-1][2]["chat_id"]
    r = await client.post("/api/runs", json={"preset": "fitness", "up_to": 3})
    rid = r.json()["run_id"]
    await main.wait_idle(rid)
    evs, text = await chat(client, {"message": "Why did the others drop out?", "lang": "en", "run_id": rid})
    assert evs[-1][2]["chat_id"] != tab_a and evs[-1][2]["run_id"] == rid
    assert "Co má kampaň udělat" not in text and "Díky" not in text
    assert main._sessions[tab_a].run_id is None       # tab A's interview is untouched


# --- chat: criteria edited on the board before the run are the ones the chat runs -------------

async def test_chat_run_uses_board_criteria(client):
    msgs = ["I run a bakery in Brno and want more people in the shop.", "Families and office workers nearby.",
            "More people in the shop on weekday mornings.", "About 20000 CZK, no competitors."]
    chat_id = None
    criteria = None
    for m in msgs:
        evs, _ = await chat(client, {"message": m, "lang": "en", "chat_id": chat_id})
        chat_id = evs[-1][2]["chat_id"]
        criteria = next((d["criteria"] for _, e, d in reversed(evs) if e == "criteria.updated"), criteria)
    assert criteria is not None
    fr = next(c for c in criteria["criteria"] if c["kind"] == "followers_range")
    fr["params"]["max"] = 30000
    evs, _ = await chat(client, {"message": "Yes, start.", "lang": "en", "chat_id": chat_id, "criteria": criteria})
    rid = evs[-1][2]["run_id"]
    assert rid
    await main.wait_idle(rid)
    run = (await client.get(f"/api/runs/{rid}")).json()
    fr = next(c for c in run["criteria"]["criteria"] if c["kind"] == "followers_range")
    assert fr["params"]["max"] == 30000


# --- a run whose process died mid-work is reported as interrupted ----------------------------

async def test_interrupted_run_is_reported(client):
    from tests.test_api import parse_sse

    r = await client.post("/api/subject", json={"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"},
                                                "preset": "bakery", "lang": "en"})
    rid = r.json()["run_id"]
    await main.wait_idle(rid)
    main._mark_busy(rid, "subject")          # what a killed process leaves behind
    main.get_bus().clear(rid)
    st = (await client.get(f"/api/runs/{rid}/status")).json()
    assert st["busy"] is False and st["interrupted"] is True and "interrupted" in st["error"]
    evs = parse_sse((await client.get(f"/api/runs/{rid}/events", params={"follow": False})).text)
    assert evs[-1][1] == "error" and evs[-1][2]["interrupted"] is True
    run = (await client.get(f"/api/runs/{rid}")).json()
    assert run["log"][-1]["text"].startswith("Interrupted: the server stopped during the creator check")
    assert not main._busy_marker(rid).exists()


async def test_finished_run_leaves_no_busy_marker(client):
    r = await client.post("/api/subject", json={"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"}, "preset": "bakery"})
    rid = r.json()["run_id"]
    await main.wait_idle(rid)
    assert not main._busy_marker(rid).exists()
    assert (await client.get(f"/api/runs/{rid}/status")).json()["interrupted"] is False


# --- English mock log lines are whole English sentences --------------------------------------

async def test_english_mock_log_lines(client):
    run, _ = await subject(client, {"subject": "@brnenska_snidane", "anchor": {"city": "Brno"}, "preset": "bakery",
                                    "lang": "en"})
    text = " | ".join(e["text"] for e in run["log"])
    assert "možné" not in text and "„" not in text.split("News")[0] and " 1 articles" not in text
    assert "possible profiles of the same creator" in text or "possible profile of the same creator" in text
    news = [e for e in run["log"] if e["text"].startswith("News ")]
    assert news and all(e.get("mode") for e in news)


async def test_owner_language_switch_wins_over_the_detected_language(client):
    evs, _ = await chat(client, {"message": "Ahoj, mám pekárnu v Brně a chci víc lidí v obchodě", "lang": "en", "reset": True})
    assert evs[-1][2]["lang"] == "cs"
    cid = evs[-1][2]["chat_id"]
    # the UI followed the guide (cs), then the owner clicked English
    evs, text = await chat(client, {"message": "Families with kids and students who live nearby", "lang": "en", "chat_id": cid})
    assert evs[-1][2]["lang"] == "en" and "Díky" not in text


async def test_english_goal_switch_in_a_czech_session_keeps_the_czech_business():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("cs"), Events()
    await say(ctx, ev, "Prověř @fit_peci_s_klarou (fitpeceni.example) pro moje fitness studio v Brně")
    await say(ctx, ev, "a co pro moji pekárnu v Brně?")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "pekárna"


async def test_goal_switch_to_a_cafe_in_prague_drops_the_old_audience():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou (fitpeceni.example) for my bakery in Brno")
    await say(ctx, ev, "change the goal to a café in Prague")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "café" and brief.city == "Praha" and "Brno" not in (brief.audience or "")


async def test_chat_subject_brief_has_no_invented_goal_or_budget():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    await say(ctx, ev, "fitpeceni.example")
    (_, _, _, brief, _), = calls(ctx, "research_subject")
    assert brief.business_type == "bakery" and "sourdough" not in (brief.goal or "") and brief.budget_hint is None
    assert brief.audience == ""


# --- report diff: each change once, Czech grammar, key summary punctuation ---------------------

async def test_goal_switch_report_diff_lists_each_change_once(client):
    from app.rounds.report import _cs_genitive

    run, cand = await subject(client, {"subject": "@kuba.jidlo.brno", "anchor": {"city": "Brno"}, "preset": "bakery",
                                       "lang": "cs"})
    assert ".;" not in cand["report"]["summary"]["cs"] and ".;" not in cand["report"]["summary"]["en"]
    r = await client.post(f"/api/runs/{run['id']}/goal", json={"preset": "fitness"})
    assert r.status_code == 200, r.text
    rd = r.json()["report_diffs"][0]
    assert not set(rd["moved_down"]) & set(rd["collapsed"])
    assert "z pekárna" not in rd["summary"]["cs"] and "kontrol dopadlo" not in rd["summary"]["cs"].replace("5 kontrol", "")
    assert rd["summary"]["cs"].startswith("Cíl změněn z pekárny na")
    assert _cs_genitive("fitness studio") == "fitness studia" and _cs_genitive("malá kavárna") is None
    run = (await client.get(f"/api/runs/{run['id']}")).json()
    assert any(e["text"].startswith("Cíl změněn: pekárna → fitness studio") for e in run["log"])
    assert any("přepočítán pro nový cíl" in e["text"] for e in run["log"])


def test_less_relevant_reason_does_not_say_not_a_competitor():
    import inspect

    from app.rounds import report

    src = inspect.getsource(report._why)
    assert "the brand is not a competitor" not in src and "not on your competitor list" in src


async def test_goal_switch_phrasings():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou (fitpeceni.example) for my bakery in Brno")
    await say(ctx, ev, "what about my fitness studio?")
    await say(ctx, ev, "switch back to bakery")
    assert calls(ctx, "change_goal")[-1][1].business_type == "bakery"
    await say(ctx, ev, "actually I run a yoga studio, competitors are YogaMax")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "yoga studio" and [c["name"] for c in brief.competitors] == ["YogaMax"]


async def test_why_questions_resolve_urls_names_and_rounds():
    from tests.test_chat_subject import Events, SubjectCtx, say

    ctx, ev = SubjectCtx("en"), Events()
    for msg in ("demo", "yes"):
        await say(ctx, ev, msg)
    text = await say(ctx, ev, "why were so many eliminated in round 2?")
    assert "Round 2: entered" in text and "@in" not in text
    text = await say(ctx, ev, "why was https://www.instagram.com/travel_tom/ eliminated")
    assert "@https" not in text and "travel_tom" in text


async def test_refused_part_of_the_first_message_keeps_the_business(client):
    evs, text = await chat(client, {"message": "I run a bakery in Brno and want more women aged 25-35 who are Catholic in the shop",
                                    "lang": "en", "reset": True})
    assert "special-category" in text or "Relig" in text
    assert "What do you sell" not in text and "bakery" in text
    cid = evs[-1][2]["chat_id"]
    answers = ["Young mothers", "More people in the shop", "10000 CZK, no competitors"]
    for a in answers:
        evs, text = await chat(client, {"message": a, "lang": "en", "chat_id": cid})
    crit = next(d["criteria"] for _, e, d in reversed(evs) if e == "criteria.updated")
    assert crit["brief"]["business_type"] == "bakery" and crit["brief"]["city"] == "Brno"
    assert crit["brief"]["audience"] == "Young mothers" and "Catholic" not in str(crit["brief"])


async def test_business_switch_during_the_interview(client):
    evs, _ = await chat(client, {"message": "I have a bakery in Brno", "lang": "en", "reset": True})
    cid = evs[-1][2]["chat_id"]
    evs, text = await chat(client, {"message": "what about my fitness studio?", "lang": "en", "chat_id": cid})
    assert "fitness studio" in text and "Thanks." not in text
    for a in ["Students", "More trial classes", "10000 CZK, no competitors"]:
        evs, text = await chat(client, {"message": a, "lang": "en", "chat_id": cid})
    crit = next(d["criteria"] for _, e, d in reversed(evs) if e == "criteria.updated")
    assert crit["brief"]["business_type"] == "fitness studio" and crit["brief"]["audience"] == "Students"
    assert crit["brief"]["city"] == "Brno"


async def test_subject_mid_interview_reuses_the_business():
    from tests.test_chat_subject import Events, SubjectCtx, calls, say

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "I have a bakery in Brno")
    await say(ctx, ev, "students")
    await say(ctx, ev, "check @toman_ochutnava")
    text = await say(ctx, ev, "Brno")
    assert "What is your business" not in text
    (_, _s, anchor, brief, preset), = calls(ctx, "research_subject")
    assert preset == "bakery" and brief.city == "Brno" and anchor == {"city": "Brno"}


def test_overall_rating_and_good_person_are_refused():
    from app.llm.sensitive import refusal_reason

    assert refusal_reason("how would you rate him overall?") and refusal_reason("is he a good person")
    assert refusal_reason("what is the engagement rate?") is None


async def test_what_we_check_on_a_subject_run_describes_the_subject_report():
    from tests.test_chat_subject import Events, SubjectCtx, say

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou (fitpeceni.example) for my bakery in Brno")
    text = await say(ctx, ev, "what do you check and what not?")
    assert "Identity" in text and "four rounds" not in text and "no score" in text


# --- report wording: discovery identity, namesake gloss, last post, names, excerpts ------------

async def test_discovery_report_identity_text_asks_for_no_anchor(client):
    r = await client.post("/api/runs", json={"preset": "bakery", "up_to": 3})
    rid = r.json()["run_id"]
    await main.wait_idle(rid)
    run = (await client.get(f"/api/runs/{rid}")).json()
    fin = [c["id"] for c in run["candidates"].values() if c["status"] == "finalist"][:2]
    assert fin
    v = await client.post(f"/api/runs/{rid}/vet", json={"candidate_ids": fin})
    assert v.status_code == 200, v.text
    await main.wait_idle(rid)
    run = (await client.get(f"/api/runs/{rid}")).json()
    for cid in fin:
        text = run["candidates"][cid]["report"]["identity_verdict"]["text"]
        assert "give another anchor" not in text["en"] and "no anchor is needed" in text["en"]
        assert "zadejte jinou kotvu" not in text["cs"]


def test_namesake_context_is_glossed_in_english():
    from app.compute.identity import _ctx_label

    assert _ctx_label("podnikatel", "en") == "businessman" and _ctx_label("podnikatelka", "en") == "businesswoman"
    assert _ctx_label("zlin", "en") == "in Zlín" and _ctx_label("zlin", "cs") == "Zlín"
    assert _ctx_label("podnikatel", "cs") == "podnikatel"


def test_display_name_tagline_and_caption_excerpt():
    from app.models import greeting_name, person_name
    from app.rounds.common import _caption_excerpt

    assert greeting_name("Kam v Brně | ty nejlepší tipy kam v Brně") == "Kam v Brně"
    assert greeting_name("Anna-Marie Nová") == "Anna-Marie Nová"
    # matching and the (recorded) news query keep the full name
    assert person_name("Kam v Brně | tipy (MOCK)") == "Kam v Brně | tipy"
    ex = _caption_excerpt("slovo " * 40 + "Nejradši mám, když mi řeknete")
    assert ex.endswith("…") and not ex.endswith("ře…") and len(ex) <= 140


async def test_refusal_on_a_subject_run_does_not_rerender_or_store_the_question(client):
    evs, _ = await chat(client, {"message": "Check @fit_peci_s_klarou for my bakery in Brno", "lang": "en", "reset": True})
    cid = evs[-1][2]["chat_id"]
    evs, _ = await chat(client, {"message": "fitpeceni.example", "lang": "en", "chat_id": cid})
    rid = evs[-1][2]["run_id"]
    await main.wait_idle(rid)
    n_log = len((await client.get(f"/api/runs/{rid}")).json()["log"])
    for q in ("is she religious?", "is she religious?", "is she gay?"):
        evs, text = await chat(client, {"message": q, "lang": "en", "chat_id": cid})
        assert not [e for _, e, _d in evs if e in ("report.diff", "diff")]
    run = (await client.get(f"/api/runs/{rid}")).json()
    assert not any("re-rendered" in e["text"] for e in run["log"][n_log:])
    refused = run["criteria"]["refused"]
    assert refused and all("religious" not in r["text"] and "gay" not in r["text"] for r in refused)
    assert len(refused) == 2      # one per reason, the repeated question is not added twice


async def test_run_chat_history_endpoint(client):
    evs, _ = await chat(client, {"message": "demo", "lang": "en", "reset": True})
    cid = evs[-1][2]["chat_id"]
    evs, _ = await chat(client, {"message": "yes", "lang": "en", "chat_id": cid})
    rid = evs[-1][2]["run_id"]
    await main.wait_idle(rid)
    h = (await client.get(f"/api/runs/{rid}/chat")).json()
    assert h["chat_id"] == cid and [m["role"] for m in h["messages"]][:2] == ["user", "assistant"]
    assert h["messages"][0]["text"] == "demo"


async def test_turning_a_criterion_off_says_who_came_back(client):
    evs, _ = await chat(client, {"message": "demo", "lang": "en", "reset": True})
    cid = evs[-1][2]["chat_id"]
    evs, _ = await chat(client, {"message": "yes", "lang": "en", "chat_id": cid})
    await main.wait_idle(evs[-1][2]["run_id"])
    evs, text = await chat(client, {"message": "turn off format", "lang": "en", "chat_id": cid})
    assert "is off" in text and "came back: @" in text
