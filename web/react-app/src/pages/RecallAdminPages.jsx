import { useState } from 'react'
import DemoLayout from '../components/DemoLayout'

const recallItems = [
  { id: 'r1', title: '알림 01 · 외부 SaaS 도입 승인 절차 변경', date: '2026-10-21', question: '신규 외부 SaaS 도구를 도입하려면 어떤 절차가 필요한가요?', before: '팀 담당자의 승인 절차를 진행하면 됩니다.', after: '팀 담당자 승인 전에 보안 검토 단계도 확인해야 합니다.', beforeSection: '도구 도입 승인 절차 안내', afterSection: '보안 검토 단계가 포함된 도구 도입 절차', reason: '승인 절차에 대한 정책 설명이 개정되어 기존 답변에 안내하지 않았던 검토 단계가 추가되었습니다.' },
  { id: 'r2', title: '알림 02 · 장애 대응 절차 안내 변경', date: '2026-10-23', question: '장애가 발생하면 어떤 순서로 대응하나요?', before: '담당자에게 장애 상황을 전달합니다.', after: '상황 공유와 원인 분류 후 담당자에게 전달합니다.', beforeSection: '장애 대응 안내', afterSection: '장애 대응 및 원인 분류 절차', reason: '장애 대응 정책의 순서가 개정되어 답변을 다시 확인해야 합니다.' },
  { id: 'r3', title: '알림 03 · 계정 접근 정책 변경', date: '2026-10-25', question: '계정 접근 권한은 어떻게 검토하나요?', before: '팀 리더가 접근 권한을 확인합니다.', after: '팀 리더와 보안 담당자가 함께 접근 권한을 확인합니다.', beforeSection: '계정 접근 권한 안내', afterSection: '보안 담당자 검토가 포함된 접근 권한 안내', reason: '접근 정책에 보안 담당자 검토 항목이 추가되었습니다.' },
]

const decisionTables = [
  ['권한 변경 결정표', 'Access Management', '2026-10-28', '승인됨'],
  ['장애 대응 결정표', 'Incident Management', '2026-10-26', '검토 중'],
  ['변경 관리 결정표', 'Change Management', '2026-10-21', '초안'],
]

const policyCandidates = [
  ['Access Management', '권한 변경 결정표', '링크', '미확인'],
  ['Incident Management', '장애 대응 결정표', '링크', '확인 필요'],
]

export function RecallReferencePage() {
  const [done, setDone] = useState([])
  const [selected, setSelected] = useState(recallItems[0])
  const acknowledge = id => setDone(current => current.includes(id) ? current : [...current, id])

  return <DemoLayout active="recalls"><main className="reference-page recall-reference-page">
    <header className="reference-page-header"><h1>리콜 알림</h1></header>
    <section className="recall-reference-card">
      <aside className="recall-reference-list"><h2>알림 목록</h2>{recallItems.map(item => <button key={item.id} type="button" className={`recall-reference-item ${selected.id === item.id ? 'selected' : ''}`} onClick={() => setSelected(item)}><strong>{item.title}</strong><span className={`recall-status ${done.includes(item.id) ? 'complete' : ''}`}>{done.includes(item.id) ? '확인 완료' : '미확인'}</span><small>개정일 {item.date} · 변경된 답변 보기</small></button>)}</aside>
      <article className="recall-reference-detail"><div className="reference-detail-heading"><div><h2>{selected.title.replace(/^알림 \d+ · /, '')}</h2><p>상태: {done.includes(selected.id) ? '확인 완료' : '미확인'} · 개정일 {selected.date}</p></div><button type="button" className="reference-outline-button" disabled={done.includes(selected.id)} onClick={() => acknowledge(selected.id)}>{done.includes(selected.id) ? '확인 완료' : '내용 확인 완료'}</button></div>
        <ReferenceLabel>당시 질문</ReferenceLabel><div className="reference-question">{selected.question}</div>
        <ReferenceLabel>과거 AI 답변과 변경된 AI 답변</ReferenceLabel><div className="reference-two-column"><ReferenceBox title="변경 전 답변">{selected.before}</ReferenceBox><ReferenceBox title="변경 후 답변" emphasized>{selected.after}</ReferenceBox></div>
        <ReferenceLabel>관련 정책 개정 전후</ReferenceLabel><div className="reference-two-column"><ReferenceBox title="이전 정책 섹션">{selected.beforeSection}</ReferenceBox><ReferenceBox title="개정된 정책 섹션">{selected.afterSection}</ReferenceBox></div>
        <ReferenceLabel>왜 답변이 변경되었나요?</ReferenceLabel><div className="reference-reason">{selected.reason}</div>
      </article>
    </section>
  </main></DemoLayout>
}

export function AdminReferencePage() {
  const [selectedDecision, setSelectedDecision] = useState(decisionTables[0])
  const [selectedCandidate, setSelectedCandidate] = useState(policyCandidates[0])
  return <DemoLayout active="admin"><main className="reference-page admin-reference-page">
    <header className="reference-page-header"><div><h1>관리자</h1></div><span className="reference-outline-label">관리자 전용</span></header>
    <section className="admin-summary reference-panel"><h2>결정표 상태 요약 / 연결 정책 상태 요약</h2><div className="admin-summary-grid"><SummaryItem label="결정표 수 / 승인 대기" value="3 / 2" /><SummaryItem label="연결 정책 후보" value="2" /><SummaryItem label="마지막 동기화" value="서버 연결 전" /></div></section>
    <section className="admin-table-panel reference-panel"><div className="reference-section-heading"><h2>결정표 목록</h2><button type="button" className="reference-outline-button">상세 보기</button></div><table><thead><tr><th>결정표</th><th>근거 정책</th><th>판 날짜</th><th>승인 상태</th></tr></thead><tbody>{decisionTables.map(row => <tr key={row[0]} className={selectedDecision[0] === row[0] ? 'selected' : ''} onClick={() => setSelectedDecision(row)}>{row.map((cell, index) => <td key={cell}>{index === 3 ? <span className="table-status">{cell}</span> : cell}</td>)}</tr>)}</tbody></table><div className="selected-reference"><small>선택한 결정표</small><strong>{selectedDecision[0]}</strong><span>{selectedDecision[1]} · {selectedDecision[2]} · {selectedDecision[3]}</span></div></section>
    <section className="admin-table-panel reference-panel"><div className="reference-section-heading"><h2>연결 정책 검토 후보</h2><button type="button" className="reference-outline-button">후보 확인</button></div><table><thead><tr><th>변경된 정책</th><th>연결 정책 후보</th><th>연결 유형</th><th>검토 상태</th></tr></thead><tbody>{policyCandidates.map(row => <tr key={row[0]} className={selectedCandidate[0] === row[0] ? 'selected' : ''} onClick={() => setSelectedCandidate(row)}>{row.map(cell => <td key={cell}>{cell}</td>)}</tr>)}</tbody></table><div className="selected-reference"><small>선택한 연결 정책 후보</small><strong>{selectedCandidate[1]}</strong><span>{selectedCandidate[0]} · {selectedCandidate[2]} · {selectedCandidate[3]}</span></div></section>
  </main></DemoLayout>
}

function ReferenceLabel({ children }) { return <h3 className="reference-label">{children}</h3> }
function ReferenceBox({ title, emphasized = false, children }) { return <div className={`reference-box ${emphasized ? 'emphasized' : ''}`}><strong>{title}</strong><p>{children}</p></div> }
function SummaryItem({ label, value }) { return <div className="summary-item"><small>{label}</small><strong>{value}</strong></div> }
