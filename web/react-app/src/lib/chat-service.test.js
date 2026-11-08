import { describe, expect, it, vi } from 'vitest'
import { streamChatMessage } from './api'
import { createApiChatAdapter, createChatService } from './chat-service'

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
})

describe('createApiChatAdapter thread mapping', () => {
  it('maps backend thread fields and preserves a last-only answer', async () => {
    const { getThreads } = await import('./api')
    getThreads.mockResolvedValueOnce([{ thread_id: 't1', title: '정책 질문', updated_at: '2026-11-07T01:02:03Z', last: { text: '마지막 답' } }])
    const updates = []
    const adapter = createApiChatAdapter({ onThreadsChange: value => updates.push(value) })

    const threads = await adapter.listThreads()

    expect(threads[0]).toMatchObject({ id: 't1', title: '정책 질문', lastActivityAt: '2026-11-07T01:02:03Z' })
    expect(threads[0].messages).toEqual([{ role: 'assistant', text: '마지막 답' }])
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
