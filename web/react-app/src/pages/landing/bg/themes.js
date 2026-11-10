// Shared palette per background theme.
export const THEMES = {
  d: { ground: '#EFEBE3', ink: '#1B1915', accent: '#D2421F', rgb: '239,235,227', label: '아카이브 페이퍼' },
  e: { ground: '#F7F7F5', ink: '#16181B', accent: '#14A06E', rgb: '247,247,245', label: '콘솔' },
  f: { ground: '#0F2A22', ink: '#F2EDE1', accent: '#C8F169', rgb: '15,42,34', label: '시간 / 햇빛' },
}

// Deterministic PRNG so layouts are stable across resizes.
export function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function makeCanvas(w, h) {
  const c = document.createElement('canvas')
  c.width = Math.max(1, Math.round(w))
  c.height = Math.max(1, Math.round(h))
  return c
}
