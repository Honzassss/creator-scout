import { Fragment, createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useApp } from '../store'
import { fmtCompact, fmtDate, fmtDayMonth, fmtTime, hasKey, type I18nKey } from '../i18n'
import { csTypo } from '../lib/typo'
import { useDialog } from '../lib/useDialog'
import type { Lang, Mode, ResultStatus, SourceRef } from '../types'

// ---------------- MOCK mode ----------------

/** True when anything on screen is MOCK: the demo, a mock backend, or any mock candidate. */
export function useMockMode(): boolean {
  const { state, demo } = useApp()
  if (demo || state.demo) return true
  if (state.health?.source_mode === 'mock') return true
  for (const id of state.order) {
    const c = state.candidates[id]
    if ((c?.profile?.source?.mode ?? c?.ref.source?.mode) === 'mock') return true
  }
  return false
}

// ---------------- source popover (one instance, rendered inside the active dialog) ----------------

interface PopState {
  sources: SourceRef[]
  caption?: string
  trigger: HTMLElement
  container: HTMLElement | null
  n: number
}
let popSeq = 0
interface PopApi {
  open: (s: SourceRef[], el: HTMLElement, caption?: string) => void
  openFor: HTMLElement | null
  id: string
}
const PopCtx = createContext<PopApi>({ open: () => undefined, openFor: null, id: 'source-popover' })

export function SourcePopoverProvider({ children }: { children: ReactNode }) {
  const [pop, setPop] = useState<PopState | null>(null)
  const id = useId().replace(/:/g, '') + 'src'
  const open = useCallback((sources: SourceRef[], el: HTMLElement, caption?: string) => {
    setPop((prev) =>
      prev && prev.trigger === el ? null : { sources, caption, trigger: el, container: el.closest<HTMLElement>('[role="dialog"][aria-modal="true"]'), n: ++popSeq },
    )
  }, [])
  const close = useCallback(() => setPop(null), [])
  const api = useMemo(() => ({ open, openFor: pop?.trigger ?? null, id }), [open, pop, id])
  const node = pop ? <SourcePopover key={pop.n} pop={pop} id={id} onClose={close} /> : null
  return (
    <PopCtx.Provider value={api}>
      {children}
      {node && (pop?.container ? createPortal(node, pop.container) : node)}
    </PopCtx.Provider>
  )
}

/** Source ids / URLs that belong to eliminated candidates (profile, posts, elimination sources). In
 *  "Rozmazat vyřazené" mode their URL, id and quote are blurred like the handle elsewhere. */
function useEliminatedRefs(): Set<string> {
  const { state } = useApp()
  return useMemo(() => {
    const out = new Set<string>()
    for (const c of Object.values(state.candidates)) {
      if (c.status !== 'eliminated') continue
      const add = (s?: { id?: string; url?: string } | null) => {
        if (s?.id) out.add(s.id)
        if (s?.url) out.add(s.url)
      }
      add(c.ref.source)
      add(c.profile?.source)
      if (c.profile?.url) out.add(c.profile.url)
      for (const p of c.profile?.latest_posts ?? []) {
        add(p.source)
        if (p.url) out.add(p.url)
      }
      for (const s of c.elimination?.sources ?? []) add(s)
    }
    return out
  }, [state.candidates])
}

function SourcePopover({ pop, id, onClose }: { pop: PopState; id: string; onClose: () => void }) {
  const { t, lang, blur } = useApp()
  const elimRefs = useEliminatedRefs()
  const triggerRef = useRef<HTMLElement | null>(pop.trigger)
  const ref = useDialog<HTMLDivElement>(true, onClose, { modal: false, trap: true, returnFocus: triggerRef })
  const rect = pop.trigger.getBoundingClientRect()
  const [pos, setPos] = useState({ left: rect.left, top: rect.bottom + 6 })
  const titleId = `${id}-title`

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = pop.trigger.getBoundingClientRect()
    const w = el.offsetWidth
    const h = el.offsetHeight
    let left = Math.min(r.left, window.innerWidth - w - 12)
    left = Math.max(12, left)
    let top = r.bottom + 6
    if (top + h > window.innerHeight - 12) top = Math.max(12, r.top - h - 6)
    setPos({ left, top })
  }, [pop, ref])

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const el = ref.current
      if (el && !el.contains(e.target as Node) && !pop.trigger.contains(e.target as Node)) onClose()
    }
    const onResize = () => onClose()
    window.addEventListener('mousedown', onDown)
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', onResize)
    }
  }, [onClose, pop.trigger, ref])

  return (
    <div ref={ref} id={id} className="popover" style={{ left: pos.left, top: pos.top }} role="dialog" aria-labelledby={titleId} tabIndex={-1}>
      <h2 id={titleId} className="sr-only">
        {t('source.dialog')}
      </h2>
      {pop.caption && <p className="text-base text-ink mb-3 pb-3 border-b border-rule">{pop.caption}</p>}
      <div className="flex flex-col gap-4 max-h-[60vh] overflow-auto scroll-thin">
        {pop.sources.map((s, i) => {
          const fake = /\.invalid(\/|$)/.test(s.url)
          // MOCK sources never link out: a fictional finding must not open a real account that may own the handle
          const noLink = fake || s.mode === 'mock'
          const hide = blur && (elimRefs.has(s.id) || elimRefs.has(s.url)) ? 'elim-id' : ''
          const noteId = `${id}-n${i}`
          return (
            <div key={`${s.id}:${i}`} className="flex flex-col gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                {s.mode === 'mock' ? <MockTag /> : <ModeBadge mode={s.mode} />}
                <span className="text-sm font-medium">{platformLong(s.platform, t)}</span>
                <span className="meta">
                  {t('source.fetched')} {fmtDate(s.fetched_at, lang)} {fmtTime(s.fetched_at, lang)}
                </span>
              </div>
              {s.quote && (
                <blockquote className={`font-display italic text-md border-l-2 border-rule-strong pl-2 text-ink ${hide}`}>
                  {lang === 'cs' ? `„${csTypo(s.quote)}“` : `“${s.quote}”`}
                </blockquote>
              )}
              <div className={`meta break-all ${hide}`} translate="no">
                {s.url}
              </div>
              <div className="meta">
                {t('source.actor')}: <span translate="no">{s.actor ?? '–'}</span>
              </div>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                {noLink ? (
                  <>
                    <span id={noteId} className="text-xs text-ink-2 flex-1 min-w-[160px]">
                      {t('source.mockUrl')}
                    </span>
                    <button type="button" className="btn btn-sm" aria-disabled="true" aria-describedby={noteId} onClick={(e) => e.preventDefault()}>
                      {t('source.open')}
                    </button>
                  </>
                ) : (
                  <a className="btn btn-sm" href={s.url} target="_blank" rel="noopener noreferrer">
                    {t('source.open')} <span aria-hidden>↗</span>
                  </a>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex justify-end mt-2 pt-2 border-t border-rule">
        <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
          {t('source.close')}
        </button>
      </div>
    </div>
  )
}

export function useSourcePopover() {
  return useContext(PopCtx).open
}

// ---------------- labels ----------------

type TFn = ReturnType<typeof useApp>['t']

export function platformLabel(p: string, t: TFn) {
  const k = `platform.${p}`
  return hasKey(k) ? t(k) : p
}
export function platformLong(p: string, t: TFn) {
  const k = `platformLong.${p}`
  return hasKey(k) ? t(k) : p
}

export function ModeDot({ mode }: { mode?: Mode | null }) {
  if (!mode) return null
  return <span className={`dot ${mode === 'live' ? 'dot-live' : mode === 'mock' ? 'dot-mock' : 'dot-idle'}`} aria-hidden />
}

export function ModeBadge({ mode }: { mode?: Mode | null }) {
  const { t } = useApp()
  if (!mode) return null
  if (mode === 'mock') return <MockTag />
  return (
    <span className="inline-flex items-center gap-2 meta !text-ink-2">
      <ModeDot mode={mode} />
      {t(`mode.${mode}`)}
    </span>
  )
}

export function MockTag({ short }: { short?: boolean }) {
  if (short)
    return (
      <span className="mock-tag" title="MOCK">
        <span aria-hidden>M</span>
        <span className="sr-only">MOCK</span>
      </span>
    )
  return <span className="mock-tag">MOCK</span>
}

/** Screen-reader-only separator, so composed accessible names pause between parts. */
export function Sep() {
  return <span className="sr-only">, </span>
}

/** "No value": a dash on screen, a word for a screen reader (never "pomlčka"). */
export function NoValue() {
  const { t } = useApp()
  return (
    <>
      <span aria-hidden>–</span>
      <span className="sr-only">{t('noValue')}</span>
    </>
  )
}

/** A @handle that may wrap after "_" or "." (never cut off with an ellipsis). */
export function Handle({ handle }: { handle: string }) {
  const parts = handle.split(/(?<=[_.])/)
  return (
    <>
      @
      {parts.map((p, i) => (
        <Fragment key={i}>
          {p}
          {i < parts.length - 1 && <wbr />}
        </Fragment>
      ))}
    </>
  )
}

/** A decorative glyph that a screen reader must not read. */
export function Glyph({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span aria-hidden className={className}>
      {children}
    </span>
  )
}

// ---------------- source chip + sourced value ----------------

/** Group sources by platform: one chip per platform, "IG ×5". */
export function groupSources(list: SourceRef[]): SourceRef[][] {
  const by = new Map<string, SourceRef[]>()
  for (const s of list) {
    const k = s.platform
    by.set(k, [...(by.get(k) ?? []), s])
  }
  return [...by.values()]
}

export function SourceChip({ src, sources }: { src?: SourceRef | null; sources?: SourceRef[]; compact?: boolean }) {
  const { open, openFor, id } = useContext(PopCtx)
  const { t, lang } = useApp()
  const btn = useRef<HTMLButtonElement>(null)
  const list = sources ?? (src ? [src] : [])
  if (!list.length) return <span className="src-chip is-none">{t('source.none')}</span>
  const s = list[0]
  const mock = s.mode === 'mock'
  const expanded = openFor != null && openFor === btn.current
  // The accessible name comes from the content (visible text + hidden words), so it always contains
  // what is on screen (WCAG 2.5.3): "Zdroj: IG (Instagram) · MOCK · staženo 9. 10. 2026".
  return (
    <button
      ref={btn}
      type="button"
      className="src-chip"
      aria-haspopup="dialog"
      aria-expanded={expanded}
      aria-controls={expanded ? id : undefined}
      onClick={(e) => {
        e.stopPropagation()
        open(list, e.currentTarget)
      }}
    >
      <span className="sr-only">{list.length > 1 ? t('source.dialogs', { n: list.length }) : t('source.dialog')}: </span>
      {!mock && <ModeDot mode={s.mode} />}
      <span>{platformLabel(s.platform, t)}</span>
      {platformLabel(s.platform, t) !== platformLong(s.platform, t) && <span className="sr-only"> ({platformLong(s.platform, t)})</span>}
      <span aria-hidden className="text-ink-3">
        ·
      </span>
      {mock ? (
        <span className="src-mock">MOCK</span>
      ) : s.mode === 'cache' ? (
        <>
          <span className="src-cache">{t('cache.tag')}</span>
          <span>{fmtDayMonth(s.fetched_at, lang)}</span>
        </>
      ) : (
        <span>{fmtDayMonth(s.fetched_at, lang)}</span>
      )}
      {list.length > 1 && <span className="text-ink-3">{t('source.more', { n: list.length })}</span>}
      <span className="sr-only">
        {' '}
        · {mock ? '' : `${t(`mode.${s.mode}`)}, `}
        {t('source.fetched')} {fmtDate(s.fetched_at, lang)}
      </span>
    </button>
  )
}

/** One chip per platform for a list of sources. */
export function SourceChips({ sources }: { sources: SourceRef[] }) {
  const groups = groupSources(sources)
  if (!groups.length) return <SourceChip sources={[]} />
  return (
    <>
      {groups.map((g, i) => (
        <SourceChip key={`${g[0].platform}:${i}`} sources={g} />
      ))}
    </>
  )
}

/** A value that clicks through to its source(s). */
export function Sourced({ sources, children, className = '', caption }: { sources?: SourceRef[] | null; children: ReactNode; className?: string; caption?: string }) {
  const open = useSourcePopover()
  if (!sources || !sources.length) return <span className={className} title={caption}>{children}</span>
  return (
    <button
      type="button"
      className={`sourced ${className}`}
      aria-haspopup="dialog"
      onClick={(e) => {
        e.stopPropagation()
        open(sources, e.currentTarget, caption)
      }}
    >
      {children}
    </button>
  )
}

// ---------------- criterion status ----------------

/** Pass / fail / unknown as a bare glyph in ink, same size and weight; the meaning is in hidden text
 *  (splněno / nesplněno / nejde ověřit). Never a box, never a traffic light. */
export function CritIcon({ status, waived, label: crit, silent }: { status: ResultStatus; waived?: boolean; label?: string; silent?: boolean }) {
  const { t } = useApp()
  const glyph = waived ? '✕' : status === 'pass' ? '✓' : status === 'fail' ? '✕' : '?'
  const word = waived ? t('card.waived') : t(`card.${status}`)
  // silent: the text next to the mark already says it (e.g. "nesplňuje: …")
  if (silent)
    return (
      <span className={`crit-mark ${waived ? 'is-waived' : ''}`} aria-hidden>
        {glyph}
      </span>
    )
  return (
    <span className={`crit-mark ${waived ? 'is-waived' : ''}`} title={crit ? `${crit}: ${word}` : word}>
      <span aria-hidden>{glyph}</span>
      <span className="sr-only">{word}</span>
    </span>
  )
}

// ---------------- misc ----------------

export function Toggle({ checked, onChange, label, className = '', testId }: { checked: boolean; onChange: (v: boolean) => void; label: string; className?: string; testId?: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className={`toggle ${className}`} data-testid={testId} onClick={() => onChange(!checked)}>
      <span className="track" aria-hidden />
      <span>{label}</span>
    </button>
  )
}

/** Renders backend or UI text: Czech typography, **bold**, and @handles (sans, translate="no";
 *  handles of eliminated candidates are wrapped so the blur toggle can hide them). */
export function RichText({ text, className, lang: textLang }: { text: string; className?: string; lang?: Lang | null }) {
  const { state, lang: uiLang } = useApp()
  // the text's own language when known (a Czech guide message under the English UI still gets Czech typography)
  const lang = textLang ?? uiLang
  const typo = lang === 'cs' ? csTypo(text) : text
  const parts = typo.split(/(@[\w.]+)/g)
  const names = useEliminatedNames()
  return (
    <span className={className}>
      {parts.map((p, i) => {
        if (!p.startsWith('@')) return <NamedText key={i} text={p} names={names} />
        const h = p.slice(1).replace(/[.]+$/, '')
        const trail = p.slice(1 + h.length)
        const c = state.candidates[`instagram:${h}`] ?? state.candidates[`tiktok:${h}`] ?? state.candidates[`youtube:${h}`]
        return (
          <span key={i}>
            <span translate="no" className={c?.status === 'eliminated' ? 'elim-id font-medium' : 'font-medium'}>
              @{h}
            </span>
            {trail}
          </span>
        )
      })}
    </span>
  )
}

/** Display names of eliminated candidates (news lines, log lines name people, not only @handles). */
function useEliminatedNames(): RegExp | null {
  const { state } = useApp()
  return useMemo(() => {
    const names = new Set<string>()
    for (const c of Object.values(state.candidates)) {
      if (c.status !== 'eliminated') continue
      const n = c.profile?.display_name?.replace(/\(MOCK\)/i, '').trim()
      if (n && n.length >= 4) names.add(n)
    }
    if (!names.size) return null
    const esc = [...names].sort((a, b) => b.length - a.length).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    return new RegExp(`(${esc.join('|')})`, 'g')
  }, [state.candidates])
}

/** Text with the names of eliminated candidates wrapped for the blur toggle. */
function NamedText({ text, names }: { text: string; names: RegExp | null }) {
  if (!names) return <InlineMd text={text} />
  const parts = text.split(names)
  if (parts.length === 1) return <InlineMd text={text} />
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span key={i} className="elim-id" translate="no">
            {p}
          </span>
        ) : (
          <InlineMd key={i} text={p} />
        ),
      )}
    </>
  )
}

function InlineMd({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((p, i) => (p.startsWith('**') && p.endsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>))}
    </>
  )
}

export function initialOf(handle: string, display?: string | null) {
  const base = (display && display.replace(/\(MOCK\)/i, '').trim()) || handle
  const ch = base.replace(/^[@_.\d]+/, '')[0] ?? handle[0] ?? '?'
  return ch.toUpperCase()
}

export function useNow(interval = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const iv = window.setInterval(() => setNow(Date.now()), interval)
    return () => window.clearInterval(iv)
  }, [interval])
  return now
}

/** Count that rolls to its new value; the previous value greys out and rolls away (<= 500 ms,
 *  transform/opacity only; reduced motion just swaps). */
export function Odometer({ value, format }: { value: number; format?: (n: number) => string }) {
  const { lang } = useApp()
  const fmt = format ?? ((n: number) => (n >= 10000 ? fmtCompact(n, lang) : new Intl.NumberFormat(lang === 'cs' ? 'cs-CZ' : 'en-GB').format(n)))
  const [prev, setPrev] = useState<number | null>(null)
  const last = useRef(value)
  useEffect(() => {
    if (last.current === value) return
    setPrev(last.current)
    last.current = value
    const tm = window.setTimeout(() => setPrev(null), 520)
    return () => window.clearTimeout(tm)
  }, [value])
  return (
    <span className="odo">
      <span key={value} className={prev != null ? 'odo-in' : undefined}>
        {fmt(value)}
      </span>
      {prev != null && (
        <span aria-hidden className="odo-out">
          {fmt(prev)}
        </span>
      )}
    </span>
  )
}

/** Smooth scroll that respects prefers-reduced-motion. */
export function scrollToEl(el: Element | null | undefined, block: ScrollLogicalPosition = 'start') {
  if (!el) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block })
}

export function tKey(k: string): I18nKey | null {
  return hasKey(k) ? k : null
}

// ---------------- unsaved edits ----------------

/**
 * Escape or a click on the scrim must not silently throw away what was typed into a dialog form
 * (Web Interface Guidelines, forms). With unsaved edits, `request()` asks first; asked again (a second
 * Escape) it keeps editing. An explicit "Zrušit" still closes at once.
 */
export function useDiscardGuard(dirty: boolean, close: () => void) {
  const [asking, setAsking] = useState(false)
  const back = useRef<HTMLElement | null>(null)
  const request = () => {
    if (!dirty) return close()
    if (asking) return keep()
    back.current = document.activeElement as HTMLElement | null
    setAsking(true)
  }
  const keep = () => {
    setAsking(false)
    const el = back.current
    window.requestAnimationFrame(() => el?.isConnected && el.focus())
  }
  return { asking, request, keep, drop: close }
}

export function DiscardBar({ guard }: { guard: ReturnType<typeof useDiscardGuard> }) {
  const { t } = useApp()
  const keepRef = useRef<HTMLButtonElement>(null)
  const id = useId()
  useEffect(() => {
    if (guard.asking) keepRef.current?.focus()
  }, [guard.asking])
  if (!guard.asking) return null
  return (
    <div role="group" aria-labelledby={`${id}-q`} className="px-6 py-3 border-t border-ink-2 bg-paper-2 flex items-center gap-2 flex-wrap">
      <p id={`${id}-q`} className="text-base font-medium mr-auto">
        {t('discard.title')}
      </p>
      <button ref={keepRef} type="button" className="btn" onClick={guard.keep}>
        {t('discard.keep')}
      </button>
      <button type="button" className="btn" onClick={guard.drop}>
        {t('discard.drop')}
      </button>
    </div>
  )
}

/** Move focus to an element once it exists (a button that started a step is about to unmount: WCAG 2.4.3).
 *  `get` is re-evaluated on every try; a non-focusable target gets tabindex=-1. */
export function focusSoon(get: () => HTMLElement | null | undefined, tries = 12) {
  const go = (n: number) => {
    const el = get()
    if (!el) {
      if (n > 0) window.setTimeout(() => go(n - 1), 50)
      return
    }
    if (!el.hasAttribute('tabindex') && !/^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) el.setAttribute('tabindex', '-1')
    el.focus({ preventScroll: true })
  }
  window.setTimeout(() => go(tries), 40)
}
