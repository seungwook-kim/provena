import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getCurrentUser, invalidateAuthRequests, login, logout, subscribeUnauthorized } from '../lib/api'
import { clearSessionMemory, selectMemoryOwner } from '../lib/session-memory'
import { SessionContext } from '../lib/session'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const MOCK_USER = { user_id: '00000000-0000-4000-8000-000000000001', role: 'admin', profile_completed: true }

function isMockSessionEnabled() {
  return import.meta.env.VITE_ENABLE_MOCK_SESSION === 'true'
}

function validateUser(user) {
  if (!UUID.test(user?.user_id ?? '') || !['user', 'admin'].includes(user?.role)) {
    throw new ApiError('사용자 정보를 확인할 수 없습니다. 다시 시도해 주세요.', 0, 'invalid_user')
  }
  return {
    user_id: user.user_id.toLowerCase(),
    role: user.role,
    ...(typeof user.profile_completed === 'boolean' ? { profile_completed: user.profile_completed } : {}),
    ...(typeof user.is_owner === 'boolean' ? { is_owner: user.is_owner } : {}),
  }
}

function sameUser(left, right) {
  return Boolean(left && right) && ['user_id', 'role', 'profile_completed', 'is_owner'].every(key => left[key] === right[key])
}

export function SessionProvider({ children }) {
  const [session, setSession] = useState({ status: 'checking', user: null, error: '' })
  const sequence = useRef(0)
  const mutating = useRef(false)
  const confirmedUser = useRef(null) // The user currently shown as authenticated, or null.

  const accept = useCallback(user => {
    invalidateAuthRequests()
    selectMemoryOwner(user.user_id)
    confirmedUser.current = user
    setSession({ status: 'authenticated', user, error: '' })
  }, [])

  const expire = useCallback(() => {
    invalidateAuthRequests()
    sequence.current += 1
    clearSessionMemory()
    confirmedUser.current = null
    setSession({ status: 'anonymous', user: null, error: '' })
  }, [])

  const refresh = useCallback(async () => {
    if (mutating.current) return
    const request = ++sequence.current
    // With a confirmed user this is a background re-check (focus, navigation, profile save):
    // keep the page mounted and only change state when the server says something different.
    const background = confirmedUser.current !== null
    const acceptChanged = user => { if (!sameUser(confirmedUser.current, user)) accept(user) }
    if (isMockSessionEnabled()) {
      acceptChanged(MOCK_USER)
      return
    }
    if (!background) setSession({ status: 'checking', user: null, error: '' })
    try {
      const user = validateUser(await getCurrentUser())
      if (request === sequence.current) acceptChanged(user)
    } catch (error) {
      if (request !== sequence.current) return
      if (error.status === 401) expire()
      else if (!background) setSession({ status: 'error', user: null, error: '세션을 확인하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.' })
      // A failed background check (offline, 5xx, bad payload) keeps the confirmed session; the next focus retries.
    }
  }, [accept, expire])

  useEffect(() => {
    const unsubscribe = subscribeUnauthorized(() => { if (!mutating.current) expire() })
    let active = true
    queueMicrotask(() => { if (active) refresh() })
    const onFocus = () => refresh()
    window.addEventListener('focus', onFocus)
    return () => {
      active = false
      sequence.current += 1
      unsubscribe()
      window.removeEventListener('focus', onFocus)
    }
  }, [refresh, expire])

  async function signIn(loginId, password) {
    if (mutating.current) return
    mutating.current = true
    const request = ++sequence.current
    try {
      if (isMockSessionEnabled()) {
        if (request === sequence.current) accept(MOCK_USER)
        return MOCK_USER
      }
      await login(loginId, password)
      const user = validateUser(await getCurrentUser())
      if (request === sequence.current) accept(user)
      return user
    } finally { mutating.current = false }
  }

  async function signOut() {
    if (mutating.current) return
    mutating.current = true
    sequence.current += 1
    try {
      if (isMockSessionEnabled()) {
        expire()
        return
      }
      await logout()
      expire() // Do not clear a valid session or pretend success when the server failed.
    } finally { mutating.current = false }
  }

  return <SessionContext.Provider value={{ ...session, refresh, signIn, signOut }}>{children}</SessionContext.Provider>
}

