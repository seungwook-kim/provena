"""질문 처리 그래프 시험용 가짜 모델. 프롬프트의 `[[task:...]]` 표지로 노드를 구분해 정해 둔 답을 돌려준다."""
from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage


class ScriptedLLM:
    """handlers: {task: 문자열 | 문자열 목록(차례로, 마지막은 반복) | 함수(user_text)->문자열}. 호출 기록은 `calls`."""

    def __init__(self, handlers: dict):
        self.handlers = handlers
        self.calls: list[tuple[str, str]] = []
        self._n: dict[str, int] = {}

    def invoke(self, messages, *a, **k):
        system, user = messages[0].content, messages[-1].content
        task = re.search(r"\[\[task:(\w+)\]\]", system).group(1)
        self.calls.append((task, user))
        h = self.handlers.get(task, "")
        if callable(h):
            out = h(user)
        elif isinstance(h, list):
            i = self._n.get(task, 0)
            self._n[task] = i + 1
            out = h[min(i, len(h) - 1)]
        else:
            out = h
        return AIMessage(content=out)

    def count(self, task: str) -> int:
        return sum(1 for t, _ in self.calls if t == task)


def j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


def first_chunk_id(user_text: str) -> str:
    return re.search(r"chunk_id=([0-9a-f]{16})", user_text).group(1)


def answer_with_top_chunk(user_text: str) -> str:
    cid = first_chunk_id(user_text)
    return j(answer=f"근거에 따라 답합니다 [{cid}]. 기준일 표시.", citations=[{"chunk_id": cid}])


def normal_llm(**override) -> ScriptedLLM:
    h = {
        "classify": j(route="rule"),
        "rewrite": j(query="SEV2 최초 대응", org="TEST-security", as_of=None),
        "judge": j(sufficient=True, reason="", clarify=None),
        "answer": answer_with_top_chunk,
    }
    h.update(override)
    return ScriptedLLM(h)


def sample_term_rows():
    """용어표 장치(덧붙임, 제목 경로 추가) 시험에 쓰는 표본 행. 서비스 표(`query_plan.TERM_ROWS`)는 비어 있다(사전 등록 62.34)."""
    from backend.graph.query_plan import TermRow
    return (
        TermRow("구매·새 도구 도입", (r"도입|구매|구입|사고\s*싶|사려", r"도구|툴|소프트웨어|SaaS|앱|애플리케이션|솔루션|벤더|업체"),
                "procurement, purchase request, new vendor", heads=("new request",)),
        TermRow("업체 보안 검토", (r"TPRM|보안\s*(검토|평가|심사)|(업체|벤더|공급사)\s*보안",), "TPRM, third party risk management assessment", heads=("TPRM assessment",)),
    )
