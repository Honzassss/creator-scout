"""Fixes from the live recording (9. 10. 2026): English run logs, the model named on every LLM step,
the report diff naming demoted findings and skeptic-note changes, consistent news counts."""

from __future__ import annotations

import json

import httpx
import pytest

from app import config
from app.events import _log_text, bind_emit, emit_log, to_en, tr
from app.llm import openrouter
from app.llm import client as llm_client
from app.llm.sensitive import _Flags

PRIMARY = "dots-studio/dots-3-note-preview:free"
FLAGS = {"flags": [{"i": 0, "sensitive": False}]}


# --------------------------------------------------------------------------------------------
# log language
# --------------------------------------------------------------------------------------------


def test_tr_picks_the_run_language_and_is_never_word_translated():
    async def emit(event, data):
        return None

    with bind_emit(emit, lang="en"):
        line = tr("zprávy „Kam v Brně“: 10 článků", "news „Kam v Brně“: 10 articles")
        assert _log_text(line) == "news „Kam v Brně“: 10 articles"
    with bind_emit(emit, lang="cs"):
        assert _log_text(tr("zprávy „Kam v Brně“", "news „Kam v Brně“")) == "zprávy „Kam v Brně“"


def test_fallback_translation_leaves_quoted_data_and_handles_alone():
    async def emit(event, data):
        return None

    with bind_emit(emit, lang="en"):
        out = _log_text("zprávy „Kam v Brně | tipy kam v Brně“: 10 článků; posty @v.z od 2026-04-12 (0 z 50)")
    assert "„Kam v Brně | tipy kam v Brně“" in out
    assert "@v.z" in out and "since 2026-04-12" in out and "(0 of 50)" in out
    assert to_en("chybný požadavek (400)") == "bad request (400)"


async def test_emit_log_english_run_gets_the_english_text():
    seen: list[str] = []

    async def emit(event, data):
        seen.append(data["text"])

    with bind_emit(emit, lang="en"):
        await emit_log(tr("hledání „v Brně“: nalezeno 3", "search „v Brně“: 3 found"))
    assert seen == ["search „v Brně“: 3 found"]


# --------------------------------------------------------------------------------------------
# the model that answered is logged on every LLM step
# --------------------------------------------------------------------------------------------


@pytest.fixture
def _openrouter(_isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_TASKS", "all")
    config.reload_settings()
    llm_client.reset_client()
    yield
    llm_client.reset_client()


def _completion(content: str, model: str = PRIMARY) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "gen-1", "model": model, "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    })


async def test_model_logged_on_every_step_and_cache_hits_say_so(_openrouter):
    script = [_completion(json.dumps(FLAGS)), _completion(json.dumps(FLAGS))]
    openrouter.use_transport(httpx.MockTransport(lambda req: script.pop(0)))
    logs: list[str] = []

    async def emit(event, data):
        logs.append(data.get("text", ""))

    with bind_emit(emit, lang="en"):
        for user in ("[0] a", "[0] b", "[0] a"):   # the third is the same request: answered from the LLM cache
            out = await llm_client.structured(_Flags, system="Flag sensitive texts.", user=user, task="sensitive")
            assert out is not None
    answered = [t for t in logs if t == f"LLM sensitive: answered by model {PRIMARY}"]
    assert len(answered) == 2   # the same model twice in one process: both steps name it
    assert any("LLM sensitive: stored answer from the LLM cache" in t for t in logs)
    assert not any("odpověděl" in t for t in logs)


# --------------------------------------------------------------------------------------------
# report diff: findings that left "key" and skeptic-note changes are named
# --------------------------------------------------------------------------------------------


async def test_diff_names_demoted_findings_and_dropped_ai_skeptic_notes():
    from app.models import Anchor
    from app.presets import get_preset
    from app.rounds.report import diff_reports, render_report
    from tests.test_report_render import vetted

    anchor = Anchor(website="fitpeceni.example")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    a = render_report(get_preset("bakery", "en"), c, c.vetting_data, anchor=anchor)
    key = [f for f in a.findings if f.tier == "key"]
    assert key
    note = {"cs": "AI: pozor na jediný zdroj.", "en": "AI: beware of the single source."}
    before = a.model_copy(update={"skeptic_notes": list(a.skeptic_notes) + [note],
                                  "text_source": {**a.text_source, "skeptic": "llm+rules"}})
    after = a.model_copy(update={"findings": [f.model_copy(update={"tier": "related"}) if f.id == key[0].id else f
                                              for f in a.findings]})
    d = diff_reports(before, after)
    assert d.left_key == [key[0].id] and d.skeptic_removed == [note]
    assert "1 finding is no longer key" in d.summary["en"]
    assert "AI skeptic notes belonged to the previous goal" in d.summary["en"]
    assert "už není klíčové" in d.summary["cs"] and "AI skeptika" in d.summary["cs"]
    # a key finding collapsed to "less" is told once, as moved to less relevant
    less = a.model_copy(update={"findings": [f.model_copy(update={"tier": "less"}) if f.id == key[0].id else f
                                             for f in a.findings]})
    d2 = diff_reports(a, less)
    assert d2.left_key == [key[0].id] and "no longer key" not in d2.summary["en"]
    assert "1 moved to less relevant" in d2.summary["en"]
    # rule notes only: a dropped note is counted
    d3 = diff_reports(a.model_copy(update={"skeptic_notes": list(a.skeptic_notes) + [note]}), a)
    assert "1 skeptic note dropped" in d3.summary["en"]
    assert "1 new skeptic note" in diff_reports(a, a.model_copy(update={"skeptic_notes": list(a.skeptic_notes) + [note]})).summary["en"]


# --------------------------------------------------------------------------------------------
# news set aside: the verdict, "How this report was built" and the stored counts agree
# --------------------------------------------------------------------------------------------


async def test_news_set_aside_counted_the_same_everywhere():
    from datetime import datetime, timezone

    from app.models import Anchor, NewsItem, make_source_ref
    from app.rounds.report import render_report
    from tests.test_report_render import vetted

    anchor = Anchor(city="Brno")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    data = c.vetting_data
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    extra = [NewsItem(id=f"n:unrelated{i}", title=f"Tramvaje v Brně jezdí odklonem {i}", outlet="Brněnský deník",
                      url=f"https://news.example/{i}", published_at=when,
                      source=make_source_ref(url=f"https://news.example/{i}", platform="news", mode="mock", fetched_at=when))
             for i in range(3)]
    data = data.model_copy(update={"news_items": list(data.news_items) + extra})
    rep = render_report(run.criteria, c, data, anchor=anchor)
    v = rep.identity_verdict
    namesakes = sum(1 for s in v.set_aside if s.kind == "namesake")
    aside = len(data.news_items) - len(rep.news)
    unrelated = aside - namesakes
    assert unrelated >= 3
    assert f"We set aside {unrelated} news results that are not about @fit_peci_s_klarou." in v.text["en"]
    ident = next(m["en"] for m in rep.method if m["en"].startswith("Identity:"))
    assert f"{unrelated} news results that are not about @fit_peci_s_klarou" in ident and "nothing" not in ident
    fetched = next(m["en"] for m in rep.method if m["en"].startswith("Fetched:"))
    assert f"{len(rep.news)} of them about this creator" in fetched
    # the stored vetting count is the same definition (items not about the creator, namesakes included)
    assert c.vetting_data.counts["news_set_aside"] == len(c.vetting_data.news_items) - len(c.report.news)


async def test_no_news_gap_says_how_many_results_were_set_aside():
    from datetime import datetime, timezone

    from app.models import Anchor, NewsItem, make_source_ref
    from app.rounds.report import render_report
    from tests.test_report_render import vetted

    anchor = Anchor(city="Brno")
    run, c = await vetted("fit_peci_s_klarou", anchor=anchor)
    when = datetime(2026, 10, 1, tzinfo=timezone.utc)
    items = [NewsItem(id="n:other", title="Tramvaje v Brně jezdí odklonem", outlet="Brněnský deník",
                      url="https://news.example/x", published_at=when,
                      source=make_source_ref(url="https://news.example/x", platform="news", mode="mock", fetched_at=when))]
    data = c.vetting_data.model_copy(update={"news_items": items})
    rep = render_report(run.criteria, c, data, anchor=anchor)
    gap = next(f for f in rep.findings if f.id == "g:news")
    assert gap.text["en"].startswith("We found no news about the creator: 1 news result is about something else")
    assert "1 nalezená zpráva je o něčem jiném" in gap.text["cs"]


# --------------------------------------------------------------------------------------------
# Apify provider: an English run logs whole English lines; quoted data stays as it is
# --------------------------------------------------------------------------------------------


async def test_apify_provider_logs_english_for_an_english_run(monkeypatch):
    import re
    from datetime import timedelta

    from app.models import DiscoveryQuery
    from app.sources import apify_provider as ap
    from app.sources.apify_provider import ApifyProvider
    from tests.test_apify_mappers import NOW, FakeRunner, sample

    monkeypatch.setenv("APIFY_TIKTOK_SEARCH", "1")
    monkeypatch.setenv("APIFY_PLACES", "1")
    seen: list[str] = []

    async def emit(event, data):
        if event == "log":
            seen.append(data["text"])

    p = ApifyProvider(token="test-token", runner=FakeRunner())
    prof = ap.map_ig_profile(sample("ig_profiles.json")[0], actor=ap.ACT_IG_PROFILE, fetched_at=NOW)
    with bind_emit(emit, lang="en"):
        await p.discover(DiscoveryQuery(keywords=["cukrárna"], hashtags=["#brnofood"], city="Brno",
                                        platforms=["instagram", "tiktok"]))
        await p.profiles(["sample_cukrarka_brno", "nikdo_takovy"], "instagram")
        await p.posts("sample_cukrarka_brno", "instagram", NOW - timedelta(days=180))
        await p.comments(["https://www.instagram.com/p/SAMPLEd1/"])
        await p.news("Kam v Brně")
        await p.collabs("sample_cukrarka_brno", "instagram")
        await p.find_cross_platform(prof)
    assert len(seen) > 10
    cz = re.compile(r"[ěščřžýáíéůúťďňĚŠČŘŽÝÁÍÉŮÚŤĎŇ]")
    quoted = re.compile(r"„[^“]*“|[@#][\w.]+")
    for line in seen:
        assert not cz.search(quoted.sub("", line)), line         # no Czech outside quoted data / handles
        assert not re.search(r"\b(živě|spouštím|odhad|položek|nalezeno|vracím)\b", line), line
    assert any(line.startswith("news „Kam v Brně“:") for line in seen)            # the query is never translated
    assert any(line.startswith("live news „Kam v Brně“: starting, estimate 0.") for line in seen)


def test_openrouter_400_reason_carries_the_provider_message():
    e = openrouter.classify_error(400, {"error": {"message": "This endpoint's maximum context length is 16384 tokens."}})
    assert e.reason == 'OpenRouter: chybný požadavek (400): "This endpoint\'s maximum context length is 16384 tokens."'
    raw = openrouter.classify_error(400, {"error": {"message": "Provider returned error",
                                                    "metadata": {"raw": "max_tokens is too large", "provider_name": "X"}}})
    assert raw.reason.endswith(': "max_tokens is too large"')
    assert to_en(openrouter.classify_error(400, {"error": {"message": "a v z"}}).reason).endswith('(400): "a v z"')
    assert openrouter.classify_error(400, b"").reason == "OpenRouter: chybný požadavek (400)"
    assert to_en(e.reason).startswith('OpenRouter: bad request (400): "This endpoint\'s')
