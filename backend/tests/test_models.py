"""Smoke test: every contract model constructs, serializes and round-trips; helpers behave."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import models as m
from app.presets import get_preset


def _ref(i: str = "ig:post:1", **kw) -> m.SourceRef:
    return m.make_source_ref(id=i, url=f"https://instagram.com/p/{i}", platform="instagram", mode="mock", **kw)


def _post(i: str = "p1") -> m.Post:
    return m.Post(
        id=i, platform="instagram", url=f"https://instagram.com/p/{i}", author_handle="@Anna_Peče",
        created_at=datetime(2026, 10, 1, 12, 0), caption="Nový chleba #BrnoFood @Pekarna_B",
        hashtags=["#BrnoFood"], mentions=["@Pekarna_B"], coauthors=["Pekarna_B"], media_type="reel",
        likes=120, comments=8, location_name="Brno", paid_partnership=False, source=_ref(f"ig:post:{i}"),
    )


def _profile() -> m.Profile:
    return m.Profile(handle="@Anna_Peče", platform="instagram", url="https://instagram.com/anna", display_name="Anna (MOCK)",
                     followers=12400, latest_posts=[_post("p1"), _post("p2")], source=_ref("ig:profile:anna"))


def test_every_model_constructs_and_roundtrips():
    now = m.utcnow()
    ref = _ref(quote="x" * 500)
    assert len(ref.quote) == m.QUOTE_MAX
    post = _post()
    assert post.hashtags == ["brnofood"] and post.mentions == ["pekarna_b"] and post.author_handle == "anna_peče"
    assert post.created_at.tzinfo is not None
    profile = _profile()
    comment = m.Comment(post_url=post.url, text="Super 😍", source=_ref("ig:comment:1"))
    cref = m.CandidateRef(handle="Anna_Peče", platform="instagram", found_via=["hashtag:brnofood"], source=_ref("ig:search:1"))
    collab = m.CollabEvidence(id="collab:p1:coauthor:pekarnab", brand="pekarnab", brand_handle="pekarna_b", kind="coauthor",
                              disclosed=False, date=now, post_id="p1", is_competitor=True, source=post.source)
    news = m.NewsItem(id=f"news:{m.short_hash('https://x.cz/a')}", title="T", outlet="Deník N", url="https://x.cz/a",
                      published_at=None, source=m.make_source_ref(url="https://x.cz/a", platform="news", mode="mock"))
    q = m.DiscoveryQuery(hashtags=["#BrnoFood"])
    assert q.platforms == ["instagram", "tiktok"] and q.hashtags == ["brnofood"]
    assert m.DiscoveryQuery().platforms is not m.DiscoveryQuery().platforms

    crit = m.Criterion(id="f", kind="followers_range", round=99, label=m.i18n("a", "b"), why=m.i18n("c", "d"), params={"min": 1})
    assert crit.round == 1
    assert m.make_criterion("topic_share").params["min_share"] == 0.4
    refused = m.Refused(text="bez věřících", reason=m.i18n("čl. 9", "Art. 9"))
    brief = m.Brief(business_type="pekárna", city="Brno", audience="rodiny", goal="víc lidí", budget_hint=None, competitors=[])
    cs = m.CriteriaSet(brief=brief, criteria=[crit], refused=[refused], discovery=q)
    result = m.CriterionResult(criterion_id="f", status="pass", value="12 400", threshold="5–50 tis.", sources=[profile.source])
    elim = m.Elimination(round=1, criterion_id="f", reason=m.i18n("a", "b"), sources=[profile.source])
    metrics = m.Metrics(posts_analyzed=2, median_likes=120.0, median_comments=8.0, engagement_rate=0.01, posts_per_week=1.0,
                        last_post_at=now, formats={"reel": 2}, commercial_share=0.0, topic_counts={"food": 2},
                        cs_comment_share=None, generic_comment_share=None, local_signals=[post.source])
    sig = m.IdentitySignal(signal="stejný web", supports=True, source=None)
    ident = m.IdentityMatch(handle="@Anna", platform="tiktok", status="matched", signals=[sig])
    fact = m.Finding(id="f1", kind="fact", text=m.i18n("a", "b"), sources=[post.source], section="collabs")
    inf = m.Finding(id="f2", kind="inference", text=m.i18n("a", "b"), sources=[], based_on=["f1"], section="collabs")
    gap = m.Finding(id="f3", kind="gap", text=m.i18n("a", "b"), sources=[], section="engagement")
    claim = m.ClaimCheck(id="c1", claim="exkluzivní ambasador @pekarna_a", claim_source=profile.source, evidence=[collab.id],
                         status="conflicts_with_record", confidence="high", note=m.i18n("a", "b"))
    nf = m.NewsFinding(item=news, label="allegation", attribution="píše Deník N")
    report = m.Report(candidate_id="instagram:anna_peče", findings=[fact, inf, gap], claims=[claim], collab_timeline=[collab],
                      news=[nf], identity=[ident], questions=[m.i18n("q", "q")], outreach_draft=m.i18n("a", "b"),
                      not_checked=[m.i18n("a", "b")], skeptic_notes=[], sensitive_filtered=2)
    cand = m.Candidate(id=m.candidate_id("instagram", "@Anna_Peče"), ref=cref, profile=profile, metrics=metrics,
                       results=[result], status="eliminated", elimination=elim, report=report)
    assert cand.id == "instagram:anna_peče" == m.candidate_id(cref.platform, cref.handle)
    run = m.Run(id="r_1", criteria=cs, candidates={cand.id: cand}, rounds=[{"round": 1, "entered": 1, "remaining": 0}],
                log=[], mode_summary={"live": 0, "cache": 0, "mock": 1})
    assert run.llm_modes == {}

    for obj in (ref, post, profile, comment, cref, collab, news, q, crit, refused, brief, cs, result, elim, metrics,
                sig, ident, fact, inf, gap, claim, nf, report, cand, run):
        again = type(obj).model_validate_json(obj.model_dump_json())
        assert again == obj

    assert len(list(m.iter_source_refs(run))) > 5


def test_fact_without_source_is_rejected():
    with pytest.raises(ValueError):
        m.Finding(id="x", kind="fact", text=m.i18n("a", "b"), sources=[], section="profile")


def test_taxonomy_and_rounds_are_consistent():
    assert set(m.CRITERION_ROUND) == set(m.CRITERION_KINDS) == set(m.CRITERION_DEFAULT_PARAMS) == set(m.CRITERION_DEFAULT_LABELS)
    assert {m.CRITERION_ROUND[k] for k in m.CRITERION_KINDS} == {1, 2, 3, 4}
    assert m.TOPICS[-1] == "other" and len(m.TOPICS) == 17


def test_presets_are_valid_and_differ():
    bakery, fitness = get_preset("bakery"), get_preset("fitness")
    for cs in (bakery, fitness):
        assert {c.kind for c in cs.criteria} == set(m.CRITERION_KINDS)
        assert len({c.id for c in cs.criteria} ) == len(cs.criteria)
        for c in cs.criteria:
            for t in c.params.get("topics", []):
                assert t in m.TOPICS
    assert bakery.discovery == fitness.discovery
    assert bakery.criteria != fitness.criteria


def test_naive_datetimes_become_utc():
    p = _post()
    assert p.created_at.utcoffset() == timedelta(0)
    aware = datetime(2026, 10, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert m.make_source_ref(url="u", platform="web", mode="live", fetched_at=aware).fetched_at.hour == 12


def test_settings_use_temp_data_dir(_isolated_settings, tmp_path):
    assert _isolated_settings.data_dir == tmp_path / "data"
    assert _isolated_settings.source_mode == "mock" and _isolated_settings.llm_mode == "fallback"


def test_all_modules_import():
    for name in [
        "app.main", "app.config", "app.store", "app.events", "app.presets",
        "app.sources.base", "app.sources.mock_provider", "app.sources.cache", "app.sources.apify_provider", "app.sources.factory",
        "app.compute.metrics", "app.compute.language", "app.compute.collabs", "app.compute.identity",
        "app.rounds.engine", "app.rounds.r0_discovery", "app.rounds.r1_basics", "app.rounds.r2_content",
        "app.rounds.r3_audience", "app.rounds.r4_vetting",
        "app.llm.client", "app.llm.sensitive", "app.llm.topics", "app.llm.vetting", "app.llm.chat", "app.llm.prompts",
    ]:
        importlib.import_module(name)


async def test_emit_log_and_llm_modes_plumbing():
    from app.events import bind_emit, emit_log
    from app.llm.client import bind_llm_modes, record_mode

    got: list[tuple[str, dict]] = []

    async def emit(event: str, data: dict) -> None:
        got.append((event, data))

    await emit_log("unbound")  # no-op
    with bind_emit(emit):
        await emit_log("Instagram: 48 účtů", actor="mock/discover", mode="mock")
    assert got[0][0] == "log" and got[0][1]["mode"] == "mock"

    modes: dict[str, str] = {}
    with bind_llm_modes(modes):
        record_mode("topics", "fallback")
        record_mode("topics", "fallback")
        record_mode("vetting", "llm")
        record_mode("vetting", "fallback")
    assert modes == {"topics": "fallback", "vetting": "mixed"}


def test_health_endpoint():
    from app.main import app

    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    from app.sources.factory import apify_available

    body = r.json()
    expected = {"source_mode": "mock", "llm_mode": "fallback", "llm_provider": None, "llm_model": None,
                "llm_models_used": {}, "apify_configured": False,
                "apify_provider_implemented": apify_available()}
    assert {k: body.get(k) for k in expected} == expected
    # LLM budget snapshot (llm.budget.usage_snapshot) rides along
    assert body["llm_requests_used"] == 0 and "llm_budget" in body and "llm_budget_left" in body
