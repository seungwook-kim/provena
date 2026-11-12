import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import App from './App'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 15000 })

const css = readFileSync('src/styles.css', 'utf8')
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('답변 줄바꿈 (A1)', () => {
  it('.demo-answer p 가 줄바꿈(\n)을 유지한다', () => {
    const rule = css.match(/\.demo-answer p\{[^}]*\}/)[0]
    expect(rule).toMatch(/white-space:pre-line/)
  })
})

describe('내 계정 메뉴 (A4)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it("'대화 기록 보기' 항목이 없다", async () => {
    window.history.replaceState({}, '', '/chat')
    vi.stubGlobal('fetch', vi.fn(async path => {
      if (path === '/me') return json({ user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true })
      if (path === '/threads') return json([])
      return json({ detail: 'not found' }, 404)
    }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '내 계정' }))
    expect(await screen.findByRole('menuitem', { name: '회원정보 수정' })).toBeTruthy()
    expect(screen.queryByRole('menuitem', { name: '대화 기록 보기' })).toBeNull()
  })
})

describe('좁은 화면 채팅 배치 (A5)', () => {
  const block = css.slice(css.lastIndexOf('@media(max-width:640px){.demo-chat-page'))

  it('대화 목록 높이를 줄인다(200px 아님)', () => {
    expect(block).toMatch(/\.demo-thread-sidebar\{[^}]*max-height:96px/)
  })

  it('입력창이 화면 아래에 붙어 항상 닿는다', () => {
    expect(block).toMatch(/\.demo-chat-page \.demo-composer\{[^}]*position:sticky;bottom:0/)
  })

  it('참고 근거 패널이 입력창보다 앞에 온다', () => {
    const order = sel => Number(block.match(new RegExp(String.raw`.demo-chat-page .${sel}\{[^}]*order:(\d+)`))[1])
    expect(order('demo-citation-sidebar')).toBeLessThan(order('demo-composer'))
    expect(order('demo-messages')).toBeLessThan(order('demo-citation-sidebar'))
    expect(block).toMatch(/\.demo-chat-main\{display:contents\}/)
  })

  it('빈 대화에서 메시지 영역 최소 높이가 480px 로 입력창을 밀어내지 않는다', () => {
    expect(block).toMatch(/\.demo-messages\{[^}]*min-height:200px/)
  })

  it('데스크톱 3열 규칙은 640px 밖에 그대로 있다', () => {
    expect(css).toMatch(/\.demo-chat-main\{display:flex;min-width:0;flex-direction:column\}/)
    expect(css.slice(0, css.lastIndexOf('@media(max-width:640px){.demo-chat-page'))).not.toMatch(/\.demo-chat-main\{display:contents\}/)
  })
})
