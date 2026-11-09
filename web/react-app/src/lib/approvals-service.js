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

// Server adapter: GET /approvals, POST /approvals/{approval_id} (backend/graph/decision/routes.py).
// Items keep the server ApprovalView shape; department reviews have no server API yet.
const unsupported = () => Promise.reject(new Error('부서별 검토 의견은 아직 서버 API가 없습니다.'))
export const liveApprovalsService = createApprovalsService({
  listApprovals: () => getApprovals(),
  getApprovalDetail: unsupported,
  getDepartmentReviews: async () => ({}),
  submitDepartmentReview: unsupported,
  decideApproval: (id, decision) => submitApproval(id, decision),
})

export { reviewDepartments }
