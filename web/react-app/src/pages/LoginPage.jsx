import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../lib/session'
import AuthIllustration from '../components/AuthIllustration'
import Logo from '../components/Logo'
import { Eye, EyeOff } from 'lucide-react'

const GOOGLE_ERRORS = {
  google_login_failed: 'Google 로그인에 실패했습니다. 다시 시도해 주세요.',
  google_signup_pending: '가입 신청이 접수되었습니다. 관리자 승인 대기 중입니다. 승인 완료 후 로그인할 수 있습니다.',
  google_signup_rejected: '가입 신청이 승인되지 않았습니다. 자세한 내용은 관리자에게 문의해 주세요.',
  google_unavailable: 'Google 로그인을 지금은 사용할 수 없습니다. 아이디와 비밀번호로 로그인해 주세요.',
}

export default function LoginPage() {
  const { signIn } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const oauthCode = params.get('oauth_error')
  const oauthMessage = Object.hasOwn(GOOGLE_ERRORS, oauthCode) ? GOOGLE_ERRORS[oauthCode] : ''
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [unverified, setUnverified] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    setUnverified(false)
    if (!loginId.trim() || !password) {
      setError('이메일 또는 아이디와 비밀번호를 입력해 주세요.')
      return
    }
    setSubmitting(true)
    try {
      const id = loginId.trim().includes('@') ? loginId.trim().toLowerCase() : loginId.trim()
      const user = await signIn(id, password)
      navigate(user?.profile_completed === false ? '/myinfo' : '/chat', { replace: true })
    } catch (loginError) {
      setError(loginError.message || '로그인에 실패했습니다.')
      setUnverified(loginError.code === 'signup_unverified')
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-panel">
        <Link to="/" className="login-brand" aria-label="Provena 처음으로">
          <Logo />
        </Link>
        <main className="login-card">
          <h1>로그인</h1>
          <form onSubmit={submit} noValidate className="login-form">
            <label>
              <span>이메일 또는 아이디</span>
              <input
                aria-label="이메일 또는 아이디"
                value={loginId}
                onChange={event => setLoginId(event.target.value)}
                type="text"
                autoComplete="username"
                placeholder="이메일 또는 아이디"
              />
            </label>
            <label>
              <span>비밀번호</span>
              <div className="password-input-wrap">
                <input
                  value={password}
                  onChange={event => setPassword(event.target.value)}
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="비밀번호"
                />
                <button
                  type="button"
                  className="password-toggle"
                  aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword(value => !value)}
                >
                  {showPassword
                    ? <EyeOff size={19} strokeWidth={1.8} aria-hidden="true" />
                    : <Eye size={19} strokeWidth={1.8} aria-hidden="true" />}
                </button>
              </div>
            </label>
            {(error || oauthMessage) && (
              <p className="form-error" role="alert">
                {error || oauthMessage}
                {error && unverified && <> <Link to="/signup?resume=1">인증번호 다시 받기</Link></>}
              </p>
            )}
            <button
              aria-label={submitting ? '로그인 중...' : '로그인'}
              className="button button-dark"
              type="submit"
              disabled={submitting}
            >
              {submitting ? '로그인 중...' : '로그인'}
            </button>
          </form>
          <div className="login-divider"><span />또는<span /></div>
          <a href="/auth/google/start" className="button google-button">
            Google로 로그인
          </a>
          <p className="signup-link">
            아직 계정이 없으신가요? <Link to="/signup">회원가입</Link>
          </p>
          <p className="signup-link">
            <Link to="/signup?resume=1">이메일 인증 이어하기</Link>
          </p>
          {import.meta.env.DEV && (
            <div className="demo-login-area">
              <span>로컬 데모 전용 · 실제 계정/API와 분리</span>
              <Link to="/demo/chat" className="demo-login-link">
                로그인 없이 둘러보기
              </Link>
            </div>
          )}
        </main>
      </div>
      <AuthIllustration />
    </div>
  )
}
