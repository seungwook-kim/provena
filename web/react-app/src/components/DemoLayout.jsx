import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Brain, History, UserRound, UserRoundPen } from 'lucide-react'
import { useSession } from '../lib/session'
import { getProfile } from '../lib/api'
import { previewRecallService } from '../lib/recall-service'
import { getLiveServices, useServiceSnapshot } from '../lib/live-services'
import Logo from './Logo'

const UNREAD_LOAD_DELAY_MS = 300

const links = [
  ['chat', '/demo/chat', '채팅'],
  ['recalls', '/demo/recalls', '리콜 알림'],
  ['changes', '/demo/changes', '변경 감시'],
  ['approvals', '/demo/approvals', '승인함'],
]

function SessionExitControl({ demoMode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, signOut } = useSession()
  const [error, setError] = useState(() => location.state?.logoutError || '')

  async function logout() {
    setError('')
    const returnTo = `${location.pathname}${location.search}`
    navigate('/', { replace: true, state: { logoutPending: true } })
    try {
      await signOut()
    } catch (logoutError) {
      const detail = logoutError.message
      const message = !detail ? '로그아웃을 확인하지 못했습니다. 다시 시도해 주세요.' : detail.includes('로그아웃') ? detail : `로그아웃하지 못했습니다. ${detail}`
      navigate(returnTo, { replace: true, state: { logoutError: message } })
    }
  }

  if (demoMode || !user) return <Link to="/" aria-label="로그아웃">나가기</Link>
  return <>
    <button type="button" className="demo-logout-button" onClick={logout}>로그아웃</button>
    {error && <span className="demo-logout-error" role="alert">{error}</span>}
  </>
}

export default function DemoLayout({ active, children }) {
  const location = useLocation()
  const { user } = useSession()
  const [accountOpen, setAccountOpen] = useState(false)
  const accountMenuRef = useRef(null)
  const [team, setTeam] = useState('')
  const demoMode = location.pathname.startsWith('/demo/')
  const liveRecalls = !demoMode && user ? getLiveServices(user.user_id).recalls : null
  const { unread } = useServiceSnapshot(liveRecalls ?? previewRecallService)
  const showUnread = demoMode || Boolean(liveRecalls)
  const logoTo = demoMode ? '/demo/chat' : '/chat'
  const isAdmin = user?.role === 'admin' || demoMode
  const isOwner = user?.is_owner === true || demoMode
  const actualPaths = { chat: '/chat', recalls: '/recalls', changes: '/changes', approvals: '/approvals' }
  const visibleLinks = links.filter(([key]) => key !== 'approvals' || isAdmin)
  const accountId = user?.login_id || user?.email || user?.name || (user ? '확인할 수 없음' : 'demo-user')
  const roleLabel = user?.role === 'admin' ? '관리자' : user ? '일반 사용자' : '데모 사용자'
  const conversationLink = demoMode ? '/demo/chat' : '/chat'

  useEffect(() => {
    if (!liveRecalls) return undefined
    // The badge waits until the screen has settled; every navigation re-checks the session first.
    const timer = setTimeout(() => { liveRecalls.loadUnread()?.catch(() => {}) }, UNREAD_LOAD_DELAY_MS)
    return () => clearTimeout(timer)
  }, [liveRecalls])

  // H-23: 소속 팀을 '설정되지 않음'으로 고정하지 않고, 메뉴를 열 때 내 정보(dept)에서 읽는다. 전화번호를 가린 보기로 읽는다(원래 번호가 필요 없다).
  useEffect(() => {
    if (!accountOpen || demoMode || !user) return undefined
    let active = true
    getProfile().then(profile => { if (active) setTeam(typeof profile?.dept === 'string' ? profile.dept : '') }).catch(() => {})
    return () => { active = false }
  }, [accountOpen, demoMode, user?.user_id])

  useEffect(() => {
    if (!accountOpen) return undefined
    const closeOnOutsidePointer = event => {
      if (!accountMenuRef.current?.contains(event.target)) setAccountOpen(false)
    }
    const closeOnEscape = event => {
      if (event.key === 'Escape') setAccountOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [accountOpen])

  return <div className="demo-screen">
    <header className="demo-app-nav">
      <Link to={logoTo} className="nav-brand"><Logo /></Link>
      <nav aria-label={isAdmin && !demoMode ? '관리자 메뉴' : '주요 메뉴'}>
        {visibleLinks.map(([key, to, label]) => <Link key={key} to={demoMode ? to : actualPaths[key]} className={active === key ? 'active' : ''}>{label}{key === 'recalls' && showUnread && unread > 0 && <b>{unread}</b>}</Link>)}
        {isAdmin && <Link to={demoMode ? '/demo/admin' : '/admin'} className={active === 'admin' ? 'active' : ''}>운영 현황</Link>}
        {isOwner && <Link to={demoMode ? '/demo/admin-users' : '/admin/users'} className={active === 'admin-users' ? 'active' : ''}>권한 관리</Link>}
      </nav>
      <div className="demo-nav-actions">
        {demoMode && <span className="demo-badge">데모 모드</span>}
        <div className="account-menu" ref={accountMenuRef}><button type="button" className="account-menu-trigger" aria-expanded={accountOpen} aria-haspopup="menu" onClick={() => setAccountOpen(open => !open)}><UserRound aria-hidden="true" size={16} strokeWidth={1.8} /><span>내 계정</span></button>{accountOpen && <div className="account-menu-panel" role="menu"><div className="account-menu-panel-header"><strong>내 계정</strong><button type="button" className="account-menu-close" aria-label="내 계정 메뉴 닫기" onClick={() => setAccountOpen(false)}>×</button></div><div className="account-menu-info"><dl><dt>계정 식별 정보</dt><dd>{accountId}</dd><dt>소속 팀</dt><dd>{demoMode ? '데모 데이터' : team || '설정되지 않음'}</dd><dt>계정 역할</dt><dd>{roleLabel}</dd></dl></div><div className="account-menu-links"><Link to={demoMode ? '/demo/myinfo/edit' : '/myinfo'} role="menuitem" onClick={() => setAccountOpen(false)}><UserRoundPen aria-hidden="true" size={15} strokeWidth={1.8} /><span>회원정보 수정</span></Link><Link to={demoMode ? '/demo/onboarding' : '/onboarding'} role="menuitem" onClick={() => setAccountOpen(false)}><Brain aria-hidden="true" size={15} strokeWidth={1.8} /><span>기억 설정</span></Link><Link to={conversationLink} role="menuitem" onClick={() => setAccountOpen(false)}><History aria-hidden="true" size={15} strokeWidth={1.8} /><span>대화 기록 보기</span></Link></div></div>}</div>
        <SessionExitControl demoMode={demoMode} />
      </div>
    </header>
    {children}
  </div>
}
