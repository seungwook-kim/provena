"""`GET /threads/{thread_id}`의 대화 이력 `messages` 시험 (SDD 4-4, `backend/api/routes.py`의 `_messages`).

새로고침이나 목록 클릭 뒤 화면이 대화를 다시 그릴 수 있게 질문 체크포인트에서 질문·답·근거를 되살린다.
가짜 모델, 합성 검색기, 메모리 체크포인터로 돈다(키·DB 없음).
"""
from __future__ import annotations

import pytest
from api_test_support import Env, ask
from qgraph_fakes import j, normal_llm
from test_api_approval import review_env, start_review

Q1 = "첫 질문: SEV2 장애 최초 대응은 몇 분 이내인가요?"
Q2 = "둘째 질문: SEV2 장애 최초 대응은 몇 분 이내인가요?"
AS_OF = "2025-06-01"
DETAIL_KEYS = {"thread_id", "title", "status", "last", "created_at", "updated_at", "messages"}


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr("backend.graph.departments.review.TEAM_RETRY_WAIT_SECONDS", 0)


def _streamed(ev: list) -> tuple[str, list[dict]]:
    """`/chat` SSE에서 화면이 받은 답 글과 citation data."""
    return "".join(d["data"]["text"] for n, d in ev if n == "token"), [d["data"] for n, d in ev if n == "citation"]


def test_two_questions_come_back_as_four_messages_in_order(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        _, ev1 = ask(c, Q1, "t1", as_of=AS_OF)
        _, ev2 = ask(c, Q2, "t1", as_of=AS_OF)
        r = c.get("/threads/t1")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == DETAIL_KEYS and body["last"]["answer_id"] == ev2[-1][1]["data"]["answer_id"]   # 기존 키는 그대로
        msgs = body["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
        assert [msgs[0]["text"], msgs[2]["text"]] == [Q1, Q2]
        for m, ev in ((msgs[1], ev1), (msgs[3], ev2)):
            text, cites = _streamed(ev)
            done = ev[-1][1]["data"]
            assert m["text"] == text and m["state"] == "done" and m["kind"] == "answer"
            assert m["answer_id"] == done["answer_id"] and m["as_of"] == AS_OF
            assert m["citations"] == [{"id": x["chunk_id"], **x} for x in cites]     # /chat의 citation과 같은 모양
            assert all(x["chunk_id"] and x["id"] == x["chunk_id"] and x["text"] for x in m["citations"])
        assert msgs[1]["answer_id"] != msgs[3]["answer_id"]                          # 질문마다 한 쌍(중간 체크포인트는 버린다)
        stamps = [m["timestamp"] for m in msgs]
        assert all(stamps) and stamps == sorted(stamps)


def test_another_users_thread_is_404_and_never_leaks_messages(monkeypatch):
    with Env(monkeypatch) as env:
        a, b = env.client(env.alice), env.client(env.bob)
        ask(a, "앨리스만 " + Q1, "alice-only", as_of=AS_OF)
        ask(a, "앨리스의 t1 " + Q1, "t1", as_of=AS_OF)
        ask(b, "밥의 t1 " + Q1, "t1", as_of=AS_OF)
        r = b.get("/threads/alice-only")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found" and "messages" not in r.json()
        mine = b.get("/threads/t1").json()["messages"]                               # 같은 바깥 이름이어도 내 체크포인트만 읽는다
        assert [m["text"] for m in mine if m["role"] == "user"] == ["밥의 t1 " + Q1]
        assert "앨리스" not in str(mine)


def test_history_read_failure_gives_empty_messages_not_500(monkeypatch, caplog):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        ask(c, Q1, "t1", as_of=AS_OF)

        def broken(*_a, **_k):
            raise RuntimeError("체크포인트 연결 끊김 postgresql://user:secret@db/x")

        monkeypatch.setattr(env.app.state.question_graph, "get_state_history", broken)
        r = c.get("/threads/t1")
        assert r.status_code == 200 and r.json()["messages"] == [] and r.json()["last"]["kind"] == "answer"
        assert "RuntimeError" in caplog.text and "secret" not in caplog.text            # 예외 종류만 남긴다


def test_refusal_is_no_evidence_without_citations(monkeypatch):
    with Env(monkeypatch, llm=normal_llm(judge=j(sufficient=False, reason="부족", clarify=None))) as env:
        c = env.client(env.alice)
        _, ev = ask(c, Q1, "t1", as_of=AS_OF)
        user, bot = c.get("/threads/t1").json()["messages"]
        assert user["text"] == Q1 and bot["state"] == "no-evidence" and bot["kind"] == "refuse" and bot["citations"] == []
        assert bot["text"] == _streamed(ev)[0]


@pytest.mark.parametrize("llm_kw, reason", [
    ({"judge": j(sufficient=False, reason="부족", clarify=None)}, "no_evidence"),   # 근거를 못 찾음
    ({"classify": j(route="out_of_domain")}, "out_of_domain"),                      # 핸드북 밖 질문
])
def test_refusal_history_carries_the_same_reason_code_as_the_chat_done_event(monkeypatch, llm_kw, reason):
    """H-34: 화면이 새로고침 뒤에도 거절 사유에 맞는 안내만 붙이게, 이력의 거절 답에 `/chat` done과 같은 `refuse_reason`을 싣는다. 답에는 이 칸이 없다."""
    with Env(monkeypatch, llm=normal_llm(**llm_kw)) as env:
        c = env.client(env.alice)
        _, ev = ask(c, Q1, "t1", as_of=AS_OF)
        done = ev[-1][1]["data"]
        assert done["kind"] == "refuse" and done["refuse_reason"] == reason
        _, bot = c.get("/threads/t1").json()["messages"]
        assert bot["kind"] == "refuse" and bot["refuse_reason"] == reason
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        ask(c, Q1, "t1", as_of=AS_OF)
        _, bot = c.get("/threads/t1").json()["messages"]
        assert bot["kind"] == "answer" and "refuse_reason" not in bot


def test_failed_question_keeps_only_the_question(monkeypatch):
    def broken_search(_q):
        raise RuntimeError("검색 실패")

    with Env(monkeypatch, search=broken_search) as env:
        c = env.client(env.alice)
        ask(c, Q1, "t1", as_of=AS_OF)
        assert [(m["role"], m["text"]) for m in c.get("/threads/t1").json()["messages"]] == [("user", Q1)]   # 답이 없었다


def test_approval_turn_waits_then_shows_the_resumed_answer(monkeypatch):
    with review_env(monkeypatch) as env:
        aid = start_review(env)
        a = env.client(env.alice)
        user, bot = a.get("/threads/rv").json()["messages"]
        assert bot == {**bot, "role": "assistant", "state": "approval", "text": "", "citations": []}
        assert env.client(env.admin).post(f"/approvals/{aid}", json={"approve": True, "comment": "확인함"}).status_code == 200
        ask(a, Q1, "rv", as_of=AS_OF)
        msgs = a.get("/threads/rv").json()["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"] and msgs[0]["text"] == user["text"]
        assert msgs[1]["state"] == "done" and msgs[1]["text"]                         # 재개된 답은 같은 질문의 답이다
        assert msgs[2]["text"] == Q1 and msgs[3]["kind"] == "answer" and msgs[3]["citations"]
