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
  const { suppressUnauthorized = false, ...requestOptions } = options
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...requestOptions,
    headers: {
      ...(requestOptions.body ? { 'Content-Type': 'application/json' } : {}),
      ...requestOptions.headers,
    },
  })

  if (!response.ok) {
    if (requestEpoch === authEpoch && response.status === 401 && !suppressUnauthorized && !['/me', '/auth/login', '/auth/logout'].includes(path)) {
      for (const listener of unauthorizedListeners) listener()
    }
    let detail = response.status === 401 ? '로그인이 필요합니다.' : response.status === 403 ? '이 작업을 수행할 권한이 없습니다.' : response.status >= 500 ? '서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' : '요청을 처리할 수 없습니다.'
    try {
      var errorCode
      const body = await response.json()
      if (typeof body.error?.message === 'string' && body.error.message.length < 160) detail = body.error.message
      else if (response.status < 500 && typeof body.detail === 'string' && body.detail.length < 160) detail = body.detail
      // 결정표·승인 API는 detail을 {reason, message}로 낸다 (backend/graph/decision/routes.py `_http`).
      else if (response.status < 500 && typeof body.detail?.message === 'string' && body.detail.message.length < 160) detail = body.detail.message
      if (typeof body.error?.code === 'string' && body.error.code) errorCode = body.error.code
      else if (typeof body.detail?.reason === 'string' && body.detail.reason) errorCode = body.detail.reason
    } catch {
      // HTML 등 JSON이 아닌 오류 응답은 내부 내용을 사용자에게 노출하지 않습니다.
    }
    throw new ApiError(detail, response.status, errorCode ?? (response.status === 401 ? 'unauthorized' : response.status === 403 ? 'forbidden' : 'request_failed'))
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
  return apiJson(`/recalls/${encodeURIComponent(recallId)}/ack`, { method: 'POST', headers: await csrfHeaders() })
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
export function getThreads() { return apiJson('/threads', { suppressUnauthorized: true }) }
export function getThread(threadId) { return apiJson(`/threads/${encodeURIComponent(threadId)}`) }
export function getMemory() { return apiJson('/me/memory', { suppressUnauthorized: true }) }
async function csrfHeaders() {
  await apiRequest('/auth/csrf')
  const token = readCsrfToken()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return { 'X-CSRF-Token': decodeURIComponent(token) }
}

export async function patchMemory(value) { return apiJson('/me/memory', { method: 'PATCH', suppressUnauthorized: true, headers: await csrfHeaders(), body: JSON.stringify(value) }) }
export async function deleteMemory() { return apiRequest('/me/memory', { method: 'DELETE', suppressUnauthorized: true, headers: await csrfHeaders() }) }
export function getRecalls({ suppressUnauthorized = false } = {}) { return apiJson('/recalls', { suppressUnauthorized }) }
export function getRecall(noticeId) { return apiJson(`/recalls/${encodeURIComponent(noticeId)}`) }
export function getRecallDigests() { return apiJson('/recalls/digests', { suppressUnauthorized: true }) }
export async function reviewRecall(noticeId, action) {
  return apiRequest(`/recalls/${encodeURIComponent(noticeId)}/review`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ action }) })
}
export async function sendRecallFeedback(noticeId, useful, reason = null) {
  return apiJson(`/recalls/${encodeURIComponent(noticeId)}/feedback`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ useful, reason }) })
}
export function getApprovals() { return apiJson('/approvals') }
export function getDecisionTables() { return apiJson('/decision-tables') }
export function getMaintenanceCandidates() { return apiJson('/maintenance-candidates') }
export async function decideMaintenanceCandidate(candidateId, status) {
  return apiJson(`/maintenance-candidates/${encodeURIComponent(candidateId)}`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ status }) })
}
export async function postImpactPreview(payload) {
  return apiJson('/impact-preview', { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify(payload) })
}
export function getChanges({ since, limit, offset } = {}) {
  const params = new URLSearchParams()
  if (since) params.set('since', since)
  if (limit != null) params.set('limit', String(limit))
  if (offset != null) params.set('offset', String(offset))
  const query = params.toString()
  return apiJson(`/changes${query ? `?${query}` : ''}`)
}
export function getChangeDetail(eventId) { return apiJson(`/changes/${encodeURIComponent(eventId)}`) }
export function getChangeMonitoring() { return apiJson('/changes/monitoring') }
export async function putChangeMonitoring(status) {
  return apiJson('/changes/monitoring', { method: 'PUT', headers: await csrfHeaders(), body: JSON.stringify({ status }) })
}

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

export async function streamChatMessage(threadId, message, { signal, onEvent } = {}) {
  const payload = { message }
  if (threadId !== null) payload.thread_id = threadId
  const response = await apiRequest('/chat', { method: 'POST', signal, headers: await csrfHeaders(), body: JSON.stringify(payload) })
  if (!(response.headers.get('content-type') ?? '').toLowerCase().includes('text/event-stream')) throw new ApiError('채팅 서버가 스트리밍 응답을 반환하지 않았습니다.', response.status, 'invalid_stream')
  if (!response.body) throw new ApiError('채팅 스트림을 읽을 수 없습니다.', response.status, 'stream_unavailable')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const emit = block => {
    const lines = block.split(/\r?\n/)
    const eventName = lines.find(line => line.startsWith('event:'))?.slice(6).trimStart() ?? ''
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
    const callback = onEvent
    onEvent = payload => callback?.(eventName && payload && typeof payload === 'object' && !Array.isArray(payload) && !payload.type ? { ...payload, type: eventName } : payload)
    if (!data || data === '[DONE]') return
    try { onEvent?.(JSON.parse(data)) } catch { throw new ApiError('채팅 스트림 이벤트 형식이 올바르지 않습니다.', response.status, 'invalid_event') }
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() ?? ''
      blocks.forEach(emit)
      if (done) break
    }
    if (buffer.trim()) emit(buffer)
  } finally { reader.releaseLock() }
}
