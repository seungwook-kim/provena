import {
  acknowledgePreviewRecall,
  filterPreviewRecalls,
  getPreviewRecall,
  getPreviewRecallSnapshot,
  getPreviewRecallUnread,
  getPreviewRecalls,
  subscribePreviewRecalls,
} from './recall-preview-store'

// Keep this contract stable and replace only this adapter when /recalls is available.
export function createRecallService(adapter) {
  return {
    listRecalls: () => adapter.listRecalls(),
    getRecall: id => adapter.getRecall(id),
    acknowledgeRecall: id => adapter.acknowledgeRecall(id),
    getUnreadCount: () => adapter.getUnreadCount(),
    filterRecalls: (records, filter) => adapter.filterRecalls(records, filter),
    getSnapshot: () => adapter.getSnapshot(),
    subscribe: listener => adapter.subscribe(listener),
  }
}

export const previewRecallService = createRecallService({
  listRecalls: async () => getPreviewRecalls(),
  getRecall: async id => getPreviewRecall(id),
  acknowledgeRecall: async id => acknowledgePreviewRecall(id),
  getUnreadCount: () => getPreviewRecallUnread(),
  filterRecalls: (records, filter) => filterPreviewRecalls(records, filter),
  getSnapshot: () => getPreviewRecallSnapshot(),
  subscribe: listener => subscribePreviewRecalls(listener),
})
