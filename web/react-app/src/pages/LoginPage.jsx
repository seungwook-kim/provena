import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../lib/session'
import AuthIllustration from '../components/AuthIllustration'
import Logo from '../components/Logo'
import { Eye, EyeOff } from 'lucide-react'

export default function LoginPage() {
  const { signIn } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (!loginId.trim() || !password) {
      setError('아이디와 비밀번호를 입력해 주세요.')
      return
    }
    setSubmitting(true)
    try {
      const user = await signIn(loginId.trim(), password)
      navigate(user?.profile_completed === false ? '/myinfo' : '/chat', { replace: true })
    } catch (loginError) {
      setError(loginError.message || '로그인에 실패했습니다.')
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return <div className="auth-page"><div className="auth-panel">
    <Link to="/" className="login-brand" aria-label="Provena 처음으로"><Logo /></Link>
    <main className="login-card">
      <h1>로그인</h1>
      <form onSubmit={submit} noValidate className="login-form">
        <label><span>아이디</span><input aria-label="아이디" value={loginId} onChange={event => setLoginId(event.target.value)} type="text" autoComplete="username" placeholder="아이디를 입력하세요" /></label>
        <label><span>비밀번호</span><div className="password-input-wrap"><input value={password} onChange={event => setPassword(event.target.value)} type={showPassword ? 'text' : 'password'} autoComplete="current-password" placeholder="비밀번호" /><button type="button" className="password-toggle" aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? <EyeOff size={19} strokeWidth={1.8} aria-hidden="true" /> : <Eye size={19} strokeWidth={1.8} aria-hidden="true" />}</button></div></label>
        {(error || params.get('oauth_error') === 'google_login_failed') && <p className="form-error" role="alert">{error || 'Google 로그인에 실패했습니다. 다시 시도해 주세요.'}</p>}
        <button aria-label={submitting ? '로그인 중...' : '로그인 →'} className="button button-dark" type="submit" disabled={submitting}>{submitting ? '로그인 중...' : '로그인'}</button>
      </form>
      <div className="login-divider"><span />또는<span /></div>
      <a href="/auth/google/start" className="button google-button">Google로 로그인</a>
      <p className="signup-link">아직 계정이 없으신가요? <Link to="/signup">회원가입</Link></p>
      {(import.meta.env.DEV || import.meta.env.VITE_ENABLE_LOCAL_DEMO === 'true') && <div className="demo-login-area"><span>로컬 데모 전용 · 실제 계정/API와 분리</span><Link to="/chat?demo=1" className="demo-login-link">로그인 없이 둘러보기</Link></div>}
    </main></div><AuthIllustration /></div>
}
