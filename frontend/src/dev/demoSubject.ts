// MOCK subject-mode data for the ?demo=1 replay (docs/subject-mode.md): ONE named creator, one anchor (city
// Brno), two goals (bakery / fitness studio). Everything is fictional; URLs use the reserved `.invalid` TLD.
//
// The two reports are written per goal, and the report diff between them is COMPUTED from the two reports
// (ids, tiers, claim statuses, checks, questions, outreach), so the "What changed" panel shows what really
// differs between the two renders, the same way the backend's diff_reports does.

import { CRITERIA_BAKERY, isoDate, postSrc, profileSrc, src } from './demoData'
import { NOT_CHECKED } from './demoReports'
import { PRESETS, type PresetName } from '../lib/presets'
import { anchorText } from '../lib/subject'
import type {
  Anchor,
  Candidate,
  ClaimCheck,
  CollabEvidence,
  Confidence,
  CriteriaSet,
  Criterion,
  CriterionResult,
  Finding,
  FindingKind,
  FindingSection,
  I18nText,
  IdentityMatch,
  IdentityVerdict,
  Lang,
  Metrics,
  NewsItem,
  Profile,
  RelevanceTier,
  Report,
  ReportDiff,
  ReportSection,
  ResultStatus,
  SourceRef,
} from '../types'

const T = (cs: string, en: string): { cs: string; en: string } => ({ cs, en })

export const SUBJECT_HANDLE = 'kuba.jidlo.brno'
export const SUBJECT_ID = `instagram:${SUBJECT_HANDLE}`
export const SUBJECT_RUN_ID = 'demo-subject-mock'
export const SUBJECT_ANCHOR = { city: 'Brno' }
const H = SUBJECT_HANDLE

// ---------------------------------------------------------------------------------------------
// Criteria: the demo criteria with the preset brief and the preset competitors (lib/presets.ts)
// ---------------------------------------------------------------------------------------------

export function subjectCriteria(preset: PresetName, lang: Lang): CriteriaSet {
  const brief = PRESETS[preset][lang]
  const handles = brief.competitors.flatMap((c) => c.handles ?? [])
  const criteria: Criterion[] = CRITERIA_BAKERY.criteria.map((c) => {
    if (c.id === 'c_competitors') return { ...c, params: { competitors: handles, months: 6 } }
    // the report prefixes a criterion's why with "For your bakery: ", so the why talks to the owner directly
    if (preset === 'bakery')
      return c.id === 'c_topics'
        ? { ...c, why: { cs: 'Pomůže vám tvůrce, který o jídle a Brně mluví pravidelně, ne jednou za čas.', en: 'You benefit from a creator who talks about food and Brno regularly.' } }
        : c
    if (c.id === 'c_topics')
      return {
        ...c,
        label: { cs: 'Fitness, sport, lokální tipy', en: 'Fitness, sport, local tips' },
        why: {
          cs: 'Pomůže vám tvůrce, který o pohybu v Brně mluví pravidelně.',
          en: 'You benefit from a creator who regularly talks about exercise in Brno.',
        },
        params: { topics: ['fitness', 'sport', 'local_tips'], min_share: 0.4 },
      }
    if (c.id === 'c_engagement') return { ...c, label: { cs: 'Interakce aspoň 1 %', en: 'Engagement at least 1%' }, params: { min_rate: 0.01 } }
    if (c.id === 'c_formats') return { ...c, why: { cs: 'Cvičení se nejlépe ukazuje ve videu.', en: 'Exercise shows best in video.' } }
    return c
  })
  return { brief, criteria, refused: [], discovery: { city: 'Brno' } }
}

// ---------------------------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------------------------

const BIO = 'Brno 🍞 pekárny, bistra a trhy · exkluzivní ambasador @pekarna_a · TikTok @kubajidlo.brno'
const pProfile = profileSrc(H, 'instagram', BIO)
const P = {
  market: postSrc(H, 'instagram', 'K3a1', 'Sobotní trh na Zelňáku: koláče, kváskový chleba a první švestky'),
  lipa: postSrc(H, 'instagram', 'K2x9', 'Nejlepší snídaně v Bistru Lípa 🥐 Recenze, nikdo mi za ně neplatí. S kódem KUBA10 máte 10 % slevu.'),
  pekB: postSrc(H, 'instagram', 'K2q4', 'S @pekarna_b jsme pekli kváskový bochník pro sousedy'),
  proteo: postSrc(H, 'instagram', 'K2m1', 'Placené partnerství s @proteomax · hrdý partner @proteomax, proteinové lívance na ráno'),
  pekA2: postSrc(H, 'instagram', 'K1z7', '#spoluprace @pekarna_a · celozrnné rohlíky'),
  zrnko: postSrc(H, 'instagram', 'K1c2', 'Kafe v Kavárně Zrnko a procházka po Lužánkách'),
  pekA1: postSrc(H, 'instagram', 'K0p5', 'Placené partnerství s @pekarna_a · nový kváskový chléb'),
  run: postSrc(H, 'instagram', 'K0r2', 'Ranní běh kolem Prýglu a pak snídaně'),
}
const comments = src(`ig:comments:${H}-1`, 'instagram', `https://instagram.mock.invalid/${H}/p/K3a1#comments`, {
  actor: 'mock:instagram-comment-scraper',
  quote: 'Kde přesně na Zelňáku ten stánek je?',
})
const ttMatch = src('tt:profile:kubajidlo.brno', 'tiktok', 'https://tiktok.mock.invalid/@kubajidlo.brno', {
  actor: 'mock:tiktok-profile-scraper',
  quote: 'IG @kuba.jidlo.brno · jídlo v Brně',
})
const ttLook = src('tt:profile:kuba_jidlo', 'tiktok', 'https://tiktok.mock.invalid/@kuba_jidlo', {
  actor: 'mock:tiktok-profile-scraper',
  quote: 'Bratislava · street food každý deň',
})
const ytUnc = src('yt:channel:kubajidlo', 'youtube', 'https://youtube.mock.invalid/@kubajidlo', {
  actor: 'mock:youtube-channel-scraper',
  quote: 'Kuba vaří · recepty',
})
const igFan = src('ig:profile:kuba.jidlo.brno.fans', 'instagram', 'https://instagram.mock.invalid/kuba.jidlo.brno.fans', {
  quote: 'Fan page · nejsme Kuba, jen sdílíme jeho fotky',
})

// Czech sources stay Czech (they are the evidence); title_gloss / snippet_gloss carry an English line for the jury
const news = (id: string, title: string, outlet: string, date: string, snippet: string, titleEn: string, snippetEn: string): NewsItem => {
  const url = `https://news.mock.invalid/${id}`
  return {
    id,
    title,
    outlet,
    url,
    published_at: date,
    snippet,
    title_gloss: { cs: title, en: titleEn },
    snippet_gloss: { cs: snippet, en: snippetEn },
    source: src(`news:${id}`, 'news', url, { actor: 'mock:google-news-scraper', quote: snippet }),
  }
}
const newsGuide = news(
  'n-brno-food-guide',
  'Kam na jídlo v Brně: tipy místních tvůrců (MOCK)',
  'Brněnský deník (MOCK)',
  isoDate(2026, 9, 14),
  'Mezi tvůrci, kteří mapují brněnská bistra a trhy, je i @kuba.jidlo.brno.',
  'Where to eat in Brno: tips from local creators (MOCK)',
  'Among the creators who map Brno bistros and markets is @kuba.jidlo.brno.',
)
const newsNamesake = news(
  'n-zlin-kubicek',
  'Zlínský podnikatel Jakub Kubíček rozšiřuje síť jídelen (MOCK)',
  'Zlínský deník (MOCK)',
  isoDate(2026, 8, 21),
  'Podnikatel Jakub Kubíček ze Zlína otevírá třetí závodní jídelnu.',
  'Zlín businessman Jakub Kubíček expands his chain of canteens (MOCK)',
  'Businessman Jakub Kubíček from Zlín is opening his third workplace canteen.',
)

// ---------------------------------------------------------------------------------------------
// Profile and metrics
// ---------------------------------------------------------------------------------------------

export function subjectProfile(): Profile {
  return {
    handle: H,
    platform: 'instagram',
    url: `https://instagram.mock.invalid/${H}`,
    display_name: 'Kuba Jídlo (MOCK)',
    bio: BIO,
    followers: 21400,
    following: 612,
    posts_count: 388,
    verified: false,
    private: false,
    is_business: true,
    business_category: null,
    external_urls: ['https://kubajidlo.mock.invalid'],
    related_handles: ['kubajidlo.brno'],
    region: null,
    is_under_18: false,
    latest_posts: [],
    source: pProfile,
  }
}

export function subjectMetrics(upTo: number): Metrics {
  const m: Metrics = {
    posts_analyzed: 24,
    median_likes: 620,
    median_comments: 44,
    engagement_rate: 0.031,
    posts_per_week: 2.8,
    last_post_at: isoDate(2026, 10, 6),
    formats: { reel: 10, photo: 9, carousel: 5 },
    commercial_share: null,
    topic_counts: {},
    cs_comment_share: null,
    comments_analyzed: 0,
    generic_comment_share: null,
    local_signals: [],
    engagement_spikes: [],
  }
  if (upTo >= 2) {
    m.topic_counts = { food: 9, restaurants_cafes: 4, local_tips: 2, recipes: 1, family: 1, sport: 2, fitness: 1, other: 4 }
    m.commercial_share = 0.25
  }
  if (upTo >= 3) {
    m.cs_comment_share = 0.84
    m.comments_analyzed = 60
    m.generic_comment_share = 0.14
    m.local_signals = [P.market, P.zrnko, P.lipa, P.run]
  }
  return m
}

// ---------------------------------------------------------------------------------------------
// Check results per goal
// ---------------------------------------------------------------------------------------------

type R = { status: ResultStatus; value: I18nText; threshold: I18nText; sources: SourceRef[] }

function resultsFor(preset: PresetName): Record<string, R> {
  const fit = preset === 'fitness'
  return {
    c_public: { status: 'pass', value: T('veřejný účet', 'public account'), threshold: T('veřejný účet', 'public account'), sources: [pProfile] },
    c_followers: { status: 'pass', value: T('21 400 sledujících', '21,400 followers'), threshold: T('5 000–50 000', '5,000–50,000'), sources: [pProfile] },
    c_active: { status: 'pass', value: T('poslední post před 2 dny', 'last post 2 days ago'), threshold: T('aspoň 1 post za 30 dní', 'at least 1 post in 30 days'), sources: [P.market] },
    c_notbrand: {
      status: 'unknown',
      value: T('profesionální účet bez kategorie, nejde rozlišit tvůrce a firmu', 'professional account without a category: creator or business cannot be told apart'),
      threshold: T('účet tvůrce', 'creator account'),
      sources: [pProfile],
    },
    c_lang: { status: 'pass', value: T('22 z 24 popisků česky', '22 of 24 captions in Czech'), threshold: T('aspoň 60 %', 'at least 60%'), sources: [P.market, P.lipa] },
    c_topics: fit
      ? {
          status: 'fail',
          value: T('3 z 24 postů (13 %)', '3 of 24 posts (13%)'),
          threshold: T('aspoň 40 % v tématech fitness, sport, lokální tipy', 'at least 40% on fitness, sport, local tips'),
          sources: [P.run, P.proteo, P.market],
        }
      : {
          status: 'pass',
          value: T('17 z 24 postů (71 %)', '17 of 24 posts (71%)'),
          threshold: T('aspoň 40 % v tématech jídlo, recepty, podniky, lokální tipy, rodina', 'at least 40% on food, recipes, cafés, local tips, family'),
          sources: [P.market, P.lipa, P.pekB],
        },
    c_formats: { status: 'pass', value: T('reely 10, fotky 9, karusely 5', 'reels 10, photos 9, carousels 5'), threshold: T('reely, videa nebo fotky', 'reels, videos or photos'), sources: [P.market, P.pekB] },
    c_freq: { status: 'pass', value: T('2,8 postu týdně', '2.8 posts a week'), threshold: T('aspoň 1 týdně', 'at least 1 a week'), sources: [P.market, P.lipa] },
    c_commercial: { status: 'pass', value: T('6 z 24 postů reklama (25 %)', '6 of 24 posts are ads (25%)'), threshold: T('nejvýš 30 %', 'at most 30%'), sources: [P.proteo, P.pekA2, P.lipa] },
    c_engagement: {
      status: 'pass',
      value: T('3,1 % (medián na post)', '3.1% (median per post)'),
      threshold: fit ? T('aspoň 1,0 %', 'at least 1.0%') : T('aspoň 1,5 %', 'at least 1.5%'),
      sources: [pProfile, P.market],
    },
    c_cscomments: { status: 'pass', value: T('84 % z 60 komentářů česky', '84% of 60 comments in Czech'), threshold: T('aspoň 60 %', 'at least 60%'), sources: [comments] },
    c_local: { status: 'pass', value: T('9× místo u postu nebo zmínka Brna', '9× post location or mention of Brno'), threshold: T('aspoň 1 lokální signál (Brno)', 'at least 1 local signal (Brno)'), sources: [P.market, P.zrnko] },
    c_generic: { status: 'pass', value: T('14 % komentářů jen emoji nebo fráze', '14% of comments are emoji-only or stock phrases'), threshold: T('nejvýš 40 %', 'at most 40%'), sources: [comments] },
    c_competitors: fit
      ? {
          status: 'fail',
          value: T('placené partnerství s @proteomax (2. 9. 2026)', 'paid partnership with @proteomax (2 Sep 2026)'),
          threshold: T('žádná spolupráce s @fitzone_brno, @proteomax za 6 měsíců', 'no collaboration with @fitzone_brno, @proteomax in 6 months'),
          sources: [P.proteo],
        }
      : {
          status: 'fail',
          value: T('společný post s @pekarna_b (18. 9. 2026)', 'co-authored post with @pekarna_b (18 Sep 2026)'),
          threshold: T('žádná spolupráce s @pekarna_b, @chlebarna_vlnka za 6 měsíců', 'no collaboration with @pekarna_b, @chlebarna_vlnka in 6 months'),
          sources: [P.pekB],
        },
    c_disclose: {
      status: 'fail',
      value: T('2 ze 6 značkových postů bez označení reklamy', '2 of 6 brand posts without an ad label'),
      threshold: T('každý značkový post označený', 'every brand post labeled'),
      sources: [P.pekB, P.lipa],
    },
  }
}

/** Results as the backend would show them after `round` (rounds 1-4 are checks; nothing is eliminated). */
export function subjectResults(preset: PresetName, lang: Lang, upToRound: number): CriterionResult[] {
  const cs = subjectCriteria(preset, lang)
  const rs = resultsFor(preset)
  return cs.criteria
    .filter((c) => c.enabled && c.round <= upToRound && rs[c.id])
    .map((c) => ({ criterion_id: c.id, status: rs[c.id].status, value: rs[c.id].value, threshold: rs[c.id].threshold, sources: rs[c.id].sources }))
}

export function subjectCandidate(preset: PresetName, lang: Lang, upToRound: number, report: Report | null = null): Candidate {
  return {
    id: SUBJECT_ID,
    ref: { handle: H, platform: 'instagram', found_via: ['manual'], source: pProfile },
    profile: upToRound >= 1 ? subjectProfile() : null,
    metrics: upToRound >= 1 ? subjectMetrics(upToRound) : null,
    results: upToRound >= 1 ? subjectResults(preset, lang, upToRound) : [],
    status: upToRound >= 3 ? 'finalist' : 'active',
    elimination: null,
    restored: false,
    sensitive_filtered: upToRound >= 1 ? 1 : 0,
    report,
  }
}

// ---------------------------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------------------------

const BASIS = {
  profile: T('údaje platformy o profilu', 'platform profile data'),
  dates: T('data postů', 'post dates'),
  media: T('typ média podle platformy', 'platform media type'),
  topics: T('pravidla s klíčovými slovy na 24 popiscích', 'keyword rules on 24 captions'),
  commercial: T('štítky, reklamní hashtagy a slevové kódy v popiscích', 'labels, ad hashtags and discount codes in captions'),
  engagement: T('veřejné počty lajků a komentářů, 24 postů', 'public like and comment counts, 24 posts'),
  lang60: T('rozpoznání jazyka u 60 komentářů', 'language detection on 60 comments'),
  lang24: T('rozpoznání jazyka u 24 popisků', 'language detection on 24 captions'),
  generic: T('třídění komentářů podle pravidel', 'rule-based comment classification'),
  local: T('místa u postů a popisky', 'place tags and captions'),
  paid: T('štítek placeného partnerství na platformě', 'platform paid-partnership label'),
  coauthor: T('pole spoluautora na platformě', 'platform co-author field'),
  caption: T('vlastní popisek', 'own caption'),
  links: T('profily na sebe odkazují', 'the profiles link to each other'),
  cityBio: T('město v bio', 'city in bio'),
  anchorBio: T('město z kotvy v bio', 'anchor city in bio'),
  newsOne: T('jedna zpráva', 'single news item'),
  namesake: T('jiný kontext v článku', 'different context in the article'),
  never: T('na platformě nikdy veřejné', 'never public on the platform'),
  infer1: T('odvozeno pravidlem z 1 faktu', 'rule-based inference from 1 fact'),
  check: T('kontrola nad údaji výše', 'check on the data above'),
}

const GOALS: Record<PresetName, { cs: string; en: string; csFor: string }> = {
  bakery: { cs: 'pekárnu', en: 'bakery', csFor: 'Pro vaši pekárnu' },
  fitness: { cs: 'fitness studio', en: 'fitness studio', csFor: 'Pro vaše fitness studio' },
}
/** "For your bakery: …" / "Pro vaši pekárnu: …" */
const forGoal = (g: PresetName, cs: string, en: string) => T(`${GOALS[g].csFor}: ${cs}`, `For your ${GOALS[g].en}: ${en}`)
const lessFor = (g: PresetName, cs: string, en: string) => T(`${GOALS[g].csFor} méně důležité: ${cs}`, `Less relevant for your ${GOALS[g].en}: ${en}`)

interface Spec {
  id: string
  kind: FindingKind
  section: FindingSection
  text: I18nText
  sources: SourceRef[]
  conf: Confidence
  basis: I18nText
  tier: RelevanceTier
  why: I18nText
  based_on?: string[]
  relevance?: string[]
  aspect: string
}


// ---------------------------------------------------------------------------------------------
// The anchor decides the identity verdict (docs/subject-mode.md section 5.2). The demo has data for ONE
// creator; what the owner gives as the anchor changes the verdict, the identity finding and the summary.
// ---------------------------------------------------------------------------------------------

/** What the owner typed and gave, plus how the texts were written (the &llm demo flag). */
export interface SubjectCtx {
  anchor: Anchor | null
  /** "@handle" or the profile link, exactly as typed */
  raw: string
  /** the goal the check (vetting) ran for; the language model wrote its per-goal texts for this one */
  firstGoal: PresetName
  /** &llm=…: a language model wrote texts during vetting (MOCK) */
  llm: boolean
}
export const subjectCtx = (x: Partial<SubjectCtx> = {}): SubjectCtx => ({ anchor: SUBJECT_ANCHOR, raw: `@${SUBJECT_HANDLE}`, firstGoal: 'bakery', llm: false, ...x })

export type AnchorCase = 'city' | 'city_other' | 'none' | 'website' | 'website_other' | 'company_id'
const fold = (x: string) => x.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()

export function anchorCase(a: Anchor | null | undefined): AnchorCase {
  if (!a || !(a.city || a.website || a.company_id)) return 'none'
  if (a.website) return /kubajidlo/i.test(a.website) ? 'website' : 'website_other'
  if (a.company_id) return 'company_id'
  return fold(a.city ?? '').includes('brno') ? 'city' : 'city_other'
}

/** "Brno is in the bio" / "the anchor is Praha, the bio says Brno" … for one anchor, both languages. */
function anchorWords(ctx: SubjectCtx) {
  const a = ctx.anchor ?? {}
  // a matching city is written as the bio writes it
  const city = anchorCase(ctx.anchor) === 'city' ? 'Brno' : (a.city ?? '').trim()
  const site = a.website ?? ''
  const id = a.company_id ?? ''
  return { city, site, id }
}

const TT_SIGNAL = { signal: T('TikTok @kubajidlo.brno odkazuje zpět na tento profil', 'TikTok @kubajidlo.brno links back to this profile'), supports: true, source: ttMatch }

function anchorFinding(ctx: SubjectCtx): Spec {
  const { city, site, id } = anchorWords(ctx)
  const base = { section: 'identity' as const, aspect: 'identity' }
  const unsure = T(
    'Bez shody nejde tento účet spolehlivě odlišit od jmenovce nebo podobného účtu. Zkontrolujte účet nebo kotvu.',
    'Without a match we cannot reliably tell this account apart from a namesake or a look-alike. Check the handle or the anchor.',
  )
  switch (anchorCase(ctx.anchor)) {
    case 'city':
      return {
        ...base,
        id: 'f:anchor:city',
        kind: 'fact',
        text: T(`Vaše kotva ${city} je v bio.`, `Your anchor, ${city}, is in the bio.`),
        sources: [pProfile],
        conf: 'medium',
        basis: BASIS.anchorBio,
        tier: 'related',
        why: T('Potvrzuje, že jde o brněnského tvůrce, kterého myslíte, ne o někoho s podobným jménem.', 'Confirms this is the Brno creator you mean, not someone with a similar name.'),
      }
    case 'city_other':
      return {
        ...base,
        id: 'f:anchor:city_other',
        kind: 'fact',
        text: T(`Vaše kotva je ${city}, ale v bio je Brno.`, `Your anchor is ${city}, but the bio says Brno.`),
        sources: [pProfile],
        conf: 'high',
        basis: BASIS.cityBio,
        tier: 'key',
        why: T(
          'Buď jde o jiného tvůrce, než myslíte, nebo kotva nesedí. Než se na report spolehnete, zkontrolujte účet nebo kotvu.',
          'Either this is not the creator you mean, or the anchor is off. Check the handle or the anchor before you rely on this report.',
        ),
      }
    case 'website':
      return {
        ...base,
        id: 'f:anchor:website',
        kind: 'fact',
        text: T(`Vaše kotva, web ${site}, je v profilu.`, `Your anchor, the website ${site}, is on the profile.`),
        sources: [pProfile],
        conf: 'high',
        basis: T('web v profilu', 'website on the profile'),
        tier: 'related',
        why: T('Web je silná kotva: jmenovec ani podobný účet ho v profilu mít nebude.', 'A website is a strong anchor: a namesake or a look-alike will not have it on their profile.'),
      }
    case 'website_other':
      return {
        ...base,
        id: 'g:anchor:website',
        kind: 'gap',
        text: T(`Web ${site} ve veřejném profilu není.`, `The website ${site} is not on the public profile.`),
        sources: [],
        conf: 'medium',
        basis: T('odkazy ve veřejném profilu', 'links on the public profile'),
        tier: 'key',
        why: unsure,
      }
    case 'company_id':
      return {
        ...base,
        id: 'g:anchor:company_id',
        kind: 'gap',
        text: T(`IČO ${id} ve veřejném profilu není; obchodní rejstřík jsme nedotazovali.`, `Company ID ${id} does not appear in the public profile; we did not query the business register.`),
        sources: [],
        conf: 'high',
        basis: T('veřejný profil', 'public profile'),
        tier: 'key',
        why: unsure,
      }
    default:
      return {
        ...base,
        id: 'g:anchor:none',
        kind: 'gap',
        text: T('Bez kotvy: identitu potvrzuje jen TikTok, který odkazuje zpět.', 'No anchor given: only the TikTok account linking back confirms the identity.'),
        sources: [],
        conf: 'high',
        basis: T('kotva nezadána', 'no anchor given'),
        tier: 'related',
        why: T('Město, web nebo IČO tvůrce by identitu potvrdily.', "The creator's city, website or company ID would confirm it."),
      }
  }
}

/** Identity problem (uncertain verdict), both languages, or null when the anchor matched or none was given. */
function identityProblem(ctx: SubjectCtx): { cs: string; en: string } | null {
  const { city, site, id } = anchorWords(ctx)
  switch (anchorCase(ctx.anchor)) {
    case 'city_other':
      return T(`v bio je Brno, kotva je ${city}`, `the bio says Brno, the anchor is ${city}`)
    case 'website_other':
      return T(`web ${site} v profilu není`, `the website ${site} is not on the profile`)
    case 'company_id':
      return T(`IČO ${id} ve veřejném profilu není`, `company ID ${id} does not appear in the public profile`)
    default:
      return null
  }
}

/** One run-log line about the identity step. */
export function identityLog(ctx: SubjectCtx): I18nText {
  const { city, site, id } = anchorWords(ctx)
  const head = T('Identita: TikTok @kubajidlo.brno odkazuje zpět (shoda).', 'Identity: TikTok @kubajidlo.brno links back (match).')
  const tail: Record<AnchorCase, { cs: string; en: string }> = {
    city: T(`Kotva ${city} je v bio.`, `The anchor ${city} is in the bio.`),
    city_other: T(`Kotva ${city} v bio NENÍ (bio: Brno): identita nejistá.`, `The anchor ${city} is NOT in the bio (bio: Brno): identity uncertain.`),
    none: T('Bez kotvy: identita pravděpodobná, ne potvrzená.', 'No anchor: identity likely, not confirmed.'),
    website: T(`Web ${site} je v profilu.`, `The website ${site} is on the profile.`),
    website_other: T(`Web ${site} v profilu není: identita nejistá.`, `The website ${site} is not on the profile: identity uncertain.`),
    company_id: T(`IČO ${id} ve veřejném profilu není (rejstřík nedotazujeme): identita nejistá.`, `Company ID ${id} is not in the public profile (no business register query): identity uncertain.`),
  }
  const t = tail[anchorCase(ctx.anchor)]
  return T(`${head.cs} ${t.cs}`, `${head.en} ${t.en}`)
}

function findingsFor(g: PresetName, ctx: SubjectCtx): Spec[] {
  const fit = g === 'fitness'
  const out: Spec[] = []
  const add = (x: Spec) => out.push(x)

  // ---- identity
  add(anchorFinding(ctx))
  add({
    id: 'f:identity:tiktok',
    kind: 'fact',
    section: 'identity',
    text: T('TikTok @kubajidlo.brno odkazuje zpět na tento instagramový profil.', 'TikTok @kubajidlo.brno links back to this Instagram profile.'),
    sources: [ttMatch],
    conf: 'high',
    basis: BASIS.links,
    tier: 'related',
    why: T('Druhá platforma, která odkazuje zpět, dělá záměnu nepravděpodobnou.', 'A second platform that links back makes a mix-up unlikely.'),
    aspect: 'identity',
  })
  add({
    id: 'f:lookalike:tiktok',
    kind: 'fact',
    section: 'identity',
    text: T('TikTok @kuba_jidlo je jiný účet: v bio má Bratislavu a účty na sebe neodkazují.', 'TikTok @kuba_jidlo is a different account: its bio says Bratislava and neither account links to the other.'),
    sources: [ttLook],
    conf: 'medium',
    basis: BASIS.cityBio,
    tier: 'related',
    why: T('Odloženo, aby se jeho posty a čísla nepromítly do tohoto reportu.', 'Set aside, so its posts and numbers do not leak into this report.'),
    aspect: 'identity',
  })
  add({
    id: 'f:namesake:news',
    kind: 'fact',
    section: 'identity',
    text: T(
      'Článek o Jakubu Kubíčkovi, podnikateli ze Zlína, je o jiném člověku: jiné město i obor.',
      'An article about Jakub Kubíček, a businessman from Zlín, is about a different person: different city and field.',
    ),
    sources: [newsNamesake.source],
    conf: 'medium',
    basis: BASIS.namesake,
    tier: 'related',
    why: T('Zprávy o jmenovci se nesmí počítat proti tomuto tvůrci.', 'News about a namesake must not count against this creator.'),
    aspect: 'identity',
  })

  // ---- content
  add({
    id: 'f:fit:topics',
    kind: 'fact',
    section: 'content',
    text: fit
      ? T(
          '3 z 24 posledních postů (13 %) je o fitness, sportu nebo lokálních tipech, tedy o tom, co je důležité pro fitness studio (požadavek 40 %).',
          '3 of 24 recent posts (13%) are about fitness, sport or local tips: what matters for a fitness studio (needs 40%).',
        )
      : T(
          '17 z 24 posledních postů (71 %) je o jídle, receptech, podnicích, lokálních tipech nebo rodině, tedy o tom, co je důležité pro pekárnu (požadavek 40 %).',
          '17 of 24 recent posts (71%) are about food, recipes, cafés, local tips or family: what matters for a bakery (needs 40%).',
        ),
    sources: fit ? [P.run, P.proteo, P.market] : [P.market, P.lipa, P.pekB, P.pekA1, P.zrnko],
    conf: 'low',
    basis: BASIS.topics,
    tier: 'key',
    why: fit
      ? forGoal(g, 'pomůže vám tvůrce, který o pohybu v Brně mluví pravidelně. Tady je to malá část obsahu.', 'you benefit from a creator who regularly talks about exercise in Brno. Here it is a small part of the feed.')
      : forGoal(g, 'pomůže vám tvůrce, který o jídle a Brně mluví pravidelně, ne jednou za čas.', 'you benefit from a creator who talks about food and Brno regularly.'),
    relevance: ['c_topics'],
    aspect: 'content_fit',
  })
  add({
    id: 'f:formats',
    kind: 'fact',
    section: 'content',
    text: T('Formáty: 10 reelů, 9 fotek, 5 karuselů.', 'Formats: 10 reels, 9 photos, 5 carousels.'),
    sources: [P.market, P.pekB],
    conf: 'high',
    basis: BASIS.media,
    tier: 'related',
    why: fit
      ? forGoal(g, 'cvičení se nejlépe ukazuje ve videu; reely jsou 10 z 24 postů.', 'exercise shows best in video; 10 of 24 posts are reels.')
      : forGoal(g, 'pečivo se dobře ukazuje ve videu i na fotce.', 'bread shows well in video and in photos.'),
    relevance: ['c_formats'],
    aspect: 'content_fit',
  })
  add({
    id: 'f:frequency',
    kind: 'fact',
    section: 'content',
    text: T('2,8 postu týdně za posledních 8 týdnů.', '2.8 posts a week over the last 8 weeks.'),
    sources: [P.market, P.lipa],
    conf: 'high',
    basis: BASIS.dates,
    tier: 'related',
    why: forGoal(g, 'pravidelnost drží pozornost publika.', 'regular posting keeps the audience engaged.'),
    relevance: ['c_freq'],
    aspect: 'content_fit',
  })

  // ---- engagement
  add({
    id: 'f:engagement',
    kind: 'fact',
    section: 'engagement',
    text: T('Medián interakcí 3,1 % sledujících na post (24 postů).', 'Median engagement is 3.1% of followers per post (24 posts).'),
    sources: [pProfile, P.market],
    conf: 'medium',
    basis: BASIS.engagement,
    tier: 'related',
    why: forGoal(g, `lajky a komentáře vůči sledujícím ukazují, jestli publikum opravdu reaguje (požadavek ${fit ? '1' : '1,5'} %).`, `likes and comments relative to followers show whether the audience reacts (needs ${fit ? '1' : '1.5'}%).`),
    relevance: ['c_engagement'],
    aspect: 'reach_engagement',
  })
  add({
    id: 'f:cs_comments',
    kind: 'fact',
    section: 'engagement',
    text: T('84 % z 60 komentářů je česky.', '84% of 60 comments are in Czech.'),
    sources: [comments],
    conf: 'medium',
    basis: BASIS.lang60,
    tier: 'related',
    why: forGoal(g, 'lidé, kteří reagují, píšou česky. Je to jazyk komentářů, ne bydliště publika.', 'the people who react write in Czech. This is the language of the comments, not where the audience lives.'),
    relevance: ['c_cscomments'],
    aspect: 'local_language',
  })
  add({
    id: 'f:local',
    kind: 'fact',
    section: 'engagement',
    text: T('9 postů má místo v Brně nebo Brno zmiňuje.', '9 posts carry a Brno location or mention Brno.'),
    sources: [P.market, P.zrnko, P.lipa, P.run],
    conf: 'medium',
    basis: BASIS.local,
    tier: 'related',
    why: fit ? forGoal(g, 'vaše studio je v Brně a tenhle obsah také.', 'your studio is in Brno, and so is this content.') : forGoal(g, 'vaše prodejna je v Brně a tenhle obsah také.', 'your shop is in Brno, and so is this content.'),
    relevance: ['c_local'],
    aspect: 'local_language',
  })
  add({
    id: 'f:generic',
    kind: 'fact',
    section: 'engagement',
    text: T('14 % komentářů jsou jen emoji nebo obecné fráze.', '14% of comments are emoji-only or stock phrases.'),
    sources: [comments],
    conf: 'low',
    basis: BASIS.generic,
    tier: 'related',
    why: forGoal(g, 'hodně prázdných komentářů je signál, ne důkaz, nepravého publika. 14 % je málo.', 'many emoji-only comments are a signal, not proof, of an inauthentic audience. 14% is low.'),
    relevance: ['c_generic'],
    aspect: 'reach_engagement',
  })
  add({
    id: 'g:demographics',
    kind: 'gap',
    section: 'engagement',
    text: T('Věk, pohlaví a bydliště publika: ve veřejných datech nejsou.', 'Audience age, gender and location: not in public data.'),
    sources: [],
    conf: 'high',
    basis: BASIS.never,
    tier: 'related',
    why: T('Zeptejte se tvůrce na statistiky z aplikace. Neodhadujeme je.', 'Ask the creator for the statistics from the app. We do not estimate them.'),
    aspect: 'reach_engagement',
  })

  // ---- collaborations
  add({
    id: 'f:collab:pekarna_b',
    kind: 'fact',
    section: 'collabs',
    text: T('Společný post s Pekárnou B (@pekarna_b) 18. 9. 2026, bez označení reklamy.', 'Co-authored post with Pekárna B (@pekarna_b) on 18 Sep 2026, with no ad label.'),
    sources: [P.pekB],
    conf: 'high',
    basis: BASIS.coauthor,
    tier: fit ? 'related' : 'key',
    why: fit
      ? forGoal(g, 'není to konkurent, ale post nemá označení reklamy.', 'not a competitor, but the post has no ad label.')
      : T(
          'Pekárna B je váš konkurent: kampaň s někým, kdo ji nedávno propagoval, může vaše zákazníky přesvědčit méně.',
          'Pekárna B is your competitor: a campaign with someone who promoted them recently may convince your customers less.',
        ),
    relevance: fit ? ['c_disclose'] : ['c_competitors', 'c_disclose'],
    aspect: 'competitors',
  })
  if (!fit)
    add({
      id: 'i:competitor:pekarna_b',
      kind: 'inference',
      section: 'collabs',
      text: T(
        'Propagace vašeho konkurenta před třemi týdny dělá kampaň pro vaši pekárnu teď méně věrohodnou.',
        'Promoting your competitor three weeks ago makes a campaign for your bakery less credible right now.',
      ),
      sources: [],
      based_on: ['f:collab:pekarna_b'],
      conf: 'medium',
      basis: BASIS.infer1,
      tier: 'key',
      why: T('Než se na něčem domluvíte, zeptejte se, jestli spolupráce pořád běží.', 'Ask whether that collaboration is still running before you agree on anything.'),
      relevance: ['c_competitors'],
      aspect: 'competitors',
    })
  add({
    id: 'f:collab:proteomax',
    kind: 'fact',
    section: 'collabs',
    text: T('Placené partnerství s ProteoMax (@proteomax) 2. 9. 2026, označené.', 'Paid partnership with ProteoMax (@proteomax) on 2 Sep 2026, labeled.'),
    sources: [P.proteo],
    conf: 'high',
    basis: BASIS.paid,
    tier: fit ? 'key' : 'less',
    why: fit
      ? T(
          'ProteoMax je váš konkurent: kampaň s někým, kdo ho nedávno propagoval, může vaše zákazníky přesvědčit méně.',
          'ProteoMax is your competitor: a campaign with someone who promoted them recently may convince your customers less.',
        )
      : lessFor(g, 'značka není konkurent a post je označený.', 'the brand is not a competitor and the post is labeled.'),
    relevance: fit ? ['c_competitors'] : [],
    aspect: 'competitors',
  })
  if (fit)
    add({
      id: 'i:competitor:proteomax',
      kind: 'inference',
      section: 'collabs',
      text: T(
        'Označené partnerství s ProteoMax před pěti týdny dělá kampaň pro vaše fitness studio teď méně věrohodnou.',
        'A labeled ProteoMax partnership five weeks ago makes a campaign for your fitness studio less credible right now.',
      ),
      sources: [],
      based_on: ['f:collab:proteomax'],
      conf: 'medium',
      basis: BASIS.infer1,
      tier: 'key',
      why: T('Než se na něčem domluvíte, zeptejte se, jestli partnerství pořád běží a jestli je exkluzivní.', 'Ask whether the partnership is still running and whether it is exclusive before you agree on anything.'),
      relevance: ['c_competitors'],
      aspect: 'competitors',
    })
  add({
    id: 'f:undisclosed',
    kind: 'fact',
    section: 'collabs',
    text: T('2 ze 6 značkových postů nemají označení reklamy (18. 9. @pekarna_b, 26. 9. Bistro Lípa).', '2 of 6 brand posts carry no ad label (18 Sep @pekarna_b, 26 Sep Bistro Lípa).'),
    sources: [P.pekB, P.lipa],
    conf: 'medium',
    basis: BASIS.commercial,
    tier: 'key',
    why: forGoal(g, 'neoznačená reklama je problém pro vás i pro tvůrce (zákon o regulaci reklamy).', 'unlabeled ads are a problem for you and for the creator (advertising law).'),
    relevance: ['c_disclose'],
    aspect: 'ad_disclosure',
  })
  add({
    id: 'f:collab:lipa',
    kind: 'fact',
    section: 'collabs',
    text: T('Slevový kód KUBA10 pro Bistro Lípa (MOCK) 26. 9. 2026, bez označení reklamy.', 'Discount code KUBA10 for Bistro Lípa (MOCK) on 26 Sep 2026, with no ad label.'),
    sources: [P.lipa],
    conf: 'medium',
    basis: BASIS.caption,
    tier: 'related',
    why: forGoal(g, 'jak tvůrce označuje reklamu, se týká i vaší kampaně. Kód není důkaz platby.', 'how the creator labels ads matters for your campaign too. A code is not proof of payment.'),
    relevance: ['c_disclose'],
    aspect: 'ad_disclosure',
  })
  add({
    id: 'f:commercial',
    kind: 'fact',
    section: 'collabs',
    text: T('6 z 24 postů má štítek, reklamní hashtag nebo slevový kód (25 %).', '6 of 24 posts carry a label, an ad hashtag or a discount code (25%).'),
    sources: [P.proteo, P.pekA2, P.lipa],
    conf: 'medium',
    basis: BASIS.commercial,
    tier: 'related',
    why: forGoal(g, 'když je reklama skoro všechno, publikum ji přestává vnímat. 25 % je pod vaší hranicí 30 %.', 'when nearly everything is an ad, the audience tunes out. 25% is under your 30% limit.'),
    relevance: ['c_commercial'],
    aspect: 'ad_disclosure',
  })
  add({
    id: 'f:collab:pekarna_a',
    kind: 'fact',
    section: 'collabs',
    text: T('Dvě označené spolupráce s Pekárnou A (@pekarna_a): 12. 6. a 3. 8. 2026.', 'Two labeled collaborations with Pekárna A (@pekarna_a): 12 Jun and 3 Aug 2026.'),
    sources: [P.pekA1, P.pekA2],
    conf: 'high',
    basis: BASIS.paid,
    tier: 'less',
    why: lessFor(g, 'značka není ve vašem seznamu konkurentů a posty jsou označené.', 'the brand is not on your competitor list and the posts are labeled.'),
    aspect: 'competitors',
  })
  add({
    id: 'f:collab:zrnko',
    kind: 'fact',
    section: 'collabs',
    text: T('Zmínka o Kavárně Zrnko (MOCK) 20. 7. 2026.', 'Mention of Kavárna Zrnko (MOCK) on 20 Jul 2026.'),
    sources: [P.zrnko],
    conf: 'medium',
    basis: BASIS.caption,
    tier: 'less',
    why: lessFor(g, 'jen zmínka a značka není konkurent.', 'a mention only, and the brand is not a competitor.'),
    aspect: 'competitors',
  })

  // ---- news
  add({
    id: 'f:news:guide',
    kind: 'fact',
    section: 'news',
    text: T(
      'Brněnský deník (MOCK) uvádí @kuba.jidlo.brno mezi tvůrci, kteří mapují brněnská bistra (14. 9. 2026).',
      'Brněnský deník (MOCK) lists @kuba.jidlo.brno among the creators who map Brno bistros (14 Sep 2026).',
    ),
    sources: [newsGuide.source],
    conf: 'medium',
    basis: BASIS.newsOne,
    tier: 'related',
    why: fit
      ? forGoal(g, 'místní médium spojuje tvůrce s jídlem v Brně, ne s pohybem.', 'a local outlet connects this creator with Brno food, not with exercise.')
      : forGoal(g, 'místní médium už tvůrce spojuje s jídlem v Brně.', 'a local outlet already connects this creator with Brno food.'),
    aspect: 'reputation',
  })

  // ---- profile
  add({
    id: 'f:followers',
    kind: 'fact',
    section: 'profile',
    text: T('21 400 sledujících, 612 sledovaných, 388 postů.', '21,400 followers, 612 following, 388 posts.'),
    sources: [pProfile],
    conf: 'high',
    basis: BASIS.profile,
    tier: 'related',
    why: forGoal(g, 'menší tvůrci mívají bližší vztah s publikem a vejdou se do rozpočtu (5–50 tisíc).', 'smaller creators tend to be closer to their audience and fit a small budget (5k–50k).'),
    relevance: ['c_followers'],
    aspect: 'reach_engagement',
  })
  add({
    id: 'g:pricing',
    kind: 'gap',
    section: 'profile',
    text: T('Cena za post nebo video: není veřejná.', 'Price for a post or a video: not public.'),
    sources: [],
    conf: 'high',
    basis: BASIS.never,
    tier: 'related',
    why: T('Zeptejte se v první zprávě. Koncept oslovení to dělá.', 'Ask in the first message. The outreach draft does.'),
    aspect: 'practical',
  })
  add({
    id: 'f:public',
    kind: 'fact',
    section: 'profile',
    text: T('Veřejný účet.', 'Public account.'),
    sources: [pProfile],
    conf: 'high',
    basis: BASIS.profile,
    tier: 'less',
    why: lessFor(g, 'základní kontrola, která prošla.', 'a basic check that passed.'),
    relevance: ['c_public'],
    aspect: 'account',
  })
  add({
    id: 'f:active',
    kind: 'fact',
    section: 'profile',
    text: T('Poslední post před 2 dny (6. 10. 2026).', 'Last post 2 days ago (6 Oct 2026).'),
    sources: [P.market],
    conf: 'high',
    basis: BASIS.dates,
    tier: 'less',
    why: lessFor(g, 'základní kontrola, která prošla.', 'a basic check that passed.'),
    relevance: ['c_active'],
    aspect: 'account',
  })
  add({
    id: 'f:language',
    kind: 'fact',
    section: 'profile',
    text: T('22 z 24 popisků je česky.', '22 of 24 captions are in Czech.'),
    sources: [P.market, P.lipa],
    conf: 'medium',
    basis: BASIS.lang24,
    tier: 'less',
    why: lessFor(g, 'základní kontrola, která prošla.', 'a basic check that passed.'),
    relevance: ['c_lang'],
    aspect: 'local_language',
  })
  return out
}

/** One finding per enabled criterion (section "goal"): f:check:<id>, or g:check:<id> when it cannot be verified. */
function goalChecks(g: PresetName, lang: Lang): Spec[] {
  const cs = subjectCriteria(g, lang)
  const rs = resultsFor(g)
  const CONF: Record<string, [Confidence, I18nText]> = {
    c_public: ['high', BASIS.profile],
    c_followers: ['high', BASIS.profile],
    c_active: ['high', BASIS.dates],
    c_notbrand: ['medium', BASIS.profile],
    c_lang: ['medium', BASIS.lang24],
    c_topics: ['low', BASIS.topics],
    c_formats: ['high', BASIS.media],
    c_freq: ['high', BASIS.dates],
    c_commercial: ['medium', BASIS.commercial],
    c_engagement: ['medium', BASIS.engagement],
    c_cscomments: ['medium', BASIS.lang60],
    c_local: ['medium', BASIS.local],
    c_generic: ['low', BASIS.generic],
    c_competitors: ['high', g === 'fitness' ? BASIS.paid : BASIS.coauthor],
    c_disclose: ['medium', BASIS.commercial],
  }
  const WORD: Record<ResultStatus, I18nText> = { pass: T('splněno', 'met'), fail: T('nesplněno', 'not met'), unknown: T('nejde ověřit', 'cannot verify') }
  const BASIC = new Set(['c_public', 'c_active', 'c_lang'])
  return cs.criteria
    .filter((c) => c.enabled && rs[c.id])
    .map((c) => {
      const r = rs[c.id]
      const tier: RelevanceTier = r.status === 'fail' ? 'key' : r.status === 'pass' && BASIC.has(c.id) ? 'less' : 'related'
      const [conf, basis] = CONF[c.id] ?? ['medium', BASIS.check]
      const label = { cs: c.label.cs ?? '', en: c.label.en ?? '' }
      const why = { cs: c.why.cs ?? '', en: c.why.en ?? '' }
      return {
        id: `${r.status === 'unknown' ? 'g' : 'f'}:check:${c.id}`,
        kind: r.status === 'unknown' ? 'gap' : 'fact',
        section: 'goal',
        text: T(`${label.cs}: ${r.value.cs} (požadavek ${r.threshold.cs}), ${WORD[r.status].cs}.`, `${label.en}: ${r.value.en} (needs ${r.threshold.en}), ${WORD[r.status].en}.`),
        sources: r.sources,
        conf,
        basis: T(`kontrola nad: ${basis.cs}`, `check on ${basis.en}`),
        tier,
        why: tier === 'less' ? lessFor(g, 'základní kontrola, která prošla.', 'a basic check that passed.') : forGoal(g, why.cs.replace(/^./, (x) => x.toLowerCase()), why.en.replace(/^./, (x) => x.toLowerCase())),
        relevance: [c.id],
        aspect: 'content_fit',
      } satisfies Spec
    })
}

function collabsFor(g: PresetName): CollabEvidence[] {
  const fit = g === 'fitness'
  const C = (id: string, brand: string, handle: string | null, kind: CollabEvidence['kind'], disclosed: boolean | null, date: string, source: SourceRef, comp = false): CollabEvidence => ({
    id,
    brand,
    brand_handle: handle,
    kind,
    disclosed,
    date,
    post_id: source.id,
    is_competitor: comp,
    source,
  })
  return [
    C('cb-k-peka1', 'Pekárna A (MOCK)', 'pekarna_a', 'paid_label', true, isoDate(2026, 6, 12), P.pekA1),
    C('cb-k-zrnko', 'Kavárna Zrnko (MOCK)', 'kavarna_zrnko', 'mention', null, isoDate(2026, 7, 20), P.zrnko),
    C('cb-k-peka2', 'Pekárna A (MOCK)', 'pekarna_a', 'ad_hashtag', true, isoDate(2026, 8, 3), P.pekA2),
    C('cb-k-proteo', 'ProteoMax (MOCK)', 'proteomax', 'paid_label', true, isoDate(2026, 9, 2), P.proteo, fit),
    C('cb-k-pekb', 'Pekárna B (MOCK)', 'pekarna_b', 'coauthor', false, isoDate(2026, 9, 18), P.pekB, !fit),
    C('cb-k-lipa', 'Bistro Lípa (MOCK)', null, 'discount_code', false, isoDate(2026, 9, 26), P.lipa),
  ]
}

function claimsFor(g: PresetName): ClaimCheck[] {
  const fit = g === 'fitness'
  return [
    {
      id: 'k:exclusive',
      claim: 'exkluzivní ambasador @pekarna_a',
      claim_gloss: T('exkluzivní ambasador @pekarna_a', 'exclusive ambassador of @pekarna_a'),
      claim_source: pProfile,
      evidence: ['cb-k-pekb', 'cb-k-peka1', 'cb-k-peka2'],
      status: 'conflicts_with_record',
      confidence: 'medium',
      confidence_basis: T('vlastní popisek vs. záznam spoluprací', 'own caption vs. collaboration record'),
      note: T(
        'Bio tvrdí exkluzivitu s @pekarna_a, ale 18. 9. 2026 má tvůrce společný post s jinou pekárnou, @pekarna_b. Podmínky smlouvy neznáme.',
        'The bio claims exclusivity with @pekarna_a, but on 18 Sep 2026 the creator co-authored a post with another bakery, @pekarna_b. We do not know the contract terms.',
      ),
      relevance: ['c_competitors', 'c_disclose'],
      aspect: 'competitors',
      tier: 'key',
      why_it_matters: fit
        ? forGoal(g, 'tvrzení, kterému záznam neodpovídá, stojí za jednu otázku, než se na něčem domluvíte.', 'a claim the record does not match is worth one question before you agree on anything.')
        : T(
            'Exkluzivita s Pekárnou A, která vypadá jako firma z vašeho oboru (shoda názvu, odhad), může spolupráci s vámi vyloučit.',
            'An exclusivity deal with Pekárna A, which looks like a business in your category (name match, a guess), may rule out working with you.',
          ),
    },
    {
      id: 'k:proteomax',
      claim: 'hrdý partner @proteomax',
      claim_gloss: T('hrdý partner @proteomax', 'proud partner of @proteomax'),
      claim_source: P.proteo,
      evidence: ['cb-k-proteo'],
      status: 'supported',
      confidence: 'high',
      confidence_basis: T('vlastní popisek vs. štítek placeného partnerství', 'own caption vs. paid-partnership label'),
      note: T('Štítek placeného partnerství na platformě partnerství s ProteoMax potvrzuje.', "The platform's paid-partnership label confirms the ProteoMax partnership."),
      relevance: ['c_competitors', 'c_disclose'],
      aspect: 'competitors',
      tier: fit ? 'key' : 'related',
      why_it_matters: fit
        ? T('ProteoMax je váš konkurent: tvůrce to říká veřejně a záznam to potvrzuje.', 'ProteoMax is your competitor: the creator says so publicly and the record confirms it.')
        : forGoal(g, 'označené partnerství se značkou, která není váš konkurent.', 'a labeled partnership with a brand that is not your competitor.'),
    },
    {
      id: 'k:unpaid',
      claim: 'Recenze, nikdo mi za ně neplatí.',
      claim_gloss: T('Recenze, nikdo mi za ně neplatí.', 'Reviews, nobody pays me for them.'),
      claim_source: P.lipa,
      evidence: ['cb-k-lipa'],
      status: 'cannot_verify',
      confidence: 'low',
      confidence_basis: T('vlastní popisek vs. záznam spoluprací', 'own caption vs. collaboration record'),
      note: T(
        'Post má slevový kód pro Bistro Lípa. Kód není důkaz platby, takže nejde říct ani jedno.',
        'The post has a discount code for Bistro Lípa. A code is not proof of payment, so we cannot say either way.',
      ),
      relevance: ['c_disclose'],
      aspect: 'ad_disclosure',
      tier: 'related',
      why_it_matters: forGoal(g, 'jak tvůrce označuje reklamu, se týká i vaší kampaně.', 'how the creator labels ads matters for your campaign too.'),
    },
  ]
}

function questionsFor(g: PresetName): I18nText[] {
  const fit = g === 'fitness'
  // the exclusivity question already covers Pekárna B for the bakery, so the competitor template is not repeated
  const q: I18nText[] = [
    fit
      ? T(
          'V bio uvádíte exkluzivitu s @pekarna_a, ale 18. 9. jste měl společný post s @pekarna_b. Platí exkluzivita pořád?',
          'Your bio says you are an exclusive ambassador of @pekarna_a, but on 18 Sep you co-authored a post with @pekarna_b. Is the exclusivity still in place?',
        )
      : T(
          'V bio uvádíte exkluzivitu s @pekarna_a, ale 18. 9. jste měl společný post s naším konkurentem @pekarna_b. Platí exkluzivita pořád a vylučuje i jiné pekárny, jako je ta naše?',
          'Your bio says you are an exclusive ambassador of @pekarna_a, but on 18 Sep you co-authored a post with our competitor @pekarna_b. Is the exclusivity still in place, and does it rule out other bakeries like ours?',
        ),
    T(
      'Dva značkové posty nemají označení reklamy (18. 9. @pekarna_b, 26. 9. Bistro Lípa). Jak označujete placené posty?',
      'Two brand posts have no ad label (18 Sep @pekarna_b, 26 Sep Bistro Lípa). How do you label paid posts?',
    ),
  ]
  if (fit) {
    q.push(
      T(
        'Natočil byste post o našem fitness studiu, i když fitness, sport a lokální tipy nejsou vaše hlavní téma?',
        'Would you make a post about our fitness studio even though fitness, sport and local tips are not your main topic?',
      ),
      T('Spolupracoval jste s ProteoMax (2. 9. 2026). Běží to ještě a je v tom exkluzivita?', 'You worked with ProteoMax (2 Sep 2026). Is that still running, and does it include exclusivity?'),
    )
  }
  q.push(
    T('Kolik vašich sledujících je z Brna? Můžete poslat statistiku měst z aplikace?', 'How many of your followers are in Brno? Could you share the city statistics from the app?'),
    T('Jaké je věkové a genderové složení vašeho publika? Ve veřejných datech to není.', 'What is the age and gender split of your audience? It is not in public data.'),
    T('Kolik si účtujete za post nebo krátké video?', 'What do you charge for a post or a short video?'),
  )
  return q
}

function outreachFor(g: PresetName): I18nText {
  return g === 'fitness'
    ? T(
        'Dobrý den, Kubo,\n\nmáme fitness studio v Brně a chceme, aby víc lidí zkusilo zkušební lekci. Líbí se nám, jak ukazujete Brno, a ranní běh kolem Prýglu by k nám sedl.\n\nNež se domluvíme na podmínkách: v září jste měl partnerství s ProteoMax. Běží ještě a je v něm exkluzivita?\n\nRozpočet máme do 30 tisíc Kč. Kolik si účtujete za post nebo krátké video?\n\nDěkujeme,\n[vaše jméno]',
        'Hi Kuba,\n\nWe run a fitness studio in Brno and want more people to try a trial class. We like how you show Brno, and your morning run around Prýgl would fit us well.\n\nBefore we talk terms: in September you had a partnership with ProteoMax. Is it still running, and does it include exclusivity?\n\nOur budget is up to CZK 30,000. What do you charge for a post or a short video?\n\nThanks,\n[your name]',
      )
    : T(
        'Dobrý den, Kubo,\n\nmáme pekárnu v Brně a uvádíme nový kváskový chléb. Líbí se nám vaše tipy na brněnská bistra a trhy.\n\nNatočil byste u nás krátké video nebo post? Než se domluvíme na podmínkách: v bio uvádíte exkluzivitu s Pekárnou A. Co přesně pokrývá?\n\nRozpočet máme do 20 tisíc Kč. Kolik si účtujete za post nebo krátké video?\n\nDěkujeme,\n[vaše jméno]',
        'Hi Kuba,\n\nWe run a bakery in Brno and are launching a new sourdough bread. We like your tips on Brno bistros and markets.\n\nWould you make a short video or a post at our shop? Before we talk terms: your bio mentions an exclusive deal with Pekárna A. What exactly does it cover?\n\nOur budget is up to CZK 20,000. What do you charge for a post or a short video?\n\nThanks,\n[your name]',
      )
}

const SECTION_TITLES: Record<string, I18nText> = {
  identity: T('Identita', 'Identity'),
  goal: T('Kontroly podle cíle', 'Goal checks'),
  claims: T('Tvrzení vs. záznam', 'Claims vs. record'),
  collabs: T('Spolupráce', 'Collaborations'),
  content: T('Obsah', 'Content'),
  engagement: T('Interakce a publikum', 'Engagement and audience'),
  news: T('Zprávy', 'News'),
  profile: T('Profil', 'Profile'),
}
const DEFAULT_ORDER = ['claims', 'collabs', 'content', 'engagement', 'news', 'profile']
const RANK: Record<RelevanceTier, number> = { key: 2, related: 1, less: 0 }

const IDENTITY: IdentityMatch[] = [
  {
    handle: 'kubajidlo.brno',
    platform: 'tiktok',
    status: 'matched',
    signals: [
      { signal: T('odkazuje zpět na @kuba.jidlo.brno', 'links back to @kuba.jidlo.brno'), supports: true, source: ttMatch },
      { signal: T('stejné jméno a Brno v bio', 'same display name and Brno in the bio'), supports: true, source: ttMatch },
    ],
  },
  {
    handle: 'kubajidlo',
    platform: 'youtube',
    status: 'uncertain',
    signals: [{ signal: T('jen podobný název, žádný odkaz', 'similar name only, no link'), supports: false, source: ytUnc }],
  },
  {
    handle: 'kuba_jidlo',
    platform: 'tiktok',
    status: 'rejected',
    signals: [
      { signal: T('v bio Bratislava, kotva je Brno', 'bio says Bratislava, the anchor is Brno'), supports: false, source: ttLook },
      { signal: T('účty na sebe neodkazují', 'no link between the accounts'), supports: false, source: ttLook },
    ],
  },
  {
    handle: 'kuba.jidlo.brno.fans',
    platform: 'instagram',
    status: 'rejected',
    signals: [{ signal: T('znaky fanouškovského účtu: „Fan page“', 'fan-account markers: “Fan page”'), supports: false, source: igFan }],
  },
]

const SET_ASIDE: NonNullable<IdentityVerdict['set_aside']> = [
  { ref: 'tiktok:kuba_jidlo', label: 'TikTok @kuba_jidlo', kind: 'look_alike', reason: T('jiné město v bio (Bratislava) a žádný odkaz mezi účty', 'different city in the bio (Bratislava) and no link between the accounts'), source: ttLook },
  { ref: 'youtube:kubajidlo', label: 'YouTube @kubajidlo', kind: 'look_alike', reason: T('jen podobný název, žádný odkaz', 'similar name only, no link'), source: ytUnc },
  {
    ref: 'instagram:kuba.jidlo.brno.fans',
    label: 'Instagram @kuba.jidlo.brno.fans',
    kind: 'fan_account',
    reason: T('bio: „Fan page · nejsme Kuba“', 'bio: “Fan page · nejsme Kuba” (“we are not Kuba”)'),
    source: igFan,
  },
  {
    ref: `news:${newsNamesake.id}`,
    label: T(`${newsNamesake.outlet}: „${newsNamesake.title}“`, `${newsNamesake.outlet}: “${newsNamesake.title}”`),
    kind: 'namesake',
    reason: T('jiné město (Zlín) a jiný obor (podnikatel, jídelny)', 'different city (Zlín) and a different field (businessman, canteens)'),
    source: newsNamesake.source,
  },
]
const ASIDE_TEXT = T(
  'Odložili jsme 4 podobné účty nebo jmenovce: TikTok @kuba_jidlo, YouTube @kubajidlo, Instagram @kuba.jidlo.brno.fans, Zlínský deník (MOCK): „Zlínský podnikatel Jakub Kubíček…“.',
  'We set aside 4 look-alike or namesake sources: TikTok @kuba_jidlo, YouTube @kubajidlo, Instagram @kuba.jidlo.brno.fans, Zlínský deník (MOCK): “Zlínský podnikatel Jakub Kubíček…”.',
)

/** The verdict templates of section 5.3, filled for the anchor the owner gave. */
function verdictFor(ctx: SubjectCtx): IdentityVerdict {
  const { city, site } = anchorWords(ctx)
  const anchor = ctx.anchor && (ctx.anchor.city || ctx.anchor.website || ctx.anchor.company_id) ? ctx.anchor : null
  const common = { set_aside: SET_ASIDE, anchor }
  const problem = identityProblem(ctx)
  if (problem)
    return {
      ...common,
      status: 'uncertain',
      text: T(
        `Nepodařilo se potvrdit, že @${H} je tvůrce, kterého myslíte: ${problem.cs}. Zkontrolujte účet nebo zadejte jinou kotvu (město, web nebo IČO). ${ASIDE_TEXT.cs}`,
        `We could not confirm @${H} is the creator you mean: ${problem.en}. Check the handle or give another anchor (city, website or company ID). ${ASIDE_TEXT.en}`,
      ),
      supporting: [TT_SIGNAL],
      contradicting: [{ signal: problem, supports: false, source: pProfile }],
    }
  switch (anchorCase(ctx.anchor)) {
    case 'website':
      return {
        ...common,
        status: 'confirmed',
        text: T(
          `Jsme si jistí, že @${H} je tvůrce, kterého myslíte: web ${site} je v profilu a TikTok @kubajidlo.brno odkazuje zpět na tento profil. ${ASIDE_TEXT.cs}`,
          `We are confident @${H} is the creator you mean because the website ${site} is on the profile, TikTok @kubajidlo.brno links back to this profile. ${ASIDE_TEXT.en}`,
        ),
        supporting: [{ signal: T(`web ${site} (kotva) je v profilu`, `the website ${site} (the anchor) is on the profile`), supports: true, source: pProfile }, TT_SIGNAL],
        contradicting: [],
      }
    case 'none':
      return {
        ...common,
        status: 'likely',
        text: T(
          `@${H} je pravděpodobně tvůrce, kterého myslíte: TikTok @kubajidlo.brno odkazuje zpět na tento profil. Potvrdilo by to město, web nebo IČO tvůrce. ${ASIDE_TEXT.cs}`,
          `@${H} is probably the creator you mean: TikTok @kubajidlo.brno links back to this profile. Their city, website or company ID would confirm it. ${ASIDE_TEXT.en}`,
        ),
        supporting: [TT_SIGNAL],
        contradicting: [],
      }
    default:
      return {
        ...common,
        status: 'confirmed',
        text: T(
          `Jsme si jistí, že @${H} je tvůrce, kterého myslíte: ${city} je v bio a TikTok @kubajidlo.brno odkazuje zpět na tento profil. ${ASIDE_TEXT.cs}`,
          `We are confident @${H} is the creator you mean because ${city} is in the bio and TikTok @kubajidlo.brno links back to this profile. ${ASIDE_TEXT.en}`,
        ),
        supporting: [{ signal: T(`${city} (kotva) je v bio`, `${city} (the anchor) is in the bio`), supports: true, source: pProfile }, TT_SIGNAL],
        contradicting: [],
      }
  }
}

/** Fail + unknown checks for a goal (the run log's "n checks not met or not verifiable"). */
export function subjectOpenChecks(preset: PresetName): number {
  return Object.values(resultsFor(preset)).filter((r) => r.status !== 'pass').length
}

export function subjectReport(g: PresetName, lang: Lang, ctx: SubjectCtx = subjectCtx()): Report {
  const fit = g === 'fitness'
  const specs = [...goalChecks(g, lang), ...findingsFor(g, ctx)]
  const findings: Finding[] = specs.map((x) => ({
    id: x.id,
    kind: x.kind,
    section: x.section,
    text: x.text,
    sources: x.sources,
    based_on: x.based_on,
    relevance: x.relevance,
    confidence: x.conf,
    confidence_basis: x.basis,
    aspect: x.aspect,
    tier: x.tier,
    why_it_matters: x.why,
  }))
  const claims = claimsFor(g).sort((a, b) => RANK[b.tier ?? 'related'] - RANK[a.tier ?? 'related'])

  // sections: identity, goal, then the rest by number of key items (then the default order)
  const items = [...findings.map((f) => ({ id: f.id, section: f.section as string, tier: f.tier ?? 'related' })), ...claims.map((k) => ({ id: k.id, section: 'claims', tier: k.tier ?? 'related' }))]
  const order = items.map((x) => x.id)
  const secIds = ['identity', 'goal', ...DEFAULT_ORDER]
  const sections: ReportSection[] = secIds
    .map((id) => {
      const mine = items.filter((x) => x.section === id).sort((a, b) => RANK[b.tier] - RANK[a.tier] || order.indexOf(a.id) - order.indexOf(b.id))
      const shown = mine.filter((x) => x.tier !== 'less')
      const best = mine.reduce<RelevanceTier>((m, x) => (RANK[x.tier] > RANK[m] ? x.tier : m), 'less')
      return { id, title: SECTION_TITLES[id], tier: best, item_ids: shown.map((x) => x.id), less_ids: mine.filter((x) => x.tier === 'less').map((x) => x.id) }
    })
    .filter((s) => s.item_ids.length || s.less_ids.length)
  const keyN = (s: ReportSection) => items.filter((x) => s.item_ids.includes(x.id) && x.tier === 'key').length
  const head = sections.filter((s) => s.id === 'identity' || s.id === 'goal')
  const rest = sections.filter((s) => s.id !== 'identity' && s.id !== 'goal').sort((a, b) => keyN(b) - keyN(a) || DEFAULT_ORDER.indexOf(a.id) - DEFAULT_ORDER.indexOf(b.id))
  const ordered = [...head, ...rest]
  const lessIds = ordered.flatMap((s) => s.less_ids ?? [])
  const shownIds = ordered.flatMap((s) => s.item_ids)
  const byId = new Map(findings.map((f) => [f.id, f]))
  const flat = [...shownIds, ...lessIds].map((id) => byId.get(id)).filter((f): f is Finding => !!f)

  const brief = PRESETS[g][lang]
  const problem = identityProblem(ctx)
  const ac = anchorCase(ctx.anchor)
  const viaLink = /^(https?:\/\/)?([a-z0-9-]+\.)*(instagram|tiktok)\.com\//i.test(ctx.raw.trim())
  const anchorCs = ac === 'none' ? 'Kotva: žádná.' : `Kotva: ${anchorText(ctx.anchor, 'cs')}.`
  const anchorEn = ac === 'none' ? 'Anchor: none given.' : `Anchor: ${anchorText(ctx.anchor, 'en')}.`
  const supN = verdictFor(ctx).supporting?.length ?? 0
  const conN = verdictFor(ctx).contradicting?.length ?? 0
  // &llm: the model wrote the texts during vetting for the first goal; a goal switch makes no new requests, so the
  // per-goal texts (skeptic, outreach) of another goal come from rules and a template (docs/subject-mode.md 6.1)
  const llmHere = ctx.llm && g === ctx.firstGoal
  const textSource = !ctx.llm
    ? { claims: 'rules', news: 'rules', skeptic: 'rules', questions: 'template', outreach: 'template' }
    : llmHere
      ? { claims: 'llm+rules', news: 'llm', skeptic: 'llm+rules', questions: 'llm+template', outreach: 'llm' }
      : { claims: 'llm+rules', news: 'llm', skeptic: 'rules', questions: 'llm+template', outreach: 'template' }
  const textLine = !ctx.llm
    ? T(
        'Tvrzení, zprávy, otázky a oslovení: pravidla a šablony (ukázka běží bez jazykového modelu). Přepnutí cíle report přeřadí a přepíše ze stejných dat, bez nových požadavků.',
        'Claims, news, questions and outreach: rules and templates (this demo runs without a language model). Switching the goal re-orders and rewrites this report from the data already fetched: no new requests.',
      )
    : llmHere
      ? T(
          'Tvrzení, zprávy, otázky, skeptik a oslovení: jazykový model (5 požadavků při prověrce), jeho tvrzení znovu ověřená pravidly proti nasbíraným důkazům. Přepnutí cíle report přeřadí a přepíše ze stejných dat, bez nových požadavků.',
          'Claims, news, questions, skeptic and outreach: language model (5 requests during vetting), with its claims re-checked by rules against the collected evidence. Switching the goal re-orders and rewrites this report from the data already fetched: no new requests.',
        )
      : T(
          `Tvrzení, zprávy a otázky: jazykový model (5 požadavků při prověrce pro cíl ${PRESETS[ctx.firstGoal].cs.business_type}), ověřené pravidly. Skeptik a oslovení pro tento cíl: pravidla a šablona, protože přepnutí cíle report přeřadí a přepíše ze stejných dat, bez nových požadavků.`,
          `Claims, news and questions: language model (5 requests during vetting, for the ${PRESETS[ctx.firstGoal].en.business_type} goal), re-checked by rules. Skeptic and outreach for this goal: rules and a template, because switching the goal re-orders and rewrites this report from the data already fetched: no new requests.`,
        )
  return {
    candidate_id: SUBJECT_ID,
    findings: flat,
    claims,
    collab_timeline: collabsFor(g),
    news: [{ item: newsGuide, label: 'neutral', attribution: 'Brněnský deník (MOCK)' }],
    identity: IDENTITY,
    questions: questionsFor(g),
    outreach_draft: outreachFor(g),
    not_checked: NOT_CHECKED,
    skeptic_notes: [
      T(
        'Nesoulad s exkluzivitou stojí na jednom společném postu. Spoluautorství může být jednorázová laskavost; než uděláte závěr, zeptejte se.',
        'The exclusivity conflict rests on one co-authored post. Co-authoring can be a one-off favour; ask before you draw conclusions.',
      ),
    ],
    sensitive_filtered: 1,
    vetted_for: PRESETS[ctx.firstGoal][lang].business_type,
    identity_verdict: verdictFor(ctx),
    rendered_for: { business_type: brief.business_type, goal: brief.goal, city: brief.city, brief_key: `demo-${g}` },
    summary: (() => {
      const body = fit
        ? T(
            'ProteoMax, váš konkurent, měl s tvůrcem označené partnerství (2. 9. 2026). Jen 13 % posledních postů je o fitness, sportu nebo lokálních tipech. 2 značkové posty nemají označení reklamy.',
            'ProteoMax, your competitor, had a labeled partnership with the creator (2 Sep 2026). Only 13% of recent posts are about fitness, sport or local tips. 2 brand posts have no ad label.',
          )
        : T(
            'Bio tvrdí exkluzivitu s @pekarna_a, ale záznam ukazuje společný post s vaším konkurentem @pekarna_b (18. 9. 2026). 71 % posledních postů sedí k vašim tématům. 2 značkové posty nemají označení reklamy.',
            'The bio claims exclusivity with @pekarna_a, but the record shows a co-authored post with your competitor @pekarna_b (18 Sep 2026). 71% of recent posts fit your topics. 2 brand posts have no ad label.',
          )
      // an unconfirmed identity comes first: everything below may be about someone else
      return problem ? T(`Identita nepotvrzená: ${problem.cs}. ${body.cs}`, `Identity not confirmed: ${problem.en}. ${body.en}`) : body
    })(),
    sections: ordered,
    less_relevant: lessIds,
    text_source: textSource,
    method: [
      T(
        `Tvůrce: @kuba.jidlo.brno na Instagramu, ${viaLink ? 'z odkazu na profil' : 'podle účtu, který jste zadali'}. ${anchorCs}`,
        `Subject: @kuba.jidlo.brno on Instagram, ${viaLink ? 'taken from the profile link' : 'from the handle you typed'}. ${anchorEn}`,
      ),
      T(
        'Staženo (MOCK): profil, 24 posledních postů, 60 komentářů, 4 účty na jiných platformách, 6 záznamů spoluprací, 2 zprávy.',
        'Fetched (MOCK): the profile, 24 recent posts, 60 comments, 4 accounts on other platforms, 6 collaboration records, 2 news items.',
      ),
      T('Odfiltrováno před uložením: 1 položka na citlivé téma (jen počet).', 'Filtered before storage: 1 item on a sensitive topic (count only).'),
      T(
        `Identita: ${supN} ${supN === 1 ? 'signál' : 'signály'} pro${conN ? `, ${conN} proti` : ''}; odloženy 3 podobné účty a 1 jmenovec ve zprávách.`,
        `Identity: ${supN} supporting ${supN === 1 ? 'signal' : 'signals'}${conN ? `, ${conN} against` : ''}; set aside 3 look-alike accounts and 1 namesake in the news.`,
      ),
      T('Každý fakt odkazuje na zdroj, odhady říkají, na kterých faktech stojí, mezery říkají, co jsme ověřit nemohli.', 'Every fact links to its source; inferences say which facts they rest on; gaps say what we could not check.'),
      fit
        ? T(`Seřazeno pro váš cíl: fitness studio v Brně. ${lessIds.length} nálezů je sbalených jako méně důležité.`, `Ordered for your goal: fitness studio in Brno. ${lessIds.length} findings are collapsed as less relevant.`)
        : T(`Seřazeno pro váš cíl: pekárna v Brně. ${lessIds.length} nálezů je sbalených jako méně důležité.`, `Ordered for your goal: bakery in Brno. ${lessIds.length} findings are collapsed as less relevant.`),
      textLine,
    ],
    last_diff: null,
  }
}

// ---------------------------------------------------------------------------------------------
// Report diff, computed from two renders (mirrors diff_reports in docs/subject-mode.md section 6)
// ---------------------------------------------------------------------------------------------

export function subjectDiff(from: PresetName, to: PresetName, lang: Lang, ctx: SubjectCtx = subjectCtx()): ReportDiff {
  const a = subjectReport(from, lang, ctx)
  const b = subjectReport(to, lang, ctx)
  const tierOf = (r: Report) => {
    const m = new Map<string, RelevanceTier>()
    for (const f of r.findings) m.set(f.id, f.tier ?? 'related')
    for (const k of r.claims) m.set(k.id, k.tier ?? 'related')
    return m
  }
  const ta = tierOf(a)
  const tb = tierOf(b)
  const added = [...tb.keys()].filter((id) => !ta.has(id))
  const removed = [...ta.keys()].filter((id) => !tb.has(id))
  const common = [...tb.keys()].filter((id) => ta.has(id))
  const moved_up = common.filter((id) => RANK[tb.get(id)!] > RANK[ta.get(id)!])
  const moved_down = common.filter((id) => RANK[tb.get(id)!] < RANK[ta.get(id)!])
  const collapsed = common.filter((id) => tb.get(id) === 'less' && ta.get(id) !== 'less')
  const claimA = new Map(a.claims.map((k) => [k.id, k]))
  const claims_changed = b.claims
    .filter((k) => claimA.has(k.id) && (claimA.get(k.id)!.status !== k.status || claimA.get(k.id)!.tier !== k.tier))
    .map((k) => ({ id: k.id, status: [claimA.get(k.id)!.status, k.status] as [string, string], tier: [claimA.get(k.id)!.tier ?? null, k.tier ?? null] as [string | null, string | null] }))
  const ra = resultsFor(from)
  const rb = resultsFor(to)
  const checks_changed = Object.keys(rb)
    .filter((id) => ra[id]?.status !== rb[id]?.status)
    .map((id) => ({ criterion_id: id, status: [ra[id]?.status ?? null, rb[id]?.status ?? null] as [ResultStatus | null, ResultStatus | null] }))
  const qa = new Set(a.questions.map((q) => q.cs))
  const qb = new Set(b.questions.map((q) => q.cs))
  const questions_added = b.questions.filter((q) => !qa.has(q.cs))
  const questions_removed = a.questions.filter((q) => !qb.has(q.cs))
  const outreach_changed = JSON.stringify(a.outreach_draft) !== JSON.stringify(b.outreach_draft)

  // "2 findings became key (ProteoMax is now a competitor), 1 moved down, ..."
  const findingIds = new Set(b.findings.map((f) => f.id))
  const becameKey = [...added, ...moved_up].filter((id) => findingIds.has(id) && tb.get(id) === 'key').length
  const down = moved_down.filter((id) => findingIds.has(id)).length
  const brandNow = b.collab_timeline.find((c) => c.is_competitor)?.brand.replace(/ \(MOCK\)$/, '')
  const pl = (n: number, one: string, other: string) => `${n} ${n === 1 ? one : other}`
  const csPl = (n: number, one: string, few: string, many: string) => `${n} ${n === 1 ? one : n >= 2 && n <= 4 ? few : many}`
  const en: string[] = []
  const cz: string[] = []
  if (becameKey) {
    en.push(`${pl(becameKey, 'finding became', 'findings became')} key${brandNow ? ` (${brandNow} is now a competitor)` : ''}`)
    cz.push(`${csPl(becameKey, 'nález je', 'nálezy jsou', 'nálezů je')} nově klíčové${brandNow ? ` (${brandNow} je teď konkurent)` : ''}`)
  }
  if (down) {
    en.push(`${pl(down, 'finding', 'findings')} moved down`)
    cz.push(`${csPl(down, 'nález klesl', 'nálezy klesly', 'nálezů kleslo')} níž`)
  }
  if (removed.length) {
    en.push(`${pl(removed.length, 'inference', 'inferences')} dropped`)
    cz.push(`${csPl(removed.length, 'odhad vypadl', 'odhady vypadly', 'odhadů vypadlo')}`)
  }
  if (collapsed.length) {
    en.push(`${collapsed.length} moved to less relevant`)
    cz.push(`${collapsed.length} mezi méně důležité`)
  }
  if (claims_changed.length) {
    en.push(`${pl(claims_changed.length, 'claim', 'claims')} changed relevance`)
    cz.push(`${csPl(claims_changed.length, 'tvrzení změnilo', 'tvrzení změnila', 'tvrzení změnilo')} důležitost`)
  }
  if (checks_changed.length) {
    en.push(`${pl(checks_changed.length, 'check', 'checks')} changed`)
    cz.push(`${csPl(checks_changed.length, 'kontrola se změnila', 'kontroly se změnily', 'kontrol se změnilo')}`)
  }
  if (questions_added.length) {
    en.push(`${pl(questions_added.length, 'new question', 'new questions')}`)
    cz.push(`${csPl(questions_added.length, 'nová otázka', 'nové otázky', 'nových otázek')}`)
  }
  if (outreach_changed) {
    en.push('outreach draft rewritten')
    cz.push('koncept oslovení přepsaný')
  }
  const fromEn = PRESETS[from].en.business_type
  const toEn = PRESETS[to].en.business_type
  const fromCs = PRESETS[from].cs.business_type
  const toCs = PRESETS[to].cs.business_type
  const summary = en.length
    ? T(`Cíl ${fromCs} → ${toCs}: ${cz.join(', ')}.`, `Goal changed from ${fromEn} to ${toEn}: ${en.join(', ')}.`)
    : T('Pro tento cíl je report stejný.', 'The report is the same for this goal.')
  const goal = (g: PresetName) => ({ business_type: PRESETS[g][lang].business_type, goal: PRESETS[g][lang].goal, brief_key: `demo-${g}` })
  return {
    candidate_id: SUBJECT_ID,
    from_goal: goal(from),
    to_goal: goal(to),
    added,
    removed,
    moved_up,
    moved_down,
    collapsed,
    claims_changed,
    checks_changed,
    questions_added,
    questions_removed,
    outreach_changed,
    summary,
  }
}
