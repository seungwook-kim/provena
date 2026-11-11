import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DEMO_SUGGESTIONS } from './demo-suggestions'

// 강사 코멘트 11/11: 키 없는 데모 첫 화면 추천 질문 3개가 녹화에 없어 거절됐다.
// 키 없는 데모는 녹화한 질문(`data/demo_replay/questions.txt`)만 답하므로, 추천 질문은 그 목록과 글자가 같아야 한다.
const QUESTIONS = resolve(process.cwd(), '../../data/demo_replay/questions.txt')   // vitest는 web/react-app에서 실행한다
const norm = text => text.replace(/\s+/g, ' ').trim()

describe('keyless demo suggestions', () => {
  const recorded = readFileSync(QUESTIONS, 'utf8').split(/\r?\n/).filter(line => line.trim() && !line.trim().startsWith('#')).map(norm)

  it('offers three questions', () => {
    expect(DEMO_SUGGESTIONS).toHaveLength(3)
    expect(new Set(DEMO_SUGGESTIONS).size).toBe(3)
  })

  it('uses only questions that are in the recorded replay question list', () => {
    for (const question of DEMO_SUGGESTIONS) expect(recorded, question).toContain(norm(question))
  })

  it('offers only questions the keyless demo answers with citations (not the refusal examples)', () => {
    const text = readFileSync(QUESTIONS, 'utf8')
    const answered = text.slice(text.indexOf('# 키 없이 인용 답이 나오는 질문'), text.indexOf('# 키 없이 거절이 나오는 질문')).split(/\r?\n/).filter(line => line.trim() && !line.startsWith('#')).map(norm)
    for (const question of DEMO_SUGGESTIONS) expect(answered, question).toContain(norm(question))
  })
})
