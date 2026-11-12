// 새 본문에서 "바뀐 부분" 한 덩어리를 구한다. 앞·뒤 공통 부분을 떼고 남은 가운데를 단어 경계로 맞춘다.
// 의존성 없음·결정적·O(n). 너무 긴 글, 공통 부분이 없거나 바뀐 곳이 없으면 null(강조 안 함).
export const MAX_DIFF_CHARS = 50000

const isSpace = ch => ch === undefined || /\s/.test(ch)

// 바뀐 부분의 위치 { start, end }(새 본문 기준, end 제외). 같은 글이 앞에도 있을 때 위치로 강조하려고 위치를 돌려준다.
export function changedRange(oldText, newText) {
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
  let end = newText.length - tail
  while (start < end && isSpace(newText[start])) start += 1
  while (end > start && isSpace(newText[end - 1])) end -= 1
  if (start >= end || end - start >= newText.trim().length) return null
  return { start, end }
}

export function changedSpan(oldText, newText) {
  const range = changedRange(oldText, newText)
  return range ? newText.slice(range.start, range.end) : null
}

// 화면 칸 두 개: changedText(강조할 글)와 changedAt(새 본문에서의 시작 위치). 바뀐 곳이 없으면 둘 다 null.
export function changedMark(oldText, newText) {
  const range = changedRange(oldText, newText)
  return range ? { changedText: newText.slice(range.start, range.end), changedAt: range.start } : { changedText: null, changedAt: null }
}
