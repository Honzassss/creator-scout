// Goal-conditioned report parts (docs/subject-mode.md sections 5-7): identity verdict, relevance-ordered
// findings with confidence and "why it matters", the "less relevant" group, how the report was built.
// Used inline on the subject board and inside the report drawer. No score, no rank of the creator:
// tiers order FINDINGS for the current goal.

import { useMemo, useState, type ReactNode } from 'react'
import { useApp } from '../store'
import { pick, type I18nKey } from '../i18n'
import type { ClaimCheck, Confidence, Finding, FindingKind, I18nText, RelevanceTier, Report, ReportSection, SourceRef } from '../types'
import { ClaimCard, CollabTimeline, IdentityPanel } from './CandidateDrawer'
import { RichText, SourceChip, SourceChips, scrollToEl } from './primitives'

// ---------------- small parts ----------------

/** Shared detail typography (spec 3, 13): one sans family, few caps. Class strings, used inside render only. */
export const CLS = {
  /** small group label: 13/18 600, never mono caps */
  label: 'text-[13px] leading-[18px] font-semibold text-[color:var(--text-2)]',
  /** section title in the detail: 18/26 600 */
  section: 'text-[18px] leading-[26px] font-semibold text-[color:var(--text)]',
  /** sub-section title: 16/22 600 */
  sub: 'text-[16px] leading-[22px] font-semibold text-[color:var(--text)]',
  /** a white block with a light border */
  block: 'bg-[color:var(--surface)] border border-[color:var(--line)] rounded-[12px]',
  /** a small info block (sources, notes) */
  info: 'bg-[color:var(--bg)] border border-[color:var(--line)] rounded-[8px]',
  meta: 'text-[12px] leading-4 text-[color:var(--text-3)] tabular-nums',
} as const

const KIND_TAG: Record<FindingKind, string> = {
  fact: 'text-[color:var(--fact)] bg-[color:var(--accent-tint)] border-solid border-[color:color-mix(in_oklab,var(--fact)_35%,transparent)]',
  inference: 'text-[color:var(--inference)] bg-[#FFF3DC] border-solid border-[color:color-mix(in_oklab,var(--inference)_35%,transparent)]',
  gap: 'text-[color:var(--gap)] bg-[color:var(--bg)] border-dashed border-[color:var(--field)]',
}

/** The mark inside a kind label: filled square (fact), diamond (inference), hollow square (gap). Shape, not colour. */
export function KindMark({ kind }: { kind: FindingKind }) {
  const cls =
    kind === 'fact'
      ? 'w-2 h-2 rounded-[1px] bg-current'
      : kind === 'inference'
        ? 'w-[7px] h-[7px] rotate-45 bg-current mx-[1px]'
        : 'w-2 h-2 rounded-[1px] border-[1.5px] border-current'
  return <span aria-hidden className={`inline-block flex-none ${cls}`} />
}

/** Fact / inference / gap: the same label everywhere, told apart by its word and shape (mark + solid or dashed
 *  outline); colour is only the third cue. */
export function KindLabel({ kind, children }: { kind: FindingKind; children?: ReactNode }) {
  const { t } = useApp()
  return (
    <span className={`kind-tag inline-flex items-center gap-1.5 min-h-[22px] px-2 rounded-[4px] border text-[12px] leading-4 font-semibold whitespace-nowrap ${KIND_TAG[kind]}`}>
      <KindMark kind={kind} />
      {children ?? t(`drawer.kind.${kind}`)}
    </span>
  )
}

/** A finding and its evidence side by side: the claim on the left, a small bordered source block on the right
 *  (under it on a narrow column), so the statement and what it rests on read as one unit. */
export function EvidenceItem({
  kind,
  id,
  head,
  sources,
  children,
  focusable,
  dataAttrs,
}: {
  kind: FindingKind
  id?: string
  head?: ReactNode
  sources?: SourceRef[] | null
  children: ReactNode
  focusable?: boolean
  /** stable test hooks (data-testid and friends): no behaviour or visual change */
  dataAttrs?: Record<`data-${string}`, string | undefined>
}) {
  const { t } = useApp()
  const src = sources ?? []
  return (
    <li
      id={id}
      tabIndex={focusable ? -1 : undefined}
      {...dataAttrs}
      className={`evidence-item @container relative list-none scroll-mt-16 rounded-[8px] border ${
        kind === 'gap' ? 'border-dashed border-[color:var(--field)] bg-[color:var(--bg)]' : 'border-[color:var(--line)] bg-[color:var(--surface)]'
      }`}
    >
      <div className={`grid ${src.length ? '@xl:grid-cols-[minmax(0,1fr)_minmax(136px,22%)]' : ''}`}>
        <div className="min-w-0 px-3 py-3 @md:px-4">
          {head && <div className="flex items-center gap-x-2 gap-y-1 flex-wrap mb-2">{head}</div>}
          <div className="text-[15px] leading-[22px] text-[color:var(--text)] min-w-0">{children}</div>
        </div>
        {src.length > 0 && (
          <div className="min-w-0 px-3 py-2 border-t @xl:border-t-0 @xl:border-l border-[color:var(--line)] bg-[color:color-mix(in_oklab,var(--bg)_70%,var(--surface))] rounded-b-[8px] @xl:rounded-b-none @xl:rounded-r-[8px]">
            <span className="block text-[12px] leading-4 text-[color:var(--text-3)] mb-1">{src.length > 1 ? t('source.dialogs', { n: src.length }) : t('source.dialog')}</span>
            <span className="flex gap-1 flex-wrap">
              <SourceChips sources={src} />
            </span>
          </div>
        )}
      </div>
    </li>
  )
}


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
        <span className="text-[color:var(--text-3)]">
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
    <span className="tier-key !bg-[color:var(--accent-tint)] !text-[color:var(--accent)] !font-sans !rounded-[4px] border border-[color:color-mix(in_oklab,var(--accent)_30%,transparent)]" title={t('report.tier.keyTitle')}>
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
    <p className="mt-2 text-[13px] leading-[18px] text-[color:var(--text-2)]">
      <span className="font-semibold text-[color:var(--text)] mr-1">{t('report.why')}</span> <RichText text={text} />
    </p>
  )
}

const NO_SKIP: ReadonlySet<string> = new Set()

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
    flashEl(el)
  }, 20)
}

/** One soft pulse on a jump target (motion contract .m-flash); restarts if it is already flashing. */
export function flashEl(el: HTMLElement) {
  el.classList.remove('flash', 'm-flash')
  void el.offsetWidth
  el.classList.add('flash', 'm-flash')
  window.setTimeout(() => el.classList.remove('m-flash'), 1600)
}

/** The goal checks are shown as the checklist (board) or the candidate card (drawer), not as findings. Both places
 *  number the findings without them, so "Finding 5" is the same finding on the board and in the drawer. */
export const SKIP_GOAL: ReadonlySet<string> = new Set(['goal'])

export function FindingRow({ f, no, findingNo, idPrefix }: { f: Finding; no?: number; findingNo: Map<string, number>; idPrefix: string }) {
  const { t, lang } = useApp()
  return (
    <EvidenceItem
      kind={f.kind}
      id={itemDomId(idPrefix, f.id)}
      focusable
      dataAttrs={{ 'data-testid': 'finding', 'data-kind': f.kind, 'data-confidence': f.confidence ?? undefined, 'data-tier': f.tier ?? undefined }}
      sources={f.sources}
      head={
        <>
          <KindLabel kind={f.kind} />
          <TierTag tier={f.tier} />
          {no != null && <span className={CLS.meta}>{t('report.finding', { n: no })}</span>}
          <span className="ml-auto">
            <ConfidenceTag level={f.confidence} basis={f.confidence_basis} />
          </span>
        </>
      }
    >
      <RichText text={pick(f.text, lang)} />
      {(f.based_on?.length ?? 0) > 0 && <BasedOn ids={f.based_on!} findingNo={findingNo} onJump={(id) => jumpToItem(id, idPrefix)} />}
      <WhyLine why={f.why_it_matters} />
    </EvidenceItem>
  )
}

/** "(based on Finding 3, Finding 5)": the inference points at the facts it rests on. */
export function BasedOn({ ids, findingNo, onJump }: { ids: string[]; findingNo: Map<string, number>; onJump: (id: string) => void }) {
  const { t } = useApp()
  return (
    <span className="text-[13px] leading-[18px] text-[color:var(--text-2)] ml-1">
      ({t('report.basedOn')}{' '}
      {ids.map((id, i) => (
        <span key={id}>
          {i > 0 && ', '}
          <span className="whitespace-nowrap">
            <button type="button" className="btn-link !min-h-0 text-[13px]" onClick={() => onJump(id)}>
              {t('report.finding', { n: findingNo.get(id) ?? 0 })}
            </button>
            {i === ids.length - 1 && ')'}
          </span>
        </span>
      ))}
    </span>
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
            <div className="px-4 py-2 border-t border-[color:var(--line)] flex flex-col gap-1">
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

/** A small status label whose outline shape carries the meaning together with its word (never a traffic light). */
export function StatusTag({ shape, children }: { shape: 'solid' | 'dashed' | 'dotted' | 'double'; children: ReactNode }) {
  const b = shape === 'double' ? 'border-[3px] border-double' : shape === 'dashed' ? 'border-[1.5px] border-dashed' : shape === 'dotted' ? 'border-[1.5px] border-dotted' : 'border-[1.5px] border-solid'
  return (
    <span className={`status-tag inline-flex items-center min-h-6 px-2 rounded-[4px] ${b} border-[color:var(--text-2)] text-[13px] leading-[18px] font-semibold text-[color:var(--text)] bg-[color:var(--surface)] whitespace-nowrap`}>
      {children}
    </span>
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
    <section className={`${CLS.block} p-4 sm:p-5`} aria-labelledby={hId} data-testid="identity-verdict" data-status={v.status}>
      <div className="flex items-center gap-3 flex-wrap">
        <h3 id={hId} className={CLS.sub}>
          {t('verdict.title')}
        </h3>
        <StatusTag shape={v.status === 'confirmed' ? 'solid' : v.status === 'likely' ? 'dashed' : 'dotted'}>{t(`verdict.${v.status}`)}</StatusTag>
      </div>
      <p className="mt-2 text-[15px] leading-[22px]">
        <RichText text={pick(v.text, lang)} />
      </p>
      <div className="grid gap-4 mt-3 sm:grid-cols-2">
        <div>
          <h4 className={CLS.label}>{t('verdict.supporting', { n: sup.length })}</h4>
          {sup.length === 0 && (
            <p className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1">{t('verdict.supporting.none')}</p>
          )}
          <ul role="list" className="mt-1 flex flex-col gap-1">
            {sup.map((s, i) => (
              <li key={i} className="text-[14px] leading-5 flex items-start gap-2">
                <span aria-hidden className="text-[color:var(--text-2)] font-semibold w-3 flex-none text-center">
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
          <h4 className={CLS.label}>{t('verdict.contradicting', { n: con.length })}</h4>
          {con.length === 0 ? (
            <p className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1">{t('verdict.contradicting.none')}</p>
          ) : (
            <ul role="list" className="mt-1 flex flex-col gap-1">
              {con.map((s, i) => (
                <li key={i} className="text-[14px] leading-5 flex items-start gap-2">
                  <span aria-hidden className="text-[color:var(--text-2)] font-semibold w-3 flex-none text-center">
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
          <h4 className={CLS.label}>{t('verdict.setAside', { n: aside.length })}</h4>
          <ul role="list" className="mt-1">
            {aside.map((a) => (
              <li key={a.ref} className="aside-row">
                <span className="tag !normal-case !tracking-normal justify-self-start">{t(`verdict.kind.${a.kind}`)}</span>
                <span className="min-w-0 text-sm">
                  <span className="font-medium [overflow-wrap:anywhere]" translate="no">
                    <RichText text={pick(a.label, lang)} />
                  </span>
                  <span className="text-[color:var(--text-2)]">
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
      <p className="mt-3 text-[13px] leading-[18px] text-[color:var(--text-2)]">{t('verdict.note')}</p>
      {others.length > 0 && (
        <details className="mt-3 disclosure !border-solid !border-[color:var(--line)] !rounded-[8px]">
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
      <p className="text-[13px] leading-[18px] text-[color:var(--text-2)]">{t('report.ranked.note')}</p>
      {skipGoal && all.some((s) => s.id === 'goal') && <p className="text-[13px] leading-[18px] text-[color:var(--text-2)] -mt-4">{t(goalNote)}</p>}
      {secs
        .filter((s) => s.item_ids.length > 0)
        .map((s, i) => (
          <section key={s.id} id={`${idPrefix}-${s.id}`} aria-labelledby={`${idPrefix}-${s.id}-h`} className="scroll-mt-16">
            <h4 id={`${idPrefix}-${s.id}-h`} className={`${CLS.sub} flex items-center gap-2 pb-2 border-b border-[color:var(--line)]`}>
              <span className={`${CLS.meta} min-w-5`} aria-hidden>
                {i + 1}
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
        <details className="less-group !border-[color:var(--field)] !rounded-[8px] !px-4" open={lessOpen} onToggle={(e) => setLessOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>
            <span className="font-semibold">{lessSkipped > 0 ? t('report.less.withChecks', { n: lessN, k: lessSkipped }) : t('report.less', { n: lessN })}</span>
            <span className="text-[13px] text-[color:var(--text-2)] ml-2 max-sm:block max-sm:ml-0">{t('report.less.hint')}</span>
          </summary>
          <div className="mt-3 flex flex-col gap-4">
            {secs
              .filter((s) => (s.less_ids?.length ?? 0) > 0)
              .map((s) => (
                <div key={s.id}>
                  <h5 className={`${CLS.label} mb-2`}>{sectionTitle(s, lang, t)}</h5>
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
          <span className={CLS.label}>{t('report.textSource')}</span>
          {ts.map(([k, v]) => (
            <span key={k} className="whitespace-nowrap">
              <span className="text-[color:var(--text-2)]">{stepLabel(k)}:</span> <span className="font-medium">{tsLabel(v)}</span>
            </span>
          ))}
        </div>
      )}
      {runRequests != null && <p className="mt-2 text-[13px] leading-[18px] text-[color:var(--text-2)]">{t('report.runRequests', { n: runRequests })}</p>}
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
    <div className="summary-line !border-l-[3px] !border-[color:var(--accent)] !pl-3">
      <span className={`${CLS.label} block mb-1`}>{t('report.summary')}</span>
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

