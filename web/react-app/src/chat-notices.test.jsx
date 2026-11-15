import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'

// 문구가 바뀌면 시험도 실패하도록 코드의 상수를 가져오지 않고 문장을 그대로 적는다(검증 지적 11/12)
const MODIFIED_LABEL = '원문을 요약·재서술함(수정됨)'
const PROGRESS_TEXT = '근거를 찾고 답을 확인하는 중입니다'
const APPROVAL_WAITING_TEXT = '담당자 승인을 기다리고 있습니다. 승인 단계가 끝나면 결과가 이 대화에 붙습니다. 이 화면으로 다시 돌아오거나 새로고침하면 보입니다. 다른 질문은 새 대화에서 해 주세요.'

configure({ asyncUtilTimeout: 5000 })
vi.setConfig({ testTimeout: 15000 })

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const user = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const listed = { thread_id: 't1', title: '연차 질문', status: 'idle', updated_at: '2026-11-09T01:00:00Z' }
const sse = events => events.map(event => `event: ${event.type}\ndata: ${JSON.stringify({ thread_id: 't1', ...event })}\n\n`).join('')
// backend/api/routes.py ATTRIBUTION 과 같은 모양
const ATTRIBUTION = { source: 'GitLab Handbook', license: 'CC BY-SA 4.0', license_url: 'https://creativecommons.org/licenses/by-sa/4.0/', modified: true, notice: 'GitLab 핸드북 기반 데모입니다.' }

// 앞 대화(t1)를 연 뒤 질문을 보낸다. chat 은 /chat 응답을 만드는 함수
async function askInThread(chat, threadMessages = [{ role: 'user', text: '앞 질문' }, { role: 'assistant', text: '앞 답', state: 'done' }]) {
  window.history.replaceState({}, '', '/chat')
  document.cookie = 'provena_csrf=test-token'
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    if (path === '/me') return json(user)
    if (path === '/threads') return json([listed])
    if (path === '/threads/t1') return json({ ...listed, messages: threadMessages })
    if (path === '/auth/csrf') return new Response(null, { status: 204 })
    if (path === '/chat') return chat(options)
    return json({ detail: 'not found' }, 404)
  }))
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
  await screen.findByText(threadMessages.at(-1).text || threadMessages[0].text)
  const box = screen.getByRole('textbox', { name: '질문' })
  fireEvent.change(box, { target: { value: '다음 질문' } })
  const send = screen.getByRole('button', { name: '보내기' })
  await waitFor(() => expect(send.disabled).toBe(false))
  fireEvent.click(send)
}

describe('출처·라이선스 수정 여부 (④)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('서버가 modified=true 를 주면 수정됨 표시를 그린다', async () => {
    await askInThread(() => new Response(sse([
      { type: 'token', data: { text: '답입니다.' } },
      { type: 'done', data: { kind: 'answer', attribution: ATTRIBUTION } },
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText('라이선스 보기')).toBeTruthy()
    expect(screen.getByText(MODIFIED_LABEL)).toBeTruthy()
  })

  it('modified 가 없으면 그리지 않는다', async () => {
    await askInThread(() => new Response(sse([
      { type: 'token', data: { text: '답입니다.' } },
      { type: 'done', data: { kind: 'answer', attribution: { ...ATTRIBUTION, modified: false } } },
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText('라이선스 보기')).toBeTruthy()
    expect(screen.queryByText(MODIFIED_LABEL)).toBeNull()
  })
})

describe('답 기다리는 동안 지난 시간 (⑤)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('생성 중 말풍선이 지난 초를 센다', async () => {
    await askInThread(options => new Response(new ReadableStream({ start(controller) { options.signal?.addEventListener('abort', () => controller.close()) } }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText(`${PROGRESS_TEXT}.`, { selector: '.demo-answer-progress' })).toBeTruthy()
    // 타이머는 말풍선이 그려질 때 걸리므로 진짜 시계로 2초 남짓 기다린다
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)) })
    expect(screen.getByText(new RegExp(`^${PROGRESS_TEXT} · [12]초 지남$`))).toBeTruthy()
  })
})

describe('승인 대기 안내 (⑥)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('승인 대기 말풍선에 다음 행동까지 적힌 고정 문구를 보여 준다', async () => {
    await askInThread(() => new Response(sse([
      { type: 'approval_request', data: { approval_id: 'iss-1', kind: 'issue_table', summary: '쟁점표' } },
    ]), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    expect(await screen.findByText(APPROVAL_WAITING_TEXT)).toBeTruthy()
    expect(screen.queryByText('승인 대기 중')).toBeNull()
  })
})

// 체크포인트 D11: 실패 경로(비용 상한, 검색 결과 없음, 응답 끊김)마다 사용자가 할 일이 화면에 보여야 한다. 문장은 코드 상수를 가져오지 않고 그대로 적는다
describe('실패 경로 안내 (D11)', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })
  const stream = events => () => new Response(sse(events), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })

  it('비용 상한 오류는 서버 문구와 다시 시도 버튼을 보인다', async () => {
    const MSG = '이번 질문의 LLM 비용 상한에 닿아 답을 멈췄습니다. 질문을 더 짧고 구체적으로 줄이거나 여러 개로 나누어 다시 물어봐 주세요.'
    await askInThread(stream([{ type: 'error', data: { code: 'limit_exceeded', message: MSG } }]))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(MSG)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
  })

  // 제공자 한도·잔액 부족(provider_limit)과 시간 초과(timeout)는 backend/api/routes.py의 MSG_PROVIDER_LIMIT, MSG_TIMEOUT 문장이다
  it.each([
    ['provider_limit', 'LLM 제공자의 요청 한도에 닿았거나 사용 잔액이 부족해 답을 만들지 못했습니다. 1~2분 뒤 다시 시도해 주세요. 같은 안내가 계속되면 관리자에게 LLM 키의 잔액과 사용 한도 확인을 요청해 주세요.'],
    ['timeout', '답을 만드는 시간이 제한을 넘어 중단했습니다. 질문을 더 짧게 줄이거나 여러 개로 나누어 잠시 뒤 다시 물어봐 주세요.'],
  ])('%s 오류는 서버 문구와 다시 시도 버튼을 보인다', async (code, MSG) => {
    await askInThread(stream([{ type: 'error', data: { code, message: MSG, request_id: 'r1' } }]))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(MSG)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
  })

  it.each([
    ['provider_limit', '관리자에게 LLM 키의 잔액과 사용 한도 확인을 요청해 주세요.'],
    ['timeout', '질문을 더 짧게 줄이거나 여러 개로 나누어 잠시 뒤 다시 물어봐 주세요.'],
  ])('%s 오류에 안내 문구가 빠져 와도 코드별 기본 안내와 다시 시도 버튼을 보인다', async (code, part) => {
    await askInThread(stream([{ type: 'error', data: { code } }]))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(part)
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
  })

  it('검색 결과가 없어 답하지 않으면 근거 부족 표시와 다음 행동을 보인다', async () => {
    await askInThread(stream([{ type: 'done', data: { kind: 'refuse', code: 'no_results', refuse_stage: 'give_up', refuse_reason: 'no_evidence', message: '핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.' } }]))
    expect(await screen.findByText('핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.')).toBeTruthy()
    expect(screen.getByText('근거 부족')).toBeTruthy()
    expect(screen.getByText('질문을 더 구체적으로 쓰거나 다른 표현으로 다시 물어봐 주세요.')).toBeTruthy()
  })

  // 놓친 것 H-34: 안내는 거절 사유가 "근거를 못 찾음"일 때만 붙는다. 서버는 token으로 문장을, done으로 사유 코드(refuse_reason)를 보낸다(backend/graph/stream.py)
  const HINT = '질문을 더 구체적으로 쓰거나 다른 표현으로 다시 물어봐 주세요.'
  const refusal = (text, reason) => stream([{ type: 'token', data: { text } }, { type: 'done', data: { kind: 'refuse', code: 'no_results', refuse_stage: 'x', ...(reason ? { refuse_reason: reason } : {}) } }])

  it.each([
    ['unsupported', '검색된 근거가 답의 주장을 받쳐 주지 못해 답하지 않습니다.'],
    ['citation_check', '답에 쓸 근거 인용을 확인하지 못해 답하지 않습니다.'],
  ])('근거가 모자란 거절(%s)에는 다시 물어보라는 안내를 붙인다', async (reason, text) => {
    await askInThread(refusal(text, reason))
    expect(await screen.findByText(text)).toBeTruthy()
    expect(screen.getByText(HINT)).toBeTruthy()
  })

  it.each([
    ['out_of_domain', '핸드북과 관련 없는 질문이라 답하지 않습니다.'],
    ['out_of_period', '질문이 묻는 기간이나 시점의 판이 수집된 핸드북에 없어 답하지 않습니다.'],
    ['nonexistent_entity', '질문이 묻는 대상이 검색된 핸드북 근거에 없어 답하지 않습니다.'],
    ['leak', '답에 내부 지시문이 섞여 있어 답하지 않습니다.'],
    ['no_key', '검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다.'],
    ['index_not_ready', '검색 색인이 아직 준비되지 않아 답할 수 없습니다.'],
    [null, '사유 코드를 주지 않는 옛 서버의 거절 문장입니다.'],
  ])('질문을 고쳐 써도 소용없는 거절(%s)에는 안내를 붙이지 않는다', async (reason, text) => {
    await askInThread(refusal(text, reason))
    expect(await screen.findByText(text)).toBeTruthy()
    expect(screen.getByText(reason === 'out_of_domain' ? '범위 밖 질문' : reason === 'no_key' ? '안내' : '근거 부족')).toBeTruthy()
    expect(screen.queryByText(HINT)).toBeNull()
  })

  // 놓친 것 N-5: 거절 머리표는 사유에 맞춘다(범위 밖 질문, 키 없음 안내, 그 밖은 근거 부족)
  it.each([
    ['out_of_domain', '핸드북과 관련 없는 질문이라 답하지 않습니다.', '범위 밖 질문'],
    ['no_key', '검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다.', '안내'],
    ['no_evidence', '핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.', '근거 부족'],
  ])('거절 사유(%s)에 맞는 머리표를 보인다', async (reason, text, label) => {
    await askInThread(refusal(text, reason))
    const bubble = (await screen.findByText(text)).closest('article')
    expect(bubble.querySelector('small').textContent).toBe(label)
  })

  it('새로고침 뒤 대화 이력의 거절도 사유에 맞는 머리표를 보인다', async () => {
    window.history.replaceState({}, '', '/chat')
    vi.stubGlobal('fetch', vi.fn(async path => {
      if (path === '/me') return json(user)
      if (path === '/threads') return json([listed])
      if (path === '/threads/t1') return json({ ...listed, messages: [
        { role: 'user', text: '오늘 점심 메뉴 추천해줘' },
        { role: 'assistant', text: '핸드북과 관련 없는 질문이라 답하지 않습니다.', state: 'no-evidence', kind: 'refuse', refuse_reason: 'out_of_domain' },
        { role: 'user', text: '없는 정책을 물음' },
        { role: 'assistant', text: '핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.', state: 'no-evidence', kind: 'refuse', refuse_reason: 'no_evidence' },
      ] })
      return json({ detail: 'not found' }, 404)
    }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    const refused = (await screen.findByText('핸드북과 관련 없는 질문이라 답하지 않습니다.')).closest('article')
    const lacking = screen.getByText('핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.').closest('article')
    expect(refused.querySelector('small').textContent).toBe('범위 밖 질문')
    expect(lacking.querySelector('small').textContent).toBe('근거 부족')
  })

  it('새로고침 뒤 대화 이력에서도 사유에 맞게 붙인다(이력의 refuse_reason)', async () => {
    window.history.replaceState({}, '', '/chat')
    vi.stubGlobal('fetch', vi.fn(async path => {
      if (path === '/me') return json(user)
      if (path === '/threads') return json([listed])
      if (path === '/threads/t1') return json({ ...listed, messages: [
        { role: 'user', text: '오늘 점심 메뉴 추천해줘' },
        { role: 'assistant', text: '핸드북과 관련 없는 질문이라 답하지 않습니다.', state: 'no-evidence', kind: 'refuse', refuse_reason: 'out_of_domain' },
        { role: 'user', text: '없는 정책을 물음' },
        { role: 'assistant', text: '핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.', state: 'no-evidence', kind: 'refuse', refuse_reason: 'no_evidence' },
      ] })
      return json({ detail: 'not found' }, 404)
    }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '연차 질문' }))
    const refused = (await screen.findByText('핸드북과 관련 없는 질문이라 답하지 않습니다.')).closest('article')
    const lacking = screen.getByText('핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.').closest('article')
    expect(refused.textContent).not.toContain(HINT)
    expect(lacking.textContent).toContain(HINT)
    expect(screen.getAllByText(HINT)).toHaveLength(1)
  })

  it('검색 일시 오류 거절은 서버 문구가 이미 다시 시도를 말하므로 같은 안내를 겹치지 않는다', async () => {
    await askInThread(stream([{ type: 'done', data: { kind: 'refuse', code: 'no_results', message: '검색을 지금 쓸 수 없어 답하지 않습니다. 잠시 뒤에 다시 시도해 주세요.' } }]))
    expect(await screen.findByText('검색을 지금 쓸 수 없어 답하지 않습니다. 잠시 뒤에 다시 시도해 주세요.')).toBeTruthy()
    expect(screen.queryByText('질문을 더 구체적으로 쓰거나 다른 표현으로 다시 물어봐 주세요.')).toBeNull()
  })

  it('응답이 끝나기 전에 연결이 끊기면(시간 초과 포함) 안내와 다시 시도 버튼을 보인다', async () => {
    await askInThread(stream([{ type: 'token', data: { text: '답 일부' } }]))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('응답이 끝나기 전에 연결이 끊겼습니다. 다시 시도해 주세요.')
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeTruthy()
  })
})
