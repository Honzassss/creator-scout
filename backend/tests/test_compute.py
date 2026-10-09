"""Unit tests for app.compute (language, metrics, collabs, identity). Small inline data only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.compute import collabs, identity, language, metrics
from app.models import Comment, NewsItem, Post, Profile, make_source_ref

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def src(url: str, platform: str = "instagram", **kw):
    return make_source_ref(url=url, platform=platform, mode="mock", fetched_at=NOW, **kw)


def post(i: str, caption: str = "", days: float = 0, *, handle: str = "anna", likes: int | None = 100,
         comments: int | None = 10, **kw) -> Post:
    url = f"https://www.instagram.com/p/{i}/"
    return Post(id=i, platform="instagram", url=url, author_handle=handle, created_at=NOW - timedelta(days=days),
                caption=caption, likes=likes, comments=comments, source=src(url, id=f"ig:post:{i}"), **kw)


def profile(handle: str = "anna", **kw) -> Profile:
    url = f"https://www.instagram.com/{handle}/"
    return Profile(handle=handle, platform=kw.pop("platform", "instagram"), url=url,
                   source=src(url, id=f"ig:profile:{handle}"), **kw)


def comment(text: str) -> Comment:
    return Comment(post_url="https://www.instagram.com/p/1/", text=text, source=src("https://www.instagram.com/p/1/"))


# ---------------------------------------------------------------------------------------------
# language
# ---------------------------------------------------------------------------------------------

def test_detect_language_czech_slovak_english():
    assert language.detect_language("Dnes jsme v Brně pekli kváskový chléb") == "cs"
    assert language.detect_language("To vyzerá výborne, kde to kúpim?") == "sk"
    assert language.detect_language("Looks amazing, where can I buy this?") == "en"
    assert language.detect_language("Das sieht wirklich lecker aus") == "de"


def test_detect_language_short_or_noise_is_none():
    assert language.detect_language("super") is None
    assert language.detect_language("😍🔥") is None
    assert language.detect_language("#brnofood #jidlo @anna") is None
    assert language.detect_language("") is None


def test_language_share_min_texts():
    caps = ["Dnes jsme pekli chléb v Brně", "Nový recept na koláče je venku", "Looks amazing today, friends"]
    assert language.language_share(caps, "cs", min_texts=3) == pytest.approx(2 / 3)
    assert language.language_share(caps[:2], "cs", min_texts=3) is None
    assert language.language_share([], "cs") is None


@pytest.mark.parametrize("text", ["😍🔥", "❤️❤️❤️", "super", "Suuuper!!", "wow 😍", "krása", "to je super",
                                  "nice pic", "👍", "@petr @jana", "top top top", "mňamka"])
def test_generic_comments(text):
    assert language.is_generic_comment(text)


@pytest.mark.parametrize("text", ["Kde to koupím?", "mnam, kde to koupím", "Moc pěkný recept, zkusím ho o víkendu",
                                  "Byla jsem tam včera a croissant byl výborný", ""])
def test_specific_comments_are_not_generic(text):
    assert not language.is_generic_comment(text)


def test_emoji_only_and_generic_share():
    assert language.is_emoji_only("😍 🔥 !")
    assert not language.is_emoji_only("super 😍")
    assert language.generic_share([]) is None
    assert language.generic_share(["😍", "Kde to koupím?", "super", "To vypadá skvěle, díky za tip"]) == 0.5


# ---------------------------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------------------------

def test_median_and_engagement_rate():
    assert metrics.median([]) is None
    assert metrics.median([3, 1, 2]) == 2
    assert metrics.median([1, 2, 3, 4]) == 2.5
    posts = [post("1", likes=90, comments=10), post("2", likes=190, comments=10), post("3", likes=None)]
    assert metrics.engagement_rate(posts, 1000) == pytest.approx(0.15)
    assert metrics.engagement_rate(posts, None) is None
    assert metrics.engagement_rate(posts, 0) is None
    assert metrics.engagement_rate([post("x", likes=None)], 1000) is None


def test_posts_per_week():
    assert metrics.posts_per_week([post("1")]) is None
    posts = [post(str(i), days=i * 7) for i in range(5)]  # 5 posts over 4 weeks
    assert metrics.posts_per_week(posts) == pytest.approx(1.0)


def test_commercial_share_and_markers():
    posts = [
        post("1", "nový chléb #reklama", hashtags=["reklama"]),
        post("2", "Se slevovým kódem ANNA20 máte slevu", paid_partnership=False),
        post("3", "obyčejný den", paid_partnership=True),
        post("4", "Není to reklama, jen tip"),
        post("5", "výlet"),
    ]
    assert [metrics.is_commercial(p) for p in posts] == [True, True, True, False, False]
    assert metrics.commercial_share(posts) == pytest.approx(0.6)
    assert metrics.commercial_share([]) is None


def test_local_signals_variants():
    prof = profile(bio="Brněnská foodie 🍰")
    posts = [
        post("1", "Snídaně", location_name="Brno, Zelný trh"),
        post("2", "Výlet do Prahy"),
        post("3", "Nejlepší kafe v Brně!"),
        post("4", "dobrota", hashtags=["brnofood"]),
    ]
    sig = metrics.local_signals(prof, posts, "Brno")
    ids = [s.id for s in sig]
    assert ids[0] == prof.source.id and "ig:post:1" in ids and "ig:post:3" in ids and "ig:post:4" in ids
    assert "ig:post:2" not in ids
    assert all(s.quote for s in sig)
    assert metrics.local_signals(prof, posts, None) == []
    praha = metrics.local_signals(profile(), posts, "Praha")
    assert [s.id for s in praha] == ["ig:post:2"]


def test_engagement_spikes():
    posts = [post("1", likes=100), post("2", likes=110), post("3", likes=1000), post("4", likes=90)]
    assert metrics.engagement_spikes(posts) == ["3"]
    assert metrics.engagement_spikes(posts[:2]) == []


def test_compute_metrics_full():
    prof = profile(followers=5000, bio="Peču v Brně")
    posts = [post("1", "Chléb v Brně", 1, media_type="reel"), post("2", "#reklama", 8, hashtags=["reklama"]),
             post("3", "Doma", 15, likes=1000, media_type="reel"), post("4", "Výlet", 22)]
    comments = [comment("Vypadá to skvěle, kde to koupím?"), comment("😍😍"), comment("super"),
                comment("Looks great, where is this place?"), comment("To musím ochutnat, díky za tip")]
    m = metrics.compute_metrics(prof, posts, city="Brno", topic_labels={"1": "food", "2": "food", "3": "family", "4": "bogus"},
                                comments=comments, now=NOW)
    assert m.posts_analyzed == 4
    assert m.formats == {"reel": 2, "other": 2}
    assert m.topic_counts == {"food": 2, "family": 1, "other": 1}
    assert m.commercial_share == 0.25
    assert m.comments_analyzed == 5
    assert m.cs_comment_share == pytest.approx(2 / 3)   # emoji / one-word comments: no detectable language
    assert m.generic_comment_share == pytest.approx(0.4)
    assert m.last_post_at == posts[0].created_at
    assert m.engagement_spikes == ["3"]
    assert len(m.local_signals) == 2
    empty = metrics.compute_metrics(prof, [], city=None)
    assert empty.cs_comment_share is None and empty.comments_analyzed == 0 and empty.topic_counts == {}


# ---------------------------------------------------------------------------------------------
# collabs
# ---------------------------------------------------------------------------------------------

COMPETITORS = [{"name": "Pekárna B", "handles": ["pekarna_b"]}]


def test_normalize_brand_and_competitor_keys():
    assert collabs.normalize_brand("Pekárna B") == "pekarnab"
    assert collabs.normalize_brand("@Pekarna_B") == "pekarnab"
    assert collabs.competitor_keys(COMPETITORS) == {"pekarnab"}
    assert collabs.competitor_keys([]) == set()


def test_find_discount_codes():
    assert collabs.find_discount_codes("Recenze, nikdo mi neplatí. Se slevovým kódem ANNA20 máte 20 %") == ["ANNA20"]
    assert collabs.find_discount_codes("use code fit10 at checkout, kod: BRNO15") == ["fit10", "BRNO15"]
    assert collabs.find_discount_codes("kód na slevu najdete v bio") == []


def test_extract_collabs_disclosure_and_competitors():
    posts = [
        post("1", "Ve spolupráci s @pekarna_b dnešní snídaně", coauthors=["pekarna_b"], paid_partnership=True),
        post("2", "Snídaně s @pekarna_b 🥐", coauthors=["pekarna_b"], paid_partnership=False),
        post("3", "Recenze, nikdo mi neplatí. Kód ANNA20 na @kavarna_x", paid_partnership=False),
        post("4", "Výlet s @kamaradka_jana", paid_partnership=False),
        post("5", "Doporučuju @mlsna_cukrarna_cz", paid_partnership=None),
        post("6", "nový drop #reklama @brandx", hashtags=["reklama"]),
    ]
    ev = collabs.extract_collabs(posts, own_handle="anna", competitors=COMPETITORS)
    by = {e.id: e for e in ev}
    assert by["collab:1:coauthor:pekarnab"].disclosed is True
    assert by["collab:1:coauthor:pekarnab"].is_competitor is True
    assert by["collab:1:paid_label:pekarnab"].kind == "paid_label"
    assert by["collab:2:coauthor:pekarnab"].disclosed is False
    assert by["collab:3:discount_code:kavarnax"].disclosed is False
    assert by["collab:5:mention:mlsnacukrarnacz"].disclosed is None     # label unknown
    assert by["collab:6:ad_hashtag:brandx"].disclosed is True
    assert not any("kamaradka" in e.id for e in ev)                       # a friend is not a brand
    assert all(e.source.quote for e in ev)
    assert len(collabs.undisclosed_posts(ev)) == 2                        # posts 2 and 3


def test_mark_competitors_and_merge_timeline():
    posts = [post("1", "s @pekarna_b", coauthors=["pekarna_b"], days=10), post("2", "#reklama @brandx", hashtags=["reklama"], days=2)]
    ev = collabs.extract_collabs(posts, competitors=[])
    assert not any(e.is_competitor for e in ev)
    marked = collabs.mark_competitors(ev, COMPETITORS)
    assert any(e.is_competitor for e in marked) and not any(e.is_competitor for e in ev)
    extra = ev[0].model_copy(update={"id": "meta:1", "kind": "meta_branded", "date": None})
    tl = collabs.merge_timeline(ev, [extra, ev[0]])
    assert len(tl) == len(ev) + 1
    assert tl[-1].id == "meta:1"                                          # None date last
    dates = [e.date for e in tl if e.date]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------------------------

def _ig() -> Profile:
    return profile("anna_pece", display_name="Anna Nováková", bio="Peču v Brně 🍞 TikTok: @annapece",
                   external_urls=["https://www.annapece.cz/"])


def _tt(handle: str, **kw) -> Profile:
    url = f"https://www.tiktok.com/@{handle}"
    return Profile(handle=handle, platform="tiktok", url=url, source=src(url, "tiktok"), **kw)


def test_identity_matched_uncertain_rejected():
    ig = _ig()
    same = _tt("annapece", display_name="Anna Nováková", bio="IG @anna_pece", external_urls=["annapece.cz"])
    fan = _tt("annapece_fans", display_name="Anna Nováková fanpage", bio="fan page, not affiliated")
    namesake = Profile(handle="anna.novakova", platform="youtube", url="https://youtube.com/@anna.novakova",
                       display_name="Anna Nováková", bio="Vlogy", source=src("https://youtube.com/@anna.novakova", "youtube"))
    res = {m.handle: m for m in identity.match_identity(ig, [same, fan, namesake])}
    assert res["annapece"].status == "matched"
    assert res["annapece_fans"].status == "rejected"
    assert any(not s.supports for s in res["annapece_fans"].signals)
    assert res["anna.novakova"].status == "uncertain"
    assert identity.is_fan_account(ig, fan) and not identity.is_fan_account(ig, same)
    assert all(s.source is not None for s in res["annapece"].signals)


def test_news_subject_and_namesake():
    ig = _ig()

    def item(i, title):
        return NewsItem(id=i, title=title, outlet="Deník", url=f"https://n/{i}", published_at=None,
                        source=src(f"https://n/{i}", "news"))

    other = item("n1", "Starostka Anna Nováková (54) otevřela nový park v Olomouci")
    maybe = item("n2", "Anna Nováková: pekařka z Instagramu chystá knihu")
    sure = item("n3", "Tvůrkyně @anna_pece vydává knihu")
    unrelated = item("n4", "Brno otevírá nové trhy")
    assert identity.news_subject(ig, other, "Brno") == "rejected"
    assert identity.news_subject(ig, maybe, "Brno") == "uncertain"
    assert identity.news_subject(ig, sure, "Brno") == "matched"
    assert identity.news_subject(ig, unrelated, "Brno") == "rejected"
    ns = identity.match_news(ig, [other, maybe, sure, unrelated], city="Brno")
    assert [m.handle for m in ns] == ["n1"]
    assert ns[0].status == "rejected" and ns[0].platform == "news"
    assert ns[0].signals[0].source is not None
