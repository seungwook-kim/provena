"""읽기 전용 MCP 도구 `get_grounding`: 저장된 답 하나의 근거 판정 기록(코드 규칙 건수, 판정 LLM 결과, 다시 쓰기 결과, 쓴 Skill, 인용 id)을 돌려준다.

판정 코드를 따로 두지 않는다. 질문 그래프의 저장 노드(`backend/graph/build.py` save)가 `grounding.public_grounding`으로 고른 값만
답 저장소에 남기고(`answer_store.save_grounding`), 이 도구는 그 기록을 `get_grounding(answer_id)`로 읽기만 한다. 저장소에 쓰지 않는다.

내보내지 않는 것: 질문, 답 본문, 초안, 뺀 문장, 판정 이유 문장, 질문에서 뽑은 말, 사용자 id, 인용 청크 본문.
인용은 `chunk_id`·`version_id`만 낸다. 거절된 답은 저장되지 않으므로 이 도구로 볼 수 없다.

저장소: MCP 앱은 FastAPI lifespan보다 먼저 만들어지므로(`backend/main.py` create_app) 저장소를 바로 받지 않고,
호출할 때 저장소를 돌려주는 함수(`register(mcp, store_fn=...)`)를 받는다. 함수가 없거나 None을 돌려주면 not_ready다.
"""
from __future__ import annotations

from typing import Any, Callable

from extras.mcp_skill.mcp_server.server import READ_ONLY, Invalid, ToolResponse, _check_text, _failure, _resp, _run

MAX_ANSWER_ID = 64
SOURCE = "answers"


def _check(answer_id: Any) -> None:
    if not isinstance(answer_id, str) or not answer_id.strip() or len(answer_id) > MAX_ANSWER_ID:
        raise Invalid(f"answer_id는 1~{MAX_ANSWER_ID}자")
    _check_text(answer_id, "answer_id")     # SQL로 간다. NUL이면 psycopg DataError → error로 새므로 미리 invalid


def register(mcp, store_fn: Callable[[], Any] | None = None) -> None:
    """get_grounding을 mcp에 붙인다. store_fn이 없거나 그 저장소에 get_grounding이 없으면 도구는 not_ready를 돌려준다."""
    get_store = store_fn or (lambda: None)

    @mcp.tool(annotations=READ_ONLY)
    async def get_grounding(answer_id: str) -> ToolResponse:
        """저장된 답 하나의 근거 판정 기록을 읽는다. 질문, 답 본문, 사용자 id는 돌려주지 않는다. 아무것도 바꾸지 않는다.

        언제 쓰나: 답이 근거 판정을 어떻게 통과했는지(코드 규칙, 판정 LLM, 다시 쓰기) 볼 때.
        언제 쓰지 않나: 근거 원문을 읽을 때는 get_section. 거절된 답은 저장되지 않아 여기 없다.
        입력: answer_id = 답 id(1~64자).
        출력: results = [기록] 하나(answer_id, grounding, skills_used, citations(chunk_id, version_id)).
        제약: 없는 답이면 not_found. 답 저장소가 없으면 not_ready. 판정 이유 문장과 초안은 내보내지 않는다.
        """
        try:
            _check(answer_id)
            store = get_store()
            if store is None or not hasattr(store, "get_grounding"):
                return _resp("not_ready", SOURCE, retryable=False, note="답 저장소가 열려 있지 않습니다. 답이 없다는 뜻이 아닙니다.")
            rec = await _run(store.get_grounding, answer_id)
        except Exception as e:  # noqa: BLE001 — 상태로 돌려준다
            return _failure("get_grounding", SOURCE, e)
        if rec is None:
            return _resp("not_found", SOURCE, note="그 답의 판정 기록이 없습니다.")
        return _resp("ok", SOURCE, [rec])
