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

// 서버 칸 이름 → 화면 칸 이름 (backend/profile_api.py validate_profile)
const SERVER_FIELD_TO_FORM = { name: 'name', dept: 'team', phone: 'phone', address: 'address' }
const ADDRESS_MESSAGE = '주소는 5~100자로 입력해 주세요.'

// 서버와 같은 기준: 앞뒤 공백을 뗀 길이 5~100자 (backend/profile_api.py)
function addressError(value) {
  const length = String(value ?? '').trim().length
  return length < 5 || length > 100 ? ADDRESS_MESSAGE : ''
}

function toFormFieldErrors(fields) {
  const result = {}
  for (const [serverField, reason] of Object.entries(fields ?? {})) {
    const formField = SERVER_FIELD_TO_FORM[serverField]
    if (formField && typeof reason === 'string' && reason) result[formField] = reason
  }
  return result
}

function FieldError({ id, message }) {
  return message ? <p className="profile-field-error" id={id} role="alert">{message}</p> : null
}

function fieldProps(errors, field) {
  return errors[field] ? { 'aria-invalid': true, 'aria-describedby': `profile-error-${field}` } : {}
}

function isBasicProfileComplete(form) {
  const phoneDigits = form.phone.replace(/\D/g, '')
  return Boolean(form.name.trim()) && PHONE_PATTERN.test(phoneDigits)
}

// 업무 역할과 담당 서비스는 저장할 칸이 서버에 없다(PUT /me/profile은 name·dept·phone·address, /me/memory는 affiliation·rank만 받는다).
// 저장되지 않는 값이 저장·가입을 막지 않도록 필수 조건에서 뺐다.
function isProfileEditComplete(form) {
  return Boolean(form.team) && isBasicProfileComplete(form)
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
  const [fieldErrors, setFieldErrors] = useState({})

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
    setFieldErrors(({ [field]: _cleared, ...rest }) => rest)
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
    const localAddressError = addressError(form.address)
    if (localAddressError) {
      setFieldErrors({ address: localAddressError })
      setError('입력한 내용을 확인해 주세요.')
      return
    }
    setSaving(true)
    setError('')
    setFieldErrors({})
    try {
      await saveProfile({ name: form.name, dept: form.team, phone: form.phone, address: form.address })
      const savedForm = { ...form, role: initialForm.role, service: initialForm.service }
      setForm(savedForm)
      setInitialForm(savedForm)
      setNotice(memoryChanged ? '소속 팀과 기본 정보만 저장했습니다. 업무 역할과 담당 서비스는 영구 저장 API 연동 전이라 반영되지 않았습니다.' : '변경사항을 저장했습니다.')
    } catch (saveError) {
      if (saveError instanceof ApiError && saveError.status === 422) {
        setFieldErrors(toFormFieldErrors(saveError.fields))
        setError('입력한 내용을 확인해 주세요.')
      } else setError(saveError.message || '회원정보를 저장하지 못했습니다.')
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
        <label><span>소속 팀 <em aria-hidden="true">*</em></span><select required value={form.team} onChange={event => update('team', event.target.value)} {...fieldProps(fieldErrors, 'team')}><option value="" disabled>소속 팀을 선택해 주세요.</option>{TEAM_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
        <FieldError id="profile-error-team" message={fieldErrors.team} />
        <label><span>업무 역할 <small>(선택 · 저장 연동 준비 중)</small></span><select value={form.role} onChange={event => update('role', event.target.value)}><option value="">설정하지 않음</option>{ROLE_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
        <label><span>담당 서비스 <small>(선택 · 저장 연동 준비 중)</small></span><input value={form.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label>
        <p className="profile-storage-notice">업무 역할은 시스템 관리자(Admin/Owner) 권한과 관계없으며, 현재 저장되지 않습니다. 담당 서비스도 현재 영구 저장 API가 없어 저장되지 않습니다.</p>
        <label><span>이름 <em aria-hidden="true">*</em></span><input required value={form.name} onChange={event => update('name', event.target.value)} autoComplete="name" {...fieldProps(fieldErrors, 'name')} /></label>
        <FieldError id="profile-error-name" message={fieldErrors.name} />
        <label><span>전화번호 <em aria-hidden="true">*</em></span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" autoComplete="tel" placeholder="예시) 010-1234-5678" {...fieldProps(fieldErrors, 'phone')} /></label>
        <FieldError id="profile-error-phone" message={fieldErrors.phone} />
        <label><span>근무지 주소 <em aria-hidden="true">*</em> <small>(5~100자)</small></span><textarea required className="profile-address-field" value={form.address} onChange={event => update('address', event.target.value)} autoComplete="street-address" {...fieldProps(fieldErrors, 'address')} /></label>
        <FieldError id="profile-error-address" message={fieldErrors.address} />
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
  const [fieldErrors, setFieldErrors] = useState({})

  const isOnboarding = user?.profile_completed === false
  const steps = useMemo(() => [
    { label: '소속 팀', title: '어느 팀에서 일하시나요?', description: '소속된 팀을 선택해 주세요.' },
    { label: '업무 역할', title: '어떤 역할을 맡고 계신가요?', description: '주로 담당하는 업무 역할을 선택해 주세요.' },
    { label: '담당 서비스', title: '어떤 서비스를 담당하시나요?', description: '담당하는 서비스를 등록해 주세요.' },
    { label: '기본 정보', title: '기본 정보를 입력해 주세요.', description: '이름·전화번호·근무지 주소는 필수입니다. 주소는 5~100자로 입력해 주세요.' },
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
  const optionalStep = step === 1 || step === 2   // 업무 역할·담당 서비스: 저장되지 않는 선택 항목이라 비워도 다음으로 간다
  const canContinue = step === 0 ? Boolean(form.team) : step === 3 ? isBasicProfileComplete(form) : true

  function update(field, value) {
    const nextValue = field === 'phone' ? formatPhone(value) : value
    setForm(currentForm => ({ ...currentForm, [field]: nextValue }))
    setFieldErrors(({ [field]: _cleared, ...rest }) => rest)
    setError('')
  }

  function next() {
    if (step === 3) {
      const localAddressError = addressError(form.address)
      if (localAddressError) {
        setFieldErrors(errors => ({ ...errors, address: localAddressError }))
        return
      }
    }
    if (canContinue) setStep(currentStep => Math.min(currentStep + 1, steps.length - 1))
  }

  async function submit() {
    if (!canContinue || saving) return
    setSaving(true)
    setError('')
    setFieldErrors({})
    try {
      await saveProfile({ name: form.name, dept: form.team, phone: form.phone, address: form.address })
      await refresh()
      navigate('/chat', { replace: true })
    } catch (saveError) {
      if (saveError instanceof ApiError && saveError.status === 422) {
        // 오류 칸이 있는 단계로 돌려보내 그 칸 아래에 이유를 보여 준다 (소속 팀 = 0단계, 이름·전화·주소 = 3단계).
        const errors = toFormFieldErrors(saveError.fields)
        setFieldErrors(errors)
        setError('입력한 내용을 확인해 주세요.')
        if (errors.team) setStep(0)
        else if (errors.name || errors.phone || errors.address) setStep(3)
      } else setError(saveError.message || '회원정보를 저장하지 못했습니다.')
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
        {step === 0 && <FieldError id="profile-error-team" message={fieldErrors.team} />}
        {step === 1 && <div className="profile-choice-grid">{ROLE_OPTIONS.map(option => <button type="button" key={option} className={form.role === option ? 'selected' : ''} onClick={() => update('role', option)}>{option}</button>)}</div>}
        {optionalStep && <p className="profile-storage-notice">선택 항목입니다. 저장되지 않으므로 고르지 않고 넘어가도 됩니다.</p>}
        {step === 2 && <label className="profile-field"><span>담당 서비스</span><input value={form.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label>}
        {step === 3 && <div className="profile-form profile-form-wizard"><label><span>이름 <em aria-hidden="true">*</em></span><input required value={form.name} onChange={event => update('name', event.target.value)} autoComplete="name" {...fieldProps(fieldErrors, 'name')} /></label><FieldError id="profile-error-name" message={fieldErrors.name} /><label><span>전화번호 <em aria-hidden="true">*</em></span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" autoComplete="tel" placeholder="예시) 010-1234-5678" {...fieldProps(fieldErrors, 'phone')} /></label><FieldError id="profile-error-phone" message={fieldErrors.phone} /><label><span>근무지 주소 <em aria-hidden="true">*</em> <small>(5~100자)</small></span><textarea required className="profile-address-field" value={form.address} onChange={event => update('address', event.target.value)} autoComplete="street-address" {...fieldProps(fieldErrors, 'address')} /></label><FieldError id="profile-error-address" message={fieldErrors.address} /></div>}
        {step === 4 && <dl className="profile-summary"><dt>소속 팀</dt><dd>{form.team}</dd><dt>업무 역할 (저장되지 않음)</dt><dd>{form.role || '설정하지 않음'}</dd><dt>담당 서비스 (저장되지 않음)</dt><dd>{form.service.trim() || '설정하지 않음'}</dd><dt>이름</dt><dd>{form.name}</dd><dt>전화번호</dt><dd>{form.phone}</dd><dt>근무지 주소</dt><dd>{form.address}</dd></dl>}
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
