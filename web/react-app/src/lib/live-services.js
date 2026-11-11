import { useSyncExternalStore } from 'react'
import { createApiRecallService } from './recall-service'
import { createApiChangeMonitoringService } from './change-monitoring-service'
import { createApiApprovalsService } from './approvals-service'
import { createApiAdminService } from './admin-service'

// API-backed services for the signed-in user. A different user always gets fresh instances,
// so cached notices never leak across accounts.
let cache = { owner: null, recalls: null, changes: null, approvals: null, admin: null }

export function getLiveServices(owner) {
  if (!owner) return null
  if (cache.owner !== owner) cache = { owner, recalls: createApiRecallService(), changes: createApiChangeMonitoringService(), approvals: createApiApprovalsService(), admin: createApiAdminService() }
  return cache
}

export function resetLiveServices() {
  cache = { owner: null, recalls: null, changes: null, approvals: null, admin: null }
}

export function useServiceSnapshot(service) {
  return useSyncExternalStore(service.subscribe, service.getSnapshot, service.getSnapshot)
}
