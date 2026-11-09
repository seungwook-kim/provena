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

// Server citations (SSE `citation` and GET /threads/{id}) use rule_title/article/version_date; the panel reads title/path/version.
export function normalizeCitation(citation, index = 0) {
  return { ...citation, id: citation.id ?? citation.chunk_id ?? `citation-${index}`, title: citation.title ?? citation.rule_title ?? '', path: citation.path ?? citation.article ?? '', version: citation.version ?? citation.version_date ?? '' }
}

// GET /threads/{id} sends `messages` (user/assistant pairs); older servers only send `last` ({kind, answer, ...}).
function mapMessage(message, fallbackState = 'done') {
  if (message.role === 'user') return { ...message, text: message.text ?? '' }
  const citations = (Array.isArray(message.citations) ? message.citations : []).filter(citation => citation && typeof citation === 'object').map(normalizeCitation)
  return { ...message, role: 'assistant', text: message.text ?? message.answer ?? '', state: message.state ?? fallbackState, citations }
}

export function mapThreadRecord(record = {}) {
  const last = record.last
  const lastState = record.status === 'pending_approval' || last?.kind === 'approval' ? 'approval' : last?.kind === 'refuse' ? 'no-evidence' : 'done'
  const messages = Array.isArray(record.messages)
    ? record.messages.filter(message => message && typeof message === 'object').map(message => mapMessage(message))
    : last == null
      ? []
      : [mapMessage(typeof last === 'object' ? last : { text: String(last) }, lastState)]
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

function isAbortError(error) {
  return error?.name === 'AbortError' || error?.code === 'ABORT_ERR'
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
      const normalized = normalizeCitation(citation, citations.length)
      const key = citationKey(normalized)
      if (!seen.has(key)) { citations.push(normalized); seen.add(key) }
    }
    draft.citations = citations
  }
  return {
    async listThreads() { const { getThreads } = await import('./api'); threads = mapThreadResponse(await getThreads()); notify(); return structuredClone(threads) },
    // Server copy unless the local one is fresher: streaming now, or already holding a user turn (fetched or sent this session).
    async getThread(id) {
      const streaming = () => [...controllers.values()].some(request => request.activeThreadId === id)
      const local = threads.find(thread => thread.id === id)
      if (local && (streaming() || local.messages?.some(message => message.role === 'user'))) return structuredClone(local)
      const { getThread } = await import('./api')
      const thread = mapThreadRecord(await getThread(id))
      const latest = threads.find(item => item.id === id)
      if (latest && streaming()) return structuredClone(latest)
      threads = latest ? threads.map(item => item.id === id ? { ...item, ...thread } : item) : [thread, ...threads]
      notify()
      return structuredClone(thread)
    },
    async createConversation() { return { id: null, title: '', messages: [] } },
    async sendMessage({ threadId, message }) {
      const { streamChatMessage } = await import('./api')
      const controller = new AbortController(); const streamId = threadId ?? `pending-${Date.now()}`
      const request = { controller, activeThreadId: threadId, cancelled: false }
      controllers.set(streamId, request); onProcessingChange?.(streamId)
      const userMessage = { role: 'user', text: message, timestamp: new Date().toISOString() }
      const answer = { role: 'assistant', text: '', citations: [], state: 'generating', timestamp: new Date().toISOString() }
      const existing = threads.find(thread => thread.id === threadId)
      if (existing) upsert(threadId, { messages: [...(existing.messages ?? []), userMessage, answer] })
      try {
        await streamChatMessage(threadId, message, { signal: controller.signal, onEvent: event => {
          if (request.cancelled || controllers.get(streamId) !== request) return
          const id = event.thread_id ?? threadId
          request.activeThreadId = id
          if (!threads.some(thread => thread.id === id)) threads = [{ id, title: message, messages: [userMessage, answer] }, ...threads]
          const current = threads.find(thread => thread.id === id); const messages = [...(current?.messages ?? [])]
          const draft = messages[messages.length - 1]?.role === 'assistant' ? messages[messages.length - 1] : answer
          if (event.type === 'token') draft.text += event.data?.text ?? ''
          if (event.type === 'citation') addCitations(draft, event.data)
          if (event.type === 'no_results') { draft.state = 'no-evidence'; draft.text = event.data?.message ?? draft.text }
          if (event.type === 'approval_request') draft.state = 'approval'
          if (event.type === 'error') { draft.state = 'error'; draft.error = event.data?.message ?? '채팅 처리 중 오류가 발생했습니다.' }
          if (event.type === 'done') draft.state = 'done'
          if (event.type === 'error') draft.errorCode = event.data?.code
          if (event.type === 'done') {
            if (event.data?.attribution) draft.attribution = event.data.attribution
            if (event.data?.code === 'no_results') {
              draft.state = 'no-evidence'
              draft.text = event.data?.message ?? draft.text
            }
          }
          upsert(id, { title: current?.title ?? message, messages, lastActivityAt: new Date().toISOString() })
        }})
        return { threadId: threadId ?? threads[0]?.id }
      } catch (error) {
        if (!request.cancelled && !isAbortError(error)) throw error
        return { threadId: request.activeThreadId ?? threadId }
      } finally {
        if (controllers.get(streamId) === request) {
          controllers.delete(streamId)
          onProcessingChange?.(null)
        }
      }
    },
    async stopMessage(id) {
      const request = controllers.get(id)
      if (!request) return false
      request.cancelled = true
      request.controller.abort()
      const threadId = request.activeThreadId
      if (threadId) {
        const thread = threads.find(item => item.id === threadId)
        const messages = [...(thread?.messages ?? [])]
        const answer = messages.findLast(message => message.role === 'assistant')
        if (answer?.state === 'generating') {
          answer.state = 'stopped'
          answer.error = '응답 생성을 중단했습니다.'
          upsert(threadId, { messages, lastActivityAt: new Date().toISOString() })
        }
      }
      controllers.delete(id)
      onProcessingChange?.(null)
      return true
    },
    async searchThreads(query) { const q = query.trim().toLowerCase(); return threads.filter(thread => thread.title.toLowerCase().includes(q)) },
    dispose() { controllers.forEach(controller => controller.abort()); controllers.clear() },
  }
}
