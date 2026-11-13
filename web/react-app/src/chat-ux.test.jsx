import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import App from './App'

// 문구·숫자가 바뀌면 시험도 실패하도록 코드의 상수를 가져오지 않고 그대로 적는다(chat-notices.test.jsx 와 같은 방식)
const RESUME_TEXT = '다른 화면에 있는 동안 이어서 만든 답을 불러오는 중입니다'
const COMPOSER_MAX_HEIGHT_PX = 208

configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 20000 })

const css = readFileSync('src/styles.css', 'utf8')
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }
const earlier = [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }]
const sse = events => events.map(event => `event: ${event.type}\ndata: ${JSON.stringify({ thread_id: 't1', ...event })}\n\n`).join('')
const endless = options => new Response(new ReadableStream({ start(controller) { options.signal?.addEventListener('abort', () => controller.close()) } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })

// jsdom 은 배치를 계산하지 않아 scrollHeight·clientHeight 가 0이고 scrollTop 을 저장하지 않는다 → 시험용으로 값을 정해 준다
const layout = new WeakMap()
function fakeLayout({ scrollHeight, clientHeight }) {
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() => scrollHeight())
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(() => clientHeight)
  vi.spyOn(HTMLElement.prototype, 'scrollTop', 'get').mockImplementation(function get() { return layout.get(this) ?? 0 })
  vi.spyOn(HTMLElement.prototype, 'scrollTop', 'set').mockImplementation(function set(value) { layout.set(this, value) })
}

function stubFetch({ chat, thread = () => json({ ...listed, messages: earlier }) }) {
  window.history.replaceState({}, '', '/chat')
  document.cookie = 'provena_csrf=test-token'
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed])
    if (path === '/threads/t1') return thread()
    if (path === '/auth/csrf') return new Response(null, { status: 204 })
    if (path === '/chat') return chat(options)
    return json({ detail: 'not found' }, 404)
  }))
}

async function openThreadAndAsk(question = '다음 질문') {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
  await screen.findByText('앞 답')
  const box = screen.getByRole('textbox', { name: '질문' })
  fireEvent.change(box, { target: { value: question } })
  const send = screen.getByRole('button', { name: '보내기' })
  await waitFor(() => expect(send.disabled).toBe(false))
  fireEvent.click(send)
}

describe('다른 메뉴에 갔다 와도 답 이어 받기', () => {
  beforeEach(() => { try { sessionStorage.clear() } catch { /* 없음 */ } })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('답을 받는 중 리콜 알림으로 갔다 돌아오면 그 대화를 열고, 서버가 끝낸 답을 보여 준다', async () => {
    let away = false
    let afterReturn = 0
    stubFetch({
      chat: endless,
      thread: () => {
        if (!away) return json({ ...listed, messages: earlier })
        afterReturn += 1
        // 돌아온 직후 한 번은 아직 만드는 중, 그다음은 끝난 답
        if (afterReturn === 1) return json({ ...listed, status: 'running', messages: earlier })
        return json({ ...listed, status: 'idle', messages: [...earlier, { role: 'user', text: '다음 질문' }, { role: 'assistant', text: '이어서 만든 답', state: 'done' }] })
      },
    })
    await openThreadAndAsk()
    await screen.findByText('근거를 찾고 답을 확인하는 중입니다.', { selector: '.demo-answer-progress' })

    away = true
    fireEvent.click(screen.getByRole('link', { name: '리콜 알림' }))
    await screen.findByRole('link', { name: '채팅' })
    fireEvent.click(screen.getByRole('link', { name: '채팅' }))

    expect(await screen.findByText(`${RESUME_TEXT}.`)).toBeTruthy()
    expect(screen.getByRole('textbox', { name: '질문' }).disabled).toBe(true)
    expect(await screen.findByText('이어서 만든 답')).toBeTruthy()
    await waitFor(() => expect(screen.queryByText(`${RESUME_TEXT}.`)).toBeNull())
    expect(afterReturn).toBeGreaterThanOrEqual(2)
  })

  it('답을 기다리다 다른 메뉴에 갔다 와도 보낸 질문이 입력칸에 다시 들어가 있지 않다', async () => {
    stubFetch({ chat: endless })
    await openThreadAndAsk('보낸 질문')
    const box = screen.getByRole('textbox', { name: '질문' })
    await waitFor(() => expect(box.value).toBe(''))   // 보내는 순간 비운다
    await screen.findByText('근거를 찾고 답을 확인하는 중입니다.', { selector: '.demo-answer-progress' })
    fireEvent.click(screen.getByRole('link', { name: '리콜 알림' }))
    fireEvent.click(await screen.findByRole('link', { name: '채팅' }))
    expect((await screen.findByRole('textbox', { name: '질문' })).value).toBe('')
  })

  it('새 대화 첫 질문을 못 보내면 그 질문을 입력칸에 되돌려 다시 보낼 수 있다', async () => {
    stubFetch({ chat: () => json({ detail: '잠시 후 다시 시도해 주세요.' }, 503) })
    render(<App />)
    const box = await screen.findByRole('textbox', { name: '질문' })
    fireEvent.change(box, { target: { value: '못 보낸 질문' } })
    const send = screen.getByRole('button', { name: '보내기' })
    await waitFor(() => expect(send.disabled).toBe(false))
    fireEvent.click(send)
    await screen.findByRole('alert')
    await waitFor(() => expect(screen.getByRole('textbox', { name: '질문' }).value).toBe('못 보낸 질문'))
  })

  it('답을 다 받은 뒤 다른 메뉴에 갔다 오면 아무 대화도 저절로 열지 않는다', async () => {
    stubFetch({ chat: () => new Response(sse([{ type: 'token', data: { text: '끝난 답' } }, { type: 'done', data: { kind: 'answer' } }]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }) })
    await openThreadAndAsk()
    await screen.findByText('끝난 답')
    fireEvent.click(screen.getByRole('link', { name: '리콜 알림' }))
    fireEvent.click(await screen.findByRole('link', { name: '채팅' }))
    await screen.findByRole('button', { name: '연차 질문' })
    expect(screen.queryByText(`${RESUME_TEXT}.`)).toBeNull()
    expect(screen.queryByText('끝난 답')).toBeNull()
  })
})

describe('질문하면 대화가 맨 아래로', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('질문을 보내고 답이 오면 메시지 영역이 맨 아래로 내려간다', async () => {
    let height = 600
    fakeLayout({ scrollHeight: () => height, clientHeight: 300 })
    stubFetch({ chat: () => new Response(sse([{ type: 'token', data: { text: '새 답' } }, { type: 'done', data: { kind: 'answer' } }]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }) })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('앞 답')
    const messages = document.querySelector('.demo-messages')
    height = 1500
    fireEvent.change(screen.getByRole('textbox', { name: '질문' }), { target: { value: '다음 질문' } })
    const send = screen.getByRole('button', { name: '보내기' })
    await waitFor(() => expect(send.disabled).toBe(false))
    fireEvent.click(send)
    await screen.findByText('새 답')
    expect(messages.scrollTop).toBe(1500)
  })

  it('위로 올려 읽는 중이면 새 말풍선이 생겨도 끌어내리지 않는다', async () => {
    let height = 1500
    fakeLayout({ scrollHeight: () => height, clientHeight: 300 })
    let push = null
    stubFetch({ chat: options => new Response(new ReadableStream({ start(controller) {
      push = text => controller.enqueue(new TextEncoder().encode(text))
      options.signal?.addEventListener('abort', () => controller.close())
    } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }) })
    await openThreadAndAsk()
    const messages = document.querySelector('.demo-messages')
    await screen.findByText('근거를 찾고 답을 확인하는 중입니다.', { selector: '.demo-answer-progress' })
    expect(messages.scrollTop).toBe(1500)
    // 맨 아래에서 위로 올린 뒤 답 조각이 새로 도착
    messages.scrollTop = 100
    fireEvent.scroll(messages)
    height = 2000
    await act(async () => { push(sse([{ type: 'token', data: { text: '도착한 조각' } }])) })
    await screen.findByText('도착한 조각')
    expect(messages.scrollTop).toBe(100)
  })
})

describe('입력칸 높이', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('글이 길면 늘어나되 최대 높이에서 멈춘다', async () => {
    let height = 72
    fakeLayout({ scrollHeight: () => height, clientHeight: 300 })
    stubFetch({ chat: endless })
    render(<App />)
    const box = await screen.findByRole('textbox', { name: '질문' })
    fireEvent.change(box, { target: { value: '한 줄\n두 줄\n세 줄' } })
    await waitFor(() => expect(box.style.height).toBe('72px'))
    height = 900
    fireEvent.change(box, { target: { value: '아주 긴 글\n'.repeat(40) } })
    await waitFor(() => expect(box.style.height).toBe(`${COMPOSER_MAX_HEIGHT_PX}px`))
  })

  it('CSS 가 최대 높이를 넘는 글을 칸 안에서 스크롤하게 한다', () => {
    expect(css).toMatch(new RegExp(String.raw`\.demo-composer textarea\{max-height:${COMPOSER_MAX_HEIGHT_PX}px;overflow-y:auto\}`))
  })
})
