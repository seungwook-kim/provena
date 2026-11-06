import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { previewRecallService } from '../lib/recall-service'
import { usePreviewRecalls } from '../lib/use-preview-recalls'

function Marked({ text, mark }) {
  if (!mark || !text.includes(mark)) return text
  const [before, after] = text.split(mark)
  return <>{before}<mark>{mark}</mark>{after}<span className="changed-text-legend"><i aria-hidden="true" />변경된 부분</span></>
}

export default function RecallPage() {
  const { records, unread } = usePreviewRecalls()
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState(() => records[0]?.id ?? null)
  const visible = useMemo(() => previewRecallService.filterRecalls(records, filter), [filter, records])
  const selected = records.find(record => record.id === selectedId) ?? visible[0] ?? null

  function acknowledge(id) {
    void previewRecallService.acknowledgeRecall(id)
  }

  return <DemoLayout active="recalls"><main className="recall-service-page">
    <header className="recall-service-heading"><div><h1>리콜 알림</h1></div><span className="recall-unread">미확인 {unread}건</span></header>
    <div className="recall-filter-row" role="group" aria-label="리콜 알림 필터">{[['all', '전체'], ['unread', '미확인'], ['changed', '결론 변경']].map(([key, label]) => <button type="button" key={key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div>
    <section className="recall-service-layout"><aside className="recall-service-list"><h2>알림 목록</h2>{visible.length === 0 ? <p className="recall-empty">해당하는 알림이 없습니다.</p> : visible.map(record => <button type="button" key={record.id} className={`recall-service-item ${record.id === selected?.id ? 'selected' : ''}`} onClick={() => setSelectedId(record.id)}><div><strong>{record.title}</strong>{!record.acked && <i aria-label="미확인" />}</div><span>{record.question}</span><small>{record.document} · {record.detectedAt}</small><em className={record.conclusionChanged ? 'changed' : ''}>{record.conclusionChanged ? '결론 변경' : record.acked ? '확인 완료' : '확인 필요'}</em></button>)}</aside>
      <article className="recall-service-detail">{selected ? <><div className="recall-detail-top"><div><span className={`recall-result ${selected.conclusionChanged ? 'changed' : ''}`}>{selected.conclusionChanged ? '결론 변경' : '결론 유지'}</span><h2>{selected.title}</h2><p>{selected.document} · 변경 감지 {selected.detectedAt}</p></div><button type="button" className="demo-outline-button" disabled={selected.acked} onClick={() => acknowledge(selected.id)}>{selected.acked ? '확인 완료' : '확인'}</button></div>
        <section className="recall-answer"><small>영향받은 답변</small><p>{selected.oldAnswer}</p></section>
        <h3>정책 변경 전후</h3><div className="recall-policy-grid"><section><small>변경 전</small><p>{selected.oldPolicy}</p></section><section className="after"><small>변경 후</small><p><Marked text={selected.newPolicy} mark={selected.changedText} /></p></section></div>
        <div className="recall-detail-actions"><a href={selected.sourceUrl} target="_blank" rel="noreferrer" className="demo-outline-button">원문 보기</a><Link to={{ pathname: '/chat', search: '?demo=1' }} state={{ question: selected.question }} className="demo-dark-button">다시 질문하기</Link></div>
      </> : <div className="recall-empty-detail"><h2>아직 알림이 없습니다.</h2><p>정책 변경으로 다시 확인이 필요한 답변이 생기면 알려드립니다.</p></div>}</article></section>
  </main></DemoLayout>
}
