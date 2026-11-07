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

export function mapThreadRecord(record = {}) {
  const last = record.last
  const messages = Array.isArray(record.messages)
    ? record.messages
    : last == null
      ? []
      : [typeof last === 'object' ? { role: 'assistant', ...last } : { role: 'assistant', text: String(last) }]
  const lastText = typeof last === 'string' ? last : last?.text ?? last?.answer ?? ''
  return {
    ...record,
    id: record.thread_id ?? record.id,
    title: String(record.title ?? lastText ?? ''),
    lastActivityAt: record.updated_at ?? record.lastActivityAt,
    messages,
  }
}

export function mapThreadResponse(payload) {
  if (Array.isArray(payload)) return payload.map(mapThreadRecord)
  if (Array.isArray(payload?.threads)) return payload.threads.map(mapThreadRecord)
  if (payload && typeof payload === 'object' && (payload.thread_id != null || payload.id != null)) return [mapThreadRecord(payload)]
  return []
}

export function createApiChatAdapter({ onThreadsChange, onProcessingChange } = {}) {
  const controllers = new Map()
  let threads = []
  const notify = () => onThreadsChange?.(structuredClone(threads))
  const upsert = (id, update) => { threads = threads.map(thread => thread.id === id ? { ...thread, ...update } : thread); notify() }
  const citationKey = citation => citation?.id ?? citation?.chunk_id ?? citation?.source_url ?? JSON.stringify(citation)
  const addCitations = (draft, values) => {
    const additions = (Array.isArray(values) ? values : [values]).filter(value => value && typeof value === 'object')
    const citations = [...(draft.citations ?? [])]
    const seen = new Set(citations.map(citationKey))
    for (const citation of additions) {
      const normalized = { id: citation.id ?? citation.chunk_id ?? `citation-${citations.length}`, ...citation }
      const key = citationKey(normalized)
      if (!seen.has(key)) { citations.push(normalized); seen.add(key) }
    }
    draft.citations = citations
  }
  return {
    async listThreads() { const { getThreads } = await import('./api'); threads = mapThreadResponse(await getThreads()); notify(); return structuredClone(threads) },
    async getThread(id) {
      const local = threads.find(thread => thread.id === id)
      if (local) return structuredClone(local)
      const { getThread } = await import('./api')
      return mapThreadRecord(await getThread(id))
    },
    async createConversation() { return { id: null, title: '', messages: [] } },
    async sendMessage({ threadId, message }) {
      const { streamChatMessage } = await import('./api')
      const controller = new AbortController(); const streamId = threadId ?? `pending-${Date.now()}`
      controllers.set(streamId, controller); onProcessingChange?.(streamId)
      const userMessage = { role: 'user', text: message, timestamp: new Date().toISOString() }
      const answer = { role: 'assistant', text: '', citations: [], state: 'generating', timestamp: new Date().toISOString() }
      const existing = threads.find(thread => thread.id === threadId)
      if (existing) upsert(threadId, { messages: [...(existing.messages ?? []), userMessage, answer] })
      try {
        await streamChatMessage(threadId, message, { signal: controller.signal, onEvent: event => {
          const id = event.thread_id ?? threadId
          if (!threads.some(thread => thread.id === id)) threads = [{ id, title: message, messages: [userMessage, answer] }, ...threads]
          const current = threads.find(thread => thread.id === id); const messages = [...(current?.messages ?? [])]
          const draft = messages[messages.length - 1]?.role === 'assistant' ? messages[messages.length - 1] : answer
          if (event.type === 'token') draft.text += event.data?.text ?? ''
          if (event.type === 'citation' || event.type === 'attribution') addCitations(draft, event.data)
          if (event.type === 'no_results') { draft.state = 'no-evidence'; draft.text = event.data?.message ?? draft.text }
          if (event.type === 'approval_request') draft.state = 'approval'
          if (event.type === 'error') { draft.state = 'error'; draft.error = event.data?.message ?? '채팅 처리 중 오류가 발생했습니다.' }
          if (event.type === 'done') draft.state = 'done'
          if (event.type === 'error') draft.errorCode = event.data?.code
          if (event.type === 'done') {
            addCitations(draft, event.data?.attribution)
            if (event.data?.code === 'no_results') {
              draft.state = 'no-evidence'
              draft.text = event.data?.message ?? draft.text
            }
          }
          upsert(id, { title: current?.title ?? message, messages, lastActivityAt: new Date().toISOString() })
        }})
        return { threadId: threadId ?? threads[0]?.id }
      } finally { controllers.delete(streamId); onProcessingChange?.(null) }
    },
    async stopMessage(id) { controllers.get(id)?.abort() },
    async searchThreads(query) { const q = query.trim().toLowerCase(); return threads.filter(thread => thread.title.toLowerCase().includes(q)) },
    dispose() { controllers.forEach(controller => controller.abort()); controllers.clear() },
  }
}
