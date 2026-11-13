import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPreviewChatAdapter } from './chat-preview'

// 새로 발견 7(미리보기 모드): '다시 시도'는 실패한 턴을 바꾸고, 일반 전송은 뒤에 붙인다
describe('preview chat adapter retry', () => {
  afterEach(() => vi.useRealTimers())

  async function failOnce(adapter, question, options = {}) {
    const result = await adapter.sendMessage({ message: question, ...options })
    vi.advanceTimersByTime(600)
    return result.threadId
  }

  it('replaces the failed turn on retry instead of stacking error bubbles', async () => {
    vi.useFakeTimers()
    let latest = []
    const adapter = createPreviewChatAdapter({ onThreadsChange: threads => { latest = threads }, onProcessingChange: () => {} })
    const question = '오류 시험 질문'
    const threadId = await failOnce(adapter, question)
    for (let i = 0; i < 3; i += 1) await failOnce(adapter, question, { threadId, retry: true })
    const messages = latest.find(thread => thread.id === threadId).messages
    expect(messages).toHaveLength(2)
    expect(messages.at(-1).state).toBe('error')
  })

  it('still appends on a normal send of the same question', async () => {
    vi.useFakeTimers()
    let latest = []
    const adapter = createPreviewChatAdapter({ onThreadsChange: threads => { latest = threads }, onProcessingChange: () => {} })
    const question = '오류 시험 질문'
    const threadId = await failOnce(adapter, question)
    await failOnce(adapter, question, { threadId })
    expect(latest.find(thread => thread.id === threadId).messages).toHaveLength(4)
  })
})
