# Apify pro Kryštofa: co spustit, co čekat, na co si dát pozor

Předávka k 8. 10. 2026. Kryštof dnes v noci vlastní všechno, co volá Apify. Nikdo jiný actory nespouští. Plán: [brand-fit-cz.md](brand-fit-cz.md), ověření faktů: [overeni-2026-10-08.md](overeni-2026-10-08.md), architektura: [architecture.md](architecture.md).

**Odkud to víme:** schémata vstupů a výstupů, README a ceníky jsme četli 8. 10. 2026 z veřejných endpointů `https://api.apify.com/v2/acts/<owner>~<name>/builds/default` a `https://api.apify.com/v2/acts/<owner>~<name>` (fungují bez tokenu). Žádný actor jsme nespustili. „Ověřeno: ano“ tedy znamená „je ve schématu nebo v ukázce README“, ne „viděli jsme to v živém běhu“. README nejsou datované, ukázky v nich jsou z let 2024 až 2026.

**Aktualizace 9. 10. 2026:** testy T1 až T12 (kromě T7) proběhly živě. Výsledky, opravy kódu a otevřené otázky jsou v sekci „Výsledky živých testů 9. 10. 2026“ níže; kde se liší od zbytku textu, platí ona.

## Shrnutí

1. **Funguje:** všechny actory z plánu existují, nejsou deprecated a nepotřebují login. Ceny (pay per event) sedí. Profily, posty, komentáře a hledání účtů na IG mají pole, která potřebujeme.
2. **Rozbité nebo rizikové:** hashtagové posty nemají souřadnice (jen `locationId`), URL místa vrací jiný tvar dat, TikTok `region` a `isUnderAge18` jsou asi prázdné, Meta Branded Content možná české spolupráce nevrátí, post-scraper bez `dataDetailLevel` účtuje detail. Plný běh stojí asi 7 USD, víc než Free kredit 5 USD.
3. **Testuj první:** profily v dávce (T5), štítek `paidPartnership` v post-scraperu (T6), Meta Branded Content na rohlik.cz s kontrolou nike (T8), hashtagy s `locationId` (T3, T4) a tvar TikTok hledání `/user` (T9).

## Výsledky živých testů 9. 10. 2026

Free plán (5 souběžných běhů na účet), každý běh se stropem `max_total_charge_usd`. Surová data jsou v `data/live-tests/` (v `.gitignore`, skutečná veřejná data, po hackathonu smazat). Tato sekce má přednost před odhady ve zbytku dokumentu.

| Test | Actor | Výsledek | Položky | USD | Hlavní zjištění |
|---|---|---|---|---|---|
| T1 | search-scraper `user` | prošel | 42 + 20 živě | 0,3384 | Bez `liveSearch` jen 11 ze 40 relevantních (vše z `facebook-ads`), hity z `google` a `threads` mimo téma. `liveSearch` 15 z 20 v Brně, stejná cena, tenké položky bez bio a čísel. Chybové položky se účtují. `relatedProfiles` u místních účtů prázdné. |
| T2 | search-scraper `place` | prošel | 45 + 30 živě | 0,2025 | `posts` je seznam surových IG médií (autor `user.username`, čas `taken_at`) u 33 ze 42 míst, jen 22 % z posledního roku. Klíč `city` ani `address` není. `CITY_BBOX` sedí (0 chyb na 41 souřadnicích). `liveSearch` u míst ne: `id` místo `location_id`, jen 11 z 30 v Brně. |
| T3 | hashtag-scraper | částečně | 36 | 0,0936 | První stránka 12 (#brnofood) a 24 (#spoluprace), ne 20. `locationId` u 36 % (67 % u #brnofood), nikdy `lat`/`lng`. `paidPartnership` false 35 z 35 i u #spoluprace, `sponsors` chybí, `type` existuje. #spoluprace je celostátní. |
| T4 | instagram-scraper, URL místa | prošel | 7 | 0,0189 | URL místa vrací jednu položku místa s 15 až 18 vnořenými posty (pro `posts` i `details`), nikdy posty. Účtuje 1 výsledek za místo bez ohledu na `resultsLimit`. Párování přes `location_id` funguje i pro víc míst v běhu. |
| T5 | profile-scraper | prošel | 9 (7 profilů) | 0,0234 + 0,0729 hledání | `username` a `fullName` jsou. `latestPosts` 12 z 12, `videoViewCount` u 52 z 52 reels, místo u 73 %, 7 % postů jsou spolupráce vlastněné partnerem. `isPinned` jen když true. `relatedProfiles` vždy prázdné. Neexistující účet je placená chybová položka. 9 profilů za 13,5 s. |
| T6 | post-scraper `detailedData` | prošel | 21 + 3 kontrola | 0,0567 + 0,0081 | `paidPartnership` true u 3 ze 3 štítkovaných postů (Meta), false u 21 z 21 českých. `sponsors` nikdy. `latestComments` až 15 na post s `text` a `timestamp`. `music-data` 0krát. V režimu `username` `likesCount` -1 u 11 z 12 postů. |
| T7 | comment-scraper | nespuštěno | 0 | 0 | Není potřeba, `latestComments` z T6 stačí. |
| T8 | brand-collaboration-scraper | neprošel | 1 + 3 | 0,0232 | rohlik.cz: jen chybová položka `no_items`, přesto účtovaná 0,0058. nike: 3 řádky. České spolupráce bez přihlášení nevidíme, Meta Branded Content škrtáme. Jména jsou IG handly, „12 months“ přijato. |
| T9 | tiktok-scraper `/user` | částečně | 24 CZ + 20 bez CZ | 0,196 | Položky jsou videa nalezených profilů, profil bez videí vrací placenou položku `note`. Klíče `region` a `isUnderAge18` chybí. `isSponsored` false 40 z 40. Hledá slovo ve jméně, vrací podniky: 5 českých food účtů s CZ, 3 bez CZ. |
| T10 | tiktok-profile-scraper | neprošel | 6 | 0,018 | `region` ani `isUnderAge18` nejsou ani u zahraničního účtu. Region nepoužívat, věk je mezera. |
| T11 | google-news-scraper-fast | prošel | 10 | 0,04 | `source` je text, 10 z 10 URL vydavatelů, žádná z Googlu. Bez `extractDescriptions` chybí `description`. `publishedAt` má jen den. |
| T12 | youtube-scraper | prošel | 2 + 3 kanál | 0,008 + 0,012 | `isPaidContent` true a false podle očekávání, vyplněné i ve výpisu kanálu. `channelLocation` jen u URL kanálu. 0,004 za video, stránka kanálu zdarma. |

**Útrata testů celkem:** 1,11 USD (IG hledání a místa 0,65, IG profily a posty 0,16, spolupráce, zprávy a YouTube 0,08, TikTok 0,21).

**Ceny potvrzené na účtu (FREE):** search 0,0027 (i `live-search-result`), hashtag 0,0026, instagram-scraper 0,0027, profil 0,0026, post 0,0017 + detail 0,001, tiktok-scraper 0,0037 + CZ 0,0013 + start 0,001 (minimální strop 0,50), tiktok-profile 0,003, brand-collab 0,0058, zprávy 0,004, YouTube 0,004. Vyúčtované `usageTotalUsd` se rovná počtu eventů × ceně, ale `call()` vrací běh dřív, než se dopočítá (často 0,0).

**Opravy tabulky „Cena jednoho plného běhu“:** řádek 4 je 1 výsledek za místo, ne 20 postů; posty z míst většinou už přijdou s vyhledáním míst. Řádek 5 je asi 24 výsledků na dotaz, tedy asi 0,12 USD. Řádek 9 odpadá (`latestComments`, úspora 1,40 USD), řádek 11 odpadá (Meta Branded Content škrtnutý, úspora 0,58 USD).

### Co se změnilo v kódu

- **Hledání účtů IG:** posílá `liveSearch` (`IG_SEARCH_LIVE`) a nechá jen účty, které mají město v handlu, jménu nebo bio (`search_user_in_city`); počet vyřazených jde do logu. Na uložených datech z 29 nesmyslných hitů nezůstal žádný.
- **Místa (`APIFY_PLACES=1`):** autoři z `posts[].user.username`, posty starší než rok pryč, účet podniku se za autora nepočítá. Druhý běh instagram-scraperu jen pro místa bez `posts`, s `details` a limitem 1. Mrtvá větev pro postové položky je pryč.
- **Profily IG:** `views` z `videoViewCount`. Spolupráce vlastněná partnerem dostane profil jako spoluautora.
- **TikTok:** handle z `authorMeta.profileUrl` a `name`, `display_name`, `following` a `posts_count` z `nickName`, `following` a `video`. Hashtagy z objektů, `location_name` je „podnik, město“ (prázdné `city` nahradí `address`), nově `location_id` a `is_pinned`, slideshow je `carousel`. Profily bez videí z hledání se přeskočí. `TRUST_TIKTOK_FALSE_LABEL` je teď `False`: falešné „neoznačené reklamy“ jsou horší než mezera.
- **Komentáře:** výchozí `APIFY_COMMENTS_SOURCE=latest`.
- **Meta Branded Content:** vypnuto, zapíná `APIFY_META_BRANDED=1`. Řádek nese `post_id` z odkazu, takže se spojí se štítkem téhož postu.
- **YouTube:** `posts(handle, "youtube")` čte videa kanálu (`map_yt_video`); `isPaidContent` false se bere jako `None`.
- **Běhy:** `wait_for_resources` 120 s místo chyby 4xx při limitu 5 souběžných běhů. Útrata v logu je max(`usageTotalUsd`, položky × cena). Varování na `music-data` jen při nenulovém počtu.
- **Beze změny:** `CITY_BBOX`, `BRAND_WINDOW`, ceny, `TRUST_IG_FALSE_LABEL = False`, `TRUST_TIKTOK_REGION = False`.
- Ruční vzorky v `backend/tests/apify_samples/` mají tvar živých položek (smyšlené účty a hodnoty).

### Co zůstává otevřené

- Český IG post se štítkem „Placené partnerství“ a štítkované české TikTok video jsme neviděli. Do té doby `False` u štítku neznamená „bez štítku“.
- Přejmenované účty, co spouští `music-data` a jestli se účtuje i v `basicData`.
- Comment-scraper a tiktok-comments-scraper neběžely. YouTube hledání netestováno.
- TikTok `/user` najde podniky podle slova ve jméně; klíčová slova ve stylu tvůrců jsme nezkoušeli.

**Účty pro demo:** aktivní foodloverbrno, gourmetbrno, foodie_brno_, judgemental_tuna; kamvbrne je mediální účet. Dobré příklady vyřazení: foodguidebrno (poslední post 12/2025), brno_best_bites (2024), foodblogcs (bez vazby na Brno).

## Prvních 45 minut

Nezávislé testy (T1, T2, T3, T8, T9, T10, T11, T12) pusť hned paralelně. T4 až T7 navazují na jejich výstup. Všechny testy dohromady stojí asi 1 USD. Surový dataset každého běhu ulož do cache, ať ho kola můžou přehrávat bez nového stahování.

Před prvním během: u každého volání nastav strop ceny běhu (v API parametr `maxTotalChargeUsd`, v Python klientovi `max_total_charge_usd`, ověř ve své verzi klienta, neověřeno). U `clockworks/tiktok-scraper` musí být strop aspoň 0,50 USD (`minimalMaxTotalChargeUsd`).

### T1. Hledání účtů na IG · `apify/instagram-search-scraper`

```json
{"search": "cukrárna brno, brno food", "searchType": "user", "searchLimit": 20}
```

Druhý běh stejně, jen s `"liveSearch": true`.

- **Zkontroluj:** kolik profilů přijde na dotaz; hodnoty `searchSource`; mají profily ze zdroje `google` i `latestPosts`; tvar `businessCategoryName`; je `relatedProfiles` neprázdné; čím se liší výstup s `liveSearch`.
- **Projde:** aspoň 10 relevantních brněnských účtů a u většiny `latestPosts`.
- **Když ne:** hledání účtů zůstane jen doplněk, hlavní zdroj jsou hashtagy a seznam od majitele. Profily bez `latestPosts` pošleme do profile-scraperu (0,0026 USD za účet).

### T2. Místa v Brně · `apify/instagram-search-scraper`

```json
{"search": "cukrárna brno, kavárna brno, pekárna brno", "searchType": "place", "searchLimit": 30}
```

Druhý běh stejně s `"liveSearch": true` (jen tam je pole `city`).

- **Zkontroluj:** `location_id`, `lat`/`lng` (leží v Brně?), `location_city` a `city`, jestli mají místa vnořené `posts`, `ig_business.profile.username`.
- **Projde:** aspoň 15 míst, která podle souřadnic leží v Brně. Brno zhruba `49.10 <= lat <= 49.30` a `16.45 <= lng <= 16.75` (náš odhad, dolaď).
- **Když ne:** cestu „posty z míst“ škrtáme. Brno poznáme jen z textu (bio, popisky, `locationName`).

### T3. Hashtagy · `apify/instagram-hashtag-scraper`

```json
{"hashtags": ["brnofood", "spoluprace"], "resultsType": "posts", "resultsLimit": 50}
```

- **Zkontroluj:** kolik položek vrátí Free na jeden hashtag (velikost první stránky není nikde uvedená); kolik postů má `locationId`; `ownerUsername`; jestli je někde `paidPartnership: true` (hlavně u #spoluprace). URL postů z #spoluprace si schovej pro T6.
- **Projde:** aspoň 20 postů na hashtag a aspoň část s `locationId`.
- **Když ne** (méně než 10 na hashtag): hashtagy jen jako doplněk. Na 300 postů by bylo potřeba 15 a víc hashtagů.

### T4. URL místa a souřadnice pro `locationId` · `apify/instagram-scraper`

```json
{"directUrls": ["https://www.instagram.com/explore/locations/<ID z T2>/"], "resultsType": "posts", "resultsLimit": 20}
```

Totéž s `"resultsType": "details"` a jednou s `locationId` z T3 (stačí URL jen s ID). Než budeš mít brněnské ID, tvar jde otestovat na `270309914` (Bakeshop Praha, z README).

- **Zkontroluj:** vrátí to posty s `ownerUsername`, nebo jednu položku místa s vnořenými `posts[].username`? Má položka `lat`/`lng`? Kolik položek se účtovalo?
- **Projde:** z URL místa dostaneme autory i souřadnice.
- **Když ne:** cestu „posty z míst“ škrtáme. Pro `locationId` z hashtagů pak nemáme souřadnice, Brno poznáme jen podle seznamu míst z T2 a podle textu.

### T5. Profily v dávce · `apify/instagram-profile-scraper`

```json
{"usernames": ["kamvbrne", "<20 až 50 jmen z T1 a T3>"], "includeAboutSection": false}
```

`kamvbrne` je brněnský průvodce jídlem z [žebříčku Modash](https://www.modash.io/find-influencers/czech-republic/brno), na Instagramu neověřený, a je to mediální účet, ne tvůrce. Vyměň ho za skutečného tvůrce, jakmile ho máš z T1 nebo T3.

- **Zkontroluj:** dobu běhu; počet `latestPosts`; `isPinned`; `productType`; prázdné `latestPosts` u veřejných profilů; položky s `error`; `relatedProfiles` u malých účtů; `fbid`.
- **Projde:** aspoň 90 % veřejných profilů má neprázdné `latestPosts` a běh doběhne do 3 minut.
- **Když ne:** dávky po 25, prázdné profily stáhnout znovu. Když je `relatedProfiles` u malých účtů prázdné, cestu „podobné účty“ škrtáme.

### T6. Štítek placeného partnerství · `apify/instagram-post-scraper`

```json
{"username": ["<5 URL postů z T3 #spoluprace>", "kamvbrne"], "resultsLimit": 12, "skipPinnedPosts": true, "dataDetailLevel": "detailedData"}
```

- **Zkontroluj:** `paidPartnership`, `sponsors[].username`, `latestComments`, `coauthorProducers`, `locationName`, `locationId`. V detailu běhu se podívej na účtované eventy: je tam `music-data`?
- **Projde:** `paidPartnership: true` aspoň u jednoho postu, který má na Instagramu štítek „Placené partnerství“.
- **Když ne:** kola 2 a 4 berou reklamu jen z popisků (#reklama, #spoluprace, slevové kódy, @značky) a druhý běh postů pro kola 2 a 3 škrtáme (úspora asi 0,8 USD). Když se účtuje `music-data`, přepni na `basicData` nebo sniž strop ceny.

### T7. Komentáře · `apify/instagram-comment-scraper` (jen když T6 nevrátí `latestComments`)

```json
{"directUrls": ["<3 URL z latestPosts v T5>"], "resultsLimit": 15}
```

- **Zkontroluj:** kolik komentářů přijde na post (Free má dát 15 nejnovějších), jestli je vyplněný `text`.
- **Projde:** aspoň 10 komentářů s textem na post.
- **Když ne:** jazyk publika bereme jen z `latestComments`, jinak kritérium „jazyk publika“ = nejde ověřit.

### T8. Meta Branded Content · `apify/brand-collaboration-scraper`

```json
{"startUrls": ["https://www.instagram.com/rohlik.cz/"], "resultsLimit": 10, "onlyPostsNewerThan": "6 months"}
```

Kontrola, že actor vůbec funguje:

```json
{"startUrls": ["https://www.instagram.com/nike/"], "resultsLimit": 3, "onlyPostsNewerThan": "6 months"}
```

- **Zkontroluj:** počet řádků; `creator.name`, `brandPartners[].name`, `link`, `dateCreated`.
- **Projde:** rohlik.cz vrátí aspoň 1 řádek.
- **Když ne:** nike vrací a rohlik.cz 0 → české spolupráce bez přihlášení nevidíme, Meta Branded Content škrtáme hned. Obojí 0 → actor nefunguje, škrtáme taky.

### T9. TikTok hledání · `clockworks/tiktok-scraper`

```json
{"searchQueries": ["cukrárna brno"], "searchSection": "/user", "maxProfilesPerQuery": 10, "resultsPerPage": 3, "proxyCountryCode": "CZ"}
```

Totéž bez `proxyCountryCode` (A/B test).

- **Zkontroluj:** jsou položky profily, nebo videa jednotlivých profilů? Kolik výsledků se účtovalo? Liší se výsledky s CZ a bez? Jsou vyplněné `authorMeta.region`, `authorMeta.isUnderAge18`, `textLanguage`, `locationCreated`, `locationMeta`?
- **Projde:** aspoň 5 českých účtů o jídle.
- **Když ne:** TikTok jen pro finalisty přes odkazy v bio. Když CZ výsledky nemění, vypnout (úspora 0,0013 USD za výsledek).

### T10. TikTok region a věk · `clockworks/tiktok-profile-scraper`

```json
{"profiles": ["apifytech", "khaby.lame"], "resultsPerPage": 3, "excludePinnedPosts": true}
```

`khaby.lame` je jen příklad ne-českého účtu (neověřeno), poslouží jakýkoli zjevně zahraniční.

- **Zkontroluj:** `authorMeta.region` u obou účtů (u zahraničního nesmí vyjít CZ), `authorMeta.isUnderAge18`, `locationMeta` u videí.
- **Projde:** region je vyplněný a u zahraničního účtu jiný než CZ. Pak smí do kritéria lokality.
- **Když ne:** region prázdný nebo všude CZ → `region` nepoužívat (je to region požadavku, ne účtu). `isUnderAge18` prázdné → věk je mezera. Nezletilé pak řešíme jen přes výslovný věk v bio a ověření majitelem.

### T11. Zprávy · `data_xplorer/google-news-scraper-fast`

```json
{"keywords": ["cukrárna Brno"], "region_language": "CZ:cs", "timeframe": "1y", "maxArticles": 10, "decodeUrls": true, "extractImages": false}
```

- **Zkontroluj:** jsou to české články, vede `url` na vydavatele (ne na news.google.com), je vyplněné `publishedAt`.
- **Projde:** aspoň 3 české články s URL vydavatele.
- **Když ne:** záloha `apify/google-search-scraper` (sekce 15), jinak zprávy v kole 4 škrtáme (jsou v pořadí škrtů).

### T12. YouTube štítek · `streamers/youtube-scraper`

```json
{"startUrls": [{"url": "https://www.youtube.com/watch?v=JsBZOcqZerk"}, {"url": "https://www.youtube.com/watch?v=1H20xp8Brnc"}], "maxResults": 1}
```

- **Zkontroluj:** `isPaidContent` je `true` u prvního videa (má štítek „Includes paid promotion“) a `false` u druhého.
- **Projde:** přesně tak.
- **Když ne:** YouTube škrtáme (je první v pořadí škrtů).

## Společná pravidla pro všechny actory

- **Chybové položky odfiltruj:** IG `error` a `errorDescription`, TikTok `errorCode`, YouTube `error`. Jestli se chybové položky účtují, nevíme.
- **Chybějící není false.** Prázdné pole = „nevíme“, nikdy „ne“. To platí hlavně pro štítky spolupráce, region a věk.
- **Identitu komentujících smaž při načtení,** ještě před cache: IG `latestComments[].ownerUsername`, `firstComment`, `owner`, `ownerProfilePicUrl`, `taggedUsers[].full_name` u cizích lidí; TikTok `uid`, `uniqueId`, `avatarThumbnail`, `mentions`, `detailedMentions`.
- **Limity vždy výslovně.** Řada actorů má nebezpečné výchozí hodnoty: `resultsPerPage` 1 nebo 100, `timeframe` 1h, `maxResults` 0, `dataDetailLevel` detailedData.
- **Ceny se mění.** Post-scraper dostal nový ceník 7. 10. 2026. Po prvním běhu každého actoru se podívej na účtované eventy.
- **Spolehlivost:** u search-scraperu za posledních 30 dní asi 4,5 % veřejných běhů FAILED a 1,2 % TIMED-OUT. Opakuj jednou a cachuj.
- **Do logu** dej u každého kroku jméno actoru a „živě“ nebo „z cache“.

## Actory jeden po druhém

### 1. `apify/instagram-search-scraper`

- **K čemu:** kolo 0. Hledání účtů podle slov s městem, hledání míst v Brně, volitelně populární reels ke slovu. [Stránka](https://apify.com/apify/instagram-search-scraper), [schéma](https://api.apify.com/v2/acts/apify~instagram-search-scraper/builds/default).
- **Vstup:** `search` (text, povinné, čárka dělí dotazy), `searchType` (`place` | `user` | `hashtag` | `popular`, výchozí `place`, vždy nastav), `searchLimit` (1 až 250 na dotaz, bez výchozí hodnoty), `liveSearch` (bool, živé hledání Instagramu, jiný a užší tvar dat), `enhanceUserSearchWithFacebookPage` (skryté, nech vypnuté, přidává e-maily firem).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `username`, `fullName`, `biography`, `followersCount`, `private`, `isBusinessAccount` | ano | profily |
| `businessCategoryName` | ano | text s čárkami, např. „None,Candy Store“; rozděl a „None“ zahoď |
| `relatedProfiles` | ano | v ukázce prázdné |
| `latestPosts` | ano | jen profily, README říká 12, ukázka má 3 |
| `latestPosts[].locationName` | nejasné | spíš chybí |
| `searchSource` | ano | `instagram` / `threads` / `facebook-ads` / `google` |
| `location_id`, `inputUrl`, `lat`, `lng` | ano | místa |
| `location_city` | ano | v ukázce vždy prázdné |
| `city` | ano | jen místa s `liveSearch` |
| `posts` (u místa) | nejasné | jen u 1 ze 3 míst v ukázce, s 1 postem; pole nebo text |
| `ig_business.profile.username` | ano | místa, firemní účet podniku |
| `latestComments[].ownerUsername` | ano | populární reels; jména smazat |

- **Cena a Free:** 0,0027 USD za výsledek na Free, 0,0023 na Starteru, i pro `liveSearch`. Bez startovního poplatku. Zvláštní limit pro Free není, 5 USD vystačí asi na 1 850 výsledků.
- **Nástrahy:** výchozí `searchType` je `place`. Hledání účtů bere z Facebook Ads (asi top 10) a Googlu (až 200), takže reálně méně než 250. Místa vrací i mimo ČR (výsledek „cakes prague“ leží v Íránu), filtruj podle souřadnic. Posty u profilů nemají místo. `popular` vrací max asi 64 reels na slovo a ne každé slovo má feed.
- **Alternativa:** `apify/instagram-hashtag-scraper` s `keywordSearch: true` (víc slov jako průnik).

### 2. `apify/instagram-hashtag-scraper`

- **K čemu:** kolo 0. Posty z hashtagů (#brnofood), seskupené podle autora. [Stránka](https://apify.com/apify/instagram-hashtag-scraper), [schéma](https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/builds/default).
- **Vstup:** `hashtags` (pole textů, povinné, # nepovinný, slova na jednom řádku se slijí v jeden tag), `resultsType` (`posts` | `reels`, výchozí `posts`; `stories` je zrušené), `resultsLimit` (na hashtag, bez výchozí hodnoty), `keywordSearch` (bool, víc slov jako průnik, přidá `latestComments`).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `ownerUsername`, `ownerId`, `ownerFullName` | ano | |
| `locationName` | ano | volný text, často název podniku, často chybí |
| `locationId` | ano | spolehlivý klíč místa |
| `lat` / `lng` | ne | souřadnice dohledej přes actor 3 |
| `timestamp`, `caption`, `hashtags`, `url`, `productType` | ano | |
| `coauthorProducers` | ano | |
| `paidPartnership`, `sponsors` | ano | ve schématu; jestli se plní, nevíme |
| `latestComments` | ano | jen s `keywordSearch`; jména smazat |

- **Cena a Free:** 0,0026 USD za výsledek na Free, 0,0023 na Starteru. Free vrací jen první stránku na hashtag; velikost stránky není uvedená (changelog z roku 2024 říkal 20).
- **Nástrahy:** jen nejnovější posty, žádné top. Posty a reels potřebují dva běhy. Brno nepoznáš z textu `locationName` (podnik „Café XY“ slovo Brno neobsahuje): posbírej různé `locationId`, rozliš je na souřadnice (actor 3, 0,0027 USD za místo) a filtruj podle Brna. Do reportu zapiš, kolik postů místo nemělo. Hodnocení actoru jen 3,49 z 91 recenzí.
- **Alternativa:** actor 1 se `searchType: popular`.

### 3. `apify/instagram-scraper`

- **K čemu:** kolo 0. Z URL místa autoři postů a souřadnice; souřadnice pro `locationId` z hashtagů. Volitelně typ účtu. [Stránka](https://apify.com/apify/instagram-scraper), [schéma](https://api.apify.com/v2/acts/apify~instagram-scraper/builds/default).
- **Vstup:** `directUrls` (pole URL; profil, post, reel, hashtag, místo `https://www.instagram.com/explore/locations/<id>/`, samotné ID stačí), `resultsType` (`posts` | `details` | `comments` | `reels` | `mentions`; `stories` skryté a zrušené), `resultsLimit` (na URL), `onlyPostsNewerThan`, `search` + `searchType` + `searchLimit` (ignorují se, když jsou `directUrls`), `addParentData`.

| Pole | Ověřeno | Poznámka |
|---|---|---|
| místo: `location_id`, `lat`, `lng`, `name`, `address` | ano | |
| místo: `posts` | ano | „poslední posty“, počet nejasný |
| místo: `posts[].username`, `code`, `taken_at`, `like_count` | ano | jiný tvar než posty, NE `ownerUsername` |
| post: `ownerUsername`, `locationName`, `locationId` | ano | jestli přijdou i pro URL místa, nejasné |
| post: `paidPartnership`, `sponsors` | ano | ve schématu |
| `statistics` (typ účtu 1 osobní, 2 firma, 3 tvůrce) | nejasné | jen v README FAQ s `addProfileStatistics`, ne ve schématu |

- **Cena a Free:** 0,0027 USD za výsledek každého typu na Free, 0,0023 na Starteru. Jedno místo je asi jedna položka (neověřeno). Free: komentáře asi 15 na post, zmínky asi 21.
- **Nástrahy:** README si odporuje, co vrací URL místa s `resultsType: posts`. Parser napiš na oba tvary. Jeden typ obsahu na běh. Otevřené issue z 8. 10. 2026: `inputUrl` se může lišit od zadané URL, páruj podle `location_id`. Otevřené issue ze 7. 10. 2026: hashtag v režimu posts nevrací reels.
- **Alternativa:** `apidojo/instagram-location-scraper` (sekce 9), ale jen na placeném plánu.

### 4. `apify/instagram-profile-scraper`

- **K čemu:** kola 1 až 3. Profily kandidátů s ~12 posty v jedné dávce. [Stránka](https://apify.com/apify/instagram-profile-scraper), [schéma](https://apify.com/apify/instagram-profile-scraper/input-schema).
- **Vstup:** `usernames` (pole, povinné; jména, URL nebo ID; počet neomezený), `includeAboutSection` (bool, výchozí false, jen placený plán).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `biography`, `followersCount`, `followsCount`, `verified`, `private`, `isBusinessAccount`, `businessCategoryName` | ano | |
| `externalUrl`, `externalUrls` | ano | položky `url`, `title`, `lynx_url`, `link_type` |
| `relatedProfiles` | ano | položky snake_case: `username`, `full_name`, `is_private`, `is_verified`; u malých účtů neověřeno |
| `postsCount`, `fbid`, `isRestrictedProfile`, `error` | ano | |
| `latestPosts[]`: `caption`, `hashtags`, `mentions`, `likesCount`, `commentsCount`, `type`, `timestamp`, `url`, `shortCode`, `isPinned`, `ownerUsername` | ano | asi 12, včetně starých připnutých |
| `latestPosts[].productType` | ano | `clips` = reel; u fotek chybí; příznak isReel neexistuje |
| `latestPosts[].taggedUsers` | ano | v ukázce u videa |
| `latestPosts[].videoViewCount` | ne | Instagram ho zrušil, u nových reels null |
| `latestPosts[].locationName` | nejasné | v žádné ukázce, počítej s tím, že chybí |
| `latestPosts[].coauthorProducers` | ne | potvrdila podpora Apify |
| `latestPosts[].paidPartnership` | nejasné | nezdokumentované, počítej s tím, že chybí |
| `about.country`, `about.date_joined`, `about.former_usernames` | ano | jen s `includeAboutSection`, jen v README ukázce; `former_usernames` je POČET změn jména, ne seznam |

- **Cena a Free:** 0,0026 USD za profil na Free, 0,0023 na Starteru. Doplněk About +0,006 USD na Starteru (ceník uvádí 0,007 i pro Free, ale schéma říká jen pro platící). Bez startovního poplatku. 60 profilů = 0,16 USD.
- **Nástrahy:** jeden omezený profil se zkouší asi 10krát a zdrží celou dávku (25 profilů: 32 s, s jedním omezeným 94 s). Data přijdou až po konci běhu, timeout klienta dej aspoň 3 minuty. Otevřené issue: veřejný profil občas vrátí prázdné `latestPosts` a běh je přesto SUCCEEDED; zopakuj, nevyřazuj. Připnuté posty vynech z aktivity za 30 dní. Lajky jsou počty, které vidí nepřihlášený; skryté lajky (null nebo -1) vynech z mediánu.
- **Alternativa:** actor 3 s `resultsType: details`.

### 5. `apify/instagram-post-scraper`

- **K čemu:** kola 2 a 3 (druhý běh pro 20 až 30 účtů: štítky, místa, komentáře) a kolo 4 (víc postů finalistů). [Stránka](https://apify.com/apify/instagram-post-scraper), [schéma](https://apify.com/apify/instagram-post-scraper/input-schema).
- **Vstup:** `username` (pole, povinné; jména, URL profilu i URL postů), `resultsLimit` (na profil, u URL postů se ignoruje), `onlyPostsNewerThan` (datum nebo „3 months“, UTC; má otevřený bug), `skipPinnedPosts` (bool, výchozí false), `dataDetailLevel` (`basicData` | `detailedData`; výchozí v API `detailedData`, v UI `basicData`, takže vždy uveď).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `caption`, `hashtags`, `mentions`, `taggedUsers`, `timestamp`, `likesCount`, `commentsCount`, `type`, `productType`, `isPinned`, `ownerUsername`, `url`, `shortCode` | ano | |
| `coauthorProducers` | ano | `id`, `username`, `is_verified` |
| `locationName`, `locationId` | ano | jestli i v `basicData`, nejasné |
| `paidPartnership`, `sponsors`, `affiliate` | ano | jen `detailedData`; na českých postech neověřeno |
| `latestComments`, `firstComment` | ano | jen `detailedData`, v ukázce 4 až 9 komentářů; jména smazat |
| `isSponsored` | ne | od 10. 12. 2025 zrušené, nečíst |

- **Cena a Free:** event `post` 0,0017 USD na Free a 0,0015 na Starteru, `post-details` +0,001 a +0,0008. Detail tedy 0,0027 a 0,0023 za post. Od 7. 10. 2026 navíc `music-data` 0,007 a 0,006 za fotku nebo carousel s hudbou; čím se spouští, není popsané. Free limit na počet položek uvedený není.
- **Nástrahy:** otevřené issue: `detailedData` vrátil 27 ze 43 postů, `basicData` vrátil duplikáty (deduplikuj podle `shortCode`). Otevřené issue: `onlyPostsNewerThan` vrací málo postů, když vlastník přeuspořádal mřížku, takže filtruj podle `timestamp` v kódu. Datum přebije `skipPinnedPosts`.
- **Alternativa:** `apify/instagram-reel-scraper` (sekce 7) pro reels.

### 6. `apify/instagram-comment-scraper`

- **K čemu:** kolo 3, jazyk komentářů a podíl obecných komentářů. Jen když nestačí `latestComments` z actoru 5. [Stránka](https://apify.com/apify/instagram-comment-scraper), [schéma](https://apify.com/apify/instagram-comment-scraper/input-schema).
- **Vstup:** `directUrls` (pole, povinné; URL `/p/`, `/reel/`, `/reels/`), `resultsLimit` (na post), `includeNestedComments` (jen placeně; FAQ ho chybně nazývá includeReplies).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `text`, `timestamp`, `likesCount`, `repliesCount`, `postUrl`, `commentUrl`, `id` | ano | |
| `ownerUsername`, `owner`, `ownerProfilePicUrl` | ano | vždy ve výstupu, smazat při načtení |
| `error`, `errorDescription` | ano | |

- **Cena a Free:** 0,0026 USD za komentář na Free, 0,0023 na Starteru. Free: 15 nejnovějších komentářů na post a bez odpovědí (popis vstupu a podpora Apify v září 2026; ověřovatel jiné skupiny tento limit v README nenašel, takže ho změř v T7).
- **Nástrahy:** věkově omezené posty dají asi 15 komentářů i na placeném plánu. Posty omezené na zemi vrátí 404.
- **Alternativa:** `latestComments` z actoru 5 v `detailedData`. Pro 12 účtů × 3 posty asi 0,10 USD místo 1,40 USD.

### 7. `apify/instagram-reel-scraper` (volitelně)

- **K čemu:** kolo 4, štítek placeného partnerství u reels, když actor 5 selže. [Stránka](https://apify.com/apify/instagram-reel-scraper).
- **Vstup:** `username` (pole; jména, URL, reels), `resultsLimit`, `onlyPostsNewerThan`, `skipPinnedPosts`, `skipTrialReels`, `includeSharesCount` (jen placeně), `includeTranscript` (drahé, nezapínat), `includeDownloadedVideo` (nezapínat).
- **Výstup:** `paidPartnership` ano (v ukázce `true` u tří reels z dubna a května 2026, sponzor `sephora`), `sponsors` ano, `locationName`, `coauthorProducers`, `taggedUsers`, `latestComments` (asi 10) ano.
- **Cena a Free:** reel 0,0026 USD na Free, 0,0023 na Starteru, plus 0,001 USD za start běhu. Přepis 0,048 USD za minutu, video 0,02 USD za MB.
- **Nástrahy:** `paidPartnership` se 18. 8. 2026 přestal vracet a ještě ten den ho opravili, takže ho ověř živě.

### 8. `apify/instagram-tagged-scraper` (volitelně)

- **K čemu:** kolo 0, doplňková cesta: kdo označuje brněnské podniky z T2 (`ig_business.profile.username`). [Stránka](https://apify.com/apify/instagram-tagged-scraper).
- **Vstup:** `username` (pole), `resultsLimit` (na profil).
- **Výstup:** `ownerUsername`, `locationName`, `locationId`, `coauthorProducers`, `timestamp` ano; `paidPartnership` jen ve schématu.
- **Cena a Free:** 0,0027 USD za post na Free, 0,0023 na Starteru. Free podle changelogu z roku 2024 max 20 na profil (možná zastaralé).

### 9. `apidojo/instagram-location-scraper` (na Free nepoužívat)

- **K čemu:** záloha pro posty z míst, jen na placeném plánu. [Stránka](https://apify.com/apidojo/instagram-location-scraper).
- **Vstup:** `startUrls`, `locationIds`, `maxItems`, `until` (navzdory jménu nechá posty od tohoto data dál), `customMapFunction` (nepoužívat k filtrování, hrozí ban).
- **Výstup:** `owner.username` (vnořené, ne `ownerUsername`), `coowners`, `location.id`, `location.name`, `location.city`, `location.lat`, `location.lng`, `isPaidPartnership`, `createdAt`, `url`, `caption` ano.
- **Cena a Free:** 0,0005 USD za post. Free = demo režim: 5 běhů měsíčně, max 10 položek na běh.
- **Nástrahy:** jen asi 54 uživatelů za 30 dní. Místa s méně než 10 posty můžou spustit jeho rate limiter.

### 10. `clockworks/tiktok-scraper`

- **K čemu:** kolo 0 na TikToku (hledání účtů), štítky u videí. [Stránka](https://apify.com/clockworks/tiktok-scraper), [schéma](https://api.apify.com/v2/acts/clockworks~tiktok-scraper/builds/default).
- **Vstup:** `searchQueries` (pole), `searchSection` (`""` top, `"/video"`, `"/user"` profily), `maxProfilesPerQuery` (výchozí 10, řídí `/user`), `resultsPerPage` (výchozí 1, vždy nastav), `profiles`, `hashtags`, `proxyCountryCode` (výchozí `"None"`, `"CZ"` je placený doplněk), `profileSorting`, `excludePinnedPosts`, `commentsPerPost` + `topLevelCommentsPerPost` + `maxRepliesPerComment` (placený doplněk), `scrapeAdditionalAuthorMeta`, `postURLs`.

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `textLanguage` | ano | jazyk popisku, ne zvuku; `un` = neznámý |
| `locationCreated` | ano | kód země; v ukázkách hledání a profilu chybí |
| `locationMeta.city`, `locationName`, `countryCode` | ano | jen u videí s označeným místem; u českých videí neověřeno |
| `isSponsored` | ano | štítek placeného partnerství; od 4. 9. 2026 i ve výsledcích hledání |
| `isAd` | ano | propagovaná reklama, ne spolupráce |
| `authorMeta.region` | nejasné | ve veřejných datech TikToku 8. 10. 2026 chybí, asi prázdné |
| `authorMeta.isUnderAge18` | nejasné | ve veřejných datech chybí, asi vždy null |
| `authorMeta.fans`, `privateAccount`, `verified`, `signature`, `bioLink` | ano | |
| `diggCount`, `commentCount`, `playCount`, `shareCount`, `collectCount`, `createTimeISO`, `webVideoUrl`, `hashtags`, `mentions` | ano | |
| `errorCode` | ano | `PROFILE_PRIVATE` = vyřadit v kole 1, `PROFILE_EMPTY` = mezera (i login zeď) |

- **Cena a Free:** výsledek 0,0037 USD na Free, 0,003 na Starteru. Start běhu 0,001 USD. CZ doplněk +0,0013 na Free, +0,001 na Starteru. Komentáře 0,00125 USD za kus. Strop ceny běhu min. 0,50 USD. Zvláštní limit pro Free není, 5 USD vystačí asi na 1 351 výsledků.
- **Nástrahy:** tvar položky u `/user` není popsaný. Changelog z roku 2023 říká, že najde profily a stáhne jejich videa, takže se asi účtuje profily × `resultsPerPage`. `proxyCountryCode` slouží k obsahu dostupnému jen v zemi; že lokalizuje řazení hledání, nikde nestojí. Actor si podle changelogu CAPTCHA řeší sám (rezidenční proxy, opakování); pro porotu: my žádnou CAPTCHA neřešíme a scraper nepíšeme.
- **Alternativa:** `clockworks/free-tiktok-scraper` („TikTok Data Extractor“). Navzdory jménu není zdarma: 0,003 USD na Free, bez startovního poplatku, stejný vstup i výstup. `clockworks/tiktok-user-search-scraper` je dražší (0,006 USD) a region nevrací.

### 11. `clockworks/tiktok-profile-scraper`

- **K čemu:** kola 1 až 3 na TikToku. [Stránka](https://apify.com/clockworks/tiktok-profile-scraper).
- **Vstup:** `profiles` (pole, povinné), `resultsPerPage` (výchozí 100, nastav 12), `profileSorting`, `excludePinnedPosts`, `profileScrapeSections`, `oldestPostDateUnified` a `newestPostDate` (placený filtr), `commentsPerPost`, `maxRepliesPerComment`. `proxyCountryCode` tu není.
- **Výstup:** stejné schéma jako actor 10. Sledující a statistiky videí ano, `region` a `isUnderAge18` nejasné.
- **Cena a Free:** 0,003 USD za výsledek na Free, 0,002 na Starteru, bez startovního poplatku. README (5 USD za 1000, Starter 29 USD) je zastaralé.
- **Nástrahy:** s výchozími 100 videi stojí 60 profilů asi 18 USD.

### 12. `clockworks/tiktok-comments-scraper` (volitelně)

- **K čemu:** kolo 3 na TikToku, jazyk komentářů. [Stránka](https://apify.com/clockworks/tiktok-comments-scraper).
- **Vstup:** `postURLs`, `commentsPerPost` (ve schématu bez výchozí hodnoty, vždy uveď, např. 30), `topLevelCommentsPerPost`, `maxRepliesPerComment` (0); nebo `profiles` + `resultsPerPage`.
- **Výstup:** `text`, `createTimeISO`, `diggCount`, `replyCommentTotal`, `videoWebUrl` ano. Pole jazyka ne, detekci děláme sami. `uid`, `uniqueId`, `avatarThumbnail`, `mentions`, `detailedMentions` ano, smazat.
- **Cena a Free:** 0,00125 USD za komentář na Free. Stejné komentáře dá doplněk `commentsPerPost` v actorech 10 a 11 za stejnou cenu.

### 13. `streamers/youtube-scraper`

- **K čemu:** kolo 4, finalisté na YouTube. První na škrt. [Stránka](https://apify.com/streamers/youtube-scraper), [schéma](https://api.apify.com/v2/acts/streamers~youtube-scraper/builds/default).
- **Vstup:** `startUrls` (pole `{url}`; video, kanál, playlist, stránka hledání; přebije `searchQueries`), `searchQueries`, `maxResults` (výchozí 0, vždy nastav), `maxResultsShorts`, `maxResultStreams`, `sortingOrder`, `dateFilter`, `videoType` (`video` | `movie`), `oldestPostDate` a `sortVideosBy` (placený doplněk).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `isPaidContent` | ano | = štítek „Includes paid promotion“; popis ve schématu („vyžaduje platbu“) je chybný; u výsledků hledání a výpisu kanálu nejasné |
| `channelLocation` | ano | země, kterou si kanál sám uvedl |
| `numberOfSubscribers`, `viewCount`, `likes`, `commentsCount`, `date`, `text`, `descriptionLinks`, `collaborators` | ano | |
| `error` | ano | ne `errorCode`; `AGE_RESTRICTED` = mezera |

- **Cena a Free:** 0,004 USD za video na Free, 0,003 na Starteru.
- **Nástrahy:** neumí hledat kanály ani filtrovat zemi. Kanál najdi přes odkazy v bio na IG a TikToku. Jen `true` je důkaz; spousta sponzorovaných videí štítek nemá.
- **Alternativa:** `streamers/youtube-channel-scraper` (0,0013 USD na Free, má `channelLocation`, nemá `isPaidContent`).

### 14. `apify/brand-collaboration-scraper`

- **K čemu:** kolo 4, štítkované spolupráce finalisty z Meta Ad Library (Branded Content). [Stránka](https://apify.com/apify/brand-collaboration-scraper), [schéma](https://api.apify.com/v2/acts/apify~brand-collaboration-scraper/builds/default), [recept Apify](https://github.com/apify/awesome-skills/blob/main/skills/apify-influencer-brand-collabs/SKILL.md).
- **Vstup:** `startUrls` (pole, povinné; URL profilu na IG nebo FB, nebo URL Meta Branded Content Library), `resultsLimit` (na URL; prázdné = bez limitu, vždy nastav), `onlyPostsNewerThan` (u URL profilu podle schématu nutné), `onlyPostsOlderThan`.

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `id`, `dateCreated` | ano | datum YYYY-MM-DD |
| `creator.name`, `creator.link` | ano | vždy tvůrce; z odkazu odstraň `/_u/` |
| `brandPartners[].name`, `brandPartners[].link` | ano | vždy značka |
| `type` | ano | post / reel / story |
| `link` | ano | URL zdroje tvrzení |
| `platform` | ano | ve schématu |
| lajky, zhlédnutí | ne | dotáhni actorem 5 nebo 7 |
| země tvůrce | ne | |

- **Cena a Free:** 0,0058 USD za položku na Free, 0,005 na Starteru. Limit pro Free není, 5 USD vystačí asi na 860 položek.
- **Nástrahy:** jen posty se štítkem Placené partnerství od 17. 8. 2023. Obsah s věkovým nebo místním omezením vidí jen přihlášení. Ruční test bez přihlášení 8. 10. 2026: Rohlík.cz 10 výsledků, ale 0 zobrazených řádků; Notino.cz 4, Alza 2, také 0; Nike 17 z 21 zobrazeno. Actor se rychle mění (build z 8. 10. 2026), na startu zkontroluj schéma. Prázdný výsledek = „nenalezeno v knihovně Meta“, ne „nemá spolupráce“. Z receptu převezmi: směr spolupráce podle toho, na které straně je cílový účet (ne podle `isBusinessAccount`), čištění `_u/` a `_n/`, přeskočení cest `p`, `reel`, `explore`.
- **Alternativa:** IG `paidPartnership` (actor 5), TikTok `isSponsored`, YouTube `isPaidContent`, hashtagy a slevové kódy v popiscích.

### 15. `data_xplorer/google-news-scraper-fast`

- **K čemu:** kolo 4, cílené zprávy o finalistovi. Komunitní actor, ne od Apify. [Stránka](https://apify.com/data_xplorer/google-news-scraper-fast), [schéma](https://api.apify.com/v2/acts/data_xplorer~google-news-scraper-fast/builds/default).
- **Vstup:** `keywords` (pole; podporuje uvozovky, `-`, `OR`, `site:`), `region_language` (`"CZ:cs"`, výchozí `"US:en"`), `timeframe` (`1h` | `1d` | `7d` | `30d` | `1y` | `all`, výchozí `1h`), `maxArticles` (na dotaz, výchozí 100), `decodeUrls` (výchozí false, README přitom tvrdí „automaticky“; nastav true), `extractDescriptions` (výchozí false), `extractImages` (výchozí true, nastav false).

| Pole | Ověřeno | Poznámka |
|---|---|---|
| `title`, `source`, `url`, `publishedAt`, `publishedTimestamp`, `image` | ano | `url` je přesměrování Googlu, pokud `decodeUrls` není true |
| `metadata.keyword`, `metadata.sourceType` | ano | |
| `description` | nejasné | asi jen s `extractDescriptions` |

- **Cena a Free:** 0,004 USD za článek na Free i Starteru, bez startovního poplatku. Limit pro Free není.
- **Nástrahy:** s výchozím `1h` cílený dotaz skoro jistě nic nenajde. Výchozích 100 článků stojí 0,40 USD na dotaz. Vlastní rozsah dat nejde, jen předvolby.
- **Alternativa:** `apify/google-search-scraper`: `queries` (dotaz na řádek), `countryCode: "cz"`, `searchLanguage: "cs"`, `languageCode: "cs"`, `quickDateRange` (např. `"y1"`), `maxPagesPerQuery: 1`. 0,0045 USD za stránku na Free, 0,0025 na Starteru, strop ceny min. 0,50 USD. Režim zpráv nemá, je to webové hledání. AI doplňky a leads nech vypnuté.

### 16. Konkurenti na Apify (jen pro srovnání, ne v běhu)

- `hypebridge/influencer-discovery-agent-instagram-tiktok`: brief v přirozeném jazyce, Instagram i TikTok, pole `location` přijme i město, výstup skóre 0 až 10. Start 1 USD za GB paměti (výchozí 1 GB) plus 0,15 USD za výsledek, takže 5 výsledků asi 1,75 USD. Za 30 dní skončilo 57 ze 139 běhů jako ABORTED. Pokud ho chceme jako srovnání v demu, pusť ho předem a výsledek cachuj. [Stránka](https://apify.com/hypebridge/influencer-discovery-agent-instagram-tiktok).
- `apify/influencer-discovery-agent`: jen TikTok, 0,10 USD za profil, max asi 50 profilů na běh. [Stránka](https://apify.com/apify/influencer-discovery-agent).
- Pro stavbu se hodí oficiální recept Apify na prověrku tvůrců ([influencer vetting](https://github.com/apify/agent-skills/blob/main/skills/apify-ultimate-scraper/references/workflows/influencer-vetting.md)).

## Cena jednoho plného běhu

Přepočteno z ověřených cen k 8. 10. 2026. Ceny v USD. „Jádro“ = Instagram bez kterého demo nejde.

| # | Krok | Actor | Množství | Free | Starter | Jádro |
|---|---|---|---|---|---|---|
| 1 | Kolo 0: hledání účtů IG | search-scraper `user` | 4 dotazy × 25 = 100 | 0,27 | 0,23 | ano |
| 2 | Kolo 0: hashtagy | hashtag-scraper | 300 postů (na Free asi 15 hashtagů) | 0,78 | 0,69 | ano |
| 3 | Kolo 0: místa v Brně | search-scraper `place` | 40 míst | 0,11 | 0,09 | ano |
| 4 | Kolo 0: posty z míst a souřadnice `locationId` | instagram-scraper | 20 míst + 100 `locationId` = 120 | 0,32 | 0,28 | ano |
| 5 | Kolo 0: TikTok hledání s CZ | tiktok-scraper | 3 dotazy × 10 profilů × 3 videa = 90 | 0,45 | 0,36 | ne |
| 6 | Kola 1 až 3: profily IG | profile-scraper | 60 | 0,16 | 0,14 | ano |
| 7 | Kola 1 až 3: profily TikTok | tiktok-profile-scraper | 20 × 12 videí = 240 | 0,72 | 0,48 | ne |
| 8 | Kola 2 a 3: štítky, místa, `latestComments` | post-scraper `detailedData` | 25 účtů × 12 = 300 | 0,81 | 0,69 | ano |
| 9 | Kolo 3: komentáře (jen když 8 nestačí) | comment-scraper | 12 × 3 posty × 15 = 540 | 1,40 | 1,24 | ne |
| 10 | Kolo 4: víc postů | post-scraper `detailedData` | 5 × 24 = 120 | 0,32 | 0,28 | ano |
| 11 | Kolo 4: Meta Branded Content | brand-collaboration-scraper | 5 × 20 = 100 | 0,58 | 0,50 | ne |
| 12 | Kolo 4: zprávy | google-news-scraper-fast | 5 × 3 dotazy × 10 = 150 | 0,60 | 0,60 | ne |
| 13 | Kolo 4: YouTube | youtube-scraper | 5 × 10 = 50 | 0,20 | 0,15 | ne |
| 14 | Kolo 4: TikTok komentáře | tiktok-comments-scraper | 5 × 3 × 30 = 450 | 0,56 | 0,56 (cena pro Starter neuvedena) | ne |
| | **Jádro (1, 2, 3, 4, 6, 8, 10)** | | | **2,77** | **2,40** | |
| | **Plný běh (vše)** | | | **7,28** | **6,29** | |
| | **Plný běh bez řádku 9** (komentáře z `latestComments`) | | | **5,88** | **5,05** | |

- **Riziko navíc:** pokud post-scraper v `detailedData` účtuje `music-data` (0,007 USD za fotku nebo carousel s hudbou), řádky 8 a 10 můžou v nejhorším případě stát až o 2,94 USD víc. Ověř v T6.
- **Nepočítáno:** startovní poplatky TikTok (0,001 USD za běh), doplněk About (0,006 USD × 5 finalistů, jen placeně), srovnávací běh hypebridge (asi 1,75 USD), testy v prvních 45 minutách (asi 1 USD).
- Plán (sekce 4) dřív uváděl kolem 2,5 USD. To odpovídá jen jádru na Instagramu.

### Free plán vs. Starter

- **Free:** 5 USD kreditu měsíčně, ceny tieru FREE, žádná sleva ([ceník Apify](https://apify.com/pricing)). Jádro se vejde jednou, plný běh (5,9 až 7,3 USD) ne. Navíc omezení: hashtagy jen první stránka, komentáře 15 nejnovějších na post, odpovědi na komentáře jen placeně, doplněk About jen placeně, počet sdílení reels jen placeně, `apidojo/instagram-location-scraper` jen demo (5 běhů × 10 položek).
- **Starter:** 19 USD měsíčně včetně 19 USD na spotřebu, ceny tieru BRONZE (u IG actorů asi o 12 až 15 % levnější, TikTok profily o 33 %). Vejdou se asi 3 plné běhy nebo asi 7 běhů jádra, s cache víc.
- **Doporučení:** na vývoj a demo Starter nebo kredity od Apify (otázka na mentory). Všechno cachovat podle hashe vstupu, živě stahovat jen nové dotazy. Na každý běh dát strop ceny.

## Datový kontrakt s aplikací

Kód: [`backend/app/sources/apify_provider.py`](../backend/app/sources/apify_provider.py). Psaný bez tokenu, 9. 10. 2026 zkontrolovaný proti živým testům (sekce „Výsledky živých testů 9. 10. 2026“). Zodpovězená místa nesou `# VERIFIED LIVE 2026-10-09:`, otevřená dál `# VERIFY LIVE:`; kde tvar zůstává neověřený, kód čte obě varianty a výchozí hodnota je `None`. Zbytek aplikace vidí jen normalizované modely z `backend/app/models.py` přes `SourceProvider` ([architecture.md](architecture.md), sekce 2).

### Jak to spustit

1. Do `.env` v kořeni repa: `SOURCE_MODE=apify` a `APIFY_TOKEN=...`. Volitelně:
   - `MAX_USD_PER_RUN=3`: strop na jeden běh actoru. Když odhad překročí strop, běh se nespustí. U post-scraperu se počítá nejhorší případ, tedy `music-data` u každého postu. Do Apify jde `max_total_charge_usd` = 2× odhad + 0,05 USD, nejvýš tento strop; TikTok vždy aspoň 0,50 (minimum actoru).
   - `APIFY_PLACES=1`: zapne cestu „místa v Brně“ (T2 + T4). Výchozí vypnuto.
   - `APIFY_POST_DETAIL=basicData`: když post-scraper účtuje `music-data` (T6). Výchozí `detailedData`.
   - `APIFY_COMMENTS_SOURCE=comments`: komentáře z comment-scraperu. Výchozí je od T6 `latest` (`latestComments` post-scraperu, asi 14krát levnější, až 15 na post).
   - `APIFY_TIKTOK_PROXY=None`: vypne placený doplněk CZ. Po T9 doporučujeme nechat CZ.
   - `APIFY_META_BRANDED=1`: zapne Meta Branded Content v `collabs()`. Výchozí vypnuto (T8).

   Konstanty v `apify_provider.py` nejsou proměnné prostředí, mění se úpravou souboru a restartem backendu: `TRUST_IG_FALSE_LABEL` (T6), `TRUST_TIKTOK_FALSE_LABEL` (T9), `TRUST_TIKTOK_REGION` (T10), `CITY_BBOX` (T2), `BRAND_WINDOW` (T8), `MIN_CHARGE_CAP_USD`.
2. Backend: `scripts/dev-backend.sh`. Každé volání actoru jde do živého logu s odhadem ceny, stropem běhu, účtovanou částkou a eventy. Účtovaná částka je max(`usageTotalUsd`, položky × cena): vyúčtované `usageTotalUsd` sedí na eventy, ale `call()` ho vrací dřív, než se dopočítá (T5, T8, T11, T12).
3. Jedno volání bez UI (zapíše i cache):

```bash
cd backend && .venv/bin/python -c "import asyncio, logging; logging.basicConfig(level='INFO'); \
from app.sources.factory import get_provider; p = get_provider('apify'); \
print(asyncio.run(p.profiles(['<jméno>'], 'instagram')))"
```

4. Testy bez tokenu: `cd backend && .venv/bin/python -m pytest -q tests/test_apify_mappers.py`. Vzorky v `backend/tests/apify_samples/` jsou ručně sestavené, se smyšlenými účty a hodnotami, ale mají tvar položek z živých testů 9. 10. 2026. Mappery na skutečných datech: přehrát uložené položky z `data/live-tests/`.

Bez tokenu konstruktor nespadne: každá metoda vrátí `[]` a do logu napíše „APIFY_TOKEN není nastavený“. Žádná metoda nevyhazuje výjimku do kol; chyba = `[]` plus řádek v logu. Neúspěšný běh se jednou zopakuje, ale ne po timeoutu klienta a ne po chybě API 4xx (špatný vstup, málo kreditu, nízký strop). Do odhadu útraty se počítá každý pokus.

### Která metoda volá který actor

| Metoda | Actor | Vstup (pevné limity) |
|---|---|---|
| `discover` (IG) | `apify/instagram-search-scraper` `user` s `liveSearch`, jeden běh na dotaz | `searchLimit` 25, max 4 dotazy, město se do dotazu doplní; účty bez města v handlu, jménu ani bio se vyřadí |
| `discover` (IG) | `apify/instagram-hashtag-scraper`, jeden běh na hashtag | `resultsLimit` 50, max 10 hashtagů, `keywordSearch` false |
| `discover` (IG) | `apify/instagram-scraper` `details` | souřadnice pro max 40 různých `locationId` z hashtagů |
| `discover` (IG, `APIFY_PLACES=1`) | search-scraper `place`, pak instagram-scraper `details` | 30 míst na dotaz; autoři z vnořených `posts` (jen poslední rok); instagram-scraper jen pro max 10 míst v Brně bez `posts`, 1 výsledek za místo |
| `discover` (TikTok) | `clockworks/tiktok-scraper` `/user` | `maxProfilesPerQuery` 10, `resultsPerPage` 3, max 3 dotazy |
| `profiles` (IG) | `apify/instagram-profile-scraper` | dávky po 50, `includeAboutSection` false; prázdné `latestPosts` u veřejného profilu jednou znovu |
| `profiles` (TikTok) | `clockworks/tiktok-profile-scraper` | dávky po 20, `resultsPerPage` 12, `excludePinnedPosts` |
| `posts` (IG) | `apify/instagram-post-scraper` | `resultsLimit` max 50, `skipPinnedPosts`, `dataDetailLevel`; bez `onlyPostsNewerThan`, datum filtrujeme v kódu, duplikáty podle `shortCode` |
| `posts` (TikTok) | `clockworks/tiktok-profile-scraper` | `resultsPerPage` = limit, datum v kódu |
| `posts` (YouTube) | `streamers/youtube-scraper`, URL kanálu | `maxResults` = limit, Shorts a streamy 0, datum v kódu |
| `comments` (IG) | post-scraper `latestComments` (výchozí `latest`, `skipPinnedPosts` false), nebo `apify/instagram-comment-scraper` při `comments` | max 40 postů na platformu × 15; zbytek log počítá zvlášť od nepodporovaných URL |
| `comments` (TikTok) | `clockworks/tiktok-comments-scraper` | `commentsPerPost` 15, `maxRepliesPerComment` 0 |
| `collabs` | `apify/brand-collaboration-scraper`, jen s `APIFY_META_BRANDED=1` | `resultsLimit` 20, `onlyPostsNewerThan` „12 months“; jen Instagram |
| `news` | `data_xplorer/google-news-scraper-fast` | `CZ:cs`, `timeframe` 1y, `maxArticles` max 20, `decodeUrls` true, `extractImages` false |
| `find_cross_platform` | žádné hledání | jen odkazy z bio a `externalUrl(s)`; IG a TikTok profil se stáhne profile-scraperem, YouTube vrací jen odkaz |

### Co který mapper plní

Všechny mappery jsou čisté funkce (`map_*`), každý objekt má `source.mode = "live"`, `source.actor` = id actoru a `fetched_at`.

- `map_ig_profile` → `Profile`: `handle` (`username`; když chybí, nejčastější `latestPosts[].ownerUsername`, a když nejsou posty, požadované jméno při dávce o jednom účtu), `display_name` (`fullName`, jinak prázdné), `bio`, `followers`, `following`, `posts_count`, `verified`, `private`, `is_business`, `business_category` („None,“ zahozeno), `external_urls` (`externalUrl` + `externalUrls[].url`, bez `lynx_url`), `related_handles`, `former_handles_count` (jen s About), `latest_posts` (post vlastněný partnerem dostane profil do `coauthors`). `region` a `is_under_18` zůstávají `None`.
- `map_ig_post` → `Post`: `id` `ig:post:<shortCode>`, `caption`, `hashtags`, `mentions`, `coauthors`, `tagged_users` (jen jména), `media_type` (`clips` = reel), `likes`/`comments` (skryté -1 = `None`), `views` z `videoViewCount` (u reels z profile-scraperu), `location_name`, `location_id`, `is_pinned`, `sponsors`, `paid_partnership`. Štítek: `True` bereme vždy. `False` jen z post-scraperu v `detailedData` a jen se zapnutou konstantou `TRUST_IG_FALSE_LABEL` (vypnutá do T6, protože `compute/collabs.py` čte `False` jako neoznačenou reklamu); jinak `None`. Hashtagy a zmínky z popisku jsou bez koncové tečky.
- `map_ig_search_user`, `map_ig_related` → `CandidateRef` s `found_via` `search:<dotaz>` a `related:@<účet>`. Hashtagy dávají `hashtag:<tag>` a při potvrzeném místě i `place:<locationName>`. Výsledek `discover` je sloučený podle účtu.
- `map_ig_place` + `place_verdict`: Brno podle souřadnic (`CITY_BBOX`), text `locationName` jen potvrzuje. Vyřadí se jen post se souřadnicemi mimo Brno; post bez místa zůstává (lokalitu řeší kolo 3).
- `map_ig_comment`, `map_ig_latest_comments`, `map_tt_comment` → `Comment`: jen `text`, čas a URL postu. Jména, id, avatary ani `commentUrl` se nečtou; `@zmínky` v textu se mění na `@user`.
- `map_tt_video`, `map_tt_profiles`, `map_tt_search`: handle a id videa z `webVideoUrl` (jinak `authorMeta.profileUrl` a `name`), `likes`/`comments`/`views` z `diggCount`/`commentCount`/`playCount`, `paid_partnership` = `isSponsored` jen `true` (`false` platí až po zapnutí `TRUST_TIKTOK_FALSE_LABEL`; `isAd` ne), `location_name` = „`locationMeta.locationName`, město“ (prázdné `city` nahradí `address`), `location_id`, `is_pinned`, `language` = `textLanguage` (`un` = `None`), `display_name` = `nickName`, `followers` = `fans`, `following`, `posts_count` = `video`, `bio` = `signature`, `external_urls` = `bioLink`, `PROFILE_PRIVATE` = soukromý profil, `PROFILE_EMPTY` = mezera. Položka `note` (profil bez videí) se v hledání přeskočí.
- `map_brand_collab` → `CollabEvidence` `meta_branded`, `disclosed` true, značka z `brandPartners[]` (je to handle), datum z `dateCreated`, `/_u/` odstraněno, `post_id` z odkazu na post.
- `map_yt_video` → `Post` `yt:video:<id>`: autor `channelUsername`, `likes`, `commentsCount`, `viewCount`, `paid_partnership` jen při `isPaidContent` true. Řádek, kde je tvůrce (`creator.link`) jiný účet na IG než náš, se zahodí: náš účet je na straně značky, nebo jde o cizí spolupráci.
- `map_news` → `NewsItem` s `id` `news:<hash URL>`.

Nezletilí: profil s výslovným věkem pod 18 v bio (`compute/minors.py`) nebo TikTok `isUnderAge18: true` (živě ten klíč chybí, T10) se zahodí ještě v provideru a do logu jde jen počet. U autorů z hashtagů bio nemáme, ty odchytí `profiles()` a kolo 1.

Nová volitelná pole v modelech (výchozí `None` / `[]`, v JSON se nevypisují, dokud nejsou vyplněná): `Post.location_id`, `Post.is_pinned`, `Post.sponsors`, `Profile.former_handles_count`. Potřebují pydantic 2.12 nebo novější; se starším `models.py` při importu varuje.

### Místa `# VERIFY LIVE`

`grep -n "VERIFY LIVE" backend/app/sources/apify_provider.py`:

**Stav po 9. 10. 2026:** zodpovězeno 1 až 3, 5 až 8, 10, 12 až 16, 18 až 23 (v kódu `# VERIFIED LIVE 2026-10-09:`, souhrn v sekci „Výsledky živých testů“). Otevřené zůstávají 4 (přejmenované účty), 9 (štítek na českém postu, `TRUST_IG_FALSE_LABEL` dál `False`), 11 (co spouští `music-data`, 0krát na 24 postech) a 17 (štítkované české TikTok video, `TRUST_TIKTOK_FALSE_LABEL` teď `False`). Původní seznam:

Instagram:

1. `username` v profile-scraperu (T5): ve vaší tabulce není. Když chybí, handle se bere z `latestPosts[].ownerUsername`; log řekne, kolik položek bylo bez `username`.
2. `fullName` v profile-scraperu (ověřené jen u search-scraperu); bez něj je `display_name` prázdné.
3. `type` u IG postů: hodnoty (čekáme Image, Video, Sidecar). Hashtag-scraper ho v tabulce nemá, bez něj vyjde `other` (reel podle `productType`).
4. Přejmenované účty: nese položka původní jméno? Pak ho dej do `former_handles`.
5. `relatedProfiles` u malých účtů (T1, T5).
6. Místa ze search-scraperu: `posts` pole nebo text, jméno místa (`name`) (T2).
7. URL místa v instagram-scraperu (T4): který `resultsType` dá `lat`/`lng`, jestli přijdou posty, nebo místo s `posts[]`, a jestli posty nesou `locationId`. Když ne, pouštěj jedno místo na běh (actor nemá startovní poplatek).
8. `CITY_BBOX` pro Brno (náš odhad, T2).
9. `paidPartnership: false` (T6): dokud nevíš, že štítkovaný český post vrací `true`, `False` se zahazuje. Když ano, nastav `TRUST_IG_FALSE_LABEL = True`.
10. Klíče položek `sponsors[]`, `latestComments[]` (`text`, `timestamp`) a `taggedUsers[]` (`username`) (T6).
11. `music-data` (T6): které posty ho spouštějí a jestli i v `basicData`.

TikTok:

12. Popisek: čteme `text` (pole je ověřené jen v comments-scraperu).
13. `hashtags`/`mentions`: tvar položek (texty, nebo objekty; jinak se berou z popisku).
14. `locationName`: v `locationMeta`, nebo nahoře? Čteme obojí.
15. Jméno, počet sledovaných a videí v `authorMeta`: v předávce nejsou, zatím prázdné.
16. `isUnderAge18` a `region` (T10); region je vypnutý přes `TRUST_TIKTOK_REGION`.
17. `isSponsored: false` (T9): když štítkované české video vrátí `false` nebo nic, nastav `TRUST_TIKTOK_FALSE_LABEL = False`.
18. `/user` (T9): tvar položky a klíč s URL profilu; bez `webVideoUrl` bereme jen jediný odkaz `tiktok.com/@` mimo bio.

Ostatní:

19. `source` u zpráv: text, nebo objekt.
20. `BRAND_WINDOW` „12 months“ (T8 testoval „6 months“).
21. Verze klienta: podporuje `max_total_charge_usd`? Když ne, log to řekne a strop hlídá jen odhad.
22. Minimální strop ceny: známe jen u `clockworks/tiktok-scraper` (0,50). Když Apify odmítne běh kvůli nízkému `max_total_charge_usd`, doplň actor do `MIN_CHARGE_CAP_USD`.
23. `usageTotalUsd`: je to u pay-per-event actorů účtovaná částka? Porovnej s Billing a s eventy.

### Cache pro demo

1. Jednou živě se `SOURCE_MODE=apify`: každá odpověď se uloží do `data/cache/<hash>.json` (jen normalizovaná data, bez jmen komentujících a bez nezletilých). Opakovaný běh už nestahuje.
2. Demo se `SOURCE_MODE=cache`: přehrává cache. Je jen pro čtení (co v cache není, vrátí `[]` a zaloguje), i když je v `.env` token; chybějící se dotáhne živě jen s `CACHE_FILL_MISSES=1` a tokenem.
3. Předání týmu: zabal `data/cache/` a pošli. Import u ostatních: `cd backend && .venv/bin/python -m app.sources.cache import <adresář>` (soubory se znovu validují do modelů, dávky profilů a komentářů se rozdělí po účtech a URL). Smazání: `python -m app.sources.cache purge` nebo tlačítko Smazat data.
4. Cache je klíčovaná přesnými argumenty metody. Demo proto pusť se stejným briefem a dotazy jako živý běh.
5. Neúplný `discover`: když dílčí běh selže, přeskočí se kvůli stropu nebo skončí předčasně, log napíše „VÝSLEDEK NEÚPLNÝ“ a jméno souboru v cache. Cache ho přesto uloží (`cache.py` příznak `last_discover_incomplete` zatím nečte), takže ten soubor smaž a `discover` pusť znovu, než cache předáš týmu.

### Co říct týmu po prvním živém běhu

- [ ] Které actory fungují a co škrtáme (T1 až T12): Meta Branded Content, místa, TikTok, YouTube, zprávy.
- [ ] Plní se `paidPartnership` (T6)? Když ne, komerční nasycenost a označování jen z popisků. Když ano i pro `false`, zapni `TRUST_IG_FALSE_LABEL` (konstanta v kódu).
- [ ] Stačí `latestComments`? Pak `APIFY_COMMENTS_SOURCE=latest`.
- [ ] TikTok `region` a `isUnderAge18` (T10): zapnout `TRUST_TIKTOK_REGION`, nebo ne (konstanta v `apify_provider.py`, ne proměnná prostředí).
- [ ] Skutečné ceny proti odhadu (účtované eventy, hlavně `music-data`) a nastavený `MAX_USD_PER_RUN`.
- [ ] Opravená pole z `# VERIFY LIVE` (hlavně TikTok jméno a popisek).
- [ ] Kolik kandidátů dala každá cesta hledání a kolik hashtagových postů mělo místo (čísla do pitche).
- [ ] Kde je cache a jak ji importovat (adresář, příkaz výše).
- [ ] Nová pole pro ostatní: `Post.is_pinned` (metriky můžou vynechat připnuté posty z aktivity), `Post.sponsors` (collabs.py může brát značku ze štítku), `Post.location_id`, `Profile.former_handles_count`.
