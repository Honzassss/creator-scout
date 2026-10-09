// Modal dialogs and popovers: one stack of layers, one keydown listener.
//  - the topmost layer gets Escape (and only it: a source popover inside the dossier closes alone)
//  - Tab / Shift+Tab stay inside the topmost layer
//  - modal layers make the rest of #root inert and return focus to their trigger on close
// WCAG 2.1.1, 2.4.3; docs/design/smer-designu.md section 3.1.

import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

interface Layer {
  el: () => HTMLElement | null
  onEscape: () => void
  trap: boolean
}

const stack: Layer[] = []
let listening = false

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'

export function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.closest('[inert]') && el.getClientRects().length > 0)
}

function onKeyDown(e: KeyboardEvent) {
  const top = stack[stack.length - 1]
  if (!top) return
  const root = top.el()
  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopImmediatePropagation()
    top.onEscape()
    return
  }
  if (e.key !== 'Tab' || !top.trap || !root) return
  const list = focusables(root)
  const active = document.activeElement as HTMLElement | null
  if (!list.length) {
    e.preventDefault()
    root.focus()
    return
  }
  const first = list[0]
  const last = list[list.length - 1]
  const inside = active ? root.contains(active) : false
  if (!inside) {
    e.preventDefault()
    ;(e.shiftKey ? last : first).focus()
  } else if (e.shiftKey && (active === first || active === root)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    first.focus()
  }
}

function ensureListener() {
  if (listening) return
  document.addEventListener('keydown', onKeyDown, true)
  listening = true
}

/** Make everything in #root inert except the path down to `el`. Returns an undo function. */
function inertOutside(el: HTMLElement): () => void {
  const root = document.getElementById('root')
  const changed: HTMLElement[] = []
  let node: HTMLElement | null = el
  while (node && node !== root && node.parentElement) {
    for (const sib of Array.from(node.parentElement.children) as HTMLElement[]) {
      if (sib === node || sib.inert || sib.tagName === 'SCRIPT') continue
      // the MOCK frame stays visible and announced; it has no interactive content
      if (sib.dataset.keepActive === 'true') continue
      sib.inert = true
      changed.push(sib)
    }
    if (node.parentElement === root) break
    node = node.parentElement
  }
  return () => {
    for (const s of changed) s.inert = false
  }
}

export interface DialogOptions {
  /** element to focus first; default: the first focusable, or the dialog itself */
  initialFocus?: RefObject<HTMLElement | null>
  /** where focus goes on close when the trigger is gone (e.g. a menu item) */
  returnFocus?: RefObject<HTMLElement | null>
  /** modal: inert outside + focus trap (default true). A popover sets trap only. */
  modal?: boolean
  trap?: boolean
}

/**
 * Wire a dialog element: focus in on open, Tab trapped, Escape closes, focus back to the trigger.
 * Returns a ref for the dialog container (give it tabIndex={-1}).
 */
export function useDialog<T extends HTMLElement = HTMLDivElement>(open: boolean, onClose: () => void, opts: DialogOptions = {}): RefObject<T | null> {
  const ref = useRef<T | null>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const optsRef = useRef(opts)
  optsRef.current = opts
  // the element that had focus before the dialog opened; kept across StrictMode's double effect run,
  // where the second run would otherwise see focus already inside the dialog
  const triggerRef = useRef<HTMLElement | null>(null)

  // Layout effect: the dialog is in the DOM, so inert + initial focus happen in the same commit.
  // (A dialog opened by the click that also closes a menu, e.g. "Smazat data", used to lose this
  // step: the menu item went hidden, Chrome blurred it, and focus stayed on <body>.)
  useLayoutEffect(() => {
    if (!open) return
    ensureListener()
    const active = document.activeElement as HTMLElement | null
    const trigger = ref.current && active && ref.current.contains(active) ? triggerRef.current : active
    triggerRef.current = trigger
    const o = optsRef.current
    const modal = o.modal !== false
    const layer: Layer = { el: () => ref.current, onEscape: () => closeRef.current(), trap: modal || !!o.trap }
    stack.push(layer)
    let undoInert: (() => void) | null = null
    const place = () => {
      const el = ref.current
      if (!el) return
      if (modal && !undoInert) undoInert = inertOutside(el)
      if (el.contains(document.activeElement)) return
      const target = o.initialFocus?.current ?? (modal ? focusables(el)[0] : null) ?? el
      target.focus({ preventScroll: !modal })
    }
    place()
    // a second chance after the browser has laid the dialog out (and blurred a hidden trigger)
    const raf = window.requestAnimationFrame(place)
    const late = window.setTimeout(place, 120)
    return () => {
      window.cancelAnimationFrame(raf)
      window.clearTimeout(late)
      const i = stack.indexOf(layer)
      if (i >= 0) stack.splice(i, 1)
      undoInert?.()
      // the trigger may be gone or hidden (a menu item in a closed menu): then use returnFocus
      const usable = (el: HTMLElement | null | undefined) => !!el && el.isConnected && el !== document.body && el.getClientRects().length > 0
      const back = usable(trigger) ? trigger : optsRef.current.returnFocus?.current
      // only pull focus back when it was inside the dialog (or nowhere): never steal it
      const now = document.activeElement
      const el = ref.current
      if (back && (!now || now === document.body || (el && el.contains(now)) || !now.isConnected)) {
        back.focus({ preventScroll: true })
      }
    }
  }, [open])

  return ref
}

/** Escape-only layer (menus, tooltips): no trap, no inert. */
export function useEscapeLayer(open: boolean, onClose: () => void) {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    ensureListener()
    const layer: Layer = { el: () => null, onEscape: () => closeRef.current(), trap: false }
    stack.push(layer)
    return () => {
      const i = stack.indexOf(layer)
      if (i >= 0) stack.splice(i, 1)
    }
  }, [open])
}
