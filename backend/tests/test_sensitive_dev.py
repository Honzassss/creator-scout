"""Keyword sensitive filter: our DEV list (tuning set).

These phrasings were written for tuning ``sensitive.keyword_flags`` on 9 Oct 2026, after the first real
Brno run dropped 4 of 12 posts of a food creator ("boží" = slang for great, "volba" = choice,
"premiéra" = premiere). They are a separate list from S1 in docs/validation-plan.md, but several of
them reword S1's earlier misses (S05, S14, H05, H14, H15), so S1 now counts as TUNED, not held out.
The honest held-out number comes from a fresh 20 + 20 list written by the reviewer and measured once
(keyword path): 12 of 20 sensitive dropped, 3 of 20 harmless dropped. Do not tune on that list either.

Every sensitive phrasing must be dropped and every harmless one kept (keyword path, no LLM).
"""

from __future__ import annotations

import pytest

from app.llm.sensitive import keyword_flags

# (lang, category, text): personal sensitive content (GDPR Art. 9 / Art. 10) -> must be dropped.
DEV_SENSITIVE: list[tuple[str, str, str]] = [
    ("cs", "health", "Po třech týdnech na kapačkách mě konečně pustili domů, ozařování mám za sebou."),
    ("cs", "health", "Doktorka mi minulý týden potvrdila nádor, takže teď chvíli nebudu péct."),
    ("cs", "health", "Jsem po operaci menisku, cvičení teď jen na židli."),
    ("cs", "health", "Čekáme miminko! V březnu nás bude o jednoho víc."),
    ("cs", "health", "Mám alergii na ořechy, tak tyhle sušenky nemůžu ani ochutnat."),
    ("cs", "health", "Měla jsem tři roky bulimii, dneska o tom chci mluvit otevřeně."),
    ("cs", "health", "Insulin si píchám čtyřikrát denně a stejně si dám kousek dortu."),
    ("cs", "health", "Zlomila jsem si kotník a teď jsem měsíc na berlích."),
    ("en", "health", "Two rounds of chemo done, my hair is gone but the appetite is back."),
    ("en", "health", "I was diagnosed with endometriosis last spring and food is part of how I cope."),
    ("en", "health", "After my miscarriage I stopped posting for a while."),
    ("en", "health", "Living with an eating disorder means some days the kitchen is hard."),
    ("cs", "politics", "Kandiduju do zastupitelstva za naši čtvrť, přijďte mě podpořit."),
    ("cs", "politics", "Letošní komunální volby rozhodnou o tramvaji na Bystrc, nezapomeňte."),
    ("cs", "politics", "Jdu volit a vy byste měli taky, každý hlas se počítá."),
    ("cs", "politics", "Pan premiér Fiala dnes navštívil náš trh a koupil si chleba."),
    ("cs", "politics", "Stávka učitelů: dneska máme zavřeno, stojíme za nimi."),
    ("cs", "politics", "Lidovci mají ten nejlepší program pro rodiny, já jim dám hlas."),
    ("en", "politics", "Free Palestine. I will not stay silent on my page."),
    ("en", "politics", "Running for city council this fall, coffee is on me at every meetup."),
    ("en", "politics", "MAGA hats are not welcome in my kitchen, sorry not sorry."),
    ("cs", "religion", "V neděli jsme šli do kostela a pak na oběd k babičce."),
    ("cs", "religion", "Dcera měla první svaté přijímání, upekla jsem jí dort ve tvaru kalichu."),
    ("cs", "religion", "Půst je pro mě duchovní věc, jím teď jen jednou denně."),
    ("en", "religion", "Eid Mubarak to everyone breaking the fast with us tonight!"),
    ("en", "religion", "Sunday mass first, then pancakes, that is our family tradition."),
    ("cs", "ethnicity", "Jako Vietnamka jsem vyrostla mezi dvěma kulturami a vařím obě."),
    ("en", "ethnicity", "As a black woman in the Czech food scene I get comments you would not believe."),
    ("cs", "ethnicity", "Původem jsem z Ukrajiny a tohle je recept mojí babičky."),
    ("cs", "sexuality", "S mojí ženou jsme se vzaly loni v létě a tohle byl náš svatební dort."),
    ("en", "sexuality", "Pride month: here is the rainbow cake I bake every June for my partner and me."),
    ("en", "sexuality", "My pronouns are they/them, please respect that in the comments."),
    ("cs", "criminal", "Nadýchal jsem 0,8 promile a řidičák mi sebrali na rok."),
    ("cs", "criminal", "Dostal jsem podmínku a teď začínám znova, tentokrát poctivě."),
    ("en", "criminal", "Got a speeding ticket on the way to the bakery, worth it."),
    ("en", "criminal", "I spent two years on probation and baking kept me sane."),
    ("cs", "politics", "V říjnu volte číslo 7, ať se v Brně konečně něco hne."),
    ("cs", "politics", "Jak volit v komunálkách, aby hlas nepropadl? Krátký návod v reelu."),
    ("cs", "health", "Dva týdny jsem byla hospitalizovaná, teď zase pomalu do kuchyně."),
    ("cs", "health", "Psychické potíže mě letos dost zbrzdily, proto ta pauza."),
    ("en", "health", "Living with PTSD and baking is the one thing that calms me down."),
    ("cs", "criminal", "Kamarád je od pátku ve vazbě, tak tenhle koláč peču pro jeho mámu."),
    ("en", "politics", "Nazis marched through our street yesterday and nobody stopped them."),
    ("en", "health", "Two nights in hospital, now home and resting."),
]

# Ordinary captions with near-miss words -> must be kept.
DEV_HARMLESS: list[tuple[str, str]] = [
    ("cs", "Ten pistáciový croissant je fakt boží, běžte tam dřív, než ho vyprodají."),
    ("cs", "Boží snídaně v nové kavárně na Veveří, vajíčka benedikt úplně top."),
    ("cs", "Kváskový chleba byl jasná volba, k tomu máslo a sůl."),
    ("cs", "Na výběr máte dvě volby: s mákem, nebo s tvarohem."),
    ("cs", "Dnes je premiéra nového menu, přijďte ochutnat podzimní polévky."),
    ("cs", "Na premiéru filmu jsme si upekli popcorn s karamelem."),
    ("cs", "Volím vždycky ten nejtmavší kakaový dort."),
    ("cs", "Vhodné i pro alergiky, bez lepku a bez laktózy."),
    ("cs", "Bezlepkové pečivo pro celiaky máme každý čtvrtek."),
    ("cs", "Pirátský dort pro malého Kubu, s truhlou plnou čokoládových mincí."),
    ("cs", "Bez trans tuků a bez palmového oleje, jen máslo."),
    ("cs", "Tenhle cheesecake mi úplně ukradl srdce."),
    ("cs", "Původ kávy: Etiopie, Yirgacheffe, lehce květinová."),
    ("cs", "Káva původem z Kolumbie, pražená tady v Brně."),
    ("cs", "Snídaně u kostela svatého Jakuba, nejlepší místo v centru."),
    ("cs", "Pokutový kop v poslední minutě a pak oslava s párkem v rohlíku."),
    ("cs", "Výpis z obchodního rejstříku jsme nechali na zdi jako vtip."),
    ("cs", "Hlasujte pro nás v anketě o nejlepší pekárnu Brna!"),
    ("cs", "Domácí zápas Bulldogs a pak burgery u stadionu."),
    ("cs", "Jaká je to rasa? Ptáte se na našeho psa v kavárně, je to bígl."),
    ("en", "We take pride in our sourdough, three days of fermentation."),
    ("en", "That trick shot was sick, dinner is on me."),
    ("en", "Oh my god, this cardamom bun is unreal."),
    ("en", "Retail therapy, but make it pastries."),
    ("en", "Premier League night: wings, fries and a pint."),
    ("en", "Our new menu premieres on Friday, come early."),
    ("en", "This brownie stole the show at the party."),
    ("en", "The vote is in: you picked the pumpkin latte as the autumn drink."),
    ("cs", "Válka o poslední kousek pizzy u nás doma vypukla v sobotu."),
    ("cs", "Vánoční cukroví podle babičky, vanilkové rohlíčky a linecké."),
    ("en", "True crime podcast and a cinnamon roll, perfect Sunday."),
    ("cs", "Přijímání objednávek na svatební dorty jsme otevřeli do konce roku."),
    ("cs", "Podmínky soutěže najdete v bio, vyhrát můžete dort."),
    ("en", "Halal and kosher options are marked on the menu."),
    ("cs", "Jedeme nadoraz, dvacet kilometrů na kole a pak buchty."),
    ("cs", "Tahle vazba knihy receptů je krásná, plátno a zlatá ražba."),
    ("en", "Bilingual menu now: Czech and English, thanks for the feedback."),
    # false drops found in the real Brno cache by the review of f8c6e3d ("naživo", "hospitality", "buddha bowl")
    ("cs", "Hrajeme naživo v pátek večer, k tomu domácí koláče."),
    ("en", "Hospitality is our thing: good coffee and a kind word."),
    ("cs", "Buddha bowl s tofu a arašídovou omáčkou, rychlý oběd."),
    ("en", "Our new buddha-bowl menu starts on Monday."),
]


@pytest.mark.parametrize("lang,cat,text", DEV_SENSITIVE)
def test_dev_sensitive_dropped(lang: str, cat: str, text: str) -> None:
    assert keyword_flags([text]) == [True], f"{cat} not caught: {text}"


@pytest.mark.parametrize("lang,text", DEV_HARMLESS)
def test_dev_harmless_kept(lang: str, text: str) -> None:
    assert keyword_flags([text]) == [False], f"false drop: {text}"


def test_dev_list_size() -> None:
    assert len(DEV_SENSITIVE) + len(DEV_HARMLESS) >= 40
    assert len({t for *_, t in DEV_SENSITIVE} | {t for _, t in DEV_HARMLESS}) == len(DEV_SENSITIVE) + len(DEV_HARMLESS)
