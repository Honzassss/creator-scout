# Směr designu: Creator Scout

Stav k 9. 10. 2026. Platí pro frontend v `frontend/`.
Tvrdá pravidla z `docs/kostra-aplikace-cz.md` (Pravidla pro design) a z `docs/architecture.md` (§ 9 a 10) mají přednost před vším, co je tady.

Shrnutí: koncept „stůl s důkazy“ necháváme. Papír, inkoust a vyhrazené barvy pro důkazy zůstávají. Ubereme velikosti písma, rámečky a barvy. Srovnáme, co je na řadě. Opravíme normy. Nezačínáme znovu.

Snímky „před“ jsou v `docs/design/pred/`. Inspirace je v `docs/design/inspirace/`. Cesty níže jsou relativní k `docs/design/`.

---

## 1. Diagnóza současného stavu

Koncept je dobrý, chybuje provedení. Je tu moc velikostí písma a moc rámečků. Není jasné, co je další krok. Několik míst ve videu vypadá rozbitě.

### Co funguje a necháváme

- Pruhovaný pruh MOCK a razítko MOCK ve spisu (`pred/04-funnel-desktop-light.png`, `pred/07-drawer-top-desktop-light.png`).
- Každé vyřazení má kolo, kritérium a zdroj (`pred/05-eliminated-desktop-light.png`).
- Odmítnutý požadavek v řádku „Nekontrolujeme“ (`pred/03-criteria-desktop-light.png`).
- Přepínač „Rozmazat vyřazené“ (`pred/13-blur-desktop-light.png`).
- Časová osa spoluprací. Štítek „Neodesláno“ u konceptu oslovení.
- Fakt, odhad a mezera mají vždy i textový štítek. Mezera má navíc čárkovaný okraj.
- Světlý motiv Papír je klidnější než tmavý. Video budeme točit v něm.

### Co nefunguje

| # | Problém | Kde to vidíme | Proč to vadí |
|---|---|---|---|
| 1 | Další krok se ztrácí. „Prověřit 5 do hloubky“ je malé tlačítko dole ve sloupci kola 4. Lišta Živý běh ho umí zakrýt. „Změnit cíl“ je jediné plné tlačítko už v prázdném stavu. | `pred/01-empty-desktop-light.png`, `pred/04-funnel-desktop-light.png` | Divák videa neví, kam se dívat. Klik na tlačítko pod lištou nic neudělá. |
| 2 | Po spuštění zůstává nahoře panel kritérií (asi 400 px). Výsledky jsou pod okrajem. Po změně cíle je trychtýř až kolem y = 700. | `pred/06-vetting-done-top-desktop-light.png`, `pred/11-goal-diff-desktop-full-light.png` | Hlavní obsah není vidět. |
| 3 | Pointa příběhu je schovaná. Kuba spolupracuje s konkurentem, kterého majitel sám jmenoval. Na kartě je z toho „✕ Bez spolupráce s kon…“. Ve spisu je rozpor až v sekci III, asi 2000 px pod začátkem. | `pred/06-vetting-done-desktop-light.png`, `pred/07-drawer-top-desktop-light.png`, `pred/08-drawer-claims-desktop-light.png` | Nejsilnější moment dema nikdo nevidí. |
| 4 | Průvodce v půlce zmlkne. Po prověrce i po změně cíle je poslední zpráva pořád „Prověřit 5 finalistů do hloubky?“. | `pred/06-vetting-done-desktop-light.png`, `pred/14-mobile-chat-light.png` | Levá třetina obrazovky stojí celou druhou půlku videa. |
| 5 | Značky ✓ a ✕ vypadají jako zaškrtávací pole. Ve světlém motivu je ✕ plný černý čtverec. | `pred/06-vetting-done-desktop-light.png`, `pred/10-compare-bottom-desktop-light.png` | Čte se jako poplach. Porušuje pravidlo neutrálních značek. |
| 6 | MOCK se rozmělnil. Každý zdrojový štítek má stejný růžový čtvereček jako MOCK. Spis zakryje pruh MOCK. Husté karty ukazují MOCK jen barvou. | `pred/09-drawer-findings-desktop-light.png`, `pred/04-funnel-desktop-full-light.png` | MOCK musí být nepřehlédnutelný. Růžová už nic neznamená. |
| 7 | Typografie je roztříštěná. Komponenty používají 20 velikostí písma od 9,5 do 30 px. Popisky 9 až 10 px ve videu 1080p nepřečtete. Serif, sans a mono se míchají i v jedné kartě. | všechny snímky | Neklid a nečitelnost. |
| 8 | Nálezy jsou moře zelené. Vidět jsou interní id (`f:followers`). Štítek „IG · 9. 10. 2026“ se opakuje pětkrát za sebou. | `pred/09-drawer-findings-desktop-light.png` | Odhady a mezery, tedy to zajímavé, se ztratí. |
| 9 | Porovnání je zeď fajfek. 72 ze 75 buněk je ✓ s větou. Rozdíly jsou až v posledních dvou řádcích. | `pred/10-compare-desktop-light.png`, `pred/10-compare-bottom-desktop-light.png` | Tabulka nic neporovnává. |
| 10 | Rozbalené vyřazené kola 1 natáhne nástěnku na 4900 px. 26 karet je ve sloupci širokém 200 px. | `pred/05-eliminated-desktop-full-light.png` | Ostatní sloupce zejí prázdnotou. |
| 11 | Po změně cíle trychtýř končí „5 → 1“. Čte se to jako „kolo 4 přežil jeden“. Ve skutečnosti jde o jednoho dříve prověřeného. | `pred/11-goal-diff-desktop-light.png` | Zavádějící číslo. |
| 12 | Vývojářské pojmy v chatu: „nástroj propose_criteria ✓“, „run_rounds ✓“. | `pred/03-criteria-desktop-light.png`, `pred/06-vetting-done-desktop-light.png` | Majitel pekárny tomu nerozumí. |
| 13 | Hlavička na mobilu má 4 řádky, asi 210 px z 812. Trychtýř je 5 sloupců vedle sebe, finalisté jsou 4 přejetí vpravo. | `pred/01-empty-mobile-light.png`, `pred/04-funnel-mobile-dark.png` | Na telefonu skoro není vidět obsah. |

### Normy (z auditu)

- axe ve světlém motivu: 37, 91 a 183 uzlů s nízkým kontrastem (prázdný stav, trychtýř, spis). Hlavní příčina jsou tokeny `--ink-3` a `--ink-4`.
- Zdrojový popover nejde ovládat klávesnicí a čtečka ho nevidí. To porušuje i naše pravidlo „každý údaj jde rozkliknout na zdroj“.
- Dialogy nedrží fokus. Pole v editoru kritérií nemají popisek.
- Karta kandidáta řekne čtečce jen „@kuba.jidlo.brno, tlačítko“.
- Čeština: v `i18n.ts` není ani jedna nezlomitelná mezera. Plurály „1 řádků“, „2 postů“.

---

## 2. Směr: klidný spis

Stůl s důkazy zůstává. Ubereme, co ruší. Zbyde papír, inkoust, jedna akční barva a tři barvy důkazů. Každá obrazovka má jednu zjevnou další akci.

### Principy

1. **Jedna další akce.** Plné tlačítko je vždy jen jedno: to, co je teď na řadě. Postup kol ukazuje stepper a pod ním jedna věta, co se právě děje.
   Inspirace: „Animated progress indicator when using Linear's import assistant“, designspells.com, https://designspells.com/spells/animated-progress-indicator-when-using-linears-import-assistant

2. **Bezbarvý stůl, barva jen pro důkaz.** Obal je jednobarevný. Papír, inkoust, tenké linky, hloubka tónem a ne stínem. Zelená, oranžová a šedá znamenají jen fakt, odhad a mezeru. Modrá je jen na akce a fokus.
   Inspirace: „Vercel style: Typeset terminal on white paper“, styles.refero.design, https://styles.refero.design/style/f24daf3a-d43f-4dec-85a9-8ac1d5148a03 a „Kobbe: calm warm-gray analytics“, details.so, https://www.details.so/inspo/kobbe-4584cb

3. **MOCK je režim, ne poznámka.** MOCK obepíná celou aplikaci rámem a pruhem. Rám je vidět i přes otevřený spis a dialog. Magenta znamená jen MOCK, nic jiného.
   Inspirace: „Incognito mode animations in Claude“, designspells.com, https://designspells.com/spells/incognito-mode-animations-in-claude

4. **Každý údaj má štítek zdroje.** Za údajem stojí malý mono štítek, třeba „IG · MOCK“ nebo „IG · 9. 10.“. Klik nebo Enter otevře zdroj s citací. V souvislém textu stačí jemné podtržení.
   Inspirace: „Answer with inline mono source chips“ (Perplexity), refero.design, https://refero.design/pages/4e086268-37b9-4104-ab13-4f8d786bde21 a „Agentwork: answers with underlined entity links“, details.so, https://www.details.so/inspo/agentwork-7c364a

5. **Práce se ukazuje jako kroky.** Průvodce i živý běh ukazují kroky prostými slovy: hledám, čtu, hotovo. Kroky jdou sbalit.
   Inspirace: „Loading animations when performing a Pro Search on Perplexity“, designspells.com, https://designspells.com/spells/loading-animations-when-performing-a-pro-search-on-perplexity a „Workflow run: collapsible steps“ (GitHub Actions), refero.design, https://refero.design/pages/6a2ab671-7af2-49fd-9fa3-151147fff32b

6. **Vyřazení je záznam, ne verdikt.** Řádek vyřazeného říká kolo, kritérium a zdroj a nabízí „Vrátit“. Značky ✓ ✕ ? jsou holé glyfy v inkoustu. Žádné skóre, žádné ničení, žádné semafory.
   Inspirace: „Archived candidates with reason and Restore“ (Wittl), refero.design, https://refero.design/pages/fd36bdf0-0f96-4a85-941e-cb3f96478ac7 a „Progress indicator animation in Linear“ (jen tvary, ne barvy), designspells.com, https://designspells.com/spells/progress-indicator-animation-in-linear

7. **Nejdřív souhrn, pak spis.** Spis začíná tím, na co se podívat, a počty faktů, odhadů a mezer. Podrobnosti jsou níž.
   Inspirace: „Company record: tabs with counts + Record Details side panel“ (Attio), refero.design, https://refero.design/pages/bcc9e9fc-c97e-404c-a925-42f1b7d51bf4 a „Criterion evidence modal“ (Parallel), refero.design, https://refero.design/pages/cdafc3c4-560e-4d35-a4ad-274c5b807fa9

---

## 3. Normy

Zavazujeme se k těmto normám:

- **WCAG 2.2, úroveň AA.**
- **Web Interface Guidelines** od Vercelu (https://vercel.com/design/guidelines).
- **ČSN 01 6910** pro českou typografii.
- **Naše tvrdá pravidla** (kapitola 3.4). Ta platí vždy.

### 3.1 WCAG 2.2 AA: co přesně platí u nás

| Kritérium | Pravidlo u nás |
|---|---|
| 1.4.3 Kontrast textu | Běžný text aspoň 4,5 : 1. Velký text (od 24 px, nebo od 18,66 px tučně) aspoň 3 : 1. Platí i pro popisky, data ve štítcích a „čeká“. `--ink-4` se na text nepoužívá nikdy. |
| 1.4.11 Netextový kontrast | Okraje polí, přepínačů a zaškrtávacích polí aspoň 3 : 1 vůči okolí. Na to je token `--field`. Značka druhu důkazu (čtvereček, levý pruh) také aspoň 3 : 1. |
| 1.4.1 Barva | MOCK, fakt, odhad, mezera i ✓ ✕ ? mají vždy i text nebo tvar. Nic se nerozlišuje jen barvou. |
| 1.3.1, 4.1.2 Struktura a jména | Nadpisy: h1 „Creator Scout“, h2 panely, h3 kola a sekce spisu. Pole mají `<label for>`. Glyf má `aria-hidden`, význam nese skrytý text. `aria-label` jen na prvku s rolí. |
| 2.1.1, 2.4.3 Klávesnice a pořadí | Všechno jde Tabem. Pořadí v DOM odpovídá pořadí na obrazovce. Dialog: fokus jde dovnitř, Tab zůstane uvnitř, Escape zavře a vrátí fokus na spouštěč. Popover zdroje se vykreslí uvnitř aktivního dialogu. |
| 2.4.7, 2.4.11 Fokus | Prstenec 2 px v akční barvě. Lepkavá lišta Živý běh nesmí zakrýt prvek s fokusem: `scroll-padding-bottom: 48px` na hlavní ploše. |
| 2.5.3 Jméno obsahuje popisek | Přístupné jméno obsahuje viditelný text. Například „Motiv: Inkoust“, ne jen „Motiv“. |
| 2.5.8 Velikost cíle | Aspoň 24 × 24 px, nebo dost volného místa kolem. Týká se zdrojových štítků, „Vrátit“, odkazů obsahu spisu a zaškrtávacích polí v prověrce. |
| 3.1.2 Jazyk částí | Anglický text má `lang="en"`. @účty, značky a „Creator Scout“ mají `translate="no"`. |
| 3.3.2 Popisky | Každé pole má viditelný popisek v češtině. Jednotka (%) je připojená přes `aria-describedby`. |
| 4.1.3 Stavové zprávy | Jedna skrytá oblast `aria-live="polite"` hlásí průběh kol, prověrky a změny cíle. Chat má `role="log"` a hlásí až hotovou zprávu. Kontejner hlášek je v DOM pořád. |
| 2.3.3 Pohyb (AAA, ale držíme) | `prefers-reduced-motion` vypne animace v CSS i plynulý posuv v JS. |

### 3.2 Web Interface Guidelines: konkrétní pravidla

- Na obrazovce je jedna primární akce. Tlačítka začínají slovesem.
- Formuláře: pole mají `name`. Pole mimo přihlášení mají `autocomplete="off"`. Číselná pole mají `inputMode="numeric"` nebo `"decimal"`. Odeslat jde Enterem. Tlačítko Odeslat není předem zakázané, chyba se ukáže až po pokusu. Zavření rozepsaného dialogu se zeptá.
- Čísla ve sloupcích a počítadlech mají `font-variant-numeric: tabular-nums`.
- Nadpisy mají `text-wrap: balance`.
- Animují se jen `transform` a `opacity`. UI do 200 ms, počítadla do 500 ms. Žádný `box-shadow` v keyframes. Žádné `transition: all`.
- Stav je v URL. `?run=` už funguje. Přidáme `?c=<id>` pro otevřený spis.
- Dotyk: `touch-action: manipulation`. `overscroll-behavior: contain` na spisu, dialogu, popoveru a chatu. Pevné prvky dole počítají s `env(safe-area-inset-bottom)`.
- `<meta name="theme-color">` pro oba motivy: `#f2ece0` a `#12141a`.
- Kopírování potvrdí krátká hláška „Zkopírováno“. Čtečka ji oznámí.
- Chybová hláška říká, co se stalo a co dál.

### 3.3 ČSN 01 6910: česká typografie

- Nezlomitelná mezera po jednopísmenných předložkách a spojkách: k, s, v, z, o, u, a, i (i velkými písmeny).
- Nezlomitelná mezera mezi číslem a jednotkou: „65 %“, „10 tis.“, „5 Kč“, „30 dní“. Také v datu („9. 10. 2026“) a mezi skupinami číslic („23 400“).
- Rozsah: pomlčka bez mezer, „5–50 tis.“, „kola 0–3“. Bez horní meze: „od 5 tis.“.
- Pomlčka ve větě: s mezerami, „Brno – Zelný trh“. Spojovník jen uvnitř slov.
- Uvozovky „…“. Výpustka jako jeden znak …
- Desetinná čárka: „2,7“. Procenta s mezerou: „65 %“.
- Znaky ≥ a ≤ mají za sebou nezlomitelnou mezeru: „≥ 40 %“, „≤ 30 dní“, „≥ 1× týdně“.
- Plurály podle čísla: 1 řádek, 2 až 4 řádky, 5 a víc řádků.
- Velké písmeno jen na začátku. Žádné Title Case. Popisky řádků začínají velkým písmenem („Nalezeno přes“).
- Měsíc na ose: „září 2026“ nebo „9/2026“, ne „září 26“.
- Provedení: jeden pomocník `csTypo()` v `translate()`, v `pick()` a v `RichText`. Projde jím i text z backendu při vykreslení. Tak se opraví i zlomy v kritériích a důvodech, aniž by se sahalo do backendu.

### 3.4 Naše tvrdá pravidla v jazyce designu

- Žádné celkové skóre, pořadí, „nejlepší“ ani semafor. Řadit jde jen podle jednoho kritéria, které vybere uživatel.
- ✓ ✕ ? jsou v inkoustu, stejně velké a stejně silné. ✕ nikdy není červené ani plné černé pole.
- Zelená, oranžová a šedá patří jen faktu, odhadu a mezeře. Nejsou ve stavech kol, v rozdílu cílů ani v tlačítkách.
- Magenta patří jen MOCK.
- Každý údaj jde otevřít na zdroj, myší i klávesnicí.
- Neutrální slova a neutrální rod: „nesplňuje kritérium“, „vyřazeno“, „postupuje dál“, „nesoulad se záznamem“.

---

## 4. Obrazovky

Id v hranatých závorkách odkazují na seznam změn v kapitole 6.

### 4.1 Rozvržení, hlavička a stav dat

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Reconnecting animation when offline in Linear | designspells.com | https://designspells.com/spells/reconnecting-animation-when-offline-in-linear | Stavový štítek v hlavičce s tooltipem, co stav znamená. |
| Incognito mode animations in Claude | designspells.com | https://designspells.com/spells/incognito-mode-animations-in-claude | Režim jako rám kolem celé aplikace a pruh s popiskem. |
| AI chat guide left, document filling in on the right (Metaview) | refero.design | https://refero.design/pages/5cb71445-d8f0-4cd9-bcc9-84c603839473 | Úzký chat vlevo, dokument vpravo se plní. Šedé linky místo spinneru. |
| Agent-at-work indicator in Paper | designspells.com | https://designspells.com/spells/agent-at-work-indicator-in-paper | Tichá značka práce u názvu kola, když průvodce něco spustí. |
| Animation when hovering on the sidebar toggle in Stripe | designspells.com | https://designspells.com/spells/animation-when-hovering-on-the-sidebar-toggle-in-stripe | Sbalení chatu do úzké lišty (P2). |

Změny:

- Hlavička má jeden řádek, nejvýš 56 px. Vlevo logo a h1 „Creator Scout“. Vpravo stavový štítek dat, „Rozmazat vyřazené“, „Změnit cíl“ jako vedlejší tlačítko a menu „⋯“ (Smazat data, Motiv, Jazyk). [P1-02]
- Stavový štítek nahradí počítadla „LIVE 0 / CACHE 0 / MOCK 1616“. Texty: „MOCK · vymyšlená data“, „Živě z Apify“, „Z cache“, „Odpojeno“. Najetí nebo fokus otevře vysvětlení: čemu věřit, počty podle původu a režim LLM. [P1-02]
- „Změnit cíl“ je vedlejší tlačítko a ukáže se až po prvním běhu. [P0-07]
- MOCK: rám 3 px v magentě kolem okna a pruh nahoře. Rám leží nad spisem i dialogem. Spis začíná pod pruhem. [P0-06]
- Pořadí na pracovní ploše: sbalená kritéria (jeden řádek), trychtýř se stepperem, porovnání, živý běh. [P0-08, P1-05]

### 4.2 Průvodce (chat) a prázdný stav

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Empty state with grouped suggestion chips (Google Bard) | refero.design | https://refero.design/pages/9c8c04e9-5f5b-41c1-92af-982737a922c0 | Pozdrav, jedna věta návodu, příklady na jedno kliknutí. |
| Wrangle: AI people-search prompt box with suggestion chips | details.so | https://www.details.so/inspo/wrangle-8f70c3 | Celá ukázková věta jako placeholder, pod polem 3 příklady. |
| Chatbox animations in Granola | designspells.com | https://designspells.com/spells/chatbox-animations-in-granola | Štítek aktuálního cíle u pole pro psaní. |
| Linear: Slack thread on the left becomes a structured issue on the right | details.so | https://www.details.so/inspo/linear-0aa2b8 | Pod zprávou tichý řádek „Navrženo 15 kritérií →“ s odkazem do pravé části. |
| Kobbe: mono tool-call line | details.so | https://www.details.so/inspo/kobbe-4584cb | Jeden mono řádek, když průvodce spustí Actor. |
| Navigate: chat FAQ with „Also asked“ pills | details.so | https://www.details.so/inspo/nvg8-xkpfhd | Rychlé odpovědi pod otázkou (závisí na backendu, viz kap. 7). |

Změny:

- Nástroje se v chatu ukazují lidsky. Místo „nástroj propose_criteria ✓“ je tichý řádek „Navrženo 15 kritérií →“, který vede na panel kritérií. Místo „run_rounds ✓“ je „Spuštěna kola 0–3 →“. Názvy nástrojů zůstávají jen v živém běhu. [P1-03]
- Průvodce nemlčí. Po dokončení prověrky přidá frontend do chatu oznámení (`chat.notice`): „Prověrka hotová: 5 finalistů. U 2 je kritérium z kola 4 nesplněné: @kuba.jidlo.brno (Bez spolupráce s konkurencí), … Otevřít spis →“. Po změně cíle: „Cíl změněn: pekárna → fitness studio. Vyřazeno jen u nového cíle: 4. Rozdíl je vpravo nahoře.“ [P0-10]
- Seznam zpráv má `role="log"`, `tabIndex={0}` a popisek „Konverzace s průvodcem“. Během psaní má zpráva `aria-busy`. [P1-03]
- Prázdný stav: vpravo místo pěti boxů „ČEKÁ“ tři kroky („Popíšete firmu“, „Schválíte kritéria“, „Projdete trychtýř“) a šedý obrys trychtýře. Porovnání se skryje, dokud nejsou finalisté. [P2-03]

### 4.3 Kritéria

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Creator profile Instagram tab with filter chip row (Spyglass) | refero.design | https://refero.design/pages/96364745-02a3-443a-b81a-343ee7388cf0 | Štítek „Název: hodnota“, jeden řádek na kolo, šedý název kola vlevo. |
| Plnty: grouped checklists with section counters | details.so | https://www.details.so/inspo/plnty-5a0a15 | Nadpis „KOLO 1 · ZÁKLAD 5“. Vypnuté kritérium zůstane přeškrtnuté na místě. |
| Animation when numbers change in Dub.co | designspells.com | https://designspells.com/spells/animation-when-numbers-change-in-dub-co | Úprava kritéria viditelně změní počet v kole. |
| Modal transitions and animations in Luma | designspells.com | https://designspells.com/spells/modal-transitions-and-animations-in-luma | „Přidat kritérium“ jako mřížka typů (nápad, P2). |

Změny:

- Před spuštěním je „Spustit kola 0–3“ jediné plné tlačítko na obrazovce. [P0-07]
- Po spuštění se panel sbalí do jednoho řádku: „Kritéria 15 · pekárna · Brno · Víc lidí v prodejně · Nekontrolujeme 1 · Upravit“. „Hledáme přes“ je v rozbalené části. [P0-08]
- Editor kritéria: každé pole má český popisek, jednotka je připojená, přepínače témat jsou skupina s nadpisem. Surové klíče (`min`, `max_share`) nejsou vidět. [P0-04]
- Shrnutí ve štítcích: „5–50 tis.“, „≤ 30 dní“, „≥ 1× týdně“, „≥ 20 %“ u formátu. [P1-12]
- Štítek jako celé tlačítko, ✎ jen při najetí a fokusu. Vypnuté kritérium přeškrtnuté s „Zapnout“. [P2-08]

### 4.4 Trychtýř, karty a vyřazení

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Animated progress indicator when using Linear's import assistant | designspells.com | https://designspells.com/spells/animated-progress-indicator-when-using-linears-import-assistant | Stepper kol a pod ním jedna věta, co se právě stahuje. |
| Funnel visualisation: narrowing band with count + % pill per step (Visitors) | refero.design | https://refero.design/pages/36a1eec0-f9ba-4287-bd89-f2d7ae2fc6a1 | Úzký pás „48 → 22 → 11 → 5“ v jedné neutrální barvě. |
| Candidates grouped by hiring stage (Wittl) | refero.design | https://refero.design/pages/a488e0a8-303b-4974-ada6-297b20e474ec | Kola s nulou zůstávají vidět, jen tlumená. |
| Progress indicator animation in Linear | designspells.com | https://designspells.com/spells/progress-indicator-animation-in-linear | Jedna rodina tvarů pro stav kola: kruh, prstenec, kruh s ✓. Jen v inkoustu. |
| Archived candidates with reason and Restore (Wittl) | refero.design | https://refero.design/pages/fd36bdf0-0f96-4a85-941e-cb3f96478ac7 | Řádek vyřazeného: kolo, důvod, zdroj, tiché „Vrátit“. |
| „Why is Camille not a fit?“ reason picker (Kinhive) | refero.design | https://refero.design/pages/c61fd9b6-cdf8-4ac2-82b4-ee77679ef070 | Ohleduplné formulace u vyřazení. |
| Clear Street: source rows with hover action | details.so | https://www.details.so/inspo/clearstreet-sx1n5q | Akce „Vrátit“ se ukáže při najetí i fokusu. |
| Creator profile overview (Spyglass) | refero.design | https://refero.design/pages/e535519b-66a9-40b4-8eea-0df165a9194d | Hlava karty: avatar, @účet, počet sledujících s platformou, jeden šedý řádek meta. |
| Integrated Biosciences: people list rows with mono meta | details.so | https://www.details.so/inspo/integratedbiosciences-qiblrg | Mono meta „IG · 23,4 tis. · Brno“. |
| Clucky: rolling odometer digits | details.so | https://www.details.so/inspo/tryclucky-ae3091 | Počty v kolech dorolují na novou hodnotu (P2). |

Změny:

- Hlavička trychtýře: stepper kol 0 až 4. Hotové kolo je plný kruh s ✓, aktuální je prstenec, budoucí prázdný kruh. Pod ním jedna věta, třeba „Stahuji profily a posledních 12 postů…“. Vpravo primární akce kroku, například „Prověřit 5 do hloubky“. [P0-07, P1-05]
- Počty jako úzký pás v inkoustu. Budoucí kola jsou tlumená. Prázdné boxy s pomlčkami zmizí. Názvy kol jsou h3. [P1-05]
- Po změně cíle kolo 4 ukáže „Finalisté 5 · prověřeno 1 (dříve)“. Pás nekončí „→ 1“. [P0-11]
- Karta finalisty: řádek 1 je avatar (rovná iniciála v sans), @účet v sans 600 a MOCK. Řádek 2 je mono meta „IG · 23,4 tis. · Brno“. Řádek 3 je výsledek kola 4 celým textem, třeba „✕ nesplňuje: Bez spolupráce s konkurencí“. Text se zalomí, nezkracuje se. [P0-09]
- Dole na kartě je viditelné tlačítko „Otevřít spis“, aspoň 24 px vysoké. Počet sledujících se nikdy neusekne. [P1-07]
- Hustá karta (víc než 12 ve sloupci) má textový štítek „M“ se skrytým textem „MOCK“. [P0-05]
- Přístupné jméno karty se skládá z obsahu: „@kuba.jidlo.brno, MOCK, Instagram, 23,4 tis. sledujících, nesplňuje: Bez spolupráce s konkurencí, spis k dispozici“. [P0-05]
- Vyřazení: ve sloupci zůstává jen souhrn podle kritéria („14× Velikost“). Klik otevře široký panel pod trychtýřem „Vyřazeno v kole 1 · 26“. Řádky jsou seskupené podle kritéria. Řádek: @účet · nesplňuje: kritérium (hodnota) · zdroj · Vrátit. Panel má nejvýš 480 px a vlastní posuv. [P1-06]

### 4.5 Spis finalisty

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Linear: side sheet with record property grid | details.so | https://www.details.so/inspo/linear-eb8d1a | Malý nadpis, velký název, mřížka „štítek nad hodnotou“, buňka zdroje. |
| Company record: tabs with counts + Record Details (Attio) | refero.design | https://refero.design/pages/bcc9e9fc-c97e-404c-a925-42f1b7d51bf4 | Řádek stavových štítků s počty pod názvem. Prázdná hodnota řečená slovy. |
| Criterion evidence modal (Parallel FindAll) | refero.design | https://refero.design/pages/cdafc3c4-560e-4d35-a4ad-274c5b807fa9 | Kritérium, výsledek, zdůvodnění a číslované citace s výňatkem. |
| Agentwork: AI answer that names conflicting sources | details.so | https://www.details.so/inspo/agentwork-80aedd | Věcně říct, který zdroj co tvrdí a kde si odporují. |
| Smooth sliding sidebars in Typefully | designspells.com | https://designspells.com/spells/smooth-sliding-sidebars-in-typefully | Tiché řádky klíč a hodnota, hodnota v mono vpravo. |
| Linear: issue view with Activity feed | details.so | https://www.details.so/inspo/linear-445982 | Systémové události tišší než text průvodce (nápad). |

Změny:

- Hlava spisu: @účet, razítko MOCK, meta řádek „Jakub Horák · IG · 23,4 tis. sledujících · staženo 9. 10. 2026“. Pod ním řádek štítků s počty: „Fakt 18 · Odhad 3 · Mezera 2“, každý ve své vyhrazené barvě a s textem. [P0-09]
- Hned pod hlavou blok „Na co se podívat“. Má 1 až 3 řádky a každý vede do sekce. U Kuby: „Záznam ukazuje 2 posty se spoluprací s @pekarna_b. Tento účet je ve vašem seznamu konkurentů. → Tvrzení vs. záznam“. Vzniká z nesplněných kritérií kola 4 a z nesouladů tvrzení. Nehodnotí člověka. [P0-09]
- Obsah spisu je jedna lepkavá lišta odkazů. Prázdné sekce se skryjí (třeba Identita bez shody). [P1-08]
- Karta kandidáta je mřížka vlastností: štítek nad hodnotou, u každé hodnoty zdroj. [P1-08]
- Tvrzení vs. záznam: vlevo citace tvrzení, vpravo záznamy. Všechny záznamy mají stejný vzhled faktu. Vztah k tvrzení je slovo a glyf: „podporuje ✓“ nebo „odporuje ✕“. Šrafování mizí, pletlo se s mezerou. Verdikt „Nesoulad se záznamem · jistota vysoká“ a jeho vysvětlení mají 14 px. [P1-08]
- Koncept oslovení: když je nesoulad, nad konceptem je věcná poznámka „Před oslovením si projděte Tvrzení vs. záznam“. [P1-08]
- Nálezy: kompaktní řádky na kartě. Druh nálezu nese levý pruh 4 px a slovo („fakt“, „odhad“, „mezera“). Nahoře filtr „Vše · Fakta · Odhady · Mezery“ s počty. Odhady a mezery jsou první. Místo interních id je „Nález 3 · Interakce“. Stejné zdroje se sloučí do „IG ×5“. [P1-09]
- Popover zdroje se otevře uvnitř spisu, dostane fokus a Escape zavře jen jeho. [P0-02]

### 4.6 Porovnání finalistů

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Companies table: tags, numeric columns, muted empty values (Attio) | refero.design | https://refero.design/pages/4230ed22-90d5-4524-8348-840c69529946 | Čísla doprava a tabulární. Chybějící údaj šedým textem. Barevné tečky síly vztahu nebereme. |
| People list with single „Sort by“ popover (Visitors) | refero.design | https://refero.design/pages/d0619a96-5b04-4419-87ab-ebd59f854f41 | Jeden ovladač „Seřadit podle“. |
| Paradigm: agent-filled spreadsheet | details.so | https://www.details.so/inspo/paradigmai-586452 | Podbarvit jen sloupec, podle kterého se řadí. Štítky „Tier“ nebereme. |
| Featurebase: comparison table with collapsible group rows | details.so | https://www.details.so/inspo/featurebase-d2fd1f | Řádky ve skupinách podle kola, skupina jde sbalit. |

Změny:

- Přepínač „Jen rozdíly“ je zapnutý, když nějaké rozdíly jsou. V demu ukáže 2 řádky. Vedle je „Zobrazit všech 15“. [P1-10]
- Řádky jsou ve skupinách podle kola. Kolo 4 je nahoře. [P1-10]
- V buňce je glyf a krátká hodnota („1 z 20 postů“). Celá věta je v popoveru zdroje. Čísla mají `tabular-nums`. [P1-10]
- Řazení má jeden ovladač „Seřadit podle“. Seřazený sloupec je jemně podbarvený (`--accent-soft`). Pořadí přes všechna kritéria neexistuje. [P1-10]
- Na mobilu je tabulka otočená: jedna karta na kritérium, finalisté pod sebou. [P2-04]

### 4.7 Změna cíle a rozdíl

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Animated timer in confirmation dialog when changing disk size on Supabase | designspells.com | https://designspells.com/spells/animated-timer-in-confirmation-dialog-when-changing-disk-size-on-supabase | Krok „Co se změní“: důsledky jednou větou a tabulka „staré → nové“. |
| Sneak peek of the Pro plan benefits when hovering on the upgrade CTA (Dub.co) | designspells.com | https://designspells.com/spells/sneak-peek-of-the-pro-plan-benefits-when-hovering-on-the-upgrade-cta-button | Gramatika „přeškrtnuté staré, vedle nové“. |
| Edit history: side-by-side versions with change header (n8n) | refero.design | https://refero.design/pages/dfc74e55-09b5-4f67-af50-f13a1d485a81 | Hlavička „staré → nové“ s přeškrtnutím. Bez červené a zelené. |
| xAI: terminal plan view where every change shows as a clean diff | details.so | https://www.details.so/inspo/x-703562 | Změny kritérií jako řádky se značkami + − ~. |

Změny:

- Dialog nahoře ukáže současný cíl: „Teď: pekárna · Brno · Víc lidí v prodejně“. Pole jsou předvyplněná současným cílem. Předvolby (fitness, pekárna) jsou tlačítka. [P1-11]
- Před potvrzením je krok „Co se změní“: „Kola 1–3 se přepočítají z uložených dat. Nic se znovu nestahuje.“ a tabulka „Co prodáváte: ~~pekárna~~ → fitness studio“. [P1-11]
- Rozdíl: nadpis „Cíl: ~~pekárna~~ → fitness studio“. Tři skupiny: „Vyřazení jen u nového cíle“, „Prošli u obou“, „Vyřazení jen u původního cíle“. Značky + − ~ a přeškrtnutí, žádná zelená ani červená. Neutrální rod („postupuje dál“). [P1-11]
- Panel rozdílu má nejvýš 360 px a „Zobrazit vše“. Hlavička trychtýře zůstane na obrazovce 1440 × 900 vidět. [P1-11]

### 4.8 Živý běh

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Workflow run: collapsible steps with durations and log lines (GitHub Actions) | refero.design | https://refero.design/pages/6a2ab671-7af2-49fd-9fa3-151147fff32b | Skupiny podle kroků, ✓, název, trvání v mono vpravo. Porota Apify to zná z Apify Console. |
| Foglamp: trace waterfall with nested spans | details.so | https://www.details.so/inspo/foglamp-caa8f3 | Kolo jako rodič, běhy Actorů jako děti, „2,4 s · 48 položek“. |
| Foglamp: dense traces table with filter chips | details.so | https://www.details.so/inspo/foglamp-8aee59 | Filtr podle kola, čísla v tabulárních sloupcích. |
| Real-time dashboard of Vercel's requests over the BFCM weekend | designspells.com | https://designspells.com/spells/real-time-dashboard-of-vercels-requests-over-the-bfcm-weekend | Tečka LIVE a mono řádky. Černý „hackerský“ vzhled nebereme. |

Změny:

- Lišta nesmí zakrýt obsah. Hlavní plocha má `scroll-padding-bottom` a dolní mezeru. [P0-07]
- Sbalená lišta: tečka stavu, poslední řádek celý, správný plurál („1 řádek“, „3 řádky“, „48 řádků“). [P1-12, P2-02]
- Rozbalený běh: skupiny podle kol. Uvnitř řádky Actorů: název Actoru, vstup, počet položek, trvání v mono vpravo, původ dat. Zdvojené řádky (MOCK news a Zprávy) se sloučí. Technické názvy tady zůstávají. [P2-02]

### 4.9 Mobil (375 px)

| Reference | Web | URL | Co si bereme |
|---|---|---|---|
| Chat with top segmented Chat / Voice switch (Grok iOS) | refero.design | https://refero.design/screens/659ef316-a735-40fd-8800-28b229c1d01f | Segmentový přepínač „Průvodce / Výsledky“ uprostřed horní lišty. Pole pro psaní přilepené dole. |

Změny:

- Hlavička má jeden řádek: logo, stavový štítek, menu. [P1-02]
- Přepínač „Průvodce / Výsledky“ místo tabů s počty. Úplný vzor tabů nebo dvě tlačítka s `aria-pressed`. [P1-14, P2-04]
- Přepnutí na Průvodce skočí na poslední zprávu. [P2-04]
- Trychtýř je svisle: kola jako sbalitelné sekce pod sebou, aktuální kolo otevřené. Akce kroku je přilepená dole. [P2-04]

---

## 5. Tokeny

### 5.1 Typová škála

Dnes je v komponentách 20 velikostí od 9,5 do 30 px. Nově jich je 7.

| Token | Velikost / řádek | Písmo | Použití |
|---|---|---|---|
| `--text-xs` | 12 / 16 px | Plex Mono 500, verzálky, prostrkání 0,06 em | Nadpisy skupin („KOLO 1“), zdrojové štítky, mono meta |
| `--text-sm` | 13 / 18 px | Plex Sans 400 | Vedlejší text, buňky tabulky, důvody vyřazení |
| `--text-base` | 14 / 21 px | Plex Sans 400 a 500 | Běžný text, chat, tlačítka, pole |
| `--text-md` | 16 / 22 px | Plex Sans 600 | @účet na kartě, nadpisy podsekcí |
| `--text-lg` | 20 / 26 px | Newsreader 600 | h2 panelů, h3 kol a sekcí spisu |
| `--text-xl` | 28 / 34 px | Newsreader 600 | Název spisu, citace tvrzení ve větší velikosti |
| `--text-num` | 36 / 40 px | Newsreader 500, `lining-nums tabular-nums` | Velká čísla v trychtýři |

Pravidla:

- Nic menšího než 12 px. Nikde.
- Newsreader jen pro nadpisy, název spisu, velká čísla a citace tvrzení.
- Plex Sans pro všechno ostatní. @účet je vždy v sans, na kartě, ve vyřazení i ve spisu.
- Plex Mono jen pro meta čísla, zdrojové štítky, nadpisy skupin a živý běh.
- Tučnosti 400, 500 a 600. Kurzíva jen u citací.

### 5.2 Mezery

Mřížka 4 px.

| Token | Hodnota | Kde |
|---|---|---|
| `--space-1` | 4 px | Mezera v štítku, mezi ikonou a textem |
| `--space-2` | 8 px | Mezi kartami ve sloupci, mezi štítky |
| `--space-3` | 12 px | Vnitřní okraj karty |
| `--space-4` | 16 px | Vnitřní okraj panelu na mobilu, mezera mezi panely |
| `--space-6` | 24 px | Vnitřní okraj panelu na desktopu, spisu a dialogu |
| `--space-8` | 32 px | Mezi sekcemi spisu |
| `--space-12` | 48 px | Spodní mezera nad lištou Živý běh |

### 5.3 Zaoblení

Dnes 1, 2, 3, 4, 6, 10 a 99 px. Nově čtyři hodnoty.

| Token | Hodnota | Kde |
|---|---|---|
| `--radius-xs` | 2 px | Štítky, zdrojové štítky, MOCK |
| `--radius-sm` | 4 px | Tlačítka, pole, karty kandidátů |
| `--radius-md` | 8 px | Panely, spis, dialog, popover |
| `--radius-full` | 999 px | Avatar, stavový štítek, tečky stepperu |

Stín má jen to, co plave: spis, dialog, popover. Karty mají jen linku.

### 5.4 Barvy: světlý motiv „Papír“ (výchozí pro video)

Poměry kontrastu podle WCAG 2.x, spočítané ze zadaných hex hodnot.

| Token | Hodnota | Kontrast | Použití |
|---|---|---|---|
| `--paper` | `#f2ece0` | podklad | Pozadí aplikace |
| `--paper-2` | `#e8e0cf` | podklad | Sloupec chatu, lišty |
| `--paper-3` | `#ddd3bf` | podklad | Aktivní řádek, vybraný segment |
| `--card` | `#fbf8f1` | podklad | Karty, panely, spis |
| `--ink` | `#1c1913` | 14,90 na paper, 16,53 na card | Hlavní text |
| `--ink-2` | `#4b453a` | 8,07 na paper, 8,95 na card | Vedlejší text, glyfy ✓ ✕ ? |
| `--ink-3` | `#615b4f` (bylo `#7b7364`) | 5,73 na paper, 6,35 na card, nejméně 4,54 na paper-3 | Tlumený text, popisky, meta |
| `--ink-4` | `#a59d8c` | 2,29 na paper | Jen dekorativní oddělovače s `aria-hidden`. Nikdy text. |
| `--rule` | `#d5cab5` | dekorace | Tenké linky mezi bloky |
| `--field` (nový) | `#7d7464` | 3,92 na paper, 4,35 na card, 3,51 na paper-2, 3,11 na paper-3 | Okraj polí, přepínačů, zaškrtávacích polí |
| `--accent` | `#2442a6` | 7,42 na paper, 8,23 na card. Bílý text na accent 8,73 | Primární tlačítko, odkazy, fokus |
| `--accent-soft` | `#dfe4f5` | ink na něm 13,82, ink-3 5,31 | Seřazený sloupec, výběr |
| `--fact` na `--fact-bg` | `#2c6a3d` na `#e1ebdc` | 5,29. Na card 6,12 | Fakt se zdrojem |
| `--inference` na `--inference-bg` | `#9e530e` (bylo `#b25d10`) na `#f5e4cf` | 4,57. Na card 5,35 | Odhad (cituje fakta) |
| `--gap` na `--gap-bg` | `#6a645a` (bylo `#847d70`) na `#e7e2d7` | 4,54. Na card 5,53 | Mezera |
| `--mock` | `#c0157a` | 5,45 na card. Bílý text na mock 5,79. Mock na `--mock-bg` (`#fbe1ef`) 4,72 | Jen MOCK: rám, pruh, štítek |

Zrnitost papíru: `--grain-opacity` z 0,35 na 0,2. Ve videu šum zbytečně zatěžuje kompresi.

### 5.5 Barvy: tmavý motiv „Inkoust“

| Token | Hodnota | Kontrast | Použití |
|---|---|---|---|
| `--paper` | `#12141a` | podklad | Pozadí aplikace |
| `--paper-2` | `#181b23` | podklad | Sloupec chatu, lišty |
| `--paper-3` | `#20242e` | podklad | Aktivní řádek |
| `--card` | `#1c2029` | podklad | Karty, panely, spis |
| `--ink` | `#ece4d4` | 14,57 na paper, 12,90 na card | Hlavní text |
| `--ink-2` | `#c3b9a6` | 9,48 na paper, 8,39 na card | Vedlejší text, glyfy |
| `--ink-3` | `#9b9486` (bylo `#8f8777`) | 6,11 na paper, 5,41 na card, nejméně 4,91 na inference-bg | Tlumený text |
| `--ink-4` | `#635d52` | 2,82 na paper | Jen dekorace |
| `--rule` | `#2e333f` | dekorace | Linky |
| `--field` (nový) | `#6b7180` (bylo `#434a59`, asi 2 : 1) | 3,77 na paper, 3,34 na card, 3,18 na paper-3 | Okraj polí |
| `--accent` | `#8497ec` (bylo `#93a8ff`, nejjasnější věc na obrazovce) | 6,68 na paper, 5,92 na card. Text `#0f1220` na accent 6,76 | Primární tlačítko, fokus |
| `--accent-soft` | `#232c4d` | ink-3 na něm 4,53 | Seřazený sloupec |
| `--fact` na `--fact-bg` | `#84c595` na `#1b2b20` | 7,36 | Fakt |
| `--inference` na `--inference-bg` | `#eca866` na `#33251a` | 7,29 | Odhad |
| `--gap` na `--gap-bg` | `#9d9686` na `#25272c` | 5,08 | Mezera |
| `--mock` | `#ff5fb4` | 5,86 na card. Text `#1a0712` na mock 6,97 | Jen MOCK. Smí být nejjasnější, je to varování. |

### 5.6 Pohyb

| Token | Hodnota | Kde |
|---|---|---|
| `--dur-fast` | 120 ms | Najetí, fokus, štítky |
| `--dur-base` | 200 ms | Spis, dialog, panel vyřazení |
| `--dur-count` | 500 ms | Dorolování čísel |
| `--ease` | `cubic-bezier(0.2, 0.8, 0.2, 1)` | Vše |

Při `prefers-reduced-motion: reduce` jsou všechny délky 0 a JS posouvá bez animace.

---

## 6. Seznam změn podle priority

P0 jsou porušení norem a věci, které ve videu vypadají rozbitě. P1 přinese největší zlepšení vzhledu a srozumitelnosti. P2 je navíc. Soubory jsou relativní k `frontend/src/`.

### P0

| Id | Oblast | Změna | Hotovo, když | Soubory |
|---|---|---|---|---|
| P0-01 | Tokeny, kontrast | Nové `--ink-3`, `--inference`, `--gap` (kap. 5.4 a 5.5). `--ink-4` pryč z textu. | axe `color-contrast` hlásí 0 uzlů v obou motivech ve stavu prázdný, trychtýř a spis. `text-ink-4` se nepoužívá na text. | `index.css`, `components/*.tsx` |
| P0-02 | Zdroje | Popover zdroje uvnitř aktivního dialogu, s fokusem a Escape. Štítek s `aria-haspopup`, `aria-expanded` a jménem „Zdroj: Instagram · MOCK · staženo 9. 10. 2026“. | Ve spisu: Enter na štítku přesune fokus do popoveru. Tab dojde na „Otevřít zdroj“. Escape zavře jen popover a fokus je zpět na štítku. | `components/primitives.tsx`, `components/CandidateDrawer.tsx` |
| P0-03 | Dialogy | Hook `useDialog`: uložit spouštěč, fokus dovnitř, `inert` na zbytek, Tab uvnitř, Escape, návrat fokusu. `aria-modal` a `aria-labelledby`. | Změnit cíl, editor kritéria, spis i potvrzení mazání: fokus jde dovnitř, Shift+Tab nevyjde ven, po Escape je fokus na spouštěči. | `lib/useDialog.ts` (nový), `components/GoalModal.tsx`, `components/CriteriaPanel.tsx`, `components/CandidateDrawer.tsx`, `components/Header.tsx`, `App.tsx` |
| P0-04 | Kritéria | Editor kritéria: `<label htmlFor>` pro každé pole, české názvy, jednotka přes `aria-describedby`, skupina témat. | axe `label` 0. Každé pole má české jméno bez surového klíče. | `components/CriteriaPanel.tsx`, `i18n.ts` |
| P0-05 | Karta kandidáta | Přístupné jméno z obsahu. Hustá karta má viditelný štítek „M“ se skrytým „MOCK“. | Čtečka přečte @účet, MOCK, platformu, sledující a výsledek. Ve sloupci se 48 kartami je MOCK vidět jako text. | `components/Funnel.tsx`, `components/primitives.tsx` |
| P0-06 | MOCK | Rám 3 px v magentě kolem okna nad spisem i dialogem. Pruh se nezakrývá. Zdrojový štítek v MOCK ukazuje text „MOCK“. Magenta jinde není. | V MOCK je rám vidět v každém stavu včetně otevřeného spisu. Každý zdrojový štítek má slovo MOCK. Magenta se v CSS používá jen pro MOCK. | `components/DemoBar.tsx`, `App.tsx`, `components/primitives.tsx`, `components/CandidateDrawer.tsx`, `index.css` |
| P0-07 | Další krok | Vždy jedno plné tlačítko. „Spustit kola 0–3“ v kritériích. „Prověřit 5 do hloubky“ v hlavičce trychtýře. „Změnit cíl“ vedlejší a až po běhu. Lišta Živý běh nic nezakryje. | V každém stavu je vidět právě jedno `.btn-primary`. Po kolech 0–3 je „Prověřit 5 do hloubky“ na 1440 × 900 vidět bez posunu a klik funguje při jakémkoli posunu. | `components/Header.tsx`, `components/Funnel.tsx`, `components/CriteriaPanel.tsx`, `components/LiveLog.tsx`, `App.tsx`, `index.css` |
| P0-08 | Kritéria | Po spuštění se panel kritérií sbalí do jednoho řádku s „Upravit“. | Po „Ano, spusť“ má panel nejvýš 56 px a hlavička trychtýře je na 1440 × 900 nejvýš na y = 200. | `components/CriteriaPanel.tsx`, `App.tsx`, `i18n.ts` |
| P0-09 | Pointa | Karta ukáže nesplněné kritérium celým textem. Spis začíná řádkem „Fakt · Odhad · Mezera“ s počty a blokem „Na co se podívat“. | Karta @kuba.jidlo.brno ukazuje „nesplňuje: Bez spolupráce s konkurencí“ bez zkrácení. První obrazovka spisu ukazuje položku o @pekarna_b s odkazem na Tvrzení vs. záznam. | `components/Funnel.tsx`, `components/CandidateDrawer.tsx`, `i18n.ts` |
| P0-10 | Průvodce | Frontend přidá do chatu oznámení po dokončení prověrky a po změně cíle. | Po prověrce je v chatu souhrn s @účty a nesplněným kritériem a odkazem na spis. Po změně cíle souhrn rozdílu. Obě zprávy jsou v `role="log"`. | `store.tsx`, `components/Chat.tsx`, `i18n.ts` |
| P0-11 | Trychtýř | Po změně cíle kolo 4 ukáže „Finalisté 5 · prověřeno 1 (dříve)“ místo „5 → 1“. | Pás počtů nekončí „→ 1“. Popisek říká, že jde o dřívější prověrku. | `components/Funnel.tsx`, `i18n.ts` |
| P0-12 | Neutrální značky | ✓ ✕ ? jako holé glyfy v `--ink-2`, bez rámečku, stejná velikost a síla. `role="img"` s českým jménem. | V žádném motivu není ✕ plné pole. Značky se liší od zaškrtávacích polí v prověrce. Čtečka řekne „splněno“, „nesplněno“ nebo „nejde ověřit“. axe `aria-prohibited-attr` 0 u značek. | `components/primitives.tsx`, `components/Compare.tsx`, `components/Funnel.tsx`, `index.css` |

### P1

| Id | Oblast | Změna | Hotovo, když | Soubory |
|---|---|---|---|---|
| P1-01 | Tokeny | Typová škála, mezery, zaoblení a pohyb podle kap. 5. Tmavý accent `#8497ec`. Zrnitost 0,2. | V kódu je nejvýš 7 velikostí písma, nic pod 12 px. @účet je všude v sans. Zaoblení jen 2, 4, 8 a 999 px. | `index.css`, `components/*.tsx` |
| P1-02 | Hlavička | Jeden řádek. Stavový štítek dat s vysvětlením místo počítadel a krabičky LLM. h1. Pořadí v DOM jako na obrazovce. Mobil: jeden řádek a menu. | Hlavička má nejvýš 56 px na desktopu i mobilu. Stavový štítek jde otevřít klávesnicí. Tab jde zleva doprava. Tlačítko motivu má jméno s viditelným slovem. | `components/Header.tsx`, `i18n.ts`, `index.css` |
| P1-03 | Chat | Nástroje lidsky s odkazem do pravé části. `role="log"`, `tabIndex={0}`, popisek, `aria-busy` při psaní. | V chatu není vidět `propose_criteria` ani `run_rounds`. axe `scrollable-region-focusable` 0. Čtečka nečte zprávu po kouscích. | `components/Chat.tsx`, `i18n.ts` |
| P1-04 | Stavové zprávy | Skrytá oblast `aria-live` v trychtýři. Kontejner hlášek je v DOM pořád. „Zkopírováno“ se oznámí. | Čtečka oznámí „Kolo 2 hotovo: vstoupilo 22, zůstalo 11“, konec prověrky i přepočet. | `components/Funnel.tsx`, `components/DemoBar.tsx`, `components/CandidateDrawer.tsx` |
| P1-05 | Trychtýř | Stepper kol, jedna věta o aktuální práci, pás počtů v inkoustu, tlumená budoucí kola, h3, jména tlačítek pásu. | Stepper ukazuje hotové, aktuální a budoucí kolo tvarem. Nejsou boxy s pomlčkami. Tlačítko pásu se jmenuje třeba „Kolo 1 Základ: zůstalo 22“. | `components/Funnel.tsx`, `i18n.ts`, `index.css` |
| P1-06 | Vyřazení | Široký panel pod trychtýřem, seskupený podle kritéria, řádky s „Vrátit“, nejvýš 480 px. České kategorie. | Rozbalení kola 1 zvětší nástěnku nejvýš o 480 px. Každý řádek má kritérium, hodnotu, zdroj a „Vrátit“ aspoň 24 px. Nejsou vidět „Bakery“ ani „Brand“. | `components/Funnel.tsx`, `i18n.ts`, `index.css` |
| P1-07 | Karta finalisty | Tlačítko „Otevřít spis“, počet sledujících se neusekne, rovná iniciála v avataru. | „27,3 tis.“ u @toman_ochutnava je celé. „Otevřít spis“ má aspoň 24 px a je hned vidět. | `components/Funnel.tsx`, `components/primitives.tsx` |
| P1-08 | Spis | Lepkavá lišta obsahu, skryté prázdné sekce, mřížka vlastností, jednotný vzhled záznamů v Tvrzení vs. záznam, poznámka u konceptu oslovení. Spis jako `div role="dialog"`. | Žádné šrafování. Vztah je slovem „podporuje“ nebo „odporuje“. Identita bez shody není vidět. Uvnitř spisu není druhý landmark banner. | `components/CandidateDrawer.tsx`, `index.css`, `i18n.ts` |
| P1-09 | Nálezy | Kompaktní řádky, filtr s počty, odhady a mezery první, žádná interní id, sloučené zdroje. | Není vidět žádné `f:` id. Filtr „Odhady“ ukáže jen odhady. Řádek má nejvýš jeden štítek zdroje na platformu („IG ×5“). | `components/CandidateDrawer.tsx`, `index.css`, `i18n.ts` |
| P1-10 | Porovnání | „Jen rozdíly“ zapnuto, skupiny podle kola s kolem 4 nahoře, v buňce jen hodnota, `tabular-nums`, podbarvený seřazený sloupec. | V demu jsou bez kliknutí vidět 2 řádky s rozdílem. Buňka má nejvýš 2 řádky. Nikde není celkové pořadí. | `components/Compare.tsx`, `i18n.ts`, `index.css` |
| P1-11 | Změna cíle | Dialog ukáže současný cíl a krok „Co se změní“. Rozdíl ve třech skupinách včetně „Prošli u obou“, přeškrtnutí a + − ~, neutrální rod, nejvýš 360 px. | Dialog se otevře s hodnotami současného cíle. V rozdílu není zelená ani červená. Po změně cíle je na 1440 × 900 vidět rozdíl i hlavička trychtýře. | `components/GoalModal.tsx`, `components/DiffView.tsx`, `i18n.ts` |
| P1-12 | Čeština | `csTypo()` pro texty UI i backendu. Plurály, rozsahy, „≥ 1× týdně“, „≤ 30 dní“. Žádné anglické zbytky (LIVE, toc, actor, reels, surové klíče). | Na 375 px žádný řádek nekončí jednopísmennou předložkou. „1 řádek / 3 řádky / 48 řádků“. „5–50 tis.“ a „od 5 tis.“. V cs režimu není anglické slovo mimo vlastní jména. | `i18n.ts`, `components/primitives.tsx`, `components/CriteriaPanel.tsx`, `components/Header.tsx`, `components/LiveLog.tsx`, `components/CandidateDrawer.tsx` |
| P1-13 | Pole a cíle | Token `--field` na okraje polí a přepínačů. Cílové plochy aspoň 24 px. | Okraj polí má aspoň 3 : 1 v obou motivech. axe `target-size` 0. | `index.css`, `components/Funnel.tsx`, `components/Compare.tsx`, `components/CandidateDrawer.tsx`, `components/Header.tsx` |
| P1-14 | Jména a struktura | Glyfy s `aria-hidden`. Česká jména tlačítek („Sbalit vyřazené“). Úplný vzor mobilních tabů. `lang="en"` a `translate="no"`. | axe best-practice (`page-has-heading-one`, `region`, `aria-allowed-role`) 0. Čtečka nečte „✕“, „↺“ ani „▤“. | `components/Header.tsx`, `components/Funnel.tsx`, `components/CandidateDrawer.tsx`, `components/DemoBar.tsx`, `components/Compare.tsx`, `App.tsx` |

### P2

| Id | Oblast | Změna | Hotovo, když | Soubory |
|---|---|---|---|---|
| P2-01 | Počítadla | Čísla v trychtýři dorolují na novou hodnotu, předchozí chvíli šedne. | Animace trvá nejvýš 500 ms, čísla jsou tabulární, při omezeném pohybu se jen vymění. | `components/Funnel.tsx`, `index.css` |
| P2-02 | Živý běh | Skupiny podle kol, řádky Actorů s trváním a počtem položek, bez duplicit, tečka stavu. | Rozbalený běh má skupinu na kolo. Sbalená lišta ukazuje celý poslední řádek. | `components/LiveLog.tsx`, `i18n.ts`, `index.css` |
| P2-03 | Prázdný stav | Tři kroky a obrys trychtýře místo boxů „ČEKÁ“. Porovnání skryté do kola 3. | V prázdném stavu není žádné „ČEKÁ“ ani pomlčka. | `components/Funnel.tsx`, `components/CriteriaPanel.tsx`, `components/Compare.tsx`, `components/Chat.tsx`, `i18n.ts` |
| P2-04 | Mobil | Přepínač „Průvodce / Výsledky“, skok na poslední zprávu, svislý trychtýř, otočené porovnání. | Na 375 px nejsou kola vedle sebe. Po přepnutí na Průvodce je vidět poslední zpráva. | `App.tsx`, `components/Chat.tsx`, `components/Funnel.tsx`, `components/Compare.tsx`, `index.css` |
| P2-05 | Pohyb, dotyk, meta | Animace bez `box-shadow`, posuv v JS podle `prefers-reduced-motion`, `overscroll-behavior`, safe-area, `theme-color`, obrys fokusu karty uvnitř, `role="list"`. | Žádné keyframes s `box-shadow`. Fokus na kartě je vidět celý. | `index.css`, `components/Funnel.tsx`, `components/CandidateDrawer.tsx`, `components/DemoBar.tsx`, `../index.html` |
| P2-06 | URL | Otevřený spis v URL jako `?c=<id>`. | Obnovení stránky znovu otevře stejný spis. | `store.tsx`, `components/CandidateDrawer.tsx` |
| P2-07 | Rozvržení | Chat jde sbalit do úzké lišty s úchytem. | Sbalení i rozbalení jde klávesnicí. Trychtýř pak využije celou šířku. | `App.tsx`, `components/Chat.tsx`, `index.css` |
| P2-08 | Kritéria | Štítek „Název: hodnota“ jako celé tlačítko, ✎ jen při najetí a fokusu, vypnuté kritérium přeškrtnuté s „Zapnout“. | Vypnutí kritéria nezmění výšku řádku. | `components/CriteriaPanel.tsx`, `index.css` |

---

## 7. Co neděláme a proč

- **Nový koncept ani nová značka.** Stůl s důkazy sedí k nástroji, kterému se má věřit. Výzkum nenašel nic lepšího. Ladíme, nezačínáme znovu.
- **Žádné skóre, měřák ani verdikt.** Vzor „Watchtower score“ z 1Password (https://designspells.com/spells/watchtower-score-calculation-animation-in-1password) je přesně to, co nesmíme. Bereme z něj jen myšlenku „?“ s popiskem „ověřuji“.
- **Žádné „vypaření“ vyřazených.** Efekt ze Safari (https://designspells.com/spells/items-get-vaporized-when-hidden-on-safari) by u skutečných lidí vypadal jako jejich ničení. Bereme jen spodní lištu s počtem a „Vrátit vše“.
- **Žádné přejíždění karet vlevo a vpravo.** Tinder styl u lidí je špatný vzor pro vyřazování.
- **Žádná duhová, žlutá ani fialová pro stavy.** Linear barví stavy, my ne. Zelená, oranžová a šedá jsou vyhrazené pro důkazy.
- **Žádná červená a zelená v rozdílu cílů.** Zelená je fakt. Rozdíl ukazuje přeškrtnutí a značky + − ~.
- **Žádné „Tier“, „#1“ ani priority.** Z Paradigm, Aside a Linear bereme rozvržení, ne pořadí.
- **Žádný černý „hackerský“ log.** Majitele pekárny by vystrašil. Bereme jen mono řádky a tečku stavu.
- **Spis nepřepisujeme na záložky.** Na to dnes není čas. Necháme sekce, přidáme souhrn nahoře a lištu obsahu.
- **Nová písma nepřidáváme.** Newsreader, Plex Sans a Plex Mono stačí. Jen je používáme přísněji.
- **Animace přes 500 ms nepřidáváme.** Klid je důležitější než efekt.
- **Pohyb ze zdrojů na Refero neopisujeme.** Toky jsou za placenou zdí. Pohyb bereme jen z designspells.com a details.so.
- **Zvýraznění místa ve zdroji při najetí na údaj** (vzor macOS, https://designspells.com/spells/floating-cursor-appears-when-you-perform-a-search-in-the-macos-app-menus) odkládáme. Je to dobrý nápad, ale potřebuje náhled zdroje, který dnes nemáme.

### Předat backendu (tento úkol na backend nesahá)

- Demo data odporují příběhu. V běhu pro pekárnu je nejčastější zdroj #brnofitness a mezi finalisty je @fit_peci_s_klarou (`pred/04-funnel-desktop-light.png`). Frontend to nespraví.
- Průvodce po prověrce a po změně cíle sám nic neřekne. Frontend to přechodně řeší oznámením (P0-10). Lepší je, když to řekne průvodce.
- Kritéria se v chatu opakují jako zeď 25 řádků (`pred/03-criteria-chat-mobile-dark.png`). Stačí věta „Navrženo 15 kritérií, jsou vpravo.“
- Rychlé odpovědi pod otázkami průvodce potřebují návrhy z backendu.
- Texty: „10 reels, 5 fotky, 5 karusely“ má být „10 reelů, 5 fotek, 5 karuselů“. „nejvýš 0 neoznačených spoluprací“ má být „žádná neoznačená spolupráce“. „(75 analyzováno)“ má být „(analyzováno 75 komentářů)“. „Brno - Zelný trh“ má mít pomlčku „–“. Kategorie z Instagramu („Digital creator“, „Bakery“) přeložit, nebo dát do uvozovek s poznámkou.

---

## 8. Poznámky k provedení (odchylky, 9. 10. 2026)

- Karta finalisty: @účet má na kartě 14 px (ne 16 px) a štítek MOCK je na řádku 2 před „IG · 23,4 tis. · Brno“. Ve sloupci širokém 184–210 px se @účet, avatar a MOCK na jeden řádek nevejdou. MOCK zůstává textem na každé kartě.
- Zdrojový štítek: přístupné jméno se skládá z obsahu, „Zdroj: IG (Instagram) · MOCK · staženo 9. 10. 2026“, aby obsahovalo viditelný text (WCAG 2.5.3). U MOCK je „Otevřít zdroj“ fokusovatelné tlačítko s `aria-disabled`, takže Tab na něj dojde, ale nic neotevře.
- Porovnání: kritéria jsou řádky, takže podbarvený (`--accent-soft`) je řádek kritéria, podle kterého se řadí. V buňce je krátká hodnota z dat (procento, počet, datum); celá věta je v popoveru zdroje.
- Rozdíl cílů: „−“ vyřazení jen u nového cíle, „~“ prošli u obou, „+“ vyřazení jen u původního cíle.
- Hlavička: menu „⋯“ má Motiv, Jazyk a Smazat data; na užších obrazovkách i Rozmazat a Změnit cíl. Pruh MOCK je nad hlavičkou jako samostatná oblast, hlavička sama má 56 px (48 px na mobilu).
- Živý běh: backend neposílá trvání ani počet položek Actoru, proto je skupina kola jen se jménem nástroje, původem a časem. Kola se poznají podle řádků enginu „Kolo N: …“; dvojice „MOCK …“ a lidský řádek téhož nástroje jsou sloučené (technický text je v `title`).
- Oznámení v chatu (P0-10) jsou strukturovaná (`ChatMessage.notice`), takže se přeloží při přepnutí jazyka. Prověrka se ohlásí jen při skutečném dokončení, ne po změně cíle.
