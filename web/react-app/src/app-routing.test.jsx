import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import App from './App'

const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('chat route adapter selection', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/chat')
    vi.stubGlobal('fetch', vi.fn(async path => {
      if (path === '/me') return json(user)
      if (path === '/threads') return json([])
      return json({ detail: 'not found' }, 404)
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses the API chat route for an authenticated user', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: '정책에 대해 물어보세요.' })
    expect(fetch).toHaveBeenCalledWith('/threads', expect.anything())
    expect(window.location.pathname).toBe('/chat')
  })

  it('keeps the preview adapter on the demo route without a session request', async () => {
    window.history.replaceState({}, '', '/demo/chat')
    render(<App />)
    await screen.findByRole('heading', { name: '정책에 대해 물어보세요.' })
    expect(fetch).not.toHaveBeenCalledWith('/threads', expect.anything())
    expect(window.location.pathname).toBe('/demo/chat')
  })
})
