import { afterEach, describe, expect, it, vi } from 'vitest'
import { actualApprovalsService } from './lib/approvals-service'

afterEach(() => vi.unstubAllGlobals())

describe('actual approvals service', () => {
  it('normalizes the live approval contract without preview fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ approvals: [
      { approval_id: 'a-1', kind: 'decision_table', summary: 'Decision draft', created_at: '2026-11-09T00:00:00Z' },
    ] }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    await expect(actualApprovalsService.listApprovals()).resolves.toEqual([expect.objectContaining({
      id: 'a-1', title: 'Decision draft', kind: 'decision', status: 'pending',
    })])
  })

  it('surfaces API failure instead of showing demo items', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'unavailable' }), { status: 503 })))
    await expect(actualApprovalsService.listApprovals()).rejects.toThrow()
  })

  it('maps approve and reject to the existing API contract', async () => {
    document.cookie = 'provena_csrf=test-token; path=/'
    const fetchMock = vi.fn(async (_path, options) => {
      if (_path === '/auth/csrf') return new Response(null, { status: 204 })
      expect(JSON.parse(options.body)).toEqual({ approval_id: 'a-1', approve: true, comment: 'ok' })
      return new Response(null, { status: 204 })
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(actualApprovalsService.decideApproval('a-1', { action: 'approve', reason: 'ok' }))
      .resolves.toEqual({ id: 'a-1', status: 'approved' })
  })

  it('does not pretend the missing revision API exists', async () => {
    await expect(actualApprovalsService.decideApproval('a-1', { action: 'revision', reason: 'more' }))
      .rejects.toThrow('보완 요청 API')
  })
})
