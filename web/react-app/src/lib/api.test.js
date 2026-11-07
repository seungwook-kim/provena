import { describe, expect, it, vi } from 'vitest'
import { streamChatMessage } from './api'

function sseResponse(...chunks) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) { chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk))); controller.close() },
  })
  return new Response(stream, { headers: { 'content-type': 'text/event-stream' } })
}

describe('streamChatMessage', () => {
  it('parses events split across response chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(
      'data: {"type":"token","thread_id":"t1","data":{"text":"안"}}\n\n',
      'data: {"type":"done","thread_id":"t1","data":{"answer_id":"a1"}}\n\n',
    )))
    const events = []
    await streamChatMessage('t1', '질문', { onEvent: event => events.push(event) })
    expect(events.map(event => event.type)).toEqual(['token', 'done'])
    expect(events[0].data.text).toBe('안')
  })
})
