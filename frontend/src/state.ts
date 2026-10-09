// Single reducer for the whole app. Fed by:
//  - GET /api/runs/{id}/events (EventSource, named events from architecture.md section 7)
//  - GET /api/runs/{id} snapshots
//  - POST /api/chat SSE (chat.delta, chat.tool, criteria.updated, done)
//  - the demo replay (src/dev/demoReplay.ts), which dispatches exactly the same actions.

import type {
  Brief,
  Candidate,
  ChatEvent,
  CriteriaSet,
  Elimination,
  Health,
  I18nText,
  LogLine,
  Mode,
  Report,
  ReportDiff,
  Run,
  RunDiff,
  RunEvent,
  RunMode,
  RoundStat,
  SubjectSpec,
} from './types'

export interface ToolCall {
  name: string
  status?: string
  input?: unknown
  result?: unknown
}

/** Structured summaries the frontend adds to the chat (P0-10), rendered in the current language. */
export type NoticeData =
  | { kind: 'vet'; vetted: number; fails: { id: string; handle: string; criteria: string[] }[] }
  | { kind: 'goal'; from: string; to: string; dropped: number; returned: number }
  /** a subject check started from the form (no chat turn behind it) */
  | { kind: 'subject'; handle: string; anchor: string | I18nText; goal: string | I18nText }
  /** the subject report is ready */
  | { kind: 'subjectReady'; candidateId: string }
  /** the subject report was re-rendered for another goal */
  | { kind: 'reportDiff'; candidateId: string; diff: ReportDiff }
  /** discovery: vetted reports that changed after a goal / criteria change (one notice for the batch) */
  | { kind: 'reportDiffs'; items: { candidateId: string; handle: string; summary: I18nText }[] }
  /** a run that was still working when the server stopped */
  | { kind: 'interrupted' }
  /** the subject's public profile was not found (form path: the chat says so and what to do) */
  | { kind: 'subjectNotFound'; handle: string; tried: string[]; reason?: I18nText; offline?: boolean }

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'notice'
  text: string
  /** demo replay: the same message in both languages, so the language toggle re-renders it */
  i18n?: I18nText
  tools: ToolCall[]
  pending: boolean
  error?: string
  notice?: NoticeData
  /** the language the guide answered in (done.lang): Czech typography follows the text, not the UI */
  lang?: 'cs' | 'en'
}

export interface StoredLog extends LogLine {
  key: string
  receivedAt: number
}

export interface DiffView {
  kind: 'goal' | 'criteria'
  goalA: Brief | null
  goalB: Brief | null
  eliminationsA: Record<string, Elimination | null>
  dropped: RunDiff['dropped']
  returned: RunDiff['returned']
  at: number
  /** provisional: the backend is still fetching data for returned candidates */
  pendingFetch?: boolean
  /** key of the provisional diff a final diff replaced (so a late HTTP copy of it is ignored) */
  replacedKey?: string
  /** restore waivers that no longer apply after this change */
  waiversDropped?: RunDiff['waivers_dropped']
  /** criteria diffs: the brief before the change (a goal changed by the guide arrives as a plain diff;
   *  the next snapshot or criteria.updated with another brief turns it into a goal diff) */
  briefBefore?: Brief | null
}

/** The latest report change after a goal / criteria switch (report.diff event or HTTP report_diffs). */
export interface ReportDiffView {
  candidateId: string
  diff: ReportDiff
  /** the report as it was before the change (texts of removed findings live only there) */
  before: Report | null
  at: number
  /** the owner closed the panel; the chat notice can open it again */
  hidden?: boolean
}

export interface AppState {
  runId: string | null
  /** "subject": one named creator checked for a goal; nothing is eliminated */
  mode: RunMode
  subject: SubjectSpec | null
  /** the subject run came from the form (the chat then says when the report is ready) */
  subjectFromForm: boolean
  subjectNotFound: { subject: string; tried: string[]; reason?: I18nText } | null
  reportDiff: ReportDiffView | null
  /** the latest report diff per candidate (dedupes the stream copy and the HTTP copy) */
  reportDiffs: Record<string, ReportDiffView>
  /** a criteria save / restore is waiting for its funnel diff (an empty diff is shown only then) */
  awaitingDiff: boolean
  /** the run was still working when the server stopped (no task, no run.finished) */
  interrupted: boolean
  /** the guide changed the brief (criteria.updated with another goal): the funnel diff that follows is a goal diff */
  briefChange: { from: Brief; at: number } | null
  /** a candidate's report before its latest re-render (the backend's candidate.updated / snapshot can carry
   *  the new render before report.diff arrives; "before" texts and tiers come from here) */
  prevReports: Record<string, Report>
  /** run.llm_usage: {"total": n, "<task group>": n} */
  llmUsage: Record<string, number>
  chatId: string | null
  runStatus: 'idle' | 'running' | 'finished' | 'error'
  criteria: CriteriaSet | null
  candidates: Record<string, Candidate>
  order: string[]
  rounds: RoundStat[]
  currentRound: number | null
  log: StoredLog[]
  logKeys: Record<string, true>
  modeSummary: Partial<Record<Mode, number>>
  vetting: Record<string, string>
  sensitive: Record<string, number>
  diff: DiffView | null
  pendingGoal: { a: Brief | null; b: Brief; eliminationsA: Record<string, Elimination | null> } | null
  chat: ChatMessage[]
  chatBusy: boolean
  health: Health | null
  healthFailed: boolean
  llmMode: string | null
  dropping: Record<string, number>
  arriving: Record<string, number>
  errors: { id: string; message: string }[]
  recomputing: boolean
  demo: boolean
}

export const initialState = (demo = false): AppState => ({
  runId: null,
  mode: 'discovery',
  subject: null,
  subjectFromForm: false,
  subjectNotFound: null,
  reportDiff: null,
  reportDiffs: {},
  awaitingDiff: false,
  interrupted: false,
  briefChange: null,
  prevReports: {},
  llmUsage: {},
  chatId: null,
  runStatus: 'idle',
  criteria: null,
  candidates: {},
  order: [],
  rounds: [],
  currentRound: null,
  log: [],
  logKeys: {},
  modeSummary: {},
  vetting: {},
  sensitive: {},
  diff: null,
  pendingGoal: null,
  chat: [],
  chatBusy: false,
  health: null,
  healthFailed: false,
  llmMode: null,
  dropping: {},
  arriving: {},
  errors: [],
  recomputing: false,
  demo,
})

export type Action =
  | { type: 'reset'; keepChat?: boolean }
  | { type: 'run.id'; id: string | null }
  | { type: 'chat.id'; id: string | null }
  | { type: 'snapshot'; run: Run; at: number }
  /** runId: the run whose stream (or response) carried the event; events of another run are dropped */
  | { type: 'event'; event: RunEvent; at: number; runId?: string | null }
  | { type: 'chat.user'; id: string; text: string }
  | { type: 'chat.assistantStart'; id: string }
  | { type: 'chat.event'; id: string; event: ChatEvent }
  | { type: 'chat.end'; id: string; error?: string }
  | { type: 'chat.notice'; id: string; text: string; notice?: NoticeData }
  | { type: 'chat.i18n'; id: string; text: I18nText }
  /** a subject run was created (POST /api/subject or the demo): new board, subject mode */
  | { type: 'subject.start'; runId: string | null; subject: SubjectSpec; fromForm?: boolean }
  | { type: 'reportDiff.dismiss' }
  | { type: 'reportDiff.show' }
  | { type: 'awaitDiff' }
  | { type: 'run.interrupted'; runId: string }
  | { type: 'criteria.local'; criteria: CriteriaSet }
  | { type: 'restore.local'; candidateId: string; criterionId: string; at: number }
  | { type: 'goal.submitted'; brief: Brief }
  | { type: 'diff.dismiss' }
  | { type: 'health'; health: Health | null }
  | { type: 'error'; message: string }
  | { type: 'error.dismiss'; id: string }
  | { type: 'recomputing'; on: boolean }
  | { type: 'anim.clear'; before: number }

let errSeq = 0

function logKey(l: LogLine): string {
  return `${l.ts ?? ''}|${l.actor ?? ''}|${l.mode ?? ''}|${l.text}`
}

function appendLog(state: AppState, line: LogLine, at: number): AppState {
  if (!line || typeof line.text !== 'string') return state
  const key = logKey(line)
  if (state.logKeys[key]) return state
  const stored: StoredLog = { ...line, ts: line.ts ?? new Date(at).toISOString(), key, receivedAt: at }
  return { ...state, log: [...state.log, stored], logKeys: { ...state.logKeys, [key]: true } }
}

function upsertCandidate(state: AppState, c: Candidate, at: number): AppState {
  if (!c || !c.id) return state
  const prev = state.candidates[c.id]
  const merged: Candidate = prev ? { ...prev, ...c, report: c.report ?? prev.report ?? null } : c
  const dropping = { ...state.dropping }
  const arriving = { ...state.arriving }
  if (prev && prev.status !== 'eliminated' && merged.status === 'eliminated') dropping[c.id] = at
  if (prev && prev.status === 'eliminated' && merged.status !== 'eliminated') arriving[c.id] = at
  const sensitive = { ...state.sensitive }
  if (typeof merged.sensitive_filtered === 'number' && merged.sensitive_filtered > 0) sensitive[c.id] = merged.sensitive_filtered
  return {
    ...state,
    candidates: { ...state.candidates, [c.id]: merged },
    order: prev ? state.order : [...state.order, c.id],
    dropping,
    arriving,
    sensitive,
  }
}

function upsertRound(rounds: RoundStat[], r: RoundStat): RoundStat[] {
  const rest = rounds.filter((x) => x.round !== r.round)
  return [...rest, { round: r.round, entered: r.entered, remaining: r.remaining }].sort((a, b) => a.round - b.round)
}

function extractCriteria(data: unknown): CriteriaSet | null {
  if (!data || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  if (d.criteria && typeof d.criteria === 'object' && !Array.isArray(d.criteria)) return d.criteria as CriteriaSet
  if (Array.isArray(d.criteria) && d.brief) return d as unknown as CriteriaSet
  return null
}

/** Find a run id anywhere shallow in a chat payload (done.run_id, tool result.run_id). */
export function findRunId(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  if (typeof d.run_id === 'string' && d.run_id) return d.run_id
  for (const k of ['result', 'output', 'data']) {
    const inner = d[k]
    if (inner && typeof inner === 'object') {
      const r = (inner as Record<string, unknown>).run_id
      if (typeof r === 'string' && r) return r
    }
  }
  return null
}

/** Same report diff from the run stream and from the HTTP response (key order may differ). */
const reportDiffKey = (d: ReportDiff) =>
  JSON.stringify([d.candidate_id, d.from_goal?.brief_key ?? d.from_goal?.business_type, d.to_goal?.brief_key ?? d.to_goal?.business_type, d.summary?.en ?? d.summary?.cs, d.added, d.removed, d.moved_up, d.moved_down])

const diffKey = (d: Pick<RunDiff, 'dropped' | 'returned'>) =>
  JSON.stringify([d.dropped.map((x) => (typeof x === 'string' ? x : (x.candidate_id ?? x.id ?? x.handle))), d.returned.map((x) => (typeof x === 'string' ? x : (x.candidate_id ?? x.id ?? x.handle)))])

function applyDiff(state: AppState, diff: RunDiff, at: number): AppState {
  const dropped = Array.isArray(diff?.dropped) ? diff.dropped : []
  const returned = Array.isArray(diff?.returned) ? diff.returned : []
  const key = diffKey({ dropped, returned })
  const pendingFetch = !!diff?.pending_fetch
  const waiversDropped = Array.isArray(diff?.waivers_dropped) ? diff.waivers_dropped : undefined
  // The backend sends the same diff on the run stream AND in the HTTP response: keep the first one.
  // A late copy of a provisional diff that a final diff already replaced is ignored too.
  if (state.diff && at - state.diff.at < 30000 && (diffKey(state.diff) === key || state.diff.replacedKey === key)) {
    return { ...state, pendingGoal: null, recomputing: false, awaitingDiff: false }
  }
  // Final diff after fill_missing: replace the provisional one in place (keeps goal A/B labels).
  if (diff?.replaces_pending && state.diff?.pendingFetch) {
    return {
      ...state,
      diff: { ...state.diff, dropped, returned, at, pendingFetch: false, replacedKey: diffKey(state.diff), waiversDropped: waiversDropped ?? state.diff.waiversDropped },
      pendingGoal: null,
      recomputing: false,
      awaitingDiff: false,
    }
  }
  if (state.pendingGoal) {
    return {
      ...state,
      diff: {
        kind: 'goal',
        goalA: state.pendingGoal.a,
        goalB: state.pendingGoal.b,
        eliminationsA: state.pendingGoal.eliminationsA,
        dropped,
        returned,
        at,
        pendingFetch,
        waiversDropped,
      },
      pendingGoal: null,
      recomputing: false,
      awaitingDiff: false,
    }
  }
  // the guide's change_goal: criteria.updated with the new brief came first (chat stream), then this diff
  if (state.briefChange && at - state.briefChange.at < 60000 && briefChanged(state.briefChange.from, state.criteria?.brief)) {
    return {
      ...state,
      diff: { kind: 'goal', goalA: state.briefChange.from, goalB: state.criteria?.brief ?? null, eliminationsA: {}, dropped, returned, at, pendingFetch, waiversDropped },
      briefChange: null,
      recomputing: false,
      awaitingDiff: false,
    }
  }
  // Nothing moved and the owner did not ask for a recompute (e.g. the guide only noted a refused request):
  // no "0 / 0" panel.
  if (!dropped.length && !returned.length && !waiversDropped?.length && !state.awaitingDiff) return { ...state, recomputing: false }
  return {
    ...state,
    diff: { kind: 'criteria', goalA: null, goalB: null, eliminationsA: {}, dropped, returned, at, pendingFetch, waiversDropped, briefBefore: state.criteria?.brief ?? null },
    recomputing: false,
    awaitingDiff: false,
  }
}

const briefChanged = (a: Brief | null | undefined, b: Brief | null | undefined) =>
  !!a && !!b && ((a.business_type ?? '') !== (b.business_type ?? '') || (a.goal ?? '') !== (b.goal ?? ''))

/** A goal changed by the guide (chat change_goal) has no goal dialog behind it: its funnel diff arrives as a
 *  criteria diff. Once the new brief is known, show it as the goal diff it is. */
function upgradeToGoalDiff(state: AppState, brief: Brief | null | undefined, at: number): AppState {
  const d = state.diff
  if (!d || d.kind !== 'criteria' || !d.briefBefore || at - d.at > 60000 || !briefChanged(d.briefBefore, brief)) return state
  return { ...state, diff: { ...d, kind: 'goal', goalA: d.briefBefore, goalB: brief ?? null, briefBefore: null } }
}

/** A report diff with no change at all (same goal, same findings): a re-render nobody needs to hear about. */
export function reportDiffChanged(d: ReportDiff): boolean {
  return !!(
    d.added?.length ||
    d.removed?.length ||
    d.moved_up?.length ||
    d.moved_down?.length ||
    d.collapsed?.length ||
    d.claims_changed?.length ||
    d.checks_changed?.length ||
    d.questions_added?.length ||
    d.questions_removed?.length ||
    d.outreach_changed
  )
}
const goalKeyOf = (g: Record<string, string> | null | undefined) => g?.brief_key ?? g?.business_type ?? ''

function applyRunEvent(state: AppState, ev: RunEvent, at: number): AppState {
  const d = ev.data as never as Record<string, unknown>
  switch (ev.type) {
    case 'run.started': {
      const id = typeof d?.run_id === 'string' ? (d.run_id as string) : state.runId
      return { ...state, runId: id, runStatus: 'running' }
    }
    case 'log':
      return appendLog(state, ev.data, at)
    case 'round.started':
      return { ...state, currentRound: ev.data.round, runStatus: 'running' }
    case 'candidate.added':
    case 'candidate.updated':
      return upsertCandidate(state, ev.data.candidate, at)
    case 'candidate.eliminated': {
      const prev = state.candidates[ev.data.id]
      if (!prev) return state
      return upsertCandidate(state, { ...prev, status: 'eliminated', elimination: ev.data.elimination }, at)
    }
    case 'candidate.removed': {
      if (!state.candidates[ev.data.id]) return state
      const candidates = { ...state.candidates }
      delete candidates[ev.data.id]
      return { ...state, candidates, order: state.order.filter((id) => id !== ev.data.id) }
    }
    case 'round.finished': {
      const rounds = upsertRound(state.rounds, ev.data)
      return { ...state, rounds, currentRound: state.currentRound === ev.data.round ? null : state.currentRound }
    }
    case 'sensitive.filtered': {
      // backend: count = dropped in this step, total = the candidate's running total
      const { candidate_id, count, total } = ev.data
      const prev = state.candidates[candidate_id]
      const n = typeof total === 'number' ? total : (prev?.sensitive_filtered ?? 0) + (count ?? 0)
      const candidates = prev ? { ...state.candidates, [candidate_id]: { ...prev, sensitive_filtered: n } } : state.candidates
      return { ...state, sensitive: { ...state.sensitive, [candidate_id]: n }, candidates }
    }
    case 'vetting.progress':
      return { ...state, vetting: { ...state.vetting, [ev.data.candidate_id]: ev.data.step } }
    case 'report.ready': {
      const vetting = { ...state.vetting }
      delete vetting[ev.data.candidate_id]
      const prev = state.candidates[ev.data.candidate_id]
      const report: Report | undefined = ev.data.report
      if (prev && report) {
        return { ...state, vetting, candidates: { ...state.candidates, [prev.id]: { ...prev, report } } }
      }
      return { ...state, vetting }
    }
    case 'diff':
      return applyDiff(state, ev.data, at)
    case 'run.finished':
      return { ...state, runStatus: 'finished', currentRound: null, recomputing: false }
    case 'subject.resolved': {
      const prev = state.subject
      const subject: SubjectSpec = {
        raw: prev?.raw ?? ev.data.handle,
        anchor: prev?.anchor ?? null,
        ...prev,
        handle: ev.data.handle ?? prev?.handle ?? '',
        platform: ev.data.platform ?? prev?.platform ?? null,
        candidate_id: ev.data.candidate_id ?? prev?.candidate_id ?? null,
        status: 'resolved',
      }
      return { ...state, mode: 'subject', subject, subjectNotFound: null }
    }
    case 'subject.not_found': {
      const prev = state.subject
      const raw = ev.data.subject ?? prev?.raw ?? ''
      return {
        ...state,
        mode: 'subject',
        subject: { raw, handle: prev?.handle ?? raw.replace(/^@/, ''), anchor: prev?.anchor ?? null, ...prev, status: 'not_found' },
        subjectNotFound: { subject: raw, tried: Array.isArray(ev.data.tried) ? ev.data.tried : [], reason: ev.data.reason },
      }
    }
    case 'report.diff': {
      const diff = ev.data?.diff
      const cid = ev.data?.candidate_id ?? diff?.candidate_id
      if (!diff || !cid) return state
      // the backend sends the same diff on the run stream AND in the HTTP response: keep the first one
      const seen = state.reportDiffs[cid]
      if (seen && at - seen.at < 30000 && reportDiffKey(seen.diff) === reportDiffKey(diff)) return { ...state, recomputing: false }
      // same goal and nothing changed (a refused request re-rendered the report, a criteria edit that did
      // not touch this report): no panel, no chat line
      if (!reportDiffChanged(diff) && goalKeyOf(diff.from_goal) === goalKeyOf(diff.to_goal)) return { ...state, recomputing: false }
      const cur = state.candidates[cid]?.report ?? null
      const toKey = diff.to_goal?.brief_key
      const before = cur && toKey && cur.rendered_for?.brief_key === toKey ? (state.prevReports[cid] ?? null) : cur
      const view: ReportDiffView = { candidateId: cid, diff, before, at }
      // a discovery goal change sends report.diff for every vetted finalist BEFORE the funnel diff: the
      // pending goal must survive until that diff (it turns it into the goal diff)
      return {
        ...state,
        reportDiff: view,
        reportDiffs: { ...state.reportDiffs, [cid]: view },
        recomputing: state.mode === 'subject' ? false : state.recomputing,
        pendingGoal: state.mode === 'subject' ? null : state.pendingGoal,
      }
    }
    case 'error':
      // the server stopped while this run was working (backend /events ends with {interrupted: true}):
      // a state, not a toast; the board and the chat say it in the owner's language
      if ((ev.data as { interrupted?: unknown } | undefined)?.interrupted === true)
        return { ...state, interrupted: true, runStatus: 'error', currentRound: null, vetting: {}, recomputing: false }
      return {
        ...state,
        errors: [...state.errors, { id: `e${++errSeq}`, message: typeof ev.data?.message === 'string' ? ev.data.message : 'error' }],
        recomputing: false,
      }
    default:
      return state
  }
}

function patchMessage(state: AppState, id: string, fn: (m: ChatMessage) => ChatMessage): AppState {
  return { ...state, chat: state.chat.map((m) => (m.id === id ? fn(m) : m)) }
}

function applyChatEvent(state: AppState, id: string, ev: ChatEvent): AppState {
  switch (ev.type) {
    case 'chat.delta': {
      const piece = ev.data.text ?? ev.data.delta ?? ''
      return patchMessage(state, id, (m) => ({ ...m, text: m.text + piece }))
    }
    case 'chat.tool': {
      const call: ToolCall = { name: ev.data.name, status: ev.data.status, input: ev.data.input, result: ev.data.result }
      const next = patchMessage(state, id, (m) => {
        // A tool event with the same name and no result yet gets updated in place.
        const idx = m.tools.findIndex((t) => t.name === call.name && t.result === undefined)
        const tools = idx >= 0 && call.result !== undefined ? m.tools.map((t, i) => (i === idx ? { ...t, ...call } : t)) : [...m.tools, call]
        return { ...m, tools }
      })
      return next
    }
    case 'criteria.updated': {
      const c = extractCriteria(ev.data)
      if (!c) return state
      const now = Date.now()
      const prev = state.criteria?.brief
      const briefChange = prev && briefChanged(prev, c.brief) && state.runId ? { from: prev, at: now } : state.briefChange
      return upgradeToGoalDiff({ ...state, criteria: c, briefChange }, c.brief, now)
    }
    case 'done': {
      // run_id is applied by the store through the 'run.id' action (which also resets a stale board)
      const llm = typeof ev.data?.llm_mode === 'string' ? ev.data.llm_mode : state.llmMode
      const chatId = typeof ev.data?.chat_id === 'string' ? ev.data.chat_id : state.chatId
      const ml = (ev.data as { lang?: unknown } | undefined)?.lang
      const next = ml === 'cs' || ml === 'en' ? patchMessage(state, id, (m) => ({ ...m, lang: ml })) : state
      return { ...next, llmMode: llm, chatId }
    }
    default:
      return state
  }
}

export function reducer(state: AppState, action: Action): AppState {
  return keepPrevReports(state, reduce(state, action))
}

/** Remember the report a re-render (another goal: another rendered_for.brief_key) replaced. */
function keepPrevReports(prev: AppState, next: AppState): AppState {
  if (next.candidates === prev.candidates) return next
  let stash: Record<string, Report> | null = null
  for (const [id, c] of Object.entries(next.candidates)) {
    const old = prev.candidates[id]?.report
    const now = c.report
    if (old && now && old !== now && (old.rendered_for?.brief_key ?? null) !== (now.rendered_for?.brief_key ?? null)) {
      ;(stash ??= { ...next.prevReports })[id] = old
    }
  }
  return stash ? { ...next, prevReports: stash } : next
}

function reduce(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'reset': {
      const fresh = initialState(state.demo)
      return action.keepChat ? { ...fresh, chat: state.chat, health: state.health, llmMode: state.llmMode } : { ...fresh, health: state.health }
    }
    case 'run.id': {
      if (action.id === state.runId) return state
      if (state.runId == null) return { ...state, runId: action.id }
      // switching runs: drop the previous run's board, keep chat, criteria and health
      const fresh = initialState(state.demo)
      return { ...fresh, runId: action.id, chat: state.chat, chatId: state.chatId, criteria: state.criteria, health: state.health, healthFailed: state.healthFailed, llmMode: state.llmMode }
    }
    case 'chat.id':
      return { ...state, chatId: action.id }
    case 'snapshot': {
      const run = action.run
      // a late snapshot of the previous run (or of a purged one) must not switch the board back
      if (run.id && run.id !== state.runId && !(state.demo && !state.runId)) return state
      let next: AppState = { ...state, runId: run.id ?? state.runId }
      if (run.criteria) next.criteria = run.criteria
      const ids = Object.keys(run.candidates ?? {})
      // Upsert keeps animation flags for status transitions; candidates no longer present are removed.
      for (const id of ids) next = upsertCandidate(next, run.candidates[id], action.at)
      const keep = new Set(ids)
      if (ids.length < next.order.length) {
        const candidates: Record<string, Candidate> = {}
        for (const id of ids) candidates[id] = next.candidates[id]
        next = { ...next, candidates, order: next.order.filter((id) => keep.has(id)) }
      }
      if (Array.isArray(run.rounds)) next.rounds = [...run.rounds].sort((a, b) => a.round - b.round)
      if (run.mode_summary) next.modeSummary = run.mode_summary
      if (Array.isArray(run.log)) {
        const log: StoredLog[] = []
        const logKeys: Record<string, true> = {}
        for (const l of run.log) {
          const key = logKey(l)
          if (logKeys[key]) continue
          logKeys[key] = true
          log.push({ ...l, key, receivedAt: action.at })
        }
        // keep lines we got via events that the snapshot does not have yet
        for (const l of next.log) if (!logKeys[l.key]) { log.push(l); logKeys[l.key] = true }
        next = { ...next, log, logKeys }
      }
      if (run.status === 'finished') next.runStatus = 'finished'
      else if (run.status === 'running') next.runStatus = 'running'
      else if (next.runStatus === 'idle' && ids.length) next.runStatus = 'running'
      if (typeof run.llm_mode === 'string') next.llmMode = run.llm_mode
      if (run.mode === 'subject' || run.mode === 'discovery') next.mode = run.mode
      if (run.subject) next.subject = { ...next.subject, ...run.subject }
      if (run.llm_usage && typeof run.llm_usage === 'object') next.llmUsage = run.llm_usage
      if (run.criteria) next = upgradeToGoalDiff(next, run.criteria.brief, action.at)
      return next
    }
    case 'event':
      // the old run's stream can still deliver a few events after the board switched to another run
      if (action.runId !== undefined && action.runId !== state.runId) return state
      return applyRunEvent(state, action.event, action.at)
    case 'chat.user':
      return {
        ...state,
        chat: [...state.chat, { id: action.id, role: 'user', text: action.text, tools: [], pending: false }],
      }
    case 'chat.assistantStart':
      return {
        ...state,
        chatBusy: true,
        chat: [...state.chat, { id: action.id, role: 'assistant', text: '', tools: [], pending: true }],
      }
    case 'chat.event':
      return applyChatEvent(state, action.id, action.event)
    case 'chat.end':
      return {
        ...patchMessage(state, action.id, (m) => ({ ...m, pending: false, error: action.error ?? m.error })),
        chatBusy: false,
      }
    case 'chat.notice':
      return { ...state, chat: [...state.chat, { id: action.id, role: 'notice', text: action.text, tools: [], pending: false, notice: action.notice }] }
    case 'chat.i18n':
      return patchMessage(state, action.id, (m) => ({ ...m, i18n: action.text }))
    case 'subject.start': {
      // a new board for the subject run; chat, chat session and health stay
      const fresh = initialState(state.demo)
      return {
        ...fresh,
        runId: action.runId,
        mode: 'subject',
        subject: action.subject,
        subjectFromForm: !!action.fromForm,
        runStatus: 'running',
        chat: state.chat,
        chatId: state.chatId,
        health: state.health,
        healthFailed: state.healthFailed,
        llmMode: state.llmMode,
      }
    }
    case 'reportDiff.dismiss':
      return state.reportDiff ? { ...state, reportDiff: { ...state.reportDiff, hidden: true } } : state
    case 'reportDiff.show':
      return state.reportDiff ? { ...state, reportDiff: { ...state.reportDiff, hidden: false } } : state
    case 'awaitDiff':
      // the owner's own edit: its diff is a criteria diff, whatever the guide changed before
      return { ...state, awaitingDiff: true, briefChange: null }
    case 'run.interrupted': {
      if (action.runId !== state.runId) return state
      return { ...state, interrupted: true, runStatus: 'error', currentRound: null, vetting: {}, recomputing: false }
    }
    case 'criteria.local':
      return { ...state, criteria: action.criteria }
    case 'restore.local': {
      const c = state.candidates[action.candidateId]
      if (!c) return state
      const results = c.results.map((r) => (r.criterion_id === action.criterionId ? { ...r, waived: true } : r))
      return upsertCandidate(state, { ...c, results, status: 'active', elimination: null, restored: true }, action.at)
    }
    case 'goal.submitted': {
      const eliminationsA: Record<string, Elimination | null> = {}
      for (const id of state.order) eliminationsA[id] = state.candidates[id]?.elimination ?? null
      return {
        ...state,
        pendingGoal: { a: state.criteria?.brief ?? null, b: action.brief, eliminationsA },
        recomputing: true,
      }
    }
    case 'diff.dismiss':
      return { ...state, diff: null }
    case 'health':
      return { ...state, health: action.health, healthFailed: action.health == null, llmMode: action.health?.llm_mode ?? state.llmMode }
    case 'error':
      return { ...state, errors: [...state.errors, { id: `e${++errSeq}`, message: action.message }] }
    case 'error.dismiss':
      return { ...state, errors: state.errors.filter((e) => e.id !== action.id) }
    case 'recomputing':
      return { ...state, recomputing: action.on }
    case 'anim.clear': {
      const dropping: Record<string, number> = {}
      const arriving: Record<string, number> = {}
      for (const [k, v] of Object.entries(state.dropping)) if (v >= action.before) dropping[k] = v
      for (const [k, v] of Object.entries(state.arriving)) if (v >= action.before) arriving[k] = v
      return { ...state, dropping, arriving }
    }
    default:
      return state
  }
}

// ---------- selectors ----------

export function lastFinishedRound(state: AppState): number {
  return state.rounds.reduce((m, r) => (r.round <= 3 ? Math.max(m, r.round) : m), -1)
}

/** Which funnel column an active/finalist candidate sits in. Eliminated ones go to the lane of their round. */
export function columnOf(state: AppState, c: Candidate): number {
  if (c.status === 'eliminated') return c.elimination?.round ?? 1
  // Survivors of round 3 have status "finalist" (backend). They move to column 4 only once vetted.
  if (state.vetting[c.id]) return 4
  if (c.report && state.rounds.some((r) => r.round === 4)) return 4
  return Math.min(Math.max(lastFinishedRound(state), 0), 3)
}

export function modeCounts(state: AppState): Record<Mode, number> {
  const s = state.modeSummary
  if (s && (s.live || s.cache || s.mock)) return { live: s.live ?? 0, cache: s.cache ?? 0, mock: s.mock ?? 0 }
  const out: Record<Mode, number> = { live: 0, cache: 0, mock: 0 }
  for (const id of state.order) {
    const c = state.candidates[id]
    const m = c?.profile?.source?.mode ?? c?.ref?.source?.mode
    if (m && m in out) out[m] += 1
  }
  return out
}

export function sensitiveTotal(state: AppState): number {
  return Object.values(state.sensitive).reduce((a, b) => a + b, 0)
}

/** The single subject of a subject run (null in discovery mode or before it resolves). */
export function subjectCandidate(state: AppState): Candidate | null {
  if (state.mode !== 'subject') return null
  const id = state.subject?.candidate_id
  if (id && state.candidates[id]) return state.candidates[id]
  const first = state.order[0]
  return first ? (state.candidates[first] ?? null) : null
}

/** The run has started (rounds or candidates exist, or a round is running). */
export function runStarted(state: AppState): boolean {
  // a subject run counts as started from its creation (a not-found subject never gets rounds or candidates)
  return state.rounds.length > 0 || state.order.length > 0 || state.currentRound != null || state.runStatus === 'running' || (state.mode === 'subject' && !!state.runId)
}

/** Finalists after round 3 that have not been vetted yet (backend vets at most 5 at once). */
export function awaitingVet(state: AppState): Candidate[] {
  // a subject run vets its one creator by itself
  if (state.mode === 'subject') return []
  if (lastFinishedRound(state) < 3 || state.currentRound === 4 || Object.keys(state.vetting).length > 0) return []
  const out: Candidate[] = []
  for (const id of state.order) {
    const c = state.candidates[id]
    if (!c || c.status === 'eliminated') continue
    if (columnOf(state, c) !== 3) continue
    if (c.report || state.vetting[c.id]) continue
    out.push(c)
  }
  return out
}

/** Which single action is the primary (filled) button right now: one per screen. */
export function primaryAction(state: AppState, demoBakeryDone = false): 'start' | 'vet' | 'demoGoal' | 'chat' {
  if (state.mode === 'subject') return 'chat'
  if (state.criteria && !runStarted(state) && !state.runId && !state.demo) return 'start'
  // the demo script vets by itself; once its first half is done, the next step is the goal change
  if (state.demo && demoBakeryDone) return 'demoGoal'
  if (awaitingVet(state).length > 0) return 'vet'
  return 'chat'
}
