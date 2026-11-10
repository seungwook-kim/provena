"""0원 시험: 녹화 래퍼(RecordingChatModel)로 녹화한 응답을 재생(ReplayChatModel)이 그래프가 읽는 그대로 돌려주는가.
배경(2026-11-10 재녹화 실패): 추론을 켠 단계(decompose, judge, answer)는 Anthropic이 [생각 블록, 글 블록] 목록을 돌려주는데, 녹화가 그 목록을 JSON 글로 적어
재생이 `[{"signature": ...` 문자열을 응답으로 내서 그래프가 JSON을 못 읽고 다른 경로(재작성, 재검색)로 가 녹화에 없는 요청이 나왔다.
가짜 LLM(결정적 응답, 일부 단계는 지연 포함)과 가짜 임베딩 키만 쓴다. LLM·Voyage·DB 호출 없음.
"""
from __future__ import annotations

import json
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.graph.build import _text
from backend.services import demo_replay as dr

THINKING_ROLES = {"decompose": 0.3, "judge": 0.2, "answer": 0.4}   # 추론 단계: 블록 목록 응답 + 지연(시간 상한·hedge 분기를 흉내)
PLAIN_ROLES = {"classify": 0.0, "decompose_gate": 0.0, "rewrite": 0.0, "answer_fast": 0.1}


class FakeAnthropic:
    """실제 모델 대신. 추론 단계는 Anthropic처럼 [thinking, text] 블록 목록, 나머지는 글 하나를 돌려준다."""

    model = "fake-haiku"

    def invoke(self, messages, stop=None, **kw):
        role = dr.message_role(messages)
        question = messages[-1].content
        payload = json.dumps({"role": role, "q": question[:20], "split": role == "decompose"}, ensure_ascii=False)
        time.sleep({**THINKING_ROLES, **PLAIN_ROLES}.get(role, 0.0))
        if role in THINKING_ROLES:
            return AIMessage(content=[{"type": "thinking", "thinking": "생각", "signature": "SIG=="}, {"type": "text", "text": payload}])
        return AIMessage(content=payload)


def _msgs(role: str, q: str) -> list:
    return [SystemMessage(content=f"[[task:{role}]]\n규칙"), HumanMessage(content=f"질문: {q}")]


@pytest.fixture()
def recorded_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(tmp_path))
    dr._stores.pop(str(tmp_path), None)
    rec = dr.RecordingChatModel(inner=FakeAnthropic(), model_name="fake", store=dr.ReplayStore(tmp_path))
    seen = {}
    for role in [*THINKING_ROLES, *PLAIN_ROLES]:
        m = _msgs(role, "외부 SaaS 5만 달러 승인자는?")
        seen[role] = _text(rec.invoke(m))   # 녹화 때 그래프가 읽는 글
    return tmp_path, seen


def test_replay_returns_what_the_graph_read_when_recording(recorded_dir):
    path, seen = recorded_dir
    replay = dr.ReplayChatModel(store=dr.ReplayStore(path))
    for role, expected in seen.items():
        got = _text(replay.invoke(_msgs(role, "외부 SaaS 5만 달러 승인자는?")))
        assert json.loads(got)["role"] == role, f"{role}: 재생 응답이 JSON 객체가 아니다: {got[:80]!r}"
        assert got == expected, f"{role}: 녹화 때 그래프가 읽은 글과 재생 글이 다르다"
    assert replay.misses == 0 and replay.hits == len(seen)


def test_recorded_rows_never_hold_block_lists(recorded_dir):
    path, _ = recorded_dir
    rows = [json.loads(x) for x in (path / dr.RECORD_FILE).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and all(not r["response"].lstrip().startswith("[{") for r in rows), "녹화 줄에 생각 블록 목록(JSON)이 들어 있다"
