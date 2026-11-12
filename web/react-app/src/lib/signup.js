import { apiJson, csrfHeaders } from './api'

const MIN_PASSWORD_LENGTH = 8
const MAX_PASSWORD_BYTES = 72
const EMAIL_RE = /^[^@\s]{1,254}@[^@\s]{1,254}\.[^@\s]{1,63}$/

export function validateSignupInput({ email = '', password = '', passwordConfirmation = '' } = {}) {
  const errors = []
  const normalizedEmail = email.trim().toLowerCase()
  if (!normalizedEmail || !password || !passwordConfirmation) errors.push('이메일과 비밀번호를 모두 입력해 주세요.')
  if (normalizedEmail && !EMAIL_RE.test(normalizedEmail)) errors.push('올바른 이메일 주소를 입력해 주세요.')
  const passwordBytes = typeof TextEncoder === 'function' ? new TextEncoder().encode(password).length : password.length
  if (password && (password.length < MIN_PASSWORD_LENGTH || passwordBytes > MAX_PASSWORD_BYTES)) errors.push(`비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상, UTF-8 기준 ${MAX_PASSWORD_BYTES}바이트 이하로 입력해 주세요.`)
  if (password && passwordConfirmation && password !== passwordConfirmation) errors.push('비밀번호가 일치하지 않습니다.')
  return errors
}

export async function requestSignup({ email, password, passwordConfirmation }) {
  return apiJson('/auth/signup', {
    method: 'POST', headers: await csrfHeaders(),
    body: JSON.stringify({ login_id: email.trim().toLowerCase(), password, password_confirmation: passwordConfirmation }),
  })
}

export async function verifySignup({ email, code }) {
  return apiJson('/auth/signup/verify', {
    method: 'POST', headers: await csrfHeaders(),
    body: JSON.stringify({ login_id: email.trim().toLowerCase(), code }),
  })
}

export async function resendSignupCode(email) {
  return apiJson('/auth/signup/resend', {
    method: 'POST', headers: await csrfHeaders(),
    body: JSON.stringify({ login_id: email.trim().toLowerCase(), code: '' }),
  })
}
