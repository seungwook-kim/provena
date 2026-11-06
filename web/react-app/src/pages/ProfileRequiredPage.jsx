import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, getProfileForEdit, saveProfile } from '../lib/api'
import { useSession } from '../lib/session'
import '../profile.css'

const EMPTY_PROFILE = { name: '', dept: '', phone: '', address: '' }

function formatPhone(value) {
  const digits = String(value ?? '').replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`
  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
}

export default function ProfileRequiredPage() {
  const navigate = useNavigate()
  const { user, refresh } = useSession()
  const [form, setForm] = useState(EMPTY_PROFILE)
  const [initialForm, setInitialForm] = useState(EMPTY_PROFILE)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const cancelButtonRef = useRef(null)

  useEffect(() => {
    let active = true
    setForm(EMPTY_PROFILE)
    setInitialForm(EMPTY_PROFILE)
    getProfileForEdit()
      .then(profile => {
        if (active) {
          const loaded = { name: profile.name ?? '', dept: profile.dept ?? '', phone: formatPhone(profile.phone), address: profile.address ?? '' }
          setForm(loaded)
          setInitialForm(loaded)
        }
      })
      .catch(profileError => {
        if (active && profileError.status !== 404) setError(profileError.message || '회원정보를 불러오지 못했습니다.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user?.user_id])

  function update(field, value) {
    if (field === 'phone') value = formatPhone(value)
    setForm(current => ({ ...current, [field]: value }))
    setError('')
    setMessage('')
  }

  async function submit(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    setSaving(true)
    try {
      await saveProfile(form)
      await refresh()
      setMessage('회원정보를 저장했습니다.')
      navigate('/chat', { replace: true })
    } catch (saveError) {
      setError(saveError instanceof ApiError && saveError.status === 422 ? '입력한 내용을 확인해 주세요.' : saveError.message || '회원정보를 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  function goBack() {
    const dirty = JSON.stringify(form) !== JSON.stringify(initialForm)
    if (dirty) {
      setConfirmOpen(true)
      return
    }
    navigate('/chat')
  }

  useEffect(() => {
    if (!confirmOpen) return undefined
    cancelButtonRef.current?.focus()
    function handleEscape(event) {
      if (event.key === 'Escape') setConfirmOpen(false)
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [confirmOpen])

  return (
    <main className="profile-page">
      <section className="profile-card" aria-labelledby="profile-title">
        {user?.profile_completed && <button type="button" className="profile-back-button profile-back-button-real" onClick={goBack}>← 뒤로가기</button>}
        <p className="profile-eyebrow">MY INFORMATION</p>
        <h1 id="profile-title">회원정보 {user?.profile_completed ? '수정' : '입력'}</h1>
        <p className="profile-description">서비스를 사용하기 전에 회원정보를 입력해 주세요. 저장된 개인정보는 서버에서 암호화됩니다.</p>
        {loading ? <p role="status">회원정보를 불러오는 중입니다.</p> : <form className="profile-form" onSubmit={submit} noValidate>
          <label><span>이름</span><input required value={form.name} onChange={event => update('name', event.target.value)} autoComplete="name" /></label>
          <label><span>소속(담당부서)</span><input required value={form.dept} onChange={event => update('dept', event.target.value)} /></label>
          <label><span>전화번호</span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" autoComplete="tel" placeholder="010-1234-5678" /></label>
          <label><span>주소</span><textarea required value={form.address} onChange={event => update('address', event.target.value)} autoComplete="street-address" rows="3" /></label>
          {(error || message) && <p className={error ? 'form-error' : 'profile-success'} role="alert">{error || message}</p>}
          <button className="button button-dark" type="submit" disabled={saving}>{saving ? '저장 중입니다.' : user?.profile_completed ? '변경사항 저장' : '회원정보 저장'}</button>
        </form>}
      </section>
      {confirmOpen && <div className="profile-confirm-backdrop" role="presentation"><section className="profile-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="profile-confirm-title"><h2 id="profile-confirm-title">안내</h2><p>변경사항을 저장하지 않고 나가시겠습니까?</p><small>저장하지 않은 내용은 사라집니다.</small><div className="profile-confirm-actions"><button type="button" className="profile-confirm-cancel" ref={cancelButtonRef} onClick={() => setConfirmOpen(false)}>취소</button><button type="button" className="button button-dark" onClick={() => navigate('/chat')}>확인</button></div></section></div>}
    </main>
  )
}
