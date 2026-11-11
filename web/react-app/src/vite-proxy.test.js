import { describe, expect, it } from 'vitest'
import { chatProxyBypass, pageOrApiProxyBypass } from '../vite.config'

describe('Vite /chat proxy', () => {
  it('serves the SPA entry for browser refreshes', () => {
    expect(chatProxyBypass({ method: 'GET' })).toBe('/index.html')
  })

  it('keeps POST /chat on the API proxy for chat and SSE requests', () => {
    expect(chatProxyBypass({ method: 'POST' })).toBeUndefined()
  })
})

describe('Vite /recalls and /changes proxy', () => {
  it('serves the SPA entry for browser page loads', () => {
    expect(pageOrApiProxyBypass({ method: 'GET', headers: { accept: 'text/html,application/xhtml+xml' } })).toBe('/index.html')
  })

  it('keeps fetch() GET and mutations on the API proxy', () => {
    expect(pageOrApiProxyBypass({ method: 'GET', headers: { accept: '*/*' } })).toBeUndefined()
    expect(pageOrApiProxyBypass({ method: 'POST', headers: { accept: 'text/html' } })).toBeUndefined()
    expect(pageOrApiProxyBypass({ method: 'GET', headers: {} })).toBeUndefined()
  })
})

describe('Vite /admin and /approvals proxy (H-20)', () => {
  it('lets browser page loads of /admin/users and /approvals reach the SPA', async () => {
    const { default: config } = await import('../vite.config')
    const proxy = config.server.proxy
    for (const path of ['/admin', '/approvals']) {
      expect(typeof proxy[path].bypass).toBe('function')
      expect(proxy[path].bypass({ method: 'GET', headers: { accept: 'text/html' } })).toBe('/index.html')
      expect(proxy[path].bypass({ method: 'GET', headers: { accept: '*/*' } })).toBeUndefined()
    }
  })
})
