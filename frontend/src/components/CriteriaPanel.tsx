import { useEffect, useId, useRef, useState } from 'react'
import { useApp } from '../store'
import { fmtNum, fmtPct, fmtRange, hasKey, pick, translate, type I18nKey } from '../i18n'
import { runStarted } from '../state'
import { csTypo } from '../lib/typo'
import { useDialog } from '../lib/useDialog'
import { DiscardBar, focusSoon, useDiscardGuard } from './primitives'
import { ResultsSummary } from './Funnel'
import type { Brief, Criterion, CriterionParams, Lang, ParamValue } from '../types'

export const TOPICS = [
  'food',
  'recipes',
  'restaurants_cafes',
  'local_tips',
  'family',
  'lifestyle',
  'fitness',
  'sport',
  'fashion',
  'beauty',
  'travel',
  'tech',
  'gaming',
  'music',
  'humor',
  'education',
  'other',
] as const
const FORMATS = ['reel', 'video', 'photo', 'carousel'] as const

const isShareKey = (k: string) => /share|rate|ratio/i.test(k)
const NUMERIC_KEYS = new Set(['min', 'max', 'days', 'min_count', 'max_undisclosed', 'min_per_week', 'months', 'min_signals'])

/** Short value for a criterion chip: "5–50 tis.", "≤ 30 dní", "≥ 1× týdně", "≥ 20 %". */
export function paramSummary(c: Criterion, lang: Lang, brief?: Brief | null): string {
  const p = c.params ?? {}
  const n = (k: string) => (typeof p[k] === 'number' ? (p[k] as number) : null)
  const typo = (s: string) => (lang === 'cs' ? csTypo(s) : s)
  switch (c.kind) {
    case 'followers_range':
      return fmtRange(n('min'), n('max'), lang)
    case 'active_recently': {
      const d = n('days')
      if (d == null) return ''
      return typo(lang === 'cs' ? `≤ ${d} ${d === 1 ? 'den' : d >= 2 && d <= 4 ? 'dny' : 'dní'}` : `≤ ${d} days`)
    }
    case 'language_cs':
    case 'cs_comment_share':
    case 'topic_share':
    case 'formats':
      return n('min_share') != null ? typo(`≥ ${fmtPct(n('min_share'), lang)}`) : ''
    case 'post_frequency':
      return n('min_per_week') != null ? typo(`≥ ${fmtNum(n('min_per_week'), lang)}× ${translate(lang, 'unit.perWeek')}`) : ''
    case 'max_commercial_share':
    case 'max_generic_comments':
      return n('max_share') != null ? typo(`≤ ${fmtPct(n('max_share'), lang)}`) : ''
    case 'min_engagement':
      return n('min_rate') != null ? typo(`≥ ${fmtPct(n('min_rate'), lang, 1)}`) : ''
    case 'local_signal':
      return typeof p.city === 'string' ? p.city : (brief?.city ?? '')
    case 'no_competitor_collab': {
      const handles = Array.isArray(p.competitors) ? (p.competitors as string[]) : (brief?.competitors ?? []).flatMap((x) => x.handles ?? [])
      return handles.map((h) => `@${h}`).join(' ')
    }
    case 'discloses_ads': {
      const m = n('max_undisclosed')
      return m != null && m > 0 ? typo(`≤ ${m}`) : ''
    }
    default: {
      const first = Object.entries(p).find(([, v]) => typeof v === 'number' || typeof v === 'string')
      if (!first) return ''
      const [k, v] = first
      return typeof v === 'number' && isShareKey(k) ? typo(fmtPct(v, lang)) : String(v)
    }
  }
}

function paramLabel(k: string, kind: string, t: ReturnType<typeof useApp>['t']): string {
  const specific = `param.${k}.${kind}`
  if (hasKey(specific)) return t(specific)
  const generic = `param.${k}`
  return hasKey(generic) ? t(generic) : t('param.other')
}

function unitKey(k: string, kind: string): I18nKey | null {
  if (isShareKey(k)) return 'criteria.unit.pct'
  if (k === 'days') return 'criteria.unit.days'
  if (k === 'min_per_week') return 'criteria.unit.perWeek'
  if (kind === 'followers_range' && (k === 'min' || k === 'max')) return 'criteria.unit.followers'
  if (k === 'competitors') return 'criteria.unit.handles'
  if (NUMERIC_KEYS.has(k)) return 'criteria.unit.count'
  return null
}

const unitSuffix = (k: string, lang: Lang) => (isShareKey(k) ? '%' : k === 'days' ? (lang === 'cs' ? 'dní' : 'days') : k === 'min_per_week' ? (lang === 'cs' ? '× týdně' : '× a week') : '')

function ToggleGroup({
  labelId,
  options,
  value,
  onChange,
  labelOf,
}: {
  labelId: string
  options: readonly string[]
  value: string[]
  onChange: (v: string[]) => void
  labelOf: (o: string) => string
}) {
  const set = new Set(value)
  return (
    <div role="group" aria-labelledby={labelId} className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = set.has(o)
        return (
          <button
            key={o}
            type="button"
            className={`chip !min-h-8 max-md:!min-h-11 ${on ? '!border-accent !bg-accent-tint !text-accent font-medium' : ''}`}
            aria-pressed={on}
            onClick={() => {
              const next = new Set(set)
              if (on) next.delete(o)
              else next.add(o)
              onChange(options.filter((x) => next.has(x)))
            }}
          >
            {on && <span aria-hidden>✓</span>}
            {labelOf(o)}
          </button>
        )
      })}
    </div>
  )
}

function CriterionEditor({ c, onClose }: { c: Criterion; onClose: () => void }) {
  const { t, lang, state, actions } = useApp()
  const uid = useId()
  const [params, setParams] = useState<CriterionParams>({ ...c.params })
  const numericKeys = Object.entries(c.params)
    .filter(([k, v]) => typeof v === 'number' || (v == null && NUMERIC_KEYS.has(k)))
    .map(([k]) => k)
  const [drafts, setDrafts] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {}
    for (const k of numericKeys) {
      const v = c.params[k] as number | null
      out[k] = v == null ? '' : isShareKey(k) ? fmtNum(Math.round(v * 1000) / 10, lang) : String(v)
    }
    return out
  })
  const [errors, setErrors] = useState<Record<string, boolean>>({})
  const [enabled, setEnabled] = useState(c.enabled)
  // Escape / scrim with unsaved edits asks first ("Zrušit" closes at once)
  const initial = useRef(JSON.stringify({ params, drafts, enabled }))
  const guard = useDiscardGuard(JSON.stringify({ params, drafts, enabled }) !== initial.current, onClose)
  const ref = useDialog<HTMLDivElement>(true, guard.request)
  const titleId = `${uid}-title`

  const save = () => {
    if (!state.criteria) return
    const nextParams: CriterionParams = { ...params }
    const errs: Record<string, boolean> = {}
    for (const k of numericKeys) {
      const raw = (drafts[k] ?? '').trim().replace(/\s/g, '').replace(',', '.')
      if (raw === '') {
        nextParams[k] = null
        continue
      }
      const num = Number(raw)
      if (Number.isNaN(num)) {
        errs[k] = true
        continue
      }
      nextParams[k] = isShareKey(k) ? num / 100 : num
    }
    setErrors(errs)
    const bad = Object.keys(errs)[0]
    if (bad) {
      document.getElementById(`${uid}-${bad}`)?.focus()
      return
    }
    actions.saveCriteria({
      ...state.criteria,
      criteria: state.criteria.criteria.map((x) => (x.id === c.id ? { ...x, params: nextParams, enabled } : x)),
    })
    onClose()
  }

  const field = (k: string, v: ParamValue) => {
    const id = `${uid}-${k}`
    const labelId = `${id}-l`
    const unit = unitKey(k, c.kind)
    const unitId = unit ? `${id}-u` : undefined
    const label = paramLabel(k, c.kind, t)
    if (k === 'topics' && Array.isArray(v))
      return (
        <div key={k}>
          <span id={labelId} className="label">
            {label}
          </span>
          <ToggleGroup labelId={labelId} options={TOPICS} value={v as string[]} onChange={(nv) => setParams((p) => ({ ...p, [k]: nv }))} labelOf={(o) => t(`topic.${o}` as I18nKey)} />
        </div>
      )
    if (k === 'formats' && Array.isArray(v))
      return (
        <div key={k}>
          <span id={labelId} className="label">
            {label}
          </span>
          <ToggleGroup labelId={labelId} options={FORMATS} value={v as string[]} onChange={(nv) => setParams((p) => ({ ...p, [k]: nv }))} labelOf={(o) => t(`format.${o}` as I18nKey)} />
        </div>
      )
    if (typeof v === 'boolean')
      return (
        <label key={k} htmlFor={id} className="flex items-center gap-2 min-h-8 text-base">
          <input id={id} name={k} type="checkbox" checked={v} onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.checked }))} />
          {label}
        </label>
      )
    if (numericKeys.includes(k)) {
      const errId = `${id}-e`
      const noLimit = v == null || k === 'max'
      const describedBy = [unitId, errors[k] ? errId : null, noLimit ? `${id}-n` : null].filter(Boolean).join(' ') || undefined
      return (
        <div key={k}>
          <label htmlFor={id} className="label">
            {label}
          </label>
          <div className="flex items-center gap-2">
            <input
              id={id}
              name={k}
              className="field tnum w-36"
              type="text"
              inputMode={isShareKey(k) || k === 'min_per_week' ? 'decimal' : 'numeric'}
              autoComplete="off"
              value={drafts[k] ?? ''}
              aria-describedby={describedBy}
              aria-invalid={errors[k] || undefined}
              onChange={(e) => setDrafts((d) => ({ ...d, [k]: e.target.value }))}
            />
            {unitSuffix(k, lang) && (
              <span className="text-base text-text-2" aria-hidden>
                {unitSuffix(k, lang)}
              </span>
            )}
            {unit && (
              <span id={unitId} className="sr-only">
                {t(unit)}
              </span>
            )}
          </div>
          {noLimit && (
            <span id={`${id}-n`} className="block text-sm text-text-3 mt-1">
              {t('criteria.noLimit')}
            </span>
          )}
          {errors[k] && (
            <span id={errId} className="block text-sm text-bad mt-1">
              {t('criteria.error.number')}
            </span>
          )}
        </div>
      )
    }
    if (Array.isArray(v))
      return (
        <div key={k}>
          <label htmlFor={id} className="label">
            {label}
          </label>
          <input
            id={id}
            name={k}
            className="field"
            autoComplete="off"
            aria-describedby={unitId}
            value={(v as (string | number)[]).map((x) => (k === 'competitors' ? `@${x}` : x)).join(', ')}
            onChange={(e) =>
              setParams((p) => ({
                ...p,
                [k]: e.target.value
                  .split(',')
                  .map((x) => x.trim().replace(/^@/, ''))
                  .filter(Boolean),
              }))
            }
          />
          {unit && (
            <span id={unitId} className="block text-sm text-text-3 mt-1">
              {t(unit)}
            </span>
          )}
        </div>
      )
    return (
      <div key={k}>
        <label htmlFor={id} className="label">
          {label}
        </label>
        <input
          id={id}
          name={k}
          className="field"
          autoComplete="off"
          value={v == null ? '' : String(v)}
          placeholder={k === 'city' ? (state.criteria?.brief?.city ?? '') : undefined}
          onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value || null }))}
        />
      </div>
    )
  }

  return (
    <>
      <div className="scrim !z-50" onClick={guard.request} />
      <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <div className="px-6 pt-6 pb-4 border-b border-line">
          <div className="text-sm font-semibold text-text-2">
            {t('criteria.edit')} · {t('criteria.round', { n: c.round })} {t(`round.${c.round}` as I18nKey)}
          </div>
          <h2 id={titleId} className="text-lg font-semibold mt-1">
            {pick(c.label, lang)}
          </h2>
          <p className="text-base text-text-2 mt-2">
            <span className="font-medium text-text">{t('criteria.why')}: </span>
            {pick(c.why, lang)}
          </p>
        </div>
        <div className="px-6 py-4 flex flex-col gap-4">
          <label htmlFor={`${uid}-enabled`} className="flex items-center gap-2 min-h-8 text-base font-medium">
            <input id={`${uid}-enabled`} name="enabled" type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            {t('criteria.enabled')}
          </label>
          {Object.keys(params).length > 0 && (
            <fieldset className="flex flex-col gap-4 border-0 p-0 m-0">
              <legend className="text-sm font-semibold text-text-2 mb-2">{t('criteria.params')}</legend>
              {Object.entries(params).map(([k, v]) => field(k, v))}
            </fieldset>
          )}
        </div>
        <DiscardBar guard={guard} />
        <div className="px-6 py-3 border-t border-line flex justify-end gap-2 bg-bg" hidden={guard.asking}>
          <button type="button" className="btn" onClick={onClose}>
            {t('criteria.cancel')}
          </button>
          <button type="submit" className="btn btn-primary">
            {state.runId ? t('criteria.save') : t('criteria.saveLocal')}
          </button>
        </div>
      </form>
      </div>
    </>
  )
}

/** The short value, or '' when the label already states it ("At most 30% ads" + "≤ 30%" says it twice). */
function summaryBeyondLabel(label: string, raw: string): string {
  if (!raw) return ''
  const norm = (x: string) => x.toLowerCase().replace(/\s/g, '')
  if (norm(label).includes(norm(raw))) return ''
  const num = (x: string) => parseFloat(x.replace(',', '.'))
  const nums = raw.match(/\d+(?:[.,]\d+)?/g)
  const inLabel = label.match(/\d+(?:[.,]\d+)?/g) ?? []
  if (nums && nums.every((n) => inLabel.some((m) => num(m) === num(n)))) return ''
  return raw
}

function CritChip({ c, onEdit }: { c: Criterion; onEdit: (c: Criterion) => void }) {
  const { t, lang, state, actions } = useApp()
  const name = pick(c.label, lang)
  const summary = summaryBeyondLabel(name, paramSummary(c, lang, state.criteria?.brief))
  const body = (
    <>
      <span className="label">
        {name}
        {summary && (
          <>
            : <span className="param">{summary}</span>
          </>
        )}
      </span>
      <span className="pen" aria-hidden>
        ✎
      </span>
    </>
  )
  if (c.enabled)
    return (
      <button type="button" className="chip" data-testid="criterion-chip" data-crit={c.id} onClick={() => onEdit(c)} title={pick(c.why, lang)} aria-label={`${name}${summary ? `: ${summary}` : ''}, ${t('criteria.edit').toLowerCase()}`}>
        {body}
      </button>
    )
  // turned off: stays in place, struck through, with "Zapnout" (row height does not change)
  return (
    <span className="chip off !pr-1" data-testid="criterion-chip" data-crit={c.id} data-off="true">
      <button type="button" className="inline-flex items-center gap-1 text-left" onClick={() => onEdit(c)} aria-label={t('criteria.editNamed', { name })}>
        {body}
        <span className="sr-only">({t('criteria.disabled')})</span>
      </button>
      <button
        type="button"
        className="btn btn-sm btn-ghost !min-h-6 text-accent"
        aria-label={t('criteria.enableNamed', { name })}
        onClick={() => {
          if (!state.criteria) return
          actions.saveCriteria({ ...state.criteria, criteria: state.criteria.criteria.map((x) => (x.id === c.id ? { ...x, enabled: true } : x)) })
          // this button disappears with the "off" state: focus moves to the restored chip, not <body>
          window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`button.chip[data-crit="${CSS.escape(c.id)}"]`)?.focus())
        }}
      >
        {t('criteria.enable')}
      </button>
    </span>
  )
}

export function CriteriaPanel() {
  const { state, t, lang, actions } = useApp()
  const [editing, setEditing] = useState<Criterion | null>(null)
  const [expandedOverride, setExpanded] = useState<boolean | null>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const cs = state.criteria
  const started = runStarted(state)

  // a new run collapses the panel again
  useEffect(() => setExpanded(null), [state.runId])

  // "Run rounds 0–3" unmounts only once the run exists (create-run can be slow): focus moves to the
  // panel toggle when it mounts, never to the pre-run funnel heading, which is replaced right after
  const focusToggle = useRef(false)
  useEffect(() => {
    if (!started || !focusToggle.current) return
    focusToggle.current = false
    focusSoon(() => toggleRef.current, 20)
  }, [started])

  if (!cs)
    return (
      <>
        <ResultsSummary />
        <section id="criteria" className="panel" aria-labelledby="crit-h">
          <h2 id="crit-h" className="text-lg font-semibold">
            {t('criteria.title')}
          </h2>
          <p className="text-base text-text-2 mt-1">{t('criteria.empty')}</p>
        </section>
      </>
    )

  const collapsed = started && expandedOverride !== true
  const rounds = [1, 2, 3, 4]
  const d = cs.discovery ?? {}
  const via = [...(d.hashtags ?? []).map((h) => `#${h}`), ...(d.keywords ?? []).map((k) => (lang === 'cs' ? `„${k}“` : `“${k}”`)), ...(d.places ?? [])]
  const enabledN = cs.criteria.filter((c) => c.enabled).length
  const offN = cs.criteria.length - enabledN
  const brief = cs.brief
  const briefBits = ([brief?.business_type, brief?.city, brief?.goal].filter(Boolean) as string[]).map((b) => (lang === 'cs' ? csTypo(b.replace(/\.$/, '')) : b.replace(/\.$/, '')))
  const showStart = !state.runId && !state.demo && !started

  return (
    <>
      <ResultsSummary />
      <section id="criteria" className="panel" aria-labelledby="crit-h">
        {/* title left, the existing edit action right; the summary of active conditions sits below */}
        <div className="flex items-start gap-x-3 gap-y-2 flex-wrap">
          <div className="min-w-0 flex-1">
            <h2 id="crit-h" className="text-lg font-semibold">
              {t('criteria.title')}
              <span className="sr-only">, {t('criteria.enabledN', { n: enabledN })}</span>
              <span className="m-num text-base font-normal text-text-2 ml-2" aria-hidden>
                {enabledN}
              </span>
            </h2>
            {briefBits.length > 0 && (
              <p className="text-sm text-text-2 mt-0.5">
                {briefBits.map((b, i) => (
                  <span key={i}>
                    {i > 0 && (
                      <span aria-hidden className="text-text-3 mx-1">
                        ·
                      </span>
                    )}
                    {i > 0 && <span className="sr-only">, </span>}
                    <span className={i === 2 ? 'italic' : undefined}>{b}</span>
                  </span>
                ))}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 ml-auto flex-wrap justify-end">
            {state.recomputing && <span className="text-sm text-text-2 max-md:hidden">{t('criteria.recomputing')}</span>}
            {showStart && (
              <button
                type="button"
                className="btn btn-primary"
                data-testid="run-rounds"
                onClick={() => {
                  // this button unmounts once the run starts: focus then goes to the panel toggle (effect above)
                  focusToggle.current = true
                  actions.startRun()
                }}
                title={t('criteria.startRun.hint')}
              >
                {t('criteria.startRun')}
              </button>
            )}
            {started && (
              <button
                ref={toggleRef}
                type="button"
                className="btn btn-sm"
                aria-expanded={!collapsed}
                aria-controls="crit-body"
                aria-label={collapsed ? t('criteria.expandLabel') : t('criteria.collapseLabel')}
                onClick={() => setExpanded(collapsed)}
              >
                {collapsed ? t('criteria.expand') : t('criteria.collapse')}
              </button>
            )}
          </div>
        </div>

        {/* collapsed: a short, readable summary of the active conditions, one line per round, wrapping */}
        {collapsed && (
          <dl className="mt-3 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 max-sm:grid-cols-1 max-sm:gap-y-0.5">
            {rounds.map((r) => {
              const list = cs.criteria.filter((c) => c.round === r && c.enabled)
              if (!list.length) return null
              return (
                <div key={r} className="contents">
                  <dt className="text-sm font-semibold text-text-2 max-sm:mt-1.5">
                    {t('criteria.round', { n: r })} · {t(`round.${r}` as I18nKey)}
                  </dt>
                  <dd className="m-0 text-sm text-text min-w-0 [overflow-wrap:anywhere]">
                    {list.map((c, i) => {
                      const label = pick(c.label, lang)
                      // "Active in last 30 days ≤ 30 days" says it twice: add the value only when the label lacks it
                      const sum = summaryBeyondLabel(label, paramSummary(c, lang, brief))
                      return (
                        <span key={c.id}>
                          {i > 0 && (
                            <span aria-hidden className="text-text-3 mx-1.5">
                              ·
                            </span>
                          )}
                          {i > 0 && <span className="sr-only">, </span>}
                          {label}
                          {sum &&<span className="text-text-2 whitespace-nowrap"> {sum}</span>}
                        </span>
                      )
                    })}
                  </dd>
                </div>
              )
            })}
          </dl>
        )}
        {collapsed && (offN > 0 || cs.refused?.length > 0) && (
          <p className="mt-2 text-sm text-text-3">
            {[offN > 0 ? `${offN} ${t('criteria.disabled')}` : null, cs.refused?.length > 0 ? t('criteria.refusedN', { n: cs.refused.length }) : null].filter(Boolean).join(' · ')}
          </p>
        )}

        <div id="crit-body" hidden={collapsed} className="mt-3 grid gap-3">
          {showStart && <p className="text-sm text-text-2 -mt-1">{t('criteria.startRun.hint')}</p>}
          {rounds.map((r) => {
            const list = cs.criteria.filter((c) => c.round === r)
            if (!list.length) return null
            return (
              <div key={r} className="grid grid-cols-[136px_1fr] gap-3 items-start max-sm:grid-cols-1 max-sm:gap-1">
                <h3 className="pt-1.5 text-sm font-semibold text-text-2">
                  {t('criteria.round', { n: r })} · {t(`round.${r}` as I18nKey)} <span className="text-text-3 font-normal m-num">{list.length}</span>
                </h3>
                <div className="flex flex-wrap gap-2">
                  {list.map((c) => (
                    <CritChip key={c.id} c={c} onEdit={setEditing} />
                  ))}
                </div>
              </div>
            )
          })}
          {cs.refused?.length > 0 && (
            <div className="grid grid-cols-[136px_1fr] gap-3 items-start max-sm:grid-cols-1 max-sm:gap-1 pt-1">
              <h3 className="pt-1.5 text-sm font-semibold text-text-2">{t('criteria.refused')}</h3>
              <ul className="flex flex-col gap-2" role="list">
                {cs.refused.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 flex-wrap">
                    <span className="chip refused">
                      <span aria-hidden>⊘</span>
                      <span className="line-through decoration-gap/60">{lang === 'cs' ? csTypo(r.text) : r.text}</span>
                    </span>
                    <span className="text-sm text-text-2 pt-1 flex-1 min-w-[200px]">{pick(r.reason, lang)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {via.length > 0 && state.mode !== 'subject' && (
            <div className="text-sm text-text-2 pt-3 border-t border-dashed border-line-strong">
              <span className="font-semibold mr-2">{t('criteria.discovery')}</span>
              <span className="text-xs" translate="no">
                {via.join(' · ')}
              </span>
              {/* the demo pool mixes food and fitness terms on purpose: say so */}
              {(d.hashtags ?? []).includes('brnofood') && (d.hashtags ?? []).includes('brnofitness') && <div className="mt-1 italic">{t('criteria.discoveryShared')}</div>}
            </div>
          )}
        </div>
        {editing && <CriterionEditor c={editing} onClose={() => setEditing(null)} />}
      </section>
    </>
  )
}
