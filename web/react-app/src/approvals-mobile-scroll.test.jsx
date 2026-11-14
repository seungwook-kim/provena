import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, configure, fireEvent, render, waitFor } from '@testing-library/react'
import App from './App'

// 승인함 모바일: 760px 이하는 목록 아래에 상세가 와서, 항목을 누르면 상세로 내려가야 한다(박진형 화면 점검 2026-11-14)
configure({ asyncUtilTimeout: 8000 })
vi.setConfig({ testTimeout: 20000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

async function openApprovals(narrow) {
  window.history.replaceState({}, '', '/demo/approvals')
  vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'unauthorized' }, 401)))
  vi.stubGlobal('matchMedia', vi.fn(query => ({ matches: narrow && query === '(max-width: 760px)', media: query, addEventListener() {}, removeEventListener() {} })))
  vi.stubGlobal('requestAnimationFrame', callback => { callback(0); return 0 })
  const scrolled = vi.fn()
  Element.prototype.scrollIntoView = scrolled
  render(<App />)
  const items = await waitFor(() => {
    const found = document.querySelectorAll('.approval-service-layout aside > button')
    expect(found.length).toBeGreaterThan(1)
    return found
  })
  fireEvent.click(items[1])
  return scrolled
}

it('760px 이하에서 승인 요청을 누르면 상세로 스크롤한다', async () => {
  const scrolled = await openApprovals(true)
  expect(scrolled).toHaveBeenCalledTimes(1)
  expect(scrolled.mock.contexts[0].tagName).toBe('ARTICLE')
  expect(scrolled.mock.contexts[0].closest('.approval-service-layout')).toBeTruthy()
})

it('넓은 화면에서는 상세가 옆에 보이므로 움직이지 않는다', async () => {
  const scrolled = await openApprovals(false)
  expect(scrolled).not.toHaveBeenCalled()
})
