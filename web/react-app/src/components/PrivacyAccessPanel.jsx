import { useState } from 'react'

const PERIODS = [
  { value: '1h', label: '1시간', hours: 1 },
  { value: '24h', label: '24시간', hours: 24 },
  { value: '3d', label: '3일', hours: 72 },
]

const FIELDS = ['이름', '전화번호', '근무지 주소', '소속 팀', '업무 역할', '담당 서비스']

const INITIAL_REQUESTS = [
  { id: 'privacy-01', target: 'pending-user-01', requestedBy: 'auditor-demo', fields: ['이름', '전화번호'], reason: '계정 소유자 확인과 업무 연락을 위해 기본 연락처 확인이 필요합니다. 승인된 항목 외에는 조회하지 않겠습니다.', period: '24h', status: 'pending', requestedAt: '2026-11-06 10:20' },
  { id: 'privacy-02', target: 'former-user-02', requestedBy: 'auditor-demo', fields: ['이름', '근무지 주소'], reason: '퇴사 계정 정리 과정에서 대상 계정의 소속 정보 확인이 필요합니다.', period: '3d', approvedFields: ['이름'], approvedPeriod: '24h', status: 'approved', requestedAt: '2026-11-05 14:10', expiresAt: '2026-11-06 14:10' },
  { id: 'privacy-03', target: 'pending-user-03', requestedBy: 'owner-demo', fields: ['전화번호'], reason: '중복 계정 검토를 위한 확인 요청입니다.', period: '1h', status: 'rejected', rejectionReason: '신청 사유가 구체적이지 않아 거절했습니다.', requestedAt: '2026-11-04 09:00' },
]

const statusLabel = { pending: '대기', approved: '승인', rejected: '거절', expired: '만료', revoked: '철회' }
const periodLabel = value => PERIODS.find(item => item.value === value)?.label ?? value
const periodHours = value => PERIODS.find(item => item.value === value)?.hours ?? 0
const formatFields = fields => fields.length ? fields.join(', ') : '선택하지 않음'

export default function PrivacyAccessPanel({ isPreview = false, reviewOnly = false, viewerId = '' }) {
  const [requests, setRequests] = useState(() => isPreview ? INITIAL_REQUESTS : [])
  const [target, setTarget] = useState('pending-user-04')
  const [fields, setFields] = useState(['이름'])
  const [reason, setReason] = useState('')
  const [period, setPeriod] = useState('24h')
  const [detail, setDetail] = useState(null)
  const [decision, setDecision] = useState(null)
  const [selectedFields, setSelectedFields] = useState([])
  const [approvalPeriod, setApprovalPeriod] = useState('24h')
  const [rejectionReason, setRejectionReason] = useState('')
  const [message, setMessage] = useState('')

  const allSelected = fields.length === FIELDS.length
  const canSubmit = Boolean(target.trim()) && fields.length > 0 && Boolean(reason.trim()) && Boolean(period)
  const allowedApprovalPeriods = detail ? PERIODS.filter(item => item.hours <= periodHours(detail.period)) : []
  const canReview = Boolean(detail && isPreview && reviewOnly && detail.status === 'pending' && detail.requestedBy !== 'owner-demo')
  const visibleRequests = reviewOnly ? requests : requests.filter(item => !isPreview || !viewerId || item.requestedBy === viewerId)

  function toggleAll() {
    setFields(allSelected ? [] : [...FIELDS])
  }

  function toggleField(field) {
    setFields(current => current.includes(field) ? current.filter(item => item !== field) : [...current, field])
  }

  function submitRequest(event) {
    event.preventDefault()
    if (!isPreview || !canSubmit) return
    setRequests(current => [...current, { id: `privacy-${Date.now()}`, target: target.trim(), requestedBy: 'auditor-demo', fields: [...fields], reason: reason.trim(), period, status: 'pending', requestedAt: '2026-11-06 11:00' }])
    setReason('')
    setMessage('열람 신청이 데모 상태로 등록되었습니다.')
  }

  function openDetail(item) {
    setDetail(item)
    setSelectedFields(item.approvedFields ?? item.fields)
    setApprovalPeriod(item.approvedPeriod ?? item.period)
    setRejectionReason('')
    setDecision(null)
  }

  function closeDetail() {
    setDetail(null)
    setDecision(null)
  }

  function startApproval() {
    if (canReview && selectedFields.length > 0) setDecision('approved')
  }

  function startRejection() {
    if (canReview && rejectionReason.trim()) setDecision('rejected')
  }

  function applyDecision() {
    if (!detail || !decision || !isPreview || !canReview) return
    const updated = {
      ...detail,
      status: decision,
      approvedFields: decision === 'approved' ? [...selectedFields] : undefined,
      approvedPeriod: decision === 'approved' ? approvalPeriod : undefined,
      rejectionReason: decision === 'rejected' ? rejectionReason.trim() : undefined,
    }
    setRequests(current => current.map(item => item.id === detail.id ? updated : item))
    setMessage(`${detail.target} 개인정보 열람 신청이 ${decision === 'approved' ? '승인' : '거절'}되었습니다. 데모 상태에만 반영됩니다.`)
    setDetail(updated)
    setDecision(null)
  }

  return <section className="privacy-access-panel" aria-label="개인정보 열람">
    {!reviewOnly && <form className="privacy-access-form" onSubmit={submitRequest}>
      <fieldset disabled={!isPreview}>
        <legend>개인정보 열람 신청</legend>
        <label><span>대상 계정</span><input value={target} onChange={event => setTarget(event.target.value)} placeholder="계정 ID" /></label>
        <fieldset><legend>열람 항목</legend><div className="privacy-field-options"><label><input type="checkbox" aria-label="전체 선택" checked={allSelected} onChange={toggleAll} />전체 선택</label>{FIELDS.map(field => <label key={field}><input type="checkbox" aria-label={field} checked={fields.includes(field)} onChange={() => toggleField(field)} />{field}</label>)}</div></fieldset>
        <label><span>상세 사유</span><textarea className="privacy-request-reason" value={reason} onChange={event => setReason(event.target.value)} placeholder="열람이 필요한 사유를 입력하세요." /></label>
        <label><span>열람 기간</span><select value={period} onChange={event => setPeriod(event.target.value)}>{PERIODS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <button type="submit" className="button button-dark" disabled={!canSubmit}>열람 신청</button>
      </fieldset>
      {!isPreview && <p className="privacy-api-notice">개인정보 열람 API 연동 전이므로 신청 및 조회 기능은 비활성화되어 있습니다.</p>}
    </form>}
    {message && <p className="profile-success" role="status">{message}</p>}
    <HistoryTable requests={visibleRequests} openDetail={openDetail} />
    {detail && <DetailDialog detail={detail} reviewOnly={reviewOnly} isPreview={isPreview} canReview={canReview} selectedFields={selectedFields} setSelectedFields={setSelectedFields} approvalPeriod={approvalPeriod} setApprovalPeriod={setApprovalPeriod} allowedApprovalPeriods={allowedApprovalPeriods} rejectionReason={rejectionReason} setRejectionReason={setRejectionReason} startApproval={startApproval} startRejection={startRejection} closeDetail={closeDetail} />}
    {decision && detail && <DecisionDialog decision={decision} selectedFields={selectedFields} approvalPeriod={approvalPeriod} rejectionReason={rejectionReason} onCancel={() => setDecision(null)} onConfirm={applyDecision} />}
  </section>
}

function HistoryTable({ requests, openDetail }) {
  return <div className="privacy-access-history"><h3>신청·승인·열람 이력</h3><div className="admin-users-table-wrap"><table className="admin-users-table"><thead><tr><th>대상 계정</th><th>신청자</th><th>항목</th><th>기간</th><th>상태</th><th>처리</th></tr></thead><tbody>{requests.map(item => <tr key={item.id}><td>{item.target}</td><td>{item.requestedBy}</td><td>{formatFields(item.approvedFields ?? item.fields)}</td><td>{item.approvedPeriod ? `${periodLabel(item.period)} 요청 / ${periodLabel(item.approvedPeriod)} 승인` : periodLabel(item.period)}</td><td><span className={`privacy-status ${item.status}`}>{statusLabel[item.status]}</span></td><td><button type="button" className="reference-outline-button" onClick={() => openDetail(item)}>상세 보기</button></td></tr>)}</tbody></table></div>{requests.length === 0 && <p className="admin-empty-state">신청 내역이 없습니다.</p>}</div>
}

function DetailDialog({ detail, reviewOnly, isPreview, canReview, selectedFields, setSelectedFields, approvalPeriod, setApprovalPeriod, allowedApprovalPeriods, rejectionReason, setRejectionReason, startApproval, startRejection, closeDetail }) {
  const pendingReview = reviewOnly && detail.status === 'pending'
  const completedReview = reviewOnly && detail.status !== 'pending'
  return <div className={`approval-dialog privacy-detail-dialog${completedReview ? ' privacy-completed-dialog' : ''}`} role="dialog" aria-modal="true">
    <section>
      <div className="privacy-detail-header"><h2>개인정보 열람 신청 상세</h2><button type="button" className="account-menu-close" aria-label="상세 보기 닫기" onClick={closeDetail}>×</button></div>
      <div className="privacy-detail-scroll">
      {completedReview ? <CompletedReviewDetail detail={detail} /> : <dl className="privacy-detail-list">
        <dt>신청자 계정 ID</dt><dd>{detail.requestedBy}</dd>
        <dt>열람 대상 계정 ID</dt><dd>{detail.target}</dd>
        <dt>신청한 개인정보 항목</dt><dd>{formatFields(detail.fields)}</dd>
        <dt>상세 신청 사유</dt><dd className="privacy-detail-reason">{detail.reason}</dd>
        <dt>신청한 열람 기간</dt><dd>{periodLabel(detail.period)}</dd>
        <dt>신청일</dt><dd>{detail.requestedAt}</dd>
        <dt>현재 처리 상태</dt><dd><span className={`privacy-status ${detail.status}`}>{statusLabel[detail.status]}</span></dd>
        {detail.rejectionReason && <><dt>거절 사유</dt><dd className="privacy-detail-reason">{detail.rejectionReason}</dd></>}
      </dl>}
      {pendingReview && canReview && <ReviewControls detail={detail} selectedFields={selectedFields} setSelectedFields={setSelectedFields} approvalPeriod={approvalPeriod} setApprovalPeriod={setApprovalPeriod} allowedApprovalPeriods={allowedApprovalPeriods} rejectionReason={rejectionReason} setRejectionReason={setRejectionReason} startApproval={startApproval} startRejection={startRejection} closeDetail={closeDetail} />}
      {pendingReview && !canReview && <p className="privacy-api-notice">이 신청은 신청자 본인의 요청이므로 직접 승인할 수 없습니다.</p>}
      {pendingReview && !isPreview && <p className="privacy-api-notice">개인정보 열람 승인 API 연동 전이므로 승인·거절 기능은 비활성화되어 있습니다.</p>}
      </div>
      {(!pendingReview || !canReview) && <div className="privacy-detail-footer"><button type="button" className="reference-outline-button" onClick={closeDetail}>닫기</button></div>}
    </section>
  </div>
}

function CompletedReviewDetail({ detail }) {
  const status = detail.status === 'approved' ? '승인 완료' : statusLabel[detail.status]
  return <div className="privacy-completed-detail">
    <section className="privacy-completed-summary" aria-label="신청 내역">
      <div className="privacy-completed-heading"><h3>신청 내역</h3><span className={`privacy-status ${detail.status}`}>{status}</span></div>
      <dl>
        <div><dt>신청자 ID</dt><dd>{detail.requestedBy}</dd></div>
        <div><dt>열람 대상 계정 ID</dt><dd>{detail.target}</dd></div>
        <div><dt>신청한 항목</dt><dd>{formatFields(detail.fields)}</dd></div>
        <div><dt>신청한 열람 기간</dt><dd>{periodLabel(detail.period)}</dd></div>
        <div><dt>신청일</dt><dd>{detail.requestedAt}</dd></div>
      </dl>
    </section>
    <section className="privacy-completed-reason"><h3>상세 신청 사유</h3><p>{detail.reason}</p></section>
    <section className={`privacy-completed-result ${detail.status}`}><h3>처리 결과</h3>
      <dl><div><dt>현재 상태</dt><dd><span className={`privacy-status ${detail.status}`}>{status}</span></dd></div>
      {detail.status === 'approved' && detail.approvedFields && <div><dt>승인된 개인정보 항목</dt><dd>{formatFields(detail.approvedFields)}</dd></div>}
      {detail.status === 'approved' && detail.approvedPeriod && <div><dt>승인 기간</dt><dd>{periodLabel(detail.approvedPeriod)}</dd></div>}
      {detail.status === 'rejected' && detail.rejectionReason && <div className="privacy-completed-rejection"><dt>거절 사유</dt><dd>{detail.rejectionReason}</dd></div>}</dl>
    </section>
  </div>
}

function ReviewControls({ detail, selectedFields, setSelectedFields, approvalPeriod, setApprovalPeriod, allowedApprovalPeriods, rejectionReason, setRejectionReason, startApproval, startRejection, closeDetail }) {
  return <div className="privacy-review-controls"><fieldset><legend>승인할 항목</legend><div className="privacy-field-options">{detail.fields.map(field => <label key={field}><input type="checkbox" checked={selectedFields.includes(field)} onChange={() => setSelectedFields(current => current.includes(field) ? current.filter(item => item !== field) : [...current, field])} />{field}</label>)}</div></fieldset><label className="privacy-approval-period"><span>승인 열람 기간</span><small>신청 기간: {periodLabel(detail.period)} 이내</small><select value={approvalPeriod} onChange={event => setApprovalPeriod(event.target.value)}>{allowedApprovalPeriods.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label className="privacy-rejection-reason"><span>거절 사유</span><textarea className="privacy-rejection-input" value={rejectionReason} onChange={event => setRejectionReason(event.target.value)} placeholder="거절 사유를 입력하세요." /></label><div className="privacy-review-actions"><button type="button" className="reference-outline-button" onClick={closeDetail}>닫기</button><button type="button" className="reference-outline-button danger" disabled={!rejectionReason.trim()} onClick={startRejection}>거절</button><button type="button" className="button button-dark" disabled={selectedFields.length === 0} onClick={startApproval}>승인</button></div></div>
}

function DecisionDialog({ decision, selectedFields, approvalPeriod, rejectionReason, onCancel, onConfirm }) {
  return <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>{decision === 'approved' ? '열람 신청을 승인' : '열람 신청을 거절'}하시겠습니까?</h2>{decision === 'approved' ? <p>{formatFields(selectedFields)} 항목을 {periodLabel(approvalPeriod)} 동안 승인합니다. 신청 기간을 초과하지 않습니다.</p> : <p>거절 사유: {rejectionReason}</p>}<div><button type="button" className="reference-outline-button" onClick={onCancel}>취소</button><button type="button" className="button button-dark" onClick={onConfirm}>최종 확인</button></div></section></div>
}
