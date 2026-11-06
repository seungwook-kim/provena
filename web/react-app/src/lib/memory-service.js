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
