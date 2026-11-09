import { useEffect, useMemo, useState } from 'react'
import DemoLayout from '../components/DemoLayout'
import { formatServerTime } from '../lib/admin-service'
import { liveApprovalsService, previewApprovalsService, reviewDepartments } from '../lib/approvals-service'

const label = { all: '전체', pending: '승인 대기', approved: '승인 완료', rejected: '반려' }
const kindLabel = { decision: '결정표', issue: '쟁점표' }

export default function ApprovalsPage() {
  const [items, setItems] = useState([])
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(null)
  const [reason, setReason] = useState('')
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reviews, setReviews] = useState({})
  const [department, setDepartment] = useState('security')
  const [result, setResult] = useState('possible')
  const [opinion, setOpinion] = useState('')
  const [evidence, setEvidence] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    let active = true
    previewApprovalsService.listApprovals()
      .then(data => { if (active) { setItems(data); setSelectedId(data[0]?.id ?? null) } })
      .catch(() => { if (active) setLoadError('승인 요청을 불러오지 못했습니다.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!selectedId) { setReviews({}); return undefined }
    let active = true
    previewApprovalsService.getDepartmentReviews(selectedId)
      .then(data => { if (active) setReviews(data) })
      .catch(() => { if (active) setActionError('부서별 검토 정보를 불러오지 못했습니다.') })
    return () => { active = false }
  }, [selectedId])

  const visible = useMemo(() => items.filter(item => filter === 'all' || item.status === filter), [filter, items])
  const selected = items.find(item => item.id === selectedId) ?? visible[0] ?? null
  const reviewed = Object.keys(reviews).length
  const allReviewed = reviewed === reviewDepartments.length
  const canDecide = selected?.status === 'pending'

  function decide(status) {
    if (!selected || !canDecide || (status !== 'approved' && !reason.trim()) || (selected.kind === 'issue' && status === 'approved' && !allReviewed)) return
    setActionError('')
    setConfirm(status)
  }

  async function confirmDecision() {
    if (!selected || !confirm || busy) return
    setBusy(true)
    setActionError('')
    try {
      const updated = await previewApprovalsService.decideApproval(selected.id, { action: confirm === 'approved' ? 'approve' : confirm === 'revision' ? 'revision' : 'reject', reason })
      setItems(current => current.map(item => item.id === updated.id ? updated : item))
      setConfirm(null)
    } catch (error) {
      setActionError(error?.message || '승인 요청을 처리하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  async function submitReview() {
    if (!selected || !opinion.trim() || reviews[department] || busy) return
    setBusy(true)
    setActionError('')
    try {
      setReviews(await previewApprovalsService.submitDepartmentReview(selected.id, { departmentId: department, result, opinion, evidence }))
      setOpinion('')
      setEvidence('')
    } catch (error) {
      setActionError(error?.message || '검토 의견을 제출하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return <DemoLayout active="approvals"><main className="approval-service-page"><header><h1>승인함</h1></header><div className="approval-filters">{Object.entries(label).map(([key, value]) => <button key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{value}</button>)}</div><section className="approval-service-layout"><aside><h2>승인 요청</h2>{loading ? <p>승인 요청을 불러오는 중입니다.</p> : loadError ? <p role="alert">{loadError}</p> : visible.length ? visible.map(item => <button key={item.id} className={item.id === selected?.id ? 'selected' : ''} onClick={() => setSelectedId(item.id)}><strong>{item.title}</strong><span>{kindLabel[item.kind]} · {item.at}</span><small>{label[item.status] ?? '보완 요청'}</small></button>) : <p>처리할 승인 요청이 없습니다.</p>}</aside><article>{selected ? <><div className="approval-detail-head"><div><span>{kindLabel[selected.kind]}</span><h2>{selected.title}</h2><p>{selected.source}</p></div><a href={selected.url} target="_blank" rel="noreferrer">원문 보기</a></div><h3>원문 대조</h3><div className="approval-compare"><section><small>원본 정책 문서</small><p>{selected.original}</p></section><section><small>{selected.kind === 'decision' ? '변환된 결정표' : '제안된 쟁점표'}</small><p>{selected.proposed}</p></section></div><div className="approval-mismatch"><strong>불일치 항목 · 검토 필요</strong><p>{selected.mismatch}</p></div>{selected.kind === 'issue' && <section className="department-review"><div className="department-review-head"><h3>부서별 검토</h3><span>{allReviewed ? '최종 승인 대기' : `검토 완료 ${reviewed}/${reviewDepartments.length}`}</span></div>{reviewDepartments.map(item => <div className="department-item" key={item.id}><div><strong>{item.name}</strong><small>{item.question}</small></div>{reviews[item.id] ? <p><b>검토 완료 · {reviews[item.id].result}</b><br />{reviews[item.id].opinion}</p> : <span className="department-pending">검토 대기</span>}</div>)}<div className="review-form"><label>담당 부서<select value={department} onChange={event => setDepartment(event.target.value)} disabled={busy}>{reviewDepartments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>검토 결과<select value={result} onChange={event => setResult(event.target.value)} disabled={busy}><option value="possible">가능</option><option value="conditional">조건부 가능</option><option value="blocked">불가</option></select></label><label>검토 의견<textarea value={opinion} onChange={event => setOpinion(event.target.value)} disabled={busy} /></label><button disabled={busy || !opinion.trim() || Boolean(reviews[department])} onClick={submitReview}>검토 의견 제출</button></div></section>}<label className="approval-reason">반려 또는 보완 요청 사유<textarea value={reason} onChange={event => setReason(event.target.value)} disabled={busy || !canDecide} /></label><div className="approval-actions"><button disabled={busy || !canDecide || !reason.trim()} onClick={() => decide('rejected')}>반려하기</button>{selected.kind === 'issue' && <button disabled={busy || !canDecide || !reason.trim()} onClick={() => decide('revision')}>보완 요청</button>}<button disabled={busy || !canDecide || (selected.kind === 'issue' && !allReviewed)} onClick={() => decide('approved')}>승인하기</button></div>{actionError && <p className="approval-complete" role="alert">{actionError}</p>}</> : <p>{loading ? '상세 정보를 불러오는 중입니다.' : '상세 정보를 불러오지 못했습니다.'}</p>}</article></section>{confirm && <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>처리하시겠습니까?</h2><p>{selected?.title}</p><div><button type="button" disabled={busy} onClick={() => setConfirm(null)}>취소</button><button type="button" disabled={busy} onClick={confirmDecision}>확인</button></div></section></div>}</main></DemoLayout>
}

// Live approvals inbox. Items are the server ApprovalView (backend/graph/decision/routes.py `ApprovalView`).
// GET /approvals lists pending items only, so approved/rejected appear here only for items decided in this screen.
const LIVE_KIND_LABEL = { decision_table: '결정표', issue_table: '쟁점표', team_review_failed: '팀 검토 실패' }
const CELL_LABEL = { approver: '업무 승인', financial: '재무 승인', cooperating: '협조', none: '없음' }
const STANCE_LABEL = { allow: '가능', condition: '조건부 가능', block: '불가' }
const RESOLUTION_LABEL = { retry: '다시 검토', mark_unreviewed: '미검토로 표시' }
const RESUME_LABEL = {
  comment_required: '원문과 다른 칸이 있는 초안을 승인하려면 의견이 필요합니다.',
  approver_missing: '승인에는 승인한 관리자가 필요합니다.',
  approval_id_mismatch: '승인 건 번호가 멈춘 승인 요청과 다릅니다.',
  bad_format: '승인 값의 형식이 틀렸습니다.',
  bad_action: '팀 검토 실패 건은 다시 검토 또는 미검토로 표시만 고를 수 있습니다.',
}
const SAVE_FAILED_TEXT = '결정은 접수됐지만 저장하지 못했습니다. 같은 결정을 다시 보내 주세요.'
const hasMismatch = comparison => Boolean(comparison?.mismatch_count || comparison?.extra_bands?.length)
const statusOf = item => item.status ?? 'pending'
const isWebUrl = value => typeof value === 'string' && /^https?:\/\//.test(value)
const joinRoles = roles => Array.isArray(roles) && roles.length ? roles.join(', ') : '—'

function statusText(item) {
  const status = statusOf(item)
  if (status === 'pending') return item.save_failed ? '저장 재시도 필요' : label.pending
  if (item.kind === 'team_review_failed' && item.resolution) return RESOLUTION_LABEL[item.resolution] ?? item.resolution
  return label[status] ?? status
}

export function ApprovalsLivePage({ service = liveApprovalsService }) {
  const [items, setItems] = useState([])
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(null)
  const [comment, setComment] = useState('')
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    service.listApprovals()
      .then(data => {
        if (!active) return
        const list = Array.isArray(data) ? data : []
        setItems(current => [...list, ...current.filter(item => statusOf(item) !== 'pending' && !list.some(view => view.approval_id === item.approval_id))])
        setSelectedId(current => list.some(view => view.approval_id === current) ? current : list[0]?.approval_id ?? current)
      })
      .catch(error => { if (active) setLoadError(error?.message || '승인 요청을 불러오지 못했습니다.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [service, reload])

  const visible = useMemo(() => items.filter(item => filter === 'all' || statusOf(item) === filter), [filter, items])
  const selected = items.find(item => item.approval_id === selectedId) ?? visible[0] ?? null
  const canDecide = selected ? statusOf(selected) === 'pending' : false
  const isTeam = selected?.kind === 'team_review_failed'
  const approveNeedsComment = selected?.kind === 'decision_table' && hasMismatch(selected.comparison)

  function refresh() {
    setLoading(true)
    setLoadError('')
    setReload(value => value + 1)
  }

  function select(id) {
    setSelectedId(id)
    setComment('')
    setActionError('')
    setNotice('')
  }

  function decide(choice) {
    if (!selected || !canDecide || busy) return
    const text = comment.trim()
    if (choice === 'reject' && !text) return
    if (choice === 'approve' && approveNeedsComment && !text) return
    const body = choice === 'retry' || choice === 'mark_unreviewed' ? { action: choice, comment } : { approve: choice === 'approve', comment }
    const name = choice === 'approve' ? '승인' : choice === 'reject' ? '반려' : RESOLUTION_LABEL[choice]
    setActionError('')
    setNotice('')
    setConfirm({ name, body })
  }

  async function confirmDecision() {
    if (!selected || !confirm || busy) return
    const id = selected.approval_id
    setBusy(true)
    setActionError('')
    try {
      const result = await service.decideApproval(id, confirm.body)
      setItems(current => current.map(item => item.approval_id === id ? { ...item, status: result?.status ?? item.status, resolution: result?.resolution ?? item.resolution, save_failed: false } : item))
      setNotice(`${confirm.name} 처리했습니다.`)
      setComment('')
      if (result?.next_approval) refresh()
    } catch (error) {
      if (error?.code === 'save_failed') {
        setItems(current => current.map(item => item.approval_id === id ? { ...item, save_failed: true } : item))
        setActionError(SAVE_FAILED_TEXT)
      } else {
        setActionError(error?.message || '승인 요청을 처리하지 못했습니다.')
      }
    } finally {
      setConfirm(null)
      setBusy(false)
    }
  }

  return <DemoLayout active="approvals"><main className="approval-service-page"><header><div><h1>승인함</h1><p>서버의 승인 대기 목록입니다. 승인 완료·반려는 이 화면에서 처리한 건만 보입니다.</p></div></header><div className="approval-filters">{Object.entries(label).map(([key, value]) => <button type="button" key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{value}</button>)}</div><section className="approval-service-layout"><aside><h2>승인 요청</h2>{loading && !items.length ? <p role="status">승인 요청을 불러오는 중입니다.</p> : loadError ? <><p role="alert">{loadError}</p><button type="button" onClick={refresh}>다시 시도</button></> : visible.length ? visible.map(item => <button type="button" key={item.approval_id} className={item.approval_id === selected?.approval_id ? 'selected' : ''} onClick={() => select(item.approval_id)}><strong>{item.summary}</strong><span>{LIVE_KIND_LABEL[item.kind] ?? item.kind} · {formatServerTime(item.created_at)}</span><small>{statusText(item)}</small></button>) : <p>처리할 승인 요청이 없습니다.</p>}</aside><article>{selected ? <>
    <div className="approval-detail-head"><div><span>{LIVE_KIND_LABEL[selected.kind] ?? selected.kind}</span><h2>{selected.summary}</h2><p>승인 건 {selected.approval_id} · 요청 {formatServerTime(selected.created_at)}{selected.table_id ? ` · 결정표 ${selected.table_id}` : ''}</p></div></div>
    {selected.save_failed && <div className="approval-mismatch"><strong>저장 재시도 필요</strong><p>{SAVE_FAILED_TEXT}</p></div>}
    {selected.rejected_resume && <div className="approval-mismatch"><strong>이전에 보낸 결정 값이 거절되었습니다</strong><p>{RESUME_LABEL[selected.rejected_resume] ?? selected.rejected_resume}</p></div>}
    {selected.kind === 'decision_table' ? <DecisionTableDetail view={selected} /> : selected.kind === 'issue_table' ? <IssueTableDetail table={selected.issue_table} /> : isTeam ? <TeamFailedDetail teams={selected.failed_teams} /> : null}
    <label className="approval-reason">{isTeam ? '의견 (선택)' : approveNeedsComment ? '의견 (반려 사유 또는 승인 의견, 불일치가 있어 승인에도 필요)' : '의견 (반려 사유 또는 승인 의견)'}<textarea value={comment} onChange={event => setComment(event.target.value)} disabled={busy || !canDecide} /></label>
    <div className="approval-actions">{isTeam ? <><button type="button" disabled={busy || !canDecide} onClick={() => decide('mark_unreviewed')}>미검토로 표시</button><button type="button" disabled={busy || !canDecide} onClick={() => decide('retry')}>다시 검토</button></> : <><button type="button" disabled={busy || !canDecide || !comment.trim()} onClick={() => decide('reject')}>반려하기</button><button type="button" disabled={busy || !canDecide || (approveNeedsComment && !comment.trim())} onClick={() => decide('approve')}>승인하기</button></>}</div>
    {actionError && <p className="approval-complete" role="alert">{actionError}</p>}
    {notice && <p className="approval-complete" role="status">{notice}</p>}
  </> : <p>{loading ? '상세 정보를 불러오는 중입니다.' : '선택한 승인 요청이 없습니다.'}</p>}</article></section>{confirm && <div className="approval-dialog" role="dialog" aria-modal="true"><section><h2>{confirm.name} 처리하시겠습니까?</h2><p>{selected?.summary}</p><div><button type="button" disabled={busy} onClick={() => setConfirm(null)}>취소</button><button type="button" disabled={busy} onClick={confirmDecision}>확인</button></div></section></div>}</main></DemoLayout>
}

function DecisionTableDetail({ view }) {
  const comparison = view.comparison
  const rows = Array.isArray(comparison?.rows) ? comparison.rows : []
  return <>
    <h3>셀 대조표</h3>
    {comparison ? <>
      <div className="approval-mismatch"><strong>{hasMismatch(comparison) ? '불일치 항목 · 검토 필요' : '원문과 일치'}</strong><p>원문 칸 {comparison.source_cells ?? '—'}개 · 불일치 {comparison.mismatch_count ?? 0}건{comparison.extra_bands?.length ? ` · 원문에 없는 구간 ${comparison.extra_bands.join(', ')}` : ''}</p></div>
      {rows.length ? <div className="admin-table-panel"><table><thead><tr><th>구간</th><th>역할</th><th>원문 값</th><th>원문 줄</th><th>원문 기준</th><th>초안</th><th>대조</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.band}-${row.role}-${index}`}><td>{row.band_label || row.band}</td><td>{row.role}</td><td>{row.source_value || '—'}</td><td>{row.source_line ?? '—'}</td><td>{CELL_LABEL[row.expected] ?? row.expected}</td><td>{CELL_LABEL[row.draft] ?? row.draft}</td><td>{row.match ? '일치' : '불일치'}</td></tr>)}</tbody></table></div> : <p>대조할 칸이 없습니다.</p>}
    </> : <p>셀 대조표를 불러오지 못했습니다.</p>}
    <h3>변환된 결정표 초안</h3>
    {view.draft?.length ? <div className="admin-table-panel"><table><thead><tr><th>구간</th><th>업무 승인</th><th>재무 승인</th><th>협조 부서</th><th>해석 메모</th></tr></thead><tbody>{view.draft.map((rule, index) => <tr key={`${rule.band}-${index}`}><td>{rule.band_label || rule.band}</td><td>{joinRoles(rule.approvers)}</td><td>{joinRoles(rule.financial_approvers)}</td><td>{joinRoles(rule.cooperating_depts)}</td><td>{rule.range_note || '—'}</td></tr>)}</tbody></table></div> : <p>결정표 초안을 불러오지 못했습니다.</p>}
  </>
}

function IssueTableDetail({ table }) {
  if (!table) return <><h3>쟁점표</h3><p>쟁점표를 불러오지 못했습니다.</p></>
  const rows = Array.isArray(table.rows) ? table.rows : []
  const unreviewed = Array.isArray(table.unreviewed) ? table.unreviewed : []
  return <>
    <h3>쟁점표{table.request ? ` · ${table.request}` : ''}</h3>
    {rows.length ? <div className="admin-table-panel"><table><thead><tr><th>팀</th><th>쟁점</th><th>입장</th><th>근거</th><th>의견 갈림</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.team}-${row.chunk_id}-${index}`}><td>{row.team_label || row.team}</td><td><strong>{row.topic}</strong><br />{row.issue}</td><td>{STANCE_LABEL[row.stance] ?? row.stance}</td><td>{isWebUrl(row.source_url) ? <a href={row.source_url} target="_blank" rel="noreferrer">{row.section_path || row.rule_title}</a> : row.section_path || row.rule_title}</td><td>{row.conflict ? '갈림' : '—'}</td></tr>)}</tbody></table></div> : <p>쟁점 행이 없습니다.</p>}
    {unreviewed.length > 0 && <div className="approval-mismatch"><strong>검토하지 못한 팀</strong><p>{unreviewed.map(item => `${item.team_label || item.team}: ${item.reason}`).join(' / ')}</p></div>}
  </>
}

function TeamFailedDetail({ teams }) {
  return <>
    <h3>검토하지 못한 팀</h3>
    {teams?.length ? <div className="admin-table-panel"><table><thead><tr><th>팀</th><th>실패 이유</th><th>시도 횟수</th></tr></thead><tbody>{teams.map(item => <tr key={item.team}><td>{item.team}</td><td>{item.reason}</td><td>{item.attempts}</td></tr>)}</tbody></table></div> : <p>실패한 팀 정보를 불러오지 못했습니다.</p>}
  </>
}
