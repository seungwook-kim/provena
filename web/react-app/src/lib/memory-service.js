import { emptyMemory, readMemory, removeMemory, saveMemory } from './session-memory'

export const DEFAULT_SETTINGS = Object.freeze(emptyMemory())

// Stable boundary for future GET/PATCH/DELETE /me/memory. Until that contract
// exists, preview state remains browser-session scoped and follows logout/user
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
  }
}

export const apiMemoryService = createMemoryService({
  getMemorySettings: async () => {
    const { getMemory } = await import('./api')
    return mapApiMemoryResponse(await getMemory())
  },
  saveMemorySettings: async (_ownerId, settings) => {
    const { patchMemory } = await import('./api')
    const response = await patchMemory({ affiliation: settings.team, rank: settings.role })
    return mapApiMemoryResponse(response, settings)
  },
  resetMemorySettings: async () => {
    const { deleteMemory } = await import('./api')
    await deleteMemory()
    return { ...DEFAULT_SETTINGS }
  },
})
