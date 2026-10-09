// "Already have a creator in mind?": the second way in, next to the chat examples. One creator (@handle or
// profile link), one anchor (city, website or company ID) and a goal -> POST /api/subject.

import { useId, useRef, useState } from 'react'
import { useApp } from '../store'
import { parseCompetitors, parseSubject, readAnchor } from '../lib/subject'
import type { PresetName } from '../lib/presets'
import type { I18nKey } from '../i18n'
import type { Anchor, Competitor } from '../types'

type GoalChoice = PresetName | 'chat'

/** "Pekárna B @pekarna_b", "@x" (named by its handle), "Lidl" */
const compLabel = (c: Competitor) =>
  (c.handles?.includes(c.name) ? [] : [c.name]).concat((c.handles ?? []).map((h) => `@${h}`)).join(' ')

/** "city Brno" -> "Brno": the anchor field's own text for a stored anchor. */
const anchorField = (a: Anchor | null | undefined) => a?.city ?? a?.website ?? a?.company_id ?? ''

/** initialSubject / initialAnchor: the not-found panel offers the same form, prefilled, to try another handle. */
export function SubjectEntry({ initialSubject, initialAnchor, title }: { initialSubject?: string; initialAnchor?: Anchor | null; title?: string } = {}) {
  const { t, actions, composeChat, reveal, state } = useApp()
  const uid = useId()
  // the demo only has data for one creator: prefill it so the path is one click
  const [subject, setSubject] = useState(initialSubject ?? (state.demo ? '@kuba.jidlo.brno' : ''))
  const [anchorRaw, setAnchorRaw] = useState(initialAnchor !== undefined ? anchorField(initialAnchor) : state.demo ? 'Brno' : '')
  const [goal, setGoal] = useState<GoalChoice>('bakery')
  // the owner's real competitors; empty = none (the preset's sample rivals are never the owner's)
  const [compRaw, setCompRaw] = useState('')
  const [error, setError] = useState<I18nKey | null>(null)
  const [busy, setBusy] = useState(false)
  // a ref, not only state: a synchronous double click must not start two (paid) runs
  const inFlight = useRef(false)
  const anchor = readAnchor(anchorRaw)
  const competitors = parseCompetitors(compRaw)

  const submit = async () => {
    if (inFlight.current) return
    const parsed = parseSubject(subject)
    if (!parsed.ok) {
      setError(`subject.error.${parsed.reason}` as I18nKey)
      document.getElementById(`${uid}-s`)?.focus()
      return
    }
    setError(null)
    if (goal === 'chat') {
      const part = anchor ? t(`subject.chatDraft.${anchor.kind}` as I18nKey, { v: anchor.value }) : ''
      composeChat(t('subject.chatDraft', { h: parsed.handle, anchor: part }))
      return
    }
    inFlight.current = true
    setBusy(true)
    try {
      await actions.researchSubject({ subject, anchor: anchor?.anchor ?? null, preset: goal, competitors })
      // this form unmounts once the conversation starts: move focus to the report heading
      reveal('subject', 'subject-h')
    } catch {
      /* the store shows the error */
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const goals: { k: GoalChoice; label: I18nKey }[] = [
    { k: 'bakery', label: 'goal.preset.bakery' },
    { k: 'fitness', label: 'goal.preset.fitness' },
    { k: 'chat', label: 'subject.goal.chat' },
  ]

  return (
    <form
      data-testid="subject-form"
      className="subject-entry"
      aria-labelledby={`${uid}-t`}
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <h3 id={`${uid}-t`} className="font-display text-md font-semibold">
        {title ?? t('subject.entry.title')}
      </h3>
      {!title && <p className="text-sm text-ink-2 mt-1">{t('subject.entry.body')}</p>}

      <div className="mt-3">
        <label htmlFor={`${uid}-s`} className="label">
          {t('subject.field.subject')}
        </label>
        <input
          id={`${uid}-s`}
          data-testid="subject-input"
          name="subject"
          autoComplete="off"
          spellCheck={false}
          className="field"
          placeholder="@kuba.jidlo.brno"
          value={subject}
          aria-invalid={error ? true : undefined}
          aria-describedby={`${uid}-sh${error ? ` ${uid}-err` : ''}`}
          onChange={(e) => {
            setSubject(e.target.value)
            setError(null)
          }}
        />
        <span id={`${uid}-sh`} className="block text-xs text-ink-2 mt-1">
          {t('subject.field.subject.hint')}
        </span>
        {error && (
          <span id={`${uid}-err`} role="alert" className="block text-sm text-ink mt-1 border-l-2 border-ink pl-2">
            {t(error)}
          </span>
        )}
      </div>

      <div className="mt-3">
        <label htmlFor={`${uid}-a`} className="label">
          {t('subject.field.anchor')}
        </label>
        <input
          id={`${uid}-a`}
          data-testid="subject-anchor"
          name="anchor"
          autoComplete="off"
          className="field"
          placeholder="Brno"
          value={anchorRaw}
          aria-describedby={`${uid}-ah`}
          onChange={(e) => setAnchorRaw(e.target.value)}
        />
        <span id={`${uid}-ah`} className="block text-xs text-ink-2 mt-1">
          {/* no aria-live: it announced every keystroke ("Read as a city: B", "Br", …); the hint is in aria-describedby */}
          <span className="block font-medium text-ink">
            {anchor ? t(`subject.anchorAs.${anchor.kind}` as I18nKey, { v: anchor.value }) : t('subject.anchor.none')}
          </span>
          {t('subject.field.anchor.hint')}
        </span>
      </div>

      <fieldset className="mt-3">
        <legend className="label">{t('subject.field.goal')}</legend>
        <div className="flex flex-wrap gap-2">
          {goals.map((g) => (
            <label key={g.k} className={`chip relative !min-h-8 cursor-pointer ${goal === g.k ? '!border-ink !bg-paper-3 font-medium' : ''}`}>
              <input type="radio" data-testid={`subject-goal-${g.k}`} name={`${uid}-goal`} value={g.k} checked={goal === g.k} onChange={() => setGoal(g.k)} className="sr-only" />
              {goal === g.k && <span aria-hidden>✓</span>}
              {t(g.label)}
            </label>
          ))}
        </div>
      </fieldset>

      {!state.demo && goal !== 'chat' && (
        <div className="mt-3">
          <label htmlFor={`${uid}-c`} className="label">
            {t('subject.field.competitors')}
          </label>
          <input
            id={`${uid}-c`}
            data-testid="subject-competitors"
            name="competitors"
            autoComplete="off"
            spellCheck={false}
            className="field"
            placeholder={t('subject.field.competitors.ph')}
            value={compRaw}
            aria-describedby={`${uid}-ch`}
            onChange={(e) => setCompRaw(e.target.value)}
          />
          <span id={`${uid}-ch`} className="block text-xs text-ink-2 mt-1">
            {competitors.length > 0 && (
              <span className="block font-medium text-ink">
                {t('subject.competitorsAs', { v: competitors.map(compLabel).join(', ') })}
              </span>
            )}
            {t('subject.field.competitors.hint')}
          </span>
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <button type="submit" data-testid="subject-submit" className={`btn ${goal === 'chat' ? '' : 'btn-primary'} min-h-[40px]`} aria-disabled={busy || undefined}>
          {busy ? t('subject.submitting') : goal === 'chat' ? t('subject.submit.chat') : t('subject.submit')}
          {!busy && <span aria-hidden>→</span>}
        </button>
      </div>
    </form>
  )
}
