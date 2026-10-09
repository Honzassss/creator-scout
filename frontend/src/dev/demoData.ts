// MOCK dataset for the ?demo=1 replay. Every creator, brand, outlet and URL here is fictional.
// URLs use the reserved `.invalid` TLD so nothing ever points at a real account.
// The funnel is computed from these seeds by a tiny evaluator that mirrors architecture.md section 5,
// so the numbers on screen (48 -> 22 -> 11 -> 6 -> 5) follow from the criteria, not from hard-coded counters.

import { fmtInt, fmtNum, fmtPct, translate } from '../i18n'
import type {
  Brief,
  Candidate,
  CriteriaSet,
  Criterion,
  CriterionResult,
  Elimination,
  I18nText,
  Lang,
  Metrics,
  Platform,
  Post,
  Profile,
  SourceRef,
} from '../types'

export const NOW = new Date('2026-10-08T19:30:00Z').getTime()
const DAY = 86400000

export const iso = (daysAgo: number, hour = 10) => {
  const d = new Date(NOW - daysAgo * DAY)
  d.setUTCHours(hour, 0, 0, 0)
  return d.toISOString()
}
export const isoDate = (y: number, m: number, d: number) => new Date(Date.UTC(y, m - 1, d, 10)).toISOString()
const fetched = (minAgo = 3) => new Date(NOW - minAgo * 60000).toISOString()

const ACTOR = {
  igProfile: 'mock:instagram-profile-scraper',
  igPost: 'mock:instagram-post-scraper',
  igComments: 'mock:instagram-comment-scraper',
  igHashtag: 'mock:instagram-hashtag-scraper',
  ttProfile: 'mock:tiktok-profile-scraper',
  ttSearch: 'mock:tiktok-search-scraper',
  news: 'mock:google-news-scraper',
  meta: 'mock:meta-branded-content',
}

const host = (p: Platform) => (p === 'tiktok' ? 'tiktok.mock.invalid' : p === 'youtube' ? 'youtube.mock.invalid' : 'instagram.mock.invalid')

export function src(id: string, platform: Platform, url: string, opts: { actor?: string; quote?: string; minAgo?: number } = {}): SourceRef {
  return {
    id,
    url,
    platform,
    actor: opts.actor ?? (platform === 'tiktok' ? ACTOR.ttProfile : ACTOR.igProfile),
    fetched_at: fetched(opts.minAgo ?? 3),
    mode: 'mock',
    quote: opts.quote ?? null,
  }
}

export const profileSrc = (h: string, p: Platform, quote?: string) =>
  src(`${p === 'tiktok' ? 'tt' : 'ig'}:profile:${h}`, p, `https://${host(p)}/${h}`, { quote })

export const postSrc = (h: string, p: Platform, n: number | string, quote?: string, actor?: string) =>
  src(`${p === 'tiktok' ? 'tt' : 'ig'}:post:${h}-${n}`, p, `https://${host(p)}/${h}/p/${n}`, {
    quote,
    actor: actor ?? (p === 'tiktok' ? ACTOR.ttProfile : ACTOR.igPost),
  })

// ---------- seeds ----------

export interface Seed {
  h: string
  name?: string
  pf?: Platform
  fol: number
  via: string[]
  priv?: boolean
  biz?: string // business category that looks like a company
  bizFlag?: boolean // is_business without category
  last?: number // days since last post
  csCap?: number
  topics?: Record<string, number>
  n?: number
  pw?: number
  com?: number
  eng?: number
  csCom?: number
  gen?: number
  loc?: number
  spikes?: number
  sens?: number
  bio?: string
}

export const SEEDS: Seed[] = [
  // round 1 misses: private
  { h: 'tajna_kuchyne_brno', fol: 8200, via: ['hashtag:brnofood'], priv: true },
  { h: 'buchty_za_zavrenymi', fol: 12400, via: ['search:cukrárna brno'], priv: true },
  { h: 'privatni_sladkosti', pf: 'tiktok', fol: 6100, via: ['search:brno jídlo'], priv: true },
  { h: 'zamceny_recept', fol: 19800, via: ['related:@pecu_s_babi'], priv: true },
  // too big / too small
  { h: 'velka_brnenska_kuchyne', fol: 214000, via: ['hashtag:brnofood', 'search:brno food'] },
  { h: 'foodie_cz_mega', pf: 'tiktok', fol: 380000, via: ['search:brno jídlo'] },
  { h: 'recepty_pro_milion', fol: 520000, via: ['hashtag:brnojidlo'] },
  { h: 'cukrar_celebrita', fol: 96000, via: ['search:cukrárna brno'] },
  { h: 'snidane_celeho_ceska', fol: 71000, via: ['related:@snidane_s_tomasem'] },
  { h: 'gastro_hvezda_cz', pf: 'tiktok', fol: 63000, via: ['search:brno jídlo'] },
  { h: 'zacinajici_pekar', fol: 1200, via: ['hashtag:brnojidlo'] },
  { h: 'maly_kuchtik_brno', pf: 'tiktok', fol: 3400, via: ['search:brno jídlo'] },
  { h: 'nova_v_kuchyni', fol: 2100, via: ['place:Brno - Zelný trh'] },
  // brands
  { h: 'pekarna_b', name: 'Pekárna B (MOCK)', fol: 15800, via: ['hashtag:brnofood', 'place:Brno - Zelný trh'], biz: 'Bakery' },
  { h: 'kavarna_zrnko', name: 'Kavárna Zrnko (MOCK)', fol: 9400, via: ['place:Brno - Náměstí Svobody'], biz: 'Cafe' },
  { h: 'cukrarna_u_raduznice', name: 'Cukrárna U Radužnice (MOCK)', fol: 7300, via: ['search:cukrárna brno'], biz: 'Bakery' },
  { h: 'bistro_pod_hradbami', name: 'Bistro pod hradbami (MOCK)', fol: 11200, via: ['place:Brno - Náměstí Svobody'], biz: 'Restaurant' },
  { h: 'trhy_na_namesti_mock', name: 'Trhy na náměstí (MOCK)', fol: 21000, via: ['place:Brno - Zelný trh'], biz: 'Local business' },
  // inactive
  { h: 'vecerni_peceni', fol: 14200, via: ['hashtag:brnofood'], last: 142 },
  { h: 'babiccin_sesit', fol: 8800, via: ['related:@pecu_s_babi'], last: 211 },
  { h: 'kolace_z_venkova', pf: 'tiktok', fol: 17600, via: ['search:brno jídlo'], last: 98 },
  { h: 'brnensky_gurman_2019', fol: 26400, via: ['search:brno food'], last: 400 },
  // mostly English captions
  { h: 'brno_eats_daily', fol: 33000, via: ['search:brno food'], csCap: 0.12 },
  { h: 'expat_foodie_brno', fol: 18500, via: ['hashtag:brnofood'], csCap: 0.05 },
  { h: 'sweet_tooth_cz', pf: 'tiktok', fol: 27300, via: ['search:brno jídlo'], csCap: 0.18 },
  { h: 'moravian_kitchen_en', fol: 9900, via: ['related:@brno_na_taliri'], csCap: 0.09 },

  // round 2 misses
  { h: 'cestovatelka_bara', fol: 24500, via: ['hashtag:brnofood'], topics: { travel: 17, food: 3, other: 4 }, eng: 0.028, loc: 1 },
  { h: 'vikendy_na_cestach', pf: 'tiktok', fol: 31200, via: ['search:brno jídlo'], topics: { travel: 15, family: 3, food: 2, other: 4 }, eng: 0.024 },
  { h: 'outfit_brno', fol: 19000, via: ['place:Brno - Náměstí Svobody'], topics: { fashion: 18, beauty: 4, lifestyle: 2 }, eng: 0.031, loc: 4 },
  { h: 'styl_na_kazdy_den', fol: 12700, via: ['related:@mlsna_brnenka'], topics: { fashion: 16, lifestyle: 6, food: 2 }, eng: 0.022 },
  { h: 'hraje_marek', pf: 'tiktok', fol: 42000, via: ['search:brno jídlo'], topics: { gaming: 20, humor: 4 }, eng: 0.044 },
  { h: 'behame_brnem', fol: 16300, via: ['related:@brnenske_rano'], topics: { sport: 14, fitness: 6, local_tips: 2, food: 2 }, eng: 0.029, csCom: 0.9, gen: 0.2, loc: 8 },
  { h: 'kettlebell_katka', fol: 22800, via: ['related:@brnenske_rano'], topics: { fitness: 17, lifestyle: 4, food: 3 }, eng: 0.041, csCom: 0.83, gen: 0.25, loc: 3 },
  { h: 'joga_u_prygle', pf: 'tiktok', fol: 9700, via: ['related:@behame_brnem'], topics: { fitness: 15, lifestyle: 6, travel: 3 }, eng: 0.007, csCom: 0.8, gen: 0.3, loc: 5 },
  { h: 'kolo_kolem_brna', fol: 28900, via: ['hashtag:brnojidlo'], topics: { sport: 16, travel: 4, food: 2, other: 2 }, eng: 0.018, csCom: 0.87, gen: 0.16, loc: 11 },
  { h: 'obcasny_kuchar', fol: 7600, via: ['hashtag:brnojidlo'], topics: { recipes: 8, food: 4 }, n: 12, pw: 0.3, last: 20 },
  { h: 'slevy_a_recenze', fol: 34100, via: ['search:brno food'], topics: { food: 12, other: 12 }, com: 0.62 },

  // round 3 misses
  { h: 'rodinne_vylety_brno', fol: 13900, via: ['place:Brno - Zelný trh'], topics: { family: 9, local_tips: 7, sport: 5, other: 3 }, eng: 0.013, csCom: 0.88, gen: 0.18, loc: 6 },
  { h: 'foto_dortu', fol: 41200, via: ['search:cukrárna brno'], topics: { food: 18, recipes: 4, other: 2 }, eng: 0.004, csCom: 0.81, gen: 0.22, loc: 2 },
  { h: 'dezerty_bez_hranic', pf: 'tiktok', fol: 25600, via: ['search:brno jídlo'], topics: { food: 14, recipes: 8, other: 2 }, eng: 0.031, csCom: 0.31, gen: 0.2, loc: 3 },
  { h: 'sladka_tecka_brno', fol: 18100, via: ['hashtag:brnofood'], topics: { food: 16, restaurants_cafes: 5, other: 3 }, eng: 0.024, csCom: 0.72, gen: 0.64, loc: 4 },
  { h: 'recepty_odkudkoli', fol: 11300, via: ['related:@pecu_s_babi'], topics: { recipes: 17, food: 5, other: 2 }, eng: 0.027, csCom: 0.9, gen: 0.15, loc: 0 },

  // bakery finalists
  {
    h: 'mlsna_brnenka',
    name: 'Jana Koláčková (MOCK)',
    fol: 18400,
    via: ['hashtag:brnofood', 'place:Brno - Zelný trh'],
    topics: { food: 11, family: 6, restaurants_cafes: 4, other: 3 },
    eng: 0.031,
    csCom: 0.86,
    gen: 0.14,
    loc: 7,
    pw: 3.1,
    com: 0.17,
    sens: 1,
    bio: 'Brno · jídlo · rodina | exkluzivní ambasador @pekarna_a | spolupráce: e-mail v odkazu',
  },
  {
    h: 'snidane_s_tomasem',
    name: 'Tomáš Snídaňový (MOCK)',
    fol: 38400,
    via: ['search:brno food', 'hashtag:brnofood'],
    bizFlag: true,
    topics: { food: 9, restaurants_cafes: 8, local_tips: 4, other: 3 },
    eng: 0.019,
    csCom: 0.74,
    gen: 0.38,
    loc: 5,
    pw: 2.6,
    com: 0.21,
    spikes: 2,
    sens: 1,
    bio: 'Snídaně po Brně ☕ komunita 120 tisíc | recenze, nikdo mi neplatí',
  },
  {
    h: 'kvasek_a_kocarek',
    name: 'Lucie Kvásková (MOCK)',
    fol: 9600,
    via: ['hashtag:brnojidlo'],
    topics: { recipes: 10, family: 9, food: 3, other: 2 },
    eng: 0.046,
    csCom: 0.93,
    gen: 0.11,
    loc: 3,
    pw: 2.2,
    com: 0.08,
    sens: 2,
    bio: 'Kvásek, děti a kočárek. Pečeme doma v Brně-Židenicích.',
  },
  {
    h: 'brno_na_taliri',
    name: 'Brno na talíři (MOCK)',
    fol: 27200,
    via: ['search:brno food', 'place:Brno - Náměstí Svobody'],
    topics: { restaurants_cafes: 12, local_tips: 7, food: 4, other: 1 },
    eng: 0.022,
    csCom: 0.89,
    gen: 0.19,
    loc: 14,
    pw: 4.0,
    com: 0.25,
    bio: 'Kde se v Brně dobře najíst. Píšu i o malých podnicích.',
  },
  {
    h: 'pecu_s_babi',
    name: 'Peču s bábi (MOCK)',
    pf: 'tiktok',
    fol: 44500,
    via: ['search:brno jídlo'],
    topics: { recipes: 14, food: 6, family: 3, other: 1 },
    eng: 0.052,
    csCom: 0.84,
    gen: 0.29,
    loc: 2,
    pw: 3.4,
    com: 0.04,
    bio: 'Babiččiny recepty z Moravy, natáčíme v Brně.',
  },
  {
    h: 'brnenske_rano',
    name: 'Brněnské ráno (MOCK)',
    fol: 12100,
    via: ['related:@behame_brnem', 'hashtag:brnofood'],
    topics: { local_tips: 8, fitness: 6, food: 6, sport: 2, other: 2 },
    eng: 0.035,
    csCom: 0.91,
    gen: 0.12,
    loc: 9,
    pw: 2.9,
    com: 0.13,
    bio: 'Ranní běh, snídaně a tipy na Brno.',
  },
]

export const pfOf = (s: Seed): Platform => s.pf ?? 'instagram'
export const idOf = (s: Seed) => `${pfOf(s)}:${s.h}`

// ---------- briefs and criteria ----------

export const BRIEF_BAKERY: Brief = {
  business_type: 'pekárna',
  city: 'Brno',
  audience: 'rodiny a mladí lidé v Brně',
  goal: 'víc lidí v prodejně, nový kváskový chléb',
  budget_hint: 'do 15 000 Kč',
  competitors: [{ name: 'Pekárna B (MOCK)', handles: ['pekarna_b'] }],
  lang: 'cs',
}

export const BRIEF_BAKERY_EN: Brief = {
  business_type: 'bakery',
  city: 'Brno',
  audience: 'families and young people in Brno',
  goal: 'more people in the shop, a new sourdough bread',
  budget_hint: 'up to CZK 15,000',
  competitors: [{ name: 'Pekárna B (MOCK)', handles: ['pekarna_b'] }],
  lang: 'en',
}

export const BRIEF_FITNESS_EN: Brief = {
  business_type: 'fitness studio',
  city: 'Brno',
  audience: 'young active people in Brno',
  goal: 'new members for morning classes',
  budget_hint: 'up to CZK 20,000',
  competitors: [
    { name: 'Studio Kotva (MOCK)', handles: ['studio_kotva_mock'] },
    { name: 'Appka Fitko (MOCK)', handles: ['appka_fitko_mock'] },
  ],
  lang: 'en',
}

export const BRIEF_FITNESS: Brief = {
  business_type: 'fitness studio',
  city: 'Brno',
  audience: 'mladí aktivní lidé v Brně',
  goal: 'noví členové na ranní lekce',
  budget_hint: 'do 20 000 Kč',
  competitors: [
    { name: 'Studio Kotva (MOCK)', handles: ['studio_kotva_mock'] },
    { name: 'Appka Fitko (MOCK)', handles: ['appka_fitko_mock'] },
  ],
  lang: 'cs',
}

const C = (
  id: string,
  kind: Criterion['kind'],
  round: number,
  label: [string, string],
  why: [string, string],
  params: Criterion['params'],
): Criterion => ({ id, kind, round, label: { cs: label[0], en: label[1] }, why: { cs: why[0], en: why[1] }, params, enabled: true })

function baseCriteria(): Criterion[] {
  return [
    C('c_public', 'public_account', 1, ['Veřejný účet', 'Public account'], ['Soukromý účet nejde ověřit.', 'A private account cannot be checked.'], {}),
    C('c_followers', 'followers_range', 1, ['5–50 tisíc sledujících', '5k–50k followers'], [
      'Menší tvůrci mívají bližší vztah s publikem a jsou dostupnější pro malý rozpočet.',
      'Smaller creators tend to be closer to their audience and fit a small budget.',
    ], { min: 5000, max: 50000 }),
    C('c_active', 'active_recently', 1, ['Aktivní za 30 dní', 'Active in last 30 days'], ['Neaktivní účet kampani nepomůže.', 'An inactive account will not help a campaign.'], { days: 30 }),
    C('c_notbrand', 'not_brand_account', 1, ['Tvůrce, ne firma', 'Creator, not a company'], ['Hledáme lidi, ne jiné podniky.', 'We look for people, not other businesses.'], {}),
    C('c_lang', 'language_cs', 1, ['Píše česky', 'Writes in Czech'], ['Zákazníci v Brně čtou česky.', 'Customers in Brno read Czech.'], { min_share: 0.6 }),
  ]
}

export const CRITERIA_BAKERY: CriteriaSet = {
  brief: BRIEF_BAKERY,
  criteria: [
    ...baseCriteria(),
    C('c_topics', 'topic_share', 2, ['Jídlo, recepty, podniky, lokální tipy, rodina', 'Food, recipes, cafés, local tips, family'], [
      'Pekárně pomůže tvůrce, který o jídle a Brně mluví pravidelně, ne jednou za čas.',
      'A bakery benefits from a creator who talks about food and Brno regularly.',
    ], { topics: ['food', 'recipes', 'restaurants_cafes', 'local_tips', 'family'], min_share: 0.4 }),
    C('c_formats', 'formats', 2, ['Reels, videa nebo fotky', 'Reels, videos or photos'], ['Pečivo se dobře ukazuje ve videu i na fotce.', 'Bread shows well in video and photos.'], {
      formats: ['reel', 'video', 'photo', 'carousel'],
    }),
    C('c_freq', 'post_frequency', 2, ['Aspoň 1 post týdně', 'At least 1 post a week'], ['Pravidelnost drží pozornost publika.', 'Regular posting keeps the audience engaged.'], { min_per_week: 1 }),
    C('c_commercial', 'max_commercial_share', 2, ['Nejvýš 30 % reklamy', 'At most 30% ads'], [
      'Když je reklama skoro všechno, publikum ji přestává vnímat.',
      'When nearly everything is an ad, the audience tunes out.',
    ], { max_share: 0.3 }),
    C('c_engagement', 'min_engagement', 3, ['Interakce aspoň 1,5 %', 'Engagement at least 1.5%'], [
      'Lajky a komentáře vůči sledujícím ukazují, jestli publikum opravdu reaguje.',
      'Likes and comments relative to followers show whether the audience reacts.',
    ], { min_rate: 0.015 }),
    C('c_cscomments', 'cs_comment_share', 3, ['Komentáře hlavně česky', 'Comments mostly in Czech'], [
      'Lidé, kteří reagují, píšou česky; je to jazyk komentářů, ne původ publika. Jména komentujících neukládáme.',
      'People who react write in Czech; this is the language of the comments, not the audience\'s origin. Commenter names are never stored.',
    ], { min_share: 0.6 }),
    C('c_local', 'local_signal', 3, ['Lokální signál: Brno', 'Local signal: Brno'], [
      'Místa u postů a zmínky Brna ukazují, že obsah má vazbu na Brno (místo obsahu, ne původ publika).',
      'Post locations and mentions of Brno show the content is tied to Brno (content location, not audience origin).',
    ], { city: 'Brno', min_signals: 1 }),
    C('c_generic', 'max_generic_comments', 3, ['Nejvýš 40 % prázdných komentářů', 'At most 40% generic comments'], [
      'Hodně komentářů jen z emoji je signál, ne důkaz, nepravého publika.',
      'Many emoji-only comments are a signal, not proof, of an inauthentic audience.',
    ], { max_share: 0.4 }),
    C('c_competitors', 'no_competitor_collab', 4, ['Bez spolupráce s konkurencí', 'No competitor collaborations'], [
      'Tvůrce, který právě dělá reklamu konkurenci, vám pomůže méně.',
      'A creator currently promoting a competitor helps you less.',
    ], { competitors: ['pekarna_b'], months: 6 }),
    C('c_disclose', 'discloses_ads', 4, ['Označuje reklamu', 'Labels ads'], [
      'Neoznačená reklama je problém pro vás i pro tvůrce (zákon o regulaci reklamy).',
      'Unlabeled ads are a problem for you and the creator (advertising law).',
    ], {}),
  ],
  refused: [
    {
      text: 'jen věřící tvůrci',
      reason: {
        cs: 'Víra je citlivý údaj (čl. 9 GDPR). Tvůrce podle ní nevybíráme ani ji neodhadujeme.',
        en: 'Religion is special-category data (GDPR Art. 9). We neither select by it nor infer it.',
      },
    },
    {
      text: 'ať má stejné hodnoty jako my',
      reason: {
        cs: 'Hodnoty a povaha člověka nejsou kritérium obsahu; znamenalo by to hodnotit osobu.',
        en: 'A person’s values and personality are not a content criterion; it would mean rating a person.',
      },
    },
    {
      text: 'publikum hlavně ženy 25–35',
      reason: {
        cs: 'Věk a pohlaví publika z veřejných dat zjistit nejde a neodhadujeme je. Zeptejte se tvůrce na jeho statistiky.',
        en: 'Audience age and gender cannot be read from public data and we do not estimate them. Ask the creator for their stats.',
      },
    },
  ],
  discovery: {
    keywords: ['cukrárna brno', 'brno food', 'brno jídlo'],
    hashtags: ['brnofood', 'brnojidlo'],
    places: ['Brno - Zelný trh', 'Brno - Náměstí Svobody'],
    city: 'Brno',
    platforms: ['instagram', 'tiktok'],
    limit: 60,
  },
}

export const CRITERIA_FITNESS: CriteriaSet = {
  brief: BRIEF_FITNESS,
  criteria: CRITERIA_BAKERY.criteria.map((c) => {
    if (c.id === 'c_topics')
      return {
        ...c,
        label: { cs: 'Fitness, sport, lokální tipy', en: 'Fitness, sport, local tips' },
        why: {
          cs: 'Studiu pomůže tvůrce, který o pohybu v Brně mluví pravidelně.',
          en: 'A studio benefits from a creator who regularly talks about exercise in Brno.',
        },
        params: { topics: ['fitness', 'sport', 'local_tips'], min_share: 0.4 },
      }
    if (c.id === 'c_engagement')
      return { ...c, label: { cs: 'Interakce aspoň 1 %', en: 'Engagement at least 1%' }, params: { min_rate: 0.01 } }
    if (c.id === 'c_competitors') return { ...c, params: { competitors: ['studio_kotva_mock', 'appka_fitko_mock'], months: 6 } }
    if (c.id === 'c_formats') return { ...c, why: { cs: 'Cvičení se nejlépe ukazuje ve videu.', en: 'Exercise shows best in video.' } }
    return c
  }),
  refused: [
    {
      text: 'žádní tvůrci s nadváhou',
      reason: {
        cs: 'Tělo a zdraví tvůrce jsou citlivé údaje (čl. 9 GDPR). Podle nich nevybíráme.',
        en: 'A creator’s body and health are special-category data (GDPR Art. 9). We do not select by them.',
      },
    },
  ],
  discovery: CRITERIA_BAKERY.discovery,
}

// the owner's words in the English script
const REFUSED_EN: Record<string, string> = {
  'jen věřící tvůrci': 'only religious creators',
  'ať má stejné hodnoty jako my': 'they should share our values',
  'publikum hlavně ženy 25–35': 'an audience of mostly women aged 25–35',
  'žádní tvůrci s nadváhou': 'no overweight creators',
}

/** The demo criteria with the brief and the refused requests in the owner's language. */
export function localized(cs: CriteriaSet, lang: Lang): CriteriaSet {
  const brief = cs.brief === BRIEF_FITNESS ? (lang === 'en' ? BRIEF_FITNESS_EN : BRIEF_FITNESS) : lang === 'en' ? BRIEF_BAKERY_EN : BRIEF_BAKERY
  const refused = cs.refused.map((r) => ({ text: lang === 'en' ? (REFUSED_EN[r.text] ?? r.text) : r.text, reason: r.reason }))
  return { ...cs, brief, refused }
}

// ---------- tiny evaluator (mirrors rounds 1-3) ----------

const TOPIC_POSTS: Record<string, string[]> = {
  food: ['Nejlepší kváskový chleba v Brně? Testuju dál', 'Koláče z trhu, sobotní ráno', 'Ochutnávka nového pečiva'],
  recipes: ['Recept na skořicové šneky krok za krokem', 'Kváskový chléb doma: můj postup', 'Rychlé buchty na neděli'],
  restaurants_cafes: ['Nová kavárna na Veveří, první dojmy', 'Snídaně v bistru u Lužánek', 'Tři podniky, kde mají dobrý croissant'],
  local_tips: ['Tip na sobotu: trh na Zelňáku', 'Kam v Brně, když prší', 'Brněnské vyhlídky na ráno'],
  family: ['Nedělní pečení s dětmi', 'Výlet s kočárkem po Brně', 'Co vaříme doma tento týden'],
  fitness: ['Ranní trénink v parku', 'Kettlebell za 20 minut', 'Strečink po práci'],
  sport: ['Běh kolem Prýglu', 'Kolo na Babí lom', 'Příprava na půlmaraton'],
  travel: ['Víkend v Lisabonu', 'Vlakem přes Alpy', 'Tipy na Chorvatsko'],
  fashion: ['Podzimní outfit', 'Šatník na týden', 'Doplňky z second handu'],
  beauty: ['Ranní péče o pleť', 'Recenze rtěnek'],
  lifestyle: ['Můj ranní rituál', 'Jak plánuju týden'],
  gaming: ['Stream dnes ve 20:00', 'Nová hra, první dojmy'],
  humor: ['Když pekárna zavře o minutu dřív'],
  other: ['Pár fotek z týdne', 'Q&A ze stories'],
}

function topicLabels(topics: string[], lang: 'cs' | 'en') {
  return topics.map((t) => translate(lang, `topic.${t}` as never)).join(', ')
}

function postsFor(s: Seed): Post[] {
  const p = pfOf(s)
  const n = s.n ?? 24
  const out: Post[] = []
  const topics = Object.entries(s.topics ?? { food: 12, other: 12 })
  let i = 0
  for (const [topic, count] of topics) {
    for (let k = 0; k < count && out.length < Math.min(n, 6); k++) {
      const caps = TOPIC_POSTS[topic] ?? TOPIC_POSTS.other
      const caption = caps[k % caps.length]
      const daysAgo = (s.last ?? 3) + i * Math.max(1, Math.round(7 / (s.pw ?? 2.5)))
      out.push({
        id: `${s.h}-${i + 1}`,
        platform: p,
        url: `https://${host(p)}/${s.h}/p/${i + 1}`,
        author_handle: s.h,
        created_at: iso(daysAgo),
        caption,
        media_type: i % 3 === 0 ? 'reel' : i % 3 === 1 ? 'photo' : 'carousel',
        location_name: (s.loc ?? 0) > i ? 'Brno' : null,
        source: postSrc(s.h, p, i + 1, caption),
      })
      i++
    }
  }
  return out
}

export function profileOf(s: Seed): Profile {
  const p = pfOf(s)
  const bio =
    s.bio ??
    (s.biz
      ? `Oficiální účet · ${s.name ?? s.h}`
      : s.csCap !== undefined && s.csCap < 0.5
        ? 'Food lover in Brno · recipes & cafés'
        : 'Jídlo, Brno a věci kolem')
  return {
    handle: s.h,
    platform: p,
    url: `https://${host(p)}/${s.h}`,
    display_name: s.name ?? `${s.h.replace(/_/g, ' ')} (MOCK)`,
    bio,
    followers: s.fol,
    following: Math.round(300 + (s.fol % 700)),
    posts_count: 120 + (s.fol % 400),
    verified: false,
    private: !!s.priv,
    is_business: s.biz ? true : s.bizFlag ? true : false,
    business_category: s.biz ?? null,
    external_urls: s.priv ? [] : [`https://${s.h.replace(/_/g, '-')}.mock.invalid`],
    region: p === 'tiktok' ? 'CZ' : null,
    is_under_18: false,
    latest_posts: s.priv ? [] : postsFor(s),
    source: profileSrc(s.h, p, bio),
  }
}

function metricsOf(s: Seed, upTo: number): Metrics | null {
  if (s.priv) return null
  const n = s.n ?? 24
  const eng = s.eng ?? 0.025
  const medLikes = Math.round(s.fol * eng * 0.93)
  const medComments = Math.max(1, Math.round(s.fol * eng * 0.07))
  const p = pfOf(s)
  const m: Metrics = {
    posts_analyzed: n,
    median_likes: medLikes,
    median_comments: medComments,
    engagement_rate: eng,
    posts_per_week: s.pw ?? 2.5,
    last_post_at: iso(s.last ?? 3),
    formats: { reel: Math.round(n * 0.4), photo: Math.round(n * 0.4), carousel: n - 2 * Math.round(n * 0.4) },
    commercial_share: null,
    topic_counts: {},
    cs_comment_share: null,
    comments_analyzed: 0,
    generic_comment_share: null,
    local_signals: [],
    engagement_spikes: [],
  }
  if (upTo >= 2) {
    m.topic_counts = { ...(s.topics ?? { food: 12, other: 12 }) }
    m.commercial_share = s.com ?? 0.1
  }
  if (upTo >= 3) {
    m.cs_comment_share = s.csCom ?? 0.82
    m.comments_analyzed = 60
    m.generic_comment_share = s.gen ?? 0.2
    m.local_signals = Array.from({ length: Math.min(s.loc ?? 1, 4) }, (_, i) =>
      postSrc(s.h, p, i + 1, i === 0 ? 'Místo u postu: Brno' : 'Popisek zmiňuje Brno'),
    )
    m.engagement_spikes = Array.from({ length: s.spikes ?? 0 }, (_, i) => `${s.h}-${i + 7}`)
  }
  return m
}

interface Outcome {
  results: Record<number, CriterionResult[]>
  elimination: Elimination | null
}

const pct0 = (x: number) => fmtPct(x, 'cs')
const pct1 = (x: number) => fmtPct(x, 'cs', 1)
const L = (cs: string, en: string): I18nText => ({ cs, en })
const atLeast = (x: number) => L(`aspoň ${pct0(x)}`, `at least ${fmtPct(x, 'en')}`)
const atMost = (x: number) => L(`nejvýš ${pct0(x)}`, `at most ${fmtPct(x, 'en')}`)

function evalCriterion(s: Seed, c: Criterion): { r: CriterionResult; reason?: I18nText } {
  const p = pfOf(s)
  const n = s.n ?? 24
  const prof = profileSrc(s.h, p, s.bio)
  const posts = [postSrc(s.h, p, 1, TOPIC_POSTS[Object.keys(s.topics ?? { food: 1 })[0]]?.[0]), postSrc(s.h, p, 2)]
  const R = (status: CriterionResult['status'], value: string | I18nText, threshold: string | I18nText, sources: SourceRef[]): CriterionResult => ({
    criterion_id: c.id,
    status,
    value,
    threshold,
    sources,
  })
  const num = (k: string, d: number) => (typeof c.params[k] === 'number' ? (c.params[k] as number) : d)
  switch (c.kind) {
    case 'public_account':
      return s.priv
        ? { r: R('fail', L('soukromý účet', 'private account'), L('veřejný účet', 'public account'), [prof]), reason: { cs: 'Kolo 1: soukromý účet, obsah nejde ověřit', en: 'Round 1: private account, content cannot be checked' } }
        : { r: R('pass', L('veřejný účet', 'public account'), L('veřejný účet', 'public account'), [prof]) }
    case 'followers_range': {
      const min = num('min', 5000)
      const max = num('max', 50000)
      const ok = s.fol >= min && s.fol <= max
      const v = L(`${fmtInt(s.fol, 'cs')} sledujících`, `${fmtInt(s.fol, 'en')} followers`)
      const th = L(`${fmtInt(min, 'cs')}–${fmtInt(max, 'cs')}`, `${fmtInt(min, 'en')}–${fmtInt(max, 'en')}`)
      return ok
        ? { r: R('pass', v, th, [prof]) }
        : {
            r: R('fail', v, th, [prof]),
            reason: {
              cs: `Kolo 1: ${fmtInt(s.fol, 'cs')} sledujících, mimo rozsah ${th.cs}`,
              en: `Round 1: ${fmtInt(s.fol, 'en')} followers, outside ${fmtInt(min, 'en')}–${fmtInt(max, 'en')}`,
            },
          }
    }
    case 'active_recently': {
      const days = num('days', 30)
      const last = s.last ?? 3
      const v = L(`poslední post před ${last} dny`, `last post ${last} days ago`)
      const th = L(`aspoň 1 post za ${days} dní`, `at least 1 post in ${days} days`)
      return last <= days
        ? { r: R('pass', v, th, [posts[0]]) }
        : {
            r: R('fail', v, th, [posts[0]]),
            reason: { cs: `Kolo 1: poslední post před ${last} dny`, en: `Round 1: last post ${last} days ago` },
          }
    }
    case 'not_brand_account':
      if (s.biz)
        return {
          r: R('fail', L(`firemní účet, kategorie ${s.biz}`, `business account, category ${s.biz}`), L('účet tvůrce', 'creator account'), [profileSrc(s.h, p, `Kategorie: ${s.biz}`)]),
          reason: { cs: `Kolo 1: firemní účet (kategorie ${s.biz}), ne tvůrce`, en: `Round 1: business account (category ${s.biz}), not a creator` },
        }
      if (s.bizFlag) return { r: R('unknown', L('firemní účet bez kategorie, nejde rozhodnout', 'business account without a category, cannot tell'), L('účet tvůrce', 'creator account'), [prof]) }
      return { r: R('pass', L('účet tvůrce', 'creator account'), L('účet tvůrce', 'creator account'), [prof]) }
    case 'language_cs': {
      const share = s.csCap ?? 0.9
      const min = num('min_share', 0.6)
      const k = Math.round(share * 12)
      const v = L(`${k} z 12 popisků česky`, `${k} of 12 captions in Czech`)
      return share >= min
        ? { r: R('pass', v, atLeast(min), posts) }
        : {
            r: R('fail', v, atLeast(min), posts),
            reason: { cs: `Kolo 1: jen ${k} z 12 popisků je česky`, en: `Round 1: only ${k} of 12 captions are in Czech` },
          }
    }
    case 'topic_share': {
      const set = (c.params.topics as string[]) ?? []
      const min = num('min_share', 0.4)
      const t = s.topics ?? { food: 12, other: 12 }
      const rel = set.reduce((a, k) => a + (t[k] ?? 0), 0)
      const v = L(`${rel} z ${n} postů (${pct0(rel / n)})`, `${rel} of ${n} posts (${fmtPct(rel / n, 'en')})`)
      const th = L(`aspoň ${pct0(min)} v tématech ${topicLabels(set, 'cs')}`, `at least ${fmtPct(min, 'en')} on ${topicLabels(set, 'en')}`)
      return rel / n >= min
        ? { r: R('pass', v, th, posts) }
        : {
            r: R('fail', v, th, posts),
            reason: {
              cs: `Kolo 2: jen ${rel} z ${n} postů jsou o tématech ${topicLabels(set, 'cs')}`,
              en: `Round 2: only ${rel} of ${n} posts are about ${topicLabels(set, 'en')}`,
            },
          }
    }
    case 'formats':
      return {
        r: R(
          'pass',
          L(`reels ${Math.round(n * 0.4)}, fotky ${Math.round(n * 0.4)}, karusely ${n - 2 * Math.round(n * 0.4)}`, `reels ${Math.round(n * 0.4)}, photos ${Math.round(n * 0.4)}, carousels ${n - 2 * Math.round(n * 0.4)}`),
          L('reels, videa nebo fotky', 'reels, videos or photos'),
          posts,
        ),
      }
    case 'post_frequency': {
      const pw = s.pw ?? 2.5
      const min = num('min_per_week', 1)
      const v = L(`${fmtNum(pw, 'cs')} postu týdně`, `${fmtNum(pw, 'en')} posts a week`)
      const th = L(`aspoň ${min} týdně`, `at least ${min} a week`)
      return pw >= min
        ? { r: R('pass', v, th, posts) }
        : {
            r: R('fail', v, th, posts),
            reason: { cs: `Kolo 2: ${fmtNum(pw, 'cs')} postu týdně, méně než ${min}`, en: `Round 2: ${fmtNum(pw, 'en')} posts a week, below ${min}` },
          }
    }
    case 'max_commercial_share': {
      const com = s.com ?? 0.1
      const max = num('max_share', 0.3)
      const k = Math.round(com * n)
      const v = L(`${k} z ${n} postů reklama (${pct0(com)})`, `${k} of ${n} posts are ads (${fmtPct(com, 'en')})`)
      return com <= max
        ? { r: R('pass', v, atMost(max), posts) }
        : {
            r: R('fail', v, atMost(max), posts),
            reason: { cs: `Kolo 2: ${k} z ${n} postů je reklama (${pct0(com)})`, en: `Round 2: ${k} of ${n} posts are ads (${fmtPct(com, 'en')})` },
          }
    }
    case 'min_engagement': {
      const eng = s.eng ?? 0.025
      const min = num('min_rate', 0.015)
      const v = L(`${pct1(eng)} (medián na post)`, `${fmtPct(eng, 'en', 1)} (median per post)`)
      const th = L(`aspoň ${pct1(min)}`, `at least ${fmtPct(min, 'en', 1)}`)
      return eng >= min
        ? { r: R('pass', v, th, [prof, posts[0]]) }
        : {
            r: R('fail', v, th, [prof, posts[0]]),
            reason: { cs: `Kolo 3: interakce ${pct1(eng)}, méně než ${pct1(min)}`, en: `Round 3: engagement ${fmtPct(eng, 'en', 1)}, below ${fmtPct(min, 'en', 1)}` },
          }
    }
    case 'cs_comment_share': {
      const sh = s.csCom ?? 0.82
      const min = num('min_share', 0.6)
      const csrc = src(`ig:comments:${s.h}-1`, p, `https://${host(p)}/${s.h}/p/1#comments`, { actor: ACTOR.igComments, quote: 'Vypadá to skvěle, kde to přesně je?' })
      const v = L(`${pct0(sh)} z 60 komentářů česky`, `${fmtPct(sh, 'en')} of 60 comments in Czech`)
      return sh >= min
        ? { r: R('pass', v, atLeast(min), [csrc]) }
        : {
            r: R('fail', v, atLeast(min), [csrc]),
            reason: { cs: `Kolo 3: jen ${pct0(sh)} komentářů je česky`, en: `Round 3: only ${fmtPct(sh, 'en')} of comments are in Czech` },
          }
    }
    case 'local_signal': {
      const loc = s.loc ?? 1
      const city = String(c.params.city ?? 'Brno')
      return loc >= 1
        ? { r: R('pass', L(`${loc}× místo u postu nebo zmínka ${city}`, `${loc}× post location or mention of ${city}`), L(`aspoň 1 lokální signál (${city})`, `at least 1 local signal (${city})`), [postSrc(s.h, p, 1, `Místo: ${city}`)]) }
        : {
            r: R('fail', L(`0 zmínek ${city} v bio, popiscích ani místech`, `no mention of ${city} in the bio, captions or locations`), L(`aspoň 1 lokální signál (${city})`, `at least 1 local signal (${city})`), [prof]),
            reason: { cs: `Kolo 3: žádný lokální signál (${city})`, en: `Round 3: no local signal (${city})` },
          }
    }
    case 'max_generic_comments': {
      const g = s.gen ?? 0.2
      const max = num('max_share', 0.4)
      const csrc = src(`ig:comments:${s.h}-2`, p, `https://${host(p)}/${s.h}/p/2#comments`, { actor: ACTOR.igComments, quote: '🔥🔥🔥' })
      const v = L(`${pct0(g)} komentářů jen emoji nebo obecná fráze`, `${fmtPct(g, 'en')} of comments are emoji-only or stock phrases`)
      return g <= max
        ? { r: R('pass', v, atMost(max), [csrc]) }
        : {
            r: R('fail', v, atMost(max), [csrc]),
            reason: { cs: `Kolo 3: ${pct0(g)} komentářů jsou jen emoji nebo obecné fráze`, en: `Round 3: ${fmtPct(g, 'en')} of comments are emoji-only or generic` },
          }
    }
    default:
      return { r: R('unknown', '–', '–', []) }
  }
}

export function evaluate(s: Seed, crit: CriteriaSet): Outcome {
  const results: Record<number, CriterionResult[]> = {}
  for (const round of [1, 2, 3]) {
    const cs = crit.criteria.filter((c) => c.round === round && c.enabled)
    const rs: CriterionResult[] = []
    let elim: Elimination | null = null
    for (const c of cs) {
      const { r, reason } = evalCriterion(s, c)
      rs.push(r)
      if (r.status === 'fail' && !elim && reason) elim = { round, criterion_id: c.id, reason, sources: r.sources }
    }
    results[round] = rs
    if (elim) return { results, elimination: elim }
  }
  return { results, elimination: null }
}

/** Candidate as the backend would show it after `round` finished (status left 'active'; elimination is emitted separately). */
export function candidateAt(s: Seed, crit: CriteriaSet, round: number): Candidate {
  const out = evaluate(s, crit)
  const elimRound = out.elimination?.round ?? 99
  const shown = Math.min(round, elimRound)
  const results: CriterionResult[] = []
  for (let r = 1; r <= shown; r++) results.push(...(out.results[r] ?? []))
  return {
    id: idOf(s),
    ref: refOf(s),
    profile: round >= 1 ? profileOf(s) : null,
    metrics: round >= 1 ? metricsOf(s, Math.min(round, elimRound)) : null,
    results,
    status: 'active',
    elimination: null,
    restored: false,
    sensitive_filtered: round >= 1 ? (s.sens ?? 0) : 0,
    report: null,
  }
}

export function refOf(s: Seed) {
  const p = pfOf(s)
  const first = s.via[0]
  const actor = first.startsWith('hashtag') ? ACTOR.igHashtag : p === 'tiktok' ? ACTOR.ttSearch : ACTOR.igProfile
  return { handle: s.h, platform: p, found_via: s.via, source: src(`disc:${s.h}`, p, `https://${host(p)}/${s.h}`, { actor, minAgo: 6 }) }
}

/** Full end state of a goal (rounds 1-3), used for the goal-change snapshot. */
export function finalState(crit: CriteriaSet) {
  const out: Record<string, { cand: Candidate; elimination: Elimination | null }> = {}
  for (const s of SEEDS) {
    const ev = evaluate(s, crit)
    const c = candidateAt(s, crit, 3)
    if (ev.elimination) {
      c.status = 'eliminated'
      c.elimination = ev.elimination
    }
    out[idOf(s)] = { cand: c, elimination: ev.elimination }
  }
  return out
}

export const seedById = (id: string) => SEEDS.find((s) => idOf(s) === id)
