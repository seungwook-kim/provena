import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { loadDraft, saveDraft } from '../lib/draft'
import { Link, Navigate, useLocation } from 'react-router-dom'
import DemoLayout from '../components/DemoLayout'
import { createPreviewChatAdapter, PREVIEW_SUGGESTIONS } from '../lib/chat-preview'
import { createApiChatAdapter, createChatService, citationHref, renumberByAppearance } from '../lib/chat-service'
import { DEMO_SUGGESTIONS } from '../lib/demo-suggestions'
import { useSession } from '../lib/session'

function CitationButtons({ citations, selectedCitation, messageIndex, onSelect }) {
  return <div className="citation-chip-list">{citations.map((citation, index) => <button type="button" key={citation.id} className={`citation-chip ${selectedCitation?.id === citation.id && selectedCitation?.messageIndex === messageIndex ? 'selected' : ''}`} onClick={() => onSelect({ ...citation, messageIndex })}>[{index + 1}] {citation.title}</button>)}</div>
}

// CC BY-SA 표시 세 가지(원문 주소·라이선스 링크·수정 여부, TEAM_GUIDE 7장) 중 수정 여부. 서버가 attribution.modified=true를 보낸다(backend/api/routes.py ATTRIBUTION)
export const MODIFIED_LABEL = '원문을 요약·재서술함(수정됨)'
export const PROGRESS_TEXT = '근거를 찾고 답을 확인하는 중입니다'
// 승인 뒤 재개는 같은 대화에 결과를 남기고(backend/graph/departments/review.py finalize), 화면은 탭으로 돌아올 때 다시 받는다(아래 H-15 effect).
// 팀 검토 실패 건은 승인·반려가 아니라 다시 검토·검토 못 한 팀 표시이고 다음 승인 건이 이어질 수 있어(backend/graph/decision/routes.py next_approval) "승인 단계가 끝나면"으로 쓴다
export const APPROVAL_WAITING_TEXT = '담당자 승인을 기다리고 있습니다. 승인 단계가 끝나면 결과가 이 대화에 붙습니다. 이 화면으로 다시 돌아오거나 새로고침하면 보입니다. 다른 질문은 새 대화에서 해 주세요.'

// 답을 받는 중에 다른 메뉴로 가면 화면이 연결을 끊지만 서버는 답을 끝까지 만들어 저장한다(backend/api/routes.py iterate_in_one_thread).
// 끊은 대화 id를 탭 안에 남겨 두고, 채팅으로 돌아오면 그 대화를 열어 서버가 끝낼 때까지 다시 받는다.
export const RESUME_KEY = 'provena-chat-resume'
export const RESUME_TEXT = '다른 화면에 있는 동안 이어서 만든 답을 불러오는 중입니다'
export const RESUME_POLL_MS = 3000
const RESUME_LIMIT_MS = 180000
// 맨 아래에서 이만큼(px) 안이면 새 말풍선이 생길 때 따라 내려간다. 위로 올려 읽는 중이면 끌어내리지 않는다.
const STICK_THRESHOLD_PX = 80
// 입력칸은 글이 길어지면 이 높이(px, 약 8줄)까지 늘어나고 그 뒤로는 칸 안에서 스크롤한다.
export const COMPOSER_MAX_HEIGHT_PX = 208

function takeResumeId() {
  try {
    const id = sessionStorage.getItem(RESUME_KEY)
    sessionStorage.removeItem(RESUME_KEY)
    return id
  } catch { return null }
}

function saveResumeId(id) {
  try { sessionStorage.setItem(RESUME_KEY, id) } catch { /* 저장소를 못 쓰면 돌아와서 목록에서 직접 연다 */ }
}

// 연 대화 id. 새로고침해도 새 대화 화면으로 가지 않고 그 대화를 다시 연다(경희님 화면 점검 2026-11-13, AC-12).
export const OPEN_THREAD_KEY = 'provena-chat-open'

function readOpenThreadId() {
  try { return sessionStorage.getItem(OPEN_THREAD_KEY) } catch { return null }
}

function writeOpenThreadId(id) {
  try {
    if (id) sessionStorage.setItem(OPEN_THREAD_KEY, id)
    else sessionStorage.removeItem(OPEN_THREAD_KEY)
  } catch { /* 저장소를 못 쓰면 새로고침 뒤 목록에서 직접 연다 */ }
}

// 답은 그래프가 끝난 뒤 한 번에 오므로(backend/graph/stream.py) 단계 대신 지난 시간만 보여 준다
function GeneratingProgress() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [])
  return <p className="demo-answer-progress">{seconds > 0 ? `${PROGRESS_TEXT} · ${seconds}초 지남` : `${PROGRESS_TEXT}.`}</p>
}

function AttributionNotice({ attribution }) {
  const items = (Array.isArray(attribution) ? attribution : [attribution]).filter(Boolean)
  if (!items.length) return null
  return <div className="demo-attribution" role="note"><strong>출처·라이선스 안내</strong>{items.map((item, index) => <div key={index}>{item.source && <span>{item.source}</span>}{item.license && <span>{item.license}</span>}{item.license_url && <a href={item.license_url} target="_blank" rel="noreferrer">라이선스 보기</a>}{item.modified === true && <span>{MODIFIED_LABEL}</span>}{item.notice && <p>{item.notice}</p>}</div>)}</div>
}

function timestampValue(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function messageTimestamp(message) {
  return timestampValue(message?.timestamp ?? message?.createdAt ?? message?.created_at ?? message?.sentAt ?? message?.sent_at)
}

function threadTimestamp(thread) {
  const direct = thread?.lastActivityAt ?? thread?.last_activity_at ?? thread?.updatedAt ?? thread?.updated_at ?? thread?.lastActivity ?? thread?.last_activity
  const directDate = timestampValue(direct)
  if (directDate) return directDate
  return (thread?.messages ?? []).map(messageTimestamp).filter(Boolean).sort((left, right) => right - left)[0] ?? null
}

// backend ChatRequest.message 상한(422 방지, H-08)
const MAX_MESSAGE_LENGTH = 4000
const EMPTY_INPUT_NOTICE = '질문을 입력해 주세요.'

export function isApprovalPending(thread) {
  return Boolean(thread?.messages?.some(message => message.role === 'assistant' && message.state === 'approval'))
}

function formatActivity(value) {
  const date = timestampValue(value)
  if (!date) return ''
  const now = new Date()
  const today = date.toDateString() === now.toDateString()
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).toDateString() === date.toDateString()
  const time = date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (today) return `오늘 ${time}`
  if (yesterday) return `어제 ${time}`
  // 같은 제목의 대화(같은 질문을 새 대화로 다시 물은 경우)를 구분하도록 지난 날짜에도 시각을 붙인다(H-32 ②)
  return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')} ${time}`
}

function dateKey(value) {
  const date = timestampValue(value)
  return date ? `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}` : ''
}

function formatDateDivider(value) {
  const date = timestampValue(value)
  return date ? `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일` : ''
}

function MessageList({ messages, selectedCitation, onSelectCitation, onRetry }) {
  return <>{messages.map((message, index) => {
    const timestamp = messageTimestamp(message)
    const currentDate = dateKey(timestamp)
    const previousDate = index > 0 ? dateKey(messageTimestamp(messages[index - 1])) : ''
    const showDivider = Boolean(currentDate && currentDate !== previousDate)
    const messageTime = timestamp ? timestamp.toLocaleString('ko-KR') : undefined
    return <Fragment key={index}>
      {showDivider && <div className="demo-message-date"><span>{formatDateDivider(timestamp)}</span></div>}
      {message.role === 'user' ? <div className="demo-user-message" title={messageTime} tabIndex={messageTime ? 0 : undefined}>{message.text}</div> : <article className={`demo-answer ${message.state}`} title={messageTime} tabIndex={messageTime ? 0 : undefined}>
        {message.state === 'approval' && <p>{APPROVAL_WAITING_TEXT}</p>}
        <small>{message.state === 'no-evidence' ? '근거 부족' : message.state === 'generating' ? 'Provena' : message.state === 'error' || message.state === 'stopped' ? '알림' : 'Provena'}</small>
        {message.state === 'generating' && <GeneratingProgress />}
        {message.text && <p>{message.text}</p>}
        {message.citations?.length > 0 && <CitationButtons citations={message.citations} selectedCitation={selectedCitation} messageIndex={index} onSelect={onSelectCitation} />}
        <AttributionNotice attribution={message.attribution} />
        {(message.state === 'error' || message.state === 'stopped') && <div className="demo-answer-error" role="alert"><span>{message.error}</span>{message.state === 'error' && <button type="button" onClick={() => onRetry(message.question)}>다시 시도</button>}</div>}
      </article>}
    </Fragment>
  })}</>
}

export default function DemoChatPage({ api = false }) {
  const location = useLocation()
  const serviceRef = useRef(null)
  const citationPanelRef = useRef(null)
  const [threads, setThreads] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('')
  const draftUserId = useSession().user?.user_id
  const draftOwner = useRef(draftUserId)
  const [input, setInput] = useState(() => loadDraft(draftUserId))
  useEffect(() => {
    // 화면이 떠 있는 채로 계정이 바뀌면 앞 계정의 질문을 새 계정 이름으로 저장하지 않고 입력칸을 바꾼다(H-29).
    if (draftOwner.current !== draftUserId) {
      draftOwner.current = draftUserId
      setInput(loadDraft(draftUserId))
      return
    }
    saveDraft(draftUserId, input)
  }, [draftUserId, input])
  const [selectedCitation, setSelectedCitation] = useState(null)
  const [loading, setLoading] = useState(true)
  const [processingId, setProcessingId] = useState(null)
  const [sendError, setSendError] = useState('')
  // 새 대화 첫 질문은 서버가 대화 id를 줄 때까지 고를 대화가 없다 → 그동안 보낸 질문과 확인 중 말풍선을 화면에서 먼저 보여 준다
  const [draftQuestion, setDraftQuestion] = useState('')
  const [threadLoad, setThreadLoad] = useState({ id: null, status: 'idle' })
  const threadRequestRef = useRef(null)
  const [resumeId, setResumeId] = useState(null)
  // 처음 그릴 때 한 번만 읽는다(아래 effect 가 selectedId=null 로 지우기 전에)
  const [reopenId] = useState(() => (api ? readOpenThreadId() : null))
  const messagesRef = useRef(null)
  const stickToBottomRef = useRef(true)
  const composerRef = useRef(null)

  const current = useMemo(() => {
    const thread = threads.find(item => item.id === selectedId)
    if (!thread && !selectedId && draftQuestion) return { id: null, title: draftQuestion, messages: [{ role: 'user', text: draftQuestion }, { role: 'assistant', text: '', citations: [], state: 'generating', question: draftQuestion }] }
    return thread ? { ...thread, messages: (thread.messages ?? []).map(renumberByAppearance) } : null
  }, [selectedId, threads, draftQuestion])
  const threadRecords = useMemo(() => threads.map(thread => ({ thread, activity: threadTimestamp(thread) })), [threads])
  const canSortByActivity = threadRecords.length > 0 && threadRecords.every(item => item.activity)
  const visibleThreads = useMemo(() => {
    const normalized = filter.trim().toLowerCase()
    return threadRecords
      .filter(item => item.thread.title.toLowerCase().includes(normalized))
      .sort((left, right) => canSortByActivity ? right.activity - left.activity : 0)
      .map(item => item.thread)
  }, [canSortByActivity, filter, threadRecords])
  // 근거 패널 번호는 대화 전체가 아니라 선택한 답 기준이다(H-32). 고른 인용이 없으면 마지막으로 근거가 있는 답.
  const panelMessageIndex = useMemo(() => {
    const messages = current?.messages ?? []
    if (Number.isInteger(selectedCitation?.messageIndex) && messages[selectedCitation.messageIndex]?.citations?.length) return selectedCitation.messageIndex
    return messages.findLastIndex(message => message.role === 'assistant' && message.citations?.length)
  }, [current, selectedCitation])
  const citationOptions = useMemo(() => {
    const seen = new Set()
    return (current?.messages?.[panelMessageIndex]?.citations ?? []).filter(citation => {
      if (seen.has(citation.id)) return false
      seen.add(citation.id)
      return true
    })
  }, [current, panelMessageIndex])
  const activeCitation = citationOptions.find(citation => citation.id === selectedCitation?.id) ?? null
  const activeCitationId = activeCitation?.id ?? null
  const processing = processingId !== null
  const approvalPending = isApprovalPending(current)
  const threadLoading = threadLoad.id === selectedId && threadLoad.status === 'loading' && !current?.messages?.length
  const threadError = threadLoad.id === selectedId && threadLoad.status === 'error'
  const resuming = resumeId !== null && resumeId === selectedId
  const composerDisabled = loading || processing || approvalPending || threadLoading || resuming

  useEffect(() => {
    if (activeCitationId && typeof citationPanelRef.current?.scrollTo === 'function') citationPanelRef.current.scrollTo({ top: 0, behavior: 'auto' })
  }, [activeCitationId])

  useEffect(() => {
    const adapter = api ? createApiChatAdapter({ onThreadsChange: setThreads, onProcessingChange: setProcessingId }) : createPreviewChatAdapter({ onThreadsChange: setThreads, onProcessingChange: setProcessingId })
    const service = createChatService(adapter)
    serviceRef.current = service
    service.listThreads().then(items => {
      setThreads(items)
      const pending = api ? takeResumeId() : null
      if (pending && items.some(item => item.id === pending)) {
        stickToBottomRef.current = true
        setSelectedId(pending)
        setResumeId(pending)
        return
      }
      const reopen = reopenId ? items.find(item => item.id === reopenId) : null
      if (reopen) selectThread(reopen)
    }).catch(() => {
      setThreads([])
    }).finally(() => setLoading(false))
    return () => {
      const cut = service.dispose()
      if (api && cut.length) saveResumeId(cut[cut.length - 1])
    }
  }, [])

  // 연 대화를 탭 안에 기억한다. 목록을 받기 전에는 쓰지 않는다(그사이 새로고침해도 기억이 지워지지 않게).
  useEffect(() => {
    if (api && !loading) writeOpenThreadId(selectedId)
  }, [selectedId, loading])

  // 돌아온 대화를 서버에서 다시 받는다. 서버가 아직 만드는 중(status running)이면 끝날 때까지 몇 초마다 다시 받는다.
  useEffect(() => {
    if (resumeId === null) return undefined
    let stopped = false
    let timer = null
    const started = Date.now()
    const poll = async () => {
      try {
        const loaded = await serviceRef.current?.getThread(resumeId, { fresh: true })
        if (stopped) return
        if (loaded?.status === 'running' && Date.now() - started < RESUME_LIMIT_MS) {
          timer = setTimeout(poll, RESUME_POLL_MS)
          return
        }
        if (loaded) setSelectedCitation(firstCitation(loaded))
      } catch { /* 못 받으면 목록에서 대화를 다시 눌러 받을 수 있다 */ }
      if (!stopped) setResumeId(null)
    }
    poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [resumeId])

  // 맨 아래 근처에 있을 때만 새 말풍선·답을 따라 내려간다. 질문을 보내거나 대화를 열면 맨 아래로 간다.
  useLayoutEffect(() => {
    const box = messagesRef.current
    if (box && stickToBottomRef.current) box.scrollTop = box.scrollHeight
  }, [current, threadLoading, resumeId])

  function handleMessagesScroll(event) {
    const box = event.currentTarget
    stickToBottomRef.current = box.scrollHeight - box.scrollTop - box.clientHeight <= STICK_THRESHOLD_PX
  }

  // 입력칸 높이를 글에 맞춘다(최대 COMPOSER_MAX_HEIGHT_PX). 보내서 비우면 한 줄로 돌아간다.
  useLayoutEffect(() => {
    const box = composerRef.current
    if (!box) return
    box.style.height = 'auto'
    if (box.scrollHeight) box.style.height = `${Math.min(box.scrollHeight, COMPOSER_MAX_HEIGHT_PX)}px`
  }, [input])

  // 승인함에서 승인이 끝나고 돌아오면 입력창이 잠긴 채라, 화면으로 돌아올 때 서버 상태를 다시 받는다(H-15)
  useEffect(() => {
    if (!approvalPending || !selectedId) return undefined
    const refresh = () => { serviceRef.current?.getThread(selectedId).catch(() => {}) }
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [approvalPending, selectedId])

  useEffect(() => {
    if (typeof location.state?.question === 'string') setInput(location.state.question)
  }, [location.state])

  const firstCitation = thread => {
    const index = thread?.messages?.findLastIndex(message => message.role === 'assistant') ?? -1
    const citation = index < 0 ? null : renumberByAppearance(thread.messages[index]).citations?.[0]   // 화면에 [1]로 보이는 근거(H-32)
    return citation ? { ...citation, messageIndex: index } : null
  }

  async function selectThread(thread) {
    setSendError('')
    stickToBottomRef.current = true
    setSelectedId(thread.id)
    setSelectedCitation(firstCitation(thread))
    if (!serviceRef.current) return
    threadRequestRef.current = thread.id
    setThreadLoad({ id: thread.id, status: 'loading' })
    try {
      const loaded = await serviceRef.current.getThread(thread.id)
      if (threadRequestRef.current !== thread.id) return
      if (loaded) setSelectedCitation(firstCitation(loaded))
      setThreadLoad({ id: thread.id, status: 'idle' })
    } catch {
      if (threadRequestRef.current === thread.id) setThreadLoad({ id: thread.id, status: 'error' })
    }
  }

  async function newConversation() {
    if (processing) return
    await serviceRef.current?.createConversation()
    setSelectedId(null)
    setSelectedCitation(null)
    setInput('')
  }

  async function ask(value, retry = false) {
    // 오류 말풍선의 '다시 시도'에 question이 없던 옛 말풍선이 와도 TypeError가 나지 않게 한다(H-08)
    const message = typeof value === 'string' ? value.trim() : ''
    if (!message && typeof value === 'string' && !processing && !approvalPending && !resuming && serviceRef.current) {   // 빈 입력은 조용히 무시하지 않고 안내한다
      setSendError(EMPTY_INPUT_NOTICE)
      return
    }
    if (!message || message.length > MAX_MESSAGE_LENGTH || processing || approvalPending || resuming || !serviceRef.current) return
    setSendError('')
    stickToBottomRef.current = true
    let result
    if (!selectedId) setDraftQuestion(message)
    try {
      result = await serviceRef.current.sendMessage({ threadId: selectedId, message, retry })
    } catch (error) {
      setSendError(error?.message || '질문을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.')
      return
    } finally {
      setDraftQuestion('')
    }
    if (!result) return
    // 새 대화의 첫 질문을 중지하면 대화 id가 없다 → 질문을 입력칸에 남기고, 서버가 만든 대화가 목록에 나타나게 다시 받는다(M3)
    if (result.threadId == null) {
      await serviceRef.current?.listThreads().catch(() => {})
      return
    }
    setSelectedId(result.threadId)
    setSelectedCitation(null)
    setInput('')
  }

  async function stopAnswer() {
    if (processingId) await serviceRef.current?.stopMessage(processingId)
  }

  function handleComposerKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return
    event.preventDefault()
    ask(input)
  }

  return <DemoLayout active="chat"><div className="demo-chat-page"><div className="demo-chat-grid">
    <aside className="demo-thread-sidebar" aria-label="대화 목록">
      <button type="button" className="button button-dark" onClick={newConversation} disabled={processing}>+ 새 대화</button>
      <label className="demo-thread-search"><span>대화 검색</span><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="대화 제목 검색" disabled={loading || processing} /></label>
      <p className="demo-thread-list-heading"><span>대화 목록</span>{canSortByActivity && <small>최근 활동순</small>}</p>
      {loading && <div className="demo-thread-state">대화를 불러오는 중입니다.</div>}
      {!loading && visibleThreads.length === 0 && <div className="demo-thread-state">{threads.length ? '검색 결과가 없습니다.' : <>아직 대화가 없습니다.<br />새 대화를 시작해 보세요.</>}</div>}
      {visibleThreads.map(thread => { const activity = threadTimestamp(thread); return <button type="button" key={thread.id} className={`demo-thread ${thread.id === selectedId ? 'selected' : ''}`} disabled={processing} title={thread.title} aria-label={thread.title} onClick={() => selectThread(thread)}><span className="demo-thread-title">{thread.title}</span>{activity && <time dateTime={activity.toISOString()}>{formatActivity(activity)}</time>}</button> })}
    </aside>
    <main className="demo-chat-main">
      <div className="demo-chat-status">{processing && <span className="demo-generating">{PROGRESS_TEXT}.</span>}{!processing && resuming && <span className="demo-generating" role="status">{RESUME_TEXT}.</span>}</div>
      <div className="demo-messages" ref={messagesRef} onScroll={handleMessagesScroll}>
        {loading || threadLoading ? <div className="demo-empty"><h1>대화를 불러오는 중입니다.</h1></div> : current ? <div className="demo-message-stack">{threadError && <div className="demo-answer-error" role="alert"><span>대화를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</span></div>}<MessageList messages={current.messages} selectedCitation={selectedCitation} onSelectCitation={setSelectedCitation} onRetry={question => ask(question, true)} /></div> : <div className="demo-empty"><h1>정책에 대해 물어보세요.</h1><p>정책 문서를 근거로 답변을 제공합니다.</p><div className="demo-suggestions">{(api ? DEMO_SUGGESTIONS : PREVIEW_SUGGESTIONS).map(question => <button type="button" key={question} disabled={processing} onClick={() => ask(question)}>{question}</button>)}</div></div>}
      </div>
      {sendError && <div className="demo-answer-error" role="alert"><span>{sendError}</span></div>}
      <form className="demo-composer" onSubmit={event => { event.preventDefault(); ask(input) }}><div><textarea ref={composerRef} value={input} onChange={event => { setInput(event.target.value); if (sendError === EMPTY_INPUT_NOTICE) setSendError('') }} onKeyDown={handleComposerKeyDown} rows="1" maxLength={MAX_MESSAGE_LENGTH} disabled={composerDisabled} placeholder="질문을 입력하세요" aria-label="질문" /><button type="submit" className="button button-dark" disabled={composerDisabled || !input.trim()}>보내기</button>{processing && <button type="button" className="demo-stop-button" onClick={stopAnswer}>답변 중지</button>}</div><p><span className="demo-composer-keyboard-hint">Enter 전송 · Shift + Enter 줄바꿈</span><span>근거 문서의 섹션과 문서 버전을 함께 확인할 수 있습니다.</span></p></form>
    </main>
    <aside ref={citationPanelRef} className="demo-citation-sidebar" aria-label="참고 근거"><h2>참고 근거</h2>{!activeCitation && <p>인용을 선택하면 관련 근거를 확인할 수 있습니다.</p>}{citationOptions.length > 1 && <div className="citation-source-tabs" role="tablist" aria-label="출처 선택">{citationOptions.map((citation, index) => <button type="button" role="tab" aria-selected={activeCitation?.id === citation.id} aria-label={`출처 ${index + 1}: ${citation.title}`} title={citation.title} key={citation.id} className={`citation-chip ${activeCitation?.id === citation.id ? 'selected' : ''}`} onClick={() => setSelectedCitation({ ...citation, messageIndex: panelMessageIndex })}>[{index + 1}]</button>)}</div>}{activeCitation ? <article className="demo-citation"><strong>출처</strong><span>{activeCitation.path}</span><blockquote>{activeCitation.text}</blockquote><dl><dt>문서명</dt><dd>{activeCitation.title}</dd><dt>문서 버전</dt><dd>{activeCitation.version}</dd></dl><a href={citationHref(activeCitation)} target="_blank" rel="noreferrer">원문 보기 →</a></article> : <p className="demo-citation-empty">선택한 인용이 없습니다.</p>}</aside>
  </div></div></DemoLayout>
}

function ChatUnavailable() {
  return <DemoLayout active="chat"><main className="demo-chat-unavailable"><h1>현재 채팅을 사용할 수 없습니다.</h1><p>잠시 후 다시 시도해 주세요.</p></main></DemoLayout>
}

export function DemoOnlyChat() {
  const location = useLocation()
  const { user } = useSession()
  const previewMode = (import.meta.env.DEV || import.meta.env.VITE_ENABLE_LOCAL_DEMO === 'true') && location.pathname.startsWith('/demo/')
  if (previewMode) return <DemoChatPage />
  if (!user) return <Navigate to="/login" replace />
  return <DemoChatPage api />
}

export function DemoAdminBlocked() {
  const location = useLocation()
  if (!(import.meta.env.DEV || import.meta.env.VITE_ENABLE_LOCAL_DEMO === 'true') || !location.pathname.startsWith('/demo/')) return <Navigate to="/login" replace />
  return <main className="status-page"><p role="alert">현재 이 기능을 사용할 수 없습니다.</p><Link className="button button-dark" to="/demo/chat">채팅으로 돌아가기</Link></main>
}
