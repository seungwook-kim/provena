import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// jsdom cannot lay out pages, so these guard the CSS rules that fixed real breakage seen in
// headless Chrome captures (1280/768/390px). Each rule must come after the rule it overrides.
const css = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8').replace(/\r\n/g, '\n')
const after = (needle, earlier) => css.lastIndexOf(needle) > css.lastIndexOf(earlier)

describe('recall, change and approval layout rules', () => {
  it('stacks the recall list above the detail on narrow screens', () => {
    // `.recall-service-page .recall-service-layout{grid-template-columns:310px ...}` beats the
    // older one-class mobile rule, so the detail was squeezed to ~20px at 390px.
    expect(css).toMatch(/@media\(max-width:760px\)\{[^@]*\.recall-service-page \.recall-service-layout\{grid-template-columns:1fr\}/)
    expect(after('.recall-service-page .recall-service-layout{grid-template-columns:1fr}', '.recall-service-page .recall-service-layout{grid-template-columns:310px')).toBe(true)
  })

  it('keeps the unread dot round next to a long title', () => {
    expect(css).toContain('.recall-service-item i{flex:none}')
  })

  it('keeps judgement badges inline inside a list item', () => {
    expect(after('.recall-service-item .recall-item-badges>span{display:inline-flex', '.recall-service-item span,.recall-service-item small{display:block')).toBe(true)
  })

  it('wraps long URLs inside the before/after policy boxes', () => {
    expect(css).toContain('.recall-policy-grid p,.change-policy-grid p,.recall-answer p,.change-summary p{overflow-wrap:anywhere}')
  })

  it('lets approval tables scroll sideways instead of breaking every Korean letter', () => {
    expect(after('.approval-table{min-width:560px}', '.approval-table{width:100%')).toBe(true)
    // Without this the 1fr grid column grows to the table width and the detail is clipped instead of the table scrolling.
    expect(css).toContain('.approval-service-layout>aside,.approval-service-layout>article{min-width:0}')
  })
})
