"""Fixes from the first real funnel run in Brno (Apify, 9. 10. 2026), provider and cache side.

(2) unflagged pinned posts, (5) discovery inputs, (9b) e-mail addresses are never mentions, (10) TikTok handles
and the TikTok search switch, (11) confirmed empty answers are cached, (12) posts are cached without ``since``.
Samples are HAND-MADE (tests/apify_samples/*_brno_run.json, ig_profile_pinned_collab.json): fictional accounts
shaped like the saved raw items. Nothing here calls Apify."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.compute.metrics import posts_per_week
from app.events import bind_emit
from app.models import DiscoveryQuery, Post, Profile, make_source_ref
from app.sources import apify_provider as ap
from app.sources.apify_provider import (
    ACT_BRAND,
    ACT_IG_POST,
    ACT_IG_PROFILE,
    ACT_IG_SCRAPER,
    ACT_IG_SEARCH,
    ACT_NEWS,
    ACT_TT,
    ACT_TT_PROFILE,
    ApifyProvider,
    RunResult,
)
from app.sources.cache import (
    POSTS_FULL_SINCE,
    CachedProvider,
    answer_is_complete,
    cache_key,
    import_cache_dir,
)

SAMPLES = Path(__file__).parent / "apify_samples"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def sample(name: str) -> list[dict]:
    return json.loads((SAMPLES / name).read_text("utf-8"))["items"]


class Runner:
    """Fake actor runner: ``routes`` maps an actor (or (actor, searchType)) to items or to a callable(run_input)."""

    def __init__(self, routes: dict | None = None, *, status: str = "SUCCEEDED", fail: bool = False) -> None:
        self.routes = routes or {}
        self.status = status
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, actor: str, run_input: dict, *, max_items: int, max_usd: float, timeout_s: int) -> RunResult:
        self.calls.append((actor, run_input))
        if self.fail:
            err = RuntimeError("Apify API 400 invalid input")
            err.status_code = 400   # type: ignore[attr-defined]  # a client error: no retry
            raise err
        route = self.routes.get((actor, run_input.get("searchType")), self.routes.get(actor, []))
        items = route(run_input) if callable(route) else route
        return RunResult(items=list(items), status=self.status, usd=0.0, events={"result": len(items)})

    def actors(self) -> list[str]:
        return [a for a, _ in self.calls]


@pytest.fixture
def logs():
    seen: list[dict] = []

    async def emit(event: str, data: dict) -> None:
        if event == "log":
            seen.append(data)

    with bind_emit(emit):
        yield seen


def text_of(logs: list[dict]) -> str:
    return " | ".join(x["text"] for x in logs)


def _post(code: str, day: str, *, pinned: bool | None = None, author: str = "anna") -> Post:
    url = f"https://www.instagram.com/p/{code}/"
    return Post(id=f"ig:post:{code}", platform="instagram", url=url, author_handle=author,
                created_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc), is_pinned=pinned,
                source=make_source_ref(url=url, platform="instagram", mode="live", actor=ACT_IG_PROFILE))


# ---------------------------------------------------------------------------------------------
# (2) pinned posts without a flag
# ---------------------------------------------------------------------------------------------


def test_unflagged_pinned_collab_no_longer_stretches_the_activity_window():
    """Brno run: 7 posts in 2 weeks scored 0.2 per week because an old pinned collab (owned by the partner, so no
    isPinned) led latestPosts."""
    p = ap.map_ig_profile(sample("ig_profile_pinned_collab.json")[0], actor=ACT_IG_PROFILE, fetched_at=NOW)
    flags = [x.is_pinned for x in p.latest_posts]
    assert flags[:2] == [True, True]                      # inferred (partner-owned) + explicit isPinned
    assert flags[2:] == [None] * 7                        # the regular grid is untouched
    assert p.latest_posts[0].author_handle == "sample_partner_bistro"
    assert p.latest_posts[0].coauthors == ["sample_weekly_eater"]   # still a collab post
    active = posts_per_week([x for x in p.latest_posts if not x.is_pinned])
    # metrics.posts_per_week now also skips leading out-of-order posts itself (engine-fixes),
    # so both the provider flag and the metric agree on the active window.
    assert active > 3.0 and posts_per_week(p.latest_posts) > 3.0   # 6 gaps over 13 days


def test_newest_unflagged_lead_post_is_not_marked():
    p = ap.map_ig_profile(sample("ig_profile_pinned_collab.json")[1], actor=ACT_IG_PROFILE, fetched_at=NOW)
    assert [x.is_pinned for x in p.latest_posts] == [None, None, None]   # in date order: nothing to infer


def test_mark_leading_pinned_rules():
    mark = ap.mark_leading_pinned
    # pins are a prefix: a post before an explicit pin is pinned even when it is in date order
    out = mark([_post("a", "2026-10-08"), _post("b", "2026-01-01", pinned=True), _post("c", "2026-10-07")])
    assert [x.is_pinned for x in out] == [True, True, None]
    # out-of-order leaders, up to MAX_PINNED
    seq = [_post("a", "2024-01-01"), _post("b", "2025-01-01"), _post("c", "2023-01-01"), _post("d", "2026-10-01"),
           _post("e", "2026-09-01")]
    assert [x.is_pinned for x in mark(seq)] == [True, True, True, None, None]
    # b is in order; c is only 4 days older than d (a grid quirk, under PIN_ORDER_SLACK): neither is a pin
    seq = [_post("a", "2025-01-01"), _post("b", "2026-10-07"), _post("c", "2026-10-01"), _post("d", "2026-10-05")]
    assert [x.is_pinned for x in mark(seq)] == [True, None, None, None]
    # an explicit False is kept and ends the scan
    seq = [_post("a", "2025-01-01", pinned=False), _post("b", "2024-01-01"), _post("c", "2026-10-01")]
    assert [x.is_pinned for x in mark(seq)] == [False, None, None]
    # equal timestamps are not "older"; a sorted grid stays untouched; never beyond the first three
    assert [x.is_pinned for x in mark([_post("a", "2026-10-01"), _post("b", "2026-10-01")])] == [None, None]
    seq = [_post(c, d) for c, d in (("a", "2026-01-01"), ("b", "2026-01-02"), ("c", "2026-01-03"),
                                    ("d", "2025-01-01"), ("e", "2026-10-01"))]
    assert [x.is_pinned for x in mark(seq)] == [True, True, True, None, None]
    assert mark([]) == []
    original = [_post("a", "2025-01-01"), _post("b", "2026-10-01")]
    mark(original)
    assert original[0].is_pinned is None                  # pure: the input is not mutated


# ---------------------------------------------------------------------------------------------
# (5) discovery inputs
# ---------------------------------------------------------------------------------------------


def test_city_evidence_name_bio_posts():
    items = {it["username"]: it for it in sample("ig_search_users_brno_run.json")}
    ev = {h: ap.search_user_city_evidence("Brno", it) for h, it in items.items()}
    assert ev == {
        "sample_bistro_hunter": "bio",          # creator: "v Brně" in the bio (declension)
        "sample_quiet_foodie": "posts",         # creator: 2 posts tagged in Brno, city nowhere in name / bio
        "sample_tourist_eats": None,            # 1 Brno post is not enough
        "sample_bruno_kitchen": None,           # fuzzy "bruno"
        "sample_bistro_brno": "name",           # an organisation: the name check keeps it (round 1 judges brands)
        "sample_volejbal_brno": "name",         # thin liveSearch item: only the name can match
        "sample_foodie_no_city": None,          # thin liveSearch item of a creator: no bio, no posts -> lost
    }
    assert ap.search_user_in_city(None, items["sample_bruno_kitchen"])


async def test_discover_uses_the_non_live_search_and_the_query_as_given(logs, monkeypatch):
    monkeypatch.setenv("APIFY_PLACES", "0")
    runner = Runner({(ACT_IG_SEARCH, "user"): sample("ig_search_users_brno_run.json")})
    refs = await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["brno foodie"], city="Brno", platforms=["instagram"]))
    assert sorted(r.handle for r in refs) == ["sample_bistro_brno", "sample_bistro_hunter", "sample_quiet_foodie",
                                              "sample_volejbal_brno"]
    (actor, run_input), = runner.calls
    assert actor == ACT_IG_SEARCH and run_input["search"] == "brno foodie" and run_input["searchType"] == "user"
    assert "liveSearch" not in run_input                  # non-live: bio + latestPosts come with the hit
    t = text_of(logs)
    assert "Brno podle jména 2, bio 1, míst postů 1" in t and "vynecháno: 3" in t
    assert "cesty: search 4" in t


@pytest.mark.parametrize("mode, runs", [(None, [False]), ("live", [True]), ("both", [False, True]),
                                        ("nonsense", [False])])
async def test_ig_search_mode_switch(mode, runs, monkeypatch, logs):
    monkeypatch.setenv("APIFY_PLACES", "0")
    if mode is None:
        monkeypatch.delenv("APIFY_IG_SEARCH", raising=False)
    else:
        monkeypatch.setenv("APIFY_IG_SEARCH", mode)
    runner = Runner({(ACT_IG_SEARCH, "user"): sample("ig_search_users_brno_run.json")})
    refs = await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["brno foodie"], city="Brno", platforms=["instagram"]))
    assert sorted(bool(r.get("liveSearch")) for _, r in runner.calls) == runs
    assert len(refs) == len({r.handle for r in refs}) == 4               # both sources merge into one ref each
    if mode == "both":
        assert "„brno foodie“ (live)" in text_of(logs)


async def test_discover_never_adds_the_defaults_itself(logs):
    runner = Runner()
    assert await ApifyProvider(token="t", runner=runner).discover(DiscoveryQuery(city="Brno")) == []
    assert runner.calls == []
    assert "default_discovery_query" in text_of(logs)


def test_default_discovery_query():
    from app.sources.factory import default_discovery_query

    q = default_discovery_query()
    assert q.keywords == list(ap.DEFAULT_KEYWORDS) == ["brno food", "brno foodie", "foodblog brno"]
    assert q.hashtags == list(ap.DEFAULT_HASHTAGS) == ["brnofood", "foodbrno"]
    assert q.city == "Brno" and q.places == ["Brno"]
    other = default_discovery_query("Hradec Králové", platforms=["instagram"])
    assert other.keywords[0] == "hradec králové food" and other.hashtags == ["hradeckralovefood", "foodhradeckralove"]
    assert other.platforms == ["instagram"]


async def test_place_author_path_is_on_by_default(logs, monkeypatch):
    monkeypatch.delenv("APIFY_PLACES", raising=False)
    routes = {(ACT_IG_SEARCH, "user"): [], (ACT_IG_SEARCH, "place"): json.loads(
        (SAMPLES / "ig_search_places.json").read_text("utf-8"))["items"],
              ACT_IG_SCRAPER: sample("ig_location_details.json")}
    runner = Runner(routes)
    refs = await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["brno food"], city="Brno", platforms=["instagram"]))
    place = next(r for a, r in runner.calls if a == ACT_IG_SEARCH and r["searchType"] == "place")
    assert place["search"] == "brno food" and "liveSearch" not in place
    by = {r.handle: r for r in refs}
    assert any(v.startswith("place:") for v in by["sample_place_author"].found_via)   # posts[].user.username
    monkeypatch.setenv("APIFY_PLACES", "0")
    runner = Runner(routes)
    await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["brno food"], city="Brno", platforms=["instagram"]))
    assert not any(r.get("searchType") == "place" for _, r in runner.calls)


# ---------------------------------------------------------------------------------------------
# (10) TikTok: search switch and handle validation
# ---------------------------------------------------------------------------------------------


def test_valid_tiktok_handle():
    ok = ap.valid_tiktok_handle
    assert ok("sample_cukrarka") and ok("@Anna.K_1") and ok("ab") and ok("a" * 24)
    assert not ok("jídlo") and not ok("a") and not ok("a" * 25) and not ok("anna-k") and not ok("") and not ok(None)


async def test_tiktok_search_is_off_by_default(logs, monkeypatch):
    monkeypatch.delenv("APIFY_TIKTOK_SEARCH", raising=False)
    monkeypatch.setenv("APIFY_PLACES", "0")
    runner = Runner()
    await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["jídlo"], city="Brno", platforms=["instagram", "tiktok"]))
    assert ACT_TT not in runner.actors() and ACT_IG_SEARCH in runner.actors()
    assert "APIFY_TIKTOK_SEARCH=1" in text_of(logs)


async def test_tiktok_search_when_on_drops_invalid_handles(logs, monkeypatch):
    monkeypatch.setenv("APIFY_TIKTOK_SEARCH", "1")
    runner = Runner({ACT_TT: sample("tt_search_brno_run.json")})
    refs = await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["jídlo"], city="Brno", platforms=["tiktok"]))
    assert [r.handle for r in refs] == ["sample_kebab_wien"]
    assert "neplatný handle vynechán: 1 (@jídlo)" in text_of(logs)
    assert [r.handle for r in ap.map_tt_search(sample("tt_search_brno_run.json"), query="x", actor=ACT_TT,
                                               fetched_at=NOW)] == ["sample_kebab_wien"]


async def test_invalid_tiktok_handle_never_reaches_a_profile_run(logs):
    runner = Runner({ACT_TT_PROFILE: sample("tt_profile_videos.json")})
    p = ApifyProvider(token="t", runner=runner)
    assert await p.profiles(["jídlo"], "tiktok") == []
    assert await p.posts("jídlo", "tiktok", NOW - timedelta(days=30)) == []
    assert runner.calls == []                             # nothing paid
    await p.profiles(["jídlo", "sample_cukrarka"], "tiktok")
    assert [r["profiles"] for _, r in runner.calls] == [["sample_cukrarka"]]
    prof = Profile(handle="sample_ig", platform="instagram", url="https://www.instagram.com/sample_ig/",
                   bio="Videa: tiktok.com/@jídlo", source=make_source_ref(url="u", platform="instagram", mode="live"))
    runner.calls.clear()
    assert await p.find_cross_platform(prof) == [] and runner.calls == []
    assert "neplatný" in text_of(logs)


# ---------------------------------------------------------------------------------------------
# (9b) e-mail addresses are never mentions or brand handles
# ---------------------------------------------------------------------------------------------


def test_email_in_caption_is_never_a_mention():
    base = {"ownerUsername": "anna", "url": "https://www.instagram.com/p/E1/", "timestamp": "2026-10-01"}
    cap = "Objednávky: objednavky@samplemedia.example, díky @sample_friend!"

    def mentions(**kw):
        return ap.map_ig_post({**base, "caption": cap, **kw}, actor=ACT_IG_POST, fetched_at=NOW).mentions

    assert mentions(mentions=[]) == ["sample_friend"]                         # caption fallback (profile scraper)
    assert mentions(mentions=["samplemedia.example", "sample_friend"]) == ["sample_friend"]   # naive actor list
    assert mentions(mentions=["samplemedia"]) == []
    hyphen = {**base, "caption": "info@sample-shop.example", "mentions": ["sample"]}
    assert ap.map_ig_post(hyphen, actor=ACT_IG_POST, fetched_at=NOW).mentions == []
    both = {**base, "caption": "@samplemedia.example píše na x@samplemedia.example", "mentions": []}
    assert ap.map_ig_post(both, actor=ACT_IG_POST, fetched_at=NOW).mentions == ["samplemedia.example"]
    assert ap.caption_mentions("ahoj @anna.k. a .@eva a mail@x.cz") == ["anna.k"]
    prof = ap.map_ig_profile(sample("ig_profile_pinned_collab.json")[0], actor=ACT_IG_PROFILE, fetched_at=NOW)
    assert all("samplemedia" not in m for x in prof.latest_posts for m in x.mentions)
    tt = {"webVideoUrl": "https://www.tiktok.com/@anna/video/1", "createTimeISO": "2026-10-01T00:00:00Z",
          "text": "spolupráce: anna@samplemedia.example @sample_brand", "mentions": ["@sample_brand"]}
    assert ap.map_tt_video(tt, actor=ACT_TT, fetched_at=NOW).mentions == ["sample_brand"]
    tt_bare = {**tt, "mentions": []}
    assert ap.map_tt_video(tt_bare, actor=ACT_TT, fetched_at=NOW).mentions == ["sample_brand"]


def test_email_in_bio_is_never_a_linked_account_and_comments_mask_it():
    src = make_source_ref(url="u", platform="instagram", mode="live")
    p = Profile(handle="anna", platform="instagram", url="https://www.instagram.com/anna/", source=src,
                bio="ig@samplecafe.example | yt@samplestudio.example | TikTok: @sample_tt")
    assert ap.cross_platform_links(p) == [("tiktok", "sample_tt", "https://www.tiktok.com/@sample_tt")]
    assert ap.mask_mentions("napiš na jan.novak@samplemail.example @eva") == "napiš na [e-mail] @user"
    # masking is privacy, not mention detection: a handle right after a letter or a dot is masked too
    assert ap.mask_mentions("díky@sample_jana") == "díky@user"
    assert ap.mask_mentions("wow!!.@sample_petr a @sample.eva.") == "wow!!.@user a @user."
    assert ap.caption_mentions("díky@sample_jana") == []    # ...while it is still never a mention


# ---------------------------------------------------------------------------------------------
# (11) confirmed empty answers are cached
# ---------------------------------------------------------------------------------------------


def _files(d: Path) -> list[dict]:
    return [json.loads(f.read_text("utf-8")) for f in sorted(d.glob("*.json"))]


async def test_empty_cross_platform_answer_is_cached_and_replays_offline(tmp_path, logs):
    runner = Runner()
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    prof = Profile(handle="sample_solo", platform="instagram", url="https://www.instagram.com/sample_solo/",
                   bio="jen Instagram", source=make_source_ref(url="u", platform="instagram", mode="live"))
    assert await c.find_cross_platform(prof) == []
    (entry,) = _files(tmp_path)
    assert entry["meta"]["empty"] is True and entry["meta"]["count"] == 0 and entry["items"] == []
    offline = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path, read_only=True)
    logs.clear()
    assert await offline.find_cross_platform(prof) == []
    assert offline.stats["hits"] == 1 and offline.stats["misses"] == 0
    assert "z cache: cross-platform @sample_solo (0, prázdná odpověď)" in text_of(logs)
    assert "není v cache" not in text_of(logs)


async def test_collabs_switched_off_is_cached_under_its_own_variant(tmp_path, monkeypatch):
    monkeypatch.delenv("APIFY_META_BRANDED", raising=False)
    runner = Runner({ACT_BRAND: sample("brand_collabs.json")})
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    assert await c.collabs("sample_cukrarka_brno", "instagram") == []
    (entry,) = _files(tmp_path)
    assert entry["meta"]["args"]["variant"] == "meta_branded_off" and entry["meta"]["empty"] is True
    offline = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path, read_only=True)
    assert await offline.collabs("sample_cukrarka_brno", "instagram") == [] and offline.stats["hits"] == 1
    monkeypatch.setenv("APIFY_META_BRANDED", "1")          # switching it on is a miss, never a stale []
    out = await c.collabs("sample_cukrarka_brno", "instagram")
    assert out and runner.actors() == [ACT_BRAND]
    assert cache_key("collabs", {"handle": "sample_cukrarka_brno", "platform": "instagram"}, "apify") in \
        {f.stem for f in tmp_path.glob("*.json")}          # the switched-on key is the old key


async def test_empty_answer_after_a_failed_or_partial_run_is_not_cached(tmp_path):
    for runner in (Runner(fail=True), Runner(status="TIMED-OUT")):
        c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
        assert await c.news("Sample Nikdo") == []
        assert await c.posts("sample_nobody", "instagram", NOW - timedelta(days=30)) == []
        assert list(tmp_path.glob("*.json")) == []
    no_token = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path)
    assert await no_token.news("Sample Nikdo") == [] and list(tmp_path.glob("*.json")) == []


async def test_confirmed_empty_news_and_comments_are_cached_but_never_discover_or_profiles(tmp_path):
    url = "https://www.instagram.com/p/SAMPLEnone/"
    post_without_comments = {"url": url, "shortCode": "SAMPLEnone", "ownerUsername": "sample_quiet",
                             "timestamp": "2026-10-01T10:00:00.000Z", "caption": "x", "latestComments": []}
    runner = Runner({ACT_NEWS: [], ACT_IG_POST: [post_without_comments], ACT_IG_PROFILE: [], ACT_IG_SEARCH: []})
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    assert await c.news("Sample Nikdo") == []
    assert await c.comments([url]) == []
    assert await c.discover(DiscoveryQuery(keywords=["x"], city="Brno", platforms=["instagram"])) == []
    assert await c.profiles(["sample_nobody"], "instagram") == []
    methods = sorted(e["meta"]["method"] for e in _files(tmp_path))
    assert methods == ["comments", "news"]
    n = len(runner.calls)
    assert await c.news("Sample Nikdo") == [] and await c.comments([url]) == []
    assert len(runner.calls) == n                         # both are hits now


async def test_comments_over_the_post_limit_are_never_cached_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "COMMENT_POSTS_MAX", 1)
    runner = Runner({ACT_IG_POST: []})
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    await c.comments(["https://www.instagram.com/p/SAMPLEa/", "https://www.instagram.com/p/SAMPLEb/"])
    assert list(tmp_path.glob("*.json")) == []            # SAMPLEb was never fetched: not "no comments"


async def test_answer_is_complete_is_opt_in(tmp_path):
    class Quiet:
        name = "quiet"

        async def news(self, *a, **k):
            return []

    class Sure(Quiet):
        async def news(self, *a, **k):
            answer_is_complete()
            return []

    await CachedProvider(Quiet(), cache_dir=tmp_path).news("x")     # type: ignore[arg-type]
    assert list(tmp_path.glob("*.json")) == []
    await CachedProvider(Sure(), cache_dir=tmp_path).news("x")      # type: ignore[arg-type]
    assert len(list(tmp_path.glob("*.json"))) == 1
    answer_is_complete()                                  # outside CachedProvider: a no-op


def test_import_keeps_empty_entries(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    for method, args in (("collabs", {"handle": "anna", "platform": "instagram", "variant": "meta_branded_off"}),
                         ("comments", {"post_urls": ["https://www.instagram.com/p/X/"], "per_post": 15}),
                         ("discover", {"q": {"keywords": ["x"]}})):
        (src / f"{method}.json").write_text(json.dumps({"meta": {"provider": "apify", "method": method, "args": args,
                                                                 "empty": True}, "items": []}), "utf-8")
    stats = import_cache_dir(src, dest)
    assert stats["entries_written"] == 2 and stats["unknown"] == 1       # discover is never an empty answer
    assert (dest / f"{cache_key('comments', {'post_urls': ['https://www.instagram.com/p/X'], 'per_post': 15}, 'apify')}"
                   f".json").exists()


# ---------------------------------------------------------------------------------------------
# (12) posts cached without since
# ---------------------------------------------------------------------------------------------


def _ig_posts_items() -> list[dict]:
    return [{"ownerUsername": "sample_weekly_eater", "url": f"https://www.instagram.com/p/SAMPLEq{i}/",
             "shortCode": f"SAMPLEq{i}", "timestamp": f"2026-{m:02d}-15T10:00:00.000Z", "caption": "x"}
            for i, m in enumerate((10, 9, 8, 7, 5, 3), start=1)]


async def test_posts_cache_key_has_no_since_and_filters_on_read(tmp_path, logs):
    runner = Runner({ACT_IG_POST: _ig_posts_items()})
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    day1 = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
    first = await c.posts("sample_weekly_eater", "instagram", day1, limit=50)
    assert [p.id for p in first] == [f"ig:post:SAMPLEq{i}" for i in (1, 2, 3, 4, 5)]
    (entry,) = _files(tmp_path)
    assert entry["meta"]["args"] == {"handle": "sample_weekly_eater", "platform": "instagram", "limit": 50}
    assert entry["meta"]["count"] == 6 and "since" not in entry["meta"]     # the full list
    assert "bez filtru data" in text_of(logs)             # the provider was asked for everything
    # round 4 the next day, and a wider window: no new run, filtered on read
    nxt = await c.posts("sample_weekly_eater", "instagram", day1 + timedelta(days=1), limit=50)
    wide = await c.posts("sample_weekly_eater", "instagram", day1 - timedelta(days=60), limit=50)
    few = await c.posts("sample_weekly_eater", "instagram", day1, limit=2)
    assert len(runner.calls) == 1 + 1                     # limit 2 is another key (another actor resultsLimit)
    assert [p.id for p in nxt] == [p.id for p in first] and len(wide) == 6
    assert [p.id for p in few] == ["ig:post:SAMPLEq1", "ig:post:SAMPLEq2"]
    assert {p.source.mode for p in nxt} == {"cache"}
    offline = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path, read_only=True)
    assert len(await offline.posts("sample_weekly_eater", "instagram", day1 + timedelta(days=40))) == 4


async def test_posts_inner_call_asks_for_the_full_list(tmp_path):
    seen: list = []

    class Inner:
        name = "apify"

        async def posts(self, handle, platform, since, limit=50):
            seen.append(since)
            return []

    c = CachedProvider(Inner(), cache_dir=tmp_path)        # type: ignore[arg-type]
    await c.posts("anna", "instagram", NOW - timedelta(days=180))
    assert seen == [POSTS_FULL_SINCE]


def _write_entry(d: Path, method: str, args: dict, items: list, **meta) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{cache_key(method, args, 'apify')}.json"
    path.write_text(json.dumps({"meta": {"provider": "apify", "method": method, "args": args, **meta},
                                "items": [x.model_dump(mode="json") for x in items]}), "utf-8")
    return path


async def test_legacy_since_keyed_posts_entry_still_replays(tmp_path, logs):
    """Old cache files (Brno live run) keyed posts with the UTC date of since: they serve that day and later."""
    posts = [_post("L1", "2026-09-01", author="sample_weekly_eater"), _post("L2", "2026-05-01", author="sample_weekly_eater")]
    legacy_args = {"handle": "sample_weekly_eater", "platform": "instagram", "since": "2026-04-12", "limit": 50}
    _write_entry(tmp_path, "posts", legacy_args, posts)
    offline = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path, read_only=True)
    later = await offline.posts("sample_weekly_eater", "instagram", datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert [p.id for p in later] == ["ig:post:L1"]
    assert await offline.posts("sample_weekly_eater", "instagram", datetime(2026, 4, 11, tzinfo=timezone.utc)) == []
    assert "není v cache" in text_of(logs)                # an earlier since is not covered by that entry
    # online: a covered since is served from the legacy file, an earlier one fetches the full list once
    runner = Runner({ACT_IG_POST: _ig_posts_items()})
    online = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    assert len(await online.posts("sample_weekly_eater", "instagram", datetime(2026, 6, 1, tzinfo=timezone.utc))) == 1
    assert runner.calls == []
    full = await online.posts("sample_weekly_eater", "instagram", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert len(full) == 6 and len(runner.calls) == 1
    again = await online.posts("sample_weekly_eater", "instagram", datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert len(again) == 4 and len(runner.calls) == 1     # the new full-list entry wins over the legacy one


def test_import_rekeys_since_keyed_posts(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    posts = [_post("I1", "2026-09-01", author="anna")]
    _write_entry(src, "posts", {"handle": "anna", "platform": "instagram", "since": "2026-04-12", "limit": 50}, posts)
    assert import_cache_dir(src, dest)["entries_written"] == 1
    entry = json.loads((dest / f"{cache_key('posts', {'handle': 'anna', 'platform': 'instagram', 'limit': 50}, 'apify')}"
                                f".json").read_text("utf-8"))
    assert entry["meta"]["since"] == "2026-04-12" and len(entry["items"]) == 1


# ---------------------------------------------------------------------------------------------
# Review of 6f15f01: pins behind pins, failed fetches never cached as answers, discover key, cache-hit hook
# ---------------------------------------------------------------------------------------------


def test_old_pin_behind_a_newer_pin_is_marked():
    mark = ap.mark_leading_pinned
    # [Oct 5 pin, Jan 11 pin, Oct 4, ...]: the January pin must not stretch the activity window; pins are a prefix,
    # so the post before it is a pin too
    seq = [_post("a", "2026-10-05"), _post("b", "2026-01-11"), _post("c", "2026-10-04"), _post("d", "2026-10-01")]
    assert [x.is_pinned for x in mark(seq)] == [True, True, None, None]
    # shape of a cached Brno profile (dates only): three pins, the middle one newer than the regular grid
    seq = [_post(c, d) for c, d in (("a", "2024-07-04"), ("b", "2026-09-13"), ("c", "2026-01-30"),
                                    ("d", "2026-06-11"), ("e", "2026-06-10"))]
    assert [x.is_pinned for x in mark(seq)] == [True, True, True, None, None]
    # an explicit False ends the scan, an explicit True still pins the posts before it
    seq = [_post("a", "2026-10-05"), _post("b", "2026-10-04", pinned=False), _post("c", "2025-01-01"),
           _post("d", "2026-10-01")]
    assert [x.is_pinned for x in mark(seq)] == [None, False, None, None]
    # idempotent (the cache-hit hook may run it on profiles that were marked when they were fetched)
    seq = [_post("a", "2026-10-05"), _post("b", "2026-01-11"), _post("c", "2026-10-04"), _post("d", "2026-10-01")]
    once = mark(seq)
    assert [x.is_pinned for x in mark(once)] == [x.is_pinned for x in once]


class CapRunner(Runner):
    """Every run reports a charge at its cap (Apify stopped it there)."""

    async def __call__(self, actor, run_input, *, max_items, max_usd, timeout_s):
        res = await super().__call__(actor, run_input, max_items=max_items, max_usd=max_usd, timeout_s=timeout_s)
        return RunResult(items=res.items, status=res.status, usd=max_usd, events=res.events)


async def test_error_only_and_empty_runs_are_never_cached_as_answers(tmp_path):
    url = "https://www.instagram.com/p/SAMPLEgap/"
    tt_link = Profile(handle="sample_linked", platform="instagram", url="https://www.instagram.com/sample_linked/",
                      bio="Brno jídlo. TikTok: @sample_linked_tt",
                      source=make_source_ref(url="u", platform="instagram", mode="live"))
    cases = [
        # IG posts: only a no_items error item ("Empty or private data")
        (Runner({ACT_IG_POST: [{"error": "no_items", "errorDescription": "Empty or private data"}]}),
         lambda c: c.posts("sample_nobody", "instagram", NOW - timedelta(days=180))),
        # IG posts: SUCCEEDED with 0 items (an empty full list is not an answer)
        (Runner({ACT_IG_POST: []}), lambda c: c.posts("sample_nobody", "instagram", NOW - timedelta(days=180))),
        # TikTok PROFILE_EMPTY (gap or login wall) behind a cross-platform link
        (Runner({ACT_TT_PROFILE: [{"url": "https://www.tiktok.com/@sample_linked_tt", "errorCode": "PROFILE_EMPTY",
                                   "error": "Profile is empty (or behind a login wall)"}]}),
         lambda c: c.find_cross_platform(tt_link)),
        # latestComments: the run returned no post item for the URL
        (Runner({ACT_IG_POST: []}), lambda c: c.comments([url])),
        # latestComments: the run stopped at its charge cap
        (CapRunner({ACT_IG_POST: []}), lambda c: c.comments([url])),
    ]
    for runner, call in cases:
        c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
        assert await call(c) == []
        assert runner.calls and list(tmp_path.glob("*.json")) == []


async def test_not_found_and_private_are_answers(tmp_path):
    prof = Profile(handle="sample_tt_only", platform="tiktok", url="https://www.tiktok.com/@sample_tt_only",
                   bio="IG: @sample_gone_ig", source=make_source_ref(url="u", platform="tiktok", mode="live"))
    runner = Runner({ACT_IG_PROFILE: [{"username": "sample_gone_ig", "url": "https://www.instagram.com/sample_gone_ig",
                                       "error": "not_found", "errorDescription": "Page not found"}]})
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    assert await c.find_cross_platform(prof) == []
    (entry,) = _files(tmp_path)
    assert entry["meta"]["method"] == "find_cross_platform" and entry["meta"]["empty"] is True


async def test_empty_posts_entry_from_older_code_is_a_miss(tmp_path):
    _write_entry(tmp_path, "posts", {"handle": "sample_weekly_eater", "platform": "instagram", "limit": 50}, [],
                 empty=True)
    runner = Runner({ACT_IG_POST: _ig_posts_items()})
    c = CachedProvider(ApifyProvider(token="t", runner=runner), cache_dir=tmp_path)
    out = await c.posts("sample_weekly_eater", "instagram", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert len(out) == 6 and len(runner.calls) == 1


def test_discover_variant_only_off_defaults(monkeypatch):
    for k in ("APIFY_IG_SEARCH", "APIFY_PLACES", "APIFY_TIKTOK_SEARCH"):
        monkeypatch.delenv(k, raising=False)
    prov = ApifyProvider(token="t", runner=Runner())
    assert prov.cache_variant("discover") is None
    monkeypatch.setenv("APIFY_IG_SEARCH", "nonlive")
    monkeypatch.setenv("APIFY_PLACES", "1")
    monkeypatch.setenv("APIFY_TIKTOK_SEARCH", "0")
    assert prov.cache_variant("discover") is None          # explicit defaults keep the default key
    monkeypatch.setenv("APIFY_IG_SEARCH", "both")
    monkeypatch.setenv("APIFY_PLACES", "0")
    monkeypatch.setenv("APIFY_TIKTOK_SEARCH", "1")
    assert prov.cache_variant("discover") == "ig_search=both,places=off,tiktok_search=on"


async def test_discover_cache_key_follows_the_switches(tmp_path, monkeypatch):
    for k in ("APIFY_IG_SEARCH", "APIFY_PLACES", "APIFY_TIKTOK_SEARCH"):
        monkeypatch.delenv(k, raising=False)
    q = DiscoveryQuery(keywords=["brno food"], city="Brno", platforms=["instagram"])
    ref = ap.CandidateRef(handle="sample_found", platform="instagram", found_via=["search:brno food"],
                          source=make_source_ref(url="https://www.instagram.com/sample_found/", platform="instagram",
                                                 mode="live", actor=ACT_IG_SEARCH))
    _write_entry(tmp_path, "discover", {"q": q.model_dump(mode="json")}, [ref])   # default key = older caches' key
    offline = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path, read_only=True)
    assert [r.handle for r in await offline.discover(q)] == ["sample_found"]
    monkeypatch.setenv("APIFY_IG_SEARCH", "live")
    assert await offline.discover(q) == [] and offline.stats["misses"] == 1   # another search, another answer


async def test_cached_ig_profile_gets_its_pins_inferred_on_read(tmp_path, logs):
    """Profiles cached before the pin rule (live-run cache) replay with the pins inferred."""
    posts = [_post("P1", "2025-02-01", author="sample_partner_bistro"),
             *[_post(f"R{i}", f"2026-10-0{i}", author="sample_weekly_eater") for i in range(8, 1, -1)]]
    prof = Profile(handle="sample_weekly_eater", platform="instagram", url="https://www.instagram.com/sample_weekly_eater/",
                   latest_posts=posts, source=make_source_ref(url="u", platform="instagram", mode="live",
                                                               actor=ACT_IG_PROFILE))
    _write_entry(tmp_path, "profiles", {"handles": ["sample_weekly_eater"], "platform": "instagram"}, [prof])
    offline = CachedProvider(ApifyProvider(token=""), cache_dir=tmp_path, read_only=True)
    (got,) = await offline.profiles(["sample_weekly_eater"], "instagram")
    assert [x.is_pinned for x in got.latest_posts] == [True] + [None] * 7
    assert {x.source.mode for x in got.latest_posts} == {"cache"} and got.source.mode == "cache"
    assert posts_per_week([x for x in got.latest_posts if not x.is_pinned]) > 3.0
    stored = _files(tmp_path)[0]["items"][0]["latest_posts"]
    assert stored[0].get("is_pinned") is None              # read-only: the file itself is unchanged
