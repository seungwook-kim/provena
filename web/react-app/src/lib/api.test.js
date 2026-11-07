import { describe, expect, it, vi } from 'vitest'
import { deleteMemory, patchMemory, streamChatMessage } from './api'

function sseResponse(...chunks) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) { chunks.forEach(chunk => controller.enqueue(encoder.encode(chunk))); controller.close() },
  })
  return new Response(stream, { headers: { 'content-type': 'text/event-stream' } })
}

describe('streamChatMessage', () => {
  it('parses events split across response chunks', async () => {
    document.cookie = 'provena_csrf=csrf-token'
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(sseResponse(
      'data: {"type":"token","thread_id":"t1","data":{"text":"안"}}\n\n',
      'data: {"type":"done","thread_id":"t1","data":{"answer_id":"a1"}}\n\n',
    )))
    const events = []
    await streamChatMessage('t1', '질문', { onEvent: event => events.push(event) })
    expect(events.map(event => event.type)).toEqual(['token', 'done'])
    expect(events[0].data.text).toBe('안')
  })

  it('fetches CSRF and sends the token on the SSE request', async () => {
    document.cookie = 'provena_csrf=csrf-token'
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(sseResponse('data: {"type":"done","thread_id":"t1","data":{}}\n\n'))
    vi.stubGlobal('fetch', fetchMock)
    await streamChatMessage('t1', 'question')
    expect(fetchMock.mock.calls[0][0]).toContain('/auth/csrf')
    expect(fetchMock.mock.calls[1][1].headers['X-CSRF-Token']).toBe('csrf-token')
  })

  it('sends CSRF on memory mutations', async () => {
    document.cookie = 'provena_csrf=memory-token'
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await patchMemory({ affiliation: 'IT' })
    await deleteMemory()
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/auth/csrf'))).toHaveLength(2)
    expect(fetchMock.mock.calls.find(([url]) => url.includes('/me/memory'))[1].headers['X-CSRF-Token']).toBe('memory-token')
  })
})
