"""LLM layer: deterministic fallbacks, the sensitive-request guard, whitelist validation, evidence-id
validation and the chat (offline state machine + live tool loop against a fake client).
No test calls the real API (conftest empties ANTHROPIC_API_KEY)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.llm import chat, client as llm_client, sensitive, topics, vetting
from app.models import (
    TOPICS, Brief, Candidate, CandidateRef, ClaimCheck, CollabEvidence, Comment, CriteriaSet, Elimination,
    Finding, IdentityMatch, Metrics, NewsFinding, NewsItem, Post, Profile, Report, Run, i18n, make_source_ref,
    utcnow,
)
from app.presets import get_preset

# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _empty_fixtures_dir(_isolated_settings, tmp_path, monkeypatch):
    """Presets come from app.presets unless a test writes its own briefs.json (independent of fixtures/)."""
    from app import config

    monkeypatch.setenv("FIXTURES_DIR", str(tmp_path / "fixtures"))
    config.reload_settings()
    llm_client.reset_client()
    yield
    llm_client.reset_client()


def src(url: str, platform: str = "instagram", id: str | None = None):
    return make_source_ref(url=url, platform=platform, mode="mock", id=id)  # type: ignore[arg-type]


def post(pid: str, caption: str, hashtags: list[str] | None = None, **kw) -> Post:
    return Post(
        id=pid, platform="instagram", url=f"https://instagram.com/p/{pid}", author_handle="anna",
        created_at=kw.pop("created_at", utcnow() - timedelta(days=3)), caption=caption, hashtags=hashtags or [],
        source=src(f"https://instagram.com/p/{pid}", id=pid), **kw,
    )


def profile(handle: str = "anna", bio: str = "", followers: int | None = 12000, posts: list[Post] | None = None) -> Profile:
    return Profile(
        handle=handle, platform="instagram", url=f"https://instagram.com/{handle}", display_name="Anna (MOCK)",
        bio=bio, followers=followers, latest_posts=posts or [], source=src(f"https://instagram.com/{handle}", id=f"ig:profile:{handle}"),
    )


def collab(cid: str, brand: str, kind: str, post_id: str | None, disclosed: bool | None, competitor: bool = False) -> CollabEvidence:
    return CollabEvidence(
        id=cid, brand=brand, brand_handle=brand, kind=kind, disclosed=disclosed, date=utcnow() - timedelta(days=10),  # type: ignore[arg-type]
        post_id=post_id, is_competitor=competitor, source=src(f"https://instagram.com/p/{post_id or cid}"),
    )


def candidate(handle: str, status: str = "finalist", elimination: Elimination | None = None, metrics: Metrics | None = None) -> Candidate:
    ref = CandidateRef(handle=handle, platform="instagram", found_via=["hashtag:brnofood"], source=src(f"https://instagram.com/{handle}"))
    return Candidate(id=f"instagram:{handle}", ref=ref, profile=profile(handle), status=status, elimination=elimination, metrics=metrics)  # type: ignore[arg-type]


def make_run(criteria: CriteriaSet) -> Run:
    elim = Elimination(round=2, criterion_id="topic_share", reason=i18n("Jen 2 z 24 postů o jídle.", "Only 2 of 24 posts about food."),
                       sources=[src("https://instagram.com/p/x1")])
    cands = {c.id: c for c in [
        candidate("anna"), candidate("petr_peče"), candidate("travel_tom", "eliminated", elim),
    ]}
    return Run(id="run1", criteria=criteria, candidates=cands,
               rounds=[{"round": 1, "entered": 48, "remaining": 22}, {"round": 2, "entered": 22, "remaining": 11},
                       {"round": 3, "entered": 11, "remaining": 2}],
               log=[], mode_summary={"mock": 3})


class FakeCtx:
    def __init__(self, lang: str = "cs") -> None:
        self.lang = lang
        self.history: list[dict] = []
        self.criteria: CriteriaSet | None = None
        self.run: Run | None = None
        self.calls: list[tuple] = []

    def current_run(self):
        return self.run

    def current_criteria(self):
        return self.criteria

    async def propose_criteria(self, criteria):
        self.calls.append(("propose_criteria", criteria))
        self.criteria = criteria
        return {"ok": True}

    async def update_criterion(self, criterion_id, params=None, enabled=None):
        self.calls.append(("update_criterion", criterion_id, params, enabled))
        return {"ok": True}

    async def run_rounds(self, up_to):
        self.calls.append(("run_rounds", up_to))
        self.run = make_run(self.criteria)
        return {"ok": True}

    async def explain_elimination(self, candidate_id):
        self.calls.append(("explain_elimination", candidate_id))
        return {"ok": True}

    async def start_deep_vetting(self, candidate_ids):
        self.calls.append(("start_deep_vetting", candidate_ids))
        return {"ok": True}

    async def change_goal(self, brief):
        self.calls.append(("change_goal", brief))
        self.criteria = chat.criteria_for_brief(brief)
        return {"diff": {"dropped": [{"candidate_id": "instagram:anna"}], "returned": []}}

    async def draft_outreach(self, candidate_id):
        self.calls.append(("draft_outreach", candidate_id))
        return {"ok": True}


class Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def __call__(self, event: str, data: dict) -> None:
        self.items.append((event, data))

    def text(self) -> str:
        return "".join(d["text"] for e, d in self.items if e == "chat.delta")

    def names(self) -> list[str]:
        return [e for e, _ in self.items]

    def clear(self) -> None:
        self.items.clear()


# --------------------------------------------------------------------------------------------
# client / fallback plumbing
# --------------------------------------------------------------------------------------------


async def test_no_key_means_fallback():
    assert llm_client.llm_available() is False
    assert llm_client.get_client() is None
    assert llm_client.global_llm_mode() == "fallback"
    assert llm_client.llm_mode() == "fallback"
    assert await llm_client.structured(sensitive._Flags, system="x", user="y") is None


def test_record_mode_mixed_and_cache(tmp_path):
    modes: dict[str, str] = {}
    with llm_client.bind_llm_modes(modes):
        llm_client.record_mode("topics", "llm")
        llm_client.record_mode("topics", "fallback")
        llm_client.record_mode("sensitive", "fallback")
    assert modes == {"topics": "mixed", "sensitive": "fallback"}
    llm_client.cache_put("topics", "k1", {"a": "food"})
    assert llm_client.cache_get("topics", "k1") == {"a": "food"}
    assert llm_client.cache_get("topics", "missing") is None
    assert str(llm_client._cache_path("topics", "k1")).startswith(str(tmp_path))  # temp DATA_DIR, never data/


# --------------------------------------------------------------------------------------------
# sensitive content filter (fallback keyword lists)
# --------------------------------------------------------------------------------------------

SENSITIVE_TEXTS = [
    "Po chemoterapii se konečně cítím líp",
    "Půjdu k volbám a volím ODS",
    "Nedělní mše v kostele",
    "Happy Pride month to all my LGBT friends",
    "Romové v našem městě",
    "Soud ho odsoudil za podvod",
    "My depression diary, day 3",
    "Ramadan kareem",
]
NEUTRAL_TEXTS = [
    "Nový kváskový chléb v pekárně na Zelném trhu #brnofood",
    "Ranní lekce jógy ve studiu, zdravá snídaně potom",
    "Původní recept na buchty od babičky",
    "Nákup v drogerii, recenze krému",
    "Během týdne běhám 3x, dnes 10 km",
    "Kód ANNA10 na 10 % slevu",
]


def test_keyword_flags():
    assert all(sensitive.keyword_flags(SENSITIVE_TEXTS))
    assert not any(sensitive.keyword_flags(NEUTRAL_TEXTS))


async def test_filter_texts_counts_only():
    modes: dict[str, str] = {}
    with llm_client.bind_llm_modes(modes):
        kept, n = await sensitive.filter_texts(SENSITIVE_TEXTS[:2] + NEUTRAL_TEXTS[:2] + [""])
    assert kept == [False, False, True, True, True]
    assert n == 2
    assert modes["sensitive"] == "fallback"
    # filter alias returns the same shape (mask + count, never a category)
    assert await sensitive.filter(["Chleba"]) == ([True], 0)


async def test_filter_models():
    posts = [post("p1", "Nový chleba!"), post("p2", "Po operaci kolena zase cvičím"), post("p3", "Pride", ["lgbt"])]
    kept, n = await sensitive.filter_posts(posts)
    assert [p.id for p in kept] == ["p1"] and n == 2

    comments = [Comment(post_url="u", text="Vypadá skvěle!", source=src("u")),
                Comment(post_url="u", text="volte Piráty", source=src("u"))]
    kc, nc = await sensitive.filter_comments(comments)
    assert len(kc) == 1 and nc == 1

    news = [NewsItem(id="n1", title="Policie obvinila influencera", outlet="Deník", url="https://x/1", published_at=None,
                     snippet="", source=src("https://x/1", "news")),
            NewsItem(id="n2", title="Nová pekárna v centru", outlet="Brněnský deník", url="https://x/2", published_at=None,
                     snippet="", source=src("https://x/2", "news"))]
    kn, nn = await sensitive.filter_news(news)
    assert [i.id for i in kn] == ["n2"] and nn == 1

    prof = profile(bio="Věřící máma a pekařka", posts=[post("p1", "Chleba"), post("p2", "Moje diagnóza")])
    fp, nf = await sensitive.filter_profile(prof)
    assert fp.bio == "" and [p.id for p in fp.latest_posts] == ["p1"] and nf == 2
    assert prof.bio  # original untouched


# --------------------------------------------------------------------------------------------
# owner-request guard: 12 sensitive requests (cs + en) refused, legitimate ones not
# --------------------------------------------------------------------------------------------

SENSITIVE_REQUESTS = [
    "Chci jen věřící tvůrce.",
    "Ideálně křesťany nebo katolíky.",
    "Nechci žádné muslimy.",
    "Vyřaď ty, kdo volí levici.",
    "Jen apolitické tvůrce, prosím.",
    "No gay or LGBT creators please",
    "Vyřaď lidi s nemocí nebo zdravotními problémy.",
    "Only creators of Czech nationality or ethnicity",
    "Jen tvůrce, co sdílí naše rodinné hodnoty.",
    "Give me the best creator with an overall score",
    "Chci tvůrce podle povahy, žádné introverty.",
    "Only religious creators who are not political",
    "publikum hlavně ženy 20–30 let",
    "Chci tvůrce, jehož sledující jsou hlavně muži.",
    "audience mostly women aged 18-24",
]
LEGIT_REQUESTS = [
    "Mám pekárnu v Brně a chci víc lidí v prodejně.",
    "Hledám tvůrce o jídle, 5 až 50 tisíc sledujících.",
    "Chci jen tvůrce, kteří píšou česky a jsou z Brna.",
    "We are a fitness studio in Brno and want more trial class sign-ups.",
    "Nechci nikoho, kdo dělá reklamu Pekárně B.",
    "Prodáváme zdravé pečivo pro rodiny s dětmi, rozpočet orientačně 20 tisíc.",
    "Vrať původní kritéria a seřaď finalisty podle sledujících.",
    "Hlavně ženám 25–40 let v Brně.",   # describing one's own customers is fine (interview answer)
    "Komentáře v češtině naznačují publikum z Česka (odhad z veřejných dat, ne demografie).",
]


def test_demographics_refusal_reason_says_ask_the_creator():
    r = sensitive.refusal_reason("publikum hlavně ženy 20–30 let")
    assert r is not None and "statistiky" in r["cs"] and "insights" in r["en"]


def test_preset_texts_never_trigger_the_guard():
    from app.presets import get_preset

    for name in ("bakery", "fitness"):
        for c in get_preset(name).criteria:
            for v in [*c.label.values(), *c.why.values()]:
                assert sensitive.refusal_reason(v) is None, (name, c.id, v)


@pytest.mark.parametrize("text", SENSITIVE_REQUESTS)
def test_sensitive_requests_refused(text):
    reason = sensitive.refusal_reason(text)
    assert reason is not None and reason["cs"] and reason["en"]


@pytest.mark.parametrize("text", LEGIT_REQUESTS)
def test_legit_requests_not_refused(text):
    assert sensitive.refusal_reason(text) is None


# --------------------------------------------------------------------------------------------
# topics
# --------------------------------------------------------------------------------------------


async def test_topics_fallback():
    posts = [
        post("a", "Nový kváskový chleba z pekárny", ["brnofood"]),
        post("b", "Ranní trénink v posilovně, dřepy a kliky"),
        post("c", "Víkend v Itálii, moře a pláž", ["travel"]),
        post("d", "Během týdne jsem toho moc nestihla"),
        post("e", "", ["gaming"]),
    ]
    modes: dict[str, str] = {}
    with llm_client.bind_llm_modes(modes):
        labels = await topics.classify(posts)
    # no keyword hit -> "unclassified" (not "other"): it must not count against topic_share
    assert labels == {"a": "food", "b": "fitness", "c": "travel", "d": topics.UNCLASSIFIED, "e": "gaming"}
    assert set(labels.values()) <= set(TOPICS) | {topics.UNCLASSIFIED}
    assert modes["topics"] == "fallback"


async def test_topics_llm_labels_validated(monkeypatch):
    posts = [post("a", "chleba"), post("b", "workout")]

    async def fake_structured(schema, **kw):
        return schema(labels=[{"i": 0, "topic": "recipes"}, {"i": 7, "topic": "food"}])  # index 7 invented

    monkeypatch.setattr(llm_client, "llm_available", lambda: True)
    monkeypatch.setattr(llm_client, "structured", fake_structured)
    modes: dict[str, str] = {}
    with llm_client.bind_llm_modes(modes):
        labels = await topics.classify(posts)
    assert labels == {"a": "recipes", "b": "fitness"}  # b missing from the answer -> keyword label
    assert modes["topics"] == "mixed"


# --------------------------------------------------------------------------------------------
# criteria whitelist validation
# --------------------------------------------------------------------------------------------


def _raw_from(cs: CriteriaSet) -> dict:
    d = cs.model_dump(mode="json")
    return {"brief": d["brief"], "criteria": d["criteria"], "refused": d["refused"], "discovery": d["discovery"]}


def test_validate_criteria_accepts_presets():
    for name in ("bakery", "fitness"):
        cs = get_preset(name)  # type: ignore[arg-type]
        out, refused = chat.validate_criteria(_raw_from(cs))
        assert out is not None and refused == []
        assert [(c.kind, c.params, c.label, c.why) for c in out.criteria] == [(c.kind, c.params, c.label, c.why) for c in cs.criteria]


def test_validate_criteria_whitelist_and_smuggling():
    raw = _raw_from(get_preset("bakery"))
    raw["criteria"] = [
        {"kind": "religion_match", "params": {}, "label": {"cs": "Jen věřící", "en": "Believers only"}, "why": {"cs": "", "en": ""}},
        {"kind": "overall_score", "params": {}, "label": {"cs": "Celkové skóre", "en": "Overall score"}, "why": {"cs": "", "en": ""}},
        {"kind": "topic_share", "params": {"topics": ["food"], "min_share": 0.4},
         "label": {"cs": "Křesťanský obsah", "en": "Christian content"}, "why": {"cs": "", "en": ""}},
        {"kind": "followers_range", "params": {"min": 60000, "max": 5000, "evil": 1},
         "label": {"cs": "Velikost", "en": "Size"}, "why": {"cs": "x", "en": "x"}},
        {"kind": "topic_share", "params": {"topics": ["food", "religion"], "min_share": 40},
         "label": {"cs": "Témata", "en": "Topics"}, "why": {"cs": "x", "en": "x"}},
    ]
    out, refused = chat.validate_criteria(raw)
    assert out is not None
    assert [c.kind for c in out.criteria] == ["followers_range", "topic_share"]
    assert out.criteria[0].params == {"min": 5000, "max": 60000}           # swapped, unknown key dropped
    assert out.criteria[1].params == {"topics": ["food"], "min_share": 0.4}  # unknown topic dropped, 40 -> 0.4
    assert len(refused) == 3 and all(r.reason["cs"] for r in refused)
    assert {r.text for r in out.refused} == {"Jen věřící", "Celkové skóre", "Křesťanský obsah"}


def test_validate_criteria_unusable():
    out, refused = chat.validate_criteria({"brief": {"business_type": ""}, "criteria": []})
    assert out is None and refused == []


# --------------------------------------------------------------------------------------------
# vetting: fallbacks + evidence-id validation
# --------------------------------------------------------------------------------------------


def _vetting_fixture():
    p1 = post("p1", "Nová kolekce dortů s @pekarna_b ❤️", coauthors=["pekarna_b"])
    p2 = post("p2", "Recenze, nikdo mi neplatí! Kód ANNA10 na slevu u @pekarna_b")
    p3 = post("p3", "Snídaně v centru")
    prof = profile(bio="Brno 🥐 | exkluzivní ambasador @pekarna_a | 15k sledujících", followers=14000, posts=[p1, p2, p3])
    collabs = [
        collab("collab:p1:coauthor:pekarnab", "pekarna_b", "coauthor", "p1", True, competitor=True),
        collab("collab:p2:mention:pekarnab", "pekarna_b", "mention", "p2", False, competitor=True),
        collab("collab:p2:discount_code:pekarnab", "pekarna_b", "discount_code", "p2", False, competitor=True),
    ]
    return prof, [p1, p2, p3], collabs


async def test_claims_fallback_conflicts():
    prof, posts, collabs = _vetting_fixture()
    modes: dict[str, str] = {}
    with llm_client.bind_llm_modes(modes):
        out = await vetting.claims(prof, posts, collabs)
    excl = next(c for c in out if "exkluzivní" in c.claim)
    unpaid = next(c for c in out if "nikdo mi neplatí" in c.claim)
    foll = next(c for c in out if "15k" in c.claim)
    assert excl.status == "conflicts_with_record" and excl.confidence == "high"
    assert set(excl.evidence) == {c.id for c in collabs}
    assert unpaid.status == "conflicts_with_record"
    assert "collab:p2:discount_code:pekarnab" in unpaid.evidence and "collab:p1:coauthor:pekarnab" not in unpaid.evidence
    assert foll.status == "supported" and foll.evidence == [prof.source.id]
    assert excl.claim_source.quote and unpaid.claim_source.id == "p2"
    assert modes["vetting"] == "fallback"


async def test_claims_llm_invented_ids_dropped(monkeypatch):
    prof, posts, collabs = _vetting_fixture()

    async def fake_structured(schema, **kw):
        return schema(claims=[
            # verbatim, one real id + one invented id
            {"claim": "exkluzivní ambasador @pekarna_a", "source": "bio", "evidence": ["collab:p1:coauthor:pekarnab", "collab:FAKE"],
             "status": "conflicts_with_record", "confidence": "high", "note_cs": "x", "note_en": "x"},
            # only invented evidence -> downgraded
            {"claim": "Snídaně v centru", "source": "2", "evidence": ["post:invented"], "status": "supported",
             "confidence": "high", "note_cs": "Platil mu někdo", "note_en": "x"},
            # not verbatim -> dropped entirely (would be a new fact)
            {"claim": "Anna dostala 50 000 Kč od Pekárny B", "source": "bio", "evidence": ["collab:p1:coauthor:pekarnab"],
             "status": "supported", "confidence": "high", "note_cs": "x", "note_en": "x"},
            # invalid source index -> dropped
            {"claim": "chleba", "source": "9", "evidence": [], "status": "unsupported", "confidence": "low", "note_cs": "", "note_en": ""},
        ])

    monkeypatch.setattr(llm_client, "structured", fake_structured)
    out = await vetting.claims(prof, posts, collabs)
    allowed = {c.id for c in collabs} | {p.id for p in posts} | {prof.source.id}
    assert all(e in allowed for c in out for e in c.evidence)
    assert not any("50 000" in c.claim for c in out)
    llm_excl = next(c for c in out if c.claim == "exkluzivní ambasador @pekarna_a")
    assert llm_excl.evidence == ["collab:p1:coauthor:pekarnab"] and llm_excl.confidence == "medium"
    snid = next(c for c in out if c.claim == "Snídaně v centru")
    assert snid.status == "cannot_verify" and snid.evidence == [] and snid.confidence == "low"
    # deterministic floor still adds the unpaid-claim conflict the model missed
    assert any("nikdo mi neplatí" in c.claim and c.status == "conflicts_with_record" for c in out)


def _report() -> Report:
    fact = Finding(id="f1", kind="fact", text=i18n("2 posty s @pekarna_b", "2 posts with @pekarna_b"),
                   sources=[src("https://instagram.com/p/p1")], section="collabs")
    good = Finding(id="i1", kind="inference", text=i18n("Spolupracuje s konkurencí", "Works with a competitor"),
                   sources=[], based_on=["f1"], section="collabs")
    bad = Finding(id="i2", kind="inference", text=i18n("Publikum je hlavně z Brna", "Audience is mostly from Brno"),
                  sources=[], based_on=["f_invented"], section="engagement")
    claim = ClaimCheck(id="c1", claim="exkluzivní ambasador", claim_source=src("https://instagram.com/anna"),
                       evidence=["collab:FAKE"], status="conflicts_with_record", confidence="high", note=i18n("x", "x"))
    item = NewsItem(id="n1", title="Influencerka údajně neoznačovala reklamu", outlet="Deník N", url="https://n/1",
                    published_at=None, snippet="", source=src("https://n/1", "news"))
    return Report(
        candidate_id="instagram:anna", findings=[fact, good, bad], claims=[claim], collab_timeline=[],
        news=[NewsFinding(item=item, label="confirmed", attribution="píše Deník N" + vetting.UNCERTAIN_MARK)],
        identity=[IdentityMatch(handle="anna_tt", platform="tiktok", status="uncertain", signals=[])],
        questions=[], outreach_draft=None, not_checked=[], skeptic_notes=[], sensitive_filtered=0,
    )


async def test_skeptic_rules():
    rep = await vetting.skeptic(_report())
    kinds = {f.id: f.kind for f in rep.findings}
    assert kinds == {"f1": "fact", "i1": "inference", "i2": "gap"}
    assert rep.claims[0].evidence == [] and rep.claims[0].status == "cannot_verify" and rep.claims[0].confidence == "low"
    assert rep.news[0].label == "allegation"
    notes = " ".join(n["cs"] for n in rep.skeptic_notes)
    assert "jiném člověku" in notes and "@anna_tt" in notes
    assert all(set(n) == {"cs", "en"} for n in rep.skeptic_notes)


def test_llm_skeptic_drops_invented_ids():
    rep = vetting.apply_skeptic_rules(_report())
    notes = [
        vetting._SkepticNote(ref_id="i1", action="downgrade_to_gap", note_cs="Jen jeden fakt.", note_en="Only one fact."),
        vetting._SkepticNote(ref_id="f_invented", action="downgrade_to_gap", note_cs="Smyšlené.", note_en="Invented."),
        vetting._SkepticNote(ref_id="f1", action="downgrade_to_gap", note_cs="Fakt nejde snížit.", note_en="Facts stay."),
    ]
    out = vetting.apply_llm_skeptic(rep, notes)
    kinds = {f.id: f.kind for f in out.findings}
    assert kinds["i1"] == "gap" and kinds["f1"] == "fact"
    texts = [n["cs"] for n in out.skeptic_notes]
    assert "Smyšlené." not in texts and "Jen jeden fakt." in texts


async def test_questions_fallback_and_invented_gap_ids(monkeypatch):
    gaps = [
        Finding(id="g1", kind="gap", text=i18n("Dosah postů nevidíme.", "We cannot see post reach."), sources=[], section="engagement"),
        Finding(id="g2", kind="gap", text=i18n("Věk a pohlaví publika neodhadujeme.", "We do not estimate audience age and gender."),
                sources=[], section="engagement"),
    ]
    qs = await vetting.questions(gaps)
    assert qs[0] == vetting.AUDIENCE_QUESTION and len(qs) == 2 and all(set(q) == {"cs", "en"} for q in qs)

    async def fake_structured(schema, **kw):
        return schema(questions=[{"gap_id": "g1", "q_cs": "Jaký mívají posty dosah?", "q_en": "What reach do posts get?"},
                                 {"gap_id": "g_fake", "q_cs": "Smyšlená otázka?", "q_en": "Invented?"}])

    monkeypatch.setattr(llm_client, "structured", fake_structured)
    qs = await vetting.questions(gaps)
    assert [q["cs"] for q in qs] == [vetting.AUDIENCE_QUESTION["cs"], "Jaký mívají posty dosah?"]


async def test_news_findings_fallback():
    prof = profile()
    items = [NewsItem(id="n1", title="Pokuta za neoznačenou reklamu: úřad uložil pokutu", outlet="iROZHLAS", url="https://n/1",
                      published_at=None, snippet="", source=src("https://n/1", "news")),
             NewsItem(id="n2", title="Influencerka údajně porušila pravidla", outlet="Deník", url="https://n/2",
                      published_at=None, snippet="", source=src("https://n/2", "news")),
             NewsItem(id="n3", title="Otevření nové kavárny", outlet="Brněnský deník", url="https://n/3",
                      published_at=None, snippet="", source=src("https://n/3", "news"))]
    out = await vetting.news_findings(prof, items)
    expected = {"n1": "confirmed", "n2": "allegation", "n3": "neutral"}
    # identity.news_subject may reject some items as namesakes; every kept one is labeled correctly
    assert all(n.label == expected[n.item.id] for n in out)
    assert all(n.attribution.startswith("píše ") for n in out)


async def test_outreach_draft_fallback():
    brief = get_preset("bakery").brief
    m = Metrics(posts_analyzed=20, median_likes=100, median_comments=5, engagement_rate=0.02, posts_per_week=2,
                last_post_at=utcnow(), formats={"reel": 12, "photo": 8}, commercial_share=0.1,
                topic_counts={"food": 12, "recipes": 5, "other": 3}, cs_comment_share=0.8, generic_comment_share=0.1,
                local_signals=[src("https://instagram.com/p/p1")])
    draft = await vetting.outreach(brief, candidate("anna", metrics=m))
    assert set(draft) == {"cs", "en"}
    assert "o jídle" in draft["cs"] and "krátká videa" in draft["cs"] and "v Brně" in draft["cs"]
    assert "[vaše jméno]" in draft["cs"] and "[your name]" in draft["en"]
    assert "pekarna_b" not in draft["cs"].lower() and "Pekárna B" not in draft["cs"]
    assert "reklamu" in draft["cs"]  # promises clear ad labelling


# --------------------------------------------------------------------------------------------
# chat: offline state machine (the 90-second demo without any key)
# --------------------------------------------------------------------------------------------


async def test_fallback_demo_flow():
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Dobrý den", ctx, ev)  # no key -> fallback
    assert "Co prodáváte a kde?" in ev.text() and ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "cs"})

    for msg in ("Mám pekárnu v Brně", "Rodiny a mladí lidé v Brně", "Víc lidí v prodejně, nový kváskový chléb"):
        ev.clear()
        await chat.chat_turn(msg, ctx, ev)
        assert ctx.criteria is None
    ev.clear()
    await chat.chat_turn("Do 20 tisíc. Konkurence je Pekárna B.", ctx, ev)
    cs = ctx.criteria
    assert cs is not None and cs.brief.business_type == "pekárna" and cs.brief.city == "Brno"
    assert cs.brief.competitors == [{"name": "Pekárna B", "handles": ["pekarna_b"]}]
    assert [c.kind for c in cs.criteria] == [c.kind for c in get_preset("bakery").criteria]
    assert "criteria.updated" in ev.names() and "Mám spustit hledání" in ev.text()

    # owner tries a sensitive criterion -> refused, recorded, nothing else changes
    ev.clear()
    await chat.chat_turn("A jen věřící tvůrce, prosím", ctx, ev)
    assert "čl. 9 GDPR" in ev.text()
    assert any(r.text.startswith("A jen věřící") for r in ctx.criteria.refused)
    assert [c.kind for c in ctx.criteria.criteria] == [c.kind for c in cs.criteria]

    ev.clear()
    await chat.chat_turn("ano", ctx, ev)
    assert ("run_rounds", 3) in ctx.calls
    assert "Prověřit 2 finalistů do hloubky?" in ev.text()
    assert not any(c[0] == "start_deep_vetting" for c in ctx.calls)  # round 4 only after a yes

    ev.clear()
    await chat.chat_turn("jo", ctx, ev)
    vet = [c for c in ctx.calls if c[0] == "start_deep_vetting"]
    assert vet and sorted(vet[-1][1]) == ["instagram:anna", "instagram:petr_peče"]
    assert "Nic nikomu neposílám" in ev.text()

    ev.clear()
    await chat.chat_turn("proč vypadl @travel_tom?", ctx, ev)
    assert ("explain_elimination", "instagram:travel_tom") in ctx.calls
    assert "2. kole" in ev.text() and "Jen 2 z 24" in ev.text()

    ev.clear()
    await chat.chat_turn("oslovení pro @anna", ctx, ev)
    assert ("draft_outreach", "instagram:anna") in ctx.calls
    assert "NEODESLÁNO" in ev.text()

    ev.clear()
    await chat.chat_turn("změnit cíl na fitness studio v Brně", ctx, ev)
    goal = [c for c in ctx.calls if c[0] == "change_goal"][-1][1]
    assert goal.business_type == "fitness studio" and ctx.criteria.brief.competitors[0]["handles"] == ["fitzone_brno"]
    assert "Nově vypadl 1 účet" in ev.text()

    ev.clear()
    n_calls = len(ctx.calls)
    await chat.chat_turn("kdo je nejlepší?", ctx, ev)
    assert "nejlepšího" in ev.text()
    assert all(c[0] == "propose_criteria" for c in ctx.calls[n_calls:])  # only the Refused chip is stored

    # history stays a valid alternating transcript of plain strings
    assert all(m["role"] in ("user", "assistant") and isinstance(m["content"], str) for m in ctx.history)


async def test_fallback_english_generic_brief():
    ctx, ev = FakeCtx("en"), Events()
    for msg in ("We run a flower shop in Olomouc", "Couples and offices", "More orders for Valentine's day",
                "About 8k, no competitors"):
        await chat.chat_turn(msg, ctx, ev)
    cs = ctx.criteria
    assert cs is not None and cs.brief.city == "Olomouc" and cs.brief.competitors == []
    fr = next(c for c in cs.criteria if c.kind == "followers_range")
    assert fr.params == {"min": 2000, "max": 20000}  # sized by the small budget
    loc = next(c for c in cs.criteria if c.kind == "local_signal")
    assert loc.params["city"] == "Olomouc" and loc.enabled
    assert "Shall I start the search" in ev.text()


def test_criteria_for_brief_presets_and_generic():
    b = chat.criteria_for_brief(get_preset("bakery").brief)
    assert [c.params for c in b.criteria] == [c.params for c in get_preset("bakery").criteria]
    f = chat.criteria_for_brief(Brief(business_type="posilovna", city="Praha", audience="", goal="", budget_hint=None, competitors=[]))
    assert next(c for c in f.criteria if c.kind == "local_signal").params["city"] == "Praha"
    assert next(c for c in f.criteria if c.kind == "topic_share").params["topics"] == ["fitness", "sport", "lifestyle"]


# --------------------------------------------------------------------------------------------
# chat: live tool loop against a fake Anthropic client
# --------------------------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, texts: list[str], final):
        self.texts, self.final = texts, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for t in self.texts:
                yield SimpleNamespace(type="text", text=t)
        return gen()

    async def get_final_message(self):
        return self.final


class _FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.messages = self

    def stream(self, **kw):
        self.calls.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _final(stop: str, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


async def test_live_guard_overrides_compliant_model(monkeypatch):
    """Owner asks for believers only; the model 'complies' and proposes such a criterion. The server
    refuses it anyway (deterministic sentence + Refused), and only whitelisted criteria are stored."""
    raw = _raw_from(get_preset("bakery"))
    raw["criteria"].append({"kind": "topic_share", "params": {"topics": ["food"], "min_share": 0.5},
                            "label": {"cs": "Jen věřící tvůrci", "en": "Believers only"}, "why": {"cs": "x", "en": "x"}})
    fake = _FakeClient([
        _FakeStream(["Dobře, "], _final("tool_use", TextBlock(type="text", text="Dobře, "),
                                       ToolUseBlock(type="tool_use", id="tu1", name="propose_criteria", input=raw))),
        _FakeStream(["Hotovo."], _final("end_turn", TextBlock(type="text", text="Hotovo."))),
    ])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Pekárna v Brně, ale chci jen věřící tvůrce.", ctx, ev)

    text = ev.text()
    assert text.startswith(sensitive.REFUSAL_REASONS["religion"]["cs"])
    cs = ctx.criteria
    assert cs is not None and all("věřící" not in c.label["cs"].lower() for c in cs.criteria)
    assert len(cs.criteria) == 15
    assert any("věřící" in r.text for r in cs.refused)
    assert ev.items[-1] == ("done", {"llm_mode": "llm", "lang": "cs"})
    # operator note reached the model as a mid-conversation system message, after the user turn
    first = fake.calls[0]["messages"]
    assert first[-2]["role"] == "user" and first[-1]["role"] == "system" and "Server guard" in first[-1]["content"]
    assert fake.calls[0]["model"] == "claude-opus-5-5" and "tool_choice" not in fake.calls[0]
    # history: user, system, assistant(tool_use), user(tool_result), assistant(text)
    roles = [m["role"] for m in ctx.history]
    assert roles == ["user", "system", "assistant", "user", "assistant"]
    tr = ctx.history[3]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "tu1"
    assert any(e == "chat.tool" and d["name"] == "propose_criteria" for e, d in ev.items)


async def test_live_vetting_requires_confirmation(monkeypatch):
    ctx, ev = FakeCtx("cs"), Events()
    ctx.criteria = get_preset("bakery")
    ctx.run = make_run(ctx.criteria)
    fake = _FakeClient([
        _FakeStream([], _final("tool_use", ToolUseBlock(type="tool_use", id="tu1", name="start_deep_vetting",
                                                        input={"candidate_ids": ["instagram:anna"]}))),
        _FakeStream(["Mám je prověřit?"], _final("end_turn", TextBlock(type="text", text="Mám je prověřit?"))),
    ])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    await chat.chat_turn("Co dál?", ctx, ev)
    assert not any(c[0] == "start_deep_vetting" for c in ctx.calls)
    tool_ev = next(d for e, d in ev.items if e == "chat.tool")
    assert "Not confirmed" in tool_ev["result"]["error"]
    assert ctx.history[3]["content"][0].get("is_error") is True


async def test_live_failure_before_output_uses_fallback(monkeypatch):
    fake = _FakeClient([RuntimeError("boom")])
    monkeypatch.setattr(llm_client, "get_client", lambda: fake)
    ctx, ev = FakeCtx("cs"), Events()
    await chat.chat_turn("Ahoj", ctx, ev)
    assert "Co prodáváte a kde?" in ev.text()
    assert ev.items[-1] == ("done", {"llm_mode": "fallback", "lang": "cs"})
    assert [m["role"] for m in ctx.history] == ["user", "assistant"]


def test_tools_shape():
    names = [t["name"] for t in chat.TOOLS]
    assert names == ["propose_criteria", "update_criterion", "run_rounds", "explain_elimination",
                     "start_deep_vetting", "change_goal", "draft_outreach", "research_subject"]
    rs = chat.TOOLS[-1]["input_schema"]
    assert rs["required"] == ["subject", "brief"] and set(rs["properties"]) == {"subject", "anchor", "brief", "preset"}
    assert rs["properties"]["anchor"]["additionalProperties"] is False
    for t in chat.TOOLS:
        assert t["input_schema"]["type"] == "object" and t["description"]
    assert "send" not in " ".join(names)


def test_load_preset_prefers_fixtures_briefs_json(tmp_path):
    import json

    from app.config import get_settings

    cs = get_preset("bakery")
    cs.brief.competitors = [{"name": "Pekárna B", "handles": ["pekarna_b"]}, {"name": "Chlebárna Vlnka", "handles": ["chlebarna_vlnka"]}]
    cs.refused = [chat.Refused(text="jen věřící tvůrci", reason=i18n("x", "x"))]
    d = get_settings().fixtures_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "briefs.json").write_text(json.dumps({"bakery": cs.model_dump(mode="json")}), encoding="utf-8")
    assert len(chat.load_preset("bakery").brief.competitors) == 2
    assert chat.load_preset("fitness").brief.business_type == "fitness studio"   # missing -> app.presets
    # demo example refusals are not copied into an owner's criteria
    assert chat.criteria_for_brief(chat.load_preset("bakery").brief).refused == []


async def test_chat_events_async_generator():
    ctx = FakeCtx("cs")
    events = [e async for e in chat.chat_events("Mám pekárnu v Brně", ctx)]
    assert events[-1] == ("done", {"llm_mode": "fallback", "lang": "cs"})
    assert "Komu chcete prodávat?" in "".join(d["text"] for e, d in events if e == "chat.delta")
