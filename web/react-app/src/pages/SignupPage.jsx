import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { requestSignup, validateSignupInput } from '../lib/signup'
import AuthIllustration from '../components/AuthIllustration'
import Logo from '../components/Logo'

export default function SignupPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setMessage('')
    const errors = validateSignupInput({ loginId, password, passwordConfirmation: confirmation })
    if (errors.length) {
      setMessage(errors[0])
      return
    }

    setSubmitting(true)
    try {
      const result = await requestSignup({ loginId: loginId.trim(), password, passwordConfirmation: confirmation })
      navigate('/login', { replace: true, state: { signupMessage: result.message } })
    } catch (error) {
      setMessage(error.message || '회원가입 요청을 처리하지 못했습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  return <div className="auth-page"><div className="auth-panel">
    <Link to="/" className="login-brand" aria-label="Provena 처음으로"><Logo /></Link>
    <main className="login-card">
      <h1>회원가입</h1>
      <form onSubmit={submit} noValidate className="login-form">
        <label><span>아이디</span><input value={loginId} onChange={event => setLoginId(event.target.value)} type="text" autoComplete="username" placeholder="아이디를 입력하세요" /></label>
        <label><span>비밀번호</span><input value={password} onChange={event => setPassword(event.target.value)} type="password" autoComplete="new-password" placeholder="8자 이상 입력" /></label>
        <label><span>비밀번호 확인</span><input value={confirmation} onChange={event => setConfirmation(event.target.value)} type="password" autoComplete="new-password" placeholder="비밀번호를 다시 입력" /></label>
        {(message || params.get('oauth_error') === 'google_login_failed') && <p className="form-error" role="alert">{message || 'Google 로그인에 실패했습니다. 다시 시도해 주세요.'}</p>}
        <button className="button button-dark" type="submit" disabled={submitting}>{submitting ? '확인 중...' : '회원가입'}</button>
      </form>
      <div className="login-divider"><span />또는<span /></div>
      <a href="/auth/google/start" aria-label="Google로 계속하기" className="button google-button">Google 계정으로 회원가입</a>
      <p className="signup-link">이미 계정이 있으신가요? <Link to="/login">로그인으로 돌아가기</Link></p>
    </main></div><AuthIllustration /></div>
}
