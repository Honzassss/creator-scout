"""Goal-conditioned report rendering (rounds/report.py) and the anchor-based identity verdict
(compute/identity.py). render_report is pure: same inputs -> identical Report; a goal switch
re-renders from VettingData without fetch or LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.compute.identity import anchor_signals, identity_verdict, look_alike_signals, match_identity
from app.events import noop_emit
from app.models import Anchor, Post, Profile, SubjectSpec, make_source_ref
from app.presets import get_preset
from app.rounds import engine
from app.rounds.report import brief_key, diff_reports, preset_for_brief, render_report
from app.sources.factory import get_provider
from app.store import get_store

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def src(url: str, platform: str = "instagram"):
    return make_source_ref(url=url, platform=platform, mode="mock", fetched_at=NOW)


def prof(handle: str, platform: str = "instagram", *, bio: str = "", urls: list[str] | None = None,
         name: str = "Klára Veselá", region: str | None = None, posts: list[Post] | None = None) -> Profile:
    url = f"https://{platform}.example/{handle}"
    return Profile(handle=handle, platform=platform, url=url, display_name=name, bio=bio, external_urls=urls or [],
                   region=region, latest_posts=posts or [], source=src(url, platform))


def post(pid: str, caption: str = "", location: str | None = None) -> Post:
    url = f"https://instagram.example/p/{pid}"
    return Post(id=pid, platform="instagram", url=url, author_handle="x", created_at=NOW, caption=caption,
                location_name=location, source=src(url))


async def vetted(handle: str, preset: str = "bakery", anchor: Anchor | None = None, lang: str = "en"):
    crit = get_preset(preset, lang)  # type: ignore[arg-type]
    run = get_store().create(crit)
    run.mode = "subject"
    run.subject = SubjectSpec(raw=f"@{handle}", handle=handle, anchor=anchor or Anchor())
    await engine.run_subject(run, get_provider(), noop_emit)
    c = run.candidates[run.subject.candidate_id]
    assert c.report is not None and c.vetting_data is not None
    return run, c


# ---------------------------------------------------------------------------------------------
# Determinism + goal switch
# ---------------------------------------------------------------------------------------------


async def test_render_is_deterministic_and_round_trips_goals():
    anchor = Anchor(website="fitpeceni.example")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    bakery, fitness = get_preset("bakery", "en"), get_preset("fitness", "en")
    a = render_report(bakery, c, c.vetting_data, anchor=anchor)
    b = render_report(bakery, c, c.vetting_data, anchor=anchor)
    assert a.model_dump_json() == b.model_dump_json()
    assert a.model_dump_json() == c.report.model_dump_json()          # what the vetting stored
    f = render_report(fitness, c, c.vetting_data, anchor=anchor, previous=a)
    back = render_report(bakery, c, c.vetting_data, anchor=anchor, previous=f)
    assert back.model_dump_json(exclude={"last_diff"}) == a.model_dump_json(exclude={"last_diff"})
    assert f.last_diff is not None and back.last_diff is not None
    assert set(f.last_diff.added) == set(back.last_diff.removed)
    same = render_report(bakery, c, c.vetting_data, anchor=anchor, previous=a)
    assert same.last_diff.summary["en"] == "The report is the same for this goal."
    assert same.last_diff.added == same.last_diff.removed == same.last_diff.moved_up == []


async def test_goal_switch_changes_content_not_only_headings():
    anchor = Anchor(website="fitpeceni.example")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    a = render_report(get_preset("bakery", "en"), c, c.vetting_data, anchor=anchor)
    f = render_report(get_preset("fitness", "en"), c, c.vetting_data, anchor=anchor, previous=a)
    fa, ff = {x.id: x for x in a.findings}, {x.id: x for x in f.findings}
    assert fa["f:fit:topics"].text["en"] != ff["f:fit:topics"].text["en"]
    assert "i:competitor" not in fa and ff["i:competitor"].tier == "key"
    assert any(e.is_competitor for e in f.collab_timeline) and not any(e.is_competitor for e in a.collab_timeline)
    assert a.questions != f.questions and a.outreach_draft != f.outreach_draft
    assert a.checks["no_competitor_collab"] == "pass" and f.checks["no_competitor_collab"] == "fail"
    assert {"criterion_id": "no_competitor_collab", "status": ["pass", "fail"]} in f.last_diff.checks_changed
    assert f.rendered_for["brief_key"] == brief_key(get_preset("fitness", "en").brief) != a.rendered_for["brief_key"]


async def test_findings_carry_goal_layer_and_hard_lines():
    anchor = Anchor(website="fitpeceni.example")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    rep = c.report
    ids = {f.id for f in rep.findings}
    for f in rep.findings:
        assert f.confidence in ("high", "medium", "low") and f.confidence_basis and f.confidence_basis["en"]
        assert f.tier in ("key", "related", "less") and f.why_it_matters and f.aspect
        if f.kind == "fact":
            assert f.sources
        if f.kind == "inference":
            assert set(f.based_on) <= ids and f.confidence != "high"
    # goal checks: one per enabled criterion
    checks = [f for f in rep.findings if f.section == "goal"]
    assert len(checks) == sum(1 for cr in run.criteria.criteria if cr.enabled)
    # structural gaps are high-confidence statements, demographics is always visible
    gaps = {f.id: f for f in rep.findings if f.kind == "gap"}
    assert gaps["g:demographics"].confidence == "high" and gaps["g:demographics"].tier != "less"
    assert "g:demographics" not in rep.less_relevant
    # display order: expanded items first, then the collapsed ones
    pos = {f.id: i for i, f in enumerate(rep.findings)}
    if rep.less_relevant:
        first_less = min(pos[i] for i in rep.less_relevant if i in pos)
        assert all(f.tier == "less" for f in rep.findings[first_less:])
    assert rep.summary and rep.summary["en"].startswith("Key for this goal")
    text = rep.model_dump_json().lower()
    for word in ("trustworthy", "overall score", "risk level"):
        assert word not in text


async def test_czech_render_uses_czech_texts():
    run, c = await vetted("toman_ochutnava", anchor=Anchor(city="Brno"), lang="cs")
    rep = c.report
    assert rep.identity_verdict.text["cs"].startswith("Jsme si jistí, že @toman_ochutnava")
    assert rep.rendered_for["business_type"] == "pekárna"
    assert any("pekárna" in q["cs"] for q in rep.questions)
    assert rep.news and rep.news[0].attribution.startswith("píše ")


def test_preset_for_brief_keywords():
    assert preset_for_brief(get_preset("bakery").brief) == "bakery"
    assert preset_for_brief(get_preset("fitness", "en").brief) == "fitness"


# ---------------------------------------------------------------------------------------------
# Anchor signals + verdict rules (pure)
# ---------------------------------------------------------------------------------------------


def test_anchor_signals_website_company_city():
    p = prof("klara", bio="Peču v Brně | IČO 01234567", urls=["https://www.fitpeceni.example/shop"],
             posts=[post("a", "Ráno v Brně", "Brno, Zelný trh")])
    sig = dict(anchor_signals(p, list(p.latest_posts), Anchor(city="Brno", website="fitpeceni.example",
                                                               company_id="01234567"), lang="en"))
    assert set(sig) == {"anchor_website", "anchor_company_id", "anchor_city_bio", "anchor_city_posts"}
    assert all(s.supports and s.source is not None and s.source.quote for s in sig.values())
    assert sig["anchor_website"].signal == "the website fitpeceni.example is on the profile"
    # company ID without leading zeros in the text still matches; another number does not
    p2 = prof("x", bio="IČ: 1234567")
    assert "anchor_company_id" in dict(anchor_signals(p2, [], Anchor(company_id="01234567"), lang="en"))
    p3 = prof("x", bio="tel 912345678")
    assert "anchor_company_id" not in dict(anchor_signals(p3, [], Anchor(company_id="12345678"), lang="en"))


def test_anchor_city_other_and_most_is_skipped():
    p = prof("kuba", bio="Jedlo a cestovanie | Bratislava")
    sig = anchor_signals(p, [], Anchor(city="Brno"), lang="en")
    assert [k for k, _ in sig] == ["anchor_city_other"] and not sig[0][1].supports
    assert "Bratislava" in sig[0][1].signal
    p2 = prof("x", bio="the most delicious bread")
    assert anchor_signals(p2, [], Anchor(city="Brno"), lang="en") == []
    assert anchor_signals(p2, [], None, lang="en") == []


def test_look_alike_in_another_city_is_rejected():
    primary = prof("kuba.jidlo.brno", bio="Jím se Brnem", name="Jakub Horák")
    other = prof("kuba_jidlo", "tiktok", bio="Jedlo a cestovanie | Bratislava", name="Jakub Horák")
    assert look_alike_signals(other, Anchor(city="Brno"), lang="en")[0].supports is False
    with_anchor = match_identity(primary, [other], lang="en", anchor=Anchor(city="Brno"))
    assert with_anchor[0].status == "rejected"
    # a linked account is never a look-alike, whatever its bio says
    linked = prof("kuba_jidlo", "tiktok", bio="IG @kuba.jidlo.brno | Bratislava", name="Jakub Horák")
    primary2 = prof("kuba.jidlo.brno", bio="Jím se Brnem | TikTok @kuba_jidlo", name="Jakub Horák")
    assert match_identity(primary2, [linked], lang="en", anchor=Anchor(city="Brno"))[0].status == "matched"


def _verdict(p: Profile, anchor: Anchor | None, cross: list[Profile] = ()):
    sig = anchor_signals(p, list(p.latest_posts), anchor, lang="en")
    ident = match_identity(p, list(cross), lang="en", anchor=anchor)
    return identity_verdict(p, anchor, sig, ident, [], [], lang="en")


def test_verdict_rules():
    site = prof("klara", urls=["https://fitpeceni.example"])
    assert _verdict(site, Anchor(website="fitpeceni.example")).status == "confirmed"
    city = prof("klara", bio="Peču v Brně")
    assert _verdict(city, Anchor(city="Brno")).status == "likely"
    tt = prof("klara", "tiktok", bio="IG @klara", urls=["https://fitpeceni.example"])
    city_linked = prof("klara", bio="Peču v Brně | TikTok @klara", urls=["https://fitpeceni.example"])
    assert _verdict(city_linked, Anchor(city="Brno"), [tt]).status == "confirmed"
    assert _verdict(city_linked, None, [tt]).status == "likely"
    other = prof("klara", bio="Peču v Ostravě")
    v = _verdict(other, Anchor(city="Brno"))
    assert v.status == "uncertain" and v.contradicting
    assert v.text["en"].startswith("We could not confirm @klara is the creator you mean:")
    assert "another anchor" in v.text["en"]
    nothing = prof("klara", bio="Pečení")
    v2 = _verdict(nothing, Anchor(website="elsewhere.example"))
    assert v2.status == "uncertain" and "nothing on the profile matches the anchor" in v2.text["en"]
    assert _verdict(nothing, None).status == "uncertain"
    nf = identity_verdict(None, None, [], [], [], [], lang="en", handle="nobody", tried=["instagram", "tiktok"])
    assert nf.status == "not_found" and nf.text["en"] == "We found no public profile @nobody on Instagram or TikTok."
    lk = _verdict(city, Anchor(city="Brno", website="fitpeceni.example"))
    assert lk.status == "likely" and "was not found on the profile" in lk.text["en"]


@pytest.mark.parametrize("anchor", [None, Anchor()])
async def test_render_without_anchor(anchor):
    run, c = await vetted("brnenska_snidane", anchor=anchor)
    rep = render_report(run.criteria, c, c.vetting_data, anchor=anchor)
    assert rep.identity_verdict.status in ("likely", "uncertain")      # no anchor: never "confirmed"
    assert not [f for f in rep.findings if f.id.startswith(("f:anchor:", "g:anchor:"))]
    assert diff_reports(rep, rep).summary["en"] == "The report is the same for this goal."


# ---------------------------------------------------------------------------------------------
# With an LLM: the 5 vetting requests run once; their text is stored and reused per goal
# ---------------------------------------------------------------------------------------------


async def test_llm_text_is_stored_once_and_goal_switch_makes_no_request(monkeypatch):
    from app.llm import client as llm_client
    from app.llm import vetting

    calls: list[str] = []
    draft_cs = ("Dobrý den, " + "rádi bychom s vámi spolupracovali na kampani pro naši pekárnu v Brně. " * 3).strip()
    draft_en = ("Hello, " + "we would love to work with you on a campaign for our bakery in Brno. " * 3).strip()

    async def fake_structured(schema, *, system, user, model=None, max_tokens=1000, effort="low", task=""):
        calls.append(task)
        name = schema.__name__
        if name == "_LLMClaims":
            return schema(claims=[])
        if name == "_NewsLabels":
            return schema(labels=[{"i": 0, "label": "neutral"}])
        if name == "_Skeptic":
            return schema(notes=[{"ref_id": "", "action": "note", "note_cs": "Ověřte si rozsah spolupráce.",
                                  "note_en": "Check how far the collaboration goes."}])
        if name == "_Questions":
            return schema(questions=[{"gap_id": "g:reach", "q_cs": "Jaký dosah mají vaše stories?",
                                      "q_en": "What reach do your stories get?"}])
        if name == "_Draft":
            return schema(cs=draft_cs, en=draft_en)
        return None

    monkeypatch.setattr(llm_client, "structured", fake_structured)
    anchor = Anchor(website="fitpeceni.example")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    vet_calls = [t for t in calls if t in ("claims", "news", "skeptic", "questions", "outreach")]
    assert sorted(vet_calls) == ["claims", "news", "outreach", "questions", "skeptic"]      # at most 5
    data = c.vetting_data
    bk = brief_key(run.criteria.brief)
    assert data.llm_claims == [] and data.llm_questions and data.llm_by_goal[bk]["outreach"]["en"] == draft_en
    assert data.llm_by_goal[bk]["skeptic"] and data.modes["news"] == "llm"
    rep = c.report
    assert rep.outreach_draft["en"] == draft_en
    assert {"cs": "Ověřte si rozsah spolupráce.", "en": "Check how far the collaboration goes."} in rep.skeptic_notes
    assert any(q["en"] == "What reach do your stories get?" for q in rep.questions)
    assert rep.text_source == {"claims": "llm+rules", "news": "llm", "skeptic": "llm+rules",
                               "questions": "llm+template", "outreach": "llm"}

    # goal switch: re-render only; the bakery-specific LLM draft and skeptic notes are not reused
    n = len(calls)
    diff = engine.recompute(run, get_preset("fitness", "en"))
    assert len(calls) == n
    fit = c.report
    assert fit.outreach_draft == vetting.outreach_template(run.criteria.brief, c)
    assert fit.text_source["outreach"] == "template" and fit.text_source["questions"] == "llm+template"
    assert diff["report_diffs"][0].outreach_changed is True
    # and back: the stored bakery text is used again
    engine.recompute(run, get_preset("bakery", "en"))
    assert len(calls) == n and c.report.outreach_draft["en"] == draft_en


async def test_snapshot_round_trip_keeps_vetting_data(tmp_path):
    from app.store import RunStore

    run, c = await vetted("kuba.jidlo.brno", anchor=Anchor(city="Brno"))
    store = RunStore(tmp_path)
    store.save(run)
    loaded = RunStore(tmp_path)
    assert loaded.load_all() == 1
    again = loaded.get(run.id)
    c2 = again.candidates[c.id]
    assert c2.vetting_data == c.vetting_data and c2.report == c.report
    # re-rendering the loaded snapshot for the same goal gives the same report
    assert render_report(again.criteria, c2, c2.vetting_data, anchor=again.subject.anchor).model_dump_json() == \
        c.report.model_dump_json()
