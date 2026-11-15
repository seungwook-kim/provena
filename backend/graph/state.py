"""그래프 상태 정의 (G4).

State에 둘 것과 Store에 둘 것을 구분하세요.
  - State: 이번 대화(thread) 안에서만 필요한 것 (질의, 검색 결과, 중간 판단)
  - Store: 대화를 넘어 사용자별로 남기는 것 (backend/memory/)

청크는 dict(`Chunk.model_dump()`)로 담는다. 체크포인트 직렬화 문제를 피하려는 선택이다.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, TypedDict

MAX_PREV_QUESTIONS = 2  # 이어 묻기(D-14)에 쓰는 같은 대화의 앞 질문 수(직전 질문과 그 앞 질문)
MAX_UNDERSTOOD = MAX_PREV_QUESTIONS + 1  # 다시 쓴 질문 기록(`understood_by_asked`)에 남기는 줄 수(`asked`와 같은 3개)


def keep_recent_questions(old: list[str] | None, new: list[str] | None) -> list[str]:
    """`asked` 칸의 합치기 규칙. 입력으로 온 질문을 뒤에 붙이고 최근 것만(지금 질문 + 앞 질문 `MAX_PREV_QUESTIONS`개) 남긴다.
    바로 앞과 같은 글(다시 시도)은 다시 붙이지 않는다. 문자열이 아니거나 빈 값은 버린다."""
    out = [q for q in (old if isinstance(old, (list, tuple)) else ()) if isinstance(q, str)]
    for q in new if isinstance(new, (list, tuple)) else ():
        if isinstance(q, str) and q.strip() and (not out or out[-1] != q):
            out.append(q)
    return out[-(MAX_PREV_QUESTIONS + 1):]


def remember_understood(table: object, typed: str, rewritten: str) -> dict[str, str]:
    """다시 쓴 질문 기록(친 글 -> 다시 쓴 글)에 한 줄을 더한 새 표. 같은 친 글은 새 줄로 바꾸고 최근 `MAX_UNDERSTOOD`줄만 남긴다. 문자열이 아닌 줄은 버린다."""
    old = table if isinstance(table, dict) else {}
    out = {k: v for k, v in old.items() if isinstance(k, str) and isinstance(v, str) and v.strip() and k != typed}
    out[typed] = rewritten
    return dict(list(out.items())[-MAX_UNDERSTOOD:])


def forget_understood(table: object, typed: str) -> dict[str, str] | None:
    """`typed` 줄을 지운 새 기록 표. 지울 줄이 없으면 None(상태를 고치지 않는다). 이번에 다시 쓰지 않은 질문이 같은 글의 옛 다시 쓴 글로 읽히지 않게 한다."""
    if not isinstance(table, dict) or typed not in table:
        return None
    return {k: v for k, v in table.items() if k != typed}


def previous_questions(state: dict | None) -> list[str]:
    """이어 묻기에 넘길 같은 대화의 앞 질문(오래된 것이 앞, 최대 `MAX_PREV_QUESTIONS`개). `asked`의 마지막은 지금 질문이라 뺀다.
    앞 질문마다 이어 묻기로 다시 쓴 기록(`understood_by_asked`)이 있으면 다시 쓴 쪽을 준다: 혼자서도 뜻이 통해, 이어 묻기 사이에 다른 질문이 끼어도 대상이 남는다.
    기록 표가 없는 대화(이 칸을 더하기 전의 체크포인트)는 직전 질문만 `user_question`·`understood_question`으로 바꾼다.
    `asked`가 없거나 질문이 하나뿐이면(새 대화, 평가 실행기) 빈 목록이다."""
    state = state or {}
    asked = [q for q in (state.get("asked") or ()) if isinstance(q, str) and q.strip()]
    table = state.get("understood_by_asked") if isinstance(state.get("understood_by_asked"), dict) else {}
    prev = [table[q] if isinstance(table.get(q), str) and table[q].strip() else q for q in asked[:-1][-MAX_PREV_QUESTIONS:]]
    understood = state.get("understood_question")
    if prev and isinstance(understood, str) and understood.strip() and state.get("user_question") == prev[-1]:
        prev[-1] = understood
    return prev

# 사용자에게 보이는 "오늘"(기준일 기본값 등)은 한국 날짜로 센다. 서버 시계는 UTC라 `date.today()`를 쓰면 한국 00:00~09:00에 전날이 나온다(놓친 것 D-15).
# 한국은 서머타임이 없어 고정 +9시간으로 둔다(`zoneinfo`는 시간대 자료(tzdata)가 없는 환경(Windows 등)에서 실패한다. docs/decisions.md 2026-11-15)
KST = timezone(timedelta(hours=9), "KST")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_kst() -> date:
    """한국 시간으로 오늘 날짜. 사용자에게 보이는 기본 날짜(기준일, 최근 N일 창, 보고서 만든 날)는 이 함수 한 곳에서 얻는다."""
    return _utcnow().astimezone(KST).date()


class AgentState(TypedDict, total=False):
    # --- 입력 ---
    question: str
    user_id: str  # 로그인한 사용자 id. thread와 Store namespace가 여기서 갈린다
    thread_id: str
    as_of: str | None  # 기준일 YYYY-MM-DD. 없으면 한국 날짜의 오늘(`today_kst`)로 채운다
    as_of_given: bool  # 입력에 기준일이 있었는지. 있으면 질문에서 뽑은 시점으로 덮지 않는다
    org: str | None  # 사용자가 지정한 절(핸드북 섹션)
    asked: Annotated[list[str], keep_recent_questions]  # 이어 묻기(D-14): 이 대화에서 `/chat`이 받은 질문(친 글, 최근 3개). `/chat`만 질문마다 `[질문]`을 넘기고 체크포인트에 쌓인다. 넘기지 않는 실행(평가 실행기)에는 없다
    followup_off: bool  # 이어 묻기 끔(`/chat`이 `CHAT_FOLLOWUP=0`일 때 질문마다 True로 넘긴다). True면 앞 질문이 있어도 `followup`을 지나지 않는다
    user_question: str | None  # 이어 묻기로 `question`을 다시 쓴 질문에서 사용자가 친 글. `followup` 노드가 지날 때마다 다시 쓴다(다시 쓰지 않았으면 None)
    understood_question: str | None  # 이어 묻기로 다시 쓴 질문(그 질문의 `question`과 같다). 다시 쓰지 않았으면 None. 화면의 "이렇게 이해했습니다"와 다음 질문의 앞 질문에 쓴다
    understood_by_asked: dict[str, str]  # 이어 묻기로 다시 쓴 질문 기록(친 글 -> 다시 쓴 글, 최근 `MAX_UNDERSTOOD`줄). `followup`이 다시 쓰면 줄을 더하고, 다시 쓰지 않으면 그 질문 글의 옛 줄을 지운다. 앞 질문을 다시 쓴 글로 바꾸는 데 쓴다(`previous_questions`)
    # --- 대화 중 값 ---
    profile: dict
    route: str  # rule | decision | review | out_of_domain
    search_query: str
    search_org: str | None
    chunks: list[dict]  # 검색 결과. 인용 검사는 이 목록과 대조한다
    retries: int  # 재검색 횟수
    judge_reason: str
    section_reads: int  # 판정이 고른 섹션 읽기 횟수. 재검색 상한에 넣지 않는다
    next_section: dict | None  # 근거 판정이 고른 섹션 읽기 {chunk_id, rule_seq, article}. 없으면 재검색이다(`chat-tool-guide`)
    judge_partial: bool  # 근거 판단의 결과: 근거가 모자라지만 묻는 사실 중 일부에는 자료가 직접 답한다. 재검색이 다 끝나도 이 값이면 그 부분만 답한다
    judge_missing: list[str]  # 근거 판단의 결과: 자료가 답하지 못한 사실. 재검색어를 그 사실에 맞추는 데 쓴다
    judge_query: str  # 근거 판단의 결과: 판정이 낸 재검색어(`GRAPH_JUDGE_QUERY=1`일 때). 있으면 재작성 LLM을 부르지 않는다
    judge_scope: str  # 근거 판단의 결과: 자료의 규칙이 질문의 범위와 다르다는 메모. 일부만 답할 때 답 작성에 넘긴다
    sub_research: str  # 빠진 하위 질문 한 번 더 찾기(`GRAPH_SUB_RESEARCH`, `GRAPH_PAGE_RESEARCH`)의 대상 하위 질문
    sub_research_phase: str  # ""(안 함), "due"(판정이 정함), "search"(재작성이 넘김), "done"(찾음)
    judge_none: bool  # `GRAPH_REFUSE_ON_NONE=1`일 때 첫 판정이 전무(충분도 부분도 아니고 되묻기도 없음)였는지. 참이면 재검색 없이 거절한다
    clarify_question: str | None
    raw_citations: list  # 답 작성이 낸 인용(검사 전)
    search_cache: dict  # 이번 실행 안의 검색 결과 기억. `GRAPH_PARALLEL_INTAKE`를 켜면 첫 재작성과 첫 검색에서 쓸 때까지 미리 받은 LLM 응답도 잠깐 담긴다
    search_stats: dict  # {"calls": 실제 검색 수, "cache_hits": 기억에서 쓴 수, "ms_*": 검색 단계 시간(사전 등록 62.72, 기록만)}
    sub_queries: list[str]  # 첫 검색 전에 나눈 한국어 하위 질문(나누지 않았거나 분해를 끄면 빈 목록)
    started_at: float  # `GRAPH_ANSWER_BUDGET_S`를 켰을 때 질문을 받은 시각(time.monotonic). 첫 답의 추론 대기를 남은 시간으로 줄인다
    judge_checks_log: list[dict]  # FL(`GRAPH_FACTS_LOG=1`, 진단): 판정마다 대표 표의 checks, sufficient, partial, 표 수
    answer_facts: dict  # FL(`GRAPH_FACTS_LOG=1`, 진단): 첫 답 초안의 asked와 picks
    judge_quote_ids: list[str]  # BO2(`GRAPH_ANSWER_BEST2=1`): 마지막 판정의 구절이 든 문맥 청크
    judge_quotes: list[list[str]]  # BO2: 마지막 판정의 사실별로 그 구절이 든 문맥 청크 id 목록(구절 글은 싣지 않는다). 측정 기록용이고 답 경로는 읽지 않는다
    best2_log: dict  # BO2: 두 답 후보의 인용, S 안/밖 수, 고른 쪽과 이유
    judge_votes: list[dict]  # 판정 다수결(`GRAPH_JUDGE_VOTE=1`)마다 표 구성(표별 충분·일부, 확정 방식, 일찍 확정했는지). 기록용이고 답 경로는 읽지 않는다(사전 등록 62.67)
    early_answer: dict  # `GRAPH_JUDGE_ANSWER`를 켰을 때 판정과 같이 받은 답(`write_answer`가 낼 칸들). 충분 판정일 때만 있다
    judged_chunks: int  # `GRAPH_STOP_STALLED_SEARCH`를 켰을 때 마지막 판정이 본 근거 수
    search_stalled: bool  # `GRAPH_STOP_STALLED_SEARCH`를 켰을 때 재검색이 근거를 더하지 못했는지
    decompose_source: str  # 분해 결과의 출처: llm | invalid | error | skipped | capped(`GRAPH_DECOMPOSE_CAP_S` 초과, 분해를 끄면 빈 문자열)
    search_error: str  # 검색을 쓸 수 없어 끝낸 이유: unavailable(임베딩 API 일시 오류) | no_key(키 없음). 정상이면 빈 문자열
    # --- 출력 ---
    kind: str  # answer | clarify | refuse
    answer: str
    citations: list[dict]  # 검사를 통과한 인용 청크
    dropped_citations: list  # 검사에서 걸러진 인용
    trimmed_citations: list  # 본문에 표시되지 않아 잘린 청크 id(인용 수 상한은 사전 등록 62.72로 없앴다). 가짜 인용이 아니므로 `dropped_citations`와 따로 둔다
    answer_id: str | None
    refuse_reason: str  # no_evidence | out_of_period | nonexistent_entity | unsupported
    grounding: dict  # 근거 판정 기록
    skills_used: list[str]  # 이번 질문에서 실제로 쓴 런타임 Skill
    drafted: bool  # 답 초안이 만들어졌는지
    decision_query: dict  # 결정표 질문에서 뽑은 {task_type, amount_usd, band}
    decision_result: dict  # 승인된 결정표 실행 결과
    decision_error: dict  # 실행을 거절한 이유 {status, reason, message}
    review_status: str  # 합동 검토 결과: clarify | no_issues | team_review_failed | pending_approval | approved | rejected (정책 질문이면 없음)
    issue_table: dict  # 승인되어 저장된 쟁점표(합동 검토)
    period_covered: bool | None  # 답 작성이 낸 "질문의 기간 자료가 있는가". false이고 질문에 시점 표현이 있으면 거절한다
