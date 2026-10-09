"""Round 1: basics. One provider.profiles() batch per platform.

prepare: attach Profile (with latest_posts); drop minors (is_under_18, or an explicit age under 18 in
the bio: compute.minors) and political parties / movements, unions and religious organisations
(``is_sensitive_org``) from run.candidates without storing anything (log a count only); run llm.sensitive.filter_profile on every profile BEFORE storing
(adds to candidate.sensitive_filtered, emits sensitive.filtered when > 0); compute base Metrics
(compute.metrics.compute_metrics without topics/comments).
Candidates whose profile the provider did not return (unknown handle, removed account, or a minor the
provider dropped) are removed from the run as well: we cannot tell a minor from a failed lookup, so
nothing about them is kept. The engine emits ``candidate.removed {"id"}`` for them.
evaluate kinds: public_account (private False -> pass), followers_range, active_recently (last post
within params.days of now), not_brand_account (organisation category -> fail whatever is_business says; creator
category -> pass; else bio / name evidence such as opening hours or "s.r.o." -> fail; personal account
without such evidence -> pass; nothing either way -> unknown), language_cs (compute.language.language_share
on captions, min_texts=3, else unknown). Missing data -> "unknown" with value saying what is missing.
sources: the profile SourceRef (and post SourceRefs where relevant).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from app.compute import language as lang_mod
from app.compute.metrics import activity_posts, compute_metrics, last_post_at, posts_per_week
from app.compute.minors import is_minor
from app.events import Emit
from app.llm import sensitive
from app.models import (
    Brief,
    Candidate,
    Criterion,
    CriterionResult,
    Profile,
    Run,
    i18n,
    norm_handle,
)
from app.rounds.common import (
    llm_actor,
    Outcome,
    add_sensitive,
    count_modes,
    cs_days_ago,
    cs_plural,
    describe_modes,
    actor_of,
    en_days_ago,
    fmt_int,
    fmt_k,
    fmt_k_range,
    LANG_NAMES_CS,
    LANG_NAMES_EN,
    fmt_pct,
    log,
    newest_first,
    param,
    post_ref,
    posts_of,
    profile_refs,
    tr,
    unknown,
)
from app.sources.base import SourceProvider

ROUND = 1

_PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube"}


# ---------------------------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------------------------

async def prepare(run: Run, candidates: list[Candidate], provider: SourceProvider, emit: Emit) -> None:
    todo = [c for c in candidates if c.profile is None and c.id in run.candidates]
    if not todo:
        return
    by_platform: dict[str, list[Candidate]] = defaultdict(list)
    for c in todo:
        by_platform[c.ref.platform].append(c)

    fetched: dict[str, Profile] = {}
    for platform, cands in by_platform.items():
        handles = [c.ref.handle for c in cands]
        profiles = await provider.profiles(handles, platform)  # type: ignore[arg-type]
        batch = count_modes(run, [*profiles, *(p for pr in profiles for p in pr.latest_posts)])
        mode, suffix = describe_modes(batch)
        n = len(profiles)
        name = _PLATFORM_NAMES.get(platform, platform)
        await log(run, emit,
                  tr(run, f"{name}: {n} {cs_plural(n, 'profil', 'profily', 'profilů')} načteno{suffix}",
                     f"{name}: {n} {'profile' if n == 1 else 'profiles'} loaded{suffix}"),
                  actor=actor_of(profiles, provider.name), mode=mode)
        for pr in profiles:
            # A renamed account comes back under its new handle; former_handles holds the one we asked for.
            for h in [pr.handle, *pr.former_handles]:
                fetched.setdefault(f"{pr.platform}:{norm_handle(h)}", pr)

    removed: list[str] = []
    minors = 0
    sensitive_orgs = 0
    missing = 0
    keep: list[tuple[Candidate, Profile]] = []
    for c in todo:
        pr = fetched.get(c.id)
        if pr is None:
            missing += 1
            removed.append(c.id)
        elif is_minor(pr):  # provider flag, or an explicit age under 18 in the bio (nothing is stored)
            minors += 1
            removed.append(c.id)
        elif is_sensitive_org(pr):  # party / union / religious organisation: never profiled, nothing stored
            sensitive_orgs += 1
            removed.append(c.id)
        else:
            keep.append((c, pr))
    for cid in removed:
        run.candidates.pop(cid, None)
    if minors:
        await log(run, emit, tr(
            run,
            f"Vynecháno {minors} {cs_plural(minors, 'účet nezletilé osoby', 'účty nezletilých', 'účtů nezletilých')} (nic se neukládá).",
            f"Skipped {minors} {'account' if minors == 1 else 'accounts'} of minors (nothing is stored).",
        ), actor="engine")
    if sensitive_orgs:
        n = sensitive_orgs
        await log(run, emit, tr(
            run,
            f"Vynecháno {n} {cs_plural(n, 'účet', 'účty', 'účtů')} politických stran, hnutí, odborů nebo náboženských organizací (nic se neukládá).",
            f"Skipped {n} {'account' if n == 1 else 'accounts'} of political parties or movements, unions or religious organisations (nothing is stored).",
        ), actor="engine")
    if missing:
        await log(run, emit, tr(
            run,
            f"Vynecháno {missing} {cs_plural(missing, 'účet', 'účty', 'účtů')} bez dostupného profilu (nenalezen, smazán nebo nezletilý; nic se neukládá).",
            f"Skipped {missing} {'account' if missing == 1 else 'accounts'} without an available profile (not found, deleted or a minor; nothing is stored).",
        ), actor="engine")

    city = run.criteria.brief.city or run.criteria.discovery.city

    sem = asyncio.Semaphore(8)

    async def filter_one(c: Candidate, pr: Profile) -> int:
        async with sem:
            clean, dropped = await sensitive.filter_profile(pr)
        await add_sensitive(run, c, emit, dropped)
        c.profile = clean
        metrics = compute_metrics(clean, list(clean.latest_posts), city=city)
        # Timestamps and counts are not sensitive content: "last post" and "posts per week" come from
        # the unfiltered list, so a dropped (e.g. health) post never makes a creator look inactive.
        # Pinned posts are left out of both (compute.metrics.activity_posts).
        all_posts = list(pr.latest_posts)
        c.metrics = metrics.model_copy(update={
            "last_post_at": last_post_at(all_posts),
            "posts_per_week": posts_per_week(all_posts),
        })
        return dropped

    total = sum(await asyncio.gather(*(filter_one(c, pr) for c, pr in keep)))
    if total:
        await log(run, emit, tr(
            run,
            f"Citlivý filtr: vynecháno {total} {cs_plural(total, 'položka', 'položky', 'položek')} (citlivé kategorie, jen počet).",
            f"Sensitive filter: {total} {'item' if total == 1 else 'items'} left out (sensitive categories, count only).",
        ), actor=llm_actor(run, "sensitive"))


# ---------------------------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------------------------

def _fold(text: str) -> str:
    # NFKD before lower(): styled letters ("𝐋𝐈𝐆𝐀") decompose to plain capitals first.
    t = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(ch for ch in t if not unicodedata.combining(ch))


_CREATOR_CATEGORIES = re.compile(
    r"(creator|tvurce|tvurkyne|blog|influencer|artist|umelec|umelkyne|public figure|verejna osobnost|"
    r"gamer|athlete|sportovec|sportovkyne|photographer|fotograf|musician|hudebni|writer|author|autor|"
    r"chef|kuchar|personal trainer|osobni trener|fitness trainer|trener|trenerka|coach|kouc|"
    r"entrepreneur|\bmodel\b|comedian|komik|journalist|novinar|actor|actress|herec|herecka|youtuber|"
    r"video creator|digital creator|personal blog|food critic|recipe|nutritionist|vyzivov|kitchen/cooking|"
    r"cooking|vareni|gaming video|sports? person|personality)",
    re.IGNORECASE,
)
# Organisations of any kind: businesses, but also teams, clubs, parties, unions, nonprofits, venues,
# media, public bodies. Checked after _CREATOR_CATEGORIES ("Food Critic" is a creator, "Restaurant" not).
_ORG_CATEGORIES = re.compile(
    r"(\bteam\b|\btym\b|\bclub\b|\bklub|\bleague\b|\bliga\b|politic|\bparty\b|\bunion\b|\bunie\b|\bodbor|"
    r"non-?profit|neziskov|charit|foundation|nadac|association|asociac|spolek|sdruzeni|organi[sz]ation|"
    r"organizac|community|komunit|"
    r"bakery|pekarn|\bcafe|caf[eé]\b|coffee|kavarn|restaurant|restaurac|bistro|\bbar\b|\bpub\b|pivnic|hospod|"
    r"vinarn|cukrar|confection|cupcake|patisser|dessert|ice cream|gelat|zmrzlin|food truck|caterer|catering|"
    r"food & beverage|food and beverage|beverage|"
    r"shop|store|obchod|prodejn|retail|grocery|supermarket|potravin|market|boutique|e-?commerce|"
    r"brand|znacka|clothing|apparel|"
    r"agency|agentur|media|news|zpravodaj|magazine|casopis|publisher|nakladatel|radio|\btv\b|televis|broadcast|"
    r"venue|event|festival|stadium|arena|\bpark\b|ground|museum|muzeum|galler|theat|divadl|cinema|\bkino|"
    r"library|knihovn|\bzoo\b|"
    r"government|vladn|\burad|municipal|city hall|magistrat|public service|"
    r"school|skola|univerzit|university|college|kindergarten|skolk|academy|akademi|"
    r"hospital|nemocnic|clinic|klinik|pharmacy|lekarn|"
    r"\bgym\b|fitness cent|fitness studio|physical fitness|yoga studio|sports? (center|centre|facility)|"
    r"salon|hotel|hostel|accommodation|ubytovan|"
    r"brewery|pivovar|winery|vinarstv|vineyard|manufactur|vyrobce|company|firma|spolecnost|business|"
    r"services?\b|product|produkt|"
    r"church|religio|mosque|synagog|cirkev|farnost|temple|"
    r"\bbank\b|insurance|real estate|reality)",
    re.IGNORECASE,
)
# Organisations we must not profile at all (GDPR Art. 9: political opinions, trade-union membership,
# religious beliefs). Round 1 removes them like minors: nothing about them is stored.
# The rule for politicians: an account whose CATEGORY declares a political role (party, movement,
# politician, political candidate) is removed, because the account itself presents as political. A
# person is never removed for what they post or write in a bio: their political texts are dropped by
# the sensitive filter and the rest is judged like anyone else's (round 2 fails the topic when most
# texts were dropped). Content only removes NON-personal accounts (is_business not False): a
# business account that is mostly election posts is a party or campaign, not a creator.
_SENSITIVE_ORG_CATEGORIES = re.compile(
    r"(politic|\b(labou?r|trade|student|workers?)'?s?\s+unions?\b|\bodbor|religio|church|mosque|synagog|"
    r"cirkev|farnost|temple)",
    re.IGNORECASE,
)
_SENSITIVE_ORG_NAMES = re.compile(
    r"(\bhnuti\b|\bpolitick\w* (stran|hnuti)|\bodbor(y|ov\w*)\b|\bfarnost|\bcirkev|\bcirkv|"
    r"\b(anarchis|komunis|socialis|nacionalis|fasis)\w*)"
)
_SENSITIVE_ORG_BIO = re.compile(
    r"(\b(jsme|jsme politicke|politicke|politicka) (stran\w*|hnuti)\b|\bodborov\w* (organizac|svaz)|"
    r"\bpolitical (party|movement)\b|\btrade union\b)"
)

# Bio / name evidence that an account belongs to an organisation (folded text, one bio line at a time).
# STRONG signals decide alone; WEAK ones only support (two of them, or one on a professional account).
_DAY = r"(?:po|ut|st|ct|pa|so|ne|pondeli|utery|streda|ctvrtek|patek|sobota|nedele|mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?"
_TIME = r"\d{1,2}(?:[:.]\d{2})?\s*(?:h\s*)?[-–]\s*\d{1,2}"
_STRONG_ORG = re.compile("|".join([
    r"\bs\.\s?r\.\s?o\b", r"\bspol\. s r\.", r"\bz\.\s?s\.(?=\s|$|,|\))", r"\bo\.\s?p\.\s?s\.", r"\ba\.\s?s\.(?=\s|$|,|\))",
    r"\bico\s*:?\s*\d{6,8}\b", r"\bgmbh\b", r"\bltd\b",
    r"\bonline (shop|store)\b",
    r"\brezervac\w*\s+(stol|stul|mist|dort|peciv|na (tel|cisle|webu|www)|pres (web|www|tel|e-?shop|formular))",
    r"\breservations?\b",
    r"\bbook (a |your )?(table|tour|class|lesson|stay|room)",
    _DAY + r"\s*[-–~]\s*" + _DAY + r"\s*[:|]?\s*" + _TIME,
    r"\b(denne|kazdy den|daily)\s*[:|]?\s*" + _TIME,
    r"\botevreno\s+(denne|kazdy den|od \d|po|ut|st|ct|pa|so|ne)\b", r"\boteviraci dob", r"\bopen daily\b",
    r"\bopening hours\b",
    r"\bnove otevren", r"\bnewly opened\b", r"\bjsme (mal[ey] |mala )?(bistro|kavarna|pekarna|restaurace|podnik|obchod)",
    # a street address: "📍Kounicova 12, Brno" (a comma or the end after the number; "📍Brno, máma 2 kluků" is not one)
    r"📍[^/|•,]*?[a-z]{3,}\s+\d{1,4}(?:/\d{1,4})?[a-z]?\s*(?:,|$)", r"\bna ulici [a-z]+ \d",
    r"\b\d{3}\s?\d{2}\s*,?\s*brno\b",
]))
# Words a creator also uses ("Můj e-shop s recepty", "Testuju rozvozy jídla", "Máma nonstop", "tel 777 ...",
# "Spolupráce / rezervace termínů", "Otevřeno pro spolupráce"): weak, they only support other evidence.
_PHONE = r"(?:(?:📞|☎|\btel\b\.?|\bvolejte\b)\s*:?\s*\+?\d[\d ]{7,}|\+420\s?\d{3}\s?\d{3}\s?\d{3})"
_PHONE_DIGITS = re.compile(r"\+?\d[\d ]{6,}\d")
# Singular business nouns in the DISPLAY NAME ("Kavárna Kofi2 Brno", "Get Jacked bistro"). Guides use
# the plural ("Brněnské kavárny") and stay out.
_BUSINESS_NAME = re.compile(
    r"(kavarna\b|\bcafe\b|\bcaffe\b|\bbistro\b|restaurace\b|\brestaurant\b|pekarna\b|\bbakery\b|cukrarna\b|"
    r"\bbar\b|\bpub\b|\bpivnice\b|\bhospoda\b|\bvinarna\b|\bcatering\b|\bfood ?truck\b|\bgelato\b|zmrzlinarna\b|"
    r"\bprazirna\b|\bherna\b|\bco-?working\b|\be-?shop\b|\bobchod\b|\bprodejna\b|\bkadernictvi\b|\bhotel\b|"
    r"\bpenzion\b|\bkvetiny\b|\bflowers\b)"
)
_WEAK_ORG = re.compile("|".join([
    r"\b(fc|sk|tj|hc|bk|fk|mfk|ac)\s", r"\bklub", r"\bclub\b", r"\bteam\b", r"\btym\b", r"\bspolek\b", r"\bsdruzeni\b",
    r"\bfestival", r"\bveletrh", r"\brocnik", r"\borganizujeme\b", r"\bnabirame (\w+ )?(cleny|hrace|hracky)",
    r"\bcasopis", r"\bmagazin", r"\bzpravodaj", r"\bredakce\b", r"\byoga studio\b", r"\bstudio jogy\b",
    r"\bfitness (centrum|studio|center)\b", r"\bposilovna\b", r"\bliga\b", r"\bleague\b", r"\bextralig", r"\bsuperlig",
    r"\bwolt\b", r"\bfoodora\b", r"\bkadernictvi\b", r"\b(official|oficialni|oficial)\b",
    r"\be-?shop\b", r"\brezervac", r"\brozvoz", r"\bdorucujeme\b", r"\bdovazime\b", r"\bwe deliver\b",
    r"\bnonstop\b", _PHONE, r"\botevreno\b",
]))
_OFFICIAL = re.compile(r"\b(official|oficialni|oficial)\b")


def classify_category(category: str | None) -> str | None:
    """'creator' | 'company' (any organisation) | None (unclear)."""
    if not category:
        return None
    f = _fold(category)
    if _CREATOR_CATEGORIES.search(f):
        return "creator"
    if _ORG_CATEGORIES.search(f):
        return "company"
    return None


def is_sensitive_org(profile: Profile) -> bool:
    """A political party or movement (or an account whose category is a political role), a (trade or
    student) union, or a religious organisation. Such accounts are removed in round 1 before anything
    is stored: they are organisations, not creators, and profiling them would mean processing
    political or religious content. Run on the UNFILTERED profile (before the sensitive filter).
    Content counts only for non-personal accounts (see the rule above _SENSITIVE_ORG_CATEGORIES)."""
    if profile.business_category and _SENSITIVE_ORG_CATEGORIES.search(_fold(profile.business_category)):
        return True
    name = _fold(f"{profile.display_name} {re.sub(r'[._]+', ' ', profile.handle or '')}")
    if _SENSITIVE_ORG_NAMES.search(name):
        return True
    if _SENSITIVE_ORG_BIO.search(_fold(profile.bio).replace("\n", " ")):
        return True
    if profile.is_business is not False:
        # a campaign account ("Volte č. 3" in the bio, or at least half of 4+ posts about the election)
        if sensitive.political_flags([profile.bio or ""])[0]:
            return True
        posts = [sensitive._post_text(p) for p in profile.latest_posts]
        if len(posts) >= 4 and 2 * sum(sensitive.political_flags(posts)) >= len(posts):
            return True
    return False


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in re.split(r"[\n\r]+|\s/\s", text or "") if ln.strip()]


def org_signals(profile: Profile) -> tuple[list[str], list[str]]:
    """(strong, weak) evidence snippets from the bio, display name and handle."""
    strong: list[str] = []
    weak: list[str] = []
    for line in _lines(profile.bio):
        f = _fold(line)
        if _STRONG_ORG.search(f):
            strong.append(line[:80])
        elif _WEAK_ORG.search(f):
            weak.append(line[:80])
    name = profile.display_name or ""
    fname = _fold(name)
    if fname and _BUSINESS_NAME.search(fname):
        strong.append(name[:80])
    elif fname and (_WEAK_ORG.search(fname + " ") or _STRONG_ORG.search(fname)):
        weak.append(name[:80])
    handle_words = re.sub(r"[._]+", " ", profile.handle or "")
    if _OFFICIAL.search(_fold(handle_words)) and not any(_OFFICIAL.search(_fold(w)) for w in weak):
        weak.append(f"@{profile.handle}")
    return strong, weak


def _mask_phone(text: str) -> str:
    """Evidence never repeats a phone number: "tel 777 123 456" -> "tel •••"."""
    return _PHONE_DIGITS.sub("•••", text)


def _org_outcome(c: Candidate, th: dict[str, str], why_cs: str, why_en: str, quote: str | None) -> Outcome:
    p = c.profile
    assert p is not None
    why_cs, why_en = _mask_phone(why_cs), _mask_phone(why_en)
    if quote and _PHONE_DIGITS.search(quote):
        quote = None  # a quote must be verbatim, so a line with a phone number is cited as the profile
    src = [p.source.model_copy(update={"quote": quote})] if quote else profile_refs(c)
    return Outcome("fail", i18n(f"organizace nebo podnik ({why_cs})", f"organisation or business ({why_en})"), th, src,
                   reason=i18n(f"jde o účet organizace nebo podniku, ne tvůrce: {why_cs}",
                               f"this is an organisation's or a business's account, not a creator: {why_en}"))


def _assess_public(c: Candidate, lang: str) -> Outcome:
    th = i18n("veřejný účet", "public account")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    src = profile_refs(c)
    if c.profile.private is None:
        return unknown("nevíme, zda je účet veřejný", "unknown whether the account is public", th, src)
    if c.profile.private:
        return Outcome("fail", i18n("soukromý účet", "private account"), th, src,
                       reason=i18n("účet je soukromý, obsah nejde prověřit", "the account is private, its content cannot be checked"))
    return Outcome("pass", i18n("veřejný účet", "public account"), th, src)


def _assess_followers(criterion: Criterion, c: Candidate) -> Outcome:
    lo, hi = param(criterion, "min"), param(criterion, "max")
    if lo is not None and hi is not None:
        th = i18n(f"{fmt_k_range(lo, hi, 'cs')} sledujících", f"{fmt_k_range(lo, hi, 'en')} followers")
    elif lo is not None:
        th = i18n(f"aspoň {fmt_k(lo, 'cs')} sledujících", f"at least {fmt_k(lo, 'en')} followers")
    elif hi is not None:
        th = i18n(f"nejvýš {fmt_k(hi, 'cs')} sledujících", f"at most {fmt_k(hi, 'en')} followers")
    else:
        th = i18n("bez omezení", "no limit")
    if c.profile is None or c.profile.followers is None:
        return unknown("počet sledujících není k dispozici", "follower count not available", th, profile_refs(c))
    n = c.profile.followers
    value = i18n(f"{fmt_int(n, 'cs')} sledujících", f"{fmt_int(n, 'en')} followers")
    src = profile_refs(c)
    if lo is not None and n < lo:
        return Outcome("fail", value, th, src, reason=i18n(
            f"jen {fmt_int(n, 'cs')} sledujících, méně než dolní hranice",
            f"only {fmt_int(n, 'en')} followers, below the lower limit"))
    if hi is not None and n > hi:
        return Outcome("fail", value, th, src, reason=i18n(
            f"{fmt_int(n, 'cs')} sledujících, víc než horní hranice",
            f"{fmt_int(n, 'en')} followers, above the upper limit"))
    return Outcome("pass", value, th, src)


def _assess_active(criterion: Criterion, c: Candidate, now: datetime) -> Outcome:
    days = int(param(criterion, "days") or 30)
    th = i18n(f"post za posledních {days} dní", f"a post in the last {days} days")
    posts = posts_of(c)
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    last = c.metrics.last_post_at if c.metrics is not None else None
    if last is None and posts:
        active = activity_posts(posts)
        last = newest_first(active)[0].created_at if active else None
    if last is None:
        if posts and not activity_posts(posts):
            return unknown("jen připnuté posty, aktivitu z nich nepoznáme", "only pinned posts, they do not show activity",
                           th, profile_refs(c))
        if c.profile.posts_count == 0:
            return Outcome("fail", i18n("žádný post", "no posts"), th, profile_refs(c),
                           reason=i18n("účet nemá žádný post", "the account has no posts"))
        return unknown("posty nejsou k dispozici", "posts not available", th, profile_refs(c))
    age = max(0, (now - last).days)
    # "yesterday" / "2 days ago" by calendar days in Czech time, as the post dates are shown elsewhere
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Prague")
        cal = max(0, (now.astimezone(tz).date() - last.astimezone(tz).date()).days)
    except Exception:
        cal = age
    value = i18n(f"poslední post {cs_days_ago(cal)}", f"last post {en_days_ago(cal)}")
    active = activity_posts(posts)
    newest = newest_first(active)[0] if active else None
    # The newest post may have been left out by the sensitive filter: then cite the profile record.
    src = [post_ref(newest)] if newest is not None and newest.created_at == last else profile_refs(c)
    if age > days:
        return Outcome("fail", value, th, src)
    return Outcome("pass", value, th, src)


def _assess_not_brand(c: Candidate) -> Outcome:
    """Category first: an organisation category (team, club, party, union, nonprofit, restaurant,
    café, shop, brand, agency, media, venue, government, ...) fails whatever ``is_business`` says;
    a creator category passes. Without a decisive category, bio / name evidence decides (a strong
    signal such as opening hours, a street address, "rezervace stolů", "s.r.o.", or two weak ones such
    as "oficiální" + "klub" or "e-shop" + a phone number; one weak signal is enough on a professional
    account). ``unknown`` only when nothing points either way."""
    th = i18n("účet tvůrce, ne firmy", "a creator, not a company")
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    p = c.profile
    src = profile_refs(c)
    cat = (p.business_category or "").strip()
    kind = classify_category(cat)
    strong, weak = org_signals(p)
    if kind == "company" or is_sensitive_org(p):
        if is_sensitive_org(p):  # do not echo a political / religious category back
            return _org_outcome(c, th, "organizace", "an organisation", None)
        extra = strong[:1] or weak[:1]
        return _org_outcome(c, th, f"kategorie „{cat}“" + (f", v profilu „{extra[0]}“" if extra else ""),
                            f"category \"{cat}\"" + (f", profile says \"{extra[0]}\"" if extra else ""),
                            extra[0] if extra else None)
    if kind == "creator":
        return Outcome("pass", i18n(f"profil tvůrce ({cat})", f"creator profile ({cat})"), th, src)
    # "official" on its own is weak even for a professional account (many creators use it in the handle).
    plain = [_fold(re.sub(r"[._]+", " ", w)) for w in weak]
    real_weak = [w for w in plain if not _OFFICIAL.search(w) or _WEAK_ORG.search(_OFFICIAL.sub("", w) + " ")]
    if strong or len(weak) >= 2 or (real_weak and p.is_business is True):
        shown = (strong + weak)[:2]
        quoted = ", ".join(f"„{x}“" for x in shown)
        quoted_en = ", ".join(f"\"{x}\"" for x in shown)
        return _org_outcome(c, th, f"v profilu {quoted}", f"profile says {quoted_en}", shown[0])
    if p.is_business is False:
        label = f" ({cat})" if cat else ""
        return Outcome("pass", i18n(f"osobní účet{label}", f"personal account{label}"), th, src)
    if p.is_business is None and not cat:
        return unknown("typ účtu není známý", "account type unknown", th, src)
    if not cat:
        return unknown("profesionální účet bez kategorie", "professional account without a category", th, src)
    return unknown(f"kategorii „{cat}“ nejde jednoznačně zařadit",
                   f"category \"{cat}\" is ambiguous", th, src)


def _assess_language(criterion: Criterion, c: Candidate) -> Outcome:
    min_share = float(param(criterion, "min_share") or 0.0)
    th = i18n(f"aspoň {fmt_pct(min_share, 'cs')} popisků česky", f"at least {fmt_pct(min_share, 'en')} of captions in Czech")
    posts = [p for p in posts_of(c) if (p.caption or "").strip()]
    if c.profile is None:
        return unknown("profil nenačten", "profile not loaded", th, profile_refs(c))
    detected = [(p, lang_mod.detect_language(p.caption)) for p in posts]
    detected = [(p, d) for p, d in detected if d is not None]
    n = len(detected)
    if n < 3:
        return unknown(f"jen {n} {cs_plural(n, 'popisek', 'popisky', 'popisků')} s rozpoznatelným jazykem",
                       f"only {n} {'caption' if n == 1 else 'captions'} with a detectable language", th, profile_refs(c))
    cs_posts = [p for p, d in detected if d == "cs"]
    other = [p for p, d in detected if d != "cs"]
    k = len(cs_posts)
    share = k / n
    value = i18n(f"{k} z {n} popisků česky", f"{k} of {n} captions in Czech")
    if share < min_share:
        langs = [lang for lang, _ in Counter(d for _, d in detected if d != "cs").most_common()]
        names_cs = ", ".join(LANG_NAMES_CS.get(x, x) for x in langs)
        names_en = ", ".join(LANG_NAMES_EN.get(x, x) for x in langs)
        if k == 0:
            reason = i18n(f"žádný z {n} popisků není česky ({names_cs})", f"none of {n} captions is in Czech ({names_en})")
        else:
            reason = i18n(f"jen {k} z {n} popisků {cs_plural(k, 'je', 'jsou', 'je')} česky (jinak {names_cs})",
                          f"only {k} of {n} captions are in Czech (otherwise {names_en})")
        return Outcome("fail", value, th, [post_ref(p) for p in other[:5]], reason=reason)
    return Outcome("pass", value, th, [post_ref(p) for p in cs_posts[:3]])


def assess(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> Outcome:
    kind = criterion.kind
    if kind == "public_account":
        return _assess_public(candidate, brief.lang)
    if kind == "followers_range":
        return _assess_followers(criterion, candidate)
    if kind == "active_recently":
        return _assess_active(criterion, candidate, now)
    if kind == "not_brand_account":
        return _assess_not_brand(candidate)
    if kind == "language_cs":
        return _assess_language(criterion, candidate)
    raise ValueError(f"criterion kind {kind!r} is not a round-1 kind")


def evaluate(criterion: Criterion, candidate: Candidate, brief: Brief, now: datetime) -> CriterionResult:
    return assess(criterion, candidate, brief, now).result(criterion.id, brief.lang)

