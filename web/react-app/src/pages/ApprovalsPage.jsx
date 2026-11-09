import { useEffect, useMemo, useState } from 'react'
import DemoLayout from '../components/DemoLayout'
import { previewApprovalsService, reviewDepartments } from '../lib/approvals-service'

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
