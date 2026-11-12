import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import AdminRoleDialog from '../components/AdminRoleDialog'
import AdminUsersTable from '../components/AdminUsersTable'
import AdminUsersTabs from '../components/AdminUsersTabs'
import { PRIVACY_NOTICE } from '../lib/privacy-notice'
import '../profile.css'
import '../admin-users.css'

const EMPTY_PROFILE = { name: '', dept: '', phone: '', address: '' }
const TEAM_OPTIONS = ['보안', '인프라·SRE', 'IT 운영', '재무', '개발']
const ROLE_OPTIONS = ['개발자', 'SRE', '관리자', '정책 담당자']
const PHONE_PATTERN = /^010\d{8}$/
let demoProfile = { team: '개발', role: '개발자', service: '결제 API', name: '김프로', phone: '010-1234-5678', address: '서울시 중구 프로베나로 1' }

const MOCK_USERS = [
  { login_id: 'local-admin', role: 'admin', is_owner: true, created_at: '2026-11-01T09:00:00Z' },
  { login_id: 'local-user', role: 'user', is_owner: false, created_at: '2026-11-02T09:00:00Z' },
  { login_id: 'demo-member', role: 'user', is_owner: false, created_at: '2026-11-03T09:00:00Z' },
]

function formatPhone(value) {
  const digits = String(value ?? '').replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`
  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
}

function isBasicProfileComplete(form) {
  return Boolean(form.team) && Boolean(form.role) && Boolean(form.service.trim()) && Boolean(form.name.trim()) && PHONE_PATTERN.test(form.phone.replace(/\D/g, ''))
}

export function DevProfilePreview({ mode = 'create' }) {
  const navigate = useNavigate()
  const editing = mode === 'edit'
  const [form, setForm] = useState(() => editing ? { ...demoProfile } : { ...EMPTY_PROFILE })
  const [initialForm] = useState(() => editing ? { ...demoProfile } : { ...EMPTY_PROFILE })
  const [saved, setSaved] = useState(false)

  const update = (field, value) => {
    if (field === 'phone') value = formatPhone(value)
    setForm(current => ({ ...current, [field]: value }))
    setSaved(false)
  }

  function goBack() {
    const dirty = JSON.stringify(form) !== JSON.stringify(initialForm)
    if (dirty && !window.confirm('저장하지 않은 변경사항을 버리고 나가시겠습니까?')) return
    navigate('/demo/chat')
  }

  function submit(event) {
    event.preventDefault()
    if (editing) demoProfile = { ...form }
    setSaved(true)
    if (!editing) navigate('/demo/chat')
  }

  return <DemoLayout active={editing ? 'myinfo-edit' : 'myinfo-create'}><main className="profile-page">
    <section className="profile-card" aria-labelledby="dev-profile-title">
      {editing && <button type="button" className="profile-back-button" onClick={goBack}><span aria-hidden="true">←</span><span>뒤로가기</span></button>}
      <p className="profile-eyebrow">DEVELOPMENT PREVIEW · MOCK DATA</p>
      <h1 id="dev-profile-title">회원정보 {editing ? '수정' : '입력'}</h1>
      <p className="profile-description">{editing ? '저장된 예시 회원정보를 수정하는 데모 화면입니다.' : '최초 로그인 시 입력하는 회원정보 화면을 체험합니다.'} 실제 서버나 DB에는 저장되지 않습니다.</p>
      <form className={`profile-form${editing ? ' profile-form-edit' : ''}`} onSubmit={submit} noValidate>
        {editing ? <>
          <label><span>소속 팀 <em aria-hidden="true">*</em></span><select required value={form.team} onChange={event => update('team', event.target.value)}><option value="" disabled>소속 팀을 선택해 주세요.</option>{TEAM_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
          <label><span>업무 역할 <em aria-hidden="true">*</em></span><select required value={form.role} onChange={event => update('role', event.target.value)}><option value="">설정하지 않음</option>{ROLE_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
          <label><span>담당 서비스 <em aria-hidden="true">*</em></span><input required value={form.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label>
          <p className="profile-storage-notice profile-privacy-notice">{PRIVACY_NOTICE}</p>
          <label><span>이름 <em aria-hidden="true">*</em></span><input required value={form.name} onChange={event => update('name', event.target.value)} /></label>
          <label><span>전화번호 <em aria-hidden="true">*</em></span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" placeholder="예시) 010-1234-5678" /></label>
          <label><span>근무지 주소 <small>(선택)</small></span><textarea className="profile-address-field" value={form.address} onChange={event => update('address', event.target.value)} /></label>
        </> : <>
          <p className="profile-storage-notice profile-privacy-notice">{PRIVACY_NOTICE}</p>
          <label><span>이름</span><input required value={form.name} onChange={event => update('name', event.target.value)} /></label>
          <label><span>소속(담당부서)</span><input required value={form.dept} onChange={event => update('dept', event.target.value)} /></label>
          <label><span>전화번호</span><input required value={form.phone} onChange={event => update('phone', event.target.value)} inputMode="tel" placeholder="010-1234-5678" /></label>
          <label><span>주소</span><textarea required value={form.address} onChange={event => update('address', event.target.value)} rows="3" /></label>
        </>}
        {saved && <p className="profile-success" role="status">변경사항을 데모 상태에 저장했습니다. 실제 서버에는 전송하지 않았습니다.</p>}
        <button className="button button-dark" type="submit" disabled={editing && !isBasicProfileComplete(form)}>{editing ? '변경사항 저장' : '회원정보 저장'}</button>
      </form>
    </section>
  </main></DemoLayout>
}

export function DevAdminUsersPreview() {
  const [users, setUsers] = useState(MOCK_USERS)
  const [message, setMessage] = useState('')
  const [confirm, setConfirm] = useState(null)

  function applyChange() {
    if (!confirm) return
    setUsers(current => current.map(item => item.login_id === confirm.login_id ? { ...item, role: confirm.action === 'promote' ? 'admin' : 'user' } : item))
    setMessage(`${confirm.login_id}의 관리자 권한을 데모 상태에서 변경했습니다.`)
    setConfirm(null)
  }

  return <DemoLayout active="admin-users"><main className="admin-users-page">
    <header><h1>권한 관리</h1></header>
    {message && <p className="profile-success" role="status">{message}</p>}
    <AdminUsersTabs users={users} onChangeRole={item => setConfirm({ login_id: item.login_id, action: item.role === 'admin' ? 'revoke' : 'promote' })} roleConfirm={confirm} onCancelRole={() => setConfirm(null)} onConfirmRole={applyChange} isPreview privacyReviewer />
    {false && <div>
      <AdminUsersTable users={users} onChangeRole={item => setConfirm({ login_id: item.login_id, action: item.role === 'admin' ? 'revoke' : 'promote' })} />
      <AdminRoleDialog confirm={confirm} onCancel={() => setConfirm(null)} onConfirm={applyChange} />
    </div>}
  </main></DemoLayout>
}
