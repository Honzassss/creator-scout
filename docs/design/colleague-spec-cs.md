# Visual spec from a teammate (Czech original, authoritative for the redesign)

Implement this in code (the team lead approved implementing it in the app, 9 Oct 2026). Plus the teammate's note on motion: "Animations sometimes make texts overlap, which is not fresh. Animations must be synchronized with each other: not everything at once, but one after another."

1. Celkový vizuální charakter
Rozhraní má působit jako klidný pracovní nástroj pro prohlížení a porovnávání tvůrců. Používej velké světlé plochy, jasnou typografickou hierarchii a střídmé barevné akcenty.
Navrhuj výhradně světlou variantu. Pozadí nesmí přecházet do tmavého režimu podle systému. Velké barevné plochy omez na jemné odstíny; sytou petrolejovou používej na hlavních ovládacích prvcích a malých zvýrazněních.

2. Přesná barevná paleta
Základ pracovní plochy je světle šedý #F3F6F8. Karty, detail profilu, formuláře a hlavní obsahové panely mají bílé pozadí #FFFFFF.
Hlavní text má barvu #182C36. Vedlejší vysvětlení používají #435965. Doplňující metadata používají #5F717B; důležité informace nesmí zesvětlit natolik, aby se obtížně četly.
Hlavní akcent je petrolejový #086B68. Jemné zvýraznění aktivního prvku má barvu #E4F3F0. Dekorativní dělicí čáry mají barvu #DCE4E8. Hranice vstupních polí mají být výraznější, například #6F8794.
Bílý text používej pouze na dostatečně tmavých tlačítkách. Petrolejový text může být na bílé nebo jemně zelené ploše.
Proč: šedé pozadí oddělí pracovní plochu od bílých panelů. Petrolej vytvoří rozpoznatelnou identitu bez vizuální agresivity původního červeného rámování.

3. Typografie a čitelnost
Používej jedno bezpatkové písmo, ideálně stávající IBM Plex Sans. Základní velikost běžného textu je 15 px s řádkováním 22 px.
Nadpis obsahového panelu má 20 px, řádkování 28 px a váhu 600. Jméno tvůrce má 16 px, řádkování 22 px a váhu 600. Vedlejší text má 13 px s řádkováním 18 px. Krátká metadata mohou mít 12 px.
Počty kandidátů mají 28–32 px a váhu 600. Čísla mají mít stejně široké číslice, aby se dobře porovnávala.
Nepoužívej velké množství verzálek. Malé štítky mohou být verzálkami, dlouhé popisky a vysvětlení mají být běžným písmem.
Proč: uživatel musí rozeznat číslo, jeho popisek a vysvětlení už při rychlém pohledu.

4. Rozestupy, rámečky a zaoblení
Používej jednotnou škálu rozestupů: 4, 8, 12, 16, 24 a 32 px.
Hlavní panely mají vnitřní odsazení 24 px na desktopu a 16 px na mobilu. Karty tvůrců mají odsazení 16 px. Mezi samostatnými panely je mezera 20–24 px.
Zaoblení hlavních panelů a karet je 12 px. Tlačítka a vstupní pole mají zaoblení 8 px. Malé informační štítky mají zaoblení 4–6 px.
Používej jednobodový jemný rámeček. Stín může být velmi slabý; základní orientaci mají vytvářet rozestupy a hranice panelů.

5. Rozložení desktopu
Levý průvodce má při širším okně přibližně 304 px. Na užším desktopu může mít 288 px. Hlavní výsledková plocha využívá zbývající prostor a má vnější odsazení 24 px.
Průvodce má zůstat podpůrným panelem. Výsledky musí být vizuálně dominantní.
Zachovej existující sbalený stav průvodce. Při sbalení má vzniknout více místa pro výsledky, bez jiného uspořádání jejich významu nebo pořadí.

6. Horní lišta a informace o demu
Hlavní horní lišta má cílovou výšku přibližně 64 px. Značka aplikace je vlevo, hlavní dostupné akce vpravo. Používej bílé pozadí a jemnou spodní dělicí čáru.
Informace o demo režimu má vlastní kompaktní pruh vysoký přibližně 28–32 px. Použij světle šedé pozadí a menší čitelný text. Ovládání přehrávání vizuálně seskup.
Demo označení musí zůstat dohledatelné, ale nesmí vytvářet dominantní barevný rám kolem celé aplikace.
Proč: nad obsahem dnes vzniká příliš mnoho vizuálního ruchu a spotřebovaného prostoru.

7. Levý průvodce
Nadpis „Průvodce“ má 18–20 px. Pod ním je krátké vysvětlení funkce panelu ve velikosti 13 px.
Zprávy průvodce mají neutrální bílou nebo velmi světle šedou plochu. Zprávy uživatele mohou mít jemně petrolejové pozadí. Role musí být rozlišitelná také textovým označením.
Delší zprávy mají řádkování alespoň 22 px a odstup mezi odstavci 12 px. Zvýraznění používej pouze u podstatného jména, zjištění nebo doporučeného dalšího kroku.
Vstupní pole má dobře rozpoznatelný obrys. Tlačítko odeslání má petrolejovou plochu. Jeho nedostupný nebo načítací stav musí být vizuálně odlišný.

8. Souhrn výsledků a kritéria
Nahoře ve výsledkové ploše navrhni stručný souhrn sestavený výhradně z existujících údajů.
Pro současnou ukázku může vizuální hierarchie pracovat s informacemi „6 finalistů“, „5 prověřeno“, „1 čeká na prověření“, pokud tyto údaje odpovídají aktuálnímu stavu. Počet finalistů a počet dokončených prověrek musí být zřetelně oddělený.
Panel kritérií má nadpis vlevo a existující akci úpravy vpravo. Pod nadpisem zobraz krátký, čitelný souhrn aktivních podmínek. Na mobilu se souhrn zalamuje na další řádky.
Proč: uživatel potřebuje okamžitě pochopit stav výběru i podmínky, podle kterých vznikl.

9. Přehled jednotlivých kol
Nad šířkou okna 1 000 px navrhni první čtyři etapy do mřížky 2 × 2. Při menší šířce je řaď pod sebe.
Každá etapa obsahuje název, krátké vysvětlení a počet kandidátů. Název má 16 px a váhu 600. Vysvětlení má 12–13 px. Čísla mají největší váhu.
Uzavřená etapa má cílovou minimální výšku přibližně 88 px. Výška může růst podle obsahu. Existující rozbalovací ovladač umísti vždy na stejné místo vpravo.
Aktuální etapa může mít úzký petrolejový proužek nebo jemně tónovanou hlavičku. Dokončení etapy neprezentuj jako pozitivní hodnocení všech kandidátů uvnitř.

10. Karty finalistů
Karty mají bílé pozadí. Okolní plocha zůstává světle šedá. Jemné zelené zvýraznění soustřeď do hlavičky finální sekce.
Na dostatečně široké ploše zobraz tři sloupce, na střední dva a na mobilu jeden. Karta má mít minimální pohodlnou šířku přibližně 240–260 px.
Pořadí informací na každé kartě je stejné: identita tvůrce, základní údaje, výsledky ověření, otevření detailu.
Avatar má přibližně 32 px. Uživatelské jméno je výrazné a dostává maximální dostupnou šířku. Pod ním jsou platforma, sledující a lokalita. Mezi identitou a zjištěními je mezera 12 px.
Dlouhá jména a důvody musí zůstat přečitelné. Karta může růst do výšky. Nevytvářej nové skóre, hvězdičky ani označení „nejlepší“, která aplikace neobsahuje.

11. Vzhled výsledků ověření
Rozlišuj tři významy: splňuje, nesplňuje, nelze ověřit.
„Splňuje“ může používat tmavší zelenou a velmi jemný zelený podklad. „Nesplňuje“ používá tlumenou červenou. „Nelze ověřit“ používá jantarovou nebo neutrální barvu.
Každý stav musí mít také ikonu a text. Barevné plochy mají být malé, například u konkrétního zjištění.
Proč: zelená celá karta by mohla naznačovat, že tvůrce splňuje všechny podmínky, přestože některá prověrka chybí nebo dopadla negativně.

12. Srovnávací tabulka
Tabulka má bílé pozadí a jemně šedou hlavičku. Text má 14 px. Odsazení buněk je přibližně 12–16 px. Běžný řádek má minimální výšku kolem 56 px a podle textu může růst.
Sloupec s kritériem má přibližně 190–220 px. Sloupce tvůrců mají alespoň 160 px. Zachovej orientaci pomocí viditelné hlavičky a prvního sloupce.
Vodorovné posouvání patří dovnitř tabulky. Hlavní stránka kvůli ní nesmí přetékat.
Řazení a přepínání rozdílů zachovává svůj současný význam. Vizuálně nesmí vzniknout dojem automatického žebříčku.

13. Detail tvůrce
Detail je bílý panel s cílovou maximální šířkou přibližně 900 px. Na telefonu využívá celou šířku.
Jméno profilu má 26 px. Pod ním jsou základní údaje ve velikosti 14 px. Zavření je vždy snadno dohledatelné.
Mezi hlavními sekcemi je mezera 32 px. Nadpis sekce má 18 px. Fakta, odhady a chybějící podklady mají jednotné, rozpoznatelné štítky.
Podklady a zdroje zobrazuj poblíž příslušného zjištění. Používej jemné rámečky a malé informační bloky, aby zůstal patrný vztah mezi tvrzením a jeho podkladem.

14. Mobilní podoba
Pod 768 px zachovej existující přepínání Guide / Results. Aktivní položka má petrolejovou plochu a bílý text; neaktivní je bílá s tmavým textem.
Vnější odsazení je 12–16 px. Hlavní ovladače mají dotykovou plochu alespoň 44 × 44 px.
Karty se řadí pod sebe. Kritéria a důvody se zalamují. Výška panelů se přizpůsobuje textu. Běžný obsah musí být čitelný při šířce 320 px; samostatně posuvná může zůstat srovnávací tabulka.

15. Interakční vzhled
Navrhni konzistentní podobu tlačítek při běžném stavu, najetí, stisku, zaměření klávesnicí a nedostupnosti. Zaměření má viditelný petrolejový obrys přibližně 2 px s odstupem od prvku.
Pro běžný text požaduj kontrast alespoň 4,5 : 1 a ověř ho u použitých kombinací.
