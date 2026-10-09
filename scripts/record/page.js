// Injected into the Creator Scout page by scripts/record/lib.sh before every eval (idempotent).
// Defines window.__rec: element lookup (data-testid first, then CSS, then label / visible text),
// a target marker for agent-browser clicks, smooth scrolling, and a visible cursor with click ripples
// (headless screencasts have no OS cursor). Recording aid only; never shipped with the app.
(() => {
  if (window.__rec) return 'ok'
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim()
  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'
  }
  const DEFAULT_ROLES = 'button,a,[role=button],[role=switch],[role=tab],[role=radio],label,summary'
  const labelOf = (el) =>
    norm(el.getAttribute('aria-label')) ||
    (el.labels && el.labels[0] ? norm(el.labels[0].innerText) : '') ||
    norm(el.getAttribute('placeholder'))
  const pickText = (els, want, exact, textOf) => {
    let hit = els.find((e) => textOf(e) === want)
    if (hit || exact) return hit || null
    hit = els.find((e) => textOf(e).startsWith(want))
    if (hit) return hit
    return els.find((e) => textOf(e).includes(want)) || null
  }
  // spec: {testid, css, label, text, role, scope, exact}; tried in that order.
  function find(spec) {
    const root = spec.scope ? document.querySelector(spec.scope) : document
    if (!root) return null
    if (spec.testid) {
      const el = [...root.querySelectorAll(`[data-testid="${spec.testid}"]`)].find(visible)
      if (el) return el
    }
    if (spec.css && !spec.text && !spec.label) {
      const el = [...root.querySelectorAll(spec.css)].find(visible)
      if (el) return el
    }
    if (spec.label) {
      const els = [...root.querySelectorAll(spec.css || 'input,textarea,select')].filter(visible)
      const el = pickText(els, norm(spec.label), spec.exact, labelOf)
      if (el) return el
    }
    if (spec.text) {
      const els = [...root.querySelectorAll(spec.css || spec.role || DEFAULT_ROLES)].filter(visible)
      const el = pickText(els, norm(spec.text), spec.exact, (e) => norm(e.innerText) || norm(e.getAttribute('aria-label')))
      if (el) return el
    }
    return null
  }
  // Marks the element so agent-browser can click / hover it by a stable selector.
  function mark(spec) {
    document.querySelectorAll('[data-rec-target]').forEach((e) => e.removeAttribute('data-rec-target'))
    const el = find(spec)
    if (!el) return null
    el.setAttribute('data-rec-target', '1')
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    const r = el.getBoundingClientRect()
    return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)]
  }
  function scrollTo(spec, block) {
    const el = find(spec)
    if (!el) return false
    el.scrollIntoView({ behavior: 'smooth', block: block || 'start' })
    return true
  }
  function text(spec) {
    const el = spec ? find(spec) : document.body
    return el ? norm(el.innerText) : ''
  }

  // Visible cursor: follows CDP mouse events; CSS transition animates the move before a click.
  const style = document.createElement('style')
  style.textContent = `
    #__rec_cursor{position:fixed;left:-40px;top:-40px;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
      background:rgba(255,206,64,.30);border:2px solid rgba(255,206,64,.95);box-shadow:0 0 0 1px rgba(0,0,0,.35);
      pointer-events:none;z-index:2147483647;transition:left .38s cubic-bezier(.3,.7,.4,1),top .38s cubic-bezier(.3,.7,.4,1)}
    .__rec_ripple{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:2px solid rgba(255,206,64,.95);
      pointer-events:none;z-index:2147483646;animation:__rec_r .55s ease-out forwards}
    @keyframes __rec_r{to{transform:scale(3.2);opacity:0}}`
  document.documentElement.appendChild(style)
  const cur = document.createElement('div')
  cur.id = '__rec_cursor'
  document.documentElement.appendChild(cur)
  const place = (x, y) => {
    cur.style.left = x + 'px'
    cur.style.top = y + 'px'
  }
  window.addEventListener('mousemove', (e) => place(e.clientX, e.clientY), true)
  window.addEventListener(
    'mousedown',
    (e) => {
      place(e.clientX, e.clientY)
      const r = document.createElement('div')
      r.className = '__rec_ripple'
      r.style.left = e.clientX + 'px'
      r.style.top = e.clientY + 'px'
      document.documentElement.appendChild(r)
      setTimeout(() => r.remove(), 700)
    },
    true,
  )

  window.__rec = { find, mark, scrollTo, text, norm, visible }
  return 'ok'
})();
