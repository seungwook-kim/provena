"""그래프 상태 정의 (G4).

State에 둘 것과 Store에 둘 것을 구분하세요.
  - State: 이번 대화(thread) 안에서만 필요한 것 (질의, 검색 결과, 중간 판단)
  - Store: 대화를 넘어 사용자별로 남기는 것 (backend/memory/)

청크는 dict(`Chunk.model_dump()`)로 담는다. 체크포인트 직렬화 문제를 피하려는 선택이다.
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    # --- 입력 ---
    question: str
    user_id: str  # 로그인한 사용자 id. thread와 Store namespace가 여기서 갈린다
    thread_id: str
    as_of: str | None  # 기준일 YYYY-MM-DD. 없으면 오늘로 채운다
    as_of_given: bool  # 입력에 기준일이 있었는지. 있으면 질문에서 뽑은 시점으로 덮지 않는다
    org: str | None  # 사용자가 지정한 절(핸드북 섹션)
    # --- 대화 중 값 ---
    profile: dict
    route: str  # rule | decision | review | out_of_domain
    search_query: str
    search_org: str | None
    chunks: list[dict]  # 검색 결과. 인용 검사는 이 목록과 대조한다
    retries: int  # 재검색 횟수
    judge_reason: str
    judge_partial: bool  # 근거 판단의 결과: 근거가 모자라지만 묻는 사실 중 일부에는 자료가 직접 답한다. 재검색이 다 끝나도 이 값이면 그 부분만 답한다
    clarify_question: str | None
    raw_citations: list  # 답 작성이 낸 인용(검사 전)
    search_cache: dict  # 이번 실행 안의 검색 결과 기억
    search_stats: dict  # {"calls": 실제 검색 수, "cache_hits": 기억에서 쓴 수}
    sub_queries: list[str]  # 첫 검색 전에 나눈 한국어 하위 질문(나누지 않았거나 분해를 끄면 빈 목록)
    decompose_source: str  # 분해 결과의 출처: llm | invalid | error | skipped(분해를 끄면 빈 문자열)
    search_error: str  # 검색을 쓸 수 없어 끝낸 이유: unavailable(임베딩 API 일시 오류) | no_key(키 없음). 정상이면 빈 문자열
    # --- 출력 ---
    kind: str  # answer | clarify | refuse
    answer: str
    citations: list[dict]  # 검사를 통과한 인용 청크
    dropped_citations: list  # 검사에서 걸러진 인용
    trimmed_citations: list  # 인용 수 상한(`MAX_CITATIONS`)이나 본문에 표시되지 않아 잘린 청크 id. 가짜 인용이 아니므로 `dropped_citations`와 따로 둔다
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
