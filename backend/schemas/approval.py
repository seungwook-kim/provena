"""에이전트 <-> 화면 승인 계약 (SDD 6장)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ApprovalItem(BaseModel):
    approval_id: str
    kind: Literal["decision_table", "issue_table"]
    summary: str
    created_at: datetime  # JSON에는 ISO 8601 문자열로 나간다


class Decision(BaseModel):
    approval_id: str
    approve: bool
    comment: str = ""
    decided_by: str | None = None  # 승인한 관리자 user_id. 화면이 보낸 값은 쓰지 않고 서버가 로그인 사용자로 채운다 (SDD 11-1 3-3)
