import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../lib/session'
import DemoLayout from '../components/DemoLayout'
import AdminUsersTabs from '../components/AdminUsersTabs'
import PrivacyAccessPanel from '../components/PrivacyAccessPanel'
import '../admin-users.css'

export default function AdminRequestsPage({ isPreview = false }) {
  const { user } = useSession()
  const [params] = useSearchParams()
  const defaultTab = params.get('tab') === 'privacy' ? 'privacy' : 'signup'
  const ownerPreview = isPreview && params.get('role') === 'owner'
  if (!isPreview && user?.is_owner) return <Navigate to="/admin/users" replace />
  if (!ownerPreview) return <DemoLayout active="privacy-access">
    <main className="admin-users-page">
      <header><h1>개인정보 열람 신청</h1></header>
      {isPreview && <p className="demo-notice"><Link to="/demo/admin-requests?role=admin">일반 관리자 미리보기</Link> · <Link to="/demo/admin-requests?role=owner">최고 관리자 미리보기</Link></p>}
      <PrivacyAccessPanel isPreview={isPreview} viewerId={isPreview ? 'auditor-demo' : user?.user_id} />
    </main>
  </DemoLayout>
  return <DemoLayout active={defaultTab === 'privacy' ? 'privacy-access' : 'signup-approval'}>
    <main className="admin-users-page">
      <header><h1>{defaultTab === 'privacy' ? '개인정보 열람 신청' : '회원가입 승인'}</h1></header>
      {isPreview && <p className="demo-notice"><Link to="/demo/admin-requests?role=admin">일반 관리자 미리보기</Link> · <Link to="/demo/admin-requests?role=owner">최고 관리자 미리보기</Link></p>}
      <AdminUsersTabs isPreview={isPreview} showRoleTab={ownerPreview} defaultTab={defaultTab} privacyReviewer={ownerPreview} viewerId={isPreview ? 'auditor-demo' : user?.user_id} />
    </main>
  </DemoLayout>
}
