import { useEffect, useRef } from 'react'

/**
 * Shared loop for the code backgrounds.
 * createEngine({ w, h, dpr }) -> { draw(ctx, t, dt), staticT }
 * - 30fps cap, DPR-aware (max 2), resize aware (debounced)
 * - stops when tab hidden / offscreen, one static frame under prefers-reduced-motion
 */
export function useCanvasBg(createEngine, fps = 30) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const host = canvas.parentElement
    // Test environments (jsdom) lack canvas and these observers; skip the animation there.
    if (typeof window.matchMedia !== 'function' || typeof IntersectionObserver === 'undefined' || typeof ResizeObserver === 'undefined') return
    let ctx = null
    try { ctx = canvas.getContext('2d') } catch { ctx = null }
    if (!ctx) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')

    let engine = null
    let raf = 0
    let last = 0
    let t = 0.001
    let reduced = mq.matches
    let inView = true
    let pageVisible = !document.hidden
    let resizeTimer = 0
    const frameMs = 1000 / fps - 1

    const paintOnce = () => {
      if (!engine) return
      engine.draw(ctx, reduced ? engine.staticT : t, 0)
    }

    const build = () => {
      const r = host.getBoundingClientRect()
      const w = Math.max(1, Math.round(r.width))
      const h = Math.max(1, Math.round(r.height))
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      engine = createEngine({ w, h, dpr })
      paintOnce()
    }

    const tick = (now) => {
      raf = requestAnimationFrame(tick)
      if (now - last < frameMs) return
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      t += dt
      engine.draw(ctx, t, dt)
    }

    const sync = () => {
      const shouldRun = !reduced && inView && pageVisible
      if (shouldRun && !raf) {
        last = performance.now()
        raf = requestAnimationFrame(tick)
      } else if (!shouldRun && raf) {
        cancelAnimationFrame(raf)
        raf = 0
      }
      if (reduced) paintOnce()
    }

    build()
    sync()

    const ro = new ResizeObserver(() => {
      clearTimeout(resizeTimer)
      resizeTimer = setTimeout(build, 120)
    })
    ro.observe(host)

    const io = new IntersectionObserver(([e]) => {
      inView = e.isIntersecting
      sync()
    })
    io.observe(host)

    const onVis = () => {
      pageVisible = !document.hidden
      sync()
    }
    const onMotion = () => {
      reduced = mq.matches
      sync()
    }
    document.addEventListener('visibilitychange', onVis)
    mq.addEventListener('change', onMotion)

    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(resizeTimer)
      ro.disconnect()
      io.disconnect()
      document.removeEventListener('visibilitychange', onVis)
      mq.removeEventListener('change', onMotion)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return canvasRef
}
