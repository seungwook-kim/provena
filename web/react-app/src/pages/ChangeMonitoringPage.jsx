import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { previewChangeMonitoringService } from '../lib/change-monitoring-service'
import { usePreviewChangeMonitoring } from '../lib/use-preview-change-monitoring'

const CHANGE_TYPES = ['MODIFIED', 'ADDED', 'REMOVED', 'HELD']
const CHANGE_LABELS = { MODIFIED: '수정', ADDED: '추가', REMOVED: '삭제', HELD: '동결 보류' }

function Marked({ text, mark }) {
  if (!mark || !text?.includes(mark)) return text
  const [before, after] = text.split(mark)
  return <>{before}<mark>{mark}</mark>{after}<span className="changed-text-legend"><i aria-hidden="true" />변경된 부분</span></>
}

function ChangeDistribution({ counts }) {
  const total = counts.reduce((sum, item) => sum + item.count, 0)
  return <section className="change-distribution" aria-label="변경 유형 분포">
    <div className="change-distribution-heading"><div><h2>변경 유형 분포</h2><small>현재 목록 기준</small></div><span>총 {total}건</span></div>
    <div className="change-distribution-track" role="img" aria-label={total ? `총 ${total}건의 변경 유형 분포` : '변경 기록이 없습니다.'}>{counts.map(item => <span key={item.type} className={`change-distribution-segment ${item.type.toLowerCase()}`} style={{ width: `${total ? (item.count / total) * 100 : 0}%` }} title={`${CHANGE_LABELS[item.type]} ${item.count}건`} />)}</div>
    <div className="change-distribution-legend">{counts.map(item => <div className="change-distribution-legend-item" key={item.type}><span className={`change-distribution-dot ${item.type.toLowerCase()}`} aria-hidden="true" /><span>{CHANGE_LABELS[item.type]}</span><b>{item.count}건</b></div>)}</div>
  </section>
}

export default function ChangeMonitoringPage() {
  const { records } = usePreviewChangeMonitoring()
  const [query, setQuery] = useState('')
  const [enabled, setEnabled] = useState({ MODIFIED: true, ADDED: true, REMOVED: true, HELD: true })
  const [selectedId, setSelectedId] = useState(() => records[0]?.id ?? null)
  const visible = useMemo(() => previewChangeMonitoringService.filterChanges(records, { query, types: enabled }), [enabled, query, records])
  const selected = visible.find(record => record.id === selectedId) ?? visible[0] ?? null
  const typeCounts = useMemo(() => CHANGE_TYPES.map(type => ({ type, count: records.filter(record => record.type === type).length })), [records])

  return <DemoLayout active="changes"><main className="change-service-page">
    <header className="change-service-heading"><div><h1>정책 변경 감시</h1></div></header>
    <section className="change-service-tools"><input value={query} onChange={event => setQuery(event.target.value)} placeholder="정책 문서 검색" aria-label="정책 문서 검색" /><div>{CHANGE_TYPES.map(kind => <button type="button" key={kind} className={enabled[kind] ? 'selected' : ''} onClick={() => setEnabled(current => ({ ...current, [kind]: !current[kind] }))}>{CHANGE_LABELS[kind]}</button>)}</div></section>
    <ChangeDistribution counts={typeCounts} />
    <section className="change-service-layout"><aside className="change-service-list"><h2>정책 변경 목록</h2>{visible.length ? visible.map(record => <button type="button" key={record.id} className={`change-service-item ${record.id === selected?.id ? 'selected' : ''}`} onClick={() => setSelectedId(record.id)}><div><strong>{record.document}</strong><span className={`change-type ${record.type.toLowerCase()}`}>{CHANGE_LABELS[record.type]}</span></div><p>{record.summary}</p><small>{record.area} · {record.detectedAt}</small>{typeof record.impactedAnswerCount === 'number' && <em>영향받는 답변 {record.impactedAnswerCount}건</em>}</button>) : <p className="change-service-empty">{records.length ? '검색 결과가 없습니다.' : '변경 기록이 없습니다.'}</p>}</aside>
      <article className="change-service-detail">{selected ? <><div className="change-detail-head"><div><span className={`change-type ${selected.type.toLowerCase()}`}>{CHANGE_LABELS[selected.type]}</span><h2>{selected.document}</h2><p>{selected.area} · 변경 감지 {selected.detectedAt}</p></div></div><section className="change-summary"><small>변경 내용 요약</small><p>{selected.summary}</p></section>{(selected.oldPolicy || selected.newPolicy) && <><h3>정책 변경 전후</h3><div className={`change-policy-grid ${!selected.oldPolicy || !selected.newPolicy ? 'single' : ''}`}>{selected.oldPolicy && <section className={selected.type === 'REMOVED' ? 'highlight' : ''}><small>변경 전</small><p><Marked text={selected.oldPolicy} mark={selected.type === 'REMOVED' ? selected.changedText : null} /></p></section>}{selected.newPolicy && <section className={selected.type === 'ADDED' || selected.type === 'MODIFIED' ? 'highlight' : ''}><small>변경 후</small><p><Marked text={selected.newPolicy} mark={selected.type === 'ADDED' || selected.type === 'MODIFIED' ? selected.changedText : null} /></p></section>}</div></>}{typeof selected.impactedAnswerCount === 'number' && <section className="change-impact"><small>관련 답변 영향</small><p>이 변경은 기존 답변 {selected.impactedAnswerCount}건과 관련되어 있습니다.</p></section>}<div className="change-detail-actions">{selected.sourceUrl && <a href={selected.sourceUrl} target="_blank" rel="noreferrer" className="demo-outline-button">원문 보기</a>}{selected.recallTo && <Link to={selected.recallTo} className="demo-dark-button">관련 리콜 알림 보기</Link>}</div></> : <div className="change-empty-detail"><h2>변경 기록을 선택하세요.</h2><p>선택한 정책 문서의 변경 내용을 확인할 수 있습니다.</p></div>}</article>
    </section>
  </main></DemoLayout>
}
