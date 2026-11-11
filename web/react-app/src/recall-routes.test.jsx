import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { resetLiveServices } from './lib/live-services'

const USER = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const ADMIN = { user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role: 'admin', profile_completed: true }

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const apiError = (status, code, message) => json({ error: { code, message, request_id: 'req-1' } }, status)

const notice = (overrides = {}) => ({
  notice_id: 'n1', answer_id: 'a1', user_id: USER.user_id, thread_id: 't1',
  question: '외부 SaaS 도입 전 어떤 검토가 필요한가요?', answer_excerpt: '구매 승인 절차를 진행하면 됩니다.',
  changed: { rule_seq: 'handbook/finance/procurement', article: 'Security review', old_version_date: '2024-01-01', new_version_date: '2024-03-01', change_type: 'modified' },
  conclusion_changed: true, explanation: '보안 검토 단계가 추가되었습니다.', severity: 'high', confidence: 0.82, needs_review: false, acked: false,
  created_at: '2026-11-03T06:12:00Z', source_url: 'https://handbook.gitlab.com/handbook/finance/procurement/',
  old_text: '구매 승인 절차를 진행합니다.', new_text: '구매 승인 전에 보안 검토를 완료해야 합니다.',
  ...overrides,
})

const candidate = (overrides = {}) => ({ candidate_id: 'c1', upper_rule: 'handbook/finance/procurement', upper_version_id: 'v2', rule_seq: 'handbook/security/third-party', article: 'Vendor review', reason: '조달 정책에서 링크로 연결됩니다.', status: 'pending', decided_by: null, ...overrides })

const change = (overrides = {}) => ({
  event_id: 'e1', rule_seq: 'handbook/finance/procurement', article: 'Security review', page_title: 'Procurement',
  old_version_date: '2024-01-01', new_version_date: '2024-03-01', change_type: 'modified', status: 'sent',
  created_at: '2026-11-03T06:12:00Z', source_url: 'https://handbook.gitlab.com/handbook/finance/procurement/', impacted_answer_count: 1,
  ...overrides,
})

let server
let calls

function requestsTo(method, path) {
  return calls.filter(call => (call.options?.method ?? 'GET') === method && call.path === path)
}

beforeEach(() => {
  resetLiveServices()
  document.cookie = 'provena_csrf=; Max-Age=0; path=/'
  calls = []
  server = {
    user: USER,
    recalls: { items: [notice(), notice({ notice_id: 'n2', acked: true, severity: 'low', conclusion_changed: false, changed: { rule_seq: 'handbook/security/access', article: 'Access review' } })], unread: 1 },
    recallsResponse: null,
    changes: { items: [change(), change({ event_id: 'e2', change_type: 'added', impacted_answer_count: 0, page_title: 'Vendor guide' })], last_run: { run_id: 'r1', status: 'ok', finished_at: '2026-11-03T06:30:00Z', to_commit: 'abc', list_complete: true }, more: false, monitoring: 'active' },
    monitoring: 'active',
  }
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options })
    const method = options.method ?? 'GET'
    if (path === '/me') return server.user ? json(server.user) : json({ detail: '인증이 필요합니다.' }, 401)
    if (path === '/auth/csrf') { document.cookie = 'provena_csrf=test-csrf; path=/'; return new Response(null, { status: 204 }) }
    if (path === '/threads') return json([])
    if (path === '/recalls' && method === 'GET') return server.recallsResponse ? server.recallsResponse() : json(server.recalls)
    if (path === '/recalls/digests') return server.digestsResponse ? server.digestsResponse() : json({ digests: [{ digest_id: 'd1', user_id: USER.user_id, day: '2026-11-03', count: 2, notice_ids: ['n1', 'n2'], created_at: '2026-11-03T00:00:00Z' }] })
    if (path === '/recalls/digest/flush' && method === 'POST') return server.flushResponse ? server.flushResponse() : json({ digests: 2, notices: 5 })
    if (path === '/recalls/process-pending' && method === 'POST') return server.pendingResponse ? server.pendingResponse() : json({ status: 'done', processed: 3, sent: 2, failed: 1, skipped: 0, notices: 4, review: 1, judge_failures: 0, candidates: 0 })
    if (path === '/webhook-subscriptions' && method === 'GET') return json({ items: server.subs ?? [] })
    if (path === '/webhook-subscriptions' && method === 'POST') return server.addSubResponse ? server.addSubResponse() : json({ sub_id: 'ws-1', url: JSON.parse(options.body).url, secret_ref: 'X', active: true, created_at: '2026-11-11T00:00:00Z', secret_configured: true }, 201)
    if (path === '/impact-preview' && method === 'POST') return json({ invalid_answers: 3, markdown: '## 영향 미리보기\n- 무효가 될 답변 3건' })
    let match = path.match(/^\/recalls\/([^/]+)\/(ack|review|feedback)$/)
    if (match && method === 'POST') {
      const [, id, action] = match
      if (id === 'missing') return apiError(404, 'not_found', '알림을 찾을 수 없습니다.')
      if (action === 'ack') return json(notice({ notice_id: id, acked: true }))
      if (action === 'review') return new Response(null, { status: 204 })
      return json({ notice_id: id, useful: JSON.parse(options.body).useful, counts: { not_useful: 1 } })
    }
    match = path.match(/^\/recalls\/([^/]+)$/)
    if (match && method === 'GET') return match[1] === 'missing' ? apiError(404, 'not_found', '알림을 찾을 수 없습니다.') : json(notice({ notice_id: match[1] }))
    match = path.match(/^\/maintenance-candidates\/([^/]+)$/)
    if (match && method === 'POST') return json(candidate({ candidate_id: match[1], status: JSON.parse(options.body).status, decided_by: 'admin-1' }))
    if (path === '/changes/monitoring' && method === 'PUT') { server.monitoring = JSON.parse(options.body).status; return json({ status: server.monitoring }) }
    if (path === '/changes/monitoring') return json({ status: server.monitoring })
    if (path.startsWith('/changes?') || path === '/changes') return server.changesResponse ? server.changesResponse() : json(server.changes)
    match = path.match(/^\/changes\/([^/?]+)$/)
    if (match) {
      const listed = server.detailMissing ? null : server.changes.items.find(item => item.event_id === match[1])
      return listed ? json({ ...listed, old_text: '이전 정책 본문', new_text: '새 정책 본문' }) : apiError(404, 'not_found', '변경 기록을 찾을 수 없습니다.')
    }
    return apiError(404, 'not_found', '요청한 경로를 찾을 수 없습니다.')
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function open(path) {
  window.history.replaceState({}, '', path)
  return render(<App />)
}

describe('live recall route', () => {
  it('shows the API notices with severity and confidence for a regular user', async () => {
    open('/recalls')
    await screen.findByRole('button', { name: /Security review/ })
    expect(screen.getByText('미확인 1건')).toBeTruthy()
    expect(screen.getByText('확신도 82%')).toBeTruthy()
    expect(screen.getAllByText('중요').length).toBeGreaterThan(0)
    expect(screen.getByText('보안 검토 단계가 추가되었습니다.')).toBeTruthy()
    expect(screen.getByText('구매 승인 전에 보안 검토를 완료해야 합니다.')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '관리자 확인 대기' })).toBeNull()
    expect(screen.queryByRole('heading', { name: '함께 볼 정책 후보' })).toBeNull()
    expect(screen.queryByRole('heading', { name: '변경 전 영향 미리보기' })).toBeNull()
    await screen.findByRole('heading', { name: '하루 요약' })
    expect(await screen.findByText(/알림 2건/)).toBeTruthy()
    const recallLink = screen.getByRole('link', { name: /리콜 알림/ })
    expect(recallLink.getAttribute('href')).toBe('/recalls')
    expect(recallLink.querySelector('b')?.textContent).toBe('1')
  })

  it('feeds the navigation badge from unread on other screens without logging out on failure', async () => {
    open('/chat')
    await screen.findByRole('heading', { name: '정책에 대해 물어보세요.' })
    await waitFor(() => expect(screen.getByRole('link', { name: /리콜 알림/ }).querySelector('b')?.textContent).toBe('1'))
    expect(requestsTo('GET', '/recalls')).toHaveLength(1)

    cleanup()
    resetLiveServices()
    calls = []
    server.recallsResponse = () => apiError(401, 'unauthorized', '로그인이 필요합니다.')
    open('/chat')
    await screen.findByRole('heading', { name: '정책에 대해 물어보세요.' })
    await waitFor(() => expect(requestsTo('GET', '/recalls')).toHaveLength(1))
    expect(screen.getByRole('button', { name: '내 계정' })).toBeTruthy()
    expect(screen.getByRole('link', { name: /리콜 알림/ }).querySelector('b')).toBeNull()
  })

  it('acknowledges a notice with CSRF and lowers the unread count', async () => {
    open('/recalls')
    await screen.findByRole('button', { name: /Security review/ })
    await userEvent.click(screen.getByRole('button', { name: '확인' }))
    await screen.findByText('미확인 0건')
    const [request] = requestsTo('POST', '/recalls/n1/ack')
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
    expect(request.options.credentials).toBe('include')
    expect(screen.getByRole('button', { name: '확인 완료' }).disabled).toBe(true)
  })

  it('sends "필요 없음" feedback with an optional reason', async () => {
    open('/recalls')
    await screen.findByRole('button', { name: /Security review/ })
    await userEvent.click(screen.getByRole('button', { name: '필요 없음' }))
    await userEvent.type(screen.getByLabelText('필요 없는 이유 (선택)'), '이미 알고 있는 변경입니다.')
    await userEvent.click(screen.getByRole('button', { name: '의견 보내기' }))
    await screen.findByText(/필요 없음으로 의견을 남겼습니다/)
    const [request] = requestsTo('POST', '/recalls/n1/feedback')
    expect(JSON.parse(request.options.body)).toEqual({ useful: false, reason: '이미 알고 있는 변경입니다.' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
  })

  it('sends "도움 됨" feedback without a reason', async () => {
    open('/recalls')
    await screen.findByRole('button', { name: /Security review/ })
    await userEvent.click(screen.getByRole('button', { name: '도움 됨' }))
    await screen.findByText('도움 됨으로 의견을 남겼습니다.')
    expect(JSON.parse(requestsTo('POST', '/recalls/n1/feedback')[0].options.body)).toEqual({ useful: true, reason: null })
  })

  it('highlights a notice whose judgement failed', async () => {
    server.recalls = { items: [notice({ explanation: '[판정 실패, 확인 필요] 판정 응답을 해석하지 못했습니다.', confidence: null })], unread: 1 }
    open('/recalls')
    await screen.findByText(/자동 판정에 실패한 알림입니다/)
    expect(screen.getByText('판정 응답을 해석하지 못했습니다.')).toBeTruthy()
    expect(screen.queryByText(/확신도/)).toBeNull()
    expect(screen.getAllByText('확인 필요').length).toBeGreaterThan(0)
  })

  it('shows a clear empty message when there are no notices', async () => {
    server.recalls = { items: [], unread: 0 }
    open('/recalls')
    await screen.findByText('받은 알림이 없습니다.')
    expect(screen.getByText('미확인 0건')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '아직 알림이 없습니다.' })).toBeTruthy()
  })

  it('shows an error state with retry when the list request fails', async () => {
    server.recallsResponse = () => apiError(500, 'internal', '서버 오류가 발생했습니다.')
    open('/recalls')
    const alert = await screen.findByText('리콜 알림을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    expect(alert).toBeTruthy()
    server.recallsResponse = null
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await screen.findByRole('button', { name: /Security review/ })
  })

  it('returns to login when the list request is unauthorized', async () => {
    server.recallsResponse = () => { server.user = null; return apiError(401, 'unauthorized', '로그인이 필요합니다.') }
    open('/recalls')
    await screen.findByLabelText('이메일 또는 아이디')
    expect(window.location.pathname).toBe('/login')
  })

  it('shows the not-found message for a notice link that no longer exists', async () => {
    open('/recalls?notice=missing')
    await screen.findByRole('heading', { name: '알림을 찾을 수 없습니다.' })
  })

  it('narrows the list to one policy change from the URL', async () => {
    open('/recalls?rule_seq=handbook%2Fsecurity%2Faccess')
    await screen.findByRole('button', { name: /Access review/ })
    expect(screen.queryByRole('button', { name: /Security review/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '전체 알림 보기' }))
    await screen.findByRole('button', { name: /Security review/ })
  })
})

describe('recall and change screens follow the real backend responses', () => {
  it("does not offer the acknowledge button on another user's notice to an administrator", async () => {
    // backend: POST /recalls/{id}/ack is owner-only, an admin gets 404 (tests/test_api_recalls.py:165)
    server.user = ADMIN
    server.recalls = { items: [notice({ user_id: USER.user_id })], unread: 0, review_queue: [], candidates: [] }
    open('/recalls')
    await screen.findByRole('button', { name: /Security review/ })
    expect(screen.queryByRole('button', { name: '확인' })).toBeNull()
    expect(screen.getByText('다른 사용자의 알림입니다.')).toBeTruthy()
  })

  it('still lets an administrator acknowledge their own notice', async () => {
    server.user = ADMIN
    server.recalls = { items: [notice({ user_id: ADMIN.user_id })], unread: 1, review_queue: [], candidates: [] }
    open('/recalls')
    await screen.findByRole('button', { name: /Security review/ })
    await userEvent.click(screen.getByRole('button', { name: '확인' }))
    await screen.findByText('미확인 0건')
  })

  it('shows the last collection run status in Korean, not the raw sync_runs value', async () => {
    // backend/rag/ingest/changes.py:79 last_run.status is 'succeeded' or 'noop'
    server.changes = { ...server.changes, last_run: { ...server.changes.last_run, status: 'succeeded' } }
    open('/changes')
    await screen.findByRole('button', { name: /Procurement/ })
    expect(screen.getByText(/마지막 수집 .* · 완료/)).toBeTruthy()
    expect(screen.queryByText(/succeeded/)).toBeNull()
  })
})

describe('live recall route for administrators', () => {
  beforeEach(() => {
    server.user = ADMIN
    server.recalls = { items: [], unread: 0, review_queue: [notice({ notice_id: 'q1', needs_review: true, confidence: 0.41, changed: { rule_seq: 'handbook/finance/procurement', article: 'Approval limits' } })], candidates: [candidate()] }
  })

  it('releases a notice from the review queue', async () => {
    open('/recalls')
    const queue = (await screen.findByRole('heading', { name: '관리자 확인 대기' })).closest('section')
    await within(queue).findByText('Approval limits')
    expect(within(queue).getByText('확신도 41%')).toBeTruthy()
    await userEvent.click(within(queue).getByRole('button', { name: '사용자에게 보내기' }))
    await screen.findByText('사용자에게 알림을 보냈습니다.')
    const [request] = requestsTo('POST', '/recalls/q1/review')
    expect(JSON.parse(request.options.body)).toEqual({ action: 'release' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
    expect(within(queue).getByText('확인 대기 중인 알림이 없습니다.')).toBeTruthy()
  })

  it('dismisses a notice from the review queue', async () => {
    open('/recalls')
    const queue = (await screen.findByRole('heading', { name: '관리자 확인 대기' })).closest('section')
    await userEvent.click(await within(queue).findByRole('button', { name: '폐기' }))
    await screen.findByText('알림을 폐기했습니다.')
    expect(JSON.parse(requestsTo('POST', '/recalls/q1/review')[0].options.body)).toEqual({ action: 'dismiss' })
  })

  it('decides a maintenance candidate and shows who decided', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '함께 볼 정책 후보' })).closest('section')
    expect(within(panel).getByText(/조달 정책에서 링크로 연결됩니다/)).toBeTruthy()
    await userEvent.click(within(panel).getByRole('button', { name: '정비 필요' }))
    await within(panel).findByText('판단한 관리자: admin-1')
    expect(JSON.parse(requestsTo('POST', '/maintenance-candidates/c1')[0].options.body)).toEqual({ status: 'needed' })
    expect(within(panel).queryByRole('button', { name: '정비 불필요' })).toBeNull()
  })

  it('runs the impact preview and shows the markdown summary', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '변경 전 영향 미리보기' })).closest('section')
    await userEvent.click(within(panel).getByLabelText('바뀐 섹션 목록(JSON)'))
    await userEvent.paste('[{"rule_seq":"12","article":"Approval limits"}]')
    await userEvent.click(within(panel).getByRole('button', { name: '미리보기 실행' }))
    await within(panel).findByText(/무효가 될 답변 3건/)
    expect(JSON.parse(requestsTo('POST', '/impact-preview')[0].options.body)).toEqual({ changes: [{ rule_seq: 12, article: 'Approval limits' }] })
  })

  it('blocks a non-numeric rule_seq before sending, because the server answers 422 (H-10)', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '변경 전 영향 미리보기' })).closest('section')
    await userEvent.click(within(panel).getByLabelText('바뀐 섹션 목록(JSON)'))
    await userEvent.paste('[{"rule_seq":"handbook/finance/procurement","article":"Approval limits"}]')
    await userEvent.click(within(panel).getByRole('button', { name: '미리보기 실행' }))
    expect(await within(panel).findByText(/rule_seq는 0 이상의 정수/)).toBeTruthy()
    expect(requestsTo('POST', '/impact-preview')).toHaveLength(0)
  })

  it('shows an error instead of an empty list when the digests cannot be loaded (H-11)', async () => {
    server.digestsResponse = () => apiError(500, 'internal_error', '서버 오류')
    open('/recalls')
    expect(await screen.findByText('하루 요약을 불러오지 못했습니다.')).toBeTruthy()
  })

  it('sends the page-pair form of the impact preview with integer rule_seq only (H-10)', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '변경 전 영향 미리보기' })).closest('section')
    await userEvent.click(within(panel).getByRole('button', { name: '개정 전후 본문(JSON)' }))
    await userEvent.click(within(panel).getByLabelText('개정 전후 본문(JSON)'))
    await userEvent.paste('{"old_version_date":"2026-11-01","new_version_date":"2026-11-10","pages":[{"path":"a.md","old":"x","new":"y"}]}')
    await userEvent.click(within(panel).getByRole('button', { name: '미리보기 실행' }))
    await within(panel).findByText(/무효가 될 답변 3건/)
    expect(JSON.parse(requestsTo('POST', '/impact-preview')[0].options.body)).toEqual({ old_version_date: '2026-11-01', new_version_date: '2026-11-10', pages: [{ path: 'a.md', old: 'x', new: 'y' }] })
    expect(within(panel).queryByRole('button', { name: 'MR diff' })).toBeNull()
  })

  it('rejects invalid impact preview JSON before calling the server', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '변경 전 영향 미리보기' })).closest('section')
    await userEvent.click(within(panel).getByLabelText('바뀐 섹션 목록(JSON)'))
    await userEvent.paste('{not json')
    await userEvent.click(within(panel).getByRole('button', { name: '미리보기 실행' }))
    await within(panel).findByText('JSON 형식이 올바르지 않습니다.')
    expect(requestsTo('POST', '/impact-preview')).toHaveLength(0)
  })
})

describe('admin manual recall actions and webhook subscriptions (H-21)', () => {
  beforeEach(() => {
    server.user = ADMIN
    server.recalls = { items: [], unread: 0, review_queue: [], candidates: [] }
    server.subs = [{ sub_id: 'ws-0', url: 'https://hooks.example.com/a', secret_ref: 'X', active: true, created_at: '2026-11-10T00:00:00Z', secret_configured: false }]
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('flushes digests with CSRF and shows the result', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '리콜 수동 실행' })).closest('section')
    await userEvent.click(within(panel).getByRole('button', { name: '하루 요약 지금 만들기' }))
    await within(panel).findByText('하루 요약 2건을 만들었습니다(알림 5건).')
    const [request] = requestsTo('POST', '/recalls/digest/flush')
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
  })

  it('does not call the server when the confirmation is cancelled', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '리콜 수동 실행' })).closest('section')
    await userEvent.click(within(panel).getByRole('button', { name: '처리 대기 변경 지금 처리' }))
    expect(requestsTo('POST', '/recalls/process-pending')).toHaveLength(0)
  })

  it('processes pending changes and shows the counts', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '리콜 수동 실행' })).closest('section')
    await userEvent.click(within(panel).getByRole('button', { name: '처리 대기 변경 지금 처리' }))
    await within(panel).findByText('변경 3건을 처리했습니다(알림 4건 생성, 실패 1건, 건너뜀 0건).')
    expect(requestsTo('POST', '/recalls/process-pending')[0].options.headers['X-CSRF-Token']).toBe('test-csrf')
  })

  it('shows a server error for a failed manual run', async () => {
    server.pendingResponse = () => apiError(503, 'not_configured', '변경 목록 저장소를 사용할 수 없습니다.')
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '리콜 수동 실행' })).closest('section')
    await userEvent.click(within(panel).getByRole('button', { name: '처리 대기 변경 지금 처리' }))
    await within(panel).findByText('변경 목록 저장소를 사용할 수 없습니다.')
  })

  it('lists webhook subscriptions and adds one', async () => {
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '웹훅 구독' })).closest('section')
    await within(panel).findByText('https://hooks.example.com/a')
    await userEvent.type(within(panel).getByLabelText('웹훅 주소'), 'https://hooks.example.com/b')
    await userEvent.click(within(panel).getByRole('button', { name: '구독 추가' }))
    await within(panel).findByText('웹훅 구독을 추가했습니다.')
    const [request] = requestsTo('POST', '/webhook-subscriptions')
    expect(JSON.parse(request.options.body)).toEqual({ url: 'https://hooks.example.com/b' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
    expect(within(panel).getByText('https://hooks.example.com/b')).toBeTruthy()
  })

  it('shows the server message when a webhook address is rejected', async () => {
    server.addSubResponse = () => apiError(400, 'bad_request', '배포 환경에서는 https 주소만 쓸 수 있습니다')
    open('/recalls')
    const panel = (await screen.findByRole('heading', { name: '웹훅 구독' })).closest('section')
    await userEvent.type(within(panel).getByLabelText('웹훅 주소'), 'http://x.example.com/h')
    await userEvent.click(within(panel).getByRole('button', { name: '구독 추가' }))
    await within(panel).findByText('배포 환경에서는 https 주소만 쓸 수 있습니다')
  })

  it('hides the admin tools from ordinary users', async () => {
    server.user = USER
    open('/recalls')
    await screen.findByText('알림 목록')
    expect(screen.queryByRole('heading', { name: '리콜 수동 실행' })).toBeNull()
    expect(screen.queryByRole('heading', { name: '웹훅 구독' })).toBeNull()
  })
})

describe('live change monitoring route', () => {
  it('shows changes, loads old and new text, and links to related recalls', async () => {
    open('/changes')
    await screen.findByRole('button', { name: /Procurement/ })
    await screen.findByText('새 정책 본문')
    expect(screen.getByText('이전 정책 본문')).toBeTruthy()
    expect(screen.getByText('감시 중')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '감시 일시 중지' })).toBeNull()
    const link = screen.getByRole('link', { name: '관련 리콜 알림 보기' })
    expect(link.getAttribute('href')).toBe('/recalls?rule_seq=handbook%2Ffinance%2Fprocurement&article=Security+review')
    await userEvent.click(link)
    await screen.findByText(/선택한 정책 변경/)
    expect(window.location.pathname).toBe('/recalls')
  })

  it('draws the distribution from server totals, not from the loaded page', async () => {
    server.changes = { ...server.changes, more: true, total: 318, counts: { modified: 280, added: 28, removed: 10 } }
    open('/changes')
    await screen.findByRole('button', { name: /Procurement/ })
    const card = screen.getByLabelText('변경 유형 분포')
    await waitFor(() => expect(card.textContent).toContain('총 318건'))
    expect(card.textContent).toContain('수정280건')
    expect(card.textContent).toContain('추가28건')
    expect(card.textContent).toContain('삭제10건')
    expect(card.textContent).toContain('조회 기간 전체 기준')
  })

  it('does not offer a recall link when no answers are impacted', async () => {
    open('/changes')
    await userEvent.click(await screen.findByRole('button', { name: /Vendor guide/ }))
    await waitFor(() => expect(requestsTo('GET', '/changes/e2')).toHaveLength(1))
    expect(screen.queryByRole('link', { name: '관련 리콜 알림 보기' })).toBeNull()
  })

  it('maps an incomplete last run to the held notice', async () => {
    server.changes = { ...server.changes, last_run: { run_id: 'r2', status: 'held', finished_at: '2026-11-03T06:30:00Z', to_commit: null, list_complete: false } }
    open('/changes')
    expect((await screen.findAllByText(/변경 목록을 확정하지 못해 보류되었습니다/)).length).toBeGreaterThan(0)
    expect(screen.getAllByText('동결 보류').length).toBeGreaterThan(1)
    expect(requestsTo('GET', '/changes/held-r2')).toHaveLength(0)
  })

  it('shows the not-found message when a change detail is gone', async () => {
    server.detailMissing = true
    open('/changes')
    await screen.findByText('변경 기록을 찾을 수 없습니다.')
    expect(screen.getByRole('button', { name: /Procurement/ })).toBeTruthy()
  })

  it('shows an empty message when there are no changes', async () => {
    server.changes = { items: [], last_run: null, more: false, monitoring: 'active' }
    open('/changes')
    await screen.findByText('변경 기록이 없습니다.')
    expect(screen.getByRole('heading', { name: '아직 감지된 변경이 없습니다.' })).toBeTruthy()
  })

  it('shows an error state when the change list fails', async () => {
    server.changesResponse = () => apiError(503, 'unavailable', '서비스를 사용할 수 없습니다.')
    open('/changes')
    await screen.findByText('변경 기록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
  })

  it('lets an administrator pause monitoring with CSRF', async () => {
    server.user = ADMIN
    open('/changes')
    await userEvent.click(await screen.findByRole('button', { name: '감시 일시 중지' }))
    await screen.findByText('일시 중지')
    const [request] = requestsTo('PUT', '/changes/monitoring')
    expect(JSON.parse(request.options.body)).toEqual({ status: 'paused' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
    expect(screen.getByRole('button', { name: '감시 다시 시작' })).toBeTruthy()
  })
})

describe('demo routes keep the preview data', () => {
  it('renders the preview recall page without calling the recall API', async () => {
    open('/demo/recalls')
    await screen.findByRole('heading', { name: '리콜 알림' })
    expect(screen.getByText('제3자 SaaS 도입 검토 절차가 변경되었습니다.', { selector: 'strong' })).toBeTruthy()
    expect(calls.some(call => call.path.startsWith('/recalls'))).toBe(false)
  })

  it('renders the preview change page without calling the change API', async () => {
    open('/demo/changes')
    await screen.findByRole('heading', { name: '정책 변경 감시' })
    expect(screen.getAllByText('Third Party Risk Management').length).toBeGreaterThan(0)
    expect(calls.some(call => call.path.startsWith('/changes'))).toBe(false)
  })
})
