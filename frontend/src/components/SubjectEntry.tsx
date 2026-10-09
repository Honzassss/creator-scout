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

// same system as the guide composer: 13 px labels, 44 px fields with a clear --field outline, petrol primary
const LABEL = 'block mb-1 text-[13px] leading-[18px] font-semibold text-(--text)'
const FIELD =
  'block w-full min-h-11 rounded-(--r-control) border border-(--field) bg-(--surface) px-3 py-2.5 text-[15px] leading-[22px] text-(--text) placeholder:text-(--text-3) hover:border-(--text-2) focus:outline-2 focus:outline-offset-2 focus:outline-(--accent) focus:border-(--field) aria-[invalid=true]:border-2 aria-[invalid=true]:border-dashed aria-[invalid=true]:border-(--bad)'
const HINT = 'block mt-1 text-[13px] leading-[18px] text-(--text-2)'

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
      // subject-entry: a hook only (Funnel's "Check one creator" focuses this form's subject field); the look is the utilities
      className="subject-entry rounded-(--r-panel) border border-(--line) bg-(--surface) p-4 shadow-[0_1px_2px_rgba(24,44,54,0.06)]"
      aria-labelledby={`${uid}-t`}
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <h3 id={`${uid}-t`} className="text-[16px] leading-[22px] font-semibold text-(--text)">
        {title ?? t('subject.entry.title')}
      </h3>
      {!title && <p className="mt-1 text-[13px] leading-[18px] text-(--text-2)">{t('subject.entry.body')}</p>}

      <div className="mt-4">
        <label htmlFor={`${uid}-s`} className={LABEL}>
          {t('subject.field.subject')}
        </label>
        <input
          id={`${uid}-s`}
          data-testid="subject-input"
          name="subject"
          autoComplete="off"
          spellCheck={false}
          className={FIELD}
          placeholder="@kuba.jidlo.brno"
          value={subject}
          aria-invalid={error ? true : undefined}
          aria-describedby={`${uid}-sh${error ? ` ${uid}-err` : ''}`}
          onChange={(e) => {
            setSubject(e.target.value)
            setError(null)
          }}
        />
        <span id={`${uid}-sh`} className={HINT}>
          {t('subject.field.subject.hint')}
        </span>
        {error && (
          // icon + text, not only the red edge
          <span
            id={`${uid}-err`}
            role="alert"
            className="mt-2 flex items-start gap-2 rounded-(--r-tag) border-l-2 border-(--bad) bg-(--bad-tint) px-2 py-1.5 text-[13px] leading-[18px] font-semibold text-(--bad)"
          >
            <span aria-hidden className="mt-px inline-flex size-4 shrink-0 items-center justify-center rounded-full border border-current text-[11px] leading-none">
              !
            </span>
            {t(error)}
          </span>
        )}
      </div>

      <div className="mt-4">
        <label htmlFor={`${uid}-a`} className={LABEL}>
          {t('subject.field.anchor')}
        </label>
        <input
          id={`${uid}-a`}
          data-testid="subject-anchor"
          name="anchor"
          autoComplete="off"
          className={FIELD}
          placeholder="Brno"
          value={anchorRaw}
          aria-describedby={`${uid}-ah`}
          onChange={(e) => setAnchorRaw(e.target.value)}
        />
        <span id={`${uid}-ah`} className={HINT}>
          {/* no aria-live: it announced every keystroke ("Read as a city: B", "Br", …); the hint is in aria-describedby */}
          <span className="block font-semibold text-(--text)">
            {anchor ? t(`subject.anchorAs.${anchor.kind}` as I18nKey, { v: anchor.value }) : t('subject.anchor.none')}
          </span>
          {t('subject.field.anchor.hint')}
        </span>
      </div>

      <fieldset className="mt-4">
        <legend className={LABEL}>{t('subject.field.goal')}</legend>
        <div className="flex flex-wrap gap-2">
          {goals.map((g) => {
            const on = goal === g.k
            return (
              <label
                key={g.k}
                className={`relative inline-flex items-center gap-1.5 min-h-11 md:min-h-9 px-3 rounded-(--r-control) border text-[14px] leading-5 cursor-pointer transition-colors duration-(--dur-1) has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-(--accent) ${
                  on ? 'border-(--accent) bg-(--accent-tint) text-(--accent-press) font-semibold' : 'border-(--field) bg-(--surface) text-(--text) hover:border-(--accent) hover:bg-(--accent-tint)'
                }`}
              >
                <input type="radio" data-testid={`subject-goal-${g.k}`} name={`${uid}-goal`} value={g.k} checked={on} onChange={() => setGoal(g.k)} className="sr-only" />
                {on && <span aria-hidden>✓</span>}
                {t(g.label)}
              </label>
            )
          })}
        </div>
      </fieldset>

      {!state.demo && goal !== 'chat' && (
        <div className="mt-4">
          <label htmlFor={`${uid}-c`} className={LABEL}>
            {t('subject.field.competitors')}
          </label>
          <input
            id={`${uid}-c`}
            data-testid="subject-competitors"
            name="competitors"
            autoComplete="off"
            spellCheck={false}
            className={FIELD}
            placeholder={t('subject.field.competitors.ph')}
            value={compRaw}
            aria-describedby={`${uid}-ch`}
            onChange={(e) => setCompRaw(e.target.value)}
          />
          <span id={`${uid}-ch`} className={HINT}>
            {competitors.length > 0 && (
              <span className="block font-semibold text-(--text)">
                {t('subject.competitorsAs', { v: competitors.map(compLabel).join(', ') })}
              </span>
            )}
            {t('subject.field.competitors.hint')}
          </span>
        </div>
      )}

      {/* full width: the busy label may be longer or shorter, nothing around it moves */}
      <button
        type="submit"
        data-testid="subject-submit"
        className={`mt-6 w-full inline-flex items-center justify-center gap-2 min-h-11 px-4 rounded-(--r-control) border text-[15px] leading-[22px] font-semibold transition-colors duration-(--dur-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent) ${
          busy
            ? 'bg-(--accent-tint) text-(--accent-press) border-(--accent) cursor-progress'
            : 'bg-(--accent) text-white border-(--accent) hover:bg-(--accent-hover) hover:border-(--accent-hover) active:bg-(--accent-press) active:border-(--accent-press)'
        }`}
        aria-disabled={busy || undefined}
        aria-busy={busy || undefined}
      >
        {busy && <span aria-hidden className="inline-block size-4 shrink-0 rounded-full border-2 border-current border-t-transparent animate-spin motion-reduce:animate-none" />}
        {busy ? t('subject.submitting') : goal === 'chat' ? t('subject.submit.chat') : t('subject.submit')}
        {!busy && <span aria-hidden>→</span>}
      </button>
    </form>
  )
}
