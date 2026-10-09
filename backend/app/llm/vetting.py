"""Round-4 LLM tasks. Each has a deterministic fallback and calls record_mode("vetting", ...).

The LLM may only reference evidence ids it is given; it may not introduce facts. Every LLM output is
validated in code: ids that were not in the input are dropped, verbatim quotes are checked against
the source text, statuses that lose their evidence are downgraded, and the deterministic rules run
as a floor (an LLM answer can add caution, never remove it).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from app.llm import client as llm_client
from app.llm import prompts
from app.llm.sensitive import keyword_flags, refusal_reason
from app.llm.text import (
    FORMAT_LABELS, TOPIC_ABOUT_CS, TOPIC_LABELS, business_en, clip, cs_locative, fmt_date, fmt_int, fold,
)
from app.models import (
    Brief, Candidate, ClaimCheck, CollabEvidence, Finding, NewsFinding, NewsItem, Post, Profile, Report,
    SourceRef, greeting_name, i18n, iter_source_refs, person_name, short_hash,
)

TASK = "vetting"

# Attribution suffix for news whose subject may be a namesake (compute.identity.news_subject ==
# "uncertain"); the skeptic turns it into a note.
UNCERTAIN_MARK = " (možná jiná osoba se stejným jménem)"
UNCERTAIN_MARK_EN = " (possibly a different person with the same name)"

_CONF_ORDER = ("low", "medium", "high")

_KIND_WORDS: dict[str, tuple[str, str]] = {
    "coauthor": ("společný post se značkou", "co-authored post with the brand"),
    "mention": ("zmínka značky", "brand mention"),
    "tag": ("označení značky na fotce", "brand tag"),
    "ad_hashtag": ("reklamní hashtag", "ad hashtag"),
    "discount_code": ("slevový kód", "discount code"),
    "paid_label": ("štítek placené spolupráce", "paid-partnership label"),
    "meta_branded": ("záznam v knihovně reklam Meta", "Meta branded-content record"),
    "affiliate_link": ("affiliate odkaz", "affiliate link"),
}
_PAID_KINDS = {"discount_code", "paid_label", "ad_hashtag", "affiliate_link", "meta_branded"}


def _norm_brand(v: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(v or ""))


def _lower(conf: str) -> str:
    i = _CONF_ORDER.index(conf) if conf in _CONF_ORDER else 1
    return _CONF_ORDER[max(0, i - 1)]


def _safe_text(*texts: str) -> bool:
    """Generated text must not carry sensitive content or person-scoring language."""
    return not any(keyword_flags(list(texts))) and not any(refusal_reason(t) for t in texts)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|\s+[|•·]\s+", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def _quote_ref(src: SourceRef, quote: str) -> SourceRef:
    return src.model_copy(update={"quote": clip(quote, 200)})


def _collab_summary(ev: list[CollabEvidence], lang: str) -> str:
    items = []
    for c in ev[:4]:
        words = _KIND_WORDS.get(c.kind, (c.kind, c.kind))[0 if lang == "cs" else 1]
        items.append(f"{c.brand} ({words}, {fmt_date(c.date, lang)})")
    more = len(ev) - len(items)
    s = "; ".join(items)
    if more > 0:
        s += f"; +{more}"
    return s


def _cs_plural(n: int, one: str, few: str, many: str) -> str:
    return one if n == 1 else (few if 2 <= n <= 4 else many)


def _day(dt, lang: str) -> str:
    if dt is None:
        return "?"
    return f"{dt.day}. {dt.month}." if lang == "cs" else fmt_date(dt, "en")  # "29 Sep 2026", as elsewhere


def post_groups(evidence: list[CollabEvidence]) -> dict[str, list[CollabEvidence]]:
    """Group evidence rows by post: one post can yield coauthor + ad hashtag + paid label + a Meta
    record. A row without a post id joins a post of the same brand on the same day."""
    groups: dict[str, list[CollabEvidence]] = {}
    by_brand_day: dict[tuple[str, object], str] = {}
    for e in evidence:
        if e.post_id:
            groups.setdefault(e.post_id, []).append(e)
            if e.date:
                by_brand_day[(_norm_brand(e.brand_handle or e.brand), e.date.date())] = e.post_id
    for e in evidence:
        if e.post_id:
            continue
        key = by_brand_day.get((_norm_brand(e.brand_handle or e.brand), e.date.date() if e.date else None)) or e.id
        groups.setdefault(key, []).append(e)
    return groups


def _brand_list(evidence: list[CollabEvidence]) -> str:
    seen: dict[str, str] = {}
    for e in evidence:
        if not e.brand or e.brand == "unknown":
            continue
        k = _norm_brand(e.brand_handle or e.brand)
        label = f"@{e.brand_handle}" if e.brand_handle else e.brand
        if k not in seen or (label.startswith("@") and not seen[k].startswith("@")):
            seen[k] = label
    return ", ".join(seen.values()) or "?"


# --------------------------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------------------------

_RX_EXCLUSIVE = re.compile(
    r"(exkluzivni|exclusive)\s+(ambasador\w*|ambassador\w*|partner\w*|tvar\w*|face)\s*"
    r"(?:(?:of|for|pro|znacky)\s+)?@?([a-z0-9_.]+)"
)
_RX_PARTNER = re.compile(
    r"(spolupracuj\w*|partner\w*|ambasador\w*|ambassador\w*)\s+(?:(?:s|se|with|pro|for|znacky)\s+)?@([a-z0-9_.]+)"
)
_RX_UNPAID = re.compile(
    r"nikdo mi (neplat|nezaplat)|neplacen|nejsem placen|neni (to )?(reklama|placen)|bez reklamy|"
    r"\bnot (paid|sponsored)\b|nobody pays|no one pays|not an ad\b|\bunpaid\b|nesponzorovan|"
    r"z vlastni kapsy|za sve penize|recenze,? (kterou )?nikdo"
)
_RX_FOLLOWERS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(k|tis\.?|tisic\w*)?\s*(sledujicich|followeru|followers|fanousku)"
)


def _claim_id(handle: str, kind: str, key: str, src_id: str) -> str:
    return f"claim:{handle}:{short_hash(f'{kind}|{key}|{src_id}')}"


def _fallback_claims(profile: Profile, posts: list[Post], collabs: list[CollabEvidence]) -> list[ClaimCheck]:
    out: list[ClaimCheck] = []
    seen: set[str] = set()
    sources: list[tuple[str, SourceRef, str | None]] = [(profile.bio or "", profile.source, None)]
    sources += [(p.caption or "", p.source, p.id) for p in posts]

    for text, src, post_id in sources:
        for sent in _sentences(text):
            f = fold(sent)
            m_ex = _RX_EXCLUSIVE.search(f)
            if m_ex:
                brand = m_ex.group(3).strip(".")
                cid = _claim_id(profile.handle, "exclusive", brand, src.id)
                if cid not in seen:
                    seen.add(cid)
                    out.append(_check_exclusive(cid, sent, src, brand, collabs))
                continue
            m_pa = _RX_PARTNER.search(f)
            if m_pa:
                brand = m_pa.group(2).strip(".")
                cid = _claim_id(profile.handle, "partner", brand, src.id)
                if cid not in seen:
                    seen.add(cid)
                    out.append(_check_partner(cid, sent, src, brand, collabs))
            if _RX_UNPAID.search(f):
                cid = _claim_id(profile.handle, "unpaid", "", src.id)
                if cid not in seen:
                    seen.add(cid)
                    out.append(_check_unpaid(cid, sent, src, post_id, collabs))
            m_fo = _RX_FOLLOWERS.search(f)
            if m_fo and post_id is None:
                cid = _claim_id(profile.handle, "followers", m_fo.group(0), src.id)
                if cid not in seen:
                    seen.add(cid)
                    out.append(_check_followers(cid, sent, src, m_fo, profile))
    return out


def _check_exclusive(cid: str, sent: str, src: SourceRef, brand: str, collabs: list[CollabEvidence]) -> ClaimCheck:
    nb = _norm_brand(brand)
    same = [c for c in collabs if nb and nb in (_norm_brand(c.brand), _norm_brand(c.brand_handle))]
    other = [c for c in collabs if c not in same]
    other.sort(key=lambda c: (not c.is_competitor, c.date is None))
    if other:
        groups = post_groups(other)
        n = len(groups)
        conf = "high" if n >= 2 else "medium"
        brands = _brand_list(other)
        dates_cs = ", ".join(_day(min((e.date for e in g if e.date), default=None), "cs") for g in groups.values())
        dates_en = ", ".join(_day(min((e.date for e in g if e.date), default=None), "en") for g in groups.values())
        und = sum(1 for g in groups.values() if any(e.disclosed is False for e in g) and not any(e.disclosed is True for e in g))
        und_cs = f"; {und} bez označení reklamy" if und else ""
        und_en = f"; {und} without an ad label" if und else ""
        return ClaimCheck(
            id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent),
            evidence=[c.id for c in other[:8]], status="conflicts_with_record", confidence=conf,
            note=i18n(
                f"Uvádí exkluzivitu pro @{brand}, ale záznam ukazuje {n} {_cs_plural(n, 'post', 'posty', 'postů')} "
                f"se spoluprací s jinou značkou ({brands}): {dates_cs}{und_cs}.",
                f"Claims exclusivity for @{brand}, but the record shows {n} {'post' if n == 1 else 'posts'} "
                f"with another brand ({brands}): {dates_en}{und_en}."),
        )
    if same:
        return ClaimCheck(
            id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent),
            evidence=[c.id for c in same[:8]], status="supported",
            confidence="high" if len(same) >= 2 else "medium",
            note=i18n(
                f"Záznam obsahuje spolupráci s @{brand}; jiné značky jsme v analyzovaných postech nenašli.",
                f"The record shows collaboration with @{brand}; no other brands in the analysed posts."),
        )
    return ClaimCheck(
        id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent), evidence=[],
        status="unsupported", confidence="low",
        note=i18n(f"Spolupráci s @{brand} jsme v analyzovaných postech nenašli.",
                  f"We found no collaboration with @{brand} in the analysed posts."),
    )


def _check_partner(cid: str, sent: str, src: SourceRef, brand: str, collabs: list[CollabEvidence]) -> ClaimCheck:
    nb = _norm_brand(brand)
    same = [c for c in collabs if nb and nb in (_norm_brand(c.brand), _norm_brand(c.brand_handle))]
    if same:
        return ClaimCheck(
            id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent),
            evidence=[c.id for c in same[:8]], status="supported",
            confidence="high" if len(same) >= 2 else "medium",
            note=i18n(f"Spolupráci s @{brand} potvrzuje záznam: {_collab_summary(same, 'cs')}.",
                      f"The record shows the collaboration with @{brand}: {_collab_summary(same, 'en')}."),
        )
    return ClaimCheck(
        id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent), evidence=[],
        status="unsupported", confidence="low",
        note=i18n(f"Spolupráci s @{brand} jsme v analyzovaných postech nenašli.",
                  f"We found no collaboration with @{brand} in the analysed posts."),
    )


def _check_unpaid(cid: str, sent: str, src: SourceRef, post_id: str | None, collabs: list[CollabEvidence]) -> ClaimCheck:
    pool = [c for c in collabs if c.kind in _PAID_KINDS and (post_id is None or c.post_id == post_id)]
    if pool:
        strong = any(c.kind in ("paid_label", "meta_branded", "discount_code") for c in pool)
        conf = "high" if strong and len(pool) >= 2 else "medium"
        where_cs = "Tento post" if post_id else "Profil"
        where_en = "This post" if post_id else "The profile"
        return ClaimCheck(
            id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent),
            evidence=[c.id for c in pool[:8]], status="conflicts_with_record", confidence=conf,
            note=i18n(
                f"{where_cs} tvrdí, že nejde o placenou spolupráci, ale obsahuje: {_collab_summary(pool, 'cs')}.",
                f"{where_en} says it is not paid, but the record shows: {_collab_summary(pool, 'en')}."),
        )
    return ClaimCheck(
        id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent), evidence=[],
        status="cannot_verify", confidence="low",
        note=i18n("Platby z veřejných dat ověřit nejde; slevový kód ani označení reklamy jsme tu nenašli.",
                  "Payments cannot be verified from public data; we found no discount code or ad label here."),
    )


def _check_followers(cid: str, sent: str, src: SourceRef, m: re.Match, profile: Profile) -> ClaimCheck:
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        n = 0.0
    if m.group(2):
        n *= 1000
    actual = profile.followers
    if actual is None or n <= 0:
        return ClaimCheck(
            id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent), evidence=[],
            status="cannot_verify", confidence="low",
            note=i18n("Počet sledujících profil neukazuje.", "The profile does not show a follower count."),
        )
    ok = actual >= 0.8 * n
    return ClaimCheck(
        id=cid, claim=clip(sent, 200), claim_source=_quote_ref(src, sent), evidence=[profile.source.id],
        status="supported" if ok else "conflicts_with_record", confidence="medium",
        note=i18n(f"Profil ukazuje {fmt_int(actual, 'cs')} sledujících.",
                  f"The profile shows {fmt_int(actual, 'en')} followers."),
    )


class _LLMClaim(BaseModel):
    claim: str
    source: str
    evidence: list[str]
    status: Literal["supported", "conflicts_with_record", "unsupported", "cannot_verify"]
    confidence: Literal["high", "medium", "low"]
    note_cs: str
    note_en: str


class _LLMClaims(BaseModel):
    claims: list[_LLMClaim]


def validate_llm_claims(
    raw: list[_LLMClaim], profile: Profile, posts: list[Post], allowed_ids: set[str]
) -> list[ClaimCheck]:
    """Keep only claims quoted verbatim from a given source; drop evidence ids not in allowed_ids;
    downgrade a supported / conflicting claim that loses all its evidence."""
    out: list[ClaimCheck] = []
    for c in raw:
        src_key = (c.source or "").strip().lower()
        if src_key == "bio":
            text, src = profile.bio or "", profile.source
        elif src_key.isdigit() and int(src_key) < len(posts):
            p = posts[int(src_key)]
            text, src = p.caption or "", p.source
        else:
            continue
        quote = (c.claim or "").strip().strip('"„“”')
        if not quote or fold(quote) not in fold(text):
            continue  # not verbatim -> could be an invented fact
        evidence = list(dict.fromkeys(e for e in c.evidence if e in allowed_ids))
        status, conf = c.status, c.confidence
        note = i18n(clip(c.note_cs, 300), clip(c.note_en, 300))
        dropped = len(evidence) < len(set(c.evidence))
        if status in ("supported", "conflicts_with_record") and not evidence:
            status, conf = "cannot_verify", "low"
            note = i18n("Tvrzení nemá v záznamu doložitelný důkaz.", "The claim has no traceable evidence in the record.")
        elif dropped or not _safe_text(note["cs"], note["en"]):
            note = i18n("Hodnocení vychází jen z uvedených důkazů.", "Assessment based only on the listed evidence.")
        if conf == "high" and len(evidence) < 2:
            conf = "medium"
        out.append(ClaimCheck(
            id=_claim_id(profile.handle, "llm", fold(quote)[:80], src.id), claim=clip(quote, 200),
            claim_source=_quote_ref(src, quote), evidence=evidence, status=status, confidence=conf, note=note,
        ))
    return out


def _overlaps(a: str, b: str) -> bool:
    fa, fb = fold(a), fold(b)
    return bool(fa and fb) and (fa in fb or fb in fa)


async def claims(profile: Profile, posts: list[Post], collabs: list[CollabEvidence]) -> list[ClaimCheck]:
    """Extract the creator's own claims about brands, payments, exclusivity ("exkluzivní ambasador"),
    unpaid reviews ("nikdo mi neplatí"), audience size from bio + captions; match ONLY to the given
    CollabEvidence ids, post ids and the profile record id. claim_source = where/when they said it.
    Fallback: regex patterns for those claim types + rules (exclusive X but collab with other brand ->
    conflicts_with_record; "neplacená" + discount code / paid label -> conflicts_with_record)."""
    floor = _fallback_claims(profile, posts, collabs)
    allowed = {c.id for c in collabs} | {p.id for p in posts} | {profile.source.id}

    post_lines = "\n".join(
        f"[{i}] {fmt_date(p.created_at, 'en')}: {clip(p.caption, 600).replace(chr(10), ' ')}" for i, p in enumerate(posts)
    )
    ev_lines = "\n".join(
        f"- id={c.id} brand={c.brand} kind={c.kind} disclosed={c.disclosed} date={fmt_date(c.date, 'en')} "
        f"post={next((i for i, p in enumerate(posts) if p.id == c.post_id), '-')}"
        for c in collabs
    )
    user = (
        f"Creator @{profile.handle}.\n<bio>\n{profile.bio}\n</bio>\n<posts>\n{post_lines}\n</posts>\n"
        f"<evidence>\n- id={profile.source.id} kind=profile followers={profile.followers}\n{ev_lines}\n</evidence>\n"
        "Post evidence ids (usable in `evidence`): " + ", ".join(p.id for p in posts)
    )
    out = None
    if posts or profile.bio:
        out = await llm_client.structured(
            _LLMClaims, system=prompts.CLAIMS_SYSTEM, user=user, max_tokens=8000, effort="medium", task="claims"
        )
    if out is None:
        llm_client.record_mode(TASK, "fallback")
        return floor
    llm_client.record_mode(TASK, "llm")
    checked = validate_llm_claims(out.claims, profile, posts, allowed)
    # Deterministic floor: keep every rule-based claim the model did not cover.
    for f in floor:
        if not any(_overlaps(f.claim, c.claim) for c in checked):
            checked.append(f)
    return checked


# --------------------------------------------------------------------------------------------
# news
# --------------------------------------------------------------------------------------------

# "confirmed" = an official statement / announcement by the person or their business. Fines, rulings
# and other legal outcomes are Art. 10 data: the sensitive filter drops them before storage.
_RX_CONFIRMED = re.compile(
    r"potvrdil|potvrzen|oficialne oznamil|oficialne predstavil|\bconfirmed\b|officially announced"
)
_RX_ALLEGATION = re.compile(
    r"udajn|obvin|podezr|tvrdi|kritizuj|kritik|stiznost|stezuj|kauza|skandal|\balleg|\baccus|reportedly|"
    r"\bclaims?\b|criticis|criticiz|complain|controvers"
)


def _keyword_label(item: NewsItem) -> str:
    t = fold(f"{item.title}. {item.snippet}")
    if _RX_CONFIRMED.search(t):
        return "confirmed"
    if _RX_ALLEGATION.search(t):
        return "allegation"
    return "neutral"


class _NewsLabel(BaseModel):
    i: int
    label: Literal["allegation", "confirmed", "neutral"]


class _NewsLabels(BaseModel):
    labels: list[_NewsLabel]


def _subject(profile: Profile, item: NewsItem) -> str:
    try:
        from app.compute.identity import news_subject

        s = news_subject(profile, item)
        return s if s in ("matched", "uncertain", "rejected") else "uncertain"
    except Exception:
        return "uncertain"


async def news_findings(profile: Profile, items: list[NewsItem]) -> list[NewsFinding]:
    """Label each item allegation / confirmed / neutral with attribution "píše <outlet>". Items whose
    subject does not match the creator (compute.identity.news_subject == "rejected") are dropped;
    "uncertain" ones are kept, marked in the attribution and flagged by the skeptic as namesake risk."""
    kept = [(it, _subject(profile, it)) for it in items]
    kept = [(it, s) for it, s in kept if s != "rejected"]
    if not kept:
        return []
    labels = [_keyword_label(it) for it, _ in kept]
    lines = "\n".join(f"[{i}] {it.outlet}: {clip(it.title, 200)} — {clip(it.snippet, 400)}" for i, (it, _) in enumerate(kept))
    out = await llm_client.structured(
        _NewsLabels, system=prompts.NEWS_SYSTEM, user=f"<news>\n{lines}\n</news>", max_tokens=2000,
        effort="low", task="news",
    )
    if out is None:
        llm_client.record_mode(TASK, "fallback")
    else:
        llm_client.record_mode(TASK, "llm")
        for lab in out.labels:
            if 0 <= lab.i < len(labels):
                labels[lab.i] = lab.label
    result = []
    for (it, subj), label in zip(kept, labels):
        attribution = f"píše {it.outlet}" + (UNCERTAIN_MARK if subj == "uncertain" else "")
        result.append(NewsFinding(item=it, label=label, attribution=attribution))  # type: ignore[arg-type]
    return result


# --------------------------------------------------------------------------------------------
# skeptic
# --------------------------------------------------------------------------------------------


class _SkepticNote(BaseModel):
    ref_id: str
    action: Literal["downgrade_to_gap", "lower_confidence", "note"]
    note_cs: str
    note_en: str


class _Skeptic(BaseModel):
    notes: list[_SkepticNote]


def _to_gap(f: Finding) -> Finding:
    return Finding(
        id=f.id, kind="gap", sources=[], based_on=[], section=f.section, relevance=list(f.relevance),
        text=i18n(f"Neověřeno: {f.text.get('cs', '')}", f"Not verified: {f.text.get('en', '')}"),
    )


def _known_ids(report: Report) -> set[str]:
    ids = {f.id for f in report.findings} | {c.id for c in report.collab_timeline} | {c.id for c in report.claims}
    ids |= {c.post_id for c in report.collab_timeline if c.post_id}
    ids |= {r.id for r in iter_source_refs(report)}
    return ids


def apply_skeptic_rules(report: Report) -> Report:
    """Deterministic skeptic pass (always runs; the LLM can only add caution on top)."""
    notes: list[dict[str, str]] = [dict(n) for n in report.skeptic_notes]

    def note(cs: str, en: str) -> None:
        n = i18n(cs, en)
        if n not in notes:
            notes.append(n)

    # 1. Inferences must rest on fact findings.
    fact_ids = {f.id for f in report.findings if f.kind == "fact"}
    findings: list[Finding] = []
    for f in report.findings:
        if f.kind == "inference":
            based = [b for b in f.based_on if b in fact_ids]
            if not based:
                findings.append(_to_gap(f))
                note(f"Odhad „{clip(f.text.get('cs', ''), 80)}“ nemá oporu ve faktech, převedeno na mezeru.",
                     f"Inference “{clip(f.text.get('en', ''), 80)}” has no supporting fact; turned into a gap.")
                continue
            if len(based) < len(f.based_on):
                f = f.model_copy(update={"based_on": based})
        findings.append(f)

    # 2. Claims: evidence must resolve; a single weak signal lowers confidence.
    known = _known_ids(report)
    collab_by_id = {c.id: c for c in report.collab_timeline}
    claims: list[ClaimCheck] = []
    for c in report.claims:
        ev = [e for e in c.evidence if e in known]
        status, conf = c.status, c.confidence
        if status in ("supported", "conflicts_with_record") and not ev:
            status, conf = "cannot_verify", "low"
            note(f"Tvrzení „{clip(c.claim, 60)}“ nemá dohledatelný důkaz; nelze ověřit.",
                 f"Claim “{clip(c.claim, 60)}” has no traceable evidence; cannot be verified.")
        elif status in ("supported", "conflicts_with_record") and len(ev) == 1:
            ce = collab_by_id.get(ev[0])
            if ce is not None and ce.kind in ("mention", "tag") and conf != "low":
                conf = _lower(conf)
                note(f"Tvrzení „{clip(c.claim, 60)}“ stojí na jediné zmínce značky; nižší jistota.",
                     f"Claim “{clip(c.claim, 60)}” rests on a single brand mention; lower confidence.")
        if conf == "high" and len(ev) < 2:
            conf = "medium"
        claims.append(c.model_copy(update={"evidence": ev, "status": status, "confidence": conf}))

    # 3. News: "confirmed" needs confirmation wording; namesake risk is spelled out.
    news: list[NewsFinding] = []
    for n in report.news:
        kw_label = _keyword_label(n.item)
        if n.label == "confirmed" and kw_label != "confirmed":
            n = n.model_copy(update={"label": kw_label})
            what_cs, what_en = ("obvinění", "an allegation") if kw_label == "allegation" else ("neutrální", "neutral")
            note(f"Zpráva „{clip(n.item.title, 60)}“ ({n.item.outlet}) neuvádí potvrzení; vedeno jako {what_cs}.",
                 f"News “{clip(n.item.title, 60)}” ({n.item.outlet}) does not state a confirmation; kept as {what_en}.")
        if UNCERTAIN_MARK in n.attribution or UNCERTAIN_MARK_EN in n.attribution:
            note(f"Zpráva v {n.item.outlet} může být o jiném člověku se stejným jménem; před použitím ověřte.",
                 f"The {n.item.outlet} article may be about a different person with the same name; verify before use.")
        news.append(n)

    # 4. Identity: uncertain cross-platform matches.
    for m in report.identity:
        if m.status == "uncertain":
            note(f"Účet @{m.handle} ({m.platform}) může, ale nemusí patřit stejnému tvůrci.",
                 f"Account @{m.handle} ({m.platform}) may or may not belong to the same creator.")

    return report.model_copy(update={"findings": findings, "claims": claims, "news": news, "skeptic_notes": notes})


def _report_digest(report: Report) -> str:
    lines = ["<findings>"]
    for f in report.findings:
        lines.append(f"- id={f.id} kind={f.kind} section={f.section} based_on={f.based_on} text={clip(f.text.get('en') or f.text.get('cs', ''), 200)}")
    lines.append("</findings>\n<claims>")
    for c in report.claims:
        lines.append(f"- id={c.id} status={c.status} confidence={c.confidence} evidence={c.evidence} claim={clip(c.claim, 160)}")
    lines.append("</claims>\n<news>")
    for n in report.news:
        lines.append(f"- label={n.label} attribution={n.attribution} title={clip(n.item.title, 160)}")
    lines.append("</news>\n<identity>")
    for m in report.identity:
        lines.append(f"- @{m.handle} {m.platform} status={m.status}")
    lines.append("</identity>")
    return "\n".join(lines)


async def skeptic(report: Report) -> Report:
    """Return a copy with skeptic_notes filled and downgrades applied: inferences whose based_on does
    not resolve to fact findings become gaps; claims resting on a single weak signal get lower
    confidence; news allegations stay "allegation" unless confirmed by an outlet; namesake risk noted.
    (architecture.md: "skeptic(report) -> notes + downgrades".)"""
    rep = apply_skeptic_rules(report)
    out = await llm_client.structured(
        _Skeptic, system=prompts.SKEPTIC_SYSTEM, user=_report_digest(rep), max_tokens=4000, effort="low", task="skeptic"
    )
    if out is None:
        llm_client.record_mode(TASK, "fallback")
        return rep
    llm_client.record_mode(TASK, "llm")
    return apply_llm_skeptic(rep, out.notes)


def apply_llm_skeptic(rep: Report, raw: list[_SkepticNote]) -> Report:
    """Apply validated LLM skeptic notes: only ids present in the report; only cautious actions."""
    finding_by_id = {f.id: f for f in rep.findings}
    claim_ids = {c.id for c in rep.claims}
    findings = list(rep.findings)
    claims = list(rep.claims)
    notes = [dict(n) for n in rep.skeptic_notes]
    for n in raw[:6]:
        ref = (n.ref_id or "").strip()
        if ref and ref not in finding_by_id and ref not in claim_ids:
            continue  # invented id -> drop the whole note
        if not _safe_text(n.note_cs, n.note_en):
            continue
        if n.action == "downgrade_to_gap" and ref in finding_by_id and finding_by_id[ref].kind == "inference":
            findings = [(_to_gap(f) if f.id == ref else f) for f in findings]
        elif n.action == "lower_confidence" and ref in claim_ids:
            claims = [(c.model_copy(update={"confidence": _lower(c.confidence)}) if c.id == ref else c) for c in claims]
        text = i18n(clip(n.note_cs, 300), clip(n.note_en, 300))
        if text["cs"] and text not in notes:
            notes.append(text)
    return rep.model_copy(update={"findings": findings, "claims": claims, "skeptic_notes": notes})


# --------------------------------------------------------------------------------------------
# questions
# --------------------------------------------------------------------------------------------

AUDIENCE_QUESTION = i18n(
    "Můžete nám poslat statistiky publika (věk, pohlaví, města) z Instagram Insights nebo TikTok Analytics? Sami je neodhadujeme.",
    "Could you share your audience statistics (age, gender, cities) from Instagram Insights or TikTok Analytics? We do not estimate them ourselves.",
)

_SECTION_Q: dict[str, dict[str, str]] = {
    "engagement": i18n("Můžete nám poslat dosah a interakce vašich postů za poslední měsíc (screenshot statistik)?",
                       "Could you share reach and engagement of your posts for the last month (a stats screenshot)?"),
    "collabs": i18n("S jakými značkami teď spolupracujete a máte s některou exkluzivitu?",
                    "Which brands are you working with now, and do you have exclusivity with any of them?"),
    "content": i18n("Jaký obsah plánujete na další měsíce a jak často obvykle publikujete?",
                    "What content are you planning for the coming months and how often do you usually post?"),
    "identity": i18n("Které účty na dalších sítích jsou vaše (a které ne)?",
                     "Which accounts on other platforms are yours (and which are not)?"),
}


def _template_question(g: Finding) -> dict[str, str] | None:
    """Template question for a gap section; None for gaps that are not a question for the creator
    (e.g. "we found no news": asking the creator about it would be odd)."""
    if g.section in _SECTION_Q:
        return dict(_SECTION_Q[g.section])
    return None


_RX_DEMOGRAPHIC_GAP = re.compile(r"\bvek|pohlav|puvod publika|\bage\b|gender|demograf")


class _Question(BaseModel):
    gap_id: str
    q_cs: str
    q_en: str


class _Questions(BaseModel):
    questions: list[_Question]


def _dedupe(qs: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for q in qs:
        k = fold(q.get("cs", ""))
        if k and k not in seen:
            seen.add(k)
            out.append(q)
    return out


def template_questions(gaps: list[Finding]) -> list[dict[str, str]]:
    """What ``questions`` returns without the LLM (deterministic): the audience-statistics request and
    one template question per gap section (no question for gaps the creator cannot answer)."""
    gaps = [g for g in gaps if g.kind == "gap"]
    relevant = [g for g in gaps if not _RX_DEMOGRAPHIC_GAP.search(fold(g.text.get("cs", "") + " " + g.text.get("en", "")))
                and _template_question(g) is not None]
    qs = [dict(AUDIENCE_QUESTION)] + [_template_question(g) for g in relevant]  # type: ignore[misc]
    return _dedupe(qs)[:7]


async def questions(gaps: list[Finding]) -> list[dict[str, str]]:
    """Polite questions for the first meeting, one per gap (i18n maps). Always include the request
    for audience statistics (age/gender/location come only from the creator)."""
    gaps = [g for g in gaps if g.kind == "gap"]
    relevant = [g for g in gaps if not _RX_DEMOGRAPHIC_GAP.search(fold(g.text.get("cs", "") + " " + g.text.get("en", "")))
                and _template_question(g) is not None]
    templated = {g.id: _template_question(g) for g in relevant}
    if not relevant:
        return [dict(AUDIENCE_QUESTION)]
    lines = "\n".join(f"- id={g.id} section={g.section} gap={g.text.get('cs', '')} / {g.text.get('en', '')}" for g in relevant)
    out = await llm_client.structured(
        _Questions, system=prompts.QUESTIONS_SYSTEM, user=f"<gaps>\n{lines}\n</gaps>", max_tokens=3000,
        effort="low", task="questions",
    )
    by_gap = dict(templated)
    if out is None:
        llm_client.record_mode(TASK, "fallback")
    else:
        llm_client.record_mode(TASK, "llm")
        for q in out.questions:
            if q.gap_id in by_gap and q.q_cs.strip() and q.q_en.strip() and _safe_text(q.q_cs, q.q_en):
                by_gap[q.gap_id] = i18n(clip(q.q_cs, 300), clip(q.q_en, 300))
    qs = [dict(AUDIENCE_QUESTION)] + [by_gap[g.id] for g in relevant]
    return _dedupe(qs)[:7]


def evidence_questions(report: Report, profile: Profile | None = None) -> list[dict[str, str]]:
    """Specific questions for the first meeting from what the record shows (deterministic): one per
    claim that conflicts with the record or is unsupported, and one for brand posts without an ad
    label that no claim question already covers. Neutral wording, dates from the evidence."""
    from app.compute.collabs import find_discount_codes, undisclosed_posts

    by_id = {e.id: e for e in report.collab_timeline}
    out: list[dict[str, str]] = []
    covered: set[str] = set()
    bio_id = profile.source.id if profile is not None else None
    for c in report.claims:
        if c.status not in ("conflicts_with_record", "unsupported"):
            continue
        claim = clip(c.claim, 90)
        where_cs = "V biu uvádíte" if c.claim_source.id == bio_id else "Uvádíte"
        where_en = "Your bio says" if c.claim_source.id == bio_id else "You say"
        evs = [by_id[e] for e in c.evidence if e in by_id]
        if c.status == "conflicts_with_record" and not evs and (c.note or {}).get("en"):
            # the record contradicts it (e.g. the profile's follower count): ask about that, do not
            # say it "could not be found"
            note_cs = (c.note.get("cs") or c.note["en"]).strip().rstrip(".")
            note_en = c.note["en"].strip().rstrip(".")
            out.append(i18n(f"{where_cs} „{claim}“; {note_cs[:1].lower() + note_cs[1:]}. Jak to počítáte?",
                            f"{where_en} “{claim}”; {note_en[:1].lower() + note_en[1:]}. How do you count it?"))
            continue
        if c.status == "unsupported" or not evs:
            out.append(i18n(f"{where_cs} „{claim}“; ve veřejných postech jsme to nedohledali. Můžete to upřesnit?",
                            f"{where_en} “{claim}”; we could not find it in the public posts. Could you tell us more?"))
            continue
        groups = post_groups(evs)
        covered.update(groups)
        dates_cs = " a ".join(_day(min((e.date for e in g if e.date), default=None), "cs") for g in groups.values())
        dates_en = " and ".join(_day(min((e.date for e in g if e.date), default=None), "en") for g in groups.values())
        codes = [code for e in evs if e.kind == "discount_code" for code in find_discount_codes(e.source.quote or "")]
        unlabeled = any(e.disclosed is False for e in evs)
        if codes:
            out.append(i18n(
                f"U postu z {dates_cs} je slevový kód {codes[0]}{' bez označení reklamy' if unlabeled else ''}. Šlo o spolupráci se značkou?",
                f"The post from {dates_en} has the discount code {codes[0]}{' without an ad label' if unlabeled else ''}. Was it a collaboration with a brand?"))
            continue
        brands = _brand_list(evs)
        joint = any(e.kind == "coauthor" for e in evs)
        what_cs = "společné posty s" if joint else "posty se značkou"
        what_en = "joint posts with" if joint else "posts featuring"
        out.append(i18n(
            f"{where_cs} „{claim}“; {dates_cs} jsou ale {what_cs} {brands}. Jak to je teď?",
            f"{where_en} “{claim}”; on {dates_en} there are {what_en} {brands}, though. Which is current?"))
    und = [e for e in undisclosed_posts(report.collab_timeline) if (e.post_id or e.id) not in covered]
    if und:
        n = len(und)
        dates_cs = ", ".join(_day(e.date, "cs") for e in und[:3])
        dates_en = ", ".join(_day(e.date, "en") for e in und[:3])
        out.append(i18n(
            f"U {n} {_cs_plural(n, 'postu', 'postů', 'postů')} se značkou ({dates_cs}) jsme nenašli označení reklamy. Šlo o placenou spolupráci?",
            f"For {n} {'post' if n == 1 else 'posts'} with a brand ({dates_en}) we found no ad label. Was it a paid collaboration?"))
    return [q for q in _dedupe(out) if _safe_text(q["cs"], q["en"])]


# --------------------------------------------------------------------------------------------
# outreach (DRAFT ONLY; there is no send function anywhere)
# --------------------------------------------------------------------------------------------


def _noticed(candidate: Candidate) -> tuple[list[str], str | None, bool]:
    m = candidate.metrics
    topics: list[str] = []
    fmt: str | None = None
    local = False
    if m is not None:
        ranked = sorted(((n, t) for t, n in (m.topic_counts or {}).items() if t not in ("other", "unclassified") and n > 0), reverse=True)
        topics = [t for _, t in ranked[:2]]
        if m.formats:
            fmt = max(m.formats.items(), key=lambda kv: kv[1])[0]
        local = bool(m.local_signals)
    return topics, fmt, local


def _safe_goal(goal: str | None) -> str:
    """The owner's campaign goal as a mid-sentence phrase ("Víc lidí v prodejně." -> "víc lidí v
    prodejně"), or "" when it is empty or would carry a sensitive / scoring request."""
    g = (goal or "").strip().rstrip(".…!? ").strip()
    if not g or not _safe_text(g):
        return ""
    if g[0].isupper() and (len(g) < 2 or not g[1].isupper()):
        g = g[0].lower() + g[1:]
    return clip(g, 160)


def _safe_business(bt: str | None, lang: str) -> str:
    bt = (bt or "").strip()
    if not bt or not _safe_text(bt):
        return "firma" if lang == "cs" else "business"
    return bt


def outreach_template(brief: Brief, candidate: Candidate, topic_status: str | None = None) -> dict[str, str]:
    """The template draft. ``topic_status`` = the current goal's topic_share check ("pass" / "fail" /
    "unknown" / None when there is no such check): only a pass (or no check) says the topics fit us."""
    prof = candidate.profile
    name = greeting_name(prof.display_name) if prof else ""
    topics, fmt, local = _noticed(candidate)
    loc = cs_locative(brief.city)
    goal = _safe_goal(brief.goal)
    bt_cs = _safe_business(brief.business_type, "cs")

    about_cs = " a ".join(TOPIC_ABOUT_CS.get(t, TOPIC_LABELS.get(t, {}).get("cs", t)) for t in topics) or "obsah, který k nám sedí"
    about_en = " and ".join(TOPIC_LABELS.get(t, {}).get("en", t) for t in topics) or "content that fits us"
    fmt_cs = f", hlavně {FORMAT_LABELS[fmt]['cs']}" if fmt in FORMAT_LABELS and fmt != "other" else ""
    fmt_en = f", mostly {FORMAT_LABELS[fmt]['en']}" if fmt in FORMAT_LABELS and fmt != "other" else ""
    local_cs = f", a často ukazujete místa {loc}" if local and loc else ""
    local_en = f", often around {brief.city}" if local and brief.city else ""
    about_cs_full = about_cs if about_cs.startswith(("o ", "s ")) or about_cs.startswith("obsah") else f"o: {about_cs}"
    campaign_cs = f"chystáme kampaň: {goal}." if goal else "chystáme kampaň."
    campaign_en = f"preparing a campaign (goal: {goal})." if goal else "preparing a campaign."
    fits = topic_status not in ("fail", "unknown")
    bt_en = business_en(_safe_business(brief.business_type, "en"))
    fit_cs = (", a to k nám dobře sedí." if fits
              else f". Rádi bychom věděli, jestli by se k vašemu kanálu hodil i příspěvek o nás ({bt_cs}).")
    fit_en = (", which fits us well." if fits
              else f", and we would like to know whether a post about our {bt_en} could fit your channel.")

    # Czech: no name in the greeting (the nominative "Dobrý den, Jakub Horák" reads wrong; the
    # vocative cannot be derived reliably). The owner can add it when copying.
    cs = (
        "Dobrý den,\n\n"
        f"jsme {bt_cs}{(' ' + loc) if loc else ''} a {campaign_cs} "
        f"Narazili jsme na váš profil – tvoříte {about_cs_full}{fmt_cs}{local_cs}{fit_cs}\n\n"
        "Měl(a) byste zájem o spolupráci? Podmínky bychom rádi domluvili tak, aby byly férové pro obě strany, "
        "a spolupráci bychom jasně označili jako reklamu.\n\n"
        "Pokud vás to zajímá, můžeme si krátce zavolat nebo se potkat u nás.\n\n"
        "Děkujeme a přejeme hezký den\n[vaše jméno]"
    )
    city_en = f" in {brief.city}" if brief.city else ""
    en = (
        f"Hello{(' ' + name) if name else ''},\n\n"
        f"we are a {bt_en}{city_en} {campaign_en} "
        f"We came across your profile – you post about {about_en}{fmt_en}{local_en}{fit_en}\n\n"
        "Would you be interested in working together? We would like to agree on terms that are fair for both "
        "sides, and the collaboration would be clearly labelled as advertising.\n\n"
        "If you are interested, we could have a short call or meet at our place.\n\n"
        "Thank you and have a nice day\n[your name]"
    )
    return i18n(cs, en)


class _Draft(BaseModel):
    cs: str
    en: str


async def outreach(brief: Brief, candidate: Candidate) -> dict[str, str]:
    """Outreach DRAFT {"cs": ..., "en": ...}. Never sent: there is no send function anywhere."""
    template = outreach_template(brief, candidate)
    prof = candidate.profile
    handle = prof.handle if prof else candidate.ref.handle
    name = (greeting_name(prof.display_name) if prof else "") or f"@{handle}"
    topics, fmt, local = _noticed(candidate)
    user = (
        f"Business: {_safe_business(brief.business_type, 'en')}; city: {brief.city or '-'}; "
        f"campaign goal (owner's words): {_safe_goal(brief.goal) or '-'}; "
        f"owner language: {brief.lang}.\nCreator name: {name}.\n"
        f"Noticed (neutral facts only): topics={', '.join(TOPIC_LABELS.get(t, {}).get('en', t) for t in topics) or '-'}; "
        f"main format={fmt or '-'}; often shows places in the city={'yes' if local else 'no'}."
    )
    out = await llm_client.structured(
        _Draft, system=prompts.OUTREACH_SYSTEM, user=user, max_tokens=3000, effort="low", task="outreach"
    )
    if out is None:
        llm_client.record_mode(TASK, "fallback")
        return template
    competitor_words = {_norm_brand(c.get("name")) for c in brief.competitors} | {
        _norm_brand(h) for c in brief.competitors for h in (c.get("handles") or [])
    }
    competitor_words.discard("")
    ok = True
    for text in (out.cs, out.en):
        flat = _norm_brand(text)
        if not (150 <= len(text) <= 1800) or not _safe_text(text) or any(w in flat for w in competitor_words):
            ok = False
    if not ok:
        llm_client.record_mode(TASK, "fallback")
        return template
    llm_client.record_mode(TASK, "llm")
    return i18n(out.cs.strip(), out.en.strip())
