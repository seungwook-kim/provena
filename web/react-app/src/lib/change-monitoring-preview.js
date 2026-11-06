// Development-only policy-change fixtures. No server request is made here.
const INITIAL_CHANGES = [
  { id: 'change-1', detectedAt: '2026-11-03 06:12', type: 'MODIFIED', area: '보안', document: 'Third Party Risk Management', summary: '보안 검토와 제3자 위험 평가 요건이 추가되었습니다.', oldPolicy: '구매 승인 절차를 진행합니다.', newPolicy: '구매 승인 전에 보안 검토와 제3자 위험 평가를 완료해야 합니다.', changedText: '보안 검토와 제3자 위험 평가', impactedAnswerCount: 2, sourceUrl: 'https://handbook.gitlab.com/handbook/finance/procurement/', recallTo: '/demo/recalls' },
  { id: 'change-2', detectedAt: '2026-11-03 06:12', type: 'ADDED', area: '재무', document: 'Procurement Approval Guide', summary: '구매 승인 절차에 새 섹션이 추가되었습니다.', newPolicy: '구매 요청에 필요한 검토 항목을 확인합니다.', changedText: '구매 요청에 필요한 검토 항목', sourceUrl: 'https://handbook.gitlab.com/handbook/finance/procurement/' },
  { id: 'change-3', detectedAt: '2026-11-03 06:13', type: 'REMOVED', area: '인프라', document: 'Legacy Deployment Procedure', summary: '더 이상 사용하지 않는 배포 절차가 삭제되었습니다.', oldPolicy: '기존 배포 절차와 승인 단계를 따릅니다.', changedText: '기존 배포 절차와 승인 단계', impactedAnswerCount: 1, sourceUrl: 'https://handbook.gitlab.com/handbook/engineering/infrastructure/' },
  { id: 'change-4', detectedAt: '2026-11-03 06:14', type: 'HELD', area: '지원', document: 'Knowledge Base Style Guide', summary: '동결 보류 상태로 변경 목록을 확정할 수 없습니다.', sourceUrl: 'https://handbook.gitlab.com/handbook/' },
]

const clone = value => structuredClone(value)
let snapshot = { records: clone(INITIAL_CHANGES), monitoring: { status: 'active' } }
const listeners = new Set()
const publish = () => listeners.forEach(listener => listener())

export const getPreviewChangeSnapshot = () => snapshot
export const getPreviewChanges = () => clone(snapshot.records)
export const getPreviewChange = id => clone(snapshot.records.find(record => record.id === id) ?? null)
export const filterPreviewChanges = (records, { query = '', types = {} } = {}) => {
  const normalized = query.trim().toLowerCase()
  return records.filter(record => types[record.type] !== false && (!normalized || record.document.toLowerCase().includes(normalized)))
}
export const getPreviewMonitoringStatus = () => snapshot.monitoring.status
export const updatePreviewMonitoringStatus = status => {
  if (status !== 'active' && status !== 'paused') return snapshot.monitoring.status
  if (snapshot.monitoring.status === status) return status
  snapshot = { ...snapshot, monitoring: { status } }
  publish()
  return status
}
export const subscribePreviewChangeMonitoring = listener => { listeners.add(listener); return () => listeners.delete(listener) }
