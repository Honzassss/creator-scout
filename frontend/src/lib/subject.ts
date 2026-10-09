// Client-side mirror of backend compute/subject.py (docs/subject-mode.md section 4.2): only used to give the
// owner instant feedback in the form. The backend parses again and is the authority.

import type { Anchor, Competitor, Platform } from '../types'

const IG_NON_PROFILE = new Set(['p', 'reel', 'reels', 'tv', 'stories', 'explore', 'accounts', 'direct'])
const HANDLE = /^[a-z0-9._]{1,30}$/

export type SubjectParse = { ok: true; platform: Platform | null; handle: string } | { ok: false; reason: 'empty' | 'post' | 'share' | 'name' | 'invalid' }

export function parseSubject(text: string): SubjectParse {
  const raw = text.trim()
  if (!raw) return { ok: false, reason: 'empty' }
  const urlish = /^(https?:\/\/)?([a-z0-9-]+\.)*(instagram\.com|tiktok\.com)(\/|$)/i.test(raw)
  if (urlish) {
    let u: URL
    try {
      u = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`)
    } catch {
      return { ok: false, reason: 'invalid' }
    }
    const parts = u.pathname.split('/').filter(Boolean)
    if (/instagram\.com$/i.test(u.hostname)) {
      const first = (parts[0] ?? '').toLowerCase()
      if (!first) return { ok: false, reason: 'invalid' }
      if (IG_NON_PROFILE.has(first)) return { ok: false, reason: 'post' }
      return HANDLE.test(first) ? { ok: true, platform: 'instagram', handle: first } : { ok: false, reason: 'invalid' }
    }
    const at = parts.find((p) => p.startsWith('@'))
    // vm.tiktok.com/ZM…, vt.tiktok.com/…, tiktok.com/t/…: share short links can point to a profile or a video
    if (!at && (/^(vm|vt)\./i.test(u.hostname) || (parts[0] ?? '').toLowerCase() === 't')) return { ok: false, reason: 'share' }
    if (!at) return { ok: false, reason: parts.length ? 'post' : 'invalid' }
    const h = at.slice(1).toLowerCase()
    return HANDLE.test(h) ? { ok: true, platform: 'tiktok', handle: h } : { ok: false, reason: 'invalid' }
  }
  const h = raw.replace(/^@/, '').toLowerCase()
  if (HANDLE.test(h)) return { ok: true, platform: null, handle: h }
  // "Ondřej Toman": a name can match namesakes; ask for the handle or the profile link
  if (!raw.startsWith('@') && /\s/.test(raw) && /^[\p{L}][\p{L}\s.'-]+$/u.test(raw)) return { ok: false, reason: 'name' }
  return { ok: false, reason: 'invalid' }
}

export type AnchorKind = 'city' | 'website' | 'company_id'

/** One free-text anchor field: a domain or URL is a website, 6-8 digits (optionally after IČO / CZ) a
 *  company ID, anything else a city. Returns null for an empty field. */
/** "skip", "none", "nevím", "don't know" in the anchor field mean no anchor (as in the chat, docs/subject-mode.md). */
const NO_ANCHOR = /^(skip|none|no|nope|n\/?a|-+|–|—|unknown|don'?t know|dont know|no idea|not sure|nevím|nevim|nevim\.|nic|žádn[áéý]|zadn[aey]|bez kotvy|bez|přeskočit|preskocit|nezn[áa]m)\.?$/i

export function readAnchor(text: string): { kind: AnchorKind; value: string; anchor: Anchor } | null {
  const raw = text.trim()
  if (!raw || NO_ANCHOR.test(raw)) return null
  const digits = raw.replace(/^(i[cč]o|company\s*id|cz)\s*:?\s*/i, '').replace(/\s/g, '')
  if (/^(cz)?\d{6,8}$/i.test(digits)) {
    const d = digits.replace(/^cz/i, '').padStart(8, '0')
    return { kind: 'company_id', value: d, anchor: { company_id: d } }
  }
  if (/^(https?:\/\/)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(\/\S*)?$/i.test(raw) && !/\s/.test(raw)) {
    const host = raw
      .replace(/^https?:\/\//i, '')
      .replace(/^www\./i, '')
      .split(/[/?#]/)[0]
      .toLowerCase()
    return { kind: 'website', value: host, anchor: { website: host } }
  }
  return { kind: 'city', value: raw, anchor: { city: raw } }
}

/** "city Brno, website fitpeceni.example" (en) / "město Brno, web fitpeceni.example" (cs). */
export function anchorText(anchor: Anchor | null | undefined, lang: 'cs' | 'en'): string {
  if (!anchor) return ''
  const words = lang === 'cs' ? { city: 'město', website: 'web', company_id: 'IČO' } : { city: 'city', website: 'website', company_id: 'company ID' }
  const out: string[] = []
  if (anchor.city) out.push(`${words.city} ${anchor.city}`)
  if (anchor.website) out.push(`${words.website} ${anchor.website}`)
  if (anchor.company_id) out.push(`${words.company_id} ${anchor.company_id}`)
  return out.join(', ')
}

/** The optional competitors field: comma (or semicolon / newline) separated names, @handles or profile
 *  links -> brief.competitors. "Pekárna B @pekarna_b" is one competitor with its handle; "@x" alone is
 *  named by the handle; a plain name has no handle (the backend matches names and handles). */
export function parseCompetitors(text: string): Competitor[] {
  const out: Competitor[] = []
  const seen = new Set<string>()
  for (const part of text.split(/[,;\n]/)) {
    const handles: string[] = []
    const words: string[] = []
    for (const w of part.trim().split(/\s+/).filter(Boolean)) {
      const t = w.replace(/^[("'„“]+|[)"'“”]+$/g, '')
      const p = /^@|instagram\.com|tiktok\.com/i.test(t) ? parseSubject(t) : null
      if (p?.ok) handles.push(p.handle)
      else words.push(w)
    }
    const name = words.join(' ').replace(/^[("'„“]+|[)"'“”]+$/g, '').trim().slice(0, 80) || handles[0]
    if (!name || seen.has(name.toLowerCase())) continue
    seen.add(name.toLowerCase())
    out.push({ name, handles: [...new Set(handles)] })
  }
  return out.slice(0, 10)
}
