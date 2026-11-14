import { describe, expect, it, vi } from 'vitest'
import { streamChatMessage } from './api'
import { createApiChatAdapter, createChatService, mapThreadRecord, normalizeCitation, citationHref, DEFAULT_SOURCE_URL } from './chat-service'

vi.mock('./api', () => ({ getThread: vi.fn(), getThreads: vi.fn(), streamChatMessage: vi.fn() }))

function setup(events) {
  const snapshots = []
  streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => {
    events.forEach(onEvent)
  })
  const adapter = createApiChatAdapter({ onThreadsChange: value => snapshots.push(value) })
  const service = createChatService(adapter)
  return { snapshots, service }
}

describe('createApiChatAdapter event handling', () => {
  it('turns an SSE approval_request event into approval state without losing citations', async () => {
    const citation = { chunk_id: 'c1', title: '원문' }
    const { snapshots, service } = setup([
      { type: 'token', thread_id: 't1', data: { text: '답변' } },
      { type: 'citation', thread_id: 't1', data: citation },
      { type: 'approval_request', thread_id: 't1', data: { code: 'approval_pending' } },
    ])

    await service.sendMessage({ threadId: 't1', message: '질문' })

    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer.state).toBe('approval')
    expect(answer.text).toBe('답변')
    expect(answer.citations).toEqual([expect.objectContaining(citation)])
  })

  it('preserves the limit_exceeded code on error events', async () => {
    const { snapshots, service } = setup([{ type: 'error', thread_id: 't1', data: { code: 'limit_exceeded', message: 'too many requests' } }])
    await service.sendMessage({ threadId: 't1', message: '질문' })
    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer.state).toBe('error')
    expect(answer.errorCode).toBe('limit_exceeded')
  })

  it('marks no_results done events as no-evidence', async () => {
    const { snapshots, service } = setup([{ type: 'done', thread_id: 't1', data: { code: 'no_results', message: '근거 없음' } }])
    await service.sendMessage({ threadId: 't1', message: '질문' })
    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer.state).toBe('no-evidence')
    expect(answer.text).toBe('근거 없음')
    expect('refuseReason' in answer).toBe(false)   // 사유 코드를 주지 않으면 지어내지 않는다
  })

  it('keeps the refusal reason code from the done event (H-34)', async () => {
    const { snapshots, service } = setup([
      { type: 'token', thread_id: 't1', data: { text: '핸드북과 관련 없는 질문이라 답하지 않습니다.' } },
      { type: 'done', thread_id: 't1', data: { kind: 'refuse', code: 'no_results', refuse_stage: 'out_of_domain', refuse_reason: 'out_of_domain' } },
    ])
    await service.sendMessage({ threadId: 't1', message: '질문' })
    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer).toMatchObject({ state: 'no-evidence', refuseReason: 'out_of_domain', text: '핸드북과 관련 없는 질문이라 답하지 않습니다.' })
  })

  it('keeps done attributions separate from citations', async () => {
    const citation = { chunk_id: 'c1', title: '출처' }
    const { snapshots, service } = setup([
      { type: 'citation', thread_id: 't1', data: citation },
      { type: 'done', thread_id: 't1', data: { attribution: [citation, { chunk_id: 'c2', title: '두 번째 출처' }] } },
    ])
    await service.sendMessage({ threadId: 't1', message: '질문' })
    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer.state).toBe('done')
    expect(answer.citations.map(item => item.chunk_id)).toEqual(['c1'])
    expect(answer.attribution).toEqual(expect.anything())
  })

  it('stops an active request, ignores AbortError, and allows a later message', async () => {
    const snapshots = []
    let release
    let lateEvent
    streamChatMessage
      .mockImplementationOnce((_threadId, _message, { signal, onEvent }) => new Promise((resolve, reject) => {
        lateEvent = onEvent
        onEvent({ type: 'token', thread_id: 't1', data: { text: '첫 답변' } })
        release = () => resolve()
        signal.addEventListener('abort', () => reject(Object.assign(new Error('cancelled'), { name: 'AbortError' })), { once: true })
      }))
      .mockImplementationOnce(async (_threadId, _message, { onEvent }) => onEvent({ type: 'done', thread_id: 't1', data: {} }))
    const adapter = createApiChatAdapter({ onThreadsChange: value => snapshots.push(value) })
    const service = createChatService(adapter)

    const first = service.sendMessage({ threadId: 't1', message: '첫 질문' })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(await service.stopMessage('t1')).toBe(true)
    lateEvent({ type: 'token', thread_id: 't1', data: { text: '늦은 토큰' } })
    release()
    await first

    const stopped = snapshots.at(-1)[0].messages.at(-1)
    expect(stopped.state).toBe('stopped')
    expect(stopped.text).toBe('첫 답변')
    await service.sendMessage({ threadId: 't1', message: '두 번째 질문' })
    expect(snapshots.at(-1)[0].messages.at(-1).state).toBe('done')
    expect(snapshots.at(-1)[0].messages.at(-2).text).toBe('두 번째 질문')
  })
})

describe('createApiChatAdapter thread mapping', () => {
  it('maps backend thread fields and preserves a last-only answer', async () => {
    const { getThreads } = await import('./api')
    getThreads.mockResolvedValueOnce([{ thread_id: 't1', title: '정책 질문', updated_at: '2026-11-07T01:02:03Z', last: { text: '마지막 답' } }])
    const updates = []
    const adapter = createApiChatAdapter({ onThreadsChange: value => updates.push(value) })

    const threads = await adapter.listThreads()

    expect(threads[0]).toMatchObject({ id: 't1', title: '정책 질문', lastActivityAt: '2026-11-07T01:02:03Z' })
    expect(threads[0].messages).toEqual([{ role: 'assistant', text: '마지막 답', state: 'done', citations: [] }])
    expect(updates.at(-1)).toEqual(threads)
  })

  it('accepts an object wrapper without requiring a single top-level shape', async () => {
    const { getThreads, getThread } = await import('./api')
    getThreads.mockResolvedValueOnce({ threads: [{ thread_id: 't2', title: '두 번째', updated_at: '2026-11-07T02:00:00Z' }] })
    getThread.mockResolvedValueOnce({ thread_id: 't2', title: '두 번째', updated_at: '2026-11-07T02:00:00Z', last: '답변' })
    const adapter = createApiChatAdapter()

    expect((await adapter.listThreads())[0].id).toBe('t2')
    expect(await adapter.getThread('t2')).toMatchObject({ id: 't2', lastActivityAt: '2026-11-07T02:00:00Z' })
  })
})

describe('thread detail after reload', () => {
  const detail = {
    thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z', last: { kind: 'answer', answer: '15일입니다.' },
    messages: [
      { role: 'user', text: '연차는 며칠인가요?', timestamp: '2026-11-09T00:59:00Z' },
      { role: 'assistant', text: '15일입니다.', state: 'done', kind: 'answer', answer_id: 'a1', as_of: null, citations: [{ chunk_id: 'c1', rule_title: '취업규칙', article: '제10조' }], timestamp: '2026-11-09T01:00:00Z' },
    ],
  }

  it('uses server messages and normalises citation ids', () => {
    const thread = mapThreadRecord(detail)
    expect(thread.messages.map(message => [message.role, message.text])).toEqual([['user', '연차는 며칠인가요?'], ['assistant', '15일입니다.']])
    expect(thread.messages[1]).toMatchObject({ state: 'done', citations: [{ id: 'c1', chunk_id: 'c1', rule_title: '취업규칙' }] })
  })

  it('falls back to last.answer when an older server sends no messages', () => {
    expect(mapThreadRecord({ thread_id: 't1', last: { kind: 'answer', answer: '마지막 답' } }).messages).toEqual([{ role: 'assistant', kind: 'answer', answer: '마지막 답', text: '마지막 답', state: 'done', citations: [] }])
    expect(mapThreadRecord({ thread_id: 't1', last: { kind: 'refuse', answer: '근거 없음' } }).messages[0].state).toBe('no-evidence')
    expect(mapThreadRecord({ thread_id: 't1', status: 'pending_approval', last: { kind: 'answer', answer: '대기' } }).messages[0].state).toBe('approval')
  })

  it('maps refuse_reason on history messages to refuseReason (H-34)', () => {
    const thread = mapThreadRecord({ thread_id: 't1', messages: [
      { role: 'user', text: '질문' },
      { role: 'assistant', text: '거절', state: 'no-evidence', kind: 'refuse', refuse_reason: 'out_of_period' },
      { role: 'assistant', text: '답', state: 'done', kind: 'answer' },
    ] })
    expect(thread.messages[1].refuseReason).toBe('out_of_period')
    expect('refuseReason' in thread.messages[2]).toBe(false)
  })

  it('fetches GET /threads/{id} when the listed thread has no messages and updates the list', async () => {
    const { getThreads, getThread } = await import('./api')
    getThreads.mockResolvedValueOnce([{ thread_id: 't1', title: '연차 질문', updated_at: '2026-11-09T01:00:00Z' }])
    getThread.mockResolvedValueOnce(detail)
    const updates = []
    const adapter = createApiChatAdapter({ onThreadsChange: value => updates.push(value) })
    await adapter.listThreads()
    expect(updates.at(-1)[0].messages).toEqual([])

    const thread = await adapter.getThread('t1')

    expect(getThread).toHaveBeenCalledWith('t1')
    expect(thread.messages).toHaveLength(2)
    expect(updates.at(-1)).toHaveLength(1)
    expect(updates.at(-1)[0].messages.map(message => message.text)).toEqual(['연차는 며칠인가요?', '15일입니다.'])
    getThread.mockClear()
    await adapter.getThread('t1')
    expect(getThread).not.toHaveBeenCalled()
  })

  it('does not overwrite a thread that is streaming', async () => {
    const { getThread } = await import('./api')
    let release
    streamChatMessage.mockImplementationOnce((_threadId, _message, { onEvent }) => new Promise(resolve => { onEvent({ type: 'token', thread_id: 't9', data: { text: '생성 중' } }); release = resolve }))
    getThread.mockClear()
    const adapter = createApiChatAdapter()
    const sending = adapter.sendMessage({ threadId: null, message: '새 질문' })
    await new Promise(resolve => setTimeout(resolve, 0))

    const thread = await adapter.getThread('t9')

    expect(getThread).not.toHaveBeenCalled()
    expect(thread.messages.at(-1)).toMatchObject({ text: '생성 중', state: 'generating' })
    release()
    await sending
  })

  it('maps server citation fields to the panel fields', () => {
    const server = { chunk_id: 'c1', rule_title: '장애 대응 런북', article: 'Incident Response > Paging', version_date: '2025-01-01', source_url: 'https://handbook.gitlab.com/x', text: '본문' }
    expect(normalizeCitation(server)).toMatchObject({ id: 'c1', title: '장애 대응 런북', path: 'Incident Response > Paging', version: '2025-01-01', source_url: 'https://handbook.gitlab.com/x', text: '본문' })
    expect(normalizeCitation({ id: 'p', title: '미리보기', path: '절', version: '2026-10-27' })).toMatchObject({ id: 'p', title: '미리보기', path: '절', version: '2026-10-27' })
    const record = mapThreadRecord({ thread_id: 't', messages: [{ role: 'assistant', text: 'a', citations: [server] }] })
    expect(record.messages[0].citations[0]).toMatchObject({ title: '장애 대응 런북', version: '2025-01-01' })
  })

  it('uses source_url for the original link only when it is https', () => {
    expect(citationHref({ source_url: 'https://handbook.gitlab.com/handbook/x/' })).toBe('https://handbook.gitlab.com/handbook/x/')
    for (const bad of ['http://example.com', 'javascript:alert(1)', '/relative', '', null, undefined, 42]) expect(citationHref({ source_url: bad })).toBe(DEFAULT_SOURCE_URL)
    expect(citationHref(null)).toBe(DEFAULT_SOURCE_URL)
  })
})

// 배포 화면 빈 화면(11/9 실측): 답을 받는 도중 채팅 화면이 내려가면(다른 메뉴 이동 등) dispose()가
// AbortController가 아닌 요청 기록에 abort()를 불러 TypeError → React가 화면 전체를 지웠다.
describe('createApiChatAdapter dispose while streaming', () => {
  it('aborts the in-flight stream without throwing and ignores later events', async () => {
    let signal; let emit
    streamChatMessage.mockImplementationOnce((_threadId, _message, options) => new Promise((_resolve, reject) => {
      signal = options.signal; emit = options.onEvent
      signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
    }))
    const snapshots = []
    const processing = []
    const service = createChatService(createApiChatAdapter({ onThreadsChange: value => snapshots.push(value), onProcessingChange: value => processing.push(value) }))
    const pending = service.sendMessage({ threadId: null, message: '질문' })
    await vi.waitFor(() => expect(signal).toBeDefined())
    emit({ type: 'token', thread_id: 't9', data: { text: '앞부분' } })

    expect(() => service.dispose()).not.toThrow()
    expect(signal.aborted).toBe(true)
    const count = snapshots.length
    emit({ type: 'token', thread_id: 't9', data: { text: '늦게 온 글자' } })
    expect(snapshots.length).toBe(count)
    await expect(pending).resolves.toEqual({ threadId: 't9' })
  })
})

// H-08: 채팅 HTTP 오류(409·503·422·403)가 화면에 남아야 한다
describe('createApiChatAdapter HTTP errors (H-08)', () => {
  const listedThread = { thread_id: 't1', title: '연차 질문', updated_at: '2026-11-09T01:00:00Z', messages: [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }] }

  it('turns a rejected request into an error answer instead of leaving the generating bubble', async () => {
    const { getThreads } = await import('./api')
    const { ApiError } = await vi.importActual('./api')
    getThreads.mockResolvedValueOnce([listedThread])
    streamChatMessage.mockRejectedValueOnce(new ApiError('이전 질문의 승인이 끝나지 않았습니다.', 409, 'approval_pending'))
    const snapshots = []
    const adapter = createApiChatAdapter({ onThreadsChange: value => snapshots.push(value) })
    await adapter.listThreads()

    const result = await adapter.sendMessage({ threadId: 't1', message: '새 질문' })

    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer).toMatchObject({ state: 'error', error: '이전 질문의 승인이 끝나지 않았습니다.', errorCode: 'approval_pending', question: '새 질문' })
    expect(result.error).toBe('이전 질문의 승인이 끝나지 않았습니다.')
  })

  it('still throws when there is no thread yet to show the error in', async () => {
    const { ApiError } = await vi.importActual('./api')
    streamChatMessage.mockRejectedValueOnce(new ApiError('채팅이 설정되지 않았습니다.', 503, 'not_configured'))
    const adapter = createApiChatAdapter()
    await expect(adapter.sendMessage({ threadId: null, message: '첫 질문' })).rejects.toMatchObject({ status: 503 })
  })

  it('turns a stream that closes without an end event into an error answer, keeping the partial text', async () => {
    const { snapshots, service } = setup([{ type: 'token', thread_id: 't1', data: { text: '답변 일부' } }])
    const result = await service.sendMessage({ threadId: 't1', message: '질문' })
    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer).toMatchObject({ state: 'error', errorCode: 'stream_incomplete', text: '답변 일부', question: '질문' })
    expect(answer.error).toContain('연결이 끊겼습니다')
    expect(result).toMatchObject({ threadId: 't1', error: answer.error })
  })

  it('turns a stream that closes with no event at all into an error answer in the open thread', async () => {
    const { getThreads } = await import('./api')
    getThreads.mockResolvedValueOnce([listedThread])
    streamChatMessage.mockImplementationOnce(async () => {})
    const snapshots = []
    const adapter = createApiChatAdapter({ onThreadsChange: value => snapshots.push(value) })
    await adapter.listThreads()
    await adapter.sendMessage({ threadId: 't1', message: '새 질문' })
    expect(snapshots.at(-1)[0].messages.at(-1)).toMatchObject({ state: 'error', errorCode: 'stream_incomplete', question: '새 질문' })
  })

  it('throws when a brand-new conversation stream closes with no event (no bubble to mark)', async () => {
    streamChatMessage.mockImplementationOnce(async () => {})
    const adapter = createApiChatAdapter()
    await expect(adapter.sendMessage({ threadId: null, message: '첫 질문' })).rejects.toMatchObject({ code: 'stream_incomplete' })
  })

  it('does not mark a stream that ended with done as an error', async () => {
    const { snapshots, service } = setup([{ type: 'token', thread_id: 't1', data: { text: '답' } }, { type: 'done', thread_id: 't1', data: {} }])
    const result = await service.sendMessage({ threadId: 't1', message: '질문' })
    expect(snapshots.at(-1)[0].messages.at(-1).state).toBe('done')
    expect(result.error).toBeUndefined()
  })

  it('keeps the question on a streamed error event so retry can resend it', async () => {
    const { snapshots, service } = setup([{ type: 'error', thread_id: 't1', data: { code: 'limit_exceeded', message: 'x' } }])
    await service.sendMessage({ threadId: 't1', message: '질문' })
    expect(snapshots.at(-1)[0].messages.at(-1).question).toBe('질문')
  })

  // 새로 발견 7: 같은 오류에 '다시 시도'를 거듭 눌러도 실패한 턴은 한 쌍(질문+오류 말풍선)만 남는다
  it('replaces the failed turn on retry instead of stacking another error bubble', async () => {
    const fail = { type: 'error', thread_id: 't1', data: { code: 'limit_exceeded', message: 'x' } }
    const { snapshots, service } = setup([fail])
    await service.sendMessage({ threadId: 't1', message: '질문' })
    expect(snapshots.at(-1)[0].messages).toHaveLength(2)
    for (let i = 0; i < 3; i += 1) {
      streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => { onEvent(fail) })
      await service.sendMessage({ threadId: 't1', message: '질문', retry: true })
    }
    const messages = snapshots.at(-1)[0].messages
    expect(messages).toHaveLength(2)
    expect(messages.map(message => message.role)).toEqual(['user', 'assistant'])
    expect(messages[1].state).toBe('error')
  })

  it('keeps earlier turns and a fresh send still appends a new turn', async () => {
    const { snapshots, service } = setup([{ type: 'done', thread_id: 't1', data: {} }])
    await service.sendMessage({ threadId: 't1', message: '앞 질문' })
    streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => { onEvent({ type: 'error', thread_id: 't1', data: { message: 'x' } }) })
    await service.sendMessage({ threadId: 't1', message: '다음 질문' })
    streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => { onEvent({ type: 'error', thread_id: 't1', data: { message: 'x' } }) })
    await service.sendMessage({ threadId: 't1', message: '다음 질문', retry: true })
    expect(snapshots.at(-1)[0].messages).toHaveLength(4)
    streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => { onEvent({ type: 'error', thread_id: 't1', data: { message: 'x' } }) })
    await service.sendMessage({ threadId: 't1', message: '새 질문' })
    expect(snapshots.at(-1)[0].messages).toHaveLength(6)
  })
})

// H-15: 승인이 끝난 대화는 다시 열 때 서버 상태를 받아와야 한다
describe('thread with a finished approval (H-15)', () => {
  it('refetches a thread whose local copy still waits for approval', async () => {
    const { getThreads, getThread } = await import('./api')
    getThreads.mockResolvedValueOnce([{ thread_id: 't1', title: '승인 질문', updated_at: '2026-11-09T01:00:00Z' }])
    getThread.mockResolvedValueOnce({ thread_id: 't1', title: '승인 질문', messages: [{ role: 'user', text: '질문' }, { role: 'assistant', text: '', state: 'approval' }] })
    getThread.mockResolvedValueOnce({ thread_id: 't1', title: '승인 질문', messages: [{ role: 'user', text: '질문' }, { role: 'assistant', text: '승인된 답', state: 'done' }] })
    const adapter = createApiChatAdapter()
    await adapter.listThreads()
    expect((await adapter.getThread('t1')).messages.at(-1).state).toBe('approval')

    const again = await adapter.getThread('t1')

    expect(again.messages.at(-1)).toMatchObject({ state: 'done', text: '승인된 답' })
  })
})

// M4: 중지한 답은 서버가 끝까지 만들어 저장하므로 다시 열 때 서버본으로 바꾼다
describe('thread with a stopped answer (M4)', () => {
  it('refetches a thread whose local copy ends with a stopped answer', async () => {
    const { getThreads, getThread } = await import('./api')
    getThreads.mockResolvedValueOnce([{ thread_id: 't1', title: '중지 질문', updated_at: '2026-11-09T01:00:00Z' }])
    getThread.mockReset()
    getThread.mockResolvedValueOnce({ thread_id: 't1', title: '중지 질문', messages: [{ role: 'user', text: '질문' }, { role: 'assistant', text: '앞부분', state: 'stopped' }] })
    getThread.mockResolvedValueOnce({ thread_id: 't1', title: '중지 질문', messages: [{ role: 'user', text: '질문' }, { role: 'assistant', text: '서버가 끝낸 답', state: 'done' }] })
    const adapter = createApiChatAdapter()
    await adapter.listThreads()
    expect((await adapter.getThread('t1')).messages.at(-1).state).toBe('stopped')

    const again = await adapter.getThread('t1')

    expect(getThread).toHaveBeenCalledTimes(2)
    expect(again.messages.at(-1)).toMatchObject({ state: 'done', text: '서버가 끝낸 답' })
  })
})

describe('stopped answer while the server is still generating (M4)', () => {
  const stoppedThread = { thread_id: 't1', title: '중지 질문', messages: [{ role: 'user', text: '질문' }, { role: 'assistant', text: '앞부분', state: 'stopped' }] }
  async function setupStopped() {
    const { getThreads, getThread } = await import('./api')
    getThreads.mockResolvedValueOnce([{ thread_id: 't1', title: '중지 질문', updated_at: '2026-11-09T01:00:00Z' }])
    getThread.mockReset()
    getThread.mockResolvedValueOnce(stoppedThread)
    const adapter = createApiChatAdapter()
    await adapter.listThreads()
    await adapter.getThread('t1')
    return { adapter, getThread }
  }

  it('keeps the local stopped copy while the server returns only the question, then refetches', async () => {
    const { adapter, getThread } = await setupStopped()
    getThread.mockResolvedValueOnce({ thread_id: 't1', title: '중지 질문', messages: [{ role: 'user', text: '질문' }] })
    getThread.mockResolvedValueOnce({ thread_id: 't1', title: '중지 질문', messages: [{ role: 'user', text: '질문' }, { role: 'assistant', text: '서버가 끝낸 답', state: 'done' }] })

    const running = await adapter.getThread('t1')
    expect(running.messages.at(-1)).toMatchObject({ state: 'stopped', text: '앞부분' })

    const finished = await adapter.getThread('t1')
    expect(getThread).toHaveBeenCalledTimes(3)
    expect(finished.messages.at(-1)).toMatchObject({ state: 'done', text: '서버가 끝낸 답' })
  })

  it('returns the local copy when the refetch fails', async () => {
    const { adapter, getThread } = await setupStopped()
    getThread.mockRejectedValueOnce(new Error('network'))

    const again = await adapter.getThread('t1')

    expect(again.messages.at(-1)).toMatchObject({ state: 'stopped', text: '앞부분' })
  })
})

describe('thread list refresh during a new stream (M3)', () => {
  it('does not replace the thread that is streaming right now', async () => {
    const { getThreads } = await import('./api')
    let release
    streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => {
      onEvent({ type: 'token', thread_id: 't9', data: { text: '앞' } })
      await new Promise(resolve => { release = resolve })
      onEvent({ type: 'done', thread_id: 't9', data: {} })
    })
    getThreads.mockResolvedValueOnce([{ thread_id: 't9', title: '재전송', updated_at: '2026-11-09T01:00:00Z' }])
    const adapter = createApiChatAdapter()
    const sending = adapter.sendMessage({ threadId: null, message: '재전송' })
    await vi.waitFor(() => expect(release).toBeTypeOf('function'))

    const listed = await adapter.listThreads()
    release()
    await sending
    const thread = await adapter.getThread('t9')

    expect(listed.find(item => item.id === 't9').messages.at(-1)).toMatchObject({ role: 'assistant', text: '앞' })
    expect(thread.messages.at(-1)).toMatchObject({ state: 'done', text: '앞' })
  })
})

describe('스트림 도중 연결이 끊긴 경우', () => {
  it('브라우저가 던진 영어 오류 대신 한국어 문구를 보인다', async () => {
    streamChatMessage.mockImplementationOnce(async (_threadId, _message, { onEvent }) => {
      onEvent({ type: 'token', thread_id: 't1', data: { text: '생성 중' } })
      throw new TypeError('network error')
    })
    const snapshots = []
    const service = createChatService(createApiChatAdapter({ onThreadsChange: value => snapshots.push(value) }))
    await service.sendMessage({ threadId: 't1', message: '질문' })
    const answer = snapshots.at(-1)[0].messages.at(-1)
    expect(answer.state).toBe('error')
    expect(answer.error).not.toMatch(/network error/)
    expect(answer.error).toBe('채팅 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.')
  })
})
