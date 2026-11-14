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
        key = task
        h = self.handlers.get(key, "")
        if callable(h):
            out = h(user)
        elif isinstance(h, list):
            i = self._n.get(key, 0)
            self._n[key] = i + 1
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
