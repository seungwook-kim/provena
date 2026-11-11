import { describe, expect, it, vi } from 'vitest'
import { apiMemoryService, mapApiMemoryResponse } from './memory-service'

vi.mock('./api', () => ({ getMemory: vi.fn(), patchMemory: vi.fn(), deleteMemory: vi.fn() }))

describe('apiMemoryService field mapping', () => {
  it('maps the actual nested GET /me/memory response', () => {
    expect(mapApiMemoryResponse({ user_id: 'user-1', profile: { affiliation: '보안', rank: 'SRE', service: '결제 API' }, allowed_fields: ['affiliation', 'rank', 'service'] })).toEqual({ team: '보안', role: 'SRE', service: '결제 API' })
  })

  it('maps affiliation and rank to the UI fields without inventing a service value', () => {
    expect(mapApiMemoryResponse({ affiliation: '보안', rank: 'SRE' })).toEqual({ team: '보안', role: 'SRE', service: '' })
  })

  it('sends team, role and service as affiliation, rank and service', async () => {
    const { getMemory, patchMemory } = await import('./api')
    getMemory.mockResolvedValueOnce({ affiliation: '보안', rank: 'SRE' })
    patchMemory.mockResolvedValueOnce({ affiliation: 'IT 운영', rank: '개발자', service: '결제 API' })

    expect(await apiMemoryService.getMemorySettings('user-1')).toEqual({ team: '보안', role: 'SRE', service: '' })
    expect(await apiMemoryService.saveMemorySettings('user-1', { team: 'IT 운영', role: '개발자', service: '결제 API' })).toEqual({ team: 'IT 운영', role: '개발자', service: '결제 API' })
    expect(patchMemory).toHaveBeenCalledWith({ affiliation: 'IT 운영', rank: '개발자', service: '결제 API' })
  })

  it('keeps affiliation and rank after a PATCH response is read again', async () => {
    const { getMemory, patchMemory } = await import('./api')
    patchMemory.mockResolvedValueOnce({ user_id: 'user-1', profile: { affiliation: '보안', rank: 'SRE' } })
    getMemory.mockResolvedValueOnce({ user_id: 'user-1', profile: { affiliation: '보안', rank: 'SRE' }, allowed_fields: ['affiliation', 'rank'] })

    await expect(apiMemoryService.saveMemorySettings('user-1', { team: '보안', role: 'SRE', service: '' })).resolves.toMatchObject({ team: '보안', role: 'SRE' })
    await expect(apiMemoryService.getMemorySettings('user-1')).resolves.toMatchObject({ team: '보안', role: 'SRE' })
  })

  it('uses DELETE /me/memory without falling back to preview storage', async () => {
    const { deleteMemory } = await import('./api')
    deleteMemory.mockResolvedValueOnce(undefined)

    expect(await apiMemoryService.resetMemorySettings('user-1')).toEqual({ team: '', role: '', service: '' })
    expect(deleteMemory).toHaveBeenCalledOnce()
  })

  it('propagates API failures so the screen can show an error', async () => {
    const { getMemory, patchMemory, deleteMemory } = await import('./api')
    const error = new Error('memory unavailable')
    getMemory.mockRejectedValueOnce(error)
    patchMemory.mockRejectedValueOnce(error)
    deleteMemory.mockRejectedValueOnce(error)

    await expect(apiMemoryService.getMemorySettings('user-1')).rejects.toBe(error)
    await expect(apiMemoryService.saveMemorySettings('user-1', { team: '보안', role: 'SRE', service: '' })).rejects.toBe(error)
    await expect(apiMemoryService.resetMemorySettings('user-1')).rejects.toBe(error)
  })
})
