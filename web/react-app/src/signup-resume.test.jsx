import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SignupPage from './pages/SignupPage'

const { resendSignupCode, verifySignup } = vi.hoisted(() => ({ resendSignupCode: vi.fn(), verifySignup: vi.fn() }))
vi.mock('./lib/signup', () => ({
  requestSignup: vi.fn(),
  verifySignup,
  validateSignupInput: () => [],
  resendSignupCode,
}))

vi.mock('./components/AuthIllustration', () => ({ default: () => null }))
vi.mock('./components/Logo', () => ({ default: () => <span>logo</span> }))

describe('email verification resume', () => {
  beforeEach(() => { resendSignupCode.mockReset(); verifySignup.mockReset() })
  afterEach(cleanup)

  it('resends for a manually entered email and opens code entry', async () => {
    resendSignupCode.mockResolvedValue({ status: 'sent', verification_expires_at: new Date(Date.now() + 300000).toISOString(), verification_resend_available_at: new Date(Date.now() + 60000).toISOString() })
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/signup?resume=1']}><SignupPage /></MemoryRouter>)
    await user.type(screen.getByLabelText('가입 이메일'), 'pending@example.com')
    await user.click(screen.getByRole('button', { name: '이메일 인증 이어하기' }))
    expect(resendSignupCode).toHaveBeenCalledWith('pending@example.com')
    expect(await screen.findByText(/인증번호를/)).toBeTruthy()
  })

  it('uses a generic message when the resume request is unavailable', async () => {
    resendSignupCode.mockResolvedValue({ status: 'unavailable' })
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/signup?resume=1']}><SignupPage /></MemoryRouter>)
    await user.type(screen.getByLabelText('가입 이메일'), 'unknown@example.com')
    await user.click(screen.getByRole('button', { name: '이메일 인증 이어하기' }))
    expect((await screen.findByRole('alert')).textContent).toContain('입력한 이메일로 인증을 이어갈 수 없습니다.')
    expect(screen.getByLabelText('6자리 인증번호')).toBeTruthy()
    verifySignup.mockResolvedValue({ status: 'verified' })
    await user.type(screen.getByLabelText('6자리 인증번호'), '123456')
    await user.click(screen.getByRole('button', { name: '인증번호 확인' }))
    expect(verifySignup).toHaveBeenCalledWith({ email: 'unknown@example.com', code: '123456' })
  })
})
