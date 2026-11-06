import { useSyncExternalStore } from 'react'
import { previewChangeMonitoringService } from './change-monitoring-service'

export function usePreviewChangeMonitoring() {
  return useSyncExternalStore(previewChangeMonitoringService.subscribe, previewChangeMonitoringService.getSnapshot, previewChangeMonitoringService.getSnapshot)
}
