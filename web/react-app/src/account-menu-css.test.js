import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

// jsdom은 레이아웃을 계산하지 못하므로 CSS 규칙 문자열만 확인한다.
describe('내 계정 팝업 CSS', () => {
  it('상위 .demo-nav-actions 의 nowrap 상속을 끊어 긴 계정 ID가 줄바꿈된다', () => {
    const css = readFileSync('src/styles.css', 'utf8')
    const panel = css.match(/\.account-menu-panel\{[^}]*\}/)[0]
    expect(panel).toContain('white-space:normal')
    expect(css).toMatch(/\.account-menu-info dd\{[^}]*overflow-wrap:anywhere/)
  })
})
