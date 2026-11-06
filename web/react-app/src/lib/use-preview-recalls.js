import { useSyncExternalStore } from 'react'
import { previewRecallService } from './recall-service'

// Shared React state for the development-only recall route and its navigation badge.
export function usePreviewRecalls() {
  return useSyncExternalStore(previewRecallService.subscribe, previewRecallService.getSnapshot, previewRecallService.getSnapshot)
}
