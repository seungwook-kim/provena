import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './pages/LoginPage'
import { ApiError } from './lib/api'

const signIn = vi.hoisted(() => vi.fn())
vi.mock('./lib/session', () => ({ useSession: () => ({ signIn }) }))
vi.mock('./components/AuthIllustration', () => ({ default: () => null }))
vi.mock('./components/Logo', () => ({ default: () => <span>logo</span> }))

async function attempt(error) {
  signIn.mockRejectedValueOnce(error)
  const user = userEvent.setup()
  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  await user.type(screen.getByLabelText('이메일 또는 아이디'), 'a@b.co')
  await user.type(screen.getByPlaceholderText('비밀번호'), 'pw123456')
  await user.click(screen.getByRole('button', { name: '로그인' }))
}

describe('login of an unverified signup', () => {
  afterEach(cleanup)
  it('shows the message and a link to resume verification', async () => {
    await attempt(new ApiError('이메일 인증을 먼저 마쳐 주세요', 403, 'signup_unverified'))
    expect((await screen.findByRole('alert')).textContent).toContain('이메일 인증을 먼저 마쳐 주세요')
    const links = screen.getAllByRole('link', { name: '이메일 인증 이어하기' })
    expect(links.some(a => a.getAttribute('href') === '/signup?resume=1')).toBe(true)
    expect(screen.getByRole('alert').querySelector('a[href="/signup?resume=1"]')).toBeTruthy()
  })
  it('does not show the in-alert link for other errors', async () => {
    await attempt(new ApiError('아이디 또는 비밀번호가 올바르지 않습니다.', 401, 'unauthorized'))
    expect((await screen.findByRole('alert')).querySelector('a')).toBeNull()
  })
})
