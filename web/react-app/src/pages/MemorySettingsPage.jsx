import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { useSession } from '../lib/session'
import { DEFAULT_SETTINGS, previewMemoryService } from '../lib/memory-service'

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
  const [step, setStep] = useState(0)
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    previewMemoryService.getMemorySettings(ownerId).then(value => { if (active) setSettings(value) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [ownerId])

  const current = steps[step]
  const keys = ['team', 'role']
  const canContinue = step === 0 ? Boolean(settings.team) : step === 1 ? Boolean(settings.role) : true
  const update = (key, value) => setSettings(currentSettings => ({ ...currentSettings, [key]: value }))

  function next() {
    if (canContinue && step < steps.length - 1) setStep(currentStep => currentStep + 1)
  }

  async function saveAndStart() {
    if (saving) return
    setSaving(true)
    try {
      await previewMemoryService.saveMemorySettings(ownerId, settings)
      navigate(user ? '/chat' : '/demo/chat')
    } finally {
      setSaving(false)
    }
  }

  return <DemoLayout active="onboarding"><main className="onboarding-demo"><div className="demo-stepper">{steps.map((item, index) => <span key={item.label} className={index <= step ? 'active' : ''} title={item.label}>{index + 1}</span>)}</div><section className="demo-form-card"><small className="mono-label">STEP {step + 1} / {steps.length} · {current.label}</small><h1>{current.title}</h1>{loading ? <p>설정을 불러오는 중입니다.</p> : step < 2 ? <div className="demo-choice-grid">{current.options.map(option => <button type="button" key={option} className={settings[keys[step]] === option ? 'selected' : ''} onClick={() => update(keys[step], option)}>{option}</button>)}</div> : step === 2 ? <label className="memory-service-field"><span>담당 서비스 (선택)</span><input className="demo-text-input" value={settings.service} onChange={event => update('service', event.target.value)} placeholder="예: 결제 API, 사내 모니터링" /></label> : <dl className="demo-summary"><dt>소속 팀</dt><dd>{settings.team || '설정하지 않음'}</dd><dt>업무 역할</dt><dd>{settings.role || '설정하지 않음'}</dd><dt>담당 서비스</dt><dd>{settings.service || '설정하지 않음'}</dd></dl>}<div className="demo-form-actions"><button type="button" className="demo-outline-button" disabled={step === 0 || loading || saving} onClick={() => setStep(currentStep => currentStep - 1)}>이전</button>{step < steps.length - 1 ? <button type="button" className="demo-dark-button" disabled={!canContinue || loading || saving} onClick={next}>다음</button> : <button type="button" className="demo-dark-button" disabled={loading || saving} onClick={saveAndStart}>{saving ? '저장 중입니다.' : '저장하고 채팅 시작'}</button>}</div></section></main></DemoLayout>
}
