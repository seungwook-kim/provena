import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import DecisionConvertPanel from './components/DecisionConvertPanel'

// 조장 추가 요청(2026-11-13, 경희님 전달): 새 대화 첫 질문 안내, 승인함 문구 삭제
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 20000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const sse = events => events.map(event => `event: ${event.type}\ndata: ${JSON.stringify({ thread_id: 't9', ...event })}\n\n`).join('')

describe('새 대화 첫 질문도 두 번째 질문처럼 말풍선으로 안내', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

  it('보내자마자 질문 말풍선과 확인 중 말풍선이 보이고, 답이 오면 그 대화로 바뀐다', async () => {
    window.history.replaceState({}, '', '/chat')
    document.cookie = 'provena_csrf=test-token'
    let answer
    vi.stubGlobal('fetch', vi.fn((path, options) => {
      if (path === '/me') return Promise.resolve(json(user))
      if (path === '/threads') return Promise.resolve(json([]))
      if (path === '/auth/csrf') return Promise.resolve(new Response(null, { status: 204 }))
      if (String(path).startsWith('/chat') && options?.method === 'POST') return new Promise(resolve => { answer = resolve })
      return Promise.resolve(json({ detail: 'not found' }, 404))
    }))
    render(<App />)
    await screen.findByText('정책에 대해 물어보세요.')
    fireEvent.change(screen.getByRole('textbox', { name: '질문' }), { target: { value: '연차는 며칠이야?' } })
    fireEvent.click(screen.getByRole('button', { name: '보내기' }))
    await waitFor(() => expect(answer).toBeTypeOf('function'))
    const stack = await waitFor(() => { const found = document.querySelector('.demo-message-stack'); expect(found).toBeTruthy(); return found })
    expect(stack.textContent).toContain('연차는 며칠이야?')
    expect(stack.querySelector('.demo-answer-progress')?.textContent).toContain('근거를 찾고 답을 확인하는 중입니다')
    expect(screen.queryByText('정책에 대해 물어보세요.')).toBeNull()
    answer(new Response(sse([{ type: 'token', data: { text: '연차는 15일입니다.' } }, { type: 'done', data: { kind: 'answer' } }]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText('연차는 15일입니다.', { exact: false })).toBeTruthy()
    expect(document.querySelector('.demo-answer-progress')).toBeNull()
    expect(screen.getByRole('button', { name: '연차는 며칠이야?' }).className).toContain('selected')
  })
})

describe('승인함 결정표 변환 안내 문구', () => {
  afterEach(cleanup)

  it("화면 설명에서 'API 키가 있으면 LLM을 호출합니다'를 뺀다", () => {
    render(<DecisionConvertPanel service={{ convertDecisionTable: vi.fn() }} onConverted={() => {}} />)
    const lede = document.querySelector('.convert-lede')
    expect(lede.textContent).toBe('핸드북 권한표의 업무 종류 하나를 결정표 초안으로 바꿔 아래 승인함에 올립니다.')
  })
})
