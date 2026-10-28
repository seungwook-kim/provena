"""그래프 상태 정의 (G4).

State에 둘 것과 Store에 둘 것을 구분하세요.
  - State: 이번 대화(thread) 안에서만 필요한 것 (질의, 검색 결과, 중간 판단)
  - Store: 대화를 넘어 사용자별로 남기는 것 (backend/memory/)
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    question: str
    user_id: str  # 로그인한 사용자 id. thread와 Store namespace가 여기서 갈린다
    # TODO: 검색 결과, 문서 채점, 재작성 횟수(상한), 답변, 인용, 승인 여부 등
