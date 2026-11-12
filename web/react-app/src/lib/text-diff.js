// 새 본문에서 "바뀐 부분" 한 덩어리를 구한다. 앞·뒤 공통 부분을 떼고 남은 가운데를 단어 경계로 맞춘다.
// 의존성 없음·결정적·O(n). 너무 긴 글, 공통 부분이 없거나 바뀐 곳이 없으면 null(강조 안 함).
export const MAX_DIFF_CHARS = 50000

const isSpace = ch => ch === undefined || /\s/.test(ch)

export function changedSpan(oldText, newText) {
  if (typeof oldText !== 'string' || typeof newText !== 'string') return null
  if (!oldText || !newText || oldText === newText) return null
  if (oldText.length > MAX_DIFF_CHARS || newText.length > MAX_DIFF_CHARS) return null
  const limit = Math.min(oldText.length, newText.length)
  let start = 0
  while (start < limit && oldText[start] === newText[start]) start += 1
  // 공통 앞부분은 단어 경계에서 끊는다(단어 중간이면 그 단어 시작까지 물린다).
  while (start > 0 && !isSpace(newText[start - 1]) && !isSpace(newText[start])) start -= 1
  let tail = 0
  while (tail < limit - start && oldText[oldText.length - 1 - tail] === newText[newText.length - 1 - tail]) tail += 1
  while (tail > 0 && !isSpace(newText[newText.length - tail - 1]) && !isSpace(newText[newText.length - tail])) tail -= 1
  const span = newText.slice(start, newText.length - tail).trim()
  if (!span || span.length >= newText.trim().length) return null
  return span
}
