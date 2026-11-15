import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import { mapThreadRecord } from './lib/chat-service'

// 이어 묻기(D-14, 팀장 결정 ①): 서버가 이어 묻는 질문을 완전한 질문으로 다시 썼을 때만 done.understood_question이 온다.
// 화면은 그 답 위에 "이렇게 이해했습니다: …"를 보이고, 값이 없으면 아무것도 더 보이지 않는다.
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 20000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const sse = events => events.map(event => `event: ${event.type}\ndata: ${JSON.stringify({ thread_id: 't1', ...event })}\n\n`).join('')
const stream = events => new Response(sse(events), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
const listed = { thread_id: 't1', title: '환불 기한은 며칠인가요?', status: 'idle', updated_at: '2026-11-15T01:00:00Z' }
const NOTE = '이렇게 이해했습니다: 고객에게 적용되는 환불 기한은 며칠인가요?'

function stubApi({ messages, replies }) {
  const sent = []
  vi.stubGlobal('fetch', vi.fn((path, options) => {
    if (path === '/me') return Promise.resolve(json(user))
    if (path === '/threads') return Promise.resolve(json([listed]))
    if (path === '/threads/t1') return Promise.resolve(json({ ...listed, messages }))
    if (path === '/auth/csrf') return Promise.resolve(new Response(null, { status: 204 }))
    if (String(path).startsWith('/chat') && options?.method === 'POST') { sent.push(JSON.parse(options.body)); return Promise.resolve(stream(replies.shift())) }
    return Promise.resolve(json({ detail: 'not found' }, 404))
  }))
  return sent
}

async function openThreadAndSend(text) {
  window.history.replaceState({}, '', '/chat')
  document.cookie = 'provena_csrf=test-token'
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: listed.title }))
  await screen.findByText('환불은 14일 안에 합니다.', { exact: false })
  fireEvent.change(screen.getByRole('textbox', { name: '질문' }), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '보내기' }))
}

const earlier = [
  { role: 'user', text: '환불 기한은 며칠인가요?', timestamp: '2026-11-15T01:00:00Z' },
  { role: 'assistant', text: '환불은 14일 안에 합니다.', state: 'done', kind: 'answer', citations: [], timestamp: '2026-11-15T01:00:05Z' },
]

describe('이어 묻기 안내(이렇게 이해했습니다)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

  it('서버가 다시 쓴 질문을 보내면 그 답 위에 안내를 보이고, 보낸 질문 말풍선은 친 글 그대로다', async () => {
    const sent = stubApi({ messages: earlier, replies: [[
      { type: 'token', data: { text: '고객 환불은 30일 안에 합니다.' } },
      { type: 'done', data: { kind: 'answer', understood_question: '고객에게 적용되는 환불 기한은 며칠인가요?' } },
    ]] })
    await openThreadAndSend('고객은요?')
    expect(await screen.findByText('고객 환불은 30일 안에 합니다.', { exact: false })).toBeTruthy()
    const notes = document.querySelectorAll('.demo-answer-understood')
    expect(notes.length).toBe(1)
    expect(notes[0].textContent).toBe(NOTE)
    const answer = notes[0].closest('.demo-answer')
    expect(answer.textContent).toContain('고객 환불은 30일 안에 합니다.')
    expect(answer.textContent.indexOf(NOTE)).toBeLessThan(answer.textContent.indexOf('고객 환불은 30일 안에 합니다.'))   // 답 위
    expect([...document.querySelectorAll('.demo-user-message')].map(node => node.textContent)).toEqual(['환불 기한은 며칠인가요?', '고객은요?'])
    expect(sent).toEqual([{ message: '고객은요?', thread_id: 't1' }])   // 요청 모양은 그대로다(앞 질문은 서버가 찾는다)
  })

  it('서버가 다시 쓰지 않았으면(칸 없음, 빈 값) 안내가 없다', async () => {
    stubApi({ messages: earlier, replies: [[
      { type: 'token', data: { text: '휴가는 연 15일입니다.' } },
      { type: 'done', data: { kind: 'answer', understood_question: '' } },
    ]] })
    await openThreadAndSend('휴가는 며칠인가요?')
    expect(await screen.findByText('휴가는 연 15일입니다.', { exact: false })).toBeTruthy()
    await waitFor(() => expect(document.querySelector('.demo-answer-progress')).toBeNull())
    expect(document.querySelector('.demo-answer-understood')).toBeNull()
    expect(document.body.textContent).not.toContain('이렇게 이해했습니다')
  })

  it('다시 연 대화에서도 서버가 준 다시 쓴 질문을 그 답에만 보인다', async () => {
    stubApi({ messages: [
      ...earlier,
      { role: 'user', text: '고객은요?', timestamp: '2026-11-15T01:01:00Z' },
      { role: 'assistant', text: '고객 환불은 30일 안에 합니다.', state: 'done', kind: 'answer', citations: [], understood_question: '고객에게 적용되는 환불 기한은 며칠인가요?', timestamp: '2026-11-15T01:01:05Z' },
    ], replies: [] })
    window.history.replaceState({}, '', '/chat')
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: listed.title }))
    await screen.findByText('고객 환불은 30일 안에 합니다.', { exact: false })
    const notes = document.querySelectorAll('.demo-answer-understood')
    expect(notes.length).toBe(1)
    expect(notes[0].closest('.demo-answer').textContent).toContain('고객 환불은 30일 안에 합니다.')
  })

  it('대화 기록 변환은 문자열인 understood_question만 옮긴다', () => {
    const mapped = mapThreadRecord({ thread_id: 't1', messages: [
      { role: 'assistant', text: '가', understood_question: '다시 쓴 질문' },
      { role: 'assistant', text: '나' },
      { role: 'assistant', text: '다', understood_question: { a: 1 } },
      { role: 'user', text: '라', understood_question: '무시' },
    ] })
    expect(mapped.messages.map(message => message.understoodQuestion)).toEqual(['다시 쓴 질문', undefined, undefined, undefined])
  })
})
