import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import './ve.css'
import Terminal from './Terminal.jsx'
import How from './How.jsx'
import VideoBg from './bg/VideoBg.jsx'

const Logo = () => (
  <a className="ve-logo" href="#top" aria-label="Provena 처음으로">
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <rect x="0.5" y="0.5" width="25" height="25" rx="7" fill="#17181B" />
      <path d="M8 9.5l4 3.5-4 3.5" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="14" y="16" width="5" height="1.8" rx="0.9" fill="#2BD08F" />
    </svg>
    <span>Provena</span>
  </a>
)

function Nav() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  const close = () => setOpen(false)

  return (
    <header className="ve-nav">
      <div className="ve-wrap ve-nav-in">
        <Logo />
        <nav className="ve-nav-links" aria-label="주요">
          <a href="#top">소개</a>
          <a href="#how">작동 방식</a>
        </nav>
        <div className="ve-nav-cta">
          <Link className="ve-link" to="/login">로그인</Link>
          <Link className="ve-btn ve-btn-ink ve-btn-sm" to="/signup">회원가입</Link>
        </div>
        <button
          type="button"
          className={`ve-burger ${open ? 'open' : ''}`}
          aria-label={open ? '메뉴 닫기' : '메뉴 열기'}
          aria-expanded={open}
          aria-controls="ve-menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span /><span />
        </button>
      </div>
      {/* Render the mobile sheet only while open, so its links are not focusable or announced when hidden. */}
      {open && (
        <div id="ve-menu" className="ve-menu open">
          <a href="#top" onClick={close}>소개</a>
          <a href="#how" onClick={close}>작동 방식</a>
          <Link to="/login" onClick={close}>로그인</Link>
          <Link className="ve-btn ve-btn-ink" to="/signup" onClick={close}>회원가입</Link>
        </div>
      )}
    </header>
  )
}

const stats = [
  { k: 'pages', v: '1,565', c: '쪽 · 공개 핸드북' },
  { k: 'chunks', v: '23,095', c: '개 · 검색 단위' },
  { k: 'authority cells', v: '363', c: '칸 · 승인 권한표' },
  { k: 'execute', v: '승인 후', c: '사람이 승인한 결정만 실행', kr: true },
]

export default function Landing() {
  return (
    <div className="ve" id="top">
      <Nav />
      <main>
        <section className="ve-hero">
          <VideoBg theme="e" src="/landing/hero.mp4" poster="/landing/hero.jpg" overlay={0.66} videoStyle={{ filter: 'grayscale(0.55) contrast(1.02) brightness(1.04)' }} />
          <div className="ve-wrap">
            <div className="ve-hero-grid">
              <div className="ve-copy">
                <p className="ve-eyebrow"><span className="ve-dot" aria-hidden="true" />ask · recall · approve</p>
                <h1>어제 맞았던 답이,<br />오늘도 맞을까요?</h1>
                <p className="ve-lede">
                  <span>섹션과 판 날짜를 인용해 답하고, 근거가 바뀌면 다시 판단합니다.</span>
                  <span>사람이 승인한 결정만 실행합니다.</span>
                </p>
                <div className="ve-ctas">
                  <Link className="ve-btn ve-btn-ink" to="/login">시작하기</Link>
                  <a className="ve-btn ve-btn-ghost" href="#how">작동 방식 보기 <span aria-hidden="true">↓</span></a>
                </div>
              </div>
              <Terminal />
            </div>

            <ul className="ve-stats" aria-label="핵심 수치">
              {stats.map((s) => (
                <li key={s.k} className="ve-stat">
                  <span className="ve-stat-k"><i aria-hidden="true" />{s.k}</span>
                  <span className={`ve-stat-v ${s.kr ? 'kr' : ''}`}>{s.v}</span>
                  <span className="ve-stat-c">{s.c}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <How />

        <section className="ve-close">
          <div className="ve-wrap">
            <div className="ve-close-card">
              <div>
                <p className="ve-close-cmd"><span aria-hidden="true">$</span> provena start</p>
                <h2>근거가 바뀌면<br />답부터 고칩니다.</h2>
              </div>
              <Link className="ve-btn ve-btn-green" to="/login">시작하기 <span aria-hidden="true">→</span></Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="ve-foot">
        <div className="ve-wrap">
          <p>Provena · 원문 GitLab Handbook (CC BY-SA 4.0) · 커밋 <span>129243bc</span></p>
        </div>
      </footer>
    </div>
  )
}
