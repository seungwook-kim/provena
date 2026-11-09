import * as apiClient from './api'
import {
  acknowledgePreviewRecall,
  filterPreviewRecalls,
  getPreviewRecall,
  getPreviewRecallSnapshot,
  getPreviewRecallUnread,
  getPreviewRecalls,
  subscribePreviewRecalls,
} from './recall-preview-store'

export const JUDGEMENT_FAILED_PREFIX = '[판정 실패, 확인 필요]'

// Keep this contract stable. Pages receive a service built from either the preview or the API adapter.
export function createRecallService(adapter) {
  return {
    live: adapter.live === true,
    listRecalls: options => adapter.listRecalls(options),
    getRecall: id => adapter.getRecall(id),
    acknowledgeRecall: id => adapter.acknowledgeRecall(id),
    getUnreadCount: () => adapter.getUnreadCount(),
    filterRecalls: (records, filter) => adapter.filterRecalls(records, filter),
    getSnapshot: () => adapter.getSnapshot(),
    subscribe: listener => adapter.subscribe(listener),
    loadUnread: () => adapter.loadUnread?.(),
    sendFeedback: adapter.sendFeedback ? (id, feedback) => adapter.sendFeedback(id, feedback) : null,
    reviewRecall: adapter.reviewRecall ? (id, action) => adapter.reviewRecall(id, action) : null,
    listCandidates: adapter.listCandidates ? () => adapter.listCandidates() : null,
    decideCandidate: adapter.decideCandidate ? (id, status) => adapter.decideCandidate(id, status) : null,
    listDigests: adapter.listDigests ? () => adapter.listDigests() : null,
    previewImpact: adapter.previewImpact ? payload => adapter.previewImpact(payload) : null,
  }
}

export const previewRecallService = createRecallService({
  listRecalls: async () => getPreviewRecalls(),
  getRecall: async id => getPreviewRecall(id),
  acknowledgeRecall: async id => acknowledgePreviewRecall(id),
  getUnreadCount: () => getPreviewRecallUnread(),
  filterRecalls: (records, filter) => filterPreviewRecalls(records, filter),
  getSnapshot: () => getPreviewRecallSnapshot(),
  subscribe: listener => subscribePreviewRecalls(listener),
})

const pad = value => String(value).padStart(2, '0')

export function formatDateTime(value) {
  if (typeof value !== 'string' || !value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatConfidence(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  if (value >= 0 && value <= 1) return `${Math.round(value * 100)}%`
  return String(value)
}

const textOrNull = value => typeof value === 'string' && value.trim() ? value : null

export function mapNotice(notice = {}) {
  const changed = notice?.changed && typeof notice.changed === 'object' ? notice.changed : {}
  const rawExplanation = typeof notice?.explanation === 'string' ? notice.explanation : ''
  const needsConfirmation = rawExplanation.trimStart().startsWith(JUDGEMENT_FAILED_PREFIX)
  const article = textOrNull(changed.article)
  const ruleSeq = changed.rule_seq == null || changed.rule_seq === '' ? null : String(changed.rule_seq)
  return {
    id: notice?.notice_id == null ? '' : String(notice.notice_id),
    answerId: notice?.answer_id ?? null,
    threadId: notice?.thread_id ?? null,
    title: article ?? ruleSeq ?? '바뀐 정책 섹션',
    question: typeof notice?.question === 'string' ? notice.question : '',
    document: ruleSeq ?? '',
    detectedAt: formatDateTime(notice?.created_at),
    createdAt: notice?.created_at ?? null,
    acked: notice?.acked === true,
    conclusionChanged: notice?.conclusion_changed === true,
    oldAnswer: typeof notice?.answer_excerpt === 'string' ? notice.answer_excerpt : '',
    oldPolicy: textOrNull(notice?.old_text),
    newPolicy: textOrNull(notice?.new_text),
    changedText: null,
    sourceUrl: textOrNull(notice?.source_url),
    ruleSeq,
    article,
    oldVersionDate: changed.old_version_date ?? null,
    newVersionDate: changed.new_version_date ?? null,
    changeType: changed.change_type ?? null,
    severity: notice?.severity === 'high' || notice?.severity === 'low' ? notice.severity : null,
    confidence: typeof notice?.confidence === 'number' && Number.isFinite(notice.confidence) ? notice.confidence : null,
    needsReview: notice?.needs_review === true,
    explanation: needsConfirmation ? rawExplanation.trimStart().slice(JUDGEMENT_FAILED_PREFIX.length).trim() : rawExplanation,
    needsConfirmation,
    feedback: null,
  }
}

export function mapCandidate(candidate = {}) {
  return {
    id: candidate?.candidate_id == null ? '' : String(candidate.candidate_id),
    upperRule: candidate?.upper_rule ?? '',
    upperVersionId: candidate?.upper_version_id ?? null,
    ruleSeq: candidate?.rule_seq == null ? '' : String(candidate.rule_seq),
    article: candidate?.article ?? '',
    reason: typeof candidate?.reason === 'string' ? candidate.reason : '',
    status: ['pending', 'needed', 'not_needed'].includes(candidate?.status) ? candidate.status : 'pending',
    decidedBy: textOrNull(candidate?.decided_by),
  }
}

export function mapDigest(digest = {}) {
  const notices = Array.isArray(digest?.notices) ? digest.notices.map(mapNotice) : []
  return {
    id: digest?.digest_id == null ? '' : String(digest.digest_id),
    day: typeof digest?.day === 'string' ? digest.day : '',
    count: Number.isFinite(digest?.count) ? digest.count : notices.length,
    high: Number.isFinite(digest?.high) ? digest.high : 0,
    low: Number.isFinite(digest?.low) ? digest.low : 0,
    notices,
  }
}

const listOf = (payload, key) => Array.isArray(payload) ? payload : Array.isArray(payload?.[key]) ? payload[key] : []

export function mapRecallsResponse(payload = {}) {
  const records = listOf(payload, 'items').map(mapNotice)
  return {
    records,
    unread: Number.isInteger(payload?.unread) ? payload.unread : records.filter(record => !record.acked).length,
    reviewQueue: Array.isArray(payload?.review_queue) ? payload.review_queue.map(mapNotice) : [],
    candidates: Array.isArray(payload?.candidates) ? payload.candidates.map(mapCandidate) : null,
    isAdminView: Array.isArray(payload?.review_queue) || Array.isArray(payload?.candidates),
  }
}

export function filterRecallRecords(records, filter) {
  return records.filter(record => {
    if (filter === 'unread') return !record.acked
    if (filter === 'changed') return record.conclusionChanged
    if (filter === 'high') return record.severity === 'high'
    if (filter === 'confirm') return record.needsConfirmation
    return true
  })
}

// Narrow the list to notices caused by one policy change (used by links from the change screen).
export function filterByChange(records, { ruleSeq, article } = {}) {
  if (!ruleSeq && !article) return records
  return records.filter(record => (!ruleSeq || record.ruleSeq === ruleSeq) && (!article || record.article === article))
}

export function describeApiError(error, notFoundMessage = '알림을 찾을 수 없습니다.') {
  if (!error) return ''
  if (error.code === 'not_found' || error.status === 404) return notFoundMessage
  if (error.status === 401 || error.code === 'unauthorized') return '로그인이 필요합니다.'
  if (error.status === 403 || error.code === 'forbidden') return '이 작업을 수행할 권한이 없습니다.'
  return error.message || '요청을 처리할 수 없습니다.'
}

export function parseImpactInput(mode, value) {
  const raw = String(value ?? '').trim()
  if (!raw) throw new Error(mode === 'diff' ? 'diff 내용을 입력해 주세요.' : '바뀐 섹션 목록을 입력해 주세요.')
  if (mode === 'diff') return { diff: raw }
  let parsed
  try { parsed = JSON.parse(raw) } catch { throw new Error('JSON 형식이 올바르지 않습니다.') }
  if (Array.isArray(parsed)) return { changes: parsed }
  if (parsed && Array.isArray(parsed.changes)) return { changes: parsed.changes }
  if (parsed && typeof parsed === 'object') return { changes: [parsed] }
  throw new Error('바뀐 섹션 목록은 배열 또는 changes 배열을 가진 객체여야 합니다.')
}

export const toErrorInfo =error => ({ code: error?.code ?? 'unknown', status: error?.status ?? 0, message: error?.message ?? '' })

const INITIAL_STATE = Object.freeze({ status: 'idle', records: [], unread: 0, reviewQueue: [], candidates: [], digests: [], isAdminView: false, error: null })

export function createApiRecallAdapter(api = apiClient) {
  let snapshot = INITIAL_STATE
  let sequence = 0
  let silentRequest = null
  const listeners = new Set()
  const update = patch => {
    snapshot = { ...snapshot, ...patch }
    listeners.forEach(listener => listener())
  }

  async function listRecalls({ silent = false } = {}) {
    const request = ++sequence
    // A silent (badge) load publishes only a successful result, so it never re-renders the screen mid-flight.
    if (!silent) update({ status: 'loading', error: null })
    try {
      const mapped = mapRecallsResponse(await api.getRecalls({ suppressUnauthorized: silent }))
      if (request !== sequence) return snapshot.records
      let candidates = mapped.candidates ?? snapshot.candidates
      if (mapped.isAdminView && mapped.candidates === null && !silent) {
        try { candidates = listOf(await api.getMaintenanceCandidates(), 'items').map(mapCandidate) } catch { candidates = snapshot.candidates }
      }
      if (request !== sequence) return snapshot.records
      update({ status: 'ready', records: mapped.records, unread: mapped.unread, reviewQueue: mapped.reviewQueue, candidates, isAdminView: mapped.isAdminView, error: null })
      return mapped.records
    } catch (error) {
      if (request !== sequence || silent) return snapshot.records
      update({ status: 'error', error: toErrorInfo(error) })
      throw error
    }
  }

  return {
    live: true,
    listRecalls,
    loadUnread() {
      if (snapshot.status !== 'idle') return Promise.resolve(snapshot.records)
      if (!silentRequest) silentRequest = listRecalls({ silent: true }).finally(() => { silentRequest = null })
      return silentRequest
    },
    async getRecall(id) {
      const record = mapNotice(await api.getRecall(id))
      const before = snapshot.records.find(item => item.id === record.id)
      const records = before ? snapshot.records.map(item => item.id === record.id ? { ...record, feedback: item.feedback } : item) : [...snapshot.records, record]
      let unread = snapshot.unread
      if (before && before.acked !== record.acked) unread = Math.max(0, unread + (record.acked ? -1 : 1))
      update({ records, unread })
      return record
    },
    async acknowledgeRecall(id) {
      const before = snapshot.records.find(record => record.id === id)
      const response = await api.acknowledgeRecall(id)
      const mapped = response && typeof response === 'object' && response.notice_id != null ? mapNotice(response) : { ...(before ?? { id }) }
      const acked = { ...mapped, acked: true, feedback: before?.feedback ?? null }
      update({
        records: snapshot.records.map(item => item.id === id ? acked : item),
        unread: before && !before.acked ? Math.max(0, snapshot.unread - 1) : snapshot.unread,
      })
      return acked
    },
    getUnreadCount: () => snapshot.unread,
    filterRecalls: filterRecallRecords,
    getSnapshot: () => snapshot,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener) },
    async sendFeedback(id, { useful, reason = null } = {}) {
      const response = await api.sendRecallFeedback(id, useful === true, typeof reason === 'string' && reason.trim() ? reason.trim() : null)
      const feedback = {
        useful: typeof response?.useful === 'boolean' ? response.useful : useful === true,
        counts: response?.counts && typeof response.counts === 'object' ? response.counts : null,
      }
      update({ records: snapshot.records.map(record => record.id === id ? { ...record, feedback } : record) })
      return feedback
    },
    async reviewRecall(id, action) {
      if (action !== 'release' && action !== 'dismiss') throw new Error('지원하지 않는 검토 동작입니다.')
      await api.reviewRecall(id, action)
      update({ reviewQueue: snapshot.reviewQueue.filter(record => record.id !== id) })
    },
    async listCandidates() {
      const candidates = listOf(await api.getMaintenanceCandidates(), 'items').map(mapCandidate)
      update({ candidates })
      return candidates
    },
    async decideCandidate(id, status) {
      if (status !== 'needed' && status !== 'not_needed') throw new Error('지원하지 않는 판단 값입니다.')
      const response = await api.decideMaintenanceCandidate(id, status)
      const current = snapshot.candidates.find(candidate => candidate.id === id)
      const candidate = response && typeof response === 'object' && response.candidate_id != null ? mapCandidate(response) : { ...(current ?? mapCandidate({ candidate_id: id })), status }
      update({ candidates: current ? snapshot.candidates.map(item => item.id === id ? candidate : item) : [...snapshot.candidates, candidate] })
      return candidate
    },
    async listDigests() {
      const digests = listOf(await api.getRecallDigests(), 'items').map(mapDigest)
      update({ digests })
      return digests
    },
    async previewImpact(payload) {
      const response = await api.postImpactPreview(payload)
      return { report: response, markdown: typeof response?.markdown === 'string' ? response.markdown : '' }
    },
  }
}

export function createApiRecallService(api = apiClient) {
  return createRecallService(createApiRecallAdapter(api))
}
