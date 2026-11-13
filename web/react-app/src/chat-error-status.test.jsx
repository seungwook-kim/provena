import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'

// H-08: POST /chat 가 422·403 으로 답하면 화면에 오류 말풍선이 남는지 본다(문구는 코드 상수를 가져오지 않고 그대로 적는다).
configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 15000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }
const messages = [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }]
const GENERATING_TEXT = '근거를 찾고 답을 확인하는 중입니다'

async function askAndFail(chat) {
  window.history.replaceState({}, '', '/chat')
  document.cookie = 'provena_csrf=test-token'
  const fetchMock = vi.fn(async (path, options = {}) => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed])
    if (path === '/threads/t1') return json({ ...listed, messages })
    if (path === '/auth/csrf') return new Response(null, { status: 204 })
    if (path === '/chat') return chat(options)
    return json({ detail: 'not found' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
  await screen.findByText('앞 답')
  fireEvent.change(screen.getByRole('textbox', { name: '질문' }), { target: { value: '다음 질문' } })
  const send = screen.getByRole('button', { name: '보내기' })
  await waitFor(() => expect(send.disabled).toBe(false))
  fireEvent.click(send)
  return fetchMock
}

describe('채팅 422·403 오류 화면 (H-08)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it.each([
    ['422 validation_error', () => json({ detail: '입력한 내용을 확인해 주세요.', error: { code: 'validation_error', message: '질문이 너무 깁니다. 줄여서 다시 보내 주세요.', request_id: 'r1' } }, 422), '질문이 너무 깁니다. 줄여서 다시 보내 주세요.'],
    ['403 csrf_failed (새 토큰으로 다시 보내도 같은 오류)', () => json({ error: { code: 'csrf_failed', message: 'CSRF 검증에 실패했습니다.' } }, 403), 'CSRF 검증에 실패했습니다.'],
    ['403 forbidden 본문 없음', () => new Response('<html>forbidden</html>', { status: 403, headers: { 'Content-Type': 'text/html' } }), '이 작업을 수행할 권한이 없습니다.'],
  ])('%s 이면 서버 문구의 오류 말풍선을 보이고 생성 중 말풍선은 남기지 않는다', async (_name, respond, expected) => {
    const fetchMock = await askAndFail(respond)

    const alert = await screen.findByText(expected)
    expect(alert.closest('[role="alert"]')).toBeTruthy()
    expect(screen.queryByText(new RegExp(GENERATING_TEXT))).toBeNull()
    expect(screen.getByText('다음 질문')).toBeTruthy()
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
    expect(fetchMock.mock.calls.some(([path]) => path === '/chat')).toBe(true)
  })

  it('다시 시도를 누르면 같은 질문을 다시 보내고, 이번에 성공하면 오류가 사라진다', async () => {
    let calls = 0
    const fetchMock = await askAndFail(() => {
      calls += 1
      if (calls === 1) return json({ error: { code: 'validation_error', message: '기준일이 올바르지 않습니다.' } }, 422)
      return new Response(`event: token\ndata: ${JSON.stringify({ type: 'token', thread_id: 't1', data: { text: '재시도 답' } })}\n\nevent: done\ndata: ${JSON.stringify({ type: 'done', thread_id: 't1', data: { kind: 'answer' } })}\n\n`, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    })
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText('재시도 답')).toBeTruthy()
    expect(screen.queryByText('기준일이 올바르지 않습니다.')).toBeNull()
    const bodies = fetchMock.mock.calls.filter(([path]) => path === '/chat').map(([, options]) => JSON.parse(options.body).message)
    expect(bodies).toEqual(['다음 질문', '다음 질문'])
  })
})
