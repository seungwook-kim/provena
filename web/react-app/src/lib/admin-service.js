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
