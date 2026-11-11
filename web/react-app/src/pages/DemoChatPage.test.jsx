import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'

// 전체 실행 부하에서 findBy/waitFor 기본 1초가 모자라 가끔 실패했다(리뷰 6번). 이 파일의 기다림 한도를 5초로 둔다.
configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 15000 })
import App from '../App'
import { PREVIEW_SUGGESTIONS } from '../lib/chat-preview'
import { DEMO_SUGGESTIONS } from '../lib/demo-suggestions'
import { isApprovalPending } from './DemoChatPage'

describe('DemoChatPage approval state', () => {
  it('only reports approval pending for the selected thread', () => {
    expect(isApprovalPending({ messages: [{ role: 'assistant', state: 'approval' }] })).toBe(true)
    expect(isApprovalPending({ messages: [{ role: 'assistant', state: 'done' }] })).toBe(false)
    expect(isApprovalPending(null)).toBe(false)
  })
})

const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }

function stubServer(detail) {
  window.history.replaceState({}, '', '/chat')
  vi.stubGlobal('fetch', vi.fn(async path => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed])
    if (path === '/threads/t1') return typeof detail === 'number' ? json({ detail: 'error' }, detail) : json(detail)
    return json({ detail: 'not found' }, 404)
  }))
}

describe('DemoChatPage thread selection after reload', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('loads the clicked thread from GET /threads/{id} and renders the question and answer', async () => {
    stubServer({ ...listed, last: { kind: 'answer', answer: '15일입니다.' }, messages: [
      { role: 'user', text: '연차는 며칠인가요?', timestamp: '2026-11-09T00:59:00Z' },
      { role: 'assistant', text: '15일입니다.', state: 'done', citations: [{ id: 'c1', chunk_id: 'c1', rule_title: '취업규칙' }], timestamp: '2026-11-09T01:00:00Z' },
    ] })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))

    expect(await screen.findByText('연차는 며칠인가요?')).toBeTruthy()
    expect(screen.getByText('15일입니다.')).toBeTruthy()
    expect(fetch).toHaveBeenCalledWith('/threads/t1', expect.anything())
    expect(document.querySelector('.demo-answer .citation-chip.selected')).toBeTruthy()
  })

  it('shows the last answer when an older server sends no messages', async () => {
    stubServer({ ...listed, last: { kind: 'answer', answer: '마지막 답변입니다.' } })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    expect(await screen.findByText('마지막 답변입니다.')).toBeTruthy()
  })

  it('shows an error line when the thread cannot be loaded', async () => {
    stubServer(500)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    expect((await screen.findByRole('alert')).textContent).toContain('대화를 불러오지 못했습니다.')
  })
})

// 배포 화면 빈 화면(11/9 실측): 답을 받는 도중 다른 메뉴로 가면 채팅 화면 정리 코드가 오류를 내 화면 전체가 하얗게 됐다.
describe('DemoChatPage leaving while an answer is streaming', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('keeps the app on screen when the user moves to another menu mid-answer', async () => {
    window.history.replaceState({}, '', '/chat')
    document.cookie = 'provena_csrf=test-token'
    let chatSignal
    vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
      if (path === '/me') return json(user)
      if (path === '/threads') return json([])
      if (path === '/auth/csrf') return new Response(null, { status: 204 })
      if (path === '/chat') {
        chatSignal = options.signal
        const body = new ReadableStream({ start(controller) {
          controller.enqueue(new TextEncoder().encode('event: token\ndata: {"type":"token","thread_id":"t2","data":{"text":"답변 앞부분"}}\n\n'))
          options.signal?.addEventListener('abort', () => controller.error(Object.assign(new Error('aborted'), { name: 'AbortError' })))
        } })
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      }
      return json({ items: [], threads: [] })
    }))
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(<App />)
    const box = await screen.findByRole('textbox', { name: '질문' })
    await waitFor(() => expect(box.disabled).toBe(false))   // 목록을 받는 동안 잠긴 버튼은 눌러도 반응이 없다
    fireEvent.change(box, { target: { value: '연차는 며칠인가요?' } })
    const send = screen.getByRole('button', { name: '보내기' })
    await waitFor(() => expect(send.disabled).toBe(false))
    fireEvent.click(send)
    // 새 대화는 답이 끝나야 본문에 열린다 → 받는 중임은 목록에 생긴 대화와 '답변 중지' 버튼으로 확인
    expect(await screen.findByRole('button', { name: '연차는 며칠인가요?' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '답변 중지' })).toBeTruthy()

    fireEvent.click(screen.getByRole('link', { name: /변경 감시/ }))

    await vi.waitFor(() => expect(window.location.pathname).toBe('/changes'), { timeout: 5000 })
    await waitFor(() => expect(chatSignal.aborted).toBe(true))
    expect(container.textContent.trim().length).toBeGreaterThan(0)
    expect(await screen.findByRole('link', { name: /채팅/ })).toBeTruthy()
    expect(consoleError.mock.calls.flat().join(' ')).not.toContain('abort is not a function')
  })
})

// 강사 코멘트 11/11: 키 없는 데모 첫 화면 추천 질문 3개가 녹화에 없어 거절됐다. 서버에 연결된 채팅(/chat)의 빈 화면은 녹화 질문을 추천한다.
describe('DemoChatPage first-screen suggestions in api mode', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('suggests the three recorded questions and sends the clicked one as is', async () => {
    window.history.replaceState({}, '', '/chat')
    document.cookie = 'provena_csrf=test-token'
    const sent = []
    vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
      if (path === '/me') return json(user)
      if (path === '/threads') return json([])
      if (path === '/auth/csrf') return new Response(null, { status: 204 })
      if (path === '/chat') {
        sent.push(JSON.parse(options.body).message)
        return new Response(new ReadableStream({ start(controller) { options.signal?.addEventListener('abort', () => controller.close()) } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      }
      return json({ items: [], threads: [] })
    }))
    const { container } = render(<App />)
    await screen.findByRole('textbox', { name: '질문' })
    await vi.waitFor(() => expect(container.querySelectorAll('.demo-suggestions button')).toHaveLength(3), { timeout: 5000 })
    const shown = [...container.querySelectorAll('.demo-suggestions button')].map(button => button.textContent)
    expect(shown).toEqual(DEMO_SUGGESTIONS)
    expect(shown).toHaveLength(3)
    expect(shown).not.toContain(PREVIEW_SUGGESTIONS[0])        // 녹화에 없는 미리보기 질문은 서버 연결 화면에 나오지 않는다
    fireEvent.click(screen.getByRole('button', { name: DEMO_SUGGESTIONS[1] }))
    await vi.waitFor(() => expect(sent).toEqual([DEMO_SUGGESTIONS[1]]), { timeout: 5000 })
  })
})

// H-08: 화면 쪽 — 오류 표시, 4000자 제한, 다시 시도
describe('DemoChatPage chat errors (H-08)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  function stubChat(chatResponse) {
    window.history.replaceState({}, '', '/chat')
    document.cookie = 'provena_csrf=test-token'
    const fetchMock = vi.fn(async path => {
      if (path === '/me') return json(user)
      if (path === '/threads') return json([listed])
      if (path === '/threads/t1') return json({ ...listed, messages: [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }] })
      if (path === '/auth/csrf') return new Response(null, { status: 204 })
      if (path === '/chat') return chatResponse()
      return json({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('shows the server message for a 409 and clears the generating bubble, and retry resends the question', async () => {
    const fetchMock = stubChat(() => json({ error: { code: 'approval_pending', message: '승인이 끝나야 다음 질문을 할 수 있습니다.' } }, 409))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('앞 답')
    fireEvent.change(screen.getByRole('textbox', { name: '질문' }), { target: { value: '다음 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '보내기' }))

    expect(await screen.findByText('승인이 끝나야 다음 질문을 할 수 있습니다.')).toBeTruthy()
    expect(screen.queryByText('답변을 생성하고 있습니다.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => path === '/chat')).toHaveLength(2), { timeout: 5000 })
    const bodies = fetchMock.mock.calls.filter(([path]) => path === '/chat').map(([, options]) => JSON.parse(options.body).message)
    expect(bodies).toEqual(['다음 질문', '다음 질문'])
  })

  it('shows the error for a first question in a new conversation too', async () => {
    stubChat(() => json({ error: { code: 'not_configured', message: '채팅이 설정되지 않았습니다.' } }, 503))
    render(<App />)
    const box = await screen.findByRole('textbox', { name: '질문' })
    // 목록을 받는 동안 입력칸과 보내기 버튼이 잠겨 있다. 잠긴 버튼을 누르면 아무 일도 없어 알림이 영영 안 뜬다.
    await waitFor(() => expect(box.disabled).toBe(false))
    fireEvent.change(box, { target: { value: '첫 질문' } })
    const send = screen.getByRole('button', { name: '보내기' })
    await waitFor(() => expect(send.disabled).toBe(false))
    fireEvent.click(send)
    expect((await screen.findByRole('alert')).textContent).toContain('채팅이 설정되지 않았습니다.')
  })

  it('limits the textarea to 4000 characters', async () => {
    stubChat(() => json({}, 500))
    render(<App />)
    expect((await screen.findByRole('textbox', { name: '질문' })).getAttribute('maxlength')).toBe('4000')
  })
})

// H-32: 근거 패널 번호는 선택한 답 기준
describe('DemoChatPage citation numbering (H-32)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('numbers panel tabs per answer, not across the whole thread', async () => {
    stubServer({ ...listed, messages: [
      { role: 'user', text: 'q1' },
      { role: 'assistant', text: 'a1', state: 'done', citations: [{ id: 'c1', rule_title: '문서A' }, { id: 'c2', rule_title: '문서B' }] },
      { role: 'user', text: 'q2' },
      { role: 'assistant', text: 'a2', state: 'done', citations: [{ id: 'c3', rule_title: '문서C' }, { id: 'c4', rule_title: '문서D' }] },
    ] })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('a2')
    expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['[1]', '[2]'])
    expect(screen.getAllByRole('tab').map(tab => tab.getAttribute('aria-label'))).toEqual(['출처 1: 문서C', '출처 2: 문서D'])
    fireEvent.click(screen.getByRole('button', { name: /문서A/ }))
    expect(screen.getAllByRole('tab').map(tab => tab.getAttribute('aria-label'))).toEqual(['출처 1: 문서A', '출처 2: 문서B'])
  })
})
