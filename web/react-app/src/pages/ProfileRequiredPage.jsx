import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, getProfileForEdit, saveProfile } from '../lib/api'
import { useSession } from '../lib/session'
import '../profile.css'

const EMPTY_FORM = { team: '', role: '', service: '', name: '', phone: '', address: '' }
const PHONE_PATTERN = /^010\d{8}$/
const TEAM_OPTIONS = ['보안', '인프라·SRE', 'IT 운영', '재무', '개발']
const ROLE_OPTIONS = ['개발자', 'SRE', '관리자', '정책 담당자']

function formatPhone(value) {
  const digits = String(value ?? '').replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`
  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
}

function isBasicProfileComplete(form) {
  const phoneDigits = form.phone.replace(/\D/g, '')
  return Boolean(form.name.trim()) && PHONE_PATTERN.test(phoneDigits)
}

function isProfileEditComplete(form) {
  return Boolean(form.team) && Boolean(form.role) && Boolean(form.service.trim()) && isBasicProfileComplete(form)
}

function ProfileEditPage() {
  const navigate = useNavigate()
  const { user } = useSession()
  const [form, setForm] = useState(EMPTY_FORM)
  const [initialForm, setInitialForm] = useState(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    getProfileForEdit()
      .then(profile => {
        if (!active) return
        const nextForm = { team: profile.dept || '', role: '', service: '', name: profile.name || '', phone: formatPhone(profile.phone), address: profile.address || '' }
        setForm(nextForm)
        setInitialForm(nextForm)
      })
      .catch(loadError => { if (active) setError(loadError.message || '회원정보를 불러오지 못했습니다.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user?.user_id])

  const canSave = isProfileEditComplete(form)

  function update(field, value) {
    setForm(current => ({ ...current, [field]: field === 'phone' ? formatPhone(value) : value }))
    setError('')
    setNotice('')
  }

  function goBack() {
    if (JSON.stringify(form) !== JSON.stringify(initialForm) && !window.confirm('저장하지 않은 변경사항을 버리고 나가시겠습니까?')) return
    navigate('/chat')
  }

  async function submit(event) {
    event.preventDefault()
    if (!canSave || saving) return
    const memoryChanged = form.role !== initialForm.role || form.service !== initialForm.service
    const profileChanged = form.team !== initialForm.team || form.name !== initialForm.name || form.phone !== initialForm.phone || form.address !== initialForm.address
    if (!profileChanged && memoryChanged) {
      setError('업무 역할과 담당 서비스는 영구 저장 API가 아직 없어 저장할 수 없습니다.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await saveProfile({ name: form.name, dept: form.team, phone: form.phone, address: form.address })
      const savedForm = { ...form, role: initialForm.role, service: initialForm.service }
      setForm(savedForm)
      setInitialForm(savedForm)
      setNotice(memoryChanged ? '소속 팀과 기본 정보만 저장했습니다. 업무 역할과 담당 서비스는 영구 저장 API 연동 전이라 반영되지 않았습니다.' : '변경사항을 저장했습니다.')
    } catch (saveError) {
      setError(saveError instanceof ApiError && saveError.status === 422 ? '입력한 내용을 확인해 주세요.' : saveError.message || '회원정보를 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return <main className="profile-page">
    <section className="profile-card" aria-labelledby="profile-edit-title">
      <button type="button" className="profile-back-button profile-back-button-real" onClick={goBack}><span aria-hidden="true">←</span><span>뒤로가기</span></button>
      <p className="profile-eyebrow">MY INFORMATION</p>
      <h1 id="profile-edit-title">회원정보 수정</h1>
      <p className="profile-description">소속 팀과 기본 정보를 수정할 수 있습니다.</p>
      {loading ? <p role="status">회원정보를 불러오는 중입니다.</p> : <form className="profile-form profile-form-edit" onSubmit={submit} noValidate>
        <label><span>소속 팀 <em aria-hidden="true">*</em></span><select required value={form.team} onChange={event => update('team', event.target.value)}><option value="" disabled>소속 팀을 선택해 주세요.</option>{TEAM_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
        <label><span>업무 역할 <em aria-hidden="true">*</em> <small>(저장 연동 준비 중)</small></span><select required value={form.role} onChange={event => update('role', event.target.value)}><option value="">설정하지 않음</option>{ROLE_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
        <label><span>담당 서비스 <em aria-hidden="true">*</em> <small>(저장 연동 준비 중)</small></span><input required value={form.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label>
        <p className="profile-storage-notice">업무 역할은 시스템 관리자(Admin/Owner) 권한과 관계없으며, 현재 저장되지 않습니다. 담당 서비스도 현재 영구 저장 API가 없어 저장되지 않습니다.</p>
        <label><span>이름 <em aria-hidden="true">*</em></span><input required value={form.name} onChange={event => update('name', event.target.value)} autoComplete="name" /></label>
        <label><span>전화번호 <em aria-hidden="true">*</em></span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" autoComplete="tel" placeholder="예시) 010-1234-5678" /></label>
        <label><span>근무지 주소 <small>(선택)</small></span><textarea className="profile-address-field" value={form.address} onChange={event => update('address', event.target.value)} autoComplete="street-address" /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p className="profile-success" role="status">{notice}</p>}
        <button className="button button-dark" type="submit" disabled={!canSave || saving}>{saving ? '저장 중입니다.' : '변경사항 저장'}</button>
      </form>}
    </section>
  </main>
}

function ProfileOnboardingPage() {
  const navigate = useNavigate()
  const { user, refresh } = useSession()
  const [step, setStep] = useState(0)
  const [form, setForm] = useState(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const isOnboarding = user?.profile_completed === false
  const steps = useMemo(() => [
    { label: '소속 팀', title: '어느 팀에서 일하시나요?', description: '소속된 팀을 선택해 주세요.' },
    { label: '업무 역할', title: '어떤 역할을 맡고 계신가요?', description: '주로 담당하는 업무 역할을 선택해 주세요.' },
    { label: '담당 서비스', title: '어떤 서비스를 담당하시나요?', description: '담당하는 서비스를 등록해 주세요.' },
    { label: '기본 정보', title: '기본 정보를 입력해 주세요.', description: '이름과 전화번호는 필수이며, 근무지 주소는 선택 사항입니다.' },
    { label: '확인 및 등록', title: '입력한 정보를 확인해 주세요.', description: '등록 정보를 확인한 후 완료 버튼을 눌러 주세요.' },
  ], [])

  useEffect(() => {
    let active = true
    setLoading(true)
    getProfileForEdit()
      .then(profile => {
        if (!active) return
        setForm({ team: profile.dept || '', role: '', service: '', name: profile.name || '', phone: formatPhone(profile.phone), address: profile.address || '' })
      })
      .catch(loadError => { if (active && loadError?.status !== 404) setError(loadError.message || '회원정보를 불러오지 못했습니다.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user?.user_id])

  const current = steps[step]
  const canContinue = step === 0 ? Boolean(form.team) : step === 1 ? Boolean(form.role) : step === 2 ? Boolean(form.service.trim()) : step === 3 ? isBasicProfileComplete(form) : true

  function update(field, value) {
    const nextValue = field === 'phone' ? formatPhone(value) : value
    setForm(currentForm => ({ ...currentForm, [field]: nextValue }))
    setError('')
  }

  function next() {
    if (canContinue) setStep(currentStep => Math.min(currentStep + 1, steps.length - 1))
  }

  async function submit() {
    if (!canContinue || saving) return
    setSaving(true)
    setError('')
    try {
      await saveProfile({ name: form.name, dept: form.team, phone: form.phone, address: form.address })
      await refresh()
      navigate('/chat', { replace: true })
    } catch (saveError) {
      setError(saveError instanceof ApiError && saveError.status === 422 ? '입력한 내용을 확인해 주세요.' : saveError.message || '회원정보를 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return <main className="profile-page">
    <section className="profile-card profile-card-wizard" aria-labelledby="profile-title">
      <p className="profile-eyebrow">MY INFORMATION · {step + 1} / {steps.length}</p>
      <div className="profile-stepper" aria-label="등록 단계">{steps.map((item, index) => <span key={item.label} className={index <= step ? 'active' : ''}>{index + 1}</span>)}</div>
      <h1 id="profile-title">{current.title}</h1>
      <p className="profile-step-description">{current.description}</p>
      <p className="profile-storage-notice">소속 팀은 등록 완료 시 저장됩니다. 업무 역할은 시스템 관리자(Admin/Owner) 권한과 관계없으며, 현재 저장되지 않습니다. 담당 서비스도 이 화면에서만 사용되며 저장되지 않습니다.</p>
      {loading ? <p role="status">회원정보를 불러오는 중입니다.</p> : <>
        {step === 0 && <div className="profile-choice-grid">{TEAM_OPTIONS.map(option => <button type="button" key={option} className={form.team === option ? 'selected' : ''} onClick={() => update('team', option)}>{option}</button>)}</div>}
        {step === 1 && <div className="profile-choice-grid">{ROLE_OPTIONS.map(option => <button type="button" key={option} className={form.role === option ? 'selected' : ''} onClick={() => update('role', option)}>{option}</button>)}</div>}
        {step === 2 && <label className="profile-field"><span>담당 서비스</span><input required value={form.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label>}
        {step === 3 && <div className="profile-form profile-form-wizard"><label><span>이름 <em aria-hidden="true">*</em></span><input required value={form.name} onChange={event => update('name', event.target.value)} autoComplete="name" /></label><label><span>전화번호 <em aria-hidden="true">*</em></span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" autoComplete="tel" placeholder="예시) 010-1234-5678" /></label><label><span>근무지 주소 <small>(선택)</small></span><textarea className="profile-address-field" value={form.address} onChange={event => update('address', event.target.value)} autoComplete="street-address" /></label></div>}
        {step === 4 && <dl className="profile-summary"><dt>소속 팀</dt><dd>{form.team}</dd><dt>업무 역할 (저장되지 않음)</dt><dd>{form.role}</dd><dt>담당 서비스 (저장되지 않음)</dt><dd>{form.service}</dd><dt>이름</dt><dd>{form.name}</dd><dt>전화번호</dt><dd>{form.phone}</dd><dt>근무지 주소</dt><dd>{form.address || '설정하지 않음'}</dd></dl>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className={`profile-wizard-actions${step === 0 ? ' first-step' : ''}`}>{step > 0 && <button type="button" className="profile-confirm-cancel" disabled={saving} onClick={() => setStep(currentStep => currentStep - 1)}>이전</button>}{step < steps.length - 1 ? <button type="button" className="button button-dark" disabled={!canContinue || saving} onClick={next}>다음</button> : <button type="button" className="button button-dark" disabled={saving} onClick={submit}>{saving ? '저장 중입니다.' : '등록 완료'}</button>}</div>
      </>}
    </section>
  </main>
}

export default function ProfileRequiredPage() {
  const { user } = useSession()
  return user?.profile_completed === true ? <ProfileEditPage /> : <ProfileOnboardingPage />
}
