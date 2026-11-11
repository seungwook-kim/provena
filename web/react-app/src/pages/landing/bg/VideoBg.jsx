import { useEffect, useRef, useState } from 'react'
import ConsoleBg from './ConsoleBg.jsx'
import { THEMES } from './themes.js'
import './bg.css'

const CODE_BG = { e: ConsoleBg }

/** The code-made background alone (no video, no overlay). Parent must be positioned. */
export function CodeBg({ theme = 'd' }) {
  const Bg = CODE_BG[theme] || ConsoleBg
  return <Bg />
}

const canMatch = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () => canMatch() && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    if (!canMatch()) return undefined
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

/**
 * Full-bleed background layer.
 *   <VideoBg theme="d" src="/videos/d.mp4" overlay={0.4} />
 * Parent should be `relative isolate`. Falls back to the matching code background when the
 * MP4 is missing / errors, and under prefers-reduced-motion.
 *
 * props
 *  theme       'd' | 'e' | 'f'
 *  src         mp4 url (default `/videos/${theme}.mp4`)
 *  poster      optional poster image
 *  overlay     0..1 strength of the theme-coloured readability veil (default: 0.5 over video, 0.2 over code bg)
 *  forceCode   true -> always show the code background (ignores the mp4)
 *  videoStyle  optional style object applied to the <video> (e.g. a CSS filter grade)
 */
export default function VideoBg({ theme = 'd', src, poster, overlay, forceCode = false, className = '', videoStyle }) {
  const t = THEMES[theme] || THEMES.d
  const url = src ?? `/videos/${theme}.mp4`
  const reduced = useReducedMotion()
  const videoRef = useRef(null)
  const rootRef = useRef(null)
  const [available, setAvailable] = useState(true)
  const [ready, setReady] = useState(false) // video can play
  const [codeOn, setCodeOn] = useState(true)

  // The hero video ships in public/, so assume it exists; a load error falls back to the code background.
  const useVideo = available && !forceCode && !reduced

  // Derived during render: without a usable video the code background always shows.
  const videoReady = useVideo && ready
  const showCode = !useVideo || codeOn

  // Drop the canvas loop once the video fully covers it.
  useEffect(() => {
    if (!videoReady) return undefined
    const id = setTimeout(() => setCodeOn(false), 1000)
    return () => clearTimeout(id)
  }, [videoReady])

  // Pause when the tab is hidden or the layer is offscreen.
  useEffect(() => {
    const v = videoRef.current
    const root = rootRef.current
    if (!v || !root || !useVideo || typeof IntersectionObserver === 'undefined') return
    let inView = true
    const sync = () => {
      if (!document.hidden && inView) v.play().catch(() => {})
      else v.pause()
    }
    const io = new IntersectionObserver(([e]) => {
      inView = e.isIntersecting
      sync()
    })
    io.observe(root)
    document.addEventListener('visibilitychange', sync)
    return () => {
      io.disconnect()
      document.removeEventListener('visibilitychange', sync)
      v.pause()
    }
  }, [useVideo])

  const strength = overlay ?? (videoReady ? 0.5 : theme === 'e' ? 0.4 : 0.2)

  return (
    <div ref={rootRef} className={`bgx-root ${className}`} aria-hidden="true" data-bg-theme={theme} data-bg-source={videoReady ? 'video' : 'code'}>
      {showCode && <CodeBg theme={theme} />}
      {useVideo && (
        <video
          ref={videoRef}
          className="bgx-layer bgx-video"
          data-ready={ready}
          src={url}
          poster={poster}
          style={videoStyle}
          muted
          autoPlay
          loop
          playsInline
          preload="metadata"
          onCanPlay={() => setReady(true)}
          onError={() => setAvailable(false)}
        />
      )}
      <div
        className="bgx-layer"
        style={{
          background: `radial-gradient(120% 90% at 50% 45%, rgba(${t.rgb},${strength * 0.8}) 0%, rgba(${t.rgb},${Math.min(1, strength * 1.15)}) 100%)`,
        }}
      />
    </div>
  )
}
