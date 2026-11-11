import { useCanvasBg } from './useCanvasBg.js'
import { THEMES, makeCanvas, mulberry32 } from './themes.js'
import './bg.css'

const T = THEMES.e

// Three depth layers: far = small/slow/sharp-ish, near = big/fast/soft.
const LAYERS = [
  { rowH: 18, barH: 5, speed: 5, alpha: 0.034, blur: 0.8 },
  { rowH: 28, barH: 8, speed: 11, alpha: 0.04, blur: 0.6 },
  { rowH: 42, barH: 12, speed: 21, alpha: 0.04, blur: 2.4 },
]

function rr(g, x, y, w, h) {
  const r = h / 2
  g.beginPath()
  g.moveTo(x + r, y)
  g.arcTo(x + w, y, x + w, y + h, r)
  g.arcTo(x + w, y + h, x, y + h, r)
  g.arcTo(x, y + h, x, y, r)
  g.arcTo(x, y, x + w, y, r)
  g.closePath()
}

function buildLayer(cfg, w, h, rnd) {
  const { rowH, barH } = cfg
  const nRows = Math.ceil(h / rowH) + 3
  const period = nRows * rowH
  const c = makeCanvas(w, period)
  const g = c.getContext('2d')
  if (cfg.blur) g.filter = `blur(${cfg.blur}px)`
  g.fillStyle = T.ink
  g.globalAlpha = cfg.alpha
  const rows = []
  const left = 24 + rnd() * 40
  for (let i = 0; i < nRows; i++) {
    const row = { segs: [] }
    rows.push(row)
    const r = rnd()
    if (r < 0.13) continue // blank line between paragraphs
    const heading = r > 0.93
    const indent = heading ? 0 : Math.floor(rnd() * 3) * barH * 2.4
    let x = left + indent
    const limit = w * (0.3 + rnd() * 0.62)
    const unit = barH * (heading ? 1.4 : 1)
    let first = true
    while (x < limit) {
      const wd = (first && heading ? 10 + rnd() * 8 : 2.5 + rnd() * 9) * unit
      const bh = heading && first ? barH * 1.5 : barH
      const y = i * rowH + rowH / 2 - bh / 2
      rr(g, x, y, wd, bh)
      g.fill()
      row.segs.push({ x, w: wd })
      x += wd + barH * (0.8 + rnd() * 0.5)
      first = false
    }
  }
  return { canvas: c, rows, period, cfg }
}

function createConsole({ w, h }) {
  const rnd = mulberry32(2203)
  const layers = LAYERS.map((cfg) => buildLayer(cfg, w, h, rnd))

  // top / bottom edge fade, pre-rendered
  const fade = makeCanvas(w, h)
  const f = fade.getContext('2d')
  const fh = h * 0.24
  const gt = f.createLinearGradient(0, 0, 0, fh)
  gt.addColorStop(0, T.ground)
  gt.addColorStop(1, 'rgba(247,247,245,0)')
  f.fillStyle = gt
  f.fillRect(0, 0, w, fh)
  const gb = f.createLinearGradient(0, h - fh, 0, h)
  gb.addColorStop(0, 'rgba(247,247,245,0)')
  gb.addColorStop(1, T.ground)
  f.fillStyle = gb
  f.fillRect(0, h - fh, w, fh)

  let hl = null
  let nextHl = 1.6
  const HL_DUR = 3

  const screenY = (L, row, t) => {
    const off = (L.cfg.speed * t) % L.period
    const y = row * L.cfg.rowH + L.cfg.rowH / 2 - off
    return ((y % L.period) + L.period) % L.period
  }

  function pickHighlight(t) {
    for (let tries = 0; tries < 40; tries++) {
      const li = rnd() < 0.4 ? 0 : 1
      const L = layers[li]
      const row = Math.floor(rnd() * L.rows.length)
      const segs = L.rows[row].segs
      const sy = screenY(L, row, t + HL_DUR * 0.5)
      if (segs.length < 3 || sy < h * 0.28 || sy > h * 0.72) continue
      const n = Math.min(segs.length, 2 + Math.floor(rnd() * 4))
      const i0 = Math.floor(rnd() * Math.max(1, segs.length - n + 1))
      return { li, row, i0, n, t0: t }
    }
    return null
  }

  return {
    staticT: 9,
    draw(ctx, t) {
      ctx.fillStyle = T.ground
      ctx.fillRect(0, 0, w, h)

      if (!hl && t >= nextHl) {
        hl = pickHighlight(t)
        if (!hl) nextHl = t + 0.5
      }

      for (let li = 0; li < layers.length; li++) {
        const L = layers[li]
        const off = (L.cfg.speed * t) % L.period
        ctx.drawImage(L.canvas, 0, -off, w, L.period)
        ctx.drawImage(L.canvas, 0, L.period - off, w, L.period)

        if (hl && hl.li === li) {
          const p = (t - hl.t0) / HL_DUR
          if (p >= 1) {
            hl = null
            nextHl = t + 2.4 + rnd() * 2
          } else {
            const env = Math.sin(Math.PI * Math.min(1, p * 1.05)) // 0 -> 1 -> 0
            const grow = Math.min(1, p / 0.28)
            const eased = 1 - Math.pow(1 - grow, 3)
            const segs = L.rows[hl.row].segs
            const a = segs[hl.i0]
            const z = segs[hl.i0 + hl.n - 1]
            const sy = screenY(L, hl.row, t)
            const bh = L.cfg.barH
            const x0 = a.x
            const x1 = a.x + (z.x + z.w - a.x) * eased
            ctx.save()
            ctx.fillStyle = T.accent
            // matched words tint
            ctx.globalAlpha = 0.3 * env
            for (let k = hl.i0; k < hl.i0 + hl.n; k++) {
              const s = segs[k]
              if (s.x > x1) break
              rr(ctx, s.x, sy - bh / 2, Math.min(s.w, x1 - s.x), bh)
              ctx.fill()
            }
            // citation underline
            ctx.globalAlpha = 0.8 * env
            ctx.fillRect(x0, sy + bh / 2 + 3, x1 - x0, 2)
            ctx.restore()
          }
        }
      }

      ctx.drawImage(fade, 0, 0, w, h)
    },
  }
}

export default function ConsoleBg() {
  const ref = useCanvasBg(createConsole)
  return (
    <div className="bgx-layer" aria-hidden="true">
      <canvas ref={ref} className="bgx-layer bgx-canvas" />
      <div className="bgx-grain bgx-grain-e" />
    </div>
  )
}
