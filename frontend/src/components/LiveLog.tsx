import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../store'
import { sensitiveTotal, type StoredLog } from '../state'
import { fmtTime, type I18nKey } from '../i18n'
import { ModeBadge, RichText } from './primitives'
import { useEscapeLayer } from '../lib/useDialog'

interface Row {
  key: string
  line: StoredLog
  /** the technical twin of a human line ("MOCK news …" next to "Zprávy …"), merged into one row */
  detail?: string
}
interface Group {
  round: number | null
  rows: Row[]
}

/** Group log lines by round. The engine writes "Kolo N: …" lines: a summary with "→" closes round N,
 *  any other "Kolo N:" line opens it. Twins from the same actor are merged. */
function groupLog(log: StoredLog[]): Group[] {
  const groups: Group[] = []
  let round: number | null = 0
  let cur: Group | null = null
  // after a goal / criteria change the re-renders and the refill ("Fetching missing data", its comments)
  // belong to the recompute, not to the last round, until the engine opens a round again
  let recompute = false
  const RECOMPUTE = /přepoč|přepočít|recomput|re-?render|nový cíl|new goal|goal chang|cíl změn|změna cíle|doplňuji data|fetching missing|missing data/i
  const push = (row: Row, r: number | null) => {
    if (!cur || cur.round !== r) {
      cur = { round: r, rows: [] }
      groups.push(cur)
    }
    cur.rows.push(row)
  }
  for (let i = 0; i < log.length; i++) {
    const l = log[i]
    const next = log[i + 1]
    // "MOCK posts @x: …" followed by the human line from the same actor: one row
    const sameTool = (a?: string | null, b?: string | null) => !!a && !!b && (a === b || a.startsWith(`${b}:`) || b.startsWith(`${a}:`))
    if (/^MOCK\s/.test(l.text) && next && sameTool(next.actor, l.actor) && !/^MOCK\s/.test(next.text)) {
      const m = /^(?:Kolo|Round) (\d):/.exec(next.text)
      push({ key: next.key, line: next, detail: l.text }, m ? Number(m[1]) : recompute ? null : round)
      i++
      continue
    }
    const m = /^(?:Kolo|Round) (\d)[:\s]/.exec(l.text)
    if (m && (l.actor === 'engine' || !l.actor)) {
      const n = Number(m[1])
      recompute = false
      push({ key: l.key, line: l }, n)
      round = /→/.test(l.text) ? Math.min(n + 1, 4) : n
      continue
    }
    if ((l.actor === 'engine' || l.actor === 'report') && RECOMPUTE.test(l.text)) recompute = true
    push({ key: l.key, line: l }, recompute ? null : round)
  }
  return groups
}

/** Shorten at a word boundary (never in the middle of a word). */
function wordCut(s: string, max = 140): string {
  if (s.length <= max) return s
  const cut = s.slice(0, max)
  return `${cut.slice(0, cut.lastIndexOf(' '))} …`
}

export function LiveLog() {
  const { state, t, lang } = useApp()
  const [open, setOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const secRef = useRef<HTMLElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const sens = sensitiveTotal(state)
  const last = state.log[state.log.length - 1]
  const groups = useMemo(() => groupLog(state.log), [state.log])
  // the header counts the rows shown (a MOCK line and its human twin are one row)
  const rowCount = groups.reduce((n, g) => n + g.rows.length, 0)
  const running = !state.interrupted && (state.runStatus === 'running' || state.currentRound != null || Object.keys(state.vetting).length > 0)

  useEffect(() => {
    const el = listRef.current
    if (open && el) el.scrollTop = el.scrollHeight
  }, [open, state.log.length])

  // The log sticks to the bottom of the results column and covers what is under it (up to 300 px
  // when open). WCAG 2.4.11: a focused control must never end up hidden behind it.
  //  1. #board's scroll-padding-bottom follows the log's real height, so scrollIntoView and focus
  //     scrolling stop above it;
  //  2. focus that lands behind the open log scrolls the board until the control is clear;
  //  3. Escape closes the log (focus inside it goes back to its toggle).
  // It also sets --log-h on #board, so sticky panels above end where this bar starts (it grows
  // when a line wraps).
  useLayoutEffect(() => {
    const el = secRef.current
    const board = document.getElementById('board')
    if (!el || !board) return
    const set = () => {
      board.style.scrollPaddingBottom = `${Math.ceil(el.getBoundingClientRect().height) + 12}px`
      board.style.setProperty('--log-h', `${el.offsetHeight}px`)
    }
    set()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(set) : null
    ro?.observe(el)
    return () => {
      ro?.disconnect()
      board.style.scrollPaddingBottom = ''
      board.style.removeProperty('--log-h')
    }
  }, [])
  useEffect(() => {
    if (!open) return
    const board = document.getElementById('board')
    if (!board) return
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement | null
      const sec = secRef.current
      if (!target || !sec || sec.contains(target)) return
      window.requestAnimationFrame(() => {
        const r = target.getBoundingClientRect()
        const top = sec.getBoundingClientRect().top
        if (r.bottom > top - 8) board.scrollBy({ top: r.bottom - top + 16 })
      })
    }
    board.addEventListener('focusin', onFocusIn)
    return () => board.removeEventListener('focusin', onFocusIn)
  }, [open])
  useEscapeLayer(open, () => {
    const inside = !!secRef.current?.contains(document.activeElement)
    setOpen(false)
    if (inside) btnRef.current?.focus()
  })

  return (
    <section
      ref={secRef}
      className="livelog sticky bottom-0 z-10 -mx-3 sm:-mx-4 md:-mx-6 mt-2 border-t border-[var(--line)] bg-[var(--surface)] shadow-[0_-1px_2px_rgba(24,44,54,.06)]"
      aria-labelledby="log-h"
    >
      <h2 id="log-h" className="sr-only">
        {t('log.title')}
      </h2>
      <button
        ref={btnRef}
        type="button"
        className="w-full flex items-center gap-3 px-3 sm:px-4 md:px-6 py-2 text-left min-h-11 focus-visible:outline-offset-[-2px] transition-colors duration-[var(--dur-1)] hover:bg-[var(--neutral-tint)]"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="log-body"
        // one short name ("Run log, idle, 20 lines"); the last line shown next to it is a visual preview
        aria-label={`${t('log.title')}, ${running ? t('log.running') : t('log.idle')}, ${t('log.lines', { n: rowCount })}`}
      >
        <span className={`dot ${running ? 'dot-live' : 'dot-idle'}`} aria-hidden />
        <span className="text-[15px] leading-[22px] font-semibold text-[var(--text)] whitespace-nowrap" aria-hidden>
          {t('log.title')}
        </span>
        <span className="text-[12px] leading-4 text-[var(--text-3)] tabular-nums whitespace-nowrap max-sm:hidden" aria-hidden>
          {t('log.lines', { n: rowCount })}
        </span>
        {sens > 0 && (
          <span className="text-[12px] leading-4 text-[var(--text-2)] border border-dashed border-[var(--field)] px-1.5 py-px rounded-[var(--r-tag)] whitespace-nowrap max-md:hidden">
            {t('log.sensitive', { n: sens })}
          </span>
        )}
        {/* the latest line: replaced in place, not animated (the round regions carry the motion) */}
        {!open && last ? (
          <span className="flex-1 min-w-0 truncate text-[13px] leading-[18px] text-[var(--text-2)] max-sm:hidden" aria-hidden>
            {last.actor && (
              <span className="font-mono text-[12px] text-[var(--text-3)] mr-2" translate="no">
                {last.actor}
              </span>
            )}
            <RichText text={wordCut(last.text)} />
          </span>
        ) : (
          <span className="flex-1" />
        )}
        <span className="ml-auto flex-none inline-flex items-center gap-1 text-[13px] leading-[18px] font-medium text-[var(--accent)] whitespace-nowrap" aria-hidden>
          {open ? t('log.hide') : t('log.show')}
          <span aria-hidden>{open ? '↓' : '↑'}</span>
        </span>
      </button>
      {open && (
        <div
          id="log-body"
          ref={listRef}
          className="m-enter max-h-[300px] overflow-y-auto scroll-thin px-3 sm:px-4 md:px-6 pb-3 border-t border-[var(--line)] overscroll-contain"
          tabIndex={0}
          role="group"
          aria-label={t('log.title')}
        >
          {state.log.length === 0 && <p className="text-[13px] leading-[18px] text-[var(--text-2)] py-3">{t('log.empty')}</p>}
          {groups.map((g, gi) => (
            <div key={gi} className="mt-3">
              <h3 className="sticky top-0 z-[1] bg-[var(--surface)] py-1.5 flex items-center gap-2 text-[12px] leading-4 font-semibold text-[var(--text-2)]">
                <span className="w-4 text-center text-[var(--text-3)]" aria-hidden>
                  {g.round == null ? '~' : state.rounds.some((r) => r.round === g.round) && state.currentRound !== g.round ? '✓' : '·'}
                </span>
                {g.round == null ? t('log.group.other') : t('log.group', { n: g.round, name: t(`round.${g.round}` as I18nKey) })}
                <span className="font-normal text-[var(--text-3)] tabular-nums">· {t('log.lines', { n: g.rows.length })}</span>
              </h3>
              <ol role="list" className="flex flex-col">
                {g.rows.map(({ key, line: l, detail }) => (
                  <li
                    key={key}
                    className="grid grid-cols-[minmax(0,180px)_1fr_auto_64px] gap-3 py-1.5 border-b border-[var(--line)] last:border-b-0 text-[13px] leading-[18px] items-baseline max-md:grid-cols-[1fr_auto] max-md:gap-x-2"
                  >
                    <span className="font-mono text-[12px] leading-4 text-[var(--text-3)] truncate max-md:col-span-2" title={l.actor ?? ''} translate="no">
                      {l.actor ?? '–'}
                    </span>
                    <span className="text-[var(--text)] min-w-0 break-words">
                      <RichText text={l.text} />
                      {/* the technical twin ("MOCK discover: …; under 18 left out: 1") stays readable, and blurrable */}
                      {detail && (
                        <span className="block text-[12px] leading-4 text-[var(--text-3)] mt-0.5">
                          <RichText text={detail} />
                        </span>
                      )}
                    </span>
                    <span>{l.mode && <ModeBadge mode={l.mode} />}</span>
                    <span className="text-[12px] leading-4 text-[var(--text-3)] tabular-nums text-right max-md:hidden">{fmtTime(l.ts, lang)}</span>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
