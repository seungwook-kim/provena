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
    route: str  # rule | decision | review
    search_query: str
    search_org: str | None
    chunks: list[dict]  # 검색 결과. 인용 검사는 이 목록과 대조한다
    retries: int  # 재검색 횟수
    judge_reason: str
    clarify_question: str | None
    raw_citations: list  # 답 작성이 낸 인용(검사 전)
    search_cache: dict  # 이번 실행 안의 검색 결과 기억
    search_stats: dict  # {"calls": 실제 검색 수, "cache_hits": 기억에서 쓴 수}
    # --- 출력 ---
    kind: str  # answer | clarify | refuse
    answer: str
    citations: list[dict]  # 검사를 통과한 인용 청크
    dropped_citations: list  # 검사에서 걸러진 인용
    answer_id: str | None
    refuse_reason: str  # no_evidence | out_of_period | nonexistent_entity | unsupported
    grounding: dict  # 근거 판정 기록
    skills_used: list[str]  # 이번 질문에서 실제로 쓴 런타임 Skill
    drafted: bool  # 답 초안이 만들어졌는지
