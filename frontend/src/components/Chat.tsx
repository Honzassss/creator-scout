import { useEffect, useId, useRef, useState } from 'react'
import { useApp } from '../store'
import { hasKey, pick, translate, type I18nKey } from '../i18n'
import { primaryAction, runStarted } from '../state'
import { RichText, platformLabel } from './primitives'
import type { Platform } from '../types'
import { SubjectEntry } from './SubjectEntry'
import type { ChatMessage, NoticeData, ToolCall } from '../state'

/** POST /api/chat accepts at most this many characters (backend ChatRequest.message max_length). */
const MAX_CHAT = 8000

const TOOL_TARGET: Record<string, string> = {
  propose_criteria: 'criteria',
  update_criterion: 'criteria',
  run_rounds: 'funnel',
  start_deep_vetting: 'funnel',
  change_goal: 'diff',
  research_subject: 'subject',
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
  if (!done)
    return (
      <span className="tool-line">
        <span className="work-dot" aria-hidden />
        {label} · {t('tool.running')}
      </span>
    )
  if (failed)
    return (
      <span className="tool-line text-ink-2">
        <span aria-hidden>✕</span>
        {t('tool.failed', { label: hasKey(`${key}.try`) ? t(`${key}.try` as I18nKey) : label })}
      </span>
    )
  if (cand && state.candidates[cand])
    return (
      <button type="button" className="tool-line" onClick={() => openCandidate(cand)}>
        <span aria-hidden>✓</span>
        {label}
        <span className="arrow" aria-hidden>
          →
        </span>
      </button>
    )
  if (!target)
    return (
      <span className="tool-line">
        <span aria-hidden>✓</span>
        {label}
      </span>
    )
  return (
    <button type="button" className="tool-line" onClick={() => reveal(target)}>
      <span aria-hidden>✓</span>
      {label}
      <span className="arrow" aria-hidden>
        →
      </span>
    </button>
  )
}

function Notice({ n }: { n: NoticeData }) {
  const { t, lang, state, openCandidate, reveal, dispatch } = useApp()
  const label = (id: string) => pick(state.criteria?.criteria.find((c) => c.id === id)?.label ?? id, lang)
  if (n.kind === 'subject')
    return (
      <div className="bubble-notice text-base">
        <RichText text={t('notice.subject', { h: n.handle, anchor: pick(n.anchor, lang), goal: pick(n.goal, lang) })} />
      </div>
    )
  if (n.kind === 'subjectReady') {
    const c = state.candidates[n.candidateId]
    const v = c?.report?.identity_verdict
    return (
      <div className="bubble-notice text-base flex flex-col gap-2">
        <p>
          <RichText text={t('notice.subjectReady', { h: c?.profile?.handle ?? c?.ref.handle ?? '–' })} />
        </p>
        {v && (
          <p>
            <RichText text={pick(v.text, lang)} />
          </p>
        )}
        <p className="text-ink-2">{t('subject.noElim')}</p>
        <p className="text-ink-2">{t('notice.subjectReady.tip')}</p>
        <button type="button" className="btn-link text-sm w-max" onClick={() => reveal('subject')}>
          {t('notice.subjectReady.open')} <span aria-hidden>→</span>
        </button>
      </div>
    )
  }
  if (n.kind === 'reportDiff') {
    const c = state.candidates[n.candidateId]
    return (
      <div className="bubble-notice text-base flex flex-col gap-1">
        <p>
          <RichText text={pick(n.diff.summary, lang)} />
        </p>
        <button
          type="button"
          className="btn-link text-sm w-max"
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
      <div className="bubble-notice text-base flex flex-col gap-2">
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
                <button type="button" className="btn-link text-sm w-max" onClick={() => openCandidate(it.candidateId)}>
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
      <div className="bubble-notice text-base flex flex-col gap-1">
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
        <button type="button" className="btn-link text-sm w-max" onClick={() => reveal('subject')}>
          {t('tool.go')} <span aria-hidden>→</span>
        </button>
      </div>
    )
  if (n.kind === 'interrupted')
    return (
      <div className="bubble-notice text-base">
        <p>{t('notice.interrupted')}</p>
      </div>
    )
  if (n.kind === 'vet')
    return (
      <div className="bubble-notice text-base flex flex-col gap-2">
        <p>{t('notice.vet', { n: n.vetted })}</p>
        {n.fails.length > 0 ? (
          <>
            <p>{t('notice.vet.fails', { n: n.fails.length })}</p>
            <ul className="flex flex-col gap-1">
              {n.fails.map((f) => (
                <li key={f.id} className="flex flex-wrap items-baseline gap-x-2">
                  <RichText text={`@${f.handle}`} />
                  <span className="text-ink-2">({f.criteria.map(label).join(', ')})</span>
                  {state.candidates[f.id] && (
                    <button type="button" className="btn-link text-sm" onClick={() => openCandidate(f.id)}>
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
          <p className="text-ink-2">{t('notice.vet.none')}</p>
        )}
      </div>
    )
  return (
    <div className="bubble-notice text-base flex flex-col gap-1">
      <p>{t('notice.goal', { from: n.from, to: n.to })}</p>
      <p className="text-ink-2">
        {t('notice.goal.dropped', { n: n.dropped })} {t('notice.goal.returned', { n: n.returned })}
      </p>
      <button type="button" className="btn-link text-sm w-max" onClick={() => reveal('diff')}>
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
          <span className="smallcaps">{t('chat.summary')}</span>
          <Notice n={m.notice} />
        </div>
      )
    return (
      <div className="text-center">
        <span className="inline-block text-sm text-ink-2 border border-dashed border-rule-strong rounded-sm px-2 py-1">
          <RichText text={m.text} />
        </span>
      </div>
    )
  }
  if (m.role === 'user')
    return (
      <div className="flex flex-col items-end gap-1" data-testid="chat-message" data-role="user">
        <span className="smallcaps">{t('chat.you')}</span>
        <div className="bubble-user text-base">
          <RichText text={m.text} />
        </div>
      </div>
    )
  return (
    <div className="flex flex-col gap-2" aria-busy={m.pending || undefined} data-testid="chat-message" data-role="assistant" data-pending={m.pending ? 'true' : undefined}>
      <span className="smallcaps">{t('chat.bot')}</span>
      {(m.text || m.pending) && (
        <div className={`bubble-bot text-base leading-relaxed ${m.pending ? 'caret' : ''}`}>
          {m.text ? <RichText text={m.text} lang={m.lang} /> : <span className="text-ink-3">{t('chat.thinking')}</span>}
        </div>
      )}
      {m.tools.length > 0 && (
        <div className="flex flex-col items-start gap-1 pl-3">
          {m.tools.map((tool, i) => (
            <ToolLine key={i} tool={tool} />
          ))}
        </div>
      )}
      {m.error && <div className="pl-3 text-sm text-ink-2 border-l-2 border-dashed border-ink-3">{m.error}</div>}
    </div>
  )
}

export function Chat({ collapsed, onCollapse, visible }: { collapsed: boolean; onCollapse: (v: boolean) => void; visible: boolean }) {
  const { state, t, lang, actions, demoStatus, chatDraft } = useApp()
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
  // during the interview the next step is to answer; once the funnel runs, "Odeslat" is the primary
  // button only when there is something to send (one primary per screen, never an empty one)
  const primary = primaryAction(state, !!demoStatus?.bakeryDone) === 'chat' && (!runStarted(state) || text.trim() !== '')

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

  if (collapsed)
    return (
      <div className="hidden md:flex flex-col items-center h-full py-3 gap-3">
        <h2 id="chat-h" className="sr-only">
          {t('chat.title')}
        </h2>
        <button ref={toggleRef} type="button" className="btn btn-ghost !px-0 w-9 h-9" onClick={() => onCollapse(false)} aria-label={t('chat.expand')} aria-expanded={false} title={t('chat.expand')}>
          <span aria-hidden>»</span>
        </button>
        <button
          type="button"
          className="flex-1 w-full flex items-start justify-center pt-2 text-sm text-ink-2 hover:text-ink"
          onClick={() => onCollapse(false)}
          aria-hidden
          tabIndex={-1}
        >
          <span style={{ writingMode: 'vertical-rl' }} className="font-display text-md">
            {t('chat.title')}
          </span>
        </button>
      </div>
    )

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 pt-4 pb-3 border-b border-rule flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <h2 id="chat-h" className="font-display text-lg font-semibold leading-tight">
            {t('chat.title')}
          </h2>
          <p className="text-sm text-ink-3 mt-1">{t('chat.subtitle')}</p>
        </div>
        <button
          ref={toggleRef}
          type="button"
          className="btn btn-ghost !px-0 w-8 h-8 max-md:hidden"
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
        aria-busy={state.chatBusy}
        className={`relative min-h-0 overflow-y-auto scroll-thin px-4 flex flex-col gap-4 overscroll-contain ${empty ? 'flex-none' : 'flex-1 py-4'}`}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
      >
        {state.chat.map((m) => (
          <Message key={m.id} m={m} />
        ))}
      </div>

      {/* empty screen: two ways in. Outside the live log region. */}
      {empty && (
        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin px-4 py-4 flex flex-col gap-3 overscroll-contain [&>*]:shrink-0">
          <div className="flex flex-col gap-2">
            <div className="font-display text-lg italic text-ink-2">{t('chat.empty.title')}</div>
            <p className="text-base text-ink-2">{t('chat.empty.body')}</p>
          </div>
          <span className="smallcaps mt-1">{t('chat.examples')}</span>
          {(['chat.suggest.1', 'chat.suggest.2', 'chat.suggest.subject', 'chat.suggest.3'] as const).map((k) => (
            <button key={k} type="button" className="text-left text-sm px-3 py-2 min-h-8 border border-rule rounded-sm bg-card hover:border-accent" onClick={() => {
              send(translate(lang, k))
              // the starters unmount: the guide asks a question next, so the composer takes focus
              window.setTimeout(() => inputRef.current?.focus(), 30)
            }}>
              <RichText text={t(k)} />
            </button>
          ))}
          <div className="or-rule" aria-hidden>
            <span>{t('subject.or')}</span>
          </div>
          <SubjectEntry />
        </div>
      )}

      <form
        className="border-t border-rule p-3 flex flex-wrap gap-2 items-end bg-paper-2/60"
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
          className="field resize-none min-h-[44px] max-h-[140px] !w-auto flex-1 min-w-0"
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
        <button type="submit" data-testid="chat-send" className={`btn ${primary ? 'btn-primary' : ''} min-h-[44px]`} aria-disabled={state.chatBusy || undefined}>
          {t('chat.send')}
        </button>
        {(tooLong || text.length > MAX_CHAT - 500) && (
          <p id={`${inputId}-len`} role={tooLong ? 'alert' : undefined} className={`basis-full text-sm ${tooLong ? 'text-ink border-l-2 border-ink pl-2' : 'text-ink-2'}`}>
            {t(tooLong ? 'chat.tooLong' : 'chat.length', { n: text.trim().length, max: MAX_CHAT })}
          </p>
        )}
      </form>
    </div>
  )
}
