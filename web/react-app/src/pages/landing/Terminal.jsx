// Hero terminal. All text is in the DOM; the reveal is CSS clip only.
const T = ({ n, d, t, children }) => (
  <span className="ve-ln" style={{ '--n': n, '--d': `${d}s`, '--t': `${t}s` }}>
    <span className="ve-ty">{children}</span>
  </span>
)

const Out = ({ d, className = '', children }) => (
  <div className={`ve-out ${className}`} style={{ '--d': `${d}s` }}>{children}</div>
)

export default function Terminal() {
  return (
    <figure className="ve-term" aria-label="Provena 명령줄 사용 예시">
      <div className="ve-term-bar">
        <span className="ve-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="ve-term-title">provena · handbook</span>
        <span className="ve-tag">예시</span>
      </div>

      <div className="ve-term-body">
        <div className="ve-row">
          <span className="ve-ps" aria-hidden="true">$</span>
          <T n={15} d={0.6} t={0.6}>
            <b className="ve-cmd">provena</b> ask <span className="ve-flag">\</span>
          </T>
        </div>
        <div className="ve-row ve-row-cont">
          <span className="ve-ps" aria-hidden="true" />
          <T n={38} d={1.3} t={1.7}>
            <span className="ve-str">"제3자가 프로덕션 데이터에 접근하면 보안 검토가 필요한가요?"</span>
          </T>
        </div>

        <Out d={3.2} className="ve-status">
          <span className="ve-ok" aria-hidden="true" />답변 · 근거 1건
        </Out>
        <Out d={3.6} className="ve-answer">
          네. 제3자가 접근하기 전에 보안 검토와 승인을 받아야 합니다.
          <sup className="ve-mark">[1]</sup>
        </Out>
        <Out d={4.1} className="ve-cite-row">
          <span className="ve-arrow" aria-hidden="true">↳</span>
          <span className="ve-cite" tabIndex={0}>
            Security › Third-party risk
            <span className="ve-tip" role="tooltip">
              <span className="ve-tip-k">근거 [1]</span>
              <span className="ve-tip-v">Security › Third-party risk</span>
              <span className="ve-tip-m">판 2026-10 · commit 129243bc</span>
            </span>
          </span>
          <span className="ve-meta"> · 2026-10판 · commit 129243bc</span>
        </Out>

        <div className="ve-row ve-gap ve-wipe" style={{ '--d': '4.9s' }}>
          <span className="ve-ps" aria-hidden="true">$</span>
          <T n={31} d={5.0} t={1.4}>
            <b className="ve-cmd">provena</b> recall <span className="ve-flag">--since</span> 2023-05
          </T>
        </div>
        <Out d={6.6} className="ve-recall">
          <span className="ve-spin" aria-hidden="true">↻</span>
          인용 답변 <b>3건</b> 재판정 · 받은 사람에게 알림
        </Out>

        <Out d={7.2} className="ve-row ve-last">
          <span className="ve-ps" aria-hidden="true">$</span>
          <span className="ve-caret-end" aria-hidden="true" />
        </Out>
      </div>

      <div className="ve-term-foot" aria-hidden="true">
        <span>main</span>
        <span>index 2026-10</span>
        <span>commit 129243bc</span>
      </div>
    </figure>
  )
}
