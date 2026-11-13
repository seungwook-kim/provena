import { describe, expect, it, vi } from 'vitest'
import { apiMemoryService, mapApiMemoryResponse } from './memory-service'

vi.mock('./api', () => ({ getMemory: vi.fn(), patchMemory: vi.fn(), deleteMemory: vi.fn(), getProfileForEdit: vi.fn(), saveProfile: vi.fn() }))

describe('apiMemoryService field mapping', () => {
  it('maps the actual nested GET /me/memory response', () => {
    expect(mapApiMemoryResponse({ user_id: 'user-1', profile: { affiliation: '보안', rank: 'SRE', service: '결제 API' }, allowed_fields: ['affiliation', 'rank', 'service'] })).toEqual({ team: '보안', role: 'SRE', service: '결제 API' })
  })

  it('maps affiliation and rank to the UI fields without inventing a service value', () => {
    expect(mapApiMemoryResponse({ affiliation: '보안', rank: 'SRE' })).toEqual({ team: '보안', role: 'SRE', service: '' })
  })

  it('sends role and service as rank and service, never the team as affiliation', async () => {
    const { getMemory, patchMemory } = await import('./api')
    getMemory.mockResolvedValueOnce({ affiliation: '보안', rank: 'SRE' })
    patchMemory.mockResolvedValueOnce({ affiliation: 'IT 운영', rank: '개발자', service: '결제 API' })

    expect(await apiMemoryService.getMemorySettings('user-1')).toEqual({ team: '보안', role: 'SRE', service: '' })
    expect(await apiMemoryService.saveMemorySettings('user-1', { team: 'IT 운영', role: '개발자', service: '결제 API' })).toEqual({ team: 'IT 운영', role: '개발자', service: '결제 API' })
    expect(patchMemory).toHaveBeenCalledWith({ rank: '개발자', service: '결제 API' })
    expect(Object.keys(patchMemory.mock.calls.at(-1)[0])).not.toContain('affiliation')
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

// 소속 팀은 내 정보 dept 에만 저장한다(docs/specs/memory.md 남은 점). 기억 설정은 dept 를 읽어 보여 주고, 바꾸면 dept 만 바꿔 PUT 한다.
describe('기억 설정의 소속 팀 = 내 정보 dept', () => {
  const profile = { name: '홍길동', dept: '재무', phone: '010-1234-5678', address: '부산시 해운대구', updated_at: null }

  it('첫 등록 뒤 기억 설정에 내 정보의 소속 팀을 채워 보여 준다', async () => {
    const { getMemory, getProfileForEdit } = await import('./api')
    getMemory.mockResolvedValueOnce({ profile: { rank: '개발자', service: '결제 API' } })
    getProfileForEdit.mockResolvedValueOnce(profile)
    expect(await apiMemoryService.getMemorySettings('user-1')).toEqual({ team: '재무', role: '개발자', service: '결제 API' })
  })

  it('팀을 바꿔 저장하면 내 정보의 다른 칸은 그대로 두고 dept 만 바꿔 저장한다. affiliation 은 보내지 않는다', async () => {
    const { getMemory, getProfileForEdit, patchMemory, saveProfile } = await import('./api')
    getMemory.mockResolvedValueOnce({ profile: { rank: '개발자' } })
    getProfileForEdit.mockResolvedValueOnce(profile)
    await apiMemoryService.getMemorySettings('user-1')
    patchMemory.mockResolvedValueOnce({ profile: { rank: '개발자', service: '' } })
    saveProfile.mockResolvedValueOnce({})
    expect(await apiMemoryService.saveMemorySettings('user-1', { team: '보안', role: '개발자', service: '' })).toMatchObject({ team: '보안' })
    expect(saveProfile).toHaveBeenLastCalledWith({ name: '홍길동', dept: '보안', phone: '010-1234-5678', address: '부산시 해운대구' })
    expect(Object.keys(patchMemory.mock.calls.at(-1)[0])).not.toContain('affiliation')
  })

  it('팀을 바꾸지 않았으면 내 정보를 다시 저장하지 않는다', async () => {
    const { getMemory, getProfileForEdit, patchMemory, saveProfile } = await import('./api')
    getMemory.mockResolvedValueOnce({ profile: {} })
    getProfileForEdit.mockResolvedValueOnce(profile)
    await apiMemoryService.getMemorySettings('user-1')
    saveProfile.mockClear()
    patchMemory.mockResolvedValueOnce({ profile: { rank: 'SRE' } })
    await apiMemoryService.saveMemorySettings('user-1', { team: '재무', role: 'SRE', service: '' })
    expect(saveProfile).not.toHaveBeenCalled()
  })

  it('내 정보를 못 읽으면 예전처럼 기억 응답만으로 채운다', async () => {
    const { getMemory, getProfileForEdit } = await import('./api')
    getMemory.mockResolvedValueOnce({ affiliation: '보안', rank: 'SRE' })
    getProfileForEdit.mockRejectedValueOnce(new Error('404'))
    expect(await apiMemoryService.getMemorySettings('user-1')).toEqual({ team: '보안', role: 'SRE', service: '' })
  })
})
