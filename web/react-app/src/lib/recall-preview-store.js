// Development-only recall fixtures. This store is never selected by a live API route.
const INITIAL_RECORDS = [
  { id: 'recall-1', title: '제3자 SaaS 도입 검토 절차가 변경되었습니다.', question: '외부 SaaS 도입 전 어떤 검토가 필요한가요?', document: 'Third Party Risk Management', detectedAt: '2026-10-21 09:30', acked: false, conclusionChanged: true, oldAnswer: '구매 담당자의 승인 절차를 진행하면 됩니다.', oldPolicy: '구매 승인 절차를 진행합니다.', newPolicy: '구매 승인 전에 보안 검토와 제3자 위험 평가를 완료해야 합니다.', changedText: '보안 검토와 제3자 위험 평가', sourceUrl: 'https://handbook.gitlab.com/handbook/finance/procurement/' },
  { id: 'recall-2', title: '사고 대응 담당자 안내가 변경되었습니다.', question: '사고가 발생하면 어떤 순서로 대응하나요?', document: 'Incident Management', detectedAt: '2026-10-23 14:10', acked: false, conclusionChanged: false, oldAnswer: '담당자에게 사고 상황을 알립니다.', oldPolicy: '담당자에게 사고 상황을 전달합니다.', newPolicy: '사고 상황을 공유하고 책임자를 지정한 뒤 담당자에게 전달합니다.', changedText: '책임자를 지정', sourceUrl: 'https://handbook.gitlab.com/handbook/engineering/infrastructure/incident-management/' },
]

const clone = value => structuredClone(value)
let records = clone(INITIAL_RECORDS)
let snapshot = createSnapshot(records)
const listeners = new Set()

function createSnapshot(items) {
  const copiedRecords = clone(items)
  return { records: copiedRecords, unread: copiedRecords.filter(record => !record.acked).length }
}

function publish() {
  snapshot = createSnapshot(records)
  listeners.forEach(listener => listener())
}

export const getPreviewRecallSnapshot = () => snapshot
export const getPreviewRecalls = () => snapshot.records
export const getPreviewRecall = id => snapshot.records.find(record => record.id === id) ?? null
export const getPreviewRecallUnread = () => snapshot.unread
export const filterPreviewRecalls = (items, filter) => items.filter(record => {
  if (filter === 'unread') return !record.acked
  if (filter === 'changed') return record.conclusionChanged
  return true
})
export const acknowledgePreviewRecall = id => {
  const target = records.find(record => record.id === id)
  if (!target || target.acked) return getPreviewRecall(id)
  records = records.map(record => record.id === id ? { ...record, acked: true } : record)
  publish()
  return getPreviewRecall(id)
}
export const subscribePreviewRecalls = listener => { listeners.add(listener); return () => listeners.delete(listener) }
