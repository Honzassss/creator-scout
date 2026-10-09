// Minimal SSE parser for fetch() + ReadableStream (POST /api/chat cannot use EventSource).

export interface SSEMessage {
  event: string
  data: string
  id?: string
}

/** Feed text chunks in; get complete messages out. Handles \r\n, multi-line data, comments. */
export function createSSEParser(onMessage: (m: SSEMessage) => void) {
  let buf = ''
  return (chunk: string, flush = false) => {
    buf += chunk.replace(/\r\n?/g, '\n')
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      emit(block)
    }
    if (flush && buf.trim()) {
      emit(buf)
      buf = ''
    }
  }

  function emit(block: string) {
    let event = 'message'
    let id: string | undefined
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      let value = colon < 0 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
      else if (field === 'id') id = value
    }
    if (data.length || event !== 'message') onMessage({ event, data: data.join('\n'), id })
  }
}

export function safeJSON(s: string): unknown {
  if (!s) return {}
  try {
    return JSON.parse(s)
  } catch {
    return { text: s }
  }
}
