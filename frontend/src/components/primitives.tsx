import { Fragment, createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useApp } from '../store'
import { fmtCompact, fmtDate, fmtDayMonth, fmtTime, hasKey, type I18nKey } from '../i18n'
import { csTypo } from '../lib/typo'
import { useDialog } from '../lib/useDialog'
import { useCountUp } from '../lib/motion'
import type { Lang, Mode, ResultStatus, SourceRef } from '../types'

// ---------------- light-system class sets (tokens from index.css, with the contract values as fallback) ----------------

/** Meta text: 12/16, tertiary ink, tabular digits. */
const META = 'text-[12px] leading-4 text-[var(--text-3,#5F717B)] tnum'

/** Small tag / badge: 4 px radius, 12/16 semibold caps. Caps only on these tiny labels. */
const TAG = 'inline-flex flex-none items-center gap-1 min-h-5 rounded-[4px] border px-1.5 align-middle text-[12px] leading-4 font-semibold uppercase tracking-[0.04em] whitespace-nowrap'
/** MOCK: quiet neutral tag (solid outline, dark ink); colour stays reserved for petrol. Differs from CACHED by its solid border and word. */
const TAG_MOCK = `${TAG} border-[var(--field,#6F8794)] bg-[var(--neutral-tint,#EEF2F4)] text-[var(--text,#182C36)]`
const TAG_LIVE = `${TAG} border-transparent bg-[var(--accent-tint,#E4F3F0)] text-[var(--accent,#086B68)]`
const TAG_CACHE = `${TAG} border-dashed border-[var(--field,#6F8794)] bg-[var(--surface,#FFFFFF)] text-[var(--text-2,#435965)]`

/** Criterion result tones: met = ok, not met = bad, cannot verify / waived = neutral (never amber). */
type Tone = 'pass' | 'fail' | 'unknown' | 'waived'
const toneOf = (status: ResultStatus, waived?: boolean): Tone => (waived ? 'waived' : status === 'pass' ? 'pass' : status === 'fail' ? 'fail' : 'unknown')
const TONE: Record<Tone, string> = {
  pass: 'text-[var(--ok,#1D6B3B)] bg-[var(--ok-tint,#E8F4EC)]',
  fail: 'text-[var(--bad,#A33A3A)] bg-[var(--bad-tint,#FBEDED)]',
  unknown: 'text-[var(--neutral,#4B5D67)] bg-[var(--neutral-tint,#EEF2F4)]',
  waived: 'text-[var(--neutral,#4B5D67)] bg-[var(--neutral-tint,#EEF2F4)]',
}

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
    <div
      ref={ref}
      id={id}
      className={`m-enter fixed z-[60] w-[340px] max-w-[calc(100vw-24px)] overscroll-contain rounded-[12px] border border-[var(--field,#6F8794)] bg-[var(--surface,#FFFFFF)] p-4 text-[var(--text,#182C36)] shadow-[0_1px_2px_rgba(24,44,54,.06)] focus:outline-2 focus:outline-offset-0 focus:outline-[var(--accent,#086B68)]`}
      style={{ left: pos.left, top: pos.top }}
      role="dialog"
      aria-labelledby={titleId}
      tabIndex={-1}
    >
      <h2 id={titleId} className="sr-only">
        {t('source.dialog')}
      </h2>
      {pop.caption && <p className="mb-3 border-b border-[var(--line,#DCE4E8)] pb-3 text-[15px] leading-[22px]">{pop.caption}</p>}
      <div className="scroll-thin flex max-h-[60vh] flex-col gap-4 overflow-auto">
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
                <span className="text-[13px] leading-[18px] font-medium">{platformLong(s.platform, t)}</span>
                <span className={META}>
                  {t('source.fetched')} {fmtDate(s.fetched_at, lang)} {fmtTime(s.fetched_at, lang)}
                </span>
              </div>
              {s.quote && (
                <blockquote className={`m-0 border-l-2 border-[var(--line,#DCE4E8)] pl-3 text-[15px] leading-[22px] italic ${hide}`}>
                  {lang === 'cs' ? `„${csTypo(s.quote)}“` : `“${s.quote}”`}
                </blockquote>
              )}
              <div className={`${META} font-mono break-all ${hide}`} translate="no">
                {s.url}
              </div>
              <div className={META}>
                {t('source.actor')}: <span translate="no">{s.actor ?? '–'}</span>
              </div>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                {noLink ? (
                  <>
                    <span id={noteId} className="min-w-[160px] flex-1 text-[12px] leading-4 text-[var(--text-2,#435965)]">
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
      <div className="mt-3 flex justify-end border-t border-[var(--line,#DCE4E8)] pt-2">
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

/** Static mode dot (no pulsing): live = petrol disc, mock = dark square, cache = hollow ring. */
export function ModeDot({ mode }: { mode?: Mode | null }) {
  if (!mode) return null
  const shape =
    mode === 'live'
      ? 'rounded-full bg-[var(--accent,#086B68)]'
      : mode === 'mock'
        ? 'rounded-[2px] bg-[var(--neutral,#4B5D67)]'
        : 'rounded-full border-[1.5px] border-[var(--text-2,#435965)]'
  return <span className={`inline-block size-2 flex-none ${shape}`} aria-hidden />
}

/** Data-mode badge: MOCK, CACHED or LIVE, each with its own text and shape (not colour alone). */
export function ModeBadge({ mode }: { mode?: Mode | null }) {
  if (!mode) return null
  if (mode === 'mock') return <MockTag />
  if (mode === 'cache') return <CacheTag />
  return <LiveTag />
}

export function MockTag({ short }: { short?: boolean }) {
  if (short)
    return (
      <span className={TAG_MOCK} title="MOCK">
        <span aria-hidden>M</span>
        <span className="sr-only">MOCK</span>
      </span>
    )
  return <span className={TAG_MOCK}>MOCK</span>
}

/** CACHED: dashed outline, so it reads differently from MOCK and LIVE without colour. */
export function CacheTag() {
  const { t } = useApp()
  return <span className={TAG_CACHE}>{t('mode.cache')}</span>
}

export function LiveTag() {
  const { t } = useApp()
  return (
    <span className={TAG_LIVE}>
      <span className="inline-block size-1.5 flex-none rounded-full bg-current" aria-hidden />
      {t('mode.live')}
    </span>
  )
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
  // <wbr> makes Chrome put a space into the accessible name ('@mlsna_ brnenka'), so the
  // breakable copy is hidden from screen readers and the plain handle is read instead
  return (
    <>
      <span aria-hidden>
        @
        {parts.map((p, i) => (
          <Fragment key={i}>
            {p}
            {i < parts.length - 1 && <wbr />}
          </Fragment>
        ))}
      </span>
      <span className="sr-only">@{handle}</span>
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

/** Source chip: small gray tag (6 px radius) that opens the source popover; petrol on hover / open. */
const CHIP_BASE = 'inline-flex items-center gap-1 min-h-6 rounded-[6px] border px-1.5 align-middle text-[12px] leading-4 font-medium whitespace-nowrap'
const CHIP = `${CHIP_BASE} border-[var(--field,#6F8794)] bg-[var(--bg,#F3F6F8)] text-[var(--text-2,#435965)] transition-colors duration-[var(--dur-1,120ms)] hover:border-[var(--accent,#086B68)] hover:text-[var(--accent,#086B68)] aria-expanded:border-[var(--accent,#086B68)] aria-expanded:bg-[var(--accent-tint,#E4F3F0)] aria-expanded:text-[var(--accent,#086B68)]`

export function SourceChip({ src, sources }: { src?: SourceRef | null; sources?: SourceRef[]; compact?: boolean }) {
  const { open, openFor, id } = useContext(PopCtx)
  const { t, lang } = useApp()
  const btn = useRef<HTMLButtonElement>(null)
  const list = sources ?? (src ? [src] : [])
  if (!list.length) return <span className={`${CHIP_BASE} border-dashed border-[var(--field,#6F8794)] bg-[var(--surface,#FFFFFF)] text-[var(--text-3,#5F717B)]`}>{t('source.none')}</span>
  const s = list[0]
  const mock = s.mode === 'mock'
  const expanded = openFor != null && openFor === btn.current
  // The accessible name comes from the content (visible text + hidden words), so it always contains
  // what is on screen (WCAG 2.5.3): "Zdroj: IG (Instagram) · MOCK · staženo 9. 10. 2026".
  return (
    <button
      data-testid="source-chip"
      ref={btn}
      type="button"
      className={CHIP}
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
      <span aria-hidden className="text-[var(--text-3,#5F717B)]">
        ·
      </span>
      {mock ? (
        <span className="font-semibold tracking-[0.04em] text-[var(--text,#182C36)]">MOCK</span>
      ) : s.mode === 'cache' ? (
        <>
          <span className="border-b border-dashed border-[var(--field,#6F8794)] font-semibold uppercase tracking-[0.04em] text-[var(--text,#182C36)]">{t('cache.tag')}</span>
          <span className="tnum">{fmtDayMonth(s.fetched_at, lang)}</span>
        </>
      ) : (
        <span className="tnum">{fmtDayMonth(s.fetched_at, lang)}</span>
      )}
      {list.length > 1 && <span className="tnum text-[var(--text-3,#5F717B)]">{t('source.more', { n: list.length })}</span>}
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
      data-testid="sourced"
      type="button"
      className={`m-0 border-0 bg-transparent p-0 text-left text-inherit underline decoration-[var(--text-3,#5F717B)] decoration-dotted decoration-1 underline-offset-[3px] hover:text-[var(--accent,#086B68)] hover:decoration-[var(--accent,#086B68)] ${className}`}
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

/** The mark's shape carries the meaning on its own: check, cross, question mark, dash (waived). */
function MarkSvg({ tone, size = 12 }: { tone: Tone; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false" className="flex-none">
      {tone === 'pass' && <path d="M3.5 8.5l3 3 6-7" />}
      {tone === 'fail' && <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />}
      {tone === 'unknown' && (
        <>
          <path d="M5.6 5.8a2.4 2.4 0 1 1 3.5 2.2c-.7.4-1.1.9-1.1 1.7v.3" />
          <circle cx="8" cy="12.9" r="0.4" fill="currentColor" />
        </>
      )}
      {tone === 'waived' && <path d="M4 8h8" />}
    </svg>
  )
}

/** Met / not met / cannot verify as a 16 px tinted mark (icon + hidden word). Use it only where the
 *  status word or a sentence saying it is visible next to it; otherwise use StatusTag. */
export function CritIcon({ status, waived, label: crit, silent }: { status: ResultStatus; waived?: boolean; label?: string; silent?: boolean }) {
  const { t } = useApp()
  const tone = toneOf(status, waived)
  const word = waived ? t('card.waived') : t(`card.${status}`)
  const box = `inline-flex size-4 flex-none items-center justify-center rounded-[4px] ${TONE[tone]}`
  // silent: the text next to the mark already says it (e.g. "nesplňuje: …")
  if (silent)
    return (
      <span className={box} aria-hidden>
        <MarkSvg tone={tone} />
      </span>
    )
  return (
    <span className={box} title={crit ? `${crit}: ${word}` : word}>
      <MarkSvg tone={tone} />
      <span className="sr-only">{word}</span>
    </span>
  )
}

/** Met / not met / cannot verify as icon + visible word on a small tint (4 px radius). */
export function StatusTag({ status, waived, label: crit, className = '' }: { status: ResultStatus; waived?: boolean; label?: string; className?: string }) {
  const { t } = useApp()
  const tone = toneOf(status, waived)
  const word = waived ? t('card.waived') : t(`card.${status}`)
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded-[4px] px-1.5 py-0.5 text-[13px] leading-[18px] font-medium ${TONE[tone]} ${className}`}
      title={crit ? `${crit}: ${word}` : undefined}
    >
      <MarkSvg tone={tone} />
      <span className="min-w-0">{word}</span>
    </span>
  )
}

// ---------------- misc ----------------

export function Toggle({ checked, onChange, label, className = '', testId }: { checked: boolean; onChange: (v: boolean) => void; label: string; className?: string; testId?: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className={`toggle max-md:min-h-11 ${className}`} data-testid={testId} onClick={() => onChange(!checked)}>
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

/** Count that counts to its new value in place (lib/motion useCountUp: one string in one box, never two
 *  overlapping; --dur-3 ease-out, tabular digits; `delayMs` lets it start after its region has entered;
 *  instant with reduced motion or a hidden tab). Screen readers get the final value only. */
export function Odometer({ value, format, delayMs = 0 }: { value: number; format?: (n: number) => string; delayMs?: number }) {
  const { lang } = useApp()
  const fmt = format ?? ((n: number) => (n >= 10000 ? fmtCompact(n, lang) : new Intl.NumberFormat(lang === 'cs' ? 'cs-CZ' : 'en-GB').format(n)))
  const shown = useCountUp(value, { delayMs })
  return (
    <span className="tnum">
      <span aria-hidden>{fmt(shown)}</span>
      <span className="sr-only">{fmt(value)}</span>
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
    <div role="group" aria-labelledby={`${id}-q`} className="flex flex-wrap items-center gap-2 border-t border-[var(--line,#DCE4E8)] bg-[var(--bg,#F3F6F8)] px-4 py-3 md:px-6">
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
