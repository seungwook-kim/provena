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

// 서버 시각(ISO)을 서울 시간으로 보인다. 승인함(ApprovalsLivePage)이 쓴다.
export function formatServerTime(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
