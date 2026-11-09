import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import App from './App'
import AppErrorBoundary from './components/AppErrorBoundary'

// 첫 화면(LandingPage)이 그리다 오류를 내는 상황을 만든다.
vi.mock('./pages/LandingPage', () => ({ default: () => { throw new Error('landing broke') } }))

function Broken() { throw new Error('render broke') }

describe('AppErrorBoundary', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('shows a reload notice instead of a blank page and logs the error', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const onReload = vi.fn()
    render(<AppErrorBoundary onReload={onReload}><Broken /></AppErrorBoundary>)
    expect(screen.getByRole('alert').textContent).toContain('화면을 표시하는 중 문제가 생겼습니다.')
    fireEvent.click(screen.getByRole('button', { name: '화면 다시 불러오기' }))
    expect(onReload).toHaveBeenCalledTimes(1)
    expect(consoleError.mock.calls.some(call => call[0] === '[Provena] 화면 오류' && call[1]?.message === 'render broke')).toBe(true)
  })

  it('wraps the whole App so a page error does not leave a blank screen', async () => {
    window.history.replaceState({}, '', '/')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'unauthorized' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { container } = render(<App />)
    expect((await screen.findByRole('alert')).textContent).toContain('화면을 표시하는 중 문제가 생겼습니다.')
    expect(container.textContent.trim().length).toBeGreaterThan(0)
  })
})
