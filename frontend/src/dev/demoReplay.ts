// Demo replay (?demo=1). Feeds a realistic synthetic event sequence through the SAME reducer the backend
// events go through, so the UI can be checked without a backend. Everything here is MOCK and labeled so.
// Texts are written in both languages and picked when a step plays; finished chat messages keep both, so the
// language toggle re-renders them.
//
// URL flags: ?demo=1                    one named creator (the jury's flow, docs/subject-mode.md): resolve,
//                                       checks, report; then "Continue" switches the goal (same creator)
//            &scenario=discovery        discovery: play the bakery run, then wait for "Change goal"
//            &scenario=empty            start on the empty screen; the chat examples and the
//                                       "Already have a creator in mind?" form start a scenario
//            &full=1                    also play the goal change automatically (fitness studio)
//            &instant=1                 apply everything synchronously (for screenshots / headless checks)
//            &speed=2                   playback speed
//            &llm=openrouter|anthropic  show a (MOCK) LLM provider and request budget in the header

import type { Action } from '../state'
import type { Anchor, Candidate, ChatEvent, Health, I18nText, Lang, LogLine, RunEvent } from '../types'
import { translate } from '../i18n'
import { anchorText, readAnchor } from '../lib/subject'
import type { PresetName } from '../lib/presets'
import { CRITERIA_BAKERY, CRITERIA_FITNESS, BRIEF_FITNESS, BRIEF_FITNESS_EN, SEEDS, candidateAt, evaluate, finalState, idOf, localized, pfOf } from './demoData'
import { ROUND4, VETTING_STEPS } from './demoReports'
import {
  SUBJECT_ANCHOR,
  SUBJECT_HANDLE,
  SUBJECT_ID,
  SUBJECT_RUN_ID,
  identityLog,
  subjectCandidate,
  subjectCriteria,
  subjectCtx,
  subjectDiff,
  subjectOpenChecks,
  subjectReport,
  type SubjectCtx,
} from './demoSubject'

export type DemoScenario = 'discovery' | 'subject' | 'empty'

export interface DemoStatus {
  scenario: DemoScenario
  phase: 'bakery' | 'goal' | 'subject' | 'subjectGoal' | 'idle'
  playing: boolean
  progress: number
  speed: number
  bakeryDone: boolean
  goalDone: boolean
  /** subject scenario: the report is ready */
  subjectDone: boolean
  /** subject scenario: the goal the report is rendered for */
  subjectGoal: PresetName
}

export interface SubjectDemoInput {
  typed?: string
  /** what the owner typed ("@handle" or a profile link) */
  raw?: string
  /** undefined: the demo's own anchor (city Brno); null: the owner gave none ("skip") */
  anchor?: Anchor | null
  preset?: PresetName
}

export interface DemoController {
  start: () => void
  stop: () => void
  pause: () => void
  resume: () => void
  restart: () => void
  setSpeed: (n: number) => void
  playGoalChange: () => void
  userChat: (text: string, lang: Lang) => void
  /** play the subject scenario (from the form, a chat example or the demo bar) */
  playSubject: (input?: SubjectDemoInput) => void
  /** subject scenario: re-render the report for the other preset goal */
  subjectGoal: (preset: PresetName) => void
  /** play the discovery scenario from the start */
  playDiscovery: () => void
}

type Dispatch = (a: Action) => void
type Txt = string | I18nText

interface Step {
  wait: number
  run: (d: Dispatch) => void
}

let seq = 0
const mid = (p: string) => `demo-${p}-${++seq}`
const T = (cs: string, en: string): { cs: string; en: string } => ({ cs, en })

const RUN_ID = 'demo-run-mock'
// the five finalists the owner picks for round 4 in the scripted chat (max 5 per backend)
const VETTED = ['mlsna_brnenka', 'snidane_s_tomasem', 'kvasek_a_kocarek', 'brno_na_taliri', 'brnenske_rano']

class Script {
  steps: Step[] = []
  constructor(private lang: () => Lang) {}
  pick(x: Txt): string {
    return typeof x === 'string' ? x : (x[this.lang()] ?? x.cs ?? x.en ?? '')
  }
  add(wait: number, run: (d: Dispatch) => void) {
    this.steps.push({ wait, run })
  }
  ev(wait: number, event: RunEvent | (() => RunEvent)) {
    this.add(wait, (d) => d({ type: 'event', event: typeof event === 'function' ? event() : event, at: Date.now() }))
  }
  log(wait: number, text: Txt, actor: string | null = 'mock', mode: LogLine['mode'] = 'mock') {
    this.add(wait, (d) => d({ type: 'event', event: { type: 'log', data: { text: this.pick(text), actor, mode } }, at: Date.now() }))
  }
  user(wait: number, text: Txt) {
    this.add(wait, (d) => {
      const id = mid('u')
      d({ type: 'chat.user', id, text: this.pick(text) })
      if (typeof text !== 'string') d({ type: 'chat.i18n', id, text })
    })
  }
  /** Stream an assistant message in small chunks, optionally with tool chips and extra chat events. */
  say(wait: number, text: Txt, extras: { tools?: { name: string; input?: unknown; result?: unknown }[]; after?: (() => ChatEvent)[] } = {}) {
    const id = mid('a')
    // the language is picked when the message starts; chunk steps are fixed in number (longest version)
    let words: string[] = []
    const all = typeof text === 'string' ? [text] : Object.values(text)
    const maxWords = Math.max(...all.map((x) => x.split(/(\s+)/).length))
    const chunks = Math.ceil(maxWords / 6)
    this.add(wait, (d) => {
      words = this.pick(text).split(/(\s+)/)
      d({ type: 'chat.assistantStart', id })
    })
    for (let i = 0; i < chunks; i++) {
      this.add(28, (d) => {
        const piece = words.slice(i * 6, i * 6 + 6).join('')
        if (piece) d({ type: 'chat.event', id, event: { type: 'chat.delta', data: { text: piece } } })
      })
    }
    for (const t of extras.tools ?? []) {
      this.add(120, (d) => d({ type: 'chat.event', id, event: { type: 'chat.tool', data: { name: t.name, input: t.input, status: 'running' } } }))
      this.add(260, (d) => d({ type: 'chat.event', id, event: { type: 'chat.tool', data: { name: t.name, input: t.input, result: t.result ?? { ok: true }, status: 'done' } } }))
    }
    for (const e of extras.after ?? []) this.add(60, (d) => d({ type: 'chat.event', id, event: e() }))
    this.add(40, (d) => {
      if (typeof text !== 'string') d({ type: 'chat.i18n', id, text })
      d({ type: 'chat.end', id })
    })
  }
}

// ---------------------------------------------------------------------------------------------
// Scenario 1, phase 1: bakery in Brno. 48 -> 22 -> 11 -> 6 -> 5
// ---------------------------------------------------------------------------------------------

function bakeryScript(lang: () => Lang): Script {
  const s = new Script(lang)
  const crit = CRITERIA_BAKERY

  s.say(
    300,
    T(
      'Dobrý den. Pomůžu vám najít tvůrce, kteří sedí k vaší firmě, a u každého ukážu, proč postupuje, nebo ne. Co prodáváte a kde?',
      'Hello. I will help you find creators who fit your business, and for each one I will show why they passed or not. What do you sell, and where?',
    ),
  )
  s.user(900, T('Mám pekárnu v Brně.', 'I run a bakery in Brno.'))
  s.say(500, T('Díky. Komu chcete prodávat a co má kampaň udělat?', 'Thanks. Who do you want to sell to, and what should the campaign do?'))
  s.user(900, T('Rodinám a mladým v Brně. Chci víc lidí v prodejně, uvádíme nový kváskový chléb.', 'Families and young people in Brno. I want more people in the shop; we are launching a new sourdough bread.'))
  s.say(500, T('Kolik zhruba můžete dát? A máte konkurenty, se kterými by tvůrce neměl spolupracovat?', 'Roughly what is your budget? And do you have competitors the creator should not be working with?'))
  s.user(
    1000,
    T(
      'Tak do 15 tisíc. Konkurence je Pekárna B (@pekarna_b). A chci jen věřící tvůrce, ať mají stejné hodnoty jako my. Publikum hlavně ženy 25–35.',
      'Up to about CZK 15,000. Our competitor is Pekárna B (@pekarna_b). And I only want religious creators who share our values. The audience should be mostly women aged 25–35.',
    ),
  )
  s.say(
    600,
    T(
      'Víru, „hodnoty“ ani věk a pohlaví publika posuzovat nebudu. Víra je citlivý údaj podle čl. 9 GDPR, hodnoty by znamenaly hodnotit člověka a demografii publika z veřejných dat zjistit nejde. Dám je mezi šedé štítky s vysvětlením.\n\nNavrhuji tato kritéria: lokální tvůrce o jídle, receptech, podnicích nebo rodině, 5 až 50 tisíc sledujících (menší tvůrci mívají bližší vztah s publikem a vejdou se do rozpočtu), aktivní za posledních 30 dní, píše česky, nejvýš 30 % reklamy a bez spolupráce s @pekarna_b. U každého štítku vpravo je důvod. Můžu spustit hledání?',
      'I will not judge religion, “values”, or the age and gender of the audience. Religion is special-category data under GDPR Art. 9, values would mean rating a person, and audience demographics cannot be read from public data. I have put them in the gray “not checked” chips with the reason.\n\nI propose these criteria: a local creator posting about food, recipes, cafés or family; 5k to 50k followers (smaller creators tend to be closer to their audience and fit the budget); active in the last 30 days; writes in Czech; at most 30 % ads; and no collaboration with @pekarna_b. Each chip on the right says why. Shall I start the search?',
    ),
    {
      tools: [{ name: 'propose_criteria', input: { business_type: 'bakery', city: 'Brno' } }],
      after: [() => ({ type: 'criteria.updated', data: { criteria: localized(crit, lang()) } })],
    },
  )
  s.user(1400, T('Ano, spusť to.', 'Yes, go ahead.'))
  s.say(400, T('Spouštím kola 0 až 3. Data jsou v ukázce smyšlená (MOCK), na nástěnce to uvidíte u každého zdroje.', 'Starting rounds 0 to 3. The data in this demo is fictional (MOCK); every source on the board says so.'), {
    tools: [{ name: 'run_rounds', input: { up_to: 3 }, result: { run_id: RUN_ID } }],
  })

  // ---- round 0
  s.ev(300, { type: 'run.started', data: { run_id: RUN_ID } })
  s.ev(100, { type: 'round.started', data: { round: 0 } })
  s.log(
    80,
    T('Hledání: #brnofood, #brnojidlo, „cukrárna brno“, „brno food“, místa Zelný trh a Náměstí Svobody', 'Search: #brnofood, #brnojidlo, “cukrárna brno”, “brno food”, places Zelný trh and Náměstí Svobody'),
    'mock:instagram-hashtag-scraper',
  )
  const ig = SEEDS.filter((x) => pfOf(x) === 'instagram').length
  const tt = SEEDS.length - ig
  for (const seed of SEEDS) {
    const c = candidateAt(seed, crit, 0)
    s.ev(45, { type: 'candidate.added', data: { candidate: c } })
  }
  s.log(80, T(`Instagram: ${ig} účtů`, `Instagram: ${ig} accounts`), 'mock:instagram-hashtag-scraper')
  s.log(60, T(`TikTok: ${tt} účtů`, `TikTok: ${tt} accounts`), 'mock:tiktok-search-scraper')
  s.log(60, T('Sloučeno podle (platforma, účet): 48 kandidátů, limit 60', 'Merged by (platform, handle): 48 candidates, limit 60'), 'engine', null)
  s.ev(120, { type: 'round.finished', data: { round: 0, entered: 48, remaining: 48 } })

  // ---- rounds 1-3
  const outcomes = new Map(SEEDS.map((x) => [idOf(x), evaluate(x, crit)]))
  const remainingAfter = (r: number) => SEEDS.filter((x) => (outcomes.get(idOf(x))!.elimination?.round ?? 99) > r).length

  const roundNotes: Record<number, { before: I18nText[]; chat: (out: number, entered: number) => I18nText }> = {
    1: {
      before: [
        T('Profily: 48 účtů v jedné dávce, posledních 12 postů', 'Profiles: 48 accounts in one batch, last 12 posts'),
        T('Nezletilí: 0 (vyřazení bez uložení dat)', 'Minors: 0 (dropped without storing any data)'),
      ],
      chat: (out, entered) =>
        T(
          `Kolo 1 hotovo: vstoupilo ${entered}, zůstalo ${entered - out}. Nejčastěji: 6 účtů je mimo rozsah 5–50 tisíc sledujících, 5 jsou firemní účty, 4 jsou soukromé a 4 píšou hlavně anglicky. Vyřazeného kandidáta můžete kliknutím vrátit, pokud pro něj kritérium neplatí.`,
          `Round 1 done: ${entered} entered, ${entered - out} left. Most often: 6 accounts are outside 5k–50k followers, 5 are business accounts, 4 are private and 4 write mostly in English. You can put an eliminated candidate back with one click if the criterion does not apply to them.`,
        ),
    },
    2: {
      before: [
        T('Témata: popisky 22 účtů do pevné taxonomie (LLM: náhradní režim, klíčová slova)', 'Topics: captions of 22 accounts into a fixed taxonomy (LLM: rule-based fallback, keywords)'),
        T('Komerční nasycenost: štítky, #reklama, slevové kódy', 'Commercial saturation: labels, #ad, discount codes'),
      ],
      chat: (out, entered) =>
        T(
          `Kolo 2: vstoupilo ${entered}, zůstalo ${entered - out}. Vypadli hlavně tvůrci o cestování, módě, hrách a sportu. Třeba @kolo_kolem_brna: jen 2 z 24 postů jsou o jídle.`,
          `Round 2: ${entered} entered, ${entered - out} left. Mostly creators about travel, fashion, gaming and sport dropped out. For example @kolo_kolem_brna: only 2 of 24 posts are about food.`,
        ),
    },
    3: {
      before: [
        T('Komentáře: posledních 5 postů u 11 účtů, 60 komentářů na účet', 'Comments: last 5 posts of 11 accounts, 60 comments per account'),
        T('Jména komentujících neukládáme, jen text pro jazyk a podíl emoji', 'Commenter names are not stored, only the text for language and the emoji share'),
      ],
      chat: (out, entered) =>
        T(
          `Kolo 3: vstoupilo ${entered}, zůstalo ${entered - out} finalistů. U publika ukazuju jen odhady z veřejných dat (interakce, jazyk komentářů, Brno), ne věk ani pohlaví.\n\nChcete finalisty prověřit do hloubky? Je to dražší krok (víc postů, spolupráce, zprávy, tvrzení vs. záznam) a najednou jde nejvýš 5. Které vybíráte?`,
          `Round 3: ${entered} entered, ${entered - out} finalists left. For the audience I only show estimates from public data (engagement, comment language, Brno), never age or gender.\n\nDo you want to vet the finalists in depth? It is a costlier step (more posts, collaborations, news, claims vs. record), at most 5 at a time. Which ones do you pick?`,
        ),
    },
  }

  let entered = 48
  for (const r of [1, 2, 3]) {
    s.ev(500, { type: 'round.started', data: { round: r } })
    for (const line of roundNotes[r].before) s.log(140, line, r === 3 ? 'mock:instagram-comment-scraper' : r === 1 ? 'mock:instagram-profile-scraper' : 'llm:fallback')
    const live = SEEDS.filter((x) => (outcomes.get(idOf(x))!.elimination?.round ?? 99) >= r)
    for (const seed of live) s.ev(18, { type: 'candidate.updated', data: { candidate: candidateAt(seed, crit, r) } })
    if (r === 1) {
      s.ev(120, { type: 'sensitive.filtered', data: { candidate_id: 'instagram:kvasek_a_kocarek', count: 2 } })
      s.ev(60, { type: 'sensitive.filtered', data: { candidate_id: 'instagram:mlsna_brnenka', count: 1 } })
      s.log(60, T('Citlivý filtr: vynechány 3 popisky (zdraví, politika). Uložen jen počet.', 'Sensitive filter: 3 captions left out (health, politics). Only the count is stored.'), 'llm:fallback')
    }
    if (r === 3) {
      s.ev(120, { type: 'sensitive.filtered', data: { candidate_id: 'instagram:snidane_s_tomasem', count: 1 } })
      s.log(60, T('Citlivý filtr: vynechán 1 komentář (politika). Uložen jen počet.', 'Sensitive filter: 1 comment left out (politics). Only the count is stored.'), 'llm:fallback')
    }
    const out = live.filter((x) => outcomes.get(idOf(x))!.elimination?.round === r)
    for (const seed of out) {
      const el = outcomes.get(idOf(seed))!.elimination!
      s.ev(r === 1 ? 110 : 220, { type: 'candidate.eliminated', data: { id: idOf(seed), elimination: el } })
      s.log(10, T(`Vyřazen @${seed.h}: ${el.reason.cs}`, `Eliminated @${seed.h}: ${el.reason.en}`), 'engine', 'mock')
    }
    if (r === 3) {
      // backend semantics: survivors of round 3 get status "finalist"
      for (const seed of live.filter((x) => !outcomes.get(idOf(x))!.elimination))
        s.ev(30, { type: 'candidate.updated', data: { candidate: { ...candidateAt(seed, crit, 3), status: 'finalist' } } })
    }
    const rem = remainingAfter(r)
    s.ev(200, { type: 'round.finished', data: { round: r, entered, remaining: rem } })
    s.say(300, roundNotes[r].chat(out.length, entered))
    entered = rem
  }

  // ---- round 4 (the owner picks at most 5; round 4 never eliminates, failures are shown)
  s.user(1600, T('Všechny kromě @pecu_s_babi, s ní už jsme mluvili.', 'All of them except @pecu_s_babi, we have already talked to her.'))
  const vetted = VETTED.map((h) => SEEDS.find((x) => x.h === h)!)
  s.say(
    300,
    T(
      'Spouštím hloubkovou prověrku 5 finalistů, které jste vybrali. Nikoho nevybírám ani nevyřazuji za vás: ukážu, co tvrdí, co ukazují jejich posty a co nevíme.',
      'Starting the deep vetting of the 5 finalists you picked. I do not pick or drop anyone for you: I will show what they claim, what their posts show, and what we do not know.',
    ),
    { tools: [{ name: 'start_deep_vetting', input: { candidate_ids: vetted.map(idOf) } }] },
  )
  s.ev(200, { type: 'round.started', data: { round: 4 } })
  s.log(80, T('Kolo 4: hloubková prověrka 5 finalistů', 'Round 4: deep vetting of 5 finalists'), 'engine', null)
  s.log(80, T('Prověrka: 48 posledních postů, TikTok/YouTube, Meta Branded Content, zprávy (cs, CZ)', 'Vetting: last 48 posts, TikTok/YouTube, Meta branded content, news (cs, CZ)'), 'mock:instagram-post-scraper')
  for (let i = 0; i < VETTING_STEPS.length; i++) {
    for (const f of vetted) s.add(70, (d) => d({ type: 'event', event: { type: 'vetting.progress', data: { candidate_id: idOf(f), step: s.pick(VETTING_STEPS[i]) } }, at: Date.now() }))
    if (i === 3) s.log(60, T('Zprávy: 5 dotazů, 3 články; 1 jmenovec (jiné město)', 'News: 5 queries, 3 articles; 1 namesake (different city)'), 'mock:google-news-scraper')
  }
  for (const f of vetted) {
    const id = idOf(f)
    const r4 = ROUND4[id]
    const base = candidateAt(f, crit, 3)
    const cand: Candidate = { ...base, results: [...base.results, ...r4.r4], report: r4.report, status: 'finalist' }
    s.ev(320, { type: 'candidate.updated', data: { candidate: cand } })
    s.ev(60, { type: 'report.ready', data: { candidate_id: id } })
    const failing = r4.r4.find((x) => x.status === 'fail')
    if (failing) {
      const v = typeof failing.value === 'string' ? T(failing.value, failing.value) : (failing.value as I18nText)
      s.log(
        10,
        T(
          `@${f.h} nesplňuje kritérium „bez spolupráce s konkurencí“: ${v.cs} (zůstává mezi finalisty, rozhoduje majitel)`,
          `@${f.h} does not meet “no competitor collaborations”: ${v.en} (stays a finalist; the owner decides)`,
        ),
        'engine',
      )
    }
  }
  s.ev(200, { type: 'round.finished', data: { round: 4, entered: vetted.length, remaining: vetted.length } })
  s.ev(80, { type: 'run.finished', data: {} })
  s.say(
    300,
    T(
      'Hotovo, 5 spisů je na nástěnce. Nikoho nevyřazuji ani nevybírám. Dvě věci stojí za pozornost:\n\n@mlsna_brnenka nesplňuje kritérium „bez spolupráce s konkurencí“: má 2 společné posty s @pekarna_b, přestože v bio uvádí exkluzivitu s @pekarna_a. To je nesoulad se záznamem, ne soud o člověku.\n\nU @snidane_s_tomasem je slevový kód bez označení u postu „recenze, nikdo mi neplatí“. Kód není důkaz platby, proto je to otázka na první schůzku.\n\nRozhodujete vy. Spis otevřete kliknutím na kartu, porovnání je pod trychtýřem.',
      'Done: 5 reports are on the board. I do not drop or pick anyone. Two things are worth a look:\n\n@mlsna_brnenka does not meet “no competitor collaborations”: 2 co-authored posts with @pekarna_b, although the bio claims exclusivity with @pekarna_a. That is a mismatch with the record, not a judgement of the person.\n\n@snidane_s_tomasem has a discount code with no ad label on a post that says “reviews, nobody pays me”. A code is not proof of payment, so it is a question for the first meeting.\n\nYou decide. Open a report by clicking a card; the comparison is below the funnel.',
    ),
  )
  return s
}

// ---------------------------------------------------------------------------------------------
// Scenario 1, phase 2: change goal to a fitness studio. Rounds 1-3 recomputed from the same data.
// ---------------------------------------------------------------------------------------------

function goalScript(lang: () => Lang): Script {
  const s = new Script(lang)
  s.user(200, T('Co kdybych místo pekárny měl fitness studio v Brně?', 'What if I had a fitness studio in Brno instead of the bakery?'))
  s.add(50, (d) => d({ type: 'goal.submitted', brief: lang() === 'en' ? BRIEF_FITNESS_EN : BRIEF_FITNESS }))
  s.say(
    300,
    T(
      'Přepočítám kola 1 až 3 ze stejných dat, bez nového stahování a bez LLM. Pro fitness studio navrhuji témata fitness, sport a lokální tipy, interakce aspoň 1 % a bez spolupráce se Studiem Kotva a Appkou Fitko. Kritérium „žádní tvůrci s nadváhou“ nekontroluju: tělo a zdraví jsou citlivé údaje.',
      'I will recompute rounds 1 to 3 from the same data, with no new fetching and no LLM. For a fitness studio I propose the topics fitness, sport and local tips, engagement of at least 1%, and no collaboration with Studio Kotva or Appka Fitko. I will not check “no overweight creators”: body and health are special-category data.',
    ),
    {
      tools: [{ name: 'change_goal', input: { business_type: 'fitness studio', city: 'Brno' } }],
      after: [() => ({ type: 'criteria.updated', data: { criteria: localized(CRITERIA_FITNESS, lang()) } })],
    },
  )
  s.log(200, T('Přepočet kol 1–3 z uložených dat a uložených témat: 0 stažení, 0 volání LLM, 0,4 s', 'Recomputed rounds 1–3 from stored data and stored topics: 0 fetches, 0 LLM calls, 0.4 s'), 'engine', 'mock')

  s.add(300, (d) => {
    const before = finalState(CRITERIA_BAKERY)
    const after = finalState(CRITERIA_FITNESS)
    const candidates: Record<string, Candidate> = {}
    for (const seed of SEEDS) {
      const id = idOf(seed)
      const c = after[id].cand
      const r4 = VETTED.includes(seed.h) ? ROUND4[id] : undefined
      candidates[id] = { ...c, status: c.status === 'active' ? 'finalist' : c.status, report: r4?.report ?? null }
    }
    const count = (st: typeof after, r: number) => Object.values(st).filter((x) => (x.elimination?.round ?? 99) > r).length
    d({
      type: 'snapshot',
      at: Date.now(),
      run: {
        id: RUN_ID,
        criteria: localized(CRITERIA_FITNESS, lang()),
        candidates,
        rounds: [
          { round: 0, entered: 48, remaining: 48 },
          { round: 1, entered: 48, remaining: count(after, 1) },
          { round: 2, entered: count(after, 1), remaining: count(after, 2) },
          { round: 3, entered: count(after, 2), remaining: count(after, 3) },
        ],
        log: [],
        mode_summary: { live: 0, cache: 0, mock: 48 },
        status: 'finished',
      },
    })
    const passedA = (id: string) => !before[id].elimination
    const passedB = (id: string) => !after[id].elimination
    // same shape as the backend DiffEntry: NEW elimination for dropped, PREVIOUS one for returned
    const dropped = SEEDS.filter((x) => passedA(idOf(x)) && !passedB(idOf(x))).map((x) => ({
      candidate_id: idOf(x),
      handle: x.h,
      platform: pfOf(x),
      before: 'finalist' as const,
      after: 'eliminated' as const,
      elimination: after[idOf(x)].elimination,
      needs_fetch: false,
    }))
    const returned = SEEDS.filter((x) => !passedA(idOf(x)) && passedB(idOf(x))).map((x) => ({
      candidate_id: idOf(x),
      handle: x.h,
      platform: pfOf(x),
      before: 'eliminated' as const,
      after: 'finalist' as const,
      elimination: before[idOf(x)].elimination,
      needs_fetch: false,
    }))
    d({ type: 'event', at: Date.now(), event: { type: 'diff', data: { dropped, returned } } })
  })
  s.say(
    400,
    T(
      'U fitness studia zůstalo po kole 3 pět kandidátů. Jeden je stejný jako u pekárny: @brnenske_rano. Pět tvůrců vypadlo jen u fitness (témata), čtyři účty vypadly jen u pekárny, třeba @rodinne_vylety_brno (u pekárny jsme chtěli interakce aspoň 1,5 %, u studia stačí 1 %). Rozdíl vidíte na nástěnce.',
      'For the fitness studio, five candidates are left after round 3. One is the same as for the bakery: @brnenske_rano. Five creators dropped out only for fitness (topics), and four only for the bakery, for example @rodinne_vylety_brno (the bakery needed at least 1.5% engagement, the studio is fine with 1%). The board shows the difference.',
    ),
  )
  return s
}

// ---------------------------------------------------------------------------------------------
// Scenario 2: one named creator (subject mode). Resolve, rounds 1-3 as checks, vetting, report.
// ---------------------------------------------------------------------------------------------

const GOAL_LABEL: Record<PresetName, { cs: string; en: string }> = { bakery: T('Pekárna v Brně', 'Bakery in Brno'), fitness: T('Fitness studio v Brně', 'Fitness studio in Brno') }

function subjectScript(lang: () => Lang, input: SubjectDemoInput, ctx: SubjectCtx): { script: Script; preset: PresetName } {
  const s = new Script(lang)
  const preset: PresetName = input.preset ?? 'bakery'
  // the anchor is the owner's: a different city or no anchor changes the verdict (prepared variants), it is
  // never silently replaced with the demo's own anchor
  const anchor = ctx.anchor
  s.add(0, (d) =>
    d({
      type: 'subject.start',
      runId: null,
      fromForm: true,
      subject: { raw: ctx.raw, handle: SUBJECT_HANDLE, platform: null, anchor, status: 'pending' },
    }),
  )
  const typed = (input.typed ?? '').replace(/^@/, '').toLowerCase()
  if (typed && typed !== SUBJECT_HANDLE) s.add(10, (d) => d({ type: 'chat.notice', id: mid('n'), text: translate(lang(), 'demo.subjectOnly', { h: SUBJECT_HANDLE }) }))
  const aCs = anchorText(anchor, 'cs') || 'bez kotvy'
  const aEn = anchorText(anchor, 'en') || 'no anchor'
  s.add(40, (d) =>
    d({
      type: 'chat.notice',
      id: mid('n'),
      text: '',
      // both languages: the language toggle during the demo re-renders the line
      notice: { kind: 'subject', handle: SUBJECT_HANDLE, anchor: { cs: aCs, en: aEn }, goal: GOAL_LABEL[preset] },
    }),
  )
  s.add(60, (d) => d({ type: 'criteria.local', criteria: subjectCriteria(preset, lang()) }))
  s.ev(200, { type: 'run.started', data: { run_id: SUBJECT_RUN_ID } })
  s.add(0, (d) => d({ type: 'run.id', id: SUBJECT_RUN_ID }))
  s.log(80, T(`Tvůrce: @${SUBJECT_HANDLE} · kotva: ${aCs} · cíl: ${GOAL_LABEL[preset].cs.toLowerCase()}`, `Subject: @${SUBJECT_HANDLE} · anchor: ${aEn} · goal: ${GOAL_LABEL[preset].en.toLowerCase()}`), 'engine', null)
  s.log(260, T('Instagram: hledám profil @kuba.jidlo.brno (1 požadavek)', 'Instagram: looking up the profile @kuba.jidlo.brno (1 request)'), 'mock:instagram-profile-scraper')
  s.ev(300, () => ({ type: 'candidate.added', data: { candidate: subjectCandidate(preset, lang(), 0) } }))
  s.ev(60, { type: 'subject.resolved', data: { candidate_id: SUBJECT_ID, platform: 'instagram', handle: SUBJECT_HANDLE } })
  s.log(40, T('Nalezeno: veřejný profil, 21 400 sledujících. Kontroly kol 1–3 nic nevyřazují.', 'Found: public profile, 21,400 followers. The round 1–3 checks eliminate nothing.'), 'engine', null)

  const notes: Record<number, I18nText[]> = {
    1: [T('Profil a posledních 12 postů: veřejný účet, čeština, velikost, aktivita', 'Profile and last 12 posts: public, Czech, size, activity')],
    2: [
      T('Témata 24 popisků (LLM: náhradní režim, klíčová slova)', 'Topics of 24 captions (LLM: rule-based fallback, keywords)'),
      T('Komerční nasycenost: štítky, #reklama, slevové kódy', 'Commercial saturation: labels, #ad, discount codes'),
    ],
    3: [T('Komentáře: posledních 5 postů, 60 komentářů; jména komentujících neukládáme', 'Comments: last 5 posts, 60 comments; commenter names are not stored')],
  }
  for (const r of [1, 2, 3]) {
    s.ev(450, { type: 'round.started', data: { round: r } })
    for (const n of notes[r]) s.log(160, n, r === 3 ? 'mock:instagram-comment-scraper' : r === 1 ? 'mock:instagram-profile-scraper' : 'llm:fallback')
    s.ev(320, () => ({ type: 'candidate.updated', data: { candidate: subjectCandidate(preset, lang(), r) } }))
    if (r === 1) {
      s.ev(80, { type: 'sensitive.filtered', data: { candidate_id: SUBJECT_ID, count: 1, total: 1 } })
      s.log(40, T('Citlivý filtr: vynechán 1 popisek (zdraví). Uložen jen počet.', 'Sensitive filter: 1 caption left out (health). Only the count is stored.'), 'llm:fallback')
    }
    s.ev(140, { type: 'round.finished', data: { round: r, entered: 1, remaining: 1 } })
  }

  s.ev(400, { type: 'round.started', data: { round: 4 } })
  s.log(80, T('Prověrka: 48 posledních postů, TikTok/YouTube, Meta Branded Content, zprávy (cs, CZ)', 'Vetting: last 48 posts, TikTok/YouTube, Meta branded content, news (cs, CZ)'), 'mock:instagram-post-scraper')
  const steps: I18nText[] = [
    T('víc postů (48)', 'more posts (48)'),
    T('účty na jiných platformách', 'accounts on other platforms'),
    T('identita a kotva', 'identity and anchor'),
    T('spolupráce a Meta Branded Content', 'collaborations and Meta branded content'),
    T('zprávy', 'news'),
    T('tvrzení vs. záznam', 'claims vs. record'),
    T('report pro cíl', 'report for the goal'),
  ]
  for (let i = 0; i < steps.length; i++) {
    s.add(380, (d) => d({ type: 'event', event: { type: 'vetting.progress', data: { candidate_id: SUBJECT_ID, step: s.pick(steps[i]) } }, at: Date.now() }))
    if (i === 1) s.log(60, T('TikTok: 2 podobné účty, YouTube: 1, Instagram: 1 fanouškovský', 'TikTok: 2 similar accounts, YouTube: 1, Instagram: 1 fan account'), 'mock:tiktok-profile-scraper')
    if (i === 2) {
      s.log(60, identityLog(ctx), 'engine', null)
      s.log(60, T('Odloženo: TikTok @kuba_jidlo (Bratislava, žádný odkaz), YouTube @kubajidlo (jen podobný název), Instagram @kuba.jidlo.brno.fans (fanouškovský účet)', 'Set aside: TikTok @kuba_jidlo (Bratislava, no link), YouTube @kubajidlo (similar name only), Instagram @kuba.jidlo.brno.fans (fan account)'), 'engine', null)
    }
    if (i === 4) s.log(60, T('Zprávy: 4 dotazy, 2 články; 1 jmenovec odložen (podnikatel ze Zlína)', 'News: 4 queries, 2 articles; 1 namesake set aside (a businessman from Zlín)'), 'mock:google-news-scraper')
  }
  s.add(300, (d) => {
    const report = subjectReport(preset, lang(), ctx)
    d({ type: 'event', event: { type: 'candidate.updated', data: { candidate: subjectCandidate(preset, lang(), 4, report) } }, at: Date.now() })
    d({ type: 'event', event: { type: 'report.ready', data: { candidate_id: SUBJECT_ID, report } }, at: Date.now() })
  })
  const open = subjectOpenChecks(preset)
  s.log(
    40,
    T(`Report: ${open} ${open === 1 ? 'kontrola nesplněná nebo neověřitelná' : open < 5 ? 'kontroly nesplněné nebo neověřitelné' : 'kontrol nesplněných nebo neověřitelných'}, nic vyřazeno, žádné skóre`, `Report: ${open} ${open === 1 ? 'check' : 'checks'} not met or not verifiable, nothing eliminated, no score`),
    'engine',
    null,
  )
  s.ev(100, { type: 'round.finished', data: { round: 4, entered: 1, remaining: 1 } })
  s.ev(60, { type: 'run.finished', data: {} })
  return { script: s, preset }
}

function subjectGoalScript(lang: () => Lang, from: PresetName, to: PresetName, ctx: SubjectCtx): Script {
  const s = new Script(lang)
  s.add(0, (d) => d({ type: 'recomputing', on: true }))
  s.log(
    120,
    T(
      `Cíl: ${GOAL_LABEL[from].cs.toLowerCase()} → ${GOAL_LABEL[to].cs.toLowerCase()}. Report se přepíše z uložených dat: 0 stažení, 0 požadavků na jazykový model.`,
      `Goal: ${GOAL_LABEL[from].en.toLowerCase()} → ${GOAL_LABEL[to].en.toLowerCase()}. The report is re-rendered from stored data: 0 fetches, 0 language model requests.`,
    ),
    'engine',
    'mock',
  )
  s.add(650, (d) => {
    const l = lang()
    const diff = subjectDiff(from, to, l, ctx)
    const report = { ...subjectReport(to, l, ctx), last_diff: diff }
    d({ type: 'criteria.local', criteria: subjectCriteria(to, l) })
    // backend order: report.diff, then the re-rendered report (the diff panel keeps the old report for texts)
    d({ type: 'event', event: { type: 'report.diff', data: { candidate_id: SUBJECT_ID, diff } }, at: Date.now() })
    d({ type: 'event', event: { type: 'candidate.updated', data: { candidate: subjectCandidate(to, l, 4, report) } }, at: Date.now() })
    d({ type: 'event', event: { type: 'report.ready', data: { candidate_id: SUBJECT_ID, report } }, at: Date.now() })
    d({ type: 'recomputing', on: false })
  })
  s.log(20, T('Report přeřazený a přepsaný za 0,2 s.', 'Report re-ordered and rewritten in 0.2 s.'), 'engine', 'mock')
  return s
}

// ---------------------------------------------------------------------------------------------
// MOCK LLM status for the header (&llm=openrouter|anthropic): the counter moves with the script
// ---------------------------------------------------------------------------------------------

function mockHealth(kind: 'openrouter' | 'anthropic', used: number): Health {
  const budget = kind === 'openrouter' ? 40 : null
  return {
    source_mode: 'mock',
    llm_mode: 'llm',
    apify_configured: false,
    llm_provider: kind,
    llm_model: kind === 'openrouter' ? 'anthropic/claude-sonnet-4.5' : 'claude-sonnet-4-5',
    llm_requests_used: used,
    llm_budget: budget,
    llm_budget_left: budget == null ? null : Math.max(0, budget - used),
    llm_budget_exhausted: budget != null && used >= budget,
    llm_tasks: ['chat', 'vetting', 'news'],
    llm_requests_by_task: { chat: Math.ceil(used / 2), vetting: Math.floor(used / 2) },
  }
}

// ---------------------------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------------------------

const SUBJECT_RX = /@([a-z0-9._]{2,30})|instagram\.com\/([a-z0-9._]+)|tiktok\.com\/@([a-z0-9._]+)/i
// docs/subject-mode.md 8.2: a handle is a subject request in the first message or next to a check verb
const CHECK_VERB = /\b(check|vet|research|look at|who is|prověř|zkontroluj|podívej se na|kdo je)/i
const SKIP_RX = /^(skip|přeskoč(it)?|preskoc(it)?|nevím|nevim|don'?t know|no idea|none|žádn[áý]|-)[.!]?$/i

/** An anchor named in the request itself ("based in Brno", a website, an IČO); undefined when there is none.
 *  "for my bakery in Brno" is the BUSINESS city, not the anchor (8.2). */
function anchorInRequest(text: string): Anchor | undefined {
  const site = /(?<![@\w.])((?:https?:\/\/)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24})(?:\/\S*)?/i.exec(text)
  if (site && !/(instagram|tiktok)\.com/i.test(site[1])) return readAnchor(site[1])?.anchor
  const ico = /(?:i[cč]o|company\s*id)\s*:?\s*(\d{6,8})\b/i.exec(text)
  if (ico) return { company_id: ico[1].padStart(8, '0') }
  const city = /\b(?:based in|lives in|living in|from|je z|žije v|působí v)\s+(\p{Lu}[\p{L}-]+(?:[ -]\p{Lu}[\p{L}-]+)?)/u.exec(text)
  if (city) return { city: city[1] }
  return undefined
}

/** The answer to the anchor question: "Brno", "based in Brno", "kubajidlo.mock.invalid", "IČO 12345678", "skip". */
function anchorFromAnswer(text: string): Anchor | null {
  const t = text.trim()
  if (SKIP_RX.test(t)) return null
  const stripped = t
    .replace(/^(?:(?:the creator|they|he|she)(?:'s| is| are)?\s+)?(?:based\s+in|lives\s+in|living\s+in|from|in|je\s+z|žije\s+v|působí\s+v|z|ve?|city\s*:?|town\s*:?)\s+/i, '')
    .replace(/[.!]+$/, '')
    .trim()
  const a = readAnchor(stripped)
  if (!a) return null
  if (a.kind === 'city') return { city: stripped.charAt(0).toUpperCase() + stripped.slice(1) }
  return a.anchor
}

export function createDemoReplay(
  dispatch: Dispatch,
  opts: {
    speed?: number
    instant?: boolean
    full?: boolean
    scenario?: DemoScenario
    llm?: 'openrouter' | 'anthropic' | null
    getLang?: () => Lang
    onStatus?: (s: DemoStatus) => void
  },
): DemoController {
  const lang = opts.getLang ?? (() => 'en' as Lang)
  let scenario: DemoScenario = opts.scenario ?? 'discovery'
  let phase: DemoStatus['phase'] = scenario === 'subject' ? 'subject' : scenario === 'empty' ? 'idle' : 'bakery'
  let steps: Step[] = scenario === 'discovery' ? bakeryScript(lang).steps : []
  let i = 0
  let timer: number | null = null
  let playing = false
  let started = false
  let speed = opts.speed && opts.speed > 0 ? opts.speed : 1
  let bakeryDone = false
  let goalDone = false
  let subjectDone = false
  let subjectPreset: PresetName = 'bakery'
  let ctx: SubjectCtx = subjectCtx({ llm: !!opts.llm })
  // a subject request in the chat waits for the answer to the anchor question
  let pending: { typed: string; raw: string; preset: PresetName } | null = null
  let userTurns = 0
  const autoGoal = !!opts.full
  let llmUsed = 0

  // subject scenario: the report is 80 % of the story, the goal switch the rest (it is not "done" before it)
  const progress = () => {
    if (phase === 'idle') return 0
    const p = steps.length ? i / steps.length : 1
    if (phase === 'subject') return 0.8 * p
    if (phase === 'subjectGoal') return 0.8 + 0.2 * p
    return p
  }

  const status = () =>
    opts.onStatus?.({
      scenario,
      phase,
      playing,
      progress: progress(),
      speed,
      bakeryDone,
      goalDone,
      subjectDone,
      subjectGoal: subjectPreset,
    })

  // the MOCK LLM counter: a few requests per chat turn and per vetting, none for a goal switch
  const bumpLlm = (n: number) => {
    if (!opts.llm) return
    llmUsed += n
    dispatch({ type: 'health', health: mockHealth(opts.llm, llmUsed) })
  }

  const clear = () => {
    if (timer != null) window.clearTimeout(timer)
    timer = null
  }

  const finishPhase = () => {
    if (phase === 'bakery') {
      bakeryDone = true
      bumpLlm(9)
      if (autoGoal) {
        startGoal(opts.instant ? 0 : 2500)
        return
      }
    } else if (phase === 'goal') goalDone = true
    else if (phase === 'subject') {
      subjectDone = true
      bumpLlm(5)
      if (autoGoal) {
        playing = false
        status()
        if (opts.instant) ctl.subjectGoal('fitness')
        else timer = window.setTimeout(() => ctl.subjectGoal('fitness'), 2500 / speed)
        return
      }
    } else if (phase === 'subjectGoal') subjectDone = true
    playing = false
    status()
  }

  const tick = () => {
    timer = null
    if (!playing) return
    if (i >= steps.length) return finishPhase()
    steps[i].run(dispatch)
    i++
    if (i >= steps.length) return finishPhase()
    timer = window.setTimeout(tick, steps[i].wait / speed)
    if (i % 4 === 0) status()
  }

  const runAllNow = () => {
    while (i < steps.length) steps[i++].run(dispatch)
  }

  /** Load a script and play it (or apply it at once with &instant=1). */
  const play = (next: Step[], nextPhase: DemoStatus['phase'], delay: number) => {
    clear()
    steps = next
    i = 0
    phase = nextPhase
    playing = true
    status()
    if (opts.instant) {
      runAllNow()
      finishPhase()
      return
    }
    timer = window.setTimeout(tick, delay / speed)
  }

  function startGoal(delay: number) {
    if (phase === 'goal') return
    play(goalScript(lang).steps, 'goal', delay)
  }

  const resetBoard = () => {
    dispatch({ type: 'reset' })
    dispatch({ type: 'run.id', id: null })
    if (opts.llm) dispatch({ type: 'health', health: mockHealth(opts.llm, llmUsed) })
  }

  const ctl: DemoController = {
    start() {
      if (started) {
        if (playing && timer == null && i < steps.length) timer = window.setTimeout(tick, 50)
        return
      }
      started = true
      dispatch({ type: 'run.id', id: null })
      if (opts.llm) dispatch({ type: 'health', health: mockHealth(opts.llm, llmUsed) })
      if (scenario === 'empty') {
        status()
        return
      }
      if (scenario === 'subject') {
        ctl.playSubject({})
        return
      }
      play(steps, 'bakery', 400)
    },
    stop() {
      clear()
    },
    pause() {
      playing = false
      clear()
      status()
    },
    resume() {
      if (playing || phase === 'idle') return
      if (i >= steps.length) {
        if (phase === 'bakery' && !bakeryDone) finishPhase()
        return
      }
      playing = true
      status()
      timer = window.setTimeout(tick, 50)
    },
    restart() {
      clear()
      pending = null
      bakeryDone = false
      goalDone = false
      subjectDone = false
      if (scenario === 'subject') {
        resetBoard()
        ctl.playSubject({ preset: 'bakery' })
        return
      }
      resetBoard()
      play(bakeryScript(lang).steps, 'bakery', 300)
    },
    setSpeed(n: number) {
      speed = n
      status()
    },
    playGoalChange() {
      if (scenario !== 'discovery' || phase === 'goal') return
      // fast-forward the rest of the bakery run, then play the goal change
      clear()
      runAllNow()
      bakeryDone = true
      startGoal(300)
    },
    playDiscovery() {
      clear()
      scenario = 'discovery'
      bakeryDone = false
      goalDone = false
      subjectDone = false
      resetBoard()
      play(bakeryScript(lang).steps, 'bakery', 300)
    },
    playSubject(input: SubjectDemoInput = {}) {
      clear()
      pending = null
      scenario = 'subject'
      subjectDone = false
      bakeryDone = false
      goalDone = false
      const preset: PresetName = input.preset ?? 'bakery'
      const typed = (input.typed ?? SUBJECT_HANDLE).replace(/^@/, '')
      ctx = subjectCtx({
        anchor: input.anchor === undefined ? SUBJECT_ANCHOR : input.anchor,
        raw: input.raw ?? `@${typed}`,
        firstGoal: preset,
        llm: !!opts.llm,
      })
      const { script } = subjectScript(lang, input, ctx)
      subjectPreset = preset
      play(script.steps, 'subject', 200)
    },
    subjectGoal(preset: PresetName) {
      if (scenario !== 'subject') return
      if (phase === 'subject' && !subjectDone) {
        // fast-forward the rest of the check first
        clear()
        runAllNow()
        subjectDone = true
      }
      if (phase === 'subjectGoal' && playing) {
        clear()
        runAllNow()
      }
      if (preset === subjectPreset) return
      const from = subjectPreset
      subjectPreset = preset
      play(subjectGoalScript(lang, from, preset, ctx).steps, 'subjectGoal', 50)
    },
    userChat(text: string, l: Lang) {
      const first = userTurns++ === 0
      const m = SUBJECT_RX.exec(text)
      // a subject request in the demo chat ("Check @x for my bakery in Brno"): one anchor question, then the run
      if (m && (first || CHECK_VERB.test(text) || pending)) {
        dispatch({ type: 'chat.user', id: mid('u'), text })
        const typed = (m[1] ?? m[2] ?? m[3]).toLowerCase()
        const raw = m[0].startsWith('@') ? `@${typed}` : m[0]
        const preset: PresetName = /fit|gym|studio|cvi/i.test(text) ? 'fitness' : 'bakery'
        const anchor = anchorInRequest(text)
        if (anchor) {
          ctl.playSubject({ typed, raw, preset, anchor })
          return
        }
        // the business city ("my bakery in Brno") is not the anchor: ask where the CREATOR is (8.2)
        clear()
        playing = false
        status()
        pending = { typed, raw, preset }
        const q = {
          cs: `Abych prověřil správného @${typed}, a ne jmenovce nebo podobný účet: kde tvůrce působí (město), nebo jaký má web či IČO? Můžete také napsat „přeskočit“.`,
          en: `To check the right @${typed} and not a namesake or look-alike account: where is the creator based (city), or what is their website or company ID (IČO)? You can also say “skip”.`,
        }
        const id = mid('a')
        dispatch({ type: 'chat.assistantStart', id })
        dispatch({ type: 'chat.event', id, event: { type: 'chat.delta', data: { text: q[l] } } })
        dispatch({ type: 'chat.i18n', id, text: q })
        dispatch({ type: 'chat.end', id })
        return
      }
      if (pending) {
        const p = pending
        dispatch({ type: 'chat.user', id: mid('u'), text })
        // "skip" gives no anchor: the verdict is "likely" at best
        ctl.playSubject({ ...p, anchor: anchorFromAnswer(text) })
        return
      }
      if (scenario === 'subject' && subjectDone && /fit|gym|studio/i.test(text)) {
        dispatch({ type: 'chat.user', id: mid('u'), text })
        ctl.subjectGoal('fitness')
        return
      }
      if (scenario === 'subject' && subjectDone && /pek|bake|bread|chleb/i.test(text)) {
        dispatch({ type: 'chat.user', id: mid('u'), text })
        ctl.subjectGoal('bakery')
        return
      }
      // the discovery examples on the empty screen start the discovery scenario
      if (phase === 'idle' && /pek|bake|fitness|studio/i.test(text)) {
        ctl.playDiscovery()
        return
      }
      dispatch({ type: 'chat.user', id: mid('u'), text })
      const id = mid('a')
      dispatch({ type: 'chat.assistantStart', id })
      dispatch({ type: 'chat.event', id, event: { type: 'chat.delta', data: { text: translate(l, 'demo.chatReply') } } })
      dispatch({ type: 'chat.i18n', id, text: { cs: translate('cs', 'demo.chatReply'), en: translate('en', 'demo.chatReply') } })
      dispatch({ type: 'chat.end', id })
    },
  }
  return ctl
}

export const DEMO_RUN_ID = RUN_ID
