import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { previewAdminService } from '../lib/admin-service'
import { getLiveServices, useServiceSnapshot } from '../lib/live-services'
import { useSession } from '../lib/session'
import { usePreviewAdmin } from '../lib/use-preview-admin'

const STATUS_LABEL = { pending: '승인 대기', approved: '승인 완료', rejected: '반려' }
const DECISION_LABEL = { needs_review: '검토 필요', not_needed: '검토 불필요' }
const ALL_STATUSES = ['pending', 'approved', 'rejected']
// 실제 API에는 반려된 결정표 목록이 없다(GET /decision-tables는 승인된 표만, GET /approvals는 승인 대기만 준다).
const LIVE_STATUSES = ['pending', 'approved']

export default function AdminPage() {
  const { decisionTables, candidates } = usePreviewAdmin()
  return <AdminDashboard decisionTables={decisionTables} candidates={candidates} adminService={previewAdminService} dataReady approvalsPath="/demo/approvals" />
}

export function AdminLivePage() {
  const { user } = useSession()
  const service = getLiveServices(user.user_id).admin   // 사용자마다 따로 둔다(다른 계정의 목록이 남지 않는다)
  const snapshot = useServiceSnapshot(service)
  useEffect(() => { service.load() }, [service])
  const live = { loading: snapshot.status !== 'ready', tablesError: snapshot.tablesError, candidatesError: snapshot.candidatesError, onRetry: () => service.load() }
  return <AdminDashboard decisionTables={snapshot.decisionTables} candidates={snapshot.candidates} adminService={service} dataReady approvalsPath="/approvals" live={live} statuses={snapshot.decisionTables.some(item => item.status === 'rejected') ? ALL_STATUSES : LIVE_STATUSES} />
}

function AdminDashboard({ decisionTables, candidates, adminService, dataReady, approvalsPath, live = null, statuses = ALL_STATUSES }) {
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(() => decisionTables[0]?.id ?? null)
  const [confirmation, setConfirmation] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [judgeError, setJudgeError] = useState('')
  // 실제 데이터는 불러오는 중·오류·빈 목록을 구분한다. 오류를 "없음"으로 보이지 않는다.
  const loading = Boolean(live?.loading)
  const tablesError = live?.tablesError ?? ''
  const candidatesError = live?.candidatesError ?? ''
  const tablesReady = dataReady && !loading && !tablesError
  const candidatesReady = dataReady && !loading && !candidatesError
  const waitingText = !dataReady ? '데이터 연동 준비 중' : loading ? '불러오는 중' : '불러오지 못했습니다'
  const visibleTables = useMemo(() => tablesReady ? adminService.filterDecisionTables(decisionTables, filter) : [], [adminService, tablesReady, decisionTables, filter])
  const selectedTable = tablesReady ? decisionTables.find(item => item.id === selectedId) ?? visibleTables[0] ?? null : null
  const pendingCount = decisionTables.filter(item => item.status === 'pending').length
  const undecidedCount = candidates.filter(item => !item.decision).length
  const approvalStatus = useMemo(() => {
    const items = statuses.map(status => ({ status, label: STATUS_LABEL[status], count: decisionTables.filter(item => item.status === status).length }))
    return { items, total: items.reduce((total, item) => total + item.count, 0) }
  }, [decisionTables, statuses])

  async function confirmJudgement() {
    if (!confirmation || busyId || !adminService) return
    setBusyId(confirmation.candidate.id)
    setJudgeError('')
    try {
      await adminService.judgeMaintenanceCandidate(confirmation.candidate.id, { decision: confirmation.decision })
      setConfirmation(null)
    } catch (error) {
      setJudgeError(error?.message || '판단을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
    } finally {
      setBusyId(null)
    }
  }

  function openConfirmation(candidate, decision) {
    setJudgeError('')
    setConfirmation({ candidate, decision })
  }

  const loadError = message => <p className="form-error" role="alert">{message} {live?.onRetry && <button type="button" className="reference-outline-button" onClick={live.onRetry}>다시 시도</button>}</p>

  return <DemoLayout active="admin"><main className="reference-page admin-reference-page">
    <header className="reference-page-header"><div><h1>운영 현황</h1></div><span className="reference-outline-label">{dataReady ? '관리자 전용' : '데이터 연동 준비 중'}</span></header>
    <section className="admin-summary reference-panel"><div className="admin-summary-grid"><SummaryItem label="결정표" value={tablesReady ? decisionTables.length : '—'} detail={tablesReady ? (live ? '승인 완료·승인 대기 합계' : '전체 결정표') : waitingText} /><SummaryItem label="정책 정비 후보" value={candidatesReady ? undecidedCount : '—'} detail={candidatesReady ? '검토 대기' : waitingText} /><SummaryItem label="처리 대기" value={tablesReady ? pendingCount : '—'} detail={tablesReady ? '승인 판단 필요' : waitingText} tone="pending" /></div><ApprovalStatusDistribution {...approvalStatus} dataReady={tablesReady} waitingText={dataReady ? waitingText : null} /></section>
    <section className="admin-table-panel reference-panel"><div className="reference-section-heading"><h2>결정표 승인 현황</h2><Link to={approvalsPath} className="reference-outline-button">승인함 보기</Link></div><div className="recall-filter-row admin-approval-filter">{[['all', '전체'], ...statuses.map(status => [status, STATUS_LABEL[status]])].map(([key, label]) => <button type="button" key={key} className={filter === key ? 'selected' : ''} aria-pressed={filter === key} disabled={!tablesReady} onClick={() => setFilter(key)}>{label}</button>)}</div>{live && !loading && !tablesError && <p className="profile-storage-notice">승인 완료와 승인 대기 결정표만 보입니다. 반려된 결정표는 목록으로 제공되지 않습니다.</p>}{visibleTables.length ? <table><thead><tr><th>결정표</th><th>관련 정책 문서</th><th>요청 일시</th><th>승인 상태</th></tr></thead><tbody>{visibleTables.map(item => <tr key={item.id} className={`${selectedTable?.id === item.id ? 'selected ' : ''}${item.status === 'pending' ? 'pending' : ''}`} onClick={() => setSelectedId(item.id)}><td>{item.title}</td><td>{item.document}</td><td>{item.requestedAt}</td><td><span className="table-status">{STATUS_LABEL[item.status]}</span></td></tr>)}</tbody></table> : !dataReady ? <p className="recall-empty">결정표 데이터 연동 준비 중입니다.</p> : loading ? <p className="recall-empty" role="status">결정표를 불러오는 중입니다.</p> : tablesError ? loadError(tablesError) : <p className="recall-empty">{filter === 'all' ? '해당하는 결정표가 없습니다.' : `${STATUS_LABEL[filter]} 상태인 결정표가 없습니다.`}</p>}{selectedTable && <div className="selected-reference admin-selected-table"><small>선택한 결정표</small><strong>{selectedTable.title}</strong><span>{selectedTable.document} · {selectedTable.requestedAt} · {STATUS_LABEL[selectedTable.status]}</span>{selectedTable.approvalId && <Link className="reference-outline-button" to={approvalsPath}>관련 승인 요청 상세 보기</Link>}</div>}</section>
    <section className="admin-table-panel reference-panel"><div className="reference-section-heading"><h2>정책 정비 후보</h2><span className="reference-outline-label">{candidatesReady ? `검토 대기 ${undecidedCount}건` : waitingText}</span></div>{candidatesReady && candidates.length ? candidates.map(candidate => <article className={`selected-reference admin-candidate${candidate.decision ? ' complete' : ' needs-review'}`} key={candidate.id}><small>관련 정책 문서</small><strong>{candidate.document}</strong><span>{candidate.relatedPolicy} · {candidate.changedContent}</span><small>정비 필요 사유</small><p>{candidate.reason}</p>{candidate.decision ? <span className="table-status">{DECISION_LABEL[candidate.decision]} · 처리 완료</span> : <div className="approval-actions"><button type="button" disabled={busyId === candidate.id} onClick={() => openConfirmation(candidate, 'not_needed')}>검토 불필요</button><button type="button" disabled={busyId === candidate.id} onClick={() => openConfirmation(candidate, 'needs_review')}>검토 필요</button></div>}</article>) : !dataReady ? <p className="recall-empty">정책 정비 후보 데이터 연동 준비 중입니다.</p> : loading ? <p className="recall-empty" role="status">정책 정비 후보를 불러오는 중입니다.</p> : candidatesError ? loadError(candidatesError) : <p className="recall-empty">정책 정비 후보가 없습니다.</p>}</section>
    {confirmation && <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>{DECISION_LABEL[confirmation.decision]}로 판단하시겠습니까?</h2><p>{confirmation.candidate.document}</p>{judgeError && <p className="form-error" role="alert">{judgeError}</p>}<div><button type="button" disabled={Boolean(busyId)} onClick={() => setConfirmation(null)}>취소</button><button type="button" disabled={Boolean(busyId)} onClick={confirmJudgement}>확인</button></div></section></div>}
  </main></DemoLayout>
}

function SummaryItem({ label, value, detail, tone }) {
  return <div className={`summary-item${tone ? ` ${tone}` : ''}`}><small>{label}</small><strong>{value}</strong><span>{detail}</span></div>
}

function ApprovalStatusDistribution({ items, total, dataReady, waitingText }) {
  return <section className="admin-status-distribution" aria-labelledby="approval-status-distribution-title">
    <div><h2 id="approval-status-distribution-title">승인 처리 현황</h2><span>{dataReady ? `총 ${total}건` : waitingText ?? '데이터 연동 준비 중'}</span></div>
    {dataReady ? <><div className="admin-status-track" role="img" aria-label={items.map(item => `${item.label} ${item.count}건`).join(', ')}>{items.filter(item => item.count > 0).map(item => <span key={item.status} className={item.status} style={{ width: `${item.count / total * 100}%` }} />)}</div><ul>{items.map(item => <li key={item.status} className={item.status}><i aria-hidden="true" /><span>{item.label}</span><b>{item.count}건</b></li>)}</ul></> : <p className="admin-data-pending">{waitingText ? `승인 상태 데이터를 ${waitingText === '불러오는 중' ? '불러오는 중입니다.' : '불러오지 못했습니다.'}` : '승인 상태 데이터를 연동하면 그래프가 표시됩니다.'}</p>}
  </section>
}
