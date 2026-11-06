import { apiJson, apiRequest } from './api'

const MIN_PASSWORD_LENGTH = 8
const MAX_PASSWORD_BYTES = 72

export function validateSignupInput({ loginId = '', email = '', password = '', passwordConfirmation = '' } = {}) {
  const errors = []
  const id = (loginId || email).trim()
  if (!id || !password || !passwordConfirmation) errors.push('아이디와 비밀번호, 비밀번호 확인을 모두 입력해 주세요.')
  if (id.length > 64 || /\s/.test(id)) errors.push('아이디는 공백 없이 64자 이하로 입력해 주세요.')
  const passwordBytes = typeof TextEncoder === 'function' ? new TextEncoder().encode(password).length : password.length
  if (password && (password.length < MIN_PASSWORD_LENGTH || passwordBytes > MAX_PASSWORD_BYTES)) errors.push(`비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상, UTF-8 기준 ${MAX_PASSWORD_BYTES}바이트 이하로 입력해 주세요.`)
  if (password && passwordConfirmation && password !== passwordConfirmation) errors.push('비밀번호와 비밀번호 확인이 일치하지 않습니다.')
  return errors
}

export async function requestSignup({ loginId, password, passwordConfirmation }) {
  await apiRequest('/auth/csrf')
  const csrfToken = document.cookie.split('; ').find(cookie => cookie.startsWith('provena_csrf='))?.split('=')[1]
  if (!csrfToken) throw new Error('CSRF 토큰을 받을 수 없습니다.')
  return apiJson('/auth/signup', {
    method: 'POST',
    headers: { 'X-CSRF-Token': decodeURIComponent(csrfToken) },
    body: JSON.stringify({ login_id: loginId, password, password_confirmation: passwordConfirmation }),
  })
}
