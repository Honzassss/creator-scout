"""ApifyProvider without a token: pure mappers on HAND-MADE samples (tests/apify_samples/: fictional
sample_* accounts and invented values, shaped like the live runs of 9. 10. 2026, see
docs/apify-pro-krystofa.md "Výsledky živých testů") and the orchestration with a fake runner.
Nothing here calls Apify."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.compute.minors import is_minor
from app.events import bind_emit
from app.models import DiscoveryQuery, iter_source_refs
from app.sources import apify_provider as ap
from app.sources.apify_provider import (
    ACT_BRAND,
    ACT_IG_COMMENT,
    ACT_IG_HASHTAG,
    ACT_IG_POST,
    ACT_IG_PROFILE,
    ACT_IG_SCRAPER,
    ACT_IG_SEARCH,
    ACT_NEWS,
    ACT_TT,
    ACT_TT_COMMENTS,
    ACT_TT_PROFILE,
    ACT_YT,
    ApifyProvider,
    RunResult,
)

SAMPLES = Path(__file__).parent / "apify_samples"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def sample(name: str) -> list[dict]:
    return json.loads((SAMPLES / name).read_text("utf-8"))["items"]


def all_live(objs, actor: str | None = None) -> bool:
    refs = list(iter_source_refs(objs))
    return bool(refs) and all(r.mode == "live" and r.actor and (actor is None or r.actor == actor) for r in refs)


def dumped(objs) -> str:
    return json.dumps([o.model_dump(mode="json") for o in objs], ensure_ascii=False)


# ---------------------------------------------------------------------------------------------
# Samples and inputs
# ---------------------------------------------------------------------------------------------


def test_samples_are_marked_hand_made():
    files = sorted(SAMPLES.glob("*.json"))
    assert len(files) >= 12
    for f in files:
        d = json.loads(f.read_text("utf-8"))
        assert "HAND-MADE" in d["_note"] and "NOT real data" in d["_note"], f.name
        assert d["items"], f.name


def test_inputs_set_limits_and_cost_traps():
    post = ap.ig_post_input(["anna"], 24, "detailedData")
    assert post == {"username": ["anna"], "resultsLimit": 24, "skipPinnedPosts": True, "dataDetailLevel": "detailedData"}
    assert "onlyPostsNewerThan" not in post                       # buggy filter: date filtered in code
    assert ap.ig_post_input(["https://www.instagram.com/p/A/"], 1, skip_pinned=False)["skipPinnedPosts"] is False
    assert ap.ig_search_input(["cukrárna, brno"], "user", 25) == {
        "search": "cukrárna brno", "searchType": "user", "searchLimit": 25, "enhanceUserSearchWithFacebookPage": False}
    assert ap.ig_search_input(["a", "b"], "place", 999)["searchLimit"] == 250
    assert ap.ig_search_input(["a"], "user", 25, live=True)["liveSearch"] is True
    assert "liveSearch" not in ap.ig_search_input(["a"], "place", 30, live=True)   # live places have no location_id
    assert ap.yt_channel_input("@SampleCukrarka", 3) == {
        "startUrls": [{"url": "https://www.youtube.com/@samplecukrarka"}], "maxResults": 3, "maxResultsShorts": 0,
        "maxResultStreams": 0}
    assert ap.ig_hashtag_input(["#BrnoFood"], 50) == {"hashtags": ["brnofood"], "resultsType": "posts",
                                                      "resultsLimit": 50, "keywordSearch": False}
    assert ap.ig_profile_input(["@Anna", ""]) == {"usernames": ["anna"], "includeAboutSection": False}
    assert ap.ig_comment_input(["u"], 15) == {"directUrls": ["u"], "resultsLimit": 15}
    loc = ap.ig_location_input(["123"], "details", 1)
    assert loc["directUrls"] == ["https://www.instagram.com/explore/locations/123/"] and loc["resultsType"] == "details"
    tt = ap.tt_search_input("cukrárna brno")
    assert tt["searchSection"] == "/user" and tt["resultsPerPage"] == 3 and tt["maxProfilesPerQuery"] == 10
    assert tt["proxyCountryCode"] == "CZ" and "proxyCountryCode" not in ap.tt_search_input("x", proxy="None")
    assert ap.tt_profile_input(["x"])["resultsPerPage"] == 12           # default 100 is the cost trap
    assert ap.tt_profile_input(["x"])["excludePinnedPosts"] is True
    assert ap.tt_comments_input(["u"], 15) == {"postURLs": ["u"], "commentsPerPost": 15, "maxRepliesPerComment": 0}
    b = ap.brand_collab_input("https://www.instagram.com/anna/")
    assert b["resultsLimit"] == 20 and b["onlyPostsNewerThan"] and b["startUrls"] == ["https://www.instagram.com/anna/"]
    n = ap.news_input("cukrárna Brno", "CZ", "cs", 100)
    assert n == {"keywords": ["cukrárna Brno"], "region_language": "CZ:cs", "timeframe": "1y", "maxArticles": 20,
                 "decodeUrls": True, "extractImages": False}


def test_estimates_use_handoff_prices():
    assert ap.estimate_usd(ACT_IG_PROFILE, 60) == pytest.approx(0.156)
    assert ap.estimate_usd(ACT_IG_POST, 300) == pytest.approx(0.81)
    assert ap.estimate_usd(ACT_TT, 90) == pytest.approx(90 * 0.0037 + 0.001)


def test_charge_cap_follows_the_estimate():
    assert ap.charge_cap_usd(ACT_NEWS, 0.04, 3.0) == pytest.approx(0.13)        # not the flat 3 USD
    assert ap.charge_cap_usd(ACT_IG_PROFILE, 2.0, 3.0) == pytest.approx(3.0)     # never above MAX_USD_PER_RUN
    assert ap.charge_cap_usd(ACT_TT, 0.05, 3.0) == pytest.approx(0.5)           # minimalMaxTotalChargeUsd
    assert ap.charge_cap_usd(ACT_TT, 0.05, 0.3) == pytest.approx(0.5)           # Apify refuses less


def test_parse_ts_variants():
    assert ap.parse_ts("2026-10-01T09:00:00.000Z") == datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    assert ap.parse_ts("2026-07-25") == datetime(2026, 7, 25, tzinfo=timezone.utc)
    assert ap.parse_ts(1786779000) == ap.parse_ts(1786779000000) == ap.parse_ts("1786779000")
    assert ap.parse_ts(None) is None and ap.parse_ts("nonsense") is None and ap.parse_ts(True) is None


# ---------------------------------------------------------------------------------------------
# Instagram mappers
# ---------------------------------------------------------------------------------------------


def test_map_ig_search_users_and_related():
    items = sample("ig_search_users.json")
    ref = ap.map_ig_search_user(items[0], query="cukrárna brno", actor=ACT_IG_SEARCH, fetched_at=NOW)
    assert ref.handle == "sample_cukrarka_brno" and ref.platform == "instagram"
    assert ref.found_via == ["search:cukrárna brno"] and "facebook-ads" in ref.source.quote
    assert all_live([ref], ACT_IG_SEARCH)
    related = ap.map_ig_related(items[0], actor=ACT_IG_SEARCH, fetched_at=NOW)
    assert [r.handle for r in related] == ["sample_related_kavarna"]               # private one skipped
    assert related[0].found_via == ["related:@sample_cukrarka_brno"]
    assert ap.raw_minor(items[1], "instagram") and not ap.raw_minor(items[0], "instagram")
    assert ap.map_ig_search_user(items[4], query="x", actor=ACT_IG_SEARCH, fetched_at=NOW) is None   # error item
    # liveSearch item (live T1): thin, no searchSource / followers / bio / latestPosts
    live = ap.map_ig_search_user(items[3], query="brno food", actor=ACT_IG_SEARCH, fetched_at=NOW)
    assert live.handle == "sample_foodie_live_brno" and live.source.quote == "search:brno food"
    thin = ap.map_ig_profile(items[3], actor=ACT_IG_SEARCH, fetched_at=NOW)
    assert (thin.bio, thin.followers, thin.latest_posts, thin.display_name) == ("", None, [], "Sample Foodie")


def test_search_user_in_city_filter():
    """Live T1: google / threads hits for Czech queries were off-topic (fuzzy "bruno", foreign mega accounts)."""
    items = sample("ig_search_users.json")
    kept = [it["username"] for it in items if not ap.error_of(it) and ap.search_user_in_city("Brno", it)]
    assert kept == ["sample_cukrarka_brno", "sample_foodie_live_brno"]      # handle substring or name / bio
    assert ap.search_user_in_city("Brno", {"username": "x", "fullName": "Cukrárna Brno"})
    assert ap.search_user_in_city("Brno", {"username": "x", "biography": "Peču dorty v Brně"})   # declension
    assert not ap.search_user_in_city("Brno", {"username": "bruno_food_factory"})
    assert ap.search_user_in_city(None, {"username": "anything"})                                 # no city: keep


def test_map_ig_profile():
    items = sample("ig_profiles.json")
    p = ap.map_ig_profile(items[0], actor=ACT_IG_PROFILE, fetched_at=NOW)
    assert p.handle == "sample_cukrarka_brno" and p.url == "https://www.instagram.com/sample_cukrarka_brno/"
    assert p.display_name == "Sample Cukrářka"                                    # fullName is there (live T5)
    assert (p.followers, p.following, p.posts_count, p.private, p.is_business) == (8200, 410, 230, False, True)
    assert p.business_category == "Candy Store"
    assert ap._business_category("None,Candy Store") == "Candy Store" and ap._business_category("None") is None
    assert p.external_urls == ["https://sample-cukrarka.example", "https://www.youtube.com/@samplecukrarka"]
    assert p.related_handles == []                                                # [] on local accounts (live)
    assert p.former_handles == [] and p.former_handles_count == 2                 # a count, not a list
    assert p.is_under_18 is None and p.region is None
    pinned, reel, collab = p.latest_posts
    assert pinned.is_pinned is True and pinned.media_type == "photo"
    assert reel.is_pinned is None                                                 # isPinned only when true
    assert reel.media_type == "reel" and (reel.likes, reel.comments, reel.views) == (640, 15, 5400)
    assert (reel.location_name, reel.location_id) == ("Sample Kavárna Zelný trh", "100000001")
    assert reel.tagged_users == ["sample_friend"] and reel.paid_partnership is None   # no label in latestPosts
    # a collab post owned by the partner sits in the grid (live T5: 6/84): the profile becomes its co-author
    assert collab.author_handle == "sample_partner_creator" and collab.coauthors == ["sample_cukrarka_brno"]
    assert reel.coauthors == []
    assert "Full Name" not in dumped([p])
    assert all_live([p], ACT_IG_PROFILE)
    assert ap.map_ig_profile(items[1], actor=ACT_IG_PROFILE, fetched_at=NOW) is None   # error item
    teen = ap.map_ig_profile(items[2], actor=ACT_IG_PROFILE, fetched_at=NOW)
    assert teen is not None and teen.handle == "sample_teen_profile" and is_minor(teen) and teen.display_name == ""


def test_ig_profile_handle_fallbacks():
    """`username` is there live (T5); the guard: latestPosts[].ownerUsername, then the requested name."""
    own = {"ownerUsername": "anna"}
    partner = {"ownerUsername": "brand_x"}
    assert ap.ig_profile_handle({"username": "Anna", "latestPosts": [partner]}) == "anna"   # username wins
    assert ap.ig_profile_handle({"latestPosts": [own, partner, own]}) == "anna"             # most common owner
    assert ap.ig_profile_handle({"latestPosts": [partner, partner, own]}, ["anna", "eva"]) == "anna"  # asked-for
    assert ap.ig_profile_handle({"latestPosts": [partner]}, ["anna"]) == "brand_x"     # an owner beats the request
    assert ap.ig_profile_handle({"latestPosts": []}, ["anna"]) == "anna"                   # batch of one
    assert ap.ig_profile_handle({"latestPosts": []}, ["anna", "eva"]) is None              # cannot tell
    assert ap.ig_profile_handle({"biography": "x"}) is None
    p = ap.map_ig_profile({"biography": "x", "private": True}, actor=ACT_IG_PROFILE, fetched_at=NOW,
                          requested=["@Anna"])
    assert p.handle == "anna" and p.private is True


def test_map_ig_post_detailed_labels():
    items = sample("ig_posts_detailed.json")
    p = ap.map_ig_post(items[0], actor=ACT_IG_POST, fetched_at=NOW, trust_false_label=True)
    assert p.id == "ig:post:SAMPLEd1" and p.author_handle == "sample_cukrarka_brno"
    assert p.paid_partnership is True and p.coauthors == ["sample_brand"]
    assert p.sponsors == []                                                      # never present live (T6)
    sponsored = ap.map_ig_post({**items[0], "sponsors": [{"username": "sample_brand"}, "x_brand"]},
                               actor=ACT_IG_POST, fetched_at=NOW)
    assert sponsored.sponsors == ["sample_brand", "x_brand"]                     # still read if it ever appears
    assert p.location_name == "Sample Kavárna Zelný trh" and p.location_id == "100000001"
    assert p.hashtags == ["reklama"] and p.mentions == ["sample_brand"] and p.is_pinned is None
    assert "real.person" not in dumped([p]) and "Vypadá" not in dumped([p])     # latestComments never on a Post
    no_label = ap.map_ig_post(items[2], actor=ACT_IG_POST, fetched_at=NOW, trust_false_label=True)
    assert no_label.paid_partnership is False                                    # detailedData: False is a real "no"
    assert ap.map_ig_post(items[2], actor=ACT_IG_POST, fetched_at=NOW).paid_partnership is None
    assert no_label.likes is None and no_label.comments == 3                     # username mode: likesCount -1
    assert no_label.media_type == "reel" and no_label.views is None              # videoPlayCount is not views
    assert ap.map_ig_post({"ownerUsername": "x", "url": "https://www.instagram.com/p/A/"}, actor=ACT_IG_POST,
                          fetched_at=NOW) is None                                # no timestamp -> skipped


def test_map_ig_hashtag_posts_and_place_verdict():
    posts = [ap.map_ig_post(i, actor=ACT_IG_HASHTAG, fetched_at=NOW) for i in sample("ig_hashtag_posts.json")]
    assert [p.author_handle for p in posts] == ["sample_foodie_brno", "sample_prague_eater", "sample_no_location",
                                                "sample_text_place"]
    assert posts[0].paid_partnership is True and posts[1].paid_partnership is None   # hashtag: only True counts
    assert [p.media_type for p in posts] == ["carousel", "photo", "photo", "photo"]  # type Sidecar / Image (live T3)
    assert posts[0].id == "ig:post:SAMPLEh1" and posts[0].mentions == ["sample_brand"]   # mentions [] -> caption
    assert posts[2].tagged_users == ["sample_friend"] and posts[0].sponsors == []
    places = [ap.map_ig_place(i) for i in sample("ig_location_details.json")]
    coords = {pl.location_id: (pl.lat, pl.lng) for pl in places if pl}
    assert set(coords) == {"100000001", "100000003"}                             # paired by location_id, any order
    post_shaped = {"ownerUsername": "x", "shortCode": "A", "locationId": "1", "timestamp": "2026-10-01"}
    assert ap.map_ig_place(post_shaped) is None                                  # a post is never a place
    verdicts = [ap.place_verdict(city="Brno", location_id=p.location_id, location_name=p.location_name,
                                 coords=coords, city_location_ids=set()) for p in posts]
    assert verdicts == ["in", "out", "unknown", "in"]
    assert ap.place_verdict(city=None, location_id="100000003", location_name=None, coords=coords,
                            city_location_ids=set()) == "unknown"


def test_map_ig_place_shapes():
    found, iran, directory = (ap.map_ig_place(i) for i in sample("ig_search_places.json"))
    # nested posts: author in user.username (live T2/T4); the venue's own account is not an author
    assert found.location_id == "100000001" and found.authors == ["sample_place_author", "sample_stale_place_author"]
    recent = ap.map_ig_place(sample("ig_search_places.json")[0], now=NOW)
    assert recent.authors == ["sample_place_author"]                            # top post from 2020 dropped
    assert found.business_handle == "sample_kavarna_business"
    assert found.city is None                       # location_city "" (filled on 4/42 live)
    assert ap.map_ig_place({"location_id": "1", "location_city": "Brno"}).city == "Brno"
    assert iran.authors == [] and ap.in_city_bbox("Brno", iran.lat, iran.lng) is False   # no posts key; trap
    assert directory is None                        # charged "city directory" item without location_id
    assert ap.in_city_bbox("Brno", found.lat, found.lng) is True
    assert ap.in_city_bbox("Ostrava", 49.8, 18.2) is None and ap.in_city_bbox("Brno", None, 16.6) is None
    # liveSearch place item: id instead of location_id, `city` (never sent by the provider for places)
    live = ap.map_ig_place({"id": "100000010", "name": "Sample Live", "lat": 49.19, "lng": 16.61, "city": "Brno"})
    assert live.location_id == "100000010" and live.city == "Brno"
    assert ap.map_ig_place({"id": "5", "ownerUsername": "x", "lat": 49.2}) is None    # post-like, not a place


def test_map_ig_comments_never_keep_identity():
    items = sample("ig_comments.json")
    url = "https://www.instagram.com/p/SAMPLEd1/"
    cs = [ap.map_ig_comment(i, actor=ACT_IG_COMMENT, fetched_at=NOW, index=n, post_url=url) for n, i in enumerate(items, 1)]
    assert cs[2] is None                                                         # error item
    a, b = cs[0], cs[1]
    assert a.text == "To vypadá výborně, zítra jdu!" and a.post_url == url and a.source.url == url
    assert b.text == "@user 😍"                                                  # third-party handle masked
    text = dumped([a, b])
    for leak in ("real.person", "another.person", "kamaradka", "ownerProfilePicUrl", "180000000001", "/c/"):
        assert leak not in text
    latest = ap.map_ig_latest_comments(sample("ig_posts_detailed.json")[0], actor=ACT_IG_POST, fetched_at=NOW, per_post=1)
    assert len(latest) == 1 and "real.person" not in dumped(latest) and "kamaradka" not in dumped(latest)


# ---------------------------------------------------------------------------------------------
# TikTok, Meta, news mappers
# ---------------------------------------------------------------------------------------------


def test_map_tt_video_and_profiles():
    items = sample("tt_search_user.json")
    v = ap.map_tt_video(items[1], actor=ACT_TT, fetched_at=NOW)
    assert v.id == "tt:video:7400000000000000002" and v.author_handle == "sample_cukrarka"
    assert (v.likes, v.comments, v.views) == (500, 20, 9000)
    assert v.paid_partnership is True and v.language is None                     # textLanguage "un" -> unknown
    # locationMeta.city "" (live T9: 5/16): the address names the town, so a city match still sees Brno
    assert v.location_name == "Sample Zelný trh, Sample Zelný trh 1, Brno" and v.location_id == "22500000000000001"
    assert v.hashtags == ["dortybrno"] and v.mentions == ["sample_brand"]       # objects {name}; "@handle" strings
    assert v.is_pinned is True and v.media_type == "video"
    first = ap.map_tt_video(items[0], actor=ACT_TT, fetched_at=NOW)
    assert first.language == "cs" and first.location_name is None and first.is_pinned is False
    assert ap.map_tt_video(items[2], actor=ACT_TT, fetched_at=NOW).media_type == "carousel"   # isSlideshow
    profs = {p.handle: p for p in ap.map_tt_profiles(sample("tt_profile_videos.json"), actor=ACT_TT_PROFILE,
                                                     fetched_at=NOW, requested=["sample_cukrarka"])}
    p = profs["sample_cukrarka"]
    assert p.followers == 12000 and p.private is False and p.external_urls == ["https://sample-cukrarka.example"]
    assert (p.display_name, p.following, p.posts_count) == ("Sample Cukrářka TT", 180, 120)   # nickName / following / video
    assert p.region is None and p.is_under_18 is None                            # keys absent (live T10)
    assert [x.created_at.month for x in p.latest_posts] == [10, 9]               # newest first
    assert all_live([p], ACT_TT_PROFILE) and len(profs) == 1                     # PROFILE_EMPTY skipped
    teen = ap.map_tt_profiles([items[2]], actor=ACT_TT, fetched_at=NOW)
    assert teen[0].is_under_18 is None and is_minor(teen[0])                     # age only from the bio
    flagged = {**items[0], "authorMeta": {**items[0]["authorMeta"], "isUnderAge18": True}}
    assert ap.map_tt_profiles([flagged], actor=ACT_TT, fetched_at=NOW)[0].is_under_18 is True   # an explicit true
    priv = ap.map_tt_profiles([{"errorCode": "PROFILE_PRIVATE"}], actor=ACT_TT_PROFILE, fetched_at=NOW,
                              requested=["sample_private_tt"])
    assert priv[0].handle == "sample_private_tt" and priv[0].private is True


def test_map_tt_video_defensive_shapes(monkeypatch):
    base = dict(sample("tt_search_user.json")[0])
    # hashtag objects give their names; without hashtags / with object mentions the caption is parsed
    objs = {**base, "hashtags": [{"name": "x"}], "mentions": [{"name": "y"}], "text": "Dort #brno_food. @sample.brand."}
    v = ap.map_tt_video(objs, actor=ACT_TT, fetched_at=NOW)
    assert v.hashtags == ["x"] and v.mentions == ["sample.brand"]               # no trailing period
    bare = ap.map_tt_video({**objs, "hashtags": []}, actor=ACT_TT, fetched_at=NOW)
    assert bare.hashtags == ["brno_food"]
    # a top-level locationName is still read (never seen live, guard)
    assert ap.map_tt_video({**base, "locationName": "Sample Top"}, actor=ACT_TT, fetched_at=NOW).location_name == "Sample Top"
    # isSponsored false on 46/46 live videos, no labelled Czech video seen: false is not trusted by default
    assert ap.TRUST_TIKTOK_FALSE_LABEL is False
    assert ap.map_tt_video(base, actor=ACT_TT, fetched_at=NOW).paid_partnership is None
    monkeypatch.setattr(ap, "TRUST_TIKTOK_FALSE_LABEL", True)
    assert ap.map_tt_video(base, actor=ACT_TT, fetched_at=NOW).paid_partnership is False
    assert ap.map_tt_video(sample("tt_search_user.json")[1], actor=ACT_TT, fetched_at=NOW).paid_partnership is True


def test_caption_tags_and_mentions_drop_trailing_period():
    p = ap.map_ig_post({"ownerUsername": "a", "url": "https://www.instagram.com/p/A/", "timestamp": "2026-10-01",
                        "caption": "Snídaně #brno_food. díky @anna.k. a #BrnoKafe!"}, actor=ACT_IG_HASHTAG, fetched_at=NOW)
    assert p.hashtags == ["brno_food", "brnokafe"] and p.mentions == ["anna.k"]
    assert ap.mask_mentions("super @anna.k.") == "super @user."


def test_scan_tiktok_handle_never_takes_someone_elses_link():
    note = sample("tt_search_user.json")[3]                                     # live T9 "note" item
    assert ap._scan_tiktok_handle(note) == "sample_tt_empty"                    # authorMeta.profileUrl
    assert ap._scan_tiktok_handle({"authorMeta": {"name": "Anna.K", "bioLink": "https://www.tiktok.com/@friend"}}) == "anna.k"
    # other shapes (error items): only a single distinct non-bio handle is accepted
    assert ap._scan_tiktok_handle({"authorMeta": {"bioLink": "https://www.tiktok.com/@friend_acc"}}) is None
    assert ap._scan_tiktok_handle({"authorMeta": {"signature": "kamarád tiktok.com/@friend_acc"}}) is None
    assert ap._scan_tiktok_handle({"x": "https://www.tiktok.com/@anna", "authorMeta": {
        "bioLink": "https://www.tiktok.com/@friend_acc"}}) == "anna"
    assert ap._scan_tiktok_handle({"x": "https://www.tiktok.com/@anna", "y": "https://www.tiktok.com/@eva"}) is None
    assert ap._scan_tiktok_handle({"webVideoUrl": "https://www.tiktok.com/@anna/video/1",
                                   "authorMeta": {"bioLink": "https://www.tiktok.com/@friend_acc"}}) == "anna"


def test_map_tt_search_and_comments():
    refs = ap.map_tt_search(sample("tt_search_user.json"), query="cukrárna brno", actor=ACT_TT, fetched_at=NOW)
    assert [r.handle for r in refs] == ["sample_cukrarka", "sample_tt_teen"]    # deduped; 0-video note skipped
    assert refs[0].found_via == ["search:cukrárna brno"] and refs[0].source.url == "https://www.tiktok.com/@sample_cukrarka"
    c = ap.map_tt_comment(sample("tt_comments.json")[0], actor=ACT_TT_COMMENTS, fetched_at=NOW, index=1)
    assert c.text == "Chci ochutnat! @user" and c.created_at.day == 5
    assert "real_commenter" not in dumped([c]) and "6800000000000000000" not in dumped([c]) and "Kamos" not in dumped([c])


def test_map_brand_collab_direction():
    rows = sample("brand_collabs.json")
    ev = ap.map_brand_collab(rows[0], creator_handle="sample_cukrarka_brno", actor=ACT_BRAND, fetched_at=NOW)
    assert len(ev) == 1
    e = ev[0]
    # live T8: names are IG handles, links instagram.com/_u/<handle> without a trailing slash
    assert (e.brand, e.brand_handle, e.kind, e.disclosed) == ("sample_brand", "sample_brand", "meta_branded", True)
    assert e.date == datetime(2026, 7, 25, tzinfo=timezone.utc) and e.id == "collab:meta:3700000000000000401"
    assert e.source.platform == "meta_branded" and e.source.url == "https://www.instagram.com/reel/SAMPLEbc1/"
    assert e.post_id == "ig:post:SAMPLEbc1"                                      # dedupes with the post's own label
    assert all_live(ev, ACT_BRAND)
    assert ap.map_brand_collab(rows[3], creator_handle="sample_cukrarka_brno", actor=ACT_BRAND, fetched_at=NOW) == []
    # our account on the brand side of someone else's post is not a creator collaboration
    assert ap.map_brand_collab(rows[1], creator_handle="sample_cukrarka_brno", actor=ACT_BRAND, fetched_at=NOW) == []
    # a row about two other accounts is not ours either (was credited to us before)
    assert ap.map_brand_collab(rows[2], creator_handle="sample_cukrarka_brno", actor=ACT_BRAND, fetched_at=NOW) == []
    fb = {**rows[0], "creator": {"name": "Sample Cukrářka", "link": "https://www.facebook.com/samplecukrarka"}}
    assert len(ap.map_brand_collab(fb, creator_handle="sample_cukrarka_brno", actor=ACT_BRAND, fetched_at=NOW)) == 1
    assert ap.ig_handle_from_link("https://www.instagram.com/_u/sample_brand/") == "sample_brand"
    assert ap.ig_handle_from_link("https://www.instagram.com/p/ABC/") is None


def test_map_news():
    a, b = (ap.map_news(i, actor=ACT_NEWS, fetched_at=NOW) for i in sample("news.json"))
    assert a.id.startswith("news:") and a.outlet == "Sample Deník" and a.published_at.month == 8
    assert a.source.platform == "news" and a.source.quote == a.title
    assert a.snippet == ""                                                       # no description key (live T11)
    assert b.url.startswith("https://news.google.com/") and b.published_at == a.published_at   # ms timestamp
    assert ap.map_news({"title": "t", "url": "u", "source": {"name": "Obj"}}, actor=ACT_NEWS, fetched_at=NOW).outlet == "Obj"


def test_map_yt_video():
    items = sample("yt_videos.json")
    old, paid = (ap.map_yt_video(i, actor=ACT_YT, fetched_at=NOW) for i in items)
    assert paid.id == "yt:video:SAMPLEyt001" and paid.platform == "youtube" and paid.author_handle == "samplecukrarka"
    assert paid.paid_partnership is True and (paid.likes, paid.comments, paid.views) == (240, 31, 5300)
    assert paid.media_type == "video" and paid.hashtags == ["dortybrno"] and paid.mentions == []
    assert paid.location_name is None and paid.source.quote.startswith("Sample: dort")
    assert old.paid_partnership is None          # live T12: false also on a video with a sponsor link
    assert all_live([old, paid], ACT_YT)
    assert ap.map_yt_video({"url": "https://www.youtube.com/watch?v=SAMPLEyt003", "date": "2026-10-01T00:00:00Z"},
                           actor=ACT_YT, fetched_at=NOW, default_author="SampleCukrarka").id == "yt:video:SAMPLEyt003"
    assert ap.map_yt_video({"error": "x"}, actor=ACT_YT, fetched_at=NOW) is None


def test_cross_platform_links_and_merge():
    p = ap.map_ig_profile(sample("ig_profiles.json")[0], actor=ACT_IG_PROFILE, fetched_at=NOW)
    links = ap.cross_platform_links(p)
    assert ("tiktok", "sample_cukrarka", "https://www.tiktok.com/@sample_cukrarka") in links
    assert ("youtube", "samplecukrarka", "https://www.youtube.com/@samplecukrarka") in links
    assert all(not (pl == "instagram" and h == p.handle) for pl, h, _ in links)
    tt = ap.map_tt_profiles(sample("tt_profile_videos.json"), actor=ACT_TT_PROFILE, fetched_at=NOW)[0]
    assert ap.cross_platform_links(tt) == [("instagram", "sample_cukrarka_brno",
                                            "https://www.instagram.com/sample_cukrarka_brno/")]   # "IG @handle" in bio
    yt = ap.link_only_profile("youtube", "samplecukrarka", links[-1][2], p, NOW)
    assert yt.platform == "youtube" and yt.followers is None and yt.source.mode == "live"
    r1 = ap.map_ig_search_user(sample("ig_search_users.json")[0], query="a", actor=ACT_IG_SEARCH, fetched_at=NOW)
    r2 = r1.model_copy(update={"found_via": ["hashtag:brnofood", "search:a"]})
    rel = ap.map_ig_related(sample("ig_search_users.json")[0], actor=ACT_IG_SEARCH, fetched_at=NOW)
    merged = ap.merge_refs([*rel, r2, r1])
    assert merged[0].handle == "sample_cukrarka_brno" and merged[0].found_via == ["hashtag:brnofood", "search:a"]
    assert merged[-1].handle == "sample_related_kavarna"


# ---------------------------------------------------------------------------------------------
# Provider orchestration (fake runner, no network)
# ---------------------------------------------------------------------------------------------


class FakeRunner:
    def __init__(self, fail_first: bool = False) -> None:
        self.calls: list[tuple[str, dict, dict]] = []
        self.fail_first = fail_first

    async def __call__(self, actor: str, run_input: dict, *, max_items: int, max_usd: float, timeout_s: int) -> RunResult:
        self.calls.append((actor, run_input, {"max_items": max_items, "max_usd": max_usd, "timeout_s": timeout_s}))
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("sample failure")
        if actor == ACT_IG_SEARCH:
            name = "ig_search_places.json" if run_input["searchType"] == "place" else "ig_search_users.json"
        else:
            name = {ACT_IG_HASHTAG: "ig_hashtag_posts.json", ACT_IG_SCRAPER: "ig_location_details.json",
                    ACT_IG_PROFILE: "ig_profiles.json", ACT_IG_POST: "ig_posts_detailed.json",
                    ACT_IG_COMMENT: "ig_comments.json", ACT_TT: "tt_search_user.json",
                    ACT_TT_PROFILE: "tt_profile_videos.json", ACT_TT_COMMENTS: "tt_comments.json",
                    ACT_BRAND: "brand_collabs.json", ACT_NEWS: "news.json", ACT_YT: "yt_videos.json"}[actor]
        return RunResult(items=sample(name), status="SUCCEEDED", usd=0.01, events={"result": 3})

    def actors(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def logs():
    seen: list[dict] = []

    async def emit(event: str, data: dict) -> None:
        if event == "log":
            seen.append(data)

    with bind_emit(emit):
        yield seen


async def test_provider_without_token_returns_empty_and_logs(logs):
    p = ApifyProvider()                    # conftest: APIFY_TOKEN="" -> must not raise
    assert p.token is None and p.name == "apify"
    prof = ap.map_ig_profile(sample("ig_profiles.json")[0], actor=ACT_IG_PROFILE, fetched_at=NOW)
    assert await p.discover(DiscoveryQuery(keywords=["cukrárna"], city="Brno")) == []
    assert await p.profiles(["anna"], "instagram") == []
    assert await p.posts("anna", "instagram", NOW - timedelta(days=30)) == []
    assert await p.comments(["https://www.instagram.com/p/SAMPLEd1/"]) == []
    assert await p.collabs("anna", "instagram") == []
    assert await p.news("Anna Peče") == []
    assert await p.find_cross_platform(prof) == []
    assert len(logs) == 7 and all("APIFY_TOKEN" in x["text"] and x["mode"] == "live" for x in logs)


def test_name_matches_cache_namespace():
    from app.sources.cache import DEFAULT_IMPORT_PROVIDER
    from app.sources.factory import CACHE_NAMESPACE

    assert ApifyProvider.name == CACHE_NAMESPACE == DEFAULT_IMPORT_PROVIDER


async def test_provider_discover_merges_paths_and_filters_city(logs, monkeypatch):
    monkeypatch.setenv("APIFY_TIKTOK_SEARCH", "1")   # default off since the Brno run (test_real_data_fixes.py)
    monkeypatch.setenv("APIFY_PLACES", "0")          # default on; this test covers search, hashtags and TikTok
    runner = FakeRunner()
    p = ApifyProvider(token="test-token", runner=runner)
    q = DiscoveryQuery(keywords=["cukrárna"], hashtags=["#brnofood"], city="Brno", platforms=["instagram", "tiktok"])
    refs = await p.discover(q)
    by = {(r.platform, r.handle): r for r in refs}
    assert by[("instagram", "sample_cukrarka_brno")].found_via == ["search:cukrárna Brno"]
    assert by[("instagram", "sample_foodie_live_brno")].found_via == ["search:cukrárna Brno"]   # liveSearch item
    assert ("instagram", "sample_teen_baker") not in by                                  # bio age 15
    assert ("instagram", "sample_bruno_patisserie") not in by                            # no Brno in name / bio
    assert ("instagram", "sample_mega_related") not in by                                # nor its related junk
    assert by[("instagram", "sample_foodie_brno")].found_via == ["hashtag:brnofood", "place:Sample Kavárna Zelný trh"]
    assert ("instagram", "sample_prague_eater") not in by                                # coordinates outside Brno
    assert by[("instagram", "sample_no_location")].found_via == ["hashtag:brnofood"]     # unknown place is kept
    assert by[("instagram", "sample_text_place")].found_via == ["hashtag:brnofood", "place:Brno, Czech Republic"]
    assert by[("instagram", "sample_related_kavarna")].found_via == ["related:@sample_cukrarka_brno"]
    assert ("tiktok", "sample_cukrarka") in by and ("tiktok", "sample_tt_teen") not in by   # bio age 15
    assert ("tiktok", "sample_tt_empty") not in by                                       # 0-video note item
    assert all_live(refs)
    assert refs[0].found_via[0].startswith("search:")                                    # path order
    search = next(c for c in runner.calls if c[0] == ACT_IG_SEARCH)
    assert "liveSearch" not in search[1] and search[1]["searchType"] == "user"          # non-live since the Brno run
    scraper = [c for c in runner.calls if c[0] == ACT_IG_SCRAPER]
    assert len(scraper) == 1 and scraper[0][1]["resultsType"] == "details"
    assert sorted(scraper[0][1]["directUrls"]) == [ap.ig_location_url(i) for i in ("100000001", "100000003", "100000004")]
    tt = next(c for c in runner.calls if c[0] == ACT_TT)
    assert tt[2]["max_usd"] >= 0.5                                                       # minimalMaxTotalChargeUsd
    tag = next(c for c in runner.calls if c[0] == ACT_IG_HASHTAG)
    assert tag[2]["max_usd"] == pytest.approx(round(2 * 50 * 0.0026 + 0.05, 2))          # tied to the estimate
    assert not any("NEÚPLNÝ" in x["text"] for x in logs)                                # every sub-run complete
    assert ACT_IG_SEARCH in runner.actors() and not any(c[1].get("searchType") == "place" for c in runner.calls)
    assert any("odhad" in x["text"] for x in logs) and any("mimo 1" in x["text"] for x in logs)
    assert any("bez zmínky Brno" in x["text"] and x["text"].endswith(": 1") for x in logs)


async def test_provider_places_path_when_enabled(logs, monkeypatch):
    monkeypatch.setenv("APIFY_PLACES", "1")
    runner = FakeRunner()
    refs = await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["kavárna"], city="Brno", platforms=["instagram"]))
    by = {r.handle: r for r in refs}
    assert "place:Sample Kavárna Zelný trh" in by["sample_place_author"].found_via
    assert "sample_kavarna_business" not in by          # the venue's own account is not a creator path
    assert "sample_stale_place_author" not in by        # nested top post older than a year
    place_search = next(c for c in runner.calls if c[1].get("searchType") == "place")
    assert "liveSearch" not in place_search[1]
    assert ACT_IG_SCRAPER not in runner.actors()        # the Brno place already nests its posts: no re-fetch


async def test_provider_profiles_drop_minors_and_errors(logs):
    runner = FakeRunner()
    out = await ApifyProvider(token="t", runner=runner).profiles(
        ["sample_cukrarka_brno", "sample_missing", "sample_teen_profile"], "instagram")
    assert [p.handle for p in out] == ["sample_cukrarka_brno"]
    assert all_live(out, ACT_IG_PROFILE) and all_live(out[0].latest_posts, ACT_IG_PROFILE)
    assert runner.calls[0][1] == {"usernames": ["sample_cukrarka_brno", "sample_missing", "sample_teen_profile"],
                                  "includeAboutSection": False}
    assert len(runner.calls) == 1                       # the minor is not retried for empty latestPosts
    text = " ".join(x["text"] for x in logs)
    assert "mladší 18 let vynecháno: 1" in text and "@sample_missing" in text and "chybové položky vynechány: 1" in text


async def test_provider_profiles_batches_of_50():
    runner = FakeRunner()
    await ApifyProvider(token="t", runner=runner).profiles([f"h{i}" for i in range(120)], "instagram")
    assert [len(c[1]["usernames"]) for c in runner.calls if c[0] == ACT_IG_PROFILE][:3] == [50, 50, 20]


async def test_provider_posts_filter_since_in_code_and_dedupe(logs):
    runner = FakeRunner()
    out = await ApifyProvider(token="t", runner=runner).posts("sample_cukrarka_brno", "instagram",
                                                             datetime(2026, 9, 1, tzinfo=timezone.utc), limit=24)
    assert [p.id for p in out] == ["ig:post:SAMPLEd1", "ig:post:SAMPLEd2"]          # old one filtered, dupe removed
    assert [p.paid_partnership for p in out] == [True, None]                        # False untrusted until T6
    assert "onlyPostsNewerThan" not in runner.calls[0][1] and runner.calls[0][1]["dataDetailLevel"] == "detailedData"
    assert runner.calls[0][1]["skipPinnedPosts"] is True
    assert runner.calls[0][2]["max_usd"] == pytest.approx(round(2 * 24 * (0.0027 + 0.007) + 0.05, 2))  # music-data


async def test_provider_posts_trusts_false_label_only_when_switched_on(logs, monkeypatch):
    monkeypatch.setattr(ap, "TRUST_IG_FALSE_LABEL", True)
    out = await ApifyProvider(token="t", runner=FakeRunner()).posts("sample_cukrarka_brno", "instagram",
                                                                   datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert [p.paid_partnership for p in out] == [True, False]
    monkeypatch.setenv("APIFY_POST_DETAIL", "basicData")
    out = await ApifyProvider(token="t", runner=FakeRunner()).posts("sample_cukrarka_brno", "instagram",
                                                                   datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert [p.paid_partnership for p in out] == [True, None]                        # basicData never trusted


async def test_provider_comments_identity_free_and_keyed_by_requested_url(logs, monkeypatch):
    monkeypatch.setenv("APIFY_COMMENTS_SOURCE", "comments")
    url = "https://www.instagram.com/p/SAMPLEd1/"
    runner = FakeRunner()
    out = await ApifyProvider(token="t", runner=runner).comments([url], per_post=15)
    assert len(out) == 2 and {c.post_url for c in out} == {url}                      # ?img_index=1 paired by shortcode
    assert "real.person" not in dumped(out) and "another.person" not in dumped(out)
    assert runner.calls[0][0] == ACT_IG_COMMENT and runner.calls[0][1]["resultsLimit"] == 15
    tt_url = "https://www.tiktok.com/@sample_cukrarka/video/7400000000000000001"
    out2 = await ApifyProvider(token="t", runner=FakeRunner()).comments([tt_url])
    assert len(out2) == 1 and out2[0].post_url == tt_url and "real_commenter" not in dumped(out2)


async def test_provider_comments_from_latest_comments(logs, monkeypatch):
    monkeypatch.delenv("APIFY_COMMENTS_SOURCE", raising=False)
    assert ap.comments_source() == "latest"                                        # default since live T6
    runner = FakeRunner()
    out = await ApifyProvider(token="t", runner=runner).comments(["https://www.instagram.com/p/SAMPLEd1/"])
    assert runner.actors() == [ACT_IG_POST] and len(out) == 2 and "real.person" not in dumped(out)
    assert runner.calls[0][1]["skipPinnedPosts"] is False                          # direct URLs: keep pinned
    assert [c.text for c in out] == ["Vypadá skvěle! @user", "Kde to koupím?"]     # live keys text / timestamp
    assert all(c.created_at is not None for c in out)


async def test_comments_log_counts_over_limit_not_as_unsupported(logs, monkeypatch):
    monkeypatch.setenv("APIFY_COMMENTS_SOURCE", "comments")
    urls = [f"https://www.instagram.com/p/SAMPLEx{i}/" for i in range(45)] + ["https://example.com/a"]
    runner = FakeRunner()
    await ApifyProvider(token="t", runner=runner).comments(urls)
    assert len(runner.calls[0][1]["directUrls"]) == 40
    text = next(x["text"] for x in logs if x["text"].startswith("komentáře:"))
    assert "nepodporované URL: 1" in text and "vynecháno: 5" in text


async def test_cost_guard_skips_run_over_cap(logs, monkeypatch):
    monkeypatch.setenv("MAX_USD_PER_RUN", "0.001")
    runner = FakeRunner()
    assert await ApifyProvider(token="t", runner=runner).profiles(["a", "b"], "instagram") == []
    assert runner.calls == []
    assert any("MAX_USD_PER_RUN" in x["text"] for x in logs)


async def test_run_retries_once_then_succeeds(logs):
    runner = FakeRunner(fail_first=True)
    p = ApifyProvider(token="t", runner=runner)
    out = await p.news("cukrárna Brno")
    assert len(runner.calls) == 2 and len(out) == 2
    assert any("zkouším znovu" in x["text"] for x in logs)
    assert p.spent_estimate_usd == pytest.approx(2 * 10 * 0.004)                    # both attempts counted
    assert runner.calls[0][2]["max_usd"] == pytest.approx(0.13)                     # not the flat 3 USD


async def test_run_does_not_retry_an_api_4xx(logs):
    class ApiError(Exception):
        status_code = 402

    class Rejects:
        calls = 0

        async def __call__(self, *a, **k):
            Rejects.calls += 1
            raise ApiError("not enough credit")

    assert await ApifyProvider(token="t", runner=Rejects()).news("x") == []
    assert Rejects.calls == 1 and not any("zkouším znovu" in x["text"] for x in logs)


async def test_failed_sub_run_marks_discover_incomplete(logs, tmp_path):
    from app.sources.cache import CachedProvider, cache_key

    class FailsHashtag(FakeRunner):
        async def __call__(self, actor, run_input, **kw):
            if actor == ACT_IG_HASHTAG:
                self.calls.append((actor, run_input, kw))
                return RunResult(items=[], status="FAILED")
            return await super().__call__(actor, run_input, **kw)

    inner = ApifyProvider(token="t", runner=FailsHashtag())
    q = DiscoveryQuery(keywords=["cukrárna"], hashtags=["brnofood"], city="Brno", platforms=["instagram"])
    refs = await CachedProvider(inner, cache_dir=tmp_path, key_name="apify").discover(q)
    assert refs and inner.last_discover_incomplete == ["hashtag #brnofood: stav FAILED"]
    warn = next(x["text"] for x in logs if "NEÚPLNÝ" in x["text"])
    key = cache_key("discover", {"q": q}, "apify")
    assert (tmp_path / f"{key}.json").exists() and key in warn                    # names the file to delete
    ok = ApifyProvider(token="t", runner=FakeRunner())
    await ok.discover(q)
    assert ok.last_discover_incomplete == []


async def test_cost_guard_skip_marks_discover_incomplete(logs, monkeypatch):
    monkeypatch.setenv("MAX_USD_PER_RUN", "0.1")                                  # hashtag run (0.13) skipped
    p = ApifyProvider(token="t", runner=FakeRunner())
    await p.discover(DiscoveryQuery(keywords=["cukrárna"], hashtags=["brnofood"], city="Brno", platforms=["instagram"]))
    assert p.last_discover_incomplete == ["hashtag #brnofood: přeskočeno (odhad nad stropem)"]


async def test_place_without_nested_posts_fetches_place_item(logs, monkeypatch):
    """Live T4: a place URL returns ONE place item with nested posts[].user.username (resultsType posts and
    details alike, 1 result per place); search-scraper places that already nest posts are not re-fetched."""
    monkeypatch.setenv("APIFY_PLACES", "1")
    nested = {"location_id": "100000009", "name": "Sample Druhá", "lat": 49.2, "lng": 16.6,
              "posts": [{"code": "SAMPLEpp", "taken_at": 1791000000, "user": {"username": "sample_place_poster"}},
                        {"code": "SAMPLEold", "taken_at": 1600000000, "user": {"username": "sample_stale_poster"}}]}
    no_posts = {k: v for k, v in nested.items() if k != "posts"}               # posts key missing (9/42 live)

    class PlacePosts(FakeRunner):
        async def __call__(self, actor, run_input, **kw):
            if actor == ACT_IG_SEARCH and run_input["searchType"] == "place":
                self.calls.append((actor, run_input, kw))
                return RunResult(items=sample("ig_search_places.json")[:1] + [no_posts], status="SUCCEEDED")
            if actor == ACT_IG_SCRAPER:
                self.calls.append((actor, run_input, kw))
                return RunResult(items=[nested], status="SUCCEEDED")
            return await super().__call__(actor, run_input, **kw)

    runner = PlacePosts()
    refs = await ApifyProvider(token="t", runner=runner).discover(
        DiscoveryQuery(keywords=["kavárna"], city="Brno", platforms=["instagram"]))
    by = {r.handle: r for r in refs}
    assert by["sample_place_poster"].found_via == ["place:Sample Druhá"]
    assert "place:Sample Kavárna Zelný trh" in by["sample_place_author"].found_via   # nested in search, no re-fetch
    assert "sample_stale_poster" not in by                                             # older than a year
    scraper = [c for c in runner.calls if c[0] == ACT_IG_SCRAPER]
    assert len(scraper) == 1 and scraper[0][1]["directUrls"] == ["https://www.instagram.com/explore/locations/100000009/"]
    assert scraper[0][1]["resultsType"] == "details" and scraper[0][1]["resultsLimit"] == 1
    assert scraper[0][2]["max_items"] == 1                                             # 1 result per place


async def test_collabs_news_cross_platform(logs, monkeypatch):
    monkeypatch.delenv("APIFY_META_BRANDED", raising=False)
    runner = FakeRunner()
    p = ApifyProvider(token="t", runner=runner)
    assert await p.collabs("sample_cukrarka_brno", "instagram") == []             # cut after live T8: no run
    assert runner.calls == [] and any("APIFY_META_BRANDED" in x["text"] for x in logs)
    monkeypatch.setenv("APIFY_META_BRANDED", "1")
    ev = await p.collabs("sample_cukrarka_brno", "instagram")
    assert [e.brand for e in ev] == ["sample_brand"] and ev[0].post_id == "ig:post:SAMPLEbc1"
    assert any("řádky jiného tvůrce vynechány" in x["text"] and x["text"].endswith(": 2") for x in logs)
    assert any("chybové položky vynechány: 1 (no_items)" in x["text"] for x in logs)   # charged, not data
    assert await p.collabs("sample_cukrarka", "tiktok") == []
    prof = ap.map_ig_profile(sample("ig_profiles.json")[0], actor=ACT_IG_PROFILE, fetched_at=NOW)
    others = await p.find_cross_platform(prof)
    assert {(o.platform, o.handle) for o in others} == {("tiktok", "sample_cukrarka"), ("youtube", "samplecukrarka")}
    assert all_live(others)


async def test_provider_never_raises_on_runner_crash(logs):
    class Boom:
        async def __call__(self, *a, **k):
            raise RuntimeError("network down")

    p = ApifyProvider(token="t", runner=Boom())
    assert await p.profiles(["a"], "instagram") == []
    assert await p.discover(DiscoveryQuery(keywords=["x"], hashtags=["y"])) == []
    assert any("běh selhal" in x["text"] for x in logs)


async def test_write_through_cache_replays_without_token(tmp_path):
    from app.sources.cache import CachedProvider

    live = CachedProvider(ApifyProvider(token="t", runner=FakeRunner()), cache_dir=tmp_path)
    got = await live.profiles(["sample_cukrarka_brno"], "instagram")
    assert got and got[0].source.mode == "live"
    offline = CachedProvider(ApifyProvider(), cache_dir=tmp_path, read_only=True)
    again = await offline.profiles(["sample_cukrarka_brno"], "instagram")
    assert again[0].handle == "sample_cukrarka_brno" and again[0].source.mode == "cache"
    assert again[0].source.actor == ACT_IG_PROFILE and again[0].former_handles_count == 2


def test_call_kwargs_match_installed_client():
    from apify_client import ApifyClientAsync

    act = ApifyClientAsync(token="x").actor(ACT_IG_PROFILE)
    kw = ap.call_kwargs(act.call, run_input={"a": 1}, max_items=50, max_usd=3, timeout_s=420)
    params = inspect.signature(act.call).parameters
    assert set(kw) <= set(params)
    assert kw["max_total_charge_usd"] == Decimal("3") and kw["max_items"] == 50 and kw["logger"] is None
    assert kw["run_timeout"] == timedelta(seconds=420)
    # Free plan: 5 concurrent runs per account; 3.x waits for a slot instead of raising a 4xx (live 9. 10.)
    assert kw["wait_for_resources"] == timedelta(seconds=ap.WAIT_FOR_RESOURCES_S)
    assert ap._outer_timeout(420) > 420 + ap.WAIT_FOR_RESOURCES_S + 60

    def old_call(run_input=None, max_items=None, timeout_secs=None, wait_secs=None):  # 1.x-style
        return None

    assert ap.call_kwargs(old_call, run_input={}, max_items=1, max_usd=1, timeout_s=60) == {
        "run_input": {}, "max_items": 1, "timeout_secs": 60, "wait_secs": 120}


def test_model_extension_fields_roundtrip_and_stay_out_of_json_when_unset():
    from app.models import Post, Profile

    item = {**sample("ig_posts_detailed.json")[0], "sponsors": [{"username": "sample_brand"}], "isPinned": False}
    p = ap.map_ig_post(item, actor=ACT_IG_POST, fetched_at=NOW, trust_false_label=True)
    d = p.model_dump(mode="json")
    assert (d["location_id"], d["sponsors"], d["is_pinned"]) == ("100000001", ["sample_brand"], False)
    assert Post.model_validate(d) == p
    bare = ap.map_ig_post(sample("ig_posts_detailed.json")[3], actor=ACT_IG_POST, fetched_at=NOW).model_dump(mode="json")
    assert not {"location_id", "sponsors", "is_pinned"} & set(bare)            # fixtures stay byte-identical
    prof = ap.map_ig_profile(sample("ig_profiles.json")[2], actor=ACT_IG_PROFILE, fetched_at=NOW)
    assert "former_handles_count" not in prof.model_dump(mode="json")
    assert Profile.model_validate(prof.model_dump(mode="json")).former_handles_count is None


# ---------------------------------------------------------------------------------------------
# Live findings of 9. 10. 2026: charge accounting, music-data warning, YouTube posts
# ---------------------------------------------------------------------------------------------


def test_charged_usd_floors_a_stale_usage_total():
    """call() returns the Run before charges settle (usageTotalUsd 0.0 or partial); every item is charged."""
    items = [{"a": 1}] * 21 + [{"error": "not_found"}]
    stale = RunResult(items=items, status="SUCCEEDED", usd=0.0)
    assert ApifyProvider._charged_usd(ACT_IG_POST, stale, units=50, est=50 * 0.0027) == pytest.approx(22 * 0.0027)
    settled = RunResult(items=items, status="SUCCEEDED", usd=0.09)
    assert ApifyProvider._charged_usd(ACT_IG_POST, settled, units=50, est=50 * 0.0027) == pytest.approx(0.09)
    # tiktok-scraper with the CZ add-on: 24 results x (0.0037 + 0.0013) + start 0.001 = 0.121 (live T9)
    tt = RunResult(items=[{"a": 1}] * 24, status="SUCCEEDED", usd=None)
    est = 30 * (0.0037 + 0.0013) + 0.001
    assert ApifyProvider._charged_usd(ACT_TT, tt, units=30, est=est) == pytest.approx(0.121)
    assert ApifyProvider._charged_usd(ACT_TT, RunResult(items=[], usd=None), units=30, est=est) == 0.0


async def test_run_reports_floored_charge_and_music_only_when_charged(logs):
    class Stale(FakeRunner):
        async def __call__(self, actor, run_input, **kw):
            res = await super().__call__(actor, run_input, **kw)
            return RunResult(items=res.items, status="SUCCEEDED", usd=0.0,
                             events={"post": 4, "post-details": 4, "music-data": 0})

    p = ApifyProvider(token="t", runner=Stale())
    await p.posts("sample_cukrarka_brno", "instagram", datetime(2026, 9, 1, tzinfo=timezone.utc), limit=24)
    assert p.spent_reported_usd == pytest.approx(4 * 0.0027)                     # 4 items, not the stale 0.0
    text = next(x["text"] for x in logs if "eventy" in x["text"])
    assert "music-data" in text and "pozor: music-data" not in text               # key present with 0
    assert "účtováno asi 0,011 USD" in text


async def test_provider_posts_youtube_channel(logs):
    runner = FakeRunner()
    out = await ApifyProvider(token="t", runner=runner).posts("SampleCukrarka", "youtube",
                                                             datetime(2026, 9, 1, tzinfo=timezone.utc), limit=3)
    assert [p.id for p in out] == ["yt:video:SAMPLEyt001", "yt:video:SAMPLEyt002"]   # newest first
    assert [p.paid_partnership for p in out] == [True, None]
    assert runner.calls[0][0] == ACT_YT and runner.calls[0][1]["maxResults"] == 3
    assert runner.calls[0][2]["max_usd"] == pytest.approx(round(2 * 3 * 0.004 + 0.05, 2))
    assert all_live(out, ACT_YT)
