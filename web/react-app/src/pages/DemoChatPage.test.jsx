import { describe, expect, it } from 'vitest'
import { isApprovalPending } from './DemoChatPage'

describe('DemoChatPage approval state', () => {
  it('only reports approval pending for the selected thread', () => {
    expect(isApprovalPending({ messages: [{ role: 'assistant', state: 'approval' }] })).toBe(true)
    expect(isApprovalPending({ messages: [{ role: 'assistant', state: 'done' }] })).toBe(false)
    expect(isApprovalPending(null)).toBe(false)
  })
})
