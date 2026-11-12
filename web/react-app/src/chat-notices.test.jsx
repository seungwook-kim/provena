import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import { APPROVAL_WAITING_TEXT, MODIFIED_LABEL, PROGRESS_TEXT } from './pages/DemoChatPage'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 15000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }
const sse = events => events.map(event => `event: ${event.type}\ndata: ${JSON.stringify({ thread_id: 't1', ...event })}\n\n`).join('')
// backend/api/routes.py ATTRIBUTION 과 같은 모양
const ATTRIBUTION = { source: 'GitLab Handbook', license: 'CC BY-SA 4.0', license_url: 'https://creativecommons.org/licenses/by-sa/4.0/', modified: true, notice: 'GitLab 핸드북 기반 데모입니다.' }

// 앞 대화(t1)를 연 뒤 질문을 보낸다. chat 은 /chat 응답을 만드는 함수
async function askInThread(chat, threadMessages = [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }]) {
  window.history.replaceState({}, '', '/chat')
  document.cookie = 'provena_csrf=test-token'
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed])
    if (path === '/threads/t1') return json({ ...listed, messages: threadMessages })
    if (path === '/auth/csrf') return new Response(null, { status: 204 })
    if (path === '/chat') return chat(options)
    return json({ detail: 'not found' }, 404)
  }))
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
  await screen.findByText(threadMessages.at(-1).text || threadMessages[0].text)
  const box = screen.getByRole('textbox', { name: '질문' })
  fireEvent.change(box, { target: { value: '다음 질문' } })
  const send = screen.getByRole('button', { name: '보내기' })
  await waitFor(() => expect(send.disabled).toBe(false))
  fireEvent.click(send)
}

describe('출처·라이선스 수정 여부 (④)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('서버가 modified=true 를 주면 수정됨 표시를 그린다', async () => {
    await askInThread(() => new Response(sse([
      { type: 'token', data: { text: '답입니다.' } },
      { type: 'done', data: { kind: 'answer', attribution: ATTRIBUTION } },
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText('라이선스 보기')).toBeTruthy()
    expect(screen.getByText(MODIFIED_LABEL)).toBeTruthy()
  })

  it('modified 가 없으면 그리지 않는다', async () => {
    await askInThread(() => new Response(sse([
      { type: 'token', data: { text: '답입니다.' } },
      { type: 'done', data: { kind: 'answer', attribution: { ...ATTRIBUTION, modified: false } } },
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText('라이선스 보기')).toBeTruthy()
    expect(screen.queryByText(MODIFIED_LABEL)).toBeNull()
  })
})

describe('답 기다리는 동안 지난 시간 (⑤)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('생성 중 말풍선이 지난 초를 센다', async () => {
    await askInThread(options => new Response(new ReadableStream({ start(controller) { options.signal?.addEventListener('abort', () => controller.close()) } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText(`${PROGRESS_TEXT}.`, { selector: '.demo-answer-progress' })).toBeTruthy()
    // 타이머는 말풍선이 그려질 때 걸리므로 진짜 시계로 2초 남짓 기다린다
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)) })
    expect(screen.getByText(new RegExp(`^${PROGRESS_TEXT} · [12]초 지남$`))).toBeTruthy()
  })
})

describe('승인 대기 안내 (⑥)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('승인 대기 말풍선에 다음 행동까지 적힌 고정 문구를 보여 준다', async () => {
    await askInThread(() => new Response(sse([
      { type: 'approval_request', data: { approval_id: 'iss-1', kind: 'issue_table', summary: '쟁점표' } },
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText(APPROVAL_WAITING_TEXT)).toBeTruthy()
    expect(screen.queryByText('승인 대기 중')).toBeNull()
  })
})
