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
    if (path === '/recalls?limit=500') return json({ items: [], unread: 0 })
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

describe('approval confirm dialog', () => {
  it('keeps the item it was opened for even if another item is selected before confirming', async () => {
    open('/approvals')
    await userEvent.click(await screen.findByRole('button', { name: /결정표 승인 요청: Travel/ }))
    await userEvent.click(screen.getByRole('button', { name: '승인하기' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/Travel/)).toBeTruthy()
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy()
    expect(document.getElementById(dialog.getAttribute('aria-labelledby')).textContent).toBe('승인하시겠습니까?')
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: '취소' }))
    await userEvent.click(screen.getByRole('button', { name: /결정표 승인 요청: Procurement/ }))
    expect(within(screen.getByRole('dialog')).getByText(/Travel/)).toBeTruthy()
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))
    await screen.findByText('승인했습니다.')
    expect(requestsTo('POST', '/approvals/dec-2')).toHaveLength(1)
    expect(requestsTo('POST', '/approvals/dec-1')).toHaveLength(0)
  })
})
