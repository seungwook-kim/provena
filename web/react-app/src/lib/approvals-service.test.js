import { describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  createApiApprovalsService,
  describeApprovalError,
  mapApproval,
  mapDecisionResult,
  previewApprovalsService,
  toApprovalRequestBody,
} from './approvals-service'

const decisionItem = (overrides = {}) => ({
  kind: 'decision_table',
  approval_id: 'dec-1',
  summary: '결정표 승인 요청: Procurement (구간 2개, 원문과 다른 칸 1개)',
  created_at: '2026-11-03T06:12:00Z',
  table_id: 'dt_1',
  draft: [
    { category: 'Procurement', band: 'Up to $5K', band_label: '5,000달러 이하', approvers: ['Manager'], financial_approvers: [], cooperating_depts: ['Legal'], range_note: null },
  ],
  comparison: {
    rows: [
      { category: 'Procurement', band: 'Up to $5K', band_label: '5,000달러 이하', role: 'Manager', approval_type: 'Approves', source_value: 'A', source_line: 4, expected: 'approver', draft: 'approver', match: true },
      { category: 'Procurement', band: 'Up to $5K', band_label: '5,000달러 이하', role: 'Legal', approval_type: 'Signs', source_value: 'S', source_line: 5, expected: 'cooperating', draft: 'none', match: false },
    ],
    source_cells: 2,
    mismatch_count: 1,
    extra_bands: [],
  },
  save_failed: false,
  ...overrides,
})

const issueItem = (overrides = {}) => ({
  kind: 'issue_table',
  approval_id: 'iss-1',
  summary: '합동 검토 쟁점표: 쟁점 2건',
  created_at: '2026-11-03T07:00:00Z',
  issue_table: {
    request: '외부 SaaS를 도입하려면 어떤 검토가 필요한가요?',
    as_of: '2026-11-05',
    rows: [
      { team: 'security', team_label: '보안', topic: 'saas', issue: '보안 검토가 필요합니다.', stance: 'condition', confidence: 'high', section_path: 'Procurement > Security review', version_date: '2024-03-01', source_url: 'https://handbook.gitlab.com/handbook/finance/procurement/', conflict: true },
      { team: 'finance', team_label: '재무', topic: 'saas', issue: '예산 승인이 필요합니다.', stance: 'block', confidence: 'low', source_url: 'javascript:alert(1)', conflict: true },
    ],
    unreviewed: [{ team: 'infra', team_label: '인프라·SRE', reason: '모델 응답을 읽지 못함' }],
    team_status: {},
  },
  save_failed: false,
  ...overrides,
})

const teamFailedItem = () => ({
  kind: 'team_review_failed',
  approval_id: 'team-1',
  summary: '팀 검토 실패: 인프라·SRE',
  created_at: '2026-11-03T08:00:00Z',
  failed_teams: [{ team: 'infra', reason: '모델 응답을 읽지 못함', attempts: 3 }],
  resolution: null,
  save_failed: false,
})

function fakeApi(overrides = {}) {
  return {
    getApprovals: vi.fn(async () => [decisionItem(), issueItem(), teamFailedItem()]),
    postApprovalDecision: vi.fn(async (id, body) => ({ approval_id: id, kind: 'decision_table', status: body.approve ? 'approved' : 'rejected', table_id: 'dt_1', decided_by: 'admin-1', comment: body.comment })),
    ...overrides,
  }
}

describe('approval mapping', () => {
  it('maps a decision table with its comparison and draft', () => {
    const item = mapApproval(decisionItem())
    expect(item).toMatchObject({ id: 'dec-1', kind: 'decision', status: 'pending', tableId: 'dt_1', saveFailed: false, hasDetail: true })
    expect(item.title).toContain('결정표 승인 요청')
    expect(item.at).toMatch(/^2026-11-0\d \d\d:\d\d$/)
    expect(item.decision.comparison).toMatchObject({ mismatchCount: 1, needsReason: true, sourceCells: 2, extraBands: [] })
    expect(item.decision.comparison.rows[1]).toMatchObject({ role: 'Legal', expected: 'cooperating', draft: 'none', match: false, bandLabel: '5,000달러 이하' })
    expect(item.decision.draft[0]).toEqual({ band: 'Up to $5K', bandLabel: '5,000달러 이하', approvers: ['Manager'], financialApprovers: [], cooperating: ['Legal'], rangeNote: null })
  })

  it('does not require a reason for a decision table that matches the source', () => {
    const item = mapApproval(decisionItem({ comparison: { rows: [], source_cells: 2, mismatch_count: 0, extra_bands: [] } }))
    expect(item.decision.comparison.needsReason).toBe(false)
  })

  it('requires a reason when the draft invented a band even without cell mismatches', () => {
    const item = mapApproval(decisionItem({ comparison: { rows: [], source_cells: 2, mismatch_count: 0, extra_bands: ['Over $1M'] } }))
    expect(item.decision.comparison.needsReason).toBe(true)
  })

  it('maps an issue table, dropping unsafe source links and unknown stances', () => {
    const item = mapApproval(issueItem())
    expect(item).toMatchObject({ id: 'iss-1', kind: 'issue', hasDetail: true })
    expect(item.issue.request).toBe('외부 SaaS를 도입하려면 어떤 검토가 필요한가요?')
    expect(item.issue.asOf).toBe('2026-11-05')
    expect(item.issue.rows[0]).toMatchObject({ teamLabel: '보안', stance: 'condition', confidence: 'high', conflict: true, sourceUrl: 'https://handbook.gitlab.com/handbook/finance/procurement/' })
    expect(item.issue.rows[1].sourceUrl).toBeNull()
    expect(item.issue.unreviewed).toEqual([{ team: 'infra', teamLabel: '인프라·SRE', reason: '모델 응답을 읽지 못함' }])
  })

  it('maps a team failure notice', () => {
    const item = mapApproval(teamFailedItem())
    expect(item).toMatchObject({ kind: 'team_failed', hasDetail: true })
    expect(item.failedTeams).toEqual([{ team: 'infra', reason: '모델 응답을 읽지 못함', attempts: 3 }])
  })

  it('marks an item without a draft as having no detail instead of inventing one', () => {
    const item = mapApproval({ kind: 'decision_table', approval_id: 'dec-2', summary: '결정표', created_at: '2026-11-03T06:12:00Z', table_id: 't', save_failed: false })
    expect(item.hasDetail).toBe(false)
    expect(item.decision).toBeNull()
    expect(mapApproval({ kind: 'something_new', approval_id: 'x' })).toMatchObject({ kind: 'unknown', hasDetail: false, title: '승인 요청' })
  })

  it('keeps the save failure flag', () => {
    expect(mapApproval(decisionItem({ save_failed: true })).saveFailed).toBe(true)
  })

  it('maps the decision result including the next approval of a team failure', () => {
    expect(mapDecisionResult({ approval_id: 'team-1', kind: 'team_review_failed', status: 'approved', resolution: 'retry', next_approval: { approval_id: 'iss-2', kind: 'issue_table', summary: '쟁점표' } }))
      .toMatchObject({ id: 'team-1', kind: 'team_failed', resolution: 'retry', nextApproval: { id: 'iss-2', summary: '쟁점표' } })
  })
})

describe('request body', () => {
  it('builds the backend body for each action and trims the comment', () => {
    expect(toApprovalRequestBody('approve', '  확인함 ')).toEqual({ approve: true, comment: '확인함' })
    expect(toApprovalRequestBody('reject', '기준이 다릅니다.')).toEqual({ approve: false, comment: '기준이 다릅니다.' })
    expect(toApprovalRequestBody('retry')).toEqual({ action: 'retry', comment: '' })
    expect(toApprovalRequestBody('mark_unreviewed', '나중에 확인')).toEqual({ action: 'mark_unreviewed', comment: '나중에 확인' })
  })

  it('rejects an action the backend does not know, such as a revision request', () => {
    expect(() => toApprovalRequestBody('revision', '보완')).toThrow('지원하지 않는 처리입니다.')
  })
})

describe('API approvals service', () => {
  it('is live and keeps the preview service separate', () => {
    expect(createApiApprovalsService(fakeApi()).live).toBe(true)
    expect(previewApprovalsService.live).toBe(false)
    expect(createApiApprovalsService(fakeApi()).getDepartmentReviews).toBeNull()
  })

  it('lists the approvals from GET /approvals', async () => {
    const api = fakeApi()
    const items = await createApiApprovalsService(api).listApprovals()
    expect(api.getApprovals).toHaveBeenCalledTimes(1)
    expect(items.map(item => item.kind)).toEqual(['decision', 'issue', 'team_failed'])
  })

  it('returns an empty list for an empty response', async () => {
    expect(await createApiApprovalsService(fakeApi({ getApprovals: vi.fn(async () => []) })).listApprovals()).toEqual([])
  })

  it('finds one approval from the list response', async () => {
    const service = createApiApprovalsService(fakeApi())
    expect((await service.getApprovalDetail('iss-1')).kind).toBe('issue')
    expect(await service.getApprovalDetail('nope')).toBeNull()
  })

  it('approves with the comment and maps the result', async () => {
    const api = fakeApi()
    const result = await createApiApprovalsService(api).decideApproval('dec-1', { action: 'approve', reason: '검토함' })
    expect(api.postApprovalDecision).toHaveBeenCalledWith('dec-1', { approve: true, comment: '검토함' })
    expect(result).toMatchObject({ id: 'dec-1', status: 'approved', tableId: 'dt_1', decidedBy: 'admin-1' })
  })

  it('rejects with the reason', async () => {
    const api = fakeApi()
    await createApiApprovalsService(api).decideApproval('dec-1', { action: 'reject', reason: '원문과 다릅니다.' })
    expect(api.postApprovalDecision).toHaveBeenCalledWith('dec-1', { approve: false, comment: '원문과 다릅니다.' })
  })

  it('sends a team failure action', async () => {
    const api = fakeApi()
    await createApiApprovalsService(api).decideApproval('team-1', { action: 'retry' })
    expect(api.postApprovalDecision).toHaveBeenCalledWith('team-1', { action: 'retry', comment: '' })
  })

  it('does not call the API for an unsupported action', async () => {
    const api = fakeApi()
    await expect(createApiApprovalsService(api).decideApproval('dec-1', { action: 'revision', reason: 'x' })).rejects.toThrow('지원하지 않는 처리입니다.')
    expect(api.postApprovalDecision).not.toHaveBeenCalled()
  })

  it.each([
    ['comment_required', 400, '사유를 입력해야 합니다'],
    ['already_decided', 409, '이미 다른 결정이 처리된 요청'],
    ['forbidden', 403, '권한이 없습니다'],
    ['csrf_failed', 403, '보안 확인에 실패했습니다'],
    ['not_found', 404, '승인 요청을 찾을 수 없습니다'],
    ['save_failed', 503, '같은 결정을 다시 보내면'],
    ['conflict', 409, '처리할 수 없는 요청'],
  ])('turns the %s error into a Korean message and keeps the code', async (code, status, snippet) => {
    const api = fakeApi({ postApprovalDecision: vi.fn(async () => { throw new ApiError('english backend text', status, code) }) })
    const error = await createApiApprovalsService(api).decideApproval('dec-1', { action: 'approve' }).catch(caught => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe(code)
    expect(error.status).toBe(status)
    expect(error.message).toContain(snippet)
    expect(error.message).not.toContain('english')
  })

  it('uses the list fallback message for a server error and for a network failure', async () => {
    const serverError = createApiApprovalsService(fakeApi({ getApprovals: vi.fn(async () => { throw new ApiError('서버 오류', 500, 'internal_error') }) }))
    await expect(serverError.listApprovals()).rejects.toThrow('승인 요청을 불러오지 못했습니다.')
    const network = createApiApprovalsService(fakeApi({ getApprovals: vi.fn(async () => { throw new TypeError('Failed to fetch') }) }))
    await expect(network.listApprovals()).rejects.toThrow('승인 요청을 불러오지 못했습니다.')
  })

  it('describes a forbidden list request for a non administrator', async () => {
    const service = createApiApprovalsService(fakeApi({ getApprovals: vi.fn(async () => { throw new ApiError('forbidden', 403, 'forbidden') }) }))
    await expect(service.listApprovals()).rejects.toThrow('권한이 없습니다')
  })
})

describe('server error reason through the real API client', () => {
  // main's api.js reads detail.reason into error.code; this checks that the approvals service maps that code to its Korean message.
  it.each([
    ['comment_required', 400, '사유를 입력해야 합니다'],
    ['already_decided', 409, '이미 다른 결정이 처리된 요청'],
    ['not_found', 404, '승인 요청을 찾을 수 없습니다'],
    ['save_failed', 503, '같은 결정을 다시 보내면'],
  ])('reads detail.reason %s from the response body and shows the mapped Korean message', async (reason, status, snippet) => {
    document.cookie = 'provena_csrf=test-csrf; path=/'
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { reason, message: 'english backend text' } }), { status, headers: { 'content-type': 'application/json' } })))
    const error = await createApiApprovalsService().decideApproval('dec-1', { action: 'approve' }).catch(caught => caught)
    vi.unstubAllGlobals()
    document.cookie = 'provena_csrf=; Max-Age=0; path=/'
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe(reason)
    expect(error.status).toBe(status)
    expect(error.message).toContain(snippet)
    expect(error.message).not.toContain('english')
  })
})
describe('describeApprovalError', () => {
  it('falls back by status and returns an empty string without an error', () => {
    expect(describeApprovalError(null)).toBe('')
    expect(describeApprovalError({ status: 401 })).toBe('로그인이 필요합니다.')
    expect(describeApprovalError({ status: 422, code: 'weird', message: '직접 만든 메시지' })).toBe('직접 만든 메시지')
    expect(describeApprovalError({ status: 502, code: 'bad_gateway' }, '대체 문구')).toBe('대체 문구')
  })
})
