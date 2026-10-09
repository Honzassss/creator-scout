/**
 * Motion system (docs/design/motion-audit.md). CSS half: src/motion.css.
 *
 * Rules: one region animates at a time; things happen one after another, never all at once;
 * transform/opacity only; no two texts in one box at any moment (key the element by its text and
 * let the new one enter, or reserve the space); prefers-reduced-motion or a hidden tab = instant.
 *
 * ---------------------------------------------------------------------------------------------
 * API for components
 *
 *   CSS classes (motion.css)
 *     .m-enter        region/card/message enters (opacity + 6 px up, --dur-2). Optional --m-delay.
 *     .m-exit         item leaves (--dur-3), keeps its box until it is removed.
 *     .m-swap         a string replaced in place: <span key={text} className="m-swap">{text}</span>
 *     .m-stagger      on a list; children get style={staggerStyle(i)}, 60 ms apart, capped at 8.
 *                     For lists that grow live, pass the index within the NEW batch, not the list.
 *     .m-flash        one soft background pulse ("What changed"); restart it with flash(el).
 *     .m-num          tabular digits for counters.
 *     tokens          --dur-1 120ms · --dur-2 200ms · --dur-3 320ms · --ease · --stagger 60ms
 *
 *   TS
 *     DUR, STAGGER_MS, STAGGER_CAP, LAG_MAX_MS    the same numbers as the CSS tokens
 *     motionInstant()                             reduced motion or hidden tab: skip all motion now
 *     useReducedMotion()                          reactive prefers-reduced-motion
 *     staggerStyle(i)                             {'--i': min(i, 8)} for children of .m-stagger
 *     flash(el)                                   restart .m-flash on an element (no-op without one)
 *     useCountUp(value, {delayMs, durationMs, fromZero})
 *                                                 the number to draw: counts from the previous value
 *                                                 to the new one in --dur-3 (ease-out), starting after
 *                                                 delayMs (pass DUR[2] when the counter's region has
 *                                                 just entered). Render it in ONE text node with .m-num.
 *     useSequence(count, {key, gapMs, startMs})   how many of `count` parts are revealed now; parts
 *                                                 appear one after another (default DUR[3] apart) and
 *                                                 restart when `key` changes. Instant when motion is off.
 *     whenPresented(fn)                           run fn once the presentation queue is idle (all
 *                                                 queued events applied, the last hold over): use it to
 *                                                 start a follow-up animation (scroll, flash, toast)
 *                                                 after the board has settled.
 *
 *   Presentation queue (store.tsx owns the instance; components do not push into it)
 *     createPresenter(apply, opts) -> { push, flush, catchUp, idle, dispose }
 *     Live SSE events, snapshots, chat notices, errors and the whole ?demo=1 replay go through
 *     push(). Each action applies in arrival order; some then hold the stage for a moment:
 *       round.started          --dur-2   (the current stage changes before cards move)
 *       candidate.eliminated   60 ms each, the first 8 of a round only (then the rest at once)
 *       round.finished         waits until the last card has left (--dur-3), clears the leaving
 *                              cards, then holds --dur-3 while the counters count
 *       report.ready, diff, report.diff, chat.notice, error   --dur-3 (one panel / toast at a time)
 *       chat.user              --dur-2
 *     Budget: each round gets LAG_MAX_MS (1.2 s) of added delay, counted from its round.started (not
 *     from each event's arrival, so a backlog from the previous round does not eat it). As a round
 *     uses up its budget, or as the backlog grows, the holds shrink proportionally (the stagger goes
 *     to 0, the eliminations of an old round leave together) but the order gates stay: round.started
 *     holds --dur-2, round.finished waits until the last card has left, its counters get --dur-3.
 *     Only a backlog older than LAG_HARD_MS (4 s) skips the gates. An action that changes nothing
 *     on screen (opts.quiet, e.g. a repeated round.finished) holds nothing.
 *     Instant (no holds) under reduced motion, in a hidden tab, with ?demo=1&instant=1, and while
 *     a reconnecting stream replays its history (catchUp()). When a hidden tab comes back, the
 *     enter animations of what mounted meanwhile are finished at once (they would all start together).
 * ---------------------------------------------------------------------------------------------
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react'

export const DUR = { 1: 120, 2: 200, 3: 320 } as const
export const STAGGER_MS = 60
export const STAGGER_CAP = 8
/** the added delay one round may take (its budget counts from its round.started) */
export const LAG_MAX_MS = 1200
/** a backlog older than this skips the order gates too (pathological bursts only) */
export const LAG_HARD_MS = 4000

const REDUCE_Q = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  try {
    return !!window.matchMedia?.(REDUCE_Q).matches
  } catch {
    return false
  }
}

/** Reduced motion or a hidden tab: apply everything at once, animate nothing. */
export function motionInstant(): boolean {
  return prefersReducedMotion() || (typeof document !== 'undefined' && document.hidden)
}

export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(prefersReducedMotion)
  useEffect(() => {
    const mq = window.matchMedia?.(REDUCE_Q)
    if (!mq) return
    const on = () => setReduce(mq.matches)
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  return reduce
}

/** Style for a child of .m-stagger: its position in the sequence, capped so long lists do not wait. */
export function staggerStyle(i: number): CSSProperties {
  return { ['--i' as string]: Math.max(0, Math.min(i, STAGGER_CAP)) } as CSSProperties
}

/**
 * One soft background pulse on an element ("What changed", a jump target), restarted if it runs.
 * Uses the Web Animations API, so it never replaces (and so never restarts) the element's own
 * CSS animation such as .m-enter. The .m-flash class does the same for markup-only use.
 */
export function flash(el: Element | null | undefined) {
  const h = el as HTMLElement | null | undefined
  if (!h || motionInstant() || typeof h.animate !== 'function') return
  for (const a of h.getAnimations?.() ?? []) if (a.id === 'm-flash') a.cancel()
  const tint = getComputedStyle(document.documentElement).getPropertyValue('--accent-tint').trim() || '#e4f3f0'
  // one keyframe: start and end are the element's own background
  h.animate([{ backgroundColor: tint, offset: 0.35 }], { duration: DUR[3] * 3, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)', id: 'm-flash' })
}

/**
 * The number to draw for a counter: rolls from the previous value to `value` in --dur-3 (ease-out),
 * after `delayMs`. One text node, so two numbers never share the box. Instant when motion is off.
 */
export function useCountUp(value: number, opts: { delayMs?: number; durationMs?: number; fromZero?: boolean } = {}): number {
  const { delayMs = 0, durationMs = DUR[3], fromZero = false } = opts
  const [shown, setShown] = useState(() => (fromZero && !motionInstant() && Number.isFinite(value) ? 0 : value))
  const shownRef = useRef(shown)
  shownRef.current = shown
  useEffect(() => {
    const from = shownRef.current
    if (from === value) return
    if (motionInstant() || !Number.isFinite(value) || !Number.isFinite(from) || durationMs <= 0) {
      setShown(value)
      return
    }
    let raf = 0
    let start = 0
    const step = (t: number) => {
      if (!start) start = t
      const p = Math.min(1, (t - start) / durationMs)
      const e = 1 - Math.pow(1 - p, 3)
      setShown(p >= 1 ? value : Math.round(from + (value - from) * e))
      if (p < 1) raf = window.requestAnimationFrame(step)
    }
    const tm = window.setTimeout(() => {
      // the tab went to the background meanwhile: no frames will come, jump to the value
      if (motionInstant()) setShown(value)
      else raf = window.requestAnimationFrame(step)
    }, delayMs)
    return () => {
      window.clearTimeout(tm)
      window.cancelAnimationFrame(raf)
    }
  }, [value, delayMs, durationMs])
  // a value that cannot count (NaN) is drawn as is
  return Number.isFinite(value) ? shown : value
}

/**
 * Reveal `count` parts one after another; returns how many are visible now (0..count).
 * Restarts when `key` changes. Use it for the parts of one region (e.g. stage cards, report
 * sections) so they do not all enter at once; render part i only when i < revealed, or give it
 * .m-enter once it is revealed. Parts past the 8th come together (same cap as .m-stagger).
 */
export function useSequence(count: number, opts: { key?: unknown; gapMs?: number; startMs?: number } = {}): number {
  const { key, gapMs = DUR[3], startMs = 0 } = opts
  const [revealed, setRevealed] = useState(() => (motionInstant() ? count : 0))
  useEffect(() => {
    if (motionInstant()) {
      setRevealed(count)
      return
    }
    setRevealed(0)
    const timers: number[] = []
    for (let i = 0; i < count; i++) {
      const at = startMs + Math.min(i, STAGGER_CAP) * gapMs
      timers.push(window.setTimeout(() => setRevealed((r) => Math.max(r, i + 1)), at))
    }
    return () => timers.forEach((t) => window.clearTimeout(t))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, count])
  return revealed
}

// ---------------------------------------------------------------------------------------------
// Presentation queue
// ---------------------------------------------------------------------------------------------

/** The minimal action shape the queue reads (the store's Action union fits it). */
export interface PresentedAction {
  type: string
  at?: number
  event?: { type: string }
}

export interface Presenter<A extends PresentedAction> {
  /** queue an action; applied in arrival order, paced per the table at the top of this file */
  push: (a: A) => void
  /** apply everything queued now, without holds (before a reset, a run switch, a user edit) */
  flush: () => void
  /** apply instantly until no action has arrived for `quietMs` (a stream replaying its history) */
  catchUp: (quietMs?: number) => void
  /** nothing queued and no hold running */
  idle: () => boolean
  /** make this the queue whenPresented() waits for (call from an effect); returns the undo */
  activate: () => () => void
  dispose: () => void
}

interface Item<A> {
  a: A
  t: number
}

let active: { idle: () => boolean; waiters: Set<() => void>; kick: () => void } | null = null

/** Run fn once the presentation queue is idle (immediately when it already is, or without a queue). */
export function whenPresented(fn: () => void): () => void {
  if (!active || active.idle()) {
    fn()
    return () => undefined
  }
  const w = active.waiters
  w.add(fn)
  active.kick()
  return () => w.delete(fn)
}

/** Jump every finite running animation (enter, exit, flash) to its end; looping ones keep running. */
function finishAnimations() {
  try {
    for (const a of document.getAnimations?.() ?? []) {
      const end = a.effect?.getComputedTiming?.().endTime
      if (typeof end === 'number' && Number.isFinite(end) && a.playState !== 'finished') a.finish()
    }
  } catch {
    /* an engine without the Web Animations API: nothing to finish */
  }
}

export function createPresenter<A extends PresentedAction>(
  apply: (a: A) => void,
  opts: {
    /** force instant (?demo=1&instant=1) */
    instant?: boolean
    /** called right before round.finished: remove cards whose exit has finished (anim.clear) */
    clearExits?: (beforeMs: number) => void
    /** the action changes nothing on screen (checked right before it is applied): no hold after it */
    quiet?: (a: A) => boolean
  } = {},
): Presenter<A> {
  const now = () => performance.now()
  const queue: Item<A>[] = []
  let timer: number | null = null
  // the running hold: started at holdStart, base length holdBase, shrinks with the backlog to holdMin
  let holdStart = 0
  let holdBase = 0
  let holdMin = 0
  let catchUntil = 0
  let catching = false
  let catchQuiet = 0
  let catchTimer: number | null = null
  // per round: how many eliminations were staggered, when the last card started to leave,
  // when the round came on stage (its budget counts from here)
  let staggered = 0
  let lastExit = 0
  let roundT = 0
  const waiters = new Set<() => void>()

  const instant = () => !!opts.instant || catching || motionInstant()

  const evType = (a: A) => (a.type === 'event' ? a.event?.type ?? '' : '')

  /** the stage time an action occupies after it is applied: [full hold, shortest hold under a backlog] */
  const holdFor = (a: A): [number, number] => {
    const ev = evType(a)
    if (ev === 'round.started') {
      staggered = 0
      roundT = now()
      return [DUR[2], DUR[2]]
    }
    if (ev === 'candidate.eliminated') {
      lastExit = now()
      return staggered++ < STAGGER_CAP ? [STAGGER_MS, 0] : [0, 0]
    }
    if (ev === 'round.finished') return [DUR[3], DUR[3]]
    if (ev === 'report.ready' || ev === 'diff' || ev === 'report.diff') return [DUR[3], DUR[1]]
    if (a.type === 'chat.notice' || a.type === 'error') return [DUR[3], DUR[1]]
    if (a.type === 'chat.user') return [DUR[2], DUR[1]]
    return [0, 0]
  }

  /**
   * 1 = full holds, 0 = the shortest ones. Shrinks proportionally with the backlog: how much of the
   * round's budget the waiting action has used (counted from round.started, or from its arrival if it
   * came later), and how old it is overall (so rounds do not add up to a run that feels slower).
   */
  const pace = (): number => {
    const head = queue[0]
    if (!head) return 1
    const t = now()
    const used = Math.max((t - Math.max(head.t, roundT)) / LAG_MAX_MS, (t - head.t) / (2 * LAG_MAX_MS))
    return Math.max(0, Math.min(1, 1 - used))
  }

  const holdEnd = () => holdStart + Math.max(holdMin, holdBase * pace())

  /** the earliest moment an action may be applied (besides the running hold) */
  const readyAt = (a: A): number => (evType(a) === 'round.finished' && lastExit ? lastExit + DUR[3] : 0)

  const restamp = (a: A): A => (typeof a.at === 'number' ? ({ ...a, at: Date.now() } as A) : a)

  /** apply one action; returns its [full, shortest] hold */
  const run = (a: A): [number, number] => {
    const quiet = !!opts.quiet?.(a)
    if (evType(a) === 'round.finished' && lastExit) {
      // the leaving cards have finished (or nothing moves): take them out before the counters move
      opts.clearExits?.(instant() ? Number.POSITIVE_INFINITY : Date.now() - DUR[3] + 1)
      lastExit = 0
    }
    // reducer animation flags (dropping / arriving) are stamped with the moment it is shown
    apply(restamp(a))
    // dev aid: window.__motionTrace = [] records what was shown when (type, event type, ms)
    const tr = (window as { __motionTrace?: unknown[] }).__motionTrace
    if (import.meta.env.DEV && Array.isArray(tr)) tr.push([Math.round(now()), a.type, evType(a)])
    const h = holdFor(a)
    return quiet ? [0, 0] : h
  }

  const settle = () => {
    if (queue.length || timer != null || !waiters.size) return
    const left = holdEnd() - now()
    if (left > 0) {
      timer = window.setTimeout(() => {
        timer = null
        drain()
      }, left)
      return
    }
    const fns = [...waiters]
    waiters.clear()
    for (const fn of fns) fn()
  }

  const drain = () => {
    if (timer != null) return
    while (queue.length) {
      const head = queue[0]
      if (instant()) {
        queue.shift()
        run(head.a)
        holdBase = holdMin = 0
        continue
      }
      const t = now()
      let wait = Math.max(holdEnd(), readyAt(head.a)) - t
      // a pathological backlog: show it now, gates or not
      if (t - head.t > LAG_HARD_MS) wait = 0
      if (wait > 4) {
        timer = window.setTimeout(() => {
          timer = null
          drain()
        }, wait)
        return
      }
      queue.shift()
      const [base, min] = run(head.a)
      holdStart = now()
      holdBase = base
      holdMin = min
    }
    settle()
  }

  const flush = () => {
    if (timer != null) window.clearTimeout(timer)
    timer = null
    while (queue.length) run(queue.shift()!.a)
    holdBase = holdMin = 0
    settle()
  }

  const endCatch = () => {
    catchTimer = null
    const left = catchUntil - now()
    if (left > 0) {
      catchTimer = window.setTimeout(endCatch, left)
      return
    }
    catching = false
  }

  const push = (a: A) => {
    if (catching) {
      catchUntil = now() + catchQuiet
      if (catchTimer == null) catchTimer = window.setTimeout(endCatch, catchQuiet)
    }
    queue.push({ a, t: now() })
    // dev aid: window.__motionArrive = [] records when each action arrived (compare with __motionTrace)
    const ar = (window as { __motionArrive?: unknown[] }).__motionArrive
    if (import.meta.env.DEV && Array.isArray(ar)) ar.push([Math.round(now()), a.type, evType(a)])
    // a backlog shortens the running hold: re-plan the wait
    if (timer != null) {
      window.clearTimeout(timer)
      timer = null
    }
    drain()
  }

  const onVisibility = () => {
    if (document.hidden) {
      flush()
      return
    }
    // back in front: everything that mounted while hidden would start its enter in this one frame;
    // show it settled instead (twice: React may commit the last hidden updates a frame later)
    finishAnimations()
    window.requestAnimationFrame(finishAnimations)
  }
  document.addEventListener('visibilitychange', onVisibility)

  const self: Presenter<A> = {
    push,
    flush,
    catchUp(quietMs = 150) {
      flush()
      catching = true
      catchQuiet = quietMs
      catchUntil = now() + quietMs
      if (catchTimer != null) window.clearTimeout(catchTimer)
      catchTimer = window.setTimeout(endCatch, quietMs)
    },
    idle: () => queue.length === 0 && timer == null && holdEnd() <= now(),
    activate() {
      const mine = { idle: self.idle, waiters, kick: settle }
      active = mine
      return () => {
        if (active === mine) active = null
      }
    },
    dispose() {
      document.removeEventListener('visibilitychange', onVisibility)
      if (timer != null) window.clearTimeout(timer)
      if (catchTimer != null) window.clearTimeout(catchTimer)
      timer = null
      queue.length = 0
      if (active?.waiters === waiters) active = null
    },
  }
  return self
}
