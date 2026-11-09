"""평가 점수가 문항별 Langfuse 트레이스에 붙는지 (G6). Langfuse는 가짜다: `tracing._make_client`·`_make_handler`를 바꿔 끼우고
주소는 127.0.0.1로 둔다. 진짜 서버에 보내지 않는다. 기대 점수는 손으로 계산했다(`run_eval._item_scores` 정의)."""
from __future__ import annotations

import uuid

import pytest
from fake_search import fake_search
from langchain_core.callbacks import BaseCallbackHandler
from qgraph_fakes import j, normal_llm

from backend.graph.build import build_graph
from backend.services import tracing
from evals.agent.run_eval import run_eval
from evals.retrieval.gold import GoldRef

SEQ = 90002  # 합성 코퍼스의 장애 대응 런북
ITEMS = [
    {"id": 1, "kind": "relevant", "input": "SEV2 장애 최초 대응은 몇 분 이내인가요?", "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=SEQ, label="런북")]},
    {"id": 2, "kind": "irrelevant", "irrelevant_type": "out_of_domain", "input": "연봉 협상 방법을 알려 주세요", "gold": []},
    {"id": 3, "kind": "relevant", "input": "고장 SEV2 대응", "as_of": "2025-06-01", "gold": [GoldRef(rule_seq=SEQ, label="런북")]},
]
EXPECTED = {  # 문항 id → 그 문항 트레이스에 붙어야 할 점수 전부
    1: {"eval/cited_correct": 1.0, "eval/over_refusal": 0.0, "eval/wrong_citation": 0.0, "eval/hallucination_risk": 0.0, "eval/error": 0.0, "eval/judge_score": 0.5},
    2: {"eval/correct_refusal": 1.0, "eval/error": 0.0},
    3: {"eval/cited_correct": 0.0, "eval/over_refusal": 1.0, "eval/error": 1.0},  # 검색 오류: 거절로 세되 error로 구별
}


class FakeHandler(BaseCallbackHandler):
    """SDK `CallbackHandler`처럼 바깥 실행(부모 없음)마다 trace를 하나 열고 `last_trace_id`를 남긴다."""

    def __init__(self, traces: dict):
        self.last_trace_id = None
        self._traces = traces

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kw):
        if parent_run_id is None:
            self.last_trace_id = uuid.uuid4().hex
            self._traces[self.last_trace_id] = dict(metadata or {})


class FakeClient:
    def __init__(self, fail: bool = False):
        self.scores: list[dict] = []
        self.flushes = 0
        self.fail = fail

    def create_score(self, **kw):
        if self.fail:
            raise RuntimeError("Langfuse 서버 오류(가짜)")
        self.scores.append(kw)

    def flush(self):
        self.flushes += 1

    def shutdown(self):
        pass


class FakeJudge:
    def __init__(self, content='{"grounded": true, "accurate": false, "reason": "x"}'):  # 점수 0.5
        self.content = content

    def invoke(self, msgs):
        return type("M", (), {"content": self.content})()


@pytest.fixture
def fake_langfuse(monkeypatch):
    made = {"clients": [], "traces": {}}

    def make_client(pk, sk, host):
        assert host.startswith("http://127.0.0.1"), host  # 진짜 Langfuse로 가지 않는다
        made["clients"].append(FakeClient(fail=made.get("fail", False)))
        return made["clients"][-1]

    monkeypatch.setattr(tracing, "_make_client", make_client)
    monkeypatch.setattr(tracing, "_make_handler", lambda pk: FakeHandler(made["traces"]))
    for k in ("LANGFUSE_TRACING_ENABLED", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")
    tracing.reset()
    yield made
    tracing.reset()


def _graph():
    def boom(q):
        raise RuntimeError("검색 실패")

    def judge(user):
        return j(sufficient=False, reason="없음", clarify=None) if "연봉" in user else j(sufficient=True)

    ok = build_graph(fake_search, llm=normal_llm(judge=judge), grounding_llm=False)
    bad = build_graph(boom, llm=normal_llm(), grounding_llm=False)

    class Dispatch:  # '고장' 문항은 그래프 안에서 검색이 실패한다(트레이스는 생긴다)
        def invoke(self, inp, config=None):
            return (bad if "고장" in inp["question"] else ok).invoke(inp, config)

    return Dispatch()


def test_item_scores_land_on_that_items_trace(fake_langfuse):
    report = run_eval(_graph(), ITEMS, judge_llm=FakeJudge(), run_id="eval-question-t")
    (client,) = fake_langfuse["clients"]
    traces = fake_langfuse["traces"]
    assert len(traces) == len(ITEMS)  # 문항마다 트레이스 하나
    for row in report["rows"]:
        tid = row["trace_id"]
        assert tid in traces and traces[tid]["item_id"] == str(row["id"])  # rows.jsonl의 trace_id = 그 문항 트레이스
        assert traces[tid]["langfuse_session_id"] == "eval-question-t"
        got = {s["name"]: s["value"] for s in client.scores if s.get("trace_id") == tid}
        assert got == EXPECTED[row["id"]], row["id"]
    assert len({r["trace_id"] for r in report["rows"]}) == len(ITEMS)
    item_scores = [s for s in client.scores if s.get("trace_id")]
    assert len(item_scores) == sum(len(v) for v in EXPECTED.values())  # 남는 점수(엉뚱한 trace)가 없다
    session = {s["name"]: s["value"] for s in client.scores if s.get("session_id")}
    assert all(s.get("session_id") in (None, "eval-question-t") for s in client.scores)
    assert session["eval/errors"] == 1.0 and session["eval/over_refusal_rate"] == 0.5 and session["eval/judge_score"] == 0.5
    assert report["run_id"] == "eval-question-t" and client.flushes >= 1


def test_judge_failure_is_not_scored(fake_langfuse):
    report = run_eval(_graph(), ITEMS[:1], judge_llm=FakeJudge("모르겠음"), run_id="eval-question-t")
    (client,) = fake_langfuse["clients"]
    assert report["rows"][0]["judge"]["score"] is None
    assert "eval/judge_score" not in {s["name"] for s in client.scores}


def test_score_failure_does_not_break_the_eval(fake_langfuse):
    fake_langfuse["fail"] = True
    report = run_eval(_graph(), ITEMS, judge_llm=FakeJudge(), run_id="eval-question-t")
    assert [r["result"] for r in report["rows"]] == ["answer", "refuse", "error"]
    assert report["metrics"]["errors"] == 1 and fake_langfuse["clients"][0].scores == []


def test_without_keys_nothing_is_sent(fake_langfuse, monkeypatch):
    monkeypatch.delenv("LANGFUSE_SECRET_KEY")
    report = run_eval(_graph(), ITEMS, judge_llm=FakeJudge(), run_id="eval-question-t")
    assert fake_langfuse["clients"] == [] and fake_langfuse["traces"] == {}
    assert [r["trace_id"] for r in report["rows"]] == [None, None, None]
    assert report["metrics"]["n"] == 3
