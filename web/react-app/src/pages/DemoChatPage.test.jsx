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
