import { useEffect, useId, useMemo, useState } from 'react'
import { useApp } from '../store'
import { lastFinishedRound } from '../state'
import { fmtCompact, fmtDate, fmtNum, fmtPct, pick, type I18nKey } from '../i18n'
import type { Candidate, Criterion, CriterionResult } from '../types'
import { CritIcon, MockTag, Sourced, Toggle, focusSoon } from './primitives'

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

export function Compare() {
  const { state, t, lang, openCandidate } = useApp()
  const [sortId, setSortId] = useState('')
  const [desc, setDesc] = useState(true)
  const [onlyDiffPref, setOnlyDiff] = useState<boolean | null>(null)
  const narrow = useNarrow()
  const sortSel = useId()

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
    if (!r) return <span className="text-ink-3">{t('card.noData')}</span>
    const full = pick(r.value, lang)
    return (
      <div className="flex items-start gap-1">
        <CritIcon status={r.status} waived={r.waived} label={label(cr)} />
        <Sourced sources={r.sources} caption={`${label(cr)}: ${full}`} className="clamp-2 min-w-0 tnum">
          {short(c, cr, r)}
        </Sourced>
      </div>
    )
  }

  return (
    <section id="compare" className="panel" aria-labelledby="compare-h" data-testid="compare">
      <div className="flex items-end justify-between gap-3 px-4 pt-3 pb-3 flex-wrap">
        <div>
          <h2 id="compare-h" className="font-display text-lg font-semibold">
            {t('compare.title')}
          </h2>
          <p className="text-sm text-ink-2 mt-1">{t('compare.note')}</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {diffCount > 0 ? (
            <>
              <Toggle checked={onlyDiff} onChange={(v) => setOnlyDiff(v)} label={`${t('compare.onlyDiff')} (${diffCount})`} />
              {onlyDiff && (
                <button
                  type="button"
                  className="btn-link text-sm"
                  onClick={() => {
                    setOnlyDiff(false)
                    // this link unmounts: focus stays in the controls, on the switch it just changed
                    focusSoon(() => document.querySelector<HTMLElement>('#compare [role="switch"]'))
                  }}
                >
                  {t('compare.showAll', { n: criteria.length })}
                </button>
              )}
            </>
          ) : (
            <span className="text-sm text-ink-2">{t('compare.noDiff')}</span>
          )}
          <span className="flex items-center gap-2">
            <label className="text-sm text-ink-2" htmlFor={sortSel}>
              {t('compare.sort')}
            </label>
            <select
              id={sortSel}
              data-testid="compare-sort"
              name="sort"
              className="field !w-auto !min-h-8 !py-1 text-sm"
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
              <button type="button" className="btn btn-sm" data-testid="compare-sort-dir" onClick={() => setDesc((v) => !v)} aria-label={t('compare.dirLabel', { dir: desc ? t('compare.desc') : t('compare.asc') })}>
                <span aria-hidden>{desc ? '↓' : '↑'}</span> {desc ? t('compare.desc') : t('compare.asc')}
              </button>
            )}
          </span>
        </div>
      </div>

      {narrow ? (
        // phones: one card per criterion, finalists listed under it
        <div className="px-4 pb-4 flex flex-col gap-3 border-t border-rule pt-3" data-testid="compare-table">
          <ul role="list" className="flex flex-wrap gap-2">
            {rows.map((c) => (
              <li key={c.id}>
                <button type="button" className="btn btn-sm" onClick={() => openCandidate(c.id)}>
                  <span translate="no" className={c.status === 'eliminated' ? 'elim-id' : ''}>
                    @{c.profile?.handle ?? c.ref.handle}
                  </span>
                  {c.report && <span className="text-ink-3">· {t('funnel.openDossier')}</span>}
                </button>
              </li>
            ))}
          </ul>
          {groups.map((g) => (
            <div key={g.round} className="flex flex-col gap-2">
              <h3 className="smallcaps !text-ink-2">{t('compare.group', { n: g.round, name: t(`round.${g.round}` as I18nKey) })}</h3>
              {g.list.map((cr) => (
                <div key={cr.id} className={`sheet p-3 ${sortId === cr.id ? '!bg-accent-soft' : ''}`}>
                  <h4 className="text-base font-semibold">{label(cr)}</h4>
                  <ul role="list" className="mt-2 flex flex-col gap-2">
                    {rows.map((c) => (
                      <li key={c.id} className="grid grid-cols-[120px_1fr] gap-2 text-sm">
                        <span translate="no" title={`@${c.profile?.handle ?? c.ref.handle}`} className={`font-medium truncate ${c.status === 'eliminated' ? 'elim-id' : ''}`}>
                          @{c.profile?.handle ?? c.ref.handle}
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
        <div className="relative overflow-x-auto scroll-thin border-t border-rule">
          <table className="ctable" data-testid="compare-table">
            <thead>
              <tr>
                <th className="min-w-[200px] !left-0 !z-[2]" style={{ position: 'sticky' }} scope="col">
                  {t('compare.criterion')}
                </th>
                {rows.map((c) => {
                  const handle = c.profile?.handle ?? c.ref.handle
                  const elim = c.status === 'eliminated'
                  return (
                    <th key={c.id} className="min-w-[164px]" scope="col">
                      <button type="button" className={`text-left hover:text-accent min-h-6 ${elim ? 'elim-id' : ''}`} onClick={() => openCandidate(c.id)}>
                        <span className="text-base font-semibold text-ink" translate="no">
                          @{handle}
                        </span>
                      </button>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className="meta">{fmtCompact(c.profile?.followers, lang)}</span>
                        {(c.profile?.source?.mode ?? c.ref.source?.mode) === 'mock' && <MockTag />}
                      </div>
                      {c.report && (
                        <button type="button" className="btn btn-sm mt-2 font-normal" onClick={() => openCandidate(c.id)}>
                          <span aria-hidden>▤</span> {t('funnel.openDossier')}
                        </button>
                      )}
                      {elim && c.elimination && <div className="text-sm text-ink-2 mt-1 font-normal">{t('compare.eliminated', { n: c.elimination.round })}</div>}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <GroupRows key={g.round} round={g.round} n={rows.length + 1}>
                  {g.list.map((cr) => (
                    <tr key={cr.id} className={sortId === cr.id ? 'is-sorted' : ''}>
                      <th scope="row">
                        <span className="text-sm">{label(cr)}</span>
                      </th>
                      {rows.map((c) => (
                        <td key={c.id}>{cell(c, cr)}</td>
                      ))}
                    </tr>
                  ))}
                </GroupRows>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function GroupRows({ round, n, children }: { round: number; n: number; children: React.ReactNode }) {
  const { t } = useApp()
  return (
    <>
      <tr className="group-row">
        <th colSpan={n} scope="colgroup" className="smallcaps !text-ink-2 text-left" style={{ position: 'static' }}>
          {t('compare.group', { n: round, name: t(`round.${round}` as I18nKey) })}
        </th>
      </tr>
      {children}
    </>
  )
}
