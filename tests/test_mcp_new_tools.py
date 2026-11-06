"""MCP 읽기 전용 도구 get_grounding 시험 (extras/mcp_skill/mcp_server/grounding_tool.py). 키, DB, 네트워크를 쓰지 않는다.

explain_decision과 get_agent_trace는 #58 구현(decision_tool.py, trace_tool.py)과 그 시험(tests/test_mcp_decision_tool.py,
tests/test_mcp_trace_tool.py)을 쓴다. 이 파일에는 get_grounding과, 합동 검토 팀 시간 칸(review.py `seconds`)이 표 해시를 바꾸지 않는지만 둔다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

from backend.graph.answer_store import InMemoryAnswerStore  # noqa: E402
from backend.graph.grounding import public_grounding  # noqa: E402
from backend.schemas import Chunk  # noqa: E402
from extras.mcp_skill.mcp_server import server as srv  # noqa: E402

TOOL = "get_grounding"
SECRET_QUESTION, SECRET_ANSWER, SECRET_USER = "비밀 질문 글", "비밀 답 본문", "user-secret"


def call(mcp, tool: str, args: dict) -> dict:
    async def go():
        async with Client(mcp) as c:
            return (await c.call_tool(tool, args, raise_on_error=False)).structured_content
    return asyncio.run(go())


def list_tools(mcp) -> list:
    async def go():
        async with Client(mcp) as c:
            return await c.list_tools()
    return asyncio.run(go())


def saved_store() -> InMemoryAnswerStore:
    store = InMemoryAnswerStore()
    c = Chunk(chunk_id="a" * 16, org="security", rule_seq=1, rule_title="T", article="A", version_id="v1", version_date="2026-10-30",
              fetched_at="2026-10-30", kind="article", text="비밀 근거", source_url="https://handbook.gitlab.com/x")
    store.save("a1", SECRET_USER, "th", SECRET_QUESTION, SECRET_ANSWER, None, [c])
    raw = {"llm": "pass", "reason": "이유 코드", "rules": {"cited": 1, "retrieved": 5, "question_years": [2023], "missing_terms": ["비밀어"]},
           "draft_answer": SECRET_ANSWER, "removed": ["뺀 문장"], "detail": "판정 문장",
           "redraft": {"result": "passed", "answer": SECRET_ANSWER}, "revise": {"result": "kept", "claims": ["주장"]}}
    store.save_grounding("a1", public_grounding(raw), ["citation-rules"])
    return store


# ---------- 도구 목록과 읽기 전용 ----------

def test_grounding_tool_is_read_only_with_five_part_description():
    by_name = {t.name: t for t in list_tools(srv.build_server(search_fn=lambda q: []))}
    t = by_name[TOOL]
    assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False
    assert TOOL.isascii() and all(p.isascii() for p in t.input_schema["properties"])
    for part in ("언제 쓰나", "언제 쓰지 않나", "입력", "출력", "제약"):
        assert part in t.description


def test_without_store_is_not_ready():
    r = call(srv.build_server(search_fn=lambda q: []), TOOL, {"answer_id": "a"})
    assert r["status"] == "not_ready" and r["retryable"] is False


def test_store_returning_none_is_not_ready():
    r = call(srv.build_server(search_fn=lambda q: [], answer_store_fn=lambda: None), TOOL, {"answer_id": "a"})
    assert r["status"] == "not_ready" and r["retryable"] is False


@pytest.mark.parametrize("answer_id", ["", " ", "x" * 65])
def test_bad_input_is_invalid(answer_id):
    r = call(srv.build_server(search_fn=lambda q: [], answer_store_fn=saved_store), TOOL, {"answer_id": answer_id})
    assert r["status"] == "invalid" and r["retryable"] is False


def test_http_token_rule_applies(monkeypatch):
    """토큰 헤더 규칙을 그대로 쓴다(test_mcp_server의 app_client와 같은 방식). 무토큰과 틀린 토큰은 401이다."""
    from fastapi.testclient import TestClient

    from backend.main import create_app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MCP_TOKEN", "abc")
    hdr = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": TOOL, "arguments": {}}}
    with TestClient(create_app()) as c:
        assert c.post("/mcp/", json=body, headers=hdr).status_code == 401
        assert c.post("/mcp/", json=body, headers={**hdr, "Authorization": "Bearer abd"}).status_code == 401


# ---------- get_grounding ----------

def test_grounding_returns_only_public_fields():
    mcp = srv.build_server(search_fn=lambda q: [], answer_store_fn=saved_store)
    r = call(mcp, TOOL, {"answer_id": "a1"})
    assert r["status"] == "ok" and r["source"] == "answers"
    rec = r["results"][0]
    assert rec["grounding"]["llm"] == "pass" and rec["grounding"]["rules"] == {"cited": 1, "retrieved": 5}
    assert rec["citations"] == [{"chunk_id": "a" * 16, "version_id": "v1"}] and rec["skills_used"] == ["citation-rules"]
    dumped = json.dumps(r, ensure_ascii=False)
    for secret in (SECRET_QUESTION, SECRET_ANSWER, SECRET_USER, "비밀 근거", "뺀 문장", "판정 문장", "비밀어", "주장"):
        assert secret not in dumped


def test_grounding_unknown_answer_is_not_found():
    mcp = srv.build_server(search_fn=lambda q: [], answer_store_fn=saved_store)
    assert call(mcp, TOOL, {"answer_id": "없음"})["status"] == "not_found"


def test_store_without_method_is_not_ready():
    mcp = srv.build_server(search_fn=lambda q: [], answer_store_fn=lambda: object())
    assert call(mcp, TOOL, {"answer_id": "a1"})["status"] == "not_ready"


def test_store_failure_is_error_without_exception_text():
    class Broken:
        def get_grounding(self, answer_id):
            raise KeyError("postgres://secret-host/db")

    r = call(srv.build_server(search_fn=lambda q: [], answer_store_fn=Broken), TOOL, {"answer_id": "a1"})
    assert r["status"] == "error" and r["retryable"] is False
    assert "secret-host" not in json.dumps(r, ensure_ascii=False)


def test_public_grounding_handles_skipped_rules_text():
    assert public_grounding({"llm": "off", "rules": "skipped(USE_SKILLS off)"})["rules"] == "skipped(USE_SKILLS off)"


# ---------- 합동 검토 팀 시간 칸 (review.py) ----------

def test_seconds_does_not_change_table_hash():
    """시간 칸이 표 해시로 들어가면 같은 검토의 승인 id가 흔들린다."""
    from backend.graph.departments import issue_table as IT

    base = {"label": "보안", "status": "reviewed", "rows": [], "reason": "", "private_excluded": 0, "dropped": 0}
    a = IT.merge_table("요청", "2026-11-05", ["security"], {"security": base})
    b = IT.merge_table("요청", "2026-11-05", ["security"], {"security": {**base, "seconds": 1.5}})
    assert a["table_hash"] == b["table_hash"]
