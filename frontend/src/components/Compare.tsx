import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useApp } from '../store'
import { lastFinishedRound } from '../state'
import { fmtCompact, fmtDate, fmtNum, fmtPct, pick, type I18nKey } from '../i18n'
import type { Candidate, Criterion, CriterionResult } from '../types'
import { Handle, MockTag, Sourced, StatusTag, Toggle, focusSoon } from './primitives'

const COLLAB_KINDS = new Set(['coauthor', 'paid_label', 'meta_branded', 'ad_hashtag', 'discount_code', 'affiliate_link'])

/** Kinds where fewer is better: their default sort direction is ascending. */
const LOWER_FIRST = new Set(['no_competitor_collab', 'discloses_ads', 'max_commercial_share', 'max_generic_comments'])

function postKey(e: { post_id?: string | null; id: string }) {
  return e.post_id ?? e.id
}

/** Numeric value used ONLY when the owner explicitly picks this criterion to sort by. Values come
 *  from data, never from parsing the display text (a "17. 9." date is not a number to sort by). */
function sortValue(c: Candidate, cr: Criterion): number | null {
  const m = c.metrics
  const r = c.results.find((x) => x.criterion_id === cr.id)
  switch (cr.kind) {
    case 'followers_range':
      return c.profile?.followers ?? null
    case 'active_recently':
      return m?.last_post_at ? +new Date(m.last_post_at) : null
    case 'topic_share': {
      const set = Array.isArray(cr.params.topics) ? (cr.params.topics as string[]) : []
      const counts = m?.topic_counts ?? {}
      const total = Object.entries(counts).reduce((a, [k, n]) => a + (k === 'unclassified' ? 0 : n), 0)
      if (!total) return null
      return set.reduce((a, k) => a + (counts[k] ?? 0), 0) / total
    }
    case 'formats': {
      const set = Array.isArray(cr.params.formats) ? (cr.params.formats as string[]) : []
      const total = m?.posts_analyzed ?? 0
      if (!m || !total) return null
      return set.reduce((a, k) => a + (m.formats[k] ?? 0), 0) / total
    }
    case 'post_frequency':
      return m?.posts_per_week ?? null
    case 'max_commercial_share':
      return m?.commercial_share ?? null
    case 'min_engagement':
      return m?.engagement_rate ?? null
    case 'cs_comment_share':
      return m?.cs_comment_share ?? null
    case 'local_signal':
      return m?.local_signals?.length ?? null
    case 'max_generic_comments':
      return m?.generic_comment_share ?? null
    case 'no_competitor_collab': {
      // number of posts with a competitor collaboration (plain mentions do not count)
      const tl = c.report?.collab_timeline
      if (!tl) return null
      return new Set(tl.filter((e) => e.is_competitor && (COLLAB_KINDS.has(e.kind) || e.disclosed !== null)).map(postKey)).size
    }
    case 'discloses_ads': {
      const tl = c.report?.collab_timeline
      if (!tl) return null
      return new Set(tl.filter((e) => e.disclosed === false).map(postKey)).size
    }
    default:
      // yes/no criteria: order by status only (pass, unknown, fail)
      if (!r) return null
      return r.status === 'pass' ? 2 : r.status === 'unknown' ? 1 : 0
  }
}

/** Short cell value: the sentence up to its first bracket or semicolon, at most ~48 characters,
 *  cut at a word boundary. The full sentence is in the source popover. */
function shortValue(v: string): string {
  let s = v.split(/\s[(;]/)[0].trim()
  if (s.length > 48) {
    const cut = s.slice(0, 48)
    s = `${cut.slice(0, Math.max(cut.lastIndexOf(' '), 24))}…`
  }
  return s
}

const statusKey = (r: CriterionResult | undefined) => (r ? (r.waived ? 'waived' : r.status) : 'none')

function useNarrow() {
  const q = '(max-width: 767px)'
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(q).matches)
  useEffect(() => {
    const m = window.matchMedia?.(q)
    if (!m) return
    const on = () => setNarrow(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return narrow
}

/** Whether a horizontally scrollable box has more content to its left / right (for the edge shadows). */
function useScrollEdges(ref: React.RefObject<HTMLDivElement | null>, deps: unknown) {
  const [edges, setEdges] = useState({ left: false, right: false })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => {
      const left = el.scrollLeft > 1
      const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
      setEdges((e) => (e.left === left && e.right === right ? e : { left, right }))
    }
    update()
    el.addEventListener('scroll', update, { passive: true })
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    ro?.observe(el)
    if (el.firstElementChild) ro?.observe(el.firstElementChild)
    return () => {
      el.removeEventListener('scroll', update)
      ro?.disconnect()
    }
  }, [ref, deps])
  return edges
}

export function Compare() {
  const { state, t, lang, openCandidate } = useApp()
  const [sortId, setSortId] = useState('')
  const [desc, setDesc] = useState(true)
  const [onlyDiffPref, setOnlyDiff] = useState<boolean | null>(null)
  const narrow = useNarrow()
  const sortSel = useId()
  const scroller = useRef<HTMLDivElement>(null)

  const criteria = useMemo(() => (state.criteria?.criteria ?? []).filter((c) => c.enabled), [state.criteria])

  const rows = useMemo(() => {
    const all = state.order.map((id) => state.candidates[id]).filter(Boolean)
    const past3 = lastFinishedRound(state) >= 3
    // finalists, everyone still active after round 3, and round-4 failures (shown, not hidden)
    const list = all.filter((c) => c.status === 'finalist' || (past3 && c.status === 'active') || (c.status === 'eliminated' && c.elimination?.round === 4))
    const handle = (c: Candidate) => c.profile?.handle ?? c.ref.handle
    list.sort((a, b) => handle(a).localeCompare(handle(b), 'cs'))
    const cr = criteria.find((c) => c.id === sortId)
    if (cr) {
      list.sort((a, b) => {
        const va = sortValue(a, cr)
        const vb = sortValue(b, cr)
        if (va == null && vb == null) return 0
        if (va == null) return 1
        if (vb == null) return -1
        return desc ? vb - va : va - vb
      })
    }
    return list
  }, [state, criteria, sortId, desc])

  const edges = useScrollEdges(scroller, `${narrow}:${rows.length}`)

  // hidden until there are finalists (empty state)
  if (rows.length === 0) return null

  const result = (c: Candidate, cr: Criterion) => c.results.find((x) => x.criterion_id === cr.id)
  const differs = (cr: Criterion) => new Set(rows.map((c) => statusKey(result(c, cr)))).size > 1
  const diffCount = criteria.filter(differs).length
  const onlyDiff = diffCount > 0 && (onlyDiffPref ?? true)
  const visible = onlyDiff ? criteria.filter(differs) : criteria
  const groups = [4, 3, 2, 1, 0].map((round) => ({ round, list: visible.filter((c) => c.round === round) })).filter((g) => g.list.length)
  const label = (cr: Criterion) => pick(cr.label, lang)

  /** Glyph + a short, comparable value ("1 z 20 postů", "23,4 tis."); the full sentence is in the popover. */
  const short = (c: Candidate, cr: Criterion, r: CriterionResult): string => {
    if (r.status === 'unknown') return shortValue(pick(r.value, lang))
    const v = sortValue(c, cr)
    if (v == null) return shortValue(pick(r.value, lang))
    switch (cr.kind) {
      case 'followers_range':
        return fmtCompact(v, lang)
      case 'active_recently':
        return fmtDate(new Date(v).toISOString(), lang)
      case 'topic_share':
      case 'formats':
      case 'max_commercial_share':
      case 'cs_comment_share':
      case 'max_generic_comments':
        return fmtPct(v, lang)
      case 'min_engagement':
        return fmtPct(v, lang, 1)
      case 'post_frequency':
        return t('compare.cell.perWeek', { n: fmtNum(v, lang) })
      case 'local_signal':
        return t('compare.cell.signals', { n: v })
      case 'no_competitor_collab':
        return t('compare.cell.competitor', { n: v })
      case 'discloses_ads':
        return t('compare.cell.undisclosed', { n: v })
      default:
        return shortValue(pick(r.value, lang))
    }
  }

  const cell = (c: Candidate, cr: Criterion) => {
    const r = result(c, cr)
    if (!r)
      // not checked for this finalist (e.g. not vetted yet): its own dashed neutral tag, glyph + words, never 'cannot verify'
      return (
        <span className="inline-flex items-center gap-1.5 rounded-[4px] border border-dashed border-[color:var(--field,#6F8794)] px-1.5 py-0.5 text-[13px] leading-[18px] font-medium text-[var(--text-2,#435965)]">
          <span aria-hidden>–</span>
          {t('subject.checks.pending')}
        </span>
      )
    const full = pick(r.value, lang)
    // status (icon + word on a small tint) first, the comparable value under it; the value opens its sources
    return (
      <div className="flex min-w-0 flex-col items-start gap-1">
        <StatusTag status={r.status} waived={r.waived} label={label(cr)} />
        <Sourced sources={r.sources} caption={`${label(cr)}: ${full}`} className="min-w-0 tnum [overflow-wrap:anywhere]">
          {short(c, cr, r)}
        </Sourced>
      </div>
    )
  }

  const handleOf = (c: Candidate) => c.profile?.handle ?? c.ref.handle
  const sortedCr = criteria.find((c) => c.id === sortId)
  const dirWord = desc ? t('compare.desc') : t('compare.asc')
  /** Marker on the row the owner sorts by: says it is their choice of order, not a rating. */
  const sortMark = (cr: Criterion) =>
    sortId === cr.id ? (
      <span className="mt-1 flex items-center gap-1 text-[12px] leading-4 font-medium text-[var(--accent,#086B68)]">
        <span aria-hidden>{desc ? '↓' : '↑'}</span>
        {t('compare.sort')} · {dirWord}
      </span>
    ) : null

  const COL_CRIT = 208
  const COL_MIN = 176

  return (
    <section id="compare" className="panel !p-0 min-w-0 max-w-full overflow-hidden" aria-labelledby="compare-h" data-testid="compare">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 p-4 md:p-6 md:pb-4">
        <div className="min-w-0 max-w-[62ch]">
          <h2 id="compare-h" className="text-[20px] leading-7 font-semibold text-[var(--text,#182C36)]">
            {t('compare.title')}
          </h2>
          <p className="mt-1 text-[13px] leading-[18px] text-[var(--text-2,#435965)]">{t('compare.note')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {diffCount > 0 ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Toggle checked={onlyDiff} onChange={(v) => setOnlyDiff(v)} label={`${t('compare.onlyDiff')} (${diffCount})`} />
              {onlyDiff && (
                <button
                  type="button"
                  className="btn-link text-[13px] max-md:min-h-11"
                  onClick={() => {
                    setOnlyDiff(false)
                    // this link unmounts: focus stays in the controls, on the switch it just changed
                    focusSoon(() => document.querySelector<HTMLElement>('#compare [role="switch"]'))
                  }}
                >
                  {t('compare.showAll', { n: criteria.length })}
                </button>
              )}
            </span>
          ) : (
            <span className="text-[13px] leading-[18px] text-[var(--text-2,#435965)]">{t('compare.noDiff')}</span>
          )}
          <span className="flex flex-wrap items-center gap-2">
            <label className="text-[13px] leading-[18px] text-[var(--text-2,#435965)]" htmlFor={sortSel}>
              {t('compare.sort')}
            </label>
            <select
              id={sortSel}
              data-testid="compare-sort"
              name="sort"
              className="field !w-auto max-w-[260px] text-[14px] max-md:!min-h-11"
              value={sortId}
              onChange={(e) => {
                const id = e.target.value
                setSortId(id)
                const kind = criteria.find((c) => c.id === id)?.kind
                setDesc(!(kind && LOWER_FIRST.has(kind)))
              }}
            >
              <option value="">{t('compare.sort.none')}</option>
              {criteria.map((c) => (
                <option key={c.id} value={c.id}>
                  {label(c)}
                </option>
              ))}
            </select>
            {sortId && (
              <button type="button" className="btn !min-h-10 max-md:!min-h-11" data-testid="compare-sort-dir" onClick={() => setDesc((v) => !v)} aria-label={t('compare.dirLabel', { dir: dirWord })}>
                <span aria-hidden>{desc ? '↓' : '↑'}</span> {dirWord}
              </button>
            )}
          </span>
        </div>
      </div>

      {narrow ? (
        // phones: one block per criterion, finalists listed under it (the whole page stays one column)
        <div className="flex flex-col gap-4 border-t border-[var(--line,#DCE4E8)] p-4" data-testid="compare-table">
          <ul role="list" className="flex flex-wrap gap-2">
            {rows.map((c) => (
              <li key={c.id} className="min-w-0 max-w-full">
                <button type="button" className="btn btn-sm min-h-11 max-w-full !whitespace-normal text-left" onClick={() => openCandidate(c.id)}>
                  <span translate="no" className={`font-semibold [overflow-wrap:anywhere] ${c.status === 'eliminated' ? 'elim-id' : ''}`}>
                    <Handle handle={handleOf(c)} />
                  </span>
                  {c.report && <span className="font-normal text-[var(--text-2,#435965)]">· {t('funnel.openDossier')}</span>}
                </button>
              </li>
            ))}
          </ul>
          {groups.map((g) => (
            <div key={g.round} className="flex flex-col gap-2">
              <h3 className="text-[12px] leading-4 font-semibold uppercase tracking-[0.04em] text-[var(--text-3,#5F717B)]">{t('compare.group', { n: g.round, name: t(`round.${g.round}` as I18nKey) })}</h3>
              {g.list.map((cr) => (
                <div
                  key={cr.id}
                  className={`rounded-[12px] border bg-[var(--surface,#FFFFFF)] p-4 ${sortId === cr.id ? 'border-[var(--accent,#086B68)]' : 'border-[var(--line,#DCE4E8)]'}`}
                >
                  <h4 className="text-[15px] leading-[22px] font-semibold text-[var(--text,#182C36)]">{label(cr)}</h4>
                  {sortMark(cr)}
                  <ul role="list" className="mt-3 flex flex-col divide-y divide-[var(--line,#DCE4E8)]">
                    {rows.map((c) => (
                      <li key={c.id} className="grid grid-cols-[minmax(0,40%)_minmax(0,1fr)] gap-3 py-2 text-[14px] leading-5 first:pt-0 last:pb-0">
                        <span translate="no" title={`@${handleOf(c)}`} className={`font-semibold [overflow-wrap:anywhere] ${c.status === 'eliminated' ? 'elim-id' : ''}`}>
                          <Handle handle={handleOf(c)} />
                        </span>
                        {cell(c, cr)}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : (
        // desktop: the table scrolls inside this box (both ways); header row and criterion column stay put
        <div className="relative min-w-0 border-t border-[var(--line,#DCE4E8)]">
          <div
            ref={scroller}
            className="scroll-thin max-h-[min(75vh,820px)] max-w-full overflow-auto focus-visible:outline-offset-[-2px]"
            role="region"
            aria-label={`${t('compare.title')}: ${t('ui.table.scrollHint')}`}
            tabIndex={0}
          >
            <table
              data-testid="compare-table"
              className="w-full table-fixed border-separate border-spacing-0 bg-[var(--surface,#FFFFFF)] text-[14px] leading-5 text-[var(--text,#182C36)] tnum"
              style={{ minWidth: COL_CRIT + rows.length * COL_MIN, maxWidth: COL_CRIT + rows.length * 360 }}
            >
              <colgroup>
                <col style={{ width: COL_CRIT }} />
                {rows.map((c) => (
                  <col key={c.id} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  <th
                    scope="col"
                    className="sticky top-0 left-0 z-[3] border-r border-b border-[var(--line,#DCE4E8)] bg-[var(--bg,#F3F6F8)] px-4 py-3 text-left align-bottom text-[12px] leading-4 font-semibold uppercase tracking-[0.04em] text-[var(--text-3,#5F717B)]"
                  >
                    {t('compare.criterion')}
                  </th>
                  {rows.map((c) => {
                    const elim = c.status === 'eliminated'
                    return (
                      <th key={c.id} scope="col" className="sticky top-0 z-[2] border-b border-[var(--line,#DCE4E8)] bg-[var(--bg,#F3F6F8)] px-4 py-3 text-left align-top font-normal">
                        <button
                          type="button"
                          className={`min-h-6 max-w-full rounded-[4px] text-left text-[16px] leading-[22px] font-semibold text-[var(--text,#182C36)] [overflow-wrap:anywhere] hover:text-[var(--accent,#086B68)] ${elim ? 'elim-id' : ''}`}
                          onClick={() => openCandidate(c.id)}
                        >
                          <span translate="no">
                            <Handle handle={handleOf(c)} />
                          </span>
                        </button>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] leading-4 text-[var(--text-3,#5F717B)] tnum">
                          <span>{t('card.followersN', { n: fmtCompact(c.profile?.followers, lang) })}</span>
                          {(c.profile?.source?.mode ?? c.ref.source?.mode) === 'mock' && <MockTag />}
                        </div>
                        {elim && c.elimination && <div className="mt-1 text-[13px] leading-[18px] text-[var(--text-2,#435965)]">{t('compare.eliminated', { n: c.elimination.round })}</div>}
                        {c.report && (
                          <button type="button" className="btn btn-sm mt-2" onClick={() => openCandidate(c.id)}>
                            {t('funnel.openDossier')}
                          </button>
                        )}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <GroupRows key={g.round} round={g.round} n={rows.length + 1}>
                    {g.list.map((cr) => {
                      const on = sortId === cr.id
                      return (
                        <tr key={cr.id}>
                          <th
                            scope="row"
                            className={`sticky left-0 z-[1] h-14 border-r border-b border-[var(--line,#DCE4E8)] px-4 py-3 text-left align-top font-medium ${
                              on ? 'bg-[var(--accent-tint,#E4F3F0)] shadow-[inset_3px_0_0_var(--accent,#086B68)]' : 'bg-[var(--surface,#FFFFFF)]'
                            }`}
                          >
                            <span className="[overflow-wrap:anywhere]">{label(cr)}</span>
                            {sortMark(cr)}
                          </th>
                          {rows.map((c) => (
                            <td key={c.id} className="h-14 border-b border-[var(--line,#DCE4E8)] px-4 py-3 align-top">
                              {cell(c, cr)}
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </GroupRows>
                ))}
              </tbody>
            </table>
            <span className="sr-only" aria-live="polite">
              {sortedCr ? `${t('compare.sort')}: ${label(sortedCr)}, ${dirWord}` : ''}
            </span>
          </div>
          {/* edge shadows: more finalists to the side (static, only opacity changes) */}
          <span
            aria-hidden
            className={`pointer-events-none absolute top-0 bottom-0 z-[4] w-3 bg-gradient-to-r from-[rgba(24,44,54,.10)] to-transparent transition-opacity duration-[var(--dur-2,200ms)] ${edges.left ? 'opacity-100' : 'opacity-0'}`}
            style={{ left: COL_CRIT }}
          />
          <span
            aria-hidden
            className={`pointer-events-none absolute top-0 right-0 bottom-0 z-[4] w-6 bg-gradient-to-l from-[rgba(24,44,54,.12)] to-transparent transition-opacity duration-[var(--dur-2,200ms)] ${edges.right ? 'opacity-100' : 'opacity-0'}`}
          />
        </div>
      )}
    </section>
  )
}

function GroupRows({ round, n, children }: { round: number; n: number; children: React.ReactNode }) {
  const { t } = useApp()
  return (
    <>
      <tr>
        <th colSpan={n} scope="colgroup" className="border-b border-[var(--line,#DCE4E8)] bg-[var(--surface,#FFFFFF)] px-0 pt-4 pb-2 text-left">
          {/* the label stays visible while the table scrolls sideways */}
          <span className="sticky left-0 inline-block px-4 text-[12px] leading-4 font-semibold uppercase tracking-[0.04em] text-[var(--text-3,#5F717B)]">
            {t('compare.group', { n: round, name: t(`round.${round}` as I18nKey) })}
          </span>
        </th>
      </tr>
      {children}
    </>
  )
}
