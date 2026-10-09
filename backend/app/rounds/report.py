"""Goal-conditioned report rendering (docs/subject-mode.md sections 5-7). PURE: no I/O, no LLM, no
clock, no randomness. Same inputs -> identical Report (ids, order, texts).

Round 4 fetches once and keeps the raw inputs in ``VettingData`` (posts, cross-platform profiles,
provider collaborations, news, and the goal-independent LLM text). ``render_report`` builds the whole
report for the CURRENT criteria from that data:

- identity verdict with the owner's anchor (city / website / company ID), look-alikes and namesakes set aside;
- one check per enabled criterion (section "goal"), the goal-fit fact ``f:fit:topics``;
- every finding family, competitors re-marked for the current brief (a goal change can turn a
  labeled collaboration into a competitor collaboration);
- claims (rule floor + validated LLM claims), news, skeptic rules (+ stored LLM skeptic notes);
- per finding: confidence + basis, aspect, relevance tier for this goal (key / related / less) and a
  one-line "why it matters";
- questions, outreach draft (never sent), sections in display order, summary, "how this report was
  built" and, against the previous render, a ``ReportDiff``.

A relevance tier ranks FINDINGS for the goal, never the creator (no score, no rank, no verdict on the person).
"""

from __future__ import annotations

from collections import Counter
import re
from types import SimpleNamespace
from typing import Any

from app.compute.collabs import (
    UNKNOWN_BRAND,
    collaboration_evidence,
    extract_collabs,
    mark_competitors,
    merge_timeline,
    normalize_brand,
    undisclosed_posts,
)
from app.compute.identity import (
    _BACKLINK_MARKS, _LINK_MARKS, _SITE_MARKS, _has, anchor_signals, identity_verdict, match_identity, match_news,
    news_subject,
)
from app.llm import topics as topics_mod, vetting
from app.llm.text import business_en, clip, fold
from app.models import (
    CRITERION_ASPECT,
    CRITERION_DEFAULT_LABELS,
    TIER_RANK,
    Anchor,
    Brief,
    Candidate,
    ClaimCheck,
    CollabEvidence,
    CriteriaSet,
    Criterion,
    Finding,
    IdentityMatch,
    IdentityVerdict,
    NewsFinding,
    Report,
    ReportDiff,
    ReportSection,
    SetAside,
    SourceRef,
    VettingData,
    i18n,
    norm_handle,
    short_hash,
)
from app.rounds import r1_basics, r2_content, r3_audience, r4_vetting
from app.rounds.common import fmt_date, fmt_pct, newest_first, post_ref

ROUND_MODULES = {1: r1_basics, 2: r2_content, 3: r3_audience, 4: r4_vetting}

# Category keywords (moved here from main.py; main imports them back for the goal -> preset mapping).
FITNESS_WORDS = ("fitness", "posilovn", "gym", "jóga", "joga", "yoga", "pilates", "crossfit", "trenér", "trener",
                 "cvičen", "cviceni", "workout", "sportovní", "sports")
BAKERY_WORDS = ("pekár", "pekar", "bakery", "cukrár", "cukrar", "kavár", "kavar", "café", "cafe", "coffee",
                "bistro", "pastry", "patisserie", "dort", "chléb", "chleb")
# For brand-name matching ("pekarna_a" looks like a bakery): folded, specific stems only.
_CATEGORY_BRAND_WORDS = {
    "bakery": ("pekar", "bakery", "cukrar", "chleb", "kavar", "pastry", "patisserie"),
    "fitness": ("fitness", "gym", "posilovn", "crossfit", "pilates", "yoga", "joga", "fitko", "protein"),
}


def preset_for_brief(brief: Brief) -> str | None:
    """"fitness" / "bakery" from the business type keywords, else None."""
    text = (brief.business_type or "").lower()
    if any(w in text for w in FITNESS_WORDS):
        return "fitness"
    if any(w in text for w in BAKERY_WORDS):
        return "bakery"
    return None


def brief_key(brief: Brief) -> str:
    """short_hash(brief.model_dump_json(exclude={"lang"}))."""
    return short_hash(brief.model_dump_json(exclude={"lang"}))


# ---------------------------------------------------------------------------------------------
# Static texts
# ---------------------------------------------------------------------------------------------

SECTION_TITLES: dict[str, dict[str, str]] = {
    "identity": i18n("Identita: je to ten pravý účet?", "Identity: is this the account you mean?"),
    "goal": i18n("Kontroly pro váš cíl", "Checks for your goal"),
    "content": i18n("Obsah", "Content"),
    "engagement": i18n("Publikum a aktivita", "Audience and engagement"),
    "collabs": i18n("Spolupráce", "Collaborations"),
    "claims": i18n("Co tvůrce tvrdí vs. záznam", "What the creator says vs. the record"),
    "news": i18n("Zprávy", "News"),
    "profile": i18n("Profil", "Profile"),
}
DEFAULT_SECTION_ORDER = ("claims", "collabs", "content", "engagement", "news", "profile")
_SECTION_ASPECT = {"identity": "identity", "news": "reputation", "collabs": "competitors", "claims": "competitors",
                   "content": "content_fit", "engagement": "reach_engagement", "profile": "account"}
_BASIC_KINDS = ("public_account", "active_recently", "not_brand_account", "language_cs")
_PAID_KINDS = {"discount_code", "paid_label", "ad_hashtag", "affiliate_link", "meta_branded"}
_NEVER_PUBLIC_GAPS = ("g:demographics", "g:reach", "g:pricing")

_ASPECT_WHY: dict[str, dict[str, str]] = {
    "identity": i18n("Potvrzuje, že jde o správný účet, ne o jmenovce nebo podobný účet.",
                     "Confirms you are looking at the right account, not a namesake or look-alike."),
    "content_fit": i18n("Ukazuje, jestli obsah tvůrce sedí k vašemu cíli.",
                        "Shows whether the creator's content fits your goal."),
    "reach_engagement": i18n("Ukazuje, kolik lidí posty vidí a reaguje na ně.",
                             "Shows how many people see and react to the posts."),
    "local_language": i18n("Ukazuje, jestli tvůrce oslovuje lidi ve vašem městě a jazyce.",
                           "Shows whether the creator reaches people in your city and language."),
    "competitors": i18n("Ukazuje, s kým dalším tvůrce spolupracuje.", "Shows who else the creator works with."),
    "ad_disclosure": i18n("Ukazuje, jestli tvůrce označuje placené posty jako reklamu.",
                          "Shows whether paid posts are labeled as ads."),
    "account": i18n("Základní údaje o účtu.", "Basic account facts."),
    "reputation": i18n("Co o tvůrci píšou média, vždy s názvem média.",
                       "What the media say about the creator, with the outlet named."),
    "practical": i18n("Potřebujete to vědět, než se na spolupráci domluvíte.",
                      "Needed before you agree on a collaboration."),
}

# Confidence bases (section 7).
_B: dict[str, dict[str, str]] = {
    "profile": i18n("údaje platformy o profilu", "platform profile data"),
    "media": i18n("typ médií z platformy", "platform media type"),
    "dates": i18n("data postů", "post dates"),
    "commercial": i18n("štítky, reklamní hashtagy a slevové kódy v popiscích",
                       "labels, ad hashtags and discount codes in captions"),
    "generic": i18n("pravidlové třídění komentářů", "rule-based comment classification"),
    "local": i18n("místa a popisky postů", "place tags and captions"),
    "paid_label": i18n("štítek placené spolupráce z platformy", "platform paid-partnership label"),
    "meta_branded": i18n("knihovna značkového obsahu Meta", "Meta branded content library"),
    "coauthor": i18n("pole spoluautora z platformy", "platform co-author field"),
    "caption": i18n("vlastní popisek", "own caption"),
    "linked": i18n("profily na sebe navzájem odkazují", "the profiles link to each other"),
    "similar": i18n("jen podobné jméno nebo uživatelské jméno", "similar name or handle only"),
    "same_website": i18n("na obou profilech je stejný web", "the same website on both profiles"),
    "similar_name": i18n("podobné uživatelské jméno a jméno", "similar handle and name"),
    "fan": i18n("znaky fanouškovského účtu", "fan-account markers"),
    "region": i18n("region účtu", "account region"),
    "city_bio": i18n("město v biu", "city in bio"),
    "anchor_found": i18n("kotva nalezená na profilu", "anchor found on the profile"),
    "anchor_city_bio": i18n("město z kotvy v biu", "anchor city in bio"),
    "anchor_city_posts": i18n("město z kotvy v místech nebo popiscích postů", "anchor city in post locations or captions"),
    "news_one": i18n("jediný článek", "single news item"),
    "news_many": i18n("shodují se aspoň 2 média", "at least 2 outlets agree"),
    "name_only": i18n("shoda jen ve jméně", "name match only"),
    "namesake": i18n("jiný kontext v článku", "different context in the article"),
    "never_public": i18n("na platformě nikdy veřejné", "never public on the platform"),
    "not_found": i18n("nenalezeno ve zdrojích, které jsme prošli", "not found in the sources we checked"),
    "collab_record": i18n("záznam spoluprací", "collaboration record"),
    "language": i18n("rozpoznání jazyka popisků", "language detection on captions"),
    "no_fact": i18n("odhad bez opory ve faktech", "inference without a supporting fact"),
    "rule_claim": i18n("vlastní slova (bio nebo popisek) vs. záznam spoluprací", "own caption vs. collaboration record"),
    "followers_claim": i18n("počet sledujících na profilu", "profile follower count"),
    "llm_claim": i18n("AI čtení popisku, ověřené proti záznamu", "AI reading of the caption, checked against the record"),
}


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------

def _bt(brief: Brief) -> dict[str, str]:
    bt = (brief.business_type or "").strip()
    if not bt or not vetting._safe_text(bt):
        return i18n("firma", "business")
    return i18n(bt, business_en(bt))


def _crit_label(cr: Criterion, lg: str) -> str:
    return (cr.label or {}).get(lg) or CRITERION_DEFAULT_LABELS.get(cr.kind, {}).get(lg) or cr.id


def _stub_report(cid: str, timeline: list[CollabEvidence]) -> Report:
    return Report(candidate_id=cid, findings=[], claims=[], collab_timeline=timeline, news=[], identity=[],
                  questions=[], outreach_draft=None, not_checked=[], skeptic_notes=[], sensitive_filtered=0)


def _claim_kind(claim: str) -> str:
    f = fold(claim)
    if vetting._RX_EXCLUSIVE.search(f):
        return "exclusive"
    if vetting._RX_PARTNER.search(f):
        return "partner"
    if vetting._RX_UNPAID.search(f):
        return "unpaid"
    if vetting._RX_FOLLOWERS.search(f):
        return "followers"
    return "other"


def _exclusive_brand(claim: str) -> str | None:
    m = vetting._RX_EXCLUSIVE.search(fold(claim))
    return m.group(3).strip(".") if m else None


def _brand_label(e: CollabEvidence) -> str:
    return f"@{e.brand_handle}" if e.brand_handle else e.brand


def _brands(evidence: list[CollabEvidence]) -> list[str]:
    seen: dict[str, str] = {}
    for e in evidence:
        if not e.brand or e.brand == UNKNOWN_BRAND:
            continue
        key = normalize_brand(e.brand_handle or e.brand)
        label = _brand_label(e)
        if key not in seen or (label.startswith("@") and not seen[key].startswith("@")):
            seen[key] = label
    return list(seen.values())


def _brand_names(evidence: list[CollabEvidence]) -> list[str]:
    """Display names: the brand name ("ProteoMax") over a handle when both are known."""
    seen: dict[str, str] = {}
    for e in evidence:
        if not e.brand or e.brand == UNKNOWN_BRAND:
            continue
        key = normalize_brand(e.brand_handle or e.brand)
        name = e.brand if (not e.brand.islower() or not e.brand_handle) else f"@{e.brand_handle}"
        if key not in seen or (seen[key].startswith("@") and not name.startswith("@")):
            seen[key] = name
    return list(seen.values())


def _join(items: list[str], lg: str) -> str:
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" a " if lg == "cs" else " and ") + items[-1]


def _join_or(items: list[str], lg: str) -> str:
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" nebo " if lg == "cs" else " or ") + items[-1]


def _cs_n(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {one if n == 1 else (few if 2 <= n <= 4 else many)}"


def _en_n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _clip_words(text: str, n: int = 160) -> str:
    """Clip at a word boundary (never mid-word) with an ellipsis."""
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    cut = t[: n - 1]
    sp = cut.rfind(" ")
    if sp > n // 2:
        cut = cut[:sp]
    return cut.rstrip(" ,;:—-") + "…"


def _short(text: str, n: int = 110) -> str:
    return clip((text or "").replace("\n", " "), n)


# ---------------------------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------------------------

def render_report(criteria: CriteriaSet, candidate: Candidate, data: VettingData, *,
                  anchor: Anchor | None = None, previous: Report | None = None) -> Report:
    """Same inputs -> identical Report (ids, order, texts). Reads candidate.profile / metrics / results /
    topic_labels / sensitive_filtered. Re-marks competitors on a COPY of the timeline built from
    data.posts + data.provider_collabs (compute.collabs.extract_collabs + merge_timeline + mark_competitors
    for criteria.brief). Uses LLM text only from data (llm_claims, llm_questions, llm_by_goal[brief_key]).
    With previous: sets last_diff = diff_reports(previous, new)."""
    brief = criteria.brief
    lang = brief.lang if brief.lang in ("cs", "en") else "cs"
    profile = candidate.profile
    cid = candidate.id
    bk = brief_key(brief)
    bt = _bt(brief)
    view = SimpleNamespace(criteria=criteria)
    enabled: dict[str, Criterion] = {c.id: c for c in criteria.criteria if c.enabled}
    vetted_for = (previous.vetted_for if previous is not None and previous.vetted_for else None) or brief.business_type

    if profile is None:
        rep = Report(candidate_id=cid, findings=[], claims=[], collab_timeline=[], news=[], identity=[],
                     questions=vetting.template_questions([]), outreach_draft=None,
                     not_checked=[dict(x) for x in r4_vetting.NOT_CHECKED], skeptic_notes=[],
                     sensitive_filtered=candidate.sensitive_filtered, vetted_for=vetted_for,
                     identity_verdict=identity_verdict(None, anchor, [], [], [], [], lang=lang, handle=candidate.ref.handle,
                                                       tried=[candidate.ref.platform]),
                     rendered_for=_rendered_for(brief, bk))
        if previous is not None:
            rep.last_diff = diff_reports(previous, rep)
        return rep

    city = brief.city or criteria.discovery.city
    news_city = (anchor.city if anchor is not None and anchor.city else None) or city

    # --- collaboration timeline for THIS goal (competitor marks and brand detection depend on it)
    paid = {x for e in data.provider_collabs if e.kind == "meta_branded" for x in (e.brand, e.brand_handle) if x}
    post_ev = extract_collabs(data.posts, own_handle=profile.handle, competitors=brief.competitors, paid_brands=paid)
    timeline = mark_competitors(merge_timeline(post_ev, data.provider_collabs), brief.competitors)
    tl_by_id = {e.id: e for e in timeline}

    # --- identity (both languages: signal texts are single-language strings)
    ident = {lg: match_identity(profile, list(data.cross_profiles), lang=lg, home_region=r4_vetting.HOME_REGION,
                                anchor=anchor) for lg in ("cs", "en")}
    subjects = {it.id: news_subject(profile, it, news_city) for it in data.news_items}
    names = {lg: match_news(profile, list(data.news_items), city=news_city, lang=lg) for lg in ("cs", "en")}
    matched_keys = {(m.platform, m.handle) for m in ident[lang] if m.status == "matched"}
    matched_cross = [o for o in data.cross_profiles if (o.platform, norm_handle(o.handle)) in matched_keys]
    asig = {lg: anchor_signals(profile, list(data.posts), anchor, cross=matched_cross, lang=lg) for lg in ("cs", "en")}
    # news set aside = not about this creator (namesakes + results that mention neither handle nor name);
    # the verdict, the method section and VettingData.counts["news_set_aside"] all count the same items
    news_aside = [it.id for it in data.news_items if subjects.get(it.id) == "rejected"]
    namesake_ids = {m.handle for m in names[lang]}
    n_unrelated = sum(1 for i in news_aside if i not in namesake_ids)
    verdict = _verdict(profile, anchor, asig, ident, names, data, lang, unrelated_news=n_unrelated)
    if anchor is None and "manual" not in (candidate.ref.found_via or []):
        verdict = _discovery_verdict_text(verdict, profile.handle, city)
    identity_list = ident[lang] + names[lang]

    # --- news (namesakes out; labels from the stored LLM pass, else the keyword rule)
    relevant = [it for it in data.news_items if subjects.get(it.id) != "rejected"]
    news: list[NewsFinding] = []
    for it in relevant:
        a_cs, a_en = r4_vetting.news_attribution(it, subjects.get(it.id))
        label = data.news_labels.get(it.id) or vetting._keyword_label(it)
        news.append(NewsFinding(item=it, label=label, attribution=a_en if lang == "en" else a_cs))  # type: ignore[arg-type]

    # --- finding families
    findings = _anchor_findings(anchor, asig, lang)
    findings += r4_vetting.build_findings(
        view, candidate, list(data.posts), timeline, list(data.provider_collabs), identity_list, names[lang], news,
        subjects, identity_i18n={lg: ident[lg] + names[lg] for lg in ("cs", "en")}, namesakes_i18n=names)
    fit = _fit_topics(criteria, candidate, bt)
    if fit is not None:
        findings.insert(_first_index(findings, "content"), fit)

    # --- goal checks (round 4 evaluated on THIS render's timeline)
    checks, check_findings = _goal_checks(criteria, candidate, data, timeline, bt)
    findings = check_findings + findings

    # --- claims: validated LLM claims first, then the rule floor for what they do not cover
    known_ids = set(tl_by_id) | {p.id for p in data.posts} | {profile.source.id}
    llm_claims: list[ClaimCheck] = []
    for c in data.llm_claims or []:
        ev = [e for e in c.evidence if e in known_ids]
        if c.status in ("supported", "conflicts_with_record") and not ev:
            c = c.model_copy(update={"evidence": [], "status": "cannot_verify", "confidence": "low", "note": i18n(
                "Tvrzení nemá v záznamu doložitelný důkaz.", "The claim has no traceable evidence in the record.")})
        elif len(ev) < len(c.evidence):
            c = c.model_copy(update={"evidence": ev})
        llm_claims.append(c)
    floor = vetting._fallback_claims(profile, list(data.posts), timeline)
    claims = llm_claims + [f for f in floor if not any(vetting._overlaps(f.claim, c.claim) for c in llm_claims)]
    llm_claim_ids = {c.id for c in llm_claims}

    # --- skeptic (rules always; stored LLM notes for this goal on top)
    rep = Report(
        candidate_id=cid, findings=findings, claims=claims, collab_timeline=timeline, news=news,
        identity=identity_list, questions=[], outreach_draft=None,
        not_checked=[dict(x) for x in r4_vetting.NOT_CHECKED], skeptic_notes=[],
        sensitive_filtered=candidate.sensitive_filtered, vetted_for=vetted_for,
    )
    rep = vetting.apply_skeptic_rules(rep)
    goal_llm = data.llm_by_goal.get(bk) or {}
    raw_skeptic = goal_llm.get("skeptic")
    if raw_skeptic:
        notes = []
        for n in raw_skeptic:
            try:
                notes.append(vetting._SkepticNote.model_validate(n))
            except Exception:
                continue
        rep = vetting.apply_llm_skeptic(rep, notes)

    # --- goal layer: relevance, aspect, tier, why, confidence
    ctx = _Ctx(criteria=criteria, enabled=enabled, checks=checks, timeline=timeline, verdict=verdict, bt=bt,
               candidate=candidate, data=data, subjects=subjects, news_labels={n.item.id: n.label for n in rep.news},
               identity=ident[lang])
    rep.findings = _goal_layer_findings(rep.findings, ctx)
    rep.claims = _goal_layer_claims(rep.claims, ctx, llm_claim_ids, profile.source.id)

    # --- questions, outreach
    rep.questions = _questions(rep, ctx, profile)
    topic_status = next((v["status"] for v in checks.values() if v.get("kind") == "topic_share" and not v.get("waived")), None)
    rep.outreach_draft = goal_llm.get("outreach") or vetting.outreach_template(brief, candidate, topic_status)
    comp_name = _subject_competitor(brief, profile)
    if comp_name:
        # the subject IS one of the owner's competitors: say so, and draft no collaboration offer
        rep.findings.insert(0, Finding(
            id="f:subject_competitor", kind="fact", section="goal", relevance=_rel_ids(ctx, ["no_competitor_collab"]),
            text=i18n(f"Tohle je jeden z konkurentů, které jste uvedli ({comp_name}).",
                      f"This is one of the competitors you listed ({comp_name})."),
            sources=[profile.source], tier="key", aspect="competitors", confidence="high",
            confidence_basis=i18n("vaše zadání a uživatelské jméno profilu", "your brief and the profile handle"),
            why_it_matters=i18n("Spolupráci s konkurentem nenabízíme; report slouží jen pro přehled.",
                                "We do not offer a collaboration to a competitor; the report is for your overview only.")))
        rep.outreach_draft = i18n(f"Koncept oslovení nepřipravujeme: {comp_name} je váš konkurent.",
                                  f"No outreach draft: {comp_name} is one of your competitors.")

    # --- ordering, sections, summary, method
    _order(rep)
    rep.identity_verdict = verdict
    rep.checks = checks_status(checks)
    rep.rendered_for = _rendered_for(brief, bk)
    rep.text_source = {
        "claims": "llm+rules" if data.llm_claims is not None else "rules",
        "news": "llm" if data.modes.get("news") == "llm" else "rules",
        "skeptic": "llm+rules" if raw_skeptic else "rules",
        "questions": "llm+template" if data.llm_questions else "template",
        "outreach": "llm" if goal_llm.get("outreach") else "template",
    }
    rep.method = _method(rep, candidate, data, anchor, brief, bt, lang, news_aside=len(news_aside),
                         unrelated_news=n_unrelated)
    if previous is not None:
        rep.last_diff = diff_reports(previous, rep)
    return rep


def _subject_competitor(brief: Brief, profile) -> str | None:
    """The competitor's name when the checked profile is one of brief.competitors (handle match)."""
    if profile is None:
        return None
    h = normalize_brand(profile.handle or "")
    for c in brief.competitors or []:
        keys = {normalize_brand(x) for x in (c.get("handles") or []) if x}
        if h and h in keys:
            return str(c.get("name") or f"@{profile.handle}")
    return None


def checks_status(checks: dict[str, dict]) -> dict[str, str]:
    return {k: ("pass" if v["waived"] else v["status"]) for k, v in checks.items()}


def _rendered_for(brief: Brief, bk: str) -> dict[str, str]:
    return {"business_type": brief.business_type or "", "goal": brief.goal or "", "city": brief.city or "",
            "brief_key": bk}


def _first_index(findings: list[Finding], section: str) -> int:
    return next((i for i, f in enumerate(findings) if f.section == section), len(findings))


# ---------------------------------------------------------------------------------------------
# Identity verdict + anchor findings
# ---------------------------------------------------------------------------------------------

def _unrelated_news_text(n: int, h: str) -> dict[str, str]:
    """News results set aside as not about the creator (other than namesakes, which the verdict lists)."""
    cs = (f"1 nalezenou zprávu, která se @{h} netýká" if n == 1 else
          f"{n} nalezené zprávy, které se @{h} netýkají" if n < 5 else f"{n} nalezených zpráv, které se @{h} netýkají")
    en = f"{_en_n(n, 'news result')} that {'is' if n == 1 else 'are'} not about @{h}"
    return {"cs": cs, "en": en}


def _discovery_verdict_text(v: IdentityVerdict, handle: str, city: str | None) -> IdentityVerdict:
    """Discovery: the owner did not name this creator, so there is no anchor to ask for. The text says
    how the account was found; the namesake / look-alike part of the verdict text is kept."""
    if v.status in ("confirmed", "not_found"):
        return v
    text: dict[str, str] = {}
    for lg, head, marker in (
        ("cs", f"@{handle} našlo hledání pro váš cíl (nezadali jste ho vy), proto kotvu nechceme. "
               f"Report je o tomto účtu, jak ho hledání našlo"
               + (f"; místní vazbu na {city} ukazují kontroly níže." if city else "."), " Stranou jsme dali"),
        ("en", f"@{handle} was found by the search for your goal (you did not name this creator), so no anchor is "
               f"needed. The report is about this account as found"
               + (f"; the checks below show its local ties to {city}." if city else "."), " We set aside"),
    ):
        old = v.text.get(lg) or ""
        i = old.find(marker)
        text[lg] = head + (old[i:] if i >= 0 else "")
    return v.model_copy(update={"text": text})


def _verdict(profile, anchor, asig, ident, names, data: VettingData, lang: str, *,
             unrelated_news: int = 0) -> IdentityVerdict:
    by_lang = {lg: identity_verdict(profile, anchor, asig[lg], ident[lg], names[lg], list(data.news_items), lang=lg)
               for lg in ("cs", "en")}
    base = by_lang[lang]
    other = by_lang["en" if lang == "cs" else "cs"]
    set_aside: list[SetAside] = []
    for i, sa in enumerate(base.set_aside):
        alt = other.set_aside[i] if i < len(other.set_aside) else sa
        reason = {lang: sa.reason[lang], ("en" if lang == "cs" else "cs"): alt.reason["en" if lang == "cs" else "cs"]}
        set_aside.append(sa.model_copy(update={"reason": {"cs": reason["cs"], "en": reason["en"]}}))
    text = {"cs": by_lang["cs"].text["cs"], "en": by_lang["en"].text["en"]}
    if unrelated_news and profile is not None:
        un = _unrelated_news_text(unrelated_news, profile.handle)
        text["cs"] += f" Stranou jsme dali {un['cs']}."
        text["en"] += f" We set aside {un['en']}."
    return base.model_copy(update={"text": text, "set_aside": set_aside})


def _anchor_findings(anchor: Anchor | None, asig: dict[str, list], lang: str) -> list[Finding]:
    if anchor is None:
        return []
    out: list[Finding] = []
    sig = {lg: {k: s for k, s in asig[lg]} for lg in ("cs", "en")}

    def fact(fid: str, kind: str) -> None:
        s_cs, s_en = sig["cs"][kind], sig["en"][kind]
        if s_cs.source is None:
            return
        out.append(Finding(id=fid, kind="fact", section="identity", sources=[s_cs.source],
                           text=i18n(f"Kotva: {s_cs.signal}", f"Anchor: {s_en.signal}")))

    def gap(fid: str, cs: str, en: str) -> None:
        out.append(Finding(id=fid, kind="gap", section="identity", sources=[], text=i18n(cs, en)))

    if anchor.website:
        if "anchor_website" in sig["cs"]:
            fact("f:anchor:website", "anchor_website")
        else:
            gap("g:anchor:website", f"Web {anchor.website} na profilu ani na propojených účtech není.",
                f"The website {anchor.website} does not appear on the profile or on linked accounts.")
    if anchor.company_id:
        if "anchor_company_id" in sig["cs"]:
            fact("f:anchor:company_id", "anchor_company_id")
        else:
            gap("g:anchor:company_id",
                f"IČO {anchor.company_id} ve veřejném profilu není; obchodní rejstřík jsme neprocházeli.",
                f"Company ID {anchor.company_id} does not appear in the public profile; we did not query the business register.")
    if anchor.city:
        if "anchor_city_bio" in sig["cs"]:
            fact("f:anchor:city", "anchor_city_bio")
        if "anchor_city_posts" in sig["cs"]:
            fact("f:anchor:city_posts", "anchor_city_posts")
        if "anchor_city_other" in sig["cs"]:
            fact("f:anchor:city_other", "anchor_city_other")
        if not any(k in sig["cs"] for k in ("anchor_city_bio", "anchor_city_posts", "anchor_city_other")):
            gap("g:anchor:city", f"{anchor.city} v biu ani v místech postů není.",
                f"{anchor.city} does not appear in the bio or in post locations.")
    return out


# ---------------------------------------------------------------------------------------------
# Goal checks + goal fit
# ---------------------------------------------------------------------------------------------

_STATUS_WORD = {
    "pass": i18n("splněno", "meets it"), "fail": i18n("nesplněno", "does not meet it"),
    "unknown": i18n("nelze ověřit", "could not check"), "waived": i18n("výjimka od vás", "waived by you"),
}


def _goal_checks(criteria: CriteriaSet, candidate: Candidate, data: VettingData, timeline: list[CollabEvidence],
                 bt: dict[str, str]) -> tuple[dict[str, dict], list[Finding]]:
    brief = criteria.brief
    lang = brief.lang if brief.lang in ("cs", "en") else "cs"
    results = {r.criterion_id: r for r in candidate.results}
    tmp = candidate.model_copy(update={"report": _stub_report(candidate.id, timeline)})
    checks: dict[str, dict] = {}
    out: list[Finding] = []
    for cr in criteria.criteria:
        if not cr.enabled or cr.round not in ROUND_MODULES:
            continue
        module = ROUND_MODULES[cr.round]
        prev = results.get(cr.id)
        try:
            fresh = module.assess(cr, tmp if cr.round == 4 else candidate, brief, data.vetted_at)
        except Exception:
            fresh = None
        if cr.round == 4 or prev is None:
            if fresh is None:
                continue
            status = fresh.status
            value, threshold, sources = dict(fresh.value), dict(fresh.threshold), list(fresh.sources)
        else:
            status = prev.status
            sources = list(prev.sources)
            if fresh is not None and fresh.status == prev.status:
                value, threshold = dict(fresh.value), dict(fresh.threshold)
            else:
                value, threshold = {"cs": prev.value, "en": prev.value}, {"cs": prev.threshold, "en": prev.threshold}
        waived = bool(prev.waived) if prev is not None else False
        checks[cr.id] = {"status": status, "waived": waived, "kind": cr.kind, "sources": sources}
        word = _STATUS_WORD["waived" if waived else status]
        texts = {}
        for lg in ("cs", "en"):
            v = value.get(lg) or value.get("cs", "")
            t = threshold.get(lg) or threshold.get("cs", "")
            need = (f" (požadavek: {t})" if t else "") if lg == "cs" else (f" (needs {t})" if t else "")
            texts[lg] = f"{_crit_label(cr, lg)}: {v}{need} — {word[lg]}"
        is_gap = status == "unknown" or not sources
        fid = f"{'g' if is_gap else 'f'}:check:{cr.id}"
        out.append(Finding(id=fid, kind="gap" if is_gap else "fact", text=texts,
                           sources=[] if is_gap else _dedupe_refs(sources)[:5], section="goal", relevance=[cr.id]))
    return checks, out


def _dedupe_refs(refs: list[SourceRef]) -> list[SourceRef]:
    seen: set[str] = set()
    out = []
    for r in refs:
        if r.id not in seen:
            seen.add(r.id)
            out.append(r)
    return out


def _fit_topics(criteria: CriteriaSet, candidate: Candidate, bt: dict[str, str]) -> Finding | None:
    crit = next((c for c in criteria.criteria if c.enabled and c.kind == "topic_share"), None)
    profile = candidate.profile
    if crit is None or profile is None:
        return None
    # The same topics the round-2 check counts: supporting topics (local tips) never carry the share.
    topics = topics_mod.counted_topics([t for t in (crit.params.get("topics") or []) if isinstance(t, str)])
    min_share = crit.params.get("min_share")
    labels = candidate.topic_labels or {}
    posts = newest_first(profile.latest_posts)
    classified = [p for p in posts if labels.get(p.id) and labels[p.id] != "unclassified"]
    if not classified or not topics:
        return None
    hits = [p for p in classified if labels.get(p.id) in topics]
    n, total = len(hits), len(classified)
    share = n / total
    t_cs = _join_or([r4_vetting.TOPIC_CS_NOM.get(t, t) for t in topics], "cs")
    t_en = _join_or([r4_vetting.TOPIC_EN_NOM.get(t, t) for t in topics], "en")
    need_cs = f" (požadavek aspoň {fmt_pct(float(min_share), 'cs')})" if isinstance(min_share, (int, float)) else ""
    need_en = f" (needs at least {fmt_pct(float(min_share), 'en')})" if isinstance(min_share, (int, float)) else ""
    sources = [post_ref(p) for p in hits[:5]] or [profile.source]
    return Finding(
        id="f:fit:topics", kind="fact", section="content", sources=sources, relevance=[crit.id],
        text=i18n(f"{n} z {total} posledních postů ({fmt_pct(share, 'cs')}) je o tématech {t_cs}: to je pro váš cíl ({bt['cs']}) podstatné{need_cs}",
                  f"{n} of {total} recent posts ({fmt_pct(share, 'en')}) are about {t_en}: what matters for a {bt['en']}{need_en}"),
    )


# ---------------------------------------------------------------------------------------------
# Goal layer: tier, aspect, why, confidence
# ---------------------------------------------------------------------------------------------

class _Ctx(SimpleNamespace):
    criteria: CriteriaSet
    enabled: dict[str, Criterion]
    checks: dict[str, dict]
    timeline: list[CollabEvidence]
    verdict: IdentityVerdict
    bt: dict[str, str]
    candidate: Candidate
    data: VettingData
    subjects: dict[str, str]
    news_labels: dict[str, str]
    identity: list[IdentityMatch]


def _collab_groups(timeline: list[CollabEvidence]) -> dict[str, list[CollabEvidence]]:
    groups: dict[str, list[CollabEvidence]] = {}
    for e in timeline:
        groups.setdefault(e.post_id or e.id, []).append(e)
    return groups


def _rel_ids(ctx: _Ctx, kinds: list[str]) -> list[str]:
    return [c.id for c in ctx.criteria.criteria if c.kind in kinds]


def _goal_layer_findings(findings: list[Finding], ctx: _Ctx) -> list[Finding]:
    groups = _collab_groups(ctx.timeline)
    collab_ids = {e.id for e in collaboration_evidence(ctx.timeline)}
    group_info: dict[str, dict[str, Any]] = {}
    for key, evs in groups.items():
        disclosed = True if any(e.disclosed is True for e in evs) else (False if any(e.disclosed is False for e in evs) else None)
        group_info[f"f:collab:{key}"] = {
            "comp": any(e.is_competitor for e in evs),
            "disclosed": disclosed,
            "mention_only": not any(e.id in collab_ids for e in evs),
            "evs": evs,
        }
    by_id = {f.id: f for f in findings}
    key_identity: set[str] = {"f:anchor:city_other"}
    if ctx.verdict.status == "uncertain":
        key_identity |= {f.id for f in findings if f.id.startswith("g:anchor:")}
    ident_status = {f"f:identity:{m.platform}:{m.handle}": m for m in ctx.identity}

    # cross-check news against the record: an article naming one of THIS goal's competitors is a
    # competitor signal; an allegation about ad labels next to a failing disclosure check is consistent
    news_comp = _news_competitors(ctx)
    ctx.news_comp = news_comp
    findings = list(findings) + _news_consistency(findings, ctx)
    if news_comp:
        findings = [f.model_copy(update={"based_on": list(f.based_on) + [n for n in news_comp if n in by_id and n not in f.based_on]})
                    if f.id == "i:competitor" else f for f in findings]

    # relevance (current criteria): collab facts get a precise one
    updated: dict[str, Finding] = {}
    for f in findings:
        rel = list(f.relevance)
        if f.id in news_comp:
            rel = rel + [r for r in _rel_ids(ctx, ["no_competitor_collab"]) if r not in rel]
        info = group_info.get(f.id)
        if info is not None:
            kinds = []
            if info["comp"]:
                kinds.append("no_competitor_collab")
            if info["disclosed"] is False and not info["mention_only"]:
                kinds.append("discloses_ads")
            rel = _rel_ids(ctx, kinds)
        updated[f.id] = f.model_copy(update={"relevance": rel})
    findings = [updated[f.id] for f in findings]
    by_id = {f.id: f for f in findings}

    tiers: dict[str, str] = {}
    reasons: dict[str, str] = {}

    def rule(f: Finding) -> tuple[str, str]:
        fid = f.id
        rel_on = [r for r in f.relevance if r in ctx.enabled]
        info = group_info.get(fid)
        if fid in key_identity:
            return "key", "identity"
        if fid == "f:fit:topics":
            return "key", "fit"
        if (info is not None and info["comp"]) or fid == "i:competitor" or fid in news_comp:
            return "key", "competitor"
        if any(ctx.checks.get(r, {}).get("status") == "fail" and not ctx.checks.get(r, {}).get("waived") for r in rel_on):
            return "key", "fail"
        if fid.startswith("f:news:") and ctx.news_labels.get(fid[len("f:news:"):]) == "allegation":
            return "key", "allegation"
        if fid.startswith("f:check:"):
            chk = ctx.checks.get(fid[len("f:check:"):], {})
            if chk.get("status") == "pass" and chk.get("kind") in _BASIC_KINDS:
                return "less", "basic_pass"
        if info is not None and not info["comp"] and (info["mention_only"] or info["disclosed"] is True):
            return "less", "mention" if info["mention_only"] else "labeled"
        if rel_on:
            return "related", "criterion"
        if f.section in ("identity", "news", "claims"):
            return "related", "section"
        if fid in ("g:pricing", "g:demographics"):
            return "related", "always"
        if info is not None and info["disclosed"] is False:
            return "related", "undisclosed"
        return "less", "unlinked"

    for f in findings:
        if f.kind != "inference":
            tiers[f.id], reasons[f.id] = rule(f)
    for f in findings:
        if f.kind == "inference":
            t, r = rule(f)
            for b in f.based_on:
                bt_ = tiers.get(b)
                if bt_ is not None and TIER_RANK[bt_] > TIER_RANK[t] and r not in ("labeled", "mention"):
                    t, r = bt_, reasons.get(b, r)
            tiers[f.id], reasons[f.id] = t, r

    conf = _Confidence(ctx, by_id, ident_status, group_info)
    out: list[Finding] = []
    for f in findings:
        tier = tiers[f.id]
        aspect = _aspect(f, ctx)
        c, basis = conf.of(f)
        out.append(f.model_copy(update={
            "tier": tier, "aspect": aspect, "confidence": c, "confidence_basis": basis,
            "why_it_matters": _why(f, tier, reasons[f.id], aspect, ctx, group_info.get(f.id)),
        }))
    return out


_AD_WORDS = re.compile(r"reklam|oznac|sponzor|slev|kod|discount|advert|label|sponsor|promo")


def _news_competitors(ctx: _Ctx) -> dict[str, list[str]]:
    """{"f:news:<id>": [competitor names]} for news about the creator (not namesakes) whose title or
    snippet names a competitor of the CURRENT brief (word match on the name, or the @handle)."""
    out: dict[str, list[str]] = {}
    comps = [c for c in ctx.criteria.brief.competitors or [] if isinstance(c, dict)]
    if not comps:
        return out
    for it in ctx.data.news_items:
        if ctx.subjects.get(it.id) == "rejected":
            continue
        t = fold(f"{it.title} {it.snippet}")
        names: list[str] = []
        for c in comps:
            name = str(c.get("name") or "").strip()
            handles = [h for h in (c.get("handles") or []) if isinstance(h, str) and h]
            pats = [r"(?<!\w)" + r"\W+".join(re.escape(w) for w in fold(name).split()) + r"(?!\w)"] if name else []
            pats += [r"(?<![\w@])@?" + re.escape(fold(h)) + r"(?!\w)" for h in handles]
            if any(re.search(p, t) for p in pats):
                names.append(name or f"@{handles[0]}")
        if names:
            out[f"f:news:{it.id}"] = names
    return out


def _news_consistency(findings: list[Finding], ctx: _Ctx) -> list[Finding]:
    """An allegation about ad labels / discount codes next to a failing disclosure check: one inference
    based on both ("the record shows N unlabeled posts, consistent with the article")."""
    ids = {f.id for f in findings}
    fail = next((cid for cid, c in ctx.checks.items() if c.get("kind") == "discloses_ads" and c.get("status") == "fail"), None)
    if fail is None or f"f:check:{fail}" not in ids:
        return []
    n = len(undisclosed_posts(ctx.timeline))
    out: list[Finding] = []
    for it in ctx.data.news_items:
        fid = f"f:news:{it.id}"
        if fid not in ids or ctx.news_labels.get(it.id) != "allegation" or ctx.subjects.get(it.id) == "rejected":
            continue
        if not _AD_WORDS.search(fold(f"{it.title} {it.snippet}")):
            continue
        out.append(Finding(
            id=f"i:news_record:{it.id}", kind="inference", section="news", sources=[], based_on=[fid, f"f:check:{fail}"],
            relevance=[fail],
            text=i18n(f"Záznam ukazuje {n} {'post' if n == 1 else ('posty' if n < 5 else 'postů')} se značkou bez označení "
                      "reklamy, což odpovídá tomu, co uvádí článek (obvinění, ne potvrzený fakt).",
                      f"The record shows {n} {'post' if n == 1 else 'posts'} with a brand and no ad label, consistent with "
                      "the article (an allegation, not a confirmed fact).")))
    return out


def _aspect(f: Finding, ctx: _Ctx) -> str:
    by = {c.id: c for c in ctx.criteria.criteria}
    rel = [r for r in f.relevance if r in ctx.enabled] or list(f.relevance)
    for r in rel:
        cr = by.get(r)
        if cr is not None and cr.kind in CRITERION_ASPECT:
            return CRITERION_ASPECT[cr.kind]
    if f.id == "g:pricing":
        return "practical"
    if f.id == "f:fit:topics":
        return "content_fit"
    return _SECTION_ASPECT.get(f.section, "practical")


def _primary_criterion(f_rel: list[str], ctx: _Ctx) -> Criterion | None:
    for r in f_rel:
        if r in ctx.enabled:
            return ctx.enabled[r]
    return None


def _why(f: Finding, tier: str, reason: str, aspect: str, ctx: _Ctx, info: dict | None) -> dict[str, str]:
    bt = ctx.bt
    if tier == "less":
        rs = {
            "labeled": i18n("značka není na vašem seznamu konkurentů a post je označený",
                            "the brand is not on your competitor list and the post is labeled"),
            "mention": i18n("jen zmínka bez známek spolupráce", "a mention only, no sign of a collaboration"),
            "basic_pass": i18n("základní kontrola prošla", "this basic check passed"),
        }.get(reason, i18n("nesouvisí s žádným z vašich kritérií", "not linked to any of your criteria"))
        return i18n(f"Pro váš cíl ({bt['cs']}) méně podstatné: {rs['cs']}.",
                    f"Less relevant for your {bt['en']}: {rs['en']}.")
    if reason == "competitor" and f.id in (getattr(ctx, "news_comp", None) or {}):
        names = ctx.news_comp[f.id]
        return i18n(f"Článek spojuje tvůrce s {_join(names, 'cs')}, vaším konkurentem; ověřte to proti záznamu spoluprací.",
                    f"The article ties the creator to {_join(names, 'en')}, your competitor; check it against the collaboration record.")
    if reason == "competitor":
        evs = info["evs"] if info else [e for e in collaboration_evidence(ctx.timeline) if e.is_competitor]
        brands = _brand_names([e for e in evs if e.is_competitor]) or ["?"]
        b_cs, b_en = _join(brands, "cs"), _join(brands, "en")
        return i18n(f"{b_cs} {'jsou vaši konkurenti' if len(brands) > 1 else 'je váš konkurent'}: tvůrce, který je nedávno propagoval, bude pro vás méně věrohodný.",
                    f"{b_en} {'are your competitors' if len(brands) > 1 else 'is your competitor'}: a creator who promoted them recently is less credible for you.")
    cr = _primary_criterion(f.relevance, ctx)
    if cr is not None and (cr.why or {}).get("en", "").strip():
        why = cr.why
        return i18n(f"Pro váš cíl ({bt['cs']}): {why.get('cs') or why.get('en')}",
                    f"For your {bt['en']}: {why.get('en') or why.get('cs')}")
    if reason == "identity":
        return i18n("Tento signál zpochybňuje, že jde o účet, který myslíte; ověřte to před oslovením.",
                    "This signal questions whether this is the account you mean; check it before reaching out.")
    if reason == "allegation":
        return i18n("Médium uvádí obvinění (ne potvrzený fakt); zvažte, jestli je pro vaši kampaň podstatné.",
                    "An outlet reports an allegation (not a confirmed fact); consider whether it matters for your campaign.")
    return dict(_ASPECT_WHY.get(aspect, _ASPECT_WHY["practical"]))


class _Confidence:
    def __init__(self, ctx: _Ctx, by_id: dict[str, Finding], ident: dict[str, IdentityMatch],
                 groups: dict[str, dict]) -> None:
        self.ctx = ctx
        self.by_id = by_id
        self.ident = ident
        self.groups = groups
        self.cache: dict[str, tuple[str, dict[str, str]]] = {}
        m = ctx.candidate.metrics
        self.m = m
        tm = ctx.data.modes.get("topics") or ""
        n_capt = sum(1 for v in (ctx.candidate.topic_labels or {}).values() if v != "unclassified") or (m.posts_analyzed if m else 0)
        if tm in ("llm", "mixed"):
            self.topics = ("medium", i18n(f"AI štítky témat u {n_capt} popisků", f"AI topic labels on {n_capt} captions"))
        else:
            self.topics = ("low", i18n(f"pravidla podle klíčových slov u {n_capt} popisků", f"keyword rules on {n_capt} captions"))
        n_posts = m.posts_analyzed if m else 0
        self.engagement = ("low" if n_posts < 5 else "medium",
                           i18n(f"veřejné počty lajků a komentářů, {n_posts} postů", f"public like and comment counts, {n_posts} posts"))
        n_com = m.comments_analyzed if m else 0
        self.comments = ("medium" if n_com >= 30 else "low",
                         i18n(f"rozpoznání jazyka u {n_com} komentářů", f"language detection on {n_com} comments"))
        n_loc = len(m.local_signals) if m else 0
        self.local = ("medium" if n_loc >= 3 else "low", _B["local"])
        outlets: Counter[str] = Counter()
        for n in ctx.data.news_items:
            if ctx.subjects.get(n.id) == "matched":
                outlets[n.outlet] += 1
        self.news_outlets = len(outlets)

    def check_conf(self, kind: str) -> tuple[str, dict[str, str]]:
        table: dict[str, tuple[str, dict[str, str]]] = {
            "public_account": ("high", _B["profile"]), "followers_range": ("high", _B["profile"]),
            "active_recently": ("high", _B["dates"]), "not_brand_account": ("high", _B["profile"]),
            "language_cs": ("medium", _B["language"]), "topic_share": self.topics, "formats": ("high", _B["media"]),
            "post_frequency": ("high", _B["dates"]), "max_commercial_share": ("medium", _B["commercial"]),
            "min_engagement": self.engagement, "cs_comment_share": self.comments, "local_signal": self.local,
            "max_generic_comments": ("low", _B["generic"]), "no_competitor_collab": ("medium", _B["collab_record"]),
            "discloses_ads": ("medium", _B["commercial"]),
        }
        c, b = table.get(kind, ("medium", _B["profile"]))
        return c, i18n(f"kontrola podle: {b['cs']}", f"check on {b['en']}")

    def of(self, f: Finding) -> tuple[str, dict[str, str]]:
        if f.id in self.cache:
            return self.cache[f.id]
        out = self._of(f)
        self.cache[f.id] = out
        return out

    def _of(self, f: Finding) -> tuple[str, dict[str, str]]:
        fid = f.id
        if f.kind == "gap":
            if fid.startswith("i:"):
                return "low", _B["no_fact"]
            if fid in _NEVER_PUBLIC_GAPS:
                return "high", _B["never_public"]
            if fid.startswith("g:check:"):
                chk = self.ctx.checks.get(fid[len("g:check:"):], {})
                return self.check_conf(chk.get("kind", ""))[0] if chk.get("status") != "unknown" else "medium", _B["not_found"]
            return "medium", _B["not_found"]
        if f.kind == "inference":
            levels = [self.of(self.by_id[b])[0] for b in f.based_on if b in self.by_id]
            order = ("low", "medium", "high")
            c = min(levels, key=order.index) if levels else "low"
            if c == "high":
                c = "medium"
            n = len(f.based_on)
            return c, i18n(f"pravidlový odhad z {n} {'faktu' if n == 1 else 'faktů'}",
                           f"rule-based inference from {n} {'fact' if n == 1 else 'facts'}")
        # facts
        if fid.startswith("f:check:"):
            chk = self.ctx.checks.get(fid[len("f:check:"):], {})
            return self.check_conf(chk.get("kind", ""))
        if fid in ("f:followers", "f:category"):
            return "high", _B["profile"]
        if fid == "f:formats":
            return "high", _B["media"]
        if fid == "f:frequency":
            return "high", _B["dates"]
        if fid in ("f:topics", "f:fit:topics"):
            return self.topics
        if fid == "f:commercial":
            return "medium", _B["commercial"]
        if fid == "f:engagement" or fid.startswith("f:spike:"):
            return self.engagement
        if fid == "f:cs_comments":
            return self.comments
        if fid == "f:generic_comments":
            return "low", _B["generic"]
        if fid == "f:local":
            return self.local
        if fid.startswith("f:collab:"):
            info = self.groups.get(fid)
            kinds = {e.kind for e in info["evs"]} if info else set()
            for k in ("paid_label", "meta_branded", "coauthor"):
                if k in kinds:
                    return "high", _B[k]
            return "medium", _B["caption"]
        if fid.startswith("f:identity:"):
            m = self.ident.get(fid)
            if m is None:
                return "medium", _B["similar"]
            if m.status == "matched":
                if any(s.supports and _has(s, _BACKLINK_MARKS) for s in m.signals) or (
                        any(s.supports and _has(s, _LINK_MARKS) for s in m.signals)):
                    return "high", _B["linked"]
                if any(s.supports and _has(s, _SITE_MARKS) for s in m.signals):
                    return "high", _B["same_website"]
                return "medium", _B["similar_name"]
            if m.status == "uncertain":
                return "low", _B["similar"]
            against = " ".join(s.signal for s in m.signals if not s.supports)
            if any(w in against for w in ("fan", "fanouš")):
                return "medium", _B["fan"]
            if "region" in against:
                return "medium", _B["region"]
            return "medium", _B["city_bio"]
        if fid in ("f:anchor:website", "f:anchor:company_id"):
            return "high", _B["anchor_found"]
        if fid == "f:anchor:city":
            return "medium", _B["anchor_city_bio"]
        if fid == "f:anchor:city_posts":
            return "low", _B["anchor_city_posts"]
        if fid == "f:anchor:city_other":
            return "medium", _B["city_bio"]
        if fid.startswith("f:news:"):
            nid = fid[len("f:news:"):]
            if self.ctx.subjects.get(nid) == "matched":
                return ("high", _B["news_many"]) if self.news_outlets >= 2 else ("medium", _B["news_one"])
            return "low", _B["name_only"]
        if fid.startswith("f:namesake:"):
            return "medium", _B["namesake"]
        return "medium", _B["profile"]


def _goal_layer_claims(claims: list[ClaimCheck], ctx: _Ctx, llm_ids: set[str], bio_id: str) -> list[ClaimCheck]:
    tl = {e.id: e for e in ctx.timeline}
    words = _CATEGORY_BRAND_WORDS.get(preset_for_brief(ctx.criteria.brief) or "", ())
    out: list[ClaimCheck] = []
    bt = ctx.bt
    by = {c.id: c for c in ctx.criteria.criteria}
    for c in claims:
        kind = _claim_kind(c.claim)
        evs = [tl[e] for e in c.evidence if e in tl]
        kinds: list[str] = []
        if kind in ("exclusive", "partner") or evs:
            kinds.append("no_competitor_collab")
            if any(e.kind in _PAID_KINDS for e in evs):
                kinds.append("discloses_ads")
        if kind == "unpaid":
            kinds.append("discloses_ads")
        if kind == "followers":
            kinds.append("followers_range")
        relevance = [cr.id for cr in ctx.criteria.criteria if cr.enabled and cr.kind in kinds]
        comp = [e for e in evs if e.is_competitor]
        brand = _exclusive_brand(c.claim) if kind == "exclusive" else None
        cat_match = bool(brand and words and any(w in fold(brand) for w in words))
        if cat_match:
            tier = "key"
            why = i18n(f"Exkluzivita s @{brand}, která podle názvu vypadá jako firma ve vašem oboru (odhad podle jména), může spolupráci s vámi vyloučit.",
                       f"An exclusivity deal with @{brand}, which looks like a business in your category (name match, a guess), may rule out working with you.")
        elif c.status == "conflicts_with_record" and (relevance or comp):
            tier = "key"
            why = None
        else:
            tier = "related"
            why = None
        if why is None:
            if comp:
                names = _brand_names(comp)
                one = len(names) <= 1
                why = i18n(f"{_join(names, 'cs')} {'je váš konkurent' if one else 'jsou vaši konkurenti'}: tvůrce, který je nedávno propagoval, bude pro vás méně věrohodný.",
                           f"{_join(names, 'en')} {'is your competitor' if one else 'are your competitors'}: a creator who promoted them recently is less credible for you.")
            elif kind in ("exclusive", "partner"):
                # the brand is not one of the owner's competitors: the competitor criterion's text
                # (which names the competitors) would explain it with the wrong brands
                label = f"@{brand}" if brand else (_join(_brand_names(evs), "en") if evs else "")
                if c.status == "conflicts_with_record" or not label:
                    why = i18n("Tvůrce tvrdí něco jiného, než ukazuje záznam: zeptejte se na to při první schůzce.",
                               "The creator says something the record does not show: ask about it at the first meeting.") \
                        if c.status == "conflicts_with_record" else dict(_ASPECT_WHY["competitors"])
                else:
                    why = i18n(f"Tvůrce spolupracuje s {label}; zeptejte se, jestli to nevylučuje jiné značky.",
                               f"The creator works with {label}; ask whether that rules out other brands.")
            else:
                cr = next((by[r] for r in relevance if r in by and by[r].kind != "no_competitor_collab"), None)
                if cr is not None and (cr.why or {}).get("en", "").strip():
                    why = i18n(f"Pro váš cíl ({bt['cs']}): {cr.why.get('cs') or cr.why.get('en')}",
                               f"For your {bt['en']}: {cr.why.get('en') or cr.why.get('cs')}")
                elif c.status == "conflicts_with_record":
                    why = i18n("Tvůrce tvrdí něco jiného, než ukazuje záznam: zeptejte se na to při první schůzce.",
                               "The creator says something the record does not show: ask about it at the first meeting.")
                else:
                    why = dict(_ASPECT_WHY["competitors"])
        aspect = next((CRITERION_ASPECT[by[r].kind] for r in relevance if r in by and by[r].kind in CRITERION_ASPECT),
                      "competitors")
        if c.id in llm_ids:
            basis = _B["llm_claim"]
        elif kind == "followers":
            basis = _B["followers_claim"]
        else:
            basis = _B["rule_claim"] if c.claim_source.id != bio_id else i18n(
                "vlastní bio vs. záznam spoluprací", "own bio vs. collaboration record")
        out.append(c.model_copy(update={"relevance": relevance, "aspect": aspect, "tier": tier, "why_it_matters": why,
                                        "confidence_basis": basis}))
    return out


# ---------------------------------------------------------------------------------------------
# Questions (6.5)
# ---------------------------------------------------------------------------------------------

_DEMOGRAPHICS_Q = vetting.AUDIENCE_QUESTION
_PRICING_Q = r4_vetting._GAP_QUESTIONS["g:pricing"]


def _questions(rep: Report, ctx: _Ctx, profile) -> list[dict[str, str]]:
    brief = ctx.criteria.brief
    bt = ctx.bt
    checks = ctx.checks
    out: list[dict[str, str]] = []
    try:
        out += vetting.evidence_questions(rep, profile)
    except Exception:
        pass

    def st(kind: str) -> str | None:
        for cid_, c in checks.items():
            if c["kind"] == kind and not c["waived"]:
                return c["status"]
        return None

    goal = vetting._safe_goal(brief.goal)
    goal_en = goal
    if goal:
        out.append(i18n(f"Náš cíl je {goal}. Hodil by se vám v příštích týdnech post nebo krátké video o naší firmě ({bt['cs']})?",
                        f"Our goal is {goal_en}. Would a post or short video about our {bt['en']} fit your plans for the coming weeks?"))
    else:
        out.append(i18n(f"Hodil by se vám v příštích týdnech post nebo krátké video o naší firmě ({bt['cs']})?",
                        f"Would a post or short video about our {bt['en']} fit your plans for the coming weeks?"))
    topic_crit = next((c for c in ctx.criteria.criteria if c.enabled and c.kind == "topic_share"), None)
    if st("topic_share") in ("fail", "unknown") and topic_crit is not None:
        topics = topics_mod.counted_topics([t for t in (topic_crit.params.get("topics") or []) if isinstance(t, str)])
        t_cs = _join_or([r4_vetting.TOPIC_CS_NOM.get(t, t) for t in topics], "cs")
        t_en = _join_or([r4_vetting.TOPIC_EN_NOM.get(t, t) for t in topics], "en")
        if st("topic_share") == "fail":
            out.append(i18n(f"Udělal(a) byste post o naší firmě ({bt['cs']}), i když témata {t_cs} nejsou vaše hlavní?",
                            f"Would you make a post about our {bt['en']} even though {t_en} are not your main topic?"))
        else:  # unknown: we could not read the posts, so we do not claim what the topics are
            out.append(i18n(f"O jakých tématech nejčastěji tvoříte a hodilo by se k vašemu profilu téma {t_cs}?",
                            f"What topics do you mostly post about, and would {t_en} fit your profile?"))
    city = brief.city or ctx.criteria.discovery.city
    if st("local_signal") in ("fail", "unknown") and city:
        out.append(i18n(f"Kolik vašich sledujících je z města {city}? Můžete poslat statistiku měst z aplikace?",
                        f"How many of your followers are in {city}? Could you share the city statistics from the app?"))
    if st("formats") == "fail":
        out.append(i18n(f"Natočil(a) byste u nás krátké video ({bt['cs']})?",
                        f"Would you film a short video at our {bt['en']}?"))
    comp = [e for e in collaboration_evidence(ctx.timeline) if e.is_competitor]
    if comp:
        latest = max(comp, key=lambda e: (e.date is not None, e.date.isoformat() if e.date else ""))
        key = normalize_brand(latest.brand_handle or latest.brand)
        same = [e for e in comp if normalize_brand(e.brand_handle or e.brand) == key]
        brand = (_brand_names(same) or [latest.brand])[0]
        out.append(i18n(f"Spolupracoval(a) jste s {brand} ({fmt_date(latest.date, 'cs')}). Běží to ještě a je v tom exkluzivita?",
                        f"You worked with {brand} ({fmt_date(latest.date, 'en')}). Is that still running, and does it include exclusivity?"))
    has_evidence_q = any("ad label" in (q.get("en") or "") for q in out)
    if st("discloses_ads") == "fail" and not has_evidence_q:  # the evidence question already asks it
        n = len(undisclosed_posts(ctx.timeline))
        out.append(i18n(f"Jak označujete placené posty? Našli jsme {n} {'post' if n == 1 else ('posty' if n < 5 else 'postů')} se značkou bez označení reklamy.",
                        f"How do you label paid posts? We found {n} {'post' if n == 1 else 'posts'} with a brand and no ad label."))
    if st("max_commercial_share") == "fail":
        out.append(i18n("Kolik placených postů měsíčně zveřejňujete?", "How many paid posts do you publish a month?"))
    if st("followers_range") == "fail" and brief.budget_hint and vetting._safe_text(brief.budget_hint):
        out.append(i18n(f"Náš rozpočet je {brief.budget_hint}. Odpovídá to tomu, jak spolupráci oceňujete?",
                        f"Our budget is {brief.budget_hint}. Does that fit how you price a collaboration?"))
    gaps = [f for f in rep.findings if f.kind == "gap"]
    out += [dict(q) for q in (ctx.data.llm_questions or vetting.template_questions(gaps))]
    tail = [dict(_DEMOGRAPHICS_Q), dict(_PRICING_Q)]
    seen: set[str] = set()
    core: list[dict[str, str]] = []
    tail_keys = {fold(q["cs"]) for q in tail}
    for q in out:
        k = fold(q.get("cs", ""))
        if not k or k in seen or k in tail_keys:
            continue
        if not vetting._safe_text(q.get("cs", ""), q.get("en", "")):
            continue
        seen.add(k)
        core.append({"cs": q.get("cs", ""), "en": q.get("en", "") or q.get("cs", "")})
    return core[: 8 - len(tail)] + tail


# ---------------------------------------------------------------------------------------------
# Ordering, sections, summary
# ---------------------------------------------------------------------------------------------

def _order(rep: Report) -> None:
    items: dict[str, list[tuple[str, str, int]]] = {}
    for i, f in enumerate(rep.findings):
        items.setdefault(f.section, []).append((f.id, f.tier or "less", i))
    for i, c in enumerate(rep.claims):
        items.setdefault("claims", []).append((c.id, c.tier or "related", 10_000 + i))

    def key_count(sec: str) -> int:
        return sum(1 for _, t, _ in items.get(sec, []) if t == "key")

    present = [s for s in items if items[s]]
    head = [s for s in ("identity", "goal") if s in present]
    rest = [s for s in present if s not in head]
    default = {s: i for i, s in enumerate(DEFAULT_SECTION_ORDER)}
    rest.sort(key=lambda s: (-key_count(s), default.get(s, 99), s))
    sections: list[ReportSection] = []
    less_all: list[str] = []
    expanded_order: list[str] = []
    for sec in head + rest:
        its = items[sec]
        shown = [x for x in its if x[1] != "less"]
        shown.sort(key=lambda x: (-TIER_RANK[x[1]], x[2]))
        less = [x[0] for x in sorted((x for x in its if x[1] == "less"), key=lambda x: x[2])]
        top = max((TIER_RANK[x[1]] for x in its), default=0)
        tier = next(t for t, r in TIER_RANK.items() if r == top)
        sections.append(ReportSection(id=sec, title=dict(SECTION_TITLES.get(sec, i18n(sec, sec))), tier=tier,  # type: ignore[arg-type]
                                      item_ids=[x[0] for x in shown], less_ids=less))
        expanded_order += [x[0] for x in shown]
        less_all += less
    rep.sections = sections
    rep.less_relevant = less_all
    pos = {fid: i for i, fid in enumerate(expanded_order + less_all)}
    rep.findings = sorted(rep.findings, key=lambda f: pos.get(f.id, 10**6))
    status_rank = {"conflicts_with_record": 0, "unsupported": 1, "cannot_verify": 2, "supported": 3}
    orig = {c.id: i for i, c in enumerate(rep.claims)}
    rep.claims = sorted(rep.claims, key=lambda c: (-TIER_RANK.get(c.tier or "related", 1), status_rank.get(c.status, 9), orig[c.id]))

    by_id: dict[str, Any] = {f.id: f for f in rep.findings} | {c.id: c for c in rep.claims}
    key_items = [by_id[i] for i in expanded_order if getattr(by_id.get(i), "tier", None) == "key"]
    # one line per aspect: "f:fit:topics" repeats the topic_share check (same aspect), and so on
    seen_aspects: set[str] = set()
    picked: list[Any] = []
    for it in key_items:
        asp = getattr(it, "aspect", None) or getattr(it, "id", "")
        if asp in seen_aspects:
            continue
        seen_aspects.add(asp)
        picked.append(it)
    key_items = picked
    if key_items:
        parts = {lg: [] for lg in ("cs", "en")}
        for it in key_items[:3]:
            for lg in ("cs", "en"):
                if isinstance(it, ClaimCheck):
                    txt = (it.note or {}).get(lg) or it.claim
                else:
                    txt = it.text.get(lg) or it.text.get("cs", "")
                # a quoted bio / caption in parentheses is evidence, not the verdict: drop it here so the
                # clip never cuts the verdict ("... does not meet it"); the finding below keeps the quote
                txt = re.sub(r"\s*\([^()]*[\"„“”][^()]*\)", "", txt)
                parts[lg].append(_clip_words(txt, 200).rstrip(" .;"))
        rep.summary = i18n("Klíčové pro tento cíl: " + "; ".join(parts["cs"]) + ".",
                           "Key for this goal: " + "; ".join(parts["en"]) + ".")
    else:
        rep.summary = i18n("Pro tento cíl nic zásadního nevystupuje; podrobnosti jsou níže.",
                           "Nothing stands out for this goal; the details are below.")


# ---------------------------------------------------------------------------------------------
# Method ("How this report was built")
# ---------------------------------------------------------------------------------------------

_PLAT = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube"}
_MODE_TXT = {"mock": i18n("ukázková data (mock)", "mock data"), "cache": i18n("uložená data (cache)", "cached data"),
             "live": i18n("živě z Apify", "live from Apify")}
_SOURCE_TXT = {"llm+rules": i18n("AI + pravidla", "AI + rules"), "rules": i18n("pravidla", "rules"),
               "llm": i18n("AI", "AI"), "llm+template": i18n("AI + šablona", "AI + template"),
               "template": i18n("šablona", "template")}


def _method(rep: Report, candidate: Candidate, data: VettingData, anchor: Anchor | None, brief: Brief,
            bt: dict[str, str], lang: str, *, news_aside: int = 0, unrelated_news: int = 0) -> list[dict[str, str]]:
    from app.compute.subject import anchor_text

    lines: list[dict[str, str]] = []
    h = candidate.ref.handle
    plat = _PLAT.get(candidate.ref.platform, candidate.ref.platform)
    if "manual" in candidate.ref.found_via:
        a_cs, a_en = anchor_text(anchor, "cs"), anchor_text(anchor, "en")
        lines.append(i18n(f"Prověřujeme @{h}, kterého jste zadali; našli jsme veřejný profil na {plat}u."
                          + (f" Kotva: {a_cs}." if a_cs else " Kotvu jste nezadali."),
                          f"We checked @{h}, the creator you named; we found the public {plat} profile."
                          + (f" Anchor: {a_en}." if a_en else " No anchor was given.")))
    else:
        via = candidate.ref.found_via[0] if candidate.ref.found_via else "?"
        lines.append(i18n(f"@{h} ({plat}) jsme našli ve vyhledávání ({via}).", f"@{h} ({plat}) was found in the search ({via})."))
    modes = Counter(p.source.mode for p in data.posts)
    if candidate.profile is not None:
        modes[candidate.profile.source.mode] += 1
    mode = modes.most_common(1)[0][0] if modes else "mock"
    mt = _MODE_TXT.get(mode, i18n(mode, mode))
    c = data.counts
    n_posts, n_com = c.get("posts", len(data.posts)), c.get("comments", 0)
    n_cross, n_meta = c.get("cross", len(data.cross_profiles)), c.get("collabs_provider", len(data.provider_collabs))
    n_news = c.get("news", len(data.news_items))
    n_about = len(data.news_items) - news_aside
    about_cs = f", z toho o tvůrci {n_about}" if n_news else ""
    about_en = f", {n_about} of them about this creator" if n_news else ""
    lines.append(i18n(
        f"Načteno: profil, {_cs_n(n_posts, 'post', 'posty', 'postů')}, {_cs_n(n_com, 'komentář', 'komentáře', 'komentářů')}, "
        f"{_cs_n(n_cross, 'účet', 'účty', 'účtů')} na jiných sítích, {_cs_n(n_meta, 'záznam', 'záznamy', 'záznamů')} "
        f"z knihovny značkového obsahu Meta, {_cs_n(n_news, 'zpráva', 'zprávy', 'zpráv')}{about_cs} ({mt['cs']}).",
        f"Fetched: the profile, {_en_n(n_posts, 'post')}, {_en_n(n_com, 'comment')}, "
        f"{_en_n(n_cross, 'account')} on other platforms, {_en_n(n_meta, 'Meta branded-content record')}, "
        f"{_en_n(n_news, 'news item')}{about_en} ({mt['en']})."))
    n = candidate.sensitive_filtered
    lines.append(i18n(f"Vyřazeno před uložením: {_cs_n(n, 'položka', 'položky', 'položek')} s citlivým obsahem (jen počet).",
                      f"Filtered before storage: {_en_n(n, 'item')} on sensitive topics (count only)."))
    v = rep.identity_verdict
    if v is not None:
        k = len(v.supporting)
        sa_cs = "; ".join(s.label for s in v.set_aside)
        sa_en = sa_cs
        if unrelated_news:
            un = _unrelated_news_text(unrelated_news, h)
            sa_cs = "; ".join(x for x in (sa_cs, un["cs"]) if x)
            sa_en = "; ".join(x for x in (sa_en, un["en"]) if x)
        kc = len(getattr(v, "contradicting", None) or [])
        con_cs = f", {_cs_n(kc, 'protichůdný signál', 'protichůdné signály', 'protichůdných signálů')}" if kc else ""
        con_en = f", {_en_n(kc, 'contradicting signal')}" if kc else ""
        lines.append(i18n(f"Identita: {_cs_n(k, 'podpůrný signál', 'podpůrné signály', 'podpůrných signálů')}{con_cs}; stranou: {sa_cs or 'nic'}.",
                          f"Identity: {_en_n(k, 'supporting signal')}{con_en}; set aside: {sa_en or 'nothing'}."))
    lines.append(i18n("Každý fakt má odkaz na zdroj; odhady říkají, o jaká fakta se opírají; mezery říkají, co jsme ověřit nemohli.",
                      "Every fact links to its source; inferences say which facts they rest on; gaps say what we could not check."))
    city = brief.city
    nl = len(rep.less_relevant)
    lines.append(i18n(f"Seřazeno pro váš cíl: {bt['cs']}{(', ' + city) if city else ''}. Jako méně podstatné je sbaleno: {nl}.",
                      f"Ordered for your goal: {bt['en']}{(' in ' + city) if city else ''}. "
                      f"{_en_n(nl, 'finding')} {'is' if nl == 1 else 'are'} collapsed as less relevant."))
    ts = rep.text_source
    def s(k: str, lg: str) -> str:
        return _SOURCE_TXT.get(ts.get(k, ""), i18n(ts.get(k, "?"), ts.get(k, "?")))[lg]
    spent = bool(data.counts.get("llm_budget_exhausted"))
    lines.append(i18n(
        f"Tvrzení: {s('claims', 'cs')} · Štítky zpráv: {s('news', 'cs')} · Kontrola skeptika: {s('skeptic', 'cs')} · "
        f"Otázky: {s('questions', 'cs')} · Koncept zprávy: {s('outreach', 'cs')}."
        + (" Rozpočet AI dotazů byl vyčerpaný, proto pravidla." if spent else "")
        + " Změna cíle report přeřadí a přepíše z už načtených dat: žádné nové dotazy.",
        f"Claims: {s('claims', 'en')} · News labels: {s('news', 'en')} · Skeptic: {s('skeptic', 'en')} · "
        f"Questions: {s('questions', 'en')} · Outreach: {s('outreach', 'en')}."
        + (" The AI request budget was used up, so these use rules." if spent else "")
        + " Switching the goal re-orders and rewrites this report from the data already fetched: no new requests."))
    return lines


# ---------------------------------------------------------------------------------------------
# diff_reports (pure)
# ---------------------------------------------------------------------------------------------

def _goal_of(rep: Report) -> dict[str, str]:
    rf = rep.rendered_for or {}
    return {"business_type": rf.get("business_type") or rep.vetted_for or "", "goal": rf.get("goal", ""),
            "brief_key": rf.get("brief_key", "")}


def _tiers(rep: Report) -> dict[str, str]:
    out = {f.id: (f.tier or "related") for f in rep.findings}
    out.update({c.id: (c.tier or "related") for c in rep.claims})
    return out


def _comp_brands(rep: Report) -> list[str]:
    return _brand_names([e for e in collaboration_evidence(rep.collab_timeline) if e.is_competitor])


_CS_GEN = {"pekarna": "pekárny", "kavarna": "kavárny", "cukrarna": "cukrárny", "posilovna": "posilovny",
           "fitness studio": "fitness studia", "fitness": "fitness", "restaurace": "restaurace", "bistro": "bistra",
           "pekarstvi": "pekařství", "kadernictvi": "kadeřnictví", "jogove studio": "jógového studia"}


def cs_accusative(bt: str) -> str:
    """Czech accusative after "na" / "pro" for a business type ("pekárna" -> "pekárnu", "malá kavárna" ->
    "malou kavárnu"); neuter and masculine inanimate types ("fitness studio", "bistro") stay as they are."""
    words = " ".join((bt or "").split()).split(" ")
    out = []
    for i, w in enumerate(words):
        lf = fold(w)
        if i < len(words) - 1 and w.endswith("á"):
            w = w[:-1] + "ou"
        elif re.search(r"[^aeiouy]a$", lf) and not lf.endswith(("ca", "ja")):
            w = w[:-1] + "u"
        out.append(w)
    return " ".join(out)


def _cs_genitive(bt: str) -> str | None:
    """Czech genitive after "z" for a business type ("pekárna" -> "pekárny", "fitness studio" ->
    "fitness studia"); None when unsure (the caller then writes "pekárna → fitness studio")."""
    t = " ".join((bt or "").split())
    if not t:
        return None
    if fold(t) in _CS_GEN:
        return _CS_GEN[fold(t)]
    words = t.split(" ")
    if any(w[-1:] in "áýéíÁÝÉÍ" for w in words[:-1]):
        return None   # an adjective in front would need its own case
    last = words[-1]
    lf = fold(last)
    if re.search(r"[^aeiouy]a$", lf) and not lf.endswith(("ca", "ja")):
        last = last[:-1] + "y"
    elif lf.endswith(("io", "ro", "no", "lo", "to")):
        last = last[:-1] + "a"
    elif lf.endswith(("ce", "ni", "vi", "tvi")):
        pass
    else:
        return None
    return " ".join(words[:-1] + [last])


def diff_reports(before: Report, after: Report) -> ReportDiff:
    """What changed between two renders of the same candidate's report (pure)."""
    tb, ta = _tiers(before), _tiers(after)
    added = [i for i in ta if i not in tb]
    removed = [i for i in tb if i not in ta]
    up = [i for i in ta if i in tb and TIER_RANK.get(ta[i], 1) > TIER_RANK.get(tb[i], 1)]
    collapsed = [i for i in ta if i in tb and ta[i] == "less" and tb[i] != "less"]
    # every change is listed once: a finding that collapsed into "less relevant" is not also "moved down"
    down = [i for i in ta if i in tb and TIER_RANK.get(ta[i], 1) < TIER_RANK.get(tb[i], 1) and i not in collapsed]
    # same tier, other words: the text of a finding rewritten for the new goal ("9 of 9 food" -> "0 of 9 fitness")
    fb = {f.id: f for f in before.findings}
    chb, cha = before.checks or {}, after.checks or {}
    status_changed = {k for k in set(chb) | set(cha) if chb.get(k) != cha.get(k)}
    # a check row whose status changed is listed under checks_changed; one that kept its status but
    # now reads differently ("3 of 9 posts about food" -> "0 of 9 posts about fitness") is reworded
    text_changed = [f.id for f in after.findings if f.id in fb and f.id not in collapsed and f.id not in up
                    and f.id not in down and (fb[f.id].text or {}).get("en") != (f.text or {}).get("en")
                    and not (f.id.startswith(("f:check:", "g:check:")) and f.id.split(":", 2)[-1] in status_changed)]
    cb = {c.id: c for c in before.claims}
    claims_changed = []
    for c in after.claims:
        p = cb.get(c.id)
        if p is not None and (p.status != c.status or (p.tier or "related") != (c.tier or "related")):
            claims_changed.append({"id": c.id, "status": [p.status, c.status], "tier": [p.tier, c.tier]})
    checks_changed = [{"criterion_id": k, "status": [chb.get(k), cha.get(k)]}
                      for k in list(dict.fromkeys(list(chb) + list(cha))) if chb.get(k) != cha.get(k)]
    qb = {fold(q.get("cs", "")) for q in before.questions}
    qa = {fold(q.get("cs", "")) for q in after.questions}
    q_added = [q for q in after.questions if fold(q.get("cs", "")) not in qb]
    q_removed = [q for q in before.questions if fold(q.get("cs", "")) not in qa]
    outreach_changed = (before.outreach_draft or None) != (after.outreach_draft or None)
    became_key = [i for i in ta if ta[i] == "key" and tb.get(i) != "key"]
    left_key = [i for i in tb if tb[i] == "key" and i in ta and ta[i] != "key"]
    sb = {fold(n.get("cs", "") or n.get("en", "")) for n in before.skeptic_notes}
    sa = {fold(n.get("cs", "") or n.get("en", "")) for n in after.skeptic_notes}
    sk_added = [n for n in after.skeptic_notes if fold(n.get("cs", "") or n.get("en", "")) not in sb]
    sk_removed = [n for n in before.skeptic_notes if fold(n.get("cs", "") or n.get("en", "")) not in sa]
    # the AI skeptic notes are stored per goal: a goal with none of its own keeps only the rule checks
    ai_skeptic_gone = (before.text_source or {}).get("skeptic") == "llm+rules" and (after.text_source or {}).get("skeptic") == "rules"

    fg, tg = _goal_of(before), _goal_of(after)
    new_comp = [b for b in _comp_brands(after) if b not in _comp_brands(before)]
    parts: dict[str, list[str]] = {"cs": [], "en": []}
    def cz(n: int, one: str, few: str, many: str) -> str:
        return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"

    if became_key:
        n = len(became_key)
        why_cs = why_en = ""
        if new_comp:
            why_cs = f" ({_join(new_comp, 'cs')} {'je' if len(new_comp) == 1 else 'jsou'} teď {'konkurent' if len(new_comp) == 1 else 'konkurenti'})"
            why_en = f" ({_join(new_comp, 'en')} {'is now a competitor' if len(new_comp) == 1 else 'are now competitors'})"
        parts["cs"].append(cz(n, "zjištění je teď klíčové", "zjištění jsou teď klíčová", "zjištění je teď klíčových") + why_cs)
        parts["en"].append(f"{n} {'finding' if n == 1 else 'findings'} became key{why_en}")
    demoted = [i for i in left_key if i not in collapsed]   # key -> less is told by "moved to less relevant"
    if demoted:
        n = len(demoted)
        parts["cs"].append(cz(n, "zjištění už není klíčové", "zjištění už nejsou klíčová", "zjištění už není klíčových"))
        parts["en"].append(f"{n} {'finding is' if n == 1 else 'findings are'} no longer key")
    if collapsed:
        n = len(collapsed)
        parts["cs"].append(cz(n, "zjištění přesunuto mezi méně podstatná", "zjištění přesunuta mezi méně podstatná",
                              "zjištění přesunuto mezi méně podstatná"))
        parts["en"].append(f"{n} moved to less relevant")
    new_other = [i for i in added if ta[i] != "key"]
    if new_other:
        n = len(new_other)
        parts["cs"].append(cz(n, "nové zjištění", "nová zjištění", "nových zjištění"))
        parts["en"].append(f"{n} new {'finding' if n == 1 else 'findings'}")
    if removed:
        n = len(removed)
        parts["cs"].append(cz(n, "zjištění odpadlo", "zjištění odpadla", "zjištění odpadlo"))
        parts["en"].append(f"{n} {'finding' if n == 1 else 'findings'} dropped")
    if text_changed:
        n = len(text_changed)
        parts["cs"].append(cz(n, "zjištění přepsáno pro nový cíl", "zjištění přepsána pro nový cíl", "zjištění přepsáno pro nový cíl"))
        parts["en"].append(f"{n} {'finding' if n == 1 else 'findings'} reworded for the goal")
    if claims_changed:
        n = len(claims_changed)
        parts["cs"].append(cz(n, "tvrzení se změnilo", "tvrzení se změnila", "tvrzení se změnilo"))
        parts["en"].append(f"{n} {'claim' if n == 1 else 'claims'} changed")
    if checks_changed:
        n = len(checks_changed)
        parts["cs"].append(cz(n, "kontrola dopadla jinak", "kontroly dopadly jinak", "kontrol dopadlo jinak"))
        parts["en"].append(f"{n} {'check' if n == 1 else 'checks'} changed")
    if q_added:
        n = len(q_added)
        parts["cs"].append(f"{n} {'nová otázka' if n == 1 else ('nové otázky' if n < 5 else 'nových otázek')}")
        parts["en"].append(f"{n} new {'question' if n == 1 else 'questions'}")
    if outreach_changed:
        parts["cs"].append("koncept zprávy přepsán")
        parts["en"].append("outreach draft rewritten")
    if ai_skeptic_gone:
        parts["cs"].append("poznámky AI skeptika patřily předchozímu cíli, zůstaly jen kontroly pravidly")
        parts["en"].append("the AI skeptic notes belonged to the previous goal, only the rule checks remain")
    elif sk_removed:
        n = len(sk_removed)
        parts["cs"].append(f"{n} {'poznámka skeptika odpadla' if n == 1 else 'poznámky skeptika odpadly' if n < 5 else 'poznámek skeptika odpadlo'}")
        parts["en"].append(f"{n} skeptic {'note' if n == 1 else 'notes'} dropped")
    if sk_added:
        n = len(sk_added)
        parts["cs"].append(f"{n} {'nová poznámka skeptika' if n == 1 else 'nové poznámky skeptika' if n < 5 else 'nových poznámek skeptika'}")
        parts["en"].append(f"{n} new skeptic {'note' if n == 1 else 'notes'}")
    goal_changed = fg.get("brief_key") != tg.get("brief_key")
    f_cs, t_cs = fg["business_type"] or "?", tg["business_type"] or "?"
    f_en, t_en = business_en(f_cs), business_en(t_cs)
    if not parts["en"]:
        summary = i18n("Report je pro tento cíl stejný.", "The report is the same for this goal.")
    elif goal_changed and (f_cs != t_cs):
        g_cs = _cs_genitive(f_cs)
        head_cs = f"Cíl změněn z {g_cs} na {cs_accusative(t_cs)}" if g_cs else f"Cíl změněn: {f_cs} → {t_cs}"
        summary = i18n(head_cs + ": " + ", ".join(parts["cs"]) + ".",
                       f"Goal changed from {f_en} to {t_en}: " + ", ".join(parts["en"]) + ".")
    elif goal_changed:
        summary = i18n("Cíl upraven: " + ", ".join(parts["cs"]) + ".", "Goal updated: " + ", ".join(parts["en"]) + ".")
    else:
        summary = i18n("Kritéria změněna: " + ", ".join(parts["cs"]) + ".", "Criteria changed: " + ", ".join(parts["en"]) + ".")
    return ReportDiff(
        candidate_id=after.candidate_id, from_goal=fg, to_goal=tg, added=added, removed=removed, moved_up=up,
        moved_down=down, collapsed=collapsed, claims_changed=claims_changed, checks_changed=checks_changed,
        questions_added=q_added, questions_removed=q_removed, outreach_changed=outreach_changed, left_key=left_key,
        skeptic_added=sk_added, skeptic_removed=sk_removed, text_changed=text_changed, summary=summary,
    )
