import { useMemo, useState } from 'react'
import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { useSession } from '../lib/session'

const recallItems = [
  { id: 'r1', title: '배포 승인 정책이 수정되었습니다', time: '2026-11-03', question: '긴급 변경은 어떻게 승인받나요?', before: '긴급 변경은 사후 기록으로 충분합니다.', after: '긴급 변경도 승인 담당자와 사후 검토를 남겨야 합니다.', reason: '배포 승인 섹션이 개정되어 기존 답변의 결론을 다시 확인해야 합니다.' },
  { id: 'r2', title: '제3자 위험 관리 섹션이 변경되었습니다', time: '2026-11-02', question: '외부 업체의 위험은 어떻게 검토하나요?', before: '구매 요청 시 위험 검토를 고려합니다.', after: '데이터·보안·업무 연속성 위험을 구매 전에 검토합니다.', reason: '제3자 위험의 필수 검토 항목이 추가되었습니다.' },
]

export function DemoRecallsPage() {
  const [done, setDone] = useState([])
  const [selected, setSelected] = useState(recallItems[0])
  const acknowledge = id => setDone(current => current.includes(id) ? current : [...current, id])
  return <DemoLayout active="recalls" title="리콜 알림"><main className="demo-content"><header className="demo-page-heading"><div><h1>리콜 알림</h1><p>정책 변경으로 다시 확인이 필요한 과거 답변입니다.</p></div><div className="demo-heading-actions"><span className="demo-count">확인 안 함 {recallItems.length - done.length}건</span><button type="button" className="demo-dark-button" onClick={() => setDone(recallItems.map(item => item.id))}>모두 확인</button></div></header><div className="demo-two-column"><aside className="demo-list-panel"><h2>알림 목록</h2>{recallItems.map(item => <button key={item.id} type="button" className={`demo-list-item ${selected.id === item.id ? 'selected' : ''}`} onClick={() => setSelected(item)}><span>{item.title}</span><small>{done.includes(item.id) ? '확인 완료' : '미확인'} · {item.time}</small></button>)}<Link className="demo-inline-link" to="/demo/changes">바뀐 섹션 전체 기록은 변경 감시에서 →</Link></aside><article className="demo-detail-panel"><h2>{selected.title}</h2><p className="demo-muted">상태: {done.includes(selected.id) ? '확인 완료' : '확인 필요'} · 개정일 {selected.time}</p><DemoField label="당시 질문">{selected.question}</DemoField><div className="demo-card-grid"><DemoField label="변경 전 답변">{selected.before}</DemoField><DemoField label="변경 후 답변">{selected.after}</DemoField></div><DemoField label="왜 답변이 변경되었나요?">{selected.reason}</DemoField><button type="button" className="demo-dark-button" disabled={done.includes(selected.id)} onClick={() => acknowledge(selected.id)}>{done.includes(selected.id) ? '✓ 확인 완료' : '내용 확인 완료'}</button></article></div></main></DemoLayout>
}

const approvalItems = [
  { id: 'a1', title: '구매 권한표 변환 검토', kind: 'decision_table', source: 'Finance Authorization Matrix · 2023-05', result: '금액 구간별 승인자 결정표', issue: '주석과 원문 칸의 대응을 확인해야 합니다.' },
  { id: 'a2', title: '연결 정책 변경 후보', kind: 'issue_table', source: 'Change Management', result: '연결 정책 후보 3건', issue: '변경된 섹션의 영향 범위를 검토해야 합니다.' },
]

export function DemoApprovalsPage() {
  const [filter, setFilter] = useState('pending'); const [selected, setSelected] = useState(approvalItems[0]); const [message, setMessage] = useState('')
  return <DemoLayout active="approvals" title="승인함"><main className="demo-content"><header className="demo-page-heading"><div><h1>승인함</h1><p>팀 검토 결과와 결정표를 원문과 대조합니다.</p></div><span className="demo-count">관리자 디자인 미리보기</span></header><div className="demo-filter-row">{[['pending', '대기'], ['approved', '승인'], ['rejected', '반려']].map(([key, label]) => <button type="button" key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div><div className="demo-two-column approval-layout"><aside className="demo-list-panel">{approvalItems.map(item => <button key={item.id} type="button" className={`demo-list-item ${selected.id === item.id ? 'selected' : ''}`} onClick={() => setSelected(item)}><span>{item.title}</span><small>{item.kind} · {filter}</small></button>)}</aside><article className="demo-detail-panel"><span className="demo-readonly">읽기 전용 데모</span><h2>{selected.title}</h2><div className="demo-card-grid"><DemoField label="원문 정책 / 권한표">{selected.source}</DemoField><DemoField label="변환 결정표 / 쟁점표">{selected.result}</DemoField></div><DemoField label="팀별 검토 쟁점">{selected.issue}</DemoField><div className="demo-action-row"><button type="button" className="demo-dark-button" onClick={() => setMessage('데모 화면에서는 승인 요청을 저장하지 않습니다.')}>승인 미리보기</button><button type="button" className="demo-outline-button" onClick={() => setMessage('데모 화면에서는 반려 요청을 저장하지 않습니다.')}>반려 미리보기</button></div>{message && <p className="demo-notice" role="status">{message}</p>}</article></div></main></DemoLayout>
}

export function DemoOnboardingPage() {
  const steps = [{ title: '어느 팀에서 일하세요?', options: ['보안', '인프라·SRE', 'IT 운영', '재무', '개발'] }, { title: '역할은 무엇인가요?', options: ['개발자', 'SRE', '팀장', '정책 담당자'] }, { title: '담당하는 서비스가 있나요?', options: [] }, { title: '이렇게 기억할게요', options: [] }]
  const [step, setStep] = useState(0); const [answers, setAnswers] = useState({ team: '', role: '', service: '' }); const keys = ['team', 'role', 'service']; const current = steps[step]
  const next = () => step < steps.length - 1 ? setStep(step + 1) : undefined
  return <DemoLayout active="onboarding" title="AI 기억 설정"><main className="onboarding-demo"><div className="demo-stepper">{steps.map((item, index) => <span key={item.title} className={index <= step ? 'active' : ''}>{index + 1}</span>)}</div><section className="demo-form-card"><small className="mono-label">STEP {step + 1} / {steps.length}</small><h1>{current.title}</h1><p>답을 고를 때만 사용하는 로컬 데모 기억입니다. 실제 계정이나 서버에는 저장되지 않습니다.</p>{step < 2 ? <div className="demo-choice-grid">{current.options.map(option => <button type="button" key={option} className={answers[keys[step]] === option ? 'selected' : ''} onClick={() => setAnswers({ ...answers, [keys[step]]: option })}>{option}</button>)}</div> : step === 2 ? <input className="demo-text-input" value={answers.service} onChange={event => setAnswers({ ...answers, service: event.target.value })} placeholder="예: 결제 API, 사내 모니터링" /> : <dl className="demo-summary"><dt>팀</dt><dd>{answers.team || '—'}</dd><dt>역할</dt><dd>{answers.role || '—'}</dd><dt>담당 서비스</dt><dd>{answers.service || '—'}</dd></dl>}<div className="demo-form-actions"><button type="button" className="demo-outline-button" disabled={step === 0} onClick={() => setStep(step - 1)}>이전</button>{step < steps.length - 1 ? <button type="button" className="demo-dark-button" onClick={next}>다음</button> : <Link className="demo-dark-button" to="/demo/chat">채팅 시작</Link>}</div></section></main></DemoLayout>
}

const changeRows = [
  ['06:12:04', 'MODIFIED', 'security', 'Third Party Risk Management', '인용한 답 2건 재판정 대기'], ['06:12:44', 'ADDED', 'finance', 'Procurement Approval Guide', '새 섹션'], ['06:13:18', 'REMOVED', 'infra', 'Legacy Deployment Procedure', '인용한 답 1건 근거 잃음'], ['06:14:02', 'HELD', 'support', 'Knowledge Base Style Guide', '삭제 보류 · 목록 불완전'],
]

export function DemoChangesPage() {
  const [query, setQuery] = useState(''); const [enabled, setEnabled] = useState({ MODIFIED: true, ADDED: true, REMOVED: true, HELD: true }); const [live, setLive] = useState(true)
  const rows = useMemo(() => changeRows.filter(row => enabled[row[1]] && (!query.trim() || row[3].toLowerCase().includes(query.trim().toLowerCase()))), [enabled, query])
  return <DemoLayout active="changes" title="정책 변경 감시"><main className="demo-content"><header className="demo-page-heading"><div><h1>정책 변경 감시</h1><p>정시 동기화가 찾은 바뀐 섹션의 정적 데모입니다.</p></div><code>129243bc → e1f04a7c</code></header><div className="change-tools"><input value={query} onChange={event => setQuery(event.target.value)} placeholder="페이지 이름 검색" aria-label="페이지 이름 검색" /><div>{Object.keys(enabled).map(kind => <button type="button" key={kind} className={enabled[kind] ? 'selected' : ''} onClick={() => setEnabled({ ...enabled, [kind]: !enabled[kind] })}>{kind}</button>)}</div><button type="button" className="demo-outline-button" onClick={() => setLive(!live)}>{live ? '일시정지' : '다시 시작'}</button></div><div className="change-log" role="log" aria-label="바뀐 섹션 목록">{rows.map(row => <div key={`${row[0]}-${row[3]}`} className={`change-row ${row[1] === 'REMOVED' ? 'removed' : ''}`}><span>{row[0]}</span><b>{row[1]}</b><span>{row[2]}</span><strong>{row[3]}</strong><em> · {row[4]}</em></div>)}</div><p className="demo-notice">{live ? '동기화 중' : '동기화 일시정지'} · 데모 데이터이며 실제 변경 감시나 알림을 실행하지 않습니다.</p></main></DemoLayout>
}

export function DemoAdminPage() { return <DemoLayout active="admin" title="운영 현황"><main className="demo-content"><header className="demo-page-heading"><div><h1>운영 현황</h1><p>기준 데이터와 시스템 상태를 확인하는 관리자 화면 미리보기입니다.</p></div><span className="demo-readonly">읽기 전용 데모</span></header><div className="demo-admin-grid"><DemoField label="결정표">3건 · 최신 판 2023-05</DemoField><DemoField label="연결 정책 후보">4건 · 검토 대기</DemoField><DemoField label="데모 권한">관리자 권한 없음</DemoField></div><p className="demo-notice">데모 화면에서는 관리자 API를 호출하지 않으며 승인·변경·저장 기능을 실행하지 않습니다.</p></main></DemoLayout> }

function DemoField({ label, children }) { return <section className="demo-field"><small>{label}</small><p>{children}</p></section> }

export function DemoRouteGuard({ children }) { const [params] = useSearchParams(); const { pathname } = useLocation(); const demoPath = pathname.startsWith('/demo/'); return import.meta.env.DEV && (demoPath || params.get('demo') === '1') ? children : <Navigate to="/login" replace /> }
export function AdminRouteGuard({ children }) { const { status, user } = useSession(); const { pathname } = useLocation(); const [params] = useSearchParams(); const demoAccess = import.meta.env.DEV && (pathname.startsWith('/demo/') || params.get('demo') === '1'); if (status === 'checking' && !demoAccess) return null; return user?.role === 'admin' || demoAccess ? children : <Navigate to={user ? '/chat' : '/login'} replace /> }
