import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

// jsdom은 레이아웃을 계산하지 못하므로 CSS 규칙 문자열만 확인한다(H-26, H-33). 실제 폭 확인은 수동(390px·800px).
const css = readFileSync('src/styles.css', 'utf8')
const lastBlock = media => css.slice(css.lastIndexOf(media))

describe('좁은 화면 채팅 레이아웃 (H-26)', () => {
  it('1000px 이하에서 참고 근거 패널을 숨기지 않고 아래 줄로 내린다', () => {
    const block = lastBlock('@media(max-width:1000px){.demo-chat-page')
    expect(block).toMatch(/\.demo-chat-page \.demo-citation-sidebar\{display:block;grid-column:1\/-1/)
  })

  it('640px 이하에서 대화 목록(새 대화·검색 포함)을 display:none 하지 않는다', () => {
    const block = lastBlock('@media(max-width:640px){.demo-chat-page')
    expect(block).toMatch(/\.demo-chat-page \.demo-thread-sidebar\{display:flex/)
  })
})

describe('좁은 화면 상단 메뉴·권한 표 (H-33)', () => {
  it('760px 이하에서 상단 메뉴가 줄바꿈되어 6번째 항목도 보인다', () => {
    const header = readFileSync('src/header.css', 'utf8')
    expect(header.slice(header.lastIndexOf('@media (max-width: 760px)'))).toMatch(/flex-wrap: wrap;\s*overflow: visible/)
  })

  it('640px 이하에서 권한 표 칸이 줄바꿈되어 버튼이 가로 스크롤 뒤로 밀리지 않는다', () => {
    const admin = readFileSync('src/admin-users.css', 'utf8')
    expect(admin.slice(admin.lastIndexOf('@media (max-width: 640px)'))).toMatch(/admin-users-table td \{[^}]*white-space: normal/)
  })
})
