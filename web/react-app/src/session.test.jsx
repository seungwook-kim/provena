import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { apiRequest } from './lib/api'

const A = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user' }
const B = { user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role: 'admin' }
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
let server
let calls

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  document.cookie = 'provena_csrf=; Max-Age=0; path=/'
  window.history.replaceState({}, '', '/chat')
  calls = []
  server = { user: null, logoutStatus: 204, csrfStatus: 204, meStatus: 200, meHook: null }
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    calls.push({ path, options })
    if (path === '/me') {
      if (server.meHook) return server.meHook()
      if (server.meStatus !== 200) return json({ detail: 'unavailable' }, server.meStatus)
      return server.user ? json(server.user) : json({ detail: '인증이 필요합니다.' }, 401)
    }
    if (path === '/auth/csrf') {
      if (server.csrfStatus !== 204) return json({}, server.csrfStatus)
      document.cookie = 'provena_csrf=fresh-csrf; path=/'
      return new Response(null, { status: 204 })
    }
    if (path === '/auth/login') {
      const body = JSON.parse(options.body)
      if (body.password !== 'test-password') return json({ detail: '로그인 정보가 올바르지 않습니다.' }, 401)
      server.user = body.login_id === 'B' ? B : A
      return json(server.user)
    }
    if (path === '/auth/logout') {
      if (server.logoutStatus !== 204) return json({}, server.logoutStatus)
      server.user = null
      return new Response(null, { status: 204 })
    }
    return json({ detail: '인증이 필요합니다.' }, 401)
  }))
})

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

async function authenticated(user = A, path = '/chat') {
  server.user = user
  window.history.replaceState({}, '', path)
  const view = render(<App />)
  await screen.findByRole('button', { name: '내 계정' })
  return view
}

async function signIn(id = 'A', password = 'test-password') {
  if (window.location.pathname !== '/login') {
    window.history.pushState({}, '', '/login')
    window.dispatchEvent(new PopStateEvent('popstate'))
  }
  await userEvent.type(await screen.findByLabelText('아이디'), id)
  await userEvent.type(screen.getByLabelText('비밀번호'), password)
  await userEvent.click(screen.getByRole('button', { name: '로그인 →' }))
}

async function openMemorySettings() {
  window.history.pushState({}, '', '/onboarding')
  window.dispatchEvent(new PopStateEvent('popstate'))
  await screen.findByRole('heading', { name: '어느 팀에서 일하시나요?' })
  await screen.findByRole('button', { name: '보안' })
}

async function saveMemorySettings(team = '보안') {
  await openMemorySettings()
  await userEvent.click(screen.getByRole('button', { name: team }))
  await userEvent.click(screen.getByRole('button', { name: '다음' }))
  await userEvent.click(screen.getByRole('button', { name: '개발자' }))
  await userEvent.click(screen.getByRole('button', { name: '다음' }))
  await userEvent.click(screen.getByRole('button', { name: '다음' }))
  await userEvent.click(screen.getByRole('button', { name: '저장하고 채팅 시작' }))
  await screen.findByRole('button', { name: '내 계정' })
}

describe('React authentication and session isolation', () => {
  it('enters the protected UI without calling /me when mock session is enabled', async () => {
    vi.stubEnv('VITE_ENABLE_MOCK_SESSION', 'true')
    window.history.replaceState({}, '', '/admin')
    render(<App />)
    await screen.findByRole('navigation', { name: '관리자 메뉴' })
    expect(window.location.pathname).toBe('/admin')
    expect(calls.some(call => call.path === '/me')).toBe(false)
  })

  it('opens the development demo chat without authentication', async () => {
    window.history.replaceState({}, '', '/demo/chat')
    render(<App />)
    await screen.findByRole('heading', { name: '정책에 대해 물어보세요.' })
    expect(window.location.pathname).toBe('/demo/chat')
    expect(screen.queryByLabelText('아이디')).toBeNull()
  })

  it('redirects the legacy demo query to the unprotected demo route in development', async () => {
    window.history.replaceState({}, '', '/chat?demo=1')
    render(<App />)
    await screen.findByRole('heading', { name: '정책에 대해 물어보세요.' })
    expect(window.location.pathname).toBe('/demo/chat')
    expect(screen.queryByLabelText('아이디')).toBeNull()
  })

  it.each(['/chat', '/recalls', '/approvals', '/admin'])('rejects anonymous direct URL %s before rendering protected UI', async path => {
    window.history.replaceState({}, '', path)
    render(<App />)
    expect(screen.queryByRole('button', { name: '내 계정' })).toBeNull()
    await screen.findByLabelText('아이디')
    expect(window.location.pathname).toBe('/login')
  })

  it('keeps protected UI hidden while the first /me is pending', async () => {
    let resolve
    const pending = new Promise(done => { resolve = done })
    server.meHook = () => pending
    render(<App />)
    expect(screen.getByRole('status').textContent).toContain('세션')
    expect(screen.queryByRole('button', { name: '로그아웃' })).toBeNull()
    await act(async () => { resolve(json(A)) })
    await screen.findByRole('button', { name: '내 계정' })
  })

  it('uses login_id, cookies and CSRF and shares confirmed /me state after login', async () => {
    render(<App />)
    await signIn()
    await screen.findByRole('button', { name: '내 계정' })
    const request = calls.find(call => call.path === '/auth/login')
    expect(JSON.parse(request.options.body)).toEqual({ login_id: 'A', password: 'test-password' })
    expect(request.options.credentials).toBe('include')
    expect(request.options.headers['X-CSRF-Token']).toBe('fresh-csrf')
    await userEvent.click(screen.getByRole('button', { name: '내 계정' }))
    expect(screen.getByText(A.user_id)).toBeTruthy()
    expect(calls.some(call => call.path === '/me')).toBe(true)
  })

  it('shows login failure and never enters a protected screen', async () => {
    render(<App />)
    await signIn('A', 'wrong-password')
    expect((await screen.findByRole('alert')).textContent).toContain('올바르지')
    expect(screen.queryByRole('button', { name: '내 계정' })).toBeNull()
  })

  it('links the Google login control to the server-side OAuth start route', async () => {
    window.history.replaceState({}, '', '/login')
    render(<App />)
    const googleLogin = await screen.findByRole('link', { name: /Google/ })
    expect(googleLogin.getAttribute('href')).toBe('/auth/google/start')
  })

  it('routes a confirmed OAuth-return session from the callback root to chat', async () => {
    server.user = A
    window.history.replaceState({}, '', '/')
    render(<App />)
    await screen.findByRole('button', { name: '내 계정' })
    expect(window.location.pathname).toBe('/chat')
    const meRequest = calls.find(call => call.path === '/me')
    expect(meRequest).toBeTruthy()
    expect(meRequest.options.credentials).toBe('include')
  })

  it('restores a valid session and its own temporary memory on remount (refresh)', async () => {
    let view = await authenticated()
    await saveMemorySettings('보안')
    view.unmount()
    view = render(<App />)
    await screen.findByRole('button', { name: '내 계정' })
    await openMemorySettings()
    expect(screen.getByRole('button', { name: '보안' }).className).toContain('selected')
    expect(localStorage.getItem('provena-memory')).toBeNull()
    view.unmount()
  })

  it('does not expose admin menus to a normal user even in development', async () => {
    await authenticated()
    expect(screen.queryByRole('navigation', { name: '관리자 메뉴' })).toBeNull()
  })

  it.each(['/admin', '/approvals'])('denies normal-user direct access to %s', async path => {
    server.user = A
    window.history.replaceState({}, '', path)
    render(<App />)
    expect((await screen.findByRole('alert')).textContent).toContain('접근 권한')
    expect(screen.queryByRole('navigation', { name: '관리자 메뉴' })).toBeNull()
  })

  it('shows admin menus using the server role', async () => {
    await authenticated(B)
    expect(screen.getByRole('navigation', { name: '관리자 메뉴' })).toBeTruthy()
    await userEvent.click(screen.getByRole('link', { name: '운영 현황' }))
    await screen.findByRole('navigation', { name: '관리자 메뉴' })
    expect(window.location.pathname).toBe('/admin')
  })

  it('expires the session on a protected API 401 and removes temporary notes', async () => {
    await authenticated()
    sessionStorage.setItem(`provena-memory:${A.user_id}`, 'private A')
    await act(async () => { await apiRequest('/protected-test').catch(() => {}) })
    await screen.findByLabelText('아이디')
    expect(sessionStorage.getItem(`provena-memory:${A.user_id}`)).toBeNull()
  })

  it('rechecks on focus and removes an expired session', async () => {
    await authenticated()
    server.user = null
    act(() => window.dispatchEvent(new Event('focus')))
    await screen.findByLabelText('아이디')
  })

  it('offers retry on /me server failure instead of pretending the user logged out', async () => {
    server.meStatus = 503
    render(<App />)
    expect((await screen.findByRole('alert')).textContent).toContain('세션')
    expect(screen.queryByLabelText('아이디')).toBeNull()
    server.meStatus = 200
    server.user = A
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await screen.findByRole('button', { name: '내 계정' })
  })

  it('offers retry after a network error while checking the session', async () => {
    server.meHook = () => Promise.reject(new TypeError('offline'))
    render(<App />)
    await screen.findByRole('button', { name: '다시 시도' })
    expect(screen.queryByLabelText('아이디')).toBeNull()
    server.meHook = null
    server.user = A
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await screen.findByRole('button', { name: '내 계정' })
  })

  it.each([{ user_id: 'not-a-uuid', role: 'user' }, { ...A, role: 'superuser' }])('rejects invalid /me contract %j', async user => {
    server.user = user
    render(<App />)
    await screen.findByRole('button', { name: '다시 시도' })
    expect(screen.queryByRole('button', { name: '내 계정' })).toBeNull()
  })

  it('does not trust a login response when the confirming /me fails', async () => {
    render(<App />)
    await screen.findByLabelText('아이디')
    server.meStatus = 503
    await signIn()
    await screen.findByRole('alert')
    expect(screen.queryByRole('button', { name: '내 계정' })).toBeNull()
  })

  it('confirms server 204 logout using a fresh CSRF and clears only app-owned state', async () => {
    await authenticated()
    sessionStorage.setItem(`provena-memory:${A.user_id}`, 'A memory')
    sessionStorage.setItem('unrelated', 'keep')
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    expect(window.location.pathname).toBe('/')
    await screen.findByRole('link', { name: '로그인' })
    const request = calls.find(call => call.path === '/auth/logout')
    expect(request.options.headers['X-CSRF-Token']).toBe('fresh-csrf')
    expect(sessionStorage.getItem(`provena-memory:${A.user_id}`)).toBeNull()
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
  })

  it.each([403, 500, 200])('does not claim logout success for HTTP %s; allows retry', async status => {
    await authenticated()
    server.logoutStatus = status
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    expect((await screen.findByRole('alert')).textContent).toContain('종료를 확인')
    expect(screen.getByRole('button', { name: '내 계정' })).toBeTruthy()
    expect(window.location.pathname).toBe('/chat')
    server.logoutStatus = 204
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    await screen.findByRole('link', { name: '로그인' })
    expect(window.location.pathname).toBe('/')
  })

  it('does not submit logout if CSRF acquisition fails', async () => {
    await authenticated()
    server.csrfStatus = 503
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    await screen.findByRole('alert')
    expect(calls.some(call => call.path === '/auth/logout')).toBe(false)
  })

  it('isolates A/B accounts and discards the legacy shared memory', async () => {
    localStorage.setItem('provena-memory', JSON.stringify({ team: 'legacy A' }))
    await authenticated()
    await saveMemorySettings('보안')
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    await signIn('B')
    await screen.findByRole('navigation', { name: '관리자 메뉴' })
    await openMemorySettings()
    expect(screen.getByRole('button', { name: '보안' }).className).not.toContain('selected')
    expect(sessionStorage.getItem(`provena-memory:${A.user_id}`)).toBeNull()
  })

  it('switches to the user confirmed after focus and ignores a slower, older /me response', async () => {
    await authenticated()
    sessionStorage.setItem(`provena-memory:${A.user_id}`, JSON.stringify({ team: 'A-only' }))
    let resolveOld
    server.meHook = () => new Promise(done => { resolveOld = done })
    act(() => window.dispatchEvent(new Event('focus')))
    server.meHook = () => Promise.resolve(json(B))
    act(() => window.dispatchEvent(new Event('focus')))
    await screen.findByRole('navigation', { name: '관리자 메뉴' })
    await act(async () => { resolveOld(json(A)) })
    expect(screen.getByRole('navigation', { name: '관리자 메뉴' })).toBeTruthy()
    expect(sessionStorage.getItem(`provena-memory:${A.user_id}`)).toBeNull()
  })

  it('does not let a previous user request expire a newer user session', async () => {
    await authenticated()
    let resolveOld
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', (path, options) => path === '/slow-protected'
      ? new Promise(done => { resolveOld = done }) : originalFetch(path, options))
    const pending = apiRequest('/slow-protected').catch(() => {})
    server.user = B
    act(() => window.dispatchEvent(new Event('focus')))
    await screen.findByRole('navigation', { name: '관리자 메뉴' })
    await act(async () => { resolveOld(json({}, 401)); await pending })
    expect(screen.getByRole('navigation', { name: '관리자 메뉴' })).toBeTruthy()
  })

  it('forgets A notes even when A logs in again after a B session', async () => {
    await authenticated()
    sessionStorage.setItem(`provena-memory:${A.user_id}`, JSON.stringify({ team: 'old A' }))
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    await signIn('B')
    await screen.findByRole('button', { name: '로그아웃' })
    await userEvent.click(screen.getByRole('button', { name: '로그아웃' }))
    await signIn('A')
    await screen.findByRole('button', { name: '내 계정' })
    await openMemorySettings()
    expect(screen.getByRole('button', { name: '보안' }).className).not.toContain('selected')
  })

  it('works with StrictMode bootstrap cleanup', async () => {
    server.user = A
    render(<StrictMode><App /></StrictMode>)
    await screen.findByRole('button', { name: '내 계정' })
  })

  it('preserves the signup route and its API-unavailable behavior', async () => {
    window.history.replaceState({}, '', '/signup')
    render(<App />)
    await screen.findByRole('heading', { name: '회원가입' })
    expect(screen.getByRole('link', { name: '로그인으로 돌아가기' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Google로 계속하기' }).getAttribute('href')).toBe('/auth/google/start')
  })
})
