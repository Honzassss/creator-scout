"""Sensitive-content filter: runs on every caption, bio, comment and news item right after fetch,
BEFORE anything is stored in the run. Dropped items only increment a counter (never stored, never
shown, not even the category per item).

Categories: health, politics, religion, ethnicity/origin, sexuality, criminal (GDPR Art. 9 + Art. 10).
LLM: model_bulk, batched structured output (one boolean per text, no category), prompt
prompts.SENSITIVE_SYSTEM. The keyword list always runs too and a text is dropped if EITHER flags it.
Fallback (no key / error): keyword lists only (cs + en, diacritics-insensitive). The keyword list is a
floor, not a classifier: its recall on real captions is unmeasured (paraphrases, slang and new names
get through), so the no-key mode is weaker than the LLM mode. record_mode("sensitive", ...).
Words with an everyday meaning only count in context ("boží snídaně", "jasná volba", "premiéra menu",
"pro alergiky" are kept). Tuned on tests/test_sensitive_dev.py (our dev phrasings) and checked against
real Brno captions. The S1 list in docs/validation-plan.md is NOT a clean held-out test any more: the
dev list contains rewordings of its earlier misses (S05, S14, H05, H14, H15), so its 16/20 sensitive
and 2/20 harmless dropped (before 14 and 3) counts as tuned. A fresh 20 + 20 list written by the
reviewer and measured once (keyword path, 9 Oct 2026): 12 of 20 sensitive dropped, 3 of 20 harmless
dropped (old code 11 and 3). So the keyword path catches roughly 60 % of sensitive captions.
Post texts include the location name; fines and administrative offences count as criminal (Art. 10).

``refusal_reason`` is the server-side guard for OWNER REQUESTS (chat messages, criterion labels): it
detects requests to filter people by religion, politics, health, sexuality, ethnicity/origin, criminal
past, a person's "values", personality, or an overall score / "best", and returns the i18n reason.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from pydantic import BaseModel

from app.llm import client as llm_client
from app.llm import prompts
from app.llm.text import clip, compile_patterns, fold
from app.models import Brief, Comment, NewsItem, Post, Profile, Refused, i18n, short_hash

SENSITIVE_CATEGORIES: tuple[str, ...] = ("health", "politics", "religion", "ethnicity", "sexuality", "criminal")

# --------------------------------------------------------------------------------------------
# 1. Content filter keywords (patterns over fold()ed text: lowercase, no diacritics)
#    Written to catch personal sensitive content while sparing ordinary food / fitness / lifestyle
#    captions (e.g. "lekce", "zdravá snídaně", "původní recept", "drogerie" are NOT matched).
# --------------------------------------------------------------------------------------------

_CONTENT: dict[str, tuple[str, ...]] = {
    # Stems that also occur inside Czech words ("psychoterapii", "otěhotněla", "cukrovce") have no
    # leading \b; stems that would hit food words keep it ("cukroví" is Christmas cookies).
    # Words with an everyday meaning carry a context rule: "pro alergiky" / "pro celiaky" describes a
    # product, "mám alergii" describes a person; "retail therapy" and "that was sick" are not health.
    "health": (
        r"\bnemoc", r"\bonemocn", r"\brakovin", r"\bonkolog", r"cukrov(k|c)\w*", r"diabet", r"\bdepres",
        r"\bantidepres", r"\buzkost", r"\bpsychiatr", r"\bpsycholog", r"(?<!retail )(?<!aroma)terapi", r"terapeut",
        r"\bdiagnoz", r"\bchemoterap", r"\bmedikac", r"\bleky\b", r"\bleku\b", r"\blekar(?!n)", r"tehotn",
        r"\bpotrat", r"\bpostizen", r"\bhandicap", r"\bautis", r"\badhd\b", r"\banorex", r"\bbulimi",
        r"\bporuch\w* prijmu", r"\bhiv\b", r"\bcovid", r"\bzranen", r"\bvyhoren", r"\bpanick\w* atak",
        r"\bdusevni (zdravi|onemocn|problem)", r"\boperac\w* (kolen|srdc|zad|kycl|ramen|menisk|slep)",
        r"\b(jsem|byla? jsem|budu|pujdu|jdu|ted|tesne)\s+(po|na|pred)\s+operac", r"\bpo operaci\b",
        r"\bporod(u|em|y|ni\w*|nic\w*|il\w*)?\b", r"\bjinac(i|e|em)?\b", r"\bivf\b", r"\bumel\w* oplodn",
        r"\buraz(u|em|y|ech|ovy|ove|ova)?\b", r"\brehabilit", r"\babstinen", r"\bstrizliv",
        r"\balkoholi(k|smus|smu|cka|cky)\b", r"\bzavislost", r"\bodvykac",
        r"\b(prestal|prestala|prestat|prestavam)\w* pit\b",
        r"\b(mam|mela? jsem|moje|muj|trpim|kvuli (me|moji|svoji)|diagnostik\w*|zjistil\w*)\s+(\w+\s+)?(alergi|celiaki)",
        r"\bjsem (alergi(k|cka)|celiak|celiacka|diabeti)", r"\balergick\w* (reakc|sok)",
        r"\binfarkt", r"\bmrtvic", r"\bepilep", r"\bastma", r"\bmigren", r"\bockovan",
        r"\bnador(?!az)", r"\bozarovan", r"\bkapack", r"\bremis(e|i)\b", r"\bdialyz", r"\binsulin", r"\binzulin",
        r"\bzlomil\w* (jsem )?(si )?(nohu|ruku|kotnik|zapest|zebr|klicni|paz)", r"\bna berlich",
        r"\bna vozicku\b", r"\bnevidom", r"\bneslysic", r"\bsebeposkoz", r"\bsebevra", r"\bneplodn",
        r"\bendometri", r"\bmenopauz", r"\bhospitaliz", r"\bskleroz", r"\bsestinedel", r"\bstitn\w* zlaz",
        r"\bhypotyre", r"\bpsychick\w* (problem|potiz|stav|zdravi|onemocn)", r"\blupenk", r"\bekzem", r"\b(cekame|cekam|ocekavame)\s+(\w+\s+)?(miminko|mimino|prirustek|dite|holcicku|chlapecka)",
        r"\bdisease", r"\bcancer", r"\bdepress", r"\banxiety", r"(?<!retail )\btherap", r"\bdiagnos", r"\bhospital(?!ity)",
        r"\bsurgery", r"\bmedication", r"\bpregnan", r"\bdisabilit", r"\billness",
        r"\b(i|she|he|we|they|kids|son|daughter)\s+(am|was|were|is|are|got|get|feel|felt|have been|has been|had been)\s+(so\s+|really\s+|very\s+)?sick\b",
        r"\b(i'm|im|been|getting|feeling|still)\s+(so\s+|really\s+|very\s+)?sick\b",
        r"\bsick (leave|day|kid|child)",
        r"\bmental health", r"\binjur", r"\bpanic attack", r"\bburn-?out\b", r"\bchronic", r"\bivf\b",
        r"\bsober\b", r"\bsobriety", r"\baddict", r"\brehab\b", r"\bvaccin", r"\bchemo\b", r"\btumou?r",
        r"\bmiscarr", r"\beating disorder", r"\bself-?harm", r"\bsuicid", r"\bwheelchair", r"\binfertil",
        r"\bexpecting (a baby|our (first|second|third)|twins)", r"\bon (meds|medication|antidepressants)\b",
        r"\bocd\b", r"\bptsd\b", r"\bbipolar", r"\bautoimmun", r"\bibs\b", r"\bpostpartum",
    ),
    # "volba"/"volby" is also "choice(s)", "volím" also "I choose", "premiéra" also "premiere", "piráti"
    # also pirates: those count only next to an election / office / party word.
    "politics": (
        r"\bvoleb\b", r"\bvolebn", r"\b(k|ke|ve|v|pred|po|u|pri|kvuli|behem|kolem)\s+volb(am|ach|ami)\b",
        r"\bvolb(y|ach|am|ami)\s+(do|na|v|ve|20\d\d)\b",
        r"\b(komunaln|krajsk|senatn|parlamentn|prezidentsk|snemovn|evropsk|obecn|predcasn|letosn|pristi|nadchazejic)\w*\s+volb",
        r"\b(jit|pujdu|pujdete|pujdeme|jdete|jdu|jdeme|jsem byla?|byli jsme|nezapomente)\s+(\w+\s+)?volit\b",
        r"\b(koho|komu)\s+(budu|budete|bych|mam|by)\s+(\w+\s+)?vol", r"\bvolit\s+(stran|kandidat|hnut|levic|pravic|babis|ano\b|ods\b|spd\b|pirat)",
        r"\bvolte\s+(jinak|zmenu|nas|stranu|ano\b|ods\b|spd\b|pirat|kandidat|spolu|nove|zelene)",
        r"\bvolte\s+(c\.?|cislo|č\.?)\s*\d", r"\bkomunalk", r"\bvolby\s+(jsou|budou|byly|se blizi|se konaj)",
        r"\bnevol(i|il|ime)\b", r"\bhlasoval", r"\bdam (jim|mu|ji) (svuj )?hlas\b", r"\bkazdy hlas se pocita",
        r"\bpoliti", r"\bparlament", r"\bsenat(?!ni ulic)", r"\bvlad(a|y|e|u|ni)\b", r"\bministr",
        r"\bprezident", r"\bpremier(ovi|em|ka|ky|ce|kou)\b", r"\b(pan|pani|byval\w*|novy|nova|soucasn\w*|cesk\w*)\s+premier",
        r"\bpremier\s+(fial|babis|sobotk|zeman|klaus|nec|topolan|gross|spidl)", r"\bposlan(ec|ci|kyne|ecka|cu|kyni)",
        r"\bods\b", r"\bspd\b", r"\bpiratsk\w*\s+(stran|poslan|volic|hnut|zastupitel|primator|kandidat|program)",
        r"\b(strana|poslan\w*|zastupitel\w*|primator\w*|kandidat\w*|volic\w*)\s+(za\s+)?pirat",
        r"\bkscm\b", r"\bkomunis", r"\bcssd\b", r"\bsocdem", r"\btop 09\b", r"\bbabis", r"\bokamur",
        r"\blidovc", r"\bkdu-?csl\b", r"\bhnuti ano\b", r"\banarchis",
        r"\bkandid(uj|ova|atk|atu|at\b|atn)\w*\s+(\w+\s+){0,2}?(do|na|za|v|ve)\s+(zastupitel|magistrat|senat|parlament|snemovn|kraj|obec|mest|prezident|starost|primator)",
        r"\bkandid\w* c\.\s?\d", r"\bzastupitelstv", r"\bkandidatn\w* listin",
        r"\blevic", r"\bpravic", r"\bliberal", r"\bkonzervativ", r"\bdemonstrac", r"\bprotest", r"\bpetic",
        r"\breferend", r"\bfasis", r"\bnacis", r"\bvalk(a|u|y|ou|e)\s+(na|v|ve|s|proti|mezi)\s+(?!posledn|o\b)",
        r"\bvalce\b", r"\bvalk(a|u|y|ou)\s+(na ukrajin|v gaz|v izrael|na blizk)", r"\bmigra(c|nt)",
        r"\bimigra", r"\buprchl", r"\bputin", r"\btrump", r"\bpodpor\w* ukrajin", r"\bslava ukrajin",
        r"\bsbirk\w* na (drony|armad|zbran|naboj)", r"\bdrony pro ukrajin", r"\baktivist", r"\bfeminis",
        r"\bdezol", r"\bsluni?ckar", r"\bantivax", r"\bpro-?life\b", r"\bpro-?choice\b",
        r"\bstavk(a|y|u|ou|ovat|ujeme|uji|uje)\b", r"\bodborar", r"\bodborov\w* (organizac|svaz)",
        r"\belection", r"\bvote (for|against)\b", r"\bvoting (for|against)\b", r"\bvoted (for|against)\b",
        r"\bgo vote\b", r"\b(i|we) (will )?vote\b", r"\bgovernment", r"\bparliament",
        r"\bleft-?wing", r"\bright-?wing", r"\bfar-?(right|left)\b", r"\bdemocrat", r"\brepublican", r"\bfascis", r"\bnazi(s|sm|st|sts)?\b",
        r"\bwar (in|on|against)\b", r"\bimmigra", r"\brefugee", r"\bstand with (ukraine|israel|palestine)",
        r"\bfree palestine", r"\bactivis", r"\bmaga\b", r"\babortion", r"\bgun control",
        r"\b(running|run|candidate) for (city |town |the |state )?(council|mayor|office|senate|parliament|congress)",
        r"\bprime minister\b", r"\bbrexit",
    ),
    # "boží" / "božský" are everyday slang for "great" ("boží snídaně"); "u kostela" names a place.
    "religion": (
        r"\bbuh\b", r"\bboh(a|u|em|ove)\b", r"\bbozi (slov|milost|pozehnan|vul|dar|lask|hrob|telo|chram|muk|syn|matk|prozretel)",
        r"\bpan buh\b", r"\bverici", r"\bneverici",
        r"\bvir(a|u|y|ou)\b(?! ve (sebe|vas|tebe))", r"\bcirkev", r"\bcirkv", r"\b(do|ve?)\s+kostel(e|a)?\b",
        r"\bkostel\w*\s+(chodim|chodime|chodila|chodil)",
        r"📍\s*(\w+\s+)?(kostel|chram|katedral|bazilik|synagog|mesit|church|cathedral|mosque)", r"\bmodlit", r"\bmodlim",
        r"\bmodli se\b", r"\bbible", r"\bbibli", r"\bkrestan", r"\bkrest\b", r"\bpokrt", r"\bkatol",
        r"\bevangel", r"\bprotestant", r"\bmuslim", r"\bislam", r"\bmesit", r"\bkoran", r"\bramadan",
        r"\bzid(e|u|y|ovsk\w*|ovstv\w*)?\b(?! (ctvrt|hrbitov|mest))", r"\bjudais", r"\bsynagog", r"\bbuddh(?!a[\s-]?bowl)", r"\bhinduis",
        r"\bateis", r"\bathei", r"\bmse\b", r"\bmsi\b", r"\bfarar", r"\bfarnost", r"\bknez", r"\bpastor\b",
        r"\bpust(u|em)?\s+(o|pred|pres|behem|na)\s+(\w+\s+)?(velikonoc|vanoc|ramadan)", r"\bpostni dob",
        r"\bdrz\w* pust\b",  # not "postím" (= "I post" in creator slang)
        r"\bpust\b\W+(\w+\W+){0,4}?(duchovn|nabozensk|vir)", r"\bduchovn\w*\W+(\w+\W+){0,4}?pust\b",
        r"\bbohosluzb", r"\bkristus\b", r"\bkrista\b", r"\bkristov", r"\bsvat\w* prijiman", r"\bprvni prijiman", r"\bbirmovan", r"\bruzenec", r"\bposviceni\b",
        r"\bchurch", r"\bpray", r"(?<!oh my )(?<!thank )\bgod\b(?! knows)", r"\bjesus", r"\bjezis", r"\bfaith\b", r"\breligio",
        r"\bnabozens", r"\bchristian", r"\bcatholic", r"\bmosque", r"\bspiritual", r"\b(during|for) lent\b",
        r"\beid mubarak", r"\b(easter|christmas|sunday|midnight|evening) mass\b", r"\bsabbath",
        r"\bhanukk?ah", r"\bchanuk", r"\bhijab", r"\bhidzab", r"\bpilgrimage", r"\bbaptis",
    ),
    "ethnicity": (
        r"\brom(ove|u|y|ka|ky|ske|sky|ska|skou|skych|skym)\b", r"\bcikan", r"\bgyps(y|ies)\b", r"\betni",
        r"\bethnic", r"\bras(a|y|ou)\b(?!\W+(\w+\W+){0,6}?(ps|pes|koc|kon|plemen|bigl|labrador|dog|cat))",
        r"\brasov", r"\brasis", r"\bracis", r"\bnarodnost",
        r"\bnationality", r"\b(muj|moje|nas|jeho|jeji|svuj|etnick\w*|narodnostn\w*)\s+puvod",
        r"\b(jsem|jsme|je|byla?|byli)\s+(\w+\s+)?puvodem\b", r"\bpuvodem\s+(jsem|jsme)\b", r"\bpristehoval", r"\bimigrant", r"\bimmigrant",
        r"\bxenofob", r"\bxenophob", r"\bantisemit", r"\bbarv\w* pleti", r"\bskin colou?r",
        r"\bblack lives", r"\bblm\b", r"\bmensin", r"\bminorit",
        # nationality as identity ("Jsem Ukrajinka", "Jako Vietnamka jsem vyrostla...", "pocházím z Ukrajiny")
        r"\bukrajin(ka|ky|kou|ec|ci|cum|cich|cem)\b", r"\bvietnam(ka|ky|kou|ec|ci|cum|cich|cem)\b",
        r"\b(jsem|jsme|pochaz\w*|narodil\w*|rodem|rodak\w*|puvodem)\s+(z|ze)\s+(ukrajin|vietnam|ruska|polska|slovenska|"
        r"indie|ciny|turecka|syrie|afghanist|nigerie|mongolska|bulharska|rumunska|moldav)",
        r"\b(i am|i'm|as an?) (ukrainian|vietnamese|immigrant|refugee|roma|romani)\b",
        r"\bas an? (black|brown|asian|latina?|latino|white|mixed-race|biracial) (woman|man|person|girl|guy|mom|mum|dad|creator)",
        r"\bcerno(ch|sk[ay]\b|sk[ou]u?\b)", r"\basiat(ka|ky|ce|e|i|kou)\b", r"\bmixed-?race\b", r"\bbiracial\b",
        r"\bpeople of colou?r\b", r"\bmy heritage\b",
    ),
    "sexuality": (
        r"\bgay", r"\blesb", r"\bhomosex", r"\bbisex", r"\btransgend", r"\btrans\b(?!\s*(tuk|mastn|fat))", r"\btranssex",
        r"\bnon-?binar", r"\bnebinar", r"\blgbt", r"\bqueer", r"\bpride (month|parade|march|flag|week|festival|walk)",
        r"\b(prague|brno|praha) pride", r"\b(at|to|for) pride\b(?! in)", r"#pride\b", r"\bduhov\w* pochod",
        r"\bpochod\w* hrdosti", r"\bprague pride", r"\b(se|jsme se)\s+(konecne\s+)?vzaly\b", r"\bvzaly jsme se\b",
        r"\bjeho (manzel|snoubenec)(em|a|ovi|i)?\b", r"\bjeji (manzelk|snoubenk)\w*", r"\b(s )?moji zenou jsme se vzaly",
        r"\bduhov\w* (rodin|rodic)", r"\bthey/them\b", r"\bjsem (bi|bisexual\w*)\b",
        r"\bsexualn", r"\bsexual", r"\bcoming ?out\b", r"\bstejnopohlav", r"\bsame-sex",
    ),
    # Art. 10: criminal matters, incl. fines for offences and administrative delicts (C-439/19).
    "criminal": (
        r"\bodsouz", r"\bobvinen", r"\bobzalob", r"\btrestn\w* (cin|stihan|oznamen|rejstrik|cinnost)",
        r"\bpolici\w*\W+(\w+\W+){0,3}?(vysetr|obvin|zadrz|stih|zatkl|pokut|zastavil|nadych)",
        r"\b(vysetr|obvin|zadrz|stih|zatkl)\w*\W+(\w+\W+){0,3}?polici",
        r"\bzatcen", r"\bzadrzen", r"\bvezen", r"\bkriminal",
        r"\bsoud(u|em|ni|niho)?\b", r"\bpodvod", r"\bkradez", r"\b(u)?kradl\w*\b(?!\W+(\w+\W+){0,2}?srd)",
        r"\bznasiln", r"\bvrazd", r"\bvrah", r"\bdrog(a|y|u|ou|ami|ach|ovy|ove|ovou|ovych)?\b", r"\bkokain",
        r"\bpervitin", r"\bmarihuan", r"\bmarijuan", r"\bdanov\w* unik", r"\bza volantem\s+(pod vlivem|opil)",
        r"\bopil(y|a)\s+za volantem", r"\bpod vlivem (alkoholu|drog|navykov)", r"\bprististen", r"\b(cist|trestn)\w* rejstrik",
        r"\bpokut(?!ov(y|e|eho|em|ym)\s+(kop|uzem|hod|strel|kriz))", r"\bsankc", r"\bprestup(ek|ku|kem|ky|cich)\b", r"\bspravn\w* delikt",
        r"\bnadychal", r"\b\d+([.,]\d+)?\s*promile\b", r"\b(vzali|sebrali|odebrali|zabavili)\s+(mi\s+)?(ridicak|ridicsky prukaz|papiry)",
        r"\bzakaz rizeni", r"\b(ve|do|z)\s+vazb(e|y|u)\b", r"\bbez ridicak", r"\bdostal\w*\s+(jsem\s+|jsme\s+)?podminku\b", r"\bpodminen\w* trest", r"\bpodminecn\w* propust",
        r"\bconvict", r"\bcharged with", r"\barrest", r"\bprison", r"\bjail", r"\bcriminal", r"\bfraud",
        r"\bassault", r"\bmurder", r"\btheft", r"\bindict", r"\bstalk", r"\bfined\b", r"\bdrunk driv",
        r"\bdrink-?driv", r"\bdui\b", r"\bdwi\b", r"\bprobation\b", r"\bon parole\b", r"\bparole (officer|board|hearing)", r"\bfelony", r"\bmisdemeano",
        r"\b(speeding|parking) (ticket|fine)", r"\bshoplift", r"\bpolice (stopped|arrested|caught|fined|questioned)",
        r"\b(in|to|at) court\b", r"\bcourt (case|hearing|date)",
    ),
}

_CONTENT_RE = compile_patterns([p for pats in _CONTENT.values() for p in pats])


def keyword_flags(texts: list[str]) -> list[bool]:
    """Fallback: True = sensitive (drop)."""
    return [bool(t) and bool(_CONTENT_RE.search(fold(t))) for t in texts]


_POLITICS_RE = compile_patterns(list(_CONTENT["politics"]))


def political_flags(texts: list[str]) -> list[bool]:
    """True = the text matches a politics keyword. Used only to recognise a political organisation
    (round 1 removes it before anything is stored); never shown, stored or used to judge a person."""
    return [bool(t) and bool(_POLITICS_RE.search(fold(t))) for t in texts]


# --------------------------------------------------------------------------------------------
# 2. LLM batch classification (one boolean per text; no category is ever returned or stored)
# --------------------------------------------------------------------------------------------

BATCH = 40
TEXT_MAX = 700


class _Flag(BaseModel):
    i: int
    sensitive: bool


class _Flags(BaseModel):
    flags: list[_Flag]


async def _llm_batch(texts: list[str]) -> list[bool] | None:
    """Flags for one batch, or None when the model is unavailable / failed."""
    key = short_hash("\n\x00".join(texts), 16)
    cached = llm_client.cache_get("sensitive", key)
    if isinstance(cached, list) and len(cached) == len(texts):
        return [bool(x) for x in cached]
    numbered = "\n".join(f"[{i}] {clip(t, TEXT_MAX).replace(chr(10), ' ')}" for i, t in enumerate(texts))
    user = (
        f"Texts to check ({len(texts)}). Return one entry per index 0..{len(texts) - 1}.\n"
        f"<texts>\n{numbered}\n</texts>"
    )
    out = await llm_client.structured(
        _Flags, system=prompts.SENSITIVE_SYSTEM, user=user, max_tokens=4000, effort="low", task="sensitive"
    )
    if out is None:
        return None
    by_i = {f.i: f.sensitive for f in out.flags if 0 <= f.i < len(texts)}
    # An index the model skipped is decided by the keyword list alone (the caller ORs both).
    flags = [bool(by_i.get(i, False)) for i in range(len(texts))]
    llm_client.cache_put("sensitive", key, flags)
    return flags


async def filter_texts(texts: list[str]) -> tuple[list[bool], int]:
    """-> (kept_mask, dropped_count); kept_mask[i] is False for a dropped text."""
    if not texts:
        return [], 0
    kw = keyword_flags(texts)
    flags = list(kw)
    # Only non-empty texts the keywords did not already drop need the model.
    idx = [i for i, t in enumerate(texts) if t and t.strip() and not kw[i]]
    if idx and llm_client.llm_available():
        batches = [idx[k:k + BATCH] for k in range(0, len(idx), BATCH)]
        results = await asyncio.gather(*(_llm_batch([texts[i] for i in b]) for b in batches))
        for b, res in zip(batches, results):
            if res is None:
                llm_client.record_mode("sensitive", "fallback")
                continue
            llm_client.record_mode("sensitive", "llm")
            for i, f in zip(b, res):
                flags[i] = flags[i] or f
    elif idx:
        llm_client.record_mode("sensitive", "fallback")
    kept = [not f for f in flags]
    return kept, sum(flags)


filter = filter_texts  # architecture.md name: sensitive.filter(texts) -> (kept_mask, dropped_count)


def _post_text(p: Post) -> str:
    """Caption + hashtags not already in it + location name (a place can be sensitive too)."""
    tags = " ".join(f"#{h}" for h in p.hashtags if f"#{h}" not in (p.caption or "").lower())
    loc = f" 📍 {p.location_name}" if p.location_name else ""
    return f"{p.caption or ''} {tags}{loc}".strip()


async def filter_posts(posts: list[Post]) -> tuple[list[Post], int]:
    """Drop posts whose caption (+ hashtags) is sensitive. -> (kept_posts, dropped_count)."""
    kept, n = await filter_texts([_post_text(p) for p in posts])
    return [p for p, k in zip(posts, kept) if k], n


async def filter_comments(comments: list[Comment]) -> tuple[list[Comment], int]:
    kept, n = await filter_texts([c.text for c in comments])
    return [c for c, k in zip(comments, kept) if k], n


async def filter_news(items: list[NewsItem]) -> tuple[list[NewsItem], int]:
    """On title + snippet."""
    kept, n = await filter_texts([f"{it.title}. {it.snippet}" for it in items])
    return [it for it, k in zip(items, kept) if k], n


async def filter_profile(profile: Profile) -> tuple[Profile, int]:
    """Copy with bio blanked if sensitive and latest_posts filtered. -> (profile, dropped_count)."""
    texts = [profile.bio or ""] + [_post_text(p) for p in profile.latest_posts]
    kept, n = await filter_texts(texts)
    posts = [p for p, k in zip(profile.latest_posts, kept[1:]) if k]
    update: dict = {"latest_posts": posts}
    if not kept[0]:
        update["bio"] = ""
    return profile.model_copy(update=update, deep=True), n


# --------------------------------------------------------------------------------------------
# 3. Owner-request guard (chat + criteria validation)
# --------------------------------------------------------------------------------------------

_POLITICS_REASON = i18n(
    "Politické názory jsou zvláštní kategorie údajů (čl. 9 GDPR); podle nich lidi netřídíme.",
    "Political opinions are special-category data (GDPR Art. 9); we do not sort people by them.",
)

REFUSAL_REASONS: dict[str, dict[str, str]] = {
    "religion": i18n(
        "Náboženská víra je zvláštní kategorie údajů (čl. 9 GDPR); podle ní lidi netřídíme.",
        "Religious belief is special-category data (GDPR Art. 9); we do not sort people by it."),
    "politics": _POLITICS_REASON,
    "health": i18n(
        "Zdravotní stav je zvláštní kategorie údajů (čl. 9 GDPR); podle něj tvůrce nevybíráme.",
        "Health is special-category data (GDPR Art. 9); we do not select creators by it."),
    "sexuality": i18n(
        "Sexuální orientace je zvláštní kategorie údajů (čl. 9 GDPR); podle ní lidi netřídíme.",
        "Sexual orientation is special-category data (GDPR Art. 9); we do not sort people by it."),
    "ethnicity": i18n(
        "Etnický původ ani národnost neposuzujeme (čl. 9 GDPR); kontrolovat můžeme jazyk obsahu a lokální signály.",
        "We do not judge ethnic origin or nationality (GDPR Art. 9); we can check content language and local signals."),
    "criminal": i18n(
        "Trestní minulost nezpracováváme (čl. 10 GDPR); ověřujeme jen veřejné spolupráce a označování reklamy.",
        "We do not process criminal records (GDPR Art. 10); we only check public collaborations and ad disclosure."),
    "demographics": i18n(
        "Věk a pohlaví publika z veřejných dat zjistit nejde a neodhadujeme je. Zeptejte se tvůrce na jeho statistiky.",
        "Audience age and gender cannot be known from public data and we do not estimate them. Ask the creator for their insights."),
    "values": i18n(
        "Hodnoty ani přesvědčení člověka z veřejných dat spolehlivě nepoznáme a soudit je nebudeme; můžeme kontrolovat, o čem a jak tvoří.",
        "We cannot reliably read a person's values or beliefs from public data and will not judge them; we can check what and how they post."),
    "personality": i18n(
        "Povahu člověka z postů nehodnotíme; můžeme kontrolovat obsah, formát a aktivitu publika.",
        "We do not assess anyone's personality from posts; we can check content, format and audience activity."),
    "score": i18n(
        "Celkové skóre ani „nejlepšího“ tvůrce neurčujeme; ukážeme důkazy u každého kritéria a rozhodnete vy.",
        "We do not give an overall score or pick a “best” creator; we show the evidence per criterion and you decide."),
    "appearance": i18n(
        "Vzhled ani postavu tvůrců neposuzujeme; můžeme kontrolovat, o čem a jak tvoří.",
        "We do not judge creators' looks or bodies; we can check what and how they post."),
    "personal": i18n(
        "Věk, rodinu, vztahy, původ ani povahu tvůrce nezjišťujeme; kontrolujeme jen veřejný obsah, spolupráce a označování reklamy. Pokud je to pro spolupráci podstatné, zeptejte se na prvním setkání.",
        "We do not look into a creator's age, family, relationships, origin or character; we only check public content, collaborations and ad disclosure. If it matters for the collaboration, ask at the first meeting."),
}

UNSUPPORTED_REASON = i18n(
    "Tohle z veřejných dat spolehlivě nezměříme, takže to jako kritérium nepoužijeme.",
    "We cannot measure this reliably from public data, so we do not use it as a criterion.",
)

# Person nouns used by several categories ("jen bílí tvůrci", "černí lidé").
_PEOPLE = r"(tvurc|tvurkyn|lid|lidi|influencer|holk|kluk|zen|muz|creators?|people|influencers?)"
_AUDIENCE = r"(publik|sledujic|sledoval|followers?|audience|fanousk)"
_GENDER_AGE = (r"(zen(a|y|am|ami|ach|sk\w*)?|muz(i|ich|um|sk\w*)|women|men|female|male|holk\w*|klu(k|ci|ku)\w*|"
               r"divk\w*|mamin\w*|matk\w*|moms?|mums?|mothers?|teens?|teenager\w*|duchodc\w*|senior\w*)")

_GUARD: dict[str, tuple[str, ...]] = {
    "religion": (
        r"\bveric", r"\bneveric", r"\bkrestan", r"\bkatol", r"\bmuslim", r"\bislam",
        r"\bzid(e|u|y|ovsk\w*)?\b", r"\bbuddh", r"\bateist", r"\bnabozens", r"\bcirkev", r"\bcirkv",
        r"\bvir(a|u|y|ou)\b", r"\bv boha\b", r"\bbuh\b", r"\bkostel", r"\bmse\b", r"\bmodli", r"\bbible",
        r"\bbeliever", r"\breligio", r"\bchristian", r"\bcatholic", r"\bjewish", r"\bjews?\b", r"\batheist",
        r"\bfaith", r"\bmuslims?\b", r"\bchurch",
    ),
    "politics": (
        r"\bpoliti", r"\bapolit", r"\bvoli\b", r"\bnevol(i|il|ime)", r"\bvolic", r"\bvolil", r"\bvolb",
        r"\bvoleb", r"\blevic", r"\bpravic", r"\bliberal", r"\bkonzervativ", r"\bkomunis", r"\bstranick",
        r"\bbabis", r"\bokamur", r"\bspd\b", r"\bods\b", r"\bpirat(i|u|um|ech)\b", r"\bpiratsk\w* (stran|poslan|volic)",
        r"\bkscm\b",
        r"\baktivist", r"\bfeminist", r"\bdezol", r"\bsluni?ckar", r"\bantivax", r"\bockovan",
        r"\bvot(e|er|ers|ing)\b", r"\bleft-?wing", r"\bright-?wing", r"\bdemocrat", r"\brepublican",
        r"\bprogresiv", r"\bprogressive", r"\bwoke\b", r"\bactivists?\b", r"\bfeminists?\b",
        r"\bpro-?life\b", r"\bpro-?choice\b", r"\banti-?vax",
    ),
    "health": (
        r"(?<!pro )\bzdravi\b", r"\bzdravotn", r"\bnemoc", r"\bpostizen", r"\bhandicap", r"\btehotn",
        r"\bdiagnoz", r"\bpsychick", r"\bdusevni", r"\bnemocn", r"\bzdrav(e|y|i|ych|ou)\s+" + _PEOPLE,
        r"\bhealth\b(?!\s*(food|foods|store|shop|bar|club|studio|center|centre)\b)", r"\billness",
        r"\bdisease", r"\bsick\b", r"\bdisab", r"\bpregnan", r"\bmental", r"\bhealthy (people|creators?|ones)\b",
    ),
    "sexuality": (
        r"\bgay", r"\blgbt", r"\bqueer", r"\bhomosex", r"\blesb", r"\bbisex", r"\btrans(gender|sexual)?\b",
        r"\bhetero", r"\bsexualit", r"\bsexualn", r"\bsexual", r"\borientac\w*\s+" + _PEOPLE,
        r"\b(sexualn|normaln|spravn|tradicn)\w* orientac", r"\bteplous", r"\bbuzn", r"\bpride (month|parade|march|flag)",
        r"\b(about|at|attends?|goes to|support\w*) pride\b",  # not "we take pride in our bread"
        r"\bstraight\s+(creators?|people|only|guys|men|women|ones)\b", r"\bonly straight\b",
    ),
    "ethnicity": (
        r"\bnarodnost", r"\bpuvod(u|em)?\b", r"\betni", r"\bethnic", r"\bras(a|y|ou)\b", r"\brasov",
        r"\brasis", r"\bracis", r"\bracial", r"\brom(ove|u|y|um|ech|ka|ky|ske|sky|ska|skou|skych)\b",
        r"\bcikan", r"\bgyps", r"\bcizin", r"\bnationalit", r"\borigin\b", r"\bimigrant", r"\bimmigrant",
        r"\bpristehoval", r"\bmigrant", r"\bbarv\w* pleti", r"\bskin colou?r", r"\bcesi\b", r"\bcechu\b",
        r"\bcernoch", r"\b(bil|cern|zlut|hned)(i|y|e|a|ych|ym|ymi)\s+" + _PEOPLE,
        # person nouns only: "vietnamské bistro" / "ukrajinský boršč" describe a business, not people
        r"\bvietnam(ci|ce|cu|cum|cich|ec|ky|ka|kam)\b", r"\bukrajin(ci|ce|cu|cum|cich|ec|ky|ka|kam)\b",
        r"\brus(ove|y|aky|aci|ky)\b", r"\barab(ove|u|um|ky|ka)?\b", r"\basiat", r"\bafri(k|c)",
        r"\brodil\w*\s+(ces|cech)", r"\bforeign\w*", r"\bnative (czechs?|speakers?|people|creators?)\b",
        r"\bonly natives?\b",
        r"\b(white|black|asian|brown) (people|creators|only|influencers?|ones)\b",
        r"\bonly (white|black|asian)\b", r"\bno (black|asian|arab)\w*\b",
    ),
    # Art. 10 incl. fines / administrative offences (C-439/19).
    "criminal": (
        r"\btrestan", r"\btrestn\w* (minul|rejstrik|cin)", r"\brejstrik\w*( trest\w*)?", r"\bodsouz",
        r"\bcriminal", r"\bconvict", r"\bvezen", r"\bjail", r"\bprison", r"\barrest", r"\bzatcen", r"\bzatkl",
        r"\bpolici", r"\bproblem\w* se zakonem", r"\btrouble with the law", r"\bpokut", r"\bfined\b",
    ),
    # Audience age / gender requests ("publikum hlavně ženy 20–30 let"): never estimated (hard line).
    # Needs an audience word next to an age / gender word, so describing one's own customers
    # ("rodiny a mladí lidé", "cílovka jsou ženy 25–35") and the criteria texts ("... ne demografie")
    # do not trigger it.
    "demographics": (
        r"\b" + _AUDIENCE + r"\w*\W+(\w+\W+){0,4}?" + _GENDER_AGE + r"\b",
        r"\b" + _GENDER_AGE + r"\W+(\w+\W+){0,3}?" + _AUDIENCE,
        r"\b(vek\w*|pohlavi|age|gender)\W+(\w+\W+){0,2}?" + _AUDIENCE,
        r"\b" + _AUDIENCE + r"\w*\W+(\w+\W+){0,4}?(\d{2}\s*[-–]\s*\d{2}|vek\w*|aged?|gender|pohlavi|let)\b",
        r"\b(audience|follower) (age|gender|demographics?)\b",
    ),
    "values": (
        r"\b(rodinn|tradicn|krestansk|konzervativn|liberaln|nase|nasi|stejn|sdil|osobn|moraln|zivotn)\w* hodnot",
        r"\bsdil\w* (nase |stejne |nasi )?hodnot", r"\bhodnot(y|ami)\b (jako|stejne)",
        r"\bpresvedcen", r"\b(politick|nabozensk|svetov)\w* nazor", r"\bnazor\w* na (politik|nabozens|vir|svet)",
        r"\bbez (politickych |jakychkoli )?nazor",
        r"\bvegan(i|y|ka|ky|ek|um|ech|ove)\b", r"\bvegans\b", r"\bonly vegan (creators?|people|influencers?)",
        r"\b(family|traditional|christian|conservative|liberal|shared|same|our|personal|moral) values\b",
        r"\bshares? (our )?values\b", r"\bbeliefs?\b", r"\b(political|religious) (opinion|view|belief)s?\b",
        r"\bworld ?view", r"\bmoral(s|ity)\b",
    ),
    "appearance": (
        r"\b(stihl|hubene|hubenou|hubeny|hubenych|tlust|nadvah|obez)\w*", r"(?<!low-)(?<!low )\bfat\b", r"\boverweight",
        r"\b(slim|skinny|thin)\s+(creators?|women|girls|people|ones|only)\b",
        r"\b(hezk|pekn|atraktivn|sexy)\w*\s+(holk|tvurkyn|zen|kluk|muz|tvurc|lid)",
        r"\b(good-?looking|attractive|pretty|hot)\s+(creators?|women|girls|guys|people)\b",
    ),
    "personality": (
        r"\bpovah", r"\bosobnost", r"\bpersonalit", r"\bintrovert", r"\bextrovert", r"\bcharakter",
        r"\btemperament", r"\bsympatick", r"\blikea?ble\b",
    ),
    # Questions about a creator's private life or character ("kolik mu je let?", "je ženatý?").
    "personal": (
        r"\bkolik (mu|ji|jim) je\b", r"\bkolik je (mu|ji|jim) let",
        r"\bjak (je )?star(y|a|ej)\s+(je\s+)?(on|ona|tvurc\w*|tvurkyn\w*|influencer\w*)\b",
        r"\bvek\w*\s+(tvurc|tvurkyn|influencer)",
        r"\bhow old\b", r"\b(je|jsou) (zenat|vdan|rozveden|svobodn)", r"\bzenaty\b", r"\bvdana\b",
        r"\b(is|are) (he|she|they) (married|divorced|single)\b", r"\b(married|divorced)\b",
        r"\bma (rodinu|deti|dite|partner(a|ku)?|pritel(e|kyni)|manzel(a|ku)|zenu|muze)\b",
        r"\b(has|have) (kids|children|a family|a (wife|husband|partner|boyfriend|girlfriend))\b",
        r"\bodkud (je|jsou|pochaz)", r"\bwhere (is|are) (he|she|they) from\b", r"\bfrom originally\b",
        r"\bjaky je to clovek\b", r"\bjaka je to (holka|zena|osoba|clovek)\b",
        r"\b(je|jsou) (arogant\w*|namysl\w*|mil(y|a|i)\b|hodn(y|a|i)\b|zl(y|a|i)\b|sympatick\w*|protivn\w*)",
        r"\b(is|are) (he|she|they) (a )?(nice|arrogant|rude|friendly|kind|mean)\b", r"\bnice person\b",
        r"\bwhat (kind of )?(a )?person\b",
        r"\bgood person\b", r"\b(is|are) (he|she|they) (a )?(good|bad|decent|honest) (person|guy|man|woman|human|people)\b",
        r"\b(je|jsou) (to )?(dobr|slusn|poctiv)\w* (clovek|osoba|lide)\b",
    ),
    "score": (
        r"\bnejlepsi\w*\s+(tvurc|influencer|kandidat|clovek|cloveka|volb|ucet|ucty|profil|z nich)",
        r"\bkdo (je|by byl|bude) (ten |tou )?nejlepsi", r"\bnejlepsiho\b", r"\bvyber\w*( mi)?( jen)?( toho| jednoho)? nejlepsi",
        r"\bskore\b", r"\bscor(e|es|ing)\b", r"\bzebric", r"\bcelkov\w* (hodnocen|skore|znamk|bod)",
        r"\bhodnocen\w* (tvurc|influencer|lid|osob)", r"\bohodno", r"\boverall (score|rating|rank)",
        r"\brank", r"\briziko", r"\brizikov", r"\brisk (score|level|rating|profile)", r"\brisky\b",
        r"\btop ?\d+\b", r"\bvitez", r"\bwinner", r"\bbest (creator|influencer|one|candidate|match|fit|person)",
        r"\bwho('s| is) (the )?best\b", r"\bpick (the )?(best|winner)\b", r"\bznamk", r"\bnejspolehliv",
        r"\bnejbezpecn", r"\bnejduveryhodn", r"\btrustworth", r"\bmost (reliable|trustworthy|safe)\b",
        r"\brate (them|each|the creators|creators)\b",
        r"\bhow would you rate\b", r"\brate (him|her|this creator|the creator|this account|the account)\b",
        r"\boverall (grade|verdict)\b", r"\bjak bys? (ho|ji|je) (hodnotil|ohodnotil)\w*",
    ),
}

_GUARD_RE = {cat: compile_patterns(pats) for cat, pats in _GUARD.items()}
# Priority when one request matches several categories.
_GUARD_ORDER = ("religion", "politics", "sexuality", "health", "ethnicity", "criminal", "demographics", "values",
                "appearance", "personality", "personal", "score")
_ART9 = ("religion", "politics", "sexuality", "health", "ethnicity")


def refusal_reason(text: str) -> dict[str, str] | None:
    """For the chatbot / criteria validation: if an owner's request targets a sensitive trait
    (religion, politics, health, sexuality, ethnicity/origin, a person's "values", personality,
    an overall score / "best"), return the i18n reason for Refused.reason; else None."""
    t = fold(text)
    if not t:
        return None
    # A request can hit several categories ("věřící bez politických názorů"); name each one.
    cats = [cat for cat in _GUARD_ORDER if _GUARD_RE[cat].search(t)]
    if not cats:
        return None
    if any(c in _ART9 for c in cats):  # the Art. 9 sentence already covers the vaguer catch-alls
        cats = [c for c in cats if c not in ("values", "personal")]
    hits = [REFUSAL_REASONS[cat] for cat in cats]
    return {lang: " ".join(h[lang] for h in hits) for lang in hits[0]}


def any_refusal(texts: Iterable[str]) -> dict[str, str] | None:
    for t in texts:
        r = refusal_reason(t or "")
        if r:
            return r
    return None


NEUTRAL_BUSINESS = {"cs": "firma", "en": "business"}


def sanitize_brief(brief: Brief) -> tuple[Brief, list[Refused]]:
    """Guard the owner's free-text brief fields (business type, city, audience, goal, budget,
    competitor names) before they are stored or reused (e.g. in the outreach draft). A flagged field
    is blanked (business type -> a neutral word) and recorded as Refused(text, reason)."""
    refused: list[Refused] = []
    update: dict = {}

    def check(value: str | None) -> bool:
        r = refusal_reason(value or "")
        if r:
            refused.append(Refused(text=clip((value or "").strip(), 200), reason=r))
            return True
        return False

    if check(brief.business_type):
        update["business_type"] = NEUTRAL_BUSINESS.get(brief.lang, "firma")
    if brief.city and check(brief.city):
        update["city"] = None
    for field in ("audience", "goal"):
        if check(getattr(brief, field)):
            update[field] = ""
    if brief.budget_hint and check(brief.budget_hint):
        update["budget_hint"] = None
    comps = []
    changed = False
    for c in brief.competitors or []:
        name = str((c or {}).get("name") or "") if isinstance(c, dict) else str(c)
        if check(name):
            changed = True
            continue
        comps.append(c)
    if changed:
        update["competitors"] = comps
    if not update:
        return brief, refused
    return brief.model_copy(update=update, deep=True), refused
