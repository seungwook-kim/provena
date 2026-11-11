import * as apiClient from './api'
import { formatDateTime, mapCandidate } from './recall-service'
import {
  filterPreviewDecisionTables,
  getPreviewAdminSnapshot,
  getPreviewDecisionTable,
  getPreviewDecisionTables,
  getPreviewMaintenanceCandidate,
  getPreviewMaintenanceCandidates,
  judgePreviewMaintenanceCandidate,
  subscribePreviewAdmin,
} from './admin-preview'

// Keep this API-shaped boundary when replacing preview data with server data.
export function createAdminService(adapter) {
  return {
    listDecisionTables: () => adapter.listDecisionTables(),
    getDecisionTable: id => adapter.getDecisionTable(id),
    filterDecisionTables: (items, status) => adapter.filterDecisionTables(items, status),
    listMaintenanceCandidates: () => adapter.listMaintenanceCandidates(),
    getMaintenanceCandidate: id => adapter.getMaintenanceCandidate(id),
    judgeMaintenanceCandidate: (id, decision) => adapter.judgeMaintenanceCandidate(id, decision),
    getSnapshot: () => adapter.getSnapshot(),
    subscribe: listener => adapter.subscribe(listener),
  }
}

export const previewAdminService = createAdminService({
  listDecisionTables: async () => getPreviewDecisionTables(),
  getDecisionTable: async id => getPreviewDecisionTable(id),
  filterDecisionTables: (items, status) => filterPreviewDecisionTables(items, status),
  listMaintenanceCandidates: async () => getPreviewMaintenanceCandidates(),
  getMaintenanceCandidate: async id => getPreviewMaintenanceCandidate(id),
  judgeMaintenanceCandidate: async (id, decision) => judgePreviewMaintenanceCandidate(id, decision),
  getSnapshot: () => getPreviewAdminSnapshot(),
  subscribe: listener => subscribePreviewAdmin(listener),
})

// ---- API adapter -------------------------------------------------------------------------
// 운영 현황(/admin) 화면이 쓰는 실제 API 연결.
// - GET /decision-tables: 승인된 결정표만 준다 (backend/graph/decision/routes.py DecisionTableItem).
// - GET /approvals: 승인 대기 건. kind가 decision_table인 건이 "승인 대기" 결정표다 (ApprovalView).
// - GET, POST /maintenance-candidates: 정비 후보와 판단 (backend/graph/recall/service.py candidate_json).
// 반려된 결정표를 주는 목록 API는 없어서 이 화면에 나오지 않는다.

const CANDIDATE_DECISION = { needed: 'needs_review', not_needed: 'not_needed' }
const CANDIDATE_STATUS = { needs_review: 'needed', not_needed: 'not_needed' }
// 백엔드 결정표 상태는 draft | approved | rejected (backend/schemas/decision.py), 화면 상태는 pending | approved | rejected 다.
const TABLE_STATUS = { draft: 'pending', approved: 'approved', rejected: 'rejected' }
const NETWORK_ERROR = '서버에 연결하지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.'

export function mapApprovedDecisionTable(item = {}) {
  const category = typeof item?.category === 'string' ? item.category : ''
  const cells = Array.isArray(item?.cells) ? item.cells : []
  const source = [item?.rule_seq == null ? null : `문서 번호 ${item.rule_seq}`, item?.version_id ? `판 ${item.version_id}` : null, `구간 ${cells.length}개`]
  return {
    id: item?.table_id == null ? '' : String(item.table_id),
    title: category ? `${category} 결정표` : '결정표',
    status: TABLE_STATUS[item?.status] ?? 'approved',   // 이 목록은 승인된 표만 준다. 모르는 값은 목록의 뜻대로 승인 완료로 본다
    document: source.filter(Boolean).join(' · '),
    requestedAt: '—',   // 승인된 표 목록에는 날짜 칸이 없다
    approvalId: null,
  }
}

export function mapPendingDecisionApproval(item = {}) {
  return {
    id: `approval:${item?.approval_id ?? ''}`,
    title: typeof item?.summary === 'string' && item.summary ? item.summary : '결정표 승인 요청',
    status: 'pending',
    document: '승인 전 초안',
    requestedAt: formatDateTime(item?.created_at) || '—',
    approvalId: item?.approval_id == null ? null : String(item.approval_id),
  }
}

export function mapAdminCandidate(raw = {}) {
  const candidate = mapCandidate(raw)
  return {
    id: candidate.id,
    document: candidate.article || '연결 정책',
    relatedPolicy: `바뀐 정책: ${candidate.upperRule || '정보 없음'}`,
    changedContent: candidate.ruleSeq ? `문서 번호 ${candidate.ruleSeq}` : '문서 번호 없음',
    reason: candidate.reason || '사유가 기록되지 않았습니다.',
    decision: CANDIDATE_DECISION[candidate.status] ?? null,
    decidedBy: candidate.decidedBy,
  }
}

export function describeAdminError(error, fallback = '데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.') {
  if (!(error instanceof apiClient.ApiError)) return NETWORK_ERROR
  if (error.status === 401) return '로그인이 필요합니다.'
  if (error.status === 403) return '관리자만 볼 수 있는 데이터입니다. 권한을 확인해 주세요.'
  if (error.status >= 500) return '서버 오류로 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
  return error.message || fallback
}

const INITIAL_LIVE_STATE = Object.freeze({ status: 'idle', decisionTables: [], candidates: [], tablesError: '', candidatesError: '' })

export function createApiAdminService(api = apiClient) {
  let snapshot = INITIAL_LIVE_STATE
  let loading = null
  const listeners = new Set()
  const update = patch => { snapshot = { ...snapshot, ...patch }; listeners.forEach(listener => listener()) }

  async function loadTables() {
    const [tables, approvals] = await Promise.all([api.getDecisionTables(), api.getApprovals()])
    if (!Array.isArray(tables) || !Array.isArray(approvals)) throw new apiClient.ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', 200, 'invalid_response')
    const pending = approvals.filter(item => item?.kind === 'decision_table').map(mapPendingDecisionApproval)
    return [...pending, ...tables.map(mapApprovedDecisionTable)]
  }

  async function loadCandidates() {
    const response = await api.getMaintenanceCandidates()
    if (!Array.isArray(response?.items)) throw new apiClient.ApiError('서버 응답 형식이 올바르지 않습니다. 잠시 후 다시 시도해 주세요.', 200, 'invalid_response')
    return response.items.map(mapAdminCandidate)
  }

  return {
    live: true,
    // 결정표와 정비 후보를 따로 불러 한쪽이 실패해도 다른 쪽은 보인다. 실패는 빈 목록이 아니라 오류로 남긴다.
    load() {
      if (loading) return loading
      update({ status: 'loading' })
      loading = Promise.allSettled([loadTables(), loadCandidates()]).then(([tables, candidates]) => {
        update({
          status: 'ready',
          decisionTables: tables.status === 'fulfilled' ? tables.value : [],
          tablesError: tables.status === 'fulfilled' ? '' : describeAdminError(tables.reason),
          candidates: candidates.status === 'fulfilled' ? candidates.value : [],
          candidatesError: candidates.status === 'fulfilled' ? '' : describeAdminError(candidates.reason),
        })
      }).finally(() => { loading = null })
      return loading
    },
    filterDecisionTables: (items, status) => status === 'all' ? items : items.filter(item => item.status === status),
    async judgeMaintenanceCandidate(id, { decision } = {}) {
      const status = CANDIDATE_STATUS[decision]
      if (!status) throw new Error('허용되지 않은 판단 상태입니다.')
      let response
      try {
        response = await api.decideMaintenanceCandidate(id, status)
      } catch (error) {
        if (error instanceof apiClient.ApiError && error.status === 404) throw new Error('정비 후보를 찾을 수 없습니다. 이미 처리되었을 수 있습니다.')
        throw new Error(describeAdminError(error, '판단을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.'))
      }
      const current = snapshot.candidates.find(item => item.id === id)
      const candidate = response && typeof response === 'object' && response.candidate_id != null ? mapAdminCandidate(response) : { ...current, id, decision }
      update({ candidates: snapshot.candidates.map(item => item.id === id ? candidate : item) })
      return candidate
    },
    getSnapshot: () => snapshot,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener) },
  }
}
