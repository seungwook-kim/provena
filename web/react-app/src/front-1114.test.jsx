import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'

// 11/14 화면 점검 3건: 위쪽 노란 진행 안내 삭제, 다른 탭 갔다 오면 랜딩이 다시 그려지던 것, 입력칸 타자 지연.
// 문구는 코드 상수를 가져오지 않고 그대로 적는다.
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 20000 })

const PROGRESS_TEXT = '근거를 찾고 답을 확인하는 중입니다'
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }
const other = { thread_id: 't2', title: '온콜 질문', status: 'idle', updated_at: '2026-11-08T01:00:00Z' }
const earlier = [
  { role: 'user', text: '앞 질문', created_at: '2026-11-09T00:59:00Z' },
  { role: 'assistant', text: '앞 답', state: 'done', created_at: '2026-11-09T01:00:00Z' },
]

function stubChat(chat = () => json({ detail: 'not found' }, 404)) {
  window.history.replaceState({}, '', '/chat')
  document.cookie = 'provena_csrf=test-token'
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed, other])
    if (path === '/threads/t1') return json({ ...listed, messages: earlier })
    if (path === '/auth/csrf') return new Response(null, { status: 204 })
    if (path === '/chat') return chat(options)
    return json({ detail: 'not found' }, 404)
  }))
}

describe('① 답을 만드는 중 위쪽 노란 안내 없음', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('생성 중에는 말풍선에만 진행 문구가 있고 위쪽 상태 줄은 비어 있다', async () => {
    stubChat(options => new Response(new ReadableStream({ start(controller) { options.signal?.addEventListener('abort', () => controller.close()) } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('앞 답')
    fireEvent.change(screen.getByRole('textbox', { name: '질문' }), { target: { value: '다음 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '보내기' }))
    expect(await screen.findByText(`${PROGRESS_TEXT}.`, { selector: '.demo-answer-progress' })).toBeTruthy()
    expect(document.querySelector('.demo-chat-status').textContent).toBe('')
  })
})

describe('② 다른 탭 갔다 오면 랜딩이 다시 그려지던 것', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('비로그인으로 확인된 뒤 창에 돌아와 다시 확인해도 랜딩을 지우지 않는다', async () => {
    window.history.replaceState({}, '', '/')
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async path => { if (path === '/me') { calls += 1; return json({ detail: 'unauthorized' }, 401) } return json([]) }))
    render(<App />)
    await waitFor(() => expect(document.querySelector('.ve-nav')).toBeTruthy())
    const before = document.querySelector('.ve-nav')
    let blanked = false
    const watch = new MutationObserver(() => { if (document.querySelector('main[aria-busy="true"]') || !document.querySelector('.ve-nav')) blanked = true })
    watch.observe(document.body, { childList: true, subtree: true })
    window.dispatchEvent(new Event('focus'))
    await waitFor(() => expect(calls).toBe(2))
    await new Promise(resolve => setTimeout(resolve, 50))
    watch.disconnect()
    expect(blanked).toBe(false)
    expect(document.querySelector('.ve-nav')).toBe(before)   // 같은 요소 = 다시 붙지 않았다(영상·애니메이션이 처음부터 다시 돌지 않는다)
  })

  it('다른 탭에서 로그인하고 돌아오면 채팅으로 간다', async () => {
    window.history.replaceState({}, '', '/')
    let signedIn = false
    vi.stubGlobal('fetch', vi.fn(async path => {
      if (path === '/me') return signedIn ? json(user) : json({ detail: 'unauthorized' }, 401)
      if (path === '/threads') return json([])
      return json([])
    }))
    render(<App />)
    await waitFor(() => expect(document.querySelector('.ve-nav')).toBeTruthy())
    signedIn = true
    window.dispatchEvent(new Event('focus'))
    await waitFor(() => expect(window.location.pathname).toBe('/chat'))
  })
})

describe('③ 입력칸에 칠 때 대화 목록·말풍선을 다시 그리지 않음', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('글자를 칠 때 대화 목록 시각과 말풍선 시각을 다시 계산하지 않는다', async () => {
    stubChat()
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('앞 답')
    // 대화 목록 시각은 toLocaleTimeString, 말풍선 시각은 toLocaleString 으로 만든다(렌더마다 한 번씩)
    const listTime = vi.spyOn(Date.prototype, 'toLocaleTimeString')
    const bubbleTime = vi.spyOn(Date.prototype, 'toLocaleString')
    const box = screen.getByRole('textbox', { name: '질문' })
    for (const value of ['ㅇ', '오', '온', '온콜']) fireEvent.change(box, { target: { value } })
    expect(box.value).toBe('온콜')
    expect(listTime).not.toHaveBeenCalled()
    expect(bubbleTime).not.toHaveBeenCalled()
  })
})
