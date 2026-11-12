import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { resetLiveServices } from './lib/live-services'

// 운영 현황(/admin)이 실제 API 응답을 화면에 보이는지 본다.
// mock 응답 모양은 백엔드와 같다: DecisionTableItem·ApprovalView(backend/graph/decision/routes.py), candidate_json(backend/graph/recall/service.py).
const ADMIN = { user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role: 'admin', profile_completed: true }

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const apiError = (status, code, message) => json({ error: { code, message, request_id: 'req-1' } }, status)

const approvedTable = (overrides = {}) => ({
  table_id: 'dt_approved_1', rule_seq: 9, version_id: '0a3de8337541', category: 'Procurement', status: 'approved',
  cells: [
    { category: 'Procurement', band: 'Up to $5K', band_label: '$5,000 이하', approvers: ['Manager'], financial_approvers: [], cooperating_depts: [], range_note: null },
    { category: 'Procurement', band: '$5K to $25K', band_label: '$5,000 초과 $25,000 이하', approvers: ['Director'], financial_approvers: ['FP&A'], cooperating_depts: [], range_note: null },
  ],
  ...overrides,
})

const pendingDecision = (overrides = {}) => ({
  kind: 'decision_table', approval_id: 'dec-1', summary: '결정표 승인 요청: Travel (구간 1개, 원문과 다른 칸 0개)', created_at: '2026-11-03T06:12:00Z', table_id: 'dt_draft_1',
  draft: [{ category: 'Travel', band: 'Up to $5K', band_label: '$5,000 이하', approvers: ['Manager'], financial_approvers: [], cooperating_depts: [], range_note: null }],
  comparison: { rows: [], source_cells: 3, mismatch_count: 0, extra_bands: [] }, rejected_resume: null, issue_table: null, failed_teams: null, save_failed: false,
  ...overrides,
})

const issueApproval = () => ({
  kind: 'issue_table', approval_id: 'iss-1', summary: '합동 검토 쟁점표: 쟁점 2건', created_at: '2026-11-03T07:00:00Z', table_id: null,
  draft: null, comparison: null, rejected_resume: null, issue_table: { request: '질문', as_of: '2026-11-05', rows: [], unreviewed: [] }, failed_teams: null, save_failed: false,
})

const candidate = (overrides = {}) => ({
  candidate_id: 'mc-1', upper_rule: 'Procurement Policy', upper_version_id: 'v2', rule_seq: 90003, article: 'SaaS 도입 정책',
  reason: '조달 정책에서 링크로 연결됩니다.', status: 'pending', decided_by: null,
  ...overrides,
})

let server
let calls

const requestsTo = (method, path) => calls.filter(call => (call.options?.method ?? 'GET') === method && call.path === path)
const summaryValue = label => screen.getByText(label, { selector: '.summary-item small' }).parentElement.querySelector('strong').textContent

beforeEach(() => {
  resetLiveServices()
  document.cookie = 'provena_csrf=; Max-Age=0; path=/'
  window.history.replaceState({}, '', '/admin')
  calls = []
  server = { tables: [approvedTable()], approvals: [pendingDecision(), issueApproval()], candidates: [candidate()], tablesResponse: null, approvalsResponse: null, candidatesResponse: null, decideResponse: null }
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options })
    const method = options.method ?? 'GET'
    if (path === '/me') return json(ADMIN)
    if (path === '/auth/csrf') { document.cookie = 'provena_csrf=test-csrf; path=/'; return new Response(null, { status: 204 }) }
    if (path === '/threads') return json([])
    if (path === '/recalls?limit=500') return json({ items: [], unread: 0 })
    if (path === '/recalls/digests') return json([])
    if (path === '/decision-tables' && method === 'GET') return server.tablesResponse ? server.tablesResponse() : json(server.tables)
    if (path === '/approvals' && method === 'GET') return server.approvalsResponse ? server.approvalsResponse() : json(server.approvals)
    if (path === '/maintenance-candidates' && method === 'GET') return server.candidatesResponse ? server.candidatesResponse() : json({ items: server.candidates })
    const match = path.match(/^\/maintenance-candidates\/([^/]+)$/)
    if (match && method === 'POST') {
      if (server.decideResponse) return server.decideResponse()
      const found = server.candidates.find(item => item.candidate_id === match[1])
      if (!found) return apiError(404, 'not_found', '함께 볼 정책 후보를 찾을 수 없습니다.')
      return json({ ...found, status: JSON.parse(options.body).status, decided_by: 'admin' })
    }
    return apiError(404, 'not_found', '요청한 경로를 찾을 수 없습니다.')
  }))
})

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('운영 현황(/admin) 실제 데이터 연결', () => {
  it('API 응답을 요약 숫자와 표에 보인다', async () => {
    render(<App />)
    await screen.findByText('Procurement 결정표')
    expect(screen.getByText('결정표 승인 요청: Travel (구간 1개, 원문과 다른 칸 0개)', { selector: 'td' })).toBeTruthy()
    expect(screen.getByText('문서 번호 9 · 판 0a3de8337541 · 구간 2개', { selector: 'td' })).toBeTruthy()
    expect(summaryValue('결정표')).toBe('2')            // 승인 완료 1 + 승인 대기 1 (쟁점표 건은 결정표가 아니라 세지 않는다)
    expect(summaryValue('처리 대기')).toBe('1')
    expect(summaryValue('정책 정비 후보')).toBe('1')
    expect(screen.getByText('SaaS 도입 정책')).toBeTruthy()
    expect(screen.getByText('조달 정책에서 링크로 연결됩니다.')).toBeTruthy()
    expect(screen.queryByText(/데이터 연동 준비 중/)).toBeNull()
    expect(requestsTo('GET', '/decision-tables')).toHaveLength(1)
    expect(requestsTo('GET', '/maintenance-candidates')).toHaveLength(1)
  })

  it('필터 탭을 누르면 선택 표시가 바뀌고 상태별로 행이 걸러진다', async () => {
    server.tables = [approvedTable(), approvedTable({ table_id: 'dt_approved_2', category: 'Travel' })]
    render(<App />)
    await screen.findByText('Procurement 결정표')
    const tab = name => screen.getByRole('button', { name })
    const rows = () => document.querySelectorAll('.admin-table-panel tbody tr')
    const selectedTabs = () => [...document.querySelectorAll('.admin-approval-filter button.selected')].map(button => button.textContent)
    expect(selectedTabs()).toEqual(['전체'])
    expect(tab('전체').disabled).toBe(false)
    expect(rows()).toHaveLength(3)                     // 승인 대기 1 + 승인 완료 2
    await userEvent.click(tab('승인 대기'))
    expect(selectedTabs()).toEqual(['승인 대기'])
    expect(tab('승인 대기').getAttribute('aria-pressed')).toBe('true')
    expect(tab('전체').getAttribute('aria-pressed')).toBe('false')
    expect(rows()).toHaveLength(1)
    expect(screen.queryByText('Procurement 결정표', { selector: 'td' })).toBeNull()
    await userEvent.click(tab('승인 완료'))
    expect(selectedTabs()).toEqual(['승인 완료'])
    expect(rows()).toHaveLength(2)
    expect([...rows()].every(row => row.textContent.includes('승인 완료'))).toBe(true)
    await userEvent.click(tab('전체'))
    expect(selectedTabs()).toEqual(['전체'])
    expect(rows()).toHaveLength(3)
    expect(screen.queryByRole('button', { name: '반려' })).toBeNull()   // 반려 목록 API가 없어 실제 화면에는 반려 탭을 두지 않는다
  })

  it('승인 대기가 0건이면 그 탭에서 상태 이름이 든 빈 결과 문구를 보인다', async () => {
    server.approvals = [issueApproval()]
    render(<App />)
    await screen.findByText('Procurement 결정표', { selector: 'td' })
    expect(summaryValue('처리 대기')).toBe('0')
    await userEvent.click(screen.getByRole('button', { name: '승인 대기' }))
    expect(screen.getByText('승인 대기 상태인 결정표가 없습니다.')).toBeTruthy()
    expect(document.querySelectorAll('.admin-table-panel tbody tr')).toHaveLength(0)
    expect(screen.queryByRole('alert')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '승인 완료' }))
    expect(document.querySelectorAll('.admin-table-panel tbody tr')).toHaveLength(1)
  })

  it('백엔드 상태값 draft는 승인 대기로, rejected는 반려로 맞춘다', async () => {
    const { mapApprovedDecisionTable } = await import('./lib/admin-service')
    expect(mapApprovedDecisionTable(approvedTable({ status: 'draft' })).status).toBe('pending')
    expect(mapApprovedDecisionTable(approvedTable({ status: 'rejected' })).status).toBe('rejected')
    expect(mapApprovedDecisionTable(approvedTable()).status).toBe('approved')
  })

  it('목록이 비면 오류가 아니라 빈 목록 안내를 보인다', async () => {
    server.tables = []
    server.approvals = []
    server.candidates = []
    render(<App />)
    await screen.findByText('해당하는 결정표가 없습니다.')
    expect(screen.getByText('정책 정비 후보가 없습니다.')).toBeTruthy()
    expect(summaryValue('결정표')).toBe('0')
    expect(summaryValue('정책 정비 후보')).toBe('0')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('결정표 API가 403이면 권한 오류를 보이고 빈 목록으로 보이지 않는다', async () => {
    server.approvalsResponse = () => apiError(403, 'forbidden', '관리자 권한이 필요합니다.')
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('관리자만 볼 수 있는 데이터입니다.')
    expect(screen.queryByText('해당하는 결정표가 없습니다.')).toBeNull()
    expect(summaryValue('결정표')).toBe('—')
    expect(summaryValue('처리 대기')).toBe('—')
    expect(summaryValue('정책 정비 후보')).toBe('1')    // 다른 쪽 데이터는 그대로 보인다
  })

  it('정비 후보 API가 500이면 서버 오류를 보이고 다시 시도로 회복한다', async () => {
    server.candidatesResponse = () => apiError(500, 'internal_error', '서버 오류')
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('서버 오류로 데이터를 불러오지 못했습니다.')
    expect(screen.queryByText('정책 정비 후보가 없습니다.')).toBeNull()
    expect(summaryValue('정책 정비 후보')).toBe('—')
    expect(summaryValue('결정표')).toBe('2')
    server.candidatesResponse = null
    await userEvent.click(within(alert).getByRole('button', { name: '다시 시도' }))
    await screen.findByText('SaaS 도입 정책')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('네트워크 오류면 연결 오류를 두 구역 모두에 보인다', async () => {
    server.tablesResponse = () => { throw new TypeError('Failed to fetch') }
    server.candidatesResponse = () => { throw new TypeError('Failed to fetch') }
    render(<App />)
    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2))
    screen.getAllByRole('alert').forEach(alert => expect(alert.textContent).toContain('서버에 연결하지 못했습니다.'))
    expect(screen.queryByText('해당하는 결정표가 없습니다.')).toBeNull()
    expect(screen.queryByText('정책 정비 후보가 없습니다.')).toBeNull()
  })

  it('판단 버튼이 CSRF 헤더와 함께 올바른 주소·본문으로 보낸다', async () => {
    render(<App />)
    await screen.findByText('SaaS 도입 정책')
    await userEvent.click(screen.getByRole('button', { name: '검토 필요' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('검토 필요 · 처리 완료')
    const [request] = requestsTo('POST', '/maintenance-candidates/mc-1')
    expect(JSON.parse(request.options.body)).toEqual({ status: 'needed' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(summaryValue('정책 정비 후보')).toBe('0')
  })

  it('검토 불필요는 not_needed로 보낸다', async () => {
    render(<App />)
    await screen.findByText('SaaS 도입 정책')
    await userEvent.click(screen.getByRole('button', { name: '검토 불필요' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('검토 불필요 · 처리 완료')
    expect(JSON.parse(requestsTo('POST', '/maintenance-candidates/mc-1')[0].options.body)).toEqual({ status: 'not_needed' })
  })

  it('판단 저장이 실패하면 대화상자에 오류를 보이고 후보는 대기 상태로 둔다', async () => {
    server.decideResponse = () => apiError(404, 'not_found', '함께 볼 정책 후보를 찾을 수 없습니다.')
    render(<App />)
    await screen.findByText('SaaS 도입 정책')
    await userEvent.click(screen.getByRole('button', { name: '검토 필요' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '확인' }))
    expect((await within(dialog).findByRole('alert')).textContent).toContain('정비 후보를 찾을 수 없습니다.')
    expect(screen.queryByText('검토 필요 · 처리 완료')).toBeNull()
  })
})
