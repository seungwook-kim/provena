"""`POST /chat`(SSE)와 대화 목록 시험 (SDD 4-4, `backend/api/routes.py`). 가짜 모델, 합성 검색기, 메모리 체크포인터로 돈다(키·DB 없음)."""
from __future__ import annotations

from api_test_support import Env, ask
from qgraph_fakes import j, normal_llm

from backend.services.cost import CostCapExceeded

Q = "SEV2 장애 최초 대응은 몇 분 이내인가요?"
AS_OF = "2025-06-01"
SECRET_TEXT = "postgresql://user:secret-password@db/x"


def test_chat_streams_agent_events_over_sse(monkeypatch):
    with Env(monkeypatch) as env:
        r, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-request-id"] and r.headers["x-accel-buffering"] == "no"
        names = [n for n, _ in ev]
        assert names[0] == "token" and names[-1] == "done" and names.count("done") == 1 and names.count("citation") == 1
        assert all(d["thread_id"] == "t1" and d["type"] == n for n, d in ev)   # 바깥 이름으로 내보낸다
        assert "".join(d["data"]["text"] for n, d in ev if n == "token").startswith("근거에 따라")
        cite = next(d["data"] for n, d in ev if n == "citation")
        assert {"chunk_id", "rule_title", "article", "version_date", "version_date_before", "source_url"} <= set(cite) and cite["text"]
        done = ev[-1][1]["data"]
        assert done["kind"] == "answer" and done["as_of"] == AS_OF and done["answer_id"] and "code" not in done
        assert done["attribution"]["license"] == "CC BY-SA 4.0" and done["attribution"]["modified"] is True
        assert set(done["usage"]) == {"input_tokens", "output_tokens", "cost_usd", "calls"}


def test_server_makes_a_thread_id_when_none_is_given(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        _, ev = ask(c, Q, as_of=AS_OF)
        tid = ev[-1][1]["thread_id"]
        assert tid.startswith("t-") and len(tid) == 14
        assert [t["thread_id"] for t in c.get("/threads").json()["threads"]] == [tid]


def test_graph_and_checkpoint_use_the_user_prefixed_thread(monkeypatch):
    with Env(monkeypatch) as env:
        ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
        uid = str(env.alice.user_id)
        values = env.app.state.question_graph.get_state({"configurable": {"thread_id": f"{uid}:t1"}}).values
        assert values["user_id"] == uid and values["thread_id"] == f"{uid}:t1"
        assert env.app.state.question_graph.get_state({"configurable": {"thread_id": "t1"}}).values == {}
        (saved,) = env.app.state.answer_store.all_answers()
        assert saved["user_id"] == uid and saved["thread_id"] == f"{uid}:t1"


def test_refusal_ends_with_no_results(monkeypatch):
    with Env(monkeypatch, llm=normal_llm(judge=j(sufficient=False, reason="부족", clarify=None))) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
        done = ev[-1][1]["data"]
        assert ev[-1][0] == "done" and done["kind"] == "refuse" and done["code"] == "no_results" and "attribution" not in done
        assert [n for n, _ in ev].count("citation") == 0


def test_error_event_hides_the_exception_text(monkeypatch):
    def broken_search(_q):
        raise RuntimeError(f"검색 실패 {SECRET_TEXT}")

    with Env(monkeypatch, search=broken_search) as env:
        c = env.client(env.alice)
        r, ev = ask(c, Q, "t1", as_of=AS_OF)
        assert [n for n, _ in ev] == ["error"]
        data = ev[0][1]["data"]
        assert data["code"] == "internal_error" and data["message"] and data["request_id"] == r.headers["x-request-id"]
        assert "secret-password" not in r.text and "RuntimeError" not in r.text
        (item,) = c.get("/threads").json()["threads"]
        assert item["status"] == "idle"                     # 다음 질문을 받을 수 있다


def _index_not_ready_error() -> RuntimeError:
    """검색기가 색인 미준비(index_meta 없음)일 때 실제로 내는 예외. 문구가 바뀌면 이 시험이 먼저 깨진다."""
    from types import SimpleNamespace

    from backend.rag.retrieve.search import Searcher
    try:
        Searcher._check_meta(SimpleNamespace(store=SimpleNamespace(meta=lambda: None), cfg=None))
    except RuntimeError as exc:
        return exc
    raise AssertionError("색인 미준비 예외가 나지 않았다")


def test_index_not_ready_is_a_refusal_not_an_error(monkeypatch, caplog):
    def not_ready(_q):
        raise _index_not_ready_error()

    with Env(monkeypatch, search=not_ready) as env:
        c = env.client(env.alice)
        with caplog.at_level("WARNING", logger="backend.api.routes"):
            r, ev = ask(c, Q, "t1", as_of=AS_OF)
        assert [n for n, _ in ev] == ["token", "done"]
        assert ev[0][1]["data"]["text"] == "검색 색인이 아직 준비되지 않아 답할 수 없습니다."
        done = ev[-1][1]["data"]
        assert done["kind"] == "refuse" and done["code"] == "no_results" and done["answer_id"] is None and done["as_of"] == AS_OF
        assert set(done["usage"]) == {"input_tokens", "output_tokens", "cost_usd", "calls"} and "attribution" not in done
        assert "index_meta" not in r.text and "RuntimeError" not in r.text          # 원인은 화면에 내지 않는다
        assert any("색인 미준비" in m and "index_meta" in m for m in caplog.messages)  # 서버 로그에는 남긴다
        (item,) = c.get("/threads").json()["threads"]
        assert item["status"] == "idle"
        last = c.get("/threads/t1").json()["last"]
        assert last["kind"] == "refuse" and last["answer"] == "검색 색인이 아직 준비되지 않아 답할 수 없습니다."


def test_other_runtime_errors_stay_internal_error(monkeypatch):
    def mismatch(_q):
        raise RuntimeError("색인 장부와 지금 설정이 다르다: 장부 {}, 설정 {}")

    with Env(monkeypatch, search=mismatch) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
        assert [n for n, _ in ev] == ["error"] and ev[0][1]["data"]["code"] == "internal_error"


def test_cost_cap_is_limit_exceeded(monkeypatch):
    def capped(_q):
        raise CostCapExceeded(0.02, 0.01)

    with Env(monkeypatch, search=capped) as env:
        _, ev = ask(env.client(env.alice), Q, "t1", as_of=AS_OF)
        assert [n for n, _ in ev] == ["error"] and ev[0][1]["data"]["code"] == "limit_exceeded"


def test_threads_list_and_detail(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        ask(c, Q, "t1", as_of=AS_OF)
        ask(c, "두 번째 대화 질문", "t2", as_of=AS_OF)
        ask(c, "같은 대화의 다음 질문", "t1", as_of=AS_OF)
        items = c.get("/threads").json()["threads"]
        assert [t["thread_id"] for t in items] == ["t1", "t2"]                     # 최근 순
        assert items[0]["title"] == Q and set(items[0]) == {"thread_id", "title", "status", "created_at", "updated_at"}
        assert all(t["status"] == "idle" for t in items)
        detail = c.get("/threads/t1").json()
        assert detail["title"] == Q and detail["last"]["kind"] == "answer" and detail["last"]["answer"].startswith("근거에 따라")
        assert detail["last"]["as_of"] == AS_OF and detail["last"]["answer_id"]
        missing = c.get("/threads/nope")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"


def test_title_is_the_first_question_cut_to_80_chars(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        ask(c, "가" * 200, "t1", as_of=AS_OF)
        assert c.get("/threads/t1").json()["title"] == "가" * 80


def test_chat_validation_errors_use_the_common_error_shape(monkeypatch):
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        for body in ({"message": ""}, {"message": "x" * 4001}, {}, {"message": Q, "thread_id": "bad id!"}, {"message": Q, "as_of": "2025/06/01"},
                     {"message": Q, "user_id": str(env.bob.user_id)}):
            r = c.post("/chat", json=body)
            err = r.json()["error"]
            assert r.status_code == 422 and err["code"] == "validation_error" and err["request_id"] == r.headers["x-request-id"], body
            assert all(set(d) == {"loc", "msg", "type"} for d in err["details"])
        r = c.post("/chat", json={"message": "", "password": "hunter2-secret"})
        assert "hunter2-secret" not in r.text                 # 입력값은 되돌리지 않는다


def test_chat_requires_login_and_csrf(monkeypatch):
    with Env(monkeypatch) as env:
        r = env.client(None).post("/chat", json={"message": ""})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"   # 로그인 확인이 본문 검사보다 먼저다
        r = env.client(env.alice, csrf=False).post("/chat", json={"message": Q})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
        assert env.client(env.alice).get("/threads").json() == {"threads": []}      # 막힌 요청은 대화를 만들지 않는다


def test_chat_is_503_when_the_runtime_did_not_open(monkeypatch):
    def refuse(*_a, **_k):
        raise RuntimeError("연결 실패")

    monkeypatch.setattr("backend.graph.decision.routes.open_persistence", refuse)
    with Env(monkeypatch) as env:
        c = env.client(env.alice)
        for r in (c.post("/chat", json={"message": Q}), c.get("/threads"), c.get("/me/memory")):
            assert r.status_code == 503 and r.json()["error"]["code"] == "not_configured"
        assert c.get("/health").status_code == 200


def test_unknown_post_is_common_404_and_existing_route_method_is_405(monkeypatch, tmp_path):
    # CI의 Python-only 실행처럼 React dist가 없는 legacy 정적 화면도 확인한다.
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "login.html").write_text("legacy", encoding="utf-8")
    monkeypatch.setattr("backend.main.WEB_DIR", web_dir)
    with Env(monkeypatch) as env:
        client = env.client(env.alice)
        unknown = client.post("/does-not-exist", json={})
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "not_found"

        wrong_method = client.post("/threads")
        assert wrong_method.status_code == 405
        assert wrong_method.json()["error"]["code"] == "method_not_allowed"

        # K-12: 정적 마운트(/)는 GET·HEAD만 받아도, 없는 경로는 어떤 메서드든 같은 404 규약이어야 한다
        for method in ("post", "put", "patch", "delete"):
            r = getattr(client, method)("/does-not-exist/deep")
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", method
        # 경로는 있고 메서드만 틀린 경우는 404가 아니라 405
        for method in ("put", "patch", "delete", "post"):
            r = getattr(client, method)("/health")
            assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed", method
        assert client.put("/health").headers["Allow"] == "GET"      # RFC 9110: 405에는 허용 메서드를 알린다


def test_legacy_root_redirects_when_react_dist_is_missing(monkeypatch, tmp_path):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "login.html").write_text("legacy", encoding="utf-8")
    monkeypatch.setattr("backend.main.WEB_DIR", web_dir)
    with Env(monkeypatch) as env:
        response = env.client(env.alice).get("/", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"] == "/login.html"


def test_react_root_and_approvals_accept_headers_are_separated(monkeypatch, tmp_path):
    web_dir = tmp_path / "web"
    index = web_dir / "react-app" / "dist" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<div id=\"root\">react</div>", encoding="utf-8")
    monkeypatch.setattr("backend.main.WEB_DIR", web_dir)
    with Env(monkeypatch) as env:
        client = env.client(env.alice)
        assert client.get("/").status_code == 200
        assert client.get("/", headers={"Accept": "text/html"}).text == index.read_text(encoding="utf-8")
        assert client.get("/approvals", headers={"Accept": "text/html"}).text == index.read_text(encoding="utf-8")
        assert client.get("/approvals", headers={"Accept": "application/json"}).status_code == 403
