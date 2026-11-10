"""그래프 실행을 `AgentEvent` 이터레이터로 바꾸는 어댑터 (API의 `/chat` SSE용).

흐름: 그래프를 `stream_mode="updates"`로 돌리며 상태 갱신을 모은다.
- 사람 승인(interrupt)이 나오면 `approval_request` 이벤트를 내고 멈춘다(`done` 없음). 이어 가기는 `Command(resume=...)`를 input으로 다시 부른다.
- 끝나면 답을 `token` 이벤트로 나눠 내고, 인용마다 `citation`, 마지막에 `done`.
- 예외는 `error` 이벤트 하나로 바꾼다(`done` 없음).
토큰 단위 LLM 스트리밍은 하지 않는다(답은 인용 검사를 통과한 뒤에야 내보낸다).
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from backend.schemas import AgentEvent

# 질문마다 주는 입력. 그래프는 입력에 없는 칸과 앞 실행에서 남은 칸을 구분하지 못하므로, 주지 않았으면 없음(None)으로 넘겨 같은 thread의 앞 질문 값을 이어 받지 않게 한다
PER_QUESTION_INPUTS = {"as_of": None, "org": None}
CITATION_KEYS = ("chunk_id", "rule_title", "article", "version_date", "version_date_before", "source_url")
APPROVAL_KEYS = ("approval_id", "kind", "summary")  # SDD 6장. 초안과 대조표는 `GET /approvals`로 본다
_TOKEN = re.compile(r"\s*\S+\s*")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text) or ([text] if text else [])


def stream_events(graph, graph_input: Any, *, thread_id: str, config: dict | None = None, values_out: dict | None = None) -> Iterator[AgentEvent]:
    """`graph_input`은 입력 dict 또는 `Command(resume=...)`.

    `values_out`을 주면 그래프가 끝난 뒤(token, citation, done을 내기 전에) 이번 실행의 노드 갱신을 합친 값을 거기에 채운다(사전 등록 62.16 `CHAT_FINAL_FROM_STREAM`:
    체크포인트에서 최종 상태를 다시 읽지 않으려는 것). 주지 않으면 이 함수의 동작은 그대로다."""
    cfg = {**(config or {})}
    cfg["configurable"] = {**cfg.get("configurable", {}), "thread_id": thread_id}
    if isinstance(graph_input, dict):
        graph_input = {**PER_QUESTION_INPUTS, **graph_input}
    final: dict = {}
    try:
        for update in graph.stream(graph_input, cfg, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    for i in delta:
                        value = getattr(i, "value", i)
                        value = value if isinstance(value, dict) else {}
                        yield AgentEvent(type="approval_request", thread_id=thread_id, data={k: value.get(k) for k in APPROVAL_KEYS})
                    return
                if isinstance(delta, dict):
                    final.update(delta)
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 화면에는 error 이벤트로 전한다
        yield AgentEvent(type="error", thread_id=thread_id, data={"code": type(e).__name__, "message": str(e)})
        return
    if values_out is not None:
        values_out.update(final)
    for tok in _tokens(final.get("answer", "")):
        yield AgentEvent(type="token", thread_id=thread_id, data={"text": tok})
    if final.get("kind") == "answer":
        for c in final.get("citations", []):
            yield AgentEvent(type="citation", thread_id=thread_id, data={k: c.get(k) for k in CITATION_KEYS})
    yield AgentEvent(
        type="done",
        thread_id=thread_id,
        data={"answer_id": final.get("answer_id")},
    )
