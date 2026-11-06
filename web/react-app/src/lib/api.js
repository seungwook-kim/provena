const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const unauthorizedListeners = new Set()
let authEpoch = 0

export function invalidateAuthRequests() { authEpoch += 1 }

export function subscribeUnauthorized(listener) {
  unauthorizedListeners.add(listener)
  return () => unauthorizedListeners.delete(listener)
}

export class ApiError extends Error {
  constructor(message, status = 0, code = 'unknown') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function apiRequest(path, options = {}) {
  const requestEpoch = authEpoch
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  })

  if (!response.ok) {
    if (requestEpoch === authEpoch && response.status === 401 && !['/me', '/auth/login', '/auth/logout'].includes(path)) {
      for (const listener of unauthorizedListeners) listener()
    }
    let detail = response.status === 401 ? '로그인이 필요합니다.' : response.status === 403 ? '이 작업을 수행할 권한이 없습니다.' : response.status >= 500 ? '서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' : '요청을 처리할 수 없습니다.'
    try {
      const body = await response.json()
      if (response.status < 500 && typeof body.detail === 'string' && body.detail.length < 160) detail = body.detail
    } catch {
      // HTML 등 JSON이 아닌 오류 응답은 내부 내용을 사용자에게 노출하지 않습니다.
    }
    throw new ApiError(detail, response.status, response.status === 401 ? 'unauthorized' : response.status === 403 ? 'forbidden' : 'request_failed')
  }

  return response
}

export async function apiJson(path, options = {}) {
  const response = await apiRequest(path, options)
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', response.status, 'invalid_response')
  }
  return response.json()
}

export async function login(loginId, password) {
  await apiRequest('/auth/csrf')
  const csrfToken = document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith('provena_csrf='))
    ?.split('=')[1]

  if (!csrfToken) throw new Error('CSRF 토큰을 받을 수 없습니다.')

  return apiJson('/auth/login', {
    method: 'POST',
    headers: { 'X-CSRF-Token': decodeURIComponent(csrfToken) },
    body: JSON.stringify({ login_id: loginId, password }),
  })
}

export async function acknowledgeRecall(recallId) {
  await apiRequest(`/recalls/${recallId}/ack`, { method: 'POST' })
}

export async function logout() {
  await apiRequest('/auth/csrf')
  const csrfToken = document.cookie.split('; ').find((cookie) => cookie.startsWith('provena_csrf='))?.split('=')[1]
  if (!csrfToken) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 로그아웃을 다시 시도해 주세요.')
  const response = await apiRequest('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': decodeURIComponent(csrfToken) } })
  if (response.status !== 204) throw new ApiError('로그아웃 완료를 확인하지 못했습니다. 다시 시도해 주세요.')
  return response
}

export function getCurrentUser() { return apiJson('/me') }

function readCsrfToken() {
  return document.cookie.split('; ').find(cookie => cookie.startsWith('provena_csrf='))?.split('=')[1]
}

export function getProfileForEdit() { return apiJson('/me/profile?view=edit') }

export async function saveProfile(profile) {
  await apiRequest('/auth/csrf')
  const token = readCsrfToken()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return apiJson('/me/profile', {
    method: 'PUT',
    headers: { 'X-CSRF-Token': decodeURIComponent(token) },
    body: JSON.stringify(profile),
  })
}

export function listAdminUsers() { return apiJson('/admin/users') }

export async function changeAdminRole(loginId, action) {
  await apiRequest('/auth/csrf')
  const token = readCsrfToken()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return apiJson(`/admin/users/${encodeURIComponent(loginId)}/${action}`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': decodeURIComponent(token) },
  })
}
export function getThreads() { return apiJson('/threads') }
export function getRecalls() { return apiJson('/recalls') }
export function getApprovals() { return apiJson('/approvals') }
export function getDecisionTables() { return apiJson('/decision-tables') }
export function getMaintenanceCandidates() { return apiJson('/maintenance-candidates') }

export async function submitApproval(approvalId, approve, comment = '') {
  await apiRequest(`/approvals/${approvalId}`, {
    method: 'POST',
    body: JSON.stringify({ approval_id: approvalId, approve, comment }),
  })
}

export async function sendChatMessage(threadId, message) {
  return apiRequest('/chat', {
    method: 'POST',
    body: JSON.stringify({ thread_id: threadId, message }),
  })
}
