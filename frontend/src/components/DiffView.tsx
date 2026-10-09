import { useRef, useState } from 'react'
import { useApp } from '../store'
import { pick } from '../i18n'
import { csTypo } from '../lib/typo'
import type { Brief, Candidate, DiffItem, I18nText, SourceRef } from '../types'
import { NoValue, SourceChips } from './primitives'

interface Resolved {
  id: string
  handle: string
  candidate?: Candidate
  reason?: I18nText | string
  sources?: SourceRef[]
  round?: number
  needsFetch?: boolean
}

function useResolve() {
  const { state } = useApp()
  return (item: DiffItem | string): Resolved => {
    const raw = typeof item === 'string' ? { candidate_id: item } : item
    let id = raw.candidate_id ?? raw.id ?? ''
    let cand: Candidate | undefined = id ? state.candidates[id] : undefined
    if (!cand && raw.handle) {
      cand = Object.values(state.candidates).find((c) => (c.profile?.handle ?? c.ref.handle) === raw.handle)
      if (cand) id = cand.id
    }
    if (!cand && id && !id.includes(':')) {
      cand = Object.values(state.candidates).find((c) => c.ref.handle === id)
      if (cand) id = cand.id
    }
    return {
      id,
      handle: raw.handle ?? cand?.profile?.handle ?? cand?.ref.handle ?? id,
      candidate: cand,
      reason: raw.reason ?? raw.elimination?.reason,
      sources: raw.sources ?? raw.elimination?.sources,
      round: raw.round ?? raw.elimination?.round,
      needsFetch: !!raw.needs_fetch,
    }
  }
}

type Mark = '+' | '−' | '~'

function Group({ title, sub, items, mark, side }: { title: string; sub: string; items: Resolved[]; mark: Mark; side: 'old' | 'new' | 'both' }) {
  const { t, lang, openCandidate, state } = useApp()
  const diff = state.diff
  return (
    <div className="min-w-0">
      <h3 className="flex items-start gap-2">
        <span className="inline-flex items-center justify-center w-5 h-5 mt-[1px] flex-none rounded-[4px] border border-[color:var(--field)] text-[14px] leading-none font-semibold text-[color:var(--text-2)]" aria-hidden>
          {mark}
        </span>
        <span className="min-w-0 text-[16px] leading-[22px] font-semibold text-[color:var(--text)]">
          {title} <span className="tabular-nums text-[color:var(--text-2)] whitespace-nowrap">{items.length}</span>
        </span>
      </h3>
      <p className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1 mb-3 ml-7">{sub}</p>
      {items.length === 0 && <p className="text-[13px] leading-[18px] text-[color:var(--text-3)] ml-7">{t('diff.empty')}</p>}
      <ul role="list" className="flex flex-col ml-7">
        {items.map((r) => {
          // reason: from the diff item; for "only the original goal" fall back to the elimination stored before the goal change
          const fallback = side === 'old' ? diff?.eliminationsA[r.id] : side === 'new' ? r.candidate?.elimination : null
          const reason = r.reason ?? fallback?.reason
          const sources = r.sources ?? fallback?.sources ?? []
          const nowElim = r.candidate?.status === 'eliminated'
          return (
            <li key={r.id} className="py-2 border-b border-[color:var(--line)] last:border-b-0 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  translate="no"
                  className={`text-[15px] leading-[22px] font-semibold min-h-6 text-left [overflow-wrap:anywhere] hover:text-[color:var(--accent)] ${nowElim ? 'elim-id' : ''} ${side === 'new' ? 'line-through decoration-[color:var(--text-3)]' : ''}`}
                  onClick={() => r.candidate && openCandidate(r.id)}
                >
                  @{r.handle}
                </button>
                {sources.length > 0 && <SourceChips sources={sources} />}
              </div>
              {reason && side !== 'both' && (
                <div className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1">
                  {/* a creator back in the funnel: the stored reason is the OLD one, never a reason against them now */}
                  {side === 'old' && <span className="text-[color:var(--text-3)] mr-1">{lang === 'cs' ? 'Dříve vyřazeno ·' : 'Previously out ·'}</span>}
                  {r.round != null && <span className="text-[color:var(--text-3)] mr-1">{t('criteria.round', { n: r.round })}:</span>}
                  {pick(reason as I18nText, lang).replace(/^(Kolo|Round)\s\d+: /, '')}
                </div>
              )}
              {r.needsFetch && <div className="text-[13px] leading-[18px] text-[color:var(--text-2)] mt-1">{t('diff.needsFetch')}</div>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function briefShort(b: Brief | null, lang: 'cs' | 'en', none: string) {
  const s = b?.business_type
  if (!s) return none
  return lang === 'cs' ? csTypo(s) : s
}
function BriefShort({ b, lang }: { b: Brief | null; lang: 'cs' | 'en' }) {
  return b?.business_type ? <>{briefShort(b, lang, '')}</> : <NoValue />
}

export function DiffView() {
  const { state, t, dispatch, lang } = useApp()
  const resolve = useResolve()
  const [all, setAll] = useState(false)
  const d = state.diff
  // one soft pulse per change (motion contract .m-flash): a new diff remounts the panel; the final diff that
  // replaces a provisional one in place keeps the same panel, so it does not pulse a second time
  const shown = useRef<string | null>(null)
  if (!d) {
    shown.current = null
    return null
  }
  const panelKey = d.replacedKey && shown.current ? shown.current : `${d.kind}:${d.at}`
  shown.current = panelKey
  const dropped = d.dropped.map(resolve)
  const returned = d.returned.map(resolve)
  const changed = new Set([...dropped, ...returned].map((r) => r.id))
  // passed under both: not eliminated before the change, not eliminated now
  const both: Resolved[] =
    d.kind === 'goal'
      ? state.order
          .filter((id) => !changed.has(id) && state.candidates[id] && state.candidates[id].status !== 'eliminated' && !d.eliminationsA[id])
          .map((id) => resolve(id))
      : []

  return (
    <section
      key={panelKey}
      id="diff"
      className="m-flash bg-[color:var(--surface)] border border-[color:var(--line)] rounded-[12px] shadow-[0_1px_2px_rgba(24,44,54,.06)]"
      aria-labelledby="diff-h"
      data-testid="what-changed-discovery"
    >
      <div className="flex items-start justify-between gap-3 px-4 sm:px-6 pt-4 sm:pt-5 pb-3 flex-wrap">
        {d.kind === 'goal' ? (
          <h2 id="diff-h" className="text-[20px] leading-[28px] font-semibold text-[color:var(--text)] min-w-0 [overflow-wrap:anywhere]" aria-label={t('diff.titleLabel', { from: briefShort(d.goalA, lang, t('noValue')), to: briefShort(d.goalB, lang, t('noValue')) })}>
            {t('changed.title')}:{' '}
            <s className="text-[color:var(--text-2)] font-normal decoration-1">
              <BriefShort b={d.goalA} lang={lang} />
            </s>{' '}
            <span aria-hidden>→</span> <BriefShort b={d.goalB} lang={lang} />
          </h2>
        ) : (
          <h2 id="diff-h" className="text-[20px] leading-[28px] font-semibold text-[color:var(--text)]">
            {t('diff.recompute')}
          </h2>
        )}
        <div className="flex items-center gap-2 flex-wrap">
          <button type="button" className="btn btn-sm max-sm:min-h-11" aria-expanded={all} aria-controls="diff-body" onClick={() => setAll((v) => !v)}>
            {all ? t('diff.showLess') : t('diff.showAll')}
          </button>
          <button type="button" className="btn btn-sm btn-ghost max-sm:min-h-11" onClick={() => dispatch({ type: 'diff.dismiss' })}>
            {t('diff.dismiss')}
          </button>
        </div>
      </div>
      {!!d.waiversDropped?.length && (
        <p className="px-4 sm:px-6 pb-3 text-[13px] leading-[18px] text-[color:var(--text-2)]">
          {t('diff.waiversDropped')}{' '}
          {d.waiversDropped.map((w, i) => (
            <span key={`${w.candidate_id}:${w.criterion_id}`}>
              {i > 0 && ', '}
              <span translate="no" className={state.candidates[w.candidate_id]?.status === 'eliminated' ? 'elim-id font-medium' : 'font-medium'}>
                @{w.handle}
              </span>{' '}
              ({pick(state.criteria?.criteria.find((c) => c.id === w.criterion_id)?.label ?? w.criterion_id, lang)})
            </span>
          ))}
        </p>
      )}
      <div id="diff-body" className={`px-4 sm:px-6 pb-4 sm:pb-6 pt-4 border-t border-[color:var(--line)] ${all ? '' : 'max-h-[320px] overflow-y-auto scroll-thin'}`} tabIndex={all ? undefined : 0} role={all ? undefined : 'group'} aria-label={all ? undefined : t('diff.title')}>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-x-8 gap-y-6">
          {d.kind === 'goal' ? (
            <>
              <Group title={t('diff.onlyNew')} sub={t('diff.onlyNew.sub')} items={dropped} mark="−" side="new" />
              <Group title={t('diff.both')} sub={t('diff.both.sub')} items={both} mark="~" side="both" />
              <Group title={t('diff.onlyOld')} sub={t('diff.onlyOld.sub')} items={returned} mark="+" side="old" />
            </>
          ) : (
            <>
              <Group title={t('diff.dropped')} sub={t('diff.dropped.sub')} items={dropped} mark="−" side="new" />
              <Group title={t('diff.returned')} sub={t('diff.returned.sub')} items={returned} mark="+" side="old" />
            </>
          )}
        </div>
      </div>
    </section>
  )
}
