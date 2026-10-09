// Subject mode board (docs/subject-mode.md): ONE named creator, checked for the owner's goal.
// The criteria are checks (✓ ✕ ?), nothing is eliminated, there is no score. The report is shown inline,
// ordered for the current goal, and a one-click goal switch shows what changed in the report.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useApp } from '../store'
import { subjectCandidate } from '../state'
import { fmtCompact, fmtDate, pick, vetStepLabel, type I18nKey } from '../i18n'
import { anchorText } from '../lib/subject'
import { PRESET_NAMES, presetOf, type PresetName } from '../lib/presets'
import type { Candidate, Criterion, CriterionResult, Finding, I18nText, Report, ResultStatus } from '../types'
import { CardBody, NewsList, Outreach } from './CandidateDrawer'
import { CritIcon, MockTag, ModeBadge, RichText, SourceChip, SourceChips, initialOf, platformLabel, platformLong } from './primitives'
import { ConfidenceTag, MethodPanel, RankedFindings, SummaryLine, VerdictBlock, goalLabel, itemDomId, jumpToItem } from './Report'
import { SubjectEntry } from './SubjectEntry'
import { useCriteriaMap } from './Funnel'

// ---------------- header: who, anchor, progress ----------------

type StepState = 'done' | 'current' | 'future' | 'stopped'

function useSubjectProgress() {
  const { state, t, lang } = useApp()
  const c = subjectCandidate(state)
  const vetStep = c ? state.vetting[c.id] : undefined
  const rounds = new Set(state.rounds.map((r) => r.round))
  const resolved = state.subject?.status === 'resolved' || !!c
  const checksDone = rounds.has(3)
  const vetDone = !!c?.report && !vetStep
  const notFound = state.subject?.status === 'not_found'
  let states: StepState[] = [
    resolved ? 'done' : 'current',
    checksDone ? 'done' : resolved ? 'current' : 'future',
    vetDone ? 'done' : checksDone ? 'current' : 'future',
    vetDone ? 'done' : 'future',
  ]
  // not found / interrupted: the step that was running ends without a result, nothing runs any more
  if (notFound) states = ['stopped', 'future', 'future', 'future']
  else if (state.interrupted && !vetDone) states = states.map((s) => (s === 'current' ? 'stopped' : s))
  const running = state.runStatus === 'running' && !vetDone && !notFound && !state.interrupted
  let status: string
  if (state.recomputing) status = t('subject.status.recomputing')
  else if (notFound) status = t(offlineSource(state.health?.source_mode) ? 'subject.notFound.titleOffline' : 'subject.notFound.title')
  else if (state.interrupted && !vetDone) status = t('subject.interrupted.title')
  else if (!resolved) status = t('subject.status.pending')
  else if (state.currentRound != null && state.currentRound < 4) status = t('subject.status.checks', { n: state.currentRound })
  else if (vetStep) status = t('subject.status.vetting', { step: vetStepLabel(vetStep, lang) })
  else if (!vetDone && checksDone) status = t('subject.status.vettingStart')
  else if (vetDone) status = t('subject.status.ready')
  else status = t('subject.status.pending')
  return { states, running, status, vetDone }
}

function Steps({ states, running }: { states: StepState[]; running: boolean }) {
  const { t } = useApp()
  const labels: I18nKey[] = ['subject.step.resolve', 'subject.step.checks', 'subject.step.vetting', 'subject.step.report']
  return (
    <ol className="stepper" aria-label={t('subject.steps')}>
      {states.map((st, i) => (
        <li key={i} className={`is-${st} ${running && st === 'current' ? 'is-running' : ''}`} aria-current={st === 'current' || st === 'stopped' ? 'step' : undefined}>
          <span className="step-dot" aria-hidden>
            {st === 'done' ? '✓' : st === 'stopped' ? '✕' : ''}
          </span>
          <span className="step-label">
            {t(labels[i])}
            <span className="sr-only">
              : {st === 'done' ? t('funnel.step.done') : st === 'stopped' ? t('subject.step.stopped') : st === 'current' ? t('funnel.step.current') : t('funnel.step.future')}
            </span>
          </span>
          {i < states.length - 1 && <span className="step-line" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

function SubjectHeader({ c }: { c: Candidate | null }) {
  const { state, t, lang } = useApp()
  const { states, running, status } = useSubjectProgress()
  const p = c?.profile
  const handle = p?.handle ?? c?.ref.handle ?? state.subject?.handle ?? '–'
  const platform = c?.ref.platform ?? state.subject?.platform ?? null
  const mode = p?.source?.mode ?? c?.ref.source?.mode
  const fetched = p?.source?.fetched_at
  const anchor = anchorText(state.subject?.anchor, lang)
  return (
    <div className="px-4 pt-4 pb-3 border-b border-rule">
      <div className="flex items-start gap-4 flex-wrap">
        <span className="avatar avatar-lg" aria-hidden>
          {initialOf(handle, p?.display_name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-x-3 gap-y-1 flex-wrap">
            <span className="smallcaps">{t('subject.title')}</span>
            {mode === 'mock' && <span className="mock-stamp">MOCK</span>}
            {mode === 'cache' && <span className="cache-stamp">{t('cache.tag')}</span>}
          </div>
          <h2 id="subject-h" tabIndex={-1} className="text-xl font-semibold tracking-tight [overflow-wrap:anywhere]" translate="no">
            @{handle}
          </h2>
          <div className="mt-1 flex items-center gap-x-2 gap-y-1 flex-wrap text-base text-ink-2">
            {p?.display_name && <span translate="no">{p.display_name}</span>}
            {platform && (
              <>
                {p?.display_name && <span aria-hidden>·</span>}
                <span>{platformLong(platform, t)}</span>
              </>
            )}
            {p?.followers != null && (
              <>
                <span aria-hidden>·</span>
                <span>{t('card.followersN', { n: fmtCompact(p.followers, lang) })}</span>
              </>
            )}
            {fetched && (
              <>
                <span aria-hidden>·</span>
                <span>{t('drawer.fetched', { date: fmtDate(fetched, lang) })}</span>
              </>
            )}
            {p?.source && <SourceChip src={p.source} />}
            {mode && mode !== 'mock' && <ModeBadge mode={mode} />}
          </div>
          <p className="mt-1 text-sm">
            <span className="smallcaps mr-2">{t('subject.anchor')}</span>
            <span className={anchor ? 'text-ink' : 'text-ink-2 italic'}>{anchor || t('subject.anchor.missing')}</span>
          </p>
        </div>
      </div>
      <div className="mt-3">
        <Steps states={states} running={running} />
      </div>
      <p className="mt-2 text-base text-ink-2 flex items-center gap-2 min-h-[21px]" role="status" aria-live="polite">
        {(running || state.recomputing) && <span className="work-dot" aria-hidden />}
        {status}
      </p>
      {(running || state.recomputing) && <div className="running-bar mt-2 max-w-[420px]" aria-hidden />}
    </div>
  )
}

// ---------------- goal bar: one-click switch ----------------

function GoalBar({ report }: { report: Report | null | undefined }) {
  const { state, t, actions, composeChat } = useApp()
  const brief = state.criteria?.brief
  const current: PresetName | null = presetOf(report?.rendered_for ? { business_type: report.rendered_for.business_type ?? '', city: null, audience: '', goal: '', budget_hint: null, competitors: [] } : brief)
  const busy = state.recomputing || state.runStatus === 'running' || !report
  const hintId = 'subj-goal-hint'
  return (
    <div className="px-4 py-3 border-b border-rule bg-paper-2/50 flex items-center gap-x-4 gap-y-2 flex-wrap">
      <h3 id="subj-goal-h" tabIndex={-1} className="font-display text-lg font-semibold mr-auto">
        {t('report.for', { goal: goalLabel(report, brief, t) })}
      </h3>
      <div className="flex items-center gap-2 flex-wrap">
        <div className="seg" role="group" aria-label={t('report.goal.label')} data-testid="goal-toggle">
          {PRESET_NAMES.map((k) => (
            <button
              key={k}
              type="button"
              data-testid={`goal-${k}`}
              aria-pressed={current === k}
              aria-disabled={busy || undefined}
              aria-describedby={busy ? hintId : undefined}
              onClick={() => {
                if (busy || current === k) return
                actions.switchGoal(k)
              }}
            >
              {t(k === 'fitness' ? 'goal.preset.fitness' : 'goal.preset.bakery')}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn-sm btn-ghost" title={t('report.goal.otherTitle')} onClick={() => composeChat(t('report.goal.otherDraft'))}>
          {t('report.goal.other')} <span aria-hidden>→</span>
        </button>
      </div>
      <p id={hintId} className="basis-full text-sm text-ink-2">
        {busy ? t(state.recomputing ? 'subject.status.recomputing' : 'report.goal.busy') : t('report.goal.hint')}
      </p>
      {report && <ReportLegend />}
    </div>
  )
}

/** One line under the goal bar: what the evidence colours mean, and a jump to "How this report was built". */
function ReportLegend() {
  const { t } = useApp()
  return (
    <p className="basis-full text-sm flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <span>
        <span className="kind-label kind-fact">{t('drawer.legend.fact')}</span> <span className="text-ink-2">{t('report.legend.fact')}</span>
      </span>
      <span>
        <span className="kind-label kind-inference">{t('drawer.legend.inference')}</span> <span className="text-ink-2">{t('report.legend.inference')}</span>
      </span>
      <span>
        <span className="kind-label kind-gap">{t('drawer.legend.gap')}</span> <span className="text-ink-2">{t('report.legend.gap')}</span>
      </span>
      <a
        href="#subj-method"
        className="btn-link text-sm ml-auto whitespace-nowrap"
        onClick={(e) => {
          e.preventDefault()
          const el = document.getElementById('subj-method')
          if (!el) return
          el.scrollIntoView({ block: 'start', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
          el.focus({ preventScroll: true })
        }}
      >
        {t('report.method')} <span aria-hidden>↓</span>
      </a>
    </p>
  )
}

// ---------------- what changed after a goal switch ----------------

const TIER_KEY: Record<string, I18nKey> = { key: 'report.tier.key', related: 'report.tier.related', less: 'report.tier.less' }

function ChangeGroup({ title, mark, children, n }: { title: string; mark: string; children: ReactNode; n: number }) {
  if (!n) return null
  return (
    <div className="min-w-0">
      <h4 className="flex items-baseline gap-2">
        <span className="num text-md text-ink-2 w-4 text-center" aria-hidden>
          {mark}
        </span>
        <span className="text-base font-semibold">{title}</span>
        <span className="tnum text-ink-2">{n}</span>
      </h4>
      <ul role="list" className="mt-1 ml-6 flex flex-col gap-2">
        {children}
      </ul>
    </div>
  )
}

function WhatChanged({ c }: { c: Candidate }) {
  const { state, t, lang, dispatch } = useApp()
  const crit = useCriteriaMap()
  const rd = state.reportDiff
  const ref = useRef<HTMLElement>(null)
  const report = c.report
  // after a goal switch, bring the panel into view (it sits right under the goal bar)
  useEffect(() => {
    if (rd && !rd.hidden) ref.current?.scrollIntoView({ block: 'nearest', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }, [rd?.at]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!rd || rd.candidateId !== c.id || rd.hidden) return null
  const d = rd.diff
  const now = new Map<string, Finding>((report?.findings ?? []).map((f) => [f.id, f]))
  const before = new Map<string, Finding>((rd.before?.findings ?? []).map((f) => [f.id, f]))
  const claimNow = new Map((report?.claims ?? []).map((k) => [k.id, k]))
  const claimBefore = new Map((rd.before?.claims ?? []).map((k) => [k.id, k]))
  const tierOf = (m: Map<string, Finding>, id: string) => m.get(id)?.tier ?? claimNow.get(id)?.tier ?? claimBefore.get(id)?.tier ?? null
  const text = (id: string, from: 'now' | 'before') => {
    const f = (from === 'now' ? now : before).get(id) ?? (from === 'now' ? before : now).get(id)
    if (f) return pick(f.text, lang)
    const k = claimNow.get(id) ?? claimBefore.get(id)
    return k ? (lang === 'cs' ? `„${k.claim}“` : `“${k.claim}”`) : t('changed.gone')
  }
  const tierWord = (x: string | null | undefined) => (x ? t(TIER_KEY[x] ?? 'report.tier.related') : '–')
  const goalWord = (g: Record<string, string>) => g?.business_type ?? '–'
  const ItemRow = ({ id, from, extra, show = true }: { id: string; from: 'now' | 'before'; extra?: ReactNode; show?: boolean }) => (
    <li className="text-sm">
      <RichText text={text(id, from)} />
      {extra && <span className="text-ink-2"> · {extra}</span>}
      {show && (now.has(id) || claimNow.has(id)) && (
        <>
          {' '}
          <button type="button" className="btn-link !min-h-0 text-sm" aria-label={t('changed.showNamed', { text: text(id, from) })} onClick={() => jumpToItem(id, 'subj')}>
            {t('changed.show')} <span aria-hidden>→</span>
          </button>
        </>
      )}
    </li>
  )
  const statusWord = (s: string | null | undefined) => (s ? t(`report.status.${s}` as I18nKey) : '–')
  const checkWord = (s: ResultStatus | null) => (s ? `${s === 'pass' ? '✓' : s === 'fail' ? '✕' : '?'} ${t(`card.${s}`)}` : '–')
  const movedUp = (d.moved_up ?? []).filter((id) => !claimNow.has(id))
  // an item both moved down and collapsed is listed once, under "collapsed"
  const collapsedSet = new Set(d.collapsed ?? [])
  const movedDown = (d.moved_down ?? []).filter((id) => !claimNow.has(id) && !collapsedSet.has(id))
  const qa = d.questions_added ?? []
  const qr = d.questions_removed ?? []
  return (
    <section ref={ref} id="what-changed" className="changed mx-4 mt-4" aria-labelledby="changed-h" data-testid="what-changed">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-[220px]">
          <h3 id="changed-h" className="font-display text-lg font-semibold">
            {t('changed.title')}
            <span className="sr-only">: {t('changed.fromTo', { a: goalWord(d.from_goal), b: goalWord(d.to_goal) })}</span>
            <span aria-hidden>
              : <s className="text-ink-2 decoration-1">{goalWord(d.from_goal)}</s> → {goalWord(d.to_goal)}
            </span>
          </h3>
          <p className="text-base mt-1">
            <RichText text={pick(d.summary, lang)} />
          </p>
        </div>
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={() => {
            // this panel unmounts: hand focus to the goal bar heading first
            document.getElementById('subj-goal-h')?.focus({ preventScroll: true })
            dispatch({ type: 'reportDiff.dismiss' })
          }}
        >
          {t('changed.dismiss')}
        </button>
      </div>
      <div className="grid gap-4 mt-3 md:grid-cols-2">
        <ChangeGroup title={t('changed.movedUp')} mark="↑" n={movedUp.length}>
          {movedUp.map((id) => (
            <ItemRow key={id} id={id} from="now" extra={`${tierWord(tierOf(before, id))} → ${tierWord(tierOf(now, id))}`} />
          ))}
        </ChangeGroup>
        <ChangeGroup title={t('changed.added')} mark="+" n={d.added?.length ?? 0}>
          {(d.added ?? []).map((id) => (
            <ItemRow key={id} id={id} from="now" extra={tierWord(tierOf(now, id))} />
          ))}
        </ChangeGroup>
        <ChangeGroup title={t('changed.movedDown')} mark="↓" n={movedDown.length}>
          {movedDown.map((id) => (
            <ItemRow key={id} id={id} from="now" extra={`${tierWord(tierOf(before, id))} → ${tierWord(tierOf(now, id))}`} />
          ))}
        </ChangeGroup>
        <ChangeGroup title={t('changed.removed')} mark="−" n={d.removed?.length ?? 0}>
          {(d.removed ?? []).map((id) => (
            <ItemRow key={id} id={id} from="before" show={false} />
          ))}
        </ChangeGroup>
        <ChangeGroup title={t('changed.collapsed')} mark="▾" n={d.collapsed?.length ?? 0}>
          {(d.collapsed ?? []).map((id) => (
            <ItemRow key={id} id={id} from="now" />
          ))}
        </ChangeGroup>
        <ChangeGroup title={t('changed.claims')} mark="~" n={d.claims_changed?.length ?? 0}>
          {(d.claims_changed ?? []).map((ch) => {
            const sameStatus = !ch.status || ch.status[0] === ch.status[1]
            return (
              <li key={ch.id} className="text-sm">
                <RichText text={text(ch.id, 'now')} />
                <span className="block text-ink-2">
                  {ch.tier && ch.tier[0] !== ch.tier[1] && <>{t('changed.claim.tier', { a: tierWord(ch.tier[0]), b: tierWord(ch.tier[1]) })} · </>}
                  {sameStatus ? t('changed.claim.sameStatus') : t('changed.claim.status', { a: statusWord(ch.status![0]), b: statusWord(ch.status![1]) })}
                </span>
                {claimNow.has(ch.id) && (
                  <button type="button" className="btn-link !min-h-0 text-sm" aria-label={t('changed.showNamed', { text: text(ch.id, 'now') })} onClick={() => jumpToItem(ch.id, 'subj')}>
                    {t('changed.show')} <span aria-hidden>→</span>
                  </button>
                )}
              </li>
            )
          })}
        </ChangeGroup>
        <ChangeGroup title={t('changed.checks')} mark="~" n={d.checks_changed?.length ?? 0}>
          {(d.checks_changed ?? []).map((ch) => (
            <li key={ch.criterion_id} className="text-sm">
              <span className="font-medium">{crit[ch.criterion_id] ? pick(crit[ch.criterion_id].label, lang) : ch.criterion_id}</span>
              <span className="text-ink-2">
                {' '}
                {checkWord(ch.status[0])} → {checkWord(ch.status[1])}
              </span>
            </li>
          ))}
        </ChangeGroup>
        <ChangeGroup title={t('changed.questions')} mark="?" n={qa.length + qr.length}>
          {qa.map((q, i) => (
            <li key={`a${i}`} className="text-sm">
              <span className="num text-ink-2 mr-1" aria-hidden>
                +
              </span>
              <span className="sr-only">{t('changed.addedSr')} </span>
              <RichText text={pick(q, lang)} />
            </li>
          ))}
          {qr.map((q, i) => (
            <li key={`r${i}`} className="text-sm text-ink-2">
              <span className="num mr-1" aria-hidden>
                −
              </span>
              <span className="sr-only">{t('changed.removedSr')} </span>
              <s className="decoration-1">
                <RichText text={pick(q, lang)} />
              </s>
            </li>
          ))}
        </ChangeGroup>
      </div>
      {d.outreach_changed && (
        <p className="mt-3 text-sm">
          {t('changed.outreach')}{' '}
          <a
            href="#subj-outreach"
            className="btn-link text-sm"
            onClick={(e) => {
              e.preventDefault()
              const el = document.getElementById('subj-outreach')
              el?.scrollIntoView({ block: 'start', behavior: 'smooth' })
              el?.focus({ preventScroll: true })
            }}
          >
            {t('changed.show')} <span aria-hidden>→</span>
          </a>
        </p>
      )}
      <p className="mt-3 text-sm text-ink-2 italic">{t('changed.noFetch')}</p>
    </section>
  )
}

// ---------------- the checklist: criteria as checks, nothing eliminated ----------------

function ChecksList({ c, report }: { c: Candidate | null; report: Report | null | undefined }) {
  const { state, t, lang } = useApp()
  const crit = useCriteriaMap()
  const changed = useMemo(() => {
    const m = new Map<string, [ResultStatus | null, ResultStatus | null]>()
    if (state.reportDiff && c && state.reportDiff.candidateId === c.id) for (const ch of state.reportDiff.diff.checks_changed ?? []) m.set(ch.criterion_id, ch.status)
    return m
  }, [state.reportDiff, c])
  const checkFinding = useMemo(() => {
    const m = new Map<string, Finding>()
    for (const f of report?.findings ?? []) if (f.section === 'goal' || /^[fg]:check:/.test(f.id)) for (const r of f.relevance ?? [f.id.replace(/^[fg]:check:/, '')]) m.set(r, f)
    return m
  }, [report])
  const results = c?.results ?? []
  const counts: Record<ResultStatus, number> = { pass: 0, fail: 0, unknown: 0 }
  for (const r of results) counts[r.status]++
  const byRound = new Map<number, CriterionResult[]>()
  for (const r of results) {
    const round = crit[r.criterion_id]?.round ?? 0
    byRound.set(round, [...(byRound.get(round) ?? []), r])
  }
  const enabled = (state.criteria?.criteria ?? []).filter((x) => x.enabled)
  const rounds = [...new Set(enabled.map((x) => x.round))].sort((a, b) => a - b)
  // a goal finding can cover several checks: only its first row carries the finding's id ("Show" target)
  const anchored = new Set<string>()
  const anchorFor = (f?: Finding) => (f && !anchored.has(f.id) ? (anchored.add(f.id), true) : false)
  return (
    <section className="checks" aria-labelledby="checks-h">
      <h3 id="checks-h" className="font-display text-lg font-semibold">
        {t('subject.checks.title')}
      </h3>
      {results.length > 0 && <p className="text-sm text-ink-2 mt-1 tnum">{t('subject.checks.counts', { pass: counts.pass, fail: counts.fail, unknown: counts.unknown })}</p>}
      <p className="text-sm text-ink-2 italic mt-1">{t('subject.noElim')}</p>
      {results.length === 0 && <p className="text-base text-ink-2 mt-3">{t('subject.checks.wait')}</p>}
      {rounds.map((round) => {
        const rs = byRound.get(round) ?? []
        const pending = enabled.filter((x) => x.round === round && !rs.some((r) => r.criterion_id === x.id))
        if (!rs.length && !pending.length) return null
        return (
          <div key={round} className="mt-3">
            <h4 className="smallcaps !text-ink-2">
              {t('criteria.round', { n: round })} · {t(`round.${round}` as I18nKey)}
            </h4>
            <ul role="list" className="mt-1">
              {rs.map((r) => (
                <CheckRow key={r.criterion_id} r={r} cr={crit[r.criterion_id]} change={changed.get(r.criterion_id)} f={checkFinding.get(r.criterion_id)} anchor={anchorFor(checkFinding.get(r.criterion_id))} />
              ))}
              {results.length > 0 &&
                pending.map((x) => (
                  <li key={x.id} className="check-row text-ink-3">
                    <span className="crit-mark" aria-hidden>
                      ·
                    </span>
                    <span className="text-sm">
                      {pick(x.label, lang)}
                      <span className="sr-only">: {t('subject.checks.pending')}</span>
                    </span>
                    <span />
                  </li>
                ))}
            </ul>
          </div>
        )
      })}
    </section>
  )
}

function CheckRow({ r, cr, change, f, anchor }: { r: CriterionResult; cr?: Criterion; change?: [ResultStatus | null, ResultStatus | null]; f?: Finding; anchor?: boolean }) {
  const { t, lang } = useApp()
  const label = cr ? pick(cr.label, lang) : r.criterion_id
  const word = (s: ResultStatus | null) => (s ? t(`card.${s}`) : '–')
  const value = pick(r.value, lang)
  const threshold = pick(r.threshold, lang)
  const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
  // "Public account: public account · required: public account" says nothing three times
  const showValue = !!value && !same(value, label)
  const showThreshold = !!threshold && !same(threshold, value)
  return (
    <li id={f && anchor ? itemDomId('subj', f.id) : undefined} tabIndex={f && anchor ? -1 : undefined} className={`check-row scroll-mt-16 ${change ? 'is-changed' : ''}`}>
      <CritIcon status={r.status} waived={r.waived} label={label} />
      <div className="min-w-0">
        <div className="text-base leading-snug">
          {label}
          {change && (
            <>
              <span className="changed-tag" title={t('subject.checks.changedTitle', { a: word(change[0]), b: word(change[1]) })}>
                {t('subject.checks.changed')}
              </span>
              <span className="text-sm text-ink-2 ml-1">
                <span className="sr-only">: </span>
                {word(change[0])} → {word(change[1])}
              </span>
            </>
          )}
        </div>
        {(showValue || showThreshold) && (
          <div className="text-sm text-ink-2">
            {showValue && <RichText text={value} />}
            {showThreshold && (
              <span className="text-ink-3">
                {showValue && ' · '}
                {t('card.threshold')}: {threshold}
              </span>
            )}
          </div>
        )}
        {f?.confidence && (
          <div className="mt-1">
            <ConfidenceTag level={f.confidence} basis={f.confidence_basis} compact />
          </div>
        )}
      </div>
      <span className="flex gap-1 flex-wrap justify-end">
        <SourceChips sources={r.sources} />
      </span>
    </li>
  )
}

// ---------------- not found ----------------

/** MOCK data and the cache replay fetch nothing, so "not found" there means "not in the offline data". */
export function offlineSource(mode: string | null | undefined): boolean {
  const m = (mode ?? '').toLowerCase()
  return m === 'mock' || m === 'cache'
}

function NotFound() {
  const { state, t, lang } = useApp()
  const nf = state.subjectNotFound
  const h = state.subject?.handle ?? nf?.subject?.replace(/^@/, '') ?? '–'
  const tried = (nf?.tried ?? []).map((p) => platformLabel(p, t)).join(', ') || t('subject.notFound.triedAll')
  // MOCK / cache replay never looks anything up: the backend's reason says so, never "we searched"
  const body = nf?.reason
    ? pick(nf.reason as I18nText, lang)
    : offlineSource(state.health?.source_mode)
      ? t('subject.notFound.offlineBody', { h })
      : t('subject.notFound.body', { h, tried })
  return (
    <div className="px-4 py-5" data-testid="subject-not-found">
      {/* the stepper status line above already says "Profile not found": here what was tried and what next */}
      <p className="text-base">{body}</p>
      <div className="mt-4 max-w-[520px]">
        <SubjectEntry initialSubject={`@${h}`} initialAnchor={state.subject?.anchor} title={t('subject.notFound.retry')} />
      </div>
    </div>
  )
}

/** The server stopped while this check was running: say so and offer the same check again. */
function Interrupted() {
  const { state, t, actions, reveal } = useApp()
  const [busy, setBusy] = useState(false)
  const subj = state.subject
  if (!subj) return null
  const preset = presetOf(state.criteria?.brief) ?? 'bakery'
  return (
    <div className="mx-4 mt-4 border border-dashed border-ink-2 rounded-sm px-4 py-3" role="alert">
      <p className="text-base">{t('subject.interrupted.body')}</p>
      <button
        type="button"
        className="btn btn-primary btn-sm mt-3"
        aria-disabled={busy || undefined}
        onClick={async () => {
          if (busy) return
          setBusy(true)
          try {
            await actions.researchSubject({ subject: subj.raw || `@${subj.handle}`, anchor: subj.anchor ?? null, preset, competitors: state.criteria?.brief?.competitors })
            reveal('subject', 'subject-h')
          } catch {
            /* the store shows the error */
          } finally {
            setBusy(false)
          }
        }}
      >
        {t('subject.interrupted.retry')} <span aria-hidden>→</span>
      </button>
    </div>
  )
}

// ---------------- the board ----------------

export function SubjectBoard() {
  const { state, t, lang } = useApp()
  const c = subjectCandidate(state)
  const crit = useCriteriaMap()
  const report = c?.report ?? null
  const notFound = state.subject?.status === 'not_found'
  return (
    <section id="subject" className="panel subject-wrap" aria-labelledby="subject-h" data-testid="subject-board">
      <SubjectHeader c={c} />
      {notFound ? (
        <NotFound />
      ) : (
        <>
          {state.interrupted && !report && <Interrupted />}
          <GoalBar report={report} />
          {c && <WhatChanged c={c} />}
          <div className="subject-grid px-4 pt-4 pb-6">
            <div className="[grid-area:verdict] min-w-0 flex flex-col gap-4">
              {report ? (
                <>
                  <VerdictBlock report={report} idPrefix="subj" />
                  <SummaryLine report={report} />
                </>
              ) : (
                <p className="text-base text-ink-2 italic">{t('subject.reportWait')}</p>
              )}
            </div>
            <div className="checks-col [grid-area:checks] min-w-0">
              <div className="checks-sticky">
                <ChecksList c={c} report={report} />
                {c?.profile && (
                  <details className="disclosure mt-4">
                    <summary>{t('subject.profile')}</summary>
                    <div className="mt-2">
                      <CardBody c={c} crit={crit} noCriteria />
                    </div>
                  </details>
                )}
              </div>
            </div>
            {report && (
              <div className="[grid-area:report] min-w-0 flex flex-col gap-8">
                <div>
                  <h3 className="dossier-h mb-3">{t('report.ranked')}</h3>
                  <RankedFindings report={report} skipGoal idPrefix="subj" />
                </div>
                {report.news.length > 0 && (
                  <div>
                    <h3 className="dossier-h mb-3">{t('report.news')}</h3>
                    <NewsList report={report} />
                  </div>
                )}
                {report.questions.length > 0 && (
                  <div>
                    <h3 className="dossier-h mb-3">{t('report.questions')}</h3>
                    <ol role="list" className="flex flex-col gap-2 list-none p-0 m-0" data-testid="questions">
                      {report.questions.map((q, i) => (
                        <li key={i} className="grid grid-cols-[28px_1fr] gap-2 text-base">
                          <span className="font-display italic text-ink-3 text-lg leading-6" aria-hidden>
                            {i + 1}.
                          </span>
                          <span>
                            <RichText text={pick(q, lang)} />
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                <div id="subj-outreach" tabIndex={-1} className="scroll-mt-16">
                  <h3 className="dossier-h mb-3">{t('report.outreach')}</h3>
                  <Outreach
                    draft={report.outreach_draft}
                    conflict={report.claims.some((k) => k.status === 'conflicts_with_record')}
                    onCheck={() => document.getElementById('subj-claims')?.scrollIntoView({ block: 'start', behavior: 'smooth' })}
                  />
                </div>
                {(report.method?.length || Object.keys(report.text_source ?? {}).length) ? (
                  <div id="subj-method" tabIndex={-1} className="scroll-mt-16">
                    <h3 className="dossier-h mb-3">{t('report.method')}</h3>
                    <MethodPanel report={report} runRequests={state.llmUsage?.total ?? null} />
                  </div>
                ) : null}
                <div>
                  <h3 className="dossier-h mb-3">{t('report.notChecked')}</h3>
                  <ul role="list" className="flex flex-col gap-1">
                    {report.not_checked.map((n, i) => (
                      <li key={i} className="finding finding-gap text-base">
                        <RichText text={pick(n, lang)} />
                      </li>
                    ))}
                  </ul>
                  {report.skeptic_notes.length > 0 && (
                    <div className="mt-4">
                      <h4 className="smallcaps mb-2">{t('report.skeptic')}</h4>
                      <ul role="list" className="flex flex-col gap-2">
                        {report.skeptic_notes.map((n, i) => (
                          <li key={i} className="text-base text-ink-2 border-l-2 border-ink-3 pl-3">
                            <RichText text={pick(n, lang)} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="mt-4 border border-dashed border-rule-strong rounded-sm px-4 py-3 flex items-center gap-4">
                    <span className="counter">{report.sensitive_filtered}</span>
                    <div>
                      <h4 className="smallcaps !text-ink-2">{t('report.sensitive')}</h4>
                      <p className="text-sm text-ink-2">{t('report.sensitive.value', { n: report.sensitive_filtered })}</p>
                    </div>
                  </div>
                </div>
                {c && c.profile?.source?.mode === 'mock' && (
                  <p className="text-sm text-ink-2">
                    <MockTag /> {t('header.status.trust.mock')}
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  )
}
