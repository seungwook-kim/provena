import { useState } from 'react'
import AdminRoleDialog from './AdminRoleDialog'
import AdminUsersTable from './AdminUsersTable'
import PrivacyAccessPanel from './PrivacyAccessPanel'

const PREVIEW_REQUESTS = [{ login_id: 'pending-user-01', requested_at: '2026-11-06T09:30:00+09:00', status: 'pending' }]
const formatDate = value => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))

export default function AdminUsersTabs({ users, loading, busyLoginId, onChangeRole, roleConfirm, roleBusy, onCancelRole, onConfirmRole, isPreview = false, showRoleTab = true, defaultTab = 'signup', privacyReviewer = false, viewerId = '', signupRequests = [], signupLoading = false, onReviewSignup }) {
  const [tab, setTab] = useState(defaultTab)
  const [previewRequests, setPreviewRequests] = useState(PREVIEW_REQUESTS)
  const [approvalConfirm, setApprovalConfirm] = useState(null)
  const [approvalMessage, setApprovalMessage] = useState('')
  const visibleRequests = isPreview ? previewRequests : signupRequests
  const applyApproval = () => {
    if (!approvalConfirm) return
    if (!isPreview) { onReviewSignup?.(approvalConfirm.login_id, approvalConfirm.action); setApprovalConfirm(null); return }
    const status = approvalConfirm.action === 'approve' ? 'approved' : 'rejected'
    setPreviewRequests(items => items.map(item => item.login_id === approvalConfirm.login_id ? { ...item, status } : item))
    setApprovalMessage(`${approvalConfirm.login_id} 승인 완료. 데모 상태에만 반영됩니다.`)
    setApprovalConfirm(null)
  }
  return <>
    <div className="admin-users-tabs" role="tablist" aria-label="권한 관리 메뉴">
      <button type="button" role="tab" aria-selected={tab === 'signup'} className={tab === 'signup' ? 'selected' : ''} onClick={() => setTab('signup')}>회원가입 승인</button>
      {showRoleTab && <button type="button" role="tab" aria-selected={tab === 'roles'} className={tab === 'roles' ? 'selected' : ''} onClick={() => setTab('roles')}>관리자 권한 관리</button>}
      <button type="button" role="tab" aria-selected={tab === 'privacy'} className={tab === 'privacy' ? 'selected' : ''} onClick={() => setTab('privacy')}>{privacyReviewer ? '개인정보 열람 승인' : '개인정보 열람'}</button>
    </div>
    {tab === 'privacy' ? <PrivacyAccessPanel isPreview={isPreview} reviewOnly={privacyReviewer} viewerId={viewerId} /> : tab === 'signup' ? <section className="admin-approval-panel" aria-label="회원가입 승인 목록">
      {approvalMessage && <p className="profile-success" role="status">{approvalMessage}</p>}
      <div className="admin-users-table-wrap"><table className="admin-users-table"><thead><tr><th>계정 ID</th><th>신청일</th><th>승인 상태</th><th>처리</th></tr></thead><tbody>{signupLoading ? <tr><td colSpan="4" role="status">가입 승인 목록을 불러오는 중입니다.</td></tr> : visibleRequests.length ? visibleRequests.map(item => <tr key={item.login_id}><td>{item.login_id}</td><td>{formatDate(item.requested_at)}</td><td>{item.status === 'pending' ? '승인 대기' : item.status === 'approved' ? '승인 완료' : '거절'}</td><td><button type="button" disabled={item.status !== 'pending'} onClick={() => setApprovalConfirm({ ...item, action: 'approve' })}>가입 승인</button><button type="button" disabled={item.status !== 'pending'} onClick={() => setApprovalConfirm({ ...item, action: 'reject' })}>거절</button></td></tr>) : <tr><td colSpan="4" className="admin-empty-state">가입 승인 목록이 없습니다.</td></tr>}</tbody></table></div>
    </section> : showRoleTab ? <section className="admin-role-panel" aria-label="관리자 권한 목록">{loading ? <p role="status">사용자 목록을 불러오는 중입니다.</p> : <AdminUsersTable users={users} busyLoginId={busyLoginId} onChangeRole={onChangeRole} />}</section> : null}
    <AdminRoleDialog confirm={roleConfirm} busy={roleBusy} onCancel={onCancelRole} onConfirm={onConfirmRole} />
    {approvalConfirm && <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>{approvalConfirm.action === 'approve' ? '가입 승인' : '가입 거절'}</h2><p>{approvalConfirm.login_id} 계정을 처리합니다.</p><button type="button" onClick={() => setApprovalConfirm(null)}>취소</button><button type="button" onClick={applyApproval}>확인</button></section></div>}
  </>
}
