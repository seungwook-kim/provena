import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { resetLiveServices } from './lib/live-services'

const USER = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const ADMIN = { user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role: 'admin', profile_completed: true }

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const apiError = (status, code, message) => json({ error: { code, message, request_id: 'req-1' } }, status)

const decisionItem = (overrides = {}) => ({
  kind: 'decision_table', approval_id: 'dec-1', summary: '결정표 승인 요청: Procurement (구간 1개, 원문과 다른 칸 1개)', created_at: '2026-11-03T06:12:00Z', table_id: 'dt_1',
  draft: [{ category: 'Procurement', band: 'Up to $5K', band_label: '5,000달러 이하', approvers: ['Manager'], financial_approvers: [], cooperating_depts: [], range_note: null }],
  comparison: {
    rows: [
      { category: 'Procurement', band: 'Up to $5K', band_label: '5,000달러 이하', role: 'Manager', approval_type: 'Approves', source_value: 'A', source_line: 4, expected: 'approver', draft: 'approver', match: true },
      { category: 'Procurement', band: 'Up to $5K', band_label: '5,000달러 이하', role: 'Legal', approval_type: 'Signs', source_value: 'S', source_line: 5, expected: 'cooperating', draft: 'none', match: false },
    ],
    source_cells: 2, mismatch_count: 1, extra_bands: [],
  },
  save_failed: false,
  ...overrides,
})

const cleanDecision = () => decisionItem({ approval_id: 'dec-2', summary: '결정표 승인 요청: Travel (구간 1개, 원문과 다른 칸 0개)', comparison: { rows: [], source_cells: 3, mismatch_count: 0, extra_bands: [] } })

const issueItem = () => ({
  kind: 'issue_table', approval_id: 'iss-1', summary: '합동 검토 쟁점표: 쟁점 2건 (보안 1, 재무 1)', created_at: '2026-11-03T07:00:00Z',
  issue_table: {
    request: '외부 SaaS를 도입하려면 어떤 검토가 필요한가요?', as_of: '2026-11-05',
    rows: [
      { team: 'security', team_label: '보안', topic: 'saas', issue: '보안 검토가 필요합니다.', stance: 'condition', confidence: 'high', section_path: 'Procurement > Security review', version_date: '2024-03-01', source_url: 'https://handbook.gitlab.com/handbook/finance/procurement/', conflict: true },
      { team: 'finance', team_label: '재무', topic: 'saas', issue: '예산 승인이 필요합니다.', stance: 'block', confidence: 'low', section_path: 'Finance > Budget', version_date: '2024-02-01', source_url: null, conflict: true },
    ],
    unreviewed: [{ team: 'infra', team_label: '인프라·SRE', reason: '모델 응답을 읽지 못함' }],
  },
  save_failed: false,
})

const teamFailedItem = () => ({
  kind: 'team_review_failed', approval_id: 'team-1', summary: '팀 검토 실패: 인프라·SRE', created_at: '2026-11-03T08:00:00Z',
  failed_teams: [{ team: 'infra', reason: '모델 응답을 읽지 못함', attempts: 3 }], resolution: null, save_failed: false,
})

let server
let calls

const requestsTo = (method, path) => calls.filter(call => (call.options?.method ?? 'GET') === method && call.path === path)

beforeEach(() => {
  resetLiveServices()
  document.cookie = 'provena_csrf=; Max-Age=0; path=/'
  calls = []
  server = { user: ADMIN, approvals: [decisionItem(), cleanDecision(), issueItem(), teamFailedItem()], listResponse: null, decideResponse: null }
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options })
    const method = options.method ?? 'GET'
    if (path === '/me') return server.user ? json(server.user) : json({ detail: '인증이 필요합니다.' }, 401)
    if (path === '/auth/csrf') { document.cookie = 'provena_csrf=test-csrf; path=/'; return new Response(null, { status: 204 }) }
    if (path === '/threads') return json([])
    if (path === '/recalls') return json({ items: [], unread: 0 })
    if (path === '/recalls/digests') return json([])
    if (path === '/approvals' && method === 'GET') return server.listResponse ? server.listResponse() : json(server.approvals)
    const match = path.match(/^\/approvals\/([^/]+)$/)
    if (match && method === 'POST') {
      if (server.decideResponse) return server.decideResponse(match[1], JSON.parse(options.body))
      const item = server.approvals.find(entry => entry.approval_id === match[1])
      if (!item) return apiError(404, 'not_found', '승인 건이 없다')
      server.approvals = server.approvals.filter(entry => entry !== item)
      const body = JSON.parse(options.body)
      return json({ approval_id: item.approval_id, kind: item.kind, status: body.approve === false ? 'rejected' : 'approved', table_id: null, decided_by: ADMIN.user_id, comment: body.comment ?? '' })
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

describe('live approvals route', () => {
  it('lists the pending approvals of every kind from the API', async () => {
    open('/approvals')
    await screen.findByRole('button', { name: /결정표 승인 요청: Procurement/ })
    expect(screen.getByRole('button', { name: /결정표 승인 요청: Travel/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /합동 검토 쟁점표/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /팀 검토 실패/ })).toBeTruthy()
    expect(requestsTo('GET', '/approvals')).toHaveLength(1)
    expect(calls.some(call => call.path.startsWith('/demo'))).toBe(false)
  })

  it('shows the source comparison and the draft of a decision table', async () => {
    open('/approvals')
    await screen.findByRole('heading', { name: '원문 대조' })
    expect(screen.getByText('불일치 항목 · 검토 필요')).toBeTruthy()
    expect(screen.getByText(/원문과 다른 칸 1개/, { selector: 'p' })).toBeTruthy()
    const [comparison, draft] = screen.getAllByRole('table')
    expect(within(comparison).getByText('불일치')).toBeTruthy()
    expect(within(comparison).getByText('협조(승인 아님)')).toBeTruthy()
    expect(within(draft).getByText('5,000달러 이하')).toBeTruthy()
    expect(within(draft).getByText('Manager')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '부서별 검토' })).toBeNull()
    expect(screen.queryByRole('button', { name: '보완 요청' })).toBeNull()
    expect(screen.queryByRole('link', { name: '원문 보기' })).toBeNull()
  })

  it('requires a reason to approve a draft that differs from the source, and sends it with CSRF', async () => {
    open('/approvals')
    await screen.findByRole('heading', { name: '원문 대조' })
    expect(screen.getByRole('button', { name: '승인하기' }).disabled).toBe(true)
    expect(screen.getByRole('button', { name: '반려하기' }).disabled).toBe(true)
    await userEvent.type(screen.getByLabelText(/^사유/), '협조 항목은 별도 확인했습니다.')
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('승인했습니다.')
    const [request] = requestsTo('POST', '/approvals/dec-1')
    expect(JSON.parse(request.options.body)).toEqual({ approval_id: 'dec-1', approve: true, comment: '협조 항목은 별도 확인했습니다.' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
    expect(request.options.credentials).toBe('include')
    expect(requestsTo('GET', '/approvals')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /결정표 승인 요청: Procurement/ })).toBeNull()
    expect(screen.getByRole('button', { name: /결정표 승인 요청: Travel/ })).toBeTruthy()
  })

  it('approves a draft that matches the source without a reason', async () => {
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /결정표 승인 요청: Travel/ }))
    expect(screen.getByText('원문과 다른 칸이 없습니다. (원문 칸 3개)')).toBeTruthy()
    expect(screen.getByRole('button', { name: '승인하기' }).disabled).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('승인했습니다.')
    expect(JSON.parse(requestsTo('POST', '/approvals/dec-2')[0].options.body)).toEqual({ approval_id: 'dec-2', approve: true, comment: '' })
  })

  it('rejects with a reason and refreshes the list', async () => {
    open('/approvals')
    await screen.findByRole('heading', { name: '원문 대조' })
    await userEvent.type(screen.getByLabelText(/^사유/), '원문과 다릅니다.')
    await userEvent.click(screen.getByRole('button', { name: '반려하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('반려했습니다.')
    expect(JSON.parse(requestsTo('POST', '/approvals/dec-1')[0].options.body)).toEqual({ approval_id: 'dec-1', approve: false, comment: '원문과 다릅니다.' })
    expect(requestsTo('GET', '/approvals')).toHaveLength(2)
  })

  it('shows the issue table by team with its unreviewed teams and no department review form', async () => {
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /합동 검토 쟁점표/ }))
    await screen.findByRole('heading', { name: '쟁점표' })
    expect(screen.getByText('외부 SaaS를 도입하려면 어떤 검토가 필요한가요?')).toBeTruthy()
    const table = screen.getByRole('table')
    expect(within(table).getByText('보안 검토가 필요합니다.')).toBeTruthy()
    expect(within(table).getByText('조건부 가능')).toBeTruthy()
    expect(within(table).getByText('불가')).toBeTruthy()
    expect(within(table).getAllByText('팀 입장 충돌')).toHaveLength(2)
    expect(within(table).getByRole('link', { name: '원문 보기' }).getAttribute('href')).toBe('https://handbook.gitlab.com/handbook/finance/procurement/')
    expect(screen.getByText(/인프라·SRE: 모델 응답을 읽지 못함/)).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '부서별 검토' })).toBeNull()
    expect(screen.getByRole('button', { name: '승인하기' }).disabled).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('승인했습니다.')
    expect(JSON.parse(requestsTo('POST', '/approvals/iss-1')[0].options.body)).toEqual({ approval_id: 'iss-1', approve: true, comment: '' })
  })

  it('offers retry and mark-unreviewed for a team failure notice', async () => {
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /팀 검토 실패/ }))
    await screen.findByRole('heading', { name: '검토하지 못한 팀' })
    expect(screen.getByText('모델 응답을 읽지 못함')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '반려하기' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '실패한 팀 다시 검토' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('실패한 팀의 검토를 다시 요청했습니다.')
    expect(JSON.parse(requestsTo('POST', '/approvals/team-1')[0].options.body)).toEqual({ approval_id: 'team-1', action: 'retry', comment: '' })
  })

  it('shows an empty message when nothing is waiting for approval', async () => {
    server.approvals = []
    open('/approvals')
    await screen.findByText(/처리할 승인 요청이 없습니다/)
    expect(screen.queryByRole('button', { name: '승인하기' })).toBeNull()
  })

  it('shows an error state with retry when the list request fails', async () => {
    server.listResponse = () => apiError(500, 'internal_error', '서버 오류가 발생했습니다.')
    open('/approvals')
    await screen.findByText('승인 요청을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    server.listResponse = null
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await screen.findByRole('button', { name: /결정표 승인 요청: Procurement/ })
  })

  it('explains that a reason is needed when the server asks for one', async () => {
    server.decideResponse = () => apiError(400, 'comment_required', 'comment가 필요하다')
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /결정표 승인 요청: Travel/ }))
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('원문과 다른 칸이 있는 초안을 승인하려면 사유를 입력해야 합니다.')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(requestsTo('GET', '/approvals')).toHaveLength(1)
  })

  it('tells the administrator the request was already decided and reloads the list', async () => {
    server.decideResponse = () => { server.approvals = server.approvals.slice(1); return apiError(409, 'already_decided', '이미 끝난 승인 건에 다른 결정') }
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /결정표 승인 요청: Travel/ }))
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText(/이미 다른 결정이 처리된 요청입니다/)
    await waitFor(() => expect(requestsTo('GET', '/approvals')).toHaveLength(2))
    expect(screen.queryByRole('button', { name: /결정표 승인 요청: Procurement/ })).toBeNull()
  })

  it('tells the user when the permission is missing', async () => {
    server.decideResponse = () => apiError(403, 'forbidden', '관리자만 가능합니다.')
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /결정표 승인 요청: Travel/ }))
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('이 작업을 수행할 권한이 없습니다. 승인 요청은 관리자만 처리할 수 있습니다.')
  })

  it('does not call the approvals API for a regular user', async () => {
    server.user = USER
    open('/approvals')
    await screen.findByText(/접근 권한이 없습니다/)
    expect(calls.some(call => call.path.startsWith('/approvals'))).toBe(false)
  })

  it('shows an item without detail as not decidable instead of inventing content', async () => {
    server.approvals = [{ kind: 'decision_table', approval_id: 'dec-9', summary: '결정표 승인 요청: Legacy', created_at: '2026-11-03T06:12:00Z', table_id: 'dt_9', save_failed: false }]
    open('/approvals')
    await screen.findByText('상세 정보 없음')
    expect(screen.getByRole('button', { name: '승인하기' }).disabled).toBe(true)
  })
})

describe('demo approvals route keeps the preview data', () => {
  it('renders the preview approvals without calling the approvals API', async () => {
    server.user = null
    open('/demo/approvals')
    await screen.findByRole('heading', { name: '승인함' })
    await screen.findByText('구매 권한표 변환 검토', { selector: 'h2' })
    expect(screen.getByRole('button', { name: '승인 대기' })).toBeTruthy()
    expect(calls.some(call => call.path.startsWith('/approvals'))).toBe(false)
  })
})
