import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { useApp } from '../store'
import { modeCounts, primaryAction } from '../state'
import { useMockMode } from './primitives'
import { PRESETS } from '../lib/presets'

/* The info strip (spec 6): one compact light-gray strip (32 px) above the top bar for the data mode.
   Demo: MOCK label, scenario, phase and grouped playback controls. Mock backend: MOCK label + one line.
   Cached data: CACHED label + one line. Never a colored frame or stripes around the app.
   It sets --mock-h (its real height) on <html>, so the scrim, drawer and modals start below it and the
   label stays visible while they are open. */

/** "MOCK · fictional data" -> ["MOCK", "fictional data"] (the label is drawn as a tag, the rest as text). */
function splitTag(s: string): [string, string] {
  const i = s.indexOf(' · ')
  return i < 0 ? [s, ''] : [s.slice(0, i), s.slice(i + 3)]
}

/** MOCK: a filled dark tag. CACHED: a dashed outline tag. Different by shape and text, not only color. */
export function ModeTag({ kind, children, title }: { kind: 'mock' | 'cache'; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      translate="no"
      className={`inline-flex flex-none items-center h-5 px-1.5 rounded-[var(--r-tag)] text-[11px] leading-4 font-semibold tracking-[0.06em] uppercase ${
        kind === 'mock' ? 'bg-[var(--text)] text-white' : 'border border-dashed border-[var(--text-2)] text-[var(--text)] bg-[var(--surface)]'
      }`}
    >
      {children}
    </span>
  )
}

function useCached(): boolean {
  const { state } = useApp()
  const counts = modeCounts(state)
  return state.health?.source_mode === 'cache' || (counts.cache > 0 && counts.live === 0)
}

/** Publishes the strip's height as --mock-h on <html> (0 when no strip). */
function useStripHeight<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useLayoutEffect(() => {
    const el = ref.current
    const root = document.documentElement
    if (!el) return
    const set = () => root.style.setProperty('--mock-h', `${Math.ceil(el.getBoundingClientRect().height)}px`)
    set()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(set) : null
    ro?.observe(el)
    return () => {
      ro?.disconnect()
      root.style.removeProperty('--mock-h')
    }
  }, [])
  return ref
}

const STRIP =
  'relative z-[45] flex items-center gap-x-3 min-h-8 px-3 sm:px-4 md:px-6 border-b border-[var(--line)] bg-[var(--neutral-tint)] text-[13px] leading-[18px] text-[var(--text-2)]'

/** Mock backend or cached data (no demo): one line. */
function DataStrip() {
  const { t } = useApp()
  const mock = useMockMode()
  const ref = useStripHeight<HTMLDivElement>()
  const [tag, text] = splitTag(mock ? t('mock.banner') : t('cache.banner'))
  const [, short] = splitTag(mock ? t('mock.banner.short') : t('cache.banner.short'))
  return (
    <div ref={ref} role="region" aria-label={mock ? t('mock.region') : t('cache.region')} className={STRIP}>
      <ModeTag kind={mock ? 'mock' : 'cache'}>{tag}</ModeTag>
      <span className="min-w-0 truncate max-md:hidden">{text}</span>
      <span className="min-w-0 truncate md:hidden">{short}</span>
    </div>
  )
}

/** Strip buttons: 28 px on desktop; on phones 32 px icons with a 44 x 44 hit area (spec 14). */
const SB =
  'relative inline-flex flex-none items-center justify-center gap-1.5 h-7 px-2.5 rounded-[var(--r-control)] border border-[var(--field)] bg-[var(--surface)] text-[13px] leading-[18px] font-medium text-[var(--text)] whitespace-nowrap transition-colors duration-[var(--dur-1)] hover:bg-[var(--neutral-tint)] active:bg-[var(--line)] max-md:h-8 max-md:min-w-8 max-md:after:absolute max-md:after:-inset-[7px]'
const SB_PRIMARY =
  'relative inline-flex flex-none items-center justify-center gap-1.5 h-7 px-2.5 rounded-[var(--r-control)] border border-[var(--accent)] bg-[var(--accent)] text-[13px] leading-[18px] font-semibold text-white whitespace-nowrap transition-colors duration-[var(--dur-1)] hover:bg-[var(--accent-hover)] hover:border-[var(--accent-hover)] active:bg-[var(--accent-press)] max-md:h-8 max-md:min-w-8 max-md:after:absolute max-md:after:-inset-[7px]'
/** one segment of a grouped control (scenario, speed) */
const SEG = (on: boolean) =>
  `inline-flex items-center justify-center h-6 px-2.5 rounded-[6px] text-[13px] leading-[18px] font-medium whitespace-nowrap transition-colors duration-[var(--dur-1)] ${
    on ? 'bg-[var(--accent)] text-white' : 'text-[var(--text)] hover:bg-[var(--neutral-tint)]'
  }`
const GROUP = 'inline-flex items-center gap-0.5 p-px rounded-[var(--r-control)] border border-[var(--field)] bg-[var(--surface)]'

function DemoStrip() {
  const { demo, demoStatus, t, state, dispatch, lang } = useApp()
  const ref = useStripHeight<HTMLDivElement>()
  // Focus never falls back to <body> (WCAG 2.4.3): a step button that unmounts hands focus to Restart,
  // which is always there. Pause/Play tracks focus because it disappears when a phase finishes on its own.
  const restartRef = useRef<HTMLButtonElement>(null)
  const playFocused = useRef(false)
  useLayoutEffect(() => {
    if (!playFocused.current) return
    const el = document.activeElement
    if (el && el !== document.body) return
    playFocused.current = false
    restartRef.current?.focus()
  })
  /** run a step whose button unmounts: move focus to Restart first */
  const step = (run: () => void) => {
    restartRef.current?.focus()
    run()
  }
  const trackFocus = { onFocus: () => (playFocused.current = true), onBlur: () => (playFocused.current = false) }
  if (!demo || !demoStatus) return null
  const primary = primaryAction(state, demoStatus.bakeryDone) === 'demoGoal'
  const s = demoStatus
  // subject scenario: the report alone is half the story; the next step is the same creator with another goal
  const subjectNext = s.phase === 'subject' && s.subjectDone && !s.playing
  const otherGoal = s.subjectGoal === 'fitness' ? 'bakery' : 'fitness'
  const done = s.phase === 'bakery' ? s.bakeryDone : s.phase === 'goal' ? s.goalDone : s.phase === 'subjectGoal' ? s.subjectDone && !s.playing : false
  const label =
    s.phase === 'idle' ? t('demo.phase.idle') : subjectNext ? t('demo.subjectReady') : done ? t('demo.done') : s.playing ? t('demo.playing') : t('demo.paused')
  const pct = `${Math.round(s.progress * 100)}${lang === 'cs' ? ' %' : '%'}`
  const phaseLabel =
    s.phase === 'bakery' ? t('demo.phase.bakery') : s.phase === 'goal' ? t('demo.phase.goal') : s.phase === 'subject' ? t('demo.phase.subject') : s.phase === 'subjectGoal' ? t('demo.phase.subjectGoal') : t('demo.scenario')
  const switchTo = (sc: 'discovery' | 'subject') => {
    dispatch({ type: 'reset' })
    if (sc === 'subject') demo.playSubject({})
    else demo.playDiscovery()
  }
  const [mockTag] = splitTag(t('mock.banner.demo'))
  return (
    <div ref={ref} role="region" aria-label={t('demo.region')} className={STRIP}>
      <ModeTag kind="mock" title={t('mock.banner.demo')}>
        {mockTag}
      </ModeTag>
      <span className="sr-only">{t('mock.banner.demo')}. </span>

      {/* status: phase (keyed: a new phase enters, never crossfades over the old one) · state · percent */}
      <span className="flex min-w-0 items-baseline gap-1 lg:gap-1.5 text-[var(--text)]" aria-live="off">
        <span key={s.phase} className="m-enter truncate md:shrink-0 font-medium">
          {phaseLabel}
        </span>
        <span aria-hidden className="text-[var(--text-3)] max-sm:hidden">
          ·
        </span>
        <span className="truncate lg:shrink-0 text-[var(--text-2)] max-sm:hidden">{label}</span>
        {s.phase !== 'idle' && (
          <span className="flex-none text-right tabular-nums text-[var(--text-2)] min-w-[4.5ch]">{pct}</span>
        )}
      </span>
      <div className="flex-none h-1 w-24 rounded-full bg-[var(--line)] overflow-hidden max-xl:hidden" role="img" aria-label={`${t('demo.progress')}: ${pct}`}>
        <div
          className="h-full w-full bg-[var(--accent)] origin-left"
          style={{ transform: `scaleX(${s.progress})`, transition: 'transform var(--dur-2, 200ms) var(--ease)' }}
        />
      </div>

      {/* controls, grouped: scenario | playback (play/pause, restart, speed) | next step */}
      <div className="flex flex-none items-center gap-2 lg:gap-3 ml-auto">
        <div className={`${GROUP} max-md:hidden`} role="group" aria-label={t('demo.scenario')}>
          {(['discovery', 'subject'] as const).map((sc) => (
            <button key={sc} type="button" className={SEG(s.scenario === sc)} aria-pressed={s.scenario === sc} onClick={() => s.scenario !== sc && switchTo(sc)}>
              {t(sc === 'subject' ? 'demo.scenario.subject' : 'demo.scenario.discovery')}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 max-md:gap-3" role="group" aria-label={t('demo.region')}>
          {!done && !subjectNext && s.phase !== 'idle' &&
            (s.playing ? (
              <button type="button" className={SB} onClick={() => demo.pause()} title={t('demo.pause')} {...trackFocus}>
                <span aria-hidden className="text-[11px]">❚❚</span>
                <span className="max-lg:sr-only">{t('demo.pause')}</span>
              </button>
            ) : (
              <button type="button" className={SB} onClick={() => demo.resume()} title={t('demo.play')} {...trackFocus}>
                <span aria-hidden className="text-[11px]">▶</span>
                <span className="max-lg:sr-only">{t('demo.play')}</span>
              </button>
            ))}
          <button ref={restartRef} type="button" className={SB} onClick={() => demo.restart()} title={t('demo.restart')}>
            <span aria-hidden>↺</span>
            <span className="max-lg:sr-only">{t('demo.restart')}</span>
          </button>
          <div className={`${GROUP} ml-1 max-md:hidden`} role="group" aria-label={t('demo.speed')}>
            {[1, 2, 4].map((n) => (
              <button
                key={n}
                type="button"
                className={`${SEG(s.speed === n)} tabular-nums !px-2`}
                onClick={() => demo.setSpeed(n)}
                aria-pressed={s.speed === n}
                aria-label={t('demo.speedN', { n })}
                title={t('demo.speedN', { n })}
              >
                {n}×
              </button>
            ))}
          </div>
        </div>

        {subjectNext && (
          <button type="button" className={SB_PRIMARY} onClick={() => step(() => demo.subjectGoal(otherGoal))}>
            <span className="max-xl:hidden">{t('demo.subjectGoal', { goal: PRESETS[otherGoal][lang].business_type })}</span>
            <span className="xl:hidden max-sm:sr-only">{t('demo.subjectGoal.short')}</span>
            <span aria-hidden>→</span>
          </button>
        )}
        {s.phase === 'bakery' && (
          <button type="button" className={primary ? SB_PRIMARY : SB} onClick={() => step(() => demo.playGoalChange())}>
            <span className="max-xl:hidden">{t('demo.goal')}</span>
            <span className="xl:hidden max-sm:sr-only">{t('demo.goal.short')}</span>
            <span aria-hidden>→</span>
          </button>
        )}
      </div>
    </div>
  )
}

/** The one info strip: demo controls, or the MOCK / CACHED line, or nothing (live data). */
export function InfoStrip() {
  const { demo, demoStatus } = useApp()
  const mock = useMockMode()
  const cached = useCached()
  if (demo && demoStatus) return <DemoStrip />
  if (mock || cached) return <DataStrip />
  return null
}

/** Error notifications. The container is always in the DOM so a screen reader announces new ones. */
export function Toasts() {
  const { state, dispatch, t } = useApp()
  return (
    <div
      role="region"
      aria-label={t('toasts.label')}
      // stays live while a dialog makes the page inert: an error from inside the dossier is announced
      data-keep-active="true"
      className="fixed right-3 sm:right-4 z-[70] flex flex-col gap-2 max-w-[min(420px,calc(100vw-24px))]"
      style={{ bottom: 'calc(56px + env(safe-area-inset-bottom))' }}
    >
      <div role="status" aria-live="polite" className="flex flex-col gap-2">
        {state.errors.slice(-3).map((e) => (
          <div
            key={e.id}
            className="m-enter flex items-start gap-3 px-4 py-3 rounded-[var(--r-panel)] border border-[var(--line)] border-l-[3px] border-l-[var(--bad)] bg-[var(--surface)] shadow-[0_1px_2px_rgba(24,44,54,.06)]"
          >
            <span aria-hidden className="flex-none mt-0.5 inline-flex items-center justify-center w-[18px] h-[18px] rounded-full bg-[var(--bad-tint)] text-[var(--bad)] text-[12px] font-bold leading-none">
              !
            </span>
            <span className="flex-1 min-w-0 text-[15px] leading-[22px] text-[var(--text)] break-words">{e.message}</span>
            <button type="button" className="btn btn-sm btn-ghost flex-none" onClick={() => dispatch({ type: 'error.dismiss', id: e.id })}>
              {t('error.dismiss')}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
