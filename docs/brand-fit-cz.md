# Creator Scout: výběr a prověrka tvůrce pro malé firmy

Ověření faktů k 8. 10. 2026: [overeni-2026-10-08.md](overeni-2026-10-08.md). Actory, vstupy, testy a ceny pro Kryštofa: [apify-pro-krystofa.md](apify-pro-krystofa.md).

Rozpracování nápadu „Hypocrisy Compass / Brand Safety Shield“ (bod 6) a dalších podkladů od kolegy. Verze 6 (8. 10. 2026): chatbot pro laika, vyřazovací kola, důraz na typ obsahu a publikum, hloubková prověrka finalistů; opravy podle ověření zdrojů. Odkazy jsou u faktů; co jsme neověřili, je označené „(neověřeno)“. Kostra obrazovek pro design: [kostra-aplikace-cz.md](kostra-aplikace-cz.md).

## 1. Verdikt v kostce

- **Problém:** majitel pekárny nebo kavárny chce spolupracovat s tvůrcem, ale neví koho, podle čeho vybírat a co si ověřit. Nástroje na hledání tvůrců (HypeAuditor, Modash od 199 USD měsíčně při ročním placení, Heepsy i ve free plánu) jsou pro marketéry, ne pro laika.
- **Řešení:** chatbot se majitele zeptá na firmu a cíl, navrhne kritéria a vysvětlí je. Aplikace najde kandidáty, v několika kolech je vyřazuje podle obsahu a publika a 3 až 5 finalistů prověří do hloubky. Každé vyřazení má kolo, důvod a zdroj.
- **Bereme z bodu 6:** hodnoty a cíl sponzora jako vstup, hledání nesouladu mezi tím, co tvůrce tvrdí, a tím, co ukazují jeho posty a spolupráce (v hloubkové prověrce).
- **Bereme z dalších podkladů:** identitu s vysvětlením, barvy fakt / inference / mezera, přepínání cíle.
- **Škrtáme:** všechno, co hodnotí člověka nebo odvozuje jeho názory: lajky, „pohledy na věci“, označení na fotkách od jiných, „vegan persona“, skóre 45/100, úrovně rizika, „Rodinné hodnoty“, „Apolitiku“. A nově i „nejlepší tvůrce“ jako jedno číslo.
- **Proč na tom záleží:**
  - Reklamu z placené spolupráce, i z barteru, je potřeba výslovně označit ([Kodex reklamy 2025, čl. 34.6](https://www.rpr.cz/wp-content/uploads/2025/09/Kodex-reklamy_2025.pdf)). Za reklamu odpovídá firma (zadavatel) společně a nerozdílně s tvůrcem ([§ 6b zák. 40/1995 Sb.](https://www.zakonyprolidi.cz/cs/1995-40), [doporučení SPIR](https://old.spir.cz/www.samoregulace.cz/doporucena-pravidla-spoluprace-zadavatele-influencera.html)), ledaže prokáže, že tvůrce nedodržel její pokyny. Jako prodávající odpovídá i podle zákona o ochraně spotřebitele, skrytá placená propagace je vždy klamavá ([zák. 634/1992 Sb., příloha 1 písm. j)](https://www.zakonyprolidi.cz/cs/1992-634)). Pokuta až 5 mil. Kč. Pomůže písemný pokyn k označení a kontrola zveřejněného postu.
  - Evropská komise a spotřebitelské úřady včetně českého na podzim 2023 prověřily 576 převážně velkých influencerů (výsledky 14. 2. 2024): 97 % zveřejňovalo komerční obsah, ale jen každý pátý ho soustavně označoval ([IP/24/708](https://ec.europa.eu/commission/presscorner/detail/en/ip_24_708), [zahájení prověrky](https://commission.europa.eu/news/commission-and-consumer-authorities-look-business-practices-influencers-2023-10-16_en)).

## 2. Co škrtáme a čím to nahradíme

| Prvek z nápadu | Proč neprojde | Náhrada |
|---|---|---|
| Lajky a odpovědi na X / Threads | Lajky na X jsou od června 2024 neveřejné ([zdroj](https://www.ksat.com/business/2024/06/12/what-happened-to-the-likes-x-is-now-hiding-which-posts-you-like-from-other-users/)). Odvodit z lajků politický názor nebo přesvědčení je podle logiky SDEU zpracování dat podle čl. 9 ([C-184/20, body 123–128](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62020CJ0184); [C-252/21, bod 68](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62021CJ0252)), i když je odhad chybný (C-252/21, bod 69). Lajky nejsou „zjevně zveřejněné“, pokud je uživatel vědomě nezveřejnil (C-252/21, body 80–82). | Vlastní veřejné posty tvůrce, jen obsah a obchodní chování. |
| „Jeho pohledy na věci“ | Profil názorů = politika, víra, zdraví, sexualita, etnicita, tedy čl. 9. | Typ obsahu (o čem tvoří) a co řekl o značkách a produktech. |
| Označení na fotkách od jiných, „steakhouse“ | Označují tě jiní, nic to nedokazuje. Z jídla jde odvodit přesvědčení nebo zdravotní stav (čl. 9). | Vlastní posty tvůrce. |
| „Vegan persona vs. chování“ | Přesvědčení je kategorie čl. 9 GDPR. ESLP uznal upřímné veganské přesvědčení za chráněné čl. 9 Úmluvy (G.K. a A.S. proti Švýcarsku, rozsudek senátu 16. 7. 2026, body 86–89, [HUDOC](https://hudoc.echr.coe.int/eng?i=001-251193)); zatím nemusí být konečný a pro GDPR je to jen analogie. | Konkurenti, které zadá majitel. |
| Brand Safety Score 45/100, „Nedoporučeno“, „nejlepší tvůrce“ | Zadání zakazuje skóre důvěryhodnosti člověka. Blízko zákazu sociálního skórování v AI Actu, čl. 5 odst. 1 písm. c), platí od 2. 2. 2025 ([FPF](https://fpf.org/blog/red-lines-under-the-eu-ai-act-unpacking-social-scoring-as-a-prohibited-ai-practice)). Odstrašující příklad: Predictim, 2018, zablokovaly ho Facebook, Instagram i Twitter ([CBS](https://www.cbsnews.com/news/ai-babysitting-service-predictim-blocked-by-facebook-and-twitter/)). | U každého kritéria splněno / nesplněno / nejde ověřit, se zdrojem. Řazení jen podle kritéria, které vybere majitel. Rozhoduje on. |
| „Jistota identity 95 %“ | Vymyšlené, nekalibrované číslo. | Signály a stav přiřazeno / nejisté / vyřazeno. |
| Hodnoty „Rodinné hodnoty“, „Apolitika“ | Ověřit je jde jen přes náboženství, sexualitu nebo politiku. | Chatbot je odmítne a vysvětlí proč. |
| „Arogantní debaty → asertivní“ | Hodnocení osobnosti, zakázané. | Jiný cíl = jiná kritéria, jiní finalisté (sekce 7). |
| Politické kampaně jako cílovka | Celé je to o politických názorech. | Vypustit. |
| Rámování „co ho může zničit“ | Porota to přečte jako stalking nástroj. | „Najdi tvůrce, který sedí, a ověř, co tvrdí.“ |
| CEO, „skrytá telemetrie“, „CryptoBros s.r.o.“ | Mimo tvůrce. | Vypustit. |

## 3. Koncept

**Uživatel:** majitel malé firmy bez zkušeností s influencer marketingem (pekárna, kavárna, e-shop). Druhotně agentury.

### Rozhovor s chatbotem

Chatbot (Claude s nástroji) se zeptá:
- Co prodáváte a kde? Komu chcete prodávat? Co má kampaň udělat?
- Zhruba jaký rozpočet (kvůli velikosti tvůrce)?
- Máte konkurenty, se kterými by tvůrce neměl spolupracovat?

Pak navrhne kritéria jednoduchou řečí a u každého řekne proč. Majitel je schválí nebo upraví. Kritéria podle víry, politiky, zdraví, sexuality nebo původu chatbot odmítne a vysvětlí proč.

### Kritéria

| Skupina | Kritérium | Z čeho to víme |
|---|---|---|
| Typ obsahu | témata (jídlo, recepty, lokální tipy, rodina, lifestyle), podíl relevantních postů | popisky a hashtagy posledních postů, LLM je roztřídí do témat |
| | formát (reels, fotky, videa), frekvence, poslední aktivita | typ a datum postů |
| | komerční nasycenost (kolik % postů je reklama) | popisky posledních ~12 postů: #reklama, #spoluprace, slevové kódy, zmínky @značek. Štítek placeného partnerství (`paidPartnership`) dá jen druhý běh post-scraperu (na českých postech neověřeno). |
| Publikum | velikost (např. 5 až 50 tisíc) | počet sledujících |
| | aktivita publika | medián veřejně viditelných lajků a komentářů, interakce vůči sledujícím. Posty se skrytými lajky vynecháme, zhlédnutí z profilu nepoužíváme. |
| | jazyk publika | podíl komentářů v češtině (detekce jazyka, jména komentujících neukládáme) |
| | lokalita | místo u postů nalezených při hledání (`locationId`, souřadnicemi ověříme, že je v Brně; text `locationName` jen záloha), zmínky města v bio a popiscích; na TikToku země vzniku videa (`locationCreated`) a místo, pokud ho tvůrce u videa označí (`locationMeta`, u českých videí neověřeno). Region účtu na TikToku dnes pravděpodobně chybí. Posty stažené z profilu místo neobsahují. |
| | pravost publika | podíl komentářů jen z emoji nebo obecných frází, nepoměr interakcí a sledujících. Jen signály o účtu. |
| Spolupráce | žádná spolupráce s konkurenty | značky v postech, společné posty, štítky spolupráce |
| | označuje reklamu | štítky a hashtagy u postů se zmínkou značky (stačí štítek platformy, text, nebo reklamní hashtag na začátku; platí i pro barter, Kodex čl. 34.6) |

**Upřímně o publiku:** věk, pohlaví a původ publika z veřejných dat zjistit nejde. Ukazují je jen statistiky v účtu tvůrce nebo placené odhady. Neodhadujeme je, protože by to znamenalo soudit lidi z jmen a fotek. V reportu je to jako mezera a otázka pro tvůrce („Můžete poslat statistiky publika?“).

### Vyřazovací kola

| Kolo | Co se děje | Cena | Typicky zůstane |
|---|---|---|---|
| 0. Hledání | hashtagy, klíčová slova a místa na IG a TikToku → seznam účtů. Nebo majitel vloží vlastní seznam. | levné | 40–60 |
| 1. Základ | veřejný účet, čeština, velikost, aktivita za 30 dní (připnuté posty nepočítáme). Kdo v bio uvede věk pod 18, jde ven hned a bez uložení dat. | levné, stejná dávka | 20–30 |
| 2. Obsah | témata, podíl relevantních postů, formát, frekvence, komerční nasycenost | jeden LLM průchod na účet | 10–15 |
| 3. Publikum | interakce, jazyk komentářů, lokalita, pravost | komentáře jen pro zbylé | 5–8 |
| 4. Hloubková prověrka | spolupráce a konkurence, tvrzení vs. důkaz, označování, pracovní zprávy, identita | dražší, chatbot se zeptá | 3–5 finalistů |

- Každé vyřazení: kolo, kritérium, hodnota, zdroj. „Kolo 2: jen 2 z 12 postů jsou o jídle.“
- Chybějící data nejsou důvod k vyřazení. Prázdné `latestPosts` u veřejného profilu (známá chyba actoru) znamená stáhnout znovu, ne „neaktivní“.
- Věk z veřejných dat spolehlivě nezjistíme (IG pole věku nemá, TikTok `isUnderAge18` je pravděpodobně prázdné). Finalista bez potvrzené plnoletosti nejde do reportu bez ověření majitelem.
- Majitel může kandidáta vrátit („tohle kritérium pro něj neplatí“).
- U vyřazených po běhu necháme jen jméno účtu a důvod, stažené posty smažeme.

### Hloubková prověrka finalisty (bod 6)

- **Tvrzení tvůrce, která ověřujeme:** „exkluzivní ambasador X“, „neplacená recenze“, „komunita 120 tisíc“, vlastní tvrzení o spolupracích.
- **Důkazy:** jeho posty, štítky placené spolupráce (IG `paidPartnership`, TikTok `isSponsored`, YouTube „Includes paid promotion“; chybějící štítek nic nedokazuje), slevové kódy, společné posty, Meta Branded Content, cílené zprávy.
- **Pracovní zprávy a kontroverze:** spolupráce, reklamy, produkty, soutěže, rozhodnutí Rady pro reklamu. Vždy „píše médium X“ a rozlišení obvinění vs. potvrzený fakt.
- **Nebereme:** názory, lajky, tón a povahu, soukromí, fotky od jiných, trestní věci ani pokuty za správní delikty (čl. 10 GDPR, [C-439/19](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62019CJ0439)). Citlivý obsah (zdraví, politika, víra, sexualita, etnicita) filtr zahodí před uložením, report ukáže jen počet.

## 4. Jak to běží

Jádro převzaté z plánu Lens (ledger tvrzení, identita, skeptik, mezery).

1. **Chatbot → kritéria.** Claude s nástroji: `navrhni_kriteria`, `spust_kolo`, `vysvetli_vyrazeni`, `napis_osloveni`. Výstup rozhovoru je kritéria jako JSON. Citlivá kritéria odmítne už tady.
2. **Kolo 0, hledání.** Dotazy podle kritérií, tři cesty: vyhledání účtů podle slov s městem („cukrárna brno“, „brno food“), hashtagy (#brnofood), u kterých místo postu (`locationId`) ověříme souřadnicemi v Brně, a posty z konkrétních míst v Brně (místa filtrujeme podle souřadnic, ne podle textu). Volitelně populární reels ke slovu (max asi 64 na slovo, ne každé slovo je má). Na TikToku vyhledání účtů. Navíc „podobné účty“ (`relatedProfiles`, u malých účtů neověřeno) u nalezených tvůrců. Výsledek: seznam účtů, u každého odkud se vzal.
3. **Kola 1 až 3 v jedné dávce.** Profily kandidátů s posledními ~12 posty v jednom běhu actoru. Štítky spolupráce, místa ani spoluautoři v nich nejsou, takže kolo 2 bere reklamu z popisků. Štítky a místa dá až druhý běh `apify/instagram-post-scraper` v detailním režimu pro 20 až 30 účtů po kole 1 (asi 0,8 USD); ten vrátí i několik posledních komentářů. Čísla počítá kód, LLM jen třídí témata z popisků. Komentáře stahujeme až pro účty v kole 3, jen z pár posledních postů.
4. **Identita.** Stejný tvůrce na IG a TikToku (vzájemné odkazy, stejný web), fanouškovské účty, jmenovci ve zprávách.
5. **Kolo 4, hloubková prověrka.** Pro finalisty: víc postů, TikTok, YouTube, spolupráce, tvrzení vs. důkaz, cílené zprávy, skeptik. Max 2 kola dohledávání z mezer.
6. **Report a porovnání finalistů.** Viz sekce 6.

**Rozpočet běhu:** kandidátů max 60, kolo 4 max 5 finalistů. Vše cachujeme podle hashe vstupu, takže změna kritéria přepočítá kola 1 až 3 během sekund bez nového stahování. V logu je u každého kroku jméno actoru a „živě“ nebo „z cache“.

**Cena běhu** (ceníky Apify k 8. 10. 2026, Free plán, rozpis v [apify-pro-krystofa.md](apify-pro-krystofa.md)): jádro na Instagramu vyjde asi na 2,8 USD (hledání včetně míst asi 1,5 USD, 60 profilů 0,16 USD, druhý běh postů pro kola 2 a 3 asi 0,8 USD, kolo 4 asi 0,3 USD). Plný běh i s TikTokem, komentáři, Meta Branded Content, zprávami a YouTube stojí asi 6 až 7 USD, tedy víc než měsíční kredit 5 USD. Free plán u hashtagů vrací jen první stránku a jen 15 nejnovějších komentářů na post. Na vývoj a demo počítat se Starter plánem (19 USD měsíčně), pokud nedostaneme kredity.

## 5. Zdroje a Apify actory

Pravidlo zadání: nepsat scraper, který už actor umí. Podmínky Meta zakazují automatický sběr bez svolení, od 1/2025 výslovně i bez přihlášení ([Meta, čl. 3.2.3](https://www.facebook.com/legal/terms?locale=en_US), [Instagram](https://help.instagram.com/581066165581870)). TikTok zakazuje automatickou extrakci bez písemného souhlasu ([podmínky EEA, 7/2026](https://www.tiktok.com/legal/page/eea/terms-of-service/en)). Zda to váže nepřihlášené, je sporné (Meta v. Bright Data, USA 2024, [rozhodnutí](https://storage.courtlistener.com/recap/gov.uscourts.cand.406956/gov.uscourts.cand.406956.181.0_1.pdf)). Sami nic nescrapujeme a nepřihlašujeme se: veřejná data bereme přes hotové Apify actory, jak chce zadání, a veřejnou Meta Ad Library (Branded Content) čteme taky přes actor. Netvrdíme, že je to v souladu s podmínkami Meta.

| Potřeba | Actor | Poznámka |
|---|---|---|
| Hledání účtů na IG | `apify/instagram-search-scraper` (`search`, `searchType: user`, `searchLimit`) | Vrací rovnou profily i s posledními posty (bez místa u postů). Max 250 na dotaz, reálně méně. `searchType` vždy nastavit, výchozí je `place`. Bez filtru na město, takže město patří do dotazu („cukrárna brno“). Podle README výsledky pocházejí z Googlu, Facebook Ads a Threads (pole `searchSource`); volitelně `liveSearch` = živé vyhledávání Instagramu. |
| Hledání přes hashtagy | `apify/instagram-hashtag-scraper` (`hashtags`, `resultsType`, `resultsLimit`) | Vrací posty (ne profily) s `ownerUsername`, `locationName` a `locationId`. Místo v Brně poznáme podle `locationId` přeloženého na souřadnice, `locationName` je často jen název podniku a mnoho postů místo nemá. Posty seskupíme podle autora. Jen nejnovější posty, jeden typ obsahu na běh. |
| Hledání podle míst | `apify/instagram-search-scraper` (`searchType: place`) → `apify/instagram-scraper` s URL místa | Místa v Brně (filtr podle `lat`/`lng`, ne textu) → `location_id` → posty z místa → autoři. URL místa vrací podle README položku místa s vnořenými `posts[].username`, ne posty s `ownerUsername`; parser na oba tvary. Komunitní alternativa: `apidojo/instagram-location-scraper` (levná, na Free jen demo režim: 5 běhů měsíčně × 10 položek). |
| Hledání na TikToku | `clockworks/tiktok-scraper` (`searchQueries`, `searchSection: /user`, `maxProfilesPerQuery`, `resultsPerPage`, `proxyCountryCode: CZ`) | `resultsPerPage` má výchozí 1, vždy nastavit. CZ je placený doplněk (+1,30 USD za 1000 výsledků). U videí `textLanguage` (jazyk popisku) a `locationCreated` (země vzniku); město jen u videí s označeným místem (`locationMeta`, u českých neověřeno). |
| Profily + posledních ~12 postů | `apify/instagram-profile-scraper` | 50 účtů v jednom běhu. Bio, sledující, `businessCategoryName`, `private`, `relatedProfiles` (podobné účty, u malých účtů neověřeno), `latestPosts` (popisek, lajky, komentáře, typ, reel = `productType: clips`, hashtagy, zmínky, připnuté `isPinned`). Místo u postů, štítek spolupráce ani `coauthorProducers` tu nejsou. Doplněk „About“ (země, datum založení, počet změn jména) je podle schématu jen pro placený účet. |
| Profil TikTok | `clockworks/tiktok-profile-scraper` | Sledující, statistiky videí. `resultsPerPage` má výchozí 100, nastavit 12. `authorMeta.region` je ve veřejných datech TikToku dnes pravděpodobně prázdné (neověřeno). |
| Víc postů (kolo 4, volitelně kola 2 a 3) | `apify/instagram-post-scraper` | Popisky, hashtagy, zmínky, `coauthorProducers`, `locationName`. S `dataDetailLevel: detailedData` i `paidPartnership` a `sponsors` (štítek placeného partnerství, na českých postech neověřeno) a `latestComments`. `dataDetailLevel` vždy uvést. `isSponsored` je od 12/2025 mrtvé (vždy false). |
| Komentáře (kolo 3) | `apify/instagram-comment-scraper` | URL postů na vstupu, bez loginu. Free: 15 nejnovějších komentářů na post, bez odpovědí. Jen pro jazyk a podíl obecných komentářů; výstup jména komentujících obsahuje, mažeme je při načtení. |
| TikTok štítky | `clockworks/tiktok-scraper` | `isSponsored` = placená spolupráce (chybějící = nevíme), `isAd` = propagovaná reklama, ne spolupráce. `authorMeta.isUnderAge18` je pravděpodobně vždy prázdné: vyřadit jen při `true`, prázdné = věk neznáme. Chybové položky (`errorCode`) odfiltrovat. |
| YouTube | `streamers/youtube-scraper` | `isPaidContent` = štítek „Includes paid promotion“; jen `true` je důkaz. Kanály podle země hledat neumí, kanál vezmeme z odkazů v bio. |
| Placené spolupráce | `apify/brand-collaboration-scraper` (`startUrls`, `resultsLimit`, `onlyPostsNewerThan`) | Oficiální Apify actor, zdroj veřejná Meta Ad Library (Branded Content). Jen posty se štítkem Placené partnerství od 17. 8. 2023. Bez přihlášení knihovna české spolupráce eviduje, ale nezobrazila je (neověřeno, jestli je vrátí actor). [Hotový recept](https://raw.githubusercontent.com/apify/awesome-skills/main/skills/apify-influencer-brand-collabs/SKILL.md). |
| Zprávy | `data_xplorer/google-news-scraper-fast` | Komunitní actor. `keywords`, `region_language: CZ:cs`, `timeframe: 1y` (výchozí 1h nic nenajde), `maxArticles: 10`, `decodeUrls: true`. Jen cílené dotazy. |

Všechny actory potřebují jen Apify token, žádný login na Instagram ani TikTok. Ověřeno na stránkách actorů 8. 10. 2026; výstupy skutečných běhů ověříme v prvních 45 minutách stavění. Přesné vstupy, výstupy a testy: [apify-pro-krystofa.md](apify-pro-krystofa.md).

## 6. Výstup

**Nástěnka s trychtýřem:** kola, počítadla „vstoupilo 48 → zůstalo 22“, karty kandidátů, vyřazené s důvodem.

**Karta kandidáta:** typ obsahu (graf témat, formát, frekvence), publikum (interakce, jazyk komentářů, lokální signály, signály pravosti), kritéria splněno / nesplněno / nejde ověřit se zdrojem. Žádné celkové skóre.

**Report finalisty** (ILUSTRACE, tvůrce je smyšlený):

| Tvrzení (kde a kdy) | Důkaz | Stav | Jistota |
|---|---|---|---|
| „Exkluzivní ambasador značky A“ (IG bio, 1. 10. 2026) | 2 posty se spoluprací s konkurenční pekárnou B, 9. 9. a 21. 9. 2026 | Nesoulad se záznamem | vysoká (vlastní posty) |
| „Recenze, nikdo mi neplatí“ (post 12. 9. 2026) | V popisu slevový kód a affiliate odkaz. Označení spolupráce jsme nenašli. | Nedoloženo, otázka | střední |
| „Komunita 120 tisíc“ (bio) | Medián interakcí 1,1 % sledujících za 24 postů, 38 % komentářů jen emoji | Signál, ne verdikt | nízká |

Dál v reportu: časová osa spoluprací (konkurenti zvýraznění), komerční nasycenost, pracovní zprávy (obvinění vs. potvrzeno), otázky na první schůzku, koncept oslovení (NEODESLÁNO, jen Kopírovat), co jsme nekontrolovali a proč, panel identity. Barvy: zelená = fakt, oranžová = inference, šedá = mezera.

**Porovnání finalistů:** vedle sebe podle kritérií, řazení jen podle kritéria, které vybere majitel.

## 7. Jiný cíl = jiný výsledek

Stejný seznam kandidátů, jiná firma:

| | Pekárna v Brně | Fitness studio v Brně |
|---|---|---|
| Typ obsahu | jídlo, recepty, lokální tipy | sport, cvičení, lokální tipy |
| Publikum | rodiny a mladí, čeština, Brno | mladí aktivní, čeština, Brno |
| Konkurenti | jiné pekárny a řetězce | jiná studia a fitness aplikace |
| Výsledek | jiní finalisté, jiná vyřazení | jiní finalisté, jiná vyřazení |
| Hloubková prověrka | spolupráce s pekárnami, recenze jídla | spolupráce s doplňky stravy a studii |

Ve videu: kdo vypadl jen u jednoho cíle a proč. A u společného finalisty jiné nálezy v reportu.

## 8. Demo (90 s)

| s | Obrazovka | Komentář |
|---|---|---|
| 0–8 | Majitel pekárny před telefonem | „Chci spolupracovat s influencerem, ale nevím s kým.“ |
| 8–25 | Chat: 4 otázky → kritéria s vysvětlením. Majitel zkusí „jen věřící“, chatbot odmítne | „Chatbot převede firmu na kritéria. Co by znamenalo soudit víru nebo názory, odmítne.“ |
| 25–45 | Trychtýř živě: 48 → 22 → 11 → 5, karty padají s důvody (pro nahrávání backend s `MOCK_LATENCY=0.8`, jinak kola doběhnou za ~1 s) | „Každé vyřazení má kolo, důvod a zdroj.“ |
| 45–62 | Report finalisty: časová osa spoluprací, nesoulad s exkluzivitou | „Vlevo co tvrdí, vpravo co ukazují jeho posty.“ |
| 62–76 | Změna cíle na fitness studio | „Jiná firma, jiní finalisté. Data z cache, přepočet za sekundy.“ |
| 76–84 | Koncept oslovení NEODESLÁNO, otázky na schůzku | „Rozhoduje majitel. My ukážeme důkazy.“ |
| 84–90 | Validace a limity | Jen čísla, která opravdu naměříme. |

**Živě vs. cache:** živě ukážeme rozhovor, přepočet kol a změnu cíle. Stahování je z cache a je to na obrazovce napsané.

**Ochrana lidí ve videu:** v trychtýři budou skuteční tvůrci. Jména vyřazených účtů ve videu rozmažeme. Hloubkovou prověrku ukážeme na tvůrci, který dá souhlas, nebo na členovi týmu na jeho skutečných profilech. Nové účty ani falešné posty nezakládat. Ochrana osobnosti: § 81 až 87 občanského zákoníku, zejména § 85 (rozšiřování podoby jen se svolením) a § 87 (svolení jde odvolat) ([text](https://www.zakonyprolidi.cz/cs/2012-89)).

## 9. Validace (co stihneme za noc)

1. **Hledání:** u 30 nalezených účtů ručně ověřit, jestli opravdu sedí na zadání (např. lokální tvůrce o jídle).
2. **Typ obsahu:** u 50 postů ručně určit téma a porovnat s LLM.
3. **Jazyk komentářů:** u 100 komentářů porovnat detekci jazyka s ruční kontrolou.
4. **Vyřazení:** u 20 vyřazených účtů ručně zkontrolovat, jestli důvod sedí.
5. **Spolupráce a označování:** u 3 finalistů ručně spočítat spolupráce a označení za 90 dní.
6. **Citlivý filtr:** 20 ručně vybraných citlivých položek, kolik jich filtr zachytil. Plus 10 citlivých kritérií v chatu, kolik jich chatbot odmítl.
7. **Citace:** automaticky u všech tvrzení kontrolujeme, že citovaný text na URL opravdu je.

Do videa a README dáme jen čísla, která opravdu naměříme, i selhání.

## 10. Pravidla a jak je plníme

| Pravidlo | Jak |
|---|---|
| Jen veřejná data | Veřejné profily, veřejná Meta Ad Library (Branded Content) čtená přes Apify actor, zprávy. Žádný login. Sami žádnou CAPTCHA neřešíme a vlastní scraper nepíšeme, používáme jen actory udržované Apify (ty si podle changelogů blokace řeší samy). Login zdi a blokace (`PROFILE_EMPTY`, `AGE_RESTRICTED`) jsou v reportu mezera. Soukromý účet v kole 1 ven. |
| Žádné odvozování čl. 9 | Chatbot odmítá citlivá kritéria; žádné „pohledy“; o publiku žádný věk, pohlaví ani původ; citlivý filtr před uložením; počet vynechaných v reportu. Trestní věci ani pokuty za správní delikty nebereme (čl. 10, C-439/19). |
| Žádné skóre osoby | Kritéria splněno / nesplněno se zdrojem, žádné celkové číslo ani „nejlepší“. Řazení jen podle kritéria majitele. Rozhoduje člověk. Jako produkt by podle návrhu pokynů Komise (19. 5. 2026, příklad hledání kontraktorů na sociálních sítích) šlo o vysoce rizikový systém podle přílohy III bodu 4 písm. a) AI Actu, i když rozhoduje člověk ([návrh pokynů](https://digital-strategy.ec.europa.eu/en/library/draft-commission-guidelines-classification-high-risk-ai-systems)). Povinnosti platí od 2. 12. 2027 ([nařízení 2026/1744](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32026R1744)), hackathonový prototyp není uveden na trh. |
| Zdroj u každého tvrzení | Kritéria i tvrzení mají URL, citaci a datum. |
| Fakt vs. inference, mezery | Barvy, inference cituje fakta, sekce „Co jsme nekontrolovali“. |
| Jiný cíl = jiný obsah | Jiná kritéria, jiná vyřazení, jiní finalisté, jiné nálezy (sekce 7). |
| Jmenovci | Panel identity: stejný tvůrce napříč sítěmi, fanouškovské účty, jmenovci ve zprávách. |
| Outreach neodeslat | Koncept oslovení jen s tlačítkem Kopírovat. |
| Nezletilí | Spolehlivý údaj o věku ve veřejných datech není (IG pole věku nemá, TikTok `isUnderAge18` je pravděpodobně prázdné). Výslovný věk pod 18 v bio nebo `isUnderAge18: true` = vyřazení v kole 1, data se neukládají. Finalista bez potvrzené plnoletosti nejde do reportu bez ověření majitelem. |
| Minimum dat | U vyřazených jen jméno účtu a důvod. `purge` smaže cache, výstupy LLM a data z Apify běhů hned po vyhlášení výsledků. |
| Živý běh | Aspoň jeden běh živě, cache je na obrazovce označená. |

## 11. Originalita: buďme upřímní

**Co existuje:**
- **Přímo na Apify:** `apify/influencer-discovery-agent`, vlastní actor Apify. Z popisu v přirozeném jazyce najde tvůrce, jen na TikToku (max asi 50 profilů na běh), a dá jim AI skóre vhodnosti 0 až 1. Vstup na lokalitu nemá, vrací jen kód země. 100 USD za 1000 profilů. Porota ho skoro jistě zná, musíme ho v pitchi zmínit sami. Bližší konkurent je `hypebridge/influencer-discovery-agent-instagram-tiktok`: brief v přirozeném jazyce, Instagram i TikTok, pole `location` přijme i město, výstup skóre 0 až 10 ([Apify](https://apify.com/hypebridge/influencer-discovery-agent-instagram-tiktok)). Dál `influship/influencer-search` (jen Instagram, filtry na sledující a interakce, lokalita jen v textu dotazu, skóre shody 0 až 1) a `alizarin_refrigerator-owner/influencer-discovery---find-influencers-across-social-platforms` (pole `locations` s městy, 5 sítí, samo rozesílá e-maily). Datovou část našich kol 1 až 3 popisuje i oficiální recept Apify ([influencer vetting](https://github.com/apify/agent-skills/blob/main/skills/apify-ultimate-scraper/references/workflows/influencer-vetting.md)).
- **Placené služby:** Modash (380 mil.+ profilů nad 1 000 sledujících, lokalita tvůrce i publika až na úroveň města na IG, veřejný žebříček [Top 20 Brno](https://www.modash.io/find-influencers/czech-republic/brno), od 199 USD měsíčně při ročním placení, 299 USD při měsíčním, [ceník](https://www.modash.io/pricing)), HypeAuditor (filtr lokality publika až 3 země, v Discovery i města, „Audience Quality Score“ 1 až 100, [AI Scout](https://help.hypeauditor.com/en/articles/15693186-ai-scout) z briefu v chatu vybere až 50 tvůrců s vysvětlením), Heepsy (i free plán, lokalita až na úroveň města, [hledání](https://www.heepsy.com/influencer-search)), Kolsquare (Compliance Score hodnotí, jak IG posty za 3 měsíce označují reklamu, [blog](https://www.kolsquare.com/en/blog/kolsquare-launches-compliance-score-feature)), Influee (globální marketplace z USA, pokrývá i ČR, od 229 USD měsíčně, vlastní skóre tvůrce). Emplifi (americká firma, vznikla z českého Socialbakers) má enterprise modul na tvůrce: 30 mil.+ tvůrců, AI skóre shody se značkou ([Emplifi](https://emplifi.io/product/influencer-management/)).
- **Brand safety:** Viral Nation (prodává i „evidence packet“ s důvody), Phyllo, Captiv8, Ferretly, Upfluence, šablona n8n „Instagram přes Apify + LLM skóre“ ([#11808](https://n8n.io/workflows/11808-influencer-brand-safety-auditor-with-engagement-analysis/)).

**Čím se lišíme:**
1. Pro laika: chatbot z rozhovoru udělá výslovná kritéria, která majitel vidí, upraví a může vetovat, a citlivá kritéria odmítne. Chat, který z briefu udělá seznam tvůrců, už má i HypeAuditor (AI Scout).
2. Průhledný trychtýř místo AI čísla: vratná kola podle kritérií majitele, každé vyřazení má kolo, důvod a zdroj. Všichni konkurenti, které jsme našli, dávají souhrnné skóre (Apify agent 0 až 1, hypebridge 0 až 10, HypeAuditor 1 až 100).
3. Lokalita doložená důkazem: tvrzení „tvoří v Brně“ odkazuje na konkrétní posty s místem v Brně nebo na bio, ne na odhad z databáze. Hledání na úrovni města samo unikátní není (Modash, Heepsy, hypebridge).
4. Publikum z veřejných signálů (jazyk komentářů, lokalita, pravost) s poctivě přiznanými mezerami.
5. Hloubková prověrka finalistů jako pár tvrzení + důkaz, ne flag ani skóre. Kontrola označování reklamy sama nová není (Kolsquare); nové je ukázat konkrétní posty a vysvětlit majiteli jeho odpovědnost podle českých pravidel.
6. Chatbot odmítá diskriminační kritéria. Konkurence (HypeAuditor, Phyllo) naopak flaguje „politiku“, HypeAuditor i náboženství ([HypeAuditor](https://hypeauditor.com/solutions-for/brands/)).
7. Platba za běh v jednotkách dolarů místo předplatného SaaS. Proti agentům na Apify (0,10 až 0,15 USD za profil) cenou nevyhráváme.

Poctivá věta do pitche: „Vyhledávače tvůrců existují, i na Apify. My jsme průvodce pro majitele pekárny v Brně, který ukáže, proč kdo vypadl, a ověří, co finalisté tvrdí.“

## 12. Rizika a co škrtnout

- **Kvalita hledání:** hashtagy jsou zašuměné (firmy, zahraniční účty, agregátory) a vyhledávání účtů nemá filtr na město. Kola 1 a 2 to musí odfiltrovat. Firemní účty: `businessCategoryName` přijde jako text s čárkami i s „None“ (např. „None,Candy Store“) a kategorii mívají i tvůrci, takže sám o sobě nikoho nevyřazuje. Záloha: majitel vloží vlastní seznam.
- **Free plán Apify:** u hashtagů jen první stránka, 15 nejnovějších komentářů na post, `apidojo/instagram-location-scraper` jen demo režim (5 běhů měsíčně × 10 položek), doplněk About a odpovědi na komentáře jen placeně. Plný běh (asi 6 až 7 USD) se do kreditu 5 USD nevejde. Na demo potřebujeme placený plán nebo kredity.
- **Čas a cena:** 60 profilů v jedné dávce, komentáře jen pro zbylé, kolo 4 max 5 finalistů. Cache je nutnost.
- **Publikum je jen odhad.** Jazyk komentářů a místa u postů nejsou demografie. Napsat to do reportu.
- **Meta Branded Content možná české spolupráce nevrátí.** Knihovna je celosvětová od 17. 8. 2023, ale jen pro posty se štítkem Placené partnerství. Bez přihlášení české spolupráce eviduje, ale nezobrazila je (Rohlík.cz 10, Notino.cz 4, Alza 2 výsledky, 0 řádků; Nike 17 z 21, [Ad Library](https://www.facebook.com/ads/library/branded_content/)). Test v 0:00 až 0:45: rohlik.cz a kontrolně nike; když česká vrátí 0, škrtáme hned. Prázdný výsledek = „nenalezeno v knihovně Meta“, ne „nemá spolupráce“. Záloha: štítky na IG (`paidPartnership`), TikToku a YouTube, hashtagy, slevové kódy.
- **Skuteční lidé ve veřejném videu:** rozmazat vyřazené, prověrka jen se souhlasem.
- **Škrtat v pořadí:** YouTube → koncept oslovení → Meta Branded Content → zprávy v kole 4 → změna cíle jako samostatná obrazovka. Chatbot, trychtýř a karta kandidáta neškrtáme nikdy.

## 13. Harmonogram (časy od startu stavění)

**Role:** A: actory (hledání, profily v dávce, komentáře, TikTok), cache. B: chatbot s nástroji, logika kol, třídění témat, jazyk komentářů, hloubková prověrka, citlivý filtr. C: od začátku UI nad statickým JSON (chat + nástěnka, trychtýř, karty, report), lov demo tvůrce, validace, video. Sólo: jen Instagram, kola 1 až 3 a jednoduchá prověrka, UI ve Streamlitu.

| Kdy | Co | Hotovo, když |
|---|---|---|
| 0:00–0:45 | **Test zdrojů** | search-scraper („cukrárna brno“), hashtag-scraper s `locationId`, profile-scraper na 50 účtech, post-scraper s `detailedData` (`paidPartnership`), comment-scraper, tiktok-scraper s CZ i bez, brand-collaboration-scraper (rohlik.cz + nike). Co nevrátí data, škrtáme. Pořadí a vstupy: [apify-pro-krystofa.md](apify-pro-krystofa.md). |
| 0:45–2:00 | Kostra + demo tvůrce | repo, schéma (Kandidát, Kritérium, Kolo, Tvrzení, Důkaz), cache. Najít tvůrce se souhlasem. |
| 1:00–3:00 | Hledání + kola 1 a 2 | seznam účtů, základ, témata obsahu |
| 3:00–4:30 | Chatbot + kolo 3 | rozhovor → kritéria JSON, publikum, odmítání citlivých kritérií |
| 4:30–6:00 | Kolo 4 | spolupráce, tvrzení vs. důkaz, zprávy |
| **6:00** | **Celý běh v hotovém UI** | commit, main se od teď nerozbíjí |
| 6:00–7:30 | Identita, skeptik, vracení kandidátů | panel identity, důvody vyřazení |
| 7:30–8:30 | Změna cíle, porovnání finalistů, koncept oslovení | dva cíle se liší finalisty |
| 8:30–9:30 | Validace + README | čísla, selhání, limity |
| 9:30–konec | Video + odevzdání | max 90 s, cache označená |

## 14. Otázky na mentory

1. Je na hledání českých tvůrců lepší `instagram-search-scraper` (účty), nebo hashtagy s filtrem na místo? A jak se díváte na `influencer-discovery-agent` a `hypebridge/influencer-discovery-agent-instagram-tiktok`, když děláme něco podobného?
2. Vrací `brand-collaboration-scraper` české spolupráce, které Meta Ad Library bez přihlášení nezobrazí?
3. Máme na hackathon kredity? Jádro běhu na Instagramu odhadujeme na 2,8 USD, plný běh na 6 až 7 USD, s vývojem a testy desítky běhů.
4. Stačí ve veřejném videu rozmazat vyřazené účty a prověrku ukázat jen se souhlasem?
