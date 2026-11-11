import { useEffect, useRef } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { SessionProvider } from './components/SessionProvider'
import AppErrorBoundary from './components/AppErrorBoundary'
import { useSession } from './lib/session'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import ProfileRequiredPage from './pages/ProfileRequiredPage'
import AdminUsersPage from './pages/AdminUsersPage'
import { DemoAdminBlocked, DemoOnlyChat } from './pages/DemoChatPage'
import { AdminRouteGuard, DemoRouteGuard } from './pages/DemoPages'
import MemorySettingsPage from './pages/MemorySettingsPage'
import ChangeMonitoringPage from './pages/ChangeMonitoringPage'
import ApprovalsPage from './pages/ApprovalsPage'
import AdminPage, { AdminLivePage } from './pages/AdminPage'
import RecallPage from './pages/RecallPage'
import NotFoundPage from './pages/NotFoundPage'
import { DevAdminUsersPreview, DevProfilePreview } from './pages/DevPreviewPages'
import { getLiveServices, resetLiveServices } from './lib/live-services'

export default function App() {
  return <AppErrorBoundary><BrowserRouter><SessionProvider><SessionRoutes /></SessionProvider></BrowserRouter></AppErrorBoundary>
}

function Protected({ children, admin = false }) {
  const { status, user, error, refresh, expired } = useSession()
  const location = useLocation()
  if (status === 'checking') return <main role="status" className="status-page">세션을 확인하고 있습니다.</main>
  if (status === 'error') return <main className="status-page"><p role="alert">{error}</p><button type="button" className="button button-dark" onClick={refresh}>다시 시도</button></main>
  if (!user) return <Navigate to={expired ? '/login?reason=expired' : '/login'} replace />
  if (user.profile_completed === false && location.pathname !== '/myinfo') return <Navigate to="/myinfo" replace />
  if (admin && user.role !== 'admin') return <main role="alert" className="status-page">접근 권한이 없습니다. <Link to="/chat">채팅으로 돌아가기</Link></main>
  return children
}

function LiveRecallRoute() {
  const { user } = useSession()
  return <RecallPage service={getLiveServices(user.user_id).recalls} isAdmin={user.role === 'admin'} />
}

function LiveChangeRoute() {
  const { user } = useSession()
  return <ChangeMonitoringPage service={getLiveServices(user.user_id).changes} isAdmin={user.role === 'admin'} />
}

function LiveApprovalsRoute() {
  const { user } = useSession()
  return <ApprovalsPage service={getLiveServices(user.user_id).approvals} />
}

function ChatRoute() {
  return <Protected><DemoOnlyChat /></Protected>
}

function SessionRoutes() {
  const { status, user, refresh } = useSession()
  const location = useLocation()
  const { pathname, state } = location
  const logoutPending = state?.logoutPending === true
  const previousPath = useRef(pathname)

  useEffect(() => {
    if (status === 'anonymous') resetLiveServices()
  }, [status])

  useEffect(() => {
    if (previousPath.current !== pathname) {
      previousPath.current = pathname
      if (status === 'authenticated') refresh()
    }
  }, [pathname, refresh, status])

  return <Routes>
    <Route path="/" element={logoutPending ? <LandingPage /> : user && import.meta.env.VITE_ENABLE_MOCK_SESSION !== 'true' ? <Navigate to={user.profile_completed === false ? '/myinfo' : '/chat'} replace /> : <LandingPage />} />
    <Route path="/login" element={user ? <Navigate to={user.profile_completed === false ? '/myinfo' : '/chat'} replace /> : <LoginPage />} />
    <Route path="/signup" element={user ? <Navigate to="/chat" replace /> : <SignupPage />} />
    <Route path="/myinfo" element={<Protected><ProfileRequiredPage /></Protected>} />
          <Route path="/admin/users" element={<Protected admin><AdminUsersPage /></Protected>} />
    <Route path="/chat" element={<ChatRoute />} />
    <Route path="/recalls" element={<Protected><LiveRecallRoute /></Protected>} />
    <Route path="/changes" element={<Protected><LiveChangeRoute /></Protected>} />
    <Route path="/approvals" element={<Protected admin><LiveApprovalsRoute /></Protected>} />
    <Route path="/admin" element={<Protected admin><AdminLivePage /></Protected>} />
    <Route path="/onboarding" element={<Protected><MemorySettingsPage /></Protected>} />
    <Route path="/demo/chat" element={<DemoRouteGuard><DemoOnlyChat /></DemoRouteGuard>} />
    <Route path="/demo/recalls" element={<DemoRouteGuard><RecallPage /></DemoRouteGuard>} />
    <Route path="/demo/approvals" element={<DemoRouteGuard><ApprovalsPage /></DemoRouteGuard>} />
    <Route path="/demo/onboarding" element={<DemoRouteGuard><MemorySettingsPage /></DemoRouteGuard>} />
    <Route path="/demo/changes" element={<DemoRouteGuard><ChangeMonitoringPage /></DemoRouteGuard>} />
    <Route path="/demo/admin" element={<DemoRouteGuard><AdminPage /></DemoRouteGuard>} />
    <Route path="/demo/myinfo" element={<DemoRouteGuard><DevProfilePreview key="create" mode="create" /></DemoRouteGuard>} />
    <Route path="/demo/myinfo/edit" element={<DemoRouteGuard><DevProfilePreview key="edit" mode="edit" /></DemoRouteGuard>} />
    <Route path="/demo/admin-users" element={<DemoRouteGuard><DevAdminUsersPreview /></DemoRouteGuard>} />
    <Route path="/demo/blocked" element={<AdminRouteGuard><DemoAdminBlocked /></AdminRouteGuard>} />
    <Route path="/dev-preview/myinfo" element={import.meta.env.DEV ? <DevProfilePreview /> : <Navigate to="/login" replace />} />
    <Route path="/dev-preview/admin-users" element={import.meta.env.DEV ? <DevAdminUsersPreview /> : <Navigate to="/login" replace />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes>
}
