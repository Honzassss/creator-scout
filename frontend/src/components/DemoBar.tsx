import { useApp } from '../store'
import { modeCounts, primaryAction } from '../state'
import { useMockMode } from './primitives'
import { PRESETS } from '../lib/presets'

/** Cached data: a quiet but always-visible strip (MOCK has its own, louder one). */
export function CacheBanner() {
  const { t, state } = useApp()
  const mock = useMockMode()
  if (mock) return null
  const counts = modeCounts(state)
  const cached = state.health?.source_mode === 'cache' || (counts.cache > 0 && counts.live === 0)
  if (!cached) return null
  return (
    <div role="region" aria-label={t('cache.region')} className="cache-banner relative z-[45] flex items-center justify-center gap-3 h-7 px-3 text-center">
      <span className="truncate max-md:hidden">{t('cache.banner')}</span>
      <span className="truncate md:hidden">{t('cache.banner.short')}</span>
    </div>
  )
}

export function MockBanner() {
  const { t, demo } = useApp()
  const mock = useMockMode()
  if (!mock) return null
  return (
    <div role="region" aria-label={t('mock.region')} className="mock-banner relative z-[45] flex items-center justify-center gap-3 h-7 px-3 text-center">
      <span aria-hidden>▲</span>
      <span className="truncate max-md:hidden">{demo ? t('mock.banner.demo') : t('mock.banner')}</span>
      <span className="truncate md:hidden">{t('mock.banner.short')}</span>
      <span aria-hidden>▲</span>
    </div>
  )
}

export function DemoBar() {
  const { demo, demoStatus, t, state, dispatch, lang } = useApp()
  if (!demo || !demoStatus) return null
  const primary = primaryAction(state, demoStatus.bakeryDone) === 'demoGoal'
  const s = demoStatus
  // subject scenario: the report alone is half the story; the next step is the same creator with another goal
  const subjectNext = s.phase === 'subject' && s.subjectDone && !s.playing
  const otherGoal = s.subjectGoal === 'fitness' ? 'bakery' : 'fitness'
  const done = s.phase === 'bakery' ? s.bakeryDone : s.phase === 'goal' ? s.goalDone : s.phase === 'subjectGoal' ? s.subjectDone && !s.playing : false
  const label =
    s.phase === 'idle' ? t('demo.phase.idle') : subjectNext ? t('demo.subjectReady') : done ? t('demo.done') : s.playing ? t('demo.playing') : t('demo.paused')
  const pct = `${Math.round(s.progress * 100)}${lang === 'cs' ? '\u00a0%' : '%'}`
  const phaseLabel =
    s.phase === 'bakery' ? t('demo.phase.bakery') : s.phase === 'goal' ? t('demo.phase.goal') : s.phase === 'subject' ? t('demo.phase.subject') : s.phase === 'subjectGoal' ? t('demo.phase.subjectGoal') : t('demo.scenario')
  const switchTo = (sc: 'discovery' | 'subject') => {
    dispatch({ type: 'reset' })
    if (sc === 'subject') demo.playSubject({})
    else demo.playDiscovery()
  }
  return (
    <div role="region" aria-label={t('demo.region')} className="flex items-center gap-x-3 gap-y-1 px-4 py-1 border-b border-rule bg-mock-bg text-sm flex-wrap">
      <span className="mock-tag">MOCK</span>
      <span className="meta !text-ink">
        {phaseLabel} · {label}
        {s.phase !== 'idle' && <> · {pct}</>}
      </span>
      <div className="h-1 w-28 bg-paper-3 rounded-full overflow-hidden max-md:hidden" role="img" aria-label={`${t('demo.progress')}: ${pct}`}>
        <div
          className="h-full w-full bg-ink-2 origin-left"
          style={{ transform: `scaleX(${s.progress})`, transition: 'transform var(--dur-base) var(--ease)' }}
        />
      </div>
      <div className="flex items-center gap-1 ml-auto flex-wrap">
        <div className="seg !min-h-6 mr-1" role="group" aria-label={t('demo.scenario')}>
          {(['discovery', 'subject'] as const).map((sc) => (
            <button key={sc} type="button" className="!min-h-6 !text-sm" aria-pressed={s.scenario === sc} onClick={() => s.scenario !== sc && switchTo(sc)}>
              {t(sc === 'subject' ? 'demo.scenario.subject' : 'demo.scenario.discovery')}
            </button>
          ))}
        </div>
        {!done && !subjectNext && s.phase !== 'idle' &&
          (s.playing ? (
            <button type="button" className="btn btn-sm" onClick={() => demo.pause()}>
              <span aria-hidden>❚❚</span> {t('demo.pause')}
            </button>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => demo.resume()}>
              <span aria-hidden>▶</span> {t('demo.play')}
            </button>
          ))}
        <button type="button" className="btn btn-sm" onClick={() => demo.restart()}>
          <span aria-hidden>↺</span> {t('demo.restart')}
        </button>
        <span className="text-sm text-ink-2 ml-1 max-md:hidden" aria-hidden>
          {t('demo.speed')}
        </span>
        {[1, 2, 4].map((n) => (
          <button
            key={n}
            type="button"
            className={`btn btn-sm tnum max-md:!hidden ${s.speed === n ? '!bg-ink !text-paper !border-ink' : ''}`}
            onClick={() => demo.setSpeed(n)}
            aria-pressed={s.speed === n}
            aria-label={t('demo.speedN', { n })}
          >
            {n}×
          </button>
        ))}
        {subjectNext && (
          <button type="button" className="btn btn-sm btn-primary" onClick={() => demo.subjectGoal(otherGoal)}>
            <span className="max-md:hidden">{t('demo.subjectGoal', { goal: PRESETS[otherGoal][lang].business_type })}</span>
            <span className="md:hidden">{t('demo.subjectGoal.short')}</span> <span aria-hidden>→</span>
          </button>
        )}
        {s.phase === 'bakery' && (
          <button type="button" className={`btn btn-sm ${primary ? 'btn-primary' : ''}`} onClick={() => demo.playGoalChange()}>
            <span className="max-md:hidden">{t('demo.goal')}</span>
            <span className="md:hidden">{t('demo.goal.short')}</span> <span aria-hidden>→</span>
          </button>
        )}
      </div>
    </div>
  )
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
      className="fixed right-4 z-[70] flex flex-col gap-2 max-w-[min(420px,calc(100vw-32px))]"
      style={{ bottom: 'calc(56px + env(safe-area-inset-bottom))' }}
    >
      <div role="status" aria-live="polite" className="flex flex-col gap-2">
        {state.errors.slice(-3).map((e) => (
          <div key={e.id} className="sheet px-4 py-3 flex items-start gap-3 border-ink-2 shadow-[var(--shadow-float)]">
            <span className="text-base flex-1 break-words">{e.message}</span>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => dispatch({ type: 'error.dismiss', id: e.id })}>
              {t('error.dismiss')}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
