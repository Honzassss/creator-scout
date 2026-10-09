import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useApp } from '../store'
import { awaitingVet, columnOf, lastFinishedRound, primaryAction, runStarted, subjectCandidate } from '../state'
import { fmtCompact, fmtInt, pick, translate, vetStepLabel, type I18nKey } from '../i18n'
import type { Candidate, Criterion, CriterionResult, Lang, ResultStatus } from '../types'
import { DUR, motionInstant, staggerStyle, useCountUp } from '../lib/motion'
import { CritIcon, Handle, MockTag, Sep, SourceChips, focusSoon, initialOf, platformLabel, platformLong, scrollToEl } from './primitives'

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

// UI strings added by the redesign (spec sections 8 to 10). They live here until the i18n owner moves them.
const TX = {
  summary: { cs: 'Souhrn výsledků', en: 'Results summary' },
  finalists: { cs: 'Finalisté po kole 3', en: 'Finalists after round 3' },
  vetting: { cs: 'Prověrka do hloubky', en: 'Deep vetting' },
  vetted: { cs: 'Prověřeno', en: 'Vetted' },
  waiting: { cs: 'Čeká na prověrku', en: 'Waiting for vetting' },
  vettingNow: { cs: 'Právě se prověřuje', en: 'Being vetted now' },
  found: { cs: 'Nalezeno', en: 'Found' },
  stillIn: { cs: 'Zůstává po kole {n}', en: 'Still in after round {n}' },
  now: { cs: 'Právě běží', en: 'Running now' },
  roundN: { cs: 'Kolo {n} · {name}', en: 'Round {n} · {name}' },
  leftOf: { cs: 'zůstalo z {n}', en: 'left of {n}' },
  entering: { cs: 'vstupuje', en: 'entering' },
  checks: { cs: 'Kontroly pro tento cíl', en: 'Checks for this goal' },
  report: { cs: 'Report', en: 'Report' },
  reportReady: { cs: 'hotový', en: 'ready' },
  reportPending: { cs: 'připravuje se', en: 'in progress' },
  waitingCard: { cs: 'Čeká na prověrku do hloubky', en: 'Waiting for deep vetting' },
  openProfile: { cs: 'Otevřít profil', en: 'Open profile' },
  finalSection: { cs: 'Finalisté', en: 'Finalists' },
  toggleRound: { cs: 'Kolo {n} {name}: {state}', en: 'Round {n} {name}: {state}' },
  vettedOf: { cs: 'prověřeno {v} z {n}', en: '{v} of {n} vetted' },
  vetProgress: { cs: 'Prověrka do hloubky: hotovo {done} z {total}', en: 'Deep vetting: {done} of {total} done' },
  vetProgressNow: { cs: 'Prověrka do hloubky: hotovo {done} z {total} · právě @{handle}', en: 'Deep vetting: {done} of {total} done · now @{handle}' },
  vetStarting: { cs: 'Prověrka do hloubky začíná…', en: 'Deep vetting is starting…' },
} satisfies Record<string, { cs: string; en: string }>

function tx(key: keyof typeof TX, lang: Lang, vars: Record<string, string | number> = {}): string {
  let s = pick(TX[key], lang)
  for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}

/** Results of the latest evaluated round for a candidate. */
function latestResults(c: Candidate, crit: Record<string, Criterion>): { round: number; results: CriterionResult[] } {
  const round = c.results.reduce((m, r) => Math.max(m, crit[r.criterion_id]?.round ?? 0), 0)
  return { round, results: c.results.filter((r) => (crit[r.criterion_id]?.round ?? 0) === round) }
}

/** One criterion result: icon + text ("does not meet: …"), the tint stays on the small icon. */
function ResultLine({ r, label }: { r: CriterionResult; label: string }) {
  const { t } = useApp()
  const key = r.waived ? 'funnel.waivedCrit' : r.status === 'fail' ? 'funnel.failsCrit' : r.status === 'pass' ? null : 'funnel.unknownCrit'
  return (
    <span className="flex items-start gap-2 text-sm text-text min-w-0">
      <span className="pt-px">
        <CritIcon status={r.status} waived={r.waived} silent />
      </span>
      {/* full text, wraps; never cut off */}
      <span className="min-w-0 [overflow-wrap:anywhere]">{key ? t(key, { name: label }) : `${t('card.pass')}: ${label}`}</span>
    </span>
  )
}

/** The results block of a card: what did not pass in the latest round, or that everything was met. */
function ResultsBlock({ c }: { c: Candidate }) {
  const { lang, t } = useApp()
  const crit = useCriteriaMap()
  const { round: lastRound, results: latest } = latestResults(c, crit)
  if (!latest.length) return null
  const issues = latest.filter((r) => r.status !== 'pass' || r.waived)
  return (
    <span className="flex flex-col gap-1.5 min-w-0">
      <Sep />
      {issues.length > 0 ? (
        issues.map((r, i) => (
          <span key={r.criterion_id} className="contents">
            {i > 0 && <Sep />}
            <ResultLine r={r} label={pick(crit[r.criterion_id]?.label ?? r.criterion_id, lang)} />
          </span>
        ))
      ) : (
        <span className="flex items-start gap-2 text-sm text-text">
          <span className="pt-px">
            <CritIcon status="pass" silent />
          </span>
          <span>{t('card.allPass', { n: lastRound })}</span>
        </span>
      )}
    </span>
  )
}

/** Platform · followers · city · restored: one wrapping meta line, separators never start a line. */
function MetaLine({ c, short, withCity }: { c: Candidate; short?: boolean; withCity?: boolean }) {
  const { state, lang, t } = useApp()
  const p = c.profile
  const mode = p?.source?.mode ?? c.ref.source?.mode
  const city = withCity && c.metrics?.local_signals?.length ? state.criteria?.brief?.city : null
  const followers = p?.followers
  return (
    <span className="meta-list text-sm text-text-2">
      <span className="meta-items">
        {mode === 'mock' && (
          <span className="mi">
            <Sep />
            <MockTag short={short} />
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
            {short ? (
              <>
                {fmtCompact(followers, lang)}
                <span className="sr-only"> {t('card.followers')}</span>
              </>
            ) : (
              t('card.followersN', { n: fmtCompact(followers, lang) })
            )}
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
  )
}

/** A candidate inside a round (rounds 0 to 3): compact, the list can hold dozens. */
function CandidateCard({
  c,
  dense,
  dropping,
  arriving,
  order = 0,
  settled,
}: {
  c: Candidate
  dense: boolean
  dropping?: boolean
  arriving?: boolean
  order?: number
  /** already on the board before this mount (it only moved to another round): no enter animation */
  settled?: boolean
}) {
  const { state, t, lang, openCandidate } = useApp()
  const p = c.profile
  const handle = p?.handle ?? c.ref.handle
  const vettingStep = state.vetting[c.id]
  const elimClass = c.status === 'eliminated' ? 'elim-id' : ''
  const cls = `ccard ${dense ? 'dense' : ''} ${dropping ? 'dropping' : ''} ${arriving ? 'arriving' : ''}`
  // A card that changes round remounts in the next column: it must not replay card-in together with
  // all the others (and with the counter). Captured once per mount; after its own intro is over the
  // card keeps animation: none, so clearing .arriving later does not start card-in again.
  const [still] = useState(() => !!settled)
  const [born] = useState(() => performance.now())
  const quiet = !dropping && !arriving && (still || performance.now() - born > DUR[3] * 2)
  const style: CSSProperties | undefined = arriving ? staggerStyle(order) : quiet ? { animation: 'none' } : undefined

  // The accessible name is composed from the visible content: @handle, MOCK, platform, followers,
  // the round result and whether a dossier exists. No aria-label with only the handle.
  if (dense)
    return (
      <button type="button" className={cls} style={style} data-testid="candidate-card" data-candidate={c.id} onClick={() => openCandidate(c.id)} tabIndex={dropping ? -1 : undefined}>
        <span className={`avatar avatar-sm ${elimClass}`} aria-hidden>
          {initialOf(handle, p?.display_name)}
        </span>
        {/* the handle keeps the full width (wraps, never cut off); MOCK and followers go on line 2 */}
        <span className="min-w-0 flex flex-col">
          <span className={`text-sm font-semibold [overflow-wrap:anywhere] ${elimClass}`} translate="no">
            <Handle handle={handle} />
          </span>
          <MetaLine c={c} short />
        </span>
      </button>
    )

  return (
    <button type="button" className={cls} style={style} data-testid="candidate-card" data-candidate={c.id} onClick={() => openCandidate(c.id)} tabIndex={dropping ? -1 : undefined}>
      <span className={`avatar ${elimClass}`} aria-hidden>
        {initialOf(handle, p?.display_name)}
      </span>
      <span className="min-w-0 flex flex-col gap-1">
        <span className={`text-base font-semibold [overflow-wrap:anywhere] ${elimClass}`} translate="no">
          <Handle handle={handle} />
        </span>
        <MetaLine c={c} short withCity />
        <ResultsBlock c={c} />
        {vettingStep && (
          <span className="flex items-center gap-2 text-sm text-text-2 min-w-0">
            <Sep />
            <span className="work-dot flex-none" aria-hidden />
            <span className="min-w-0">
              {t('funnel.vetting')}: {vetStepLabel(vettingStep, lang)}
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

/**
 * A finalist card (spec 10): white on the gray workspace, always in the same order:
 * identity (32 px avatar, @handle with the full width) -> basics (platform, followers, city)
 * -> verification results -> open the detail. No score, no stars, no "best".
 */
function FinalistCard({ c, dropping, arriving, style }: { c: Candidate; dropping?: boolean; arriving?: boolean; style?: CSSProperties }) {
  const { state, lang, t, openCandidate } = useApp()
  const p = c.profile
  const handle = p?.handle ?? c.ref.handle
  const vettingStep = state.vetting[c.id]
  const elimClass = c.status === 'eliminated' ? 'elim-id' : ''
  return (
    <li style={style} className="min-w-0 flex">
      {/* exit / enter sit on the card, not the <li>: the list's .m-stagger animation owns the <li> */}
      <button
        type="button"
        data-testid="candidate-card"
        data-candidate={c.id}
        className={`group card flex flex-col w-full min-w-0 text-left transition-colors duration-[var(--dur-1)] hover:border-field active:bg-bg ${dropping ? 'm-exit' : arriving ? 'm-enter' : ''}`}
        onClick={() => openCandidate(c.id)}
        tabIndex={dropping ? -1 : undefined}
      >
        {/* identity */}
        <span className="flex items-start gap-3 min-w-0">
          <span className={`avatar avatar-md ${elimClass}`} aria-hidden>
            {initialOf(handle, p?.display_name)}
          </span>
          <span className="min-w-0 flex-1 flex flex-col gap-0.5">
            <span className={`text-md font-semibold [overflow-wrap:anywhere] ${elimClass}`} translate="no">
              <Handle handle={handle} />
            </span>
            {/* basics */}
            <MetaLine c={c} withCity />
          </span>
        </span>
        {/* verification results (12 px under the identity) */}
        <span className="mt-3 flex flex-col gap-1.5 min-w-0">
          {vettingStep ? (
            <span className="flex items-center gap-2 text-sm text-text-2 min-w-0">
              <Sep />
              <span className="work-dot flex-none" aria-hidden />
              <span className="min-w-0">
                {t('funnel.vetting')}: {vetStepLabel(vettingStep, lang)}
              </span>
            </span>
          ) : (
            <>
              <ResultsBlock c={c} />
              {!c.report && (
                <span className="text-sm text-text-3">
                  <Sep />
                  {tx('waitingCard', lang)}
                </span>
              )}
            </>
          )}
        </span>
        {/* open the detail: always last, pinned to the bottom so a row of cards lines up */}
        <span className="mt-auto pt-3">
          <span className="card-open !mt-0 group-hover:border-accent group-hover:text-accent">
            <Sep />
            {c.report && !vettingStep ? t('funnel.openDossier') : tx('openProfile', lang)}
            <span aria-hidden>→</span>
          </span>
        </span>
      </button>
    </li>
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
      <h4 className="text-sm font-semibold text-text-2" title={t('funnel.eliminatedLane', { n: round })}>
        {t('funnel.eliminatedN', { n: items.length })}
      </h4>
      <ul role="list" className="mt-1 flex flex-col gap-1">
        {[...groups.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([id, n]) => (
            <li key={id} className="flex items-baseline gap-2 text-sm text-text-2">
              <span className="m-num text-text-3 w-8 text-right flex-none">{n}×</span>
              <span className="min-w-0">{crit[id] ? pick(crit[id].label, lang) : id}</span>
            </li>
          ))}
      </ul>
      <button type="button" data-testid="show-eliminated" className="btn btn-sm w-full mt-2" aria-expanded={open} aria-controls="elim-panel" onClick={onToggle}>
        {open ? t('funnel.hideEliminated') : t('funnel.showEliminated', { n: items.length })}
        <span aria-hidden>{open ? '↑' : '↓'}</span>
      </button>
    </div>
  )
}

/** Wide panel under the rounds: eliminated in one round, grouped by criterion, with "Restore". */
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
    <div ref={ref} id="elim-panel" data-testid="eliminated-panel" className="panel m-enter !py-4 max-h-[520px] flex flex-col" role="region" aria-labelledby="elim-h">
      <div className="flex items-center justify-between gap-3 flex-none">
        <h3 id="elim-h" className="text-sec font-semibold">
          {t('funnel.eliminatedLane', { n: round })} <span className="text-text-3 m-num font-normal">· {items.length}</span>
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
                <h4 className="text-sm font-semibold text-text-2 py-1 sticky top-0 bg-surface">
                  {label} · <span className="m-num">{list.length}</span>
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
                        <span className="flex items-start gap-2 text-sm text-text min-w-0">
                          <span className="pt-px">
                            <CritIcon status="fail" silent />
                          </span>
                          <span className="min-w-0">
                            {t('funnel.failsCrit', { name: label })}{' '}
                            <span className="text-text-3">{value.includes('(') ? `– ${value}` : `(${value})`}</span>
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
    <div>
      <h4 className="text-sm font-semibold text-text-2 mb-2">{t('funnel.foundVia')}</h4>
      <ul role="list" className="flex flex-col gap-2">
        {list.map(([v, n]) => (
          <li key={v} className="text-sm">
            <div className="flex justify-between gap-2">
              <span className="truncate text-text-2" translate="no">
                {foundViaLabel(v, lang)}
              </span>
              <span className="m-num text-text-2">{n}</span>
            </div>
            <div className="h-1 bg-line mt-1 rounded-xs overflow-hidden" aria-hidden>
              <div className="h-full bg-field origin-left" style={{ transform: `scaleX(${n / max})` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

const MAX_VET = 5

/** The step action: "Vet 5 in depth" (the one primary button), with an optional picker. */
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
        <fieldset id={pickId} className="m-enter text-left border border-line rounded-md p-2 bg-surface min-w-[220px]">
          <legend className="text-sm text-text-2 px-1">{t('funnel.vet.pickHint', { n: MAX_VET })}</legend>
          {candidates.map((c) => {
            const handle = c.profile?.handle ?? c.ref.handle
            const on = sel.includes(c.id)
            return (
              <label key={c.id} className="flex items-center gap-2 min-h-8 max-md:min-h-11 px-1 text-sm cursor-pointer rounded-xs hover:bg-bg">
                <input type="checkbox" name="vet" value={c.id} checked={on} onChange={() => toggle(c.id)} disabled={!on && sel.length >= MAX_VET} />
                <span className="truncate font-medium" translate="no">
                  @{handle}
                </span>
              </label>
            )
          })}
        </fieldset>
      )}
      {!sticky && <p className="text-sm text-text-2 max-w-[300px]">{t('funnel.vet.hint')}</p>}
    </div>
  )
}

type StepState = 'done' | 'current' | 'future'

/**
 * A counter that counts from the previous value (tabular digits, one text node). It waits for its
 * region's enter when the region has just appeared; the presentation queue already holds round.finished
 * until the leaving cards are gone, so the number moves after the eliminations have settled.
 */
/** A status line that changes at most every 2 × --dur-3 (the latest text wins), so a line that fades in
 *  is readable before it is replaced. Instant under reduced motion or in a hidden tab. */
function useSteadyText(text: string, minMs: number = DUR[3] * 2): string {
  const [shown, setShown] = useState(text)
  const last = useRef(0)
  useEffect(() => {
    if (text === shown) return
    const wait = motionInstant() ? 0 : Math.max(0, last.current + minMs - performance.now())
    const tm = window.setTimeout(() => {
      last.current = performance.now()
      setShown(text)
    }, wait)
    return () => window.clearTimeout(tm)
  }, [text, shown, minMs])
  return shown
}

function Count({ value, className = '' }: { value: number; className?: string }) {
  const { lang } = useApp()
  const born = useRef(performance.now())
  const delayMs = performance.now() - born.current < DUR[2] + 40 ? DUR[2] : 0
  const shown = useCountUp(value, { delayMs })
  return <span className={`m-num ${className}`}>{fmtInt(shown, lang)}</span>
}

/** A small text state label: running / next / done / waiting. Done is neutral, never a "pass". */
function StateTag({ st, running }: { st: StepState; running: boolean }) {
  const { t } = useApp()
  const label = st === 'done' ? t('funnel.step.done') : st === 'current' ? (running ? t('funnel.step.current') : t('funnel.step.next')) : t('funnel.step.future')
  const cls = st === 'current' ? 'tag tag-accent' : st === 'done' ? 'tag tag-neutral' : 'tag border-dashed text-text-3'
  return (
    <span key={label} className={`${cls} m-swap`}>
      {st === 'current' && running && <span className="work-dot !size-1.5" aria-hidden />}
      {label}
    </span>
  )
}

function EmptyFunnel() {
  const { state, t, setView, setChatCollapsed, composeChat } = useApp()
  const step = state.criteria ? 2 : 1
  const steps = [
    { n: 1, title: t('funnel.empty.step1'), body: t('funnel.empty.step1.body') },
    { n: 2, title: t('funnel.empty.step2'), body: t('funnel.empty.step2.body') },
    { n: 3, title: t('funnel.empty.step3'), body: t('funnel.empty.step3.body') },
  ]
  return (
    <section id="funnel" className="panel" aria-labelledby="funnel-h">
      <h2 id="funnel-h" className="text-lg font-semibold">
        {t('funnel.title')}
      </h2>
      <p className="text-base text-text-2 mt-1">{t('funnel.status.idle')}</p>
      <ol role="list" className="grid md:grid-cols-3 gap-4 mt-4">
        {steps.map((s) => (
          <li key={s.n} className="flex gap-3" aria-current={s.n === step ? 'step' : undefined}>
            <span
              className={`flex-none w-8 h-8 rounded-full inline-grid place-content-center text-md font-semibold m-num ${
                s.n < step ? 'bg-neutral text-surface' : s.n === step ? 'border-2 border-accent text-accent' : 'border border-field text-text-2'
              }`}
              aria-hidden
            >
              {s.n}
            </span>
            <span className="min-w-0">
              <span className={`block text-md font-semibold ${s.n === step ? 'text-text' : 'text-text-2'}`}>{s.title}</span>
              <span className="block text-sm text-text-2 mt-1">{s.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-6 flex items-center gap-3 flex-wrap border border-dashed border-line-strong rounded-md px-4 py-3">
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
      {/* the stages to come, in the same 2 × 2 order the results will use */}
      <ol role="list" className="grid gap-3 mt-6 min-[1000px]:grid-cols-2" aria-label={t('funnel.empty.outline')}>
        {[0, 1, 2, 3].map((r) => (
          <li key={r} className="rounded-lg border border-dashed border-line-strong px-4 py-3 min-h-[72px]">
            <span className="flex items-baseline gap-2">
              <span className="meta">{r}</span>
              <span className="text-md font-semibold text-text-2">{t(`round.${r}` as I18nKey)}</span>
            </span>
            <span className="block text-sm text-text-3 mt-0.5">{t(`round.${r}.what` as I18nKey)}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

// ---------------- results summary (spec 8): built only from existing data ----------------

function Stat({ label, value, sub, title }: { label: string; value: number | string; sub?: string; title?: string }) {
  const { lang } = useApp()
  return (
    <div className="min-w-0" title={title}>
      <div className="text-sm text-text-2">{label}</div>
      <div className={typeof value === 'number' ? 'text-num font-semibold m-num text-text' : 'text-md font-semibold text-text mt-1.5'}>{typeof value === 'number' ? fmtInt(value, lang) : value}</div>
      {sub && <div className="text-xs text-text-3">{sub}</div>}
    </div>
  )
}

function SubjectSummary() {
  const { state, lang, t } = useApp()
  const c = subjectCandidate(state)
  if (!c || !c.results.length) return null
  const counts: Record<ResultStatus, number> = { pass: 0, fail: 0, unknown: 0 }
  for (const r of c.results) counts[r.status]++
  const ready = !!c.report && !state.vetting[c.id]
  return (
    <section className="panel m-enter" aria-labelledby="sum-h">
      <h2 id="sum-h" className="sr-only">
        {tx('summary', lang)}
      </h2>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
        <div className="min-w-0">
          <div className="text-sm text-text-2">{tx('checks', lang)}</div>
          <ul role="list" className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
            {(['pass', 'fail', 'unknown'] as const).map((s) => (
              <li key={s} className="flex items-center gap-2 text-base">
                <CritIcon status={s} silent />
                <span className="text-lg font-semibold m-num">{fmtInt(counts[s], lang)}</span>
                <span className="text-text-2">{t(`card.${s}`)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0 sm:border-l sm:border-line sm:pl-8">
          <Stat label={tx('report', lang)} value={ready ? tx('reportReady', lang) : tx('reportPending', lang)} />
        </div>
      </div>
    </section>
  )
}

/** Short state of the selection at the top of the results: finalists and finished vetting kept apart. */
export function ResultsSummary() {
  const { state, t, lang } = useApp()
  if (state.mode === 'subject') return <SubjectSummary />
  if (!runStarted(state)) return null
  const cands = state.order.map((id) => state.candidates[id]).filter(Boolean)
  const roundStat = (r: number) => state.rounds.find((x) => x.round === r)
  const lastFinished = lastFinishedRound(state)
  const vetted = cands.filter((c) => c.report && c.status !== 'eliminated')
  const vettingNow = Object.keys(state.vetting).length
  const waiting = awaitingVet(state).length
  const brief = state.criteria?.brief
  const staleVet = vetted.some((c) => {
    const forGoal = c.report?.rendered_for?.business_type ?? c.report?.vetted_for
    return !!forGoal && !!brief?.business_type && forGoal !== brief.business_type
  })
  const r3 = roundStat(3)
  const found = roundStat(0)?.remaining ?? cands.length
  const running = state.currentRound != null && state.currentRound < 4 ? state.currentRound : null

  return (
    <section className="panel" aria-labelledby="sum-h">
      <h2 id="sum-h" className="sr-only">
        {tx('summary', lang)}
      </h2>
      {r3 && lastFinished >= 3 ? (
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
          <Stat label={tx('finalists', lang)} value={r3.remaining} />
          {/* finished vetting is a separate fact from the number of finalists: its own group */}
          <div role="group" aria-label={tx('vetting', lang)} className="min-w-0 flex flex-wrap gap-x-8 gap-y-3 max-sm:basis-full max-sm:border-t max-sm:pt-3 sm:border-l border-line sm:pl-8">
            <Stat label={tx('vetted', lang)} value={vetted.length} sub={staleVet ? t('funnel.earlier') : undefined} title={staleVet ? t('funnel.earlier.title') : undefined} />
            {vettingNow > 0 && <Stat label={tx('vettingNow', lang)} value={vettingNow} />}
            {waiting > 0 && <Stat label={tx('waiting', lang)} value={waiting} />}
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
          <Stat label={tx('found', lang)} value={found} />
          {lastFinished >= 1 && roundStat(lastFinished) && <Stat label={tx('stillIn', lang, { n: lastFinished })} value={roundStat(lastFinished)!.remaining} />}
          {running != null && (
            <div className="min-w-0 sm:border-l sm:border-line sm:pl-8">
              <Stat label={tx('now', lang)} value={tx('roundN', lang, { n: running, name: t(`round.${running}` as I18nKey) })} />
            </div>
          )}
        </div>
      )}
    </section>
  )
}

// ---------------- the funnel: rounds 0 to 3 in a 2 × 2 grid, finalists below ----------------

export function Funnel() {
  const { state, t, lang, demoStatus } = useApp()
  const lastCol = useRef<Record<string, number>>({})
  // ids already drawn on the board (committed renders): such a card only moves between rounds
  const seen = useRef<{ run: string | null; ids: Set<string> }>({ run: null, ids: new Set() })
  if (seen.current.run !== (state.runId ?? null)) seen.current = { run: state.runId ?? null, ids: new Set() }
  // when this board first drew each leaving card: the batch is taken out once its exit has played
  const dropSeen = useRef<Record<string, number>>({})
  const [, setDropTick] = useState(0)
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
  useEffect(
    () => () => {
      if (summary.current.timer) window.clearTimeout(summary.current.timer)
    },
    [],
  )
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

  // where each candidate sits now; leaving cards stay in their previous column while they fade out
  const cols: Record<number, { list: { c: Candidate; dropping: boolean }[]; lane: Candidate[] }> = {}
  for (let r = 0; r <= 4; r++) cols[r] = { list: [], lane: [] }
  const nextCols: Record<string, number> = {}
  for (const c of cands) {
    const col = columnOf(state, c)
    if (c.status === 'eliminated') {
      const lane = c.elimination?.round ?? 1
      cols[Math.min(Math.max(lane, 1), 4)].lane.push(c)
      if (state.dropping[c.id]) {
        const from = lastCol.current[c.id] ?? (lane === 4 ? 4 : Math.max(0, lane - 1))
        cols[from].list.push({ c, dropping: true })
        nextCols[c.id] = from
      }
    } else {
      cols[col].list.push({ c, dropping: false })
      nextCols[c.id] = col
    }
  }
  lastCol.current = { ...lastCol.current, ...nextCols }
  // A leaving card keeps its box only while its exit plays (--dur-3), then the whole batch of a column
  // goes at once (one reflow, not one per card), instead of an invisible box for ~1 s.
  const goneAfter = motionInstant() ? 0 : DUR[3] + 80
  const nowMs = performance.now()
  for (let r = 0; r <= 4; r++) {
    const drops = cols[r].list.filter((x) => x.dropping)
    if (!drops.length) continue
    let latest = 0
    for (const d of drops) latest = Math.max(latest, (dropSeen.current[d.c.id] ??= nowMs))
    if (nowMs - latest >= goneAfter) cols[r].list = cols[r].list.filter((x) => !x.dropping)
  }
  const dropKey = Object.keys(state.dropping).sort().join(',')
  useEffect(() => {
    for (const id of Object.keys(dropSeen.current)) if (!state.dropping[id]) delete dropSeen.current[id]
    if (!dropKey) return
    const tm = window.setTimeout(() => setDropTick((x) => x + 1), DUR[3] + 120)
    return () => window.clearTimeout(tm)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dropKey])
  useEffect(() => {
    for (const c of cands) seen.current.ids.add(c.id)
  })
  const activeIn = (r: number) => cols[r].list.filter((x) => !x.dropping).length

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

  // round states
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
  // vetting has run for some finalists and stopped, others still wait: "5 of 6 vetted", not "next"
  const partialVet = !!roundStat(4) && running !== 4 && vettingIds.length === 0 && vetted.length > 0 && waiting.length > 0
  // finals: round 3 is over, everyone still in is a finalist and shows in the finalists section
  const finals = lastFinished >= 3
  const liveCol = finals ? 4 : ([3, 2, 1, 0].find((r) => activeIn(r) > 0) ?? 0)
  const currentCol = state.currentRound ?? (vettingIds.length ? 4 : liveCol)

  // A finished run that found nobody: say why (the reason is otherwise only in the collapsed live log).
  const emptyRun = cands.length === 0 && state.runStatus !== 'running' && state.rounds.some((x) => x.round === 0 && x.remaining === 0)
  const emptyWhy = emptyRun ? state.log.filter((l) => l.mode || l.actor).slice(-2) : []

  // one sentence about the work going on now
  const finalistsAll = finals ? [...cols[3].list, ...cols[4].list] : []
  const status = (() => {
    if (state.recomputing) return t('funnel.status.recomputing')
    if (emptyRun) return t('funnel.status.empty')
    if (state.currentRound != null && state.currentRound < 4) return t(`round.${state.currentRound}.doing` as I18nKey)
    if (vettingIds.length || state.currentRound === 4) {
      // count over everyone vetted so far plus the ones in progress (the finalists may sit in the
      // finalists section, not in column 4, so column 4 alone undercounts: "Vetting 1 of 1" with 4 done)
      // One meaning throughout: how many have finished. The step stays on the card (it changes every
      // ~100 ms); the line changes only when a vetting finishes or another account comes first.
      const vb = state.vetBatch ?? []
      const batch = vb.length && vettingIds.every((id) => vb.includes(id)) ? vb : null
      const done = batch ? batch.filter((id) => state.vetDone?.[id] && !state.vetting[id]).length : vetted.filter((c) => !state.vetting[c.id]).length
      const total = batch ? batch.length : done + vettingIds.length
      const first = vettingIds[0] ? state.candidates[vettingIds[0]] : null
      if (!total) return tx('vetStarting', lang)
      return first
        ? tx('vetProgressNow', lang, { done: fmtInt(done, lang), total: fmtInt(total, lang), handle: first.profile?.handle ?? first.ref.handle })
        : tx('vetProgress', lang, { done: fmtInt(done, lang), total: fmtInt(total, lang) })
    }
    if (waiting.length) {
      const left = roundStat(3)?.remaining ?? waiting.length
      return vetted.length > 0 && left > waiting.length
        ? t('funnel.status.awaitVetPartial', { n: left, w: waiting.length, v: vetted.length })
        : t('funnel.status.awaitVet', { n: waiting.length })
    }
    if (roundStat(4) && vetted.length) return t('funnel.status.done', { n: vetted.length })
    if (lastFinished >= 3) return t('funnel.status.doneNoVet', { n: roundStat(3)?.remaining ?? 0 })
    // between two rounds of a running run: name the round that just finished, not "Starting the rounds…"
    if (lastFinished >= 0 && roundStat(lastFinished)) return t('funnel.status.between', { r: lastFinished, n: roundStat(lastFinished)?.remaining ?? 0 })
    return t('funnel.status.starting')
  })()

  const statusShown = useSteadyText(status)

  const focusCol = (r: number) => {
    setOpenCols((o) => ({ ...o, [r]: true }))
    const el = document.getElementById(`round-${r}`)
    if (!el) return
    scrollToEl(el, 'nearest')
    el.classList.remove('flash-ring')
    void el.offsetWidth
    el.classList.add('flash-ring')
  }

  if (!started) return <EmptyFunnel />

  const strip = [0, 1, 2, 3].filter((r) => roundStat(r))
  const laneItems = (r: number) => cols[r].lane.filter((c) => !state.dropping[c.id])
  const showAction = isPrimaryVet && waiting.length > 0
  const stateLabel = (r: number) =>
    states[r] === 'done' ? t('funnel.step.done') : states[r] === 'current' ? (running === r ? t('funnel.step.current') : t('funnel.step.next')) : t('funnel.step.future')

  return (
    <section id="funnel" className="flex flex-col gap-4 scroll-mt-4" aria-labelledby="funnel-h">
      {/* header: title, the path of counts, what is happening now, the one step action */}
      <div className="panel flex items-start gap-6 flex-wrap">
        <div className="flex-1 min-w-[min(100%,420px)]">
          <div className="flex items-baseline gap-x-4 gap-y-1 flex-wrap">
            <h2 id="funnel-h" className="text-lg font-semibold">
              {t('funnel.title')}
            </h2>
            {strip.length > 0 && (
              <div role="group" aria-label={t('funnel.stripLabel')} className="flex items-baseline gap-1 flex-wrap text-base text-text-2">
                {strip.map((r, i) => {
                  const st = roundStat(r)!
                  return (
                    <span key={r} className="inline-flex items-baseline gap-1">
                      {i > 0 && (
                        <span className="text-text-3" aria-hidden>
                          →
                        </span>
                      )}
                      <button
                        type="button"
                        className={`m-num min-w-6 min-h-6 max-md:min-h-11 max-md:min-w-11 px-1 rounded-xs hover:text-accent ${r === currentCol ? 'text-text font-semibold underline decoration-2 underline-offset-4 decoration-accent' : ''}`}
                        aria-label={t(r === 0 ? 'funnel.stripButton0' : 'funnel.stripButton', { n: r, name: t(`round.${r}` as I18nKey), count: fmtInt(st.remaining, lang) })}
                        onClick={() => focusCol(r)}
                      >
                        {fmtInt(st.remaining, lang)}
                      </button>
                    </span>
                  )
                })}
                {roundStat(3) && vetted.length > 0 && (
                  <span className="text-sm text-text-2 ml-1" title={staleVet ? t('funnel.earlier.title') : undefined}>
                    · {t('funnel.stripVetted', { n: vetted.length })}
                    {staleVet && ` ${t('funnel.earlier')}`}
                  </span>
                )}
              </div>
            )}
          </div>
          <p className="mt-2 text-base text-text-2 min-h-[22px]">
            <span key={statusShown} className="m-swap">
              {statusShown}
            </span>{' '}
            {emptyWhy.map((l, i) => (
              <span key={i} className="meta">
                {i > 0 && ' · '}
                {l.text}
                {(l.actor || l.mode) && ` (${[l.actor, l.mode].filter(Boolean).join(', ')})`}
              </span>
            ))}
          </p>
          {/* the running round card (or the vetting section) carries the one running bar */}
        </div>
        {showAction && (
          <div className="flex-none max-md:hidden">
            <VetAction candidates={waiting} />
          </div>
        )}
      </div>

      {/* rounds 0 to 3: 2 × 2 from 1000 px, stacked below */}
      <ol role="list" aria-label={t('funnel.stepper')} className="grid gap-4 items-start min-[1000px]:grid-cols-2 m-stagger">
        {[0, 1, 2, 3].map((r, idx) => {
          const stat = roundStat(r)
          const isRunning = state.currentRound === r
          const prev = roundStat(r - 1)
          const entered = stat?.entered ?? (isRunning ? prev?.remaining : undefined)
          // in the finals the survivors of round 3 are shown as finalist cards, not inside round 3
          const list = finals && r === 3 ? cols[3].list.filter((x) => x.dropping) : cols[r].list
          const future = !stat && !isRunning
          const dense = list.length > 12
          const lane = laneItems(r)
          const hasBody = list.length > 0 || (r === 0 && cands.length > 0) || lane.length > 0
          const open = hasBody && (openCols[r] ?? (r === currentCol || r === liveCol))
          const remaining = stat?.remaining ?? (r === 0 ? cands.length : undefined)
          return (
            <li
              key={r}
              id={`round-${r}`}
              data-testid="round-column"
              data-round={r}
              style={staggerStyle(idx)}
              aria-current={states[r] === 'current' ? 'step' : undefined}
              className={`relative min-w-0 rounded-lg border bg-surface ${future ? 'border-dashed border-line-strong' : 'border-line'} ${
                states[r] === 'current' ? 'shadow-[inset_3px_0_0_var(--accent),var(--shadow-1)]' : 'shadow-[var(--shadow-1)]'
              }`}
            >
              <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-x-3 min-h-[88px] py-4 pl-4 pr-2">
                <div className="min-w-0">
                  <h3 className="flex items-baseline gap-x-2 gap-y-1 flex-wrap">
                    <span className="meta m-num">{r}</span>
                    <span className={`text-md font-semibold ${future ? 'text-text-2' : ''}`}>{t(`round.${r}` as I18nKey)}</span>
                    <span className="sr-only">: </span>
                    <StateTag st={states[r]} running={running === r} />
                  </h3>
                  <p className="text-sm text-text-2 mt-1">{future ? `${t(`round.${r}.what` as I18nKey)} · ${t('funnel.future', { n: r - 1 })}` : t(`round.${r}.what` as I18nKey)}</p>
                  {isRunning && <div className="running-bar mt-3 max-w-[240px]" aria-hidden />}
                </div>
                {/* the count: the strongest element of the stage */}
                <div className="text-right min-w-[64px]">
                  {/* one Count stays mounted from "entering" to "left of": the number counts down from the
                      entered to the remaining; only the small label below swaps (keyed, opacity only) */}
                  {future || (remaining ?? entered) == null ? null : (
                    <div className="m-enter" data-testid={remaining != null ? 'round-counter' : undefined} data-value={remaining ?? undefined}>
                      <Count value={(remaining ?? entered)!} className={`block text-num font-semibold ${remaining != null ? 'text-text' : 'text-text-2'}`} />
                      {(() => {
                        const lbl =
                          remaining != null
                            ? r === 0
                              ? t('funnel.found')
                              : entered != null
                                ? tx('leftOf', lang, { n: fmtInt(entered, lang) })
                                : t('funnel.remaining')
                            : tx('entering', lang)
                        return (
                          <div key={lbl} className="text-xs text-text-2 whitespace-nowrap m-swap">
                            {lbl}
                          </div>
                        )
                      })()}
                    </div>
                  )}
                </div>
                {/* the expand control: always the same place, top right */}
                <div className="w-8 max-md:w-11">
                  {hasBody && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm !px-0 w-8 h-8 max-md:w-11 max-md:h-11 justify-center"
                      aria-expanded={open}
                      aria-controls={`round-${r}-body`}
                      aria-label={tx('toggleRound', lang, { n: r, name: t(`round.${r}` as I18nKey), state: stateLabel(r) })}
                      onClick={() => setOpenCols((o) => ({ ...o, [r]: !open }))}
                    >
                      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden className={`transition-transform duration-[var(--dur-2)] ${open ? 'rotate-180' : ''}`}>
                        <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              {open && (
                <div id={`round-${r}-body`} className="m-enter border-t border-line px-4 pt-3 pb-4"
                  // opened by the run (not by a click): enters after the counter has counted, not with it
                  style={openCols[r] === undefined ? { animationDelay: 'var(--dur-3)' } : undefined}>
                  {list.length > 0 && (
                    <div className={`flex flex-col gap-2 ${dense ? 'max-h-[440px]' : 'max-h-[520px]'} overflow-y-auto scroll-thin pr-1 -mr-1`}
                      // a long list scrolls on its own: keyboard users need to be able to reach it
                      {...(list.length > 8 ? { tabIndex: 0, role: 'region', 'aria-label': t('funnel.listLabel', { n: r }) } : {})}
                    >
                      {(() => {
                        // cards arriving together enter one after another (index within the new batch, capped at 8)
                        let k = 0
                        return list.map(({ c, dropping }) => {
                          const arriving = !dropping && !!state.arriving[c.id]
                          return <CandidateCard key={c.id} c={c} dense={dense} dropping={dropping} arriving={arriving} order={arriving ? k++ : 0} settled={seen.current.ids.has(c.id)} />
                        })
                      })()}
                    </div>
                  )}
                  {r === 0 && list.length === 0 && cands.length > 0 && <FoundVia cands={cands} />}
                  {r > 0 && <LaneSummary round={r} items={lane} open={openLane === r} onToggle={() => setOpenLane((v) => (v === r ? null : r))} />}
                </div>
              )}
            </li>
          )
        })}
      </ol>

      {openLane != null && laneItems(openLane).length > 0 && <EliminatedPanel round={openLane} items={laneItems(openLane)} onClose={() => setOpenLane(null)} />}

      {/* stage 4: the finalists. The soft green sits in this header only; the cards are white on gray. */}
      <section id="round-4" data-testid="round-column" data-round={4} aria-labelledby="final-h" aria-current={states[4] === 'current' ? 'step' : undefined} className="flex flex-col gap-3 min-w-0">
        <div
          className={`rounded-lg border px-4 md:px-6 py-4 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 items-start ${
            finals ? 'bg-accent-tint border-transparent' : 'bg-surface border-dashed border-line-strong'
          } ${states[4] === 'current' ? 'shadow-[inset_3px_0_0_var(--accent)]' : ''}`}
        >
          <div className="min-w-0">
            <h3 id="final-h" className="flex items-baseline gap-x-2 gap-y-1 flex-wrap">
              <span className={`meta m-num ${finals ? '!text-text-2' : ''}`}>4</span>
              <span className={`text-md font-semibold ${finals ? '' : 'text-text-2'}`}>
                {tx('finalSection', lang)} · {t('round.4')}
              </span>
              <span className="sr-only">: </span>
              {partialVet ? (
                <span className="tag tag-neutral m-swap">{tx('vettedOf', lang, { v: fmtInt(vetted.length, lang), n: fmtInt(vetted.length + waiting.length, lang) })}</span>
              ) : (
                <StateTag st={states[4]} running={running === 4} />
              )}
            </h3>
            <p className="text-sm text-text-2 mt-1">{finals ? t('round.4.what') : `${t('round.4.what')} · ${t('funnel.future', { n: 3 })}`}</p>
            {running === 4 && <div className="running-bar mt-3 max-w-[240px]" aria-hidden />}
          </div>
          {finals && roundStat(3) && (
            <div className="text-right" data-testid="round-counter" data-value={roundStat(3)!.remaining}>
              <div className="text-num font-semibold m-num">{fmtInt(roundStat(3)!.remaining, lang)}</div>
              <div className="text-xs text-text-2">{t('funnel.finalists')}</div>
            </div>
          )}
        </div>
        {finalistsAll.length > 0 && (
          <div className="@container min-w-0">
            <ul role="list" aria-label={t('funnel.listLabel', { n: 4 })} className="grid gap-3 grid-cols-1 @lg:grid-cols-2 @3xl:grid-cols-3 m-stagger">
              {cands
                .filter((c) => finalistsAll.some((x) => x.c.id === c.id))
                .map((c, i) => {
                  const dropping = !!finalistsAll.find((x) => x.c.id === c.id)?.dropping
                  return <FinalistCard key={c.id} c={c} dropping={dropping} arriving={!dropping && !!state.arriving[c.id]} style={staggerStyle(i)} />
                })}
            </ul>
          </div>
        )}
        {laneItems(4).length > 0 && (
          <div className="panel !py-3">
            <LaneSummary round={4} items={laneItems(4)} open={openLane === 4} onToggle={() => setOpenLane((v) => (v === 4 ? null : 4))} />
          </div>
        )}
      </section>

      {/* phones: the step action sticks to the bottom while the funnel is on screen */}
      {showAction && (
        <div className="md:hidden sticky bottom-14 z-[5] border border-line bg-surface px-4 py-3 rounded-lg shadow-[var(--shadow-1)]">
          <VetAction candidates={waiting} sticky />
        </div>
      )}

      <div className="sr-only" aria-live="polite" role="status">
        {announce}
      </div>
    </section>
  )
}
