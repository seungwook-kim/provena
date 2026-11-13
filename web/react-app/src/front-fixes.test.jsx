import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import App from './App'

// 경희님 화면 점검(2026-11-13)에서 나온 수정 6건. 문구·숫자는 코드 상수를 가져오지 않고 그대로 적는다.
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 20000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }
const earlier = [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }]

function stubChat() {
  vi.stubGlobal('fetch', vi.fn(async path => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed])
    if (path === '/threads/t1') return json({ ...listed, messages: earlier })
    return json({ detail: 'not found' }, 404)
  }))
}

describe('① 채팅 새로고침해도 연 대화 유지 (AC-12)', () => {
  beforeEach(() => { sessionStorage.clear(); window.history.replaceState({}, '', '/chat') })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('대화를 연 뒤 새로고침(다시 그리기)하면 같은 대화가 열린다', async () => {
    stubChat()
    const first = render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('앞 답')
    first.unmount()
    render(<App />)
    expect(await screen.findByText('앞 답')).toBeTruthy()
  })

  it('"+ 새 대화"를 누른 뒤 새로고침하면 새 대화 화면이다', async () => {
    stubChat()
    const first = render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    await screen.findByText('앞 답')
    fireEvent.click(screen.getByRole('button', { name: '+ 새 대화' }))
    await waitFor(() => expect(screen.queryByText('앞 답')).toBeNull())
    first.unmount()
    render(<App />)
    await screen.findByRole('button', { name: '연차 질문' })
    expect(screen.queryByText('앞 답')).toBeNull()
  })

  it('목록에 없는 대화 id(지워졌거나 다른 계정)는 무시한다', async () => {
    sessionStorage.setItem('provena-chat-open', 'gone')
    stubChat()
    render(<App />)
    await screen.findByRole('button', { name: '연차 질문' })
    expect(screen.queryByText('앞 답')).toBeNull()
  })
})

describe('③ 구글 로그인 뒤 첫 화면에서 랜딩 깜빡임', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('세션 확인(/me)이 끝나기 전에는 랜딩을 그리지 않는다', async () => {
    window.history.replaceState({}, '', '/')
    let answer
    vi.stubGlobal('fetch', vi.fn(path => path === '/me' ? new Promise(resolve => { answer = resolve }) : Promise.resolve(json([]))))
    render(<App />)
    await waitFor(() => expect(answer).toBeTypeOf('function'))
    expect(document.querySelector('main[aria-busy="true"]')).toBeTruthy()
    expect(document.querySelector('.ve-nav')).toBeNull()
    answer(json(user))
    await waitFor(() => expect(window.location.pathname).toBe('/chat'))
    expect(document.querySelector('.ve-nav')).toBeNull()
  })

  it('로그인하지 않은 사람은 확인이 끝나면 랜딩을 본다', async () => {
    window.history.replaceState({}, '', '/')
    vi.stubGlobal('fetch', vi.fn(async path => path === '/me' ? json({ detail: 'unauthorized' }, 401) : json([])))
    render(<App />)
    await waitFor(() => expect(document.querySelector('.ve-nav')).toBeTruthy())
  })
})

describe('② 기억 설정 첫 단계의 "이전" 버튼', () => {
  beforeEach(() => { sessionStorage.clear() })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('첫 단계에는 이전 버튼이 없고, 다음 단계로 가면 생긴다', async () => {
    window.history.replaceState({}, '', '/demo/onboarding')
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'unauthorized' }, 401)))
    render(<App />)
    await screen.findByText('어느 팀에서 일하시나요?')
    await waitFor(() => expect(screen.queryByText('설정을 불러오는 중입니다.')).toBeNull())
    expect(screen.queryByRole('button', { name: '이전' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '보안' }))
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(await screen.findByRole('button', { name: '이전' })).toBeTruthy()
  })
})

describe('⑤ 모바일 변경 감시: 항목을 누르면 변경 전후로 내려감', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  async function openChanges(narrow) {
    window.history.replaceState({}, '', '/demo/changes')
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'unauthorized' }, 401)))
    vi.stubGlobal('matchMedia', vi.fn(query => ({ matches: narrow && query === '(max-width: 760px)', media: query, addEventListener() {}, removeEventListener() {} })))
    vi.stubGlobal('requestAnimationFrame', callback => { callback(0); return 0 })
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    render(<App />)
    const items = await waitFor(() => {
      const found = document.querySelectorAll('.change-service-item')
      expect(found.length).toBeGreaterThan(1)
      return found
    })
    fireEvent.click(items[1])
    return scrolled
  }

  it('760px 이하에서는 상세(article)로 스크롤한다', async () => {
    const scrolled = await openChanges(true)
    expect(scrolled).toHaveBeenCalledTimes(1)
    expect(scrolled.mock.contexts[0].classList.contains('change-service-detail')).toBe(true)
  })

  it('넓은 화면에서는 상세가 옆에 보이므로 움직이지 않는다', async () => {
    const scrolled = await openChanges(false)
    expect(scrolled).not.toHaveBeenCalled()
  })

  it('760px 이하에서는 목록과 상세가 한 줄씩 쌓인다(뒤쪽 338px 두 칸 규칙이 덮지 않음)', () => {
    const css = readFileSync('src/styles.css', 'utf8')
    const twoColumns = css.lastIndexOf('.change-service-layout{grid-template-columns:338px')
    const narrow = css.indexOf('@media(max-width:760px){.change-service-page{padding:22px', twoColumns)
    expect(twoColumns).toBeGreaterThan(-1)
    expect(narrow).toBeGreaterThan(twoColumns)
    expect(css.slice(narrow, css.indexOf('}}', narrow))).toMatch(/\.change-service-layout\{grid-template-columns:minmax\(0,1fr\)\}/)
  })
})

describe('④⑥ 권한 관리 간격과 좁은 화면 줄바꿈 (CSS)', () => {
  const css = readFileSync('src/admin-users.css', 'utf8')
  const narrow = css.slice(css.lastIndexOf('@media (max-width: 640px)'))

  it("'보기' 고르기와 아래 목록 사이를 띄운다", () => {
    expect(css).toMatch(/\.admin-signup-filter \{[^}]*margin: 0 auto 16px/)
  })

  it('처리 칸 버튼 사이를 띄운다', () => {
    expect(css).toMatch(/\.admin-users-table td:last-child button \{[^}]*margin: 2px 8px 2px 0/)
  })

  it("좁은 화면에서 한글을 낱말 단위로만 자른다('이메/일/인증' 방지)", () => {
    expect(narrow).toMatch(/\.admin-users-table th, \.admin-users-table td \{[^}]*word-break: keep-all/)
    expect(narrow).not.toMatch(/\.admin-users-table th, \.admin-users-table td \{[^}]*overflow-wrap: anywhere/)
    expect(narrow).toMatch(/\.admin-users-table td:first-child \{ overflow-wrap: anywhere; \}/)
  })
})
