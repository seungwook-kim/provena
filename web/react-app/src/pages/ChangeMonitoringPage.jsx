import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { previewChangeMonitoringService } from '../lib/change-monitoring-service'
import { describeApiError } from '../lib/recall-service'
import { useServiceSnapshot } from '../lib/live-services'

const CHANGE_TYPES = ['MODIFIED', 'ADDED', 'REMOVED', 'HELD']
const CHANGE_LABELS = { MODIFIED: '수정', ADDED: '추가', REMOVED: '삭제', HELD: '동결 보류' }
const DELIVERY_LABELS = { pending: '알림 발송 대기', sent: '알림 발송 완료', failed: '알림 발송 실패' }
const MONITORING_LABELS = { active: '감시 중', paused: '일시 중지' }
const NOT_FOUND = '변경 기록을 찾을 수 없습니다.'

function Marked({ text, mark }) {
  if (!mark || !text?.includes(mark)) return text
  const [before, after] = text.split(mark)
  return <>{before}<mark>{mark}</mark>{after}<span className="changed-text-legend"><i aria-hidden="true" />변경된 부분</span></>
}

function ChangeDistribution({ counts, scope }) {
  const total = counts.reduce((sum, item) => sum + item.count, 0)
  return <section className="change-distribution" aria-label="변경 유형 분포">
    <div className="change-distribution-heading"><div><h2>변경 유형 분포</h2><small>{scope}</small></div><span>총 {total}건</span></div>
    <div className="change-distribution-track" role="img" aria-label={total ? `총 ${total}건의 변경 유형 분포` : '변경 기록이 없습니다.'}>{counts.map(item => <span key={item.type} className={`change-distribution-segment ${item.type.toLowerCase()}`} style={{ width: `${total ? (item.count / total) * 100 : 0}%` }} title={`${CHANGE_LABELS[item.type]} ${item.count}건`} />)}</div>
    <div className="change-distribution-legend">{counts.map(item => <div className="change-distribution-legend-item" key={item.type}><span className={`change-distribution-dot ${item.type.toLowerCase()}`} aria-hidden="true" /><span>{CHANGE_LABELS[item.type]}</span><b>{item.count}건</b></div>)}</div>
  </section>
}

function listErrorMessage(error) {
  if (!error) return ''
  if (error.status === 403 || error.code === 'forbidden') return '이 작업을 수행할 권한이 없습니다.'
  if (error.status === 401 || error.code === 'unauthorized') return '로그인이 필요합니다.'
  return '변경 기록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
}

function MonitoringControl({ service, status, isAdmin }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const next = status === 'paused' ? 'active' : 'paused'

  async function toggle() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await service.updateMonitoringStatus(next)
    } catch (updateError) {
      setError(describeApiError(updateError, '감시 상태를 바꿀 수 없습니다.'))
    } finally {
      setBusy(false)
    }
  }

  return <div className="change-monitoring-control">
    <span className={`change-monitoring-status ${status ?? 'unknown'}`}>{status ? MONITORING_LABELS[status] : '감시 상태 확인 전'}</span>
    {isAdmin && status && <button type="button" className="demo-outline-button" disabled={busy} onClick={toggle}>{busy ? '변경 중입니다.' : status === 'paused' ? '감시 다시 시작' : '감시 일시 중지'}</button>}
    {error && <span className="recall-action-error" role="alert">{error}</span>}
  </div>
}

export default function ChangeMonitoringPage({ service = previewChangeMonitoringService, isAdmin = false }) {
  const live = service.live
  const snapshot = useServiceSnapshot(service)
  const { records } = snapshot
  const status = snapshot.status ?? 'ready'
  const [query, setQuery] = useState('')
  const [enabled, setEnabled] = useState({ MODIFIED: true, ADDED: true, REMOVED: true, HELD: true })
  const [selectedId, setSelectedId] = useState(() => records[0]?.id ?? null)
  const [detailError, setDetailError] = useState({ id: null, message: '' })
  const visible = useMemo(() => service.filterChanges(records, { query, types: enabled }), [enabled, query, records, service])
  const selected = visible.find(record => record.id === selectedId) ?? visible[0] ?? null
  // 실서버는 목록을 쪽으로 나눠 받으므로 분포·합계는 서버가 센 전체 건수를 쓴다(없으면 불러온 목록으로 센다). 동결 보류는 목록 맨 앞 알림 한 줄이다.
  const serverCounts = live ? snapshot.typeCounts ?? null : null
  const typeCounts = useMemo(() => CHANGE_TYPES.map(type => ({ type, count: serverCounts && type !== 'HELD' ? serverCounts[type] ?? 0 : records.filter(record => record.type === type).length })), [records, serverCounts])
  const selectedNeedsDetail = live && selected && !selected.detailLoaded

  useEffect(() => {
    if (!live) return
    service.listChanges().catch(() => {})
  }, [live, service])

  const selectedDetailId = selectedNeedsDetail ? selected.id : null
  useEffect(() => {
    if (!selectedDetailId) return undefined
    let active = true
    service.getChange(selectedDetailId).catch(error => { if (active) setDetailError({ id: selectedDetailId, message: describeApiError(error, NOT_FOUND) }) })
    return () => { active = false }
  }, [selectedDetailId, service])

  const loadingFirst = status === 'loading' && records.length === 0
  const failedFirst = status === 'error' && records.length === 0
  const detailFailed = Boolean(selected) && detailError.id === selected.id && !selected.detailLoaded
  const detailState = { loading: Boolean(selectedNeedsDetail) && !detailFailed, error: detailFailed ? detailError.message : '' }
  const lastRun = snapshot.lastRun

  return <DemoLayout active="changes"><main className="change-service-page">
    <header className="change-service-heading"><div><h1>정책 변경 감시</h1>{live && lastRun && <p>마지막 수집 {lastRun.finishedAt || '시각 미기록'}{lastRun.status ? ` · ${lastRun.status}` : ''}</p>}</div>{live && <MonitoringControl service={service} status={snapshot.monitoring?.status ?? null} isAdmin={isAdmin} />}</header>
    <section className="change-service-tools"><input value={query} onChange={event => setQuery(event.target.value)} placeholder="정책 문서 검색" aria-label="정책 문서 검색" /><div>{CHANGE_TYPES.map(kind => <button type="button" key={kind} className={enabled[kind] ? 'selected' : ''} onClick={() => setEnabled(current => ({ ...current, [kind]: !current[kind] }))}>{CHANGE_LABELS[kind]}</button>)}</div></section>
    {status === 'error' && records.length > 0 && <p className="recall-action-error" role="alert">{listErrorMessage(snapshot.error)} <button type="button" onClick={() => service.listChanges().catch(() => {})}>다시 시도</button></p>}
    <ChangeDistribution counts={typeCounts} scope={serverCounts ? '조회 기간 전체 기준' : '현재 목록 기준'} />
    <section className="change-service-layout"><aside className="change-service-list"><h2>정책 변경 목록</h2>
      {loadingFirst ? <p className="change-service-empty" role="status">변경 기록을 불러오고 있습니다.</p>
        : failedFirst ? <div className="change-service-empty recall-load-error" role="alert"><p>{listErrorMessage(snapshot.error)}</p><button type="button" className="demo-outline-button" onClick={() => service.listChanges().catch(() => {})}>다시 시도</button></div>
          : visible.length ? visible.map(record => <button type="button" key={record.id} className={`change-service-item ${record.id === selected?.id ? 'selected' : ''}`} onClick={() => setSelectedId(record.id)}><div><strong>{record.document}</strong><span className={`change-type ${record.type.toLowerCase()}`}>{CHANGE_LABELS[record.type]}</span></div><p>{record.summary}</p><small>{[record.area, record.detectedAt].filter(Boolean).join(' · ')}</small>{typeof record.impactedAnswerCount === 'number' && <em>영향받는 답변 {record.impactedAnswerCount}건</em>}</button>) : <p className="change-service-empty">{records.length ? '검색 결과가 없습니다.' : '변경 기록이 없습니다.'}</p>}
      {live && snapshot.more && <button type="button" className="demo-outline-button change-load-more" disabled={status === 'loading'} onClick={() => service.loadMore?.().catch(() => {})}>{status === 'loading' ? '불러오는 중입니다.' : '더 보기'}</button>}
    </aside>
      <article className="change-service-detail">{selected ? <><div className="change-detail-head"><div><span className={`change-type ${selected.type.toLowerCase()}`}>{CHANGE_LABELS[selected.type]}</span><h2>{selected.document}</h2><p>{[selected.area, `변경 감지 ${selected.detectedAt}`].filter(Boolean).join(' · ')}{selected.deliveryStatus && ` · ${DELIVERY_LABELS[selected.deliveryStatus]}`}</p></div></div><section className="change-summary"><small>변경 내용 요약</small><p>{selected.summary}</p></section>
        {detailState.loading && <p className="change-service-empty" role="status">변경 전후 본문을 불러오고 있습니다.</p>}
        {detailState.error && <p className="recall-action-error" role="alert">{detailState.error}</p>}
        {(selected.oldPolicy || selected.newPolicy) && <><h3>정책 변경 전후</h3><div className={`change-policy-grid ${!selected.oldPolicy || !selected.newPolicy ? 'single' : ''}`}>{selected.oldPolicy && <section className={selected.type === 'REMOVED' ? 'highlight' : ''}><small>변경 전</small><p><Marked text={selected.oldPolicy} mark={selected.type === 'REMOVED' ? selected.changedText : null} /></p></section>}{selected.newPolicy && <section className={selected.type === 'ADDED' || selected.type === 'MODIFIED' ? 'highlight' : ''}><small>변경 후</small><p><Marked text={selected.newPolicy} mark={selected.type === 'ADDED' || selected.type === 'MODIFIED' ? selected.changedText : null} /></p></section>}</div></>}
        {live && selected.detailLoaded && !selected.held && !selected.oldPolicy && !selected.newPolicy && <p className="change-service-empty">저장된 변경 전후 본문이 없습니다.</p>}
        {typeof selected.impactedAnswerCount === 'number' && <section className="change-impact"><small>관련 답변 영향</small><p>이 변경은 기존 답변 {selected.impactedAnswerCount}건과 관련되어 있습니다.</p></section>}
        <div className="change-detail-actions">{selected.sourceUrl && <a href={selected.sourceUrl} target="_blank" rel="noreferrer" className="demo-outline-button">원문 보기</a>}{selected.recallTo && <Link to={selected.recallTo} className="demo-dark-button">관련 리콜 알림 보기</Link>}</div></>
        : <div className="change-empty-detail"><h2>{records.length || !live ? '변경 기록을 선택하세요.' : '아직 감지된 변경이 없습니다.'}</h2><p>{records.length || !live ? '선택한 정책 문서의 변경 내용을 확인할 수 있습니다.' : '정책 문서에 변경이 감지되면 이곳에 표시됩니다.'}</p></div>}</article>
    </section>
  </main></DemoLayout>
}
