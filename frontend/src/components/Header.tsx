import { useEffect, useId, useRef, useState } from 'react'
import { useApp } from '../store'
import { lastFinishedRound, modeCounts } from '../state'
import { fmtInt } from '../i18n'
import { useDialog, useEscapeLayer } from '../lib/useDialog'
import { Toggle, useMockMode } from './primitives'
import { InfoStrip } from './DemoBar'
import type { AppState } from '../state'

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden className="flex-none text-[var(--accent)]">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M7 9h18l-6.5 8.5V24l-5 2.2v-8.7z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="16" cy="13" r="1.4" fill="currentColor" />
    </svg>
  )
}

type StatusKind = 'mock' | 'live' | 'cache' | 'offline' | 'idle'

const cap = (w: string) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w)

/** "anthropic/claude-sonnet-4.5" -> "Claude Sonnet"; "meta-llama/llama-3.3-70b-instruct:free" -> "Llama 3.3 70b". */
export function prettyModel(id: string | null | undefined): string {
  if (!id) return ''
  let m = id.split('/').pop() ?? id
  m = m.replace(/:free$/i, '').replace(/-\d{8}$/, '')
  const claude = /claude[-_ ]?(opus|sonnet|haiku)/i.exec(m)
  if (claude) return `Claude ${cap(claude[1].toLowerCase())}`
  return m
    .split(/[-_]/)
    .filter(Boolean)
    .slice(0, 3)
    .map(cap)
    .join(' ')
}

const PROVIDERS: Record<string, string> = { openrouter: 'OpenRouter', anthropic: 'Anthropic' }

/** The language model line for the header: provider, model and requests used / budget (docs/subject-mode.md 9.2). */
export function llmStatus(state: AppState, t: ReturnType<typeof useApp>['t']): { short: string; tip: string; byTask: [string, number][]; models: [string, string][] } {
  const h = state.health
  const provider = h?.llm_provider ?? null
  const mode = (state.llmMode ?? h?.llm_mode ?? '').toLowerCase()
  const used = h?.llm_requests_used
  const budget = h?.llm_budget
  const byTask = Object.entries(h?.llm_requests_by_task ?? {}).filter(([, n]) => n > 0)
  const models = Object.entries(h?.llm_models_used ?? {})
  const fallback = !provider && (!mode || /fallback|none|off|rule/.test(mode) || state.demo)
  if (fallback) {
    const demo = state.demo ? ` (${t('llm.demo')})` : ''
    return { short: `${t('llm.label')}: ${t('llm.ruleBased')}${demo}`, tip: t('llm.tip.fallback'), byTask, models }
  }
  const model = prettyModel(h?.llm_model)
  const prov = provider ? (PROVIDERS[provider] ?? cap(provider)) : ''
  const who = model && prov ? t('llm.via', { model, provider: prov }) : model || prov || t('header.llm.claude')
  if (h?.llm_budget_exhausted) {
    return { short: `${t('llm.label')}: ${t('llm.exhausted')} (${used ?? budget}/${budget})`, tip: t('llm.tip.budget', { used: used ?? 0, budget: budget ?? 0 }), byTask, models }
  }
  const count = used == null ? '' : budget != null ? ` · ${used}/${budget}` : ` · ${used}`
  const tip = used == null ? '' : budget != null ? t('llm.tip.budget', { used, budget }) : t('llm.tip.unlimited', { used })
  return { short: `${t('llm.label')}: ${who}${count}`, tip, byTask, models }
}


function LlmPill() {
  const { state, t } = useApp()
  // unknown until /api/health answers (the data-status pill says "Disconnected" if it never does)
  if (!state.demo && !state.health) return null
  const s = llmStatus(state, t)
  return (
    <span
      className="max-xl:hidden inline-block h-8 max-w-[300px] truncate px-3 rounded-[var(--r-tag)] border border-[var(--line)] bg-[var(--surface)] text-[12px] leading-[30px] text-[var(--text-2)]"
      title={s.tip || undefined}
      data-testid="llm-status"
    >
      {s.short}
    </span>
  )
}

/** "MOCK · fictional data" -> "fictional data": the strip above already carries the MOCK tag. */
const afterTag = (s: string) => {
  const i = s.indexOf(' · ')
  return i < 0 ? s : s.slice(i + 3)
}

/** Shape per data origin, so the status reads without color: square (MOCK), dashed square (cached),
 *  filled pulsing dot (live), hollow dot (waiting / disconnected). */
function StatusMark({ kind }: { kind: StatusKind }) {
  if (kind === 'mock') return <span aria-hidden className="flex-none w-2 h-2 rounded-[2px] bg-[var(--text)]" />
  if (kind === 'cache') return <span aria-hidden className="flex-none w-2.5 h-2.5 rounded-[2px] border border-dashed border-[var(--text-2)]" />
  return <span aria-hidden className={`dot ${kind === 'live' ? 'dot-live' : 'dot-idle'}`} />
}

/** One data-status pill instead of LIVE / CACHE / MOCK counters: what to trust, on hover or focus. */
function DataStatus() {
  const { state, t, lang } = useApp()
  const mock = useMockMode()
  const [open, setOpen] = useState(false)
  const wasOpen = useRef(false)
  const id = useId()
  useEscapeLayer(open, () => setOpen(false))
  const counts = modeCounts(state)
  const src = (state.health?.source_mode ?? '').toLowerCase()
  const kind: StatusKind =
    state.healthFailed && !state.demo
      ? 'offline'
      : mock
        ? 'mock'
        : counts.live
          ? 'live'
          : counts.cache
            ? 'cache'
            : src === 'live' || src === 'apify'
              ? 'live'
              : src === 'cache'
                ? 'cache'
                : 'idle'
  const llm = llmStatus(state, t)
  const label = t(`header.status.${kind}`)

  return (
    <div className="relative" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className={`relative inline-flex items-center gap-2 h-8 px-3 rounded-[var(--r-control)] border bg-[var(--surface)] text-[13px] leading-[18px] font-medium text-[var(--text)] whitespace-nowrap transition-colors duration-[var(--dur-1)] hover:bg-[var(--neutral-tint)] max-md:after:absolute max-md:after:-inset-[7px] ${
          kind === 'offline' ? 'border-dashed border-[var(--field)]' : 'border-[var(--field)]'
        }`}
        data-testid="data-mode"
        data-mode={kind}
        aria-describedby={`${id}-tip`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        // a tap fires mouseenter and focus (both open) before click: toggle from the state before the tap
        onPointerDown={() => {
          wasOpen.current = open
        }}
        onClick={(e) => (e.detail === 0 ? setOpen((v) => !v) : setOpen(!wasOpen.current))}
      >
        <StatusMark kind={kind} />
        {kind === 'mock' ? (
          <>
            <span className="max-sm:hidden">{afterTag(label)}</span>
            <span className="sm:hidden" translate="no">
              {t('header.status.mock.short')}
            </span>
            <span className="sr-only max-sm:hidden">, {t('header.status.mock.short')}</span>
          </>
        ) : (
          <span>{label}</span>
        )}
      </button>
      <div id={`${id}-tip`} role="tooltip" className={`float right-0 top-[calc(100%+8px)] w-[min(320px,calc(100vw-24px))] p-4 text-[13px] leading-[18px] ${open ? '' : 'hidden'}`}>
        <div className="text-[12px] leading-4 font-semibold text-[var(--text-2)] mb-1">{t('header.status.title')}</div>
        <p className="text-[var(--text)]">{t(`header.status.trust.${kind}`)}</p>
        <div className="text-[12px] leading-4 font-semibold text-[var(--text-2)] mt-3 mb-1">{t('header.status.counts')}</div>
        <p className="text-[var(--text-2)] tabular-nums">
          {t('header.status.live.n')} {fmtInt(counts.live, lang)} · {t('header.status.cache.n')} {fmtInt(counts.cache, lang)} · {t('header.status.mock.n')}{' '}
          {fmtInt(counts.mock, lang)}
        </p>
        <div className="text-[12px] leading-4 font-semibold text-[var(--text-2)] mt-3 mb-1">{t('header.status.llm')}</div>
        <p className="text-[var(--text)]">{llm.short}</p>
        {llm.tip && <p className="text-[var(--text-2)] mt-1">{llm.tip}</p>}
        {llm.byTask.length > 0 && (
          <p className="text-[12px] leading-4 text-[var(--text-2)] mt-1">
            {t('llm.tip.byTask')}: {llm.byTask.map(([k, n]) => `${k} ${n}`).join(' · ')}
          </p>
        )}
        {llm.models.length > 0 && (
          <p className="text-[12px] leading-4 text-[var(--text-2)] mt-1 break-all">
            {llm.models.map(([k, m]) => `${k}: ${m}`).join(' · ')}
          </p>
        )}
      </div>
    </div>
  )
}

function PurgeDialog({ onClose, returnTo }: { onClose: () => void; returnTo: React.RefObject<HTMLButtonElement | null> }) {
  const { t, actions } = useApp()
  const keep = useRef<HTMLButtonElement>(null)
  const ref = useDialog<HTMLDivElement>(true, onClose, { initialFocus: keep, returnFocus: returnTo })
  const id = useId()
  return (
    <>
      <div className="scrim !z-50" onClick={onClose} />
      <div ref={ref} className="modal !w-[min(420px,calc(100vw-24px))]" role="alertdialog" aria-modal="true" aria-labelledby={`${id}-t`} aria-describedby={`${id}-b`} tabIndex={-1}>
        <div className="p-6 max-md:p-4">
          <h2 id={`${id}-t`} className="text-[20px] leading-7 font-semibold text-[var(--text)]">
            {t('purge.title')}
          </h2>
          <p id={`${id}-b`} className="text-[15px] leading-[22px] text-[var(--text-2)] mt-2">
            {t('purge.body')}
          </p>
          <div className="flex justify-end gap-2 mt-6">
            <button ref={keep} type="button" className="btn" onClick={onClose}>
              {t('purge.cancel')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              data-testid="purge-confirm"
              onClick={() => {
                onClose()
                actions.purge()
              }}
            >
              {t('purge.confirm')}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

/** menu row: 40 px (44 px on phones), full width, left aligned */
const MI =
  'flex items-center gap-2 w-full min-h-10 max-md:min-h-11 px-3 rounded-[var(--r-control)] text-left text-[15px] leading-[22px] text-[var(--text)] transition-colors duration-[var(--dur-1)] hover:bg-[var(--neutral-tint)] active:bg-[var(--line)]'

export function Header() {
  const { state, t, lang, setLang, blur, setBlur, setGoalOpen, demoStatus, demo, dispatch } = useApp()
  const [menu, setMenu] = useState(false)
  const [confirmPurge, setConfirmPurge] = useState(false)
  const moreRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const closeMenu = (focusBack = true) => {
    setMenu(false)
    if (focusBack) moreRef.current?.focus()
  }
  useEscapeLayer(menu, () => closeMenu())
  // a tap outside the open menu closes it (touch does not move focus, so onBlur alone misses it)
  const menuWrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const onDown = (e: PointerEvent) => {
      if (menuWrap.current && !menuWrap.current.contains(e.target as Node)) setMenu(false)
    }
    document.addEventListener('pointerdown', onDown, true)
    return () => document.removeEventListener('pointerdown', onDown, true)
  }, [menu])

  // "Změnit cíl" appears only after the first run (rounds 0–3 done)
  const showGoal = state.mode !== 'subject' && (lastFinishedRound(state) >= 3 || !!demoStatus?.bakeryDone)
  // phones: the demo strip has no room for the scenario switch, so it lives in this menu
  const scenario = demo && demoStatus ? demoStatus.scenario : null
  const switchTo = (sc: 'discovery' | 'subject') => {
    if (!demo || scenario === sc) return
    dispatch({ type: 'reset' })
    if (sc === 'subject') demo.playSubject({})
    else demo.playDiscovery()
  }

  return (
    <>
      <InfoStrip />
      <header className="relative border-b border-[var(--line)] bg-[var(--surface)]">
        <div className="flex items-center gap-2 sm:gap-3 h-[63px] max-md:h-[55px] px-3 sm:px-4 md:px-6">
          <div className="flex items-center gap-2.5 min-w-0 mr-auto">
            <Logo />
            <h1 className="text-[18px] leading-6 font-semibold tracking-[-0.01em] text-[var(--text)] whitespace-nowrap" translate="no">
              {t('app.name')}
            </h1>
          </div>

          <LlmPill />
          <DataStatus />

          <Toggle checked={blur} onChange={setBlur} label={t('header.blur')} className="max-lg:hidden" testId="blur-toggle" />

          {showGoal && (
            <button type="button" className="btn max-md:hidden" onClick={() => setGoalOpen(true)}>
              {t('header.changeGoal')}
            </button>
          )}

          <div
            ref={menuWrap}
            className="relative"
            onBlur={(e) => {
              if (menu && !e.currentTarget.contains(e.relatedTarget as Node | null)) setMenu(false)
            }}
          >
            <button
              ref={moreRef}
              type="button"
              className="inline-flex items-center justify-center w-10 h-10 max-md:w-11 max-md:h-11 rounded-[var(--r-control)] text-[var(--text)] transition-colors duration-[var(--dur-1)] hover:bg-[var(--neutral-tint)] active:bg-[var(--line)] aria-expanded:bg-[var(--neutral-tint)]"
              aria-label={t('header.more')}
              aria-expanded={menu}
              aria-controls={menuId}
              onClick={() => setMenu((v) => !v)}
            >
              <span aria-hidden className="text-[20px] leading-none">
                ⋯
              </span>
            </button>
            <div id={menuId} className={`float right-0 top-[calc(100%+8px)] w-[260px] p-2 flex flex-col gap-0.5 ${menu ? '' : 'hidden'}`}>
              {scenario && (
                <div className="md:hidden flex flex-col gap-0.5" role="group" aria-label={t('demo.scenario')}>
                  <div className="px-3 pt-1 pb-0.5 text-[12px] leading-4 font-semibold text-[var(--text-2)]" aria-hidden>
                    {t('demo.scenario')}
                  </div>
                  {(['discovery', 'subject'] as const).map((sc) => (
                    <button
                      key={sc}
                      type="button"
                      className={`${MI} ${scenario === sc ? 'font-semibold' : ''}`}
                      aria-pressed={scenario === sc}
                      onClick={() => {
                        closeMenu(false)
                        switchTo(sc)
                      }}
                    >
                      <span aria-hidden className="w-4 text-[var(--accent)]">
                        {scenario === sc ? '✓' : ''}
                      </span>
                      {t(sc === 'subject' ? 'demo.scenario.subject' : 'demo.scenario.discovery')}
                    </button>
                  ))}
                  <div className="h-px bg-[var(--line)] my-1" aria-hidden />
                </div>
              )}
              {showGoal && (
                <button
                  type="button"
                  className={`${MI} md:hidden`}
                  onClick={() => {
                    closeMenu(false)
                    setGoalOpen(true)
                  }}
                >
                  {t('header.changeGoal')}
                </button>
              )}
              <Toggle checked={blur} onChange={setBlur} label={t('header.blur')} className="lg:hidden !justify-start w-full min-h-10 max-md:min-h-11 !px-3" testId="blur-toggle-menu" />
              <button
                type="button"
                className={MI}
                lang={lang === 'cs' ? 'en' : 'cs'}
                onClick={() => {
                  setLang(lang === 'cs' ? 'en' : 'cs')
                  closeMenu()
                }}
              >
                {t('header.lang.other')}
              </button>
              <div className="h-px bg-[var(--line)] my-1" aria-hidden />
              <button
                type="button"
                className={MI}
                data-testid="purge"
                onClick={() => {
                  closeMenu(false)
                  setConfirmPurge(true)
                }}
              >
                {t('header.purge')}
              </button>
            </div>
          </div>
        </div>
        {confirmPurge && <PurgeDialog onClose={() => setConfirmPurge(false)} returnTo={moreRef} />}
      </header>
    </>
  )
}
