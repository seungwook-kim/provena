import userEvent from '@testing-library/user-event'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test } from 'vitest'
import AdminUsersTabs from './components/AdminUsersTabs'
import { SessionContext } from './lib/session'

const users = [{ login_id: 'owner', role: 'admin', is_owner: true, created_at: '2026-11-06T09:00:00Z' }]

function renderTabs() {
  return render(<AdminUsersTabs users={users} loading={false} onChangeRole={() => {}} isPreview />)
}

test('shows signup approval preview and confirms a local demo action', async () => {
  const user = userEvent.setup()
  renderTabs()
  expect(screen.getByRole('tab', { name: '회원가입 승인' })).toBeTruthy()
  expect(screen.getByText('pending-user-01')).toBeTruthy()
  await user.click(screen.getAllByRole('button', { name: '가입 승인' })[0])
  expect(screen.getByRole('dialog')).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '확인' }))
  expect(screen.getByText('승인 완료')).toBeTruthy()
  expect(screen.getByText(/데모 상태에만 반영됩니다/)).toBeTruthy()
})

afterEach(cleanup)

test('keeps the existing administrator role tab', async () => {
  const user = userEvent.setup()
  renderTabs()
  await user.click(screen.getByRole('tab', { name: '관리자 권한 관리' }))
  expect(screen.getByRole('region', { name: '관리자 권한 목록' })).toBeTruthy()
  expect(screen.getByText('owner')).toBeTruthy()
})

test('shows the privacy access tab and demo request form without exposing raw data', async () => {
  const user = userEvent.setup()
  renderTabs()
  await user.click(screen.getByRole('tab', { name: '개인정보 열람' }))
  expect(screen.getByRole('textbox', { name: '대상 계정' })).toBeTruthy()
  const all = screen.getByRole('checkbox', { name: '전체 선택' })
  expect(all.checked).toBe(false)
  await user.click(all)
  expect(screen.getAllByRole('checkbox')).toHaveLength(7)
  expect(screen.getAllByRole('checkbox').every(input => input.checked)).toBe(true)
  await user.click(all)
  expect(screen.getAllByRole('checkbox').every(input => !input.checked)).toBe(true)
  await user.click(screen.getByRole('checkbox', { name: '이름' }))
  const period = screen.getByRole('combobox', { name: '열람 기간' })
  expect([...period.options].map(option => option.textContent)).toEqual(['1시간', '24시간', '3일'])
  expect(screen.getByRole('button', { name: '열람 신청' }).disabled).toBe(true)
  await user.type(screen.getByRole('textbox', { name: '상세 사유' }), '중복 계정 확인')
  expect(screen.getByRole('button', { name: '열람 신청' }).disabled).toBe(false)
  expect(screen.getByText('신청·승인·열람 이력')).toBeTruthy()
  await user.click(screen.getAllByRole('button', { name: '상세 보기' })[0])
  expect(screen.getByRole('dialog')).toBeTruthy()
})

test('ordinary admin request view omits role management and real privacy history is empty', () => {
  render(<AdminUsersTabs users={[]} loading={false} isPreview={false} showRoleTab={false} defaultTab="privacy" />)
  expect(screen.getAllByRole('tab')).toHaveLength(2)
  expect(screen.queryByText('pending-user-01')).toBeNull()
})

test('ordinary admin preview shows only the signed-in demo requester history', () => {
  render(<AdminUsersTabs users={[]} loading={false} isPreview showRoleTab={false} defaultTab="privacy" viewerId="auditor-demo" />)
  expect(screen.getByText('pending-user-01')).toBeTruthy()
  expect(screen.getByText('former-user-02')).toBeTruthy()
  expect(screen.queryByText('pending-user-03')).toBeNull()
})

test('owner preview opens full request details and limits approval to requested fields and period', async () => {
  const user = userEvent.setup()
  render(<AdminUsersTabs users={[]} loading={false} isPreview privacyReviewer defaultTab="privacy" />)
  await user.click(screen.getAllByRole('button', { name: '상세 보기' })[0])
  expect(screen.getByText('계정 소유자 확인과 업무 연락을 위해 기본 연락처 확인이 필요합니다. 승인된 항목 외에는 조회하지 않겠습니다.')).toBeTruthy()
  expect(screen.getAllByText('24시간').length).toBeGreaterThan(0)
  await user.click(screen.getByRole('button', { name: '승인' }))
  expect(screen.getAllByRole('dialog')).toHaveLength(2)
  expect(screen.getByText(/신청 기간을 초과하지 않습니다/)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '최종 확인' }))
  expect(screen.getAllByText('승인').length).toBeGreaterThan(0)
})

test('owner preview shows a compact read-only result for a completed approval', async () => {
  const user = userEvent.setup()
  render(<AdminUsersTabs users={[]} loading={false} isPreview privacyReviewer defaultTab="privacy" />)
  await user.click(screen.getAllByRole('button', { name: '상세 보기' })[1])
  expect(screen.getByRole('region', { name: '신청 내역' })).toBeTruthy()
  expect(screen.getAllByText('승인 완료')).toHaveLength(2)
  expect(screen.getByText('승인된 개인정보 항목')).toBeTruthy()
  expect(screen.getAllByText('이름')).toHaveLength(2)
  expect(screen.queryByRole('button', { name: '승인' })).toBeNull()
  await user.click(screen.getByRole('button', { name: '닫기' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('owner preview shows the rejection reason in the read-only completed layout', async () => {
  const user = userEvent.setup()
  render(<AdminUsersTabs users={[]} loading={false} isPreview privacyReviewer defaultTab="privacy" />)
  await user.click(screen.getAllByRole('button', { name: '상세 보기' })[2])
  const dialog = screen.getByRole('dialog')
  expect(dialog.className).toContain('privacy-completed-dialog')
  expect(screen.getByText('거절 사유')).toBeTruthy()
  expect(screen.getByText('신청 사유가 구체적이지 않아 거절했습니다.')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '승인' })).toBeNull()
})
