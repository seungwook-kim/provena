"""에이전트 -> 화면 계약 (SDD 6장).

`data`는 `type`마다 키가 정해져 있다(SDD 6장 "AgentEvent.data" 표).
- token: text
- citation: chunk_id, rule_title, article, version_date, version_date_before, source_url
- approval_request: approval_id, kind, summary (ApprovalItem과 같은 이름)
- error: code, message
- done: answer_id (거절·되묻기로 저장한 답이 없으면 None)
"""
from typing import Literal

from pydantic import BaseModel


class AgentEvent(BaseModel):
    type: Literal["token", "citation", "approval_request", "error", "done"]
    thread_id: str
    data: dict  # type별 키는 SDD 6장 "AgentEvent.data" 표
