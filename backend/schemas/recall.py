"""수집 -> 에이전트 -> 화면 리콜 계약 (SDD 6장)."""
from typing import Literal

from pydantic import BaseModel


class ChangedArticle(BaseModel):  # 바뀐 섹션 (같은 페이지의 두 커밋 비교)
    rule_seq: int  # 페이지 id (Chunk.rule_seq와 같은 값, DB는 BIGINT)
    article: str
    old_version_date: str
    new_version_date: str
    change_type: Literal["added", "removed", "modified"]  # 삭제된 섹션을 인용한 답은 판정이 다르다 (SDD 11-1 3-5)


class RecallNotice(BaseModel):
    answer_id: str
    user_id: str
    changed: ChangedArticle
    conclusion_changed: bool
    explanation: str


class MaintenanceCandidate(BaseModel):  # 연결 정책 개정 -> 관리자 "함께 볼 정책" (F-02)
    candidate_id: str
    upper_rule: str  # 개정된 정책 페이지 (링크로 연결된 쪽)
    upper_version_id: str
    rule_seq: int  # 영향받는 다른 정책 페이지 (DB는 BIGINT)
    article: str
    reason: str  # 페이지 링크 그래프에서 찾은 근거
