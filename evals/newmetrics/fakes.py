"""시험·예행용 가짜 LLM(0원). 실제 모델 응답 모양(JSON 한 개)만 흉내 낸다. 측정 결과에는 쓰지 않는다."""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage


def decision_row(rid: str, band_line: int, **over) -> dict:
    """시험용 결정표 정답 행: 권한표 원문 줄(구간 줄, 이어지는 11칸)을 그대로 옮긴 것. 실제 정답 세트가 아니다."""
    from evals.newmetrics.common import AUTHZ_MD
    from evals.newmetrics.gold_validate import strip_tags
    from evals.newmetrics.spec_tables import ROLES, category_for_line

    ls = AUTHZ_MD.read_text(encoding="utf-8").split("\n")
    row = {"id": rid, "category": category_for_line(band_line), "band": strip_tags(ls[band_line - 1]), "band_line": band_line,
           "cells": {role: strip_tags(ls[band_line - 1 + k]) for k, role in enumerate(ROLES, start=1)}, "ambiguous": False}
    row.update(over)
    return row


class FakeRecallLLM:
    """리콜 판정 가짜: 사용자 글의 [지난 질문] 블록으로 미리 정한 답(결론 바뀜 여부)을 낸다. 모르는 질문은 '그대로'."""

    def __init__(self, verdicts: dict[str, bool], confidence: float = 0.9):
        self.verdicts, self.confidence, self.calls = dict(verdicts), confidence, 0

    def invoke(self, messages: Any, config: Any = None) -> AIMessage:
        self.calls += 1
        user = messages[-1].content if isinstance(messages, list) else str(messages)
        m = re.search(r"\[지난 질문\]\n<<<자료>>>\n(.*?)\n<<<끝>>>", user, re.S)
        q = (m.group(1) if m else "").strip()
        changed = next((v for k, v in self.verdicts.items() if k.strip() == q), False)
        return AIMessage(content=json.dumps({"conclusion_changed": changed, "confidence": self.confidence,
                                             "explanation": "가짜 판정(시험용)"}, ensure_ascii=False))


class FakeDraftLLM:
    """결정표 초안 가짜: 입력 칸(JSON)에서 규칙대로 옮긴 초안을 내되, `flip`에 든 (구간, 역할)은 틀리게 옮긴다(셀 정확도 계산 시험용)."""

    def __init__(self, flip: set[tuple[str, str]] | None = None, broken: bool = False):
        self.flip, self.broken, self.calls = set(flip or ()), broken, 0

    def invoke(self, messages: Any, config: Any = None) -> AIMessage:
        self.calls += 1
        if self.broken:
            return AIMessage(content="not json")
        user = messages[-1].content
        cells = json.loads(user.split("<<<자료>>>\n", 1)[1].rsplit("\n<<<끝>>>", 1)[0])
        rules: dict[str, dict] = {}
        for c in cells:
            r = rules.setdefault(c["band"], {"band": c["band"], "approvers": [], "financial_approvers": [], "cooperating_depts": []})
            v = (c.get("value") or "").strip()
            slot = None
            if v:
                slot = ("financial_approvers" if c["approval_type"] == "financial" else "approvers") if "approve" in v.lower() else "cooperating_depts"
            if (c["band"], c["role"]) in self.flip:
                slot = None if slot else "cooperating_depts"
            if slot:
                r[slot].append(c["role"])
        return AIMessage(content=json.dumps({"rules": list(rules.values())}, ensure_ascii=False))
