import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { resetLiveServices } from './lib/live-services'

const USER = { user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', role: 'user', profile_completed: true }
const ADMIN = { user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', role: 'admin', profile_completed: true }

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const apiError = (status, code, message) => json({ error: { code, message, request_id: 'req-1' } }, status)
// 실제 서버 모양(backend/api/errors.py error_body): detail은 문자열, error 봉투에 code·message·request_id
const realError = (status, code, message) => json({ detail: message, error: { code, message, request_id: 'req-1' } }, status)
// 옛 모양(detail이 {reason, message}). api.js가 아직 받아 주므로 한 건만 남긴다
const detailError = (status, reason, message) => json({ detail: { reason, message } }, status)

const RULES = [{ category: 'Approving expense', band: 'Up to $5K', band_label: '5,000달러 이하', approvers: ['Manager'], financial_approvers: ['Finance'], cooperating_depts: [], range_note: null }]
const exampleView = () => ({ approval_id: 'example-convert', kind: 'decision_table', summary: '예시 응답: Approving expense 결정표 초안 (키 없는 데모, 저장·승인되지 않음)', created_at: '2026-11-12T01:00:00Z', status: 'example', draft: RULES })
const queuedView = () => ({ approval_id: 'dec-new', kind: 'decision_table', summary: '결정표 승인 요청: Approving expense (구간 1개, 원문과 다른 칸 0개)', created_at: '2026-11-12T01:00:00Z', status: 'pending', table_id: 'dt_9', draft: RULES })
const pendingItem = () => ({
  kind: 'decision_table', approval_id: 'dec-new', summary: '결정표 승인 요청: Approving expense (구간 1개, 원문과 다른 칸 0개)', created_at: '2026-11-12T01:00:00Z', table_id: 'dt_9',
  draft: RULES, comparison: { rows: [], source_cells: 3, mismatch_count: 0, extra_bands: [] }, save_failed: false,
})

let server
let calls

const requestsTo = (method, path) => calls.filter(call => (call.options?.method ?? 'GET') === method && call.path === path)

beforeEach(() => {
  resetLiveServices()
  document.cookie = 'provena_csrf=; Max-Age=0; path=/'
  calls = []
  server = { user: ADMIN, approvals: [], convert: () => json(exampleView(), 201) }
  vi.stubGlobal('fetch', vi.fn(async (path, options = {}) => {
    calls.push({ path, options })
    const method = options.method ?? 'GET'
    if (path === '/me') return json(server.user)
    if (path === '/auth/csrf') { document.cookie = 'provena_csrf=test-csrf; path=/'; return new Response(null, { status: 204 }) }
    if (path === '/threads') return json([])
    if (path === '/recalls') return json({ items: [], unread: 0 })
    if (path === '/recalls/digests') return json([])
    if (path === '/approvals' && method === 'GET') return json(server.approvals)
    if (path === '/decision-tables/convert' && method === 'POST') return server.convert(JSON.parse(options.body))
    return apiError(404, 'not_found', '요청한 경로를 찾을 수 없습니다.')
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function open(path = '/approvals') {
  window.history.replaceState({}, '', path)
  return render(<App />)
}

async function startConvert(category = 'Approving expense') {
  await userEvent.type(await screen.findByLabelText('권한표 업무 종류'), category)
  await userEvent.click(screen.getByRole('button', { name: '결정표로 변환' }))
}

const confirmDialog = () => userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '확인' }))

describe('decision table convert panel on the approvals page', () => {
  it('shows the form to an admin and hides it from a non-admin', async () => {
    open()
    expect(await screen.findByRole('heading', { name: '결정표 변환' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '결정표로 변환' })).toBeTruthy()
    cleanup()
    resetLiveServices()
    calls = []
    server.user = USER
    open()
    await screen.findByText(/접근 권한이 없습니다/)
    expect(screen.queryByRole('heading', { name: '결정표 변환' })).toBeNull()
    expect(screen.queryByLabelText('권한표 업무 종류')).toBeNull()
    expect(requestsTo('POST', '/decision-tables/convert')).toHaveLength(0)
  })

  it('asks for confirmation before calling the API and sends the category with CSRF only after confirming', async () => {
    open()
    await startConvert('  Approving expense  ')
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: '결정표로 변환하시겠습니까?' })).toBeTruthy()
    expect(within(dialog).getByText(/Approving expense/)).toBeTruthy()
    expect(requestsTo('POST', '/decision-tables/convert')).toHaveLength(0)
    await userEvent.click(within(dialog).getByRole('button', { name: '취소' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(requestsTo('POST', '/decision-tables/convert')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '결정표로 변환' }))
    await confirmDialog()
    await screen.findByText('예시 응답(키 없는 데모, 저장되지 않음)')
    const [request] = requestsTo('POST', '/decision-tables/convert')
    expect(JSON.parse(request.options.body)).toEqual({ category: 'Approving expense' })
    expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf')
  })

  it('does not open the dialog or call the API for an empty category', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: '결정표로 변환' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect((await screen.findByRole('alert')).textContent).toMatch(/업무 종류를 입력/)
    expect(requestsTo('POST', '/decision-tables/convert')).toHaveLength(0)
  })

  it('labels the keyless demo response as an example and does not add it to the approval list', async () => {
    open()
    await startConvert()
    await confirmDialog()
    await screen.findByText('예시 응답(키 없는 데모, 저장되지 않음)')
    expect(screen.getByText(/승인함에 올라가지 않았고/)).toBeTruthy()
    const exampleTable = screen.getByRole('table', { name: '예시 초안' })
    expect(within(exampleTable).getByText('5,000달러 이하')).toBeTruthy()
    expect(screen.queryByText(/승인함에 올렸습니다/)).toBeNull()
    expect(requestsTo('GET', '/approvals')).toHaveLength(1)
    expect(screen.getByText('처리할 승인 요청이 없습니다. 새 요청이 올라오면 이곳에 표시됩니다.')).toBeTruthy()
  })

  it('tells the admin a real draft went to the approval inbox and reloads the list', async () => {
    server.convert = () => { server.approvals = [pendingItem()]; return json(queuedView(), 201) }
    open()
    await startConvert()
    await confirmDialog()
    await screen.findByText(/결정표 초안을 승인함에 올렸습니다/)
    expect(screen.queryByText('예시 응답(키 없는 데모, 저장되지 않음)')).toBeNull()
    await screen.findByRole('button', { name: /결정표 승인 요청: Approving expense/ })
    expect(requestsTo('GET', '/approvals')).toHaveLength(2)
    expect(screen.getByLabelText('권한표 업무 종류').value).toBe('')
  })

  it.each([
    [409, realError(409, 'conflict', '이 업무 종류로 승인된 결정표가 이미 있다'), '이미 같은 결정표가 있거나 승인 대기 중이거나, 초안이 승인 대기에 이르지 못했습니다. 승인함을 확인하고 다시 시도해 주세요.'],
    [409, realError(409, 'conflict', '이 업무 종류의 결정표 초안이 이미 승인을 기다리고 있다'), '이미 같은 결정표가 있거나 승인 대기 중이거나, 초안이 승인 대기에 이르지 못했습니다. 승인함을 확인하고 다시 시도해 주세요.'],
    [400, realError(400, 'bad_request', 'category(권한표 업무 종류)가 필요하다'), '권한표 업무 종류를 입력해 주세요.'],
    [404, realError(404, 'not_found', '권한표에 그 업무 종류가 없다'), '권한표에 그 업무 종류가 없습니다. 이름을 확인해 주세요.'],
    [502, realError(502, 'draft_unreadable', '초안을 읽지 못해 승인함에 올리지 않았다'), '초안을 읽지 못해 승인함에 올리지 않았습니다. 잠시 후 다시 시도해 주세요.'],
    [502, realError(502, 'no_source', '권한표 칸을 읽지 못했다'), '권한표 칸을 읽지 못해 승인함에 올리지 않았습니다.'],
    [503, realError(503, 'convert_failed', '결정표 초안을 만들지 못했다'), '결정표 초안을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'],
    [403, realError(403, 'forbidden', '관리자 권한이 필요합니다.'), '이 작업을 수행할 권한이 없습니다. 결정표 변환은 관리자만 할 수 있습니다.'],
    [409, realError(409, 'conflict', '초안이 승인 대기에 이르지 못했다'), '이미 같은 결정표가 있거나 승인 대기 중이거나, 초안이 승인 대기에 이르지 못했습니다. 승인함을 확인하고 다시 시도해 주세요.'],
    [409, detailError(409, 'conflict', '이 업무 종류로 승인된 결정표가 이미 있다'), '이미 같은 결정표가 있거나 승인 대기 중이거나, 초안이 승인 대기에 이르지 못했습니다. 승인함을 확인하고 다시 시도해 주세요.'],
    [409, json({}, 409), '이미 같은 결정표가 있거나 승인 대기 중이거나, 초안이 승인 대기에 이르지 못했습니다. 승인함을 확인하고 다시 시도해 주세요.'],
    [503, realError(503, 'not_configured', '결정표 저장소를 사용할 수 없습니다.'), '결정표 변환에 필요한 저장소나 권한표 파일을 지금 쓸 수 없습니다. 잠시 후 다시 시도해 주세요.'],
  ])('shows a fixed polite Korean message for a %i error and keeps the form usable', async (_status, response, message) => {
    server.convert = () => response
    open()
    await startConvert()
    await confirmDialog()
    expect((await screen.findByRole('alert')).textContent).toBe(message)
    expect(screen.queryByText(/승인함에 올렸습니다/)).toBeNull()
    expect(screen.getByRole('button', { name: '결정표로 변환' }).disabled).toBe(false)
    expect(requestsTo('GET', '/approvals')).toHaveLength(1)
  })

  it('disables the form and button while converting and sends only one request', async () => {
    let release
    server.convert = () => new Promise(resolve => { release = () => resolve(json(exampleView(), 201)) })
    open()
    await startConvert()
    await confirmDialog()
    const button = await screen.findByRole('button', { name: '변환 중입니다.' })
    expect(button.disabled).toBe(true)
    expect(screen.getByLabelText('권한표 업무 종류').disabled).toBe(true)
    await userEvent.click(button)
    await waitFor(() => expect(requestsTo('POST', '/decision-tables/convert')).toHaveLength(1))
    release()
    await screen.findByText('예시 응답(키 없는 데모, 저장되지 않음)')
    expect(screen.getByRole('button', { name: '결정표로 변환' }).disabled).toBe(false)
    expect(requestsTo('POST', '/decision-tables/convert')).toHaveLength(1)
  })
})
