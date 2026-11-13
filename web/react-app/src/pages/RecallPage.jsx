import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { describeApiError, filterByChange, formatConfidence, parseImpactInput, previewRecallService } from '../lib/recall-service'
import { versionText } from '../lib/change-monitoring-service'
import { useServiceSnapshot } from '../lib/live-services'

const SEVERITY_LABEL = { high: '중요', low: '참고' }
const CANDIDATE_STATUS_LABEL = { pending: '검토 대기', needed: '정비 필요', not_needed: '정비 불필요' }
const NOT_FOUND = '알림을 찾을 수 없습니다.'

function Marked({ text, mark, at: markAt }) {
  if (!mark || !text?.includes(mark)) return text
  // 실서버 값은 바뀐 위치(changedAt)를 함께 준다. 같은 글이 앞에도 있으면 첫 위치가 아니라 그 위치를 강조한다.
  const at = Number.isInteger(markAt) && text.slice(markAt, markAt + mark.length) === mark ? markAt : text.indexOf(mark)
  const before = text.slice(0, at)
  const after = text.slice(at + mark.length)
  return <>{before}<mark>{mark}</mark>{after}<span className="changed-text-legend"><i aria-hidden="true" />변경된 부분</span></>
}

function JudgementBadges({ record }) {
  const confidence = formatConfidence(record.confidence)
  return <>
    {record.severity && <span className={`recall-severity ${record.severity}`}>{SEVERITY_LABEL[record.severity]}</span>}
    {confidence && <span className="recall-confidence">확신도 {confidence}</span>}
    {record.needsConfirmation && <span className="recall-confirm-badge">확인 필요</span>}
  </>
}

function listErrorMessage(error) {
  if (!error) return ''
  if (error.status === 403 || error.code === 'forbidden') return '이 작업을 수행할 권한이 없습니다.'
  if (error.status === 401 || error.code === 'unauthorized') return '로그인이 필요합니다.'
  return '리콜 알림을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
}

export default function RecallPage({ service = previewRecallService, isAdmin = false, userId = null }) {
  const live = service.live
  const snapshot = useServiceSnapshot(service)
  const { records, unread } = snapshot
  const status = snapshot.status ?? 'ready'
  const [params, setParams] = useSearchParams()
  const ruleSeq = live ? params.get('rule_seq') ?? '' : ''
  const article = live ? params.get('article') ?? '' : ''
  const requestedId = live ? params.get('notice') : null
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(() => requestedId ?? records[0]?.id ?? null)
  const [actionError, setActionError] = useState('')
  const [digestError, setDigestError] = useState('')
  const [busy, setBusy] = useState(false)
  const [missingId, setMissingId] = useState(null)
  const scoped = useMemo(() => filterByChange(records, { ruleSeq, article }), [article, records, ruleSeq])
  const visible = useMemo(() => service.filterRecalls(scoped, filter), [filter, scoped, service])
  const selected = records.find(record => record.id === selectedId) ?? (selectedId && selectedId === missingId ? null : visible[0] ?? null)
  // An administrator sees every user's notices, but the backend lets only the owner acknowledge one (POST /recalls/{id}/ack -> 404).
  const othersNotice = Boolean(live && userId && selected?.userId && selected.userId !== String(userId).toLowerCase())
  const filters = live ? [['all', '전체'], ['unread', '미확인'], ['changed', '결론 변경'], ['high', '중요'], ['confirm', '확인 필요']] : [['all', '전체'], ['unread', '미확인'], ['changed', '결론 변경']]

  useEffect(() => {
    if (!live) return
    service.listRecalls().catch(() => {})
    setDigestError('')
    service.listDigests?.().catch(() => setDigestError('하루 요약을 불러오지 못했습니다.'))
  }, [live, service])

  useEffect(() => {
    if (!live || !requestedId || missingId === requestedId || status !== 'ready' || records.some(record => record.id === requestedId)) return undefined
    let active = true
    service.getRecall(requestedId).catch(error => {
      if (!active) return
      setMissingId(requestedId)
      setActionError(describeApiError(error, NOT_FOUND))
    })
    return () => { active = false }
  }, [live, missingId, records, requestedId, service, status])

  function select(id) {
    setActionError('')
    setSelectedId(id)
  }

  async function acknowledge(id) {
    if (busy) return
    setBusy(true)
    setActionError('')
    try {
      await service.acknowledgeRecall(id)
    } catch (error) {
      setActionError(describeApiError(error, NOT_FOUND))
    } finally {
      setBusy(false)
    }
  }

  function clearChangeFilter() {
    const next = new URLSearchParams(params)
    next.delete('rule_seq')
    next.delete('article')
    setParams(next, { replace: true })
  }

  const loadingFirst = status === 'loading' && records.length === 0
  const failedFirst = status === 'error' && records.length === 0
  const chatLink = live ? { pathname: '/chat' } : { pathname: '/demo/chat' }

  return <DemoLayout active="recalls"><main className="recall-service-page">
    <header className="recall-service-heading"><div><h1>리콜 알림</h1></div><span className="recall-unread">미확인 {unread}건</span></header>
    <div className="recall-filter-row" role="group" aria-label="리콜 알림 필터">{filters.map(([key, label]) => <button type="button" key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div>
    {(ruleSeq || article) && <p className="recall-scope-note">선택한 정책 변경({[ruleSeq, article].filter(Boolean).join(' · ')})과 관련된 알림만 표시하고 있습니다. <button type="button" onClick={clearChangeFilter}>전체 알림 보기</button></p>}
    {status === 'error' && records.length > 0 && <p className="recall-action-error" role="alert">{listErrorMessage(snapshot.error)} <button type="button" onClick={() => service.listRecalls().catch(() => {})}>다시 시도</button></p>}
    <section className="recall-service-layout"><aside className="recall-service-list"><h2>알림 목록</h2>
      {loadingFirst ? <p className="recall-empty" role="status">알림을 불러오고 있습니다.</p>
        : failedFirst ? <div className="recall-empty recall-load-error" role="alert"><p>{listErrorMessage(snapshot.error)}</p><button type="button" className="demo-outline-button" onClick={() => service.listRecalls().catch(() => {})}>다시 시도</button></div>
          : visible.length === 0 ? <p className="recall-empty">{records.length ? '해당하는 알림이 없습니다.' : '받은 알림이 없습니다.'}</p>
            : visible.map(record => <button type="button" key={record.id} className={`recall-service-item ${record.id === selected?.id ? 'selected' : ''} ${record.needsConfirmation ? 'needs-confirmation' : ''}`} onClick={() => select(record.id)}><div><strong>{record.title}</strong>{!record.acked && <i aria-label="미확인" />}</div><span>{record.question}</span><small>{[record.document, record.detectedAt].filter(Boolean).join(' · ')}</small>{live && (record.severity || record.needsConfirmation) && <span className="recall-item-badges"><JudgementBadges record={{ ...record, confidence: null }} /></span>}<em className={record.conclusionChanged ? 'changed' : ''}>{record.conclusionChanged ? '결론 변경' : record.acked ? '확인 완료' : '확인 필요'}</em></button>)}
      {live && snapshot.truncated && <p className="recall-empty" role="status">최근 알림 500건만 표시하고 있습니다. 더 오래된 알림은 목록에 나오지 않습니다.</p>}
    </aside>
      <article className="recall-service-detail">{selected ? <><div className="recall-detail-top"><div><span className={`recall-result ${selected.conclusionChanged ? 'changed' : ''}`}>{selected.conclusionChanged ? '결론 변경' : '결론 유지'}</span>{live && <span className="recall-detail-badges"><JudgementBadges record={selected} /></span>}<h2>{selected.title}</h2><p>{[selected.document, `변경 감지 ${selected.detectedAt}`].filter(Boolean).join(' · ')}{versionText(selected.oldVersionDate, selected.newVersionDate) && ` · ${versionText(selected.oldVersionDate, selected.newVersionDate)}`}</p></div>{othersNotice ? <span className="recall-owner-note">다른 사용자의 알림입니다.</span> : <button type="button" className="demo-outline-button" disabled={selected.acked || busy} onClick={() => acknowledge(selected.id)}>{selected.acked ? '확인 완료' : '확인'}</button>}</div>
        {actionError && <p className="recall-action-error" role="alert">{actionError}</p>}
        {selected.needsConfirmation && <p className="recall-confirm-needed" role="note">자동 판정에 실패한 알림입니다. 원문과 당시 답변을 직접 확인해 주세요.</p>}
        {live && selected.question && <section className="recall-answer recall-question"><small>당시 질문</small><p>{selected.question}</p></section>}
        <section className="recall-answer"><small>영향받은 답변</small><p>{selected.oldAnswer || '저장된 답변 요약이 없습니다.'}</p></section>
        {live && selected.explanation && <section className="recall-explanation"><small>판정 설명</small><p>{selected.explanation}</p></section>}
        {(selected.oldPolicy || selected.newPolicy) && <><h3>정책 변경 전후</h3><div className="recall-policy-grid">{selected.oldPolicy && <section><small>변경 전</small><p>{selected.oldPolicy}</p></section>}{selected.newPolicy && <section className="after"><small>변경 후</small><p><Marked text={selected.newPolicy} mark={selected.changedText} at={selected.changedAt} /></p></section>}</div></>}
        <div className="recall-detail-actions">{selected.sourceUrl && <a href={selected.sourceUrl} target="_blank" rel="noreferrer" className="demo-outline-button">원문 보기</a>}<Link to={chatLink} state={{ question: selected.question }} className="demo-dark-button">다시 질문하기</Link></div>
        {service.sendFeedback && <FeedbackControls key={selected.id} record={selected} service={service} />}
      </> : selectedId && selectedId === missingId ? <div className="recall-empty-detail" role="alert"><h2>{NOT_FOUND}</h2><p>삭제되었거나 접근할 수 없는 알림입니다. 목록에서 다른 알림을 선택해 주세요.</p></div>
        : <div className="recall-empty-detail"><h2>아직 알림이 없습니다.</h2><p>정책 변경으로 다시 확인이 필요한 답변이 생기면 알려드립니다.</p></div>}</article></section>
    {live && digestError && <p className="recall-action-error" role="alert">{digestError}</p>}
    {live && snapshot.digests?.length > 0 && <DigestPanel digests={snapshot.digests} />}
    {live && isAdmin && <>
      <ReviewQueue items={snapshot.reviewQueue ?? []} service={service} />
      <CandidatePanel items={snapshot.candidates ?? []} service={service} />
      {service.previewImpact && <ImpactPreviewPanel service={service} />}
      {(service.flushDigests || service.processPending) && <OperationsPanel service={service} />}
      {service.listWebhooks && <WebhookPanel service={service} />}
    </>}
  </main></DemoLayout>
}

function FeedbackControls({ record, service }) {
  const [askReason, setAskReason] = useState(false)
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const feedback = record.feedback

  async function send(useful) {
    if (sending) return
    setSending(true)
    setError('')
    try {
      await service.sendFeedback(record.id, { useful, reason: useful ? null : reason })
      setAskReason(false)
      setReason('')
    } catch (sendError) {
      setError(describeApiError(sendError, NOT_FOUND))
    } finally {
      setSending(false)
    }
  }

  return <section className="recall-feedback" aria-label="알림 의견">
    <small>이 알림이 도움이 되었나요?</small>
    {feedback ? <p role="status">{feedback.useful ? '도움 됨으로 의견을 남겼습니다.' : '필요 없음으로 의견을 남겼습니다. 비슷한 유형의 알림은 줄여 드립니다.'}</p>
      : askReason ? <div className="recall-feedback-reason"><label><span>필요 없는 이유 (선택)</span><textarea value={reason} maxLength={500} onChange={event => setReason(event.target.value)} placeholder="예: 이미 알고 있는 변경입니다." /></label><div><button type="button" className="demo-outline-button" disabled={sending} onClick={() => setAskReason(false)}>취소</button><button type="button" className="demo-dark-button" disabled={sending} onClick={() => send(false)}>{sending ? '보내는 중입니다.' : '의견 보내기'}</button></div></div>
        : <div className="recall-feedback-actions"><button type="button" className="demo-outline-button" disabled={sending} onClick={() => send(true)}>도움 됨</button><button type="button" className="demo-outline-button" disabled={sending} onClick={() => setAskReason(true)}>필요 없음</button></div>}
    {error && <p className="recall-action-error" role="alert">{error}</p>}
  </section>
}

function DigestPanel({ digests }) {
  return <section className="recall-admin-section recall-digest" aria-labelledby="recall-digest-title">
    <div className="recall-admin-heading"><h2 id="recall-digest-title">하루 요약</h2><span>최근 {Math.min(digests.length, 7)}일</span></div>
    <ul>{digests.slice(0, 7).map(digest => <li key={digest.id || digest.day}><strong>{digest.day}</strong><span>{[`알림 ${digest.count}건`, digest.high != null && `중요 ${digest.high}건`, digest.low != null && `참고 ${digest.low}건`].filter(Boolean).join(' · ')}</span></li>)}</ul>
  </section>
}

function ReviewQueue({ items, service }) {
  const [busyId, setBusyId] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function review(id, action) {
    if (busyId || !service.reviewRecall) return
    setBusyId(id)
    setError('')
    setMessage('')
    try {
      await service.reviewRecall(id, action)
      setMessage(action === 'release' ? '사용자에게 알림을 보냈습니다.' : '알림을 폐기했습니다.')
    } catch (reviewError) {
      setError(describeApiError(reviewError, NOT_FOUND))
    } finally {
      setBusyId(null)
    }
  }

  return <section className="recall-admin-section" aria-labelledby="recall-review-title">
    <div className="recall-admin-heading"><h2 id="recall-review-title">관리자 확인 대기</h2><span>{items.length}건</span></div>
    <p className="recall-admin-lede">확신도가 낮아 사용자에게 보내기 전에 관리자 확인이 필요한 알림입니다.</p>
    {message && <p role="status" className="recall-admin-message">{message}</p>}
    {error && <p role="alert" className="recall-action-error">{error}</p>}
    {items.length === 0 ? <p className="recall-empty">확인 대기 중인 알림이 없습니다.</p> : <div className="recall-admin-list">{items.map(item => <article key={item.id} className={`recall-admin-card ${item.needsConfirmation ? 'needs-confirmation' : ''}`}>
      <div className="recall-admin-card-top"><strong>{item.title}</strong><span className="recall-detail-badges"><JudgementBadges record={item} /></span></div>
      <small>{[item.document, item.detectedAt].filter(Boolean).join(' · ')}</small>
      {item.question && <p><b>질문</b> {item.question}</p>}
      {item.explanation && <p><b>판정 설명</b> {item.explanation}</p>}
      <div className="recall-admin-actions"><button type="button" className="demo-outline-button" disabled={Boolean(busyId)} onClick={() => review(item.id, 'dismiss')}>폐기</button><button type="button" className="demo-dark-button" disabled={Boolean(busyId)} onClick={() => review(item.id, 'release')}>사용자에게 보내기</button></div>
    </article>)}</div>}
  </section>
}

function CandidatePanel({ items, service }) {
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const pending = items.filter(item => item.status === 'pending').length

  async function decide(id, status) {
    if (busyId || !service.decideCandidate) return
    setBusyId(id)
    setError('')
    try {
      await service.decideCandidate(id, status)
    } catch (decideError) {
      setError(describeApiError(decideError, '정비 후보를 찾을 수 없습니다.'))
    } finally {
      setBusyId(null)
    }
  }

  return <section className="recall-admin-section" aria-labelledby="recall-candidate-title">
    <div className="recall-admin-heading"><h2 id="recall-candidate-title">함께 볼 정책 후보</h2><span>검토 대기 {pending}건</span></div>
    <p className="recall-admin-lede">바뀐 정책과 링크로 연결된 다른 정책입니다. 함께 정비가 필요한지 판단해 주세요.</p>
    {error && <p role="alert" className="recall-action-error">{error}</p>}
    {items.length === 0 ? <p className="recall-empty">함께 볼 정책 후보가 없습니다.</p> : <div className="recall-admin-list">{items.map(item => <article key={item.id} className="recall-admin-card">
      <div className="recall-admin-card-top"><strong>{[item.ruleSeq, item.article].filter(Boolean).join(' · ') || '연결 정책'}</strong><span className={`recall-candidate-status ${item.status}`}>{CANDIDATE_STATUS_LABEL[item.status]}</span></div>
      <small>바뀐 정책: {item.upperRule || '정보 없음'}</small>
      <p><b>사유</b> {item.reason || '사유가 기록되지 않았습니다.'}</p>
      {item.decidedBy && <small>판단한 관리자: {item.decidedBy}</small>}
      {item.status === 'pending' && <div className="recall-admin-actions"><button type="button" className="demo-outline-button" disabled={Boolean(busyId)} onClick={() => decide(item.id, 'not_needed')}>정비 불필요</button><button type="button" className="demo-dark-button" disabled={Boolean(busyId)} onClick={() => decide(item.id, 'needed')}>정비 필요</button></div>}
    </article>)}</div>}
  </section>
}

function ImpactPreviewPanel({ service }) {
  const [mode, setMode] = useState('changes')
  const [input, setInput] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)

  async function run(event) {
    event.preventDefault()
    if (running) return
    setError('')
    let payload
    try { payload = parseImpactInput(mode, input) } catch (parseError) { setError(parseError.message); return }
    setRunning(true)
    try {
      setResult(await service.previewImpact(payload))
    } catch (previewError) {
      setResult(null)
      setError(describeApiError(previewError, '영향 미리보기 기능을 찾을 수 없습니다.'))
    } finally {
      setRunning(false)
    }
  }

  return <section className="recall-admin-section" aria-labelledby="impact-preview-title">
    <div className="recall-admin-heading"><h2 id="impact-preview-title">변경 전 영향 미리보기</h2><span>저장·알림 없음</span></div>
    <p className="recall-admin-lede">개정안의 바뀐 섹션 목록이나 개정 전후 본문을 넣으면 무효가 될 답변과 알림 대상 수를 미리 계산합니다.</p>
    <form className="impact-preview-form" onSubmit={run}>
      <div className="recall-filter-row" role="group" aria-label="입력 형식">{[['changes', '바뀐 섹션 목록(JSON)'], ['pages', '개정 전후 본문(JSON)']].map(([key, label]) => <button type="button" key={key} className={mode === key ? 'selected' : ''} onClick={() => setMode(key)}>{label}</button>)}</div>
      <label><textarea aria-label={mode === 'pages' ? '개정 전후 본문(JSON)' : '바뀐 섹션 목록(JSON)'} value={input} onChange={event => setInput(event.target.value)} rows={8} placeholder={mode === 'pages' ? '{"old_version_date": "2026-11-01", "new_version_date": "2026-11-10", "pages": [{"path": "handbook/a.md", "old": "# 문서 제목\\n\\n## 1조\\n이전 본문", "new": "# 문서 제목\\n\\n## 1조\\n새 본문"}]}' : '[{"rule_seq": 12, "article": "조항 이름", "old_version_date": "2026-11-01", "new_version_date": "2026-11-10", "change_type": "modified"}]'} /></label>
      <div className="recall-admin-actions"><button type="submit" className="demo-dark-button" disabled={running}>{running ? '계산 중입니다.' : '미리보기 실행'}</button></div>
    </form>
    {error && <p role="alert" className="recall-action-error">{error}</p>}
    {result && hasUnnamedSection(result) && <p className="recall-admin-lede" role="note">섹션 이름이 비어 있는 항목이 있습니다. 섹션 이름은 본문의 제목 줄('## 1조'처럼 #로 시작)에서 가져오므로, 개정 전후 본문(old·new)에 제목 줄을 넣어 주세요.</p>}
    {result && <div className="impact-preview-result"><small>MR 댓글용 요약</small><pre>{result.markdown || '요약 내용이 없습니다.'}</pre></div>}
  </section>
}

// 개정 전후 본문(pages) 입력에 제목 줄(#)이 없으면 서버가 섹션 이름을 비워 보낸다(backend/rag/ingest/diff.py article_of). 표의 '섹션' 칸이 비는 이유를 알려 준다.
function hasUnnamedSection(result) {
  const changes = result?.report?.changes
  return Array.isArray(changes) && changes.some(change => typeof change?.article === 'string' && change.article.trim() === '')
}

function OperationsPanel({ service }) {
  const [running, setRunning] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function run(kind) {
    if (running) return
    const question = kind === 'digest' ? '오늘의 하루 요약을 지금 만들까요? 사용자에게 알림이 전달될 수 있습니다.' : '처리 대기 중인 변경을 지금 처리할까요? LLM을 호출하고 사용자에게 알림이 전달될 수 있습니다.'
    if (!window.confirm(question)) return
    setRunning(kind)
    setMessage('')
    setError('')
    try {
      if (kind === 'digest') {
        const result = await service.flushDigests()
        setMessage(`하루 요약 ${result.digests}건을 만들었습니다(알림 ${result.notices}건).`)
        service.listDigests?.().catch(() => {})
      } else {
        const result = await service.processPending()
        setMessage(`변경 ${result.processed}건을 처리했습니다(알림 ${result.notices}건 생성, 실패 ${result.failed}건, 건너뜀 ${result.skipped}건).`)
        service.listRecalls().catch(() => {})
      }
    } catch (runError) {
      setError(describeApiError(runError))
    } finally {
      setRunning('')
    }
  }

  return <section className="recall-admin-section" aria-labelledby="recall-ops-title">
    <div className="recall-admin-heading"><h2 id="recall-ops-title">리콜 수동 실행</h2><span>관리자 전용</span></div>
    <p className="recall-admin-lede">정해진 시간을 기다리지 않고 지금 실행합니다. 두 작업 모두 사용자에게 알림을 보낼 수 있습니다.</p>
    <div className="recall-admin-actions">
      {service.flushDigests && <button type="button" className="demo-outline-button" disabled={Boolean(running)} onClick={() => run('digest')}>{running === 'digest' ? '만드는 중입니다.' : '하루 요약 지금 만들기'}</button>}
      {service.processPending && <button type="button" className="demo-outline-button" disabled={Boolean(running)} onClick={() => run('pending')}>{running === 'pending' ? '처리 중입니다.' : '처리 대기 변경 지금 처리'}</button>}
    </div>
    {message && <p role="status" className="recall-admin-lede">{message}</p>}
    {error && <p role="alert" className="recall-action-error">{error}</p>}
  </section>
}

function WebhookPanel({ service }) {
  const [items, setItems] = useState(null)
  const [url, setUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    service.listWebhooks().then(list => { if (alive) setItems(list) }).catch(loadError => { if (alive) { setItems([]); setError(describeApiError(loadError, '웹훅 구독을 찾을 수 없습니다.')) } })
    return () => { alive = false }
  }, [service])

  async function add(event) {
    event.preventDefault()
    if (adding) return
    if (!url.trim()) { setError('웹훅 주소를 입력해 주세요.'); return }
    setAdding(true)
    setMessage('')
    setError('')
    try {
      const created = await service.addWebhook(url)
      setItems(current => [...(current ?? []), created])
      setUrl('')
      setMessage('웹훅 구독을 추가했습니다.')
    } catch (addError) {
      setError(describeApiError(addError))
    } finally {
      setAdding(false)
    }
  }

  return <section className="recall-admin-section" aria-labelledby="recall-webhook-title">
    <div className="recall-admin-heading"><h2 id="recall-webhook-title">웹훅 구독</h2><span>{items ? `${items.length}건` : '불러오는 중'}</span></div>
    <p className="recall-admin-lede">리콜 알림을 받을 외부 주소입니다. 서버에 삭제 기능이 없어 화면에서도 삭제할 수 없습니다.</p>
    {items && (items.length === 0 ? <p className="recall-empty">등록된 웹훅 구독이 없습니다.</p> : <ul>{items.map(item => <li key={item.id}><strong>{item.url}</strong> <span>{[item.active ? '사용 중' : '꺼짐', item.secretConfigured ? '서명 키 있음' : '서명 키 없음', item.createdAt].filter(Boolean).join(' · ')}</span></li>)}</ul>)}
    <form className="impact-preview-form" onSubmit={add}>
      <label>웹훅 주소<input type="url" value={url} onChange={event => setUrl(event.target.value)} placeholder="https://example.com/hook" maxLength={500} /></label>
      <div className="recall-admin-actions"><button type="submit" className="demo-dark-button" disabled={adding}>{adding ? '추가하는 중입니다.' : '구독 추가'}</button></div>
    </form>
    {message && <p role="status" className="recall-admin-lede">{message}</p>}
    {error && <p role="alert" className="recall-action-error">{error}</p>}
  </section>
}
