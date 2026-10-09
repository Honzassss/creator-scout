import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useApp } from '../store'
import { awaitingVet, columnOf, lastFinishedRound, primaryAction, runStarted } from '../state'
import { fmtCompact, fmtInt, pick, translate, vetStepLabel, type I18nKey } from '../i18n'
import type { Candidate, Criterion, CriterionResult } from '../types'
import { CritIcon, Handle, MockTag, Odometer, Sep, SourceChips, focusSoon, initialOf, platformLabel, platformLong, scrollToEl } from './primitives'

export function foundViaLabel(v: string, lang: 'cs' | 'en'): string {
  const [kind, ...rest] = v.split(':')
  const val = rest.join(':')
  switch (kind) {
    case 'hashtag':
      return `#${val}`
    case 'search':
      return lang === 'cs' ? `„${val}“` : `“${val}”`
    case 'place':
      return `⌖ ${lang === 'cs' ? val.replace(/(\S) - (\S)/g, '$1 – $2') : val}`
    case 'related':
      return `≈ ${val}`
    case 'manual':
      return translate(lang, 'foundVia.manual')
    default:
      return v
  }
}

export function useCriteriaMap() {
  const { state } = useApp()
  return useMemo(() => {
    const m: Record<string, Criterion> = {}
    for (const c of state.criteria?.criteria ?? []) m[c.id] = c
    return m
  }, [state.criteria])
}

/** Results of the latest evaluated round for a candidate. */
function latestResults(c: Candidate, crit: Record<string, Criterion>): { round: number; results: CriterionResult[] } {
  const round = c.results.reduce((m, r) => Math.max(m, crit[r.criterion_id]?.round ?? 0), 0)
  return { round, results: c.results.filter((r) => (crit[r.criterion_id]?.round ?? 0) === round) }
}

function ResultLine({ r, label }: { r: CriterionResult; label: string }) {
  const { t } = useApp()
  const key = r.waived ? 'funnel.waivedCrit' : r.status === 'fail' ? 'funnel.failsCrit' : 'funnel.unknownCrit'
  return (
    <span className="flex items-start gap-1 text-sm text-ink-2 min-w-0">
      <CritIcon status={r.status} waived={r.waived} silent />
      {/* full text, wraps; never cut off */}
      <span className="min-w-0 [overflow-wrap:anywhere]">{t(key, { name: label })}</span>
    </span>
  )
}

function CandidateCard({ c, dense, dropping, arriving }: { c: Candidate; dense: boolean; dropping?: boolean; arriving?: boolean }) {
  const { state, lang, t, openCandidate } = useApp()
  const crit = useCriteriaMap()
  const p = c.profile
  const handle = p?.handle ?? c.ref.handle
  const mode = p?.source?.mode ?? c.ref.source?.mode
  const vettingStep = state.vetting[c.id]
  const { round: lastRound, results: latest } = latestResults(c, crit)
  const issues = latest.filter((r) => r.status !== 'pass' || r.waived)
  const elimClass = c.status === 'eliminated' ? 'elim-id' : ''
  const city = c.metrics?.local_signals?.length ? state.criteria?.brief?.city : null
  const followers = p?.followers
  const cls = `ccard ${dense ? 'dense' : ''} ${dropping ? 'dropping' : ''} ${arriving ? 'arriving' : ''}`

  // The accessible name is composed from the visible content: @handle, MOCK, platform, followers,
  // the round result and whether a dossier exists. No aria-label with only the handle.
  if (dense)
    return (
      <button type="button" className={cls} data-testid="candidate-card" data-candidate={c.id} onClick={() => openCandidate(c.id)} tabIndex={dropping ? -1 : undefined}>
        <span className={`avatar avatar-sm ${elimClass}`} aria-hidden>
          {initialOf(handle, p?.display_name)}
        </span>
        {/* the handle keeps the full width (wraps, never cut off); MOCK and followers go on line 2 */}
        <span className="min-w-0 flex flex-col">
          <span className={`text-sm font-semibold leading-5 [overflow-wrap:anywhere] ${elimClass}`} translate="no">
            <Handle handle={handle} />
          </span>
          <span className="meta-list meta">
            <span className="meta-items">
              {mode === 'mock' && (
                <span className="mi">
                  <Sep />
                  <MockTag short />
                </span>
              )}
              <span className={`mi ${mode === 'mock' ? 'nodot' : ''}`}>
                <Sep />
                <span aria-hidden>{platformLabel(c.ref.platform, t)}</span>
                <span className="sr-only">{platformLong(c.ref.platform, t)}</span>
              </span>
              {followers != null && (
                <span className="mi whitespace-nowrap">
                  <Sep />
                  {fmtCompact(followers, lang)}
                  <span className="sr-only"> {t('card.followers')}</span>
                </span>
              )}
            </span>
          </span>
        </span>
      </button>
    )

  return (
    <button type="button" className={cls} data-testid="candidate-card" data-candidate={c.id} onClick={() => openCandidate(c.id)} tabIndex={dropping ? -1 : undefined}>
      <span className={`avatar ${elimClass}`} aria-hidden>
        {initialOf(handle, p?.display_name)}
      </span>
      <span className="min-w-0 flex flex-col gap-1">
        {/* the full handle, wrapping after "_" or "." when the column is narrow (never an ellipsis) */}
        <span className={`text-base font-semibold leading-6 [overflow-wrap:anywhere] ${elimClass}`} translate="no">
          <Handle handle={handle} />
        </span>
        {/* the "·" separators are drawn by CSS and clipped at the start of a line, so a wrapped
            line never starts or ends with a stray dot (.meta-list in index.css) */}
        <span className="meta-list meta">
          <span className="meta-items">
            {mode === 'mock' && (
              <span className="mi">
                <Sep />
                <MockTag />
              </span>
            )}
            <span className={`mi ${mode === 'mock' ? 'nodot' : ''}`}>
              <Sep />
              {platformLabel(c.ref.platform, t) === platformLong(c.ref.platform, t) ? (
                <span>{platformLabel(c.ref.platform, t)}</span>
              ) : (
                <>
                  <span aria-hidden>{platformLabel(c.ref.platform, t)}</span>
                  <span className="sr-only">{platformLong(c.ref.platform, t)}</span>
                </>
              )}
            </span>
            {followers != null && (
              <span className="mi whitespace-nowrap">
                <Sep />
                {fmtCompact(followers, lang)}
                <span className="sr-only"> {t('card.followers')}</span>
              </span>
            )}
            {city && (
              <span className="mi whitespace-nowrap">
                <Sep />
                {city}
              </span>
            )}
            {c.restored && (
              <span className="mi whitespace-nowrap italic">
                <Sep />
                {t('funnel.restored')}
              </span>
            )}
          </span>
        </span>
        {latest.length > 0 && (
          <span className="flex flex-col gap-1 min-w-0">
            <Sep />
            {issues.length > 0 ? (
              issues.map((r, i) => (
                <Fragment key={r.criterion_id}>
                  {i > 0 && <Sep />}
                  <ResultLine r={r} label={pick(crit[r.criterion_id]?.label ?? r.criterion_id, lang)} />
                </Fragment>
              ))
            ) : (
              <span className="flex items-start gap-1 text-sm text-ink-2">
                <CritIcon status="pass" silent />
                <span>{t('card.allPass', { n: lastRound })}</span>
              </span>
            )}
          </span>
        )}
        {vettingStep && (
          <span className="flex items-center gap-2 text-sm text-ink-2 min-w-0">
            <Sep />
            <span className="work-dot flex-none" aria-hidden />
            <span className="truncate">
              {t('funnel.vetting')}: {vettingStep}
            </span>
          </span>
        )}
        {c.report && !vettingStep && (
          <span className="card-open">
            <Sep />
            {t('funnel.openDossier')}
          </span>
        )}
      </span>
    </button>
  )
}

function LaneSummary({ round, items, open, onToggle }: { round: number; items: Candidate[]; open: boolean; onToggle: () => void }) {
  const { t, lang } = useApp()
  const crit = useCriteriaMap()
  if (!items.length) return null
  const groups = new Map<string, number>()
  for (const c of items) {
    const id = c.elimination?.criterion_id ?? '?'
    groups.set(id, (groups.get(id) ?? 0) + 1)
  }
  return (
    <div className="lane" data-testid="eliminated-lane" data-round={round}>
      <h4 className="smallcaps !text-ink-2" title={t('funnel.eliminatedLane', { n: round })}>
        {t('funnel.eliminatedN', { n: items.length })}
      </h4>
      <ul role="list" className="mt-1 flex flex-col gap-1">
        {[...groups.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([id, n]) => (
            <li key={id} className="flex items-baseline gap-2 text-sm text-ink-2">
              <span className="num text-ink-3 w-8 text-right flex-none">{n}×</span>
              <span className="min-w-0">{crit[id] ? pick(crit[id].label, lang) : id}</span>
            </li>
          ))}
      </ul>
      <button type="button" className="btn btn-sm w-full mt-2" aria-expanded={open} aria-controls="elim-panel" onClick={onToggle}>
        {open ? t('funnel.hideEliminated') : t('funnel.showEliminated', { n: items.length })}
        <span aria-hidden>{open ? '↑' : '↓'}</span>
      </button>
    </div>
  )
}

/** Wide panel under the funnel: eliminated in one round, grouped by criterion, with "Vrátit". */
function EliminatedPanel({ round, items, onClose }: { round: number; items: Candidate[]; onClose: () => void }) {
  const { t, lang, actions, openCandidate } = useApp()
  const crit = useCriteriaMap()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    scrollToEl(ref.current, 'nearest')
  }, [round])
  const groups = new Map<string, Candidate[]>()
  for (const c of items) {
    const id = c.elimination?.criterion_id ?? '?'
    groups.set(id, [...(groups.get(id) ?? []), c])
  }
  return (
    <div ref={ref} id="elim-panel" data-testid="eliminated-panel" className="elim-panel px-4 py-3 max-h-[480px] flex flex-col" role="region" aria-labelledby="elim-h">
      <div className="flex items-center justify-between gap-3 flex-none">
        <h3 id="elim-h" className="text-md font-semibold">
          {t('funnel.eliminatedLane', { n: round })} <span className="text-ink-3 tnum">· {items.length}</span>
        </h3>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          {t('funnel.hideEliminated')} <span aria-hidden>↑</span>
        </button>
      </div>
      <div className="mt-2 min-h-0 overflow-y-auto scroll-thin pr-2 flex flex-col gap-4">
        {[...groups.entries()]
          .sort((a, b) => b[1].length - a[1].length)
          .map(([id, list]) => {
            const label = crit[id] ? pick(crit[id].label, lang) : id
            return (
              <div key={id}>
                <h4 className="smallcaps !text-ink-2 py-1 sticky top-0 bg-paper-2">
                  {label} · {list.length}
                </h4>
                <ul role="list">
                  {list.map((c) => {
                    const handle = c.profile?.handle ?? c.ref.handle
                    const r = c.results.find((x) => x.criterion_id === id)
                    const value = r?.value ? pick(r.value, lang) : pick(c.elimination?.reason, lang).replace(/^(Kolo|Round) \d+: /, '')
                    return (
                      <li key={c.id} className="elim-row lane-item">
                        <button type="button" className="elim-id text-left font-semibold [overflow-wrap:anywhere] min-h-6 hover:underline" translate="no" onClick={() => openCandidate(c.id)}>
                          <Handle handle={handle} />
                        </button>
                        <span className="flex items-start gap-1 text-sm text-ink-2 min-w-0">
                          <CritIcon status="fail" silent />
                          <span className="min-w-0">
                            {t('funnel.failsCrit', { name: label })}{' '}
                            <span className="text-ink-3">{value.includes('(') ? `– ${value}` : `(${value})`}</span>
                          </span>
                        </span>
                        <span className="flex gap-1 flex-wrap">
                          <SourceChips sources={c.elimination?.sources ?? []} />
                        </span>
                        {c.elimination?.criterion_id ? (
                          <button
                            type="button"
                            className="btn btn-sm restore"
                            data-testid="restore"
                            title={t('funnel.restore.title')}
                            aria-label={t('funnel.restoreNamed', { handle })}
                            onClick={() => actions.restore(c.id, c.elimination!.criterion_id)}
                          >
                            <span aria-hidden>↺</span> {t('funnel.restore')}
                          </button>
                        ) : (
                          <span />
                        )}
                      </li>
                    )
                  })}
                </ul>
              </div>
            )
          })}
      </div>
    </div>
  )
}

function FoundVia({ cands }: { cands: Candidate[] }) {
  const { t, lang } = useApp()
  const counts = new Map<string, number>()
  for (const c of cands) for (const v of c.ref.found_via ?? []) counts.set(v, (counts.get(v) ?? 0) + 1)
  const list = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 9)
  const max = Math.max(1, ...list.map((x) => x[1]))
  if (!list.length) return null
  return (
    <div className="mt-1">
      <h4 className="smallcaps mb-2">{t('funnel.foundVia')}</h4>
      <ul role="list" className="flex flex-col gap-2">
        {list.map(([v, n]) => (
          <li key={v} className="text-sm">
            <div className="flex justify-between gap-2">
              <span className="truncate text-ink-2" translate="no">
                {foundViaLabel(v, lang)}
              </span>
              <span className="num text-ink-2">{n}</span>
            </div>
            <div className="h-1 bg-paper-3 mt-1 rounded-xs overflow-hidden" aria-hidden>
              <div className="h-full bg-ink-2 origin-left" style={{ transform: `scaleX(${n / max})` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

const MAX_VET = 5

/** The step action: "Prověřit 5 do hloubky" (the one primary button), with an optional picker. */
function VetAction({ candidates, sticky }: { candidates: Candidate[]; sticky?: boolean }) {
  const { t, actions } = useApp()
  const ids = candidates.map((c) => c.id).join('|')
  // a candidate the owner restored by hand is in the default pick (it was left out silently at 6 finalists)
  const defaults = () => [...candidates.filter((c) => c.restored), ...candidates.filter((c) => !c.restored)].slice(0, MAX_VET).map((c) => c.id)
  const [sel, setSel] = useState<string[]>(defaults)
  const [picking, setPicking] = useState(false)
  const pickId = useId()
  useEffect(() => {
    setSel(defaults())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids])
  const toggle = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX_VET ? s : [...s, id]))
  return (
    <div className={sticky ? 'flex flex-wrap items-center gap-x-3 gap-y-1' : 'flex flex-col items-end gap-1 text-right'}>
      <button type="button" className={`btn btn-primary btn-lg ${sticky ? 'flex-1' : ''}`} onClick={() => {
          if (!sel.length) return
          actions.vet(sel)
          // this button unmounts when vetting starts: focus goes to the funnel heading
          focusSoon(() => document.getElementById('funnel-h'))
        }} aria-disabled={!sel.length || undefined} title={sticky ? t('funnel.vet.hint') : undefined}>
        {t('funnel.vet', { n: sel.length })}
      </button>
      {candidates.length > 1 && (
        <button type="button" className="btn-link text-sm" aria-expanded={picking} aria-controls={pickId} onClick={() => setPicking((v) => !v)}>
          {t('funnel.vet.pick', { sel: sel.length, n: candidates.length })}
        </button>
      )}
      {picking && (
        <fieldset id={pickId} className="text-left border border-rule rounded-sm p-2 bg-card min-w-[220px]">
          <legend className="text-sm text-ink-2 px-1">{t('funnel.vet.pickHint', { n: MAX_VET })}</legend>
          {candidates.map((c) => {
            const handle = c.profile?.handle ?? c.ref.handle
            const on = sel.includes(c.id)
            return (
              <label key={c.id} className="flex items-center gap-2 min-h-8 px-1 text-sm cursor-pointer rounded-xs hover:bg-paper-2">
                <input type="checkbox" name="vet" value={c.id} checked={on} onChange={() => toggle(c.id)} disabled={!on && sel.length >= MAX_VET} />
                <span className="truncate font-medium" translate="no">
                  @{handle}
                </span>
              </label>
            )
          })}
        </fieldset>
      )}
      {!sticky && <p className="text-sm text-ink-2 max-w-[300px]">{t('funnel.vet.hint')}</p>}
    </div>
  )
}

type StepState = 'done' | 'current' | 'future'

function Stepper({ states, running }: { states: StepState[]; running: number | null }) {
  const { t } = useApp()
  return (
    <ol className="stepper" aria-label={t('funnel.stepper')}>
      {states.map((st, r) => (
        <li key={r} className={`is-${st} ${running === r ? 'is-running' : ''}`} aria-current={st === 'current' ? 'step' : undefined}>
          <span className="step-dot" aria-hidden>
            {st === 'done' ? '✓' : ''}
          </span>
          <span className="step-label">
            <span className="tnum">{r}</span> {t(`round.${r}` as I18nKey)}
            <span className="sr-only">
              : {st === 'done' ? t('funnel.step.done') : st === 'current' ? (running === r ? t('funnel.step.current') : t('funnel.step.next')) : t('funnel.step.future')}
            </span>
          </span>
          {r < states.length - 1 && <span className="step-line" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

function EmptyFunnel() {
  const { state, t, setView, setChatCollapsed, composeChat } = useApp()
  const step = state.criteria ? 2 : state.chat.length ? 1 : 1
  const steps = [
    { n: 1, title: t('funnel.empty.step1'), body: t('funnel.empty.step1.body') },
    { n: 2, title: t('funnel.empty.step2'), body: t('funnel.empty.step2.body') },
    { n: 3, title: t('funnel.empty.step3'), body: t('funnel.empty.step3.body') },
  ]
  return (
    <section id="funnel" className="panel" aria-labelledby="funnel-h">
      <div className="px-4 pt-3 pb-4">
        <h2 id="funnel-h" className="font-display text-lg font-semibold">
          {t('funnel.title')}
        </h2>
        <p className="text-base text-ink-2 mt-1">{t('funnel.status.idle')}</p>
        <ol role="list" className="grid md:grid-cols-3 gap-4 mt-4">
          {steps.map((s) => (
            <li key={s.n} className={`flex gap-3 ${s.n === step ? '' : ''}`} aria-current={s.n === step ? 'step' : undefined}>
              <span
                className={`flex-none w-8 h-8 rounded-full inline-grid place-content-center font-display text-md font-semibold ${
                  s.n < step ? 'bg-ink-2 text-paper' : s.n === step ? 'border-2 border-ink text-ink' : 'border border-field text-ink-2'
                }`}
                aria-hidden
              >
                {s.n < step ? '✓' : s.n}
              </span>
              <span className="min-w-0">
                <span className={`block text-base font-semibold ${s.n === step ? 'text-ink' : 'text-ink-2'}`}>{s.title}</span>
                <span className="block text-sm text-ink-2 mt-1">{s.body}</span>
              </span>
            </li>
          ))}
        </ol>
        <div className="mt-5 flex items-center gap-3 flex-wrap border border-dashed border-rule-strong rounded-sm px-4 py-3">
          <p className="text-base flex-1 min-w-[220px]">{t('funnel.empty.subject')}</p>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              // the form lives in the guide: open a collapsed guide first, then focus once it has mounted
              setChatCollapsed(false)
              setView('chat')
              let tries = 0
              const focus = () => {
                const el = document.querySelector<HTMLInputElement>('.subject-entry input[name="subject"]')
                if (el) el.focus()
                else if (++tries < 10) window.setTimeout(focus, 40)
                // the form is shown only before a conversation starts: then the composer gets a draft
                else composeChat(t('funnel.empty.subjectDraft'))
              }
              window.setTimeout(focus, 40)
            }}
          >
            {t('funnel.empty.subjectGo')} <span aria-hidden>→</span>
          </button>
        </div>
        <svg viewBox="0 0 600 120" className="outline-funnel w-full max-w-[640px] h-auto mt-6 mx-auto block" role="img" aria-label={t('funnel.empty.outline')}>
          {[0, 1, 2, 3, 4].map((r) => {
            const x = r * 120
            const h0 = 100 - r * 18
            const h1 = 100 - (r + 1) * 18
            return <path key={r} d={`M${x + 4} ${60 - h0 / 2} L${x + 116} ${60 - Math.max(h1, 14) / 2} L${x + 116} ${60 + Math.max(h1, 14) / 2} L${x + 4} ${60 + h0 / 2} Z`} />
          })}
        </svg>
        <div className="grid grid-cols-5 max-w-[640px] mx-auto mt-1 text-center text-sm text-ink-2" aria-hidden>
          {[0, 1, 2, 3, 4].map((r) => (
            <span key={r}>
              {r} {t(`round.${r}` as I18nKey)}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}

export function Funnel() {
  const { state, t, lang, demoStatus } = useApp()
  const lastCol = useRef<Record<string, number>>({})
  const gridRef = useRef<HTMLDivElement>(null)
  const [openLane, setOpenLane] = useState<number | null>(null)
  const [openCols, setOpenCols] = useState<Record<number, boolean>>({})
  const [announce, setAnnounce] = useState('')
  const cands = state.order.map((id) => state.candidates[id]).filter(Boolean)
  const lastFinished = lastFinishedRound(state)
  const roundStat = (r: number) => state.rounds.find((x) => x.round === r)
  const started = runStarted(state)

  // ---------- screen reader announcements: round ends, vetting end, recompute ----------
  // A recompute (goal or criteria change) updates several rounds, and the new counts arrive one by
  // one after `recomputing` turns off. Per-round lines are skipped then; one summary
  // ("Přepočítáno: 48 → 34 → 10 → 5") is announced once the counts have settled.
  const prevRounds = useRef<Map<number, string> | null>(null)
  const roundsRef = useRef(state.rounds)
  roundsRef.current = state.rounds
  const summary = useRef<{ pending: boolean; timer: number | null }>({ pending: false, timer: null })
  const scheduleSummary = () => {
    const s = summary.current
    if (s.timer) window.clearTimeout(s.timer)
    s.timer = window.setTimeout(() => {
      s.pending = false
      s.timer = null
      const path = [0, 1, 2, 3]
        .map((r) => roundsRef.current.find((x) => x.round === r))
        .filter(Boolean)
        .map((x) => fmtInt(x!.remaining, lang))
        .join(' → ')
      if (path) setAnnounce(t('funnel.announce.recomputed', { path }))
    }, 900)
  }
  useEffect(() => () => {
    if (summary.current.timer) window.clearTimeout(summary.current.timer)
  }, [])
  useEffect(() => {
    const next = new Map(state.rounds.map((r) => [r.round, `${r.entered}/${r.remaining}`]))
    const prev = prevRounds.current
    if (summary.current.pending) scheduleSummary()
    else if (prev && !state.recomputing) {
      for (const r of state.rounds) {
        if (r.round > 3 || prev.get(r.round) === next.get(r.round)) continue
        setAnnounce(
          r.round === 0
            ? t('funnel.announce.round0', { remaining: fmtInt(r.remaining, lang) })
            : t('funnel.announce.round', { n: r.round, entered: fmtInt(r.entered, lang), remaining: fmtInt(r.remaining, lang) }),
        )
      }
    }
    prevRounds.current = next
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.rounds])
  const vettingN = Object.keys(state.vetting).length
  const r4 = state.rounds.find((r) => r.round === 4)
  const prevVetting = useRef({ n: vettingN, r4: !!r4 })
  useEffect(() => {
    const prev = prevVetting.current
    prevVetting.current = { n: vettingN, r4: !!r4 }
    if (vettingN === 0 && r4 && (prev.n > 0 || !prev.r4)) setAnnounce(t('funnel.announce.vet', { n: r4.remaining }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vettingN, r4?.remaining])
  const wasRecomputing = useRef(state.recomputing)
  useEffect(() => {
    const was = wasRecomputing.current
    wasRecomputing.current = state.recomputing
    if (state.recomputing) {
      summary.current.pending = false
      setAnnounce(t('funnel.announce.recompute'))
    } else if (was) {
      summary.current.pending = true
      scheduleSummary()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.recomputing])

  // where each candidate sits now; dropping cards stay in their previous column while they fall
  const cols: Record<number, { active: Candidate[]; dropping: Candidate[]; lane: Candidate[] }> = {}
  for (let r = 0; r <= 4; r++) cols[r] = { active: [], dropping: [], lane: [] }
  const nextCols: Record<string, number> = {}
  for (const c of cands) {
    const col = columnOf(state, c)
    if (c.status === 'eliminated') {
      const lane = c.elimination?.round ?? 1
      cols[Math.min(Math.max(lane, 1), 4)].lane.push(c)
      if (state.dropping[c.id]) {
        const from = lastCol.current[c.id] ?? (lane === 4 ? 4 : Math.max(0, lane - 1))
        cols[from].dropping.push(c)
        nextCols[c.id] = from
      }
    } else {
      cols[col].active.push(c)
      nextCols[c.id] = col
    }
  }
  lastCol.current = { ...lastCol.current, ...nextCols }

  const waiting = awaitingVet(state)
  const isPrimaryVet = primaryAction(state, !!demoStatus?.bakeryDone) === 'vet'
  const vetted = cands.filter((c) => c.report && c.status !== 'eliminated')
  const brief = state.criteria?.brief
  // a report re-rendered for the current goal (rendered_for) is not stale even though its data was fetched for another
  const staleVet = vetted.some((c) => {
    const forGoal = c.report?.rendered_for?.business_type ?? c.report?.vetted_for
    return !!forGoal && !!brief?.business_type && forGoal !== brief.business_type
  })
  const vettingIds = Object.keys(state.vetting)

  // round states for the stepper
  const states: StepState[] = [0, 1, 2, 3, 4].map((r) => {
    if (state.currentRound === r || (r === 4 && vettingIds.length > 0)) return 'current'
    if (r < 4 && roundStat(r)) return 'done'
    if (r === 4 && roundStat(4) && vettingIds.length === 0 && waiting.length === 0) return 'done'
    return 'future'
  })
  if (!states.includes('current')) {
    const next = states.indexOf('future')
    if (next >= 0 && (next === 0 || states[next - 1] === 'done')) states[next] = 'current'
  }
  const running = state.currentRound ?? (vettingIds.length ? 4 : null)
  const currentCol = state.currentRound ?? (vettingIds.length ? 4 : [4, 3, 2, 1, 0].find((r) => cols[r].active.length > 0) ?? 0)

  // A finished run that found nobody: say why (the reason is otherwise only in the collapsed live log).
  const emptyRun = cands.length === 0 && state.runStatus !== 'running' && state.rounds.some((x) => x.round === 0 && x.remaining === 0)
  const emptyWhy = emptyRun ? state.log.filter((l) => l.mode || l.actor).slice(-2) : []

  // one sentence about the work going on now
  const status = (() => {
    if (state.recomputing) return t('funnel.status.recomputing')
    if (emptyRun) return t('funnel.status.empty')
    if (state.currentRound != null && state.currentRound < 4) return t(`round.${state.currentRound}.doing` as I18nKey)
    if (vettingIds.length || state.currentRound === 4) {
      const total = cols[4].active.length || vettingIds.length
      const done = cols[4].active.filter((c) => c.report && !state.vetting[c.id]).length
      const first = vettingIds[0] ? state.candidates[vettingIds[0]] : null
      return first
        ? t('funnel.status.vetting', { done: done + 1, total, handle: first.profile?.handle ?? first.ref.handle, step: vetStepLabel(state.vetting[first.id], lang) })
        : t('funnel.status.vettingShort', { done, total })
    }
    if (waiting.length) {
      const left = roundStat(3)?.remaining ?? waiting.length
      return vetted.length > 0 && left > waiting.length
        ? t('funnel.status.awaitVetPartial', { n: left, w: waiting.length, v: vetted.length })
        : t('funnel.status.awaitVet', { n: waiting.length })
    }
    if (roundStat(4) && vetted.length) return t('funnel.status.done', { n: vetted.length })
    if (lastFinished >= 3) return t('funnel.status.doneNoVet', { n: roundStat(3)?.remaining ?? 0 })
    return t('funnel.status.starting')
  })()

  const focusCol = (r: number) => {
    setOpenCols((o) => ({ ...o, [r]: true }))
    const grid = gridRef.current
    const el = document.getElementById(`round-${r}`)
    if (!grid || !el) return
    if (grid.scrollWidth > grid.clientWidth + 4) grid.scrollTo({ left: el.offsetLeft - 8, behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
    else if (window.innerWidth < 768) scrollToEl(el)
    el.classList.remove('flash-ring')
    void el.offsetWidth
    el.classList.add('flash-ring')
  }

  // keep the current column in view on narrow (horizontally scrolling) layouts
  useEffect(() => {
    const grid = gridRef.current
    if (!grid || grid.scrollWidth <= grid.clientWidth + 4) return
    const el = document.getElementById(`round-${currentCol}`)
    if (el) grid.scrollTo({ left: el.offsetLeft - 8 })
  }, [currentCol])

  if (!started) return <EmptyFunnel />

  const strip = [0, 1, 2, 3].filter((r) => roundStat(r))
  const laneItems = (r: number) => cols[r].lane.filter((c) => !state.dropping[c.id])
  const showAction = isPrimaryVet && waiting.length > 0

  return (
    <section id="funnel" className="panel" aria-labelledby="funnel-h">
      <div className="px-4 pt-3 pb-4 flex items-start gap-6 flex-wrap">
        <div className="flex-1 min-w-[min(100%,420px)]">
          <div className="flex items-baseline gap-4 flex-wrap">
            <h2 id="funnel-h" className="font-display text-lg font-semibold">
              {t('funnel.title')}
            </h2>
            {strip.length > 0 && (
              <div role="group" aria-label={t('funnel.stripLabel')} className="flex items-baseline gap-1 flex-wrap font-display text-lg lining">
                {strip.map((r, i) => {
                  const st = roundStat(r)!
                  return (
                    <span key={r} className="inline-flex items-baseline gap-1">
                      {i > 0 && (
                        <span className="text-ink-3 text-md" aria-hidden>
                          →
                        </span>
                      )}
                      <button
                        type="button"
                        className={`min-w-6 min-h-6 px-1 rounded-xs hover:text-accent ${r === currentCol ? 'underline decoration-2 underline-offset-4' : ''}`}
                        aria-label={t(r === 0 ? 'funnel.stripButton0' : 'funnel.stripButton', { n: r, name: t(`round.${r}` as I18nKey), count: fmtInt(st.remaining, lang) })}
                        onClick={() => focusCol(r)}
                      >
                        <Odometer value={st.remaining} />
                      </button>
                    </span>
                  )
                })}
                {roundStat(3) && vetted.length > 0 && (
                  <span className="font-sans text-sm text-ink-2 ml-1" title={staleVet ? t('funnel.earlier.title') : undefined}>
                    · {t('funnel.stripVetted', { n: vetted.length })}
                    {staleVet && ` ${t('funnel.earlier')}`}
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="mt-3">
            <Stepper states={states} running={running} />
          </div>
          <p className="mt-2 text-base text-ink-2 min-h-[21px]">
            {status}{' '}
            {emptyWhy.map((l, i) => (
              <span key={i} className="meta">
                {i > 0 && ' · '}
                {l.text}
                {(l.actor || l.mode) && ` (${[l.actor, l.mode].filter(Boolean).join(', ')})`}
              </span>
            ))}
          </p>
          {state.currentRound != null && <div className="running-bar mt-2 max-w-[420px]" aria-hidden />}
        </div>
        {showAction && (
          <div className="flex-none max-md:hidden">
            <VetAction candidates={waiting} />
          </div>
        )}
      </div>

      <div ref={gridRef} className="funnel scroll-thin">
        {[0, 1, 2, 3, 4].map((r) => {
          const stat = roundStat(r)
          const isRunning = state.currentRound === r
          const prev = roundStat(r - 1)
          const entered = stat?.entered ?? (isRunning ? prev?.remaining : undefined)
          const col = cols[r]
          const future = !stat && !isRunning && !(r === 4 && (vettingIds.length > 0 || col.active.length > 0 || roundStat(3)))
          const isCurrent = r === currentCol
          const dense = col.active.length > 12
          const open = openCols[r] ?? isCurrent
          const lane = laneItems(r)
          return (
            <div key={r} id={`round-${r}`} data-testid="round-column" data-round={r} className={`fcol ${isCurrent ? 'is-current' : ''} ${future ? 'is-future' : ''} ${open ? 'is-open' : ''}`}>
              <div className="fcol-head">
                <div className="flex items-start gap-2">
                  <h3 className="flex items-baseline gap-2 flex-1 min-w-0">
                    <span className="meta">{r}</span>
                    <span className={`font-display text-lg font-semibold ${future ? 'text-ink-3' : ''}`}>{t(`round.${r}` as I18nKey)}</span>
                  </h3>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost md:hidden"
                    aria-expanded={open}
                    aria-controls={`round-${r}-body`}
                    onClick={() => setOpenCols((o) => ({ ...o, [r]: !open }))}
                  >
                    <span className="sr-only">{t(`round.${r}` as I18nKey)}</span>
                    <span aria-hidden>{open ? '↑' : '↓'}</span>
                  </button>
                </div>
                <p className="text-sm text-ink-3 mt-1 min-h-9 max-md:min-h-0">{t(`round.${r}.what` as I18nKey)}</p>
                {future ? (
                  <p className="text-sm text-ink-3 mt-2">{t('funnel.future', { n: r - 1 })}</p>
                ) : r === 4 ? (
                  <div className="mt-2">
                    <div className="counter-label">{t('funnel.finalists')}</div>
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="counter" data-testid="round-counter" data-value={roundStat(3)?.remaining ?? undefined}>{roundStat(3) ? <Odometer value={roundStat(3)!.remaining} /> : null}</span>
                      {vetted.length > 0 && (
                        <span className="text-sm text-ink-2" title={staleVet ? t('funnel.earlier.title') : undefined}>
                          · {t('funnel.stripVetted', { n: vetted.length })}
                          {staleVet && ` ${t('funnel.earlier')}`}
                        </span>
                      )}
                    </div>
                  </div>
                ) : r === 0 ? (
                  <div className="mt-2">
                    <div className="counter-label">{t('funnel.found')}</div>
                    <div className="counter" data-testid="round-counter" data-value={stat ? stat.remaining : cands.length || undefined}>{stat ? <Odometer value={stat.remaining} /> : cands.length ? <Odometer value={cands.length} /> : null}</div>
                  </div>
                ) : (
                  <div className="flex items-end gap-2 mt-2">
                    {entered != null && (
                      <>
                        <div>
                          <div className="counter-label">{t('funnel.entered')}</div>
                          <div className="counter">
                            <Odometer value={entered} />
                          </div>
                        </div>
                        <div className="text-ink-3 text-lg pb-2" aria-hidden>
                          →
                        </div>
                      </>
                    )}
                    {stat && (
                      <div>
                        <div className="counter-label">{t('funnel.remaining')}</div>
                        <div className="counter" data-testid="round-counter" data-value={stat.remaining}>
                          <Odometer value={stat.remaining} />
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {isRunning && <div className="running-bar mt-2" aria-hidden />}
              </div>

              <div id={`round-${r}-body`} className="fcol-body">
                {(col.active.length > 0 || col.dropping.length > 0) && (
                  <div
                    className={`flex flex-col gap-2 ${dense ? 'max-h-[460px]' : 'max-h-[560px]'} overflow-y-auto scroll-thin pr-1 -mr-1`}
                    // the finalists list scrolls on its own: keyboard users need to be able to reach it
                    {...(r === 4 ? { tabIndex: 0, role: 'region', 'aria-label': t('funnel.listLabel', { n: r }) } : {})}
                  >
                    {col.active.map((c) => (
                      <CandidateCard key={c.id} c={c} dense={dense} arriving={!!state.arriving[c.id]} />
                    ))}
                    {col.dropping.map((c) => (
                      <CandidateCard key={`drop-${c.id}`} c={c} dense={dense} dropping />
                    ))}
                  </div>
                )}
                {r === 0 && col.active.length === 0 && cands.length > 0 && <FoundVia cands={cands} />}
                {r > 0 && <LaneSummary round={r} items={lane} open={openLane === r} onToggle={() => setOpenLane((v) => (v === r ? null : r))} />}
              </div>
            </div>
          )
        })}
      </div>

      {openLane != null && laneItems(openLane).length > 0 && <EliminatedPanel round={openLane} items={laneItems(openLane)} onClose={() => setOpenLane(null)} />}

      {/* phones: the step action sticks to the bottom while the funnel is on screen */}
      {showAction && (
        <div className="md:hidden sticky bottom-14 z-[5] border-t border-rule bg-paper px-4 py-3 rounded-b-md">
          <VetAction candidates={waiting} sticky />
        </div>
      )}

      <div className="sr-only" aria-live="polite" role="status">
        {announce}
      </div>
    </section>
  )
}
