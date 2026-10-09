// Goal-conditioned report parts (docs/subject-mode.md sections 5-7): identity verdict, relevance-ordered
// findings with confidence and "why it matters", the "less relevant" group, how the report was built.
// Used inline on the subject board and inside the report drawer. No score, no rank of the creator:
// tiers order FINDINGS for the current goal.

import { useMemo, useState, type ReactNode } from 'react'
import { useApp } from '../store'
import { pick, type I18nKey } from '../i18n'
import type { ClaimCheck, Confidence, Finding, I18nText, RelevanceTier, Report, ReportSection } from '../types'
import { ClaimCard, CollabTimeline, IdentityPanel } from './CandidateDrawer'
import { RichText, SourceChip, SourceChips, scrollToEl } from './primitives'

// ---------------- small parts ----------------

/** "medium confidence · public like and comment counts, 24 posts": about the finding, never a score. */
export function ConfidenceTag({ level, basis, compact }: { level?: Confidence | null; basis?: I18nText | null; compact?: boolean }) {
  const { t, lang } = useApp()
  if (!level) return null
  const b = basis ? pick(basis, lang) : ''
  return (
    <span className="conf" title={t('report.conf.title', { basis: b || '–' })}>
      <span className={`conf-mark conf-${level}`} aria-hidden />
      <span>{t('report.conf', { level: t(`report.confidence.${level}`) })}</span>
      {compact && b && <span className="sr-only">: {b}</span>}
      {!compact && b && (
        <span className="text-ink-3">
          <span aria-hidden> · </span>
          {b}
        </span>
      )}
    </span>
  )
}

export function TierTag({ tier }: { tier?: RelevanceTier | null }) {
  const { t } = useApp()
  if (tier !== 'key') return null
  return (
    <span className="tier-key" title={t('report.tier.keyTitle')}>
      {t('report.tier.key')}
    </span>
  )
}

export function WhyLine({ why }: { why?: I18nText | null }) {
  const { t, lang } = useApp()
  if (!why) return null
  const text = pick(why, lang)
  if (!text) return null
  return (
    <p className="why">
      <span className="why-label">{t('report.why')}</span> <RichText text={text} />
    </p>
  )
}

const NO_SKIP: ReadonlySet<string> = new Set()

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII']

/** DOM id of a finding / claim row. The prefix keeps the board and the drawer apart (both can be in the DOM). */
export const itemDomId = (prefix: string, id: string) => `${prefix}-rf-${id}`

/** Scroll to a finding / claim of the report rendered with `prefix`, flash it and move focus to it. */
export function jumpToItem(id: string, prefix: string) {
  window.setTimeout(() => {
    const el = document.getElementById(itemDomId(prefix, id))
    if (!el) return
    const details = el.closest('details')
    if (details && !details.open) details.open = true
    scrollToEl(el, 'center')
    el.focus({ preventScroll: true })
    el.classList.remove('flash')
    void el.offsetWidth
    el.classList.add('flash')
  }, 20)
}

/** The goal checks are shown as the checklist (board) or the candidate card (drawer), not as findings. Both places
 *  number the findings without them, so "Finding 5" is the same finding on the board and in the drawer. */
export const SKIP_GOAL: ReadonlySet<string> = new Set(['goal'])

export function FindingRow({ f, no, findingNo, idPrefix }: { f: Finding; no?: number; findingNo: Map<string, number>; idPrefix: string }) {
  const { t, lang } = useApp()
  return (
    <li id={itemDomId(idPrefix, f.id)} tabIndex={-1} className={`finding finding-${f.kind} scroll-mt-16`} data-testid="finding" data-kind={f.kind} data-confidence={f.confidence ?? undefined} data-tier={f.tier ?? undefined}>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className={`kind-label kind-${f.kind}`}>{t(`drawer.legend.${f.kind}`)}</span>
        <TierTag tier={f.tier} />
        {no != null && <span className="meta">{t('report.finding', { n: no })}</span>}
        <span className="ml-auto">
          <ConfidenceTag level={f.confidence} basis={f.confidence_basis} />
        </span>
      </div>
      <div className="flex items-start justify-between gap-3 mt-1">
        <div className="text-base min-w-0">
          <RichText text={pick(f.text, lang)} />
          {(f.based_on?.length ?? 0) > 0 && (
            <span className="text-sm text-ink-2 ml-1">
              ({t('report.basedOn')}{' '}
              {f.based_on!.map((id, i) => (
                <span key={id}>
                  {i > 0 && ', '}
                  <button type="button" className="btn-link !min-h-0 text-sm" onClick={() => jumpToItem(id, idPrefix)}>
                    {t('report.finding', { n: findingNo.get(id) ?? 0 })}
                  </button>
                </span>
              ))}
              )
            </span>
          )}
        </div>
        {f.sources.length > 0 && (
          <span className="flex gap-1 flex-wrap justify-end flex-none">
            <SourceChips sources={f.sources} />
          </span>
        )}
      </div>
      <WhyLine why={f.why_it_matters} />
    </li>
  )
}

function ClaimItem({ k, report, findingNo, idPrefix }: { k: ClaimCheck; report: Report; findingNo: Map<string, number>; idPrefix: string }) {
  // the claim card itself prints the confidence and its basis; this strip adds only the goal layer
  return (
    <li id={itemDomId(idPrefix, k.id)} tabIndex={-1} className="scroll-mt-16 list-none" data-testid="claim-check" data-status={k.status}>
      <ClaimCard
        k={k}
        report={report}
        findingNo={findingNo}
        onJump={(id) => jumpToItem(id, idPrefix)}
        extra={
          (k.tier === 'key' || k.why_it_matters) && (
            <div className="px-4 py-2 border-t border-rule flex flex-col gap-1">
              {k.tier === 'key' && (
                <div className="flex items-baseline gap-2 flex-wrap">
                  <TierTag tier={k.tier} />
                </div>
              )}
              <WhyLine why={k.why_it_matters} />
            </div>
          )
        }
      />
    </li>
  )
}

// ---------------- identity verdict ----------------

export function VerdictBlock({ report, idPrefix }: { report: Report; idPrefix: string }) {
  const { t, lang } = useApp()
  const hId = `${idPrefix}-verdict-h`
  const v = report.identity_verdict
  if (!v) return null
  const sup = v.supporting ?? []
  const con = v.contradicting ?? []
  const aside = v.set_aside ?? []
  const others = report.identity ?? []
  return (
    <section className="verdict" aria-labelledby={hId} data-testid="identity-verdict" data-status={v.status}>
      <div className="flex items-baseline gap-3 flex-wrap">
        <h3 id={hId} className="text-md font-semibold">
          {t('verdict.title')}
        </h3>
        <span className={`stamp verdict-${v.status}`}>{t(`verdict.${v.status}`)}</span>
      </div>
      <p className="mt-2 text-md leading-relaxed">
        <RichText text={pick(v.text, lang)} />
      </p>
      <div className="grid gap-4 mt-3 sm:grid-cols-2">
        <div>
          <h4 className="smallcaps !text-ink-2">{t('verdict.supporting', { n: sup.length })}</h4>
          <ul role="list" className="mt-1 flex flex-col gap-1">
            {sup.map((s, i) => (
              <li key={i} className="text-sm flex items-start gap-2">
                <span aria-hidden className="num text-ink-2">
                  ✓
                </span>
                <span className="flex-1 min-w-0">
                  <RichText text={pick(s.signal, lang)} />
                </span>
                {s.source && <SourceChip src={s.source} />}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="smallcaps !text-ink-2">{t('verdict.contradicting', { n: con.length })}</h4>
          {con.length === 0 ? (
            <p className="text-sm text-ink-2 mt-1">{t('verdict.contradicting.none')}</p>
          ) : (
            <ul role="list" className="mt-1 flex flex-col gap-1">
              {con.map((s, i) => (
                <li key={i} className="text-sm flex items-start gap-2">
                  <span aria-hidden className="num text-ink-2">
                    ✕
                  </span>
                  <span className="flex-1 min-w-0">
                    <RichText text={pick(s.signal, lang)} />
                  </span>
                  {s.source && <SourceChip src={s.source} />}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {aside.length > 0 && (
        <div className="mt-4">
          <h4 className="smallcaps !text-ink-2">{t('verdict.setAside', { n: aside.length })}</h4>
          <ul role="list" className="mt-1">
            {aside.map((a) => (
              <li key={a.ref} className="aside-row">
                <span className="tag !normal-case !tracking-normal justify-self-start">{t(`verdict.kind.${a.kind}`)}</span>
                <span className="min-w-0 text-sm">
                  <span className="font-medium [overflow-wrap:anywhere]" translate="no">
                    <RichText text={pick(a.label, lang)} />
                  </span>
                  <span className="text-ink-2">
                    {' · '}
                    <RichText text={pick(a.reason, lang)} />
                  </span>
                </span>
                {a.source ? <SourceChip src={a.source} /> : <span />}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-sm text-ink-2 italic">{t('verdict.note')}</p>
      {others.length > 0 && (
        <details className="mt-2 disclosure">
          <summary>{t('verdict.matches')}</summary>
          <div className="mt-2">
            <IdentityPanel items={others} />
          </div>
        </details>
      )}
    </section>
  )
}

// ---------------- ranked findings ----------------

/** Sections from the report, or (older reports) built here from the findings' own sections and tiers. */
export function reportSections(report: Report): ReportSection[] {
  if (report.sections?.length) return report.sections
  const order = ['identity', 'goal', 'claims', 'collabs', 'content', 'engagement', 'news', 'profile']
  const out: ReportSection[] = []
  const rank = (x?: RelevanceTier | null) => (x === 'key' ? 2 : x === 'less' ? 0 : 1)
  for (const id of order) {
    const items: { id: string; tier?: RelevanceTier | null }[] =
      id === 'claims' ? report.claims.map((k) => ({ id: k.id, tier: k.tier })) : report.findings.filter((f) => f.section === id).map((f) => ({ id: f.id, tier: f.tier }))
    if (!items.length) continue
    const sorted = [...items].sort((a, b) => rank(b.tier) - rank(a.tier))
    out.push({
      id,
      title: { cs: id, en: id },
      tier: sorted[0].tier ?? 'related',
      item_ids: sorted.filter((x) => x.tier !== 'less').map((x) => x.id),
      less_ids: sorted.filter((x) => x.tier === 'less').map((x) => x.id),
    })
  }
  return out
}

/** Display numbers: expanded items first in section order, then the collapsed ones. */
export function displayNumbers(report: Report, skip: ReadonlySet<string> = new Set()): Map<string, number> {
  const secs = reportSections(report).filter((s) => !skip.has(s.id))
  const ids = [...secs.flatMap((s) => s.item_ids), ...secs.flatMap((s) => s.less_ids ?? [])]
  const fids = new Set(report.findings.map((f) => f.id))
  const m = new Map<string, number>()
  let n = 0
  for (const id of ids) if (fids.has(id)) m.set(id, ++n)
  for (const f of report.findings) if (!m.has(f.id)) m.set(f.id, ++n)
  return m
}

function sectionTitle(s: ReportSection, lang: 'cs' | 'en', t: ReturnType<typeof useApp>['t']): string {
  const key = `report.section.${s.id}` as I18nKey
  const own = pick(s.title, lang)
  return own && own !== s.id ? own : t(key)
}

export function RankedFindings({ report, skipGoal, idPrefix, goalNote = 'report.goalChecks.inline' }: { report: Report; skipGoal?: boolean; idPrefix: string; goalNote?: I18nKey }) {
  const { t, lang } = useApp()
  const skip = skipGoal ? SKIP_GOAL : NO_SKIP
  const all = reportSections(report)
  const secs = all.filter((s) => !skip.has(s.id))
  const findings = useMemo(() => new Map(report.findings.map((f) => [f.id, f])), [report])
  const claims = useMemo(() => new Map(report.claims.map((k) => [k.id, k])), [report])
  const findingNo = useMemo(() => displayNumbers(report, skip), [report, skip])
  const lessN = secs.reduce((a, s) => a + (s.less_ids?.length ?? 0), 0)
  // the passed goal checks collapsed as less relevant are in the checklist: count them, so this number and the
  // method line ("k findings are collapsed as less relevant", which counts all less_relevant ids) add up
  const lessSkipped = all.filter((s) => skip.has(s.id)).reduce((a, s) => a + (s.less_ids?.length ?? 0), 0)
  const [lessOpen, setLessOpen] = useState(false)

  const item = (id: string): ReactNode => {
    const f = findings.get(id)
    if (f) return <FindingRow key={id} f={f} no={findingNo.get(id)} findingNo={findingNo} idPrefix={idPrefix} />
    const k = claims.get(id)
    if (k) return <ClaimItem key={id} k={k} report={report} findingNo={findingNo} idPrefix={idPrefix} />
    return null
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-ink-2 italic">{t('report.ranked.note')}</p>
      {skipGoal && all.some((s) => s.id === 'goal') && <p className="text-sm text-ink-2 -mt-4">{t(goalNote)}</p>}
      {secs
        .filter((s) => s.item_ids.length > 0)
        .map((s, i) => (
          <section key={s.id} id={`${idPrefix}-${s.id}`} aria-labelledby={`${idPrefix}-${s.id}-h`} className="scroll-mt-16">
            <h4 id={`${idPrefix}-${s.id}-h`} className="rsec-h">
              <span className="roman" aria-hidden>
                {ROMAN[i]}.
              </span>
              {sectionTitle(s, lang, t)}
              {s.tier === 'key' && <TierTag tier="key" />}
            </h4>
            {s.id === 'collabs' && report.collab_timeline.length > 0 && (
              <div className="mt-3 mb-3">
                <CollabTimeline items={report.collab_timeline} />
              </div>
            )}
            <ul role="list" className="mt-2 flex flex-col gap-2 p-0 m-0">
              {s.item_ids.map(item)}
            </ul>
          </section>
        ))}
      {lessN > 0 && (
        <details className="less-group" open={lessOpen} onToggle={(e) => setLessOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>
            <span className="font-semibold">{lessSkipped > 0 ? t('report.less.withChecks', { n: lessN, k: lessSkipped }) : t('report.less', { n: lessN })}</span>
            <span className="text-sm text-ink-2 ml-2 max-sm:block max-sm:ml-0">{t('report.less.hint')}</span>
          </summary>
          <div className="mt-3 flex flex-col gap-4">
            {secs
              .filter((s) => (s.less_ids?.length ?? 0) > 0)
              .map((s) => (
                <div key={s.id}>
                  <h5 className="smallcaps !text-ink-2 mb-1">{sectionTitle(s, lang, t)}</h5>
                  <ul role="list" className="flex flex-col gap-2 p-0 m-0">
                    {(s.less_ids ?? []).map(item)}
                  </ul>
                </div>
              ))}
          </div>
        </details>
      )}
    </div>
  )
}

// ---------------- how the report was built ----------------

export function MethodPanel({ report, runRequests }: { report: Report; runRequests?: number | null }) {
  const { t, lang } = useApp()
  const lines = report.method ?? []
  const ts = Object.entries(report.text_source ?? {})
  if (!lines.length && !ts.length) return null
  const tsLabel = (v: string) => {
    const k = `report.ts.${v}`
    return k in { 'report.ts.llm': 1, 'report.ts.rules': 1, 'report.ts.template': 1, 'report.ts.llm+rules': 1, 'report.ts.llm+template': 1 } ? t(k as I18nKey) : v
  }
  const stepLabel = (k: string) => {
    const key = `report.ts.${k}`
    return ['claims', 'news', 'skeptic', 'questions', 'outreach'].includes(k) ? t(key as I18nKey) : k
  }
  return (
    <div>
      {lines.length > 0 && (
        <ol className="method">
          {lines.map((l, i) => (
            <li key={i}>
              <RichText text={pick(l, lang)} />
            </li>
          ))}
        </ol>
      )}
      {ts.length > 0 && (
        <div className="mt-3 text-sm flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="smallcaps">{t('report.textSource')}</span>
          {ts.map(([k, v]) => (
            <span key={k} className="whitespace-nowrap">
              <span className="text-ink-2">{stepLabel(k)}:</span> <span className="font-medium">{tsLabel(v)}</span>
            </span>
          ))}
        </div>
      )}
      {runRequests != null && <p className="mt-2 text-sm text-ink-2">{t('report.runRequests', { n: runRequests })}</p>}
    </div>
  )
}

/** "Key for this goal: …" (report.summary): the top key findings, never a verdict on the creator. */
export function SummaryLine({ report }: { report: Report }) {
  const { t, lang } = useApp()
  if (!report.summary) return null
  // the label is shown above: drop the backend's own "Key for this goal:" prefix, and ".;" between items
  const text = pick(report.summary, lang)
    .replace(/^\s*(?:(?:Key for this goal|Klíčové pro tento cíl)\s*:\s*)+/i, '')
    .replace(/\.\s*;\s*/g, '; ')
  return (
    <div className="summary-line">
      <span className="smallcaps !text-ink-2 block mb-1">{t('report.summary')}</span>
      <RichText text={text} />
    </div>
  )
}

/** The goal the report is rendered for, e.g. "Bakery in Brno". */
export function goalLabel(report: Report | null | undefined, brief: { business_type?: string; city?: string | null } | null | undefined, t: ReturnType<typeof useApp>['t']): string {
  const bt = report?.rendered_for?.business_type ?? brief?.business_type ?? ''
  const city = report?.rendered_for?.city ?? brief?.city ?? ''
  if (/fit|gym|posil/i.test(bt) && /brno/i.test(city ?? '')) return t('goal.preset.fitness')
  if (/pek|bake/i.test(bt) && /brno/i.test(city ?? '')) return t('goal.preset.bakery')
  if (!bt) return '–'
  const cap = bt.charAt(0).toUpperCase() + bt.slice(1)
  return city ? `${cap} · ${city}` : cap
}

