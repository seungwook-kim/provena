"""사용자별 분리 시험 (G4): 대화(thread)와 장기 기억(Store namespace)이 로그인한 사용자 id로 나뉘는지.

D7 확인 절차(평가용 계정 A·B)를 사용자별 `TestClient`(쿠키 분리)로 재현한다. 가짜 모델, 메모리 체크포인터, 메모리 Store로 돈다."""
from __future__ import annotations

from api_test_support import Env, ask

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
AS_OF = "2025-06-01"


def test_same_client_thread_id_is_two_separate_threads(monkeypatch):
    with Env(monkeypatch) as env:
        a, b = env.client(env.alice), env.client(env.bob)
        ask(a, "앨리스의 질문 " + Q, "t1", as_of=AS_OF)
        ask(b, "밥의 질문 " + Q, "t1", as_of=AS_OF)
        (mine,) = a.get("/threads").json()["threads"]
        (theirs,) = b.get("/threads").json()["threads"]
        assert mine["thread_id"] == theirs["thread_id"] == "t1"
        assert mine["title"].startswith("앨리스") and theirs["title"].startswith("밥")
        g = env.app.state.question_graph
        for who, name in ((env.alice, "앨리스"), (env.bob, "밥")):
            values = g.get_state({"configurable": {"thread_id": f"{who.user_id}:t1"}}).values
            assert values["question"].startswith(name) and values["user_id"] == str(who.user_id)


def test_user_cannot_read_anothers_thread(monkeypatch):
    with Env(monkeypatch) as env:
        ask(env.client(env.alice), Q, "alice-only", as_of=AS_OF)
        r = env.client(env.bob).get("/threads/alice-only")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"   # 없는 것과 같은 응답
        assert env.client(env.bob).get("/threads").json() == {"threads": []}
        assert env.client(env.alice).get("/threads/alice-only").status_code == 200


def test_long_term_memory_is_per_user(monkeypatch):
    with Env(monkeypatch) as env:
        a, b = env.client(env.alice), env.client(env.bob)
        r = a.patch("/me/memory", json={"affiliation": "TEST-security"})
        assert r.status_code == 200 and r.json() == {"user_id": str(env.alice.user_id), "profile": {"affiliation": "TEST-security"}}
        assert b.get("/me/memory").json() == {"user_id": str(env.bob.user_id), "profile": {}, "allowed_fields": ["affiliation", "rank"]}
        b.patch("/me/memory", json={"affiliation": "TEST-finance"})
        assert a.get("/me/memory").json()["profile"] == {"affiliation": "TEST-security"}
        store = env.app.state.store                                        # 저장 위치도 직접 본다
        assert store.get((str(env.alice.user_id), "profile"), "me").value == {"affiliation": "TEST-security"}
        assert store.get((str(env.bob.user_id), "profile"), "me").value == {"affiliation": "TEST-finance"}


def test_memory_patch_is_partial_and_delete_only_clears_own(monkeypatch):
    with Env(monkeypatch) as env:
        a, b = env.client(env.alice), env.client(env.bob)
        a.patch("/me/memory", json={"affiliation": "TEST-security"})
        assert a.patch("/me/memory", json={"rank": "매니저"}).json()["profile"] == {"affiliation": "TEST-security", "rank": "매니저"}
        b.patch("/me/memory", json={"rank": "디렉터"})
        r = a.delete("/me/memory")
        assert r.status_code == 200 and r.json() == {"user_id": str(env.alice.user_id), "profile": {}}
        assert a.get("/me/memory").json()["profile"] == {} and b.get("/me/memory").json()["profile"] == {"rank": "디렉터"}


def test_memory_accepts_only_allowed_fields(monkeypatch):
    with Env(monkeypatch) as env:
        a = env.client(env.alice)
        for body in ({}, {"team": "x"}, {"affiliation": "A", "question": "대화 내용"}, {"affiliation": "x" * 101}):
            r = a.patch("/me/memory", json=body)
            assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", body
        assert a.get("/me/memory").json()["profile"] == {}


def test_request_cannot_choose_another_user_id(monkeypatch):
    with Env(monkeypatch) as env:
        a, b = env.client(env.alice), env.client(env.bob)
        b.patch("/me/memory", json={"affiliation": "TEST-finance"})
        r = a.get(f"/me/memory?user_id={env.bob.user_id}")
        assert r.json()["user_id"] == str(env.alice.user_id) and r.json()["profile"] == {}
        r = a.patch("/me/memory", json={"affiliation": "X", "user_id": str(env.bob.user_id)})
        assert r.status_code == 422 and b.get("/me/memory").json()["profile"] == {"affiliation": "TEST-finance"}
        r = a.post("/chat", json={"message": Q, "thread_id": "t1", "user_id": str(env.bob.user_id)})
        assert r.status_code == 422 and b.get("/threads").json() == {"threads": []}


def test_memory_changes_need_login_and_csrf(monkeypatch):
    with Env(monkeypatch) as env:
        assert env.client(None).get("/me/memory").json()["error"]["code"] == "unauthorized"
        no_csrf = env.client(env.alice, csrf=False)
        for r in (no_csrf.patch("/me/memory", json={"affiliation": "A"}), no_csrf.delete("/me/memory")):
            assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
        assert no_csrf.get("/me/memory").status_code == 200                 # 읽기는 CSRF 검사가 없다
        assert env.client(env.alice).get("/me/memory").json()["profile"] == {}


def test_memory_is_read_by_the_next_question(monkeypatch):
    with Env(monkeypatch) as env:
        a = env.client(env.alice)
        a.patch("/me/memory", json={"affiliation": "TEST-finance", "rank": "매니저"})
        ask(a, Q, "t1", as_of=AS_OF)
        ask(env.client(env.bob), Q, "t1", as_of=AS_OF)
        g = env.app.state.question_graph
        assert g.get_state({"configurable": {"thread_id": f"{env.alice.user_id}:t1"}}).values["profile"] == {"affiliation": "TEST-finance", "rank": "매니저"}
        assert g.get_state({"configurable": {"thread_id": f"{env.bob.user_id}:t1"}}).values["profile"] == {}
