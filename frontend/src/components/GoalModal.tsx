import { useEffect, useId, useRef, useState } from 'react'
import { useApp } from '../store'
import { csTypo } from '../lib/typo'
import { useDialog } from '../lib/useDialog'
import type { Brief, Competitor } from '../types'
import { DiscardBar, NoValue, useDiscardGuard } from './primitives'

import { PRESETS } from '../lib/presets'

const compToText = (cs: Competitor[]) => cs.map((c) => [c.name, ...(c.handles ?? []).map((h) => `@${h}`)].join(' ')).join('\n')

function textToComp(s: string): Competitor[] {
  return s
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const handles = [...line.matchAll(/@([\w.]+)/g)].map((m) => m[1].toLowerCase())
      const name = line.replace(/@[\w.]+/g, '').trim() || handles[0] || line
      return { name, handles }
    })
}

const EMPTY: Brief = { business_type: '', city: '', audience: '', goal: '', budget_hint: '', competitors: [] }

type Field = 'business_type' | 'city' | 'audience' | 'goal' | 'budget_hint'
const FIELDS: { k: Field; label: 'goal.business' | 'goal.city' | 'goal.audience' | 'goal.goal' | 'goal.budget'; wide?: boolean; required?: boolean }[] = [
  { k: 'business_type', label: 'goal.business', required: true },
  { k: 'city', label: 'goal.city' },
  { k: 'audience', label: 'goal.audience', wide: true },
  { k: 'goal', label: 'goal.goal', wide: true },
  { k: 'budget_hint', label: 'goal.budget' },
]

function GoalDialog({ onClose }: { onClose: () => void }) {
  const { state, t, lang, actions } = useApp()
  // reports rendered for a goal (rendered_for) are rewritten for the new goal from stored data on a goal change
  const rerenders = Object.values(state.candidates).some((c) => !!c.report?.rendered_for)
  const uid = useId()
  const current = state.criteria?.brief ?? null
  // opens with the current goal's values (P1-11)
  const [b, setB] = useState<Brief>(() => ({ ...EMPTY, ...(current ?? PRESETS.bakery[lang]) }))
  const [comp, setComp] = useState(() => compToText((current ?? PRESETS.bakery[lang]).competitors ?? []))
  const [step, setStep] = useState<'edit' | 'review'>('edit')
  const [error, setError] = useState(false)
  const firstRef = useRef<HTMLInputElement>(null)
  // Escape / scrim with unsaved edits asks first ("Zrušit" closes at once)
  const initial = useRef({ b: JSON.stringify(b), comp })
  const guard = useDiscardGuard(JSON.stringify(b) !== initial.current.b || comp !== initial.current.comp, onClose)
  const ref = useDialog<HTMLDivElement>(true, guard.request, { initialFocus: firstRef })
  const canSubmit = state.demo || !!state.runId
  const typo = (s: string) => (lang === 'cs' ? csTypo(s) : s)

  useEffect(() => {
    // focus the dialog body on step change so the review is announced from the top
    if (step === 'review') ref.current?.querySelector<HTMLElement>('[data-review-h]')?.focus()
  }, [step, ref])

  const next: Brief = { ...b, competitors: textToComp(comp), lang }
  const rows = FIELDS.map((f) => ({ f, old: (current?.[f.k] ?? '') as string, now: (next[f.k] ?? '') as string })).filter((r) => r.old.trim() !== r.now.trim())
  const compOld = compToText(current?.competitors ?? [])
  const compChanged = compOld.trim() !== comp.trim()
  const presetActive = (p: Brief) => b.business_type === p.business_type && b.city === p.city && b.goal === p.goal

  return (
    <>
      <div className="scrim !z-50" onClick={guard.request} />
      <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby={`${uid}-t`} tabIndex={-1}>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (step === 'edit') {
            if (!rows.length && !compChanged && current) {
              setError(true)
              return
            }
            setError(false)
            setStep('review')
            return
          }
          if (!canSubmit) return
          actions.changeGoal(next)
          onClose()
        }}
      >
        <div className="px-6 pt-6 pb-4 border-b border-rule">
          <h2 id={`${uid}-t`} className="font-display text-xl font-semibold">
            {t('goal.title')}
          </h2>
          {current && (
            <p className="text-base mt-2">
              <span className="smallcaps mr-2">{t('goal.now')}</span>
              {typo([current.business_type, current.city, current.goal].filter(Boolean).join(' · '))}
            </p>
          )}
          <p className="text-sm text-ink-2 mt-2">{t('goal.body')}</p>
        </div>

        {step === 'edit' ? (
          <div className="px-6 py-4 flex flex-col gap-4">
            <div className="flex items-center gap-2 flex-wrap" role="group" aria-labelledby={`${uid}-p`}>
              <span id={`${uid}-p`} className="text-sm text-ink-2 mr-1">
                {t('goal.presets')}:
              </span>
              {(['fitness', 'bakery'] as const).map((k) => {
                const p = PRESETS[k][lang]
                return (
                  <button
                    key={k}
                    type="button"
                    className="btn btn-sm"
                    aria-pressed={presetActive(p)}
                    onClick={() => {
                      setB({ ...EMPTY, ...p })
                      setComp(compToText(p.competitors))
                      setError(false)
                    }}
                  >
                    {t(k === 'fitness' ? 'goal.preset.fitness' : 'goal.preset.bakery')}
                  </button>
                )
              })}
            </div>
            <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
              {FIELDS.map((f, i) => (
                <div key={f.k} className={f.wide ? 'col-span-2 max-sm:col-span-1' : ''}>
                  <label htmlFor={`${uid}-${f.k}`} className="label">
                    {t(f.label)}
                  </label>
                  <input
                    ref={i === 0 ? firstRef : undefined}
                    id={`${uid}-${f.k}`}
                    name={f.k}
                    autoComplete="off"
                    className="field"
                    value={(b[f.k] ?? '') as string}
                    aria-describedby={f.k === 'audience' ? `${uid}-an` : error && i === 0 ? `${uid}-err` : undefined}
                    onChange={(e) => {
                      setError(false)
                      setB((x) => ({ ...x, [f.k]: e.target.value }))
                    }}
                    required={f.required}
                  />
                  {f.k === 'audience' && (
                    <span id={`${uid}-an`} className="block text-sm text-ink-2 mt-1 italic">
                      {t('goal.audienceNote')}
                    </span>
                  )}
                </div>
              ))}
              <div className="col-span-2 max-sm:col-span-1">
                <label htmlFor={`${uid}-comp`} className="label">
                  {t('goal.competitors')}
                </label>
                <textarea
                  id={`${uid}-comp`}
                  name="competitors"
                  autoComplete="off"
                  className="field text-sm"
                  rows={3}
                  value={comp}
                  onChange={(e) => {
                    setError(false)
                    setComp(e.target.value)
                  }}
                />
              </div>
            </div>
            {error && (
              <p id={`${uid}-err`} role="alert" className="text-sm text-ink border border-dashed border-ink-2 rounded-sm px-3 py-2">
                {t('goal.unchanged')}
              </p>
            )}
            {!canSubmit && <p className="text-sm text-ink-2 border border-dashed border-rule-strong px-3 py-2 rounded-sm">{t('goal.noRun')}</p>}
          </div>
        ) : (
          <div className="px-6 py-4">
            <h3 data-review-h tabIndex={-1} className="text-md font-semibold">
              {t('goal.review')}
            </h3>
            <p className="text-base text-ink-2 mt-1">{t(rerenders ? 'goal.review.bodyRender' : 'goal.review.body')}</p>
            <table className="ctable mt-3 !text-sm">
              <thead>
                <tr>
                  <th scope="col">{t('goal.review.field')}</th>
                  <th scope="col">{t('goal.review.old')}</th>
                  <th scope="col">{t('goal.review.new')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ f, old, now }) => (
                  <tr key={f.k}>
                    <th scope="row" className="!static !bg-transparent font-normal text-ink-2">
                      {t(f.label)}
                    </th>
                    <td>
                      <s className="text-ink-2">{typo(old) || <NoValue />}</s>
                    </td>
                    <td className="font-medium">{typo(now) || <NoValue />}</td>
                  </tr>
                ))}
                {compChanged && (
                  <tr>
                    <th scope="row" className="!static !bg-transparent font-normal text-ink-2">
                      {t('goal.competitors')}
                    </th>
                    <td className="whitespace-pre-line">
                      <s className="text-ink-2">{compOld || <NoValue />}</s>
                    </td>
                    <td className="font-medium whitespace-pre-line">{comp || <NoValue />}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <DiscardBar guard={guard} />
        <div className="px-6 py-3 border-t border-rule flex flex-wrap justify-end gap-2 bg-paper-2/60" hidden={guard.asking}>
          {step === 'review' ? (
            <button type="button" className="btn mr-auto" onClick={() => setStep('edit')}>
              <span aria-hidden>←</span> {t('goal.back')}
            </button>
          ) : null}
          <button type="button" className="btn" onClick={onClose}>
            {t('goal.cancel')}
          </button>
          <button type="submit" className="btn btn-primary" aria-disabled={(step === 'review' && !canSubmit) || undefined}>
            {step === 'edit' ? t('goal.next') : t('goal.submit')}
          </button>
        </div>
      </form>
      </div>
    </>
  )
}

export function GoalModal() {
  const { goalOpen, setGoalOpen } = useApp()
  if (!goalOpen) return null
  return <GoalDialog onClose={() => setGoalOpen(false)} />
}
