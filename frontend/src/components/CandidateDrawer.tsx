import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useApp } from '../store'
import { fmtCompact, fmtDate, fmtInt, fmtMonth, fmtNum, fmtPct, pick, vetStepLabel, type I18nKey } from '../i18n'
import { categoryCs, csTypo } from '../lib/typo'
import { useDialog } from '../lib/useDialog'
import type { Candidate, ClaimCheck, CollabEvidence, Criterion, Finding, FindingKind, I18nText, IdentityMatch, Metrics, Report, SourceRef } from '../types'
import { CritIcon, MockTag, ModeBadge, NoValue, RichText, SourceChip, SourceChips, initialOf, platformLabel, scrollToEl } from './primitives'
import { foundViaLabel } from './Funnel'
import { BasedOn, CLS, EvidenceItem, KindLabel, MethodPanel, RankedFindings, SKIP_GOAL, StatusTag, SummaryLine, VerdictBlock, displayNumbers, flashEl, goalLabel, jumpToItem } from './Report'

/** A main section of the detail: 32 px above, a light rule, an 18 px title (spec 13). */
function Section({ id, title, children, aside, first }: { id: string; title: string; children: ReactNode; aside?: ReactNode; first?: boolean }) {
  return (
    <section id={id} className={`scroll-mt-24 ${first ? 'mt-8' : 'mt-8 pt-6 border-t border-[color:var(--line)]'}`} aria-labelledby={`${id}-h`}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 id={`${id}-h`} className={CLS.section} tabIndex={-1}>
          {title}
        </h3>
        {aside}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  )
}

/** A property: label above value, the value's source next to it. */
function Prop({ label, children, sources, wide }: { label: string; children: ReactNode; sources?: SourceRef[] | null; wide?: boolean }) {
  return (
    <div className={`min-w-0 py-3 border-b border-[color:var(--line)] ${wide ? 'col-span-full' : ''}`}>
      <dt className="text-[13px] leading-[18px] text-[color:var(--text-2)]">{label}</dt>
      <dd className="mt-1 flex flex-wrap items-start justify-between gap-2 m-0">
        <div className="min-w-0 flex-1 text-[15px] leading-[22px] text-[color:var(--text)]">{children}</div>
        {sources && sources.length > 0 && (
          <span className="flex gap-1 flex-wrap justify-end flex-none">
            <SourceChips sources={sources} />
          </span>
        )}
      </dd>
    </div>
  )
}

/** Met / not met / cannot verify: icon + word in a small tinted label; the tint never spreads to the card. */
function CritStatus({ status, waived }: { status: Candidate['results'][number]['status']; waived?: boolean }) {
  const { t } = useApp()
  const tone = waived || status === 'unknown' ? 'neutral' : status === 'pass' ? 'ok' : status === 'fail' ? 'bad' : 'neutral'
  const cls =
    tone === 'ok'
      ? 'text-[color:var(--ok)] bg-[color:var(--ok-tint)]'
      : tone === 'bad'
        ? 'text-[color:var(--bad)] bg-[color:var(--bad-tint)]'
        : 'text-[color:var(--neutral)] bg-[color:var(--neutral-tint)]'
  return (
    <span className={`crit-status inline-flex items-center gap-1 min-h-[22px] pl-1 pr-2 rounded-[4px] text-[12px] leading-4 font-semibold whitespace-nowrap [&_.crit-mark]:!text-inherit ${cls}`}>
      <CritIcon status={status} waived={waived} silent />
      {waived ? t('card.waived') : t(`card.${status}`)}
    </span>
  )
}

// ---------------- card part ----------------

// relevant topics in petrol (dark to light), the rest in greys
const TOPIC_SHADES = ['var(--accent)', '#3F8F8B', '#86BDB9', 'var(--field)', '#AFC0C8', 'var(--line)']

function TopicBar({ m, relevant }: { m: Metrics; relevant: Set<string> }) {
  const { t, lang } = useApp()
  const entries = Object.entries(m.topic_counts ?? {}).filter(([, n]) => n > 0)
  if (!entries.length) return <span className="text-[color:var(--text-2)]">{t('card.noData')}</span>
  // relevant topics first and dark; the rest lighter
  entries.sort((a, b) => Number(relevant.has(b[0])) - Number(relevant.has(a[0])) || b[1] - a[1])
  const total = entries.reduce((a, [, n]) => a + n, 0)
  let darkIdx = 0
  let lightIdx = 3
  const colors = entries.map(([k]) => (relevant.has(k) ? TOPIC_SHADES[Math.min(darkIdx++, 2)] : TOPIC_SHADES[Math.min(lightIdx++, 5)]))
  const name = (k: string) => t(`topic.${k}` as I18nKey)
  return (
    <div>
      <div className="topic-bar" role="img" aria-label={entries.map(([k, n]) => `${name(k)} ${fmtPct(n / total, lang)}`).join(', ')}>
        {entries.map(([k, n], i) => (
          <span key={k} style={{ width: `${(n / total) * 100}%`, background: colors[i] }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-[13px] leading-[18px]" aria-hidden>
        {entries.map(([k, n], i) => (
          <span key={k} className="inline-flex items-center gap-1">
            <span className="legend-swatch border border-[color:var(--line)]" style={{ background: colors[i] }} />
            <span className={relevant.has(k) ? 'text-[color:var(--text)] font-medium' : 'text-[color:var(--text-2)]'}>{name(k)}</span>
            <span className="meta">{fmtPct(n / total, lang)}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

export function CardBody({ c, crit, noCriteria }: { c: Candidate; crit: Record<string, Criterion>; noCriteria?: boolean }) {
  const { t, lang, state } = useApp()
  const p = c.profile
  const m = c.metrics
  const relevant = new Set<string>(
    (state.criteria?.criteria ?? []).filter((x) => x.kind === 'topic_share').flatMap((x) => (Array.isArray(x.params.topics) ? (x.params.topics as string[]) : [])),
  )
  const profileSrc = p?.source ? [p.source] : []
  const postSrcs = (p?.latest_posts ?? []).slice(0, 3).map((x) => x.source)
  const byRound = new Map<number, typeof c.results>()
  for (const r of c.results) {
    const round = crit[r.criterion_id]?.round ?? 0
    byRound.set(round, [...(byRound.get(round) ?? []), r])
  }
  const sens = c.sensitive_filtered ?? state.sensitive[c.id] ?? 0
  const srcByKind = (kind: Criterion['kind']) => c.results.find((r) => crit[r.criterion_id]?.kind === kind)?.sources ?? []
  const category = p?.business_category ? (lang === 'cs' ? categoryCs(p.business_category) : p.business_category) : ''

  return (
    <>
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))] gap-x-6 m-0">
        {p?.followers != null && (
          <Prop label={t('card.followers').replace(/^./, (x) => x.toUpperCase())} sources={profileSrc}>
            <span className="tnum">{fmtInt(p.followers, lang)}</span>
          </Prop>
        )}
        {(p?.private || p?.is_business) && (
          <Prop label={t('card.profile')} sources={profileSrc}>
            {[p?.private ? t('card.private') : null, p?.is_business ? `${t('card.business')}${category ? ` · ${category}` : ''}` : null].filter(Boolean).join(' · ')}
          </Prop>
        )}
        <Prop label={t('card.foundVia')} sources={c.ref.source ? [c.ref.source] : []}>
          <span className="flex flex-wrap gap-1">
            {(c.ref.found_via ?? []).map((v) => (
              <span key={v} className="text-[12px] leading-[18px] px-1.5 border border-[color:var(--line)] rounded-[4px] bg-[color:var(--bg)]" translate="no">
                {foundViaLabel(v, lang)}
              </span>
            ))}
          </span>
        </Prop>
        {p?.bio && (
          <Prop label={t('card.bio')} sources={profileSrc} wide>
            <span className="whitespace-pre-line">
              <RichText text={p.bio} />
            </span>
          </Prop>
        )}
        {m && (
          <>
            <Prop label={t('card.topics')} sources={postSrcs} wide>
              <TopicBar m={m} relevant={relevant} />
            </Prop>
            <Prop label={t('card.formats')} sources={postSrcs}>
              {Object.entries(m.formats ?? {})
                .filter(([, n]) => n > 0)
                .map(([k, n]) => `${t(`format.${k}` as I18nKey)} ${n}`)
                .join(' · ') || <NoValue />}
            </Prop>
            <Prop label={t('card.frequency')} sources={postSrcs}>
              {m.posts_per_week != null ? t('card.perWeek', { n: fmtNum(m.posts_per_week, lang) }) : <NoValue />}
            </Prop>
            <Prop label={t('card.lastPost')} sources={postSrcs.slice(0, 1)}>
              {fmtDate(m.last_post_at, lang)}
            </Prop>
            <Prop label={t('card.commercial')} sources={postSrcs}>
              {m.commercial_share != null ? `${fmtPct(m.commercial_share, lang)} ${t('card.postsAnalyzed', { n: m.posts_analyzed })}` : <NoValue />}
            </Prop>
            <Prop label={t('card.engagement')} sources={[...profileSrc, ...postSrcs]}>
              {fmtPct(m.engagement_rate, lang, 1)}
            </Prop>
            <Prop label={t('card.medianBoth')} sources={postSrcs}>
              <span className="tnum">
                {fmtInt(m.median_likes, lang)} / {fmtInt(m.median_comments, lang)}
              </span>
            </Prop>
            <Prop label={t('card.csComments')} sources={srcByKind('cs_comment_share')}>
              {m.cs_comment_share != null ? `${fmtPct(m.cs_comment_share, lang)} ${t('card.commentsAnalyzed', { n: m.comments_analyzed ?? 0 })}` : <NoValue />}
            </Prop>
            <Prop label={t('card.genericComments')} sources={srcByKind('max_generic_comments')}>
              {fmtPct(m.generic_comment_share, lang)}
            </Prop>
            <Prop label={t('card.localSignals')} sources={m.local_signals ?? []}>
              <span className="tnum">{m.local_signals?.length ? `${m.local_signals.length}×` : m.cs_comment_share == null ? <NoValue /> : '0'}</span>
            </Prop>
            {(m.engagement_spikes?.length ?? 0) > 0 && (
              <Prop label={t('card.authenticity')} wide>
                {t('card.spikes', { n: m.engagement_spikes!.length })}
              </Prop>
            )}
          </>
        )}
      </dl>
      {m && <p className="mt-3 text-[13px] leading-[18px] text-[color:var(--text-2)] border-l-2 border-dashed border-[color:var(--field)] pl-3">{t('card.audienceNote')}</p>}

      {!noCriteria && (
      <div className="mt-8">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h4 className={CLS.sub}>{t('card.criteria')}</h4>
          <p className="text-[13px] leading-[18px] text-[color:var(--text-2)]">{t('card.noScore')}</p>
        </div>
        {c.results.length === 0 && <p className="text-[15px] text-[color:var(--text-2)] mt-1">{t('card.noData')}</p>}
        {[...byRound.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([round, rs]) => (
            <div key={round} className="mt-4">
              <h5 className={CLS.label}>
                {t('criteria.round', { n: round })} · {t(`round.${round}` as I18nKey)}
              </h5>
              <ul role="list" className="mt-1">
                {rs.map((r) => (
                  <li key={r.criterion_id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 items-start py-3 border-b border-[color:var(--line)]">
                    <div className="min-w-0">
                      <div className="flex items-center gap-x-2 gap-y-1 flex-wrap">
                        <span className="text-[15px] leading-[22px] font-medium">{crit[r.criterion_id] ? pick(crit[r.criterion_id].label, lang) : r.criterion_id}</span>
                        <CritStatus status={r.status} waived={r.waived} />
                      </div>
                      <div className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1">
                        <RichText text={pick(r.value, lang)} />
                        <span className="text-[color:var(--text-3)]">
                          {' '}
                          · {t('card.threshold')}: {pick(r.threshold, lang)}
                        </span>
                      </div>
                    </div>
                    <span className="flex gap-1 flex-wrap justify-end">
                      <SourceChips sources={r.sources} />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </div>
      )}
      {sens > 0 && <p className="mt-3 text-[13px] leading-[18px] text-[color:var(--text-2)] border border-dashed border-[color:var(--field)] rounded-[8px] px-3 py-2">{t('card.sensitive', { n: sens })}</p>}
    </>
  )
}

// ---------------- dossier parts ----------------

function disclosedLabel(d: boolean | null, t: ReturnType<typeof useApp>['t']) {
  return d === true ? t('report.disclosed.yes') : d === false ? t('report.disclosed.no') : t('report.disclosed.unknown')
}

interface CollabGroup {
  id: string
  date: string | null
  brand: string
  brand_handle: string | null
  /** every brand this post tags or mentions (a recap post can name 20 businesses) */
  brands: { name: string; handle: string | null; is_competitor: boolean }[]
  kinds: CollabEvidence['kind'][]
  disclosed: boolean | null
  is_competitor: boolean
  sources: CollabEvidence['source'][]
}

/** One row per post: a post can yield a co-author record, an ad hashtag, a paid label and a Meta
 *  record at once; a record without a post joins a post of the same brand on the same day. */
function groupByPost(items: CollabEvidence[]): CollabGroup[] {
  const brandKey = (e: CollabEvidence) => (e.brand_handle ?? e.brand).toLowerCase().normalize('NFKD').replace(/[^a-z0-9]/g, '')
  const day = (e: CollabEvidence) => (e.date ? e.date.slice(0, 10) : '')
  const byPostBrandDay = new Map<string, string>()
  for (const e of items) if (e.post_id) byPostBrandDay.set(`${brandKey(e)}|${day(e)}`, e.post_id)
  const groups = new Map<string, CollabEvidence[]>()
  for (const e of items) {
    const key = e.post_id ?? byPostBrandDay.get(`${brandKey(e)}|${day(e)}`) ?? e.id
    groups.set(key, [...(groups.get(key) ?? []), e])
  }
  return [...groups.entries()].map(([id, evs]) => {
    const brands = new Map<string, { name: string; handle: string | null; is_competitor: boolean }>()
    for (const e of evs) {
      if (!e.brand || e.brand === 'unknown') continue
      const k = brandKey(e)
      const b = brands.get(k)
      if (b) {
        b.is_competitor ||= !!e.is_competitor
        b.handle ??= e.brand_handle ?? null
      } else brands.set(k, { name: e.brand, handle: e.brand_handle ?? null, is_competitor: !!e.is_competitor })
    }
    const list = [...brands.values()].sort((a, b) => Number(b.is_competitor) - Number(a.is_competitor))
    // the row is named after a competitor when the post names one, else after the first brand
    const named = list[0] ?? { name: evs[0].brand, handle: evs[0].brand_handle ?? null, is_competitor: !!evs[0].is_competitor }
    return {
      id,
      date: evs.map((e) => e.date).filter(Boolean).sort()[0] ?? null,
      brand: named.name,
      brand_handle: named.handle,
      brands: list,
      kinds: [...new Set(evs.map((e) => e.kind))],
      disclosed: evs.some((e) => e.disclosed === true) ? true : evs.some((e) => e.disclosed === false) ? false : null,
      is_competitor: evs.some((e) => e.is_competitor),
      sources: evs.map((e) => e.source),
    }
  })
}

export function CollabTimeline({ items: raw }: { items: CollabEvidence[] }) {
  const { t, lang } = useApp()
  const items = groupByPost(raw)
  const dated = items.filter((x) => x.date).sort((a, b) => +new Date(a.date!) - +new Date(b.date!))
  if (!items.length) return <p className="text-[15px] text-[color:var(--text-2)]">{t('report.collabs.empty')}</p>
  const min = dated.length ? +new Date(dated[0].date!) : 0
  const max = dated.length ? +new Date(dated[dated.length - 1].date!) : 0
  // month ticks at midnight: with the time of day kept, the month after the last record could appear
  const start = new Date(min)
  start.setUTCDate(1)
  start.setUTCHours(0, 0, 0, 0)
  const end = new Date(max)
  end.setUTCMonth(end.getUTCMonth() + 1, 1)
  end.setUTCHours(0, 0, 0, 0)
  const span = Math.max(1, +end - +start)
  const months: Date[] = []
  for (const d = new Date(start); d < end; d.setUTCMonth(d.getUTCMonth() + 1)) months.push(new Date(d))
  const pos = (iso: string) => ((+new Date(iso) - +start) / span) * 100

  return (
    <div data-testid="collab-timeline">
      {dated.length > 0 && (
        <div className="relative h-[56px] mb-1 mx-1 overflow-hidden" aria-hidden>
          <div className="absolute left-0 right-0 top-[28px] h-px bg-[color:var(--field)]" />
          {months.map((m) => (
            <div key={m.toISOString()} className="absolute top-[32px] meta whitespace-nowrap max-w-[30%] overflow-hidden" style={{ left: `${pos(m.toISOString())}%` }}>
              <div className="w-px h-2 bg-[color:var(--field)] -mt-1" />
              {fmtMonth(m.toISOString(), lang)}
            </div>
          ))}
          {dated.map((c) => (
            <div key={c.id} className="absolute -translate-x-1/2" style={{ left: `${pos(c.date!)}%`, top: 14 }} title={`${c.brand} · ${fmtDate(c.date, lang)} · ${disclosedLabel(c.disclosed, t)}`}>
              {c.is_competitor ? (
                <span className={`block w-4 h-4 mt-[6px] border-[2.5px] border-[color:var(--text)] ${c.disclosed ? 'bg-[color:var(--text)]' : 'bg-[color:var(--surface)]'}`} />
              ) : (
                <span
                  className={`block w-3 h-3 rounded-full border-[1.5px] border-[color:var(--text-2)] mt-[8px] ${c.disclosed === true ? 'bg-[color:var(--text-2)]' : c.disclosed === null ? 'border-dashed bg-[color:var(--surface)]' : 'bg-[color:var(--surface)]'}`}
                />
              )}
            </div>
          ))}
        </div>
      )}
      {dated.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3 text-[13px] leading-[18px] text-[color:var(--text-2)]" aria-hidden>
          <span className="inline-flex items-center gap-2">
            <span className="block w-3 h-3 border-[2.5px] border-[color:var(--text)] bg-ink" />
            {t('report.legend.competitor')}
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="block w-3 h-3 rounded-full border-[1.5px] border-[color:var(--text-2)] bg-[color:var(--text-2)]" />
            {t('report.legend.disclosed')}
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="block w-3 h-3 rounded-full border-[1.5px] border-[color:var(--text-2)] bg-[color:var(--surface)]" />
            {t('report.legend.undisclosed')}
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="block w-3 h-3 rounded-full border-[1.5px] border-dashed border-[color:var(--text-2)] bg-[color:var(--surface)]" />
            {t('report.legend.unknown')}
          </span>
        </div>
      )}
      <ul role="list" className="flex flex-col gap-1">
        {[...items]
          .sort((a, b) => +new Date(a.date ?? 0) - +new Date(b.date ?? 0))
          .map((c) => (
            <li
              key={c.id}
              className={`grid grid-cols-[92px_1fr_auto] gap-3 items-center px-3 py-2 border border-[color:var(--line)] rounded-[8px] bg-[color:var(--surface)] text-[15px] leading-[22px] max-sm:grid-cols-[1fr_auto] ${c.is_competitor ? 'competitor-row' : ''}`}
            >
              <span className="meta !text-[color:var(--text-2)] max-sm:col-span-2">{fmtDate(c.date, lang)}</span>
              <span className="min-w-0">
                <span className="font-semibold" translate="no">
                  {c.brand}
                </span>
                {c.brand_handle && (
                  <span className="text-[13px] leading-[18px] text-[color:var(--text-2)] ml-2" translate="no">
                    @{c.brand_handle}
                  </span>
                )}
                {c.is_competitor && <span className="tag tag-solid ml-2">{t('report.competitor')}</span>}
                {c.brands.length > 1 && (
                  <span className="block text-[13px] leading-[18px] text-[color:var(--text-2)]">
                    {t('report.collabs.alsoNamed', { n: c.brands.length - 1 })}{' '}
                    <span translate="no">
                      {c.brands
                        .slice(1, 9)
                        .map((b) => (b.handle && b.handle.toLowerCase() !== b.name.toLowerCase() ? `${b.name} @${b.handle}` : b.handle ? `@${b.handle}` : b.name))
                        .join(', ')}
                      {c.brands.length > 9 ? ` +${c.brands.length - 9}` : ''}
                    </span>
                  </span>
                )}
                <span className="block text-[13px] leading-[18px] text-[color:var(--text-2)]">
                  {c.kinds.map((k) => t(`kind.${k}` as I18nKey)).join(', ')} ·{' '}
                  <span className={c.disclosed === false ? 'text-[color:var(--text)] font-medium underline decoration-dotted' : ''}>{disclosedLabel(c.disclosed, t)}</span>
                </span>
              </span>
              <span className="flex gap-1 flex-wrap justify-end">
                <SourceChips sources={c.sources} />
              </span>
            </li>
          ))}
      </ul>
    </div>
  )
}

type Rel = 'supports' | 'contradicts' | 'related'
/** How a record relates to the claim: said in words (and a glyph), never by colour or hatching. */
function relationOf(k: ClaimCheck, brandHandle?: string | null): Rel {
  if (k.status === 'supported') return 'supports'
  if (k.status === 'conflicts_with_record') {
    const h = (brandHandle ?? '').toLowerCase()
    return h && k.claim.toLowerCase().includes(h) ? 'supports' : 'contradicts'
  }
  return 'related'
}

function RelWord({ rel }: { rel: Rel }) {
  const { t } = useApp()
  return (
    <span className="text-[13px] leading-[18px] font-semibold whitespace-nowrap text-[color:var(--text)]">
      {t(`report.rel.${rel}`)}{' '}
      <span aria-hidden>
        {rel === 'supports' ? '✓' : rel === 'contradicts' ? '✕' : '~'}
      </span>
    </span>
  )
}

const CLAIM_SHAPE: Record<ClaimCheck['status'], 'solid' | 'double' | 'dashed' | 'dotted'> = {
  supported: 'solid',
  conflicts_with_record: 'double',
  unsupported: 'dashed',
  cannot_verify: 'dotted',
}

/** Claim on the left, the record on the right (stacked on a narrow column): every record item is a small bordered
 *  block with its own source chips, so a claim and the evidence for it stay visibly together. */
export function ClaimCard({ k, report, findingNo, onJump, extra }: { k: ClaimCheck; report: Report; findingNo: Map<string, number>; onJump: (id: string) => void; extra?: ReactNode }) {
  const { t, lang } = useApp()
  const findings = new Map(report.findings.map((f) => [f.id, f]))
  const collabs = new Map(report.collab_timeline.map((c) => [c.id, c]))
  const evCollabs = k.evidence.map((id) => collabs.get(id)).filter((x): x is CollabEvidence => !!x)
  const evFindings = k.evidence.map((id) => findings.get(id)).filter((x): x is Finding => !!x)
  const unknown = k.evidence.filter((id) => !collabs.has(id) && !findings.has(id))
  const groups = groupByPost(evCollabs).sort((a, b) => +new Date(b.date ?? 0) - +new Date(a.date ?? 0))
  const evBlock = 'rounded-[8px] border border-[color:var(--line)] bg-[color:var(--surface)] px-3 py-2'
  const srcRow = 'mt-2 pt-2 border-t border-[color:var(--line)] flex gap-1 flex-wrap'
  return (
    <article className={`claim-card @container ${CLS.block} overflow-hidden`}>
      <div className="grid @xl:grid-cols-2">
        <div className="p-4 @xl:border-r border-[color:var(--line)] bg-[color:color-mix(in_oklab,var(--bg)_55%,var(--surface))] min-w-0">
          <h4 className={`${CLS.label} mb-2`}>{t('report.claims.says')}</h4>
          <blockquote className="text-[16px] leading-[24px] text-[color:var(--text)] [overflow-wrap:anywhere]">{lang === 'cs' ? `„${csTypo(k.claim)}“` : `“${k.claim}”`}</blockquote>
          <Gloss original={k.claim} gloss={k.claim_gloss} />
          <div className="mt-3 flex gap-1 flex-wrap">
            <SourceChip src={k.claim_source} />
          </div>
        </div>
        <div className="p-4 border-t @xl:border-t-0 border-[color:var(--line)] min-w-0">
          <h4 className={`${CLS.label} mb-2`}>{t('report.claims.record')}</h4>
          {k.evidence.length === 0 && <p className="text-[15px] text-[color:var(--text-2)]">{t('report.claims.noEvidence')}</p>}
          <ul role="list" className="flex flex-col gap-2">
            {groups.map((g) => (
              <li key={g.id} className={`${evBlock} ${g.is_competitor ? 'competitor-row' : ''}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <KindLabel kind="fact" />
                  <RelWord rel={relationOf(k, g.brand_handle)} />
                  <span className="meta">{fmtDate(g.date, lang)}</span>
                </div>
                <div className="text-[15px] leading-[22px] mt-1">
                  <span className="font-semibold" translate="no">
                    {g.brand}
                  </span>
                  {g.brand_handle && (
                    <span className="text-[13px] text-[color:var(--text-2)] ml-1" translate="no">
                      @{g.brand_handle}
                    </span>
                  )}
                  {g.is_competitor && <span className="tag tag-solid ml-2">{t('report.competitor')}</span>}
                </div>
                <div className="text-[13px] leading-[18px] text-[color:var(--text-2)]">
                  {g.kinds.map((x) => t(`kind.${x}` as I18nKey)).join(', ')} · {disclosedLabel(g.disclosed, t)}
                </div>
                <div className={srcRow}>
                  <SourceChips sources={g.sources} />
                </div>
              </li>
            ))}
            {evFindings.map((f) => (
              <li key={f.id} className={evBlock}>
                <div className="flex items-center gap-2 flex-wrap">
                  <KindLabel kind={f.kind} />
                  <RelWord rel={relationOf(k)} />
                  <button type="button" className="btn-link !min-h-0 text-[12px]" onClick={() => onJump(f.id)}>
                    {t('report.finding', { n: findingNo.get(f.id) ?? 0 })}
                  </button>
                </div>
                <div className="text-[15px] leading-[22px] mt-1">
                  <RichText text={pick(f.text, lang)} />
                </div>
                <div className={srcRow}>
                  <SourceChips sources={f.sources} />
                </div>
              </li>
            ))}
            {unknown.map((id) => (
              <li key={id} className="meta">
                {id}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="flex items-start gap-3 flex-wrap px-4 py-3 border-t border-[color:var(--line)] bg-[color:var(--bg)]">
        <span data-status={k.status}>
          <StatusTag shape={CLAIM_SHAPE[k.status]}>{t(`report.status.${k.status}`)}</StatusTag>
        </span>
        <span className="text-[14px] leading-5 text-[color:var(--text-2)] pt-0.5">
          {t('report.confidence')}: <b className="text-[color:var(--text)] font-semibold">{t(`report.confidence.${k.confidence}`)}</b>
          {k.confidence_basis && <span className="block text-[13px] leading-[18px] text-[color:var(--text-3)]">{pick(k.confidence_basis, lang)}</span>}
        </span>
        <span className="text-[15px] leading-[22px] text-[color:var(--text)] flex-1 min-w-[220px] max-sm:min-w-0 pt-0.5">
          <RichText text={pick(k.note, lang)} />
        </span>
      </div>
      {extra}
    </article>
  )
}

export function Saturation({ m, report }: { m: Metrics | null | undefined; report?: Report | null }) {
  const { t, lang } = useApp()
  // With a report, use its f:commercial fact ("k z N postů", the same posts as the dossier) and its
  // sources; otherwise the round-2 metric. Never an invented denominator.
  const fc = report?.findings.find((f) => f.id === 'f:commercial')
  const mm = fc && /(\d+)\s*(?:z|of)\s*(\d+)/.exec(fc.text.cs ?? fc.text.en ?? '')
  let n: number
  let total: number
  if (mm) {
    n = Number(mm[1])
    total = Number(mm[2])
  } else if (m && m.commercial_share != null && m.posts_analyzed) {
    total = m.posts_analyzed
    n = Math.round(m.commercial_share * total)
  } else {
    return <p className="text-[15px] text-[color:var(--text-2)]">{t('report.saturation.none')}</p>
  }
  const share = total ? n / total : 0
  const sources = fc?.sources ?? []
  return (
    <div className="grid md:grid-cols-[minmax(0,380px)_1fr] gap-6 items-center">
      <div className="post-grid" role="img" aria-label={t('report.saturation.value', { n, total })}>
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className={`post-cell ${i < n ? 'ad' : ''}`} />
        ))}
      </div>
      <div>
        <span className="block text-[30px] leading-[36px] font-semibold tabular-nums text-[color:var(--text)]">{fmtPct(share, lang)}</span>
        <p className="text-[15px] leading-[22px] text-[color:var(--text-2)] mt-1">{t('report.saturation.value', { n, total })}</p>
        {sources.length > 0 && (
          <div className="mt-2 flex gap-1 flex-wrap">
            <SourceChips sources={sources} />
          </div>
        )}
      </div>
    </div>
  )
}

/** A quote stays in its own language (it is the source); a short translation sits under it when the UI language
 *  differs (gloss = {cs, en}: shown only when the UI-language text is not the quote itself). */
export function Gloss({ original, gloss }: { original: string; gloss?: I18nText | null }) {
  const { t, lang } = useApp()
  const g = gloss ? pick(gloss, lang) : ''
  if (!gloss?.[lang] || !g || g.trim() === original.trim()) return null
  return (
    <p className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1 not-italic font-sans" lang={lang}>
      {t('claim.gloss')} <RichText text={g} />
    </p>
  )
}

export function NewsList({ report }: { report: Report }) {
  const { t, lang } = useApp()
  return (
    <ul role="list" className="flex flex-col gap-2">
      {report.news.map((n) => (
        <li key={n.item.id} className={`${CLS.block} px-4 py-3`}>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`tag tag-${n.label}`}>{t(`report.news.${n.label}`)}</span>
            <span className="meta">{fmtDate(n.item.published_at, lang)}</span>
            <span className="text-[13px] text-[color:var(--text-2)]" translate="no">
              <RichText text={n.attribution} />
            </span>
          </div>
          <div className="text-[16px] leading-[22px] font-semibold mt-2">
            <RichText text={lang === 'cs' ? `„${n.item.title}“` : `“${n.item.title}”`} />
          </div>
          <Gloss original={n.item.title} gloss={n.item.title_gloss} />
          {n.item.snippet && (
            <p className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1">
              <RichText text={n.item.snippet} />
            </p>
          )}
          {n.item.snippet && <Gloss original={n.item.snippet} gloss={n.item.snippet_gloss} />}
          <div className="mt-3 pt-2 border-t border-[color:var(--line)] flex gap-1 flex-wrap">
            <SourceChip src={n.item.source} />
          </div>
        </li>
      ))}
    </ul>
  )
}

export function IdentityPanel({ items }: { items: IdentityMatch[] }) {
  const { t, lang } = useApp()
  const order: IdentityMatch['status'][] = ['matched', 'uncertain', 'rejected']
  return (
    // minmax(0,1fr): a column never grows to the min-content of a long chip (320 px phones)
    <div className="grid grid-cols-[minmax(0,1fr)] md:grid-cols-3 gap-3 [&>*]:min-w-0">
      {order
        .filter((st) => items.some((x) => x.status === st))
        .map((st) => (
          <div key={st} className={`min-w-0 border rounded-[8px] p-3 bg-[color:var(--surface)] border-[color:var(--field)] ${st === 'matched' ? 'border-solid' : st === 'uncertain' ? 'border-dashed' : 'border-dotted'}`}>
            <h4 className={`${CLS.label} mb-2`}>{t(`report.identity.${st}`)}</h4>
            <ul role="list" className="flex flex-col gap-3">
              {items
                .filter((x) => x.status === st)
                .map((x) => (
                  <li key={`${x.platform}:${x.handle}`}>
                    <div className="text-[15px] leading-[22px] font-semibold [overflow-wrap:anywhere]" translate="no">
                      <span className="meta mr-1">{platformLabel(x.platform, t)}</span>
                      {x.platform === 'news' ? x.handle : `@${x.handle.replace(/^@/, '')}`}
                    </div>
                    <ul role="list" className="mt-1 flex flex-col gap-1">
                      {x.signals.map((s, i) => (
                        <li key={i} className="text-[13px] leading-[18px] text-[color:var(--text-2)] flex items-start gap-2 min-w-0">
                          <span className="meta w-12 flex-none">{s.supports ? t('report.identity.supports') : t('report.identity.against')}</span>
                          {/* the chip sits under its text: in a narrow column it can never be pushed out of the card */}
                          <span className="flex-1 min-w-0 [overflow-wrap:anywhere]">
                            <RichText text={pick(s.signal, lang)} />
                            {s.source && (
                              <span className="flex flex-wrap gap-1 mt-1 max-w-full">
                                <SourceChip src={s.source} />
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
            </ul>
          </div>
        ))}
    </div>
  )
}

export function Outreach({ draft, conflict, onCheck }: { draft: Report['outreach_draft']; conflict: boolean; onCheck: () => void }) {
  const { t, lang } = useApp()
  const [copied, setCopied] = useState(false)
  if (!draft) return <p className="text-[15px] text-[color:var(--text-2)]">{t('report.outreach.none')}</p>
  const text = pick(draft, lang)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1800)
  }
  return (
    <div data-testid="outreach">
      {conflict && (
        <p className="mb-4 text-[15px] leading-[22px] border-l-4 border-[color:var(--text-2)] pl-3 py-1">
          {t('report.outreach.check')}{' '}
          <button type="button" className="btn-link" onClick={onCheck}>
            <span aria-hidden>→</span> {t('report.claims')}
          </button>
        </p>
      )}
      <div className={`${CLS.block} overflow-hidden`}>
        <div className="flex items-center justify-between gap-3 flex-wrap px-4 py-2 border-b border-[color:var(--line)] bg-[color:var(--bg)]">
          <span data-testid="outreach-not-sent" className="notsent-tag inline-flex items-center min-h-6 px-2 rounded-[4px] border-[1.5px] border-[color:var(--text)] bg-[color:var(--surface)] text-[12px] leading-4 font-bold tracking-[0.08em] uppercase text-[color:var(--text)]">
            {t('report.outreach.notSent')}
          </span>
          {/* fixed width: "Copy" and "Copied" swap in place without moving or overlapping anything */}
          <button type="button" className="btn min-w-[112px] max-sm:min-h-11" data-testid="outreach-copy" onClick={copy}>
            {copied ? (
              <>
                <span aria-hidden>✓</span> {t('report.outreach.copied')}
              </>
            ) : (
              t('report.outreach.copy')
            )}
          </button>
        </div>
        <div data-testid="outreach-text" className="letter-body px-4 py-3 sm:px-5 sm:py-4 text-[15px] leading-[24px] whitespace-pre-wrap [overflow-wrap:anywhere] text-[color:var(--text)]">{text}</div>
      </div>
      <p className="mt-2 text-[13px] leading-[18px] text-[color:var(--text-2)]">{t('report.outreach.note')}</p>
      {/* announced by screen readers */}
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? t('report.outreach.copied') : ''}
      </span>
    </div>
  )
}

type Filter = 'all' | FindingKind
const KIND_ORDER: Record<FindingKind, number> = { inference: 0, gap: 1, fact: 2 }

function Findings({
  report,
  filter,
  setFilter,
  findingNo,
  onJump,
}: {
  report: Report
  filter: Filter
  setFilter: (f: Filter) => void
  findingNo: Map<string, number>
  onJump: (id: string) => void
}) {
  const { t, lang } = useApp()
  const count = (k: FindingKind) => report.findings.filter((f) => f.kind === k).length
  const opts: { k: Filter; label: string; n: number }[] = [
    { k: 'all', label: t('report.findings.all'), n: report.findings.length },
    { k: 'fact', label: t('report.findings.facts'), n: count('fact') },
    { k: 'inference', label: t('report.findings.inferences'), n: count('inference') },
    { k: 'gap', label: t('report.findings.gaps'), n: count('gap') },
  ]
  // inferences and gaps first: that is where the owner has to think
  const list = report.findings
    .filter((f) => filter === 'all' || f.kind === filter)
    .slice()
    .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || (findingNo.get(a.id) ?? 0) - (findingNo.get(b.id) ?? 0))
  return (
    <div>
      <div role="group" aria-label={t('report.findings.filter')} className="seg mb-4 flex-wrap">
        {opts.map((o) => (
          <button key={o.k} type="button" aria-pressed={filter === o.k} onClick={() => setFilter(o.k)}>
            {o.label} <span className="tnum">{o.n}</span>
          </button>
        ))}
      </div>
      <ul role="list" className="flex flex-col gap-2 p-0 m-0">
        {list.map((f) => (
          <EvidenceItem
            key={f.id}
            id={`finding-${f.id}`}
            kind={f.kind}
            sources={f.sources}
            head={
              <>
                <KindLabel kind={f.kind} />
                <span className="meta">
                  {t('report.finding', { n: findingNo.get(f.id) ?? 0 })} · {t(`report.section.${f.section}` as I18nKey)}
                </span>
              </>
            }
          >
            <RichText text={pick(f.text, lang)} />
            {(f.based_on?.length ?? 0) > 0 && <BasedOn ids={f.based_on!} findingNo={findingNo} onJump={onJump} />}
          </EvidenceItem>
        ))}
      </ul>
    </div>
  )
}

interface LookItem {
  text: string
  target: string
  label: string
}

/** "Na co se podívat": 1–3 things from round-4 criteria that are not met and claims that conflict
 *  with the record. Facts about the record, never a judgement of the person. */
function lookAtItems(c: Candidate, report: Report, crit: Record<string, Criterion>, t: ReturnType<typeof useApp>['t'], lang: 'cs' | 'en'): LookItem[] {
  const items: LookItem[] = []
  const conflicts = report.claims.filter((k) => k.status === 'conflicts_with_record')
  const comp = groupByPost(report.collab_timeline.filter((e) => e.is_competitor))
  if (comp.length) {
    const handles = [...new Set(comp.map((g) => (g.brand_handle ? `@${g.brand_handle}` : g.brand)))]
    items.push({
      text: t('drawer.lookAt.competitor', { n: comp.length, handles: handles.join(', '), many: handles.length }),
      target: conflicts.length ? 'sec-claims' : 'sec-collabs',
      label: conflicts.length ? t('report.claims') : t('report.collabs'),
    })
  }
  for (const k of conflicts) items.push({ text: t('drawer.lookAt.claim', { claim: k.claim }), target: 'sec-claims', label: t('report.claims') })
  for (const r of c.results) {
    const cr = crit[r.criterion_id]
    if (!cr || cr.round !== 4 || r.waived || r.status === 'pass') continue
    if (cr.kind === 'no_competitor_collab' && comp.length) continue
    items.push({
      text: t(r.status === 'fail' ? 'drawer.lookAt.fail' : 'drawer.lookAt.unknown', { name: pick(cr.label, lang), value: pick(r.value, lang) }),
      target: cr.kind === 'discloses_ads' || cr.kind === 'no_competitor_collab' ? 'sec-collabs' : 'sec-card',
      label: cr.kind === 'discloses_ads' || cr.kind === 'no_competitor_collab' ? t('report.collabs') : t('drawer.candidate'),
    })
  }
  return items.slice(0, 3)
}

// ---------------- drawer ----------------

export function CandidateDrawer() {
  const { state, openId, openCandidate, t, lang, actions } = useApp()
  const c = openId ? state.candidates[openId] : null
  const close = useCallback(() => openCandidate(null), [openCandidate])
  const closeRef = useRef<HTMLButtonElement>(null)
  const ref = useDialog<HTMLDivElement>(!!c, close, { initialFocus: closeRef })
  const bodyRef = useRef<HTMLDivElement>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const crit = useMemo(() => {
    const m: Record<string, Criterion> = {}
    for (const x of state.criteria?.criteria ?? []) m[x.id] = x
    return m
  }, [state.criteria])

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 })
    setFilter('all')
  }, [openId])

  // Status messages from inside the dossier (the funnel's own live region is inert behind it):
  // vetting progress, and "Vráceno do trychtýře" after Vrátit.
  const status = c?.status
  const prevStatus = useRef<{ id: string | null; status?: string }>({ id: null })
  const [said, setSaid] = useState('')
  useEffect(() => {
    const prev = prevStatus.current
    if (prev.id === openId && prev.status === 'eliminated' && status && status !== 'eliminated') setSaid(t('drawer.restored'))
    else if (prev.id !== openId) setSaid('')
    prevStatus.current = { id: openId, status }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId, status])

  if (!c) return null
  const p = c.profile
  const handle = p?.handle ?? c.ref.handle
  const mode = p?.source?.mode ?? c.ref.source?.mode
  const report = c.report
  const elim = c.status === 'eliminated'
  const vetStep = state.vetting[c.id]
  // goal-ordered reports: the same numbers as on the subject board (goal checks are in the candidate card)
  const ranked = !!report && (!!report.sections?.length || report.findings.some((f) => f.tier))
  const findingNo = report && ranked ? displayNumbers(report, SKIP_GOAL) : new Map((report?.findings ?? []).map((f, i) => [f.id, i + 1]))
  const conflict = !!report?.claims.some((k) => k.status === 'conflicts_with_record')

  const goTo = (id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    scrollToEl(el)
    el.querySelector<HTMLElement>('h3')?.focus({ preventScroll: true })
  }
  const jump = (id: string) => {
    if (ranked) return jumpToItem(id, 'drw')
    setFilter('all')
    window.setTimeout(() => {
      const el = document.getElementById(`finding-${id}`)
      if (!el) return
      scrollToEl(el, 'center')
      flashEl(el)
    }, 20)
  }
  const pickKind = (k: FindingKind) => {
    setFilter((f) => (f === k ? 'all' : k))
    window.setTimeout(() => goTo('sec-findings'), 20)
  }

  const hasIdentity = !!report?.identity.some((x) => x.status === 'matched' || x.status === 'uncertain')
  type Sec = { id: string; key: I18nKey; show: boolean }
  const sections: Sec[] = report
    ? ([
        { id: 'sec-card', key: 'drawer.candidate', show: true },
        { id: 'sec-collabs', key: 'report.collabs', show: report.collab_timeline.length > 0 },
        { id: 'sec-claims', key: 'report.claims', show: report.claims.length > 0 },
        { id: 'sec-saturation', key: 'report.saturation', show: true },
        { id: 'sec-news', key: 'report.news', show: report.news.length > 0 },
        { id: 'sec-identity', key: 'report.identity', show: hasIdentity },
        { id: 'sec-findings', key: 'report.findings', show: report.findings.length > 0 },
        { id: 'sec-questions', key: 'report.questions', show: report.questions.length > 0 },
        { id: 'sec-outreach', key: 'report.outreach', show: !!report.outreach_draft },
        { id: 'sec-method', key: 'report.method', show: !!(report.method?.length || Object.keys(report.text_source ?? {}).length) },
        { id: 'sec-notchecked', key: 'report.notChecked', show: true },
      ] satisfies Sec[]).filter((s) => s.show)
    : []
  const num = (id: string) => sections.findIndex((s) => s.id === id)
  const kindN = (k: FindingKind) => report?.findings.filter((f) => f.kind === k).length ?? 0
  const look = report ? lookAtItems(c, report, crit, t, lang) : []
  const fetched = p?.source?.fetched_at ?? c.ref.source?.fetched_at

  const tocLink =
    'inline-flex items-center min-h-8 max-sm:min-h-11 px-2.5 rounded-[6px] text-[13px] leading-[18px] text-[color:var(--text-2)] whitespace-nowrap hover:bg-[color:var(--bg)] hover:text-[color:var(--text)]'

  return (
    <>
      <div className="scrim" onClick={close} />
      <div
        ref={ref}
        className="drawer !w-[min(900px,100vw)] !bg-[color:var(--surface)] !border-[color:var(--line)] !shadow-[0_1px_2px_rgba(24,44,54,.06)]"
        data-testid="candidate-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        tabIndex={-1}
      >
        {/* never scrolls away: the panel kind on the left, Close (also Escape) top right */}
        <div className="flex-none flex items-center justify-between gap-3 min-h-14 px-4 sm:px-6 border-b border-[color:var(--line)] bg-[color:var(--surface)]">
          <span className="text-[13px] leading-[18px] font-semibold text-[color:var(--text-2)]">{report ? t('drawer.dossier') : t('drawer.candidate')}</span>
          <button ref={closeRef} type="button" className="btn max-sm:min-h-11 max-sm:min-w-11" aria-keyshortcuts="Escape" onClick={close}>
            <span aria-hidden>✕</span> {t('drawer.close')}
            <kbd aria-hidden className="max-sm:hidden ml-1 px-1 rounded-[4px] border border-[color:var(--line)] bg-[color:var(--bg)] text-[11px] leading-4 font-sans font-medium text-[color:var(--text-3)]">
              Esc
            </kbd>
          </button>
        </div>

        <div ref={bodyRef} className="relative flex-1 overflow-y-auto scroll-thin px-4 sm:px-6 pb-16 overscroll-contain">
          <div className="pt-6 flex items-start gap-4">
            <span className={`avatar avatar-lg ${elim ? 'elim-id' : ''}`} aria-hidden>
              {initialOf(handle, p?.display_name)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-3 flex-wrap">
                <h2 id="drawer-title" className={`text-[26px] leading-[32px] font-semibold tracking-[-0.01em] text-[color:var(--text)] [overflow-wrap:anywhere] ${elim ? 'elim-id' : ''}`} translate="no">
                  @{handle}
                </h2>
                {/* the same solid MOCK tag as the cards and source chips (dashed is CACHED's shape) */}
                {mode === 'mock' && <MockTag />}
              </div>
              <div className="mt-2 flex items-center gap-x-2 gap-y-1 flex-wrap text-[14px] leading-5 text-[color:var(--text-2)]">
                {p?.display_name && (
                  <span className={elim ? 'elim-id' : ''} translate="no">
                    {p.display_name}
                  </span>
                )}
                {p?.display_name && <span aria-hidden>·</span>}
                <span>{platformLabel(c.ref.platform, t)}</span>
                {p?.followers != null && (
                  <>
                    <span aria-hidden>·</span>
                    <span className="tabular-nums">{t('card.followersN', { n: fmtCompact(p.followers, lang) })}</span>
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
            </div>
          </div>

          {report && (
            <div role="group" aria-label={t('drawer.counts')} className="mt-6 flex flex-wrap gap-2">
              {(['fact', 'inference', 'gap'] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  className="kind-count-btn inline-flex items-center gap-2 min-h-9 max-sm:min-h-11 pl-1.5 pr-3 rounded-[8px] border border-[color:var(--line)] bg-[color:var(--surface)] hover:border-[color:var(--field)] aria-pressed:border-[color:var(--accent)] aria-pressed:bg-[color:var(--accent-tint)]"
                  aria-pressed={filter === k}
                  onClick={() => pickKind(k)}
                >
                  <KindLabel kind={k} />
                  <span className="tabular-nums font-semibold text-[15px] text-[color:var(--text)]">{kindN(k)}</span>
                </button>
              ))}
            </div>
          )}

          {elim && c.elimination && (
            <div className="mt-6 rounded-[8px] border border-[color:var(--field)] px-4 py-3 bg-[color:var(--surface)] flex items-start gap-3 flex-wrap">
              <div className="flex-1 min-w-[220px] max-sm:min-w-0">
                <h3 className={CLS.label}>{t('card.eliminatedIn', { n: c.elimination.round })}</h3>
                <div className="text-[15px] leading-[22px] mt-1">
                  <RichText text={pick(c.elimination.reason, lang)} />
                </div>
                <div className="mt-2 flex gap-1 flex-wrap">
                  <SourceChips sources={c.elimination.sources} />
                </div>
              </div>
              <button type="button" className="btn max-sm:min-h-11" title={t('funnel.restore.title')} onClick={() => actions.restore(c.id, c.elimination!.criterion_id)}>
                <span aria-hidden>↺</span> {t('funnel.restore')}
              </button>
            </div>
          )}
          <div role="status">
            {vetStep ? (
              <p className="mt-3 text-[15px] text-[color:var(--text-2)] flex items-center gap-2">
                <span className="work-dot" aria-hidden />
                {t('drawer.vetting', { step: vetStepLabel(vetStep, lang) })}
              </p>
            ) : (
              said && <p className="mt-3 text-[15px] text-[color:var(--text-2)]">{said}</p>
            )}
          </div>
          {report?.vetted_for && !report.rendered_for && state.criteria?.brief?.business_type && report.vetted_for !== state.criteria.brief.business_type && (
            <div className={`mt-3 flex items-start gap-3 text-[13px] leading-[18px] text-[color:var(--text-2)] px-3 py-2 ${CLS.info}`}>
              <span className="flex-1">{t('report.vettedFor', { goal: report.vetted_for })}</span>
              {c.status === 'finalist' && !vetStep && (
                <button type="button" className="btn btn-sm" onClick={() => actions.vet([c.id])}>
                  {t('report.revet')}
                </button>
              )}
            </div>
          )}

          {report?.rendered_for && <p className="mt-6 text-[18px] leading-[26px] font-semibold">{t('report.for', { goal: goalLabel(report, state.criteria?.brief, t) })}</p>}
          {report && !state.demo && state.criteria?.brief?.lang && state.criteria.brief.lang !== lang && (
            <p className="mt-1 text-[13px] leading-[18px] text-[color:var(--text-2)]" data-testid="report-lang-note">
              {t(state.criteria.brief.lang === 'cs' ? 'report.langNote.cs' : 'report.langNote.en')}
            </p>
          )}
          {report?.last_diff?.summary && state.mode !== 'subject' && (
            <p className={`mt-2 px-3 py-2 text-[13px] leading-[18px] text-[color:var(--text-2)] ${CLS.info}`}>
              <span className="font-semibold text-[color:var(--text)] mr-2">{t('changed.title')}</span>
              <RichText text={pick(report.last_diff.summary, lang)} />
            </p>
          )}
          {report?.identity_verdict && (
            <div className="mt-6">
              <VerdictBlock report={report} idPrefix="drw" />
            </div>
          )}
          {report?.summary && (
            <div className="mt-6">
              <SummaryLine report={report} />
            </div>
          )}

          {report && (
            <section className={`mt-6 p-4 sm:p-5 ${CLS.block}`} aria-labelledby="lookat-h">
              <h3 id="lookat-h" className={CLS.sub}>
                {t('drawer.lookAt')}
              </h3>
              {look.length === 0 ? (
                <p className="text-[15px] text-[color:var(--text-2)] mt-1">{t('drawer.lookAt.none')}</p>
              ) : (
                <ol role="list" className="mt-3 flex flex-col gap-3 list-none p-0 m-0">
                  {look.map((it, i) => (
                    <li key={i} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 text-[15px] leading-[22px]">
                      <span className="text-[13px] leading-[22px] font-semibold tabular-nums text-[color:var(--text-3)]" aria-hidden>
                        {i + 1}
                      </span>
                      <span className="min-w-0">
                        <RichText text={it.text} />{' '}
                        <a
                          href={`#${it.target}`}
                          className="btn-link text-[13px] whitespace-nowrap"
                          onClick={(e) => {
                            e.preventDefault()
                            goTo(it.target)
                          }}
                        >
                          <span aria-hidden>→</span> {it.label}
                        </a>
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}

          {report && (
            <nav
              className="sticky top-0 z-[5] -mx-4 sm:-mx-6 px-4 sm:px-6 mt-6 py-1.5 flex flex-wrap gap-1 max-sm:flex-nowrap max-sm:overflow-x-auto scroll-thin bg-[color:var(--surface)] border-b border-[color:var(--line)]"
              aria-label={t('drawer.toc')}
            >
              {sections.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  className={tocLink}
                  onClick={(e) => {
                    e.preventDefault()
                    // phones: the strip scrolls sideways; keep the chosen section's link in view
                    e.currentTarget.scrollIntoView({ inline: 'center', block: 'nearest' })
                    goTo(s.id)
                  }}
                >
                  {t(s.key)}
                </a>
              ))}
            </nav>
          )}

          <Section id="sec-card" title={t('drawer.candidate')} first={!!report}>
            <CardBody c={c} crit={crit} />
          </Section>

          {!report && <p className="mt-8 text-[15px] text-[color:var(--text-2)]">{t('drawer.noReport')}</p>}

          {report && (
            <>
              {num('sec-collabs') >= 0 && (
                <Section id="sec-collabs" title={t('report.collabs')}>
                  <CollabTimeline items={report.collab_timeline} />
                </Section>
              )}
              {num('sec-claims') >= 0 && (
                <Section id="sec-claims" title={t('report.claims')}>
                  <div className="flex flex-col gap-4">
                    {report.claims.map((k) => (
                      <ClaimCard key={k.id} k={k} report={report} findingNo={findingNo} onJump={jump} />
                    ))}
                  </div>
                </Section>
              )}
              <Section id="sec-saturation" title={t('report.saturation')}>
                <Saturation m={c.metrics} report={report} />
              </Section>
              {num('sec-news') >= 0 && (
                <Section id="sec-news" title={t('report.news')}>
                  <NewsList report={report} />
                </Section>
              )}
              {num('sec-identity') >= 0 && (
                <Section id="sec-identity" title={t('report.identity')}>
                  <IdentityPanel items={report.identity} />
                </Section>
              )}
              {num('sec-findings') >= 0 && (
                <Section id="sec-findings" title={t('report.findings')}>
                  {ranked ? (
                    <RankedFindings report={report} idPrefix="drw" skipGoal goalNote="report.goalChecks.card" />
                  ) : (
                    <Findings report={report} filter={filter} setFilter={setFilter} findingNo={findingNo} onJump={jump} />
                  )}
                </Section>
              )}
              {num('sec-questions') >= 0 && (
                <Section id="sec-questions" title={t('report.questions')}>
                  <ol role="list" className="flex flex-col gap-3 list-none p-0 m-0" data-testid="questions">
                    {report.questions.map((q, i) => (
                      <li key={i} className="grid grid-cols-[24px_minmax(0,1fr)] gap-2 text-[15px] leading-[22px]">
                        <span className="text-[13px] leading-[22px] font-semibold tabular-nums text-[color:var(--text-3)]" aria-hidden>
                          {i + 1}.
                        </span>
                        <span>
                          <RichText text={pick(q, lang)} />
                        </span>
                      </li>
                    ))}
                  </ol>
                </Section>
              )}
              {num('sec-outreach') >= 0 && (
                <Section id="sec-outreach" title={t('report.outreach')}>
                  <Outreach draft={report.outreach_draft} conflict={conflict} onCheck={() => goTo('sec-claims')} />
                </Section>
              )}
              {num('sec-method') >= 0 && (
                <Section id="sec-method" title={t('report.method')}>
                  <MethodPanel report={report} runRequests={state.llmUsage?.total ?? null} />
                </Section>
              )}
              <Section id="sec-notchecked" title={t('report.notChecked')}>
                <ul role="list" className="flex flex-col gap-2 p-0 m-0">
                  {report.not_checked.map((n, i) => (
                    <EvidenceItem key={i} kind="gap" head={<KindLabel kind="gap" />}>
                      <RichText text={pick(n, lang)} />
                    </EvidenceItem>
                  ))}
                </ul>
                {report.skeptic_notes.length > 0 && (
                  <div className="mt-6">
                    <h4 className={`${CLS.sub} mb-2`}>{t('report.skeptic')}</h4>
                    <ul role="list" className="flex flex-col gap-2">
                      {report.skeptic_notes.map((n, i) => (
                        <li key={i} className="text-[15px] leading-[22px] text-[color:var(--text-2)] border-l-2 border-[color:var(--field)] pl-3">
                          <RichText text={pick(n, lang)} />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="mt-6 border border-dashed border-[color:var(--field)] rounded-[8px] px-4 py-3 flex items-center gap-4">
                  <span className="text-[30px] leading-[36px] font-semibold tabular-nums">{report.sensitive_filtered}</span>
                  <div>
                    <h4 className={CLS.label}>{t('report.sensitive')}</h4>
                    <p className="text-[13px] leading-[18px] text-[color:var(--text-2)]">{t('report.sensitive.value', { n: report.sensitive_filtered })}</p>
                  </div>
                </div>
              </Section>
            </>
          )}
        </div>
      </div>
    </>
  )
}
