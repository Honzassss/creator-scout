// App context: reducer state + actions that talk to the backend (or to the demo replay when ?demo=1).

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react'
import { api, extractDiff, extractReportDiffs, streamChat } from './lib/api'
import { reducer, initialState, findRunId, reportDiffChanged, subjectCandidate, type Action, type AppState } from './state'
import { translate, type I18nKey } from './i18n'
import type { Anchor, Brief, ChatEvent, Competitor, CriteriaSet, Lang, RunEvent } from './types'
import { createDemoReplay, type DemoController, type DemoStatus } from './dev/demoReplay'
import { PRESETS, type PresetName } from './lib/presets'
import { anchorText, parseSubject } from './lib/subject'

const RUN_EVENTS: RunEvent['type'][] = [
  'run.started',
  'log',
  'round.started',
  'candidate.added',
  'candidate.updated',
  'candidate.eliminated',
  'candidate.removed',
  'round.finished',
  'sensitive.filtered',
  'vetting.progress',
  'report.ready',
  'diff',
  'run.finished',
  'error',
  'subject.resolved',
  'subject.not_found',
  'report.diff',
]

let seq = 0
const uid = (p: string) => `${p}${Date.now().toString(36)}${(++seq).toString(36)}`

export type Theme = 'light' | 'dark' | 'system'
const THEME_COLOR = { light: '#f2ece0', dark: '#12141a' }

function readPref<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null
    return v && allowed.includes(v) ? v : fallback
  } catch {
    return fallback
  }
}
function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage may be blocked; preference is a convenience only */
  }
}

/** What the "Already have a creator in mind?" form sends. */
export interface SubjectInput {
  subject: string
  anchor: Anchor | null
  preset: PresetName
  /** the owner's own competitors; empty or missing = the preset's sample competitors */
  competitors?: Competitor[]
}

export interface Actions {
  /** resolves false when the guide did not answer (the composer then gets the text back) */
  sendChat: (text: string) => Promise<boolean> | void
  /** POST /api/subject: one named creator, one anchor, a preset goal */
  researchSubject: (input: SubjectInput) => Promise<void>
  /** subject mode: one-click switch between the two preset goals (no fetch, no LLM) */
  switchGoal: (preset: PresetName) => void
  startRun: () => void
  vet: (ids: string[]) => void
  saveCriteria: (c: CriteriaSet) => void
  restore: (candidateId: string, criterionId: string) => void
  changeGoal: (brief: Brief) => void
  purge: () => void
}

interface Ctx {
  state: AppState
  dispatch: React.Dispatch<Action>
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: I18nKey, vars?: Record<string, string | number>) => string
  theme: Theme
  setTheme: (t: Theme) => void
  blur: boolean
  setBlur: (b: boolean) => void
  openId: string | null
  openCandidate: (id: string | null) => void
  /** narrow screens show either the guide or the results */
  view: 'chat' | 'board'
  setView: (v: 'chat' | 'board') => void
  /** reveal a panel on the right (switches to results on narrow screens, scrolls, moves focus to focusId or the panel's heading) */
  reveal: (targetId: string, focusId?: string) => void
  /** desktop: the guide column is collapsed to a rail */
  chatCollapsed: boolean
  setChatCollapsed: (v: boolean) => void
  goalOpen: boolean
  setGoalOpen: (b: boolean) => void
  /** text waiting in the chat composer (e.g. "Check @x (based in Brno) for my ") */
  chatDraft: { text: string; n: number } | null
  composeChat: (text: string) => void
  actions: Actions
  demo: DemoController | null
  demoStatus: DemoStatus | null
}

const AppCtx = createContext<Ctx | null>(null)

export function useApp(): Ctx {
  const c = useContext(AppCtx)
  if (!c) throw new Error('useApp outside provider')
  return c
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem('cs.chatCollapsed') === '1'
  } catch {
    return false
  }
}

function urlParams() {
  return new URLSearchParams(window.location.search)
}

function setParam(name: string, value: string | null) {
  try {
    const u = new URL(window.location.href)
    if (value) u.searchParams.set(name, value)
    else u.searchParams.delete(name)
    if (u.toString() !== window.location.href) window.history.replaceState(null, '', u.toString())
  } catch {
    /* ignore */
  }
}
const setRunParam = (id: string | null) => setParam('run', id)

/** A chat session id made here: a reloaded page or a second tab never continues another tab's session
 *  (the backend otherwise falls back to the most recently used session). */
const newChatId = () => {
  const b = new Uint8Array(6)
  try {
    crypto.getRandomValues(b)
  } catch {
    for (let i = 0; i < b.length; i++) b[i] = Math.floor(Math.random() * 256)
  }
  return `c_${Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')}`
}

/** "Yes, start." / "ano, spusť": the owner confirms the guide's question to start the rounds. */
const AFFIRMATIVE = /^\s*(yes|yep|yeah|ok|okay|sure|go|go ahead|start|run|do it|let'?s go|ano|jo|jj|jasně|jasne|spusť|spust|spusťte|spustit|dobře|dobre|souhlas[íi]m|můžeš|muzes)\b/i
const criteriaSig = (c: CriteriaSet | null | undefined) =>
  JSON.stringify((c?.criteria ?? []).map((x) => [x.id, x.enabled, x.params]))

export function AppProvider({ children }: { children: ReactNode }) {
  const params = useMemo(urlParams, [])
  const isDemo = params.get('demo') === '1'
  const [state, dispatch] = useReducer(reducer, isDemo, initialState)
  // English by default (the jury reads English); ?lang=cs|en wins over a saved preference
  const [lang, setLangState] = useState<Lang>(() => {
    const q = params.get('lang')
    return q === 'cs' || q === 'en' ? q : readPref<Lang>('cs.lang', 'en', ['cs', 'en'])
  })
  const [theme, setThemeState] = useState<Theme>(() => readPref<Theme>('cs.theme', 'system', ['light', 'dark', 'system']))
  const [blur, setBlur] = useState(false)
  // ?c=<candidateId> keeps the open dossier in the URL (reload reopens it)
  const [openId, setOpenId] = useState<string | null>(() => params.get('c'))
  // a ?run= link (reload, shared link) opens on the results: on a phone the report is otherwise hidden behind a tab
  const [view, setView] = useState<'chat' | 'board'>(() => (params.get('run') && params.get('demo') !== '1' ? 'board' : 'chat'))
  const [goalOpen, setGoalOpen] = useState(false)
  const [demoStatus, setDemoStatus] = useState<DemoStatus | null>(null)
  const [chatDraft, setChatDraft] = useState<{ text: string; n: number } | null>(null)
  const [chatCollapsed, setChatCollapsedState] = useState(readCollapsed)
  const setChatCollapsed = useCallback((v: boolean) => {
    setChatCollapsedState(v)
    writePref('cs.chatCollapsed', v ? '1' : '0')
  }, [])
  const composeChat = useCallback(
    (text: string) => {
      // a collapsed guide has no composer: open it first, the draft effect then focuses the textarea
      setChatCollapsed(false)
      setView('chat')
      setChatDraft((d) => ({ text, n: (d?.n ?? 0) + 1 }))
    },
    [setChatCollapsed],
  )
  const stateRef = useRef(state)
  stateRef.current = state
  const langRef = useRef(lang)
  langRef.current = lang

  const t = useCallback((key: I18nKey, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang])
  const tRef = useRef(t)
  tRef.current = t

  // the owner picked a language in the menu: the guide's language no longer switches the UI
  const langChosen = useRef(false)
  const setLang = useCallback((l: Lang) => {
    langChosen.current = true
    setLangState(l)
    writePref('cs.lang', l)
    // a ?lang= left in the URL would undo this choice on reload
    setParam('lang', null)
  }, [])
  const setTheme = useCallback((th: Theme) => {
    setThemeState(th)
    writePref('cs.theme', th)
  }, [])

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    // browser chrome follows the chosen theme too, not only the OS setting
    for (const m of Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'))) {
      const darkMeta = (m.getAttribute('media') ?? '').includes('dark')
      const dark = theme === 'system' ? darkMeta : theme === 'dark'
      m.setAttribute('content', dark ? THEME_COLOR.dark : THEME_COLOR.light)
    }
  }, [theme])

  // ---------- demo replay ----------
  const demoRef = useRef<DemoController | null>(null)
  if (isDemo && !demoRef.current) {
    const sc = params.get('scenario')
    demoRef.current = createDemoReplay(dispatch, {
      speed: Number(params.get('speed')) || 1,
      instant: params.get('instant') === '1',
      full: params.get('full') === '1',
      // ?demo=1 opens on the jury's flow (one creator, one anchor, one goal); discovery is &scenario=discovery
      scenario: sc === 'discovery' ? 'discovery' : sc === 'empty' ? 'empty' : 'subject',
      llm: params.get('llm') === 'openrouter' || params.get('llm') === 'anthropic' ? (params.get('llm') as 'openrouter' | 'anthropic') : null,
      getLang: () => langRef.current,
      onStatus: setDemoStatus,
    })
  }
  useEffect(() => {
    const d = demoRef.current
    if (!d) return
    d.start()
    return () => d.stop()
  }, [])

  // ---------- health (also carries the LLM provider, model and request budget) ----------
  const healthTimer = useRef<number | null>(null)
  const refreshHealth = useCallback(
    (delay = 400) => {
      if (isDemo) return
      if (healthTimer.current) window.clearTimeout(healthTimer.current)
      healthTimer.current = window.setTimeout(() => {
        api
          .health()
          .then((h) => dispatch({ type: 'health', health: h }))
          .catch(() => dispatch({ type: 'health', health: null }))
      }, delay)
    },
    [isDemo],
  )
  useEffect(() => {
    if (isDemo) return
    refreshHealth(0)
    const iv = window.setInterval(() => refreshHealth(0), 20000)
    return () => window.clearInterval(iv)
  }, [isDemo, refreshHealth])

  // ---------- initial run from URL ----------
  useEffect(() => {
    if (isDemo) return
    const id = params.get('run')
    if (!id) return
    dispatch({ type: 'run.id', id })
  }, [isDemo, params])

  // the conversation lives only in the tab that had it: say so beside the loaded run, but only once the
  // run has actually loaded (an unreachable backend must not get a "run loaded" line)
  const linkRunId = isDemo ? null : params.get('run')
  const restoredSig = linkRunId && state.runId === linkRunId && state.criteria ? 'restored' : ''
  useEffect(() => {
    if (!restoredSig || !linkRunId || announced.current.has('restored')) return
    announced.current.add('restored')
    // the server keeps the conversation bound to the run: show it and continue the same chat session
    api
      .runChat(linkRunId)
      .then((r) => {
        if (stateRef.current.runId !== linkRunId) return
        const messages = (r.messages ?? []).filter((m) => (m.role === 'user' || m.role === 'assistant') && m.text)
        if (messages.length) dispatch({ type: 'chat.restore', chatId: r.chat_id, lang: r.lang ?? null, messages })
        else dispatch({ type: 'chat.notice', id: uid('n'), text: tRef.current('chat.restored') })
      })
      .catch(() => dispatch({ type: 'chat.notice', id: uid('n'), text: tRef.current('chat.restored') }))
  }, [restoredSig, linkRunId])

  useEffect(() => {
    if (!isDemo) setRunParam(state.runId)
  }, [state.runId, isDemo])

  useEffect(() => {
    setParam('c', openId)
  }, [openId])

  // ---------- the guide speaks after vetting and after a goal change (P0-10) ----------
  const announced = useRef<Set<string>>(new Set())
  // A vetting finishes when the vetting map empties, or when round 4 appears (fast mock runs).
  // A goal change that only shrinks the set of vetted finalists is not a new vetting.
  const vettingN = Object.keys(state.vetting).length
  const hasRound4 = state.rounds.some((r) => r.round === 4)
  const prevVet = useRef({ n: vettingN, r4: hasRound4 })
  useEffect(() => {
    const prev = prevVet.current
    prevVet.current = { n: vettingN, r4: hasRound4 }
    const finished = vettingN === 0 && hasRound4 && (prev.n > 0 || !prev.r4)
    // a reloaded page replays an old vetting: only a vetting started from this page is news
    if (!finished || (!localChange.current && !isDemo)) return
    const s = stateRef.current
    // a subject run has its own notice (the report is ready); the funnel summary does not apply
    if (s.mode === 'subject') return
    const crit = new Map((s.criteria?.criteria ?? []).map((c) => [c.id, c]))
    const vettedIds = s.order.filter((id) => s.candidates[id]?.report && s.candidates[id]?.status !== 'eliminated')
    if (!vettedIds.length) return
    const sig = `vet:${s.runId ?? 'demo'}:${vettedIds.join('|')}:${s.criteria?.brief?.business_type ?? ''}`
    if (announced.current.has(sig)) return
    announced.current.add(sig)
    const fails: { id: string; handle: string; criteria: string[] }[] = []
    for (const id of vettedIds) {
      const c = s.candidates[id]
      const failed = c.results.filter((r) => crit.get(r.criterion_id)?.round === 4 && r.status === 'fail' && !r.waived).map((r) => r.criterion_id)
      if (failed.length) fails.push({ id, handle: c.profile?.handle ?? c.ref.handle, criteria: failed })
    }
    dispatch({ type: 'chat.notice', id: uid('n'), text: '', notice: { kind: 'vet', vetted: vettedIds.length, fails } })
  }, [vettingN, hasRound4])

  // subject runs: the report diff is the news, not the (empty) funnel diff
  const goalSig = state.mode !== 'subject' && state.diff && state.diff.kind === 'goal' && !state.diff.pendingFetch ? `goal:${state.diff.at}` : ''
  useEffect(() => {
    if (!goalSig || announced.current.has(goalSig)) return
    announced.current.add(goalSig)
    const d = stateRef.current.diff
    if (!d) return
    dispatch({
      type: 'chat.notice',
      id: uid('n'),
      text: '',
      notice: {
        kind: 'goal',
        from: d.goalA?.business_type ?? '–',
        to: d.goalB?.business_type ?? '–',
        dropped: d.dropped.length,
        returned: d.returned.length,
      },
    })
    // the change may have been made with the board scrolled down (e.g. at the comparison): bring the
    // diff and the funnel header into view, without switching the phone view or moving focus
    window.setTimeout(() => {
      const board = document.getElementById('board')
      const diff = document.getElementById('diff')
      if (!board || !diff || !board.getClientRects().length) return
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      board.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' })
      diff.classList.remove('flash-ring')
      void diff.offsetWidth
      diff.classList.add('flash-ring')
    }, 60)
  }, [goalSig])

  // report diffs after a goal / criteria change: a subject run gets one line with a link to its panel; a
  // discovery run gets ONE line for the whole batch (the stream and the HTTP response each carry one
  // report.diff per vetted finalist) that names each creator whose report changed
  const rdLatest = useMemo(() => Object.values(state.reportDiffs).reduce((m, r) => Math.max(m, r.at), 0), [state.reportDiffs])
  const rdAnnounced = useRef(0)
  useEffect(() => {
    if (!rdLatest || rdLatest <= rdAnnounced.current) return
    const timer = window.setTimeout(() => {
      const s = stateRef.current
      const fresh = Object.values(s.reportDiffs).filter((r) => r.at > rdAnnounced.current)
      if (!fresh.length) return
      rdAnnounced.current = Math.max(rdAnnounced.current, ...fresh.map((r) => r.at))
      if (s.mode === 'subject') {
        const rd = s.reportDiff ?? fresh[fresh.length - 1]
        dispatch({ type: 'chat.notice', id: uid('n'), text: '', notice: { kind: 'reportDiff', candidateId: rd.candidateId, diff: rd.diff } })
        return
      }
      const items = fresh
        .filter((r) => reportDiffChanged(r.diff))
        .map((r) => {
          const c = s.candidates[r.candidateId]
          return { candidateId: r.candidateId, handle: c?.profile?.handle ?? c?.ref.handle ?? r.candidateId, summary: r.diff.summary }
        })
      if (items.length) dispatch({ type: 'chat.notice', id: uid('n'), text: '', notice: { kind: 'reportDiffs', items } })
    }, 500)
    return () => window.clearTimeout(timer)
  }, [rdLatest])

  // a subject check started from the form: say in the chat when its report is ready
  const subj = subjectCandidate(state)
  const readySig = state.subjectFromForm && subj?.report && state.runStatus === 'finished' ? `ready:${state.runId ?? 'demo'}:${subj.id}` : ''
  useEffect(() => {
    if (!readySig || announced.current.has(readySig)) return
    announced.current.add(readySig)
    const c = subjectCandidate(stateRef.current)
    if (c) dispatch({ type: 'chat.notice', id: uid('n'), text: '', notice: { kind: 'subjectReady', candidateId: c.id } })
  }, [readySig])

  // a subject check from the form found no profile: the guide says so, what was tried and what to send instead
  const nfSig = state.subjectFromForm && state.subject?.status === 'not_found' ? `nf:${state.runId ?? 'demo'}` : ''
  useEffect(() => {
    if (!nfSig || announced.current.has(nfSig)) return
    announced.current.add(nfSig)
    const s = stateRef.current
    dispatch({
      type: 'chat.notice',
      id: uid('n'),
      text: '',
      notice: {
        kind: 'subjectNotFound',
        handle: s.subject?.handle ?? s.subjectNotFound?.subject?.replace(/^@/, '') ?? '',
        tried: s.subjectNotFound?.tried ?? [],
        reason: s.subjectNotFound?.reason,
        offline: ['mock', 'cache'].includes((s.health?.source_mode ?? '').toLowerCase()),
      },
    })
  }, [nfSig])

  // a discovery run cut off by a server stop: one line in the chat (a subject run shows it on its board)
  const intSig = state.interrupted && state.mode !== 'subject' ? `int:${state.runId}` : ''
  useEffect(() => {
    if (!intSig || announced.current.has(intSig)) return
    announced.current.add(intSig)
    dispatch({ type: 'chat.notice', id: uid('n'), text: '', notice: { kind: 'interrupted' } })
  }, [intSig])

  // ---------- snapshot + event stream for the active run ----------
  const snapshotTimer = useRef<number | null>(null)
  // The run stream replays its whole history on connect. A 'diff' in that history belongs to a change
  // made before this page was loaded: the board already shows its result (snapshot), and a
  // "Po úpravě kritérií" panel popping in seconds after a reload, without any action, is wrong.
  // Diffs are shown only once this page has changed something itself (chat, criteria, goal, restore).
  // The same holds for a subject report's report.diff (its panel and chat line).
  const localChange = useRef(false)
  const acceptDiff = () => localChange.current || !!stateRef.current.pendingGoal || stateRef.current.recomputing
  const refreshSnapshot = useCallback((id: string, delay = 0) => {
    if (snapshotTimer.current) window.clearTimeout(snapshotTimer.current)
    snapshotTimer.current = window.setTimeout(() => {
      api
        .run(id)
        .then((run) => dispatch({ type: 'snapshot', run, at: Date.now() }))
        .catch((e: Error) => {
          if (stateRef.current.runId !== id) return
          // an old link to a deleted run: say so once, drop ?run= ("try again" cannot help)
          if (/^404\b/.test(e.message)) {
            dispatch({ type: 'reset', keepChat: true })
            setRunParam(null)
            dispatch({ type: 'error', message: tRef.current('error.runGone') })
            return
          }
          dispatch({ type: 'error', message: tRef.current('error.generic', { msg: e.message }) })
        })
    }, delay)
  }, [])

  // A subject run whose server stopped mid-check has no task and no report: nothing will ever finish it.
  const checkInterrupted = useCallback((id: string) => {
    api
      .status(id)
      .then((st) => {
        if (st.busy) return
        const s = stateRef.current
        if (s.runId !== id) return
        if (st.interrupted) {
          dispatch({ type: 'run.interrupted', runId: id })
          return
        }
        if (s.mode !== 'subject' || s.subject?.status === 'not_found') return
        return api.run(id).then((run) => {
          if (stateRef.current.runId !== id) return
          dispatch({ type: 'snapshot', run, at: Date.now() })
          const hasReport = Object.values(run.candidates ?? {}).some((c) => c.report)
          if (!hasReport && run.subject?.status !== 'not_found') dispatch({ type: 'run.interrupted', runId: id })
        })
      })
      .catch(() => undefined)
  }, [])

  // the backend came back after an outage: reopen the run stream and reload the snapshot
  const [streamEpoch, setStreamEpoch] = useState(0)
  const chatAbort = useRef<AbortController | null>(null)
  const prevHealthFailed = useRef(false)
  useEffect(() => {
    const was = prevHealthFailed.current
    prevHealthFailed.current = state.healthFailed
    if (state.healthFailed) {
      // a chat stream through the dev proxy never ends when the backend dies: end it here
      chatAbort.current?.abort()
      return
    }
    if (was && stateRef.current.runId) {
      // the stream replays its history: diffs in it are old news
      localChange.current = false
      setStreamEpoch((e) => e + 1)
    }
  }, [state.healthFailed])

  // The page shows work in progress: ask the server now and then whether it is really busy. Through the dev
  // proxy a dead or restarted backend leaves the stream open and silent; an idle server means the stream
  // missed the end (reopen it: the replay carries run.finished) or the work died with the server.
  const idleReopen = useRef<Record<string, number>>({})
  const looksBusy = !isDemo && !!state.runId && !state.interrupted && (state.runStatus === 'running' || state.currentRound != null || Object.keys(state.vetting).length > 0)
  useEffect(() => {
    if (!looksBusy || !state.runId) return
    const id = state.runId
    const iv = window.setInterval(() => {
      api
        .status(id)
        .then((st) => {
          if (st.busy || stateRef.current.runId !== id) return
          const n = (idleReopen.current[id] ?? 0) + 1
          if (n > 3) return
          idleReopen.current[id] = n
          localChange.current = false
          setStreamEpoch((e) => e + 1)
        })
        .catch(() => refreshHealth(0))
    }, 8000)
    return () => window.clearInterval(iv)
  }, [looksBusy, state.runId, refreshHealth])

  useEffect(() => {
    if (isDemo || !state.runId) return
    const id = state.runId
    refreshSnapshot(id)
    const es = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`)
    // a run that was busy when the server stopped never sends run.finished: find out once the history replayed
    const interruptedTimer = window.setTimeout(() => checkInterrupted(id), 2500)
    // a dropped stream: check the server now instead of at the next 20 s health poll
    es.onerror = () => refreshHealth(0)
    const handle = (type: RunEvent['type']) => (e: MessageEvent) => {
      // EventSource fires a plain Event named "error" when the connection fails: not a run error event
      if (type === 'error' && (!(e instanceof MessageEvent) || e.data == null)) return
      let data: unknown = {}
      try {
        data = e.data ? JSON.parse(e.data) : {}
      } catch {
        data = { text: e.data }
      }
      if ((type === 'diff' || type === 'report.diff') && !acceptDiff()) {
        refreshSnapshot(id, 150)
        return
      }
      dispatch({ type: 'event', event: { type, data } as RunEvent, at: Date.now(), runId: id })
      // report.ready only carries the id; the full report comes with the snapshot.
      if (type === 'report.ready' && !(data as { report?: unknown }).report) refreshSnapshot(id, 250)
      if (type === 'run.finished' || type === 'diff') refreshSnapshot(id, 150)
      if (type === 'subject.resolved' || type === 'subject.not_found') refreshSnapshot(id, 100)
      // the LLM request counter in the header moves with vetting and report renders
      if (type === 'report.ready' || type === 'run.finished') refreshHealth()
    }
    const listeners = RUN_EVENTS.map((type) => {
      const fn = handle(type)
      es.addEventListener(type, fn as EventListener)
      return [type, fn] as const
    })
    // Unnamed messages carrying {type, data}
    es.onmessage = (e) => {
      try {
        const m = JSON.parse(e.data)
        if (m && typeof m.type === 'string' && RUN_EVENTS.includes(m.type)) {
          if ((m.type === 'diff' || m.type === 'report.diff') && !acceptDiff()) return
          dispatch({ type: 'event', event: { type: m.type, data: m.data ?? m } as RunEvent, at: Date.now(), runId: id })
        }
      } catch {
        /* ignore */
      }
    }
    return () => {
      window.clearTimeout(interruptedTimer)
      for (const [type, fn] of listeners) es.removeEventListener(type, fn as EventListener)
      es.onerror = null
      es.close()
    }
  }, [state.runId, isDemo, refreshSnapshot, refreshHealth, checkInterrupted, streamEpoch])

  // clear animation flags
  useEffect(() => {
    const iv = window.setInterval(() => {
      const s = stateRef.current
      if (Object.keys(s.dropping).length || Object.keys(s.arriving).length) dispatch({ type: 'anim.clear', before: Date.now() - 1400 })
    }, 500)
    return () => window.clearInterval(iv)
  }, [])

  // ---------- actions ----------
  const fail = useCallback((e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e)
    dispatch({ type: 'error', message: tRef.current('error.generic', { msg }) })
    dispatch({ type: 'recomputing', on: false })
  }, [])

  const applyMutationResult = useCallback(
    (id: string, body: unknown) => {
      // report diffs first: the diff panel keeps the report as it was before the change
      for (const rd of extractReportDiffs(body)) dispatch({ type: 'event', event: { type: 'report.diff', data: { candidate_id: rd.candidate_id, diff: rd } }, at: Date.now(), runId: id })
      const diff = extractDiff(body)
      if (diff) dispatch({ type: 'event', event: { type: 'diff', data: diff }, at: Date.now(), runId: id })
      const crit = body && typeof body === 'object' ? (body as { criteria?: CriteriaSet }).criteria : undefined
      if (crit && typeof crit === 'object' && !Array.isArray(crit) && 'criteria' in crit) dispatch({ type: 'criteria.local', criteria: crit })
      dispatch({ type: 'recomputing', on: false })
      refreshSnapshot(id)
      refreshHealth()
    },
    [refreshSnapshot, refreshHealth],
  )

  const subjectStarting = useRef(false)
  // the form's goal and the competitors the owner typed for it: a one-click switch to the other
  // preset must not carry them over (a bakery's rivals are not a gym's) nor invent the preset's samples
  const formGoal = useRef<{ runId: string; preset: PresetName; competitors: Brief['competitors'] | null } | null>(null)
  // synchronous guards: chatBusy / recomputing reach stateRef only after a render (a double submit in one task)
  const chatSending = useRef(false)
  const goalInFlight = useRef(false)
  // criteria edited before any run exists: the guide's run_rounds would start from ITS proposal, so the
  // edit is sent along, used when the owner says "yes", and applied to a run the guide starts anyway
  const pendingCrit = useRef<CriteriaSet | null>(null)
  const actions: Actions = useMemo(() => {
    const demo = demoRef.current
    if (demo) {
      return {
        sendChat: (text) => demo.userChat(text, langRef.current),
        startRun: () => demo.resume(),
        vet: () => dispatch({ type: 'chat.notice', id: uid('n'), text: tRef.current('demo.vetOnlyScripted') }),
        saveCriteria: (c) => {
          dispatch({ type: 'criteria.local', criteria: c })
          dispatch({ type: 'event', event: { type: 'log', data: { text: tRef.current('demo.localOnly'), actor: 'demo', mode: 'mock' } }, at: Date.now() })
        },
        restore: (candidateId, criterionId) => {
          dispatch({ type: 'restore.local', candidateId, criterionId, at: Date.now() })
          dispatch({ type: 'event', event: { type: 'log', data: { text: `${tRef.current('demo.restored')} (${candidateId})`, actor: 'demo', mode: 'mock' } }, at: Date.now() })
        },
        changeGoal: (brief: Brief) => {
          if (stateRef.current.mode === 'subject') {
            const p = brief.business_type && /fit/i.test(brief.business_type) ? 'fitness' : /pek|bake/i.test(brief.business_type ?? '') ? 'bakery' : null
            if (p) demo.subjectGoal(p)
            else dispatch({ type: 'chat.notice', id: uid('n'), text: tRef.current('demo.otherGoal') })
            return
          }
          demo.playGoalChange()
        },
        researchSubject: async (input: SubjectInput) => {
          const parsed = parseSubject(input.subject)
          // an empty anchor field is "no anchor" (verdict likely at best), not the demo's own anchor
          demo.playSubject({ typed: parsed.ok ? parsed.handle : input.subject, raw: input.subject.trim(), anchor: input.anchor, preset: input.preset })
        },
        switchGoal: (preset: PresetName) => demo.subjectGoal(preset),
        purge: () => {
          demo.stop()
          dispatch({ type: 'reset' })
          dispatch({ type: 'chat.notice', id: uid('n'), text: tRef.current('purge.demo') })
        },
      }
    }
    /** The guide started a run while the owner's own criteria edit was pending: apply the edit to it
     *  (once the run is idle), unless the run already uses it. */
    const applyPendingCriteria = (rid: string) => {
      const c = pendingCrit.current
      if (!c) return
      pendingCrit.current = null
      let tries = 0
      const attempt = () => {
        api
          .status(rid)
          .then((st) => {
            if (stateRef.current.runId !== rid) return
            if (st.busy) {
              if (++tries < 90) window.setTimeout(attempt, 1000)
              return
            }
            return api.run(rid).then((run) => {
              if (criteriaSig(run.criteria) === criteriaSig(c)) return
              localChange.current = true
              dispatch({ type: 'criteria.local', criteria: { ...run.criteria, criteria: c.criteria } })
              dispatch({ type: 'awaitDiff' })
              dispatch({ type: 'recomputing', on: true })
              return api.criteria(rid, { ...run.criteria, criteria: c.criteria }).then((body) => applyMutationResult(rid, body))
            })
          })
          .catch(fail)
      }
      attempt()
    }
    const sendChat = (text: string, s: AppState, runOverride?: string): Promise<boolean> => {
      localChange.current = true
      const msgId = uid('a')
      dispatch({ type: 'chat.assistantStart', id: msgId })
      let sawRun: string | null = null
      const runId = runOverride ?? s.runId
      let chatId = s.chatId
      if (!chatId) {
        chatId = newChatId()
        dispatch({ type: 'chat.id', id: chatId })
      }
      const ctl = new AbortController()
      chatAbort.current = ctl
      return streamChat(
        // A fresh page (no chat, no run) starts a new backend chat session instead of continuing
        // whatever session the backend touched last.
        { run_id: runId, chat_id: chatId, message: text, lang: langRef.current, reset: !s.chatId && !runId, criteria: runId ? null : pendingCrit.current },
        {
          onEvent: (event, data) => {
            const known = ['chat.delta', 'chat.tool', 'criteria.updated', 'done']
            if (event === 'chat.id') {
              const cid = (data as { chat_id?: string }).chat_id
              if (cid) dispatch({ type: 'chat.id', id: cid })
            } else if (known.includes(event)) {
              // the guide proposed criteria again: the chips show those now, the old edit is gone
              if (event === 'criteria.updated') pendingCrit.current = null
              dispatch({ type: 'chat.event', id: msgId, event: { type: event, data } as ChatEvent })
              // the guide answers in the owner's language; the UI follows it (docs/subject-mode.md section 12),
              // unless the owner picked the language in the menu
              const dl = event === 'done' ? (data as { lang?: unknown })?.lang : null
              if ((dl === 'cs' || dl === 'en') && dl !== langRef.current && !langChosen.current) {
                setLangState(dl)
                writePref('cs.lang', dl)
              }
              const rid = findRunId(data)
              if (rid && rid !== sawRun) {
                sawRun = rid
                dispatch({ type: 'run.id', id: rid })
              }
            } else if (event === 'error') {
              const m = (data as { message?: string })?.message ?? 'error'
              dispatch({ type: 'chat.end', id: msgId, error: m })
            } else if (RUN_EVENTS.includes(event as RunEvent['type'])) {
              // some backends interleave run events in the chat stream
              dispatch({ type: 'event', event: { type: event, data } as RunEvent, at: Date.now() })
            } else if (event === 'message' && data && typeof data === 'object' && 'text' in (data as object)) {
              dispatch({ type: 'chat.event', id: msgId, event: { type: 'chat.delta', data: data as { text: string } } })
            }
          },
        },
        ctl.signal,
      )
        .then(() => {
          dispatch({ type: 'chat.end', id: msgId })
          const rid = sawRun ?? stateRef.current.runId
          if (rid) refreshSnapshot(rid, 200)
          if (sawRun && !runId) applyPendingCriteria(sawRun)
          refreshHealth()
          return true
        })
        .catch((e: Error) => {
          const msg = e.name === 'AbortError' ? tRef.current('chat.lost') : /string_too_long/.test(e.message) ? tRef.current('chat.tooLong', { n: text.length, max: 8000 }) : e.message
          dispatch({ type: 'chat.end', id: msgId, error: tRef.current('chat.error', { msg }) })
          return false
        })
        .finally(() => {
          if (chatAbort.current === ctl) chatAbort.current = null
        })
    }
    return {
      sendChat: (text: string) => {
        const s = stateRef.current
        if (s.chatBusy || chatSending.current) return
        chatSending.current = true
        dispatch({ type: 'chat.user', id: uid('u'), text })
        const pending = pendingCrit.current
        // "Yes, start" right after the owner edited a criterion: start the run from the edited criteria here,
        // then let the guide answer about that run (its own run_rounds would use its unedited proposal)
        const start = pending && !s.runId && s.criteria && text.length <= 80 && AFFIRMATIVE.test(text) ? api.createRun(s.criteria) : null
        const go = start
          ? start.then(
              (r) => {
                pendingCrit.current = null
                dispatch({ type: 'run.id', id: r.run_id })
                return sendChat(text, stateRef.current, r.run_id)
              },
              () => sendChat(text, stateRef.current),
            )
          : sendChat(text, s)
        return go.finally(() => {
          chatSending.current = false
        })
      },
      startRun: () => {
        const c = stateRef.current.criteria
        if (!c) return
        pendingCrit.current = null
        api
          .createRun(c)
          .then((r) => dispatch({ type: 'run.id', id: r.run_id }))
          .catch(fail)
      },
      vet: (ids: string[]) => {
        const id = stateRef.current.runId
        if (!id) return
        localChange.current = true
        api.vet(id, ids).catch(fail)
      },
      saveCriteria: (c: CriteriaSet) => {
        localChange.current = true
        dispatch({ type: 'criteria.local', criteria: c })
        const id = stateRef.current.runId
        if (!id) {
          pendingCrit.current = c
          return
        }
        dispatch({ type: 'awaitDiff' })
        dispatch({ type: 'recomputing', on: true })
        api
          .criteria(id, c)
          .then((body) => applyMutationResult(id, body))
          .catch(fail)
      },
      restore: (candidateId: string, criterionId: string) => {
        const id = stateRef.current.runId
        if (!id) return
        localChange.current = true
        dispatch({ type: 'awaitDiff' })
        api
          .restore(id, candidateId, criterionId)
          .then((body) => applyMutationResult(id, body))
          .catch(fail)
      },
      changeGoal: (brief: Brief) => {
        const id = stateRef.current.runId
        if (!id) return
        localChange.current = true
        dispatch({ type: 'goal.submitted', brief })
        api
          .goal(id, brief)
          .then((body) => applyMutationResult(id, body))
          .catch(fail)
      },
      researchSubject: async (input: SubjectInput) => {
        // one start at a time: each POST /api/subject is a paid Apify (and LLM) run
        if (subjectStarting.current) return
        subjectStarting.current = true
        const parsed = parseSubject(input.subject)
        const l = langRef.current
        // the owner's own competitors only: the preset's sample rivals are not theirs
        const brief = { ...PRESETS[input.preset][l], competitors: input.competitors?.length ? input.competitors : [] }
        try {
          const r = await api.subject({ subject: input.subject.trim(), anchor: input.anchor, brief, preset: input.preset, lang: l })
          formGoal.current = { runId: r.run_id, preset: input.preset, competitors: input.competitors?.length ? input.competitors : null }
          const handle = r.subject?.handle ?? (parsed.ok ? parsed.handle : input.subject.trim().replace(/^@/, ''))
          dispatch({
            type: 'subject.start',
            runId: r.run_id,
            fromForm: true,
            subject: {
              raw: r.subject?.raw ?? input.subject.trim(),
              handle,
              platform: r.subject?.platform ?? (parsed.ok ? parsed.platform : null),
              anchor: input.anchor,
              status: 'pending',
            },
          })
          dispatch({
            type: 'chat.notice',
            id: uid('n'),
            text: '',
            notice: {
              kind: 'subject',
              handle,
              anchor: { cs: anchorText(input.anchor, 'cs') || translate('cs', 'subject.anchor.missing'), en: anchorText(input.anchor, 'en') || translate('en', 'subject.anchor.missing') },
              goal: { cs: translate('cs', input.preset === 'fitness' ? 'goal.preset.fitness' : 'goal.preset.bakery'), en: translate('en', input.preset === 'fitness' ? 'goal.preset.fitness' : 'goal.preset.bakery') },
            },
          })
        } catch (e) {
          fail(e)
          throw e
        } finally {
          subjectStarting.current = false
        }
      },
      switchGoal: (preset: PresetName) => {
        const s = stateRef.current
        const id = s.runId
        if (!id || s.recomputing || goalInFlight.current) return
        goalInFlight.current = true
        localChange.current = true
        let brief = { ...PRESETS[preset][langRef.current] }
        const fg = formGoal.current
        if (fg && fg.runId === id) {
          // the form's own preset keeps what the form sent; the other preset starts with no competitors
          brief = { ...brief, competitors: preset === fg.preset ? (fg.competitors ?? []) : [] }
        }
        dispatch({ type: 'recomputing', on: true })
        api
          .goal(id, brief, preset)
          .then((body) => applyMutationResult(id, body))
          .catch(fail)
          .finally(() => {
            goalInFlight.current = false
          })
      },
      purge: () => {
        api
          .purge()
          .then(() => {
            dispatch({ type: 'reset' })
            dispatch({ type: 'chat.notice', id: uid('n'), text: tRef.current('purge.done') })
            setRunParam(null)
            api.health().then((h) => dispatch({ type: 'health', health: h })).catch(() => undefined)
          })
          .catch(fail)
      },
    }
  }, [fail, applyMutationResult, refreshSnapshot, refreshHealth])

  const reveal = useCallback((targetId: string, focusId?: string) => {
    setView('board')
    // after the phone view has switched (the results panel must be visible before it can take focus);
    // the target may mount a little later (the demo script, a snapshot): retry for about a second
    let tries = 0
    const attempt = () => {
      const el = document.getElementById(targetId)
      if (!el) {
        if (++tries < 25) window.setTimeout(attempt, 50)
        return
      }
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
      el.classList.remove('flash-ring')
      void el.offsetWidth
      el.classList.add('flash-ring')
      // WCAG 2.4.3: focus follows the reveal. The trigger may sit in the now hidden guide panel; the
      // next Tab continues in the revealed section. focusId wins, else its heading takes focus (and names it).
      const own = focusId ? document.getElementById(focusId) : null
      const target = own ?? el.querySelector<HTMLElement>('h2') ?? el
      if (!target.hasAttribute('tabindex') && !/^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) target.setAttribute('tabindex', '-1')
      target.focus({ preventScroll: true })
    }
    window.setTimeout(attempt, 30)
  }, [])

  const value: Ctx = {
    state,
    dispatch,
    lang,
    setLang,
    t,
    theme,
    setTheme,
    blur,
    setBlur,
    openId,
    openCandidate: setOpenId,
    view,
    setView,
    reveal,
    chatCollapsed,
    setChatCollapsed,
    goalOpen,
    setGoalOpen,
    chatDraft,
    composeChat,
    actions,
    demo: demoRef.current,
    demoStatus,
  }
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}
