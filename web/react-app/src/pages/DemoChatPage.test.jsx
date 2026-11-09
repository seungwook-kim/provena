import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import App from '../App'
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
    fireEvent.change(await screen.findByRole('textbox', { name: '질문' }), { target: { value: '연차는 며칠인가요?' } })
    fireEvent.click(screen.getByRole('button', { name: '보내기' }))
    // 새 대화는 답이 끝나야 본문에 열린다 → 받는 중임은 목록에 생긴 대화와 '답변 중지' 버튼으로 확인
    expect(await screen.findByRole('button', { name: '연차는 며칠인가요?' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '답변 중지' })).toBeTruthy()

    fireEvent.click(screen.getByRole('link', { name: /변경 감시/ }))

    await vi.waitFor(() => expect(window.location.pathname).toBe('/changes'))
    expect(chatSignal.aborted).toBe(true)
    expect(container.textContent.trim().length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /채팅/ })).toBeTruthy()
    expect(consoleError.mock.calls.flat().join(' ')).not.toContain('abort is not a function')
  })
})
