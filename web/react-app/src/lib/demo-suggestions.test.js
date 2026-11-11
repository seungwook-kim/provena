import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { RECORDED_SUGGESTIONS } from './demo-suggestions'

// K-20: 첫 화면 추천 질문은 녹화에 있는 질문이어야 키 없는 데모에서 거절되지 않는다.
describe('RECORDED_SUGGESTIONS', () => {
  it('data/demo_replay/questions.txt 의 질문과 글자가 같다', () => {
    const text = readFileSync('../../data/demo_replay/questions.txt', 'utf-8') // vitest는 web/react-app에서 돈다
    const recorded = text.split('\n').map(line => line.trim()).filter(line => line && !line.startsWith('#'))
    expect(RECORDED_SUGGESTIONS).toHaveLength(3)
    for (const question of RECORDED_SUGGESTIONS) expect(recorded).toContain(question)
  })
})
