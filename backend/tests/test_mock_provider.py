"""MockProvider over fixtures/ + the fixtures' own consistency (fixtures/expected.json is the oracle)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import REPO_DIR
from app.events import bind_emit
from app.models import (
    CandidateRef,
    CollabEvidence,
    Comment,
    CriteriaSet,
    DiscoveryQuery,
    NewsItem,
    Post,
    Profile,
    candidate_id,
    iter_source_refs,
    utcnow,
)
from app.presets import DEMO_DISCOVERY
from app.sources.base import SourceProvider
from app.sources.mock_provider import MockProvider

FIXTURES = REPO_DIR / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text("utf-8"))


def _mp(**kw) -> MockProvider:
    return MockProvider(latency=0, **kw)


def _unique(refs: list[CandidateRef]) -> list[str]:
    return list(dict.fromkeys(candidate_id(r.platform, r.handle) for r in refs))


def _all_mock(objs, actor: str) -> None:
    refs = list(iter_source_refs(objs))
    assert refs, "no SourceRefs"
    for r in refs:
        assert r.mode == "mock"
        assert r.actor == actor


class Logs:
    def __init__(self) -> None:
        self.items: list[dict] = []

    async def __call__(self, event: str, data: dict) -> None:
        if event == "log":
            self.items.append(data)


# --------------------------------------------------------------------------------- protocol


def test_is_source_provider():
    assert isinstance(_mp(), SourceProvider)
    assert MockProvider.name == "mock"


def test_defaults_from_settings(monkeypatch):
    from app import config

    monkeypatch.setenv("MOCK_LATENCY", "0.07")
    config.reload_settings()
    p = MockProvider()
    assert p.latency == pytest.approx(0.07)
    assert p.fixtures_dir == config.get_settings().fixtures_dir


# --------------------------------------------------------------------------------- discover


async def test_discover_demo_query_returns_pool_without_minor():
    logs = Logs()
    with bind_emit(logs):
        refs = await _mp().discover(DEMO_DISCOVERY)
    uniq = _unique(refs)
    assert len(uniq) == EXPECTED["discovery"]["unique_after_minor_drop"] == 48
    assert len(refs) == EXPECTED["discovery"]["raw_refs"] - 1  # the minor's single ref is dropped
    for minor in EXPECTED["discovery"]["minors_dropped"]:
        assert minor not in uniq
    assert all(len(r.found_via) == 1 for r in refs)
    _all_mock(refs, "mock:discover")
    kinds = {r.found_via[0].split(":")[0] for r in refs}
    assert kinds == {"search", "hashtag", "place", "related"}
    assert any("18" in x["text"] for x in logs.items), "minor drop must be logged (count only)"
    assert all(x["mode"] == "mock" and x["actor"] == "mock:discover" for x in logs.items)


async def test_discover_filters_loosely_and_falls_back():
    p = _mp()
    only_fit = await p.discover(DiscoveryQuery(hashtags=["brnofitness"], platforms=["instagram"]))
    handles = {r.handle for r in only_fit}
    assert "trener_marek_brno" in handles and "kuba.jidlo.brno" not in handles
    assert all(r.platform == "instagram" for r in only_fit)
    # related:@x follows its parent
    rel = await p.discover(DiscoveryQuery(hashtags=["brnojidlo"], platforms=["instagram"]))
    assert "proteomax" in {r.handle for r in rel}  # related:@fit_peci_s_klarou
    # loose keyword match ("pekárny" ~ "pekárna")
    loose = await p.discover(DiscoveryQuery(keywords=["pekárny brno"], city="Brno", places=[]))
    assert "pekarna_b" in {r.handle for r in loose}
    # nothing matches -> whole pool
    anything = await p.discover(DiscoveryQuery(keywords=["kadeřnictví ostrava"], places=[], city=None))
    assert len(_unique(anything)) == 48
    tt = await p.discover(DiscoveryQuery(keywords=["nic"], platforms=["tiktok"]))
    assert tt and all(r.platform == "tiktok" for r in tt)


# --------------------------------------------------------------------------------- profiles


async def test_profiles_all_candidates_dates_fresh_and_labeled():
    p = _mp()
    refs = await p.discover(DEMO_DISCOVERY)
    out: list[Profile] = []
    for platform in ("instagram", "tiktok"):
        handles = [r.handle for r in refs if r.platform == platform]
        out += await p.profiles(handles, platform)
    assert len(out) == 48
    _all_mock(out, "mock:profiles")
    now = utcnow()
    for prof in out:
        assert prof.source.fetched_at <= now + timedelta(seconds=5)
        for post in prof.latest_posts:
            assert post.created_at <= now
    by = {candidate_id(x.platform, x.handle): x for x in out}
    newest = max(x.created_at for x in by["instagram:kuba.jidlo.brno"].latest_posts)
    assert now - newest < timedelta(days=3)
    inactive = max(x.created_at for x in by["instagram:honza_jedlik"].latest_posts)
    assert now - inactive > timedelta(days=90)
    assert by["instagram:anicka_doma"].private is True and by["instagram:anicka_doma"].latest_posts == []
    for prof in out:
        if not prof.private and prof.platform != "youtube":
            assert 12 <= len(prof.latest_posts) <= 24, prof.handle


async def test_profiles_drop_minor_and_unknown_and_normalize():
    logs = Logs()
    with bind_emit(logs):
        out = await _mp().profiles(["nikolka_pece", "@TOMAN_ochutnava", "nobody_here", "toman_ochutnava"], "tiktok")
    assert [x.handle for x in out] == ["toman_ochutnava"]
    text = " ".join(x["text"] for x in logs.items)
    assert "18" in text and "nobody_here" in text
    assert await _mp().profiles(["toman_ochutnava"], "instagram") == []  # wrong platform


async def test_returned_objects_are_copies():
    p = _mp()
    a = (await p.profiles(["verca_pece"], "instagram"))[0]
    a.bio = "changed"
    a.latest_posts.clear()
    b = (await p.profiles(["verca_pece"], "instagram"))[0]
    assert b.bio != "changed" and b.latest_posts


async def test_fixed_now_shifts_dates():
    fixed = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    prof = (await _mp(now=fixed).profiles(["kuba.jidlo.brno"], "instagram"))[0]
    newest = max(x.created_at for x in prof.latest_posts)
    assert timedelta(0) < fixed - newest < timedelta(days=3)
    assert prof.source.fetched_at == fixed


# --------------------------------------------------------------------------------- posts


async def test_posts_since_sorted_with_extra_history():
    p = _mp()
    now = utcnow()
    allp = await p.posts("kuba.jidlo.brno", "instagram", since=now - timedelta(days=180), limit=100)
    latest = (await p.profiles(["kuba.jidlo.brno"], "instagram"))[0].latest_posts
    assert len(allp) > len(latest)
    assert [x.created_at for x in allp] == sorted((x.created_at for x in allp), reverse=True)
    _all_mock(allp, "mock:posts")
    recent = await p.posts("kuba.jidlo.brno", "instagram", since=now - timedelta(days=30))
    assert all(x.created_at >= now - timedelta(days=30) for x in recent)
    # the two @pekarna_b coauthored posts are within the last 30 days, one unlabeled
    pb = [x for x in recent if "pekarna_b" in x.coauthors]
    assert len(pb) == 2 and {x.paid_partnership for x in pb} == {True, False}
    assert len(await p.posts("kuba.jidlo.brno", "instagram", since=now - timedelta(days=180), limit=5)) == 5
    naive = await p.posts("kuba.jidlo.brno", "instagram", since=(now - timedelta(days=10)).replace(tzinfo=None))
    assert naive
    assert await p.posts("anicka_doma", "instagram", since=now - timedelta(days=90)) == []  # private
    assert await p.posts("nikolka_pece", "tiktok", since=now - timedelta(days=90)) == []    # minor
    assert await p.posts("nobody", "instagram", since=now - timedelta(days=90)) == []


# --------------------------------------------------------------------------------- comments


async def test_comments_text_only_and_capped():
    p = _mp()
    prof = (await p.profiles(["brnenska_snidane"], "instagram"))[0]
    urls = [x.url for x in sorted(prof.latest_posts, key=lambda x: x.created_at, reverse=True)[:5]]
    cs = await p.comments(urls + [urls[0] + "/"], per_post=15)  # trailing slash variant deduped by URL key
    assert cs and all(isinstance(c, Comment) for c in cs)
    assert set(Comment.model_fields) == {"post_url", "text", "created_at", "source"}  # no commenter identity
    by_url: dict[str, int] = {}
    for c in cs:
        by_url[c.post_url] = by_url.get(c.post_url, 0) + 1
    assert max(by_url.values()) <= 15
    _all_mock(cs, "mock:comments")
    few = await p.comments(urls, per_post=3)
    assert len(few) <= 3 * len(urls)
    assert await p.comments(["https://www.instagram.com/p/UNKNOWN/"]) == []


# --------------------------------------------------------------------------------- collabs, news, cross


async def test_collabs_meta_branded():
    p = _mp()
    b1 = await p.collabs("kuba.jidlo.brno", "instagram")
    assert {c.brand_handle for c in b1} == {"pekarna_a", "pekarna_b"}
    assert all(c.kind == "meta_branded" and c.disclosed is True for c in b1)
    _all_mock(b1, "mock:collabs")
    assert all(c.source.platform == "meta_branded" for c in b1)
    assert await p.collabs("verca_pece", "instagram") == []
    assert await p.collabs("toman_ochutnava", "tiktok") == []


async def test_news_matching_and_namesakes():
    p = _mp()
    toman = await p.news("Ondřej Toman")
    assert len(toman) == 2
    assert all(isinstance(n, NewsItem) for n in toman)
    assert toman[0].published_at >= toman[1].published_at
    assert len(await p.news("@toman_ochutnava")) == 1
    assert len(await p.news("Jakub Horák")) == 2  # one is the criminal namesake the filter must drop
    assert await p.news("Barbora Kolářová") == []
    assert len(await p.news("Ondřej Toman", limit=1)) == 1
    _all_mock(toman, "mock:news")


async def test_find_cross_platform():
    p = _mp()
    b3 = (await p.profiles(["brnenska_snidane"], "instagram"))[0]
    cross = await p.find_cross_platform(b3)
    assert {(x.platform, x.handle) for x in cross} == {("tiktok", "brnenska_snidane"), ("tiktok", "brnenska_snidane_fans")}
    _all_mock(cross, "mock:find_cross_platform")
    f5 = (await p.profiles(["kalisthenika_brno_tom"], "instagram"))[0]
    assert [x.platform for x in await p.find_cross_platform(f5)] == ["youtube"]
    b2 = (await p.profiles(["verca_pece"], "instagram"))[0]
    assert await p.find_cross_platform(b2) == []


# --------------------------------------------------------------------------------- robustness


async def test_never_raises_on_broken_fixtures(tmp_path):
    (tmp_path / "meta.json").write_text("{not json", "utf-8")
    logs = Logs()
    p = MockProvider(fixtures_dir=tmp_path, latency=0)
    with bind_emit(logs):
        assert await p.discover(DEMO_DISCOVERY) == []
        assert await p.profiles(["x"], "instagram") == []
        assert await p.news("x") == []
    assert logs.items and all(x["mode"] == "mock" for x in logs.items)


async def test_latency_is_applied():
    p = MockProvider(latency=0.05)
    t = time.perf_counter()
    await p.news("Ondřej Toman")
    assert time.perf_counter() - t >= 0.045


async def test_concurrent_calls():
    p = _mp()
    res = await asyncio.gather(*(p.profiles(["verca_pece"], "instagram") for _ in range(10)))
    assert all(len(r) == 1 for r in res)


# --------------------------------------------------------------------------------- fixtures oracle


def test_fixture_files_load_through_models():
    for x in json.loads((FIXTURES / "discovery.json").read_text("utf-8")):
        CandidateRef.model_validate(x)
    profiles = [Profile.model_validate(x) for x in json.loads((FIXTURES / "profiles.json").read_text("utf-8"))]
    for v in json.loads((FIXTURES / "posts.json").read_text("utf-8")).values():
        [Post.model_validate(x) for x in v]
    for v in json.loads((FIXTURES / "collabs.json").read_text("utf-8")).values():
        [CollabEvidence.model_validate(x) for x in v]
    briefs = json.loads((FIXTURES / "briefs.json").read_text("utf-8"))
    for name in ("bakery", "fitness"):
        cs = CriteriaSet.model_validate(briefs[name])
        assert len(cs.brief.competitors) == 2 and cs.refused
    every_ref = list(iter_source_refs(profiles))
    assert every_ref and all(r.mode == "mock" for r in every_ref)


def test_expected_oracle_is_consistent():
    for goal in ("bakery", "fitness"):
        g = EXPECTED["goals"][goal]
        assert len(g["finalists"]) == 5
        assert g["rounds"][0]["entered"] == 48
        assert g["rounds"][-1]["remaining"] == 5
        assert len(g["eliminated"]) + len(g["finalists"]) == 48
    shared = set(EXPECTED["goals"]["bakery"]["finalists"]) & set(EXPECTED["goals"]["fitness"]["finalists"])
    assert shared == {"instagram:fit_peci_s_klarou"}
    r4b = EXPECTED["goals"]["bakery"]["round4"]["instagram:kuba.jidlo.brno"]
    assert r4b["no_competitor_collab"]["status"] == "fail" and r4b["discloses_ads"]["status"] == "fail"
    assert EXPECTED["goals"]["fitness"]["round4"]["instagram:fit_peci_s_klarou"]["no_competitor_collab"]["status"] == "fail"
    assert EXPECTED["goals"]["bakery"]["round4"]["instagram:fit_peci_s_klarou"]["no_competitor_collab"]["status"] == "not_fail"
    sens = EXPECTED["sensitive"]
    assert len(sens["posts"]) + len(sens["comments"]) >= 5
    assert {x["category"] for x in sens["posts"] + sens["comments"]} >= {"health", "politics", "religion"}


async def test_sensitive_items_are_reachable_through_the_provider():
    p = _mp()
    sens = EXPECTED["sensitive"]
    for item in sens["posts"]:
        platform, handle = item["candidate"].split(":", 1)
        prof = (await p.profiles([handle], platform))[0]
        assert item["id"] in {x.id for x in prof.latest_posts}
    for item in sens["comments"]:
        cs = await p.comments([item["post_url"]])
        assert item["id"] in {c.source.id for c in cs}
    news_ids = {n.id for n in await p.news("Jakub Horák")}
    assert {x["id"] for x in sens["news"]} <= news_ids


def test_generator_is_deterministic_and_fresh():
    """Regenerating (with the lingua + reference-funnel verification) gives byte-identical files."""
    out = subprocess.run([sys.executable, str(FIXTURES / "generate.py"), "--check"],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr + out.stdout
