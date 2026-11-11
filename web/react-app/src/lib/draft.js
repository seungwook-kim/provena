// 세션이 만료돼 로그인 화면으로 갔다 와도 쓰던 질문이 남도록 탭 안에만 임시 저장한다(H-29).
// 키에 계정 id를 넣어, 같은 탭에서 다른 계정이 로그인해도 앞 계정의 질문이 보이지 않게 한다.
const LEGACY_KEY = 'provena-chat-draft' // 계정 구분 없이 쓰던 예전 키. 남아 있으면 지운다.
const PREFIX = `${LEGACY_KEY}:`

export function loadDraft(userId) {
  if (!userId) return ''
  try { return sessionStorage.getItem(PREFIX + userId) ?? '' } catch { return '' }
}

export function saveDraft(userId, text) {
  if (!userId) return
  try {
    if (text) sessionStorage.setItem(PREFIX + userId, text)
    else sessionStorage.removeItem(PREFIX + userId)
  } catch { /* 저장소를 못 쓰면 임시 저장 없이 동작한다 */ }
}

// keepUserId 계정의 임시 저장만 남기고 나머지를 지운다. 인자가 없으면 전부 지운다.
export function clearDrafts(keepUserId) {
  try {
    for (const key of Object.keys(sessionStorage)) {
      const stale = key === LEGACY_KEY || (key.startsWith(PREFIX) && key !== PREFIX + keepUserId)
      if (stale) sessionStorage.removeItem(key)
    }
  } catch { /* 저장소를 못 쓰면 지울 것도 없다 */ }
}
