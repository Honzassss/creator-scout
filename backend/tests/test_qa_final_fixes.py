"""Final QA round (rule-based chat, no keys): bare dotted handles, competitor phrasing, display names."""

from __future__ import annotations

from tests.test_chat_subject import Events, SubjectCtx, calls, say


async def test_bare_dotted_handle_is_not_a_website_anchor():
    ctx, ev = SubjectCtx("en"), Events()
    text = await say(ctx, ev, "Check kuba.jidlo.brno for my bakery in Brno")
    assert not calls(ctx, "research_subject"), text
    assert "@kuba.jidlo.brno" in text

    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check Kuba for my bakery in Brno")
    text = await say(ctx, ev, "kuba.jidlo.brno")
    assert not calls(ctx, "research_subject"), text
    text = await say(ctx, ev, "Brno")
    rs = calls(ctx, "research_subject")
    assert rs and rs[0][2] and not rs[0][2].get("website"), rs


async def test_art9_mix_names_the_city_once():
    from tests.test_llm import FakeCtx

    ctx, ev = FakeCtx(), Events()
    text = await say(ctx, ev, "I run a bakery in Brno and want more women aged 25-35 who are Catholic in the shop")
    assert "The rest I can use: bakery in Brno." in text, text


def test_competitor_phrasings():
    from app.llm.chat import parse_competitors

    assert [c["name"] for c in parse_competitors("Nechci tvůrce, kteří spolupracují s Lidl.")] == ["Lidl"]
    assert parse_competitors("dunno") == [] and parse_competitors("idk") == []
    assert [c["name"] for c in parse_competitors("I would avoid Pekárna A")] == ["Pekárna A"]


async def test_subject_goal_switch_does_not_invent_preset_goal():
    ctx, ev = SubjectCtx("en"), Events()
    await say(ctx, ev, "Check @fit_peci_s_klarou for my bakery in Brno")
    await say(ctx, ev, "fitpeceni.example")
    assert calls(ctx, "research_subject")
    await say(ctx, ev, "what about my fitness studio?")
    cg = calls(ctx, "change_goal")
    assert cg, ctx.calls
    brief = cg[-1][1]
    assert brief.goal == "" and brief.budget_hint is None and brief.audience == "", brief


def test_cafe_brief_gets_neutral_criterion_reasons():
    from app.llm.chat import build_criteria_from_answers

    cs = build_criteria_from_answers({"q1": "Mám kavárnu v Brně a chci víc hostů", "q2": "studenti", "q3": "víc hostů odpoledne",
                                      "q4": "do 15 tisíc", "q5": "žádné"}, "cs")
    assert cs.brief.business_type == "kavárna"
    whys = " ".join((c.why or {}).get("cs", "") + " " + (c.why or {}).get("en", "") for c in cs.criteria)
    assert "ekárn" not in whys and "bakery" not in whys.lower() and "pečivo" not in whys, whys
    # the bakery itself keeps its own reasons
    cs = build_criteria_from_answers({"q1": "Mám pekárnu v Brně", "q2": "rodiny", "q3": "víc lidí", "q4": "do 20 tisíc",
                                      "q5": "žádné"}, "cs")
    assert any("ekárn" in (c.why or {}).get("cs", "") for c in cs.criteria)


async def test_goal_switch_from_an_english_tab_keeps_the_czech_brief():
    ctx, ev = SubjectCtx("cs"), Events()
    await say(ctx, ev, "Prověř @fit_peci_s_klarou pro moji pekárnu v Brně")
    await say(ctx, ev, "fitpeceni.example")
    assert calls(ctx, "research_subject")
    await say(ctx, ev, "Změnit cíl na fitness studio v Brně")
    ctx.lang = "en"   # a second tab with the English UI on the same run
    await say(ctx, ev, "What about my bakery in Brno instead?")
    brief = calls(ctx, "change_goal")[-1][1]
    assert brief.business_type == "pekárna" and brief.lang == "cs", brief
