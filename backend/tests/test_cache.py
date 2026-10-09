"""CachedProvider: keys, miss/hit, per-handle and per-URL granularity, offline, import, purge."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import REPO_DIR, get_settings
from app.events import bind_emit
from app.models import (
    CandidateRef,
    Comment,
    DiscoveryQuery,
    NewsItem,
    Profile,
    iter_source_refs,
    make_source_ref,
    utcnow,
)
from app.presets import DEMO_DISCOVERY
from app.sources.base import SourceProvider
from app.sources.cache import CachedProvider, cache_key, import_cache_dir, purge_cache
from app.sources.mock_provider import MockProvider


class Spy:
    """Wraps a provider and records calls (method, args)."""

    def __init__(self, inner, name: str | None = None) -> None:
        self.inner = inner
        self.name = name or inner.name
        self.calls: list[tuple[str, tuple]] = []

    def __getattr__(self, method):
        target = getattr(self.inner, method)

        async def call(*args, **kwargs):
            self.calls.append((method, args))
            return await target(*args, **kwargs)

        return call

    def count(self, method: str) -> int:
        return sum(1 for m, _ in self.calls if m == method)


class Boom:
    name = "boom"

    async def _raise(self, *a, **k):
        raise RuntimeError("actor exploded")

    discover = profiles = posts = comments = collabs = news = find_cross_platform = _raise


class Logs:
    def __init__(self) -> None:
        self.items: list[dict] = []

    async def __call__(self, event: str, data: dict) -> None:
        if event == "log":
            self.items.append(data)


def _modes(objs) -> set[str]:
    return {r.mode for r in iter_source_refs(objs)}


def _mock() -> MockProvider:
    return MockProvider(latency=0)


# --------------------------------------------------------------------------------- keys


def test_cache_key_canonical():
    a = cache_key("profiles", {"handles": ["b", "a"], "platform": "instagram"}, "apify")
    b = cache_key("profiles", {"platform": "instagram", "handles": ["a", "b", "a"]}, "apify")
    assert a == b and len(a) == 64
    assert a != cache_key("profiles", {"handles": ["a", "b"], "platform": "tiktok"}, "apify")
    assert a != cache_key("posts", {"handles": ["a", "b"], "platform": "instagram"}, "apify")
    assert a != cache_key("profiles", {"handles": ["a", "b"], "platform": "instagram"}, "mock")
    d1 = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 8, 23, 0, tzinfo=timezone.utc)
    assert cache_key("posts", {"since": d1}) == cache_key("posts", {"since": d2})
    assert cache_key("posts", {"since": d1}) != cache_key("posts", {"since": d1 + timedelta(days=1)})
    q1 = DiscoveryQuery(keywords=["b", "a"], hashtags=["#X"])
    q2 = DiscoveryQuery(keywords=["a", "b"], hashtags=["x"])
    assert cache_key("discover", {"q": q1}) == cache_key("discover", {"q": q2})


def test_is_source_provider_and_name():
    c = CachedProvider(_mock())
    assert isinstance(c, SourceProvider)
    assert c.name == "cache(mock)"
    assert c.cache_dir == get_settings().cache_dir  # temp DATA_DIR from conftest
    assert not c.cache_dir.is_relative_to(REPO_DIR / "data")  # never the real data/ dir


def test_aliases(tmp_path):
    c = CachedProvider(_mock(), data_dir=tmp_path, offline=True)
    assert c.read_only and c.offline
    assert c.cache_dir == tmp_path / "cache"


# --------------------------------------------------------------------------------- miss / hit


async def test_miss_writes_then_hit_relabels_cache(tmp_path):
    spy = Spy(_mock())
    c = CachedProvider(spy, cache_dir=tmp_path)
    first = await c.news("Ondřej Toman")
    assert len(first) == 2 and _modes(first) == {"mock"}
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text("utf-8"))
    assert payload["meta"]["method"] == "news" and payload["meta"]["provider"] == "mock"
    assert payload["meta"]["actor"] == "mock:news" and payload["meta"]["count"] == 2
    assert payload["meta"]["args"]["query"] == "ondřej toman"
    logs = Logs()
    with bind_emit(logs):
        second = await c.news("  ondřej   TOMAN ")
    assert spy.count("news") == 1
    assert [n.id for n in second] == [n.id for n in first]
    assert _modes(second) == {"cache"}
    assert all(n.source.actor == "mock:news" for n in second)  # original actor kept
    assert logs.items and logs.items[0]["mode"] == "cache" and logs.items[0]["actor"] == "mock:news"
    assert c.stats["hits"] == 1 and c.stats["writes"] == 1


async def test_profiles_cached_per_handle(tmp_path):
    spy = Spy(_mock())
    c = CachedProvider(spy, cache_dir=tmp_path)
    a = await c.profiles(["verca_pece", "brnenska_snidane"], "instagram")
    assert [p.handle for p in a] == ["verca_pece", "brnenska_snidane"]
    assert len(list(tmp_path.glob("*.json"))) == 2
    b = await c.profiles(["@Brnenska_Snidane", "kuba.jidlo.brno"], "instagram")
    assert [p.handle for p in b] == ["brnenska_snidane", "kuba.jidlo.brno"]
    assert spy.calls[-1] == ("profiles", (["kuba.jidlo.brno"], "instagram"))
    assert _modes(b[0]) == {"cache"} and _modes(b[1]) == {"mock"}
    # nested latest_posts are relabeled too
    assert {p.source.mode for p in b[0].latest_posts} == {"cache"}
    c2 = CachedProvider(Spy(_mock()), cache_dir=tmp_path)
    again = await c2.profiles(["verca_pece", "brnenska_snidane", "kuba.jidlo.brno"], "instagram")
    assert len(again) == 3 and c2.inner.calls == []


async def test_comments_cached_per_url(tmp_path):
    m = _mock()
    prof = (await m.profiles(["brnenska_snidane"], "instagram"))[0]
    urls = [x.url for x in sorted(prof.latest_posts, key=lambda p: p.created_at, reverse=True)[:4]]
    spy = Spy(m)
    c = CachedProvider(spy, cache_dir=tmp_path)
    first = await c.comments(urls[:2], per_post=15)
    assert first and len(list(tmp_path.glob("*.json"))) == 2
    second = await c.comments(urls, per_post=15)
    assert spy.calls[-1][0] == "comments" and spy.calls[-1][1][0] == urls[2:]
    assert {c_.post_url for c_ in second} == set(urls)
    assert all(c_.source.mode == "cache" for c_ in second if c_.post_url in urls[:2])
    assert set(Comment.model_fields) == {"post_url", "text", "created_at", "source"}


async def test_posts_key_ignores_since(tmp_path):
    """Brno run 9. 10. 2026: since (as a UTC date) was in the key and round 4 missed the cache the next day.
    Now the full list is stored per handle + platform + limit and filtered by since on read."""
    spy = Spy(_mock())
    c = CachedProvider(spy, cache_dir=tmp_path)
    since = utcnow() - timedelta(days=180)
    a = await c.posts("kuba.jidlo.brno", "instagram", since)
    b = await c.posts("kuba.jidlo.brno", "instagram", since + timedelta(seconds=30))
    nxt = await c.posts("kuba.jidlo.brno", "instagram", since + timedelta(days=1))
    assert spy.count("posts") == 1 and len(a) == len(b) and _modes(b) == {"cache"}
    assert [p.id for p in nxt] == [p.id for p in a if p.created_at >= since + timedelta(days=1)]
    (entry,) = [json.loads(f.read_text("utf-8")) for f in tmp_path.glob("*.json")]
    assert "since" not in entry["meta"]["args"]


async def test_all_methods_roundtrip(tmp_path):
    spy = Spy(_mock())
    c = CachedProvider(spy, cache_dir=tmp_path)
    prof = (await c.profiles(["fit_peci_s_klarou"], "instagram"))[0]
    calls = [
        lambda: c.discover(DEMO_DISCOVERY),
        lambda: c.collabs("fit_peci_s_klarou", "instagram"),
        lambda: c.find_cross_platform(prof),
        lambda: c.news("Klára Veselá"),
    ]
    first = [await f() for f in calls]
    n_calls = len(spy.calls)
    second = [await f() for f in calls]
    assert len(spy.calls) == n_calls
    for a, b in zip(first, second):
        assert a and len(a) == len(b) and _modes(b) == {"cache"}
    assert isinstance(second[0][0], CandidateRef)


# --------------------------------------------------------------------------------- failure modes


async def test_empty_results_are_not_cached(tmp_path):
    spy = Spy(_mock())
    c = CachedProvider(spy, cache_dir=tmp_path)
    assert await c.news("nikdo takový neexistuje") == []
    assert await c.news("nikdo takový neexistuje") == []
    assert spy.count("news") == 2 and list(tmp_path.glob("*.json")) == []


async def test_offline_never_calls_inner(tmp_path):
    spy = Spy(_mock())
    logs = Logs()
    c = CachedProvider(spy, cache_dir=tmp_path, read_only=True)
    with bind_emit(logs):
        assert await c.news("Ondřej Toman") == []
        assert await c.profiles(["verca_pece"], "instagram") == []
        assert await c.comments(["https://www.instagram.com/p/x/"]) == []
        assert await c.posts("verca_pece", "instagram", utcnow()) == []
    assert spy.calls == []
    assert logs.items and all(x["mode"] == "cache" for x in logs.items)
    # warm with a writer, then offline hits
    await CachedProvider(_mock(), cache_dir=tmp_path).news("Ondřej Toman")
    hit = await c.news("Ondřej Toman")
    assert len(hit) == 2 and _modes(hit) == {"cache"} and spy.calls == []


async def test_inner_errors_and_corrupt_files_never_raise(tmp_path):
    c = CachedProvider(Boom(), cache_dir=tmp_path)
    assert await c.discover(DEMO_DISCOVERY) == []
    assert await c.profiles(["a"], "instagram") == []
    assert await c.comments(["u"]) == []
    assert await c.news("x") == []
    assert c.stats["errors"] >= 4
    # corrupt file -> treated as a miss, refetched and overwritten
    good = CachedProvider(_mock(), cache_dir=tmp_path)
    key = cache_key("news", {"query": "ondřej toman", "lang": "cs", "region": "CZ", "limit": 10}, "mock")
    (tmp_path / f"{key}.json").write_text("{broken", "utf-8")
    res = await good.news("Ondřej Toman")
    assert len(res) == 2 and _modes(res) == {"mock"}
    assert json.loads((tmp_path / f"{key}.json").read_text("utf-8"))["meta"]["count"] == 2


async def test_minor_in_cache_is_dropped_on_hit(tmp_path):
    ref = make_source_ref(url="https://www.tiktok.com/@kid", platform="tiktok", mode="live", actor="clockworks/tiktok-scraper")
    kid = Profile(handle="kid", platform="tiktok", url="https://www.tiktok.com/@kid", is_under_18=True, source=ref)
    ok = Profile(handle="ok", platform="tiktok", url="https://www.tiktok.com/@ok", is_under_18=False, source=ref)
    for p in (kid, ok):
        key = cache_key("profiles", {"handles": [p.handle], "platform": "tiktok"}, "apify")
        (tmp_path / f"{key}.json").write_text(json.dumps({"meta": {}, "items": [p.model_dump(mode="json")]}), "utf-8")

    class Apify:
        name = "apify"

    c = CachedProvider(Apify(), cache_dir=tmp_path, read_only=True)  # type: ignore[arg-type]
    out = await c.profiles(["kid", "ok"], "tiktok")
    assert [p.handle for p in out] == ["ok"] and out[0].source.mode == "cache"
    assert out[0].source.actor == "clockworks/tiktok-scraper"


# --------------------------------------------------------------------------------- purge / import


async def test_purge_cache(tmp_path):
    c = CachedProvider(_mock(), cache_dir=tmp_path)
    await c.profiles(["verca_pece", "brnenska_snidane"], "instagram")
    await c.news("Ondřej Toman")
    assert purge_cache(tmp_path) == 3
    assert list(tmp_path.glob("*.json")) == []
    assert purge_cache(tmp_path / "missing") == 0


async def test_purge_cache_default_dir_is_temp_data_dir():
    c = CachedProvider(_mock())
    await c.news("Ondřej Toman")
    d = get_settings().cache_dir
    assert list(d.glob("*.json"))
    assert purge_cache() == 1


async def test_import_cache_dir_roundtrip(tmp_path):
    src, dest = tmp_path / "krystof", tmp_path / "dest"

    class AsApify(MockProvider):  # Kryštof's files come from CachedProvider(ApifyProvider())
        name = "apify"

    writer = CachedProvider(AsApify(latency=0), cache_dir=src / "nested")
    prof = (await writer.profiles(["kuba.jidlo.brno"], "instagram"))[0]
    await writer.news("Jakub Horák")
    await writer.comments([prof.latest_posts[0].url])
    (src / "notes.json").write_text('{"hello": 1}', "utf-8")
    (src / "broken.json").write_text("{", "utf-8")

    stats = import_cache_dir(src, dest)
    assert stats["entries_written"] == 3 and stats["unknown"] == 1 and stats["invalid"] == 1

    class Apify:
        name = "apify"

    offline = CachedProvider(Apify(), cache_dir=dest, read_only=True)  # type: ignore[arg-type]
    assert len(await offline.profiles(["kuba.jidlo.brno"], "instagram")) == 1
    assert len(await offline.news("Jakub Horák")) == 2
    assert await offline.comments([prof.latest_posts[0].url])
    again = import_cache_dir(src, dest)
    assert again["skipped_existing"] == 3 and again["entries_written"] == 0


def test_import_splits_batch_files_and_raw_key_files(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    ref = lambda h: make_source_ref(url=f"https://www.instagram.com/{h}/", platform="instagram", mode="live",  # noqa: E731
                                    actor="apify/instagram-profile-scraper")
    profiles = [Profile(handle=h, platform="instagram", url=f"https://www.instagram.com/{h}/", source=ref(h))
                for h in ("a", "b")]
    batch = {"meta": {"provider": "apify", "method": "profiles", "args": {"handles": ["a", "b"], "platform": "instagram"}},
             "items": [p.model_dump(mode="json") for p in profiles]}
    (src / "batch.json").write_text(json.dumps(batch), "utf-8")
    news = NewsItem(id="news:1", title="T", outlet="O", url="https://x.example/1", published_at=None,
                    source=make_source_ref(url="https://x.example/1", platform="news", mode="live"))
    key = cache_key("news", {"query": "t", "lang": "cs", "region": "CZ", "limit": 10}, "apify")
    (src / f"{key}.json").write_text(json.dumps([news.model_dump(mode="json")]), "utf-8")
    stats = import_cache_dir(src, dest)
    assert stats["entries_written"] == 3
    for h in ("a", "b"):
        assert (dest / f"{cache_key('profiles', {'handles': [h], 'platform': 'instagram'}, 'apify')}.json").exists()
    assert (dest / f"{key}.json").exists()


async def test_end_to_end_with_mock_inner_twice(tmp_path):
    """Second run over the same cache never touches the inner provider for the funnel calls."""
    spy = Spy(_mock())
    c = CachedProvider(spy, cache_dir=tmp_path)

    async def funnel():
        refs = await c.discover(DEMO_DISCOVERY)
        ig = list(dict.fromkeys(r.handle for r in refs if r.platform == "instagram"))
        profs = await c.profiles(ig, "instagram")
        urls = [p.latest_posts[0].url for p in profs if p.latest_posts][:10]
        cms = await c.comments(urls)
        return refs, profs, cms

    a = await funnel()
    n = len(spy.calls)
    b = await funnel()
    assert len(spy.calls) == n
    assert [len(x) for x in a] == [len(x) for x in b]
    assert all(_modes(x) == {"cache"} for x in b)
