import illustration from '../assets/auth-illustration-v2.png'

export default function AuthIllustration() {
  return <aside className="auth-illustration" aria-label="근거 문서와 정책 변경을 표현한 일러스트">
    <div className="auth-illustration-copy">
      <h2>오늘의 답이,<br />내일도 정확하도록.</h2>
    </div>
    <div className="auth-illustration-art">
      <img src={illustration} alt="겹쳐진 정책 문서와 근거 확인 및 정책 변경을 나타내는 입체 그래픽" />
    </div>
    <p className="illustration-caption">근거 확인 · 변경 감지 · 답변 재검토</p>
  </aside>
}
