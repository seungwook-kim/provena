import {
  filterPreviewChanges,
  getPreviewChange,
  getPreviewChangeSnapshot,
  getPreviewChanges,
  getPreviewMonitoringStatus,
  subscribePreviewChangeMonitoring,
  updatePreviewMonitoringStatus,
} from './change-monitoring-preview'

// Stable API boundary. Replace this adapter when change-monitoring APIs exist.
export function createChangeMonitoringService(adapter) {
  return {
    listChanges: () => adapter.listChanges(),
    getChange: id => adapter.getChange(id),
    filterChanges: (records, filters) => adapter.filterChanges(records, filters),
    getMonitoringStatus: () => adapter.getMonitoringStatus(),
    updateMonitoringStatus: status => adapter.updateMonitoringStatus(status),
    getSnapshot: () => adapter.getSnapshot(),
    subscribe: listener => adapter.subscribe(listener),
  }
}

export const previewChangeMonitoringService = createChangeMonitoringService({
  listChanges: async () => getPreviewChanges(),
  getChange: async id => getPreviewChange(id),
  filterChanges: (records, filters) => filterPreviewChanges(records, filters),
  getMonitoringStatus: () => getPreviewMonitoringStatus(),
  updateMonitoringStatus: async status => updatePreviewMonitoringStatus(status),
  getSnapshot: () => getPreviewChangeSnapshot(),
  subscribe: listener => subscribePreviewChangeMonitoring(listener),
})
