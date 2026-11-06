import { useSyncExternalStore } from 'react'
import { previewAdminService } from './admin-service'

export function usePreviewAdmin() {
  return useSyncExternalStore(previewAdminService.subscribe, previewAdminService.getSnapshot, previewAdminService.getSnapshot)
}
