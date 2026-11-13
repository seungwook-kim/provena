import { useState } from 'react'

// 관리자 전용(승인함 라우트가 관리자만 연다): 핸드북 권한표의 한 업무 종류를 결정표 초안으로 바꿔 승인함에 올린다.
// 키가 있으면 LLM을 부르므로 확인창을 거친다. 키 없는 데모는 status=example 고정 응답이라 저장·승인함 등록이 없다(README L-23).
export default function DecisionConvertPanel({ service, onConverted }) {
  const [category, setCategory] = useState('')
  const [pending, setPending] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  function ask(event) {
    event.preventDefault()
    if (busy) return
    const name = category.trim()
    if (!name) { setError('권한표 업무 종류를 입력해 주세요. 예: Approving expense'); return }
    setError('')
    setPending(name)
  }

  async function run() {
    if (busy || !pending) return
    const name = pending
    setPending('')
    setBusy(true)
    setResult(null)
    setError('')
    try {
      const converted = await service.convertDecisionTable(name)
      setResult(converted)
      if (!converted.example) {
        setCategory('')
        await onConverted?.()
      }
    } catch (convertError) {
      setError(convertError?.message || '결정표 변환을 처리하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return <section className="convert-panel" aria-labelledby="convert-title">
    <div className="convert-heading"><h2 id="convert-title">결정표 변환</h2><span>관리자 전용</span></div>
    <p className="convert-lede">핸드북 권한표의 업무 종류 하나를 결정표 초안으로 바꿔 아래 승인함에 올립니다.</p>
    <form className="convert-form" onSubmit={ask}>
      <label>권한표 업무 종류<input type="text" value={category} onChange={event => setCategory(event.target.value)} placeholder="예: Approving expense" maxLength={200} disabled={busy} /></label>
      <button type="submit" disabled={busy}>{busy ? '변환 중입니다.' : '결정표로 변환'}</button>
    </form>
    {error && <p role="alert" className="convert-error">{error}</p>}
    {result && (result.example
      ? <div className="approval-mismatch convert-result" role="status">
        <strong>예시 응답(키 없는 데모, 저장되지 않음)</strong>
        <p>{result.title}</p>
        <p>승인함에 올라가지 않았고 쓸 수 있는 결정표도 아닙니다. 권한표 칸에서 코드로 만든 기준 규칙입니다. LLM 키를 넣고 데모 모드를 끄면 실제 초안이 승인함에 올라갑니다.</p>
        <ExampleDraft draft={result.draft} />
      </div>
      : <p role="status" className="convert-result">결정표 초안을 승인함에 올렸습니다: {result.title}</p>)}
    {pending && <div className="approval-dialog" role="dialog" aria-modal="true" aria-labelledby="convert-dialog-title">
      <section>
        <h2 id="convert-dialog-title">결정표로 변환하시겠습니까?</h2>
        <p>업무 종류: {pending}</p>
        <p>API 키가 있으면 LLM을 호출해 비용이 듭니다. 초안은 승인함에 올라가 승인 전까지 쓰이지 않습니다.</p>
        <div>
          <button type="button" onClick={() => setPending('')}>취소</button>
          <button type="button" onClick={run}>확인</button>
        </div>
      </section>
    </div>}
  </section>
}

function ExampleDraft({ draft }) {
  if (!draft.length) return <p>예시에 구간이 없습니다.</p>
  return <div className="approval-table-wrap"><table className="approval-table">
    <caption>예시 초안</caption>
    <thead><tr><th scope="col">구간</th><th scope="col">업무 승인</th><th scope="col">재무 승인</th><th scope="col">협조</th></tr></thead>
    <tbody>{draft.map((rule, index) => <tr key={`${rule.band}-${index}`}>
      <td>{rule.bandLabel}</td><td>{rule.approvers.join(', ') || '없음'}</td><td>{rule.financialApprovers.join(', ') || '없음'}</td><td>{rule.cooperating.join(', ') || '없음'}</td>
    </tr>)}</tbody>
  </table></div>
}
