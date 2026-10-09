"""Engine fixes from the first real Brno run (9 Oct 2026): discovery round-robin, organisation
accounts, local-tips topics, e-mail "mentions", pinned posts, real-data preset thresholds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.compute import collabs, metrics
from app.llm import topics
from app.models import (
    Candidate,
    CandidateRef,
    Metrics,
    Post,
    Profile,
    Run,
    candidate_id,
    make_criterion,
    make_source_ref,
)
from app.presets import get_preset
from app.rounds import r0_discovery, r1_basics, r2_content

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def src(url: str, platform: str = "instagram", **kw):
    return make_source_ref(url=url, platform=platform, mode="cache", fetched_at=NOW, **kw)


def post(i: str, caption: str = "", days: float = 0, *, handle: str = "anna", **kw) -> Post:
    url = f"https://www.instagram.com/p/{i}/"
    return Post(id=i, platform="instagram", url=url, author_handle=handle, created_at=NOW - timedelta(days=days),
                caption=caption, likes=kw.pop("likes", 100), comments=kw.pop("comments", 5),
                source=src(url, id=f"ig:post:{i}"), **kw)


def profile(handle: str = "anna", **kw) -> Profile:
    url = f"https://www.instagram.com/{handle}/"
    return Profile(handle=handle, platform="instagram", url=url, source=src(url, id=f"ig:profile:{handle}"), **kw)


def ref(handle: str, via: str, platform: str = "instagram") -> CandidateRef:
    url = f"https://www.instagram.com/{handle}/"
    return CandidateRef(handle=handle, platform=platform, found_via=[via], source=src(url, platform, id=f"x:{handle}"))  # type: ignore[arg-type]


def cand(p: Profile) -> Candidate:
    return Candidate(id=candidate_id(p.platform, p.handle), ref=ref(p.handle, "manual"), profile=p)


async def _noop_emit(event: str, data: dict) -> None:
    return None


# ---------------------------------------------------------------------------------------------
# (4) discovery: round-robin across paths and platforms before the cap
# ---------------------------------------------------------------------------------------------

def test_round_robin_keeps_every_path_under_the_cap():
    refs = [ref(f"s{i}", f"search:jidlo brno") for i in range(30)]
    refs += [ref(f"h{i}", "hashtag:brnofood") for i in range(6)] + [ref(f"g{i}", "hashtag:foodbrno") for i in range(6)]
    refs += [ref(f"p{i}", f"place:Kavárna {i}") for i in range(5)]
    refs += [ref(f"t{i}", "search:jidlo brno", "tiktok") for i in range(4)]
    out = r0_discovery.round_robin(r0_discovery.dedupe(refs, len(refs)))
    first = out[:12]
    kinds = {(r0_discovery.path_kind(r.found_via[0]), r.platform) for r in first}
    assert kinds == {("search", "instagram"), ("hashtag", "instagram"), ("place", "instagram"), ("search", "tiktok")}
    # both hashtags take turns inside the hashtag group
    tags = [r.found_via[0] for r in out if r.found_via[0].startswith("hashtag:")][:4]
    assert tags == ["hashtag:brnofood", "hashtag:foodbrno", "hashtag:brnofood", "hashtag:foodbrno"]
    assert sorted(r.handle for r in out) == sorted(r.handle for r in refs)


class _DiscoverOnly:
    name = "fake"

    def __init__(self, refs):
        self.refs = refs

    async def discover(self, q):
        return list(self.refs)


async def test_discovery_cap_admits_hashtag_and_place_authors_and_merges_found_via():
    cs = get_preset("bakery")
    cs.discovery.limit = 6
    cs.discovery.platforms = ["instagram"]
    refs = [ref(f"s{i}", "search:jidlo brno") for i in range(10)]
    refs += [ref("h1", "hashtag:brnofood"), ref("h2", "hashtag:brnofood"), ref("p1", "place:Sesamo"),
             ref("s0", "hashtag:brnofood")]  # s0 found twice: found_via merged, counted once
    run = Run(id="r_t", criteria=cs, candidates={}, rounds=[], log=[], mode_summary={})
    added, raw = await r0_discovery.discover_with_stats(run, _DiscoverOnly(refs), _noop_emit)  # type: ignore[arg-type]
    assert raw == 14 and len(added) == 6
    handles = {c.ref.handle for c in added}
    assert {"h1", "p1"} <= handles
    assert run.candidates["instagram:s0"].ref.found_via == ["search:jidlo brno", "hashtag:brnofood"]
    assert any("Discovery paths take turns" in e["text"] or "Cesty hledání se střídají" in e["text"] for e in run.log)


# ---------------------------------------------------------------------------------------------
# (6) not_brand_account: category first, then bio / name evidence
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    {"is_business": False, "business_category": "Sports team", "display_name": "Bulldogs Brno"},
    {"is_business": False, "business_category": "Sports Club", "bio": "Oficiální profil basketbalového klubu"},
    {"is_business": False, "business_category": "Mexican Restaurant"},
    {"is_business": False, "business_category": "Coffee shop"},
    {"is_business": False, "business_category": "Clothing (Brand)"},
    {"is_business": True, "business_category": "Nonprofit organization"},
    {"is_business": True, "business_category": "Local service", "bio": "Nově otevřené bistro"},
    {"is_business": False, "business_category": None, "display_name": "FC Slovan Brno",
     "bio": "Oficiální profil FC Slovan Brno\nFotbalový klub s tradicí"},
    {"is_business": False, "business_category": None, "display_name": "Polévkové okýnko", "bio": "🕔 Po-Pá 11-17:00h"},
    {"is_business": True, "business_category": None, "display_name": "Vážkafé | Kavárna v centru Brna"},
    {"is_business": None, "business_category": None, "bio": "Řemeslné pečivo, Brno\nRezervace dortů přes web"},
    {"is_business": False, "business_category": None, "bio": "Pekárna Kvásek s.r.o."},
    {"is_business": True, "business_category": None, "bio": "Časopis nejen o brněnské gastronomii"},
])
def test_organisations_fail_whatever_is_business_says(kw):
    out = r1_basics._assess_not_brand(cand(profile("org", **kw)))
    assert out.status == "fail" and out.reason is not None
    assert "organisation" in out.reason["en"] and out.sources


@pytest.mark.parametrize("kw,status", [
    ({"is_business": True, "business_category": "Digital creator"}, "pass"),
    ({"is_business": False, "business_category": "Personal blog"}, "pass"),
    ({"is_business": False, "business_category": "Food Critic"}, "pass"),
    ({"is_business": True, "business_category": "Chef"}, "pass"),
    ({"is_business": False, "business_category": None, "bio": "Tipy, kam na jídlo v Brně"}, "pass"),
    ({"is_business": False, "business_category": None, "bio": "Objevujeme kavárny na cestách", "display_name": "Brněnské kavárny"}, "pass"),
    ({"is_business": True, "business_category": None, "bio": "Tipy a recenze na podniky v Brně"}, "unknown"),
    ({"is_business": None, "business_category": None, "bio": ""}, "unknown"),
    # "official" alone is weak: many creators use it in the handle
    ({"is_business": True, "business_category": None, "bio": "Fitness, Brno"}, "unknown"),
    ({"is_business": False, "business_category": None, "bio": "objednávky v DM"}, "pass"),
])
def test_creators_and_unclear_accounts(kw, status):
    p = profile("nela_official" if "Fitness" in (kw.get("bio") or "") else "anna", **kw)
    assert r1_basics._assess_not_brand(cand(p)).status == status


def test_styled_unicode_letters_are_read():
    p = profile("dorost", is_business=False, bio="Oficiální účet dorostu!\n𝙇𝙄𝙂𝘼: 3-MSDL")
    assert r1_basics._assess_not_brand(cand(p)).status == "fail"


@pytest.mark.parametrize("kw", [
    {"is_business": True, "business_category": "Political Party"},
    {"is_business": True, "business_category": "Student Union"},
    {"is_business": True, "business_category": "Religious organization"},
    {"is_business": True, "business_category": None, "display_name": "Hnutí Nové Brno"},
    {"is_business": False, "business_category": None, "display_name": "Anarchistický Bookfair Brno"},
])
def test_parties_unions_religious_orgs_are_sensitive(kw):
    assert r1_basics.is_sensitive_org(profile("org", **kw))


def test_sensitive_org_does_not_hit_ordinary_names():
    for kw in ({"display_name": "Jana Nováková"}, {"display_name": "Sladká strana Brna"},
               {"business_category": "Party Supply Store"}, {"business_category": "Sports team"},
               {"bio": "Peču s láskou, spolupráce e-mailem"}):
        assert not r1_basics.is_sensitive_org(profile("x", **kw))


class _ProfilesOnly:
    name = "fake"

    def __init__(self, profiles):
        self.by = {p.handle: p for p in profiles}

    async def profiles(self, handles, platform):
        return [self.by[h] for h in handles if h in self.by]


async def test_round1_removes_party_and_union_accounts_storing_nothing():
    party = profile("pirati.brno", is_business=True, business_category="Political Party", followers=8000, private=False,
                    latest_posts=[post("a1", "Program pro Brno", 1, handle="pirati.brno")])
    union = profile("elsabrno", is_business=True, business_category="Student Union", followers=9000, private=False)
    creator = profile("anna", is_business=False, followers=9000, private=False,
                      latest_posts=[post("b1", "Kváskový chleba z Brna", 1)])
    cs = get_preset("bakery")
    cands = {c.id: c for c in (Candidate(id=candidate_id("instagram", p.handle), ref=ref(p.handle, "search:jidlo brno"))
                               for p in (party, union, creator))}
    run = Run(id="r_t", criteria=cs, candidates=cands, rounds=[], log=[], mode_summary={})
    await r1_basics.prepare(run, list(cands.values()), _ProfilesOnly([party, union, creator]), _noop_emit)  # type: ignore[arg-type]
    assert set(run.candidates) == {"instagram:anna"}
    assert any("political parties" in e["text"] or "politických stran" in e["text"] for e in run.log)


# ---------------------------------------------------------------------------------------------
# (7) topics: local tips support a food goal but never carry it
# ---------------------------------------------------------------------------------------------

def _topic_candidate(counts: dict[str, int]) -> Candidate:
    posts, labels, i = [], {}, 0
    for t, n in counts.items():
        for _ in range(n):
            posts.append(post(f"t{i}", f"post {i}", i))
            labels[f"t{i}"] = t
            i += 1
    c = cand(profile("tips", latest_posts=posts))
    c.metrics = Metrics(posts_analyzed=len(posts), median_likes=None, median_comments=None, engagement_rate=None,
                        posts_per_week=None, last_post_at=None, formats={}, commercial_share=None,
                        topic_counts=metrics.topic_counts(labels), cs_comment_share=None, comments_analyzed=0,
                        generic_comment_share=None, local_signals=[], engagement_spikes=[])
    c.topic_labels = labels
    return c


def test_local_tips_alone_fail_a_food_goal():
    crit = make_criterion("topic_share", {"topics": ["food", "recipes", "restaurants_cafes", "local_tips"], "min_share": 0.4})
    out = r2_content._assess_topics(crit, _topic_candidate({"local_tips": 7, "family": 3}))
    assert out.status == "fail"
    ok = r2_content._assess_topics(crit, _topic_candidate({"food": 5, "local_tips": 5}))
    assert ok.status == "pass"
    only_tips = make_criterion("topic_share", {"topics": ["local_tips"], "min_share": 0.4})
    assert r2_content._assess_topics(only_tips, _topic_candidate({"local_tips": 7, "family": 3})).status == "pass"


def test_counted_topics():
    assert topics.counted_topics(["food", "local_tips"]) == ["food"]
    assert topics.counted_topics(["local_tips"]) == ["local_tips"]


@pytest.mark.parametrize("caption,tags", [
    ("Domácí zápas v Brně! Výhra 5:2, díky za podporu fanoušků.", ["brno", "florbal"]),
    ("Brno, sobota, extraliga. Postup do semifinále!", ["brnosport"]),
])
def test_sports_club_posts_are_not_local_tips_or_recipes(caption, tags):
    t = topics.fallback_topic(post("x", caption, hashtags=tags))
    assert t not in ("local_tips", "recipes", "food")


def test_real_local_tips_still_classified():
    assert topics.fallback_topic(post("x", "Tipy kam zajít v Brně na víkend", hashtags=["brnotipy"])) == "local_tips"


# ---------------------------------------------------------------------------------------------
# (9) e-mail addresses are not mentions
# ---------------------------------------------------------------------------------------------

def test_email_address_is_not_a_brand_mention():
    p = post("e1", "Spolupráce: brnenskamama@gmail.com #spoluprace s @kavarna_lipa", 2,
             mentions=["gmail.com", "kavarna_lipa"], paid_partnership=True)
    ev = collabs.extract_collabs([p], own_handle="brnenska_mama")
    brands = {e.brand for e in ev}
    assert "gmail.com" not in brands and "kavarna_lipa" in brands
    assert collabs._caption_mentions(post("e2", "mail: jana.novakova@seznam.cz nebo @jana")) == ["jana"]


# ---------------------------------------------------------------------------------------------
# (2b) pinned posts do not stretch the activity window
# ---------------------------------------------------------------------------------------------

def test_explicit_pinned_posts_ignored_for_activity():
    posts = [post("old", "", 400, is_pinned=True), post("a", "", 40), post("b", "", 47), post("c", "", 54)]
    assert metrics.last_post_at(posts) == NOW - timedelta(days=40)
    assert metrics.posts_per_week(posts) == pytest.approx(2 / 2)


def test_leading_out_of_order_posts_count_as_pinned_when_unknown():
    posts = [post("pin1", "", 300), post("pin2", "", 500), post("a", "", 2), post("b", "", 5), post("c", "", 9)]
    assert metrics.pinned_post_ids(posts) == {"pin1", "pin2"}
    assert metrics.last_post_at(posts) == NOW - timedelta(days=2)
    m = metrics.compute_metrics(profile(followers=1000), posts)
    assert m.last_post_at == NOW - timedelta(days=2)
    # is_pinned False is trusted; an oldest-first list gets no heuristic
    assert metrics.pinned_post_ids([post("x", "", 300, is_pinned=False), *posts[2:]]) == set()
    asc = [post("o1", "", 30), post("o2", "", 20), post("o3", "", 10), post("o4", "", 1)]
    assert metrics.pinned_post_ids(asc) == set()


def test_round1_activity_ignores_a_pinned_recent_looking_list():
    # Only pinned posts are recent; the real activity is 120 days old -> inactive.
    posts = [post("p", "", 1, is_pinned=True), post("a", "", 120), post("b", "", 130)]
    c = cand(profile("anna", latest_posts=posts, posts_count=3))
    c.metrics = metrics.compute_metrics(c.profile, posts)  # type: ignore[arg-type]
    out = r1_basics._assess_active(make_criterion("active_recently", {"days": 30}), c, NOW)
    assert out.status == "fail"


# ---------------------------------------------------------------------------------------------
# (P) presets tuned to real Brno creators
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["bakery", "fitness"])
def test_presets_follow_real_brno_numbers(name):
    cs = get_preset(name)
    by = {c.kind: c.params for c in cs.criteria}
    assert by["followers_range"] == {"min": 1000, "max": 50000}
    assert by["min_engagement"] == {"min_rate": 0.008}


# ---------------------------------------------------------------------------------------------
# Review of f8c6e3d: creator bios are not business evidence, campaign accounts, phone numbers,
# politicians filtered out of the topic check, e-mail lookbehind in identity
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bio", [
    "📍Brno, máma 2 kluků", "Testuju rozvozy jídla", "Můj e-shop s recepty", "Máma nonstop",
    "Spolupráce / rezervace termínů", "tel 777 123 456", "Otevřeno pro spolupráce",
])
def test_creator_bios_do_not_fail_a_personal_account(bio):
    p = profile("anna", is_business=False, business_category=None, bio=bio)
    assert r1_basics._assess_not_brand(cand(p)).status == "pass"


@pytest.mark.parametrize("bio", [
    "📍Kounicova 12, Brno", "Otevřeno denně 8-18", "Rezervace stolů na tel. 777 123 456", "NOVĚ OTEVŘENO",
    "Po-Pá 7-18 | So 8-12", "Pekárna s.r.o.", "tel 777 123 456\nRozvoz po Brně",
])
def test_business_bios_still_fail_a_personal_account(bio):
    p = profile("anna", is_business=False, business_category=None, bio=bio)
    assert r1_basics._assess_not_brand(cand(p)).status == "fail"


def test_org_evidence_never_repeats_a_phone_number():
    p = profile("bistro", is_business=False, business_category=None, bio="Rezervace stolů na tel. 777 123 456")
    out = r1_basics._assess_not_brand(cand(p))
    assert out.status == "fail"
    shown = f"{out.value} {out.reason} {[s.quote for s in out.sources]}"
    assert "777" not in shown and "123 456" not in shown


def test_campaign_business_account_is_a_sensitive_org():
    posts = [post(f"z{i}", c, i, handle="zelene") for i, c in enumerate([
        "9. a 10. října pojďte volit Zelené Brno, číslo 3.", "Volte č. 3, Brno má na víc!",
        "Náš volební program: dostupné bydlení.", "Komunální volby jsou za dveřmi, přijďte k urnám.",
        "Dnes sázíme stromy v parku."])]
    org = profile("zelene", is_business=True, business_category=None, display_name="Zelené Brno",
                  bio="Brno má na víc! Volte č. 3", latest_posts=posts)
    assert r1_basics.is_sensitive_org(org)
    no_bio = org.model_copy(update={"bio": "Brno má na víc!"})
    assert r1_basics.is_sensitive_org(no_bio)  # 4 of 5 posts are election posts


def test_a_person_is_never_removed_for_what_they_post():
    posts = [post(f"m{i}", c, i, handle="marie") for i, c in enumerate([
        "Kandiduju do zastupitelstva, volte č. 3.", "Komunální volby jsou za dveřmi.", "Volte lidovce!",
        "Dnes jsem upekla bábovku."])]
    person = profile("marie", is_business=False, business_category=None, bio="Volte č. 3 na Magistrát",
                     latest_posts=posts)
    assert not r1_basics.is_sensitive_org(person)
    # a creator whose business account posts about the election now and then stays
    creator = profile("pekarka", is_business=True, business_category=None, bio="Peču v Brně",
                      latest_posts=[*[post(f"b{i}", "Kváskový chleba", i, handle="pekarka") for i in range(4)],
                                    post("b9", "Nezapomeňte jít volit!", 9, handle="pekarka")])
    assert not r1_basics.is_sensitive_org(creator)


def test_political_role_category_is_removed():
    for cat in ("Politician", "Political Candidate", "Political Party"):
        assert r1_basics.is_sensitive_org(profile("x", is_business=True, business_category=cat))


def test_topic_fails_when_most_texts_were_sensitive_filtered():
    crit = make_criterion("topic_share", {"topics": ["food", "recipes", "restaurants_cafes"], "min_share": 0.4})
    c = _topic_candidate({"food": 1})
    c.sensitive_filtered = 9
    out = r2_content._assess_topics(crit, c)
    assert out.status == "fail"
    assert "polit" not in str(out.reason).lower()
    few = _topic_candidate({"food": 1})
    few.sensitive_filtered = 1
    assert r2_content._assess_topics(crit, few).status == "unknown"


def test_identity_ignores_email_addresses():
    from app.compute import identity
    src_p = profile("anna", bio="Spolupráce: kontakt@pekarna TikTok")
    target = profile("pekarna").model_copy(update={"platform": "tiktok", "url": "https://www.tiktok.com/@pekarna"})
    assert identity._links_to(src_p, target) is None
    assert identity._links_to(src_p.model_copy(update={"bio": "TikTok: @pekarna"}), target) == "@pekarna"
    assert not identity._handle_in(target, "piš na kontakt@pekarna")
    assert identity._handle_in(target, "díky @pekarna za chleba")
