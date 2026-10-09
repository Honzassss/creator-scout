"""The two demo briefs as ready CriteriaSets (implemented; shared by chat fallback, API, fixtures, tests).

"bakery": pekárna v Brně. "fitness": fitness studio v Brně. Same discovery pool, different criteria,
so different finalists (architecture.md section 8). Fixtures are tuned against these params.

Followers 1,000-50,000 and engagement >= 0.8 % in both presets: the first real Brno run (9 Oct 2026)
showed local food creators at 0.5k-5k followers and 0.5-1.5 % engagement, so the earlier 5k / 1.5 %
floor removed nearly everyone. The owner can change both in the chat or the criteria panel.
"""

from __future__ import annotations

from typing import Literal

from app.models import Brief, CriteriaSet, DiscoveryQuery, Lang, Refused, i18n, make_criterion

PresetName = Literal["bakery", "fitness"]

# Same discovery pool for both goals ("Změnit cíl" keeps the candidate list).
DEMO_DISCOVERY = DiscoveryQuery(
    keywords=["cukrárna brno", "pekárna brno", "brno food", "fitness brno", "brno tipy"],
    hashtags=["brnofood", "brnojidlo", "foodbrno", "brnofitness", "brno"],
    places=["Brno"],
    city="Brno",
    platforms=["instagram", "tiktok"],
    limit=60,
)


_BRIEFS: dict[str, dict[str, dict]] = {
    "bakery": {
        "cs": {"business_type": "pekárna", "audience": "rodiny a mladí lidé v Brně",
               "goal": "víc lidí v prodejně, představit nový kváskový chléb", "budget_hint": "do 20 tisíc Kč"},
        "en": {"business_type": "bakery", "audience": "families and young people in Brno",
               "goal": "more people in the shop and a launch for our new sourdough bread", "budget_hint": "up to CZK 20,000"},
    },
    "fitness": {
        "cs": {"business_type": "fitness studio", "audience": "lidé v Brně, kteří chtějí začít cvičit",
               "goal": "víc přihlášek na zkušební lekci", "budget_hint": "do 30 tisíc Kč"},
        "en": {"business_type": "fitness studio", "audience": "people in Brno who want to start exercising",
               "goal": "more sign-ups for a trial class", "budget_hint": "up to CZK 30,000"},
    },
}
_COMPETITORS: dict[str, list[dict]] = {
    "bakery": [{"name": "Pekárna B", "handles": ["pekarna_b"]}, {"name": "Chlebárna Vlnka", "handles": ["chlebarna_vlnka"]}],
    "fitness": [{"name": "FitZone Brno", "handles": ["fitzone_brno"]}, {"name": "ProteoMax", "handles": ["proteomax"]}],
}


def preset_brief(name: PresetName, lang: Lang = "cs") -> Brief:
    """The preset's Brief in ``lang`` (same city and competitors in both languages). Fresh object."""
    if name not in _BRIEFS:
        raise KeyError(name)
    texts = _BRIEFS[name]["en" if lang == "en" else "cs"]
    return Brief(city="Brno", competitors=[{"name": c["name"], "handles": list(c["handles"])} for c in _COMPETITORS[name]],
                 lang="en" if lang == "en" else "cs", **texts)


def _bakery(lang: Lang = "cs") -> CriteriaSet:
    brief = preset_brief("bakery", lang)
    c = [
        make_criterion("public_account", why=i18n(
            "Obsah soukromého účtu nevidíme, takže ho nejde prověřit.",
            "We cannot see a private account's content, so it cannot be checked.")),
        make_criterion("followers_range", {"min": 1000, "max": 50000}, why=i18n(
            "Menší tvůrci mívají bližší vztah s publikem a jsou dostupnější.",
            "Smaller creators tend to have a closer audience and are more affordable.")),
        make_criterion("active_recently", {"days": 30}, why=i18n(
            "Tvůrce, který měsíc nic nezveřejnil, kampaň nejspíš neodvede.",
            "A creator with no post for a month is unlikely to deliver a campaign.")),
        make_criterion("not_brand_account", why=i18n(
            "Hledáme tvůrce, ne jiné firmy.", "We are looking for creators, not other businesses.")),
        make_criterion("language_cs", {"min_share": 0.5}, why=i18n(
            "Zákazníci pekárny v Brně čtou česky.", "The bakery's customers in Brno read Czech.")),
        make_criterion("topic_share", {"topics": ["food", "recipes", "restaurants_cafes", "local_tips"], "min_share": 0.4}, why=i18n(
            "Doporučení pekárny zapadne k tvůrci, který o jídle mluví pravidelně.",
            "A bakery recommendation fits a creator who talks about food regularly.")),
        make_criterion("formats", {"formats": ["reel", "video"], "min_share": 0.2}, why=i18n(
            "Krátká videa ukážou pečivo a prodejnu nejlépe.", "Short videos show the pastry and the shop best.")),
        make_criterion("post_frequency", {"min_per_week": 1.0}, why=i18n(
            "Pravidelné posty drží publikum aktivní.", "Regular posting keeps the audience engaged.")),
        make_criterion("max_commercial_share", {"max_share": 0.3}, why=i18n(
            "Když je reklama skoro každý post, lidé jí přestanou věřit.",
            "When almost every post is an ad, people stop trusting it.")),
        make_criterion("min_engagement", {"min_rate": 0.008}, why=i18n(
            "Sledující, kteří reagují, spíš přijdou i do prodejny.",
            "Followers who react are more likely to visit the shop.")),
        make_criterion("cs_comment_share", {"min_share": 0.5}, why=i18n(
            "Lidé, kteří reagují, píšou česky; je to jazyk komentářů, ne demografie publika.",
            "People who react write in Czech; this is the language of the comments, not a demographic estimate.")),
        make_criterion("local_signal", {"city": "Brno", "min_count": 1}, why=i18n(
            "Pekárna potřebuje lidi z Brna, ne z celé republiky.",
            "The bakery needs people from Brno, not the whole country.")),
        make_criterion("max_generic_comments", {"max_share": 0.5}, why=i18n(
            "Hodně komentářů jen z emoji může znamenat nakoupenou aktivitu.",
            "Many emoji-only comments can indicate bought engagement.")),
        make_criterion("no_competitor_collab", why=i18n(
            "Tvůrce, který právě dělá reklamu Pekárně B nebo Chlebárně Vlnka, by pro vás nebyl věrohodný.",
            "A creator currently promoting Pekárna B or Chlebárna Vlnka would not be credible for you.")),
        make_criterion("discloses_ads", {"max_undisclosed": 0}, why=i18n(
            "Neoznačená reklama je problém i pro zadavatele.",
            "Undisclosed advertising is a problem for the advertiser too.")),
    ]
    return CriteriaSet(brief=brief, criteria=c, refused=[], discovery=DEMO_DISCOVERY.model_copy(deep=True))


def _fitness(lang: Lang = "cs") -> CriteriaSet:
    brief = preset_brief("fitness", lang)
    c = [
        make_criterion("public_account", why=i18n(
            "Obsah soukromého účtu nevidíme, takže ho nejde prověřit.",
            "We cannot see a private account's content, so it cannot be checked.")),
        make_criterion("followers_range", {"min": 1000, "max": 50000}, why=i18n(
            "Pro studio stačí menší až střední tvůrce s aktivním publikem.",
            "Small to mid-size creators with an active audience suit a studio.")),
        make_criterion("active_recently", {"days": 30}, why=i18n(
            "Tvůrce, který měsíc nic nezveřejnil, kampaň nejspíš neodvede.",
            "A creator with no post for a month is unlikely to deliver a campaign.")),
        make_criterion("not_brand_account", why=i18n(
            "Hledáme tvůrce, ne jiné firmy.", "We are looking for creators, not other businesses.")),
        make_criterion("language_cs", {"min_share": 0.5}, why=i18n(
            "Zákazníci studia v Brně čtou česky.", "The studio's customers in Brno read Czech.")),
        make_criterion("topic_share", {"topics": ["fitness", "sport", "lifestyle"], "min_share": 0.4}, why=i18n(
            "Pozvánka do studia zapadne k tvůrci, který o pohybu tvoří pravidelně.",
            "A studio invitation fits a creator who regularly makes content about exercise.")),
        make_criterion("formats", {"formats": ["reel", "video"], "min_share": 0.3}, why=i18n(
            "Cvičení se nejlépe ukazuje ve videu.", "Exercise is best shown on video.")),
        make_criterion("post_frequency", {"min_per_week": 1.5}, why=i18n(
            "Fitness publikum čeká pravidelný obsah.", "Fitness audiences expect regular content.")),
        make_criterion("max_commercial_share", {"max_share": 0.3}, why=i18n(
            "Když je reklama skoro každý post, lidé jí přestanou věřit.",
            "When almost every post is an ad, people stop trusting it.")),
        make_criterion("min_engagement", {"min_rate": 0.008}, why=i18n(
            "Zkušební lekce potřebuje lidi, kteří opravdu reagují.",
            "A trial class needs followers who actually respond.")),
        make_criterion("cs_comment_share", {"min_share": 0.5}, why=i18n(
            "Lidé, kteří reagují, píšou česky; je to jazyk komentářů, ne demografie publika.",
            "People who react write in Czech; this is the language of the comments, not a demographic estimate.")),
        make_criterion("local_signal", {"city": "Brno", "min_count": 1}, why=i18n(
            "Studio potřebuje lidi z Brna.", "The studio needs people from Brno.")),
        make_criterion("max_generic_comments", {"max_share": 0.5}, why=i18n(
            "Hodně komentářů jen z emoji může znamenat nakoupenou aktivitu.",
            "Many emoji-only comments can indicate bought engagement.")),
        make_criterion("no_competitor_collab", why=i18n(
            "Tvůrce, který dělá reklamu FitZone Brno nebo doplňkům ProteoMax, by pro vás nebyl věrohodný.",
            "A creator promoting FitZone Brno or ProteoMax supplements would not be credible for you.")),
        make_criterion("discloses_ads", {"max_undisclosed": 0}, why=i18n(
            "Neoznačená reklama je problém i pro zadavatele.",
            "Undisclosed advertising is a problem for the advertiser too.")),
    ]
    return CriteriaSet(brief=brief, criteria=c, refused=[], discovery=DEMO_DISCOVERY.model_copy(deep=True))


# A typical request the chatbot must refuse (demo moment); not part of either preset by default.
EXAMPLE_REFUSED = Refused(
    text="jen tvůrci, kteří nejsou politicky aktivní",
    reason=i18n(
        "Politické názory jsou zvláštní kategorie údajů (čl. 9 GDPR); podle nich lidi netřídíme.",
        "Political opinions are special-category data (GDPR Art. 9); we do not sort people by them."),
)


def get_preset(name: PresetName, lang: Lang = "cs") -> CriteriaSet:
    """Fresh (deep) copy each call; safe to mutate. ``lang="cs"`` is byte-identical to the original
    Czech preset; ``"en"`` only swaps the brief texts (criteria labels/why are already i18n)."""
    if name == "bakery":
        return _bakery(lang)
    if name == "fitness":
        return _fitness(lang)
    raise KeyError(name)


def _same_business(brief: Brief, name: PresetName) -> bool:
    from app.llm.text import fold

    bt = fold(brief.business_type or "").strip()
    return bt in {fold(preset_brief(name, lg).business_type).strip() for lg in ("cs", "en")}


def _same_competitors(brief: Brief, name: PresetName) -> bool:
    def key(cs: list[dict]) -> set[str]:
        return {str(c.get("name") or "").strip().lower() for c in cs or []}

    return key(brief.competitors) == key(_COMPETITORS[name])


def overlay_why(cs: CriteriaSet, name: PresetName, brief: Brief) -> CriteriaSet:
    """A custom brief mapped to a preset ("coffee roastery" -> bakery, "yoga studio" -> fitness) keeps
    the preset's criteria parameters, but the why texts must not name the preset's business or its
    competitors: they are rewritten for ``brief`` (in place; returns ``cs``)."""
    same_bt, same_comp = _same_business(brief, name), _same_competitors(brief, name)
    if same_bt and same_comp:
        return cs
    bt = (brief.business_type or "").strip()
    city = (brief.city or "").strip()
    names = [str(c.get("name") or "").strip() for c in brief.competitors or [] if str(c.get("name") or "").strip()]
    generic = {
        "followers_range": i18n("Menší až střední tvůrci mívají bližší vztah s publikem a jsou dostupnější.",
                                "Small to mid-size creators tend to have a closer audience and are more affordable."),
        "language_cs": i18n(f"Vaši zákazníci{(' (' + city + ')') if city else ''} čtou česky.",
                            f"Your customers{(' in ' + city) if city else ''} read Czech."),
        "topic_share": i18n(f"Doporučení pro váš podnik ({bt}) zapadne k tvůrci, který o těchto tématech tvoří pravidelně.",
                            f"A recommendation for your {bt} fits a creator who posts about these topics regularly."),
        "formats": i18n("Krátká videa ukážou, co nabízíte, nejlépe.", f"Short videos show your {bt} best."),
        "post_frequency": i18n("Pravidelné posty drží publikum aktivní.", "Regular posting keeps the audience engaged."),
        "min_engagement": i18n("Sledující, kteří reagují, spíš přijdou i k vám.",
                               "Followers who react are more likely to become your customers."),
        "local_signal": i18n(f"Potřebujete lidi z okolí{(' (' + city + ')') if city else ''}, ne z celé republiky.",
                             f"Your {bt} needs people from {city or 'your city'}, not the whole country."),
    }
    for c in cs.criteria:
        if not same_bt and c.kind in generic and not (c.kind == "local_signal" and not c.enabled):
            c.why = generic[c.kind]
        if c.kind == "no_competitor_collab" and not same_comp:
            if names:
                lst_cs = ", ".join(names[:-1]) + (" nebo " if len(names) > 1 else "") + names[-1]
                lst_en = ", ".join(names[:-1]) + (" or " if len(names) > 1 else "") + names[-1]
                c.why = i18n(f"Tvůrce, který právě dělá reklamu {lst_cs}, by pro vás nebyl věrohodný.",
                             f"A creator currently promoting {lst_en} would not be credible for you.")
            else:
                c.why = i18n("Tvůrce, který právě dělá reklamu vaší konkurenci, by pro vás nebyl věrohodný.",
                             "A creator currently promoting one of your competitors would not be credible for you.")
    return cs
