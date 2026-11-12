import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminUsersPage from './pages/AdminUsersPage'
import { SessionContext } from './lib/session'

const api = vi.hoisted(() => ({
  listAdminUsers: vi.fn(), listSignupRequests: vi.fn(), reviewSignupRequestById: vi.fn(), resetSignupVerification: vi.fn(), changeAdminRole: vi.fn(),
}))
vi.mock('./lib/api', async importOriginal => ({ ...(await importOriginal()), ...api }))
vi.mock('./components/DemoLayout', () => ({ default: ({ children }) => <div>{children}</div> }))

const row = (over = {}) => ({ request_id: 7, login_id: 'p@example.com', requested_at: '2026-11-10T00:00:00Z', status: 'pending', email_verified: true, ...over })

function renderPage() {
  return render(<MemoryRouter><SessionContext.Provider value={{ user: { is_owner: true } }}><AdminUsersPage /></SessionContext.Provider></MemoryRouter>)
}

describe('가입 승인 연타 방지·결과 문구 (A8)', () => {
  beforeEach(() => {
    Object.values(api).forEach(fn => fn.mockReset())
    api.listAdminUsers.mockResolvedValue({ users: [] })
    api.listSignupRequests.mockResolvedValue({ requests: [row()] })
  })
  afterEach(cleanup)

  it('승인 확인을 여러 번 눌러도 요청은 한 번이고 누구를 어떻게 했는지 알려 준다', async () => {
    let finish
    api.reviewSignupRequestById.mockReturnValue(new Promise(resolve => { finish = resolve }))
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: '가입 승인' }))
    await user.click(screen.getByRole('button', { name: '확인' }))
    expect(screen.getByRole('button', { name: '가입 승인' }).disabled).toBe(true)
    expect(screen.getByRole('button', { name: '거절' }).disabled).toBe(true)
    await user.click(screen.getByRole('button', { name: '가입 승인' }))
    expect(api.reviewSignupRequestById).toHaveBeenCalledTimes(1)
    finish({ changed: true })
    expect(await screen.findByText('p@example.com 가입을 승인했습니다.')).toBeTruthy()
  })

  it('인증 재설정을 연타해도 요청은 한 번이고 대상 이메일이 문구에 들어간다', async () => {
    api.listSignupRequests.mockResolvedValue({ requests: [row({ email_verified: false })] })
    let finish
    api.resetSignupVerification.mockReturnValue(new Promise(resolve => { finish = resolve }))
    renderPage()
    const button = await screen.findByRole('button', { name: '인증 재설정' })
    button.click(); button.click()
    expect(api.resetSignupVerification).toHaveBeenCalledTimes(1)
    finish({})
    expect(await screen.findByText(/p@example\.com 인증을 초기화했습니다/)).toBeTruthy()
  })

  it('실패하면 오류를 보이고 다시 누를 수 있다', async () => {
    api.reviewSignupRequestById.mockRejectedValueOnce(new Error('서버 오류'))
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: '거절' }))
    await user.click(screen.getByRole('button', { name: '확인' }))
    // 실패 문구에도 누구의 신청인지 나온다
    expect(await screen.findByText('p@example.com: 서버 오류')).toBeTruthy()
    await waitFor(() => expect(screen.getByRole('button', { name: '거절' }).disabled).toBe(false))
  })
})
