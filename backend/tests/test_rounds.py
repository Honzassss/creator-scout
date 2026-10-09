"""Funnel engine tests with a small inline FakeProvider and monkeypatched LLM functions.

They do not depend on fixtures/ (another agent writes those). The last test checks the designed
outcomes with the real MockProvider and is skipped while fixtures/ is missing.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from app.llm import sensitive, topics, vetting
from app.models import (
    CandidateRef,
    ClaimCheck,
    Comment,
    CriteriaSet,
    DiscoveryQuery,
    NewsFinding,
    NewsItem,
    Post,
    Profile,
    Report,
    Run,
    i18n,
    make_source_ref,
)
from app.presets import get_preset
from app.rounds import engine, r0_discovery, r4_vetting

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------------------------
# Inline dataset
# ---------------------------------------------------------------------------------------------

CS_FOOD = [
    "Dnes jsme v Brně pekli kváskový chléb, recept najdete v bio",
    "Nejlepší croissanty ve městě, tohle musíte ochutnat",
    "Víkendová snídaně s koláči od babičky, jednoduchý recept",
    "Zkoušíme nové bistro na Zelném trhu, jídlo bylo výborné",
    "Domácí buchty podle mámy, recept je jednoduchý a rychlý",
    "Ranní káva a čerstvé pečivo, lepší start dne neznám",
    "Upekla jsem žitný chléb poprvé a povedl se mi",
    "Tip na oběd v centru: polévka a domácí chleba",
]
EN_FOOD = [
    "Baking sourdough bread today, recipe in my bio",
    "Best croissants in town, you have to try these",
    "Weekend breakfast with homemade cakes and coffee",
    "Trying a new bistro downtown, the food was great",
    "Homemade buns from my mom's recipe, quick and easy",
    "Morning coffee with fresh pastries, perfect start",
    "I baked rye bread for the first time and it worked",
    "Lunch tip downtown: soup and homemade bread today",
]
CS_TRAVEL = [
    "Cestujeme po Itálii, dnes jsme navštívili Florencii",
    "Hory v Rakousku jsou na podzim nádherné, doporučuji",
    "Víkend v Paříži a spousta procházek po městě",
    "Letíme na Island, těšíme se na gejzíry a vodopády",
    "Pláže v Chorvatsku jsou mimo sezónu skoro prázdné",
    "Toulky po Skotsku a hrady na každém kroku",
    "Výlet do Vídně vlakem je rychlý a pohodlný",
    "Norské fjordy jsou nejkrásnější místo, kde jsem byl",
]
CS_FIT = [
    "Ranní trénink v Brně, dnes nohy a hodně dřepů",
    "Jak začít cvičit doma bez vybavení, krátký návod",
    "Běh kolem přehrady a pak protažení, skvělý start",
    "Silový trénink pro začátečníky, tři cviky na záda",
    "Cvičení s kamarády v parku, motivace je všechno",
    "Moje rutina na mobilitu po celém dni v kanceláři",
    "Zkoušíme kruhový trénink, po dvaceti minutách hotovo",
    "Strečink na večer, aby se dobře spalo a odpočinulo",
]
CS_COMMENTS = [
    "Vypadá to skvěle, kde to koupím?",
    "Tohle musím vyzkoušet o víkendu",
    "Díky za tip, zítra tam zajdu",
    "Byla jsem tam včera a bylo to výborné",
    "Super recept, pekla jsem podle něj",
    "😍",
]
EN_COMMENTS = ["Looks amazing, where is this place?", "I need to try this soon", "Great tip, thanks a lot",
               "Where can I buy this bread?", "Love your content so much", "🔥"]
EMOJI_COMMENTS = ["😍😍", "🔥🔥🔥", "❤️", "👏👏", "super", "wow"]


def _src(url: str, platform: str = "instagram", sid: str | None = None):
    return make_source_ref(url=url, platform=platform, mode="mock", id=sid, actor="fake/test", fetched_at=NOW)


def _posts(handle: str, captions: list[str], *, start_days: float = 1, step: float = 3, likes: int = 400,
           comments: int = 20, hashtags: list[str] | None = None, media: tuple[str, ...] = ("reel", "photo"),
           location: str | None = None, extra: dict[int, dict] | None = None) -> list[Post]:
    out = []
    for i, cap in enumerate(captions):
        pid = f"{handle}_{i}"
        url = f"https://www.instagram.com/p/{pid}/"
        kw = dict(id=pid, platform="instagram", url=url, author_handle=handle,
                  created_at=NOW - timedelta(days=start_days + i * step), caption=cap,
                  hashtags=list(hashtags or []), media_type=media[i % len(media)], likes=likes, comments=comments,
                  location_name=location if i == 0 else None, paid_partnership=False,
                  source=_src(url, sid=f"ig:post:{pid}"))
        kw.update((extra or {}).get(i, {}))
        out.append(Post(**kw))
    return out


def _profile(handle: str, followers: int, posts: list[Post], **kw) -> Profile:
    url = f"https://www.instagram.com/{handle}/"
    base = dict(handle=handle, platform="instagram", url=url, display_name=kw.pop("display_name", handle.title()),
                followers=followers, posts_count=len(posts) + 50, private=False, is_business=False,
                latest_posts=posts, source=_src(url, sid=f"ig:profile:{handle}"))
    base.update(kw)
    return Profile(**base)


def build_dataset() -> dict[str, Profile]:
    d: dict[str, Profile] = {}
    d["anna_pece"] = _profile(
        "anna_pece", 12000,
        _posts("anna_pece", CS_FOOD + ["Nemoc mě skolila, dnes jen čaj"], hashtags=["jidlo", "brnofood"], location="Brno, Zelný trh",
               extra={7: {"caption": "Nový kváskový chléb #reklama", "hashtags": ["jidlo", "reklama"], "paid_partnership": True}}),
        display_name="Anna Nováková", bio="Peču a ochutnávám v Brně 🥐 exkluzivní ambasador @pekarna_a",
        external_urls=["https://annapece.cz"])
    d["private_petr"] = _profile("private_petr", 8000, [], private=True)
    d["big_star"] = _profile("big_star", 300000, _posts("big_star", CS_FOOD, hashtags=["jidlo"]))
    d["pekarna_brand"] = _profile("pekarna_brand", 9000, _posts("pekarna_brand", CS_FOOD, hashtags=["jidlo"]),
                                  is_business=True, business_category="Bakery")
    d["english_emma"] = _profile("english_emma", 15000, _posts("english_emma", EN_FOOD, hashtags=["food"]))
    d["inactive_ivan"] = _profile("inactive_ivan", 20000, _posts("inactive_ivan", CS_FOOD, start_days=100, hashtags=["jidlo"]))
    d["travel_tom"] = _profile("travel_tom", 20000, _posts("travel_tom", CS_TRAVEL, hashtags=["cestovani", "brno"], likes=800))
    d["lowengage_lenka"] = _profile("lowengage_lenka", 40000, _posts("lowengage_lenka", CS_FOOD, hashtags=["jidlo", "brno"], likes=50, comments=2))
    d["emoji_eva"] = _profile("emoji_eva", 10000, _posts("emoji_eva", CS_FOOD, hashtags=["jidlo", "brno"], likes=300))
    d["fit_filip"] = _profile("fit_filip", 18000, _posts("fit_filip", CS_FIT, hashtags=["fitness", "brno"], likes=500,
                                                        media=("reel", "reel", "photo")))
    d["minor_mia"] = _profile("minor_mia", 7000, _posts("minor_mia", CS_FOOD, hashtags=["jidlo"]), is_under_18=True)
    d["minor_max"] = _profile("minor_max", 7000, _posts("minor_max", CS_FOOD, hashtags=["jidlo"]), is_under_18=True)
    return d


def comments_for(handle: str) -> list[str]:
    if handle == "emoji_eva":
        return EMOJI_COMMENTS
    if handle == "english_emma":
        return EN_COMMENTS
    if handle == "fit_filip":
        return ["Skvělý trénink, zkusím to zítra", "Díky za motivaci, jdu cvičit", "Kde v Brně cvičíš?",
                "Tohle cvičení mi pomohlo se zády", "💪"]
    return CS_COMMENTS + ["Politika je hrozná, volte jinak"]


class FakeProvider:
    """In-memory SourceProvider. Drops minors like a real provider, except ``minor_max`` (tests the
    engine's own guard). Counts calls so tests can assert "no fetch"."""

    name = "fake"

    def __init__(self) -> None:
        self.data = build_dataset()
        self.calls: Counter[str] = Counter()

    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]:
        self.calls["discover"] += 1
        refs = []
        for h in self.data:
            refs.append(CandidateRef(handle=h, platform="instagram", found_via=["hashtag:brnofood"],
                                     source=_src(f"https://www.instagram.com/explore/tags/brnofood/#{h}")))
        refs.append(CandidateRef(handle="@Anna_Pece", platform="instagram", found_via=["search:pekárna brno"],
                                 source=_src("https://www.instagram.com/anna_pece/")))
        return refs

    async def profiles(self, handles, platform):
        self.calls["profiles"] += 1
        out = []
        for h in handles:
            p = self.data.get(h)
            if p is None or (p.is_under_18 and h != "minor_max"):
                continue
            out.append(p.model_copy(deep=True))
        return out

    async def posts(self, handle, platform, since, limit=50):
        self.calls["posts"] += 1
        if handle != "anna_pece":
            return []
        mk = lambda i, cap, days, **kw: Post(  # noqa: E731
            id=f"old_{i}", platform="instagram", url=f"https://www.instagram.com/p/old_{i}/", author_handle=handle,
            created_at=NOW - timedelta(days=days), caption=cap, likes=300, comments=10,
            source=_src(f"https://www.instagram.com/p/old_{i}/", sid=f"ig:post:old_{i}"), **kw)
        return [
            mk(1, "Snídaně s @pekarna_b #spoluprace", 30, coauthors=["pekarna_b"], hashtags=["spoluprace"], paid_partnership=True),
            mk(2, "Ranní pečivo s @pekarna_b 🥐", 45, coauthors=["pekarna_b"], paid_partnership=False),
            mk(3, "Recenze, nikdo mi neplatí. Se slevovým kódem ANNA20 máte slevu na @kavarna_x", 60, paid_partnership=False),
            mk(4, "Volby a politika, sdílím názor", 70, paid_partnership=False),
        ]

    async def comments(self, post_urls, per_post=15):
        self.calls["comments"] += 1
        out = []
        for url in post_urls:
            handle = url.rstrip("/").split("/")[-1].rsplit("_", 1)[0]
            for t in comments_for(handle)[:per_post]:
                out.append(Comment(post_url=url, text=t, source=_src(url)))
        return out

    async def collabs(self, handle, platform):
        self.calls["collabs"] += 1
        return []

    async def news(self, query, lang="cs", region="CZ", limit=10):
        self.calls["news"] += 1
        if query != "Anna Nováková":
            return []
        mk = lambda i, title: NewsItem(id=f"news:{i}", title=title, outlet="Deník", url=f"https://denik.cz/{i}",  # noqa: E731
                                       published_at=NOW - timedelta(days=20), source=_src(f"https://denik.cz/{i}", "news"))
        return [mk("a", "Starostka Anna Nováková (54) otevřela park v Olomouci"),
                mk("b", "Brněnská tvůrkyně @anna_pece upekla rekordní chléb")]

    async def find_cross_platform(self, profile):
        self.calls["cross"] += 1
        if profile.handle != "anna_pece":
            return []
        url = "https://www.tiktok.com/@annapece"
        fan = "https://www.tiktok.com/@annapece_fans"
        return [Profile(handle="annapece", platform="tiktok", url=url, display_name="Anna Nováková",
                        bio="IG @anna_pece", external_urls=["annapece.cz"], source=_src(url, "tiktok")),
                Profile(handle="annapece_fans", platform="tiktok", url=fan, display_name="Anna fanpage",
                        bio="fan page, not affiliated", source=_src(fan, "tiktok"))]


# ---------------------------------------------------------------------------------------------
# LLM fakes (deterministic; the real llm/ module is another agent's)
# ---------------------------------------------------------------------------------------------

SENSITIVE_WORDS = ("nemoc", "politik", "volby")


def _flag(text: str) -> bool:
    return any(w in (text or "").lower() for w in SENSITIVE_WORDS)


class LLMCalls(Counter):
    pass


@pytest.fixture
def llm(monkeypatch):
    calls = LLMCalls()

    async def filter_profile(p: Profile):
        calls["filter_profile"] += 1
        kept = [x for x in p.latest_posts if not _flag(x.caption)]
        dropped = len(p.latest_posts) - len(kept)
        bio = p.bio
        if _flag(bio):
            bio, dropped = "", dropped + 1
        return p.model_copy(update={"latest_posts": kept, "bio": bio}), dropped

    async def filter_posts(posts):
        calls["filter_posts"] += 1
        kept = [x for x in posts if not _flag(x.caption)]
        return kept, len(posts) - len(kept)

    async def filter_comments(cms):
        calls["filter_comments"] += 1
        kept = [x for x in cms if not _flag(x.text)]
        return kept, len(cms) - len(kept)

    async def filter_news(items):
        calls["filter_news"] += 1
        kept = [x for x in items if not _flag(x.title + x.snippet)]
        return kept, len(items) - len(kept)

    async def classify(posts):
        calls["classify"] += 1
        out = {}
        for p in posts:
            tags = set(p.hashtags)
            if tags & {"jidlo", "food"}:
                out[p.id] = "food"
            elif "fitness" in tags:
                out[p.id] = "fitness"
            elif "cestovani" in tags:
                out[p.id] = "travel"
            else:
                out[p.id] = "other"
        return out

    async def news_findings(profile, items):
        calls["news_findings"] += 1
        return [NewsFinding(item=i, label="neutral", attribution=f"píše {i.outlet}") for i in items]

    async def claims(profile, posts, collabs):
        calls["claims"] += 1
        comp = [c.id for c in collabs if c.is_competitor]
        if "exkluzivní ambasador" in profile.bio and comp:
            return [ClaimCheck(id="claim:exclusive", claim="exkluzivní ambasador @pekarna_a", claim_source=profile.source,
                               evidence=comp, status="conflicts_with_record", confidence="high",
                               note=i18n("Spolupráce s konkurencí v postech.", "Competitor collaboration in posts."))]
        return []

    async def skeptic(report: Report):
        calls["skeptic"] += 1
        return report.model_copy(update={"skeptic_notes": [i18n("pozor na jmenovce", "namesake risk")]})

    async def questions(gaps):
        calls["questions"] += 1
        return [i18n(f"Otázka k {g.id}", f"Question about {g.id}") for g in gaps]

    async def outreach(brief, candidate):
        calls["outreach"] += 1
        return i18n(f"Dobrý den, @{candidate.ref.handle}", f"Hello @{candidate.ref.handle}")

    for mod, name, fn in [
        (sensitive, "filter_profile", filter_profile), (sensitive, "filter_posts", filter_posts),
        (sensitive, "filter_comments", filter_comments), (sensitive, "filter_news", filter_news),
        (topics, "classify", classify), (vetting, "news_findings", news_findings), (vetting, "claims", claims),
        (vetting, "skeptic", skeptic), (vetting, "questions", questions), (vetting, "outreach", outreach),
    ]:
        monkeypatch.setattr(mod, name, fn)
    return calls


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event: str, data: dict) -> None:
        self.events.append((event, data))

    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def of(self, name: str) -> list[dict]:
        return [d for e, d in self.events if e == name]


def new_run(criteria: CriteriaSet) -> Run:
    return Run(id="r_test", criteria=criteria, candidates={}, rounds=[], log=[],
               mode_summary={"live": 0, "cache": 0, "mock": 0})


async def funnel(preset: str = "bakery", up_to: int = 3):
    prov = FakeProvider()
    rec = Recorder()
    run = new_run(get_preset(preset))  # type: ignore[arg-type]
    await engine.run_funnel(run, prov, rec, up_to=up_to, now=NOW)
    return run, prov, rec


def statuses(run: Run) -> dict[str, tuple[str, str | None]]:
    return {c.ref.handle: (c.status, c.elimination.criterion_id if c.elimination else None) for c in run.candidates.values()}


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------

def test_dedupe_merges_found_via_and_caps():
    s = _src("https://x")
    refs = [CandidateRef(handle="a", platform="instagram", found_via=["hashtag:x"], source=s),
            CandidateRef(handle="@A", platform="instagram", found_via=["search:y", "hashtag:x"], source=s),
            CandidateRef(handle="a", platform="tiktok", found_via=["hashtag:x"], source=s),
            CandidateRef(handle="b", platform="instagram", found_via=["manual"], source=s)]
    out = r0_discovery.dedupe(refs, 10)
    assert [(r.platform, r.handle) for r in out] == [("instagram", "a"), ("tiktok", "a"), ("instagram", "b")]
    assert out[0].found_via == ["hashtag:x", "search:y"]
    assert len(r0_discovery.dedupe(refs, 2)) == 2


async def test_bakery_funnel_eliminations(llm):
    run, prov, rec = await funnel("bakery")
    st = statuses(run)
    assert st["private_petr"] == ("eliminated", "public_account")
    assert st["big_star"] == ("eliminated", "followers_range")
    assert st["pekarna_brand"] == ("eliminated", "not_brand_account")
    assert st["english_emma"] == ("eliminated", "language_cs")
    assert st["inactive_ivan"] == ("eliminated", "active_recently")
    assert st["travel_tom"] == ("eliminated", "topic_share")
    assert st["fit_filip"] == ("eliminated", "topic_share")
    assert st["lowengage_lenka"] == ("eliminated", "min_engagement")
    assert st["emoji_eva"] == ("eliminated", "max_generic_comments")
    assert st["anna_pece"] == ("finalist", None)
    # minors: removed, nothing stored, candidate.removed emitted
    assert "minor_mia" not in st and "minor_max" not in st
    assert {d["id"] for d in rec.of("candidate.removed")} == {"instagram:minor_mia", "instagram:minor_max"}
    dump = run.model_dump_json()
    assert "minor_mia" not in dump and "minor_max" not in dump
    # found_via merged from two discovery paths
    assert run.candidates["instagram:anna_pece"].ref.found_via == ["hashtag:brnofood", "search:pekárna brno"]


async def test_elimination_reasons_are_bilingual_and_sourced(llm):
    run, _, _ = await funnel("bakery")
    tom = run.candidates["instagram:travel_tom"].elimination
    assert tom.round == 2
    assert tom.reason["cs"].startswith("Kolo 2: žádný z 8 postů není o jídle")
    assert "(kritérium aspoň 40" in tom.reason["cs"]
    assert tom.reason["en"].startswith("Round 2: none of 8 posts is about food")
    assert tom.sources and all(s.mode == "mock" for s in tom.sources)
    for c in run.candidates.values():
        if c.elimination:
            assert c.elimination.reason["cs"].startswith(f"Kolo {c.elimination.round}:")
            assert c.elimination.reason["en"].startswith(f"Round {c.elimination.round}:")
            assert c.elimination.sources, c.id
            # all results of the elimination round are kept for the card
            assert any(r.criterion_id == c.elimination.criterion_id and r.status == "fail" for r in c.results)
    emma = run.candidates["instagram:english_emma"].elimination
    assert emma.reason["cs"].startswith("Kolo 1: žádný z 8 popisků není česky (angličtina)")
    assert emma.reason["en"].startswith("Round 1: none of 8 captions is in Czech (English)")


async def test_events_rounds_and_logs(llm):
    run, _, rec = await funnel("bakery")
    names = rec.names()
    assert names[0] == "run.started" and names[-1] == "run.finished"
    assert [d["round"] for d in rec.of("round.started")] == [0, 1, 2, 3]
    fin = {d["round"]: (d["entered"], d["remaining"]) for d in rec.of("round.finished")}
    assert fin[0] == (13, 12)                    # 13 hits (anna twice) -> 12 unique
    assert fin[1] == (12, 5)                     # 2 minors removed, 5 out in round 1
    assert fin[2][0] == 5 and fin[3][1] == 1
    assert [e["round"] for e in run.rounds] == [0, 1, 2, 3]
    assert run.rounds[1] == {"round": 1, "entered": 12, "remaining": 5, "removed": 2}
    assert len(rec.of("candidate.added")) == 12
    assert {d["id"] for d in rec.of("candidate.eliminated")} == {
        c.id for c in run.candidates.values() if c.status == "eliminated"}
    # log lines have an actor; data lines have a mode
    assert run.log and all("text" in e and "ts" in e for e in run.log)
    assert any(e.get("mode") == "mock" and e.get("actor") == "fake/test" for e in run.log)
    assert all(e.get("actor") for e in run.log)
    assert run.mode_summary["mock"] > 0 and run.mode_summary.get("live", 0) == 0
    assert run.llm_modes == {} or isinstance(run.llm_modes, dict)


async def test_sensitive_filter_counts_only_and_comments_not_stored(llm):
    run, _, rec = await funnel("bakery")
    anna = run.candidates["instagram:anna_pece"]
    # one sensitive caption (health) + one sensitive comment per comment post (politics)
    assert anna.sensitive_filtered >= 2
    assert all("Nemoc" not in p.caption for p in anna.profile.latest_posts)
    events = rec.of("sensitive.filtered")
    assert events and all(set(e) >= {"candidate_id", "count"} for e in events)
    dump = run.model_dump_json()
    assert "Nemoc" not in dump and "Politika" not in dump
    for t in CS_COMMENTS + EN_COMMENTS:      # comment texts never stored on the run
        if len(t) > 3:
            assert t not in dump
    assert anna.metrics.comments_analyzed > 0 and anna.metrics.cs_comment_share is not None


async def test_unknown_never_eliminates(llm, monkeypatch):
    prov = FakeProvider()

    async def no_comments(post_urls, per_post=15):
        return []

    prov.comments = no_comments  # type: ignore[assignment]
    run = new_run(get_preset("bakery"))
    await engine.run_funnel(run, prov, Recorder(), now=NOW)
    anna = run.candidates["instagram:anna_pece"]
    assert anna.status == "finalist"
    res = {r.criterion_id: r for r in anna.results}
    assert res["cs_comment_share"].status == "unknown"
    assert res["max_generic_comments"].status == "unknown"


async def test_run_funnel_continues_from_last_round(llm):
    run, prov, rec = await funnel("bakery", up_to=1)
    assert [e["round"] for e in run.rounds] == [0, 1]
    assert all(c.status != "finalist" for c in run.candidates.values())
    await engine.run_funnel(run, prov, rec, up_to=3, now=NOW)
    assert prov.calls["discover"] == 1 and prov.calls["profiles"] == 1
    assert [e["round"] for e in run.rounds] == [0, 1, 2, 3]
    assert statuses(run)["anna_pece"] == ("finalist", None)


async def test_recompute_goal_change_no_llm_no_fetch_fast(llm, monkeypatch):
    run, prov, _ = await funnel("bakery")
    before_calls = Counter(prov.calls)
    before_llm = Counter(llm)

    async def boom(*a, **k):
        raise AssertionError("LLM must not be called in recompute")

    monkeypatch.setattr(topics, "classify", boom)
    t0 = time.perf_counter()
    diff = engine.recompute(run, get_preset("fitness"), now=NOW)
    assert time.perf_counter() - t0 < 2.0
    assert prov.calls == before_calls and Counter(llm) == before_llm
    dropped = {d["handle"]: d for d in diff["dropped"]}
    returned = {d["handle"]: d for d in diff["returned"]}
    assert "anna_pece" in dropped and dropped["anna_pece"]["elimination"]["criterion_id"] == "topic_share"
    assert dropped["anna_pece"]["elimination"]["reason"]["cs"].startswith("Kolo 2:")
    assert "fit_filip" in returned
    assert returned["fit_filip"]["elimination"]["criterion_id"] == "topic_share"   # the previous reason
    assert returned["fit_filip"]["needs_fetch"] is True                           # no comments fetched yet
    filip = run.candidates["instagram:fit_filip"]
    assert filip.status == "finalist"
    assert {r.criterion_id: r.status for r in filip.results}["cs_comment_share"] == "unknown"
    # fill_missing fetches the missing comments and re-evaluates
    rec = Recorder()
    diff2 = await engine.fill_missing(run, prov, rec)
    assert prov.calls["comments"] == before_calls["comments"] + 1
    assert filip.metrics.comments_analyzed > 0
    assert {r.criterion_id: r.status for r in filip.results}["cs_comment_share"] == "pass"
    assert filip.status == "finalist"
    assert isinstance(diff2, dict) and set(diff2) == {"dropped", "returned"}
    # and back to bakery: anna returns, filip drops
    diff3 = engine.recompute(run, get_preset("bakery"), now=NOW)
    assert {d["handle"] for d in diff3["returned"]} == {"anna_pece"}
    assert {d["handle"] for d in diff3["dropped"]} == {"fit_filip"}
    assert run.rounds[1]["remaining"] == 5 and run.rounds[1]["entered"] == 12


async def test_restore_waives_and_reevaluates(llm):
    run, prov, _ = await funnel("bakery")
    diff = engine.restore(run, "instagram:travel_tom", "topic_share", now=NOW)
    tom = run.candidates["instagram:travel_tom"]
    assert tom.restored is True
    res = {r.criterion_id: r for r in tom.results}
    assert res["topic_share"].waived is True and res["topic_share"].status == "fail"
    assert [d["handle"] for d in diff["returned"]] == ["travel_tom"]
    assert diff["returned"][0]["needs_fetch"] is True
    assert tom.status == "finalist"
    await engine.fill_missing(run, prov, Recorder())
    assert tom.metrics.comments_analyzed > 0
    # waiver survives a recompute with the same criteria
    engine.recompute(run, get_preset("bakery"), now=NOW)
    assert {r.criterion_id: r.waived for r in tom.results}["topic_share"] is True
    assert tom.status == "finalist"
    with pytest.raises(KeyError):
        engine.restore(run, "instagram:nobody", "topic_share")
    with pytest.raises(KeyError):
        engine.restore(run, "instagram:travel_tom", "no_such_criterion")


async def test_restore_can_hit_next_failure(llm):
    run, _, _ = await funnel("bakery")
    # lenka fails round 3 on engagement; waive it -> she becomes finalist (other round-3 checks pass)
    engine.restore(run, "instagram:lowengage_lenka", "min_engagement", now=NOW)
    assert run.candidates["instagram:lowengage_lenka"].status == "finalist"
    # eva fails max_generic_comments; cs_comment_share is unknown (only emoji) -> finalist after waiver
    engine.restore(run, "instagram:emoji_eva", "max_generic_comments", now=NOW)
    assert run.candidates["instagram:emoji_eva"].status == "finalist"
    # pekarna_brand waived on not_brand_account still has to pass the rest of round 1..3
    engine.restore(run, "instagram:pekarna_brand", "not_brand_account", now=NOW)
    pb = run.candidates["instagram:pekarna_brand"]
    assert pb.status in ("finalist", "eliminated")
    if pb.status == "eliminated":
        assert pb.elimination.criterion_id != "not_brand_account"


async def test_vetting_report(llm):
    run, prov, _ = await funnel("bakery")
    rec = Recorder()
    await engine.run_vetting(run, ["instagram:anna_pece", "instagram:travel_tom"], prov, rec)
    anna = run.candidates["instagram:anna_pece"]
    rep = anna.report
    assert rep is not None and anna.status == "finalist"
    assert run.candidates["instagram:travel_tom"].report is None          # eliminated ones are skipped
    steps = [d["step"] for d in rec.of("vetting.progress") if d["candidate_id"] == anna.id]
    assert steps == ["posts", "cross", "collabs", "news", "findings", "claims", "skeptic", "questions", "outreach"]
    assert rec.of("report.ready") == [{"candidate_id": anna.id}]
    assert rec.names()[-1] == "run.finished"
    # facts have sources, inferences cite existing facts, gaps have none
    ids = {f.id for f in rep.findings}
    for f in rep.findings:
        if f.kind == "fact":
            assert f.sources
        elif f.kind == "inference":
            assert f.based_on and set(f.based_on) <= ids
        else:
            assert f.sources == []
    assert "g:demographics" in ids and "g:meta_branded" in ids
    assert rep.not_checked == r4_vetting.NOT_CHECKED
    # collab timeline: competitor coauthor posts, one without label; discount code without label
    comp = [e for e in rep.collab_timeline if e.is_competitor]
    assert {e.post_id for e in comp} == {"old_1", "old_2"}
    assert any(e.kind == "discount_code" and e.disclosed is False for e in rep.collab_timeline)
    # sensitive filtered (the politics post) counted, not stored
    assert "Volby" not in run.model_dump_json()
    assert rep.sensitive_filtered == anna.sensitive_filtered
    # identity: TikTok matched, fan account rejected, namesake from news rejected
    idm = {(m.platform, m.handle): m.status for m in rep.identity}
    assert idm[("tiktok", "annapece")] == "matched"
    assert idm[("tiktok", "annapece_fans")] == "rejected"
    assert idm[("news", "news:a")] == "rejected"
    assert [n.item.id for n in rep.news] == ["news:b"]
    assert rep.claims and rep.claims[0].status == "conflicts_with_record"
    assert rep.outreach_draft == {"cs": "Dobrý den, @anna_pece", "en": "Hello @anna_pece"}
    assert rep.skeptic_notes and rep.questions
    # round 4 results recorded, nothing eliminated
    res = {r.criterion_id: r for r in anna.results}
    assert res["no_competitor_collab"].status == "fail" and "pekarna_b" in res["no_competitor_collab"].value
    assert res["discloses_ads"].status == "fail"
    assert run.rounds[-1] == {"round": 4, "entered": 1, "remaining": 1}


async def test_vetting_survives_llm_failures(llm, monkeypatch):
    run, prov, _ = await funnel("bakery")

    async def boom(*a, **k):
        raise RuntimeError("LLM down")

    for name in ("claims", "skeptic", "questions", "outreach", "news_findings"):
        monkeypatch.setattr(vetting, name, boom)
    rec = Recorder()
    await engine.run_vetting(run, ["instagram:anna_pece"], prov, rec)
    anna = run.candidates["instagram:anna_pece"]
    rep = anna.report
    # The deterministic floor stands in for every failed LLM step: rule claims (exclusive @pekarna_a
    # vs. posts with @pekarna_b), keyword news labels, template questions and outreach (never sent).
    assert rep is not None and rep.claims and rep.claims[0].status == "conflicts_with_record"
    assert rep.outreach_draft == vetting.outreach_template(run.criteria.brief, anna)
    assert rep.questions and rep.news and rep.news[0].attribution == "píše Deník"
    assert rep.text_source == {"claims": "rules", "news": "rules", "skeptic": "rules", "questions": "template",
                               "outreach": "template"}
    data = anna.vetting_data
    assert data is not None and data.llm_claims is None and data.llm_questions is None and data.llm_by_goal == {}
    assert run.llm_modes.get("vetting") == "fallback"
    assert "error" not in rec.names()


async def test_goal_change_reevaluates_round4_competitors(llm):
    run, prov, _ = await funnel("bakery")
    await engine.run_vetting(run, ["instagram:anna_pece"], prov, Recorder())
    crit = get_preset("bakery")
    crit.brief.competitors = [{"name": "Kavárna X", "handles": ["kavarna_x"]}]
    engine.recompute(run, crit, now=NOW)
    anna = run.candidates["instagram:anna_pece"]
    assert anna.status == "finalist"
    comp = [e for e in anna.report.collab_timeline if e.is_competitor]
    assert comp and all(e.brand == "kavarna_x" for e in comp)
    res = {r.criterion_id: r for r in anna.results}
    assert res["no_competitor_collab"].status == "fail" and "kavarna_x" in res["no_competitor_collab"].value


async def test_compare_no_score_sort_only_by_picked_criterion(llm):
    run, _, _ = await funnel("bakery")
    engine.restore(run, "instagram:lowengage_lenka", "min_engagement", now=NOW)
    engine.restore(run, "instagram:emoji_eva", "max_generic_comments", now=NOW)
    out = engine.compare(run)
    assert out["sort"] is None
    assert [r["handle"] for r in out["rows"]] == [c.ref.handle for c in run.candidates.values() if c.status == "finalist"]
    sorted_out = engine.compare(run, "followers_range")
    vals = [r["sort_value"] for r in sorted_out["rows"]]
    assert vals == sorted(vals, reverse=True) and sorted_out["sort"] == "followers_range"
    assert engine.compare(run, "nope")["sort"] is None
    assert set(out) == {"sort", "criteria", "rows"}
    for row in out["rows"]:
        assert set(row) == {"candidate_id", "handle", "platform", "status", "results", "sort_value"}


async def test_hard_lines_in_run_dump(llm):
    run, prov, _ = await funnel("bakery")
    await engine.run_vetting(run, ["instagram:anna_pece"], prov, Recorder())
    data = json.loads(run.model_dump_json())
    keys: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            keys.update(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    for banned in ("score", "rank", "risk", "age", "gender", "origin", "author", "username", "commenter"):
        assert banned not in keys
    # every SourceRef carries a mode
    from app.models import iter_source_refs
    modes = {s.mode for s in iter_source_refs(run)}
    assert modes == {"mock"}


async def test_error_in_round_emits_error(llm, monkeypatch):
    prov = FakeProvider()

    async def broken(handles, platform):
        raise RuntimeError("actor exploded")

    prov.profiles = broken  # type: ignore[assignment]
    rec = Recorder()
    run = new_run(get_preset("bakery"))
    await engine.run_funnel(run, prov, rec, now=NOW)
    assert "error" in rec.names() and "run.finished" not in rec.names()
    assert "actor exploded" in rec.of("error")[0]["message"]


async def test_discovery_quote_sensitive_filtered(llm):
    prov = FakeProvider()
    orig = prov.discover

    async def discover(q):
        refs = await orig(q)
        r = refs[0]
        refs[0] = r.model_copy(update={"source": r.source.model_copy(update={"quote": "Kvůli volbám dnes nepeču"})})
        return refs

    prov.discover = discover  # type: ignore[assignment]
    run = new_run(get_preset("bakery"))
    rec = Recorder()
    await engine.run_funnel(run, prov, rec, up_to=0, now=NOW)
    first = next(iter(run.candidates.values()))
    # blanked before storage; NOT counted here (round 1 counts the post itself, no double count)
    assert first.ref.source.quote is None and first.sensitive_filtered == 0
    assert "volbám" not in run.model_dump_json()
    assert not rec.of("sensitive.filtered")


async def test_funnel_with_real_llm_fallbacks():
    """No monkeypatching: the real llm/ module runs in fallback mode (no key)."""
    run, prov, rec = await funnel("bakery")
    assert "error" not in rec.names(), rec.of("error")
    assert run.llm_modes.get("topics") == "fallback" and run.llm_modes.get("sensitive") == "fallback"
    assert run.candidates["instagram:anna_pece"].status == "finalist"
    assert sum(c.sensitive_filtered for c in run.candidates.values()) > 0
    await engine.run_vetting(run, ["instagram:anna_pece"], prov, rec)
    assert "error" not in rec.names(), rec.of("error")
    rep = run.candidates["instagram:anna_pece"].report
    assert rep is not None and rep.outreach_draft and rep.questions
    assert all(f.sources for f in rep.findings if f.kind == "fact")
    assert run.llm_modes.get("vetting") == "fallback"
    t0 = time.perf_counter()
    engine.recompute(run, get_preset("fitness"))
    assert time.perf_counter() - t0 < 2.0


# ---------------------------------------------------------------------------------------------
# Designed outcomes with the real MockProvider
# ---------------------------------------------------------------------------------------------

def _expected() -> dict | None:
    from app.config import get_settings

    path = get_settings().fixtures_dir / "expected.json"
    if not (get_settings().fixtures_dir / "README.md").exists() or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_criteria(goal: str) -> CriteriaSet:
    """fixtures/briefs.json holds the canonical demo CriteriaSets (preset params + 2 competitors)."""
    from app.config import get_settings

    path = get_settings().fixtures_dir / "briefs.json"
    if path.exists():
        return CriteriaSet.model_validate(json.loads(path.read_text(encoding="utf-8"))[goal])
    return get_preset(goal)  # type: ignore[arg-type]


def _mock_provider():
    from app.sources.mock_provider import MockProvider

    try:
        return MockProvider(latency=0)
    except NotImplementedError:
        return None


@pytest.mark.parametrize("goal", ["bakery", "fitness"])
async def test_mock_fixtures_designed_outcomes(goal):
    """Engine + real MockProvider + real LLM fallbacks reproduce the fixtures' designed outcome
    (fixtures/expected.json "goals", verified by the fixture generator's reference funnel)."""
    exp = _expected()
    prov = _mock_provider() if exp else None
    assert exp is not None and prov is not None and "goals" in exp, "fixtures/expected.json or MockProvider missing"
    want = exp["goals"][goal]
    run = new_run(_fixture_criteria(goal))
    rec = Recorder()
    await engine.run_funnel(run, prov, rec)
    assert "error" not in rec.names(), rec.of("error")

    got_fin = sorted(c.id for c in run.candidates.values() if c.status == "finalist")
    assert got_fin == sorted(want["finalists"])
    got_elim = {c.id: (c.elimination.round, c.elimination.criterion_id)
                for c in run.candidates.values() if c.elimination}
    want_elim = {cid: (e["round"], e["criterion_id"]) for cid, e in want["eliminated"].items()}
    assert got_elim == want_elim
    for minor in exp["discovery"]["minors_dropped"]:
        assert minor not in run.candidates and minor not in run.model_dump_json()
    by_round = {e["round"]: e for e in run.rounds}
    for r in want["rounds"]:
        mine = by_round[r["round"]]
        assert mine["remaining"] == r["remaining"]
        assert mine["entered"] - mine.get("removed", 0) == r["entered"]
    assert sum(c.sensitive_filtered for c in run.candidates.values()) > 0
    for c in run.candidates.values():
        if c.elimination:
            assert c.elimination.sources and c.elimination.reason["cs"].startswith(f"Kolo {c.elimination.round}:")

    # round 4: designed fail / not-fail per finalist; never eliminates
    await engine.run_vetting(run, got_fin, prov, rec)
    assert "error" not in rec.names(), rec.of("error")
    for cid, crits in want["round4"].items():
        cand = run.candidates[cid]
        assert cand.status == "finalist" and cand.report is not None
        res = {r.criterion_id: r for r in cand.results}
        for crit_id, w in crits.items():
            got = "fail" if res[crit_id].status == "fail" else "not_fail"
            assert got == w["status"], (cid, crit_id, res[crit_id].value, w["value"])
        assert all(f.sources for f in cand.report.findings if f.kind == "fact")


@pytest.mark.parametrize("goal", ["bakery", "fitness"])
async def test_mock_fixtures_identity_and_news(goal):
    """Cross-platform matches, fan accounts, namesakes and sensitive news as designed in fixtures."""
    exp = _expected()
    prov = _mock_provider() if exp else None
    assert exp is not None and prov is not None and "goals" in exp, "fixtures/expected.json or MockProvider missing"
    run = new_run(_fixture_criteria(goal))
    await engine.run_funnel(run, prov, Recorder())
    fins = [c.id for c in run.candidates.values() if c.status == "finalist"]
    await engine.run_vetting(run, fins, prov, Recorder())
    dump = run.model_dump_json()
    for cid in fins:
        rep = run.candidates[cid].report
        ident = {(m.platform, m.handle): m.status for m in rep.identity}
        for x in exp["cross_platform"].get(cid, []):
            status = ident[(x["platform"], x["handle"])]
            text = x["expected"]
            if text.startswith("same creator"):
                assert status == "matched", (cid, x)
            else:  # fan account / "not the same creator"
                assert status == "rejected", (cid, x, status)
        news_ids = {n.item.id for n in rep.news}
        for n in exp["news"].values():
            if n["about"] != cid:
                continue
            if n["sensitive"]:
                assert n["id"] not in dump                      # filtered before storage, count only
            elif n["kind"] == "namesake":
                assert ident.get(("news", n["id"])) == "rejected" and n["id"] not in news_ids
            else:
                assert n["id"] in news_ids


async def test_mock_fixtures_goal_change_matches_fresh_run():
    exp = _expected()
    prov = _mock_provider() if exp else None
    assert exp is not None and prov is not None and "goals" in exp, "fixtures/expected.json or MockProvider missing"
    run = new_run(_fixture_criteria("bakery"))
    await engine.run_funnel(run, prov, Recorder())
    t0 = time.perf_counter()
    diff = engine.recompute(run, _fixture_criteria("fitness"))
    assert time.perf_counter() - t0 < 2.0
    await engine.fill_missing(run, prov, Recorder())
    got = sorted(c.id for c in run.candidates.values() if c.status == "finalist")
    assert got == sorted(exp["goals"]["fitness"]["finalists"])
    assert diff["dropped"] or diff["returned"]
