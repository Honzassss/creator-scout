// Thin client for the backend API (docs/architecture.md section 7). Everything goes through the Vite /api proxy.

import { createSSEParser, safeJSON } from './sse'
import type { Anchor, Brief, CriteriaSet, Health, Lang, Platform, ReportDiff, Run, RunDiff } from '../types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? body)
    } catch {
      detail = await res.text().catch(() => '')
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`)
  }
  if (res.status === 204) return {} as T
  return res.json() as Promise<T>
}

const post = (url: string, body?: unknown) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: async (): Promise<Health> => json(await fetch('/api/health')),
  run: async (id: string): Promise<Run> => json(await fetch(`/api/runs/${encodeURIComponent(id)}`)),
  status: async (id: string): Promise<{ busy: boolean; error?: string | null; interrupted?: boolean }> => json(await fetch(`/api/runs/${encodeURIComponent(id)}/status`)),
  /** GET /api/runs/{id}/chat: the conversation bound to this run (text only), for a reload on ?run= */
  runChat: async (id: string): Promise<{ chat_id: string | null; lang?: 'cs' | 'en' | null; messages: { role: 'user' | 'assistant'; text: string }[] }> =>
    json(await fetch(`/api/runs/${encodeURIComponent(id)}/chat`)),
  createRun: async (criteria: CriteriaSet): Promise<{ run_id: string }> => json(await post('/api/runs', { criteria })),
  vet: async (id: string, candidate_ids: string[]): Promise<unknown> => json(await post(`/api/runs/${encodeURIComponent(id)}/vet`, { candidate_ids })),
  criteria: async (id: string, criteria: CriteriaSet): Promise<unknown> =>
    json(await post(`/api/runs/${encodeURIComponent(id)}/criteria`, { criteria })),
  restore: async (id: string, candidate_id: string, criterion_id: string): Promise<unknown> =>
    json(await post(`/api/runs/${encodeURIComponent(id)}/restore`, { candidate_id, criterion_id })),
  /** With a preset name the backend builds the preset criteria (docs/subject-mode.md: {"preset": "fitness"})
   *  and overlays the brief, so the texts stay in the owner's language. */
  goal: async (id: string, brief: Brief, preset?: 'bakery' | 'fitness' | null): Promise<unknown> =>
    json(await post(`/api/runs/${encodeURIComponent(id)}/goal`, preset ? { preset, brief } : { brief })),
  /** POST /api/subject (docs/subject-mode.md section 4.1): one named creator, one anchor, a goal. */
  subject: async (body: {
    subject: string
    platform?: Platform | null
    anchor?: Anchor | null
    brief?: Brief | null
    preset?: 'bakery' | 'fitness' | null
    lang: Lang
  }): Promise<{ run_id: string; mode?: string; subject?: { raw: string; handle: string; platform?: Platform | null }; status?: string }> =>
    json(await post('/api/subject', body)),
  purge: async (): Promise<unknown> => json(await post('/api/purge')),
}

/** Accepts `{dropped, returned}` at top level or under `diff`. */
export function extractDiff(body: unknown): RunDiff | null {
  if (!body || typeof body !== 'object') return null
  const b = body as Record<string, unknown>
  const d = (b.diff && typeof b.diff === 'object' ? b.diff : b) as Record<string, unknown>
  if (Array.isArray(d.dropped) || Array.isArray(d.returned)) {
    return {
      dropped: (d.dropped as RunDiff['dropped']) ?? [],
      returned: (d.returned as RunDiff['returned']) ?? [],
      pending_fetch: d.pending_fetch === true,
      final: d.final === true,
      replaces_pending: d.replaces_pending === true,
    }
  }
  return null
}

export interface ChatStreamHandlers {
  onEvent: (event: string, data: unknown) => void
}

/** POST /api/chat and stream SSE back through fetch + ReadableStream. */
export async function streamChat(
  body: { run_id?: string | null; chat_id?: string | null; message: string; lang: Lang; reset?: boolean; criteria?: CriteriaSet | null },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ ...body, run_id: body.run_id ?? undefined, chat_id: body.chat_id ?? undefined, reset: body.reset || undefined, criteria: body.criteria ?? undefined }),
    signal,
  })
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text.slice(0, 200)}` : ''}`)
  }
  const chatId = res.headers.get('X-Chat-Id')
  if (chatId) handlers.onEvent('chat.id', { chat_id: chatId })
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const feed = createSSEParser((m) => handlers.onEvent(m.event, safeJSON(m.data)))
  // Through the dev proxy a dead backend never closes the stream: give up after IDLE_MS without a byte
  // (the backend answers a turn within its 90 s tool wait), so the composer is not locked for good.
  const IDLE_MS = 120000
  for (;;) {
    let timer: number | undefined
    const idle = new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => reject(new Error('no answer from the server')), IDLE_MS)
    })
    let r: ReadableStreamReadResult<Uint8Array>
    try {
      r = await Promise.race([reader.read(), idle])
    } catch (e) {
      reader.cancel().catch(() => undefined)
      throw e
    } finally {
      window.clearTimeout(timer)
    }
    if (r.done) break
    feed(decoder.decode(r.value, { stream: true }))
  }
  feed(decoder.decode(), true)
}

/** `report_diffs` of a goal / criteria response (subject runs, and discovery reports with vetting data). */
export function extractReportDiffs(body: unknown): ReportDiff[] {
  if (!body || typeof body !== 'object') return []
  const list = (body as { report_diffs?: unknown }).report_diffs
  return Array.isArray(list) ? (list.filter((d) => d && typeof d === 'object' && typeof (d as ReportDiff).candidate_id === 'string') as ReportDiff[]) : []
}
