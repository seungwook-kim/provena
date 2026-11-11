import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SignupPage from './pages/SignupPage'
import { ApiError } from './lib/api'

const { resendSignupCode, verifySignup } = vi.hoisted(() => ({ resendSignupCode: vi.fn(), verifySignup: vi.fn() }))
vi.mock('./lib/signup', () => ({ requestSignup: vi.fn(), verifySignup, validateSignupInput: () => [], resendSignupCode }))
vi.mock('./components/AuthIllustration', () => ({ default: () => null }))
vi.mock('./components/Logo', () => ({ default: () => <span>logo</span> }))

const sent = (resendMs = 60000) => ({ status: 'sent', verification_expires_at: new Date(Date.now() + 300000).toISOString(), verification_resend_available_at: new Date(Date.now() + resendMs).toISOString() })

async function openCodeStep(resendMs) {
  resendSignupCode.mockResolvedValueOnce(sent(resendMs))
  const user = userEvent.setup()
  render(<MemoryRouter initialEntries={['/signup?resume=1']}><SignupPage /></MemoryRouter>)
  await user.type(screen.getByLabelText('가입한 이메일'), 'p@example.com')
  await user.click(screen.getByRole('button', { name: '인증번호 다시 받기' }))
  await screen.findByLabelText('6자리 인증번호')
  return user
}

describe('signup verification step fixes', () => {
  beforeEach(() => resendSignupCode.mockReset())
  afterEach(cleanup)

  it('H-09: hides Google link on the code step', async () => {
    await openCodeStep(60000)
    expect(screen.queryByText('Google로 계속하기')).toBeNull()
  })

  it('H-14: shows server message for 503 and 429, generic otherwise', async () => {
    for (const [status, msg] of [[503, '메일 발송이 설정되지 않았습니다.'], [429, '잠시 후 다시 시도해 주세요.']]) {
      cleanup(); resendSignupCode.mockReset()
      const user = await openCodeStep(0)
      resendSignupCode.mockRejectedValueOnce(new ApiError(msg, status, 'x'))
      await user.click(await screen.findByRole('button', { name: '인증번호 재발송' }))
      expect((await screen.findByRole('alert')).textContent).toBe(msg)
    }
    cleanup(); resendSignupCode.mockReset()
    const user = await openCodeStep(0)
    resendSignupCode.mockRejectedValueOnce(new ApiError('세부 내용', 404, 'x'))
    await user.click(await screen.findByRole('button', { name: '인증번호 재발송' }))
    expect((await screen.findByRole('alert')).textContent).toContain('인증을 이어갈 수 없습니다')
  })

  it('H-14: resume() also shows 503 server message', async () => {
    resendSignupCode.mockRejectedValueOnce(new ApiError('메일 미설정', 503, 'x'))
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/signup?resume=1']}><SignupPage /></MemoryRouter>)
    await user.type(screen.getByLabelText('가입한 이메일'), 'p@example.com')
    await user.click(screen.getByRole('button', { name: '인증번호 다시 받기' }))
    expect((await screen.findByRole('alert')).textContent).toBe('메일 미설정')
  })

  it('H-28-1: shows remaining seconds while resend is disabled', async () => {
    await openCodeStep(45000)
    expect(screen.getByRole('button', { name: '인증번호 재발송' }).disabled).toBe(true)
    expect(screen.getByText(/재발송까지 (4[0-5])초/)).toBeTruthy()
  })

  it('H-28-2: success message is not in the error alert', async () => {
    const user = await openCodeStep(0)
    resendSignupCode.mockResolvedValueOnce(sent(60000))
    await user.click(await screen.findByRole('button', { name: '인증번호 재발송' }))
    const ok = await screen.findByText('새 인증번호를 발송했습니다.')
    expect(ok.className).toContain('form-success')
    expect(ok.className).not.toContain('form-error')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
