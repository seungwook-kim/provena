import { describe, expect, it } from 'vitest'
import { chatProxyBypass } from '../vite.config'

describe('Vite /chat proxy', () => {
  it('serves the SPA entry for browser refreshes', () => {
    expect(chatProxyBypass({ method: 'GET' })).toBe('/index.html')
  })

  it('keeps POST /chat on the API proxy for chat and SSE requests', () => {
    expect(chatProxyBypass({ method: 'POST' })).toBeUndefined()
  })
})
