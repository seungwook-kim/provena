import { useEffect, useState } from 'react'
import { ApiError, changeAdminRole, listAdminUsers, listSignupRequests, resetSignupVerification, reviewSignupRequestById } from '../lib/api'
import { useSession } from '../lib/session'
import DemoLayout from '../components/DemoLayout'
import AdminUsersTabs from '../components/AdminUsersTabs'
import AdminRoleDialog from '../components/AdminRoleDialog'
import AdminUsersTable from '../components/AdminUsersTable'
import '../admin-users.css'

export default function AdminUsersPage() {
  const { user } = useSession()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState('')
  const [confirm, setConfirm] = useState(null)
  const [signupRequests, setSignupRequests] = useState([])
  const [signupLoading, setSignupLoading] = useState(false)

  async function load() {
    setLoading(true)
    setError('')
    try {
      const result = await listAdminUsers()
      setUsers(result.users ?? [])
    } catch (loadError) {
      setError(loadError.message || '사용자 목록을 불러오지 못했습니다.')
    } finally { setLoading(false) }
  }

  async function loadSignupRequests() {
    setSignupLoading(true)
    try { const result = await listSignupRequests(); setSignupRequests(result.requests ?? []) }
    catch (loadError) { setError(loadError.message || '가입 승인 목록을 불러오지 못했습니다.') }
    finally { setSignupLoading(false) }
  }

  useEffect(() => { if (user?.is_owner) { load(); loadSignupRequests() } else setLoading(false) }, [user?.is_owner])
  async function reviewSignup(requestId, action) {
    setError(''); setMessage('')
    try { const result = await reviewSignupRequestById(requestId, action); setMessage(result.changed ? '가입 신청 처리가 완료되었습니다.' : '변경할 상태가 없습니다.'); await loadSignupRequests() }
    catch (reviewError) { setError(reviewError.message || '가입 신청 처리에 실패했습니다.') }
  }
  async function resetVerification(requestId) {
    setError(''); setMessage('')
    try { await resetSignupVerification(requestId); setMessage('인증번호를 초기화했습니다. 신청자가 새 인증번호를 받을 수 있습니다.'); await loadSignupRequests() }
    catch (resetError) { setError(resetError.message || '인증 재설정에 실패했습니다.') }
  }
  async function applyChange() {
    if (!confirm || busy) return
    setBusy(confirm.login_id)
    setError('')
    setMessage('')
    try {
      const result = await changeAdminRole(confirm.login_id, confirm.action)
      setMessage(result.changed ? `${confirm.login_id} 계정의 권한을 변경했습니다.` : '변경할 내용이 없어 현재 상태를 유지했습니다.')
      setConfirm(null)
      await load()
    } catch (changeError) {
      setError(changeError instanceof ApiError && changeError.status === 403 ? '최고 관리자 권한이 필요합니다.' : changeError.message || '권한을 변경하지 못했습니다.')
    } finally { setBusy('') }
  }

  if (!user?.is_owner) return <main className="status-page"><h1>접근 권한이 없습니다</h1><p>최고 관리자만 사용자 관리를 사용할 수 있습니다.</p></main>

  return <DemoLayout active="admin-users"><main className="admin-users-page">
    <header><h1>권한 관리</h1></header>
    {error && <p className="form-error" role="alert">{error}</p>}
    {message && <p className="profile-success" role="status">{message}</p>}
    <AdminUsersTabs users={users} loading={loading} busyLoginId={busy} onChangeRole={item => setConfirm({ login_id: item.login_id, action: item.role === 'admin' ? 'revoke' : 'promote' })} roleConfirm={confirm} roleBusy={Boolean(busy)} onCancelRole={() => setConfirm(null)} onConfirmRole={applyChange} privacyReviewer defaultTab="signup" signupRequests={signupRequests} signupLoading={signupLoading} onReviewSignup={reviewSignup} onTabChange={() => { setMessage(''); setError('') }} onResetVerification={resetVerification} />
    {false && <div>
    <header><h1>권한 관리</h1></header>
    {error && <p className="form-error" role="alert">{error}</p>}
    {message && <p className="profile-success" role="status">{message}</p>}
    {loading ? <p role="status">사용자 목록을 불러오는 중입니다.</p> : <AdminUsersTable users={users} busyLoginId={busy} onChangeRole={item => setConfirm({ login_id: item.login_id, action: item.role === 'admin' ? 'revoke' : 'promote' })} />}
    <AdminRoleDialog confirm={confirm} busy={Boolean(busy)} onCancel={() => setConfirm(null)} onConfirm={applyChange} />
    </div>}
  </main></DemoLayout>
}
