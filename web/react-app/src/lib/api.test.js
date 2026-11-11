import { describe, expect, it, vi } from 'vitest'
import { apiRequest, deleteMemory, patchMemory, streamChatMessage } from './api'

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

  it('parses an approval_request SSE event', async () => {
    document.cookie = 'provena_csrf=csrf-token'
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(sseResponse('event: approval_request\ndata: {"thread_id":"t1","data":{"code":"approval_pending"}}\n\n')))
    const events = []
    await streamChatMessage('t1', 'question', { onEvent: event => events.push(event) })
    expect(events).toEqual([{ type: 'approval_request', thread_id: 't1', data: { code: 'approval_pending' } }])
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

describe('apiRequest cache', () => {
  it('never lets the browser reuse a cached page for an API URL that is also a screen URL', async () => {
    // /admin/users·/recalls·/approvals 새로고침 뒤 캐시된 HTML을 fetch가 받던 문제(11/11)
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"users":[]}', { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await apiRequest('/admin/users')
    expect(fetchMock.mock.calls[0][1].cache).toBe('no-store')
    vi.unstubAllGlobals()
  })
})

// H-17: 이벤트가 아주 많아도 콜백 호출이 겹겹이 쌓이지 않는다
describe('streamChatMessage many events (H-17)', () => {
  it('delivers 30000 named events in one chunk without nesting callbacks', async () => {
    document.cookie = 'provena_csrf=csrf-token'
    const block = 'event: token\ndata: {"thread_id":"t1","data":{"text":"a"}}\n\n'
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(sseResponse(block.repeat(30000))))
    let count = 0
    await streamChatMessage('t1', 'q', { onEvent: event => { count += 1; if (event.type !== 'token') throw new Error('type') } })
    expect(count).toBe(30000)
  })
})
