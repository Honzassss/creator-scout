#!/usr/bin/env python3
"""Deterministic generator for the MOCK dataset (fictional creators in Brno).

Run from the repo root with the backend venv (models are validated through app.models):

    backend/.venv/bin/python fixtures/generate.py            # write fixtures/*.json + README.md
    backend/.venv/bin/python fixtures/generate.py --check    # regenerate in memory, diff against disk
    backend/.venv/bin/python fixtures/generate.py --out DIR --no-verify

Everything here is fictional: people, handles, brands, outlets, websites (*.example). Every
SourceRef has mode "mock". The generator also runs a small *reference funnel* (same rules as
docs/architecture.md section 5, own simple metric code, lingua for language) and refuses to write
the files when the designed outcome (``Spec.bakery`` / ``Spec.fitness``) does not match. The
README and expected.json are rendered from that verified result, so they are the test oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "backend"))

from app import models as M  # noqa: E402
from app.llm.topics import counted_topics  # noqa: E402
from app.presets import get_preset  # noqa: E402

SEED = "creator-scout-mock-v1"
# All fixture timestamps are written relative to this instant. MockProvider shifts them by
# (now - ANCHOR) at load time, so "last post 1 day ago" stays true on any day.
ANCHOR = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
COMMENT_POSTS = 7        # comments exist for the newest N posts of every public creator
MAX_COMMENTS = 15        # fetched comments per post (Free plan returns ~15)
R3_POSTS = 5             # rounds/r3_audience.COMMENT_POSTS (reference funnel uses the newest 5)
EXTRA_POSTS = 16         # older posts (round 4) per finalist

# ---------------------------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------------------------


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-z]+", fold(s)) if t]


HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_.]+)")
URL_RE = re.compile(r"(https?://\S+|\b\S+\.example\S*)")

# ---------------------------------------------------------------------------------------------
# Cities, places, tags
# ---------------------------------------------------------------------------------------------

CITIES: dict[str, dict[str, Any]] = {
    "Brno": {
        "loc": "v Brně",
        "en": "Brno",
        "near": ["Zelného trhu", "Moravského náměstí", "Lužánek", "Špilberku", "Kraví hory",
                 "Náměstí Svobody", "Brněnské přehrady", "Mendlova náměstí"],
        "locations": ["Brno - Zelný trh", "Brno - Moravské náměstí", "Brno - Lužánky",
                      "Brno - Náměstí Svobody", "Brno - Špilberk", "Brno - Brněnská přehrada",
                      "Brno, Czech Republic"],
    },
    "Praha": {
        "loc": "v Praze",
        "en": "Prague",
        "near": ["Vinohrad", "Karlína", "Letné", "Smíchova", "Holešovic"],
        "locations": ["Praha - Vinohrady", "Praha - Karlín", "Praha - Letná", "Praha - Smíchov"],
        "tags": ["praha", "prahajidlo", "foodpraha"],
    },
    "_none": {
        "loc": "ve městě",
        "en": "town",
        "near": ["nádraží", "hlavního náměstí", "městského parku"],
        "locations": [],
    },
    "Ostrava": {
        "loc": "v Ostravě",
        "en": "Ostrava",
        "near": ["Poruby", "Stodolní", "Komenského sadů", "Dolních Vítkovic"],
        "locations": ["Ostrava - Poruba", "Ostrava - Dolní Vítkovice", "Ostrava - Komenského sady"],
        "tags": ["ostrava", "ostravafitness", "silovytrenink"],
    },
}

BRNO_TAGS = {
    "food": ["brnofood", "brnojidlo", "foodbrno"],
    "recipes": ["brnojidlo"],
    "restaurants_cafes": ["brnokavarny", "brnofood"],
    "local_tips": ["brnotipy", "brno"],
    "fitness": ["brnofitness"],
    "sport": ["brnosport", "brno"],
}

TOPIC_TAGS: dict[str, list[str]] = {
    "food": ["jidlo", "foodblog", "dobrejidlo", "pecivo", "foodie", "mnam"],
    "recipes": ["recept", "recepty", "peceni", "domacipeceni", "kvasek", "pecemedoma"],
    "restaurants_cafes": ["kavarna", "kafe", "bistro", "snidane", "brunch", "coffeetime"],
    "local_tips": ["tipy", "kamvyrazit", "tipnavikend", "mistnitipy"],
    "fitness": ["fitness", "trenink", "cviceni", "posilovna", "workout"],
    "sport": ["beh", "behani", "sport", "running", "zavod"],
    "lifestyle": ["lifestyle", "rutina", "motivace", "pomalyzivot"],
    "family": ["rodina", "deti", "maminka", "rodinnyvylet", "materstvi"],
    "fashion": ["moda", "outfit", "ootd", "styl", "secondhand"],
    "beauty": ["beauty", "makeup", "liceni", "kosmetika", "skincare"],
    "travel": ["cestovani", "travel", "vylet", "hory", "cestovatel"],
    "gaming": ["gaming", "hry", "stream", "gamer", "twitch"],
    "music": ["hudba", "beatbox", "muzika", "cover", "koncert"],
    "humor": ["humor", "vtipy", "skec", "smich", "parodie"],
}
TOPIC_TAGS_EN = {
    "food": ["foodie", "foodblog", "brunch", "pastry"],
    "fitness": ["fitness", "workout", "gym", "training"],
}

# ---------------------------------------------------------------------------------------------
# Caption templates (cs unless noted). Slots: {a} feminine past-tense suffix, {near} genitive place,
# {city_loc} "v Brně", {city_en}, {pastry_nom}/{pastry_acc}, {bake}, {trip}, {mountains}.
# Deliberately free of words a sensitive keyword list would flag (see README "Sensitive").
# ---------------------------------------------------------------------------------------------

PASTRIES = [
    ("kváskový chléb", "kváskový chléb"), ("tvarohový koláč", "tvarohový koláč"),
    ("makový závin", "makový závin"), ("skořicový šnek", "skořicového šneka"),
    ("máslový croissant", "máslový croissant"), ("povidlová buchta", "povidlovou buchtu"),
    ("ořechový věneček", "ořechový věneček"), ("valašský frgál", "valašský frgál"),
    ("bramborový chléb", "bramborový chléb"),
]
BAKES = ["kváskový chléb", "skořicové šneky", "tvarohové koláče", "bábovku", "perník", "focacciu",
         "domácí rohlíky", "mřížkový koláč", "žitný chléb", "makové buchty"]
TRIPS = ["Lisabonu", "Neapoli", "Splitu"]
MOUNTAINS = ["Krkonoších", "Alpách", "Dolomitech"]

TEMPLATES: dict[str, dict[str, list[str]]] = {"cs": {}, "en": {}}
TEMPLATES["cs"]["food"] = [
    "Dneska jsem ochutnal{a} {pastry_acc} z malé pekárny kousek od {near}. Křupavá kůrka, uvnitř vláčné těsto, za mě rozhodně jednička.",
    "Sobotní snídaně {city_loc}: {pastry_nom}, pořádné kafe a čerstvé ovoce. Lepší start víkendu si neumím představit.",
    "Kde najdete nejlepší {pastry_acc} {city_loc}? Zkusil{a} jsem pět míst a tady je moje pořadí, poslední místo vás překvapí.",
    "Dnešní objev: {pastry_nom}. Těsto voní máslem a náplně je tak akorát, žádné šizení.",
    "Rychlý oběd mezi schůzkami: polévka dne, krajíc chleba se sýrem a malý dezert. Přesně tohle člověk potřebuje.",
    "Ochutnávka sezónních dobrot na trhu u {near}. Dýňová polévka, pečené kaštany a teplý mošt, podzim jak má být.",
    "Zkoušel{a} jsem nový podnik s domácími dobrotami. Porce jsou velké, ceny férové a obsluha příjemná.",
    "Dneska čistě sladká nálada: {pastry_nom}, horká čokoláda a dobrá kniha. Víkend si užívám po svém.",
    "Přinesl{a} jsem domů tašku čerstvého pečiva. Cestou z pekárny polovina záhadně zmizela, nebudu zapírat.",
    "Večeře s přáteli v novém bistru. Grilovaná zelenina, kuře s bylinkami a na závěr tvarohový dort.",
    "Ranní kolečko po pekárnách {city_loc} je u mě tradice. Dneska vyhrála pekárna u {near} s neskutečně křupavými rohlíky.",
]
TEMPLATES["cs"]["recipes"] = [
    "Recept na {bake} pro úplné začátečníky. Těsto necháte přes noc kynout v lednici a ráno jen pečete.",
    "Dnes jsem podle babičky upekl{a} {bake}. Na těsto stačí mouka, máslo, vejce, cukr a špetka soli. Pečeme na 180 stupňů zhruba půl hodiny.",
    "Můj kvásek má dneska narozeniny, takže jsem upekl{a} {bake}. Kůrka praská a celý byt krásně voní.",
    "Neděle je u nás pečicí den. Tentokrát jsem upekl{a} {bake} s ořechy a skořicí.",
    "Nejčastější chyba při pečení chleba? Málo trpělivosti. Dejte těstu čas a výsledek bude úplně jiný.",
    "Dnešní recept je na {bake} s povidly. Těsto vyválejte na tenko, naplňte a pečte dozlatova.",
    "Zkusil{a} jsem upéct {bake} bez kynutí a překvapivě to vyšlo. Uložte si recept, budete ho chtít.",
    "Pečení s kváskem krok za krokem: krmení, první kynutí, tvarování a pečení v litinovém hrnci. Ptejte se v komentářích.",
    "Rychlé pečení na večer: {bake} z jednoho těsta za čtyřicet minut. Návštěva může přijít.",
]
TEMPLATES["cs"]["restaurants_cafes"] = [
    "Nová kavárna u {near} mě mile překvapila. Výborné espresso, domácí dorty a klidné místo na práci.",
    "Moje oblíbené místo na snídani {city_loc}. Vajíčka na másle, kváskový toast a flat white, nic víc nepotřebuju.",
    "Recenze bistra, o kterém se teď hodně mluví: porce dobré, čekání dlouhé, dezerty vynikající.",
    "Kavárenský tip na deštivý den: velká okna, gauč u knihovny a perníkové latte. Zůstal{a} jsem tři hodiny.",
    "Tady pečou vlastní croissanty každé ráno. Přijďte před devátou, potom už bývá vyprodáno.",
    "Zkoušel{a} jsem tři nové podniky v centru a tohle bistro vyhrálo. Polévka, domácí chleba a příjemná obsluha.",
    "Kafe a mrkvový dort v malé kavárně u {near}. Lepší mrkvový dort jsem snad ještě nejedl{a}.",
    "Brunch, na který se vyplatí počkat: lívance s ovocem, vejce benedikt a čerstvě vymačkaný džus.",
]
TEMPLATES["cs"]["local_tips"] = [
    "Pět míst {city_loc}, kam vzít návštěvu na víkend. Uložte si to, ať to pak nehledáte.",
    "Tip na podzimní procházku: od {near} až k vyhlídce, cestou dvě kavárny a pekárna.",
    "Víte, kde {city_loc} seženete čerstvé pečivo i v neděli ráno? Sepsal{a} jsem vám malý seznam.",
    "Farmářské trhy u {near} jsou zpátky. Každou sobotu tam najdete sýry, pečivo, med a čerstvou zeleninu ze zahrádek.",
    "Kam na brunch {city_loc}? Moje tři nejoblíbenější podniky podle ceny, porcí a atmosféry.",
    "Místní tip: nejkrásnější podzimní výhled {city_loc} je kousek od {near}. Vezměte si termosku a dobrou svačinu.",
]
TEMPLATES["cs"]["fitness"] = [
    "Dnešní trénink nohou: dřepy, výpady a mrtvý tah. Čtyři série po deseti opakováních, odpočinek minutu a půl.",
    "Ranní kruhový trénink za dvacet minut: kliky, dřepy, plank a skoky přes švihadlo. Zvládne to každý.",
    "Jak začít s posilováním, když jste nikdy necvičili? Tři cviky, které můžete dělat i doma.",
    "Shyby jsem dlouho nezvládal{a} ani jeden. Dneska jich dám deset v kuse. Trpělivost se vyplácí.",
    "Trénink zad v posilovně: přítahy, veslování s jednoručkou a stahování kladky. Technika je důležitější než váha.",
    "Protahování po tréninku nevynechávejte. Deset minut denně a záda vám poděkují.",
    "Středeční trénink s kettlebellem byl náročný, ale parta byla skvělá. Kdo se přidá příště?",
    "Tréninkový plán na tento týden: tři silové tréninky, dva běhy a jeden den úplného volna.",
    "Cviky na střed těla za deset minut: sklapovačky, nůžky, plank a ruský twist. Zapněte si video a cvičte se mnou.",
    "Ranní jóga v parku u {near}: dvacet minut protahování, dýchání a klidu, než se celé město probudí. Přidáte se zítra ráno?",
    "Mobilita kyčlí pro všechny, kdo celý den sedí. Pět cviků, které zvládnete i v kanceláři.",
    "Trénink s vlastní vahou na hřišti u {near}: kliky na bradlech, shyby a výskoky. Hodina venku je nejlepší.",
]
TEMPLATES["cs"]["sport"] = [
    "Ranní běh kolem {near}: osm kilometrů, mlha a skoro nikdo na cestě.",
    "Víkendový závod na deset kilometrů za mnou. Osobní rekord o minutu a půl, mám obrovskou radost.",
    "Na kole jsem dneska najel{a} šedesát kilometrů. Kopce dávají zabrat, ale výhledy stojí za to.",
    "Intervalový běh na dráze: osm úseků po čtyřech stech metrech. Nohy hoří, hlava je čistá.",
    "Lezecká stěna, tři hodiny a úplně vyčerpaná předloktí. Příště zkusím těžší cestu.",
    "Plavání ráno před prací je můj nový zvyk. Kilometr za třicet minut a pak hned do kanceláře.",
    "Dlouhý nedělní běh: osmnáct kilometrů v klidném tempu. Příprava na jarní půlmaraton začíná.",
]
TEMPLATES["cs"]["lifestyle"] = [
    "Pomalé ráno, káva, deník a seznam věcí, které tento týden opravdu stihnu. Jak plánujete vy?",
    "Úklid šatníku a pracovního stolu. Méně věcí znamená víc klidu v hlavě.",
    "Můj večerní rituál: telefon pryč, čaj, kniha a do postele před jedenáctou.",
    "Týden v číslech: čtyři tréninky, dvě knihy, jeden výlet a spousta dobrého spánku.",
    "Ráno bez telefonu už třetí týden. Překvapivě mi to dává víc času i lepší náladu.",
]
TEMPLATES["cs"]["family"] = [
    "Víkend s dětmi na chalupě. Bláto, šišky a večer táborák s kytarou.",
    "Malá dneska poprvé sama jela na kole. Máma pláče dojetím a táta točí video.",
    "Rodinná neděle: procházka lesem, návštěva u babičky a odpoledne deskovky.",
    "Jak zvládáme ranní chaos se dvěma dětmi? Večer připravené oblečení a taška u dveří.",
    "Kluci postavili v obýváku bunkr z gauče a dek. Úklid zítra, dnes se tam spí.",
    "První den ve školce zvládnutý. Malý byl statečný, já o něco méně.",
    "Rodinný výlet do zoo. Žirafy, tučňáci a dva unavení kluci na zpáteční cestě.",
    "Večerní čtení před spaním je u nás povinné. Dneska třikrát dokola stejná kniha.",
]
TEMPLATES["cs"]["fashion"] = [
    "Podzimní outfit: oversize sako, pruhované triko a bílé tenisky. Všechno z druhé ruky.",
    "Kapsulový šatník na podzim: deset kousků, třicet kombinací. Ukážu vám jak.",
    "Nové boty, starý kabát a šála od babičky. Styl nemusí stát majlant.",
    "Tři způsoby, jak nosit džínovou bundu. Který vám sedí nejvíc?",
    "Nákup v sekáči se vydařil: vlněný svetr, kostkovaná sukně a kožený pásek.",
    "Barvy podzimu v šatníku: hořčicová, vínová a tmavě zelená. Co nosíte vy?",
]
TEMPLATES["cs"]["beauty"] = [
    "Moje ranní rutina pro pleť ve čtyřech krocích. Méně je někdy víc.",
    "Test nových rtěnek: vydrží kafe, oběd i pusu na rozloučenou?",
    "Podzimní líčení za pět minut. Teplé tóny, trochu třpytu a hotovo.",
    "Moje oblíbená kosmetika do kabelky. Nic z toho nestojí víc než tři stovky.",
    "Jak si udělat vlny bez kulmy? Návod krok za krokem.",
    "Nehty v barvě lesních plodů. Vydržely celý týden bez jediného odštípnutí.",
]
TEMPLATES["cs"]["travel"] = [
    "Tři dny v {trip}. Úzké uličky, výhledy z kopce a večery u moře.",
    "Balím batoh na víkend v horách. Co nikdy nesmí chybět? Čelovka a náhradní ponožky.",
    "Vlakem přes celou Evropu za týden. Sepsal{a} jsem trasu, ceny i tipy na nocleh.",
    "Ranní výhled z chaty v {mountains}. Kvůli tomuhle se vyplatí vstávat v pět.",
    "Nejlevnější letenky letos? Moje tipy, jak je hledat a kdy kupovat.",
    "Přechod hřebene za dva dny: třicet kilometrů, dva západy slunce a jedna bouřka.",
]
TEMPLATES["cs"]["gaming"] = [
    "Dneska večer stream: projdeme nový update a zkusíme rekord v hodnocené hře. Začínáme v osm.",
    "Moje herní sestava po upgradu: nová grafika, tichá klávesnice a lepší mikrofon.",
    "Tahle nezávislá hra mě úplně pohltila. Krásný pixel art a příběh, který vás chytne.",
    "Nejtěžší boss, jakého jsem kdy hrál{a}. Čtyřicet pokusů a konečně padl.",
    "Turnaj s komunitou tuto sobotu. Přihlášky přes Discord, výherce dostane herní myš.",
    "Retro večer: staré konzole, hry z dětství a kamarádi na gauči.",
]
TEMPLATES["cs"]["music"] = [
    "Nový beat z dnešního večera. Smyčky nahrané v obýváku, basa z telefonu.",
    "Zkouška s kapelou před sobotním koncertem. Přijdete?",
    "Beatbox výzva: zvládnete zopakovat tenhle rytmus?",
    "Cover písničky, kterou mi poslali sledující. Další přání pište do komentářů.",
    "Moje první vlastní skladba po dvou letech. Dejte vědět, jak se vám líbí.",
]
TEMPLATES["cs"]["humor"] = [
    "Když ti mamka řekne, ať si uklidíš pokoj, a ty najdeš věci z roku 2015.",
    "Typy lidí v tramvaji, část třetí. Kterého poznáváte?",
    "Moje snaha vstát v šest versus realita v osm patnáct.",
    "Když kamarád řekne, že to bude jen na jedno kafe.",
    "Pondělní porada pohledem stážisty. Poznáváte se?",
    "Když se v obchodě otevře nová pokladna a všichni začnou sprintovat.",
]
# Brand accounts (company voice).
TEMPLATES["cs"]["brand_bakery"] = [
    "Dnes jsme pro vás upekli {pastry_acc}. Na prodejně od sedmi ráno, dokud zásoby stačí.",
    "Nový sezónní chléb s dýňovými semínky je tady. Ochutnejte ho na prodejně nebo si ho objednejte předem.",
    "Hledáme posilu do týmu: pekaře na ranní směny. Více informací najdete na webu.",
    "Víkendová nabídka: ke každému chlebu croissant za polovic.",
    "Ranní pohled do pekárny: těsto odpočívá, trouby se nahřívají a za hodinu jsou první rohlíky venku.",
]
TEMPLATES["cs"]["brand_cafe"] = [
    "Dnes u nás dýňové latte a švestkový koláč. Těšíme se na vás.",
    "Nové menu snídaní platí od pondělí. Vajíčka, kváskový chléb a domácí marmeláda.",
    "Otevřeno denně od osmi, o víkendu od devíti. Přijďte si sednout k oknu.",
]
TEMPLATES["cs"]["brand_gym"] = [
    "Nový rozvrh na říjen je venku. Rezervace v aplikaci.",
    "Otevřeno denně od šesti do desíti. První vstup zdarma.",
    "Nové stroje v posilovně jsou tady. Přijďte je vyzkoušet.",
    "Ranní kruhový trénink každé úterý a čtvrtek od sedmi.",
]
TEMPLATES["cs"]["brand_supplement"] = [
    "Nová příchuť proteinu: slaný karamel. Ochutnejte jako první.",
    "Doprava zdarma nad 999 Kč platí celý říjen.",
    "Proteinová tyčinka s lískovými oříšky je zpět skladem.",
    "Tip na svačinu po tréninku: jogurt, ovoce a odměrka proteinu.",
]
TEMPLATES["en"]["food"] = [
    "Best cinnamon rolls I have found so far in {city_en}. Flaky, buttery and not too sweet.",
    "Sunday brunch spot of the week: great eggs, strong coffee and friendly staff.",
    "Trying traditional Czech pastries one bakery at a time. Today it was a poppy seed strudel.",
    "Rainy day, warm soup and fresh bread. Simple things are the best.",
    "Ranking five breakfast places in {city_en} so you do not have to.",
    "Found a tiny bakery that sells out by ten in the morning. Worth the early alarm.",
    "Street food market this weekend: dumplings, grilled cheese and the best lemonade in town.",
]
TEMPLATES["en"]["fitness"] = [
    "Leg day done: squats, lunges and deadlifts. Four sets of ten with ninety seconds of rest.",
    "Twenty minute circuit you can do anywhere: push ups, squats, planks and jumping jacks.",
    "How to start lifting if you have never trained before. Three exercises to master first.",
    "Pull up progress: from zero to ten in six months. Consistency wins.",
    "Back day at the gym. Rows, pulldowns and face pulls. Form over ego.",
    "Morning run along the river before work. Cold, quiet and exactly what I needed.",
]
BRAND_TOPIC = {"brand_bakery": "food", "brand_cafe": "restaurants_cafes", "brand_gym": "fitness",
               "brand_supplement": "fitness"}

# ---------------------------------------------------------------------------------------------
# Comment pools
# ---------------------------------------------------------------------------------------------

CS_FOOD = [
    "To vypadá úžasně, příště tam jdu taky!",
    "Díky za tip, v sobotu to vyzkouším s přítelem.",
    "Tohle místo znám, mají tam výborné koláče.",
    "Můžeš prosím napsat, kolik to stálo?",
    "Ten chleba vypadá dokonale, jak dlouho kyne těsto?",
    "Konečně někdo, kdo píše poctivé recenze.",
    "Tam jsem byla minulý týden a souhlasím, je to tam skvělé.",
    "Přidáš prosím recept? Rád bych to zkusil doma.",
    "Jdu tam zítra ráno, doufám, že ještě něco zbude.",
    "Tvoje tipy mě vždycky dostanou, děkuju!",
    "Kde přesně to je? Nemůžu to najít na mapě.",
    "Tohle jsem pekla podle tebe a celá rodina byla nadšená.",
    "Ti skořicoví šneci vypadají neskutečně, musím to zkusit.",
    "Byl jsem tam včera a fronta byla až ven, ale stálo to za to.",
]
CS_FITNESS = [
    "Díky za ten plán, zkusím ho od pondělí.",
    "Ten kruhový trénink jsem dal dneska ráno, pořádně jsem se zpotil.",
    "Můžeš ukázat správnou techniku dřepu ještě jednou?",
    "Kolik sérií děláš u shybů, když začínáš?",
    "Přidám se příště, kde přesně cvičíte?",
    "Tvoje videa mě konečně dostala do posilovny.",
    "Skvělé vysvětlení, konečně chápu, jak držet záda rovně.",
    "Běháš i v zimě? Já se vždycky vymluvím na počasí.",
    "Tohle protahování dělám každý večer, díky moc.",
    "Jak dlouho ti trvalo dostat se na deset shybů?",
    "Ráno jsem to zkusila a bylo to těžší, než to vypadá.",
    "Přesně tohle jsem potřeboval slyšet, jdu cvičit.",
]
CS_GENERAL = [
    "Krásně natočené, těším se na další díl.",
    "Tohle je přesně důvod, proč tě sleduju.",
    "Moc pěkné, díky, že to sdílíš.",
    "Úplně souhlasím, nemám co dodat.",
    "Další díl prosím, tohle mě strašně baví.",
    "Tvoje videa mi vždycky zlepší náladu.",
    "Kde se to natáčelo? Vypadá to tam nádherně.",
    "Tohle si ukládám a pošlu kamarádce.",
    "Přesně tohle jsem dneska potřebovala vidět.",
    "Děkuju za inspiraci, hned to zkouším.",
    "Čím dál lepší obsah, jen tak dál!",
]
SK = [
    "Vyzerá to fantasticky, určite to vyskúšam.",
    "Ďakujem za tip, cez víkend sa tam zastavím.",
    "Toto je moje obľúbené miesto, veľmi dobré koláče.",
    "Môžeš prosím napísať recept? Veľmi by ma to zaujímalo.",
    "Bola som tam minulý týždeň a bolo to výborné.",
    "Super video, teším sa na ďalšie.",
    "Kde presne to je? Nemôžem to nájsť.",
    "Toto si musím uložiť, vyzerá to úžasne.",
    "Cvičím podľa teba už mesiac a cítim sa oveľa lepšie.",
    "Koľko sérií robíš pri drepoch?",
    "Takéto videá ma vždy motivujú ísť cvičiť.",
    "Ďakujem, konečne som pochopila techniku.",
    "Ja by som tam išiel hneď zajtra ráno.",
    "Veľmi pekne spracované, len tak ďalej.",
]
EN = [
    "This looks amazing, adding it to my list!",
    "Thanks for the tip, I will check it out this weekend.",
    "Where exactly is this place? Cannot find it on the map.",
    "Great video, keep them coming.",
    "I tried this workout yesterday and it was tough.",
    "Love your content, always so helpful.",
    "How long did it take you to get there?",
    "Need the recipe for this please!",
    "This is my favourite spot in town too.",
    "Wow, those pastries look incredible.",
    "Saving this for my next trip.",
    "Such a good explanation, thank you.",
]
EMOJI_ONLY = ["😍😍😍", "🔥🔥", "❤️", "👏👏", "😋", "🙌🔥", "💪💪", "🥰", "👍", "😍🔥", "❤️❤️❤️", "🤤🤤",
              "💯", "👌", "😮😍"]
GENERIC = ["Super", "Paráda", "Krása", "Nádhera", "Top", "Wow", "Pěkné", "Krásné", "Mňam", "Nice",
           "Super 👍", "Krása 😍", "Top 🔥", "Paráda ❤️"]
GENERIC_CS = ["Pěkné", "Krásné", "Paráda ❤️", "Super 👍", "Krása 😍", "Top 🔥", "Pěkné 👏"]
COMMENT_MIX: dict[str, dict[str, float]] = {
    "cs": {"cs": 0.70, "sk": 0.06, "en": 0.06, "emoji": 0.12, "generic": 0.06},
    "sk": {"cs": 0.18, "sk": 0.60, "en": 0.04, "emoji": 0.12, "generic": 0.06},
    "en": {"cs": 0.18, "sk": 0.04, "en": 0.60, "emoji": 0.12, "generic": 0.06},
    "bought": {"cs": 0.25, "emoji": 0.60, "generic": 0.15},
}

# ---------------------------------------------------------------------------------------------
# Sensitive content (must be dropped by llm/sensitive.py) and the superset keyword check
# ---------------------------------------------------------------------------------------------

SENSITIVE_STEMS = {
    "health": ["nemoc", "operac", "lekar", "doktor", "diagnoz", "rakovin", "cukrovk", "diabet",
               "celiaki", "depres", "terapi", "lecb", "lecen", "leky", "pacient", "tehoten", "tehotn",
               "potrat", "psychiatr", "psycholog", "uzkost", "covid", "alergi", "postizen", "zdravotn",
               "zdravi", "hospital", "surgery", "doctor", "diagnos", "cancer", "therapy", "health",
               "disease", "illness"],
    "politics": ["volb", "volit", "volim", "volte", "volic", "zvolen", "politi", "parlament",
                 "prezident", "vlad", "ministr", "poslan", "senat", "komunis", "fasis", "demonstrac",
                 "referend", "strana", "strany", "stranu", "stranou", "election", "vote", "voting",
                 "government", "politic"],
    "religion": ["kostel", "mse", "cirkev", "cirkv", "buh", "boha", "bohu", "bozi", "modlit", "vira",
                 "viry", "veri", "nabozen", "katoli", "evangel", "muslim", "islam", "zid", "krest",
                 "bible", "biblick", "farar", "knez", "ramadan", "velikonoc", "vanoc", "svaty", "svata",
                 "svate", "church", "god", "pray", "religio", "faith", "christian", "jewish"],
    "ethnicity": ["romsk", "romove", "etnick", "etnik", "rasa", "rasis", "rasov", "cikan", "imigrant",
                  "migrant", "narodnost", "puvod", "ethnic", "racis", "immigrant"],
    "sexuality": ["gay", "lesb", "lgbt", "queer", "homosex", "bisex", "transgend", "sexual", "sex",
                  "pride"],
    "criminal": ["polici", "kradez", "krade", "kradl", "ukradl", "soud", "obvin", "trestn", "trest",
                 "vezen", "zatcen", "zatkl", "podvod", "vysetr", "kriminal", "zlocin", "drog",
                 "pachatel", "obzalob", "police", "arrest", "crime", "criminal", "court", "jail",
                 "prison", "drug", "fraud", "steal", "stole"],
}


def sensitive_hits(text: str) -> list[str]:
    hits = []
    for tok in tokens(text):
        for cat, stems in SENSITIVE_STEMS.items():
            for st in stems:
                if tok.startswith(st):
                    hits.append(f"{cat}:{tok}")
    return hits


# ---------------------------------------------------------------------------------------------
# Candidate specs (the design)
# ---------------------------------------------------------------------------------------------

AD_HASHTAGS = {"reklama", "spoluprace", "spolupráce", "placenaspoluprace", "ad", "ads", "sponsored",
               "sponzorovano", "partnerstvi", "partnership", "advertisement", "affiliate", "collab"}
AD_PHRASES = ["reklama", "spoluprace", "spolupraci", "placena spoluprace", "sponsored", "#ad"]
DISCOUNT_RE = re.compile(r"(?:k[oó]d(?:em)?|code)\s*:?\s*([A-Z0-9]{4,})", re.IGNORECASE)

COMPANY_CATEGORIES = ["Bakery", "Café", "Gym/Physical Fitness Center", "Brand", "Restaurant"]
CREATOR_CATEGORIES = ["Digital creator", "Blogger", "Personal blog", "Video creator", "Athlete"]

BRANDS = {  # every brand handle used in captions / collab records -> display name
    "pekarna_a": "Pekárna A", "pekarna_b": "Pekárna B", "chlebarna_vlnka": "Chlebárna Vlnka",
    "mlynek_eshop": "Mlýnek e-shop", "prazirna_hrudka": "Pražírna Hrudka", "proteomax": "ProteoMax",
    "fitzone_brno": "FitZone Brno", "vrcholek_sport": "Vrcholek Sport", "fitbar_cz": "FitBar",
    "hodinky_tempo": "Hodinky Tempo", "snack_planeta": "Snack Planeta", "burger_box_cz": "Burger Box",
    "sladke_krabicky": "Sladké krabičky",
}


@dataclass
class Spec:
    key: str
    platform: str
    handle: str
    name: str
    bio: str
    followers: int
    role: str                                  # README one-liner
    bakery: str                                # "F" or "R<n>:<criterion_id>" (designed outcome)
    fitness: str
    gender: str = "f"                          # f / m / x (brand)
    n: int = 18                                # latest_posts incl. specials
    topics: dict[str, int] = field(default_factory=dict)   # non-special posts
    lang: dict[str, float] = field(default_factory=lambda: {"cs": 1.0})
    media: dict[str, float] = field(default_factory=lambda: {"reel": 0.45, "carousel": 0.25, "photo": 0.30})
    er: float = 0.04
    cadence: float = 2.5
    last: float = 1.0                          # age (days) of the newest post at ANCHOR
    city: str | None = "Brno"                  # where the creator is (None = no city signal)
    comments: str = "cs"                       # COMMENT_MIX profile
    found_via: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    is_business: bool | None = False
    category: str | None = None
    private: bool = False
    verified: bool = False
    under18: bool = False
    external_urls: list[str] = field(default_factory=list)
    special: list[dict] = field(default_factory=list)       # {"idx", "caption", "topic", ...}
    extra_special: list[dict] = field(default_factory=list) # {"age", ...} in older posts
    ads: int = 0                                # extra posts with #spoluprace + paid label
    ad_brands: list[str] = field(default_factory=list)
    spikes: list[int] = field(default_factory=list)
    extra: int = 0                              # older posts for round 4
    sensitive_comment: dict | None = None       # {"idx": post idx, "text": ...}
    template_group: str | None = None           # brand_* template set
    following: int | None = None

    @property
    def cid(self) -> str:
        return M.candidate_id(self.platform, self.handle)


IG, TT = "instagram", "tiktok"
FOODMIX = {"reel": 0.45, "carousel": 0.25, "photo": 0.30}
FITMIX = {"reel": 0.55, "carousel": 0.20, "photo": 0.25}
VIDEO = {"video": 1.0}

SPECS: list[Spec] = [
    # ---------------------------------------------------------------- finalists ----------
    Spec("B1", IG, "kuba.jidlo.brno", "Jakub Horák", gender="m",
         bio="Jím se Brnem 🥐☕ | exkluzivní ambasador @pekarna_a | tipy na snídaně a pekárny | kontakt v DM",
         followers=23400, role="bakery finalist: claims exclusivity for @pekarna_a, 2 posts with competitor @pekarna_b in the last 30 days (one unlabeled)",
         bakery="F", fitness="R2:topic_share", n=20,
         topics={"food": 9, "restaurants_cafes": 5, "local_tips": 2, "recipes": 2}, er=0.042, cadence=2.6, last=1.2,
         is_business=True, category="Digital creator", extra=EXTRA_POSTS,
         found_via=["search:brno food", "hashtag:brnofood", "place:Brno - Zelný trh"],
         related=["gurmanka_lenka", "brnenska_snidane"],
         special=[
             {"idx": 3, "topic": "food", "paid": True, "coauthors": ["pekarna_b"], "media": "reel",
              "caption": "Ranní směna v @pekarna_b: ukázali mi, jak se tvaruje kváskový chléb a proč těsto potřebuje celou noc. Díky za pozvání! #spoluprace #brnofood"},
             {"idx": 8, "topic": "food", "paid": False, "coauthors": ["pekarna_b"], "media": "reel",
              "caption": "Nejlepší croissant v Brně? Dneska znovu u @pekarna_b a pořád mě to baví. Zastavte se ráno, dokud jsou teplé. #brnofood #pecivo"},
         ],
         extra_special=[
             {"age": 78, "topic": "food", "paid": True, "mentions": ["pekarna_a"], "media": "photo",
              "caption": "Jsem hrdý ambasador @pekarna_a 🥐 Jejich kváskový chléb mám doma každý týden. #spoluprace #reklama"},
         ],
         sensitive_comment={"idx": 0, "text": "Mám celiakii, dá se tam koupit něco bez lepku? Lékař mi lepek úplně zakázal."}),
    Spec("B2", IG, "verca_pece", "Veronika Šťastná",
         bio="Peču doma v Brně 🍞 kvásek, koláče, buchty | nové recepty každý týden",
         followers=14800, role="bakery finalist: 'poctivá recenze, nikdo mi neplatí' + discount code VERCA15 + affiliate link, no ad label",
         bakery="F", fitness="R2:topic_share", n=18,
         topics={"recipes": 11, "food": 5, "local_tips": 1}, er=0.051, cadence=2.3, last=0.8,
         media={"reel": 0.40, "carousel": 0.35, "photo": 0.25}, extra=EXTRA_POSTS,
         external_urls=["https://verca-pece.example", "https://mlynek-eshop.example/?aff=VERCA15"],
         found_via=["search:pekárna brno", "hashtag:brnojidlo"],
         special=[
             {"idx": 4, "topic": "recipes", "paid": False, "media": "reel",
              "caption": "Poctivá recenze, nikdo mi neplatí 🙂 Mouka od @mlynek_eshop je zatím nejlepší, kterou jsem na kvásek zkoušela, chleba se krásně zvedá a kůrka křupe. Se slevovým kódem VERCA15 máte 15 % na první nákup: mlynek-eshop.example/?aff=VERCA15 #recept #kvasek"},
         ],
         extra_special=[
             {"age": 61, "topic": "recipes", "paid": False, "media": "carousel",
              "caption": "Žitný chléb z mouky od @mlynek_eshop, recenze po měsíci pečení. Kód VERCA15 pořád platí. #recept #peceni"},
         ]),
    Spec("B3", IG, "brnenska_snidane", "Barbora Kolářová",
         bio="Snídaně a kavárny v Brně ☕🥐 | nové podniky každý týden | TikTok @brnenska_snidane",
         followers=18900, role="bakery finalist, clean: one labeled coffee collab; cross-platform TikTok + a fan account",
         bakery="F", fitness="R2:topic_share", n=21,
         topics={"restaurants_cafes": 9, "food": 6, "local_tips": 4}, er=0.047, cadence=2.4, last=0.6,
         media={"reel": 0.40, "carousel": 0.35, "photo": 0.25}, is_business=True, category="Blogger",
         extra=EXTRA_POSTS,
         external_urls=["https://brnenska-snidane.example", "https://tiktok.mock.invalid/@brnenska_snidane"],
         found_via=["hashtag:brnofood", "place:Brno - Moravské náměstí", "search:brno tipy"],
         related=["srdicka_a_dorty", "praha_na_talire", "kuba.jidlo.brno"],
         special=[
             {"idx": 2, "topic": "lifestyle", "sensitive": "health", "media": "photo",
              "caption": "Omlouvám se za ticho, poslední dva týdny jsem strávila v nemocnici po operaci slepého střeva. Už je to lepší a brzy jsem zpátky v kavárnách."},
             {"idx": 6, "topic": "restaurants_cafes", "paid": True, "mentions": ["prazirna_hrudka"], "media": "carousel",
              "caption": "Ochutnávka nových káv od @prazirna_hrudka. Etiopie voní borůvkami, Brazílie čokoládou. Díky za pozvání! #spoluprace #brnokavarny"},
         ]),
    Spec("B5", TT, "toman_ochutnava", "Ondřej Toman", gender="m",
         bio="Ochutnávám Brno 🍔🥐 | každý den jedno místo | IG @toman_ochutnava",
         followers=27300, role="bakery finalist (TikTok), clean; news: one matched item + one namesake allegation",
         bakery="F", fitness="R2:topic_share", n=18,
         topics={"food": 11, "restaurants_cafes": 4, "local_tips": 3}, media=VIDEO, er=0.065, cadence=2.1, last=0.9,
         is_business=None, extra=EXTRA_POSTS,
         external_urls=["https://instagram.mock.invalid/toman_ochutnava/"],
         found_via=["search:brno food"]),
    Spec("S1", IG, "fit_peci_s_klarou", "Klára Veselá",
         bio="Peču a cvičím v Brně 🍞💪 | domácí pečení i trénink pro každého | TikTok @fit_peci_s_klarou",
         followers=19600, role="SHARED finalist: baking + workouts; labeled ProteoMax collab = competitor only for the fitness goal",
         bakery="F", fitness="F", n=23,
         topics={"recipes": 10, "food": 1, "fitness": 9, "sport": 1}, media=FITMIX, er=0.046, cadence=2.2, last=1.0,
         is_business=True, category="Digital creator", extra=EXTRA_POSTS,
         external_urls=["https://fitpeceni.example", "https://tiktok.mock.invalid/@fit_peci_s_klarou"],
         found_via=["hashtag:brnojidlo", "hashtag:brnofitness"], related=["proteomax", "trener_marek_brno"],
         special=[
             {"idx": 3, "topic": "lifestyle", "sensitive": "politics", "media": "photo",
              "caption": "Než půjdete v sobotu k volbám, přečtěte si programy politických stran. Já už vím, koho budu volit."},
             {"idx": 5, "topic": "fitness", "paid": True, "coauthors": ["proteomax"], "media": "reel",
              "caption": "Po tréninku si dávám shake od @proteomax. Vanilková příchuť mi chutná nejvíc. S kódem KLARA10 máte 10 % slevu. #spoluprace #reklama #fitness"},
         ],
         extra_special=[
             {"age": 104, "topic": "fitness", "paid": True, "mentions": ["proteomax"], "media": "reel",
              "caption": "Ranní trénink a pak snídaně s @proteomax. Díky za podporu! #spoluprace #fitness"},
         ]),
    Spec("F2", IG, "trener_marek_brno", "Marek Šimek", gender="m",
         bio="Osobní trenér v Brně 💪 | silový trénink a technika | online plány na webu",
         followers=28500, role="fitness finalist: trains at competitor @fitzone_brno (unlabeled post + Meta branded record + news)",
         bakery="R2:topic_share", fitness="F", n=20,
         topics={"fitness": 13, "sport": 4, "lifestyle": 2}, media={"reel": 0.60, "carousel": 0.15, "photo": 0.25},
         er=0.038, cadence=2.4, last=0.7, is_business=True, category="Digital creator", extra=EXTRA_POSTS,
         external_urls=["https://marek-trener.example"],
         found_via=["search:fitness brno", "hashtag:brnofitness"], related=["fit_mama_eliska", "silova_ostrava"],
         special=[
             {"idx": 5, "topic": "fitness", "paid": False, "mentions": ["fitzone_brno"], "media": "reel",
              "caption": "Dneska ráno jsem vedl trénink ve @fitzone_brno. Přijďte si zacvičit, ve středu jsem tam zase od sedmi! #brnofitness #trenink"},
         ],
         extra_special=[
             {"age": 68, "topic": "fitness", "paid": True, "mentions": ["fitzone_brno"], "media": "reel",
              "caption": "Nový tréninkový program ve @fitzone_brno startuje v pondělí. Přihlášky na recepci. #spoluprace #brnofitness"},
         ]),
    Spec("F3", TT, "pavla_hybe_brnem", "Pavla Krejčí",
         bio="Komunita 120 tisíc sledujících 💪 | cvičení pro každého | Brno | IG @pavla_hybe_brnem",
         followers=31200, role="fitness finalist (TikTok): bio claims '120 tisíc' (31.2k + 9.8k IG); 2 unlabeled discount-code posts for @vrcholek_sport",
         bakery="R2:topic_share", fitness="F", n=18,
         topics={"fitness": 10, "sport": 3, "lifestyle": 3}, media=VIDEO, er=0.055, cadence=2.0, last=0.5,
         is_business=None, extra=EXTRA_POSTS,
         external_urls=["https://instagram.mock.invalid/pavla_hybe_brnem/"],
         found_via=["search:fitness brno"],
         special=[
             {"idx": 2, "topic": "fitness", "paid": False, "mentions": ["vrcholek_sport"],
              "caption": "Nové legíny od @vrcholek_sport vydržely i dnešní dřepy 😅 S kódem PAVLA20 máte 20 % slevu. #fitness #brnofitness"},
             {"idx": 9, "topic": "sport", "paid": False, "mentions": ["vrcholek_sport"],
              "caption": "Běžecká bunda, která přežila i říjnový déšť. Odkaz na @vrcholek_sport je v biu, kód PAVLA20 platí do neděle. #behani"},
         ]),
    Spec("F4", TT, "jogina_lucie", "Lucie Benešová",
         bio="Jóga a běh v Brně 🧘‍♀️🏃‍♀️ | ranní jóga v Lužánkách",
         followers=4200, role="fitness finalist (TikTok), small and clean; wrong topic for the bakery goal",
         bakery="R2:topic_share", fitness="F", n=16,
         topics={"fitness": 7, "sport": 6, "lifestyle": 3}, media=VIDEO, er=0.082, cadence=2.6, last=1.1,
         is_business=None, extra=EXTRA_POSTS, found_via=["search:fitness brno"],
         sensitive_comment={"idx": 0, "text": "Tohle by měla podporovat vláda místo toho, co dělá teď. V příštích volbách volte jinak!"}),
    Spec("F5", IG, "kalisthenika_brno_tom", "Tomáš Říha", gender="m",
         bio="Kalistenika v Brně 💪 | parky, hrazdy a vlastní váha | YouTube: Tomáš Říha – kalisthenika",
         followers=44000, role="fitness finalist, clean (labeled apparel collab); wrong topic for the bakery goal; YouTube channel; namesake in sports news",
         bakery="R2:topic_share", fitness="F", n=22,
         topics={"fitness": 15, "sport": 4, "lifestyle": 1}, media={"reel": 0.60, "carousel": 0.20, "photo": 0.20},
         er=0.031, cadence=2.3, last=0.9, is_business=True, category="Digital creator", extra=EXTRA_POSTS,
         external_urls=["https://kalisthenika-brno.example"],
         found_via=["hashtag:brnofitness", "place:Brno - Lužánky"],
         special=[
             {"idx": 5, "topic": "lifestyle", "sensitive": "religion", "media": "photo",
              "caption": "Neděle ráno: nejdřív mše v kostele, potom trénink v Lužánkách. Klidný začátek týdne."},
             {"idx": 7, "topic": "sport", "paid": True, "mentions": ["vrcholek_sport"], "media": "reel",
              "caption": "Nová kolekce triček od @vrcholek_sport v akci. Díky za podporu, tohle tričko přežilo i stovku shybů. #spoluprace #brnofitness"},
         ]),
    # ---------------------------------------------------------------- round 1 (both goals) ----
    Spec("P1", IG, "anicka_doma", "Anna Pokorná", bio="Vařím pro radost 🍲 Brno",
         followers=8900, role="private account", bakery="R1:public_account", fitness="R1:public_account",
         private=True, n=0, found_via=["hashtag:brnofood"]),
    Spec("P2", IG, "michal_v_kuchyni", "Michal Beneš", gender="m", bio="Kuchyně, víkendy, Brno",
         followers=12300, role="private account", bakery="R1:public_account", fitness="R1:public_account",
         private=True, n=0, found_via=["search:brno tipy"]),
    Spec("X1", IG, "jidelni_listek_cz", "Jídelní lístek CZ", gender="m",
         bio="Největší jídelní průvodce Brnem a okolím 🍽️ | denně nové podniky",
         followers=240000, role="> 200k followers", bakery="R1:followers_range", fitness="R1:followers_range",
         n=16, topics={"food": 10, "restaurants_cafes": 6}, er=0.012, cadence=1.5, last=0.4, verified=True,
         is_business=True, category="Digital creator", found_via=["hashtag:brnofood", "search:brno food"]),
    Spec("X2", IG, "fit_nela_official", "Nela Marková", bio="Fitness, motivace, Brno 💪 | online programy",
         followers=120000, role="120k followers (above both ranges)", bakery="R1:followers_range",
         fitness="R1:followers_range", n=18, topics={"fitness": 16, "lifestyle": 2}, media=FITMIX, er=0.021,
         cadence=1.8, last=0.6, verified=True, is_business=True, category="Digital creator",
         found_via=["hashtag:brnofitness"]),
    Spec("BR1", IG, "pekarna_b", "Pekárna B", gender="x",
         bio="Řemeslná pekárna v Brně 🥖 | Otevřeno Po–So 7–18 | objednávky na webu",
         followers=12400, role="brand account (bakery competitor A)", bakery="R1:not_brand_account",
         fitness="R1:not_brand_account", n=16, topics={"food": 16}, template_group="brand_bakery", er=0.02,
         cadence=1.4, last=0.3, is_business=True, category="Bakery",
         external_urls=["https://pekarna-b.example"], found_via=["search:pekárna brno", "place:Brno - Zelný trh"]),
    Spec("BR2", IG, "chlebarna_vlnka", "Chlebárna Vlnka", gender="x",
         bio="Kváskový chléb a koláče 🍞 | Brno-střed | rozvoz po Brně",
         followers=8700, role="brand account (bakery competitor B)", bakery="R1:not_brand_account",
         fitness="R1:not_brand_account", n=14, topics={"food": 14}, template_group="brand_bakery", er=0.02,
         cadence=2.0, last=0.8, is_business=True, category="Bakery",
         external_urls=["https://chlebarna-vlnka.example"], found_via=["search:pekárna brno"]),
    Spec("BR3", IG, "fitzone_brno", "FitZone Brno", gender="x",
         bio="Fitness centrum v Brně 💪 | skupinové tréninky, posilovna | rezervace v aplikaci",
         followers=9300, role="brand account (fitness competitor A)", bakery="R1:not_brand_account",
         fitness="R1:not_brand_account", n=14, topics={"fitness": 14}, template_group="brand_gym",
         media=FITMIX, er=0.018, cadence=1.6, last=0.5, is_business=True, category="Gym/Physical Fitness Center",
         external_urls=["https://fitzone-brno.example"], found_via=["search:fitness brno", "hashtag:brnofitness"]),
    Spec("BR4", IG, "proteomax", "ProteoMax", gender="x",
         bio="Proteiny a tyčinky 💪 | doprava zdarma nad 999 Kč | e-shop",
         followers=44000, role="brand account (fitness competitor B, supplements)", bakery="R1:not_brand_account",
         fitness="R1:not_brand_account", n=14, topics={"fitness": 14}, template_group="brand_supplement",
         media=FITMIX, er=0.012, cadence=1.5, last=0.4, is_business=True, category="Brand", city=None,
         external_urls=["https://proteomax.example"], found_via=["related:@fit_peci_s_klarou"]),
    Spec("BR5", IG, "kafe_lipova_alej", "Kafe Lipová alej", gender="x",
         bio="Kavárna a dorty ☕ | Brno, Lipová alej | otevřeno denně",
         followers=6100, role="brand account (café)", bakery="R1:not_brand_account",
         fitness="R1:not_brand_account", n=12, topics={"restaurants_cafes": 12}, template_group="brand_cafe",
         er=0.025, cadence=2.2, last=1.0, is_business=True, category="Café",
         found_via=["search:cukrárna brno", "place:Brno - Moravské náměstí"]),
    Spec("I1", IG, "honza_jedlik", "Jan Jedlička", gender="m", bio="Jídlo a pivnice, Brno 🍽️",
         followers=11000, role="inactive ~130 days", bakery="R1:active_recently", fitness="R1:active_recently",
         n=14, topics={"food": 10, "restaurants_cafes": 4}, er=0.035, cadence=3.0, last=131,
         found_via=["hashtag:brnojidlo"]),
    Spec("I2", IG, "sportovni_zuzka", "Zuzana Kopecká", bio="Sport a pohyb v Brně 🏃‍♀️",
         followers=7500, role="inactive 104 days", bakery="R1:active_recently", fitness="R1:active_recently",
         n=12, topics={"fitness": 8, "sport": 4}, media=FITMIX, er=0.045, cadence=2.8, last=104,
         found_via=["hashtag:brnofitness"]),
    Spec("I3", IG, "dobroty_od_babi", "Marie Dvořáková", bio="Babiččiny recepty z Brna 🥧",
         followers=16000, role="inactive 117 days", bakery="R1:active_recently", fitness="R1:active_recently",
         n=15, topics={"recipes": 15}, er=0.04, cadence=3.5, last=117, found_via=["search:cukrárna brno"]),
    Spec("E1", IG, "brno_eats_with_sam", "Sam Turner", gender="m",
         bio="British guy eating his way through Brno 🇬🇧🥐 | food in English",
         followers=13000, role="mostly English captions", bakery="R1:language_cs", fitness="R1:language_cs",
         n=16, topics={"food": 12, "restaurants_cafes": 4}, lang={"en": 0.8, "cs": 0.2}, er=0.04,
         cadence=2.2, last=1.3, found_via=["hashtag:foodbrno"]),
    Spec("E2", IG, "lift_with_dan_cz", "Dan Miller", gender="m",
         bio="Strength coach in Brno 🏋️ | training tips in English",
         followers=9000, role="mostly English captions", bakery="R1:language_cs", fitness="R1:language_cs",
         n=15, topics={"fitness": 15}, lang={"en": 0.85, "cs": 0.15}, media=FITMIX, er=0.045, cadence=2.3,
         last=0.9, found_via=["hashtag:brnofitness"]),
    # ---------------------------------------------------------------- goal-dependent round 1 ---
    Spec("G1", IG, "gurmanka_lenka", "Lenka Svobodová", bio="Gurmánka z Brna 🍰 | restaurace, kavárny, recepty",
         followers=65000, role="65k food creator: too big for both goals (maximum 50k)",
         bakery="R1:followers_range", fitness="R1:followers_range", n=18,
         topics={"food": 10, "restaurants_cafes": 8}, er=0.028, cadence=2.0, last=0.7,
         is_business=True, category="Digital creator",
         found_via=["hashtag:brnofood", "related:@kuba.jidlo.brno"]),
    Spec("G2", IG, "mala_kucharka_ema", "Ema Vlková", bio="Malá kuchařka z Brna 🧁 pečení pro radost",
         followers=800, role="800-follower recipes creator: too small for both goals (minimum 1,000)",
         bakery="R1:followers_range", fitness="R1:followers_range", n=14, topics={"recipes": 14}, er=0.06,
         cadence=2.4, last=1.6, found_via=["search:cukrárna brno"]),
    # ---------------------------------------------------------------- fitness-only misses -------
    Spec("FS1", IG, "suplement_sara", "Sára Vlčková", bio="Fitness a suplementy 💊💪 | Brno | kódy na slevy v highlights",
         followers=42000, role="fitness creator, 12 of 18 posts are paid partnerships",
         bakery="R2:topic_share", fitness="R2:max_commercial_share", n=18,
         topics={"fitness": 18}, media=FITMIX, er=0.025, cadence=1.8, last=0.5, ads=12,
         ad_brands=["proteomax", "fitbar_cz", "hodinky_tempo"], is_business=True, category="Digital creator",
         found_via=["hashtag:brnofitness"]),
    Spec("FS2", IG, "behame_s_petrem", "Petr Kučera", gender="m", bio="Běhám po Brně 🏃 | maratony a trailové běhy",
         followers=4300, role="runner posting ~1.2x per week (fitness needs 1.5)", bakery="R2:topic_share",
         fitness="R2:post_frequency", n=12, topics={"sport": 10, "fitness": 2},
         media={"reel": 0.42, "carousel": 0.25, "photo": 0.33}, er=0.05, cadence=6.0, last=2.0,
         found_via=["hashtag:brno"]),
    Spec("FS3", IG, "gym_bro_brno", "Filip Dostál", gender="m", bio="Posilovna, objem, Brno 🏋️‍♂️",
         followers=36000, role="fitness creator with 0.6% engagement (both goals need 0.8%)", bakery="R2:topic_share",
         fitness="R3:min_engagement", n=18, topics={"fitness": 18}, media={"reel": 0.50, "carousel": 0.20, "photo": 0.30},
         er=0.006, cadence=2.0, last=0.8, found_via=["hashtag:brnofitness"]),
    Spec("FS4", IG, "crossfit_jana", "Jana Habrová", bio="Crossfit a kettlebell v Brně 🔥",
         followers=4100, role="small fitness creator with 0.5% engagement", bakery="R2:topic_share",
         fitness="R3:min_engagement", n=16, topics={"fitness": 12, "sport": 4}, media=FITMIX, er=0.005,
         cadence=2.2, last=1.4, found_via=["search:fitness brno"]),
    Spec("FS5", TT, "fitko_s_matejem", "Matěj Polák", gender="m", bio="Fitko a motivace 💪 | Brno | spolupráce e-mailem",
         followers=41000, role="fitness TikToker whose comments are mostly Slovak", bakery="R2:topic_share",
         fitness="R3:cs_comment_share", n=16, topics={"fitness": 12, "sport": 4}, media=VIDEO, er=0.045,
         cadence=2.1, last=0.6, is_business=None, comments="sk", found_via=["search:fitness brno"]),
    Spec("FS6", IG, "fit_mama_eliska", "Eliška Zemanová", bio="Fit máma z Brna 💪 | cvičení doma i venku",
         followers=38000, role="fitness creator, ~75% emoji-only/generic comments + engagement spikes",
         bakery="R2:topic_share", fitness="R3:max_generic_comments", n=18,
         topics={"fitness": 13, "lifestyle": 5}, media={"reel": 0.50, "carousel": 0.20, "photo": 0.30},
         er=0.032, cadence=2.0, last=0.9, comments="bought", spikes=[2, 7],
         found_via=["hashtag:brnofitness", "related:@trener_marek_brno"]),
    Spec("FS7", IG, "silova_ostrava", "Radek Holub", gender="m", bio="Silový trénink | Ostrava 🏋️",
         followers=3600, role="fitness creator based in Ostrava, no Brno signal", bakery="R2:topic_share",
         fitness="R3:local_signal", n=16, topics={"fitness": 13, "sport": 3}, media=FITMIX, er=0.05,
         cadence=2.3, last=1.2, city="Ostrava", found_via=["related:@trener_marek_brno"]),
    Spec("M1", TT, "beatbox_vojta", "Vojtěch Jelínek", gender="m", bio="Beatbox a hudba 🎤 | Brno",
         followers=68000, role="music TikToker", bakery="R1:followers_range", fitness="R1:followers_range",
         n=14, topics={"music": 14}, media=VIDEO, er=0.07, cadence=2.5, last=1.0, is_business=None,
         found_via=["search:brno tipy"]),
    # ---------------------------------------------------------------- round 2 (both goals) -----
    Spec("T1", IG, "cestovatelka_iva", "Iva Marešová", bio="Cestuju z Brna do světa ✈️ | tipy na výlety",
         followers=21000, role="travel creator (2 of 18 posts about food)", bakery="R2:topic_share",
         fitness="R2:topic_share", n=18, topics={"travel": 16, "food": 2}, er=0.035, cadence=2.5, last=1.5,
         found_via=["hashtag:brno"]),
    Spec("T2", IG, "outfity_od_adely", "Adéla Krausová", bio="Móda z druhé ruky 👗 | Brno",
         followers=17000, role="fashion creator", bakery="R2:topic_share", fitness="R2:topic_share",
         n=16, topics={"fashion": 15, "lifestyle": 1}, er=0.04, cadence=2.4, last=0.9,
         found_via=["hashtag:brno", "place:Brno - Náměstí Svobody"]),
    Spec("T3", TT, "hraje_vitek", "Vít Sedláček", gender="m", bio="Hraju hry a streamuju 🎮 | Brno",
         followers=33000, role="gaming TikToker", bakery="R2:topic_share", fitness="R2:topic_share",
         n=15, topics={"gaming": 15}, media=VIDEO, er=0.06, cadence=2.2, last=0.7, is_business=None,
         found_via=["search:brno tipy"]),
    Spec("T4", IG, "rodinka_novakovi", "Petra Nováková", bio="Máma dvou kluků 👦👦 | rodinné výlety | Brno",
         followers=26000, role="family account, only 2 of 24 posts about food", bakery="R2:topic_share",
         fitness="R2:topic_share", n=24, topics={"family": 22, "food": 2},
         media={"reel": 0.40, "carousel": 0.25, "photo": 0.35}, er=0.03, cadence=2.0, last=1.1,
         found_via=["hashtag:brnojidlo"]),
    Spec("T5", IG, "degustace_dominik", "Dominik Kratochvíl", gender="m", bio="Ochutnávám a hodnotím 🍔 | Brno",
         followers=26000, role="food creator, 13 of 20 posts are paid partnerships", bakery="R2:max_commercial_share",
         fitness="R2:topic_share", n=20, topics={"food": 14, "restaurants_cafes": 6}, er=0.03, cadence=2.0,
         last=0.6, ads=13, ad_brands=["snack_planeta", "burger_box_cz", "sladke_krabicky"],
         found_via=["hashtag:brnofood", "search:brno food"]),
    Spec("T6", IG, "fotim_jidlo_brno", "Simona Pospíšilová", bio="Fotím jídlo v Brně 📷🍝",
         followers=11000, role="food creator, photos only (no reels/videos)", bakery="R2:formats",
         fitness="R2:topic_share", n=16, topics={"food": 10, "restaurants_cafes": 6},
         media={"photo": 0.70, "carousel": 0.30}, er=0.04, cadence=2.3, last=1.0, found_via=["hashtag:foodbrno"]),
    Spec("T7", IG, "obcas_upeku", "Jitka Šebestová", bio="Občas upeču něco dobrého 🥧 Brno",
         followers=8200, role="baker posting every ~9 days", bakery="R2:post_frequency",
         fitness="R2:topic_share", n=12, topics={"recipes": 10, "food": 2},
         media={"reel": 0.34, "carousel": 0.33, "photo": 0.33}, er=0.05, cadence=9.0, last=3.0,
         found_via=["search:cukrárna brno"]),
    Spec("T8", IG, "krasa_s_kristynou", "Kristýna Urbanová", bio="Líčení a kosmetika 💄 | Brno",
         followers=15000, role="beauty creator", bakery="R2:topic_share", fitness="R2:topic_share",
         n=16, topics={"beauty": 15, "lifestyle": 1}, er=0.04, cadence=2.2, last=0.8, found_via=["hashtag:brno"]),
    Spec("T9", TT, "vtipny_kamil", "Kamil Vávra", gender="m", bio="Skeče ze života 😂 | Brno",
         followers=22000, role="humor TikToker", bakery="R2:topic_share", fitness="R2:topic_share",
         n=15, topics={"humor": 15}, media=VIDEO, er=0.08, cadence=2.0, last=0.5, is_business=None,
         found_via=["search:brno tipy"]),
    # ---------------------------------------------------------------- round 3 (bakery) ---------
    Spec("A1", IG, "maly_gurman_brno", "Adam Bartoš", gender="m", bio="Malý gurmán, velké Brno 🍕",
         followers=19000, role="food creator with 0.5% engagement", bakery="R3:min_engagement",
         fitness="R2:topic_share", n=18, topics={"food": 12, "restaurants_cafes": 6}, er=0.005, cadence=2.2,
         last=0.9, found_via=["hashtag:brnofood"]),
    Spec("A2", IG, "kolacky_od_hanky", "Hana Jirešová", bio="Koláčky a buchty z Brna 🥮",
         followers=12000, role="baker with 0.6% engagement (bakery needs 0.8%)", bakery="R3:min_engagement",
         fitness="R2:topic_share", n=16, topics={"recipes": 12, "food": 4},
         media={"reel": 0.38, "carousel": 0.31, "photo": 0.31}, er=0.006, cadence=2.4, last=1.2,
         found_via=["search:cukrárna brno", "hashtag:brnojidlo"]),
    Spec("A3", IG, "zuzka_vari_v_brne", "Zuzana Hrubá", bio="Vařím v Brně 🍲 | recepty pro každý den",
         followers=16000, role="food creator whose comments are mostly Slovak", bakery="R3:cs_comment_share",
         fitness="R2:topic_share", n=18, topics={"recipes": 10, "food": 8}, er=0.044, cadence=2.3, last=0.7,
         comments="sk", found_via=["hashtag:brnojidlo"]),
    Spec("A4", IG, "srdicka_a_dorty", "Monika Šimková", bio="Dorty a sladkosti 🎂 | Brno | objednávky v DM",
         followers=24000, role="cake creator, ~75% emoji-only/generic comments + engagement spikes",
         bakery="R3:max_generic_comments", fitness="R2:topic_share", n=18,
         topics={"recipes": 12, "food": 6}, er=0.05, cadence=2.1, last=0.5, comments="bought", spikes=[1, 6],
         found_via=["search:cukrárna brno", "related:@brnenska_snidane"]),
    Spec("A5", IG, "praha_na_talire", "Tereza Bláhová", bio="Jídlo a kavárny v Praze 🍜☕",
         followers=20000, role="Prague food creator, no Brno signal", bakery="R3:local_signal",
         fitness="R2:topic_share", n=18, topics={"food": 10, "restaurants_cafes": 8}, er=0.043, cadence=2.2,
         last=0.8, city="Praha", found_via=["related:@brnenska_snidane"]),
    Spec("A6", TT, "mlsny_jirka", "Jiří Král", gender="m", bio="Mlsám po Brně 🍩 | food TikTok",
         followers=29000, role="food TikToker whose comments are mostly English", bakery="R3:cs_comment_share",
         fitness="R2:topic_share", n=16, topics={"food": 12, "restaurants_cafes": 4}, media=VIDEO, er=0.06,
         cadence=2.0, last=0.4, is_business=None, comments="en", found_via=["search:brno food"]),
    # ---------------------------------------------------------------- minor (dropped) ----------
    Spec("U1", TT, "nikolka_pece", "Nikolka", bio="14 let 🎂 | ráda peču", followers=2300,
         role="under 18: dropped by the provider, nothing stored", bakery="minor", fitness="minor",
         n=4, topics={"recipes": 4}, media=VIDEO, er=0.08, cadence=3.0, last=2.0, is_business=None,
         under18=True, found_via=["hashtag:brnojidlo"]),
]

# Cross-platform profiles (returned by find_cross_platform; not candidates).
CROSS_SPECS: dict[str, list[Spec]] = {
    "instagram:brnenska_snidane": [
        Spec("xB3a", TT, "brnenska_snidane", "Barbora Kolářová",
             bio="Snídaně a kavárny v Brně ☕ | IG @brnenska_snidane", followers=7300, role="same creator (links both ways, same website)",
             bakery="-", fitness="-", n=5, topics={"restaurants_cafes": 3, "food": 2}, media=VIDEO, er=0.06,
             cadence=3.0, last=1.4, is_business=None,
             external_urls=["https://brnenska-snidane.example", "https://instagram.mock.invalid/brnenska_snidane/"]),
        Spec("xB3b", TT, "brnenska_snidane_fans", "Brněnská snídaně fans",
             bio="Fanouškovský účet 💛 Nejsme Bára, jen ji rádi sledujeme. Not affiliated.", followers=410,
             role="fan account", bakery="-", fitness="-", n=4, topics={"restaurants_cafes": 4}, media=VIDEO,
             er=0.05, cadence=5.0, last=3.0, is_business=None),
    ],
    "instagram:fit_peci_s_klarou": [
        Spec("xS1", TT, "fit_peci_s_klarou", "Klára Veselá", bio="Pečení a cvičení 🍞💪 | IG @fit_peci_s_klarou",
             followers=8800, role="same creator", bakery="-", fitness="-", n=5,
             topics={"recipes": 3, "fitness": 2}, media=VIDEO, er=0.07, cadence=3.0, last=1.0, is_business=None,
             external_urls=["https://fitpeceni.example", "https://instagram.mock.invalid/fit_peci_s_klarou/"]),
    ],
    "tiktok:toman_ochutnava": [
        Spec("xB5", IG, "toman_ochutnava", "Ondřej Toman", gender="m",
             bio="Ochutnávám Brno 🍔 | víc na TikToku @toman_ochutnava", followers=6100, role="same creator",
             bakery="-", fitness="-", n=6, topics={"food": 4, "restaurants_cafes": 2}, er=0.05, cadence=3.0,
             last=2.0, external_urls=["https://tiktok.mock.invalid/@toman_ochutnava"]),
    ],
    "tiktok:pavla_hybe_brnem": [
        Spec("xF3", IG, "pavla_hybe_brnem", "Pavla Krejčí", bio="Cvičení pro každého 💪 | Brno | TikTok @pavla_hybe_brnem",
             followers=9800, role="same creator (IG audience 9.8k)", bakery="-", fitness="-", n=6,
             topics={"fitness": 4, "lifestyle": 2}, media=FITMIX, er=0.05, cadence=3.0, last=1.5,
             external_urls=["https://tiktok.mock.invalid/@pavla_hybe_brnem"]),
    ],
    "instagram:kalisthenika_brno_tom": [
        Spec("xF5", "youtube", "kalisthenika_brno_tom", "Tomáš Říha – kalisthenika", gender="m",
             bio="Tréninky s vlastní vahou z brněnských parků. Web: kalisthenika-brno.example", followers=12400,
             role="same creator (same website)", bakery="-", fitness="-", n=0, is_business=None,
             external_urls=["https://kalisthenika-brno.example"]),
    ],
    "instagram:kuba.jidlo.brno": [
        Spec("xB1", TT, "kuba_jidlo", "Kuba", gender="m", bio="Jedlo a cestovanie 🍜 | Bratislava",
             followers=2900, role="similar handle only, region SK, no links: not the same creator",
             bakery="-", fitness="-", n=4, topics={"food": 4}, media=VIDEO, er=0.05, cadence=4.0, last=2.0,
             is_business=None, city=None),
    ],
}
CROSS_REGION = {"xB1": "SK"}

# Meta Branded Content records (provider.collabs) keyed by candidate key.
META_COLLABS: dict[str, list[dict]] = {
    "B1": [{"brand_handle": "pekarna_a", "age": 75}, {"brand_handle": "pekarna_b", "post": ("special", 3)}],
    "B3": [{"brand_handle": "prazirna_hrudka", "post": ("special", 6)}],
    "S1": [{"brand_handle": "proteomax", "post": ("special", 5)}, {"brand_handle": "proteomax", "post": ("extra", 104)}],
    "F2": [{"brand_handle": "fitzone_brno", "post": ("extra", 68)}],
    "F5": [{"brand_handle": "vrcholek_sport", "post": ("special", 7)}],
}

# News items (provider.news). "sensitive": must be dropped by the filter (criminal = GDPR Art. 10).
NEWS: list[dict] = [
    {"key": "news_b5_namesake", "about": "B5", "kind": "namesake", "label": "allegation", "age": 23,
     "outlet": "Zlínský kurýr", "url": "https://zlinsky-kuryr.example/zpravy/podnikatel-a-subdodavatele",
     "title": "Zlínský podnikatel Ondřej Toman podle subdodavatelů dluží za stavbu školky",
     "snippet": "Tři subdodavatelé tvrdí, že stavební firma Ondřeje Tomana jim dluží přes dva miliony korun. Toman uvedl, že faktury rozporuje a věc chce vyřešit dohodou."},
    {"key": "news_b5_match", "about": "B5", "kind": "match", "label": "neutral", "age": 34,
     "outlet": "Jihomoravský kurýr", "url": "https://jihomoravsky-kuryr.example/brno/dvacet-trdelniku",
     "title": "Brněnský tiktoker otestoval dvacet trdelníků, vítěz překvapil",
     "snippet": "Ondřej Toman, na TikToku @toman_ochutnava, prošel za víkend dvacet stánků v centru Brna. Nejvíc ho nadchl malý stánek u Zelného trhu."},
    {"key": "news_b1_criminal", "about": "B1", "kind": "namesake", "label": "allegation", "age": 15, "sensitive": "criminal",
     "outlet": "Olomoucký kurýr", "url": "https://olomoucky-kuryr.example/zpravy/kradeze-kol",
     "title": "Policie obvinila muže z krádeže jízdních kol, jde o Jakuba Horáka z Olomouce",
     "snippet": "Jakub Horák podle policie ukradl během léta sedm kol ze sklepů v Olomouci."},
    {"key": "news_b1_match", "about": "B1", "kind": "match", "label": "neutral", "age": 70,
     "outlet": "Jihomoravský kurýr", "url": "https://jihomoravsky-kuryr.example/byznys/pekarna-a-nove-tvare",
     "title": "Pekárna A představila nové tváře své kampaně",
     "snippet": "Mezi ambasadory je i brněnský food tvůrce Jakub Horák (@kuba.jidlo.brno), který bude pekárnu podle majitelky zastupovat celý rok."},
    {"key": "news_f2_match", "about": "F2", "kind": "match", "label": "neutral", "age": 40,
     "outlet": "Jihomoravský kurýr", "url": "https://jihomoravsky-kuryr.example/sport/fitzone-rozsiruje-tym",
     "title": "FitZone Brno rozšiřuje tým trenérů",
     "snippet": "Nově vede ranní tréninky Marek Šimek (@trener_marek_brno), který se specializuje na silový trénink a techniku."},
    {"key": "news_f3_allegation", "about": "F3", "kind": "match", "label": "allegation", "age": 12,
     "outlet": "Spotřebitelský týdeník", "url": "https://spotrebitelsky-tydenik.example/clanky/slevove-kody-bez-oznaceni",
     "title": "Sledující si stěžují na neoznačené slevové kódy u fitness tvůrců",
     "snippet": "Podle stížností sledujících kódy bez označení reklamy údajně používá i brněnská tvůrkyně Pavla Krejčí (@pavla_hybe_brnem). Ta na dotaz redakce do uzávěrky nereagovala."},
    {"key": "news_s1_match", "about": "S1", "kind": "match", "label": "neutral", "age": 50,
     "outlet": "Jihomoravský kurýr", "url": "https://jihomoravsky-kuryr.example/kultura/kniha-domaciho-peceni",
     "title": "Brněnská blogerka vydává knihu receptů na domácí pečení",
     "snippet": "Klára Veselá (@fit_peci_s_klarou) v knize spojuje kváskové pečení s tréninkem pro začátečníky."},
    {"key": "news_f5_namesake", "about": "F5", "kind": "namesake", "label": "neutral", "age": 9,
     "outlet": "Hokejový zpravodaj", "url": "https://hokejovy-zpravodaj.example/extraliga/riha-prodlouzil",
     "title": "Útočník Tomáš Říha prodloužil smlouvu v Třinci o dva roky",
     "snippet": "Třiadvacetiletý hokejista Tomáš Říha bude za Třinec hrát i další dvě sezony."},
]

# Refused examples per goal (canonical demo; chat fallback loads briefs.json).
REFUSED = {
    "bakery": [
        M.Refused(text="jen věřící tvůrci", reason=M.i18n(
            "Víra je zvláštní kategorie údajů (čl. 9 GDPR). Podle ní tvůrce netřídíme.",
            "Religious belief is special-category data (GDPR Art. 9). We do not sort creators by it.")),
        M.Refused(text="najdi mi toho nejlepšího tvůrce", reason=M.i18n(
            "Celkové skóre ani „nejlepšího“ tvůrce neurčujeme. Ukážeme, jak kdo splňuje vaše kritéria, a rozhodnete vy.",
            "We do not produce an overall score or a 'best' creator. We show how each one meets your criteria and you decide.")),
    ],
    "fitness": [
        M.Refused(text="jen tvůrci, kteří nejsou politicky aktivní", reason=M.i18n(
            "Politické názory jsou zvláštní kategorie údajů (čl. 9 GDPR); podle nich lidi netřídíme.",
            "Political opinions are special-category data (GDPR Art. 9); we do not sort people by them.")),
        M.Refused(text="publikum hlavně ženy 20–30 let", reason=M.i18n(
            "Věk a pohlaví publika z veřejných dat zjistit nejde a neodhadujeme je. Zeptejte se tvůrce na jeho statistiky.",
            "Audience age and gender cannot be known from public data and we do not estimate them. Ask the creator for their insights.")),
    ],
}
COMPETITORS = {
    "bakery": [{"name": "Pekárna B", "handles": ["pekarna_b"]},
               {"name": "Chlebárna Vlnka", "handles": ["chlebarna_vlnka"]}],
    "fitness": [{"name": "FitZone Brno", "handles": ["fitzone_brno"]},
                {"name": "ProteoMax", "handles": ["proteomax"]}],
}
COMPETITOR_WHY = {
    "bakery": M.i18n(
        "Tvůrce, který právě dělá reklamu Pekárně B nebo Chlebárně Vlnka, by pro vás nebyl věrohodný.",
        "A creator currently promoting Pekárna B or Chlebárna Vlnka would not be credible for you."),
    "fitness": M.i18n(
        "Tvůrce, který dělá reklamu FitZone Brno nebo doplňkům ProteoMax, by pro vás nebyl věrohodný.",
        "A creator promoting FitZone Brno or ProteoMax supplements would not be credible for you."),
}

# ---------------------------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------------------------

PLATFORM_PREFIX = {"instagram": "ig", "tiktok": "tt", "youtube": "yt"}


def h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def base62(n: int, width: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = ""
    while len(out) < width:
        n, r = divmod(n, 62)
        out += alphabet[r]
    return out


# Reserved, never-resolving hosts (RFC 6761 ".invalid"): a MOCK link must never open a real account
# that may happen to own the same handle.
IG_HOST = "https://instagram.mock.invalid"
TT_HOST = "https://tiktok.mock.invalid"
YT_HOST = "https://youtube.mock.invalid"
FB_HOST = "https://facebook.mock.invalid"
MOCK_NAME_SUFFIX = " (MOCK)"


def profile_url(platform: str, handle: str) -> str:
    if platform == "instagram":
        return f"{IG_HOST}/{handle}/"
    if platform == "tiktok":
        return f"{TT_HOST}/@{handle}"
    return f"{YT_HOST}/@{handle}"


def post_ident(spec: Spec, i: int) -> tuple[str, str]:
    """-> (post id, url)."""
    if spec.platform == "instagram":
        code = "MOCK" + base62(int(h(f"{spec.handle}:{i}"), 16), 7)
        return f"ig:post:{code}", f"{IG_HOST}/p/{code}/"
    vid = str(7_400_000_000_000_000_000 + int(h(f"{spec.handle}:{i}")[:15], 16) % 10**17)
    return f"tt:video:{vid}", f"{TT_HOST}/@{spec.handle}/video/{vid}"


def src(id_: str, url: str, platform: str, quote: str | None = None) -> M.SourceRef:
    return M.SourceRef(id=id_, url=url, platform=platform, actor="mock:fixtures", fetched_at=ANCHOR,
                       mode="mock", quote=quote)


def stratified(counts: dict[str, float], n: int, rng: random.Random) -> list[str]:
    """Exact-proportion assignment (largest remainder), shuffled."""
    total = sum(counts.values()) or 1.0
    raw = {k: v / total * n for k, v in counts.items()}
    base = {k: int(v) for k, v in raw.items()}
    rest = n - sum(base.values())
    for k in sorted(raw, key=lambda k: (raw[k] - base[k], k), reverse=True)[:rest]:
        base[k] += 1
    out = [k for k, c in base.items() for _ in range(c)]
    rng.shuffle(out)
    return out


class Cycler:
    """Deterministic non-repeating picks from pools."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.state: dict[str, list] = {}

    def pick(self, key: str, pool: list):
        st = self.state.get(key)
        if not st:
            st = list(pool)
            self.rng.shuffle(st)
            self.state[key] = st
        return st.pop()


def fill(template: str, spec: Spec, rng: random.Random, cyc: Cycler) -> str:
    city = CITIES.get(spec.city or "_none", CITIES["_none"])
    pn, pa = cyc.pick("pastry", PASTRIES)
    return template.format(
        a="a" if spec.gender == "f" else "",
        near=cyc.pick("near", city["near"]),
        city_loc=city["loc"],
        city_en=city["en"],
        pastry_nom=pn,
        pastry_acc=pa,
        bake=cyc.pick("bake", BAKES),
        trip=cyc.pick("trip", TRIPS),
        mountains=cyc.pick("mountains", MOUNTAINS),
    )


def local_tags(spec: Spec, topic: str) -> list[str]:
    if spec.city == "Brno":
        return BRNO_TAGS.get(topic, ["brno"])
    if spec.city in CITIES and "tags" in CITIES[spec.city]:
        return CITIES[spec.city]["tags"]
    return []


@dataclass
class GenPost:
    post: M.Post
    topic: str
    sensitive: str | None = None
    special: bool = False
    lang: str = "cs"


def build_posts(spec: Spec, rng: random.Random, cyc: Cycler, *, extra: bool = False) -> list[GenPost]:
    """Latest posts (extra=False) or older posts for round 4 (extra=True), newest first."""
    if extra:
        count, start = spec.extra, spec.n
        specials_by_age = {round(s["age"]): s for s in spec.extra_special}
    else:
        count, start = spec.n, 0
        specials_by_age = {}
    if count <= 0:
        return []
    specials = {} if extra else {s["idx"]: s for s in spec.special}
    # ages
    ages = []
    for j in range(count):
        i = start + j
        jitter = rng.uniform(-0.3, 0.3) * spec.cadence if i > 0 else 0.0
        ages.append(round(spec.last + i * spec.cadence + jitter, 3))
    if extra:  # place each extra special on the nearest age slot
        for age, s in specials_by_age.items():
            j = min(range(count), key=lambda k: abs(ages[k] - age))
            specials[j] = s
    plain = [j for j in range(count) if j not in specials]
    if extra:
        topic_pool = [t for t, c in spec.topics.items() for _ in range(c)]
        topic_list = [rng.choice(topic_pool) for _ in plain]
    else:
        topic_list = [t for t, c in spec.topics.items() for _ in range(c)]
        assert len(topic_list) == len(plain), f"{spec.key}: topics {len(topic_list)} != plain slots {len(plain)}"
        rng.shuffle(topic_list)
    lang_list = stratified(spec.lang, len(plain), rng)
    media_list = stratified(spec.media, count, rng)
    ad_slots = set(rng.sample(plain, spec.ads)) if spec.ads and not extra else set()
    group = spec.template_group
    loc_city = CITIES.get(spec.city) if spec.city else None
    out: list[GenPost] = []
    tp = iter(topic_list)
    lg = iter(lang_list)
    for j in range(count):
        i = start + j
        pid, url = post_ident(spec, i)
        s = specials.get(j)
        sensitive = None
        mentions: list[str] = []
        coauthors: list[str] = []
        paid: bool | None = False
        lang = "cs"
        location = None
        if s:
            topic = s["topic"]
            caption = s["caption"]
            coauthors = list(s.get("coauthors", []))
            mentions = list(s.get("mentions", []))
            paid = s.get("paid", False)
            sensitive = s.get("sensitive")
            media = s.get("media") or media_list[j]
            if spec.platform == "tiktok":
                media = "video"
        else:
            topic = next(tp)
            lang = next(lg)
            media = media_list[j]
            tset = group or topic
            pool = TEMPLATES[lang].get(tset) or TEMPLATES[lang].get(topic) or TEMPLATES[lang]["food"]
            text = fill(cyc.pick(f"{lang}:{tset}", pool), spec, rng, cyc)
            tag_pool = (TOPIC_TAGS_EN if lang == "en" else TOPIC_TAGS).get(topic) or TOPIC_TAGS.get(topic, ["jidlo"])
            tags = rng.sample(tag_pool, 2)
            ltags = local_tags(spec, topic)
            if ltags and (j % 2 == 0 or j < 2):
                tags.append(ltags[j % len(ltags)])
            if j == 0 or j == 1:  # make discovery hashtags visible in the newest posts
                for fv in spec.found_via:
                    if fv.startswith("hashtag:") and fv.split(":", 1)[1] not in tags:
                        tags.append(fv.split(":", 1)[1])
            if j in ad_slots:
                brand = spec.ad_brands[len(out) % len(spec.ad_brands)]
                text += f" Díky @{brand} za spolupráci!"
                tags += ["spoluprace", "reklama"]
                mentions.append(brand)
                paid = True
            caption = text + "\n\n" + " ".join(f"#{t}" for t in dict.fromkeys(tags))
        if loc_city and spec.platform == "instagram" and not sensitive and j % 3 == 1:
            location = loc_city["locations"][(i // 3) % len(loc_city["locations"])]
        # engagement
        if spec.private:
            raise AssertionError("private accounts have no visible posts")
        inter = spec.followers * spec.er * rng.uniform(0.82, 1.18)
        if not extra and j in spec.spikes:
            inter *= 5
        ncom = max(2, round(inter * rng.uniform(0.05, 0.08)))
        likes = max(0, round(inter) - ncom)
        views = round(likes * rng.uniform(9, 18)) if media in ("reel", "video") else None
        mentions = list(dict.fromkeys(mentions + [m.lower() for m in MENTION_RE.findall(caption)]))
        mentions = [m.rstrip(".") for m in mentions]
        hashtags = [t.lower() for t in HASHTAG_RE.findall(caption)]
        created = (ANCHOR - timedelta(days=ages[j])).replace(microsecond=0)
        post = M.Post(
            id=pid, platform=spec.platform, url=url, author_handle=spec.handle, created_at=created,
            caption=caption, hashtags=hashtags, mentions=mentions, coauthors=coauthors, tagged_users=[],
            media_type=media, likes=likes, comments=ncom, views=views, location_name=location,
            paid_partnership=paid, language=lang if spec.platform == "tiktok" else None,
            source=src(pid, url, spec.platform),
        )
        out.append(GenPost(post=post, topic=topic, sensitive=sensitive, special=bool(s), lang=lang))
    return out


def build_profile(spec: Spec, posts: list[GenPost], rng: random.Random, region: str | None = None) -> M.Profile:
    prefix = PLATFORM_PREFIX[spec.platform]
    url = profile_url(spec.platform, spec.handle)
    pid = f"{prefix}:profile:{spec.handle}" if spec.platform != "youtube" else f"yt:channel:{spec.handle}"
    return M.Profile(
        handle=spec.handle, platform=spec.platform, url=url, display_name=spec.name + MOCK_NAME_SUFFIX, bio=spec.bio,
        followers=spec.followers, following=spec.following or rng.randint(180, 950),
        posts_count=(spec.n + spec.extra + rng.randint(40, 600)) if spec.platform != "youtube" else rng.randint(80, 160),
        verified=spec.verified, private=spec.private,
        is_business=spec.is_business if spec.platform == "instagram" else None,
        business_category=spec.category if spec.platform == "instagram" else None,
        external_urls=spec.external_urls, related_handles=spec.related,
        region=(region or "CZ") if spec.platform == "tiktok" else None,
        is_under_18=(True if spec.under18 else (False if spec.platform == "tiktok" else None)),
        former_handles=[], latest_posts=[g.post for g in posts],
        source=src(pid, url, spec.platform, quote=spec.bio or None),
    )


def build_comments(spec: Spec, posts: list[GenPost], rng: random.Random, cyc: Cycler) -> tuple[dict[str, list[M.Comment]], dict[str, str]]:
    """Comments for the newest COMMENT_POSTS posts. -> ({post_url: [Comment]}, {comment_id: category})."""
    out: dict[str, list[M.Comment]] = {}
    cats: dict[str, str] = {}
    main = max(spec.topics, key=spec.topics.get) if spec.topics else "food"
    group = "food" if main in ("food", "recipes", "restaurants_cafes", "local_tips") else (
        "fitness" if main in ("fitness", "sport", "lifestyle") else "general")
    cs_pool = (CS_FOOD if group == "food" else CS_FITNESS if group == "fitness" else []) + CS_GENERAL
    mix = COMMENT_MIX[spec.comments]
    for idx, g in enumerate(posts[:COMMENT_POSTS]):
        k = min(MAX_COMMENTS, g.post.comments or 0)
        cat_list = stratified(mix, k, rng)
        sens_text = None
        if spec.sensitive_comment and spec.sensitive_comment["idx"] == idx and k:
            sens_text = spec.sensitive_comment["text"]
            # replace one Czech comment with the sensitive one
            ci = cat_list.index("cs") if "cs" in cat_list else 0
            cat_list[ci] = "sensitive"
        lst = []
        code = g.post.id.split(":")[-1]
        for n, cat in enumerate(cat_list):
            if cat == "cs":
                text = cyc.pick(f"c:cs:{group}", cs_pool)
            elif cat == "sk":
                text = cyc.pick("c:sk", SK)
            elif cat == "en":
                text = cyc.pick("c:en", EN)
            elif cat == "emoji":
                text = cyc.pick("c:emoji", EMOJI_ONLY)
            elif cat == "generic":
                text = cyc.pick("c:gen", GENERIC_CS if spec.comments == "bought" else GENERIC)
            else:
                text = sens_text
            cid = f"{PLATFORM_PREFIX[spec.platform]}:comment:{code}:{n + 1}"
            created = (g.post.created_at + timedelta(hours=rng.uniform(0.2, 30))).replace(microsecond=0)
            lst.append(M.Comment(post_url=g.post.url, text=text, created_at=created,
                                 source=src(cid, g.post.url, spec.platform)))
            cats[cid] = cat
        out[g.post.url] = lst
    return out, cats


def discovery_refs(specs: list[Spec]) -> list[M.CandidateRef]:
    """One raw CandidateRef per (candidate, path), grouped by path kind like separate actor runs."""
    order = ["search", "hashtag", "place", "related"]
    refs = []
    for kind in order:
        for s in specs:
            for fv in s.found_via:
                if fv.split(":", 1)[0] != kind:
                    continue
                val = fv.split(":", 1)[1]
                if kind == "hashtag":
                    url = (f"{IG_HOST}/explore/tags/{val}/" if s.platform == "instagram"
                           else f"{TT_HOST}/tag/{val}")
                elif kind == "search" and s.platform == "tiktok":
                    url = f"{TT_HOST}/search/user?q=" + val.replace(" ", "%20")
                else:
                    url = profile_url(s.platform, s.handle)
                refs.append(M.CandidateRef(
                    handle=s.handle, platform=s.platform, found_via=[fv],
                    source=src(f"disc:{PLATFORM_PREFIX[s.platform]}:{s.handle}:{kind}:{h(fv)[:6]}", url, s.platform, quote=fv)))
    return refs


# ---------------------------------------------------------------------------------------------
# Reference funnel (verification + oracle)
# ---------------------------------------------------------------------------------------------

_DETECTOR = None


def detector():
    global _DETECTOR
    if _DETECTOR is None:
        from lingua import Language, LanguageDetectorBuilder
        _DETECTOR = LanguageDetectorBuilder.from_languages(
            Language.CZECH, Language.SLOVAK, Language.ENGLISH, Language.GERMAN, Language.POLISH,
            Language.UKRAINIAN, Language.RUSSIAN, Language.SPANISH, Language.ITALIAN, Language.FRENCH).build()
    return _DETECTOR


def detect(text: str) -> str | None:
    t = URL_RE.sub(" ", text)
    t = re.sub(r"[@#][\w.]+", " ", t)
    letters = "".join(ch if (ch.isalpha() or ch.isspace()) else " " for ch in t)
    if sum(ch.isalpha() for ch in letters) < 3:
        return None
    lang = detector().detect_language_of(letters)
    return lang.iso_code_639_1.name.lower() if lang else None


def is_emoji_only(text: str) -> bool:
    return not any(ch.isalnum() for ch in text)


GENERIC_FOLDED = {fold(re.sub(r"[^\w\s]", "", g)).strip() for g in GENERIC + GENERIC_CS}


def is_generic(text: str) -> bool:
    return is_emoji_only(text) or fold(re.sub(r"[^\w\s]", "", text)).strip() in GENERIC_FOLDED


def is_commercial(p: M.Post) -> bool:
    return bool(p.paid_partnership) or any(t in AD_HASHTAGS for t in p.hashtags) or bool(DISCOUNT_RE.search(p.caption))


def mentions_city(text: str, city: str) -> bool:
    f = fold(text)
    stem = fold(city)[:4]  # "brno" -> "brno"; also matches "brněnský" via "brn" below
    return stem in f or (city == "Brno" and re.search(r"\bbrn[eě]", f) is not None)


@dataclass
class Eval:
    status: str
    value: str
    margin: float | None = None   # relative distance from the threshold (positive = safe side)


def evaluate_criterion(c: M.Criterion, d: dict, competitors: list[dict]) -> Eval:
    p = c.params
    k = c.kind
    prof: M.Profile = d["profile"]
    posts: list[M.Post] = d["kept_posts"]
    if k == "public_account":
        return Eval("pass" if prof.private is False else ("fail" if prof.private else "unknown"), f"private={prof.private}")
    if k == "followers_range":
        f = prof.followers
        lo, hi = p.get("min"), p.get("max")
        ok = (lo is None or f >= lo) and (hi is None or f <= hi)
        m = min(((f - lo) / lo) if lo else 9, ((hi - f) / hi) if hi else 9)
        return Eval("pass" if ok else "fail", f"{f}", abs(m))
    if k == "active_recently":
        if not posts:
            return Eval("unknown", "no posts")
        age = (ANCHOR - max(x.created_at for x in posts)).total_seconds() / 86400
        return Eval("pass" if age <= p["days"] else "fail", f"{age:.1f} d", abs(p["days"] - age) / p["days"])
    if k == "not_brand_account":
        if prof.is_business is None:
            return Eval("unknown", "n/a")
        if prof.is_business and prof.business_category in COMPANY_CATEGORIES:
            return Eval("fail", prof.business_category or "")
        return Eval("pass", prof.business_category or "personal")
    if k == "language_cs":
        langs = [detect(x.caption) for x in posts]
        langs = [x for x in langs if x]
        if len(langs) < 3:
            return Eval("unknown", "<3 captions")
        share = langs.count("cs") / len(langs)
        return Eval("pass" if share >= p["min_share"] else "fail", f"{share:.2f}", abs(share - p["min_share"]) / p["min_share"])
    if k == "topic_share":
        if not posts:
            return Eval("unknown", "no posts")
        topics = d["topics"]
        counted = counted_topics(p["topics"])   # local tips support a food goal but never carry it alone
        hit = sum(1 for x in posts if topics[x.id] in counted)
        share = hit / len(posts)
        return Eval("pass" if share >= p["min_share"] else "fail", f"{hit}/{len(posts)}", abs(share - p["min_share"]) / p["min_share"])
    if k == "formats":
        if not posts:
            return Eval("unknown", "no posts")
        hit = sum(1 for x in posts if x.media_type in p["formats"])
        share = hit / len(posts)
        return Eval("pass" if share >= p["min_share"] else "fail", f"{hit}/{len(posts)}", abs(share - p["min_share"]) / p["min_share"])
    if k == "post_frequency":
        if len(posts) < 2:
            return Eval("unknown", "<2 posts")
        ts = sorted(x.created_at for x in posts)
        span = (ts[-1] - ts[0]).total_seconds() / 86400 / 7
        a, b = (len(posts) - 1) / span, len(posts) / span
        thr = p["min_per_week"]
        if (a >= thr) != (b >= thr):
            return Eval("ambiguous", f"{a:.2f}-{b:.2f}/wk", 0.0)
        return Eval("pass" if a >= thr else "fail", f"{a:.2f}-{b:.2f}/wk", min(abs(a - thr), abs(b - thr)) / thr)
    if k == "max_commercial_share":
        if not posts:
            return Eval("unknown", "no posts")
        share = sum(map(is_commercial, posts)) / len(posts)
        return Eval("pass" if share <= p["max_share"] else "fail", f"{share:.2f}", abs(p["max_share"] - share) / p["max_share"])
    if k == "min_engagement":
        rates = [((x.likes or 0) + (x.comments or 0)) / prof.followers for x in posts if x.likes is not None]
        if not rates:
            return Eval("unknown", "n/a")
        er = statistics.median(rates)
        return Eval("pass" if er >= p["min_rate"] else "fail", f"{er:.4f}", abs(er - p["min_rate"]) / p["min_rate"])
    if k in ("cs_comment_share", "max_generic_comments"):
        texts = d["r3_comments"]
        if not texts:
            return Eval("unknown", "no comments")
        if k == "cs_comment_share":
            langs = [x for x in (detect(t) for t in texts) if x]
            share = langs.count("cs") / len(langs) if langs else 0.0
            return Eval("pass" if share >= p["min_share"] else "fail", f"{share:.2f} of {len(langs)}", abs(share - p["min_share"]) / p["min_share"])
        share = sum(map(is_generic, texts)) / len(texts)
        return Eval("pass" if share <= p["max_share"] else "fail", f"{share:.2f} of {len(texts)}", abs(p["max_share"] - share) / p["max_share"])
    if k == "local_signal":
        city = p.get("city") or "Brno"
        n = sum(1 for x in posts if mentions_city((x.location_name or "") + " " + x.caption, city))
        n += 1 if mentions_city(prof.bio, city) else 0
        ok = n >= p["min_count"]
        return Eval("pass" if ok else "fail", f"{n} signals", None if (n == 0 or n >= p["min_count"] + 1) else 0.0)
    if k in ("no_competitor_collab", "discloses_ads"):
        ev = d["evidence"]
        if k == "no_competitor_collab":
            comp = {M.norm_handle(x) for c2 in competitors for x in c2.get("handles", [])}
            hits = sorted({e["brand"] for e in ev if e["brand"] in comp})
            return Eval("fail" if hits else "pass", ",".join(hits) or "none")
        und = sum(1 for e in ev if e["disclosed"] is False)
        if not ev:
            return Eval("not_fail", "no brand evidence")
        return Eval("fail" if und > p["max_undisclosed"] else "pass", f"{und} undisclosed")
    raise ValueError(k)


def collab_evidence(spec: Spec, posts: list[M.Post], meta: list[dict]) -> list[dict]:
    ev = []
    for x in posts:
        brands = [b for b in dict.fromkeys(x.coauthors + x.mentions) if b in BRANDS and b != spec.handle]
        if not brands:
            continue
        marker = bool(x.paid_partnership) or any(t in AD_HASHTAGS for t in x.hashtags) or any(
            ph in fold(x.caption) for ph in AD_PHRASES)
        disclosed = True if marker else (False if x.paid_partnership is False else None)
        for b in brands:
            ev.append({"brand": b, "disclosed": disclosed, "post_id": x.id})
    for m in meta:
        ev.append({"brand": m["brand_handle"], "disclosed": True, "post_id": m.get("post_id")})
    return ev


# ---------------------------------------------------------------------------------------------
# Build everything
# ---------------------------------------------------------------------------------------------


def build() -> dict[str, Any]:
    data: dict[str, Any] = {"profiles": [], "posts": {}, "comments": {}, "collabs": {}, "news": [],
                            "cross_platform": {}}
    gen: dict[str, dict] = {}
    sensitive = {"posts": [], "comments": [], "news": []}
    comment_cats: dict[str, str] = {}
    post_topics: dict[str, str] = {}
    by_key = {s.key: s for s in SPECS}

    for spec in SPECS:
        rng = random.Random(f"{SEED}:{spec.handle}")
        cyc = Cycler(random.Random(f"{SEED}:cyc:{spec.handle}"))
        latest = build_posts(spec, rng, cyc) if not spec.private else []
        extra = build_posts(spec, rng, cyc, extra=True) if spec.extra else []
        prof = build_profile(spec, latest, rng)
        data["profiles"].append(prof)
        if extra:
            data["posts"][spec.cid] = [g.post for g in extra]
        comments, cats = ({}, {}) if (spec.private or spec.under18) else build_comments(spec, latest, rng, cyc)
        data["comments"].update(comments)
        comment_cats.update(cats)
        for g in latest + extra:
            if g.sensitive:
                sensitive["posts"].append({"id": g.post.id, "candidate": spec.cid, "category": g.sensitive,
                                           "text": g.post.caption, "stems": sensitive_hits(g.post.caption)})
            else:
                post_topics[g.post.id] = g.topic
        for url, lst in comments.items():
            for c in lst:
                if cats[c.source.id] == "sensitive":
                    sensitive["comments"].append({"id": c.source.id, "candidate": spec.cid, "post_url": url,
                                                  "category": "health" if "celiak" in fold(c.text) else "politics",
                                                  "text": c.text, "stems": sensitive_hits(c.text)})
        gen[spec.key] = {"spec": spec, "latest": latest, "extra": extra, "profile": prof, "comments": comments}

    # Meta Branded Content records
    for key, items in META_COLLABS.items():
        spec = by_key[key]
        g = gen[key]
        lst = []
        for n, m in enumerate(items):
            post = None
            if "post" in m:
                where, val = m["post"]
                if where == "special":
                    post = g["latest"][val].post
                else:
                    post = min((x.post for x in g["extra"]), key=lambda p: abs((ANCHOR - p.created_at).days - val))
            date = post.created_at if post else ANCHOR - timedelta(days=m["age"])
            ad_id = str(9_100_000_000_000 + int(h(f"{spec.handle}:meta:{n}")[:10], 16) % 10**12)
            url = f"{FB_HOST}/ads/library/?id={ad_id}"
            bh = m["brand_handle"]
            lst.append(M.CollabEvidence(
                id=f"collab:meta:{ad_id}", brand=BRANDS[bh], brand_handle=bh, kind="meta_branded", disclosed=True,
                date=date, post_id=post.id if post else None, is_competitor=False,
                source=src(f"meta:ad:{ad_id}", url, "meta_branded",
                           quote=f"Placené partnerství s {BRANDS[bh]} (Meta Branded Content)")))
            m["post_id"] = post.id if post else None
        data["collabs"][spec.cid] = lst

    # News
    for item in NEWS:
        url = item["url"]
        ni = M.NewsItem(id=f"news:{M.short_hash(url)}", title=item["title"], outlet=item["outlet"], url=url,
                        published_at=ANCHOR - timedelta(days=item["age"]), snippet=item["snippet"],
                        source=src(f"news:{M.short_hash(url)}", url, "news", quote=item["title"]))
        data["news"].append(ni)
        item["id"] = ni.id
        if item.get("sensitive"):
            sensitive["news"].append({"id": ni.id, "candidate": by_key[item["about"]].cid, "category": item["sensitive"],
                                      "text": item["title"], "stems": sensitive_hits(item["title"] + " " + item["snippet"])})

    # Cross-platform
    for key, specs in CROSS_SPECS.items():
        profs = []
        for cs_ in specs:
            rng = random.Random(f"{SEED}:x:{cs_.key}")
            cyc = Cycler(random.Random(f"{SEED}:xcyc:{cs_.key}"))
            posts = build_posts(cs_, rng, cyc) if cs_.n else []
            profs.append(build_profile(cs_, posts, rng, region=CROSS_REGION.get(cs_.key)))
        data["cross_platform"][key] = profs

    data["discovery"] = discovery_refs(SPECS)
    data["sensitive"] = sensitive
    data["post_topics"] = post_topics
    data["comment_cats"] = comment_cats
    data["gen"] = gen
    return data


def briefs() -> dict[str, M.CriteriaSet]:
    out = {}
    for name in ("bakery", "fitness"):
        cs = get_preset(name)
        cs.brief.competitors = COMPETITORS[name]
        cs.refused = REFUSED[name]
        for c in cs.criteria:
            if c.kind == "no_competitor_collab":
                c.why = COMPETITOR_WHY[name]
        out[name] = M.CriteriaSet.model_validate(cs.model_dump())
    return out


def run_reference(data: dict, crit: dict[str, M.CriteriaSet]) -> tuple[dict, list[str]]:
    """Reference funnel for both goals; returns (oracle, problems)."""
    problems: list[str] = []
    sens_ids = {x["id"] for x in data["sensitive"]["posts"]}
    sens_comment_ids = {x["id"] for x in data["sensitive"]["comments"]}
    per: dict[str, dict] = {}
    for spec in SPECS:
        if spec.under18:
            continue
        g = data["gen"][spec.key]
        kept = [x.post for x in g["latest"] if x.post.id not in sens_ids]
        newest = sorted(kept, key=lambda p: p.created_at, reverse=True)[:R3_POSTS]
        r3 = []
        for p in newest:
            for c in g["comments"].get(p.url, [])[:MAX_COMMENTS]:
                if c.source.id not in sens_comment_ids:
                    r3.append(c.text)
        all_posts = kept + [x.post for x in g["extra"]]
        meta = META_COLLABS.get(spec.key, [])
        per[spec.key] = {"profile": g["profile"], "kept_posts": kept, "r3_comments": r3,
                         "topics": data["post_topics"], "evidence": collab_evidence(spec, all_posts, meta)}

    oracle: dict[str, Any] = {}
    for goal, cs in crit.items():
        active = [s for s in SPECS if not s.under18]
        rounds = []
        elim: dict[str, dict] = {}
        results: dict[str, dict] = {}
        for r in (1, 2, 3):
            entered = len(active)
            nxt = []
            for s in active:
                fail = None
                for c in cs.criteria:
                    if c.round != r or not c.enabled:
                        continue
                    ev = evaluate_criterion(c, per[s.key], cs.brief.competitors)
                    results.setdefault(s.cid, {})[c.id] = ev
                    if ev.status == "ambiguous":
                        problems.append(f"{goal} {s.key} {c.id}: ambiguous {ev.value}")
                    if ev.status == "fail" and fail is None:
                        fail = (c, ev)
                if fail:
                    elim[s.cid] = {"round": r, "criterion_id": fail[0].id, "value": fail[1].value}
                else:
                    nxt.append(s)
            rounds.append({"round": r, "entered": entered, "remaining": len(nxt)})
            active = nxt
        finalists = [s.cid for s in active]
        r4 = {}
        for s in active:
            r4[s.cid] = {}
            for c in cs.criteria:
                if c.round == 4:
                    ev = evaluate_criterion(c, per[s.key], cs.brief.competitors)
                    r4[s.cid][c.id] = {"status": "fail" if ev.status == "fail" else "not_fail", "value": ev.value}
        # compare with design + margins
        for s in SPECS:
            if s.under18:
                continue
            designed = getattr(s, goal)
            got = "F" if s.cid in finalists else f"R{elim[s.cid]['round']}:{elim[s.cid]['criterion_id']}"
            if designed != got:
                problems.append(f"{goal} {s.key} {s.handle}: designed {designed}, reference funnel got {got} "
                                f"({elim.get(s.cid, {}).get('value')})")
            for cid_, ev in results.get(s.cid, {}).items():
                if ev.margin is not None and ev.status in ("pass", "fail") and ev.margin < 0.1:
                    # only matters for criteria that were actually decisive or passed on the way
                    problems.append(f"{goal} {s.key} {cid_}: thin margin {ev.margin:.2f} ({ev.value})")
        oracle[goal] = {"rounds": rounds, "eliminated": elim, "finalists": finalists, "round4": r4,
                        "results": {k: {c: {"status": e.status, "value": e.value} for c, e in v.items()}
                                    for k, v in results.items()}}
    return oracle, problems


def validate_texts(data: dict) -> list[str]:
    """lingua: designed languages detected as designed; sensitive superset: only designated items hit."""
    problems = []
    sens_post_ids = {x["id"] for x in data["sensitive"]["posts"]}
    sens_comment_ids = {x["id"] for x in data["sensitive"]["comments"]}
    sens_news_ids = {x["id"] for x in data["sensitive"]["news"]}
    for spec in SPECS:
        g = data["gen"][spec.key]
        for x in g["latest"] + g["extra"]:
            p = x.post
            want = x.lang
            got = detect(p.caption)
            if p.id not in sens_post_ids and got != want:
                problems.append(f"lang {spec.key} {p.id}: want {want} got {got}: {p.caption[:70]!r}")
            hits = sensitive_hits(p.caption)
            if (p.id in sens_post_ids) != bool(hits):
                problems.append(f"sensitive {spec.key} {p.id}: hits={hits}: {p.caption[:70]!r}")
        if sensitive_hits(spec.bio) or sensitive_hits(spec.name):
            problems.append(f"sensitive bio {spec.key}: {sensitive_hits(spec.bio)}")
    for url, lst in data["comments"].items():
        for c in lst:
            cat = data["comment_cats"][c.source.id]
            hits = sensitive_hits(c.text)
            if (c.source.id in sens_comment_ids) != bool(hits):
                problems.append(f"sensitive comment {c.source.id}: {hits} {c.text!r}")
            if cat in ("cs", "sk", "en"):
                got = detect(c.text)
                if got != cat:
                    problems.append(f"comment lang {c.source.id}: want {cat} got {got}: {c.text!r}")
    for n in data["news"]:
        hits = sensitive_hits(n.title + " " + n.snippet)
        if (n.id in sens_news_ids) != bool(hits):
            problems.append(f"sensitive news {n.id}: {hits}")
    for key, profs in data["cross_platform"].items():
        for p in profs:
            for x in p.latest_posts:
                if sensitive_hits(x.caption):
                    problems.append(f"sensitive cross {p.handle}: {x.caption[:60]!r}")
    for kind in ("posts", "comments", "news"):
        for it in data["sensitive"][kind]:
            if not it["stems"]:
                problems.append(f"designated sensitive {kind} {it['id']} has no keyword hit")
    return problems


# ---------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------


def dump(obj: Any) -> Any:
    if isinstance(obj, M.BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: dump(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dump(v) for v in obj]
    return obj


def to_json(obj: Any) -> str:
    return json.dumps(dump(obj), ensure_ascii=False, indent=1) + "\n"


def comments_json(comments: dict[str, list[M.Comment]]) -> str:
    """Compact: one post URL per line (the file is the biggest one)."""
    lines = [json.dumps(url, ensure_ascii=False) + ": " + json.dumps(
        [c.model_dump(mode="json", exclude_none=True) for c in lst], ensure_ascii=False, separators=(",", ":"))
        for url, lst in comments.items()]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def candidate_table(data: dict) -> dict[str, dict]:
    out = {}
    for s in SPECS:
        out[s.cid] = {"key": s.key, "platform": s.platform, "handle": s.handle, "display_name": s.name,
                      "followers": s.followers, "role": s.role, "bakery": s.bakery, "fitness": s.fitness,
                      "found_via": s.found_via}
    return out


def expected_json(data: dict, oracle: dict | None) -> dict:
    gen = data["gen"]
    raw = data["discovery"]
    unique = list(dict.fromkeys((r.platform, r.handle) for r in raw))
    minors = [s.cid for s in SPECS if s.under18]
    exp: dict[str, Any] = {
        "anchor": ANCHOR.isoformat(),
        "note": "MOCK dataset: fictional creators, brands, outlets. Generated by fixtures/generate.py.",
        "discovery": {"raw_refs": len(raw), "unique": len(unique), "unique_after_minor_drop": len(unique) - len(minors),
                      "minors_dropped": minors},
        "candidates": candidate_table(data),
        "sensitive": data["sensitive"],
        "comment_posts_per_creator": COMMENT_POSTS,
        "company_categories": COMPANY_CATEGORIES,
        "creator_categories": CREATOR_CATEGORIES,
        "topic_hashtags": TOPIC_TAGS,
        "generic_comment_phrases": sorted(set(GENERIC + GENERIC_CS)),
        "emoji_only_comments": EMOJI_ONLY,
        "post_topics": data["post_topics"],
        "news": {n["key"]: {"id": n["id"], "about": by_cid(n["about"]), "kind": n["kind"], "label": n["label"],
                            "sensitive": n.get("sensitive")} for n in NEWS},
        "cross_platform": {k: [{"handle": p.handle, "platform": p.platform, "expected": c.role}
                               for p, c in zip(v, CROSS_SPECS[k])] for k, v in data["cross_platform"].items()},
        "collabs": {cid: [{"id": e.id, "brand_handle": e.brand_handle, "post_id": e.post_id}
                          for e in lst] for cid, lst in data["collabs"].items()},
    }
    if oracle:
        exp["goals"] = {g: {k: v for k, v in o.items() if k != "results"} for g, o in oracle.items()}
    return exp


def by_cid(key: str) -> str:
    for s in SPECS:
        if s.key == key:
            return s.cid
    raise KeyError(key)


CRIT_CS = {k: v["cs"] for k, v in M.CRITERION_DEFAULT_LABELS.items()}


def render_readme(data: dict, oracle: dict, crit: dict[str, M.CriteriaSet]) -> str:
    L: list[str] = []
    w = L.append
    exp = expected_json(data, oracle)
    by = {s.cid: s for s in SPECS}
    w("# MOCK dataset (fictional): test oracle")
    w("")
    w("**Everything in this folder is MOCK data.** All creators, handles, brands, news outlets and websites are "
      "fictional (websites use the reserved `.example` domain). Display names look like normal Czech names on "
      "purpose; every fetched object carries `source.mode = \"mock\"` and the UI shows a MOCK badge. "
      "Any resemblance to a real account is coincidental.")
    w("")
    w("Generated by `fixtures/generate.py` (deterministic, seeded). **Do not edit the JSON or this README by hand.** "
      "Regenerate from the repo root:")
    w("")
    w("```")
    w("backend/.venv/bin/python fixtures/generate.py          # writes fixtures/*.json + README.md")
    w("backend/.venv/bin/python fixtures/generate.py --check  # fails if the files on disk are stale")
    w("```")
    w("")
    w("Before writing, the generator runs a *reference funnel* (own simple metric code + lingua, rules from "
      "docs/architecture.md section 5, criteria from `briefs.json`) and aborts if any candidate's outcome differs "
      "from the design or a decisive value sits within 10 % of its threshold. Everything below comes from that run.")
    w("")
    w("## Files")
    w("")
    w("| File | Shape |")
    w("|---|---|")
    w("| `meta.json` | `{anchor, seed, ...}`. All timestamps are relative to `anchor`; MockProvider shifts them by `now - anchor` |")
    w(f"| `discovery.json` | `[CandidateRef]`, one per (creator, path): {exp['discovery']['raw_refs']} raw refs, {exp['discovery']['unique']} unique, the minor is dropped by the provider -> **{exp['discovery']['unique_after_minor_drop']} candidates** |")
    w("| `profiles.json` | `[Profile]` with `latest_posts` (12-24 posts, private accounts have none) |")
    w("| `posts.json` | `{\"<platform>:<handle>\": [Post]}` older posts (up to ~5 months) for the 9 finalists; `posts()` returns latest + these |")
    w(f"| `comments.json` | `{{post_url: [Comment]}}` for the newest {COMMENT_POSTS} posts of every public creator, max {MAX_COMMENTS} per post, text only (no commenter identity) |")
    w("| `collabs.json` | `{\"<platform>:<handle>\": [CollabEvidence]}` Meta Branded Content records (kind `meta_branded`) |")
    w("| `news.json` | `[NewsItem]`; `news(query)` matches query tokens against title + snippet |")
    w("| `cross_platform.json` | `{\"<platform>:<handle>\": [Profile]}` for `find_cross_platform` |")
    w("| `briefs.json` | `{\"bakery\": CriteriaSet, \"fitness\": CriteriaSet}` canonical demo criteria (params = app/presets.py, plus 2 competitors and refused examples per goal) |")
    w("| `expected.json` | machine-readable version of this README (oracle for tests) + `post_topics` {post_id: designed topic} |")
    w("")
    w("## Two goals, one pool")
    w("")
    for g in ("bakery", "fitness"):
        cs = crit[g]
        comp = ", ".join(f"{c['name']} (@{c['handles'][0]})" for c in cs.brief.competitors)
        w(f"- **{g}**: {cs.brief.business_type}, {cs.brief.city}; competitors {comp}.")
    w("")
    w("Criteria params that decide the outcomes (from `briefs.json`):")
    w("")
    w("| criterion | bakery | fitness |")
    w("|---|---|---|")
    pb = {c.id: c.params for c in crit["bakery"].criteria}
    pf = {c.id: c.params for c in crit["fitness"].criteria}
    for c in crit["bakery"].criteria:
        w(f"| `{c.id}` (R{c.round}) | `{json.dumps(pb[c.id], ensure_ascii=False)}` | `{json.dumps(pf.get(c.id), ensure_ascii=False)}` |")
    w("")
    for g in ("bakery", "fitness"):
        o = oracle[g]
        funnel = " → ".join([str(o["rounds"][0]["entered"])] + [str(r["remaining"]) for r in o["rounds"]])
        w(f"## Goal `{g}`: {funnel}")
        w("")
        w("| round | entered | remaining |")
        w("|---|---|---|")
        for r in o["rounds"]:
            w(f"| {r['round']} | {r['entered']} | {r['remaining']} |")
        w("")
        for r in (1, 2, 3):
            w(f"### {g}, round {r}: eliminated")
            w("")
            w("| candidate | first failing criterion | reference value | why it is in the dataset |")
            w("|---|---|---|---|")
            for cid, e in sorted(o["eliminated"].items(), key=lambda kv: (kv[1]["criterion_id"], kv[0])):
                if e["round"] != r:
                    continue
                w(f"| `{cid}` | `{e['criterion_id']}` | {e['value']} | {by[cid].role} |")
            w("")
        w(f"### {g}: finalists ({len(o['finalists'])})")
        w("")
        w("| candidate | `no_competitor_collab` | `discloses_ads` | story |")
        w("|---|---|---|---|")
        for cid in o["finalists"]:
            r4 = o["round4"][cid]
            w(f"| `{cid}` | {r4['no_competitor_collab']['status']} ({r4['no_competitor_collab']['value']}) | "
              f"{r4['discloses_ads']['status']} ({r4['discloses_ads']['value']}) | {by[cid].role} |")
        w("")
        w("Round 4 never eliminates; `not_fail` means pass or unknown (no brand evidence at all may be shown as unknown).")
        w("")
    w("## Goal change: who differs")
    w("")
    w("| candidate | bakery | fitness |")
    w("|---|---|---|")
    for s in SPECS:
        if s.under18 or s.bakery == s.fitness:
            continue
        w(f"| `{s.cid}` | {s.bakery} | {s.fitness} |")
    w("")
    w("`F` = finalist, `R<n>:<criterion>` = eliminated in round n by that criterion. Shared finalist: "
      "`instagram:fit_peci_s_klarou` (ProteoMax collab is a competitor only for fitness).")
    w("")
    w("## Sensitive items (must be dropped before storage, count only)")
    w("")
    w("The keyword fallback must catch these (cs, diacritics-insensitive). The *stems* column lists what the "
      "generator's own superset check found; no other caption, bio, comment or news text in the dataset "
      "matches that superset (prefix match on words).")
    w("")
    w("| kind | id | candidate | category | text | stems |")
    w("|---|---|---|---|---|---|")
    for kind in ("posts", "comments", "news"):
        for it in data["sensitive"][kind]:
            text = it["text"].replace("\n", " ").replace("|", "/")
            w(f"| {kind.rstrip('s') if kind != 'news' else 'news'} | `{it['id']}` | `{it['candidate']}` | {it['category']} | {text} | {', '.join(sorted(set(it['stems'])))} |")
    w("")
    w("Expected `sensitive_filtered` per candidate: B3 `brnenska_snidane` 1 (post), S1 `fit_peci_s_klarou` 1 (post), "
      "F5 `kalisthenika_brno_tom` 1 (post) after round 1; B1 `kuba.jidlo.brno` +1 and F4 `jogina_lucie` +1 (comment) "
      "in round 3; B1 +1 (news) in round 4. Note for the keyword list: the dataset uses the word *lekce* nowhere, but "
      "a bare `lek` stem would also hit *mléko*/*lekce*; prefer `lék`, `lékař`, `léčb`.")
    w("")
    w("## Round 4 stories (finalists)")
    w("")
    w("- **`instagram:kuba.jidlo.brno`** bio: \"exkluzivní ambasador @pekarna_a\". Posts coauthored with competitor "
      "`@pekarna_b`: one labeled (`paid_partnership=true`, `#spoluprace`, also in Meta Branded Content), one unlabeled "
      "(`paid_partnership=false`, no marker) — both within the last 30 days. Older labeled @pekarna_a post (~78 d) + "
      "Meta record. News: matched neutral item (Pekárna A ambassadors) and a *criminal* namesake item (Olomouc) that "
      "the filter must drop. Cross-platform: TikTok `kuba_jidlo` (region SK, no links) = not the same creator.")
    w("- **`instagram:verca_pece`** caption \"Poctivá recenze, nikdo mi neplatí\" + `@mlynek_eshop` + code `VERCA15` + "
      "affiliate link `mlynek-eshop.example/?aff=VERCA15`, `paid_partnership=false`; same pattern in an older post. "
      "No Meta records, no news, no cross-platform.")
    w("- **`instagram:brnenska_snidane`** clean: one labeled coffee collab (`@prazirna_hrudka`, also in Meta). "
      "Cross-platform: TikTok `brnenska_snidane` (links both ways, same website) and fan account "
      "`brnenska_snidane_fans` (\"Fanouškovský účet ... Not affiliated\"). No news.")
    w("- **`tiktok:toman_ochutnava`** clean. News: matched neutral item (handle in snippet) and a namesake *allegation* "
      "about a Zlín builder with the same name (only the name matches, other city and job -> namesake: `uncertain` or "
      "`rejected`, never attributed to the creator; skeptic flags the risk). Cross-platform: "
      "IG `toman_ochutnava` (links both ways). `collabs()` returns [] (Meta records are IG/FB only).")
    w("- **`instagram:fit_peci_s_klarou`** (shared) labeled `@proteomax` coauthor post with code KLARA10 + 2 Meta "
      "records. Bakery: no competitor. Fitness: ProteoMax is a competitor -> `no_competitor_collab` fail. News: matched "
      "neutral (book). Cross-platform: TikTok `fit_peci_s_klarou` (same website).")
    w("- **`instagram:trener_marek_brno`** unlabeled post \"vedl trénink ve @fitzone_brno\" (~13 d), older labeled "
      "FitZone post + Meta record, news \"FitZone Brno rozšiřuje tým trenérů\" (matched, handle in snippet).")
    w("- **`tiktok:pavla_hybe_brnem`** bio \"Komunita 120 tisíc sledujících\" vs 31.2k TikTok + 9.8k IG (cross-platform). Two "
      "unlabeled `@vrcholek_sport` posts with code PAVLA20 (not a competitor). News: matched *allegation* "
      "(undisclosed discount codes, consumer weekly).")
    w("- **`tiktok:jogina_lucie`** clean, 4.2k followers (yoga and running: wrong topic for the bakery). One politics comment to drop.")
    w("- **`instagram:kalisthenika_brno_tom`** clean (labeled `@vrcholek_sport` collab + Meta record), 44k (wrong topic "
      "for the bakery). YouTube channel with the same website. News: hockey-player namesake (neutral, name only).")
    w("")
    w("## Notes for implementers")
    w("")
    w("- **Dates**: fixtures are written relative to `meta.json.anchor`; MockProvider shifts every timestamp by "
      "`now - anchor` at load. Active creators posted 0.4-3 days before now; inactive ones 104-131 days.")
    w("- **Discovery**: `discover(DEMO_DISCOVERY)` returns one ref per path (search, hashtag, place, related); "
      "round 0 must dedupe by (platform, handle) and merge `found_via`. A query matching nothing returns the whole pool.")
    w("- **Brand accounts**: `is_business=true` with `business_category` in "
      f"{', '.join('`'+c+'`' for c in COMPANY_CATEGORIES)}. Creator business accounts use "
      f"{', '.join('`'+c+'`' for c in CREATOR_CATEGORIES[:2])}. TikTok profiles have `is_business=None` (unknown).")
    w("- **Paid labels**: unlike real Instagram data (often `None`), the mock sets `paid_partnership` to `true`/`false` "
      "on every post, so `disclosed=False` is reachable for unlabeled brand posts.")
    w("- **Topics**: every post carries 2+ topic hashtags (see `expected.json.topic_hashtags`) and topic words; "
      "`expected.json.post_topics` has the designed topic per post for testing `topics.fallback_classify`.")
    w("- **Local signal**: local creators have `Brno` in bio, `#brno...` hashtags and `location_name` like "
      "`Brno - Zelný trh` on every third IG post. Prague/Ostrava creators have no `brno`/`brněnsk` anywhere.")
    w("- **Comments**: categories per creator are stratified per post (Czech, Slovak, English, emoji-only, generic). "
      "Generic phrases: `expected.json.generic_comment_phrases`.")
    w("- **Engagement spikes**: `srdicka_a_dorty` and `fit_mama_eliska` have two posts with ~5x interactions.")
    w("")
    w("## All candidates")
    w("")
    w("| candidate | followers | found via | bakery | fitness |")
    w("|---|---|---|---|---|")
    for s in SPECS:
        w(f"| `{s.cid}` ({s.name}) | {s.followers:,} | {', '.join(s.found_via)} | {s.bakery} | {s.fitness} |")
    w("")
    return "\n".join(L)


def outputs(data: dict, crit: dict, oracle: dict | None) -> dict[str, str]:
    meta = {"anchor": ANCHOR.isoformat(), "seed": SEED, "city": "Brno", "mode": "mock",
            "note": "MOCK dataset: fictional creators, brands, outlets and websites. Do not edit by hand; run fixtures/generate.py.",
            "date_fields": ["created_at", "published_at", "date", "fetched_at"]}
    files = {
        "meta.json": to_json(meta),
        "discovery.json": to_json(data["discovery"]),
        "profiles.json": to_json(data["profiles"]),
        "posts.json": to_json(data["posts"]),
        "comments.json": comments_json(data["comments"]),
        "collabs.json": to_json(data["collabs"]),
        "news.json": to_json(data["news"]),
        "cross_platform.json": to_json(data["cross_platform"]),
        "briefs.json": to_json(crit),
        "expected.json": to_json(expected_json(data, oracle)),
    }
    if oracle:
        files["README.md"] = render_readme(data, oracle, crit)
    return files


def self_check(files: dict[str, str]) -> None:
    """Every file loads back through app.models."""
    json.loads(files["meta.json"])
    [M.CandidateRef.model_validate(x) for x in json.loads(files["discovery.json"])]
    [M.Profile.model_validate(x) for x in json.loads(files["profiles.json"])]
    for v in json.loads(files["posts.json"]).values():
        [M.Post.model_validate(x) for x in v]
    for v in json.loads(files["comments.json"]).values():
        [M.Comment.model_validate(x) for x in v]
    for v in json.loads(files["collabs.json"]).values():
        [M.CollabEvidence.model_validate(x) for x in v]
    [M.NewsItem.model_validate(x) for x in json.loads(files["news.json"])]
    for v in json.loads(files["cross_platform.json"]).values():
        [M.Profile.model_validate(x) for x in v]
    for v in json.loads(files["briefs.json"]).values():
        M.CriteriaSet.model_validate(v)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=HERE, help="output directory (default: fixtures/)")
    ap.add_argument("--no-verify", action="store_true", help="skip lingua + reference funnel (README not written)")
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if files on disk differ")
    ap.add_argument("--force", action="store_true", help="write even if verification finds problems")
    args = ap.parse_args(argv)

    data = build()
    crit = briefs()
    oracle = None
    if not args.no_verify:
        problems = validate_texts(data)
        oracle, p2 = run_reference(data, crit)
        problems += p2
        if problems:
            print("VERIFICATION PROBLEMS:", file=sys.stderr)
            for p in problems:
                print("  -", p, file=sys.stderr)
            if not args.force:
                return 2
    files = outputs(data, crit, oracle)
    self_check(files)
    if args.check:
        stale = [n for n, c in files.items() if not (args.out / n).exists() or (args.out / n).read_text("utf-8") != c]
        if stale:
            print("stale:", ", ".join(stale), file=sys.stderr)
            return 1
        print("fixtures up to date")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, "utf-8")
    if oracle:
        for g, o in oracle.items():
            print(g, " -> ".join([str(o["rounds"][0]["entered"])] + [str(r["remaining"]) for r in o["rounds"]]),
                  "finalists:", ", ".join(o["finalists"]))
    print(f"wrote {len(files)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
