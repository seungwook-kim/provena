import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
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
