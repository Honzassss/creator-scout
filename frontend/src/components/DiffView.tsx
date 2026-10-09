import { useState } from 'react'
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
      <h3 className="flex items-baseline gap-2">
        <span className="num text-md text-ink-2 w-4 text-center" aria-hidden>
          {mark}
        </span>
        <span className="text-base font-semibold">{title}</span>
        <span className="tnum text-ink-2">{items.length}</span>
      </h3>
      <p className="text-sm text-ink-2 mb-2 ml-6">{sub}</p>
      {items.length === 0 && <p className="text-sm text-ink-3 ml-6">{t('diff.empty')}</p>}
      <ul role="list" className="flex flex-col gap-2 ml-6">
        {items.map((r) => {
          // reason: from the diff item; for "only the original goal" fall back to the elimination stored before the goal change
          const fallback = side === 'old' ? diff?.eliminationsA[r.id] : side === 'new' ? r.candidate?.elimination : null
          const reason = r.reason ?? fallback?.reason
          const sources = r.sources ?? fallback?.sources ?? []
          const nowElim = r.candidate?.status === 'eliminated'
          return (
            <li key={r.id} className="lane-item border-b border-dotted border-rule-strong pb-2">
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  translate="no"
                  className={`font-semibold min-h-6 hover:text-accent ${nowElim ? 'elim-id' : ''} ${side === 'new' ? 'line-through decoration-ink-3' : ''}`}
                  onClick={() => r.candidate && openCandidate(r.id)}
                >
                  @{r.handle}
                </button>
                {sources.length > 0 && <SourceChips sources={sources} />}
              </div>
              {reason && side !== 'both' && (
                <div className="text-sm text-ink-2 mt-1">
                  {r.round != null && <span className="text-ink-3 mr-1">{t('criteria.round', { n: r.round })}:</span>}
                  {pick(reason as I18nText, lang).replace(/^(Kolo|Round)\s\d+: /, '')}
                </div>
              )}
              {r.needsFetch && <div className="text-sm text-ink-2 italic mt-1">{t('diff.needsFetch')}</div>}
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
  if (!d) return null
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
    <section id="diff" className="panel border-ink-2" aria-labelledby="diff-h" data-testid="what-changed-discovery">
      <div className="flex items-start justify-between gap-3 px-4 pt-3 pb-2 flex-wrap">
        {d.kind === 'goal' ? (
          <h2 id="diff-h" className="font-display text-lg font-semibold" aria-label={t('diff.titleLabel', { from: briefShort(d.goalA, lang, t('noValue')), to: briefShort(d.goalB, lang, t('noValue')) })}>
            {t('diff.title')}:{' '}
            <s className="text-ink-2 decoration-1">
              <BriefShort b={d.goalA} lang={lang} />
            </s>{' '}
            <span aria-hidden>→</span> <BriefShort b={d.goalB} lang={lang} />
          </h2>
        ) : (
          <h2 id="diff-h" className="font-display text-lg font-semibold">
            {t('diff.recompute')}
          </h2>
        )}
        <div className="flex items-center gap-2">
          <button type="button" className="btn btn-sm" aria-expanded={all} aria-controls="diff-body" onClick={() => setAll((v) => !v)}>
            {all ? t('diff.showLess') : t('diff.showAll')}
          </button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => dispatch({ type: 'diff.dismiss' })}>
            {t('diff.dismiss')}
          </button>
        </div>
      </div>
      {!!d.waiversDropped?.length && (
        <p className="px-4 pb-2 text-sm text-ink-2">
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
      <div id="diff-body" className={`px-4 pb-4 ${all ? '' : 'max-h-[300px] overflow-y-auto scroll-thin'}`} tabIndex={all ? undefined : 0} role={all ? undefined : 'group'} aria-label={all ? undefined : t('diff.title')}>
        <div className="grid md:grid-cols-3 gap-6">
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
