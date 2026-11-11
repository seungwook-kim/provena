import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AdminUsersTabs from './components/AdminUsersTabs'

afterEach(cleanup)

const baseProps = { users: [], signupLoading: false, signupRequests: [], onReviewSignup: () => {} }

describe('signup approval email verification gate', () => {
  it.each([false, null, undefined])('disables approval when email_verified is %s', email_verified => {
    const { container } = render(<AdminUsersTabs {...baseProps} signupRequests={[{ request_id: 'pending', login_id: 'pending@example.com', requested_at: '2026-11-10T00:00:00Z', status: 'pending', email_verified }]} />)
    expect(container.querySelector('tbody button').disabled).toBe(true)
  })

  it('keeps approval enabled after email verification', () => {
    const { container } = render(<AdminUsersTabs {...baseProps} signupRequests={[{ request_id: 'verified', login_id: 'verified@example.com', requested_at: '2026-11-10T00:00:00Z', status: 'pending', email_verified: true }]} />)
    expect(container.querySelector('tbody button').disabled).toBe(false)
  })
})

describe('verification reset button (H-21)', () => {
  const pending = email_verified => [{ request_id: 7, login_id: 'p@example.com', requested_at: '2026-11-10T00:00:00Z', status: 'pending', email_verified }]

  it('shows the reset button only for pending requests without a verified email and calls it with the request id', async () => {
    const onResetVerification = vi.fn()
    render(<AdminUsersTabs {...baseProps} onResetVerification={onResetVerification} signupRequests={pending(false)} />)
    await userEvent.click(screen.getByRole('button', { name: '인증 재설정' }))
    expect(onResetVerification).toHaveBeenCalledWith(7)
  })

  it('hides it once the email is verified', () => {
    render(<AdminUsersTabs {...baseProps} onResetVerification={() => {}} signupRequests={pending(true)} />)
    expect(screen.queryByRole('button', { name: '인증 재설정' })).toBeNull()
  })
})
