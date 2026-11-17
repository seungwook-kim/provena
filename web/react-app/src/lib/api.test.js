import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiJson, apiRequest, deleteMemory, patchMemory, streamChatMessage } from './api'

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

describe('CSRF token race (H-18)', () => {
  it('shares one token fetch between concurrent mutations', async () => {
    document.cookie = 'provena_csrf=tok'
    const fetchMock = vi.fn(async url => url.includes('/auth/csrf') ? new Response(null, { status: 204 }) : new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await Promise.all([patchMemory({ a: 1 }), patchMemory({ a: 2 }), patchMemory({ a: 3 })])
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/auth/csrf'))).toHaveLength(1)
  })

  it('retries once with a fresh token when the server answers csrf_failed', async () => {
    document.cookie = 'provena_csrf=old'
    let posts = 0
    const fetchMock = vi.fn(async (url, init) => {
      if (url.includes('/auth/csrf')) { document.cookie = 'provena_csrf=fresh'; return new Response(null, { status: 204 }) }
      posts += 1
      if (init.headers['X-CSRF-Token'] !== 'fresh') return new Response(JSON.stringify({ error: { code: 'csrf_failed', message: 'CSRF 검증에 실패했습니다.' } }), { status: 403, headers: { 'content-type': 'application/json' } })
      return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    document.cookie = 'provena_csrf=old'
    await expect(patchMemory({ a: 1 })).resolves.toBeDefined()
    expect(posts).toBeLessThanOrEqual(2)
  })

  it('gives up after one retry', async () => {
    document.cookie = 'provena_csrf=old'
    const fetchMock = vi.fn(async url => url.includes('/auth/csrf') ? new Response(null, { status: 204 }) : new Response(JSON.stringify({ error: { code: 'csrf_failed', message: 'x' } }), { status: 403, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(patchMemory({ a: 1 })).rejects.toMatchObject({ code: 'csrf_failed' })
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/me/memory'))).toHaveLength(2)
  })
})

describe('network failure', () => {
  it('turns a browser fetch failure into a Korean ApiError instead of the English "Failed to fetch"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const error = await apiJson('/me').catch(e => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('서버에 연결하지 못했습니다. 네트워크를 확인하고 잠시 후 다시 시도해 주세요.')
    expect(error.status).toBe(0)
    expect(error.code).toBe('network_error')
    vi.unstubAllGlobals()
  })

  it('keeps an aborted request as an AbortError so cancelling is not reported as a failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError')))
    const error = await apiJson('/me').catch(e => e)
    expect(error.name).toBe('AbortError')
    vi.unstubAllGlobals()
  })
})

describe('가입 요청의 CSRF는 api.js 공용 경로를 쓴다 (A9)', () => {
  it('403 csrf_failed를 받으면 새 토큰으로 한 번만 다시 보낸다', async () => {
    const { requestSignup } = await import('./signup')
    document.cookie = 'provena_csrf=old'
    let signupCalls = 0
    const fetchMock = vi.fn(async (url, init) => {
      if (url.includes('/auth/csrf')) { document.cookie = 'provena_csrf=fresh'; return new Response(null, { status: 204 }) }
      signupCalls += 1
      if (signupCalls === 1) return new Response(JSON.stringify({ error: { code: 'csrf_failed', message: 'x' } }), { status: 403, headers: { 'content-type': 'application/json' } })
      return new Response('{"status":"sent"}', { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    document.cookie = 'provena_csrf=old'
    await requestSignup({ email: 'a@b.co', password: 'password1', passwordConfirmation: 'password1' })
    const signups = fetchMock.mock.calls.filter(([url]) => url.includes('/auth/signup'))
    expect(signups).toHaveLength(2)
    expect(signups[1][1].headers['X-CSRF-Token']).toBe('fresh')
    vi.unstubAllGlobals()
  })

  it('동시에 보낸 가입 요청도 /auth/csrf는 한 번만 받는다', async () => {
    const { requestSignup, resendSignupCode } = await import('./signup')
    const fetchMock = vi.fn(async url => {
      if (url.includes('/auth/csrf')) { document.cookie = 'provena_csrf=t1'; return new Response(null, { status: 204 }) }
      return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    await Promise.all([requestSignup({ email: 'a@b.co', password: 'password1', passwordConfirmation: 'password1' }), resendSignupCode('a@b.co')])
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/auth/csrf'))).toHaveLength(1)
    vi.unstubAllGlobals()
  })
})

describe('rate limit message', () => {
  afterEach(() => { vi.unstubAllGlobals() })
  const limited = headers => vi.fn(async () => new Response(JSON.stringify({ error: { code: 'rate_limited', message: '요청이 너무 많습니다.' } }), { status: 429, headers: { 'Content-Type': 'application/json', ...headers } }))

  it('adds the Retry-After seconds to a 429 error', async () => {
    vi.stubGlobal('fetch', limited({ 'Retry-After': '30' }))
    const error = await apiJson('/anything').catch(caught => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(429)
    expect(error.message).toContain('약 30초 뒤')
  })

  it('leaves a 429 without Retry-After as the plain message', async () => {
    vi.stubGlobal('fetch', limited({}))
    const error = await apiJson('/anything').catch(caught => caught)
    expect(error.message).toBe('요청이 너무 많습니다.')
  })

  it('adds no seconds text when Retry-After is an HTTP date', async () => {
    vi.stubGlobal('fetch', limited({ 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' }))
    const error = await apiJson('/anything').catch(caught => caught)
    expect(error.message).toBe('요청이 너무 많습니다.')
  })

  // 하루 질문 한도(backend/api/daily_limit.py): 서버 문구를 그대로 보이고, 다음 자정까지의 초는 붙이지 않는다
  it('shows the daily question limit message as is', async () => {
    const message = '오늘 질문 한도(50건)를 넘었습니다. 내일 다시 이용해 주세요.'
    document.cookie = 'provena_csrf=csrf-token'
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: message, error: { code: 'daily_limit', message } }), { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '43200' } }))
    vi.stubGlobal('fetch', fetchMock)
    const error = await streamChatMessage(null, '질문').catch(caught => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(429)
    expect(error.code).toBe('daily_limit')
    expect(error.message).toBe(message)
    expect(fetchMock.mock.calls.at(-1)[0]).toContain('/chat')
  })
})
