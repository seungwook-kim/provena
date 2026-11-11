// 세션이 만료돼 로그인 화면으로 갔다 와도 쓰던 질문이 남도록 탭 안에만 임시 저장한다(H-29).
const KEY = 'provena-chat-draft'

export function loadDraft() {
  try { return sessionStorage.getItem(KEY) ?? '' } catch { return '' }
}

export function saveDraft(text) {
  try {
    if (text) sessionStorage.setItem(KEY, text)
    else sessionStorage.removeItem(KEY)
  } catch { /* 저장소를 못 쓰면 임시 저장 없이 동작한다 */ }
}
