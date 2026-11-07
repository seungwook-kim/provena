import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { useSession } from '../lib/session'
import { DEFAULT_SETTINGS, apiMemoryService, previewMemoryService } from '../lib/memory-service'

const steps = [
  { label: '소속 팀', title: '어느 팀에서 일하시나요?', options: ['보안', '인프라·SRE', 'IT 운영', '재무', '개발'] },
  { label: '업무 역할', title: '주로 어떤 역할을 맡고 있나요?', options: ['개발자', 'SRE', '관리자', '정책 담당자'] },
  { label: '담당 서비스', title: '담당하는 서비스를 알려 주세요.', options: [] },
  { label: '설정 확인', title: '설정 내용을 확인해 주세요', options: [] },
]

export default function MemorySettingsPage() {
  const navigate = useNavigate()
  const { user } = useSession()
  const ownerId = user?.user_id || 'anonymous'
  const memoryService = user ? apiMemoryService : previewMemoryService
  const [step, setStep] = useState(0)
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError] = useState('')
  const isApiMode = Boolean(user)

  useEffect(() => {
    let active = true
    memoryService.getMemorySettings(ownerId).then(value => { if (active) setSettings(value) }).catch(() => { if (active) setError('Memory API를 불러오지 못했습니다.') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [memoryService, ownerId])

  useEffect(() => {
    const card = document.querySelector('.demo-form-card')
    if (!card) return
    let alert = card.querySelector('[data-memory-error]')
    if (error) {
      if (!alert) { alert = document.createElement('p'); alert.dataset.memoryError = 'true'; alert.setAttribute('role', 'alert'); card.prepend(alert) }
      alert.textContent = error
    } else if (alert) alert.remove()
  }, [error])

  const current = steps[step]
  const keys = ['team', 'role']
  const canContinue = step === 0 ? Boolean(settings.team) : step === 1 ? Boolean(settings.role) : true
  const update = (key, value) => { setError(''); setSettings(currentSettings => ({ ...currentSettings, [key]: value })) }

  function next() {
    if (canContinue && step < steps.length - 1) setStep(currentStep => currentStep + 1)
  }

  async function saveAndStart() {
    if (saving || resetting) return
    setSaving(true)
    try {
      await memoryService.saveMemorySettings(ownerId, settings)
      navigate(user ? '/chat' : '/demo/chat')
    } catch {
      setError(isApiMode ? 'Memory API에 저장하지 못했습니다. 입력 내용을 확인하고 다시 시도해 주세요.' : '설정을 저장하지 못했습니다. 다시 시도해 주세요.')
    } finally {
      setSaving(false)
    }
  }

  async function resetMemory() {
    if (saving || resetting || loading) return
    if (!window.confirm('기억을 모두 초기화할까요?')) return
    setResetting(true)
    setError('')
    try {
      await memoryService.resetMemorySettings(ownerId)
      setSettings({ ...DEFAULT_SETTINGS })
      setStep(0)
    } catch {
      setError(isApiMode ? '기억 초기화에 실패했습니다. 다시 시도해 주세요.' : '설정 초기화에 실패했습니다. 다시 시도해 주세요.')
    } finally {
      setResetting(false)
    }
  }

  return <DemoLayout active="onboarding"><main className="onboarding-demo"><div className="demo-stepper">{steps.map((item, index) => <span key={item.label} className={index <= step ? 'active' : ''} title={item.label}>{index + 1}</span>)}</div><section className="demo-form-card"><small className="mono-label">STEP {step + 1} / {steps.length} · {current.label}</small><h1>{current.title}</h1>{loading ? <p>설정을 불러오는 중입니다.</p> : step < 2 ? <div className="demo-choice-grid">{current.options.map(option => <button type="button" key={option} className={settings[keys[step]] === option ? 'selected' : ''} onClick={() => update(keys[step], option)}>{option}</button>)}</div> : step === 2 ? <label className="memory-service-field"><span>담당 서비스 (선택)</span><input className="demo-text-input" value={settings.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label> : <dl className="demo-summary"><dt>소속 팀</dt><dd>{settings.team || '설정하지 않음'}</dd><dt>업무 역할</dt><dd>{settings.role || '설정하지 않음'}</dd><dt>담당 서비스</dt><dd>{settings.service || '설정하지 않음'}</dd></dl>}<div className="demo-form-actions"><button type="button" className="demo-outline-button" disabled={step === 0 || loading || saving || resetting} onClick={() => setStep(currentStep => currentStep - 1)}>이전</button>{step < steps.length - 1 ? <button type="button" className="demo-dark-button" disabled={!canContinue || loading || saving || resetting} onClick={next}>다음</button> : <><button type="button" className="demo-outline-button" disabled={loading || saving || resetting} onClick={resetMemory}>{resetting ? '초기화 중...' : '기억 초기화'}</button><button type="button" className="demo-dark-button" disabled={loading || saving || resetting} onClick={saveAndStart}>{saving ? '저장 중입니다.' : '저장하고 채팅 시작'}</button></>}</div></section></main></DemoLayout>
}
