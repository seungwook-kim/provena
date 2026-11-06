// Temporary, non-sensitive UI notes only. Browser storage is not an access boundary.
const PREFIX = 'provena-memory:'
const OWNER = 'provena-session-user'
export const emptyMemory = () => ({ team: '', role: '', service: '' })

export function clearSessionMemory() {
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith(PREFIX) || key === OWNER) sessionStorage.removeItem(key)
    }
    localStorage.removeItem('provena-memory')
    localStorage.removeItem('provena-auth')
  } catch { /* Storage can be unavailable; authentication must still work. */ }
}

export function selectMemoryOwner(userId) {
  try {
    localStorage.removeItem('provena-memory') // Never attribute the old shared notes to a user.
    if (sessionStorage.getItem(OWNER) !== userId) clearSessionMemory()
    sessionStorage.setItem(OWNER, userId)
  } catch { /* No persistence when browser storage is unavailable. */ }
}

export function readMemory(userId) {
  try {
    const value = JSON.parse(sessionStorage.getItem(PREFIX + userId))
    return Object.fromEntries(Object.keys(emptyMemory()).map(key => [key, typeof value?.[key] === 'string' ? value[key] : '']))
  } catch { return emptyMemory() }
}

export function saveMemory(userId, value) {
  sessionStorage.setItem(PREFIX + userId, JSON.stringify(value))
}

export function removeMemory(userId) {
  sessionStorage.removeItem(PREFIX + userId)
}
