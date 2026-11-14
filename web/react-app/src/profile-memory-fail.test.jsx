import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const refresh = vi.fn(async () => {})
const api = vi.hoisted(() => ({
  getProfileForEdit: vi.fn(),
  getMemory: vi.fn(),
  saveProfile: vi.fn(),
  patchMemory: vi.fn(),
}))

vi.mock('./lib/api', () => ({
  ApiError: class ApiError extends Error {
    constructor(message, status, code, fields) { super(message); this.status = status; this.code = code; this.fields = fields }
  },
  ...api,
}))
vi.mock('./lib/session', () => ({ useSession: () => ({ user: { user_id: 'u1', profile_completed: false }, refresh }) }))

import ProfileRequiredPage from './pages/ProfileRequiredPage'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function fillWizardAndSubmit() {
  const user = userEvent.setup({ delay: null })
  render(<MemoryRouter initialEntries={['/profile']}>
    <Routes>
      <Route path="/profile" element={<ProfileRequiredPage />} />
      <Route path="/chat" element={<p>채팅 화면</p>} />
    </Routes>
  </MemoryRouter>)
  await user.click(await screen.findByRole('button', { name: '보안' }))
  await user.click(screen.getByRole('button', { name: '다음' }))
  await user.click(screen.getByRole('button', { name: '개발자' }))
  await user.click(screen.getByRole('button', { name: '다음' }))
  await user.click(screen.getByRole('button', { name: '다음' }))
  await user.type(screen.getByLabelText(/이름/), '홍길동')
  await user.type(screen.getByLabelText(/전화번호/), '01012345678')
  await user.type(screen.getByLabelText(/근무지 주소/), '부산시 해운대구 센텀로 1')
  await user.click(screen.getByRole('button', { name: '다음' }))
  await user.click(screen.getByRole('button', { name: '등록 완료' }))
}

describe('profile onboarding when the memory save fails', () => {
  it('offers a continue button that refreshes the session and goes to chat', { timeout: 15000 }, async () => {
    api.getProfileForEdit.mockRejectedValue({ status: 404, message: 'none' })
    api.getMemory.mockResolvedValue({ profile: {} })
    api.saveProfile.mockResolvedValue({})
    api.patchMemory.mockRejectedValue(Object.assign(new Error('기억 저장소가 응답하지 않습니다.'), { status: 503 }))
    await fillWizardAndSubmit()
    expect(await screen.findByText(/AI 기억\(업무 역할·담당 서비스\)은 저장하지 못했습니다/)).toBeTruthy()
    expect(refresh).not.toHaveBeenCalled()
    await userEvent.setup({ delay: null }).click(screen.getByRole('button', { name: '나중에 입력하고 계속' }))
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('채팅 화면')).toBeTruthy()
  })

  it('does not offer the continue button when the profile save itself fails', { timeout: 15000 }, async () => {
    api.getProfileForEdit.mockRejectedValue({ status: 404, message: 'none' })
    api.getMemory.mockResolvedValue({ profile: {} })
    api.saveProfile.mockRejectedValue(Object.assign(new Error('저장하지 못했습니다.'), { status: 503 }))
    await fillWizardAndSubmit()
    expect(await screen.findByText(/아무것도 저장되지 않았습니다/)).toBeTruthy()
    expect(api.patchMemory).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '나중에 입력하고 계속' })).toBeNull()
  })
})
