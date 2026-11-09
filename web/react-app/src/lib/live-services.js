import { useSyncExternalStore } from 'react'
import { createApiRecallService } from './recall-service'
import { createApiChangeMonitoringService } from './change-monitoring-service'

// API-backed services for the signed-in user. A different user always gets fresh instances,
// so cached notices never leak across accounts.
let cache = { owner: null, recalls: null, changes: null }

export function getLiveServices(owner) {
  if (!owner) return null
  if (cache.owner !== owner) cache = { owner, recalls: createApiRecallService(), changes: createApiChangeMonitoringService() }
  return cache
}

export function resetLiveServices() {
  cache = { owner: null, recalls: null, changes: null }
}

export function useServiceSnapshot(service) {
  return useSyncExternalStore(service.subscribe, service.getSnapshot, service.getSnapshot)
}
