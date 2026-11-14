"""기본 날짜("오늘")는 서버(UTC) 날짜가 아니라 한국 날짜다 (놓친 것 D-15).

서버 시계가 2026-11-14 16:30 UTC이면 한국은 2026-11-15 01:30이다(`test_today_kst_is_the_korean_calendar_date`). 호출하는 곳 시험은 시험을 돌리는 날과
겹치지 않게 먼 날짜(2027-03-01 16:30 UTC = 한국 2027-03-02 01:30)로 시계를 세운다(돌리는 PC의 오늘과 같으면 고치기 전 코드도 통과한다). 사용자에게 보이는 기본 날짜(답의 기준일, 팀 검토 기준일,
변경 목록의 "최근 30일" 시작일, 영향 미리보기 만든 날, 기간 판정의 올해)가 모두 한국 날짜로 나오는지 본다. DB·키·네트워크 없이 돈다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from api_test_support import Env
from fake_search import fake_search
from qgraph_fakes import normal_llm
from recall_test_support import changed, reader
from team_review_fakes import Retriever, review_llm

from backend.graph import grounding as G
from backend.graph import state as S
from backend.graph.answer_store import InMemoryAnswerStore
from backend.graph.build import build_graph
from backend.graph.departments import single_review as SR
from backend.graph.departments.review import build_review_graph
from backend.graph.recall.impact import preview_impact

UTC_EVENING = datetime(2027, 3, 1, 16, 30, tzinfo=timezone.utc)   # 한국 2027-03-02 01:30
KST_TODAY = "2027-03-02"
Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(S, "_utcnow", lambda: UTC_EVENING)


@pytest.mark.parametrize("utc, want", [
    (datetime(2026, 11, 14, 14, 59, tzinfo=timezone.utc), "2026-11-14"),   # 한국 23:59, 아직 14일
    (datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc), "2026-11-15"),    # 한국 00:00, 15일로 넘어감
    (datetime(2026, 11, 14, 16, 30, tzinfo=timezone.utc), "2026-11-15"),   # 조장 목록 D-15의 예: 한국 01:30
    (UTC_EVENING, KST_TODAY),
    (datetime(2026, 12, 31, 16, 0, tzinfo=timezone.utc), "2027-01-01"),    # 해가 바뀌는 날
])
def test_today_kst_is_the_korean_calendar_date(monkeypatch, utc, want):
    monkeypatch.setattr(S, "_utcnow", lambda: utc)
    assert S.today_kst().isoformat() == want


def test_question_graph_default_as_of_is_korean_today(frozen):
    seen = []

    def search(q):
        seen.append(q.as_of)
        return fake_search(q)

    out = build_graph(search, llm=normal_llm()).invoke({"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": None})
    assert out["as_of"] == KST_TODAY and out["as_of_given"] is False and set(seen) == {KST_TODAY}
    assert f"기준일 {KST_TODAY}" in out["answer"]


def test_given_as_of_is_kept_as_is(frozen):
    out = build_graph(fake_search, llm=normal_llm()).invoke({"question": Q, "user_id": "u1", "thread_id": "t1", "as_of": "2025-06-01"})
    assert out["as_of"] == "2025-06-01" and out["as_of_given"] is True


def test_team_review_default_as_of_is_korean_today(frozen):
    g = build_review_graph(Retriever(), None, llm=review_llm())
    out = g.invoke({"question": "", "user_id": "u1", "thread_id": "t1"})
    assert out["as_of"] == KST_TODAY and out["review_status"] == "clarify"


def test_single_review_default_as_of_is_korean_today(frozen):
    r = Retriever()
    SR.run_single("새 외부 SaaS 모니터링 도구를 연 4만 달러에 도입하려 한다.", None, retriever=r, llm=review_llm(), search="undivided", wide_retriever=r)
    assert r.calls and {c.as_of for c in r.calls} == {KST_TODAY}


def test_changes_default_window_starts_30_days_before_korean_today(frozen, monkeypatch):
    with Env(monkeypatch) as env:
        store = env.app.state.change_store
        store.add(changed(article="Edge", new="2027-01-30"))   # UTC 날짜(03-01)로 세면 30일 전이 01-30이라 목록에 들어온다
        store.add(changed(article="In", new="2027-01-31"))     # 한국 날짜(03-02)의 30일 전
        items = env.client(env.alice).get("/changes").json()["items"]
    assert [i["article"] for i in items] == ["In"]


def test_impact_preview_generated_on_is_korean_today(frozen):
    rep = preview_impact([changed()], answers=InMemoryAnswerStore(), read_section=reader())
    assert rep.generated_on == KST_TODAY


def test_period_rule_uses_the_korean_year(monkeypatch):
    """12월 31일 16:00 UTC는 한국 1월 1일이다. 그 해(2027)를 묻는 개정 이력 질문을 기간 밖으로 거절하지 않는다."""
    monkeypatch.setattr(S, "_utcnow", lambda: datetime(2026, 12, 31, 16, 0, tzinfo=timezone.utc))
    row = {"chunk_id": "c1", "version_date": "2026-10-27", "fetched_at": "2026-10-27", "text": "Approval limits are reviewed every year.",
           "rule_title": "Approval", "article": "Limits"}
    verdict = G.check_rules("2027년 기준으로 승인 한도가 바뀌었나요?", [row], [row])
    assert verdict.reason != G.OUT_OF_PERIOD
    monkeypatch.setattr(S, "_utcnow", lambda: datetime(2026, 12, 31, 14, 0, tzinfo=timezone.utc))   # 한국도 아직 2026년
    assert G.check_rules("2027년 기준으로 승인 한도가 바뀌었나요?", [row], [row]).reason == G.OUT_OF_PERIOD


def test_replay_request_key_ignores_the_default_date_in_prompts():
    """기준일 기본값이 한국 날짜로 바뀌어도(하루 차이) 키 없는 데모의 녹화 요청 키는 같다: 답·다시 쓰기·근거 확인 프롬프트의 맨 앞 `기준일:` 줄은 키에서 지운다."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.prompts import question as P
    from backend.services.demo_replay import request_key

    chunks = [fake_search(type("Q", (), {"query": Q, "org": None, "as_of": None, "k": 5, "sub_queries": None})())[0].model_dump()]

    def keys(as_of):
        users = [P.answer_user(Q, chunks, as_of), P.redraft_user(Q, chunks, as_of, "초안", "사유", ["주장"]), P.grounding_user(Q, "답", chunks, as_of)]
        return [request_key([SystemMessage(content="[[task:answer]]"), HumanMessage(content=u)]) for u in users]

    assert keys("2026-11-14") == keys("2026-11-15")
