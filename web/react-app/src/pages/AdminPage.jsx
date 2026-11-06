import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { previewAdminService } from '../lib/admin-service'
import { usePreviewAdmin } from '../lib/use-preview-admin'

const STATUS_LABEL = { pending: '승인 대기', approved: '승인 완료', rejected: '반려' }
const DECISION_LABEL = { needs_review: '검토 필요', not_needed: '검토 불필요' }

export default function AdminPage() {
  const { decisionTables, candidates } = usePreviewAdmin()
  return <AdminDashboard decisionTables={decisionTables} candidates={candidates} adminService={previewAdminService} dataReady approvalsPath="/demo/approvals" />
}

export function AdminLivePage() {
  return <AdminDashboard decisionTables={[]} candidates={[]} dataReady={false} approvalsPath="/approvals" />
}

function AdminDashboard({ decisionTables, candidates, adminService, dataReady, approvalsPath }) {
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(() => decisionTables[0]?.id ?? null)
  const [confirmation, setConfirmation] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const visibleTables = useMemo(() => dataReady ? adminService.filterDecisionTables(decisionTables, filter) : [], [adminService, dataReady, decisionTables, filter])
  const selectedTable = decisionTables.find(item => item.id === selectedId) ?? visibleTables[0] ?? null
  const pendingCount = decisionTables.filter(item => item.status === 'pending').length
  const undecidedCount = candidates.filter(item => !item.decision).length
  const approvalStatus = useMemo(() => {
    const items = Object.keys(STATUS_LABEL).map(status => ({ status, label: STATUS_LABEL[status], count: decisionTables.filter(item => item.status === status).length }))
    return { items, total: items.reduce((total, item) => total + item.count, 0) }
  }, [decisionTables])

  async function confirmJudgement() {
    if (!confirmation || busyId || !adminService) return
    setBusyId(confirmation.candidate.id)
    try {
      await adminService.judgeMaintenanceCandidate(confirmation.candidate.id, { decision: confirmation.decision })
      setConfirmation(null)
    } finally {
      setBusyId(null)
    }
  }

  return <DemoLayout active="admin"><main className="reference-page admin-reference-page">
    <header className="reference-page-header"><div><h1>운영 현황</h1></div><span className="reference-outline-label">{dataReady ? '관리자 전용' : '데이터 연동 준비 중'}</span></header>
    <section className="admin-summary reference-panel"><div className="admin-summary-grid"><SummaryItem label="결정표" value={dataReady ? decisionTables.length : '—'} detail={dataReady ? '전체 결정표' : '데이터 연동 준비 중'} /><SummaryItem label="정책 정비 후보" value={dataReady ? undecidedCount : '—'} detail={dataReady ? '검토 대기' : '데이터 연동 준비 중'} /><SummaryItem label="처리 대기" value={dataReady ? pendingCount : '—'} detail={dataReady ? '승인 판단 필요' : '데이터 연동 준비 중'} tone="pending" /></div><ApprovalStatusDistribution {...approvalStatus} dataReady={dataReady} /></section>
    <section className="admin-table-panel reference-panel"><div className="reference-section-heading"><h2>결정표 승인 현황</h2><Link to={approvalsPath} className="reference-outline-button">승인함 보기</Link></div><div className="recall-filter-row admin-approval-filter">{[['all', '전체'], ['pending', '승인 대기'], ['approved', '승인 완료'], ['rejected', '반려']].map(([key, label]) => <button type="button" key={key} className={filter === key ? 'selected' : ''} disabled={!dataReady} onClick={() => setFilter(key)}>{label}</button>)}</div>{visibleTables.length ? <table><thead><tr><th>결정표</th><th>관련 정책 문서</th><th>요청 일시</th><th>승인 상태</th></tr></thead><tbody>{visibleTables.map(item => <tr key={item.id} className={`${selectedTable?.id === item.id ? 'selected ' : ''}${item.status === 'pending' ? 'pending' : ''}`} onClick={() => setSelectedId(item.id)}><td>{item.title}</td><td>{item.document}</td><td>{item.requestedAt}</td><td><span className="table-status">{STATUS_LABEL[item.status]}</span></td></tr>)}</tbody></table> : <p className="recall-empty">{dataReady ? '해당하는 결정표가 없습니다.' : '결정표 데이터 연동 준비 중입니다.'}</p>}{selectedTable && <div className="selected-reference admin-selected-table"><small>선택한 결정표</small><strong>{selectedTable.title}</strong><span>{selectedTable.document} · {selectedTable.requestedAt} · {STATUS_LABEL[selectedTable.status]}</span>{selectedTable.approvalId && <Link className="reference-outline-button" to={approvalsPath}>관련 승인 요청 상세 보기</Link>}</div>}</section>
    <section className="admin-table-panel reference-panel"><div className="reference-section-heading"><h2>정책 정비 후보</h2><span className="reference-outline-label">{dataReady ? `검토 대기 ${undecidedCount}건` : '데이터 연동 준비 중'}</span></div>{candidates.length ? candidates.map(candidate => <article className={`selected-reference admin-candidate${candidate.decision ? ' complete' : ' needs-review'}`} key={candidate.id}><small>관련 정책 문서</small><strong>{candidate.document}</strong><span>{candidate.relatedPolicy} · {candidate.changedContent}</span><small>정비 필요 사유</small><p>{candidate.reason}</p>{candidate.decision ? <span className="table-status">{DECISION_LABEL[candidate.decision]} · 처리 완료</span> : <div className="approval-actions"><button type="button" disabled={busyId === candidate.id} onClick={() => setConfirmation({ candidate, decision: 'not_needed' })}>검토 불필요</button><button type="button" disabled={busyId === candidate.id} onClick={() => setConfirmation({ candidate, decision: 'needs_review' })}>검토 필요</button></div>}</article>) : <p className="recall-empty">{dataReady ? '정책 정비 후보가 없습니다.' : '정책 정비 후보 데이터 연동 준비 중입니다.'}</p>}</section>
    {confirmation && <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>{DECISION_LABEL[confirmation.decision]}로 판단하시겠습니까?</h2><p>{confirmation.candidate.document}</p><div><button type="button" disabled={Boolean(busyId)} onClick={() => setConfirmation(null)}>취소</button><button type="button" disabled={Boolean(busyId)} onClick={confirmJudgement}>확인</button></div></section></div>}
  </main></DemoLayout>
}

function SummaryItem({ label, value, detail, tone }) {
  return <div className={`summary-item${tone ? ` ${tone}` : ''}`}><small>{label}</small><strong>{value}</strong><span>{detail}</span></div>
}

function ApprovalStatusDistribution({ items, total, dataReady }) {
  return <section className="admin-status-distribution" aria-labelledby="approval-status-distribution-title">
    <div><h2 id="approval-status-distribution-title">승인 처리 현황</h2><span>{dataReady ? `총 ${total}건` : '데이터 연동 준비 중'}</span></div>
    {dataReady ? <><div className="admin-status-track" role="img" aria-label={items.map(item => `${item.label} ${item.count}건`).join(', ')}>{items.filter(item => item.count > 0).map(item => <span key={item.status} className={item.status} style={{ width: `${item.count / total * 100}%` }} />)}</div><ul>{items.map(item => <li key={item.status} className={item.status}><i aria-hidden="true" /><span>{item.label}</span><b>{item.count}건</b></li>)}</ul></> : <p className="admin-data-pending">승인 상태 데이터를 연동하면 그래프가 표시됩니다.</p>}
  </section>
}
