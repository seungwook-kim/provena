import {
  decideApproval as decidePreviewApproval,
  getApprovalDetail as getPreviewApprovalDetail,
  getDepartmentReviews as getPreviewDepartmentReviews,
  listApprovals as listPreviewApprovals,
  reviewDepartments,
  submitDepartmentReview as submitPreviewDepartmentReview,
} from './approvals-preview'

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

export { reviewDepartments }
