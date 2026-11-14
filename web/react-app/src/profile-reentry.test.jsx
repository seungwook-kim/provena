// 놓친 것 K-23: 로컬 데모에서 암호화 키가 바뀌어 저장된 내 정보를 못 풀 때, 회원정보 수정 화면이 빈 칸을 열어 다시 입력·저장하게 한다.
// 서버 응답 모양은 backend/profile_api.py (404 profile_reentry_required). 503(운영의 키 설정 오류 등)은 전과 같이 오류로만 보인다.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

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
// 저장된 줄이 있으므로 서버 /me 는 profile_completed=true 를 준다(줄이 있는지만 본다) → 수정 화면이 열린다
vi.mock('./lib/session', () => ({ useSession: () => ({ user: { user_id: 'u1', profile_completed: true }, refresh: vi.fn() }) }))

import ProfileRequiredPage from './pages/ProfileRequiredPage'

const REENTRY_MESSAGE = '저장된 내 정보를 열 수 없습니다. 로컬 데모의 암호화 키가 바뀌었습니다. 다시 입력해 저장해 주세요.'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderPage() {
  render(<MemoryRouter initialEntries={['/myinfo']}>
    <Routes><Route path="/myinfo" element={<ProfileRequiredPage />} /></Routes>
  </MemoryRouter>)
}

describe('회원정보 수정: 저장된 내 정보를 풀 수 없을 때 (K-23)', () => {
  it('404 profile_reentry_required 면 안내와 빈 칸을 보이고, 다시 입력하면 저장된다', { timeout: 15000 }, async () => {
    api.getProfileForEdit.mockRejectedValue(Object.assign(new Error(REENTRY_MESSAGE), { status: 404, code: 'profile_reentry_required' }))
    api.getMemory.mockResolvedValue({ profile: { rank: '개발자', service: '결제 API' } })
    api.saveProfile.mockResolvedValue({})
    const user = userEvent.setup({ delay: null })
    renderPage()

    expect((await screen.findByRole('alert')).textContent).toBe(REENTRY_MESSAGE)
    const save = screen.getByRole('button', { name: '변경사항 저장' })
    expect(save.disabled).toBe(true)                       // 필수 칸이 비어 있는 동안만 잠긴다
    expect(screen.getByLabelText(/이름/).value).toBe('')
    expect(screen.getByLabelText(/업무 역할/).disabled).toBe(false)   // AI 기억은 정상으로 불러왔다
    expect(screen.getByLabelText(/담당 서비스/).value).toBe('결제 API')

    await user.selectOptions(screen.getByLabelText(/소속 팀/), '보안')
    await user.type(screen.getByLabelText(/이름/), '홍길동')
    await user.type(screen.getByLabelText(/전화번호/), '01012345678')
    await user.type(screen.getByLabelText(/근무지 주소/), '부산시 해운대구 센텀로 1')
    expect(save.disabled).toBe(false)
    await user.click(save)

    expect(api.saveProfile).toHaveBeenCalledWith({ name: '홍길동', dept: '보안', phone: '010-1234-5678', address: '부산시 해운대구 센텀로 1' })
    expect(await screen.findByText('변경사항을 저장했습니다.')).toBeTruthy()
    expect(api.patchMemory).not.toHaveBeenCalled()          // 기억 칸은 바꾸지 않았다
  })

  it('503 은 전과 같이 오류로만 보이고 AI 기억 칸은 잠긴 채다(운영 동작 그대로)', async () => {
    api.getProfileForEdit.mockRejectedValue(Object.assign(new Error('내 정보 저장소를 사용할 수 없습니다.'), { status: 503, code: 'not_configured' }))
    api.getMemory.mockResolvedValue({ profile: { rank: '개발자' } })
    renderPage()
    expect((await screen.findByRole('alert')).textContent).toBe('내 정보 저장소를 사용할 수 없습니다.')
    expect(screen.getByLabelText(/업무 역할/).disabled).toBe(true)
    expect(screen.queryByText(/다시 입력해 저장/)).toBeNull()
  })
})
