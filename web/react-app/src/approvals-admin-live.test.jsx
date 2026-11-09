import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import App from './App'

const admin = { user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role: 'admin', profile_completed: true }

// Server ApprovalView shape (backend/graph/decision/routes.py ApprovalView).
const decisionView = {
  approval_id: 'ap-1', kind: 'decision_table', summary: 'Purchase 결정표 초안', created_at: '2026-11-09T01:20:00+00:00', table_id: 'dt-9',
  draft: [{ category: 'Purchase', band: 'Up to $25K', band_label: '$25,000 이하', approvers: ['Director'], financial_approvers: ['CFO'], cooperating_depts: [], range_note: null }],
  comparison: { rows: [{ category: 'Purchase', band: 'Up to $25K', band_label: '$25,000 이하', role: 'Director', approval_type: 'Functional', source_value: 'X', source_line: 12, expected: 'approver', draft: 'approver', match: true }], source_cells: 1, mismatch_count: 0, extra_bands: [] },
  rejected_resume: null, issue_table: null, failed_teams: null, save_failed: false,
}
const issueView = {
  approval_id: 'ap-2', kind: 'issue_table', summary: '합동 검토 쟁점표: 쟁점 1건', created_at: '2026-11-09T02:00:00+00:00', table_id: null, draft: null, comparison: null, rejected_resume: null,
  issue_table: { request: '새 SaaS 도입', rows: [{ team: 'security', team_label: '보안', topic: '데이터 반출', issue: '고객 데이터가 외부로 나간다', stance: 'condition', chunk_id: 'c1', section_path: 'Security > Data', source_url: 'https://handbook.gitlab.com/x', conflict: false }], unreviewed: [] },
  failed_teams: null, save_failed: false,
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

// Server candidate_json shape (backend/graph/recall/service.py candidate_json, GET /maintenance-candidates -> {items}).
const candidateItem = {
  candidate_id: 'mc-1', upper_rule: 'Engaging with Security', upper_version_id: 'e1f04a7c', rule_seq: 4100, article: 'CVE 공개 기한',
  reason: "참조 그래프: HackerOne Process의 'CVE 공개 기한' 섹션이 개정된 'Engaging with Security' 페이지를 링크합니다", status: 'pending', decided_by: null,
}

function stubServer({ approvals = [decisionView, issueView], decide, tables = [], candidates = { items: [] }, decideCandidate } = {}) {
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    const method = options.method ?? 'GET'
    if (path === '/me') return json(admin)
    if (path === '/auth/csrf') return new Response(null, { status: 204 })
    if (path === '/approvals' && method === 'GET') return json(approvals)
    if (path.startsWith('/approvals/') && method === 'POST') return decide(path, options)
    if (path === '/decision-tables' && method === 'GET') return json(tables)
    if (path === '/maintenance-candidates' && method === 'GET') return typeof candidates === 'function' ? candidates() : json(candidates)
    if (path.startsWith('/maintenance-candidates/') && method === 'POST') return decideCandidate(path, options)
    return json({ detail: 'not found' }, 404)
  }))
}

function decisionCalls() {
  return fetch.mock.calls.filter(([path, options]) => path.startsWith('/approvals/') && options?.method === 'POST')
}

async function approveFirstItem() {
  await screen.findByRole('heading', { name: 'Purchase 결정표 초안' })
  fireEvent.click(screen.getByRole('button', { name: '승인하기' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: '확인' }))
}

describe('live approvals inbox (/approvals)', () => {
  beforeEach(() => {
    document.cookie = 'provena_csrf=csrf-token-1; path=/'
    window.history.replaceState({}, '', '/approvals')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('lists pending items from GET /approvals with the cell comparison', async () => {
    stubServer({ decide: () => json({}) })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Purchase 결정표 초안' })).toBeTruthy()
    expect(screen.getByText('합동 검토 쟁점표: 쟁점 1건')).toBeTruthy()
    expect(screen.getAllByText('$25,000 이하').length).toBeGreaterThan(0)
    expect(screen.getByText('원문과 일치')).toBeTruthy()
    expect(screen.queryByText(/실제 업무 API는 아직 연결되지 않았습니다/)).toBeNull()
    expect(fetch).toHaveBeenCalledWith('/approvals', expect.anything())
  })

  it('sends POST /approvals/{id} with CSRF and the {approve, comment} body', async () => {
    stubServer({ decide: () => json({ approval_id: 'ap-1', kind: 'decision_table', status: 'approved', table_id: 'dt-9', decided_by: admin.user_id, comment: '', next_approval: null }) })
    render(<App />)
    await approveFirstItem()
    expect(await screen.findByText('승인 처리했습니다.')).toBeTruthy()
    const [[path, options]] = decisionCalls()
    expect(path).toBe('/approvals/ap-1')
    expect(options.headers['X-CSRF-Token']).toBe('csrf-token-1')
    expect(JSON.parse(options.body)).toEqual({ approval_id: 'ap-1', approve: true, comment: '' })
    expect(fetch).toHaveBeenCalledWith('/auth/csrf', expect.anything())
  })

  it('shows the server 403 message when the decision is refused', async () => {
    stubServer({ decide: () => json({ detail: '관리자 권한이 필요합니다.' }, 403) })
    render(<App />)
    await approveFirstItem()
    expect((await screen.findByText('관리자 권한이 필요합니다.')).getAttribute('role')).toBe('alert')
    expect(screen.getByRole('button', { name: '승인하기' }).disabled).toBe(false)
  })

  it('shows the message of a {reason, message} error detail', async () => {
    stubServer({ decide: () => json({ detail: { reason: 'already_decided', message: '다른 결정이 이미 접수되었다' } }, 409) })
    render(<App />)
    await approveFirstItem()
    expect(await screen.findByText('다른 결정이 이미 접수되었다')).toBeTruthy()
  })
})
