// 서버가 준 원문 링크는 http(s) 주소만 화면에 링크로 쓴다. javascript:·data: 같은 다른 형식은 버린다.
export function safeHttpUrl(value) {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value.trim())
    return url.protocol === 'http:' || url.protocol === 'https:' ? value.trim() : null
  } catch {
    return null
  }
}
