import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SignupPage from './pages/SignupPage'

const { requestSignup } = vi.hoisted(() => ({ requestSignup: vi.fn() }))
vi.mock('./lib/signup', () => ({
  requestSignup,
  verifySignup: vi.fn(),
  validateSignupInput: () => [],
  resendSignupCode: vi.fn(),
}))
vi.mock('./components/AuthIllustration', () => ({ default: () => null }))
vi.mock('./components/Logo', () => ({ default: () => <span>logo</span> }))

describe('signup screen without the fixed resume link', () => {
  afterEach(cleanup)

  it('has no fixed "이메일 인증 이어하기" link', () => {
    render(<MemoryRouter initialEntries={['/signup']}><SignupPage /></MemoryRouter>)
    expect(screen.queryByRole('link', { name: '이메일 인증 이어하기' })).toBeNull()
  })

  it('offers "인증번호 다시 받기" only when the email already has a request (409)', async () => {
    requestSignup.mockRejectedValueOnce(Object.assign(new Error('conflict'), { status: 409 }))
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/signup']}><SignupPage /></MemoryRouter>)
    await user.type(screen.getByLabelText('이메일'), 'a@b.co')
    await user.click(screen.getByRole('button', { name: '인증번호 발송' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('이미 가입 신청한 이메일입니다')
    await user.click(screen.getByRole('link', { name: '인증번호 다시 받기' }))
    expect(screen.getByRole('heading', { name: '인증번호 다시 받기' })).toBeTruthy()
  })

  it('does not offer the link for other errors', async () => {
    requestSignup.mockRejectedValueOnce(Object.assign(new Error('잠시 후 다시 시도해 주세요.'), { status: 503 }))
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/signup']}><SignupPage /></MemoryRouter>)
    await user.type(screen.getByLabelText('이메일'), 'a@b.co')
    await user.click(screen.getByRole('button', { name: '인증번호 발송' }))
    expect((await screen.findByRole('alert')).querySelector('a')).toBeNull()
  })
})
