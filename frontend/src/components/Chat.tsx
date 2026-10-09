import { useEffect, useId, useRef, useState } from 'react'
import type { AnimationEvent, CSSProperties } from 'react'
import { useApp } from '../store'
import { hasKey, pick, translate, type I18nKey } from '../i18n'
import { RichText, platformLabel } from './primitives'
import type { Lang, Platform } from '../types'
import { SubjectEntry } from './SubjectEntry'
import type { ChatMessage, NoticeData, ToolCall } from '../state'

/** POST /api/chat accepts at most this many characters (backend ChatRequest.message max_length). */
const MAX_CHAT = 8000

// Guide panel (spec section 7). Styled with the shared tokens from index.css (--surface, --text, --accent ...)
// through utilities, so it does not depend on how the legacy component classes are restyled.
const FOCUS = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)'
/** role label above a message: tiny, normal case, text not colour carries the role */
const ROLE = 'text-[12px] leading-4 font-semibold text-(--text-3)'
/** long text: 15/22, emphasis only where the message itself marks a key noun or next step */
const BODY = 'text-[15px] leading-[22px] text-(--text) [&_strong]:font-semibold'
const LINK = `inline-flex items-center gap-1 w-max min-h-6 max-md:min-h-11 rounded-(--r-tag) text-[13px] leading-[18px] font-semibold text-(--accent) underline decoration-1 underline-offset-[3px] hover:decoration-2 hover:text-(--accent-hover) ${FOCUS}`
const ICON_BTN = `inline-flex items-center justify-center size-9 rounded-(--r-control) text-(--text-2) hover:bg-(--neutral-tint) hover:text-(--text) active:bg-(--line) ${FOCUS}`

const TOOL_TARGET: Record<string, string> = {
  propose_criteria: 'criteria',
  update_criterion: 'criteria',
  run_rounds: 'funnel',
  start_deep_vetting: 'funnel',
  change_goal: 'diff',
  research_subject: 'subject',
}

/** Blank-line separated paragraphs get 12 px between them; single line breaks stay inside a paragraph. */
function Paragraphs({ text, caret, lang }: { text: string; caret?: boolean; lang?: Lang | null }) {
  const paras = text.split(/\n[ \t]*\n+/).filter((p) => p.trim() !== '')
  return (
    <div className="flex flex-col gap-3">
      {paras.map((p, i) => (
        <p key={i} className="whitespace-pre-wrap break-words">
          <RichText text={p} lang={lang} />
          {caret && i === paras.length - 1 && <Caret />}
        </p>
      ))}
    </div>
  )
}

/** Streaming caret with zero width: it never pushes a word onto the next line, so the text does not jump. */
function Caret() {
  return (
    <span aria-hidden className="relative inline-block w-0 align-baseline">
      <span className="absolute left-0.5 bottom-[-0.15em] text-(--text-3) animate-pulse motion-reduce:animate-none">▍</span>
    </span>
  )
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block size-4 shrink-0 rounded-full border-2 border-current border-t-transparent animate-spin motion-reduce:animate-none"
    />
  )
}

/** A tool call shown the way a bakery owner reads it: a quiet line that leads to the right panel. */
function ToolLine({ tool }: { tool: ToolCall }) {
  const { t, state, reveal, openCandidate } = useApp()
  const done = tool.result !== undefined || tool.status === 'done'
  // {ok: false, error}: the step did not happen (run busy, nothing to vet …); never show it as done
  const failed = done && !!tool.result && typeof tool.result === 'object' && (tool.result as { ok?: unknown }).ok === false
  const key = `tool.${tool.name}`
  let label: string
  if (tool.name === 'propose_criteria') {
    const n = state.criteria?.criteria.length ?? 0
    label = n ? t('tool.propose_criteria', { n }) : t('tool.propose_criteria.plain')
  } else {
    label = hasKey(key) ? t(key) : t('tool.other')
  }
  const cand = (tool.input as { candidate_id?: string } | undefined)?.candidate_id
  // on a subject run the goal change shows up in the report, not in the funnel diff
  const target = tool.name === 'change_goal' && state.mode === 'subject' ? 'subject' : TOOL_TARGET[tool.name]
  const line = 'inline-flex items-center gap-2 min-h-8 max-md:min-h-11 text-left text-[13px] leading-[18px] text-(--text-2)'
  const btn = `${line} group rounded-(--r-tag) hover:text-(--text) ${FOCUS}`
  const check = (
    <span aria-hidden className="text-(--text-3)">
      ✓
    </span>
  )
  const arrow = (
    <span aria-hidden className="text-(--accent) transition-transform duration-(--dur-1) group-hover:translate-x-0.5">
      →
    </span>
  )
  if (!done)
    return (
      <span className={line}>
        <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-(--accent) animate-pulse motion-reduce:animate-none" />
        {label} · {t('tool.running')}
      </span>
    )
  if (failed)
    return (
      <span className={line}>
        <span aria-hidden className="text-(--text-3)">
          ✕
        </span>
        {t('tool.failed', { label: hasKey(`${key}.try`) ? t(`${key}.try` as I18nKey) : label })}
      </span>
    )
  if (cand && state.candidates[cand])
    return (
      <button type="button" className={btn} onClick={() => openCandidate(cand)}>
        {check}
        {label}
        {arrow}
      </button>
    )
  if (!target)
    return (
      <span className={line}>
        {check}
        {label}
      </span>
    )
  return (
    <button type="button" className={btn} onClick={() => reveal(target)}>
      {check}
      {label}
      {arrow}
    </button>
  )
}

function Notice({ n }: { n: NoticeData }) {
  const { t, lang, state, openCandidate, reveal, dispatch } = useApp()
  const label = (id: string) => pick(state.criteria?.criteria.find((c) => c.id === id)?.label ?? id, lang)
  // a summary of what just happened: white card with a thin petrol mark, set apart from the guide's own words
  const box = `${BODY} flex flex-col gap-3 rounded-(--r-panel) border border-(--line) border-l-[3px] border-l-(--accent) bg-(--surface) px-3 py-3 shadow-[0_1px_2px_rgba(24,44,54,0.06)]`
  if (n.kind === 'subject')
    return (
      <div className={box}>
        <p>
          <RichText text={t('notice.subject', { h: n.handle, anchor: pick(n.anchor, lang), goal: pick(n.goal, lang) })} />
        </p>
      </div>
    )
  if (n.kind === 'subjectReady') {
    const c = state.candidates[n.candidateId]
    const v = c?.report?.identity_verdict
    return (
      <div className={box}>
        <p>
          <RichText text={t('notice.subjectReady', { h: c?.profile?.handle ?? c?.ref.handle ?? '–' })} />
        </p>
        {v && (
          <p>
            <RichText text={pick(v.text, lang)} />
          </p>
        )}
        <p className="text-(--text-2)">{t('subject.noElim')}</p>
        <p className="text-(--text-2)">{t('notice.subjectReady.tip')}</p>
        <button type="button" className={LINK} onClick={() => reveal('subject')}>
          {t('notice.subjectReady.open')} <span aria-hidden>→</span>
        </button>
      </div>
    )
  }
  if (n.kind === 'reportDiff') {
    const c = state.candidates[n.candidateId]
    return (
      <div className={box}>
        <p>
          <RichText text={pick(n.diff.summary, lang)} />
        </p>
        <button
          type="button"
          className={LINK}
          onClick={() => {
            // subject board: (re)open the "What changed" panel, even after Hide; elsewhere the report itself
            if (state.mode === 'subject' && state.reportDiff?.candidateId === n.candidateId) {
              dispatch({ type: 'reportDiff.show' })
              reveal('what-changed', 'changed-h')
            } else if (c) openCandidate(n.candidateId)
            else reveal('subject')
          }}
        >
          {t('notice.reportDiff.show')} <span aria-hidden>→</span>
        </button>
      </div>
    )
  }
  if (n.kind === 'reportDiffs')
    return (
      <div className={box}>
        <p>{t('notice.reportDiffs', { n: n.items.length })}</p>
        <ul className="flex flex-col gap-2">
          {n.items.map((it) => (
            <li key={it.candidateId} className="flex flex-col gap-0.5">
              <span>
                <RichText text={`@${it.handle}`} />
                {': '}
                <RichText text={pick(it.summary, lang)} />
              </span>
              {state.candidates[it.candidateId] && (
                <button type="button" className={LINK} onClick={() => openCandidate(it.candidateId)}>
                  {t('notice.vet.open')}
                  <span className="sr-only" translate="no">
                    {' '}@{it.handle}
                  </span>{' '}
                  <span aria-hidden>→</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    )
  if (n.kind === 'subjectNotFound')
    return (
      <div className={box}>
        <p>
          <RichText
            text={
              n.reason
                ? pick(n.reason, lang)
                : n.offline
                  ? t('subject.notFound.offlineBody', { h: n.handle })
                  : t('subject.notFound.body', { h: n.handle, tried: n.tried.map((p) => platformLabel(p as Platform, t)).join(', ') || t('subject.notFound.triedAll') })
            }
          />
        </p>
        <button type="button" className={LINK} onClick={() => reveal('subject')}>
          {t('tool.go')} <span aria-hidden>→</span>
        </button>
      </div>
    )
  if (n.kind === 'interrupted')
    return (
      <div className={box}>
        <p>{t('notice.interrupted')}</p>
      </div>
    )
  if (n.kind === 'vet')
    return (
      <div className={box}>
        <p>{t('notice.vet', { n: n.vetted })}</p>
        {n.fails.length > 0 ? (
          <>
            <p>{t('notice.vet.fails', { n: n.fails.length })}</p>
            <ul className="flex flex-col gap-2">
              {n.fails.map((f) => (
                <li key={f.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="font-semibold break-all">
                    <RichText text={`@${f.handle}`} />
                  </span>
                  <span className="text-[13px] leading-[18px] text-(--text-2)">({f.criteria.map(label).join(', ')})</span>
                  {state.candidates[f.id] && (
                    <button type="button" className={LINK} onClick={() => openCandidate(f.id)}>
                      {t('notice.vet.open')}
                      <span className="sr-only" translate="no">
                        {' '}@{f.handle}
                      </span>{' '}
                      <span aria-hidden>→</span>
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-(--text-2)">{t('notice.vet.none')}</p>
        )}
      </div>
    )
  return (
    <div className={box}>
      <p>{t('notice.goal', { from: n.from, to: n.to })}</p>
      <p className="text-(--text-2)">
        {t('notice.goal.dropped', { n: n.dropped })} {t('notice.goal.returned', { n: n.returned })}
      </p>
      <button type="button" className={LINK} onClick={() => reveal('diff')}>
        {t('notice.goal.show')} <span aria-hidden>→</span>
      </button>
    </div>
  )
}

function Message({ m: raw }: { m: ChatMessage }) {
  const { t, lang } = useApp()
  // demo messages carry both languages: the toggle re-renders them
  const m = raw.i18n && !raw.pending ? { ...raw, text: pick(raw.i18n, lang) } : raw
  if (m.role === 'notice') {
    if (m.notice)
      return (
        <div className="flex flex-col gap-1" data-testid="chat-notice" data-kind={m.notice.kind}>
          <span className={ROLE}>{t('chat.summary')}</span>
          <Notice n={m.notice} />
        </div>
      )
    return (
      <div className="text-center">
        <span className="inline-block text-[13px] leading-[18px] text-(--text-2) bg-(--bg) border border-dashed border-(--field) rounded-(--r-tag) px-2 py-1">
          <RichText text={m.text} />
        </span>
      </div>
    )
  }
  if (m.role === 'user')
    return (
      <div className="flex flex-col items-end gap-1" data-testid="chat-message" data-role="user">
        <span className={ROLE}>{t('chat.you')}</span>
        <div className={`${BODY} max-w-[88%] rounded-(--r-panel) rounded-tr-(--r-tag) bg-(--accent-tint) px-3 py-3`}>
          <Paragraphs text={m.text} />
        </div>
      </div>
    )
  return (
    <div className="flex flex-col gap-1" aria-busy={m.pending || undefined} data-testid="chat-message" data-role="assistant" data-pending={m.pending ? 'true' : undefined}>
      <span className={ROLE}>{t('chat.bot')}</span>
      {(m.text || m.pending) && (
        // full width from the first frame: streamed text only grows downwards, never sideways
        <div className={`${BODY} w-full rounded-(--r-panel) rounded-tl-(--r-tag) border border-(--line) bg-(--bg) px-3 py-3`}>
          {m.text ? <Paragraphs text={m.text} caret={m.pending} lang={m.lang} /> : <p className="text-(--text-3)">{t('chat.thinking')}</p>}
        </div>
      )}
      {m.tools.length > 0 && (
        <div className="flex flex-col items-start gap-0.5 pl-3 pt-1">
          {m.tools.map((tool, i) => (
            <ToolLine key={i} tool={tool} />
          ))}
        </div>
      )}
      {m.error && (
        <div className="mt-1 flex items-start gap-2 rounded-(--r-tag) border-l-2 border-(--bad) bg-(--bad-tint) px-2 py-1.5 text-[13px] leading-[18px] text-(--text)">
          <span aria-hidden className="font-semibold text-(--bad)">
            !
          </span>
          <span>{m.error}</span>
        </div>
      )}
    </div>
  )
}

export function Chat({ collapsed, onCollapse, visible }: { collapsed: boolean; onCollapse: (v: boolean) => void; visible: boolean }) {
  const { state, t, lang, actions, chatDraft } = useApp()
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  // "Describe in chat" / "Other goal…": a draft lands in the composer, caret at the end
  useEffect(() => {
    if (!chatDraft) return
    setText(chatDraft.text)
    window.setTimeout(() => {
      const el = inputRef.current
      if (!el) return
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }, 30)
  }, [chatDraft])
  const listRef = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const inputId = useId()
  const toggleRef = useRef<HTMLButtonElement>(null)
  const prevCollapsed = useRef(collapsed)
  // keep keyboard focus on the toggle when the column collapses or expands
  useEffect(() => {
    if (prevCollapsed.current === collapsed) return
    prevCollapsed.current = collapsed
    toggleRef.current?.focus()
  }, [collapsed])

  // Entry motion: only messages that arrive while the guide is open slide in, one after another within a
  // burst (60 ms apart, at most 8 steps; .m-stagger is not used here because it would animate every child). What was there at mount, or while collapsed, renders still: expanding the panel or
  // switching tabs on a phone never replays every message at once. Once a message has entered, its class
  // is dropped, so a display:none -> block flip (phone tabs) cannot restart the animation.
  const enter = useRef<Map<string, number> | null>(null)
  if (enter.current === null || collapsed) enter.current = new Map(state.chat.map((m) => [m.id, -1]))
  let burst = 0
  for (const m of state.chat) if (!enter.current.has(m.id)) enter.current.set(m.id, Math.min(burst++, 8))
  const entered = (id: string) => (e: AnimationEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return
    enter.current?.set(id, -1)
    e.currentTarget.classList.remove('m-enter')
  }

  useEffect(() => {
    const el = listRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [state.chat])

  // switching to the guide on a phone jumps to the latest message
  useEffect(() => {
    const el = listRef.current
    if (visible && el) {
      el.scrollTop = el.scrollHeight
      stick.current = true
    }
  }, [visible])

  const [tooLong, setTooLong] = useState(false)
  const send = (msg?: string) => {
    const v = (msg ?? text).trim()
    if (!v || state.chatBusy) return
    // the backend takes at most MAX_CHAT characters: say so here and keep the text, instead of a raw 422
    if (v.length > MAX_CHAT) {
      setTooLong(true)
      inputRef.current?.focus()
      return
    }
    setTooLong(false)
    const sent = actions.sendChat(v)
    setText('')
    stick.current = true
    // the guide did not answer (server down, error): the message comes back into an empty composer
    if (sent) void sent.then((ok) => !ok && setText((cur) => cur || v))
  }

  // the purge notice ("Data deleted.") alone is not a conversation: the two ways in stay visible
  const empty = !state.chat.some((m) => m.role !== 'notice' || m.notice)
  const busy = state.chatBusy
  const canSend = !busy && text.trim() !== ''

  if (collapsed)
    return (
      <div className="hidden md:flex flex-col items-center h-full py-3 gap-3 bg-(--surface)">
        <h2 id="chat-h" className="sr-only">
          {t('chat.title')}
        </h2>
        <button ref={toggleRef} type="button" className={ICON_BTN} onClick={() => onCollapse(false)} aria-label={t('chat.expand')} aria-expanded={false} title={t('chat.expand')}>
          <span aria-hidden>»</span>
        </button>
        <button
          type="button"
          className="flex-1 w-full flex items-start justify-center pt-2 text-[13px] leading-[18px] font-semibold text-(--text-2) hover:text-(--text)"
          onClick={() => onCollapse(false)}
          aria-hidden
          tabIndex={-1}
        >
          <span style={{ writingMode: 'vertical-rl' }}>{t('chat.title')}</span>
        </button>
      </div>
    )

  // send: petrol when there is something to send; grey when empty; tinted with a spinner while the guide answers
  const sendCls = busy
    ? 'bg-(--accent-tint) text-(--accent-press) border-(--accent) cursor-progress'
    : canSend
      ? 'bg-(--accent) text-white border-(--accent) hover:bg-(--accent-hover) hover:border-(--accent-hover) active:bg-(--accent-press) active:border-(--accent-press)'
      : 'bg-(--neutral-tint) text-(--text-3) border-(--line) cursor-not-allowed'

  return (
    <div className="flex flex-col h-full min-h-0 bg-(--surface)">
      <div className="px-4 pt-4 pb-3 border-b border-(--line) flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <h2 id="chat-h" className="text-[18px] leading-[26px] font-semibold text-(--text)">
            {t('chat.title')}
          </h2>
          <p className="text-[13px] leading-[18px] text-(--text-2) mt-1">{t('chat.subtitle')}</p>
        </div>
        <button
          ref={toggleRef}
          type="button"
          className={`${ICON_BTN} max-md:hidden -mr-1`}
          onClick={() => onCollapse(true)}
          aria-label={t('chat.collapse')}
          aria-expanded={true}
          title={t('chat.collapse')}
        >
          <span aria-hidden>«</span>
        </button>
      </div>

      <div
        ref={listRef}
        role="log"
        data-testid="chat-log"
        tabIndex={empty ? -1 : 0}
        aria-label={t('chat.log')}
        aria-busy={busy}
        className={`relative min-h-0 overflow-y-auto scroll-thin px-4 flex flex-col gap-5 overscroll-contain ${FOCUS} focus-visible:outline-offset-[-2px] ${empty ? 'flex-none' : 'flex-1 py-4'}`}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
      >
        {state.chat.map((m) => {
          const i = enter.current?.get(m.id) ?? -1
          return (
            <div
              key={m.id}
              className={i >= 0 ? 'm-enter' : undefined}
              style={i > 0 ? ({ animationDelay: `calc(${i} * var(--stagger, 60ms))` } as CSSProperties) : undefined}
              onAnimationEnd={i >= 0 ? entered(m.id) : undefined}
            >
              <Message m={m} />
            </div>
          )
        })}
      </div>

      {/* empty screen: two ways in. Outside the live log region. */}
      {empty && (
        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin px-4 py-4 flex flex-col gap-3 overscroll-contain [&>*]:shrink-0">
          <div className="flex flex-col gap-1">
            <h3 className="text-[16px] leading-[22px] font-semibold text-(--text)">{t('chat.empty.title')}</h3>
            <p className="text-[15px] leading-[22px] text-(--text-2)">{t('chat.empty.body')}</p>
          </div>
          <span className="mt-1 text-[13px] leading-[18px] font-semibold text-(--text-2)">{t('chat.examples')}</span>
          {(['chat.suggest.1', 'chat.suggest.2', 'chat.suggest.subject', 'chat.suggest.3'] as const).map((k) => (
            <button
              key={k}
              type="button"
              className={`w-full text-left text-[14px] leading-5 text-(--text) px-3 py-2.5 min-h-11 rounded-(--r-control) border border-(--line) bg-(--surface) hover:border-(--accent) hover:bg-(--accent-tint) active:bg-(--accent-tint) active:border-(--accent-press) ${FOCUS}`}
              onClick={() => {
                send(translate(lang, k))
                // the starters unmount: the guide asks a question next, so the composer takes focus
                window.setTimeout(() => inputRef.current?.focus(), 30)
              }}
            >
              <RichText text={t(k)} />
            </button>
          ))}
          <div className="flex items-center gap-3 my-1 text-[12px] leading-4 font-semibold text-(--text-3)" aria-hidden>
            <span className="h-px flex-1 bg-(--line)" />
            {t('subject.or')}
            <span className="h-px flex-1 bg-(--line)" />
          </div>
          <SubjectEntry />
        </div>
      )}

      <form
        // stacked: in a 288-304 px column a side-by-side button leaves the field too narrow for one sentence
        className="border-t border-(--line) bg-(--surface) p-3 flex flex-col gap-2"
        style={{ paddingBottom: 'calc(12px + env(safe-area-inset-bottom))' }}
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          {t('chat.input')}
        </label>
        <textarea
          data-testid="chat-input"
          ref={inputRef}
          id={inputId}
          name="message"
          autoComplete="off"
          className="w-full block resize-none min-h-11 max-h-[140px] rounded-(--r-control) border border-(--field) bg-(--surface) px-3 py-2.5 text-[15px] leading-[22px] text-(--text) placeholder:text-(--text-3) hover:border-(--text-2) focus:outline-2 focus:outline-offset-2 focus:outline-(--accent) focus:border-(--field)"
          rows={2}
          value={text}
          placeholder={t('chat.placeholder')}
          aria-invalid={tooLong || undefined}
          aria-describedby={tooLong || text.length > MAX_CHAT - 500 ? `${inputId}-len` : undefined}
          onChange={(e) => {
            setText(e.target.value)
            if (tooLong && e.target.value.trim().length <= MAX_CHAT) setTooLong(false)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
        />
        {/* the label never changes and the icon slot is fixed: no width jump between idle, empty and busy */}
        <button
          type="submit"
          data-testid="chat-send"
          className={`self-end inline-flex shrink-0 items-center justify-center gap-2 min-h-11 min-w-28 px-4 rounded-(--r-control) border text-[15px] leading-[22px] font-semibold transition-colors duration-(--dur-1) ${sendCls} ${FOCUS}`}
          aria-disabled={!canSend || undefined}
          aria-busy={busy || undefined}
        >
          {t('chat.send')}
          {busy ? (
            <Spinner />
          ) : (
            <span aria-hidden className="inline-flex size-4 items-center justify-center">
              →
            </span>
          )}
        </button>
        {(tooLong || text.length > MAX_CHAT - 500) && (
          <p id={`${inputId}-len`} role={tooLong ? 'alert' : undefined} className={`text-[13px] leading-[18px] ${tooLong ? 'text-(--bad) font-semibold border-l-2 border-(--bad) pl-2' : 'text-(--text-2)'}`}>
            {t(tooLong ? 'chat.tooLong' : 'chat.length', { n: text.trim().length, max: MAX_CHAT })}
          </p>
        )}
      </form>
    </div>
  )
}
