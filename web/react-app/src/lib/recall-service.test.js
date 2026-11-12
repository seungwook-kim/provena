import { describe, expect, it, vi } from 'vitest'
import {
  JUDGEMENT_FAILED_PREFIX,
  createApiRecallService,
  describeApiError,
  filterByChange,
  filterRecallRecords,
  formatConfidence,
  mapCandidate,
  mapDigest,
  mapNotice,
  mapRecallsResponse,
  parseImpactInput,
  previewRecallService,
} from './recall-service'

const notice = (overrides = {}) => ({
  notice_id: 'n1',
  answer_id: 'a1',
  user_id: 'u1',
  thread_id: 't1',
  question: '외부 SaaS 도입 전 어떤 검토가 필요한가요?',
  answer_excerpt: '구매 승인 절차를 진행하면 됩니다.',
  changed: { rule_seq: 'handbook/finance/procurement', article: 'Security review', old_version_date: '2024-01-01', new_version_date: '2024-03-01', change_type: 'modified' },
  conclusion_changed: true,
  explanation: '보안 검토 단계가 추가되었습니다.',
  severity: 'high',
  confidence: 0.82,
  needs_review: false,
  acked: false,
  created_at: '2026-11-03T06:12:00Z',
  source_url: 'https://handbook.gitlab.com/handbook/finance/procurement/',
  old_text: '구매 승인 절차를 진행합니다.',
  new_text: '구매 승인 전에 보안 검토를 완료해야 합니다.',
  ...overrides,
})

const candidate = (overrides = {}) => ({ candidate_id: 'c1', upper_rule: 'handbook/finance/procurement', upper_version_id: 'v2', rule_seq: 'handbook/security/third-party', article: 'Vendor review', reason: '조달 정책에서 링크로 연결됩니다.', status: 'pending', decided_by: null, ...overrides })

function fakeApi(overrides = {}) {
  return {
    getRecalls: vi.fn(async () => ({ items: [notice(), notice({ notice_id: 'n2', acked: true, severity: 'low', conclusion_changed: false })], unread: 1 })),
    getRecall: vi.fn(async id => notice({ notice_id: id })),
    acknowledgeRecall: vi.fn(async id => notice({ notice_id: id, acked: true })),
    sendRecallFeedback: vi.fn(async (id, useful) => ({ notice_id: id, useful, counts: { not_useful: 1 } })),
    reviewRecall: vi.fn(async () => new Response(null, { status: 204 })),
    getMaintenanceCandidates: vi.fn(async () => [candidate()]),
    decideMaintenanceCandidate: vi.fn(async (id, status) => candidate({ candidate_id: id, status, decided_by: 'admin-1' })),
    getRecallDigests: vi.fn(async () => [{ digest_id: 'd1', user_id: 'u1', day: '2026-11-03', count: 2, high: 1, low: 1, notices: [notice()] }]),
    postImpactPreview: vi.fn(async () => ({ invalid_answers: 3, markdown: '## 영향 미리보기\n- 무효 답변 3건' })),
    ...overrides,
  }
}

describe('recall notice mapping', () => {
  it('maps the backend notice to the record shape used by the recall screen', () => {
    const record = mapNotice(notice())
    expect(record).toMatchObject({
      id: 'n1',
      title: 'Security review',
      document: 'handbook/finance/procurement',
      question: '외부 SaaS 도입 전 어떤 검토가 필요한가요?',
      oldAnswer: '구매 승인 절차를 진행하면 됩니다.',
      oldPolicy: '구매 승인 절차를 진행합니다.',
      newPolicy: '구매 승인 전에 보안 검토를 완료해야 합니다.',
      sourceUrl: 'https://handbook.gitlab.com/handbook/finance/procurement/',
      acked: false,
      conclusionChanged: true,
      severity: 'high',
      confidence: 0.82,
      ruleSeq: 'handbook/finance/procurement',
      article: 'Security review',
      oldVersionDate: '2024-01-01',
      newVersionDate: '2024-03-01',
      needsConfirmation: false,
    })
    expect(record.detectedAt).toMatch(/^2026-11-0\d \d\d:\d\d$/)
  })

  it('flags notices whose judgement failed and strips the prefix from the explanation', () => {
    const record = mapNotice(notice({ explanation: `${JUDGEMENT_FAILED_PREFIX} 모델 응답을 해석하지 못했습니다.` }))
    expect(record.needsConfirmation).toBe(true)
    expect(record.explanation).toBe('모델 응답을 해석하지 못했습니다.')
  })

  it('keeps missing optional fields empty instead of inventing values', () => {
    const record = mapNotice({ notice_id: 7, changed: null, severity: 'unknown', confidence: null, old_text: null, new_text: '', source_url: null })
    expect(record).toMatchObject({ id: '7', title: '바뀐 정책 섹션', document: '', oldPolicy: null, newPolicy: null, sourceUrl: null, severity: null, confidence: null, detectedAt: '' })
  })

  it('maps user and admin list responses', () => {
    const user = mapRecallsResponse({ items: [notice()], unread: 5 })
    expect(user).toMatchObject({ unread: 5, reviewQueue: [], candidates: null, isAdminView: false })
    expect(user.records).toHaveLength(1)

    const admin = mapRecallsResponse({ items: [], unread: 0, review_queue: [notice({ notice_id: 'q1', needs_review: true })], candidates: [candidate()] })
    expect(admin.isAdminView).toBe(true)
    expect(admin.reviewQueue[0]).toMatchObject({ id: 'q1', needsReview: true })
    expect(admin.candidates[0]).toMatchObject({ id: 'c1', upperRule: 'handbook/finance/procurement', status: 'pending', decidedBy: null })
  })

  it('treats an empty or malformed list response as no notices', () => {
    expect(mapRecallsResponse({})).toMatchObject({ records: [], unread: 0 })
    expect(mapRecallsResponse(null)).toMatchObject({ records: [], unread: 0 })
    expect(mapRecallsResponse({ items: [notice(), notice({ notice_id: 'n2', acked: true })] }).unread).toBe(1)
  })

  it('maps candidates and digests', () => {
    expect(mapCandidate(candidate({ status: 'needed', decided_by: 'admin-1' }))).toMatchObject({ status: 'needed', decidedBy: 'admin-1', reason: '조달 정책에서 링크로 연결됩니다.' })
    expect(mapCandidate({ candidate_id: 3, status: 'weird' }).status).toBe('pending')
    const digest = mapDigest({ digest_id: 'd1', day: '2026-11-03', count: 2, high: 1, low: 1, notices: [notice()] })
    expect(digest).toMatchObject({ id: 'd1', day: '2026-11-03', count: 2, high: 1, low: 1 })
    expect(digest.notices[0].id).toBe('n1')
  })

  it('formats confidence as a percentage when it is a ratio', () => {
    expect(formatConfidence(0.824)).toBe('82%')
    expect(formatConfidence(1)).toBe('100%')
    expect(formatConfidence(null)).toBeNull()
    expect(formatConfidence(7)).toBe('7')
  })

  it('filters by status and by the policy change that caused the notice', () => {
    const records = [mapNotice(notice()), mapNotice(notice({ notice_id: 'n2', acked: true, severity: 'low', conclusion_changed: false, changed: { rule_seq: 'other', article: 'Other' }, explanation: `${JUDGEMENT_FAILED_PREFIX} 확인` }))]
    expect(filterRecallRecords(records, 'unread').map(record => record.id)).toEqual(['n1'])
    expect(filterRecallRecords(records, 'changed').map(record => record.id)).toEqual(['n1'])
    expect(filterRecallRecords(records, 'high').map(record => record.id)).toEqual(['n1'])
    expect(filterRecallRecords(records, 'confirm').map(record => record.id)).toEqual(['n2'])
    expect(filterByChange(records, { ruleSeq: 'other' }).map(record => record.id)).toEqual(['n2'])
    expect(filterByChange(records, { ruleSeq: 'handbook/finance/procurement', article: 'Security review' }).map(record => record.id)).toEqual(['n1'])
    expect(filterByChange(records, {})).toHaveLength(2)
  })

  it('describes API errors with the not-found message', () => {
    expect(describeApiError({ status: 404, code: 'not_found', message: 'x' })).toBe('알림을 찾을 수 없습니다.')
    expect(describeApiError({ status: 403, code: 'forbidden' })).toBe('이 작업을 수행할 권한이 없습니다.')
    expect(describeApiError({ status: 500, code: 'internal', message: '서버 오류가 발생했습니다.' })).toBe('서버 오류가 발생했습니다.')
  })

  it('parses impact preview input', () => {
    expect(parseImpactInput('changes', '[{"rule_seq":1}]')).toEqual({ changes: [{ rule_seq: 1 }] })
    expect(parseImpactInput('changes', '{"changes":[{"rule_seq":1}]}')).toEqual({ changes: [{ rule_seq: 1 }] })
    expect(parseImpactInput('changes', '{"rule_seq":1}')).toEqual({ changes: [{ rule_seq: 1 }] })
    // 서버는 rule_seq 정수만 받는다(ImpactChange.rule_seq: int, ge=0) — 문자열 경로·음수·소수·없음은 보내기 전에 막는다
    for (const bad of ['"handbook/finance/procurement"', '"a"', '-1', '1.5', 'null']) {
      expect(() => parseImpactInput('changes', `[{"rule_seq":${bad},"article":"x"}]`)).toThrow('rule_seq')
    }
    expect(() => parseImpactInput('changes', '[{"article":"x"}]')).toThrow('rule_seq')
    expect(() => parseImpactInput('changes', '{oops')).toThrow('JSON 형식이 올바르지 않습니다.')
    expect(() => parseImpactInput('changes', '  ')).toThrow('바뀐 섹션 목록을 입력해 주세요.')
  })

  it('sends rule_seq as an integer and never sends the unsupported diff field (H-10)', () => {
    expect(parseImpactInput('changes', '[{"rule_seq":"12","article":"a"},{"rule_seq":7,"article":"b"}]')).toEqual({ changes: [{ rule_seq: 12, article: 'a' }, { rule_seq: 7, article: 'b' }] })
    const pages = '{"old_version_date":"2026-11-01","new_version_date":"2026-11-10","pages":[{"path":"a.md","old":"x","new":"y"}]}'
    expect(parseImpactInput('pages', pages)).toEqual({ old_version_date: '2026-11-01', new_version_date: '2026-11-10', pages: [{ path: 'a.md', old: 'x', new: 'y' }] })
    expect(() => parseImpactInput('pages', '[{"path":"a.md"}]')).toThrow('pages')
    expect(() => parseImpactInput('pages', '{"pages":[{"path":"a.md"}]}')).toThrow('old_version_date')
    expect(Object.keys(parseImpactInput('pages', pages))).not.toContain('diff')
  })
})

describe('API recall service', () => {
  it('loads notices into its snapshot and notifies subscribers', async () => {
    const api = fakeApi()
    const service = createApiRecallService(api)
    const listener = vi.fn()
    service.subscribe(listener)
    expect(service.live).toBe(true)
    expect(service.getSnapshot().status).toBe('idle')
    await service.listRecalls()
    expect(api.getRecalls).toHaveBeenCalledWith({ suppressUnauthorized: false, limit: 500 })
    expect(service.getSnapshot()).toMatchObject({ status: 'ready', unread: 1, isAdminView: false })
    expect(service.getSnapshot().records.map(record => record.id)).toEqual(['n1', 'n2'])
    expect(service.getUnreadCount()).toBe(1)
    expect(listener).toHaveBeenCalled()
  })

  it('records the error in the snapshot and rethrows for the screen', async () => {
    const error = Object.assign(new Error('서버 오류가 발생했습니다.'), { status: 500, code: 'internal' })
    const service = createApiRecallService(fakeApi({ getRecalls: vi.fn(async () => { throw error }) }))
    await expect(service.listRecalls()).rejects.toBe(error)
    expect(service.getSnapshot()).toMatchObject({ status: 'error', error: { status: 500, code: 'internal' } })
  })

  it('loads the unread badge silently without publishing a failure', async () => {
    const getRecalls = vi.fn(async () => { throw Object.assign(new Error('로그인이 필요합니다.'), { status: 401, code: 'unauthorized' }) })
    const service = createApiRecallService(fakeApi({ getRecalls }))
    const listener = vi.fn()
    service.subscribe(listener)
    await service.loadUnread()
    expect(getRecalls).toHaveBeenCalledWith({ suppressUnauthorized: true, limit: 500 })
    expect(listener).not.toHaveBeenCalled()
    expect(service.getSnapshot().status).toBe('idle')
  })

  it('fetches candidates separately when an admin list omits them', async () => {
    const api = fakeApi({ getRecalls: vi.fn(async () => ({ items: [], unread: 0, review_queue: [] })) })
    const service = createApiRecallService(api)
    await service.listRecalls()
    expect(api.getMaintenanceCandidates).toHaveBeenCalledOnce()
    expect(service.getSnapshot().candidates[0].id).toBe('c1')
  })

  it('acknowledges a notice and lowers the unread count once', async () => {
    const api = fakeApi()
    const service = createApiRecallService(api)
    await service.listRecalls()
    const record = await service.acknowledgeRecall('n1')
    expect(api.acknowledgeRecall).toHaveBeenCalledWith('n1')
    expect(record.acked).toBe(true)
    expect(service.getSnapshot().unread).toBe(0)
    await service.acknowledgeRecall('n1')
    expect(service.getSnapshot().unread).toBe(0)
  })

  it('propagates not_found from acknowledge without changing the list', async () => {
    const error = Object.assign(new Error('알림을 찾을 수 없습니다.'), { status: 404, code: 'not_found' })
    const service = createApiRecallService(fakeApi({ acknowledgeRecall: vi.fn(async () => { throw error }) }))
    await service.listRecalls()
    await expect(service.acknowledgeRecall('n1')).rejects.toBe(error)
    expect(service.getSnapshot().unread).toBe(1)
  })

  it('sends feedback and stores the result on the notice', async () => {
    const api = fakeApi()
    const service = createApiRecallService(api)
    await service.listRecalls()
    await service.sendFeedback('n1', { useful: false, reason: '  이미 알고 있습니다.  ' })
    expect(api.sendRecallFeedback).toHaveBeenCalledWith('n1', false, '이미 알고 있습니다.')
    expect(service.getSnapshot().records[0].feedback).toEqual({ useful: false, counts: { not_useful: 1 } })
    await service.sendFeedback('n2', { useful: true, reason: '' })
    expect(api.sendRecallFeedback).toHaveBeenLastCalledWith('n2', true, null)
  })

  it('removes a reviewed notice from the admin queue', async () => {
    const api = fakeApi({ getRecalls: vi.fn(async () => ({ items: [], unread: 0, review_queue: [notice({ notice_id: 'q1' }), notice({ notice_id: 'q2' })], candidates: [] })) })
    const service = createApiRecallService(api)
    await service.listRecalls()
    await service.reviewRecall('q1', 'release')
    expect(api.reviewRecall).toHaveBeenCalledWith('q1', 'release')
    expect(service.getSnapshot().reviewQueue.map(record => record.id)).toEqual(['q2'])
    await expect(service.reviewRecall('q2', 'approve')).rejects.toThrow()
  })

  it('records a candidate decision from the server response', async () => {
    const api = fakeApi({ getRecalls: vi.fn(async () => ({ items: [], unread: 0, review_queue: [], candidates: [candidate()] })) })
    const service = createApiRecallService(api)
    await service.listRecalls()
    await service.decideCandidate('c1', 'needed')
    expect(api.decideMaintenanceCandidate).toHaveBeenCalledWith('c1', 'needed')
    expect(service.getSnapshot().candidates[0]).toMatchObject({ status: 'needed', decidedBy: 'admin-1' })
    await expect(service.decideCandidate('c1', 'maybe')).rejects.toThrow()
  })

  it('loads digests and runs the impact preview', async () => {
    const api = fakeApi()
    const service = createApiRecallService(api)
    await service.listDigests()
    expect(service.getSnapshot().digests[0]).toMatchObject({ day: '2026-11-03', count: 2 })
    const result = await service.previewImpact({ changes: [] })
    expect(api.postImpactPreview).toHaveBeenCalledWith({ changes: [] })
    expect(result.markdown).toContain('무효 답변 3건')
  })

  it('reads the digests key the server returns and keeps count from the server (H-11)', async () => {
    const api = fakeApi({ getRecallDigests: vi.fn(async () => ({ digests: [{ digest_id: 'd1', user_id: 'u1', day: '2026-11-03', count: 2, notice_ids: ['n1', 'n2'], created_at: '2026-11-03T00:00:00Z' }] })) })
    const service = createApiRecallService(api)
    await service.listRecalls()
    const digests = await service.listDigests()
    expect(digests).toHaveLength(1)
    expect(digests[0]).toMatchObject({ id: 'd1', day: '2026-11-03', count: 2, high: null, low: null })
  })

  it('does not swallow a digest load failure (H-11)', async () => {
    const api = fakeApi({ getRecallDigests: vi.fn(async () => { throw new Error('boom') }) })
    await expect(createApiRecallService(api).listDigests()).rejects.toThrow('boom')
  })

  it('leaves the preview service without live-only actions', () => {
    expect(previewRecallService.live).toBe(false)
    expect(previewRecallService.sendFeedback).toBeNull()
    expect(previewRecallService.reviewRecall).toBeNull()
  })
})

describe('recall list limit and changed text (A2, A7)', () => {
  it('computes changedText from old_text and new_text', () => {
    expect(mapNotice(notice()).changedText).toBe('전에 보안 검토를 완료해야')
    expect(mapNotice(notice({ old_text: null })).changedText).toBeNull()
  })
  it('flags a truncated list only when the server returned the 500-item cap', async () => {
    const full = Array.from({ length: 500 }, (_, i) => notice({ notice_id: `n${i}` }))
    const capped = createApiRecallService(fakeApi({ getRecalls: vi.fn(async () => ({ items: full, unread: 3 })) }))
    await capped.listRecalls()
    expect(capped.getSnapshot().truncated).toBe(true)
    const small = createApiRecallService(fakeApi())
    await small.listRecalls()
    expect(small.getSnapshot().truncated).toBe(false)
  })
})
