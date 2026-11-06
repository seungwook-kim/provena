const initialItems = [
  { id: 'approval-1', title: '구매 권한표 변환 검토', kind: 'decision', status: 'pending', at: '2026-11-03 10:20', source: 'Finance Authorization Matrix · 2023-05', original: '25,000달러 이상 구매는 재무 승인과 보안 검토가 필요합니다.', proposed: '25,000달러 이상 · 재무 승인 / 보안 검토', mismatch: '보안 검토 조건이 원문 주석에만 있어 검토가 필요합니다.', url: 'https://handbook.gitlab.com/handbook/finance/' },
  { id: 'approval-2', title: '연결 정책 변경 후보 검토', kind: 'issue', status: 'pending', at: '2026-11-03 09:40', source: 'Change Management', original: '변경 영향 범위와 담당 팀을 확인해야 합니다.', proposed: '연결 정책 후보 3건', mismatch: '영향 범위와 담당 팀의 확인이 필요합니다.', url: 'https://handbook.gitlab.com/handbook/engineering/infrastructure/change-management/' },
]
export const reviewDepartments = [{ id: 'security', name: '보안', question: '보안 검토가 필요한 데이터와 접근 권한이 있나요?' }, { id: 'it', name: 'IT 운영', question: '운영 환경과 지원 범위에 영향이 있나요?' }, { id: 'legal', name: '법무', question: '계약 또는 규제상 확인할 사항이 있나요?' }]
let items = initialItems; let reviewsByApproval = {}
const clone = value => structuredClone(value)
export const listApprovals = async () => clone(items)
export const getApprovalDetail = async id => clone(items.find(item => item.id === id) ?? null)
export const getDepartmentReviews = async id => clone(reviewsByApproval[id] ?? {})
export const submitDepartmentReview = async (id, review) => { reviewsByApproval = { ...reviewsByApproval, [id]: { ...reviewsByApproval[id], [review.departmentId]: review } }; return getDepartmentReviews(id) }
export const decideApproval = async (id, decision) => { const item = items.find(value => value.id === id); if (!item || item.status === 'approved' || item.status === 'rejected') throw new Error('이미 처리되었거나 찾을 수 없는 요청입니다.'); const status = decision.action === 'approve' ? 'approved' : decision.action === 'revision' ? 'revision_requested' : 'rejected'; items = items.map(value => value.id === id ? { ...value, status } : value); return getApprovalDetail(id) }
