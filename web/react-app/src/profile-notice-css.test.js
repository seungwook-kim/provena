import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

// 내 정보 선택 단계 안내가 위 버튼 묶음에 겹치던 것(2026-11-13 화면 점검)
describe('내 정보 선택 단계 안내 위치 (CSS)', () => {
  const css = readFileSync('src/profile.css', 'utf8')

  it('버튼 묶음 바로 밑의 안내는 위로 끌어올리지 않고 12px 띄운다', () => {
    expect(css).toMatch(/\.profile-choice-grid \+ \.profile-storage-notice \{ margin-top: 12px; \}/)
    expect(css.indexOf('.profile-choice-grid + .profile-storage-notice')).toBeGreaterThan(css.indexOf('.profile-storage-notice { margin: -4px'))
  })
})
