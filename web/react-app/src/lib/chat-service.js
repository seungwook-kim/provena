// Stable chat-service boundary. Keep this interface while replacing only the
// adapter implementation when business APIs become available.
export function createChatService(adapter) {
  return {
    listThreads: () => adapter.listThreads(),
    getThread: (threadId, options) => adapter.getThread(threadId, options),
    createConversation: () => adapter.createConversation(),
    sendMessage: ({ threadId, message }) => adapter.sendMessage({ threadId, message }),
    stopMessage: threadId => adapter.stopMessage(threadId),
    searchThreads: query => adapter.searchThreads(query),
    dispose: () => adapter.dispose?.() ?? [],
  }
}

// Server citations (SSE `citation` and GET /threads/{id}) use rule_title/article/version_date; the panel reads title/path/version.
// 원문 보기 링크는 https 주소일 때만 근거의 source_url을 쓴다(그 밖은 핸드북 첫 화면, #71 리뷰).
export const DEFAULT_SOURCE_URL = 'https://handbook.gitlab.com/handbook/'
export function citationHref(citation) {
  const url = citation?.source_url
  return typeof url === 'string' && url.startsWith('https://') ? url : DEFAULT_SOURCE_URL
}

export function normalizeCitation(citation, index = 0) {
  return { ...citation, id: citation.id ?? citation.chunk_id ?? `citation-${index}`, title: citation.title ?? citation.rule_title ?? '', path: citation.path ?? citation.article ?? '', version: citation.version ?? citation.version_date ?? '' }
}

// 답 본문 [n]을 본문에 처음 나오는 순서대로 다시 매긴다(H-32 ①). 서버는 근거 목록 순서로 번호를 붙여 본문이 [1][3][2]처럼 뒤섞일 수 있다.
// 화면 표시만 바꾼다: 본문과 근거 목록(칩·패널)의 번호를 같이 바꾸고, 본문에 없는 근거는 뒤에 그대로 둔다. 서버 값·평가 지표는 그대로다.
const FOOTER_MARK = '\n\n기준일 '
export function renumberByAppearance(message) {
  const citations = message?.citations
  const text = message?.text
  if (message?.role !== 'assistant' || message.state === 'generating' || !Array.isArray(citations) || citations.length < 2 || typeof text !== 'string') return message
  const cut = text.lastIndexOf(FOOTER_MARK)
  const body = cut < 0 ? text : text.slice(0, cut)
  const footer = cut < 0 ? '' : text.slice(cut)
  const order = []
  for (const match of body.matchAll(/\[(\d+)\]/g)) {
    const n = Number(match[1])
    if (n >= 1 && n <= citations.length && !order.includes(n)) order.push(n)
  }
  for (let n = 1; n <= citations.length; n += 1) if (!order.includes(n)) order.push(n)
  if (order.every((n, i) => n === i + 1)) return message
  const renumber = new Map(order.map((n, i) => [n, i + 1]))
  const newBody = body.replace(/\[(\d+)\]/g, (whole, digits) => renumber.has(Number(digits)) ? `[${renumber.get(Number(digits))}]` : whole)
  return { ...message, text: newBody + footer, citations: order.map(n => citations[n - 1]) }
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
    // fresh: 화면을 떠난 사이 서버가 이어서 만든 답을 받을 때 로컬 사본을 건너뛴다
    async getThread(id, { fresh = false } = {}) {
      const streaming = () => [...controllers.values()].some(request => request.activeThreadId === id)
      const local = fresh ? null : threads.find(thread => thread.id === id)
      // 승인을 기다리던 대화는 그동안 승인함에서 끝났을 수 있어 서버에서 다시 받는다(H-15)
      const waiting = local?.messages?.some(message => message.role === 'assistant' && message.state === 'approval')
      if (local && (streaming() || (local.messages?.some(message => message.role === 'user') && !waiting))) return structuredClone(local)
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
      // question: 오류 말풍선의 '다시 시도'가 다시 보낼 질문(H-08)
      const answer = { role: 'assistant', text: '', citations: [], state: 'generating', question: message, timestamp: new Date().toISOString() }
      const existing = threads.find(thread => thread.id === threadId)
      if (existing) upsert(threadId, { messages: [...(existing.messages ?? []), userMessage, answer] })
      let finished = false
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
          finished = draft.state !== 'generating'
          upsert(id, { title: current?.title ?? message, messages, lastActivityAt: new Date().toISOString() })
        }})
        // 끝 이벤트(done·error·approval_request·no_results) 없이 스트림이 닫히면 생성 중 말풍선이 남는다 → 아래 오류 처리로 넘긴다(H-08)
        if (!finished && !request.cancelled) throw Object.assign(new Error('응답이 끝나기 전에 연결이 끊겼습니다. 다시 시도해 주세요.'), { code: 'stream_incomplete' })
        return { threadId: threadId ?? threads[0]?.id }
      } catch (error) {
        if (request.cancelled || isAbortError(error)) return { threadId: request.activeThreadId ?? threadId }
        // HTTP 오류(409 approval_pending, 503, 422, 403)는 생성 중 말풍선을 오류로 바꿔 화면에 남긴다(H-08).
        // 말풍선을 둘 대화가 아직 없으면(새 대화 첫 질문) 호출한 쪽이 알리도록 던진다.
        const id = request.activeThreadId ?? threadId
        const messages = [...(threads.find(thread => thread.id === id)?.messages ?? [])]
        const draft = messages.findLast(item => item.role === 'assistant' && item.state === 'generating')
        if (!draft) throw error
        draft.state = 'error'
        // 우리 코드가 만든 오류(ApiError, code가 붙은 오류)만 문구를 그대로 쓴다. 스트림 도중 끊기면 브라우저가 던지는 영어 오류(TypeError 등)는 보이지 않는다.
        draft.error = (error?.name === 'ApiError' || error?.code) && error?.message ? error.message : '채팅 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'
        draft.errorCode = error?.code
        draft.question = message
        upsert(id, { messages, lastActivityAt: new Date().toISOString() })
        return { threadId: id, error: draft.error }
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
    // controllers 값은 AbortController가 아니라 요청 기록 { controller, activeThreadId, cancelled }다.
    // 예전 코드는 기록에 abort()를 불러 TypeError → 답을 받는 중 화면이 내려가면 React가 화면 전체를 지웠다(배포 실측 11/9).
    // 돌려주는 값: 끊은 요청의 대화 id. 서버는 연결이 끊겨도 답을 끝까지 만들어 저장하므로(backend/api/routes.py iterate_in_one_thread)
    // 채팅 화면으로 돌아오면 이 대화를 서버에서 다시 받는다.
    dispose() {
      const active = [...controllers.values()].map(request => request.activeThreadId).filter(Boolean)
      controllers.forEach(request => { request.cancelled = true; request.controller.abort() }); controllers.clear()
      return active
    },
  }
}
