"""결정표 계약 (SDD 6장 표, 5장 decision_tables, 11-1 3-2).

- DecisionRule: 권한표 한 행 = 업무 종류 x 금액 구간 -> 업무 승인자, 재무 승인자, 협조 부서.
  칸 이름은 수집 파트 `parse_authz()` 출력(category, band, band_lo, band_hi, approval_type)에 맞췄다.
  재무 승인자는 SDD 11-1 3-2 추천대로 `cooperating_depts`와 섞지 않고 따로 둔다.
- DecisionTable: SDD 5장 `decision_tables`와 같은 칸 (table_id, rule_seq, version_id, cells, status, approved_by).
"""
from typing import Any, Literal

from pydantic import BaseModel


class DecisionRule(BaseModel):
    category: str  # 업무 종류 (권한표 행 이름)
    band: str  # 금액 구간 원문
    band_lo: int | None = None  # 금액 구간 아래 끝(USD). 원문에 없으면 비운다
    band_hi: int | None = None  # 금액 구간 위 끝(USD). 위 끝이 없는 구간은 비운다
    approvers: list[str]  # 업무 승인(Functional approval) 역할
    financial_approvers: list[str] = []  # 재무 승인(Financial approval) 역할 (SDD 11-1 3-2)
    cooperating_depts: list[str] = []  # 협조 부서
    # 원문에 구간 끝이 없어 해석으로 채운 칸의 설명. 이 칸으로 답하면 답 끝에 주의로 붙인다. 원문 그대로면 None (I-004)
    range_note: str | None = None


class DecisionTable(BaseModel):
    table_id: str
    rule_seq: int  # 권한표 페이지 id (DB는 BIGINT)
    version_id: str
    cells: Any  # SDD 5장 "cells(json)". 행(DecisionRule) 목록을 JSON으로 담는다
    status: Literal["draft", "approved", "rejected"]
    approved_by: str | None = None  # draft, rejected에서는 비어 있다
