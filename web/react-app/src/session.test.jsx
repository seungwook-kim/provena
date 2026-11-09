import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
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
  server = { user: null, profile: null, savedProfile: null, memory: {}, logoutStatus: 204, csrfStatus: 204, meStatus: 200, meHook: null }
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
    if (path === '/me/memory' && options?.method === 'PATCH') {
      const memoryOwner = server.user?.user_id ?? 'anonymous'
      server.memory[memoryOwner] = JSON.parse(options.body)
      return json({ profile: server.memory[memoryOwner] })
    }
    if (path === '/me/memory' && options?.method === 'DELETE') {
      const memoryOwner = server.user?.user_id ?? 'anonymous'
      delete server.memory[memoryOwner]
      return new Response(null, { status: 204 })
    }
    if (path === '/me/memory') {
      return json({ profile: server.memory[server.user?.user_id ?? 'anonymous'] ?? {} })
    }
    if (path === '/auth/logout') {
      if (server.logoutStatus !== 204) return json({}, server.logoutStatus)
      server.user = null
      return new Response(null, { status: 204 })
    }
    if (path === '/me/profile?view=edit') return server.profile ? json(server.profile) : json({ detail: '내 정보가 아직 없습니다.' }, 404)
    if (path === '/me/profile' && options?.method === 'PUT') {
      server.savedProfile = JSON.parse(options.body)
      if (server.user) server.user = { ...server.user, profile_completed: true }
      return json({ name: server.savedProfile.name, dept: server.savedProfile.dept, phone_masked: '010-****-5678', address: server.savedProfile.address })
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

  it('does not let the legacy demo query bypass the protected chat route', async () => {
    window.history.replaceState({}, '', '/chat?demo=1')
    render(<App />)
    await screen.findByRole('heading', { name: '로그인' })
    expect(window.location.pathname).toBe('/login')
    expect(screen.getByLabelText('아이디')).toBeTruthy()
  })

  it.each(['/chat', '/recalls', '/approvals', '/admin'])('rejects anonymous direct URL %s before rendering protected UI', async path => {
    window.history.replaceState({}, '', path)
    render(<App />)
    expect(screen.queryByRole('button', { name: '내 계정' })).toBeNull()
    await screen.findByLabelText('아이디')
    expect(window.location.pathname).toBe('/login')
  })

  it('forces an incomplete user from every protected URL into the first registration step', async () => {
    server.user = { ...A, profile_completed: false }
    window.history.replaceState({}, '', '/admin')
    render(<App />)
    await screen.findByRole('heading', { name: '어느 팀에서 일하시나요?' })
    expect(window.location.pathname).toBe('/myinfo')
    expect(screen.queryByRole('navigation', { name: '관리자 메뉴' })).toBeNull()
  })

  it('shows all six fields on the completed-user profile edit screen and saves only the profile API fields', async () => {
    server.user = { ...A, profile_completed: true }
    server.profile = { name: '홍길동', dept: '개발', phone: '010-1234-5678', address: '' }
    window.history.replaceState({}, '', '/myinfo')
    render(<App />)
    await screen.findByRole('heading', { name: '회원정보 수정' })
    expect(await screen.findByLabelText('소속 팀 *')).toBeTruthy()
    await userEvent.selectOptions(screen.getByLabelText('업무 역할 * (저장 연동 준비 중)'), '개발자')
    const service = screen.getByLabelText('담당 서비스 * (저장 연동 준비 중)')
    await userEvent.type(service, '결제 API')
    expect(screen.getByLabelText('이름 *')).toBeTruthy()
    const phone = screen.getByLabelText('전화번호 *')
    expect(phone.getAttribute('placeholder')).toBe('예시) 010-1234-5678')
    const address = screen.getByLabelText('근무지 주소 (선택)')
    expect(address.className).toBe('profile-address-field')
    await userEvent.clear(service)
    expect(screen.getByRole('button', { name: '변경사항 저장' }).disabled).toBe(true)
    await userEvent.type(service, '결제 API')
    await userEvent.clear(phone)
    await userEvent.type(phone, '01098765432')
    await userEvent.click(screen.getByRole('button', { name: '변경사항 저장' }))
    expect(server.savedProfile).toEqual({ name: '홍길동', dept: '개발', phone: '010-9876-5432', address: '' })
  })

  it('keeps all five registration steps and saves the profile before entering chat', async () => {
    server.user = { ...A, profile_completed: false }
    window.history.replaceState({}, '', '/myinfo')
    render(<App />)
    await screen.findByRole('heading', { name: '어느 팀에서 일하시나요?' })
    expect(screen.getByText('소속된 팀을 선택해 주세요.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '이전' })).toBeNull()
    await userEvent.click(await screen.findByRole('button', { name: '보안' }))
    await userEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(screen.getByRole('heading', { name: '어떤 역할을 맡고 계신가요?' })).toBeTruthy()
    expect(screen.getByText('주로 담당하는 업무 역할을 선택해 주세요.')).toBeTruthy()
    expect(screen.getByRole('button', { name: '이전' })).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '개발자' }))
    await userEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(screen.getByRole('heading', { name: '어떤 서비스를 담당하시나요?' })).toBeTruthy()
    expect(screen.getByText('담당하는 서비스를 등록해 주세요.')).toBeTruthy()
    await userEvent.type(await screen.findByLabelText('담당 서비스'), '결제 API')
    await userEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(screen.getByRole('heading', { name: '기본 정보를 입력해 주세요.' })).toBeTruthy()
    expect(screen.getByText('이름과 전화번호는 필수이며, 근무지 주소는 선택 사항입니다.')).toBeTruthy()
    const nameInput = screen.getByRole('textbox', { name: '이름' })
    const phoneInput = screen.getByRole('textbox', { name: '전화번호' })
    const addressInput = screen.getByRole('textbox', { name: '근무지 주소 (선택)' })
    expect(phoneInput.getAttribute('placeholder')).toBe('예시) 010-1234-5678')
    expect(addressInput.className).toBe('profile-address-field')
    expect(nameInput.closest('label').textContent).toContain('*')
    expect(addressInput.closest('label').textContent).toContain('(선택)')
    await userEvent.type(nameInput, '홍길동')
    await userEvent.type(phoneInput, '01112345678')
    expect(phoneInput.value).toBe('011-1234-5678')
    expect(screen.getByRole('button', { name: /다음/ }).disabled).toBe(true)
    await userEvent.clear(phoneInput)
    await userEvent.type(phoneInput, '0101234567')
    expect(screen.getByRole('button', { name: /다음/ }).disabled).toBe(true)
    await userEvent.clear(phoneInput)
    await userEvent.type(phoneInput, '01012345678999')
    expect(phoneInput.value).toBe('010-1234-5678')
    expect(screen.getByRole('button', { name: '다음' }).disabled).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(screen.getByRole('heading', { name: '입력한 정보를 확인해 주세요.' })).toBeTruthy()
    expect(screen.getByText('등록 정보를 확인한 후 완료 버튼을 눌러 주세요.')).toBeTruthy()
    expect(await screen.findByText('결제 API')).toBeTruthy()
    expect(screen.getByText('010-1234-5678')).toBeTruthy()
    expect(screen.getByText('설정하지 않음')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '등록 완료' }))
    expect(server.savedProfile).toEqual({ name: '홍길동', dept: '보안', phone: '010-1234-5678', address: '' })
    await screen.findByRole('button', { name: '내 계정' })
    expect(window.location.pathname).toBe('/chat')
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
    await screen.findByRole('button', { name: '내 계정' })
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

  describe('background re-check on window focus', () => {
    const meCalls = () => calls.filter(call => call.path === '/me').length
    const focus = () => act(() => window.dispatchEvent(new Event('focus')))

    async function chatWithDraft(user = A) {
      await authenticated(user)
      const composer = await screen.findByRole('textbox', { name: '질문' })
      await waitFor(() => expect(composer.disabled).toBe(false))
      await userEvent.type(composer, '작성 중인 질문')
      return composer
    }

    it('keeps the page mounted and shows no loading screen while /me is re-checked', async () => {
      const composer = await chatWithDraft()
      const before = meCalls()
      let resolve
      server.meHook = () => new Promise(done => { resolve = done })
      focus()
      await waitFor(() => expect(meCalls()).toBe(before + 1))
      expect(screen.queryByText('세션을 확인하고 있습니다.')).toBeNull()
      expect(screen.getByRole('textbox', { name: '질문' })).toBe(composer)
      await act(async () => { resolve(json(A)) })
      expect(screen.getByRole('textbox', { name: '질문' })).toBe(composer)
      expect(composer.value).toBe('작성 중인 질문')
    })

    it('logs out when the focus check returns 401', async () => {
      await chatWithDraft()
      sessionStorage.setItem(`provena-memory:${A.user_id}`, 'private A')
      server.user = null
      focus()
      await screen.findByLabelText('아이디')
      expect(sessionStorage.getItem(`provena-memory:${A.user_id}`)).toBeNull()
    })

    it.each([
      ['a network error', () => Promise.reject(new TypeError('offline'))],
      ['HTTP 503', () => Promise.resolve(json({ detail: 'unavailable' }, 503))],
    ])('stays logged in when the focus check fails with %s', async (_, meHook) => {
      const composer = await chatWithDraft()
      const before = meCalls()
      server.meHook = meHook
      focus()
      await waitFor(() => expect(meCalls()).toBe(before + 1))
      await act(async () => {})
      expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
      expect(screen.getByRole('button', { name: '내 계정' })).toBeTruthy()
      expect(screen.getByRole('textbox', { name: '질문' })).toBe(composer)
      expect(composer.value).toBe('작성 중인 질문')
    })

    it('applies a changed role from the focus check', async () => {
      await chatWithDraft()
      expect(screen.queryByRole('navigation', { name: '관리자 메뉴' })).toBeNull()
      server.user = { ...A, role: 'admin' }
      focus()
      await screen.findByRole('navigation', { name: '관리자 메뉴' })
    })
  })

  it('moves between protected pages without the session checking screen or a remount after /me', async () => {
    const baseFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async (path, options) => {
      if (String(path).startsWith('/recalls')) return json([])
      if (String(path).startsWith('/changes')) return json({ items: [] })
      return baseFetch(path, options)
    }))
    await authenticated(A, '/recalls')
    await screen.findByRole('heading', { name: '리콜 알림' })
    let sawChecking = false
    const observer = new MutationObserver(() => { if (document.body.textContent.includes('세션을 확인하고 있습니다.')) sawChecking = true })
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    try {
      let resolve
      server.meHook = () => new Promise(done => { resolve = done })
      const meBefore = calls.filter(call => call.path === '/me').length
      act(() => {
        window.history.pushState({}, '', '/changes')
        window.dispatchEvent(new PopStateEvent('popstate'))
      })
      const heading = await screen.findByRole('heading', { name: '정책 변경 감시' })
      await waitFor(() => expect(calls.filter(call => call.path === '/me').length).toBe(meBefore + 1))
      expect(screen.queryByText('세션을 확인하고 있습니다.')).toBeNull()
      await act(async () => { resolve(json(A)) })
      expect(screen.getByRole('heading', { name: '정책 변경 감시' })).toBe(heading)
      expect(screen.getByRole('button', { name: '내 계정' })).toBeTruthy()
      expect(sawChecking).toBe(false)
    } finally { observer.disconnect() }
  })

  it('preserves the signup route and its API-unavailable behavior', async () => {
    window.history.replaceState({}, '', '/signup')
    render(<App />)
    await screen.findByRole('heading', { name: '회원가입' })
    expect(screen.getByRole('link', { name: '로그인으로 돌아가기' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Google로 계속하기' }).getAttribute('href')).toBe('/auth/google/start')
  })
})
