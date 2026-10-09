# Kostra aplikace: obrazovky a funkce

Ověření faktů k 8. 10. 2026: [overeni-2026-10-08.md](overeni-2026-10-08.md). Actory a data pro Kryštofa: [apify-pro-krystofa.md](apify-pro-krystofa.md).

Krátká verze pro design (verze 6, 8. 10. 2026). Detaily jsou v [brand-fit-cz.md](brand-fit-cz.md).

**Jedna věta:** Majitel malé firmy si s chatbotem řekne, koho hledá. Aplikace najde kandidáty mezi tvůrci, v několika kolech je vyřazuje podle obsahu a publika a finalisty prověří do hloubky. U každého kroku je vidět proč a podle jakého zdroje.

**Pro koho:** majitel pekárny, kavárny nebo e-shopu, který neví, jakého tvůrce vybrat a podle čeho. Druhotně marketingové a PR agentury.

## Rozložení: chatbot + nástěnka

Jedna obrazovka, dvě části:
- **Vlevo chatbot** (průvodce). Ptá se, vysvětluje, navrhuje kritéria, spouští kola, odpovídá „proč vypadl X?“.
- **Vpravo nástěnka** (co se děje). Kritéria, trychtýř s koly, karty kandidátů, finalisté.

Na mobilu se přepíná záložkami Chat / Nástěnka.

## 1. Rozhovor na začátku

Chatbot vede laika krok za krokem:
- „Co prodáváte a kde?“ → pekárna, Brno
- „Komu chcete prodávat?“ → rodiny, mladí lidé v Brně
- „Co má kampaň udělat?“ → víc lidí v prodejně, nový produkt
- „Kolik zhruba můžete dát?“ → orientačně, kvůli velikosti tvůrce
- „Máte konkurenty, se kterými by tvůrce neměl spolupracovat?“

Pak navrhne **kritéria** jednoduchou řečí a u každého řekne proč: „Pro pekárnu v Brně dává smysl lokální tvůrce o jídle s 5 až 50 tisíci sledujícími. Menší tvůrci mívají bližší vztah s publikem a jsou dostupnější.“

**Odmítnutí:** když majitel chce kritérium podle víry, politiky, zdraví, sexuality nebo původu, chatbot ho zdvořile odmítne a vysvětlí proč. Je to dobrý moment do videa.

## 2. Panel kritérií

Štítky, které jde upravit klikem i v chatu:
- **Typ obsahu:** jídlo, recepty, lokální tipy, rodina, lifestyle. Formát: reels, fotky, videa.
- **Publikum:** jazyk (čeština), lokalita (Brno a okolí), velikost (5 až 50 tisíc), aktivita publika (minimální interakce).
- **Spolupráce:** žádné spolupráce s konkurencí, označuje reklamu, ne víc než X % postů jako reklama.
- **Šedé štítky** s vysvětlením: kritéria, která nekontrolujeme (víra, politika, „hodnoty“ osoby).

## 3. Trychtýř s vyřazovacími koly

Hlavní prvek nástěnky. Kandidáti jsou karty, které postupně padají stranou.

| Kolo | Co se kontroluje | Typicky zůstane |
|---|---|---|
| 0. Hledání | hashtagy, klíčová slova a místa → seznam účtů | 40–60 |
| 1. Základ | veřejný účet, čeština, velikost, aktivní za 30 dní | 20–30 |
| 2. Obsah | o čem tvoří, podíl relevantních postů, formát, frekvence | 10–15 |
| 3. Publikum | interakce, jazyk komentářů, lokální signály, pravost publika | 5–8 |
| 4. Hloubková prověrka | spolupráce, konkurence, označování reklamy, pracovní zprávy | 3–5 finalistů |

- U každého kola počítadlo „vstoupilo 48 → zůstalo 22“.
- **Vyřazená karta** ukazuje kolo a důvod se zdrojem: „Kolo 2: jen 2 z 12 postů jsou o jídle“.
- Když data chybí (prázdný profil, login zeď, nic v knihovně Meta), kandidát nevypadne: kritérium dostane „nejde ověřit“.
- Kliknutím na vyřazenou kartu jde kandidáta vrátit zpět („tohle kritérium pro něj neplatí“).
- Kolo 4 je dražší, chatbot se před ním zeptá: „Prověřit 6 finalistů do hloubky?“

## 4. Karta kandidáta

- Profilovka, jméno účtu, sledující, kategorie, odkaz.
- **Typ obsahu:** graf témat (např. 60 % jídlo, 25 % rodina, 15 % ostatní), formát, frekvence postů.
- **Publikum:** medián veřejně viditelných interakcí na post (lajky a komentáře), interakce vůči sledujícím, podíl komentářů v češtině, lokální signály (místa v postech, zmínky Brna), signály pravosti (např. „38 % komentářů jen emoji“). Popisek: „odhad z veřejných dat, ne demografie“.
- **Kritéria:** u každého splněno / nesplněno / nejde ověřit, se zdrojem. **Žádné celkové skóre.**

## 5. Report finalisty (kolo 4)

- **Časová osa spoluprací:** značka, datum, platforma, označeno ano/ne. Konkurenti zvýraznění.
- **Karta tvrzení:** pár „co tvůrce tvrdí“ ↔ „co ukazují jeho posty“, stav (Doloženo / Nesoulad se záznamem / Nedoloženo / Nejde ověřit), jistota, zdroj a datum.
- **Komerční nasycenost:** kolik % postů je reklama.
- **Pracovní zprávy:** článek, médium, datum, štítek „obvinění“ nebo „potvrzeno“.
- **Otázky na první schůzku** s tvůrcem.
- **Koncept oslovení:** štítek NEODESLÁNO, jen tlačítko Kopírovat.
- **Co jsme nekontrolovali a proč.**
- **Barvy:** zelená = fakt se zdrojem, oranžová = inference, šedá = mezera.

## 6. Porovnání finalistů

- Finalisté vedle sebe podle kritérií, každé políčko rozkliknutelné na zdroj.
- Řazení jen podle kritéria, které si vybere uživatel (např. podle interakcí). Žádné „nejlepší tvůrce“, rozhoduje majitel.

## 7. Jiný cíl = jiný výsledek

- Tlačítko „Změnit cíl“: stejný seznam kandidátů, jiná firma nebo kampaň (pekárna vs. fitness studio).
- Jiná kritéria → jiná vyřazení → jiní finalisté. Zobrazit rozdíl: kdo vypadl jen u jednoho cíle a proč.

## 8. Živý běh

- Kroky a log se zdroji: „Instagram: 48 účtů“, „TikTok: 20 účtů“. Štítek **živě** nebo **z cache**.
- Chatbot průběžně komentuje: „Vyřadil jsem 14 účtů, které píšou hlavně anglicky.“
- **Počítadlo citlivého filtru:** „vynecháno 4 položky (citlivé kategorie)“.

## 9. Bonus, jen když zbyde čas

- **Hlasový průvodce (ElevenLabs):** chatbot mluví, nebo 30 s shrnutí finalistů.

## Pravidla pro design

- Vyřazení je vždy **kritérium + důvod + zdroj**, ne „nevhodný člověk“.
- Žádné celkové skóre, semafory ani „Nedoporučeno“. Rozhoduje majitel.
- Nic o názorech, soukromí, jídelníčku tvůrce ani fotkách od jiných lidí.
- O publiku jen odhady z veřejných dat. Věk, pohlaví a původ publika neodhadujeme.
- Neutrální slova: „nesplňuje kritérium“, „nesoulad se záznamem“, „obvinění“.
- Každý údaj jde rozkliknout na zdroj.
- Funguje i na úzké obrazovce.

## Co se děje na pozadí (pro vývoj)

| Funkce | Co dělá |
|---|---|
| Chatbot | Claude s nástroji: navrhni kritéria, spusť kolo, vysvětli vyřazení, napiš koncept oslovení |
| Hledání | hashtagy, klíčová slova a místa na IG a TikToku → seznam účtů |
| Kola 1 až 3 | profily a posledních ~12 postů v jedné dávce, výpočty v kódu, LLM jen na témata obsahu. Štítky spolupráce a místa u postů v profilu nejsou: reklama z popisků, případně druhý běh post-scraperu |
| Citlivý filtr | zahodí citlivá kritéria i citlivý obsah před uložením |
| Kolo 4 | hloubková prověrka finalistů: spolupráce, tvrzení vs. důkaz, zprávy |
| Identita | jmenovci, fanouškovské účty, stejný tvůrce na IG a TikToku |
| Cache + živý stream | kola z cache v řádu sekund, živě jen nové dotazy |
| Smazat data | smaže cache, výstupy LLM a data z Apify |
