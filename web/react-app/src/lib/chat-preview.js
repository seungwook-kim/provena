// Development-only chat adapter. This module must only be selected by the
// development preview route; it does not perform network requests.

const PREVIEW_KB = [
  {
    match: /(위험|공급업체|리스크)/i,
    question: '공급업체를 들이기 전에 어떤 위험을 검토해야 하나요?',
    answer: '구매와 보안 관점에서 데이터 유출, 보안 사고, 업무 연속성, 업체의 법규 준수 위험을 함께 검토합니다. 검토가 끝나기 전에는 계약을 진행하지 않습니다.[1][2]',
    citations: [
      { id: 'risk', title: 'The GitLab Procurement Team', path: 'Third Party Risk Management', version: '2026-10-27', text: 'The procurement team from a compliance and risk perspective has developed a process to handle third party risk.' },
      { id: 'security', title: 'Security Assurance', path: 'Third-party security review', version: '2026-10-27', text: 'Security review is required before third-party services handle company data.' },
    ],
  },
  {
    match: /(기간|며칠|몇 주|얼마|구매)/i,
    question: '소프트웨어 구매 승인은 얼마나 걸리나요?',
    answer: '계약 금액과 검토 범위에 따라 다릅니다. 일반적으로 구매, 보안, IT, 법무 검토가 필요한 경우 2~3주가 걸릴 수 있습니다.[1]',
    citations: [{ id: 'procurement', title: 'Field Marketing and Events', path: 'How Long Does it take to get my New Software Purchase Approved?', version: '2025-10-03', text: 'The negotiation, review and approval cycle typically takes 2-3 weeks based on the scope of the request.' }],
  },
  {
    match: /(IT|설문|질문지)/i,
    question: '소프트웨어 도입 때 IT 검토는 어떻게 받나요?',
    answer: '요청자는 업체의 IT New Software Questionnaire를 작성하도록 하고 구매 요청과 함께 제출해야 합니다. IT 검토가 끝난 뒤 다음 절차로 진행할 수 있습니다.[1]',
    citations: [{ id: 'it-review', title: 'The GitLab Procurement Team', path: 'The Procurement Process · IT Review', version: '2026-10-27', text: 'Requester should have vendor complete the IT New Software Questionnaire and submit with the purchase request.' }],
  },
]

export const PREVIEW_SUGGESTIONS = PREVIEW_KB.map(({ question }) => question)

const NO_EVIDENCE = '현재 확인된 근거만으로는 정확한 답변을 제공하기 어렵습니다.'
const PREVIEW_ERROR = /(오류|error)/i
const newThreadId = () => `preview-${Date.now()}-${Math.random().toString(16).slice(2)}`
const clone = value => structuredClone(value)

// Fixed demo-only conversations make timestamp-dependent UI reproducible.
const PREVIEW_THREADS = [
  {
    id: 'preview-risk',
    title: PREVIEW_KB[0].question,
    lastActivityAt: '2026-10-30T14:03:00+09:00',
    messages: [
      { role: 'user', text: PREVIEW_KB[0].question, timestamp: '2026-10-30T14:02:00+09:00' },
      { role: 'assistant', text: PREVIEW_KB[0].answer, citations: clone(PREVIEW_KB[0].citations), state: 'done', timestamp: '2026-10-30T14:03:00+09:00' },
    ],
  },
  {
    id: 'preview-procurement',
    title: PREVIEW_KB[1].question,
    lastActivityAt: '2026-10-29T16:20:00+09:00',
    messages: [
      { role: 'user', text: PREVIEW_KB[1].question, timestamp: '2026-10-29T16:19:00+09:00' },
      { role: 'assistant', text: PREVIEW_KB[1].answer, citations: clone(PREVIEW_KB[1].citations), state: 'done', timestamp: '2026-10-29T16:20:00+09:00' },
    ],
  },
]

function answerFor(question) {
  const item = PREVIEW_KB.find(entry => entry.question === question) ?? PREVIEW_KB.find(entry => entry.match.test(question))
  return item ? { text: item.answer, citations: clone(item.citations), state: 'done' } : { text: NO_EVIDENCE, citations: [], state: 'no-evidence' }
}

/**
 * In-memory implementation of the future chat service contract.
 * It owns fixture data and simulated generation; the page only renders its state.
 */
export function createPreviewChatAdapter({ onThreadsChange, onProcessingChange }) {
  let threads = clone(PREVIEW_THREADS)
  let timerId = null
  let processingId = null

  const emitThreads = () => onThreadsChange(clone(threads))
  const replaceLastAssistant = (threadId, update) => {
    threads = threads.map(thread => thread.id !== threadId ? thread : {
      ...thread,
      messages: thread.messages.map((message, index) => index === thread.messages.length - 1 ? update(message) : message),
    })
    emitThreads()
  }
  const setProcessing = id => {
    processingId = id
    onProcessingChange(id)
  }

  return {
    async listThreads() { return clone(threads) },
    async getThread(id) { return clone(threads.find(thread => thread.id === id) ?? null) },
    async createConversation() { return null },
    async sendMessage({ threadId, message, retry = false }) {
      const question = message.trim()
      if (!question || processingId) return null

      const id = threadId ?? newThreadId()
      const existing = threads.find(thread => thread.id === id)
      const timestamp = new Date().toISOString()
      const pending = { role: 'assistant', text: '', citations: [], state: 'generating', question, timestamp }
      // '다시 시도'는 실패한 한 턴(질문+오류 말풍선)을 새 턴으로 바꾼다(chat-service.js와 같은 규칙).
      let kept = existing?.messages ?? []
      const failed = kept.at(-1)
      if (retry && failed?.role === 'assistant' && failed.state === 'error' && failed.question === question && kept.at(-2)?.role === 'user') kept = kept.slice(0, -2)
      const nextThread = existing
        ? { ...existing, lastActivityAt: timestamp, messages: [...kept, { role: 'user', text: question, timestamp }, pending] }
        : { id, title: question.slice(0, 28), lastActivityAt: timestamp, messages: [{ role: 'user', text: question, timestamp }, pending] }

      threads = existing ? threads.map(thread => thread.id === id ? nextThread : thread) : [nextThread, ...threads]
      emitThreads()
      setProcessing(id)
      timerId = window.setTimeout(() => {
        if (PREVIEW_ERROR.test(question)) {
          replaceLastAssistant(id, entry => ({ ...entry, state: 'error', error: '답변을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.' }))
        } else {
          replaceLastAssistant(id, entry => ({ ...entry, ...answerFor(question) }))
        }
        timerId = null
        setProcessing(null)
      }, 550)
      return { threadId: id }
    },
    async stopMessage(threadId) {
      if (!processingId || processingId !== threadId) return false
      if (timerId) window.clearTimeout(timerId)
      timerId = null
      replaceLastAssistant(threadId, entry => ({ ...entry, state: 'stopped', error: '답변 생성이 중지되었습니다.' }))
      setProcessing(null)
      return true
    },
    async searchThreads(query) {
      const normalized = query.trim().toLowerCase()
      return clone(threads.filter(thread => thread.title.toLowerCase().includes(normalized)))
    },
    dispose() { if (timerId) window.clearTimeout(timerId) },
  }
}
