import { describe, expect, it, vi } from 'vitest'
import {
  buildRecallLink,
  createApiChangeMonitoringService,
  filterChangeRecords,
  heldRecordFor,
  mapChange,
  mapChangeType,
  mapChangesResponse,
  previewChangeMonitoringService,
} from './change-monitoring-service'

const change = (overrides = {}) => ({
  event_id: 'e1',
  rule_seq: 'handbook/finance/procurement',
  article: 'Security review',
  page_title: 'Procurement',
  old_version_date: '2024-01-01',
  new_version_date: '2024-03-01',
  change_type: 'modified',
  status: 'sent',
  created_at: '2026-11-03T06:12:00Z',
  source_url: 'https://handbook.gitlab.com/handbook/finance/procurement/',
  impacted_answer_count: 2,
  ...overrides,
})

const listResponse = (overrides = {}) => ({ items: [change(), change({ event_id: 'e2', change_type: 'added', impacted_answer_count: 0, page_title: null })], last_run: { run_id: 'r1', status: 'ok', finished_at: '2026-11-03T06:30:00Z', to_commit: 'abc123', list_complete: true }, more: false, monitoring: 'active', ...overrides })

function fakeApi(overrides = {}) {
  return {
    getChanges: vi.fn(async () => listResponse()),
    getChangeDetail: vi.fn(async id => ({ ...change({ event_id: id }), old_text: '이전 본문', new_text: '새 본문' })),
    getChangeMonitoring: vi.fn(async () => ({ status: 'paused' })),
    putChangeMonitoring: vi.fn(async status => ({ status })),
    ...overrides,
  }
}

describe('change mapping', () => {
  it('maps change types to the screen labels', () => {
    expect(mapChangeType('added')).toBe('ADDED')
    expect(mapChangeType('removed')).toBe('REMOVED')
    expect(mapChangeType('modified')).toBe('MODIFIED')
    expect(mapChangeType('MODIFIED')).toBe('MODIFIED')
  })

  it('maps a change event to the record shape used by the change screen', () => {
    const record = mapChange(change())
    expect(record).toMatchObject({
      id: 'e1',
      type: 'MODIFIED',
      document: 'Procurement',
      area: 'Security review',
      impactedAnswerCount: 2,
      sourceUrl: 'https://handbook.gitlab.com/handbook/finance/procurement/',
      deliveryStatus: 'sent',
      recallTo: '/recalls?rule_seq=handbook%2Ffinance%2Fprocurement&article=Security+review',
      detailLoaded: false,
      oldPolicy: null,
      newPolicy: null,
    })
    expect(record.summary).toContain('2024-01-01 → 2024-03-01')
    expect(record.detectedAt).toMatch(/^2026-11-0\d \d\d:\d\d$/)
  })

  it('falls back to rule_seq for the document and links recalls only when answers are impacted', () => {
    const record = mapChange(change({ page_title: null, impacted_answer_count: 0 }))
    expect(record.document).toBe('handbook/finance/procurement')
    expect(record.recallTo).toBeNull()
    expect(buildRecallLink({ ruleSeq: null, article: null })).toBe('/recalls')
  })

  it('marks detail responses with old and new text', () => {
    const record = mapChange({ ...change(), old_text: '이전 본문', new_text: null })
    expect(record).toMatchObject({ oldPolicy: '이전 본문', newPolicy: null, detailLoaded: true })
  })

  it('turns an incomplete last run into the held notice', () => {
    const mapped = mapChangesResponse(listResponse({ last_run: { run_id: 'r9', status: 'held', finished_at: null, to_commit: null, list_complete: false } }))
    expect(mapped.lastRun.listComplete).toBe(false)
    expect(heldRecordFor(mapped.lastRun)).toMatchObject({ id: 'held-r9', type: 'HELD', held: true })
    expect(heldRecordFor({ listComplete: true })).toBeNull()
    expect(heldRecordFor(null)).toBeNull()
  })

  it('treats empty or missing payloads as no changes', () => {
    expect(mapChangesResponse({})).toEqual({ records: [], lastRun: null, more: false, monitoring: null })
    expect(mapChangesResponse(null).records).toEqual([])
  })

  it('filters by type and searches document, section and rule', () => {
    const records = [mapChange(change()), mapChange(change({ event_id: 'e2', change_type: 'removed', page_title: 'Legacy', article: 'Deploy' }))]
    expect(filterChangeRecords(records, { types: { REMOVED: false } }).map(record => record.id)).toEqual(['e1'])
    expect(filterChangeRecords(records, { query: 'deploy' }).map(record => record.id)).toEqual(['e2'])
    expect(filterChangeRecords(records, { query: 'finance/procurement' })).toHaveLength(2)
  })
})

describe('API change monitoring service', () => {
  it('loads changes with paging parameters and monitoring status', async () => {
    const api = fakeApi()
    const service = createApiChangeMonitoringService(api, { pageSize: 2 })
    await service.listChanges()
    expect(api.getChanges).toHaveBeenCalledWith({ since: undefined, limit: 2, offset: 0 })
    expect(service.getSnapshot()).toMatchObject({ status: 'ready', more: false, monitoring: { status: 'active' } })
    expect(service.getSnapshot().records.map(record => record.id)).toEqual(['e1', 'e2'])
    expect(service.getMonitoringStatus()).toBe('active')
  })

  it('prepends the held notice when the last run list is incomplete', async () => {
    const service = createApiChangeMonitoringService(fakeApi({ getChanges: vi.fn(async () => listResponse({ last_run: { run_id: 'r2', status: 'held', finished_at: '2026-11-03T06:30:00Z', list_complete: false } })) }))
    await service.listChanges()
    expect(service.getSnapshot().records[0]).toMatchObject({ type: 'HELD', id: 'held-r2' })
    expect(service.getSnapshot().records).toHaveLength(3)
  })

  it('appends the next page with the current offset', async () => {
    const getChanges = vi.fn()
      .mockResolvedValueOnce(listResponse({ more: true }))
      .mockResolvedValueOnce({ items: [change({ event_id: 'e3' }), change({ event_id: 'e2' })], last_run: null, more: false, monitoring: 'active' })
    const service = createApiChangeMonitoringService(fakeApi({ getChanges }), { pageSize: 2 })
    await service.listChanges()
    expect(service.getSnapshot().more).toBe(true)
    await service.loadMore()
    expect(getChanges).toHaveBeenLastCalledWith({ since: undefined, limit: 2, offset: 2 })
    expect(service.getSnapshot().records.map(record => record.id)).toEqual(['e1', 'e2', 'e3'])
  })

  it('merges the detail text into the selected change', async () => {
    const api = fakeApi()
    const service = createApiChangeMonitoringService(api)
    await service.listChanges()
    const record = await service.getChange('e1')
    expect(api.getChangeDetail).toHaveBeenCalledWith('e1')
    expect(record).toMatchObject({ oldPolicy: '이전 본문', newPolicy: '새 본문', detailLoaded: true, impactedAnswerCount: 2 })
    expect(service.getSnapshot().records.find(item => item.id === 'e1').newPolicy).toBe('새 본문')
  })

  it('records list errors and rethrows them', async () => {
    const error = Object.assign(new Error('서버 오류가 발생했습니다.'), { status: 500, code: 'internal' })
    const service = createApiChangeMonitoringService(fakeApi({ getChanges: vi.fn(async () => { throw error }) }))
    await expect(service.listChanges()).rejects.toBe(error)
    expect(service.getSnapshot()).toMatchObject({ status: 'error', error: { status: 500 } })
  })

  it('updates the monitoring status through PUT and rejects unknown values', async () => {
    const api = fakeApi()
    const service = createApiChangeMonitoringService(api)
    await service.listChanges()
    await expect(service.updateMonitoringStatus('paused')).resolves.toBe('paused')
    expect(api.putChangeMonitoring).toHaveBeenCalledWith('paused')
    expect(service.getMonitoringStatus()).toBe('paused')
    await expect(service.updateMonitoringStatus('stopped')).rejects.toThrow()
  })

  it('keeps the preview service as a non-live service', () => {
    expect(previewChangeMonitoringService.live).toBe(false)
    expect(previewChangeMonitoringService.loadMore).toBeNull()
  })
})
