function Card({ no, title, desc, children }) {
  return (
    <article className="ve-card">
      <header className="ve-card-h">
        <span className="ve-no">{no}</span>
        <h3>{title}</h3>
      </header>
      <p className="ve-card-p">{desc}</p>
      <div className="ve-mini">
        <div className="ve-mini-bar">
          <span className="ve-dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="ve-tag">예시</span>
        </div>
        <div className="ve-mini-body">{children}</div>
      </div>
    </article>
  )
}

export default function How() {
  return (
    <section id="how" className="ve-how">
      <div className="ve-wrap">
        <div className="ve-how-head">
          <span className="ve-eyebrow"><i aria-hidden="true">#</i> how</span>
          <h2>작동 방식</h2>
        </div>

        <div className="ve-cards">
          <Card no="01" title="근거 인용" desc="답마다 섹션과 판 날짜를 함께 붙입니다.">
            <p className="ve-q"><span className="ve-ps" aria-hidden="true">Q</span>제3자가 프로덕션 데이터에 접근하면 보안 검토가 필요한가요?</p>
            <p className="ve-ans">네. 접근 전에 보안 검토와 승인을 받아야 합니다.</p>
            <p className="ve-chip"><span aria-hidden="true">↳</span> <em>Security › Third-party risk</em> <em>· 2026-10판</em></p>
          </Card>

          <Card no="02" title="답변 리콜" desc="근거가 바뀌면 지난 답을 다시 판단합니다.">
            <p className="ve-diff-h">@@ Security › Third-party risk</p>
            <p className="ve-diff ve-del"><b aria-hidden="true">-</b><s>제3자 접근 전 보안 검토를 권장합니다.</s></p>
            <p className="ve-diff ve-add"><b aria-hidden="true">+</b>제3자 접근 전 보안 검토가 필요합니다.</p>
            <p className="ve-note"><span aria-hidden="true">↻</span> 인용 답변 3건 · 받은 사람에게 알림</p>
          </Card>

          <Card no="03" title="결정표 승인" desc="사람이 승인한 결정만 실행합니다.">
            <table className="ve-table">
              <thead>
                <tr><th scope="col">결정</th><th scope="col">상태</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>권한 변경 R-12</td>
                  <td><span className="ve-pill ve-old">검토 대기</span><span className="ve-arr" aria-hidden="true">→</span><span className="ve-pill ve-new">승인됨</span></td>
                </tr>
                <tr>
                  <td>권한 변경 R-13</td>
                  <td><span className="ve-pill ve-old">검토 대기</span></td>
                </tr>
              </tbody>
            </table>
            <p className="ve-note"><span aria-hidden="true">›</span> 승인됨만 실행</p>
          </Card>
        </div>
      </div>
    </section>
  )
}
