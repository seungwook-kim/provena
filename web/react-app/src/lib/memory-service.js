import { emptyMemory, readMemory, removeMemory, saveMemory } from './session-memory'

export const DEFAULT_SETTINGS = Object.freeze(emptyMemory())

// Boundary for GET/PATCH/DELETE /me/memory (rank=role, service=service; GET maps affiliation to team).
// PATCH never sends affiliation: the screen's Korean team name differs from corpus section names (security, finance ...)
// and affiliation becomes the search scope, so sending it empties every search. Same as ProfileRequiredPage (내 정보).
// The preview adapter (no login) stays browser-session scoped and follows logout/user
// switching cleanup implemented by SessionProvider.
export function createMemoryService(adapter) {
  return {
    getMemorySettings: ownerId => adapter.getMemorySettings(ownerId),
    saveMemorySettings: (ownerId, settings) => adapter.saveMemorySettings(ownerId, settings),
    resetMemorySettings: ownerId => adapter.resetMemorySettings(ownerId),
  }
}

export const previewMemoryService = createMemoryService({
  getMemorySettings: async ownerId => readMemory(ownerId),
  saveMemorySettings: async (ownerId, settings) => {
    const value = { ...DEFAULT_SETTINGS, ...settings }
    saveMemory(ownerId, value)
    return value
  },
  resetMemorySettings: async ownerId => {
    removeMemory(ownerId)
    return { ...DEFAULT_SETTINGS }
  },
})

export function mapApiMemoryResponse(value = {}, fallback = DEFAULT_SETTINGS) {
  const profile = value.profile && typeof value.profile === 'object' ? value.profile : value
  return {
    ...DEFAULT_SETTINGS,
    ...fallback,
    team: typeof profile.affiliation === 'string' ? profile.affiliation : fallback.team,
    role: typeof profile.rank === 'string' ? profile.rank : fallback.role,
    service: typeof profile.service === 'string' ? profile.service : fallback.service,
  }
}

// 소속 팀은 내 정보 `dept`에만 저장한다(docs/specs/memory.md 남은 점, PR #131 조장 확정). 그래서 기억 설정 화면은
// 팀을 내 정보에서 읽어 보여 주고, 바꾸면 내 정보의 다른 칸은 그대로 둔 채 `dept`만 바꿔 PUT /me/profile 로 저장한다
// (PUT 은 네 칸을 모두 받는다, backend/profile_api.py put_profile). 내 정보가 없거나 못 읽으면 팀은 화면 안에서만 쓴다.
let editableProfile = null

export const apiMemoryService = createMemoryService({
  getMemorySettings: async () => {
    const { getMemory, getProfileForEdit } = await import('./api')
    const [memory, profile] = await Promise.all([getMemory(), Promise.resolve().then(() => getProfileForEdit()).catch(() => null)])
    editableProfile = profile && typeof profile === 'object' ? profile : null
    const settings = mapApiMemoryResponse(memory)
    return typeof editableProfile?.dept === 'string' && editableProfile.dept ? { ...settings, team: editableProfile.dept } : settings
  },
  saveMemorySettings: async (_ownerId, settings) => {
    const { patchMemory, saveProfile } = await import('./api')
    const response = await patchMemory({ rank: settings.role, service: settings.service })
    if (editableProfile && settings.team && settings.team !== editableProfile.dept) {
      const { name, phone, address } = editableProfile
      await saveProfile({ name, dept: settings.team, phone, address })
      editableProfile = { ...editableProfile, dept: settings.team }
    }
    return { ...mapApiMemoryResponse(response, settings), team: settings.team }
  },
  resetMemorySettings: async () => {
    const { deleteMemory } = await import('./api')
    await deleteMemory()
    // 기억만 지운다. 소속 팀은 내 정보에 남아 있으므로 그대로 보여 준다.
    return { ...DEFAULT_SETTINGS, team: editableProfile?.dept || '' }
  },
})
