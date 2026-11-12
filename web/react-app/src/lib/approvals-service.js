import * as apiClient from './api'
import {
  decideApproval as decidePreviewApproval,
  getApprovalDetail as getPreviewApprovalDetail,
  getDepartmentReviews as getPreviewDepartmentReviews,
  listApprovals as listPreviewApprovals,
  reviewDepartments,
  submitDepartmentReview as submitPreviewDepartmentReview,
} from './approvals-preview'
import { formatDateTime } from './recall-service'

// Stable boundary for the approvals API. Pages receive a service built from either
// the preview adapter or the API adapter and keep this interface.
export function createApprovalsService(adapter) {
  return {
    live: adapter.live === true,
    listApprovals: () => adapter.listApprovals(),
    getApprovalDetail: id => adapter.getApprovalDetail(id),
    getDepartmentReviews: adapter.getDepartmentReviews ? id => adapter.getDepartmentReviews(id) : null,
    submitDepartmentReview: adapter.submitDepartmentReview ? (id, review) => adapter.submitDepartmentReview(id, review) : null,
    decideApproval: (id, decision) => adapter.decideApproval(id, decision),
    convertDecisionTable: adapter.convertDecisionTable ? category => adapter.convertDecisionTable(category) : null,
  }
}

export const previewApprovalsService = createApprovalsService({
  listApprovals: () => listPreviewApprovals(),
  getApprovalDetail: id => getPreviewApprovalDetail(id),
  getDepartmentReviews: id => getPreviewDepartmentReviews(id),
  submitDepartmentReview: (id, review) => submitPreviewDepartmentReview(id, review),
  decideApproval: (id, decision) => decidePreviewApproval(id, decision),
})

export { reviewDepartments }

// ---- API adapter -------------------------------------------------------------------------

export const APPROVAL_KIND_MAP = { decision_table: 'decision', issue_table: 'issue', team_review_failed: 'team_failed' }

// After these errors the item was already handled or is gone, so the screen reloads the list.
export const STALE_APPROVAL_ERROR_CODES = ['already_decided', 'conflict', 'not_found']

const list = value => Array.isArray(value) ? value : []
const text = value => typeof value === 'string' ? value : ''
const textOrNull = value => typeof value === 'string' && value.trim() ? value : null
const count = value => Number.isFinite(value) ? value : 0
const httpUrl = value => typeof value === 'string' && /^https?:\/\//i.test(value) ? value : null
const roles = value => list(value).filter(role => typeof role === 'string')

const APPROVAL_ERROR_MESSAGES = {
  comment_required: '원문과 다른 칸이 있는 초안을 승인하려면 사유를 입력해야 합니다.',
  already_decided: '이미 다른 결정이 처리된 요청입니다. 목록을 새로 불러옵니다.',
  conflict: '지금 상태에서는 처리할 수 없는 요청입니다. 목록을 새로 불러옵니다.',
  not_found: '승인 요청을 찾을 수 없습니다. 이미 처리되었을 수 있어 목록을 새로 불러옵니다.',
  forbidden: '이 작업을 수행할 권한이 없습니다. 승인 요청은 관리자만 처리할 수 있습니다.',
  unauthorized: '로그인이 필요합니다.',
  csrf_failed: '보안 확인에 실패했습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.',
  csrf_unavailable: '보안 확인에 실패했습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.',
  save_failed: '결정은 접수되었지만 저장을 끝내지 못했습니다. 같은 결정을 다시 보내면 이어서 처리합니다.',
  approver_missing: '승인한 관리자를 확인할 수 없습니다. 다시 로그인한 뒤 시도해 주세요.',
  approval_id_mismatch: '승인 요청 번호가 맞지 않습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.',
  bad_request: '요청 형식이 올바르지 않습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.',
  bad_format: '요청 형식이 올바르지 않습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.',
  bad_action: '지원하지 않는 처리입니다. 목록을 새로고침한 뒤 다시 시도해 주세요.',
  validation_error: '요청 형식이 올바르지 않습니다. 목록을 새로고침한 뒤 다시 시도해 주세요.',
  not_configured: '승인 저장소를 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
}

export function describeApprovalError(error, fallback = '승인 요청을 처리하지 못했습니다.') {
  if (!error) return ''
  if (APPROVAL_ERROR_MESSAGES[error.code]) return APPROVAL_ERROR_MESSAGES[error.code]
  if (error.status === 401) return APPROVAL_ERROR_MESSAGES.unauthorized
  if (error.status === 403) return APPROVAL_ERROR_MESSAGES.forbidden
  if (error.status === 404) return APPROVAL_ERROR_MESSAGES.not_found
  if (error.status >= 500 || !error.status) return fallback
  return error.message || fallback
}

function localizeError(error, fallback) {
  if (!(error instanceof apiClient.ApiError)) return new apiClient.ApiError(fallback, 0, 'request_failed')
  return new apiClient.ApiError(describeApprovalError(error, fallback), error.status, error.code)
}

function mapComparison(comparison) {
  if (!comparison || typeof comparison !== 'object') return null
  const rows = list(comparison.rows).map(row => ({
    band: text(row?.band),
    bandLabel: textOrNull(row?.band_label) ?? text(row?.band),
    role: text(row?.role),
    approvalType: textOrNull(row?.approval_type),
    sourceValue: text(row?.source_value),
    sourceLine: row?.source_line ?? null,
    expected: text(row?.expected),
    draft: text(row?.draft),
    match: row?.match === true,
  }))
  const extraBands = roles(comparison.extra_bands)
  const mismatchCount = Number.isFinite(comparison.mismatch_count) ? comparison.mismatch_count : rows.filter(row => !row.match).length
  return { rows, extraBands, mismatchCount, sourceCells: count(comparison.source_cells), needsReason: mismatchCount > 0 || extraBands.length > 0 }
}

function mapDraft(draft) {
  if (!Array.isArray(draft)) return null
  return draft.map(rule => ({
    band: text(rule?.band),
    bandLabel: textOrNull(rule?.band_label) ?? text(rule?.band),
    approvers: roles(rule?.approvers),
    financialApprovers: roles(rule?.financial_approvers),
    cooperating: roles(rule?.cooperating_depts),
    rangeNote: textOrNull(rule?.range_note),
  }))
}

function mapIssueTable(table) {
  if (!table || typeof table !== 'object') return null
  return {
    request: text(table.request),
    asOf: textOrNull(table.as_of),
    rows: list(table.rows).map(row => ({
      team: text(row?.team),
      teamLabel: textOrNull(row?.team_label) ?? text(row?.team),
      topic: text(row?.topic),
      issue: text(row?.issue),
      stance: ['allow', 'condition', 'block'].includes(row?.stance) ? row.stance : null,
      confidence: ['high', 'medium', 'low'].includes(row?.confidence) ? row.confidence : null,
      sectionPath: text(row?.section_path),
      versionDate: textOrNull(row?.version_date),
      sourceUrl: httpUrl(row?.source_url),
      conflict: row?.conflict === true,
    })),
    unreviewed: list(table.unreviewed).map(item => ({ team: text(item?.team), teamLabel: textOrNull(item?.team_label) ?? text(item?.team), reason: text(item?.reason) })),
  }
}

export function mapApproval(item = {}) {
  const kind = APPROVAL_KIND_MAP[item?.kind] ?? 'unknown'
  const mapped = {
    id: item?.approval_id == null ? '' : String(item.approval_id),
    kind,
    title: text(item?.summary) || '승인 요청',
    status: 'pending',
    at: formatDateTime(item?.created_at),
    createdAt: item?.created_at ?? null,
    saveFailed: item?.save_failed === true,
    tableId: textOrNull(item?.table_id),
    decision: null,
    issue: null,
    failedTeams: [],
  }
  if (kind === 'decision') {
    const comparison = mapComparison(item?.comparison)
    const draft = mapDraft(item?.draft)
    if (comparison && draft) mapped.decision = { comparison, draft }
  } else if (kind === 'issue') {
    mapped.issue = mapIssueTable(item?.issue_table)
  } else if (kind === 'team_failed') {
    mapped.failedTeams = list(item?.failed_teams).map(team => ({ team: text(team?.team), reason: text(team?.reason), attempts: Number.isFinite(team?.attempts) ? team.attempts : null }))
  }
  mapped.hasDetail = Boolean(mapped.decision || mapped.issue || (kind === 'team_failed' && mapped.failedTeams.length))
  return mapped
}

export function mapDecisionResult(result = {}) {
  return {
    id: result?.approval_id == null ? '' : String(result.approval_id),
    kind: APPROVAL_KIND_MAP[result?.kind] ?? 'unknown',
    status: text(result?.status),
    tableId: textOrNull(result?.table_id),
    decidedBy: textOrNull(result?.decided_by),
    comment: text(result?.comment),
    resolution: textOrNull(result?.resolution),
    nextApproval: result?.next_approval && typeof result.next_approval === 'object' ? { id: String(result.next_approval.approval_id ?? ''), summary: text(result.next_approval.summary) } : null,
  }
}

// 결정표 변환(POST /decision-tables/convert)의 응답. status가 'example'이면 키 없는 데모의 고정 응답이라 승인함에 올라가지 않았다.
export function mapConvertResult(view = {}) {
  return {
    example: view?.status === 'example',
    id: view?.approval_id == null ? '' : String(view.approval_id),
    title: text(view?.summary) || '결정표 초안',
    tableId: textOrNull(view?.table_id),
    draft: mapDraft(view?.draft) ?? [],
  }
}

// 변환 전용 오류 문구. 502·503은 api.js가 서버 문구를 일반 문구로 바꾸므로 detail.reason 코드로 고른다.
const CONVERT_ERROR_MESSAGES = {
  bad_request: '권한표 업무 종류를 입력해 주세요.',
  not_found: '권한표에 그 업무 종류가 없습니다. 이름을 확인해 주세요.',
  draft_unreadable: '초안을 읽지 못해 승인함에 올리지 않았습니다. 잠시 후 다시 시도해 주세요.',
  no_source: '권한표 칸을 읽지 못해 승인함에 올리지 않았습니다.',
  convert_failed: '결정표 초안을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.',
  forbidden: '이 작업을 수행할 권한이 없습니다. 결정표 변환은 관리자만 할 수 있습니다.',
}

export function describeConvertError(error, fallback = '결정표 변환을 처리하지 못했습니다.') {
  if (!error) return ''
  if (CONVERT_ERROR_MESSAGES[error.code]) return CONVERT_ERROR_MESSAGES[error.code]
  // 409(이미 승인된 표가 있음·이미 승인 대기 중)는 서버가 이유를 한국어로 준다
  if (error.status === 409 && error.message) return error.message
  return describeApprovalError(error, fallback)
}

export function toApprovalRequestBody(action, reason = '') {
  const comment = typeof reason === 'string' ? reason.trim() : ''
  if (action === 'approve') return { approve: true, comment }
  if (action === 'reject') return { approve: false, comment }
  if (action === 'revision') throw new Error('보완 요청 API가 아직 연결되지 않았습니다.')
  if (action === 'retry' || action === 'mark_unreviewed') return { action, comment }
  throw new Error('지원하지 않는 처리입니다.')
}

export function createApiApprovalsAdapter(api = apiClient) {
  const listApprovals = async () => {
    try {
      const response = await api.getApprovals()
      const rows = Array.isArray(response) ? response : response?.approvals
      if (!Array.isArray(rows)) throw new Error('승인 API 응답 형식이 올바르지 않습니다.')
      return rows.map(mapApproval)
    } catch (error) {
      throw localizeError(error, '승인 요청을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    }
  }
  return {
    live: true,
    listApprovals,
    // The list response already carries each draft or issue table, and the backend has no per-item endpoint.
    getApprovalDetail: async id => (await listApprovals()).find(item => item.id === id) ?? null,
    async decideApproval(id, { action, reason = '' } = {}) {
      const body = toApprovalRequestBody(action, reason)
      try {
        const result = mapDecisionResult(await api.postApprovalDecision(id, body))
        return result.id ? result : { id, status: action === 'approve' ? 'approved' : 'rejected' }
      } catch (error) {
        throw localizeError(error, '승인 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      }
    },
    async convertDecisionTable(category) {
      try {
        return mapConvertResult(await api.convertDecisionTable(category))
      } catch (error) {
        if (!(error instanceof apiClient.ApiError)) throw new apiClient.ApiError('결정표 변환을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.', 0, 'request_failed')
        throw new apiClient.ApiError(describeConvertError(error), error.status, error.code)
      }
    },
  }
}

export function createApiApprovalsService(api = apiClient) {
  return createApprovalsService(createApiApprovalsAdapter(api))
}

// Keep the historical export as an alias of the canonical live adapter.
export const actualApprovalsService = createApiApprovalsService()

