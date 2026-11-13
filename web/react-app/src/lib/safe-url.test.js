import { describe, expect, it } from 'vitest'
import { safeHttpUrl } from './safe-url'

describe('safeHttpUrl', () => {
  it('keeps http and https addresses', () => {
    expect(safeHttpUrl('https://handbook.gitlab.com/x')).toBe('https://handbook.gitlab.com/x')
    expect(safeHttpUrl('http://example.com/a?b=1')).toBe('http://example.com/a?b=1')
  })

  it('drops other schemes, relative text and non-strings', () => {
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(safeHttpUrl('data:text/html,x')).toBeNull()
    expect(safeHttpUrl('/relative/path')).toBeNull()
    expect(safeHttpUrl('not a url')).toBeNull()
    expect(safeHttpUrl('https:example.com')).toBeNull()
    expect(safeHttpUrl('http:/example.com')).toBeNull()
    expect(safeHttpUrl('')).toBeNull()
    expect(safeHttpUrl(null)).toBeNull()
    expect(safeHttpUrl(42)).toBeNull()
  })
})
