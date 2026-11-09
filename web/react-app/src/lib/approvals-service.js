import {
  decideApproval as decidePreviewApproval,
  getApprovalDetail as getPreviewApprovalDetail,
  getDepartmentReviews as getPreviewDepartmentReviews,
  listApprovals as listPreviewApprovals,
  reviewDepartments,
  submitDepartmentReview as submitPreviewDepartmentReview,
} from './approvals-preview'
import { getApprovals, submitApproval } from './api'

// Stable boundary for the approvals API. Replace only this adapter when the
// backend contract is available; page components should keep this interface.
export function createApprovalsService(adapter) {
  return {
    listApprovals: () => adapter.listApprovals(),
    getApprovalDetail: id => adapter.getApprovalDetail(id),
    getDepartmentReviews: id => adapter.getDepartmentReviews(id),
    submitDepartmentReview: (id, review) => adapter.submitDepartmentReview(id, review),
    decideApproval: (id, decision) => adapter.decideApproval(id, decision),
  }
}

export const previewApprovalsService = createApprovalsService({
  listApprovals: () => listPreviewApprovals(),
  getApprovalDetail: id => getPreviewApprovalDetail(id),
  getDepartmentReviews: id => getPreviewDepartmentReviews(id),
  submitDepartmentReview: (id, review) => submitPreviewDepartmentReview(id, review),
  decideApproval: (id, decision) => decidePreviewApproval(id, decision),
})

function normalizeApiApproval(item) {
  return {
    ...item,
    id: item.id ?? item.approval_id,
    title: item.title ?? item.summary ?? item.approval_id,
    kind: item.kind === 'issue_table' ? 'issue' : item.kind === 'decision_table' ? 'decision' : item.kind,
    status: item.status ?? 'pending',
    at: item.at ?? item.created_at ?? '',
  }
}

// The live route uses only the backend contract. It deliberately does not fall
// back to preview data when the API is unavailable.
export const actualApprovalsService = createApprovalsService({
  async listApprovals() {
    const response = await getApprovals()
    const rows = Array.isArray(response) ? response : response?.approvals
    if (!Array.isArray(rows)) throw new Error('승인 API 응답 형식이 올바르지 않습니다.')
    return rows.map(normalizeApiApproval)
  },
  async getApprovalDetail(id) {
    const rows = await this.listApprovals()
    return rows.find(item => item.id === id) ?? null
  },
  async getDepartmentReviews(id) {
    const item = await this.getApprovalDetail(id)
    return item?.department_reviews ?? {}
  },
  async submitDepartmentReview() {
    throw new Error('부서별 검토 API가 아직 연결되지 않았습니다.')
  },
  async decideApproval(id, decision) {
    if (decision.action === 'revision') throw new Error('보완 요청 API가 아직 연결되지 않았습니다.')
    const updated = await submitApproval(id, decision.action === 'approve', decision.reason ?? '')
    return { ...(updated ?? {}), id, status: decision.action === 'approve' ? 'approved' : 'rejected' }
  },
})

export { reviewDepartments }
