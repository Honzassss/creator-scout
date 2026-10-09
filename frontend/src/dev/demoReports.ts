// MOCK round-4 reports for the demo. Two are detailed (the exclusivity conflict and the unlabeled discount code);
// the other finalists get a shorter, still honest report. All names, brands and outlets are fictional.

import { isoDate, postSrc, profileSrc, src } from './demoData'
import type { CollabEvidence, CriterionResult, Finding, I18nText, NewsItem, Report, SourceRef } from '../types'

const T = (cs: string, en: string): I18nText => ({ cs, en })

export const NOT_CHECKED: I18nText[] = [
  T('Smlouvy a soukromé zprávy: nejsou veřejné.', 'Contracts and private messages: not public.'),
  T('Lajky a komentující: lajky nestahujeme, jména komentujících neukládáme.', 'Likes and commenters: we do not fetch likes or store commenter names.'),
  T('Názory, víra, zdraví, soukromí a povaha tvůrce: záměrně nekontrolujeme.', 'Views, religion, health, private life and personality: deliberately not checked.'),
  T('Věk, pohlaví a původ publika: z veřejných dat zjistit nejde a neodhadujeme je.', 'Audience age, gender and origin: not knowable from public data; we do not estimate them.'),
  T('Trestní věci: nebereme (čl. 10 GDPR).', 'Criminal matters: out of scope (GDPR Art. 10).'),
]

const GAP_DEMOGRAPHICS = (id: string): Finding => ({
  id,
  kind: 'gap',
  section: 'engagement',
  text: T('Věk, pohlaví a původ publika z veřejných dat nezjistíme. Otázka pro tvůrce.', 'Audience age, gender and origin are not in public data. A question for the creator.'),
  sources: [],
})

const news = (id: string, title: string, outlet: string, date: string, snippet: string): NewsItem => {
  const url = `https://news.mock.invalid/${id}`
  return {
    id,
    title,
    outlet,
    url,
    published_at: date,
    snippet,
    source: src(`news:${id}`, 'news', url, { actor: 'mock:google-news-scraper', quote: snippet.slice(0, 160) }),
  }
}

const collab = (
  id: string,
  brand: string,
  handle: string | null,
  kind: CollabEvidence['kind'],
  disclosed: boolean | null,
  date: string,
  source: SourceRef,
  is_competitor = false,
): CollabEvidence => ({ id, brand, brand_handle: handle, kind, disclosed, date, post_id: source.id, is_competitor, source })

// ---------------------------------------------------------------------------------------------
// 1) @mlsna_brnenka: bio claims exclusivity with @pekarna_a, but two posts are co-authored with
//    competitor @pekarna_b (one without any ad label).
// ---------------------------------------------------------------------------------------------

const MB = 'mlsna_brnenka'
const mbBio = 'Brno · jídlo · rodina | exkluzivní ambasador @pekarna_a | spolupráce: e-mail v odkazu'
const mbP0909 = postSrc(MB, 'instagram', 'B9k2', 'Placená spolupráce s @pekarna_b · Nový kváskový bochník, ochutnali jsme ho celá rodina')
const mbP0921 = postSrc(MB, 'instagram', 'C1x7', 'S @pekarna_b jsme pekly koláče pro sousedy. Kdo si dá?')
const mbP0815 = postSrc(MB, 'instagram', 'A7m3', 'Spolupráce s @pekarna_a #spoluprace · celozrnné rohlíky')
const mbP0514 = postSrc(MB, 'instagram', 'A1q8', '#reklama Snídaně s @pekarna_a')
const mbP0702 = postSrc(MB, 'instagram', 'A4z0', 'Mouka od @mlyn_zrnko_mock na domácí pizzu')
const mbTt = src('tt:profile:mlsna.brnenka', 'tiktok', 'https://tiktok.mock.invalid/mlsna.brnenka', {
  actor: 'mock:tiktok-profile-scraper',
  quote: 'IG: @mlsna_brnenka · kolacky.mock.invalid',
})
const mbFan = src('ig:profile:mlsna_brnenka_fan', 'instagram', 'https://instagram.mock.invalid/mlsna_brnenka_fan', {
  quote: 'Fan page · všechny fotky patří @mlsna_brnenka',
})
const mbNews1 = news(
  'n-olomouc-kolackova',
  'Cukrářka Jana Koláčková z Olomouce vyhrála krajskou soutěž (MOCK)',
  'Hanácké listy (MOCK)',
  isoDate(2026, 6, 3),
  'Olomoucká cukrářka Jana Koláčková zvítězila v krajské soutěži s tvarohovými koláči.',
)
const mbNews2 = news(
  'n-rada-pekarna-b',
  'Stížnost na neoznačené spolupráce pekárny s tvůrci (MOCK)',
  'Jihomoravský zpravodaj (MOCK)',
  isoDate(2026, 9, 29),
  'Podle zpravodaje dostala Rada pro reklamu stížnost na neoznačené příspěvky Pekárny B. Rada zatím nerozhodla.',
)

const mbCollabs: CollabEvidence[] = [
  collab('cb-mb-1', 'Pekárna A (MOCK)', 'pekarna_a', 'ad_hashtag', true, isoDate(2026, 5, 14), mbP0514),
  collab('cb-mb-2', 'Mlýn Zrnko (MOCK)', 'mlyn_zrnko_mock', 'tag', null, isoDate(2026, 7, 2), mbP0702),
  collab('cb-mb-3', 'Pekárna A (MOCK)', 'pekarna_a', 'paid_label', true, isoDate(2026, 8, 15), mbP0815),
  collab('cb-mb-4', 'Pekárna B (MOCK)', 'pekarna_b', 'coauthor', true, isoDate(2026, 9, 9), mbP0909, true),
  collab('cb-mb-5', 'Pekárna B (MOCK)', 'pekarna_b', 'coauthor', false, isoDate(2026, 9, 21), mbP0921, true),
]

export const REPORT_MLSNA: Report = {
  candidate_id: `instagram:${MB}`,
  findings: [
    {
      id: 'F1',
      kind: 'fact',
      section: 'collabs',
      text: T('2 společné posty s @pekarna_b (9. 9. a 21. 9. 2026).', '2 co-authored posts with @pekarna_b (9 Sep and 21 Sep 2026).'),
      sources: [mbP0909, mbP0921],
      relevance: ['c_competitors'],
    },
    {
      id: 'F2',
      kind: 'fact',
      section: 'collabs',
      text: T(
        'Post z 21. 9. 2026 s @pekarna_b nemá štítek spolupráce ani #reklama.',
        'The 21 Sep 2026 post with @pekarna_b has no partnership label and no #ad.',
      ),
      sources: [mbP0921],
      relevance: ['c_disclose'],
    },
    {
      id: 'F3',
      kind: 'fact',
      section: 'profile',
      text: T('Bio uvádí „exkluzivní ambasador @pekarna_a“.', 'The bio says “exclusive ambassador @pekarna_a”.'),
      sources: [profileSrc(MB, 'instagram', mbBio)],
    },
    {
      id: 'F4',
      kind: 'inference',
      section: 'claims',
      text: T(
        'Spolupráce s @pekarna_b po 9. 9. 2026 nejspíš odporuje tvrzené exkluzivitě s @pekarna_a. Podmínky smlouvy ale neznáme.',
        'Working with @pekarna_b after 9 Sep 2026 likely contradicts the claimed exclusivity with @pekarna_a. We do not know the contract terms.',
      ),
      sources: [],
      based_on: ['F1', 'F3'],
    },
    {
      id: 'F5',
      kind: 'fact',
      section: 'content',
      text: T('21 z 24 postů je o jídle, rodině nebo podnicích.', '21 of 24 posts are about food, family or cafés.'),
      sources: [postSrc(MB, 'instagram', 1), postSrc(MB, 'instagram', 2)],
    },
    {
      id: 'F6',
      kind: 'fact',
      section: 'engagement',
      text: T('Medián interakcí 3,1 % sledujících za 24 postů; 86 % ze 60 komentářů česky.', 'Median engagement 3.1% of followers over 24 posts; 86% of 60 comments in Czech.'),
      sources: [profileSrc(MB, 'instagram'), postSrc(MB, 'instagram', 1)],
    },
    GAP_DEMOGRAPHICS('F7'),
    {
      id: 'F8',
      kind: 'gap',
      section: 'claims',
      text: T('Nevíme, jestli a kdy exkluzivita s @pekarna_a skončila.', 'We do not know whether or when the exclusivity with @pekarna_a ended.'),
      sources: [],
    },
    {
      id: 'F9',
      kind: 'fact',
      section: 'identity',
      text: T('TikTok @mlsna.brnenka v bio odkazuje na IG @mlsna_brnenka a stejný web.', 'TikTok @mlsna.brnenka links to IG @mlsna_brnenka and the same website.'),
      sources: [mbTt],
    },
    {
      id: 'F10',
      kind: 'fact',
      section: 'news',
      text: T(
        'Hanácké listy (MOCK) 3. 6. 2026 píšou o cukrářce Janě Koláčkové z Olomouce.',
        'Hanácké listy (MOCK) wrote on 3 Jun 2026 about a pastry chef Jana Koláčková from Olomouc.',
      ),
      sources: [mbNews1.source],
    },
    {
      id: 'F11',
      kind: 'inference',
      section: 'identity',
      text: T(
        'Článek se týká jiné osoby se stejným jménem (jiné město, jiný obor). Do profilu ho nezapočítáváme.',
        'The article is about a different person with the same name (different city and field). Not counted.',
      ),
      sources: [],
      based_on: ['F10', 'F3'],
    },
  ],
  claims: [
    {
      id: 'K1',
      claim: 'exkluzivní ambasador @pekarna_a',
      claim_source: profileSrc(MB, 'instagram', mbBio),
      evidence: ['cb-mb-4', 'cb-mb-5', 'F1'],
      status: 'conflicts_with_record',
      confidence: 'high',
      note: T(
        '2 společné posty s konkurenční @pekarna_b, 9. 9. a 21. 9. 2026. Jistota vysoká: jde o vlastní posty tvůrkyně.',
        '2 co-authored posts with competitor @pekarna_b, 9 and 21 Sep 2026. High confidence: these are the creator’s own posts.',
      ),
    },
    {
      id: 'K2',
      claim: 'Placená spolupráce s @pekarna_b',
      claim_source: mbP0909,
      evidence: ['cb-mb-4'],
      status: 'supported',
      confidence: 'high',
      note: T('Post má platformní štítek placené spolupráce.', 'The post carries the platform’s paid-partnership label.'),
    },
  ],
  collab_timeline: mbCollabs,
  news: [
    { item: mbNews2, label: 'allegation', attribution: 'píše Jihomoravský zpravodaj (MOCK)' },
    { item: mbNews1, label: 'neutral', attribution: 'píšou Hanácké listy (MOCK)' },
  ],
  identity: [
    {
      handle: 'mlsna.brnenka',
      platform: 'tiktok',
      status: 'matched',
      signals: [
        { signal: T('TikTok bio odkazuje na IG @mlsna_brnenka', 'the TikTok bio links to IG @mlsna_brnenka'), supports: true, source: mbTt },
        { signal: T('stejný web kolacky.mock.invalid', 'same website kolacky.mock.invalid'), supports: true, source: mbTt },
      ],
    },
    {
      handle: 'mlsna_brnenka_fan',
      platform: 'instagram',
      status: 'rejected',
      signals: [
        { signal: T('fanouškovský účet: jen sdílí její posty s uvedením autorky', 'fan account: only reshares her posts with credit'), supports: false, source: mbFan },
      ],
    },
    {
      handle: 'Jana Koláčková (Olomouc)',
      platform: 'news',
      status: 'rejected',
      signals: [
        { signal: T('stejné jméno', 'same name'), supports: true, source: mbNews1.source },
        { signal: T('jiné město: Olomouc, ne Brno', 'different city: Olomouc, not Brno'), supports: false, source: mbNews1.source },
        { signal: T('jiný obor: cukrářská soutěž, ne tvorba obsahu', 'different field: a pastry contest, not content creation'), supports: false, source: mbNews1.source },
      ],
    },
  ],
  questions: [
    T('Jaké jsou podmínky ambasadorství s @pekarna_a (exkluzivita, období, obor)?', 'What are the terms of the @pekarna_a ambassadorship (exclusivity, period, category)?'),
    T('Proč post z 21. 9. 2026 s @pekarna_b nemá označení spolupráce?', 'Why does the 21 Sep 2026 post with @pekarna_b carry no partnership label?'),
    T('Spolupracujete teď s jinou pekárnou v Brně?', 'Are you currently working with another bakery in Brno?'),
    T('Můžete poslat statistiky publika z aplikace (lokalita, dosah)?', 'Can you share audience statistics from the app (location, reach)?'),
  ],
  outreach_draft: {
    cs: 'Dobrý den, Jano,\n\njsme malá pekárna v Brně a líbí se nám, jak ukazujete pečení s rodinou. Chystáme nový kváskový chléb a hledáme tvůrce z Brna.\n\nVidíme, že spolupracujete s @pekarna_a i @pekarna_b. Než se domluvíme, potřebovali bychom vědět, jestli vám smlouvy dovolují spolupráci s další pekárnou.\n\nPokud ano, rádi vám pošleme podrobnosti.\n\nDěkujeme,\n[vaše jméno]',
    en: 'Hello Jana,\n\nwe are a small bakery in Brno and we like how you show baking with your family. We are launching a new sourdough bread and are looking for creators from Brno.\n\nWe see you work with both @pekarna_a and @pekarna_b. Before we talk further, we would need to know whether your contracts allow working with another bakery.\n\nIf they do, we would be happy to send details.\n\nThank you,\n[your name]',
  },
  not_checked: NOT_CHECKED,
  skeptic_notes: [
    T(
      'F4 stojí na dvou postech; exkluzivita mohla skončit před 9. 9. 2026. Ponecháno jako inference, ne fakt.',
      'F4 rests on two posts; the exclusivity may have ended before 9 Sep 2026. Kept as inference, not fact.',
    ),
    T('Zpráva o Janě Koláčkové z Olomouce je jmenovec; nezapočítáno.', 'The news about Jana Koláčková from Olomouc is a namesake; not counted.'),
    T(
      'Zpráva Jihomoravského zpravodaje je obvinění vůči pekárně, ne vůči tvůrkyni, a Rada zatím nerozhodla.',
      'The Jihomoravský zpravodaj item is an allegation against the bakery, not the creator, and the Council has not decided.',
    ),
  ],
  sensitive_filtered: 1,
}

export const R4_MLSNA: CriterionResult[] = [
  {
    criterion_id: 'c_competitors',
    status: 'fail',
    value: T('2 společné posty s @pekarna_b (9. 9. a 21. 9. 2026)', '2 co-authored posts with @pekarna_b (9 Sep and 21 Sep 2026)'),
    threshold: T('žádná spolupráce s @pekarna_b za 6 měsíců', 'no collaboration with @pekarna_b in 6 months'),
    sources: [mbP0909, mbP0921],
  },
  {
    criterion_id: 'c_disclose',
    status: 'fail',
    value: T('1 z 5 spoluprací bez označení (21. 9. 2026)', '1 of 5 collaborations without a label (21 Sep 2026)'),
    threshold: T('každá spolupráce označená', 'every collaboration labeled'),
    sources: [mbP0921],
  },
]

// ---------------------------------------------------------------------------------------------
// 2) @snidane_s_tomasem: "recenze, nikdo mi neplatí" while a post carries discount code TOMAS15
//    and an affiliate link, no label found. Plus an unverifiable "120k community" claim.
// ---------------------------------------------------------------------------------------------

const ST = 'snidane_s_tomasem'
const stBio = 'Snídaně po Brně ☕ komunita 120 tisíc | recenze, nikdo mi neplatí'
const stP0912 = postSrc(ST, 'instagram', 'D3r5', 'Recenze, nikdo mi neplatí :) Džemy od @dzemy_kopecek_mock, s kódem TOMAS15 máte 15 % → odkaz v bio')
const stP0620 = postSrc(ST, 'instagram', 'B0h1', 'Placená spolupráce · Kavárna Zrnko, nová snídaňová karta')
const stP0803 = postSrc(ST, 'instagram', 'C2c9', '#reklama Granola od @granola_hrstka_mock')
const stP0927 = postSrc(ST, 'instagram', 'E8u4', 'Mléko z @mlekarna_louka_mock do kávy')
const stLink = src('web:link:tomas-ref', 'web', 'https://dzemy-kopecek.mock.invalid/?ref=tomas', {
  actor: 'mock:link-resolver',
  quote: 'odkaz v bio vede na e-shop s parametrem ?ref=tomas',
})
const stTt = src('tt:profile:snidane.s.tomasem', 'tiktok', 'https://tiktok.mock.invalid/snidane.s.tomasem', {
  actor: 'mock:tiktok-profile-scraper',
  quote: '79,1 tis. sledujících · IG: @snidane_s_tomasem',
})
const stYt = src('yt:channel:tomas-snidanovy', 'youtube', 'https://youtube.mock.invalid/@tomassnidanovy', {
  actor: 'mock:youtube-channel-scraper',
  quote: 'Tomáš Snídaňový · 3 videa, poslední 2023',
})
const stFan = src('ig:profile:tomas_snidane_fans', 'instagram', 'https://instagram.mock.invalid/tomas_snidane_fans', { quote: 'fanklub, neoficiální' })
const stNews = news(
  'n-brno-snidane-tipy',
  'Brněnské snídaně: pět tipů od místních tvůrců (MOCK)',
  'Brněnské listy (MOCK)',
  isoDate(2026, 8, 22),
  'Tvůrci z Brna doporučují podniky se snídaní; mezi nimi Tomáš Snídaňový.',
)

export const REPORT_SNIDANE: Report = {
  candidate_id: `instagram:${ST}`,
  findings: [
    {
      id: 'F1',
      kind: 'fact',
      section: 'collabs',
      text: T('2 ze 4 značek v posledních 24 postech jsou označené jako reklama.', '2 of 4 brands in the last 24 posts are labeled as ads.'),
      sources: [stP0620, stP0803],
    },
    {
      id: 'F2',
      kind: 'fact',
      section: 'collabs',
      text: T(
        'Post z 12. 9. 2026 obsahuje slevový kód TOMAS15 a odkaz s parametrem ?ref=tomas. Štítek spolupráce ani #reklama jsme nenašli.',
        'The 12 Sep 2026 post contains discount code TOMAS15 and a link with ?ref=tomas. No partnership label or #ad found.',
      ),
      sources: [stP0912, stLink],
      relevance: ['c_disclose'],
    },
    {
      id: 'F3',
      kind: 'inference',
      section: 'claims',
      text: T(
        'Kód a affiliate odkaz obvykle znamenají provizi, tedy komerční vztah. Potvrdit to může jen tvůrce.',
        'A code plus an affiliate link usually means a commission, i.e. a commercial relationship. Only the creator can confirm.',
      ),
      sources: [],
      based_on: ['F2'],
    },
    {
      id: 'F4',
      kind: 'fact',
      section: 'content',
      text: T('5 z 24 postů má štítek, reklamní hashtag nebo slevový kód (21 %).', '5 of 24 posts carry a label, ad hashtag or discount code (21%).'),
      sources: [stP0620, stP0803, stP0912],
    },
    {
      id: 'F5',
      kind: 'fact',
      section: 'profile',
      text: T('IG 38 400 sledujících, TikTok 79 100 sledujících (dohromady 117 500).', 'IG 38,400 followers, TikTok 79,100 followers (117,500 combined).'),
      sources: [profileSrc(ST, 'instagram', stBio), stTt],
    },
    {
      id: 'F6',
      kind: 'gap',
      section: 'engagement',
      text: T('Překryv publika mezi IG a TikTokem z veřejných dat nezjistíme.', 'Audience overlap between IG and TikTok is not knowable from public data.'),
      sources: [],
    },
    {
      id: 'F7',
      kind: 'fact',
      section: 'engagement',
      text: T('Medián interakcí 1,9 %; 38 % ze 60 komentářů jsou jen emoji nebo obecné fráze.', 'Median engagement 1.9%; 38% of 60 comments are emoji-only or generic.'),
      sources: [postSrc(ST, 'instagram', 1), src('ig:comments:snidane_s_tomasem-2', 'instagram', 'https://instagram.mock.invalid/snidane_s_tomasem/p/2#comments', { actor: 'mock:instagram-comment-scraper', quote: '🔥🔥' })],
    },
    {
      id: 'F8',
      kind: 'fact',
      section: 'engagement',
      text: T('2 posty mají interakce nad 3× medián; oba jsou soutěže.', '2 posts have interactions above 3× median; both are giveaways.'),
      sources: [postSrc(ST, 'instagram', 7, 'SOUTĚŽ o snídani pro dva'), postSrc(ST, 'instagram', 8, 'SOUTĚŽ: 3× voucher')],
    },
    {
      id: 'F9',
      kind: 'inference',
      section: 'engagement',
      text: T('Špičky u soutěží: zájem může být o výhru, ne o obsah. Signál, ne verdikt.', 'Spikes on giveaways: interest may be in the prize, not the content. A signal, not a verdict.'),
      sources: [],
      based_on: ['F8'],
    },
    GAP_DEMOGRAPHICS('F10'),
  ],
  claims: [
    {
      id: 'K1',
      claim: 'recenze, nikdo mi neplatí',
      claim_source: stP0912,
      evidence: ['cb-st-3', 'cb-st-4', 'F2'],
      status: 'unsupported',
      confidence: 'medium',
      note: T(
        'V popisu je slevový kód a affiliate odkaz. Označení spolupráce jsme nenašli. Kód nemusí znamenat platbu, proto otázka na schůzku.',
        'The caption has a discount code and an affiliate link. No partnership label found. A code is not proof of payment, hence a question for the meeting.',
      ),
    },
    {
      id: 'K2',
      claim: 'komunita 120 tisíc',
      claim_source: profileSrc(ST, 'instagram', stBio),
      evidence: ['F5', 'F7'],
      status: 'cannot_verify',
      confidence: 'low',
      note: T(
        'IG a TikTok dohromady 117 500 sledujících, překryv neznáme. Medián interakcí 1,9 %, 38 % komentářů jen emoji. Signál, ne verdikt.',
        'IG and TikTok together 117,500 followers, overlap unknown. Median engagement 1.9%, 38% emoji-only comments. A signal, not a verdict.',
      ),
    },
  ],
  collab_timeline: [
    collab('cb-st-1', 'Kavárna Zrnko (MOCK)', 'kavarna_zrnko', 'paid_label', true, isoDate(2026, 6, 20), stP0620),
    collab('cb-st-2', 'Granola Hrstka (MOCK)', 'granola_hrstka_mock', 'ad_hashtag', true, isoDate(2026, 8, 3), stP0803),
    collab('cb-st-3', 'Džemy Kopeček (MOCK)', 'dzemy_kopecek_mock', 'discount_code', false, isoDate(2026, 9, 12), stP0912),
    collab('cb-st-4', 'Džemy Kopeček (MOCK)', 'dzemy_kopecek_mock', 'affiliate_link', false, isoDate(2026, 9, 12), stLink),
    collab('cb-st-5', 'Mlékárna Louka (MOCK)', 'mlekarna_louka_mock', 'mention', null, isoDate(2026, 9, 27), stP0927),
  ],
  news: [{ item: stNews, label: 'neutral', attribution: 'píšou Brněnské listy (MOCK)' }],
  identity: [
    {
      handle: 'snidane.s.tomasem',
      platform: 'tiktok',
      status: 'matched',
      signals: [
        { signal: T('TikTok bio uvádí IG @snidane_s_tomasem', 'the TikTok bio names IG @snidane_s_tomasem'), supports: true, source: stTt },
        { signal: T('IG bio odkazuje na stejný TikTok', 'the IG bio links to the same TikTok'), supports: true, source: profileSrc(ST, 'instagram', stBio) },
      ],
    },
    {
      handle: '@tomassnidanovy',
      platform: 'youtube',
      status: 'uncertain',
      signals: [
        { signal: T('stejné jméno kanálu', 'same channel name'), supports: true, source: stYt },
        { signal: T('žádný vzájemný odkaz, poslední video 2023', 'no link either way, last video in 2023'), supports: false, source: stYt },
      ],
    },
    {
      handle: 'tomas_snidane_fans',
      platform: 'instagram',
      status: 'rejected',
      signals: [{ signal: T('fanklub: neoficiální, sdílí cizí obsah', 'fan club: unofficial, reshares other people’s content'), supports: false, source: stFan }],
    },
  ],
  questions: [
    T('Je kód TOMAS15 placená spolupráce nebo provize? Jak takové posty označujete?', 'Is code TOMAS15 a paid deal or a commission? How do you label such posts?'),
    T('Kolik lidí sleduje IG i TikTok zároveň? Můžete poslat statistiky z obou aplikací?', 'How many people follow both IG and TikTok? Can you share stats from both apps?'),
    T('Spolupracujete teď s jinou pekárnou?', 'Are you currently working with another bakery?'),
  ],
  outreach_draft: {
    cs: 'Dobrý den, Tomáši,\n\njsme pekárna v Brně a vaše snídaňové tipy nám připomněly, proč pečeme. Chystáme nový kváskový chléb a rádi bychom ho nabídli k ochutnání.\n\nPokud byste měl zájem o spolupráci, byla by placená a jasně označená jako reklama. Pošlete nám prosím i statistiky publika z IG a TikToku, ať víme, kolik lidí v Brně oslovíme.\n\nDěkujeme,\n[vaše jméno]',
    en: 'Hello Tomáš,\n\nwe are a bakery in Brno and your breakfast tips reminded us why we bake. We are launching a new sourdough bread and would love you to taste it.\n\nIf you are interested in working together, it would be paid and clearly labeled as an ad. Please also send audience stats from IG and TikTok so we know how many people in Brno we would reach.\n\nThank you,\n[your name]',
  },
  not_checked: NOT_CHECKED,
  skeptic_notes: [
    T('Slevový kód není důkaz platby. Stav „Nedoloženo“, ne „Nesoulad“.', 'A discount code is not proof of payment. Status “Unsupported”, not “Conflict”.'),
    T('YouTube kanál se stejným jménem nemá vzájemný odkaz; ponecháno jako nejisté.', 'The same-name YouTube channel has no mutual link; left as uncertain.'),
  ],
  sensitive_filtered: 1,
}

export const R4_SNIDANE: CriterionResult[] = [
  {
    criterion_id: 'c_competitors',
    status: 'pass',
    value: T('žádná spolupráce s @pekarna_b v posledních 48 postech', 'no collaboration with @pekarna_b in the last 48 posts'),
    threshold: T('žádná spolupráce s @pekarna_b za 6 měsíců', 'no collaboration with @pekarna_b in 6 months'),
    sources: [profileSrc(ST, 'instagram')],
  },
  {
    criterion_id: 'c_disclose',
    status: 'unknown',
    value: T('2 ze 4 značek označené; u kódu TOMAS15 štítek chybí a platformní štítek actor nevrací', '2 of 4 brands labeled; the TOMAS15 code has no label and the actor does not return the platform label'),
    threshold: T('každá spolupráce označená', 'every collaboration labeled'),
    sources: [stP0912],
  },
]

// ---------------------------------------------------------------------------------------------
// 3) Shorter reports for the other finalists.
// ---------------------------------------------------------------------------------------------

interface Short {
  h: string
  pf?: 'instagram' | 'tiktok'
  first: string
  topicFact: [string, string]
  engFact: [string, string]
  collabs: { brand: string; handle: string; kind: CollabEvidence['kind']; disclosed: boolean | null; date: string; quote: string }[]
  discloseStatus: CriterionResult['status']
  discloseValue: I18nText
  tiktok?: string
  sens?: number
  q: [string, string][]
}

const SHORTS: Short[] = [
  {
    h: 'kvasek_a_kocarek',
    first: 'Lucie',
    topicFact: ['19 z 24 postů jsou recepty a rodina.', '19 of 24 posts are recipes and family.'],
    engFact: ['Medián interakcí 4,6 %; 93 % komentářů česky.', 'Median engagement 4.6%; 93% of comments in Czech.'],
    collabs: [{ brand: 'Mlýn Zrnko (MOCK)', handle: 'mlyn_zrnko_mock', kind: 'paid_label', disclosed: true, date: isoDate(2026, 8, 28), quote: 'Placená spolupráce · mouka na kvásek' }],
    discloseStatus: 'pass',
    discloseValue: T('1 z 1 spolupráce označená', '1 of 1 collaboration labeled'),
    sens: 2,
    q: [
      ['Pečete i na zakázku, nebo jen doma?', 'Do you bake to order, or only at home?'],
      ['Můžete poslat statistiky publika (lokalita)?', 'Can you share audience statistics (location)?'],
    ],
  },
  {
    h: 'brno_na_taliri',
    first: '',
    topicFact: ['19 z 24 postů jsou o podnicích a tipech v Brně.', '19 of 24 posts are about places and tips in Brno.'],
    engFact: ['Medián interakcí 2,2 %; 14 postů s místem v Brně.', 'Median engagement 2.2%; 14 posts located in Brno.'],
    collabs: [
      { brand: 'Bistro pod hradbami (MOCK)', handle: 'bistro_pod_hradbami', kind: 'paid_label', disclosed: true, date: isoDate(2026, 7, 11), quote: 'Placená spolupráce · nové menu' },
      { brand: 'Kavárna Zrnko (MOCK)', handle: 'kavarna_zrnko', kind: 'mention', disclosed: null, date: isoDate(2026, 9, 18), quote: 'Ranní káva v @kavarna_zrnko' },
    ],
    discloseStatus: 'pass',
    discloseValue: T('1 placená spolupráce označená; zmínka bez známek placení', '1 paid collaboration labeled; a mention with no sign of payment'),
    q: [
      ['Jak vybíráte podniky, o kterých píšete? Berete za recenze peníze?', 'How do you pick the places you write about? Are reviews paid?'],
      ['Můžete poslat statistiky publika (lokalita)?', 'Can you share audience statistics (location)?'],
    ],
  },
  {
    h: 'pecu_s_babi',
    pf: 'tiktok',
    first: '',
    topicFact: ['20 z 24 videí jsou recepty a pečení.', '20 of 24 videos are recipes and baking.'],
    engFact: ['Medián interakcí 5,2 %; 84 % komentářů česky.', 'Median engagement 5.2%; 84% of comments in Czech.'],
    collabs: [],
    discloseStatus: 'unknown',
    discloseValue: T('žádná spolupráce v posledních 48 videích, není co ověřit', 'no collaboration in the last 48 videos, nothing to verify'),
    tiktok: 'pecu_s_babi',
    q: [
      ['Točíte i s produkty jiných podniků? Jak je označujete?', 'Do you film with other businesses’ products? How do you label them?'],
      ['Kde v Brně natáčíte? (jen kvůli lokálnímu publiku)', 'Where in Brno do you film? (only for local audience)'],
    ],
  },
  {
    h: 'brnenske_rano',
    first: '',
    topicFact: ['16 z 24 postů jsou tipy na Brno a snídaně, část o běhu.', '16 of 24 posts are Brno tips and breakfasts, some about running.'],
    engFact: ['Medián interakcí 3,5 %; 9 postů s místem v Brně.', 'Median engagement 3.5%; 9 posts located in Brno.'],
    collabs: [{ brand: 'Běžecké ponožky Krok (MOCK)', handle: 'krok_mock', kind: 'ad_hashtag', disclosed: true, date: isoDate(2026, 9, 2), quote: '#reklama ponožky na ranní běh' }],
    discloseStatus: 'pass',
    discloseValue: T('1 z 1 spolupráce označená', '1 of 1 collaboration labeled'),
    q: [
      ['Kolik postů měsíčně je o jídle a kolik o sportu?', 'How many posts a month are about food vs. sport?'],
      ['Můžete poslat statistiky publika (lokalita)?', 'Can you share audience statistics (location)?'],
    ],
  },
]

function shortReport(s: Short): { report: Report; r4: CriterionResult[] } {
  const pf = s.pf ?? 'instagram'
  const cid = `${pf}:${s.h}`
  const posts = [postSrc(s.h, pf, 1), postSrc(s.h, pf, 2)]
  const collabs = s.collabs.map((c, i) => collab(`cb-${s.h}-${i + 1}`, c.brand, c.handle, c.kind, c.disclosed, c.date, postSrc(s.h, pf, `k${i + 1}`, c.quote)))
  const greet = s.first ? `Dobrý den, ${s.first === 'Lucie' ? 'Lucie' : s.first},` : 'Dobrý den,'
  const greetEn = s.first ? `Hello ${s.first},` : 'Hello,'
  const findings: Finding[] = [
    { id: 'F1', kind: 'fact', section: 'content', text: T(s.topicFact[0], s.topicFact[1]), sources: posts },
    { id: 'F2', kind: 'fact', section: 'engagement', text: T(s.engFact[0], s.engFact[1]), sources: [profileSrc(s.h, pf), posts[0]] },
    collabs.length
      ? {
          id: 'F3',
          kind: 'fact',
          section: 'collabs',
          text: T(`${collabs.length} spolupráce v posledních 48 postech, žádná s konkurencí.`, `${collabs.length} collaboration(s) in the last 48 posts, none with competitors.`),
          sources: collabs.map((c) => c.source),
        }
      : {
          id: 'F3',
          kind: 'gap',
          section: 'collabs',
          text: T('Žádné spolupráce v dostupných datech; zkušenost s reklamou neznáme.', 'No collaborations in the available data; ad experience unknown.'),
          sources: [],
        },
    GAP_DEMOGRAPHICS('F4'),
  ]
  const identity = s.tiktok
    ? []
    : [
        {
          handle: `${s.h.replace(/_/g, '.')}`,
          platform: 'tiktok' as const,
          status: 'uncertain' as const,
          signals: [
            { signal: T('podobné jméno účtu', 'similar account name'), supports: true, source: src(`tt:profile:${s.h}`, 'tiktok', `https://tiktok.mock.invalid/${s.h.replace(/_/g, '.')}`, { actor: 'mock:tiktok-profile-scraper' }) },
            { signal: T('žádný vzájemný odkaz v bio', 'no link between the bios'), supports: false, source: null },
          ],
        },
      ]
  const report: Report = {
    candidate_id: cid,
    findings,
    claims: [],
    collab_timeline: collabs,
    news: [],
    identity,
    questions: s.q.map(([cs, en]) => T(cs, en)),
    outreach_draft: {
      cs: `${greet}\n\njsme malá pekárna v Brně a chystáme nový kváskový chléb. Vaše posty o Brně a jídle nám sedí, proto se ozýváme.\n\nPokud byste měli zájem, spolupráce by byla placená a jasně označená jako reklama. Rádi pošleme podrobnosti.\n\nDěkujeme,\n[vaše jméno]`,
      en: `${greetEn}\n\nwe are a small bakery in Brno launching a new sourdough bread. Your posts about Brno and food fit us, so we are reaching out.\n\nIf you are interested, the collaboration would be paid and clearly labeled as an ad. Happy to send details.\n\nThank you,\n[your name]`,
    },
    not_checked: NOT_CHECKED,
    skeptic_notes: [],
    sensitive_filtered: s.sens ?? 0,
  }
  const r4: CriterionResult[] = [
    { criterion_id: 'c_competitors', status: 'pass', value: T('žádná spolupráce s @pekarna_b v posledních 48 postech', 'no collaboration with @pekarna_b in the last 48 posts'), threshold: T('žádná spolupráce s @pekarna_b za 6 měsíců', 'no collaboration with @pekarna_b in 6 months'), sources: [profileSrc(s.h, pf)] },
    { criterion_id: 'c_disclose', status: s.discloseStatus, value: s.discloseValue, threshold: T('každá spolupráce označená', 'every collaboration labeled'), sources: collabs.length ? collabs.map((c) => c.source) : [profileSrc(s.h, pf)] },
  ]
  return { report, r4 }
}

export const ROUND4: Record<string, { report: Report; r4: CriterionResult[] }> = {
  [`instagram:${MB}`]: { report: REPORT_MLSNA, r4: R4_MLSNA },
  [`instagram:${ST}`]: { report: REPORT_SNIDANE, r4: R4_SNIDANE },
  ...Object.fromEntries(SHORTS.map((s) => [`${s.pf ?? 'instagram'}:${s.h}`, shortReport(s)])),
}

export const VETTING_STEPS: I18nText[] = [
  T('víc postů (48)', 'more posts (48)'),
  T('TikTok a YouTube', 'TikTok and YouTube'),
  T('spolupráce a Meta Branded Content', 'collaborations and Meta branded content'),
  T('zprávy', 'news'),
  T('tvrzení vs. záznam', 'claims vs. record'),
  T('skeptik', 'skeptical second look'),
]
