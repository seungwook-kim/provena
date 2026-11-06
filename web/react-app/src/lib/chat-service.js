// Stable chat-service boundary. Keep this interface while replacing only the
// adapter implementation when business APIs become available.
export function createChatService(adapter) {
  return {
    listThreads: () => adapter.listThreads(),
    getThread: threadId => adapter.getThread(threadId),
    createConversation: () => adapter.createConversation(),
    sendMessage: ({ threadId, message }) => adapter.sendMessage({ threadId, message }),
    stopMessage: threadId => adapter.stopMessage(threadId),
    searchThreads: query => adapter.searchThreads(query),
    dispose: () => adapter.dispose?.(),
  }
}
