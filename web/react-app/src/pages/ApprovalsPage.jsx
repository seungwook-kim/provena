import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DecisionConvertPanel from '../components/DecisionConvertPanel'
import DemoLayout from '../components/DemoLayout'
import { STALE_APPROVAL_ERROR_CODES, previewApprovalsService, reviewDepartments } from '../lib/approvals-service'
import { NARROW_LAYOUT_QUERY } from './ChangeMonitoringPage'

const label = { all: '전체', pending: '승인 대기', approved: '승인 완료', rejected: '반려' }
const kindLabel = { decision: '결정표', issue: '쟁점표', team_failed: '팀 검토 실패', unknown: '승인 요청' }
const roleLabel = { approver: '업무 승인', financial: '재무 승인', cooperating: '협조(승인 아님)', none: '없음' }
const stanceLabel = { allow: '가능', condition: '조건부 가능', block: '불가' }
const reviewResultLabel = { possible: '가능', conditional: '조건부 가능', blocked: '불가' }
const confidenceLabel = { high: '높음', medium: '보통', low: '낮음' }
// 팀 검토 실패 알림의 failed_teams 에는 화면 이름이 없어(backend/graph/departments/review.py) 서버 팀 표(backend/graph/departments/teams.py)와 같은 이름을 둔다. 모르는 코드는 그대로
const teamLabel = { security: '보안', infra: '인프라·SRE', itops: 'IT 운영', finance: '재무' }
const actionByConfirm = { approved: 'approve', rejected: 'reject', revision: 'revision', retry: 'retry', mark_unreviewed: 'mark_unreviewed' }
const doneMessage = {
  approved: '승인했습니다.',
  rejected: '반려했습니다.',
  retry: '실패한 팀의 검토를 다시 요청했습니다.',
  mark_unreviewed: '실패한 팀을 검토하지 못한 팀으로 표시하고 다음 단계로 넘겼습니다.',
}
const confirmTitle = { approved: '승인하시겠습니까?', rejected: '반려하시겠습니까?', revision: '보완을 요청하시겠습니까?', retry: '다시 검토를 요청하시겠습니까?', mark_unreviewed: '검토하지 못한 팀으로 표시하시겠습니까?' }
const LOAD_ERROR = '승인 요청을 불러오지 못했습니다.'
const EMPTY_DRAFT = { id: null, text: '' }
const draftFor = (draft, item) => (item && draft.id === item.id ? draft.text : '')

export default function ApprovalsPage({ service = previewApprovalsService }) {
  const live = service.live === true
  const [items, setItems] = useState([])
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(null)
  // 760px 이하는 목록 아래에 상세가 와서, 항목을 눌러도 화면이 그대로라 반응이 없는 것처럼 보였다(박진형 화면 점검 2026-11-14)
  // → 항목을 누르면 상세로 내려간다. 넓은 화면은 옆에 보이므로 움직이지 않는다(변경 감시와 같은 방식).
  const detailRef = useRef(null)
  function chooseItem(id) {
    setSelectedId(id)
    const narrow = typeof window.matchMedia === 'function' && window.matchMedia(NARROW_LAYOUT_QUERY).matches
    if (narrow) requestAnimationFrame(() => detailRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }))
  }
  const [reasonDraft, setReasonDraft] = useState(EMPTY_DRAFT)
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [reviews, setReviews] = useState({})
  const [department, setDepartment] = useState('security')
  const [result, setResult] = useState('possible')
  const [opinionDraft, setOpinionDraft] = useState(EMPTY_DRAFT)
  const [evidenceDraft, setEvidenceDraft] = useState(EMPTY_DRAFT)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const requestRef = useRef(0)
  const cancelRef = useRef(null)
  const dialogRef = useRef(null)
  const openerRef = useRef(null)

  const loadList = useCallback(async () => {
    const request = ++requestRef.current
    setLoadError('')
    try {
      const data = await service.listApprovals()
      if (request !== requestRef.current) return
      setItems(data)
      setSelectedId(current => data.some(item => item.id === current) ? current : data[0]?.id ?? null)
    } catch (error) {
      if (request === requestRef.current) setLoadError(service.live === true && error?.message ? error.message : LOAD_ERROR)
    } finally {
      if (request === requestRef.current) setLoading(false)
    }
  }, [service])

  useEffect(() => {
    loadList()
    return () => { requestRef.current += 1 }
  }, [loadList])

  useEffect(() => {
    if (confirm) { cancelRef.current?.focus(); return undefined }
    const opener = openerRef.current
    openerRef.current = null
    if (opener?.isConnected) opener.focus()
    return undefined
  }, [confirm])

  useEffect(() => {
    if (live || !selectedId) { setReviews({}); return undefined }
    let active = true
    service.getDepartmentReviews(selectedId)
      .then(data => { if (active) setReviews(data) })
      .catch(() => { if (active) setActionError('부서별 검토 정보를 불러오지 못했습니다.') })
    return () => { active = false }
  }, [live, selectedId, service])

  const visible = useMemo(() => items.filter(item => filter === 'all' || item.status === filter), [filter, items])
  const selected = items.find(item => item.id === selectedId) ?? visible[0] ?? null
  // Typed text belongs to the item it was typed for: switching items shows that item's own (empty) text,
  // so a reason written for A can never be sent as B's reason.
  const reason = draftFor(reasonDraft, selected)
  const opinion = draftFor(opinionDraft, selected)
  const evidence = draftFor(evidenceDraft, selected)
  const setReason = text => setReasonDraft({ id: selected?.id ?? null, text })
  const setOpinion = text => setOpinionDraft({ id: selected?.id ?? null, text })
  const setEvidence = text => setEvidenceDraft({ id: selected?.id ?? null, text })
  const reviewed = Object.keys(reviews).length
  const allReviewed = reviewed === reviewDepartments.length
  const canDecide = selected?.status === 'pending' && (!live || selected.hasDetail)
  const approveNeedsReason = live && Boolean(selected?.decision?.comparison.needsReason)

  function decide(status) {
    if (!selected || !canDecide) return
    if ((status === 'rejected' || status === 'revision') && !reason.trim()) return
    if (status === 'approved' && ((approveNeedsReason && !reason.trim()) || (!live && selected.kind === 'issue' && !allReviewed))) return
    setActionError('')
    openerRef.current = document.activeElement
    setConfirm({ status, id: selected.id, title: selected.title, reason })
  }

  function onDialogKeyDown(event) {
    if (event.key === 'Escape') {
      if (!busy) { event.stopPropagation(); setConfirm(null) }
      return
    }
    if (event.key !== 'Tab') return
    const buttons = [...(dialogRef.current?.querySelectorAll('button:not([disabled])') ?? [])]
    if (!buttons.length) { event.preventDefault(); return }
    const first = buttons[0]
    const last = buttons[buttons.length - 1]
    if (!dialogRef.current.contains(document.activeElement)) { event.preventDefault(); first.focus() }
    else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  async function confirmDecision() {
    if (!confirm || busy) return
    const { status, id, reason: confirmedReason } = confirm
    setBusy(true)
    setActionError('')
    try {
      const updated = await service.decideApproval(id, { action: actionByConfirm[status] ?? 'reject', reason: confirmedReason })
      if (live) {
        setNotice(`${doneMessage[status] ?? '처리했습니다.'}${updated?.nextApproval ? ' 다음 승인 요청이 올라왔습니다.' : ''}`)
        setReason('')
        setConfirm(null)
        await loadList()
      } else {
        setItems(current => current.map(item => item.id === updated.id ? updated : item))
        setConfirm(null)
      }
    } catch (error) {
      setActionError(error?.message || '승인 요청을 처리하지 못했습니다.')
      if (live) {
        setNotice('')
        setConfirm(null)
        if (STALE_APPROVAL_ERROR_CODES.includes(error?.code)) await loadList()
      }
    } finally {
      setBusy(false)
    }
  }

  async function submitReview() {
    if (!selected || !opinion.trim() || reviews[department] || busy) return
    setBusy(true)
    setActionError('')
    try {
      setReviews(await service.submitDepartmentReview(selected.id, { departmentId: department, result, opinion, evidence }))
      setOpinion('')
      setEvidence('')
    } catch (error) {
      setActionError(error?.message || '검토 의견을 제출하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const reasonLabel = !live ? '반려 또는 보완 요청 사유' : selected?.kind === 'team_failed' ? '메모 (선택)' : approveNeedsReason ? '사유 (반려와, 원문과 다른 칸이 있는 초안의 승인에는 필수)' : '사유 (반려에는 필수)'

  return <DemoLayout active="approvals"><main className="approval-service-page">
    <header><h1>승인함</h1></header>
    {!live && <div className="approval-filters">{Object.entries(label).map(([key, value]) => <button key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{value}</button>)}</div>}
    {live && notice && <p className="approval-complete" role="status">{notice}</p>}
    {live && service.convertDecisionTable && <DecisionConvertPanel service={service} onConverted={loadList} />}
    <section className="approval-service-layout">
      <aside>
        <h2>승인 요청</h2>
        {loading ? <p>승인 요청을 불러오는 중입니다.</p>
          : loadError ? <><p role="alert">{loadError}</p>{live && <button type="button" onClick={() => { setLoading(true); loadList() }}>다시 시도</button>}</>
          : visible.length ? visible.map(item => <button key={item.id} className={item.id === selected?.id ? 'selected' : ''} onClick={() => chooseItem(item.id)}>
            <strong>{item.title}</strong>
            <span>{kindLabel[item.kind]} · {item.at}</span>
            <small>{item.saveFailed ? '저장 재시도 필요' : label[item.status] ?? '보완 요청'}</small>
          </button>)
          : <p>{live ? '처리할 승인 요청이 없습니다. 새 요청이 올라오면 이곳에 표시됩니다.' : '처리할 승인 요청이 없습니다.'}</p>}
      </aside>
      <article ref={detailRef}>
        {selected ? <>
          <div className="approval-detail-head">
            <div>
              <span>{kindLabel[selected.kind]}</span>
              <h2>{selected.title}</h2>
              <p>{live ? (selected.at ? `${selected.at} 올라옴` : '') : selected.source}</p>
            </div>
            {!live && selected.url && <a href={selected.url} target="_blank" rel="noreferrer">원문 보기</a>}
          </div>
          {live ? <LiveDetail item={selected} /> : <>
            <h3>원문 대조</h3>
            <div className="approval-compare">
              <section><small>원본 정책 문서</small><p>{selected.original}</p></section>
              <section><small>{selected.kind === 'decision' ? '변환된 결정표' : '제안된 쟁점표'}</small><p>{selected.proposed}</p></section>
            </div>
            <div className="approval-mismatch"><strong>불일치 항목 · 검토 필요</strong><p>{selected.mismatch}</p></div>
            {selected.kind === 'issue' && <section className="department-review">
              <div className="department-review-head"><h3>부서별 검토</h3><span>{allReviewed ? '최종 승인 대기' : `검토 완료 ${reviewed}/${reviewDepartments.length}`}</span></div>
              {reviewDepartments.map(item => <div className="department-item" key={item.id}>
                <div><strong>{item.name}</strong><small>{item.question}</small></div>
                {reviews[item.id] ? <p><b>검토 완료 · {reviewResultLabel[reviews[item.id].result] ?? reviews[item.id].result}</b><br />{reviews[item.id].opinion}</p> : <span className="department-pending">검토 대기</span>}
              </div>)}
              <div className="review-form">
                <label>담당 부서<select value={department} onChange={event => setDepartment(event.target.value)} disabled={busy}>{reviewDepartments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                <label>검토 결과<select value={result} onChange={event => setResult(event.target.value)} disabled={busy}><option value="possible">가능</option><option value="conditional">조건부 가능</option><option value="blocked">불가</option></select></label>
                <label>검토 의견<textarea value={opinion} onChange={event => setOpinion(event.target.value)} disabled={busy} /></label>
                <button disabled={busy || !opinion.trim() || Boolean(reviews[department])} onClick={submitReview}>검토 의견 제출</button>
              </div>
            </section>}
          </>}
          {live && selected.saveFailed && <p className="approval-complete" role="status">이전에 받은 결정을 저장하지 못했습니다. 같은 결정을 다시 보내면 이어서 처리합니다.</p>}
          <label className="approval-reason">{reasonLabel}<textarea value={reason} onChange={event => setReason(event.target.value)} disabled={busy || !canDecide} /></label>
          <div className="approval-actions">
            {live && selected.kind === 'team_failed' ? <>
              <button disabled={busy || !canDecide} onClick={() => decide('mark_unreviewed')}>검토하지 못한 팀으로 표시</button>
              <button disabled={busy || !canDecide} onClick={() => decide('retry')}>실패한 팀 다시 검토</button>
            </> : <>
              <button disabled={busy || !canDecide || !reason.trim()} onClick={() => decide('rejected')}>반려하기</button>
              {!live && selected.kind === 'issue' && <button disabled={busy || !canDecide || !reason.trim()} onClick={() => decide('revision')}>보완 요청</button>}
              <button disabled={busy || !canDecide || (approveNeedsReason && !reason.trim()) || (!live && selected.kind === 'issue' && !allReviewed)} onClick={() => decide('approved')}>승인하기</button>
            </>}
          </div>
          {actionError && <p className="approval-complete" role="alert">{actionError}</p>}
          {/* 판단에는 쓰지 않지만 서버 로그·재개 기록·GET /approvals/{id} 와 대조할 번호라 지우지 않고 맨 아래에 둔다 */}
          {live && <p className="approval-id-line">승인 번호 {selected.id}{selected.tableId ? ` · 결정표 ${selected.tableId}` : ''}</p>}
        </> : <p>{loading ? '상세 정보를 불러오는 중입니다.' : live && !loadError ? '왼쪽 목록에서 승인 요청을 선택하면 상세 내용이 표시됩니다.' : '상세 정보를 불러오지 못했습니다.'}</p>}
      </article>
    </section>
    {confirm && <div className="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-confirm-title" ref={dialogRef} onKeyDown={onDialogKeyDown}>
      <section>
        <h2 id="approval-confirm-title">{confirmTitle[confirm.status] ?? '처리하시겠습니까?'}</h2>
        <p>{confirm.title}</p>
        <div>
          <button type="button" ref={cancelRef} disabled={busy} onClick={() => setConfirm(null)}>취소</button>
          <button type="button" disabled={busy} onClick={confirmDecision}>확인</button>
        </div>
      </section>
    </div>}
  </main></DemoLayout>
}

function LiveDetail({ item }) {
  if (item.kind === 'decision' && item.decision) return <DecisionDetail detail={item.decision} />
  if (item.kind === 'issue' && item.issue) return <IssueDetail table={item.issue} />
  if (item.kind === 'team_failed' && item.failedTeams.length) return <TeamFailedDetail teams={item.failedTeams} />
  return <div className="approval-mismatch"><strong>상세 정보 없음</strong><p>서버가 이 승인 요청의 상세 내용을 내려주지 않아 처리할 수 없습니다. 목록을 새로 불러온 뒤에도 같으면 관리자에게 확인해 주세요.</p></div>
}

function DecisionDetail({ detail }) {
  const { comparison, draft } = detail
  const extra = comparison.extraBands.length ? `, 원문에 없는 구간 ${comparison.extraBands.join(', ')}` : ''
  return <>
    <h3>원문 대조</h3>
    {comparison.needsReason
      ? <div className="approval-mismatch"><strong>불일치 항목 · 검토 필요</strong><p>원문과 다른 칸 {comparison.mismatchCount}개{extra}. 승인하려면 사유를 입력해야 합니다.</p></div>
      : <div className="approval-compare"><section><small>대조 결과</small><p>원문과 다른 칸이 없습니다. (원문 칸 {comparison.sourceCells}개)</p></section></div>}
    {comparison.rows.length ? <div className="approval-table-wrap"><table className="approval-table">
      <thead><tr><th scope="col">구간</th><th scope="col">역할</th><th scope="col">원문 값</th><th scope="col">원문 기준</th><th scope="col">초안</th><th scope="col">결과</th></tr></thead>
      <tbody>{comparison.rows.map((row, index) => <tr key={`${row.band}-${row.role}-${index}`} className={row.match ? '' : 'mismatch'}>
        <td>{row.bandLabel}</td><td>{row.role}</td><td>{row.sourceValue || '없음'}</td><td>{roleLabel[row.expected] ?? row.expected}</td><td>{roleLabel[row.draft] ?? row.draft}</td><td>{row.match ? '일치' : '불일치'}</td>
      </tr>)}</tbody>
    </table></div> : <p>대조할 칸이 없습니다.</p>}
    <h3>변환된 결정표 초안</h3>
    {draft.length ? <div className="approval-table-wrap"><table className="approval-table">
      <thead><tr><th scope="col">구간</th><th scope="col">업무 승인</th><th scope="col">재무 승인</th><th scope="col">협조</th></tr></thead>
      <tbody>{draft.map((rule, index) => <tr key={`${rule.band}-${index}`}>
        <td>{rule.bandLabel}</td><td>{rule.approvers.join(', ') || '없음'}</td><td>{rule.financialApprovers.join(', ') || '없음'}</td><td>{rule.cooperating.join(', ') || '없음'}</td>
      </tr>)}</tbody>
    </table></div> : <p>초안에 구간이 없습니다.</p>}
  </>
}

function IssueDetail({ table }) {
  return <>
    <h3>합동 검토 요청</h3>
    <div className="approval-compare"><section><small>요청{table.asOf ? ` · 기준일 ${table.asOf}` : ''}</small><p>{table.request || '없음'}</p></section></div>
    <h3>쟁점표</h3>
    {table.rows.length ? <div className="approval-table-wrap"><table className="approval-table">
      <thead><tr><th scope="col">팀</th><th scope="col">쟁점</th><th scope="col">입장</th><th scope="col">확신도</th><th scope="col">근거</th></tr></thead>
      <tbody>{table.rows.map((row, index) => <tr key={`${row.team}-${index}`}>
        <td>{row.teamLabel}</td>
        <td>{row.issue}{row.conflict && <><br /><b>팀 입장 충돌</b></>}</td>
        <td>{stanceLabel[row.stance] ?? '없음'}</td>
        <td>{confidenceLabel[row.confidence] ?? '없음'}</td>
        <td>{row.sectionPath || '없음'}{row.versionDate ? ` · ${row.versionDate}` : ''}{row.sourceUrl && <><br /><a href={row.sourceUrl} target="_blank" rel="noreferrer">원문 보기</a></>}</td>
      </tr>)}</tbody>
    </table></div> : <p>쟁점 행이 없습니다.</p>}
    {table.unreviewed.length > 0 && <div className="approval-mismatch"><strong>검토하지 못한 팀</strong>{table.unreviewed.map((team, index) => <p key={`${team.team}-${index}`}>{team.teamLabel}: {team.reason}</p>)}</div>}
  </>
}

function TeamFailedDetail({ teams }) {
  return <>
    <h3>검토하지 못한 팀</h3>
    <div className="approval-table-wrap"><table className="approval-table">
      <thead><tr><th scope="col">팀</th><th scope="col">이유</th><th scope="col">시도 횟수</th></tr></thead>
      <tbody>{teams.map((team, index) => <tr key={`${team.team}-${index}`}><td>{teamLabel[team.team] ?? team.team}</td><td>{team.reason || '없음'}</td><td>{team.attempts ?? '없음'}</td></tr>)}</tbody>
    </table></div>
    <div className="approval-compare"><section><small>선택할 수 있는 처리</small><p>다시 검토를 고르면 실패한 팀만 다시 실행합니다. 검토하지 못한 팀으로 표시를 고르면 그 팀의 쟁점 없이 쟁점표 승인 단계로 넘어갑니다.</p></section></div>
  </>
}
