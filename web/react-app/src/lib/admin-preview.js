// Development-only administrator fixtures. This module has no API side effects.
const INITIAL_DECISION_TABLES = [
  { id: 'decision-1', title: '권한 변경 결정표', status: 'pending', document: 'Access Management', requestedAt: '2026-10-28', approvalId: 'approval-1' },
  { id: 'decision-2', title: '사고 대응 결정표', status: 'approved', document: 'Incident Management', requestedAt: '2026-10-26', approvalId: null },
  { id: 'decision-3', title: '변경 관리 결정표', status: 'rejected', document: 'Change Management', requestedAt: '2026-10-21', approvalId: null },
]

const INITIAL_MAINTENANCE_CANDIDATES = [
  { id: 'candidate-1', document: 'HackerOne Process', relatedPolicy: 'Engaging with Security', changedContent: 'CVE 공개 기한 섹션의 참조 관계', reason: '상위 정책 개정으로 관련 문서의 참조 관계를 다시 확인해야 합니다.', decision: null, decidedReason: null },
  { id: 'candidate-2', document: 'Incident Management', relatedPolicy: 'Incident Management', changedContent: 'IMOC 책임 섹션의 참조 관계', reason: '변경된 책임 섹션이 관련 문서에 반영되었는지 검토가 필요합니다.', decision: null, decidedReason: null },
]

const clone = value => structuredClone(value)
let snapshot = { decisionTables: clone(INITIAL_DECISION_TABLES), candidates: clone(INITIAL_MAINTENANCE_CANDIDATES) }
const listeners = new Set()
const publish = () => listeners.forEach(listener => listener())

export const getPreviewAdminSnapshot = () => snapshot
export const getPreviewDecisionTables = () => clone(snapshot.decisionTables)
export const getPreviewDecisionTable = id => clone(snapshot.decisionTables.find(item => item.id === id) ?? null)
export const filterPreviewDecisionTables = (items, status) => status === 'all' ? items : items.filter(item => item.status === status)
export const getPreviewMaintenanceCandidates = () => clone(snapshot.candidates)
export const getPreviewMaintenanceCandidate = id => clone(snapshot.candidates.find(item => item.id === id) ?? null)
export const judgePreviewMaintenanceCandidate = (id, { decision, reason }) => {
  if (decision !== 'needs_review' && decision !== 'not_needed') throw new Error('허용되지 않은 판단 상태입니다.')
  const candidate = snapshot.candidates.find(item => item.id === id)
  if (!candidate || candidate.decision) throw new Error('이미 처리되었거나 찾을 수 없는 후보입니다.')
  snapshot = { ...snapshot, candidates: snapshot.candidates.map(item => item.id === id ? { ...item, decision, decidedReason: reason || null } : item) }
  publish()
  return getPreviewMaintenanceCandidate(id)
}
export const subscribePreviewAdmin = listener => { listeners.add(listener); return () => listeners.delete(listener) }
