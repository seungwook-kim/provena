const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const unauthorizedListeners = new Set()
let authEpoch = 0

export function invalidateAuthRequests() { authEpoch += 1 }

export function subscribeUnauthorized(listener) {
  unauthorizedListeners.add(listener)
  return () => unauthorizedListeners.delete(listener)
}

export class ApiError extends Error {
  constructor(message, status = 0, code = 'unknown', fields = undefined) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    // 422의 칸별 이유 {칸: 이유} (backend/profile_api.py). 없으면 undefined.
    if (fields) this.fields = fields
  }
}

// 변경 요청이 겹칠 때 /auth/csrf를 여러 번 받으면 쿠키가 바뀌어 먼저 읽은 토큰이 틀어진다(H-18).
// 진행 중인 토큰 요청은 하나로 합친다.
let csrfInFlight = null
function fetchCsrfCookie() {
  if (!csrfInFlight) {
    csrfInFlight = apiRequest('/auth/csrf').then(() => readCsrfToken()).finally(() => { csrfInFlight = null })
  }
  return csrfInFlight
}

export async function apiRequest(path, options = {}, csrfRetried = false) {
  const requestEpoch = authEpoch
  const { suppressUnauthorized = false, ...requestOptions } = options
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: 'include',
      // 화면 주소와 API 주소가 같은 곳(/admin/users, /recalls, /approvals)은 새로고침 때 받은 HTML이 브라우저 캐시에 남아
      // fetch가 그 HTML을 받으면 '서버 응답 형식이 올바르지 않습니다'가 된다 → API 요청은 캐시를 쓰지 않는다
      cache: 'no-store',
      ...requestOptions,
      headers: {
        ...(requestOptions.body ? { 'Content-Type': 'application/json' } : {}),
        ...requestOptions.headers,
      },
    })
  } catch (error) {
    // 서버가 꺼졌거나 네트워크가 끊기면 브라우저가 영어 "Failed to fetch"를 던진다 → 한국어 안내로 바꾼다. 취소(AbortError)는 그대로 둔다.
    if (error?.name === 'AbortError') throw error
    throw new ApiError('서버에 연결하지 못했습니다. 네트워크를 확인하고 잠시 후 다시 시도해 주세요.', 0, 'network_error')
  }

  if (!response.ok) {
    // 다른 요청이 쿠키를 바꿔 토큰이 어긋났으면(403 csrf_failed) 새 토큰으로 한 번만 다시 보낸다.
    if (response.status === 403 && !csrfRetried && requestOptions.headers?.['X-CSRF-Token']) {
      const code = await response.clone().json().then(body => body?.error?.code, () => undefined)
      if (code === 'csrf_failed') {
        const fresh = await fetchCsrfCookie()
        if (fresh) return apiRequest(path, { ...options, headers: { ...requestOptions.headers, 'X-CSRF-Token': decodeURIComponent(fresh) } }, true)
      }
    }
    if (requestEpoch === authEpoch && response.status === 401 && !suppressUnauthorized && !['/me', '/auth/login', '/auth/logout'].includes(path)) {
      for (const listener of unauthorizedListeners) listener()
    }
    let detail = response.status === 401 ? '로그인이 필요합니다.' : response.status === 403 ? '이 작업을 수행할 권한이 없습니다.' : response.status >= 500 ? '서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.' : '요청을 처리할 수 없습니다.'
    let fieldReasons
    try {
      var errorCode
      const body = await response.json()
      if (typeof body.error?.message === 'string' && body.error.message.length < 160) detail = body.error.message
      else if (response.status < 500 && typeof body.detail === 'string' && body.detail.length < 160) detail = body.detail
      // 결정표·승인 API는 detail을 {reason, message}로 낸다 (backend/graph/decision/routes.py `_http`).
      else if (response.status < 500 && typeof body.detail?.message === 'string' && body.detail.message.length < 160) detail = body.detail.message
      // 칸별 이유는 운영 오류 처리기가 내는 error.details.fields에 있다(backend/profile_api.py). 옛 위치 detail.fields도 받는다.
      const rawFields = body.error?.details?.fields ?? body.detail?.fields
      if (response.status === 422 && rawFields && typeof rawFields === 'object' && !Array.isArray(rawFields)) {
        fieldReasons = Object.fromEntries(Object.entries(rawFields).filter(([, reason]) => typeof reason === 'string'))
      }
      if (typeof body.error?.code === 'string' && body.error.code) errorCode = body.error.code
      else if (typeof body.detail?.reason === 'string' && body.detail.reason) errorCode = body.detail.reason
    } catch {
      // HTML 등 JSON이 아닌 오류 응답은 내부 내용을 사용자에게 노출하지 않습니다.
    }
    // 429에 Retry-After(초)가 있으면 남은 시간을 문구에 붙인다(H-29). 하루 질문 한도(daily_limit)는 문구에 "내일"이 있어 초를 붙이지 않는다
    const wait = Number.parseInt(response.headers.get('Retry-After') ?? '', 10)
    if (response.status === 429 && wait > 0 && errorCode !== 'daily_limit') detail = `${detail} (약 ${wait}초 뒤 가능)`
    throw new ApiError(detail, response.status, errorCode ?? (response.status === 401 ? 'unauthorized' : response.status === 403 ? 'forbidden' : 'request_failed'), fieldReasons)
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
  const csrfToken = await fetchCsrfCookie()

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
  const csrfToken = await fetchCsrfCookie()
  if (!csrfToken) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 로그아웃을 다시 시도해 주세요.')
  let response
  try {
    response = await apiRequest('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': decodeURIComponent(csrfToken) } })
  } catch (error) {
    // 세션이 이미 만료됐으면 서버에 지울 세션이 없다. 로컬 세션은 그대로 지운다(H-19).
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
  if (response.status !== 204) throw new ApiError('로그아웃 완료를 확인하지 못했습니다. 다시 시도해 주세요.')
  return response
}

// optional: 로그인 쿠키가 없으면 서버가 401 대신 204로 답한다(H-33, 로그아웃 상태 첫 확인이 콘솔에 401을 남기지 않게). 그때 null.
// 주소는 그대로 `/me`이고 머리글 `X-Session-Optional: 1`로 알린다(쿠키가 있으면 서버는 예전처럼 검사해 401·200을 준다)
export async function getCurrentUser({ optional = false } = {}) {
  if (!optional) return apiJson('/me')
  const response = await apiRequest('/me', { headers: { 'X-Session-Optional': '1' } })
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', response.status, 'invalid_response')
  }
  return response.json()
}

function readCsrfToken() {
  return document.cookie.split('; ').find(cookie => cookie.startsWith('provena_csrf='))?.split('=')[1]
}

// 전화번호를 가린 보기(phone_masked). 화면에 보여 주기만 할 때 쓴다.
export function getProfile() { return apiJson('/me/profile') }

// 원래 전화번호가 담긴 보기. 내 정보를 고치는 화면에서만 쓴다.
export function getProfileForEdit() { return apiJson('/me/profile?view=edit') }

export async function saveProfile(profile) {
  const token = await fetchCsrfCookie()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return apiJson('/me/profile', {
    method: 'PUT',
    headers: { 'X-CSRF-Token': decodeURIComponent(token) },
    body: JSON.stringify(profile),
  })
}

export function listAdminUsers() { return apiJson('/admin/users') }
export function listSignupRequests() { return apiJson('/admin/signup-requests') }

export async function reviewSignupRequest(loginId, action) {
  const token = await fetchCsrfCookie()
  if (!token) throw new ApiError('CSRF token unavailable', 0, 'csrf_unavailable')
  return apiJson(`/admin/signup-requests/${encodeURIComponent(loginId)}/${action}`, {
    method: 'POST', headers: { 'X-CSRF-Token': decodeURIComponent(token) },
  })
}

export async function reviewSignupRequestById(requestId, action) {
  const token = await fetchCsrfCookie()
  if (!token) throw new ApiError('CSRF token unavailable', 0, 'csrf_unavailable')
  return apiJson(`/admin/signup-requests/by-id/${encodeURIComponent(requestId)}/${action}`, {
    method: 'POST', headers: { 'X-CSRF-Token': decodeURIComponent(token) },
  })
}

export async function resetSignupVerification(requestId) {
  const token = await fetchCsrfCookie()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return apiJson(`/admin/signup-requests/by-id/${encodeURIComponent(requestId)}/reset-verification`, {
    method: 'POST', headers: { 'X-CSRF-Token': decodeURIComponent(token) },
  })
}

export async function changeAdminRole(loginId, action) {
  const token = await fetchCsrfCookie()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return apiJson(`/admin/users/${encodeURIComponent(loginId)}/${action}`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': decodeURIComponent(token) },
  })
}
export function getThreads() { return apiJson('/threads', { suppressUnauthorized: true }) }
export function getThread(threadId) { return apiJson(`/threads/${encodeURIComponent(threadId)}`) }
export function getMemory() { return apiJson('/me/memory', { suppressUnauthorized: true }) }
export async function csrfHeaders() {
  const token = await fetchCsrfCookie()
  if (!token) throw new ApiError('CSRF 토큰을 받을 수 없습니다. 다시 시도해 주세요.', 0, 'csrf_unavailable')
  return { 'X-CSRF-Token': decodeURIComponent(token) }
}

export async function patchMemory(value) { return apiJson('/me/memory', { method: 'PATCH', suppressUnauthorized: true, headers: await csrfHeaders(), body: JSON.stringify(value) }) }
export async function deleteMemory() { return apiRequest('/me/memory', { method: 'DELETE', suppressUnauthorized: true, headers: await csrfHeaders() }) }
export function getRecalls({ suppressUnauthorized = false, limit } = {}) { return apiJson(limit != null ? `/recalls?limit=${encodeURIComponent(limit)}` : '/recalls', { suppressUnauthorized }) }
export function getRecall(noticeId) { return apiJson(`/recalls/${encodeURIComponent(noticeId)}`) }
export function getRecallDigests() { return apiJson('/recalls/digests', { suppressUnauthorized: true }) }
export async function reviewRecall(noticeId, action) {
  return apiRequest(`/recalls/${encodeURIComponent(noticeId)}/review`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ action }) })
}
export async function sendRecallFeedback(noticeId, useful, reason = null) {
  return apiJson(`/recalls/${encodeURIComponent(noticeId)}/feedback`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ useful, reason }) })
}
export function getApprovals() { return apiJson('/approvals') }
export async function postApprovalDecision(approvalId, body) {
  const response = await apiRequest(`/approvals/${encodeURIComponent(approvalId)}`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ approval_id: approvalId, ...body }) })
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.toLowerCase().includes('application/json')) throw new ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', response.status, 'invalid_response')
  return response.json()
}
export function getDecisionTables() { return apiJson('/decision-tables') }
// 관리자: 핸드북 권한표의 한 업무 종류를 결정표 초안으로 바꿔 승인함에 올린다. 키 없는 데모는 201 + status=example(저장 안 됨).
export async function convertDecisionTable(category) {
  return apiJson('/decision-tables/convert', { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ category }) })
}
export function getMaintenanceCandidates() { return apiJson('/maintenance-candidates') }
export async function decideMaintenanceCandidate(candidateId, status) {
  return apiJson(`/maintenance-candidates/${encodeURIComponent(candidateId)}`, { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ status }) })
}
export async function flushRecallDigests() { return apiJson('/recalls/digest/flush', { method: 'POST', headers: await csrfHeaders() }) }
export async function processPendingRecalls() { return apiJson('/recalls/process-pending', { method: 'POST', headers: await csrfHeaders() }) }
export function getWebhookSubscriptions() { return apiJson('/webhook-subscriptions') }
export async function addWebhookSubscription(url) {
  return apiJson('/webhook-subscriptions', { method: 'POST', headers: await csrfHeaders(), body: JSON.stringify({ url }) })
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
    if (!data || data === '[DONE]') return
    let payload
    try { payload = JSON.parse(data) } catch { throw new ApiError('채팅 스트림 이벤트 형식이 올바르지 않습니다.', response.status, 'invalid_event') }
    // 콜백을 다시 만들어 덮어쓰면 이벤트마다 호출 깊이가 늘어 긴 답에서 RangeError가 난다(H-17) → 호출 때마다 새 객체만 만든다
    onEvent?.(eventName && payload && typeof payload === 'object' && !Array.isArray(payload) && !payload.type ? { ...payload, type: eventName } : payload)
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
