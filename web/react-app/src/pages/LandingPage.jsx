import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo'

const prefersReducedMotion = () => typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const examples = {
  security: ['제3자 위험을 평가해야 하는 기준은?', '제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요합니다.', 'Security > Third-party risk', '2023-05'],
  approver: ['구매 승인에는 얼마나 시간이 걸리나요?', '승인 단계와 금액 구간에 따라 필요한 승인자를 권한표에서 확인합니다.', 'Finance > Procurement approvals', '2023-05'],
  itreview: ['IT 검토가 필요한 변경은 무엇인가요?', '서비스 안정성이나 보안에 영향을 주는 변경은 실행 전에 검토합니다.', 'Engineering > Change management', '2023-05'],
  vendor: ['공급사를 등록할 때 무엇을 확인하나요?', '공급사 정보와 위험 평가를 확인한 뒤 정해진 승인 절차를 따릅니다.', 'Security > Vendor management', '2023-05'],
}
const exampleTabTitles = {
  security: '제3자 위험 평가',
  approver: '구매 승인 절차',
  itreview: 'IT 검토 기준',
  vendor: '공급사 등록 절차',
}
const steps = [['01', '수집·정리', '공개 핸드북을 고정 커밋으로 받아 문서와 승인 권한표를 나눕니다.', '정책 문서 수집'], ['02', '검색', '한국어 질문을 검색하고 관련 근거의 순위를 다시 매깁니다.', '관련 근거 탐색'], ['03', '답변·근거 검증', '섹션과 판 날짜를 붙여 답하고 인용을 코드로 확인합니다.', '출처와 버전 확인'], ['04', '답변 리콜', '정책이 바뀌면 그 섹션을 인용한 과거 답을 다시 판정합니다.', '정책 변경 후 재검토']]
const featureCards = [
  ['01', '근거를 붙여 답합니다', '흩어진 정책에서 필요한 기준을 찾고, 답변에 섹션과 판 날짜를 붙입니다.', '질문', '외부 SaaS 도입을 검토하려면?', '근거 문서와 인용 위치를 함께 확인합니다.'],
  ['02', '정책이 바뀌면 리콜합니다', '정책 개정으로 결론이 달라질 수 있는 오래된 답변을 다시 확인합니다.', '변경 전후', '기존 답변 → 개정된 정책', '결론이 바뀐 답만 리콜 알림으로 연결합니다.'],
  ['03', '여러 팀이 함께 검토합니다', '보안·인프라·IT 운영·재무가 같은 근거를 기준으로 쟁점을 확인합니다.', '검토 팀', '보안 · 인프라 · IT 운영 · 재무', '팀별 검토 결과를 한 흐름에서 비교합니다.'],
  ['04', '결정표는 사람이 승인합니다', '권한표와 원문을 사람이 대조해 승인하기 전에는 결정을 실행하지 않습니다.', '승인 상태', '결정표 검토 대기', '사람의 확인과 승인 이력을 남깁니다.'],
]
const evidenceStats = [
  ['핸드북 페이지 수', 1565, 'GitLab Handbook'],
  ['수집 대상 절 수', 11, '공개 핸드북 기준'],
  ['검색 단위(청크) 수', 23095, '제목·표 행 단위'],
  ['승인 권한표 칸 수', 363, '2023-05판 기준'],
]
const evidenceProcess = [
  ['01', '수집', '공개 핸드북에서 정책 문서를 수집하고 출처를 확인합니다.'],
  ['02', '청킹', '문서를 검색하기 쉬운 단위로 나누고 출처와 버전 정보를 정리합니다.'],
  ['03', '검색', '질문과 관련된 정책 내용을 찾아 필요한 근거를 선택합니다.'],
  ['04', '답 또는 거절', '근거가 있으면 출처를 붙여 답하고, 없으면 답하지 않습니다.'],
]

function HeroEvidenceNetwork() {
  const canvasRef = useRef(null)

  useEffect(() => {
    if (import.meta.env.MODE === 'test') return undefined
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return undefined
    const reducedMotion = prefersReducedMotion()
    let frame = 0
    let width = 0
    let height = 0
    let particles = []

    function inCopyArea(x, y) {
      const sideInset = width < 560 ? 0.06 : 0.3
      return x > width * sideInset && x < width * (1 - sideInset) && y > height * 0.08 && y < height * 0.8
    }

    function resize() {
      const rect = canvas.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      width = rect.width
      height = rect.height
      canvas.width = width * ratio
      canvas.height = height * ratio
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      const count = width < 560 ? 50 : 108
      particles = []
      while (particles.length < count) {
        const x = Math.random() * width
        const y = Math.random() * height
        if (inCopyArea(x, y) && Math.random() < 0.78) continue
        const primary = Math.random() < 0.15
        particles.push({ x, y, vx: (Math.random() - 0.5) * 0.085, vy: (Math.random() - 0.5) * 0.085, radius: (primary ? 1.35 : 1.1) + Math.random() * 1.5, lavender: Math.random() > 0.58, phase: Math.random() * Math.PI * 2 })
      }
    }

    function draw(time) {
      context.clearRect(0, 0, width, height)
      particles.forEach((particle) => {
        if (!reducedMotion) {
          particle.x += particle.vx
          particle.y += particle.vy
          if (particle.x < 0 || particle.x > width) particle.vx *= -1
          if (particle.y < 0 || particle.y > height) particle.vy *= -1
        }
      })
      context.lineWidth = 1
      for (let index = 0; index < particles.length; index += 1) {
        for (let next = index + 1; next < particles.length; next += 1) {
          const a = particles[index]
          const b = particles[next]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const distance = Math.hypot(dx, dy)
          if (distance > 112) continue
          context.strokeStyle = a.lavender || b.lavender ? `rgba(169,154,213,${0.3 * (1 - distance / 112)})` : `rgba(133,169,206,${0.31 * (1 - distance / 112)})`
          context.beginPath()
          context.moveTo(a.x, a.y)
          context.lineTo(b.x, b.y)
          context.stroke()
        }
      }
      particles.forEach((particle) => {
        const pulse = reducedMotion ? 0.96 : 0.82 + Math.sin(time * 0.00065 + particle.phase) * 0.14
        context.beginPath()
        context.fillStyle = particle.lavender ? `rgba(169,154,213,${pulse})` : `rgba(133,169,206,${pulse})`
        context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2)
        context.fill()
      })
      if (!reducedMotion) frame = requestAnimationFrame(draw)
    }

    resize()
    window.addEventListener('resize', resize)
    draw(performance.now())
    return () => { cancelAnimationFrame(frame); window.removeEventListener('resize', resize) }
  }, [])

  return <canvas ref={canvasRef} className="landing-hero-network" aria-hidden="true" />
}

export default function LandingPage() {
  const [active, setActive] = useState('security')
  const [statsStarted, setStatsStarted] = useState(false)
  const item = examples[active]
  const stackRef = useRef(null)
  const statsRef = useRef(null)

  useEffect(() => {
    const section = stackRef.current
    if (!section) return undefined
    const cards = [...section.querySelectorAll('.landing-stack-card')]
    const reduce = prefersReducedMotion()
    let frame = 0
    const update = () => {
      frame = 0
      if (reduce) return
      cards.forEach((card, index) => {
        const next = cards[index + 1]
        if (!next) return
        const overlap = Math.min(Math.max((card.getBoundingClientRect().bottom - next.getBoundingClientRect().top) / card.offsetHeight, 0), 1)
        card.style.setProperty('--stack-scale', `${1 - overlap * 0.05}`)
        card.style.setProperty('--stack-background', `rgb(${Math.round(255 - overlap * 12)} ${Math.round(255 - overlap * 22)} ${Math.round(255 - overlap * 39)})`)
      })
    }
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update) }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => { window.removeEventListener('scroll', onScroll); window.removeEventListener('resize', onScroll); if (frame) cancelAnimationFrame(frame) }
  }, [])

  useEffect(() => {
    const section = statsRef.current
    if (!section) return undefined
    if (import.meta.env.MODE === 'test' || typeof IntersectionObserver === 'undefined' || prefersReducedMotion()) {
      setStatsStarted(true)
      return undefined
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setStatsStarted(true)
        observer.disconnect()
      }
    }, { threshold: 0.25 })
    observer.observe(section)
    return () => observer.disconnect()
  }, [])

  return <div className="landing-page">
    <nav className="pill-nav" aria-label="주요 메뉴"><Link to="/" className="nav-brand"><Logo /></Link><div className="nav-links"><a className="active" href="#top">소개</a><a href="#features">작동 방식</a><a href="#numbers">데이터</a></div><div className="nav-actions"><Link to="/login" className="nav-login">로그인</Link><Link to="/signup" className="nav-cta">회원가입</Link></div></nav>
    <main id="top">
      <section className="hero"><HeroEvidenceNetwork /><span className="eyebrow">GitLab 공개 핸드북 기반 · 답변 예시</span><h1>어제 맞았던 답이,<br />오늘도 맞을까요?</h1><p>정책은 계속 바뀌지만, 이전에 전달된 답변은 그대로 남아 있을 수 있습니다.</p>
        <div className="intro-closing"><h2>답변은 끝나도,<br />검증은 계속됩니다.</h2><p>Provena는 정책 문서를 근거로 답하고,<br />정책이 변경되면 이전 답변까지 다시 확인합니다.</p></div>
        <div className="intro-problems" aria-label="정책과 답변의 문제점"><article className="intro-problem-card"><code>01</code><h2>흩어진 정책</h2><p>최신 정책을 찾기 어렵습니다.</p></article><article className="intro-problem-card"><code>02</code><h2>불분명한 근거</h2><p>답변의 출처를 확인하기 어렵습니다.</p></article><article className="intro-problem-card"><code>03</code><h2>오래된 답변</h2><p>정책이 바뀌어도 예전 답이 남습니다.</p></article></div>
        <div className="example-card"><div className="window-bar"><span /><span /><span /><em>예시 화면</em></div><div className="tabs" role="tablist">{Object.entries(examples).map(([key, value]) => <button key={key} className={active === key ? 'selected' : ''} onClick={() => setActive(key)} role="tab">{exampleTabTitles[key]}</button>)}</div><div className="example-body"><div className="question"><span>›</span>{item[0]}<button type="button" onClick={() => navigator.clipboard?.writeText(item[0])}>복사</button></div><p className="answer">{item[1]}</p><figure><blockquote>“{item[1]}”</blockquote><figcaption>[1] {item[2]} <code>{item[3]}</code> CC BY-SA 4.0</figcaption></figure></div></div>
        <div className="landing-preview-alert" aria-label="예시 애니메이션"><span>정책 변경 감지 · 기존 답변 재검토</span></div>
        <div className="hero-actions"><Link to="/login" className="button button-dark">시작하기</Link><a href="#how" className="text-link">작동 방식 보기 →</a></div><small className="hero-foot">원문 CC BY-SA 4.0 · 키 없이 뜨는 데모 모드 · 사람 승인 전엔 실행하지 않음</small>
      </section>
      <section ref={stackRef} id="features" className="landing-stack-section section"><div className="section-inner"><p className="stack-kicker">기능</p><h2>답 하나에 네 겹의 확인</h2><p className="section-lede">근거 확인부터 사람의 승인까지, Provena의 네 가지 핵심 기능을 살펴보세요.</p><div className="landing-stack-list">{featureCards.map(([number, title, description, label, value, detail], index) => <article key={number} className="landing-stack-card" style={{ '--stack-index': index }}><div className="stack-card-copy"><code>{number} / 04</code><h3>{title}</h3><p>{description}</p></div><div className="stack-card-visual"><small>{label}</small><strong>{value}</strong><span>{detail}</span></div></article>)}</div></div></section>
      <section id="how" className="section section-tint"><div className="section-inner"><h2>질문 하나가 지나가는 길</h2><p className="section-lede">문서를 받는 순간부터, 정책이 바뀐 뒤 답을 고치는 순간까지.</p><div className="steps">{steps.map(([number, title, body, tags]) => <article key={number}><code>{number}</code><div className="step-icon">{number === '01' ? '▤' : number === '02' ? '⌕' : number === '03' ? '✓' : '↺'}</div><h3>{title}</h3><p>{body}</p><small>{tags}</small></article>)}</div><div className="callouts"><article><b>⊘ 근거로 쓰지 않는 것</b><p>비공개 주소로만 연결된 문서는 답의 근거로 쓰지 않습니다.</p></article><article className="ok"><b>중요한 결정은 사람이 승인합니다.</b><p>승인이 필요한 결정은 담당자가 원문과 근거를 검토한 후 최종 승인합니다.</p></article><article><b>◫ 답변과 근거를 기록합니다.</b><p>질문과 답변, 사용한 정책 문서의 버전을 함께 기록해 이후 정책 변경의 영향을 추적합니다.</p></article></div></div></section>
      <section ref={statsRef} id="numbers" className="section landing-numbers-section"><div className="section-inner"><h2>무엇을 근거로 답하나요?</h2><p className="section-lede">GitLab 공개 핸드북을 활용한 근거 기반 답변 방식을 소개합니다.</p><div className="landing-evidence-layout"><article className="landing-process-card"><h3>질문이 답이 되기까지</h3><ol>{evidenceProcess.map(([number, title, body]) => <li key={number}><code>{number}</code><div><strong>{title}</strong><p>{body}</p></div></li>)}</ol></article><div className="landing-stat-grid">{evidenceStats.slice(0, 3).map(([label, value, note]) => <CountUpCard key={label} label={label} value={value} note={note} started={statsStarted} />)}<article className="landing-number-card landing-rejection-card"><small>근거 없을 때</small><strong>답하지 않음</strong><span>지어낸 답 대신 거절</span></article></div></div><p className="landing-source-note">데이터 기준: GitLab 공개 핸드북 · 커밋 <code>129243bc</code></p></div></section>
      <section className="landing-final-cta" aria-labelledby="landing-final-cta-title"><div className="landing-final-cta-inner"><h2 id="landing-final-cta-title">더 신뢰할 수 있는 답변,<br />Provena에서 시작하세요.</h2><p>근거를 확인하고,<br />정책의 변화까지 놓치지 않도록.</p><div className="landing-final-cta-actions"><Link to="/login" className="button button-dark">시작하기</Link></div></div></section>
    </main><footer>Provena · 근거가 바뀌면 답부터 고칩니다.</footer>
  </div>
}

function CountUpCard({ label, value, note, started }) {
  const [display, setDisplay] = useState(value)

  useEffect(() => {
    if (!started || prefersReducedMotion()) {
      setDisplay(value)
      return undefined
    }
    let frame = 0
    const start = performance.now()
    const duration = 700
    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1)
      setDisplay(Math.round(value * progress))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [started, value])

  return <article className="landing-number-card"><small>{label}</small><strong>{display.toLocaleString('ko-KR')}</strong><span>{note}</span></article>
}
