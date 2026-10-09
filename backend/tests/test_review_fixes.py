"""Regression tests for the review findings (hard lines, correctness, demo). Temp DATA_DIR (conftest),
mock sources, no keys."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import config, main
from app.compute import identity, language, metrics
from app.compute.collabs import collaboration_evidence, extract_collabs
from app.compute.minors import bio_states_minor
from app.llm import chat, sensitive, vetting
from app.models import (
    Brief, Candidate, CandidateRef, Comment, CriteriaSet, Metrics, NewsItem, Post, Profile, Report, Run,
    make_criterion, make_source_ref, utcnow,
)
from app.presets import get_preset
from app.rounds import engine, r1_basics, r3_audience
from app.rounds.r4_vetting import NOT_CHECKED, _assess_competitor
from app.sources.cache import import_cache_dir
from app.store import get_store

from tests.test_api import client, real_run  # noqa: F401  (pytest fixture + helper)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def src(url: str, sid: str | None = None, platform: str = "instagram"):
    return make_source_ref(url=url, platform=platform, mode="mock", id=sid)  # type: ignore[arg-type]


def post(pid: str, caption: str, days: float, **kw) -> Post:
    url = f"https://instagram.mock.invalid/p/{pid}/"
    return Post(id=pid, platform="instagram", url=url, author_handle=kw.pop("author", "anna"),
                created_at=NOW - timedelta(days=days), caption=caption, likes=kw.pop("likes", 300),
                comments=kw.pop("comments", 10), source=src(url, pid), **kw)


def profile(handle: str = "anna", bio: str = "", posts: list[Post] | None = None, **kw) -> Profile:
    url = f"https://instagram.mock.invalid/{handle}/"
    return Profile(handle=handle, platform="instagram", url=url, display_name=kw.pop("display_name", "Anna Nováková (MOCK)"),
                   bio=bio, followers=kw.pop("followers", 12000), latest_posts=posts or [],
                   source=src(url, f"ig:profile:{handle}"), **kw)


def cand(handle: str = "anna") -> Candidate:
    return Candidate(id=f"instagram:{handle}", ref=CandidateRef(handle=handle, platform="instagram", found_via=["manual"],
                                                                source=src(f"https://instagram.mock.invalid/{handle}/")))


class ListProvider:
    name = "list"

    def __init__(self, profiles: list[Profile], comments: list[Comment] | None = None) -> None:
        self._p = profiles
        self._c = comments or []
        self.comment_calls = 0

    async def profiles(self, handles, platform):
        return [p.model_copy(deep=True) for p in self._p]

    async def comments(self, post_urls, per_post=15):
        self.comment_calls += 1
        return list(self._c)


async def noop(*_a, **_k):
    return None


# ============================================================================================
# hard lines: owner-request guard, content filter, brief guard, API writes
# ============================================================================================

NEW_SENSITIVE_REQUESTS = [
    "žádné Romy", "jen bílí tvůrci", "ne Vietnamci", "nechci Ukrajince", "no foreigners", "only native Czechs",
    "hetero only", "straight creators only", "jen tvůrce s normální orientací", "žádní teplouši",
    "avoid anyone who posts about pride", "nechci nikoho, kdo chodí do kostela", "nechci aktivisty", "no feminists",
    "only pro-life creators", "nechci antivaxery", "žádní dezoláti", "jen štíhlé tvůrkyně", "nechci tvůrce s nadváhou",
    "aby ho sledovaly hlavně ženy", "sledující hlavně mladé maminky", "followers should be mostly moms", "jen vegani",
    "dej jim známku 1-10", "který je nejspolehlivější?", "má záznam v rejstříku trestů?", "chci někoho kdo nevolí Babiše",
    "jen zdravé lidi", "jen štíhlé holky",
    # private life / character questions about a creator
    "kolik mu je let?", "how old is she?", "je ženatý?", "má rodinu? má děti?", "odkud pochází?",
    "where is he from originally?", "je arogantní?", "is she a nice person?", "jaký je to člověk?",
    "has he been arrested?", "nemá problémy se zákonem?",
]
NEW_LEGIT_REQUESTS = [
    "Mám vietnamské bistro v Brně", "Ukrajinský boršč a pelmeně", "We take pride in our bread", "low-fat yogurt bar",
    "Tahle bábovka je zlatá", "Pekárna má rodinnou atmosféru", "jak starý je ten kvásek?", "Kávu z arabiky",
    "Mladé maminky s dětmi a studenti", "cílovka jsou ženy 25-35",  # describing one's own customers
    "Co přesně kontrolujete a co ne?", "Pekárna B a Chlebárna Vlnka.", "Tak 10 tisíc korun.",
]


@pytest.mark.parametrize("text", NEW_SENSITIVE_REQUESTS)
def test_guard_refuses_more_phrasings(text):
    assert sensitive.refusal_reason(text) is not None


@pytest.mark.parametrize("text", NEW_LEGIT_REQUESTS)
def test_guard_keeps_ordinary_requests(text):
    assert sensitive.refusal_reason(text) is None


CONTENT_SENSITIVE = [
    "Byl jsem na psychoterapii a pomohlo mi to", "otehotněla jsem!", "jsme v jináči 🤰", "IVF nám konečně vyšlo",
    "Po porodu se vracím k pečení", "Držím dietu kvůli cukrovce", "Tvůrkyně byla na rehabilitaci po úrazu",
    "Přestal jsem pít alkohol, 100 dní střízlivý", "Jsem Ukrajinka a v Brně žiju 3 roky",
    "Jako Vietnamka jsem vyrostla v bistru rodičů", "Podpořte Ukrajinu, sbírka na drony", "Pochod hrdosti v Praze byl úžasný",
    "S přítelkyní jsme se konečně vzaly 💍", "Tvůrce vyšetřuje policie kvůli daňovým únikům",
    "Influencer přistižen opilý za volantem", "Půst o Velikonocích",
    # fines / administrative offences are Art. 10 too (C-439/19)
    "ČOI uložila brněnské tvůrkyni pokutu 50 000 Kč za neoznačenou reklamu",
    "Česká obchodní inspekce pokutovala influencera za skrytou reklamu",
    "Creator fined by consumer authority for hidden ads", "Tvůrce dostal pokutu za rychlou jízdu",
]
CONTENT_NEUTRAL = [
    "Vánoční cukroví od babičky", "pocukrovaný koláč", "Pusť si zvuk a koukej", "nealkoholické pivo k obědu",
    "Koktejl bez alkoholu", "opilé třešně v čokoládě", "Konečně prázdniny!", "slovenské halušky jako od babičky",
    "Best Vietnamese pho in Brno", "Pocházím z Brna", "za volantem nového auta na výletě", "urazila jsem se, že nebyl dort",
    "Postím fotky každý den", "Přestup do nového týmu",
]


@pytest.mark.parametrize("text", CONTENT_SENSITIVE)
def test_content_filter_catches_more(text):
    assert sensitive.keyword_flags([text]) == [True]


@pytest.mark.parametrize("text", CONTENT_NEUTRAL)
def test_content_filter_spares_food_and_fitness(text):
    assert sensitive.keyword_flags([text]) == [False]


async def test_location_name_is_filtered():
    p = post("p1", "Dnešní snídaně", 1, location_name="Kostel sv. Jakuba")
    kept, n = await sensitive.filter_posts([p])
    assert kept == [] and n == 1


def test_sanitize_brief_blanks_and_records():
    b = Brief(business_type="pekárna", city="Brno", audience="jen bílí lidé",
              goal="najít tvůrce bez politických názorů a s křesťanskými hodnotami", budget_hint=None, competitors=[])
    clean, refused = sensitive.sanitize_brief(b)
    assert clean.goal == "" and clean.audience == "" and clean.business_type == "pekárna"
    assert len(refused) == 2


def test_outreach_template_never_quotes_a_sensitive_goal():
    b = Brief(business_type="pekárna", city="Brno", audience="", goal="Jen věřící tvůrci.", budget_hint=None, competitors=[])
    c = cand()
    c.profile = profile()
    d = vetting.outreach_template(b, c)
    assert "věřící" not in d["cs"] and "chystáme kampaň." in d["cs"]
    assert d["cs"].startswith("Dobrý den,\n")
    b2 = b.model_copy(update={"goal": "Víc lidí v prodejně."})
    d2 = vetting.outreach_template(b2, c)
    assert "kampaň: víc lidí v prodejně." in d2["cs"] and ".." not in d2["cs"]
    assert "(MOCK)" not in d2["en"]


def test_normalize_criteria_set_guards_api_writes():
    cs = get_preset("bakery")
    cs.criteria[0].label = {"cs": "Jen věřící, bez Romů", "en": "Believers only, no Roma"}
    fr = next(c for c in cs.criteria if c.kind == "followers_range")
    fr.params = {"min": "5000", "max": "100000", "bogus": 1}
    out = chat.normalize_criteria_set(cs)
    assert cs.criteria[0].id not in {c.id for c in out.criteria}
    assert any("věřící" in r.text for r in out.refused)
    fr2 = next(c for c in out.criteria if c.kind == "followers_range")
    assert fr2.params == {"min": 5000, "max": 100000}
    fr.params = {"max": "abc"}
    with pytest.raises(chat.CriteriaRejected):
        chat.normalize_criteria_set(cs)


# ============================================================================================
# hard lines: minors, cache imports, namesakes, fines, MOCK fixtures
# ============================================================================================


def test_bio_age_detection():
    for bio in ("14 let 🎂 | ráda peču", "16yo | Brno", "Je mi 15 a peču", "ročník 2011", "I'm 14 and I love baking"):
        assert bio_states_minor(bio, NOW), bio
    for bio in ("Pečeme už 15 let", "10 let v oboru", "Food tvůrce z Brna | 25 let", "I'm 5 minutes from the center",
                "ročník 1995", "12 let zkušeností s kváskem"):
        assert not bio_states_minor(bio, NOW), bio


async def test_round1_drops_minor_by_bio_without_flag():
    minor = profile("nikolka", bio="14 let 🎂 | ráda peču", posts=[post("p1", "Bábovka", 2)], is_under_18=None)
    run = Run(id="r1", criteria=get_preset("bakery"), candidates={"instagram:nikolka": cand("nikolka")}, rounds=[], log=[],
              mode_summary={})
    await r1_basics.prepare(run, list(run.candidates.values()), ListProvider([minor]), noop)
    assert run.candidates == {}
    assert "ráda peču" not in run.model_dump_json()


def test_import_strips_commenter_identity_and_minors(tmp_path):
    srcdir, dest = tmp_path / "imp", tmp_path / "cache"
    srcdir.mkdir()
    item = {"post_url": "https://x/p/1", "text": "Super!", "ownerUsername": "real.person.123",
            "ownerProfilePicUrl": "https://x/pic.jpg",
            "source": src("https://x/p/1").model_dump(mode="json")}
    (srcdir / ("a" * 64 + ".json")).write_text(json.dumps([item]))
    kid = profile("kid", bio="14 let 🎂").model_dump(mode="json")
    (srcdir / ("b" * 64 + ".json")).write_text(json.dumps({"meta": {"method": "find_cross_platform"}, "items": [kid]}))
    stats = import_cache_dir(srcdir, dest)
    assert stats["entries_written"] == 1
    written = (dest / ("a" * 64 + ".json")).read_text()
    assert "real.person.123" not in written and "ownerProfilePicUrl" not in written
    assert not (dest / ("b" * 64 + ".json")).exists()


async def test_cache_mode_replays_import_while_apify_is_a_stub(tmp_path, monkeypatch):
    from app.sources.factory import get_provider

    prof = profile("kuba.jidlo.brno")
    srcdir = tmp_path / "imp"
    srcdir.mkdir()
    (srcdir / "p.json").write_text(json.dumps({"meta": {"method": "profiles", "args": {"handles": ["kuba.jidlo.brno"],
                                                                                        "platform": "instagram"}},
                                               "items": [prof.model_dump(mode="json")]}))
    import_cache_dir(srcdir)  # default namespace "apify", default cache dir
    monkeypatch.setenv("SOURCE_MODE", "cache")
    config.reload_settings()
    prov = get_provider()
    got = await prov.profiles(["kuba.jidlo.brno"], "instagram")
    assert len(got) == 1 and got[0].source.mode == "cache"


def test_rejected_namesake_keeps_no_headline():
    p = profile("toman", display_name="Ondřej Toman (MOCK)", bio="Ochutnávám jídlo v Brně")
    item = NewsItem(id="news:1", title="Zlínský podnikatel Ondřej Toman podle subdodavatelů dluží za stavbu",
                    outlet="Zlínský kurýr", url="https://zk.example/1", published_at=NOW, snippet="",
                    source=src("https://zk.example/1", "news:1", "news"))
    m = identity.match_news(p, [item], city="Brno")
    assert m and m[0].status == "rejected"
    assert m[0].signals[0].source.quote is None and "dluží" not in m[0].signals[0].signal


def test_fines_are_not_a_confirmed_label_and_are_listed_as_not_checked():
    item = NewsItem(id="n", title="Pekárna A oficiálně oznámila nové ambasadory", outlet="X", url="https://x/1",
                    published_at=None, snippet="", source=src("https://x/1", "n", "news"))
    assert vetting._keyword_label(item) == "confirmed"
    assert "pokut" not in vetting._RX_CONFIRMED.pattern
    assert any("Pokuty" in x["cs"] for x in NOT_CHECKED)


def test_mock_fixtures_never_link_to_real_platforms():
    for f in FIXTURES.glob("*.json"):
        text = f.read_text("utf-8")
        assert "www.instagram.com" not in text and "www.tiktok.com" not in text and "www.facebook.com" not in text, f.name
    for pr in json.loads((FIXTURES / "profiles.json").read_text("utf-8")):
        assert pr["display_name"].endswith("(MOCK)") and ".invalid/" in pr["url"]


# ============================================================================================
# correctness
# ============================================================================================


async def test_sensitive_newest_post_does_not_make_creator_inactive():
    posts = [post("new", "Po operaci kolena zpátky v kuchyni, dnes bábovka", 2)] + \
        [post(f"o{i}", "Kváskový chléb a croissanty", 45 + i) for i in range(5)]
    run = Run(id="r1", criteria=get_preset("bakery"), candidates={"instagram:anna": cand()}, rounds=[], log=[], mode_summary={})
    await r1_basics.prepare(run, list(run.candidates.values()), ListProvider([profile(posts=posts)]), noop)
    c = run.candidates["instagram:anna"]
    assert c.sensitive_filtered == 1 and all(p.id != "new" for p in c.profile.latest_posts)
    crit = next(x for x in run.criteria.criteria if x.kind == "active_recently")
    out = r1_basics.assess(crit, c, run.criteria.brief, NOW)
    assert out.status == "pass", out.value
    assert "operaci" not in run.model_dump_json()


def test_plain_competitor_mention_is_not_a_collaboration():
    comps = [{"name": "Pekárna B", "handles": ["pekarna_b"]}]
    p = post("p1", "Dneska srovnání croissantů: u @pekarna_b byl suchý", 3, paid_partnership=False)
    ev = extract_collabs([p], own_handle="anna", competitors=comps)
    assert ev and all(e.disclosed is None for e in ev)
    assert collaboration_evidence(ev) == []
    c = cand()
    c.profile = profile(posts=[p])
    c.report = Report(candidate_id=c.id, findings=[], claims=[], collab_timeline=ev, news=[], identity=[], questions=[],
                      outreach_draft=None, not_checked=[], skeptic_notes=[], sensitive_filtered=0)
    brief = get_preset("bakery").brief
    out = _assess_competitor(c, brief)
    assert out.status == "unknown" and "zmínka" in out.value["cs"]
    # no competitors named -> unknown, not a pass
    assert _assess_competitor(c, brief.model_copy(update={"competitors": []})).status == "unknown"


def test_local_signal_city_follows_brief_or_switches_off():
    brief = {"business_type": "kavárna", "city": "Praha", "audience": "", "goal": "", "competitors": []}
    cs, _ = chat.validate_criteria({"brief": brief, "criteria": [{"kind": "local_signal", "params": {"min_count": 1}}]})
    assert cs.criteria[0].params["city"] == "Praha" and cs.criteria[0].enabled
    cs2, _ = chat.validate_criteria({"brief": {**brief, "city": None}, "criteria": [{"kind": "local_signal", "params": {}}]})
    assert cs2.criteria[0].enabled is False and cs2.criteria[0].params["city"] is None


def test_czech_without_diacritics_is_czech():
    for t in ("Diky za tip, urcite zajdu", "Vypada to skvele", "Jsem z Brna a nevedela jsem o tom"):
        assert language.detect_language(t) == "cs", t
    assert language.detect_language("Vyzera to skvele") == "sk"


def test_praha_pattern_spares_holidays():
    pat = metrics.city_pattern("Praha")
    assert not pat.search("prazdniny") and not pat.search("prazdny talir")
    assert pat.search("v praze") and pat.search("z prahy") and pat.search("prazska kavarna")
    assert metrics.city_pattern("Mladá Boleslav").search("v mlade boleslavi")


async def test_comments_fetched_once_even_when_empty():
    p = profile(posts=[post("p1", "Chleba", 2), post("p2", "Koláč", 4)])
    c = cand()
    c.profile = p
    c.metrics = metrics.compute_metrics(p, list(p.latest_posts))
    run = Run(id="r", criteria=get_preset("bakery"), candidates={c.id: c}, rounds=[], log=[], mode_summary={})
    prov = ListProvider([], comments=[])
    assert r3_audience.needs_comments(c)
    await r3_audience.prepare(run, [c], prov, noop)
    assert prov.comment_calls == 1 and not r3_audience.needs_comments(c)
    crit = next(x for x in run.criteria.criteria if x.kind == "cs_comment_share")
    assert "nestažené" not in r3_audience.assess(crit, c, run.criteria.brief, NOW).value["cs"]


async def test_comment_refetch_replaces_sensitive_count():
    p = profile(posts=[post("p1", "Chleba", 2)])
    c = cand()
    c.profile = p
    c.metrics = metrics.compute_metrics(p, list(p.latest_posts))
    bad = [Comment(post_url=p.latest_posts[0].url, text="Moje diagnóza je ...", source=src(p.latest_posts[0].url))]
    run = Run(id="r", criteria=get_preset("bakery"), candidates={c.id: c}, rounds=[], log=[], mode_summary={})
    await r3_audience.prepare(run, [c], ListProvider([], comments=bad), noop)
    assert c.sensitive_filtered == 1
    await r3_audience.prepare(run, [c], ListProvider([], comments=bad), noop)  # forced refetch
    assert c.sensitive_filtered == 1


def test_trainer_named_in_article_is_not_a_namesake():
    p = profile("pavla", display_name="Pavla Krejčí (MOCK)", bio="Trenérka v Brně")
    item = NewsItem(id="n", title="Trenérka Pavla Krejčí otevírá v Brně nové studio", outlet="Brněnský deník",
                    url="https://bd.example/1", published_at=None, snippet="", source=src("https://bd.example/1", "n", "news"))
    assert identity.news_subject(p, item, "Brno") != "rejected"
    assert identity.match_news(p, [item], city="Brno") == []


def test_explicit_platform_prefix_resolves_exactly():
    run = Run(id="r", criteria=get_preset("bakery"), candidates={"instagram:kuba": cand("kuba")}, rounds=[], log=[],
              mode_summary={})
    assert main._resolve_candidate(run, "tiktok:kuba") is None
    assert main._resolve_candidate(run, "@kuba") == "instagram:kuba"
    assert chat.find_candidate(run, "youtube:kuba") is None


async def test_renamed_account_is_kept():
    renamed = profile("kuba.vari.brno", former_handles=["kuba.jidlo.brno"], posts=[post("p1", "Chleba", 2)])
    run = Run(id="r", criteria=get_preset("bakery"), candidates={"instagram:kuba.jidlo.brno": cand("kuba.jidlo.brno")},
              rounds=[], log=[], mode_summary={})
    await r1_basics.prepare(run, list(run.candidates.values()), ListProvider([renamed]), noop)
    assert run.candidates["instagram:kuba.jidlo.brno"].profile is not None


def test_run_log_is_trimmed(monkeypatch):
    monkeypatch.setattr(main, "RUN_LOG_MAX", 5)
    run = get_store().create(get_preset("bakery"))
    for i in range(12):
        entry = {"ts": f"t{i}", "text": f"line {i}"}
        run.log.append(entry)          # the engine appends first ...
        main._append_log(run.id, entry)  # ... then the emitter sees the same line
    assert len(run.log) == 5 and run.log[-1]["text"] == "line 11"


# ============================================================================================
# demo path (real engine + MockProvider through the API)
# ============================================================================================


async def test_demo_path_goal_change_refreshes_reports_and_drops_waivers(client):  # noqa: F811
    run_id = await real_run(client)
    run = get_store().get(run_id)
    victim = next(c for c in run.candidates.values()
                  if c.status == "eliminated" and c.elimination and c.elimination.criterion_id == "topic_share")
    r = await client.post(f"/api/runs/{run_id}/restore", json={"candidate_id": victim.id, "criterion_id": "topic_share"})
    assert r.status_code == 200
    await main.wait_idle(run_id, timeout=60)
    r = await client.post(f"/api/runs/{run_id}/vet", json={"candidate_ids": []})
    assert r.status_code == 200
    await main.wait_idle(run_id, timeout=120)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    text = json.dumps(data, ensure_ascii=False).lower()
    assert "publikum je" not in text and "audience is" not in text  # no audience origin claims
    kuba = data["candidates"]["instagram:kuba.jidlo.brno"]["report"]
    assert any("2 posty" in c["note"]["cs"] for c in kuba["claims"])           # posts, not evidence rows
    assert any("@pekarna_b" in q["cs"] for q in kuba["questions"])            # the conflict becomes a question
    verca = data["candidates"]["instagram:verca_pece"]["report"]
    assert any("VERCA15" in q["cs"] for q in verca["questions"])
    assert not any("Zprávy o tvůrci" in q["cs"] for q in kuba["questions"])

    # goal change via the form with a sensitive goal: guarded, refused, never in a draft
    brief = dict(data["criteria"]["brief"])
    brief.update(goal="najít tvůrce bez politických názorů a s křesťanskými hodnotami", audience="jen bílí lidé")
    r = await client.post(f"/api/runs/{run_id}/goal", json={"brief": brief})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["criteria"]["brief"]["goal"] == "" and d["criteria"]["brief"]["audience"] == ""
    assert {x["text"] for x in d["criteria"]["refused"]} >= {brief["goal"], brief["audience"]}
    assert d.get("waivers_dropped") and d["waivers_dropped"][0]["candidate_id"] == victim.id
    await main.wait_idle(run_id, timeout=60)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    drafts = json.dumps([c["report"]["outreach_draft"] for c in data["candidates"].values() if c["report"]], ensure_ascii=False)
    assert "politick" not in drafts and "křesťansk" not in drafts

    # fitness goal: shared vetted finalists get a new outreach draft; the refused chips stay
    r = await client.post(f"/api/runs/{run_id}/goal", json={"preset": "fitness"})
    assert r.status_code == 200
    assert len(r.json()["criteria"]["refused"]) >= 2
    await main.wait_idle(run_id, timeout=60)
    run = get_store().get(run_id)
    vetted = [c for c in run.candidates.values() if c.report is not None]
    assert vetted
    for c in vetted:
        assert "pekárna" not in (c.report.outreach_draft or {}).get("cs", ""), c.id
        assert c.report.vetted_for == "pekárna"
    assert run.candidates[victim.id].restored is False or not any(
        r.waived and r.criterion_id == "topic_share" for r in run.candidates[victim.id].results)


async def test_api_rejects_uncoercible_params_and_coerces_strings(client):  # noqa: F811
    cs = get_preset("bakery")
    fr = next(c for c in cs.criteria if c.kind == "followers_range")
    fr.params = {"min": 5000, "max": "abc"}
    r = await client.post("/api/runs", json={"criteria": cs.model_dump(mode="json"), "up_to": 0})
    assert r.status_code == 422 and "followers_range.max" in r.text
    fr.params = {"min": 5000, "max": "100000"}
    r = await client.post("/api/runs", json={"criteria": cs.model_dump(mode="json"), "up_to": 0})
    assert r.status_code == 200
    run = get_store().get(r.json()["run_id"])
    assert next(c for c in run.criteria.criteria if c.kind == "followers_range").params["max"] == 100000


# ============================================================================================
# fallback chat
# ============================================================================================


class Ctx:
    def __init__(self) -> None:
        self.lang = "cs"
        self.history: list[dict] = []
        self.criteria: CriteriaSet | None = None

    def current_run(self):
        return None

    def current_criteria(self):
        return self.criteria

    async def propose_criteria(self, criteria):
        self.criteria = criteria
        return {"ok": True}


class Ev:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def __call__(self, e, d):
        self.items.append((e, d))

    def text(self) -> str:
        return "".join(d.get("text", "") for e, d in self.items if e == "chat.delta")


async def turn(ctx: Ctx, msg: str) -> str:
    ev = Ev()
    await chat.fallback_turn(msg, ctx, ev)
    return ev.text()


async def test_scope_question_is_answered_in_fallback():
    ctx = Ctx()
    out = await turn(ctx, "Co přesně kontrolujete a co ne?")
    assert "Co nekontrolujeme" in out and "Pokuty" in out and "Co prodáváte a kde?" in out
    out = await turn(ctx, "Mám pekárnu v Brně")
    assert "Komu chcete prodávat?" in out  # the scope question was not taken as the q1 answer


async def test_budget_only_answer_asks_for_competitors_then_refusal_reasks_run():
    ctx = Ctx()
    for msg in ("Mám pekárnu v Brně", "Rodiny s dětmi", "Víc lidí v prodejně"):
        await turn(ctx, msg)
    out = await turn(ctx, "Tak 10 tisíc korun.")
    assert chat.Q_TEXTS["q5"]["cs"] in out and ctx.criteria is None
    out = await turn(ctx, "Pekárna B a Chlebárna Vlnka.")
    assert ctx.criteria is not None
    assert [c["name"] for c in ctx.criteria.brief.competitors] == ["Pekárna B", "Chlebárna Vlnka"]
    out = await turn(ctx, "Chci jen věřící tvůrce.")
    assert "čl. 9" in out and "Mám spustit hledání" in out and "porovnat finalisty" not in out
