"""Round 4: deep vetting of finalists (only after the owner confirms). Never eliminates.

vet_candidate steps (emit vetting.progress {"candidate_id", "step"} for each):
  "posts"     provider.posts(handle, platform, since=now-180d) -> sensitive filter -> merge with latest_posts
  "cross"     provider.find_cross_platform(profile) -> compute.identity.match_identity
  "collabs"   compute.collabs.extract_collabs(posts, competitors=brief.competitors) + provider.collabs()
              -> merge_timeline
  "news"      provider.news(display_name / handle) -> sensitive filter (criminal etc. dropped, count only)
              -> llm.vetting.news_findings (allegation vs confirmed, namesake via identity.news_subject)
  "findings"  facts (each with >= 1 SourceRef), inferences (based_on fact ids), gaps (sources []):
              always include the gaps "audience age/gender/origin not estimated" and the
              not_checked items
  "claims"    llm.vetting.claims(profile, posts, collabs)
  "skeptic"   llm.vetting.skeptic(report)
  "questions" llm.vetting.questions(gaps)
  "outreach"  llm.vetting.outreach(brief, candidate)   (draft only, NEVER sent)
then report.ready. evaluate kinds: no_competitor_collab (recompute is_competitor from
brief.competitors via collabs.mark_competitors, since a goal change may change competitors; any hit ->
fail, value names brand + date), discloses_ads (count disclosed=False vs params.max_undisclosed;
all None -> unknown).
Every LLM step is wrapped: if it raises, the step falls back to a deterministic minimum (labeled via
record_mode("vetting", "fallback")) so a report is always produced. The extra posts fetched here are
used for the report only; they never change the round 1-3 metrics.
"""

from __future__ import annotations

import asyncio
from typing import Any
import contextlib
import unicodedata
from datetime import datetime, timedelta

from app.compute.collabs import (
    UNKNOWN_BRAND,
    collaboration_evidence,
    competitor_keys,
    normalize_brand,
    extract_collabs,
    mark_competitors,
    merge_timeline,
    undisclosed_posts,
)
from app.compute.identity import match_identity, match_news, news_subject
from app.compute.minors import is_minor
from app.compute.metrics import commercial_posts, engagement_spikes, interactions, local_signals, median, posts_per_week
from app.events import Emit
from app.llm import sensitive, vetting
from app.llm.client import bind_llm_modes, record_mode
from app.models import (
    Brief,
    Candidate,
    ClaimCheck,
    CollabEvidence,
    Criterion,
    CriterionResult,
    Finding,
    IdentityMatch,
    NewsFinding,
    NewsItem,
    Post,
    Profile,
    Report,
    ReportDiff,
    Run,
    SourceRef,
    VettingData,
    i18n,
    person_name,
    utcnow,
)
from app.rounds.common import (
    FORMAT_CS,
    FORMAT_EN,
    Outcome,
    actor_of,
    add_sensitive,
    count_modes,
    cs_plural,
    describe_modes,
    fmt_date,
    fmt_int,
    fmt_num,
    fmt_pct,
    log,
    logger,
    newest_first,
    param,
    post_ref,
    profile_refs,
    tr,
    unknown,
)
from app.rounds.r3_audience import comment_posts
from app.sources.base import SourceProvider

ROUND = 4
MAX_FINALISTS = 5
POSTS_SINCE_DAYS = 180


_STEP_LABELS = {
    "posts": i18n("starší posty", "older posts"),
    "cross": i18n("účty na jiných sítích", "other platforms"),
    "collabs": i18n("spolupráce", "collaborations"),
    "news": i18n("zprávy", "news"),
    "findings": i18n("zjištění", "findings"),
    "claims": i18n("tvrzení vs. záznam", "claims vs. record"),
    "skeptic": i18n("kontrola skeptika", "skeptic check"),
    "questions": i18n("otázky na schůzku", "meeting questions"),
    "outreach": i18n("koncept zprávy", "outreach draft"),
}


def _mode_of(objs: Any, provider: Any) -> str | None:
    """The data mode for a log line whose batch was empty: the objects' own source mode, else the
    provider's (an empty MOCK answer is still MOCK, an empty cache answer still cache)."""
    for o in objs or []:
        src = getattr(o, "source", None)
        if src is not None and getattr(src, "mode", None):
            return src.mode
    n = str(getattr(provider, "name", "") or "")
    if n.startswith("mock"):
        return "mock"
    if n.startswith("cache"):
        return "cache"
    return "live" if n else None
POSTS_LIMIT = 50
NEWS_LIMIT = 10
MAX_COLLAB_FACTS = 20
HOME_REGION = "CZ"   # market we search in (news region too); a cross-platform account elsewhere is a contradicting signal

# What we deliberately do not check, and why (shown in every report, i18n maps).
NOT_CHECKED: list[dict[str, str]] = [
    {"cs": "Věk, pohlaví a původ publika: z veřejných dat nejdou zjistit a neodhadujeme je.",
     "en": "Audience age, gender and origin: not knowable from public data; we do not estimate them."},
    {"cs": "Názory, víra, zdraví, politika ani povaha tvůrce: nekontrolujeme (čl. 9 GDPR).",
     "en": "Views, beliefs, health, politics or personality of the creator: not checked (GDPR Art. 9)."},
    {"cs": "Trestní věci: nebereme (čl. 10 GDPR).", "en": "Criminal matters: not processed (GDPR Art. 10)."},
    {"cs": "Pokuty za přestupky a správní delikty: nebereme (čl. 10 GDPR, C-439/19); zprávy o nich se vynechají jen jako počet.",
     "en": "Fines for offences and administrative delicts: not processed (GDPR Art. 10, C-439/19); such news is left out, count only."},
    {"cs": "Lajky jednotlivých lidí, fotky od jiných lidí, rozpoznávání tváří: nestahujeme.",
     "en": "Individual likes, photos posted by others, face recognition: not collected."},
    {"cs": "Soukromé statistiky účtu (dosah, demografie): má jen tvůrce, zeptejte se ho.",
     "en": "Private account insights (reach, demographics): only the creator has them; ask."},
]

TOPIC_CS_NOM: dict[str, str] = {
    "food": "jídlo", "recipes": "recepty", "restaurants_cafes": "restaurace a kavárny", "local_tips": "lokální tipy",
    "family": "rodina", "lifestyle": "lifestyle", "fitness": "fitness", "sport": "sport", "fashion": "móda",
    "beauty": "kosmetika", "travel": "cestování", "tech": "technologie", "gaming": "hry", "music": "hudba",
    "humor": "humor", "education": "vzdělávání", "other": "ostatní", "unclassified": "nezařazeno",
}
TOPIC_EN_NOM: dict[str, str] = {
    "food": "food", "recipes": "recipes", "restaurants_cafes": "restaurants & cafes", "local_tips": "local tips",
    "family": "family", "lifestyle": "lifestyle", "fitness": "fitness", "sport": "sport", "fashion": "fashion",
    "beauty": "beauty", "travel": "travel", "tech": "tech", "gaming": "gaming", "music": "music",
    "humor": "humor", "education": "education", "other": "other", "unclassified": "unclassified",
}
_KIND_CS = {"coauthor": "společný post", "mention": "zmínka", "tag": "označení v postu", "ad_hashtag": "reklamní hashtag",
            "discount_code": "slevový kód", "paid_label": "štítek placené spolupráce", "meta_branded": "Meta značkový obsah",
            "affiliate_link": "affiliate odkaz"}
_KIND_EN = {"coauthor": "co-authored post", "mention": "mention", "tag": "tag", "ad_hashtag": "ad hashtag",
            "discount_code": "discount code", "paid_label": "paid partnership label", "meta_branded": "Meta branded content",
            "affiliate_link": "affiliate link"}
_NEWS_LABEL_CS = {"allegation": "obvinění", "confirmed": "potvrzeno", "neutral": "neutrální"}
_NEWS_LABEL_EN = {"allegation": "allegation", "confirmed": "confirmed", "neutral": "neutral"}

_ALLEGATION_WORDS = ("obvin", "udajn", "podezr", "tvrdi", "stezuj", "kritik", "vysetr", "allegedly", "accused",
                     "claims", "complain", "investigat")
# "confirmed" = an official statement / announcement; fines and rulings are Art. 10 and filtered out before storage.
_CONFIRMED_WORDS = ("potvrdil", "potvrzen", "oficialne oznamil", "oficialne predstavil", "confirmed", "officially announced")


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------

def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _merge_posts(*groups: list[Post]) -> list[Post]:
    by_id: dict[str, Post] = {}
    for g in groups:
        for p in g:
            by_id.setdefault(p.id, p)
    return newest_first(by_id.values())


def _relevance(run: Run, kinds: list[str]) -> list[str]:
    return [c.id for c in run.criteria.criteria if c.kind in kinds]


def fallback_news_label(item: NewsItem) -> str:
    text = _fold(f"{item.title} {item.snippet}")
    if any(w in text for w in _CONFIRMED_WORDS):
        return "confirmed"
    if any(w in text for w in _ALLEGATION_WORDS):
        return "allegation"
    return "neutral"


def news_attribution(item: NewsItem, subject: str | None) -> tuple[str, str]:
    """("píše <outlet>", "<outlet> reports"), each with the namesake-risk mark when the article
    names only the creator's name (subject "uncertain")."""
    unsure = subject == "uncertain"
    return (f"píše {item.outlet}" + (vetting.UNCERTAIN_MARK if unsure else ""),
            f"{item.outlet} reports" + (vetting.UNCERTAIN_MARK_EN if unsure else ""))


def _fallback_news(items: list[NewsItem], lang: str) -> list[NewsFinding]:
    return [NewsFinding(item=it, label=fallback_news_label(it),  # type: ignore[arg-type]
                        attribution=(f"{it.outlet} reports" if lang == "en" else f"píše {it.outlet}"))
            for it in items]


_GAP_QUESTIONS: dict[str, dict[str, str]] = {
    "g:demographics": i18n("Můžete nám poslat statistiky publika (věk, pohlaví, města) z aplikace?",
                           "Could you share your audience statistics (age, gender, cities) from the app?"),
    "g:reach": i18n("Jaký mají vaše posty a stories obvykle dosah?", "What reach do your posts and stories usually get?"),
    "g:pricing": i18n("Jak si představujete spolupráci a cenu?", "How do you see the collaboration and its price?"),
    "g:meta_branded": i18n("Se kterými značkami jste v posledním roce spolupracoval(a)?",
                           "Which brands have you worked with in the past year?"),
    "g:paid_label": i18n("Jak označujete placené spolupráce?", "How do you label paid collaborations?"),
    "g:exclusivity": i18n("Máte teď s někým exkluzivitu nebo konkurenční doložku?",
                          "Do you currently have an exclusivity or non-compete agreement with anyone?"),
}


def _fallback_questions(gaps: list[Finding]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = [_GAP_QUESTIONS["g:demographics"]]
    for g in gaps:
        q = _GAP_QUESTIONS.get(g.id)
        if q and q not in out:
            out.append(q)
    if _GAP_QUESTIONS["g:exclusivity"] not in out:
        out.append(_GAP_QUESTIONS["g:exclusivity"])
    return out


# ---------------------------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------------------------

def build_findings(
    run: Run,
    candidate: Candidate,
    posts: list[Post],
    timeline: list[CollabEvidence],
    provider_collabs: list[CollabEvidence],
    identity: list[IdentityMatch],
    namesakes: list[IdentityMatch],
    news: list[NewsFinding],
    news_subjects: dict[str, str],
    *,
    identity_i18n: dict[str, list[IdentityMatch]] | None = None,
    namesakes_i18n: dict[str, list[IdentityMatch]] | None = None,
) -> list[Finding]:
    """Facts carry >= 1 SourceRef, inferences cite fact ids in based_on, gaps have no sources.
    ``identity_i18n`` / ``namesakes_i18n`` ({"cs": [...], "en": [...]}, aligned with ``identity`` /
    ``namesakes``) give the signal texts per language; without them both use the brief language."""
    brief = run.criteria.brief
    profile = candidate.profile
    assert profile is not None
    m = candidate.metrics
    city = brief.city or run.criteria.discovery.city
    out: list[Finding] = []

    def fact(fid: str, cs: str, en: str, sources: list[SourceRef], section: str, kinds: list[str]) -> str | None:
        if not sources:
            return None
        out.append(Finding(id=fid, kind="fact", text=i18n(cs, en), sources=sources, section=section,  # type: ignore[arg-type]
                           relevance=_relevance(run, kinds)))
        return fid

    def inference(fid: str, cs: str, en: str, based_on: list[str | None], section: str, kinds: list[str]) -> None:
        basis = [b for b in based_on if b]
        if not basis:
            return
        out.append(Finding(id=fid, kind="inference", text=i18n(cs, en), sources=[], based_on=basis,
                           section=section, relevance=_relevance(run, kinds)))  # type: ignore[arg-type]

    def gap(fid: str, cs: str, en: str, section: str, kinds: list[str]) -> None:
        out.append(Finding(id=fid, kind="gap", text=i18n(cs, en), sources=[], section=section,  # type: ignore[arg-type]
                           relevance=_relevance(run, kinds)))

    psrc = [profile.source]
    # content facts rest on the posts, not on the bio: cite posts (no bio quote under "Formats: ...")
    def _content_src(ps: list) -> list:
        refs = [p.source.model_copy(update={"quote": None}) for p in sorted(ps, key=lambda p: p.created_at, reverse=True)[:5]]
        return refs or [profile.source.model_copy(update={"quote": None})]

    csrc = _content_src(list(profile.latest_posts))

    # --- profile
    if profile.followers is not None:
        extra_cs = f", {fmt_int(profile.posts_count, 'cs')} postů celkem" if profile.posts_count is not None else ""
        extra_en = f", {fmt_int(profile.posts_count, 'en')} posts in total" if profile.posts_count is not None else ""
        fact("f:followers", f"{fmt_int(profile.followers, 'cs')} sledujících{extra_cs}",
             f"{fmt_int(profile.followers, 'en')} followers{extra_en}", psrc, "profile", ["followers_range"])
    if profile.business_category:
        fact("f:category", f"Kategorie profilu: {profile.business_category}",
             f"Profile category: {profile.business_category}", psrc, "profile", ["not_brand_account"])

    # --- content (from the round 1-3 posts, so it matches the criteria results)
    if m and m.topic_counts:
        total = sum(m.topic_counts.values())
        top = sorted(m.topic_counts.items(), key=lambda kv: -kv[1])  # "unclassified" shows as "nezařazeno"
        cs = ", ".join(f"{fmt_pct(n / total, 'cs')} {TOPIC_CS_NOM.get(t, t)}" for t, n in top)
        en = ", ".join(f"{fmt_pct(n / total, 'en')} {TOPIC_EN_NOM.get(t, t)}" for t, n in top)
        fact("f:topics", f"Témata posledních {total} postů: {cs}", f"Topics of the last {total} posts: {en}",
             csrc, "content", ["topic_share"])
    if m and m.formats:
        cs = ", ".join(f"{n} {FORMAT_CS.get(f, f)}" for f, n in sorted(m.formats.items(), key=lambda kv: -kv[1]))
        en = ", ".join(f"{n} {FORMAT_EN.get(f, f)}" for f, n in sorted(m.formats.items(), key=lambda kv: -kv[1]))
        fact("f:formats", f"Formáty: {cs}", f"Formats: {en}", csrc, "content", ["formats"])
    ppw = posts_per_week(posts)
    if ppw is not None:
        oldest = min(p.created_at for p in posts)
        fact("f:frequency",
             f"{len(posts)} {cs_plural(len(posts), 'post', 'posty', 'postů')} od {fmt_date(oldest, 'cs')}, zhruba {fmt_num(ppw, 'cs')} postu týdně",
             f"{len(posts)} posts since {fmt_date(oldest, 'en')}, about {fmt_num(ppw, 'en')} posts per week",
             _content_src(posts), "content", ["post_frequency"])
    com = commercial_posts(posts)
    f_commercial = None
    if posts:
        share = len(com) / len(posts)
        f_commercial = fact(
            "f:commercial",
            f"Komerční nasycenost: {len(com)} ze všech {len(posts)} postů od {fmt_date(min(p.created_at for p in posts), 'cs')} "
            f"({fmt_pct(share, 'cs')}) má štítek spolupráce, reklamní hashtag nebo slevový kód",
            f"Commercial saturation: {len(com)} of all {len(posts)} posts since {fmt_date(min(p.created_at for p in posts), 'en')} "
            f"({fmt_pct(share, 'en')}) carry a partnership label, ad hashtag or discount code",
            [post_ref(p) for p in com[:5]] or psrc, "content", ["max_commercial_share"])
        if share > 0.3:
            inference("i:commercial",
                      "Vysoký podíl komerčních postů může snižovat důvěru publika v další doporučení.",
                      "A high share of commercial posts may lower the audience's trust in further recommendations.",
                      [f_commercial], "content", ["max_commercial_share"])

    # --- engagement (public signals only)
    if m and m.engagement_rate is not None:
        ml = fmt_int(m.median_likes, "cs") if m.median_likes is not None else "?"
        mc = fmt_int(m.median_comments, "cs") if m.median_comments is not None else "?"
        fact("f:engagement",
                     f"Medián interakcí {fmt_pct(m.engagement_rate, 'cs', 1)} sledujících na post (medián {ml} lajků, {mc} komentářů)",
                     f"Median interactions {fmt_pct(m.engagement_rate, 'en', 1)} of followers per post (median {ml} likes, {mc} comments)",
                     psrc + [post_ref(p) for p in newest_first(candidate.profile.latest_posts)[:3]],
                     "engagement", ["min_engagement"])
    f_cs = None
    csrc = [post_ref(p) for p in comment_posts(candidate)]
    if m and m.cs_comment_share is not None:
        f_cs = fact("f:cs_comments", f"{fmt_pct(m.cs_comment_share, 'cs')} komentářů česky ({m.comments_analyzed} analyzováno)",
                    f"{fmt_pct(m.cs_comment_share, 'en')} of comments in Czech ({m.comments_analyzed} analyzed)",
                    csrc or psrc, "engagement", ["cs_comment_share"])
    if m and m.generic_comment_share is not None:
        f_gen = fact("f:generic_comments",
                     f"{fmt_pct(m.generic_comment_share, 'cs')} komentářů je jen emoji nebo obecné fráze",
                     f"{fmt_pct(m.generic_comment_share, 'en')} of comments are emoji-only or generic phrases",
                     csrc or psrc, "engagement", ["max_generic_comments"])
        if m.generic_comment_share > 0.4:
            inference("i:generic",
                      "Hodně obecných komentářů může znamenat nakoupenou aktivitu, ale i jen krátké reakce fanoušků. Je to signál, ne verdikt.",
                      "Many generic comments can mean bought engagement, or just short reactions from fans. A signal, not a verdict.",
                      [f_gen], "engagement", ["max_generic_comments"])
    f_local = None
    if city:
        sig = local_signals(profile, list(profile.latest_posts), city)
        if sig:
            n = len(sig)
            f_local = fact("f:local",
                           f"{n} {cs_plural(n, 'lokální signál', 'lokální signály', 'lokálních signálů')} pro {city} (místo, popisek, hashtag, bio)",
                           f"{n} local {'signal' if n == 1 else 'signals'} for {city} (location, caption, hashtag, bio)",
                           sig[:5], "engagement", ["local_signal"])
    if f_local and f_cs and m and m.cs_comment_share is not None and m.cs_comment_share >= 0.5:
        inference("i:local",
                  f"Většina komentářů je v češtině a část obsahu má vazbu na {city} (jazyk a místo obsahu, ne původ publika).",
                  f"Most comments are in Czech and part of the content is tied to {city} (language and content location, not audience origin).",
                  [f_local, f_cs], "engagement", ["local_signal", "cs_comment_share"])
    spike_ids = engagement_spikes(list(profile.latest_posts))
    spike_facts: list[str | None] = []
    med = median([float(i) for i in (interactions(p) for p in profile.latest_posts) if i is not None])
    by_id = {p.id: p for p in profile.latest_posts}
    for pid in spike_ids[:3]:
        p = by_id[pid]
        ratio = (interactions(p) or 0) / med if med else 0
        spike_facts.append(fact(f"f:spike:{pid}",
                                f"Post z {fmt_date(p.created_at, 'cs')} má {fmt_num(ratio, 'cs')}× víc interakcí než medián",
                                f"Post from {fmt_date(p.created_at, 'en')} has {fmt_num(ratio, 'en')}x the median interactions",
                                [post_ref(p)], "engagement", ["min_engagement"]))
    if spike_facts:
        inference("i:spikes",
                  "Některé posty mají výrazně víc interakcí než ostatní: může jít o virální obsah i o placenou propagaci.",
                  "Some posts get far more interactions than the rest: viral content or paid promotion are both possible.",
                  spike_facts, "engagement", ["min_engagement"])
    gap("g:demographics",
        "Věk, pohlaví a původ publika z veřejných dat nezjistíme a neodhadujeme je; statistiky má jen tvůrce.",
        "Audience age, gender and origin cannot be known from public data and we do not estimate them; only the creator has these statistics.",
        "engagement", ["cs_comment_share", "local_signal"])
    gap("g:reach", "Dosah postů a stories není veřejný.", "Post and story reach is not public.", "engagement", ["min_engagement"])
    if not m or m.comments_analyzed == 0:
        gap("g:comments", "Komentáře jsme neanalyzovali (nejsou dostupné).", "Comments were not analyzed (not available).",
            "engagement", ["cs_comment_share", "max_generic_comments"])

    # --- collabs (rebuilt on a goal change too, see refresh_for_brief)
    out.extend(collab_findings(run, timeline, provider_collabs))

    # --- identity
    plat_cs = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "web": "web"}

    def alt(lists: dict[str, list[IdentityMatch]] | None, base: list[IdentityMatch], i: int, lg: str) -> IdentityMatch:
        if lists and len(lists.get(lg) or []) == len(base):
            return lists[lg][i]
        return base[i]

    for i, im in enumerate(identity):
        if im.platform == "news":
            continue
        srcs = [s.source for s in im.signals if s.source is not None]
        sig_cs = "; ".join(s.signal for s in alt(identity_i18n, identity, i, "cs").signals)
        sig_en = "; ".join(s.signal for s in alt(identity_i18n, identity, i, "en").signals)
        name = f"{plat_cs.get(im.platform, im.platform)} @{im.handle}"
        if im.status == "matched":
            fact(f"f:identity:{im.platform}:{im.handle}", f"{name}: stejný tvůrce ({sig_cs})",
                 f"{name}: same creator ({sig_en})", srcs, "identity", [])
        elif im.status == "uncertain":
            fact(f"f:identity:{im.platform}:{im.handle}", f"{name}: nejisté, jestli jde o stejného tvůrce ({sig_cs})",
                 f"{name}: uncertain whether this is the same creator ({sig_en})", srcs, "identity", [])
        else:
            # what we observed is the fact; "a different account" is our conclusion from it
            fid = fact(f"f:identity:{im.platform}:{im.handle}", f"{name}: podobný účet, signály: {sig_cs}",
                       f"{name}: a similar account; signals: {sig_en}", srcs, "identity", [])
            inference(f"i:lookalike:{im.platform}:{im.handle}",
                      f"Nejspíš jiný účet než tvůrcův ({name}); do reportu ho nebereme.",
                      f"Most likely a different account ({name}), not the creator's; not used.", [fid], "identity", [])
    if not any(im.status == "matched" for im in identity if im.platform != "news"):
        gap("g:cross_platform", "Stejného tvůrce na jiné síti jsme jednoznačně nenašli.",
            "We did not find the same creator on another network with certainty.", "identity", [])

    # --- news (namesakes first, then the ones that may be about the creator)
    for i, im in enumerate(namesakes):
        s = im.signals[0]
        s_cs = alt(namesakes_i18n, namesakes, i, "cs").signals[0].signal
        s_en = alt(namesakes_i18n, namesakes, i, "en").signals[0].signal
        fid = fact(f"f:namesake:{im.handle}", f"Článek zmiňuje stejné jméno v jiném kontextu: {s_cs}",
                   f"An article mentions the same name in another context: {s_en}",
                   [s.source] if s.source else [], "identity", [])
        inference(f"i:namesake:{im.handle}", "Nejspíš jde o jmenovce, ne o tohoto tvůrce; článek do hodnocení nebereme.",
                  "Most likely a namesake, not this creator; the article is not used.", [fid], "identity", [])
    for nf in news:
        it = nf.item
        attr_cs, attr_en = news_attribution(it, news_subjects.get(it.id))
        fid = fact(f"f:news:{it.id}",
                   f"{attr_cs}: „{it.title}“ ({_NEWS_LABEL_CS.get(nf.label, nf.label)}, {fmt_date(it.published_at, 'cs')})",
                   f"{attr_en}: \"{it.title}\" ({_NEWS_LABEL_EN.get(nf.label, nf.label)}, {fmt_date(it.published_at, 'en')})",
                   [it.source], "news", [])
        if news_subjects.get(it.id) == "uncertain":
            inference(f"i:news_subject:{it.id}",
                      "Článek zmiňuje jen jméno, ne účet tvůrce: nemusí jít o stejnou osobu.",
                      "The article mentions only the name, not the creator's account: it may be a different person.",
                      [fid], "news", [])
    if not news:
        n_aside = sum(1 for v in news_subjects.values() if v == "rejected")   # == counts["news_set_aside"]
        if n_aside:
            gap("g:news", f"Zprávy o tvůrci jsme nenašli: {n_aside} {cs_plural(n_aside, 'nalezená zpráva je', 'nalezené zprávy jsou', 'nalezených zpráv je')} "
                          f"o něčem jiném, dali jsme {'ji' if n_aside == 1 else 'je'} stranou (neznamená to, že zprávy o tvůrci neexistují).",
                f"We found no news about the creator: {n_aside} news {'result is' if n_aside == 1 else 'results are'} about "
                f"something else and {'was' if n_aside == 1 else 'were'} set aside (that does not mean there is none).", "news", [])
        else:
            gap("g:news", "Zprávy o tvůrci jsme nenašli (neznamená to, že neexistují).",
                "We found no news about the creator (that does not mean there is none).", "news", [])
    return out


def collab_findings(run: Run, timeline: list[CollabEvidence], provider_collabs: list[CollabEvidence]) -> list[Finding]:
    """Collab section: one fact per post (all evidence kinds of that post together) or per evidence
    without a post (e.g. a Meta record), the competitor / unlabeled inferences and the collab gaps.
    Depends on brief.competitors, so a goal change rebuilds it."""
    brief = run.criteria.brief
    out: list[Finding] = []

    def fact(fid: str, cs: str, en: str, sources: list[SourceRef], kinds: list[str]) -> str | None:
        if not sources:
            return None
        out.append(Finding(id=fid, kind="fact", text=i18n(cs, en), sources=sources, section="collabs",
                           relevance=_relevance(run, kinds)))
        return fid

    def inference(fid: str, cs: str, en: str, based_on: list[str | None], kinds: list[str]) -> None:
        basis = [b for b in based_on if b]
        if basis:
            out.append(Finding(id=fid, kind="inference", text=i18n(cs, en), sources=[], based_on=basis,
                               section="collabs", relevance=_relevance(run, kinds)))

    def gap(fid: str, cs: str, en: str, kinds: list[str]) -> None:
        out.append(Finding(id=fid, kind="gap", text=i18n(cs, en), sources=[], section="collabs",
                           relevance=_relevance(run, kinds)))

    keys = competitor_keys(brief.competitors)
    collab = collaboration_evidence(timeline)
    collab_ids = {e.id for e in collab}
    groups: dict[str, list[CollabEvidence]] = {}
    for e in timeline:
        groups.setdefault(e.post_id or e.id, []).append(e)
    collab_fact_ids: dict[str, str] = {}   # evidence id -> fact id
    for key, evs in list(groups.items())[:MAX_COLLAB_FACTS]:
        first = evs[0]
        brands = _display_brands(evs)
        brand_cs = ", ".join(brands) or "značka neuvedena"
        brand_en = ", ".join(brands) or "brand not named"
        kinds_cs = ", ".join(dict.fromkeys(_KIND_CS.get(e.kind, e.kind) for e in evs))
        kinds_en = ", ".join(dict.fromkeys(_KIND_EN.get(e.kind, e.kind) for e in evs))
        disclosed = True if any(e.disclosed is True for e in evs) else (False if any(e.disclosed is False for e in evs) else None)
        mention_only = not any(e.id in collab_ids for e in evs)
        if mention_only:
            disc_cs, disc_en = "jen zmínka, bez známek spolupráce", "mention only, no sign of a collaboration"
        else:
            disc_cs = {True: "označeno jako reklama", False: "označení reklamy jsme nenašli", None: "štítek platformy neznámý"}[disclosed]
            disc_en = {True: "labeled as an ad", False: "no ad label found", None: "platform label unknown"}[disclosed]
        is_comp = any(e.is_competitor for e in evs)
        fid = fact(f"f:collab:{key}",
                   f"{fmt_date(first.date, 'cs')}: {brand_cs}{', konkurent' if is_comp else ''} ({kinds_cs}), {disc_cs}",
                   f"{fmt_date(first.date, 'en')}: {brand_en}{', competitor' if is_comp else ''} ({kinds_en}), {disc_en}",
                   [first.source], ["no_competitor_collab", "discloses_ads", "max_commercial_share"])
        if fid:
            for e in evs:
                collab_fact_ids[e.id] = fid
    comp = [e for e in collab if e.is_competitor]
    if comp and keys:
        brands = _brand_names(comp)
        last = max((e.date for e in comp if e.date), default=None)
        inference("i:competitor",
                  f"Tvůrce spolupracoval s konkurencí ({', '.join(brands)}), naposledy {fmt_date(last, 'cs')}; doporučení vaší firmy by teď mohlo působit méně věrohodně.",
                  f"The creator worked with a competitor ({', '.join(brands)}), most recently {fmt_date(last, 'en')}; recommending your business now might seem less credible.",
                  list(dict.fromkeys(collab_fact_ids.get(e.id) for e in comp)), ["no_competitor_collab"])
    und = undisclosed_posts(timeline)
    if und:
        inference("i:undisclosed",
                  f"U {len(und)} {cs_plural(len(und), 'postu', 'postů', 'postů')} se značkou a se známkou spolupráce (společný post, slevový kód, odkaz) jsme nenašli označení reklamy: může jít o neplacenou zmínku i o neoznačenou spolupráci.",
                  f"For {len(und)} {'post' if len(und) == 1 else 'posts'} with a brand and a collaboration signal (joint post, discount code, link) we found no ad label: it may be an unpaid mention or an unlabeled collaboration.",
                  list(dict.fromkeys(collab_fact_ids.get(e.id) for e in und)), ["discloses_ads"])
    if not any(e.kind == "meta_branded" for e in provider_collabs):
        gap("g:meta_branded",
            "Data z Meta knihovny značkového obsahu nemáme (pokrytí ČR je nejisté); spolupráce známe jen z postů.",
            "No data from Meta's branded content library (Czech coverage is uncertain); collaborations are known from posts only.",
            ["no_competitor_collab", "discloses_ads"])
    unknown_label = sorted({e.post_id for e in collab if e.disclosed is None and e.post_id})
    if unknown_label:
        n = len(unknown_label)
        gap("g:paid_label",
            f"U {n} {cs_plural(n, 'postu', 'postů', 'postů')} se značkou platforma nehlásí, zda má štítek placené spolupráce.",
            f"For {n} {'post' if n == 1 else 'posts'} with a brand the platform does not say whether it has a paid-partnership label.",
            ["discloses_ads"])
    gap("g:pricing", "Cena a podmínky spolupráce nejsou veřejné.", "Price and terms of a collaboration are not public.", [])
    return out


def _display_brands(evs: list[CollabEvidence]) -> list[str]:
    """One name per brand ("ProteoMax" and "proteomax" are one brand; the written name wins)."""
    by_key: dict[str, str] = {}
    for e in evs:
        if not e.brand or e.brand == UNKNOWN_BRAND:
            continue
        key = normalize_brand(e.brand_handle or e.brand)
        if key not in by_key or (by_key[key].islower() and not e.brand.islower()):
            by_key[key] = e.brand
    return list(by_key.values())


_COLLAB_SECTION_IDS = ("f:collab:", "i:competitor", "i:undisclosed", "g:meta_branded", "g:paid_label", "g:pricing")


def refresh_for_brief(run: Run, candidate: Candidate) -> None:
    """After a goal change (no fetch, no LLM): re-mark competitors in the timeline, rebuild the collab
    findings (competitor / unlabeled inferences) and the outreach draft from the deterministic
    template for the new brief. Claims, news and identity do not depend on the brief and stay;
    ``report.vetted_for`` keeps the goal the deep check was run for, so the drawer can say so."""
    rep = candidate.report
    if rep is None:
        return
    brief = run.criteria.brief
    rep.collab_timeline = mark_competitors(rep.collab_timeline, brief.competitors)
    has_meta = [e for e in rep.collab_timeline if e.kind == "meta_branded"]
    new = collab_findings(run, rep.collab_timeline, has_meta)
    idx = next((i for i, f in enumerate(rep.findings) if f.id.startswith(_COLLAB_SECTION_IDS)), len(rep.findings))
    kept = [f for f in rep.findings if not f.id.startswith(_COLLAB_SECTION_IDS)]
    idx = min(idx, len(kept))
    rep.findings = kept[:idx] + new + kept[idx:]
    try:
        rep.outreach_draft = vetting.outreach_template(brief, candidate)  # DRAFT only, never sent
    except Exception:
        logger.exception("outreach template failed for %s", candidate.id)


# ---------------------------------------------------------------------------------------------
# vet_candidate / prepare
# ---------------------------------------------------------------------------------------------

@contextlib.contextmanager
def _probe_mode():
    """Capture what one LLM step records with record_mode ("vetting" -> llm | fallback | mixed)."""
    probe: dict[str, str] = {}
    with bind_llm_modes(probe):
        yield probe


def _replay_mode(probe: dict[str, str]) -> None:
    for task, mode in probe.items():
        if mode == "mixed":
            record_mode(task, "llm")
            record_mode(task, "fallback")
        elif mode in ("llm", "fallback"):
            record_mode(task, mode)  # type: ignore[arg-type]


def _step_mode(probe: dict[str, str], default: str = "llm") -> str:
    """Mode of one step: what it recorded, else ``default`` (stand-in functions record nothing)."""
    m = probe.get(vetting.TASK)
    return "llm" if m == "mixed" else (m or default)


def _skeptic_raw(before: Report, after: Report) -> list[dict]:
    """What the LLM skeptic changed, as replayable notes (apply_llm_skeptic input)."""
    raw: list[dict] = []
    kinds = {f.id: f.kind for f in before.findings}
    for f in after.findings:
        if kinds.get(f.id) == "inference" and f.kind == "gap":
            raw.append({"ref_id": f.id, "action": "downgrade_to_gap", "note_cs": "", "note_en": ""})
    conf = {c.id: c.confidence for c in before.claims}
    order = ("low", "medium", "high")
    for c in after.claims:
        prev = conf.get(c.id)
        if prev in order and c.confidence in order and order.index(c.confidence) < order.index(prev):
            raw.append({"ref_id": c.id, "action": "lower_confidence", "note_cs": "", "note_en": ""})
    old = [dict(n) for n in before.skeptic_notes]
    for n in after.skeptic_notes:
        if dict(n) not in old and (n.get("cs") or n.get("en")):
            raw.append({"ref_id": "", "action": "note", "note_cs": n.get("cs", ""), "note_en": n.get("en", "") or n.get("cs", "")})
    return raw


def _anchor_of(run: Run):
    subject = getattr(run, "subject", None)
    if getattr(run, "mode", "discovery") == "subject" and subject is not None:
        return subject.anchor
    return None


async def vet_candidate(run: Run, candidate: Candidate, provider: SourceProvider, emit: Emit) -> Report:
    """Fetch once (posts, cross-platform, collabs, news), keep the raw inputs in
    ``candidate.vetting_data``, run the LLM steps (news labels, claims, skeptic, questions, outreach;
    at most 5 requests, each with a deterministic fallback) and render the report for the current goal
    (rounds.report.render_report). A goal change re-renders from vetting_data: no fetch, no LLM."""
    from app.rounds.report import brief_key, render_report

    brief = run.criteria.brief
    lang = brief.lang
    cid = candidate.id
    profile = candidate.profile
    now = utcnow()
    anchor = _anchor_of(run)

    async def step(name: str) -> None:
        # "label": a readable step name for the UI / screen readers (the key stays for the code)
        await emit("vetting.progress", {"candidate_id": cid, "step": name, "label": _STEP_LABELS.get(name, i18n(name, name))})

    # Re-vetting (e.g. after a goal change) replaces this round's sensitive count instead of adding
    # to it, so the same filtered item is never counted twice.
    if candidate.sensitive_vetting:
        candidate.sensitive_filtered = max(0, candidate.sensitive_filtered - candidate.sensitive_vetting)
        candidate.sensitive_vetting = 0

    async def add_r4(dropped: int) -> None:
        if dropped > 0:
            candidate.sensitive_vetting += dropped
        await add_sensitive(run, candidate, emit, dropped)

    if profile is None:
        report = Report(candidate_id=cid, findings=[], claims=[], collab_timeline=[], news=[], identity=[],
                        questions=_fallback_questions([]), outreach_draft=None,
                        not_checked=[dict(x) for x in NOT_CHECKED], skeptic_notes=[], sensitive_filtered=candidate.sensitive_filtered)
        candidate.report = report
        await emit("report.ready", {"candidate_id": cid})
        return report

    # posts ---------------------------------------------------------------------------------
    await step("posts")
    extra = await provider.posts(profile.handle, profile.platform, since=now - timedelta(days=POSTS_SINCE_DAYS), limit=POSTS_LIMIT)
    batch = count_modes(run, extra)
    latest = list(profile.latest_posts)
    if latest:
        # Posts inside the round-1 window were already filtered (and counted) in round 1. A post in
        # that window that is not among latest_posts is one round 1 dropped: skip it, do not recount.
        latest_ids = {p.id for p in latest}
        lo, hi = min(p.created_at for p in latest), max(p.created_at for p in latest)
        extra = [p for p in extra if p.id not in latest_ids and not (lo <= p.created_at <= hi)]
    kept_extra: list[Post] = []
    dropped = 0
    if extra:
        kept_extra, dropped = await sensitive.filter_posts(extra)
    await add_r4(dropped)
    sensitive_dropped = dropped
    posts = _merge_posts(list(profile.latest_posts), kept_extra)
    mode, suffix = describe_modes(batch)
    window_start = now - timedelta(days=POSTS_SINCE_DAYS)
    in_window = sum(1 for p in posts if p.created_at >= window_start)
    if in_window == len(posts):
        p_cs = f"@{profile.handle}: {len(posts)} postů za {POSTS_SINCE_DAYS} dní{suffix}"
        p_en = f"@{profile.handle}: {len(posts)} {'post' if len(posts) == 1 else 'posts'} over {POSTS_SINCE_DAYS} days{suffix}"
    else:
        # older posts from the profile are still used (labeled), but the line must not claim they are recent
        older = len(posts) - in_window
        p_cs = (f"@{profile.handle}: {in_window} postů za {POSTS_SINCE_DAYS} dní, k tomu {older} starších z profilu "
                f"(použito {len(posts)}){suffix}")
        p_en = (f"@{profile.handle}: {in_window} {'post' if in_window == 1 else 'posts'} in the last {POSTS_SINCE_DAYS} days, "
                f"plus {older} older {'post' if older == 1 else 'posts'} from the profile ({len(posts)} used){suffix}")
    await log(run, emit, tr(run, p_cs, p_en),
              actor=actor_of(extra, None) or actor_of(posts, provider.name), mode=mode or _mode_of(posts, provider))

    # cross-platform -------------------------------------------------------------------------
    await step("cross")
    others = [o for o in await provider.find_cross_platform(profile) if not is_minor(o)]
    count_modes(run, others)
    cleaned: list[Profile] = []
    for o in others:
        o2, d = await sensitive.filter_profile(o)
        await add_r4(d)
        sensitive_dropped += d
        cleaned.append(o2)

    # collabs --------------------------------------------------------------------------------
    await step("collabs")
    prov_ev = await provider.collabs(profile.handle, profile.platform)
    count_modes(run, prov_ev)
    paid = {x for e in prov_ev if e.kind == "meta_branded" for x in (e.brand, e.brand_handle) if x}
    post_ev = extract_collabs(posts, own_handle=profile.handle, competitors=brief.competitors, paid_brands=paid)
    timeline = mark_competitors(merge_timeline(post_ev, prov_ev), brief.competitors)

    # news -----------------------------------------------------------------------------------
    await step("news")
    query = person_name(profile.display_name) or profile.handle
    items = await provider.news(query, lang="cs", region=HOME_REGION, limit=NEWS_LIMIT)
    nbatch = count_modes(run, items)
    kept_items: list[NewsItem] = []
    d = 0
    if items:
        kept_items, d = await sensitive.filter_news(items)
    await add_r4(d)
    sensitive_dropped += d
    city = (anchor.city if anchor is not None and anchor.city else None) or brief.city or run.criteria.discovery.city
    subjects = {it.id: news_subject(profile, it, city) for it in kept_items}
    relevant = [it for it in kept_items if subjects.get(it.id) != "rejected"]
    nmode, _ = describe_modes(nbatch)
    pname = str(getattr(provider, "name", "") or "")
    await log(run, emit, tr(run, f"Zprávy „{query}“: {len(items)} nalezeno, {len(relevant)} se může týkat tvůrce",
                            f"News \"{query}\": {len(items)} found, {len(relevant)} may concern the creator"),
              actor=actor_of(items, f"{pname}:news" if pname == "mock" else pname), mode=nmode or _mode_of(items, provider))

    m = candidate.metrics
    data = VettingData(
        vetted_at=now, brief_key=brief_key(brief), posts=posts, cross_profiles=cleaned, provider_collabs=prov_ev,
        news_items=kept_items,
        modes={"topics": str(run.llm_modes.get("topics") or "fallback")},
        counts={"posts": len(posts), "comments": m.comments_analyzed if m else 0, "cross": len(cleaned),
                "news": len(items), "news_relevant": len(relevant), "news_set_aside": len(kept_items) - len(relevant),
                "collabs_provider": len(prov_ev),
                "sensitive_dropped": sensitive_dropped},
    )
    news_labels: dict[str, str] = {}
    if relevant:
        with _probe_mode() as probe:
            try:
                news = await vetting.news_findings(profile, relevant)
                news_labels = {nf.item.id: nf.label for nf in news}
                data.modes["news"] = _step_mode(probe) if news else "fallback"
            except Exception:
                logger.exception("vetting.news_findings failed; using keyword rule")
                probe[vetting.TASK] = "fallback"
                data.modes["news"] = "fallback"
        _replay_mode(probe)
    data.news_labels = news_labels

    # findings + claims -------------------------------------------------------------------------
    await step("findings")
    await step("claims")
    floor_ids = {c.id for c in vetting._fallback_claims(profile, posts, timeline)}
    with _probe_mode() as probe:
        try:
            out_claims: list[ClaimCheck] = await vetting.claims(profile, posts, timeline)
            if _step_mode(probe) == "llm":
                data.llm_claims = [c for c in out_claims if c.id not in floor_ids]
            data.modes["claims"] = _step_mode(probe)
        except Exception:
            logger.exception("vetting.claims failed")
            probe[vetting.TASK] = "fallback"
            data.modes["claims"] = "fallback"
    _replay_mode(probe)

    candidate.vetting_data = data
    first = render_report(run.criteria, candidate, data, anchor=anchor)

    await step("skeptic")
    with _probe_mode() as probe:
        try:
            checked = await vetting.skeptic(first)
            if isinstance(checked, Report) and _step_mode(probe) == "llm":
                data.llm_by_goal.setdefault(data.brief_key, {})["skeptic"] = _skeptic_raw(first, checked)
            data.modes["skeptic"] = _step_mode(probe)
        except Exception:
            logger.exception("vetting.skeptic failed")
            probe[vetting.TASK] = "fallback"
            data.modes["skeptic"] = "fallback"
    _replay_mode(probe)

    await step("questions")
    gaps = [f for f in first.findings if f.kind == "gap"]
    with _probe_mode() as probe:
        try:
            qs = await vetting.questions(gaps)
            if _step_mode(probe, default="fallback") == "llm":
                data.llm_questions = [dict(q) for q in qs]
            data.modes["questions"] = _step_mode(probe, default="fallback")
        except Exception:
            logger.exception("vetting.questions failed")
            probe[vetting.TASK] = "fallback"
            data.modes["questions"] = "fallback"
    _replay_mode(probe)

    await step("outreach")
    candidate.report = first
    with _probe_mode() as probe:
        try:
            draft = await vetting.outreach(brief, candidate)  # DRAFT only, never sent
            if draft and _step_mode(probe) == "llm":
                data.llm_by_goal.setdefault(data.brief_key, {})["outreach"] = dict(draft)
            data.modes["outreach"] = _step_mode(probe)
        except Exception:
            logger.exception("vetting.outreach failed")
            probe[vetting.TASK] = "fallback"
            data.modes["outreach"] = "fallback"
    _replay_mode(probe)

    try:
        from app.llm import budget as _budget

        if _budget.usage_snapshot().get("llm_budget_exhausted"):
            data.counts["llm_budget_exhausted"] = 1   # the method line says why the text is rule-based
    except Exception:
        pass
    candidate.vetting_data = data
    report = render_report(run.criteria, candidate, data, anchor=anchor)
    report.sensitive_filtered = candidate.sensitive_filtered
    candidate.report = report
    await emit("report.ready", {"candidate_id": cid})
    return report


def rerender(run: Run, candidate: Candidate) -> ReportDiff | None:
    """Re-render a vetted candidate's report for the run's CURRENT criteria from vetting_data (no fetch,
    no LLM). Returns the diff against the previous render (also stored as report.last_diff)."""
    from app.rounds.report import render_report

    if candidate.vetting_data is None:
        return None
    previous = candidate.report
    rep = render_report(run.criteria, candidate, candidate.vetting_data, anchor=_anchor_of(run), previous=previous)
    candidate.report = rep
    return rep.last_diff


async def prepare(run: Run, candidates: list[Candidate], provider: SourceProvider, emit: Emit) -> None:
    """vet_candidate for each (max MAX_FINALISTS, concurrently), set candidate.report."""
    todo = candidates[:MAX_FINALISTS]

    async def one(c: Candidate) -> None:
        try:
            c.report = await vet_candidate(run, c, provider, emit)
        except Exception as e:  # one failing finalist must not stop the others
            logger.exception("vetting %s failed", c.id)
            await log(run, emit, tr(run, f"Prověrka @{c.ref.handle} selhala: {e}", f"Vetting @{c.ref.handle} failed: {e}"),
                      actor="engine")
            await emit("error", {"message": f"vetting {c.id}: {e}", "candidate_id": c.id})

    await asyncio.gather(*(one(c) for c in todo))


# ---------------------------------------------------------------------------------------------
# evaluate (never eliminates; the engine records results only)
# ---------------------------------------------------------------------------------------------

def _brand_label(e: CollabEvidence) -> tuple[str, str]:
    """(dedupe key, display) so "Pekárna B" (Meta record) and "pekarna_b" (post) are one brand."""
    if e.brand_handle:
        return normalize_brand(e.brand_handle), f"@{e.brand_handle}"
    return normalize_brand(e.brand), e.brand


def _brand_names(evidence: list[CollabEvidence]) -> list[str]:
    by_key: dict[str, str] = {}
    for e in evidence:
        key, label = _brand_label(e)
        if key not in by_key or (label.startswith("@") and not by_key[key].startswith("@")):
            by_key[key] = label
    return list(by_key.values())


def _brand_dates(evidence: list[CollabEvidence], lang: str, limit: int = 3) -> str:
    by_brand: dict[str, tuple[str, list[datetime]]] = {}
    for e in evidence:
        key, label = _brand_label(e)
        cur_label, dates = by_brand.get(key, (label, []))
        if label.startswith("@"):
            cur_label = label
        if e.date and all(d.date() != e.date.date() for d in dates):
            dates.append(e.date)
        by_brand[key] = (cur_label, dates)
    parts = []
    for label, dates in list(by_brand.values())[:limit]:
        ds = ", ".join(fmt_date(d, lang) for d in sorted(dates)[:3])
        parts.append(f"{label} ({ds})" if ds else label)
    return "; ".join(parts)


def _no_post_data(c: Candidate) -> bool:
    """Nothing to check collaborations against: no profile, a private account, or no readable posts."""
    p = c.profile
    if p is None or p.private:
        return True
    n = c.metrics.posts_analyzed if c.metrics is not None else 0
    return not p.latest_posts and not n


def _assess_competitor(c: Candidate, brief: Brief) -> Outcome:
    th = i18n("žádná spolupráce s konkurencí", "no collaboration with competitors")
    if c.report is None:
        return unknown("ještě neprověřeno (kolo 4)", "not vetted yet (round 4)", th, profile_refs(c))
    if not competitor_keys(brief.competitors):
        # Not a pass: nothing was checked against. Unknown never eliminates and says what is missing.
        return unknown("konkurence není zadaná", "no competitors named", th, profile_refs(c))
    timeline = mark_competitors(c.report.collab_timeline, brief.competitors)
    if not timeline and _no_post_data(c):
        # absence of data is not a pass: nothing was checked
        return unknown("příspěvky nejsou dostupné", "posts not available", th, profile_refs(c))
    hits = [e for e in collaboration_evidence(timeline) if e.is_competitor]
    mentions = [e for e in timeline if e.is_competitor and e not in hits]
    if hits:
        posts = {e.post_id or e.id for e in hits}
        value = i18n(_brand_dates(hits, "cs"), _brand_dates(hits, "en"))  # the label already says "competitor"
        return Outcome("fail", value, th, [e.source for e in hits][:5], reason=i18n(
            f"{len(posts)} {cs_plural(len(posts), 'post', 'posty', 'postů')} se spoluprací s konkurencí ({_brand_dates(hits, 'cs')})",
            f"{len(posts)} {'post' if len(posts) == 1 else 'posts'} with a competitor ({_brand_dates(hits, 'en')})"))
    if mentions:
        return unknown(f"zmínka konkurence bez známek spolupráce ({_brand_dates(mentions, 'cs')})",
                       f"competitor mentioned without signs of a collaboration ({_brand_dates(mentions, 'en')})",
                       th, [e.source for e in mentions][:5])
    return Outcome("pass", i18n("spolupráci s konkurencí jsme nenašli", "no competitor collaboration found"), th,
                   [e.source for e in timeline][:3] or profile_refs(c))


def _assess_disclosure(criterion: Criterion, c: Candidate) -> Outcome:
    max_und = int(param(criterion, "max_undisclosed") or 0)
    th = i18n(f"nejvýš {max_und} neoznačených spoluprací", f"at most {max_und} unlabeled collaborations")
    if c.report is None:
        return unknown("ještě neprověřeno (kolo 4)", "not vetted yet (round 4)", th, profile_refs(c))
    timeline = c.report.collab_timeline
    if not timeline and _no_post_data(c):
        return unknown("příspěvky nejsou dostupné", "posts not available", th, profile_refs(c))
    if not timeline:
        return Outcome("pass", i18n("žádnou spolupráci jsme nenašli", "no collaboration found"), th, profile_refs(c))
    und = undisclosed_posts(timeline)
    labeled = {e.post_id or e.id for e in timeline if e.disclosed is True}
    n = len(und)
    if n > max_und:
        dates_cs = ", ".join(fmt_date(e.date, "cs") for e in und[:3])
        dates_en = ", ".join(fmt_date(e.date, "en") for e in und[:3])
        value = i18n(f"{n} {cs_plural(n, 'post', 'posty', 'postů')} se značkou bez označení reklamy ({dates_cs})",
                     f"{n} {'post' if n == 1 else 'posts'} with a brand and no ad label ({dates_en})")
        return Outcome("fail", value, th, [e.source for e in und][:5])
    if n == 0 and not labeled:
        return unknown("u spoluprací neznáme štítek platformy", "platform label unknown for the collaborations", th,
                       [e.source for e in timeline][:3])
    value = i18n(f"{len(labeled)} {cs_plural(len(labeled), 'spolupráce označena', 'spolupráce označeny', 'spoluprací označeno')}"
                 + (f", {n} bez označení" if n else ""),
                 f"{len(labeled)} {'collaboration' if len(labeled) == 1 else 'collaborations'} labeled" + (f", {n} unlabeled" if n else ""))
    return Outcome("pass", value, th, [e.source for e in timeline if e.disclosed is True][:3] or profile_refs(c))


def assess(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> Outcome:
    if criterion.kind == "no_competitor_collab":
        return _assess_competitor(candidate, brief)
    if criterion.kind == "discloses_ads":
        return _assess_disclosure(criterion, candidate)
    raise ValueError(f"criterion kind {criterion.kind!r} is not a round-4 kind")


def evaluate(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> CriterionResult:
    return assess(criterion, candidate, brief, now).result(criterion.id, brief.lang)

