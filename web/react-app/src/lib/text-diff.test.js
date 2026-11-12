import { describe, expect, it } from 'vitest'
import { changedSpan, MAX_DIFF_CHARS } from './text-diff'

describe('changedSpan', () => {
  it('returns the inserted words of the new text', () => {
    expect(changedSpan('구매 승인 절차를 진행합니다.', '구매 승인 전에 보안 검토를 완료해야 합니다.')).toBe('전에 보안 검토를 완료해야')
    expect(changedSpan('담당자에게 사고 상황을 전달합니다.', '사고 상황을 공유하고 책임자를 지정한 뒤 담당자에게 전달합니다.')).toBeTruthy()
  })
  it('snaps to word boundaries and keeps a single contiguous span', () => {
    expect(changedSpan('a b c d', 'a b X c d')).toBe('X')
    expect(changedSpan('hello world', 'hello brave world')).toBe('brave')
  })
  it('returns null when nothing is comparable', () => {
    expect(changedSpan('same', 'same')).toBeNull()
    expect(changedSpan(null, 'x')).toBeNull()
    expect(changedSpan('abc', 'xyz')).toBeNull()
    expect(changedSpan('a b c', 'a c')).toBeNull()
  })
  it('falls back to null above the size cap', () => {
    const big = 'word '.repeat(MAX_DIFF_CHARS)
    expect(changedSpan(big, `${big}extra`)).toBeNull()
  })
})
