import * as apiClient from './api'
import {
  filterPreviewChanges,
  getPreviewChange,
  getPreviewChangeSnapshot,
  getPreviewChanges,
  getPreviewMonitoringStatus,
  subscribePreviewChangeMonitoring,
  updatePreviewMonitoringStatus,
} from './change-monitoring-preview'
import { formatDateTime, toErrorInfo } from './recall-service'

// Stable API boundary. Pages receive a service built from either the preview or the API adapter.
export function createChangeMonitoringService(adapter) {
  return {
    live: adapter.live === true,
    listChanges: options => adapter.listChanges(options),
    getChange: id => adapter.getChange(id),
    filterChanges: (records, filters) => adapter.filterChanges(records, filters),
    getMonitoringStatus: () => adapter.getMonitoringStatus(),
    updateMonitoringStatus: status => adapter.updateMonitoringStatus(status),
    getSnapshot: () => adapter.getSnapshot(),
    subscribe: listener => adapter.subscribe(listener),
    loadMore: adapter.loadMore ? () => adapter.loadMore() : null,
  }
}

export const previewChangeMonitoringService = createChangeMonitoringService({
  listChanges: async () => getPreviewChanges(),
  getChange: async id => getPreviewChange(id),
  filterChanges: (records, filters) => filterPreviewChanges(records, filters),
  getMonitoringStatus: () => getPreviewMonitoringStatus(),
  updateMonitoringStatus: async status => updatePreviewMonitoringStatus(status),
  getSnapshot: () => getPreviewChangeSnapshot(),
  subscribe: listener => subscribePreviewChangeMonitoring(listener),
})

const CHANGE_TYPE_MAP = { added: 'ADDED', removed: 'REMOVED', modified: 'MODIFIED' }
const CHANGE_SUMMARY = { ADDED: '새 정책 섹션이 추가되었습니다.', REMOVED: '정책 섹션이 삭제되었습니다.', MODIFIED: '정책 섹션 내용이 수정되었습니다.' }
const textOrNull = value => typeof value === 'string' && value.trim() ? value : null

export function mapChangeType(value) {
  return CHANGE_TYPE_MAP[String(value ?? '').toLowerCase()] ?? 'MODIFIED'
}

export function buildRecallLink({ ruleSeq, article }) {
  const params = new URLSearchParams()
  if (ruleSeq) params.set('rule_seq', ruleSeq)
  if (article) params.set('article', article)
  const query = params.toString()
  return `/recalls${query ? `?${query}` : ''}`
}

// 판 날짜 표기. 삭제는 새 판이, 추가는 옛 판이 없으므로 있는 쪽 날짜만 "판에서 삭제/추가"로 말한다(리콜 화면도 같은 말을 쓴다).
export function versionText(oldDate, newDate) {
  const before = textOrNull(oldDate)
  const after = textOrNull(newDate)
  if (before && after) return `${before} 판 → ${after} 판`
  if (before) return `${before} 판에서 삭제`
  if (after) return `${after} 판에서 추가`
  return ''
}

export function describeVersions(oldDate, newDate) {
  const text = versionText(oldDate, newDate)
  return text ? ` (${text})` : ''
}

export function mapChange(change = {}) {
  const type = mapChangeType(change?.change_type)
  const ruleSeq = change?.rule_seq == null || change.rule_seq === '' ? null : String(change.rule_seq)
  const article = textOrNull(change?.article)
  const impacted = Number.isInteger(change?.impacted_answer_count) ? change.impacted_answer_count : null
  const versions = describeVersions(change?.old_version_date, change?.new_version_date)
  const hasDetail = Object.prototype.hasOwnProperty.call(change ?? {}, 'old_text') || Object.prototype.hasOwnProperty.call(change ?? {}, 'new_text')
  return {
    id: change?.event_id == null ? '' : String(change.event_id),
    detectedAt: formatDateTime(change?.created_at),
    createdAt: change?.created_at ?? null,
    type,
    area: article ?? '',
    document: textOrNull(change?.page_title) ?? ruleSeq ?? '정책 문서',
    summary: `${CHANGE_SUMMARY[type]}${versions}`,
    oldPolicy: textOrNull(change?.old_text),
    newPolicy: textOrNull(change?.new_text),
    changedText: null,
    impactedAnswerCount: impacted,
    sourceUrl: textOrNull(change?.source_url),
    recallTo: impacted && impacted > 0 ? buildRecallLink({ ruleSeq, article }) : null,
    ruleSeq,
    article,
    oldVersionDate: change?.old_version_date ?? null,
    newVersionDate: change?.new_version_date ?? null,
    deliveryStatus: ['pending', 'sent', 'failed'].includes(change?.status) ? change.status : null,
    detailLoaded: hasDetail,
  }
}

export function mapLastRun(run) {
  if (!run || typeof run !== 'object') return null
  return {
    runId: run.run_id ?? null,
    status: typeof run.status === 'string' ? run.status : '',
    finishedAt: formatDateTime(run.finished_at),
    toCommit: run.to_commit ?? null,
    listComplete: run.list_complete !== false,
  }
}

export function heldRecordFor(lastRun) {
  if (!lastRun || lastRun.listComplete) return null
  return {
    id: `held-${lastRun.runId ?? 'latest'}`,
    detectedAt: lastRun.finishedAt,
    type: 'HELD',
    area: '자동 수집',
    document: '최근 수집 결과',
    summary: '최근 수집에서 변경 목록을 확정하지 못해 보류되었습니다. 다음 수집에서 다시 확인합니다.',
    held: true,
    detailLoaded: true,
  }
}

// 서버가 센 전체 건수(`counts`: change_type별)를 화면 종류(MODIFIED·ADDED·REMOVED)별로 합친다. 없으면 null(불러온 목록으로 센다).
export function mapTypeCounts(counts) {
  if (!counts || typeof counts !== 'object' || Array.isArray(counts)) return null
  const out = { MODIFIED: 0, ADDED: 0, REMOVED: 0 }
  for (const [key, value] of Object.entries(counts)) {
    if (Number.isInteger(value) && value > 0) out[mapChangeType(key)] += value
  }
  return out
}

export function mapChangesResponse(payload = {}) {
  const items = Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : []
  return {
    records: items.map(mapChange),
    lastRun: mapLastRun(payload?.last_run),
    more: payload?.more === true,
    monitoring: payload?.monitoring === 'paused' ? 'paused' : payload?.monitoring === 'active' ? 'active' : null,
    typeCounts: mapTypeCounts(payload?.counts),
  }
}

export function filterChangeRecords(records, { query = '', types = {} } = {}) {
  const normalized = query.trim().toLowerCase()
  return records.filter(record => types[record.type] !== false && (!normalized || [record.document, record.area, record.ruleSeq].some(value => typeof value === 'string' && value.toLowerCase().includes(normalized))))
}

const PAGE_SIZE = 50
const INITIAL_STATE = Object.freeze({ status: 'idle', records: [], lastRun: null, more: false, monitoring: { status: null }, typeCounts: null, error: null })

export function createApiChangeMonitoringAdapter(api = apiClient, { pageSize = PAGE_SIZE } = {}) {
  let snapshot = INITIAL_STATE
  let changes = []
  let sequence = 0
  const listeners = new Set()
  const withHeld = (items, lastRun) => {
    const held = heldRecordFor(lastRun)
    return held ? [held, ...items] : items
  }
  const update = patch => {
    snapshot = { ...snapshot, ...patch }
    listeners.forEach(listener => listener())
  }

  async function listChanges({ append = false, since } = {}) {
    const request = ++sequence
    update({ status: 'loading', error: null })
    try {
      const mapped = mapChangesResponse(await api.getChanges({ since, limit: pageSize, offset: append ? changes.length : 0 }))
      if (request !== sequence) return snapshot.records
      const known = new Set(changes.map(record => record.id))
      changes = append ? [...changes, ...mapped.records.filter(record => !known.has(record.id))] : mapped.records
      update({ status: 'ready', records: withHeld(changes, mapped.lastRun), lastRun: mapped.lastRun, more: mapped.more, typeCounts: mapped.typeCounts, monitoring: { status: mapped.monitoring ?? snapshot.monitoring.status }, error: null })
      return snapshot.records
    } catch (error) {
      if (request !== sequence) return snapshot.records
      update({ status: 'error', error: toErrorInfo(error) })
      throw error
    }
  }

  return {
    live: true,
    listChanges,
    loadMore: () => listChanges({ append: true }),
    async getChange(id) {
      const held = snapshot.records.find(record => record.id === id && record.held)
      if (held) return held
      const record = { ...mapChange(await api.getChangeDetail(id)), detailLoaded: true }
      const current = changes.find(item => item.id === record.id)
      const merged = current ? { ...current, ...record, impactedAnswerCount: record.impactedAnswerCount ?? current.impactedAnswerCount, recallTo: record.recallTo ?? current.recallTo } : record
      changes = current ? changes.map(item => item.id === record.id ? merged : item) : [...changes, merged]
      update({ records: withHeld(changes, snapshot.lastRun) })
      return merged
    },
    filterChanges: filterChangeRecords,
    getMonitoringStatus: () => snapshot.monitoring.status,
    async updateMonitoringStatus(status) {
      if (status !== 'active' && status !== 'paused') throw new Error('지원하지 않는 감시 상태입니다.')
      const response = await api.putChangeMonitoring(status)
      const next = response?.status === 'active' || response?.status === 'paused' ? response.status : status
      update({ monitoring: { status: next } })
      return next
    },
    async refreshMonitoringStatus() {
      const response = await api.getChangeMonitoring()
      const next = response?.status === 'active' || response?.status === 'paused' ? response.status : snapshot.monitoring.status
      update({ monitoring: { status: next } })
      return next
    },
    getSnapshot: () => snapshot,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener) },
  }
}

export function createApiChangeMonitoringService(api = apiClient, options) {
  return createChangeMonitoringService(createApiChangeMonitoringAdapter(api, options))
}
