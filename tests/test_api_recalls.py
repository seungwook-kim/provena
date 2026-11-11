"""리콜 API 시험 (F-02, F-05, F-06, F-08, docs/specs/recall.md AC-01~AC-06, EC-06·EC-10·EC-11).

가짜 모델·메모리 저장소로 앱을 띄운다(키·네트워크·DB 없음). 키가 없어 판정은 규칙 판정이다. 웹훅은 `post`를 바꿔 넣는다.
"""
from __future__ import annotations

import dataclasses

import pytest
from api_test_support import CSRF, Env, FakeAuthStore
from recall_test_support import ARTICLE, SEQ, WORDING_NEW, WORDING_OLD, changed, reader, save_answer

from backend.graph.recall.acl import MemoryAcl
from backend.graph.recall.maintenance import MemoryLinks
from backend.graph.recall.webhook import SIGNATURE_HEADER, WebhookSender, verify_signature

SECRET = "test-webhook-secret"
SERVICE_KEY = "test-service-key"
CHANGE = changed().model_dump()


class Post:
    def __init__(self, *codes):
        self.codes, self.calls = list(codes) or [200], []

    def __call__(self, url, content, headers):
        self.calls.append((url, content, dict(headers)))
        return self.codes[min(len(self.calls), len(self.codes)) - 1]


@pytest.fixture
def env(monkeypatch):
    for k in ("RECALL_DIGEST", "RECALL_MIN_CONFIDENCE", "RECALL_FEEDBACK_THRESHOLD", "RECALL_STORE", "SERVICE_API_KEY",
              "RECALL_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with Env(monkeypatch) as e:
        svc = e.app.state.recall_service
        svc.read_section = reader()
        save_answer(svc.answers, "a-alice", str(e.alice.user_id))
        save_answer(svc.answers, "a-bob", str(e.bob.user_id))
        e.svc = svc
        e.post = Post()
        svc.sender = WebhookSender(svc.store, post=e.post, sleep=lambda s: None, max_tries=3, backoff=0.0, local_demo=False)
        yield e


def seed(env, read=None) -> dict:
    """개정 하나를 처리해 alice·bob 알림을 만든다. {사용자 login_id: notice_id}."""
    if read is not None:
        env.svc.read_section = read
    env.svc.process(changed())
    ids = {}
    for r in env.svc.store.notices_all():
        who = env.alice if r["user_id"] == str(env.alice.user_id) else env.bob
        ids[who.login_id] = r["notice_id"]
    return ids


# ---------------------------------------------------------------- 로그인·권한


@pytest.mark.parametrize("method,path", [("get", "/recalls"), ("get", "/recalls/rn-x"), ("post", "/recalls/rn-x/ack"),
                                         ("post", "/recalls/rn-x/feedback"), ("get", "/recalls/digests"), ("get", "/changes")])
def test_login_required(env, method, path):
    r = getattr(env.client(), method)(path, **({"json": {"useful": True}} if method == "post" else {}))
    assert r.status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("get", "/recalls/feedback-stats", None), ("post", "/recalls/digest/flush", None), ("post", "/recalls/process-pending", None),
    ("post", "/recalls/rn-x/review", {"action": "release"}), ("get", "/webhook-subscriptions", None),
    ("post", "/webhook-subscriptions", {"url": "https://hooks.example.com/x"}), ("get", "/webhook-deliveries", None),
    ("get", "/maintenance-candidates", None), ("post", "/maintenance-candidates/mc-x", {"status": "needed"}),
    ("post", "/impact-preview", {"changes": [CHANGE]}), ("put", "/changes/monitoring", {"status": "paused"}),
])
def test_admin_only(env, method, path, body):
    """AC-04: 후보·검토함·구독 등 관리 기능은 일반 사용자에게 403."""
    r = getattr(env.client(env.alice), method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 403


@pytest.mark.parametrize("method,path,body", [
    ("post", "/recalls/{id}/ack", None), ("post", "/recalls/{id}/feedback", {"useful": False}),
])
def test_csrf_required_for_user_writes(env, method, path, body):
    ids = seed(env)
    r = getattr(env.client(env.alice, csrf=False), method)(path.format(id=ids["alice"]), **({"json": body} if body else {}))
    assert r.status_code == 403


@pytest.mark.parametrize("method,path,body", [
    ("post", "/recalls/digest/flush", None), ("post", "/recalls/process-pending", None),
    ("post", "/webhook-subscriptions", {"url": "https://hooks.example.com/x"}), ("post", "/impact-preview", {"changes": [CHANGE]}),
    ("put", "/changes/monitoring", {"status": "paused"}), ("post", "/maintenance-candidates/mc-x", {"status": "needed"}),
])
def test_csrf_required_for_admin_writes(env, method, path, body):
    r = getattr(env.client(env.admin, csrf=False), method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 403


# ---------------------------------------------------------------- 알림 목록·한 건


def test_user_sees_only_own_notices(env):
    """AC-02: 알림은 그 답을 받은 사용자에게만 간다. 남의 알림은 404."""
    ids = seed(env)
    r = env.client(env.alice).get("/recalls")
    assert r.status_code == 200
    body = r.json()
    assert [n["notice_id"] for n in body["items"]] == [ids["alice"]] and body["unread"] == 1
    assert "review_queue" not in body and "candidates" not in body
    assert env.client(env.alice).get(f"/recalls/{ids['alice']}").json()["answer_id"] == "a-alice"
    other = env.client(env.alice).get(f"/recalls/{ids['bob']}")
    assert other.status_code == 404 and other.json()["error"]["code"] == "not_found"
    assert env.client(env.alice).get("/recalls/rn-none").status_code == 404


def test_notice_json_shape_over_api(env):
    ids = seed(env)
    n = env.client(env.alice).get(f"/recalls/{ids['alice']}").json()
    assert set(n) == {"notice_id", "answer_id", "user_id", "thread_id", "question", "answer_excerpt", "changed", "conclusion_changed",
                      "explanation", "severity", "confidence", "needs_review", "acked", "created_at", "source_url", "old_text", "new_text"}
    assert set(n["changed"]) == {"rule_seq", "article", "old_version_date", "new_version_date", "change_type"}
    assert n["severity"] == "high" and 0.0 <= n["confidence"] <= 1.0 and n["needs_review"] is False and n["thread_id"] == "t1"


def test_admin_list_has_queue_candidates_and_failures(env):
    env.svc.links = MemoryLinks([{"rule_seq": 90003, "article": "Procurement", "title": "SaaS 도입 정책", "target": SEQ}])
    seed(env)
    body = env.client(env.admin).get("/recalls").json()
    assert len(body["items"]) == 2 and body["unread"] == 0
    assert body["review_queue"] == [] and len(body["candidates"]) == 1 and body["judge_failures"] == []
    assert set(body["candidates"][0]) == {"candidate_id", "upper_rule", "upper_version_id", "rule_seq", "article", "reason", "status",
                                          "decided_by"}


def test_admin_can_read_any_notice(env):
    ids = seed(env)
    assert env.client(env.admin).get(f"/recalls/{ids['bob']}").status_code == 200


def test_judge_failures_listed_for_admin(env):
    """EC-01, AC-05: 원문을 못 읽어 판정이 깨진 알림도 사용자에게 가고, 관리자 목록의 실패 목록에 남는다."""
    ids = seed(env, read=lambda *a: None)
    body = env.client(env.admin).get("/recalls").json()
    assert sorted(body["judge_failures"]) == sorted(ids.values())
    assert env.client(env.alice).get(f"/recalls/{ids['alice']}").json()["explanation"].startswith("[판정 실패, 확인 필요]")


# ---------------------------------------------------------------- 확인·의견


def test_ack_returns_updated_notice(env):
    ids = seed(env)
    c = env.client(env.alice)
    r = c.post(f"/recalls/{ids['alice']}/ack")
    assert r.status_code == 200 and r.json()["acked"] is True and r.json()["notice_id"] == ids["alice"]
    assert c.get("/recalls").json()["unread"] == 0
    assert c.post(f"/recalls/{ids['alice']}/ack").json()["acked"] is True          # 두 번 눌러도 같다


def test_cannot_ack_others_notice(env):
    ids = seed(env)
    assert env.client(env.alice).post(f"/recalls/{ids['bob']}/ack").status_code == 404
    assert env.client(env.admin).post(f"/recalls/{ids['bob']}/ack").status_code == 404     # 확인은 본인만


def test_feedback_counts_and_stats(env):
    ids = seed(env)
    c = env.client(env.alice)
    r = c.post(f"/recalls/{ids['alice']}/feedback", json={"useful": False, "reason": "이미 알고 있음"})
    assert r.status_code == 200 and r.json() == {"notice_id": ids["alice"], "useful": False, "counts": {"useful": 0, "not_useful": 1}}
    r = c.post(f"/recalls/{ids['alice']}/feedback", json={"useful": True})              # 다시 보내면 덮어쓴다
    assert r.json()["counts"] == {"useful": 1, "not_useful": 0}
    assert env.client(env.bob).post(f"/recalls/{ids['alice']}/feedback", json={"useful": True}).status_code == 404
    assert c.post(f"/recalls/{ids['alice']}/feedback", json={"useful": "x"}).status_code == 422
    stats = env.client(env.admin).get("/recalls/feedback-stats").json()
    assert stats["total"] == 1 and stats["precision_from_feedback"] == 1.0


# ---------------------------------------------------------------- 검토함


def test_review_queue_hidden_until_released(env, monkeypatch):
    """F-08: 확신도가 낮은 알림은 관리자 검토함에만 있고, 풀어 주면 사용자에게 보이고 웹훅이 나간다."""
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    ids = seed(env, read=reader(WORDING_OLD, WORDING_NEW))
    assert env.client(env.alice).get("/recalls").json()["items"] == []
    assert env.client(env.alice).get(f"/recalls/{ids['alice']}").status_code == 404
    admin = env.client(env.admin)
    queue = admin.get("/recalls").json()["review_queue"]
    assert sorted(n["notice_id"] for n in queue) == sorted(ids.values()) and all(n["needs_review"] for n in queue)
    assert env.post.calls == []
    r = admin.post(f"/recalls/{ids['alice']}/review", json={"action": "release"})
    assert r.status_code == 200 and r.json()["needs_review"] is False
    assert [n["notice_id"] for n in env.client(env.alice).get("/recalls").json()["items"]] == [ids["alice"]]
    assert len(env.post.calls) == 1                                    # 풀어 준 알림만 웹훅
    assert admin.post(f"/recalls/{ids['bob']}/review", json={"action": "dismiss"}).status_code == 200
    assert admin.post(f"/recalls/{ids['bob']}/review", json={"action": "release"}).status_code == 409
    assert admin.post("/recalls/rn-none/review", json={"action": "release"}).status_code == 404
    assert admin.post(f"/recalls/{ids['bob']}/review", json={"action": "x"}).status_code == 422
    assert env.client(env.bob).get(f"/recalls/{ids['bob']}").status_code == 404


# ---------------------------------------------------------------- 하루 요약


def test_digest_flush_and_list(env, monkeypatch):
    monkeypatch.setenv("RECALL_DIGEST", "daily")
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    seed(env)
    assert env.post.calls == []                                         # 요약 모드: 알림마다 보내지 않는다
    assert len(env.client(env.alice).get("/recalls").json()["items"]) == 1   # 앱에는 바로 보인다
    r = env.client(env.admin).post("/recalls/digest/flush", params={"day": "2026-11-09"})
    assert r.status_code == 200 and r.json() == {"digests": 2, "notices": 2}
    assert len(env.post.calls) == 2 and all(b'"type":"recall_digest"' in c[1] for c in env.post.calls)
    mine = env.client(env.alice).get("/recalls/digests").json()["digests"]
    assert len(mine) == 1 and mine[0]["user_id"] == str(env.alice.user_id) and mine[0]["day"] == "2026-11-09"
    assert len(env.client(env.admin).get("/recalls/digests").json()["digests"]) == 2
    assert env.client(env.admin).post("/recalls/digest/flush").json() == {"digests": 0, "notices": 0}


# ---------------------------------------------------------------- 처리 대기·수집 쪽 알림


def test_process_pending_marks_sent_and_is_idempotent(env):
    changes = env.app.state.change_store
    row = changes.add(changed())
    admin = env.client(env.admin)
    r = admin.post("/recalls/process-pending")
    assert r.status_code == 200 and r.json()["processed"] == 1 and r.json()["sent"] == 1 and r.json()["notices"] == 2
    assert changes.get(row["event_id"])["status"] == "sent"
    assert admin.post("/recalls/process-pending").json()["processed"] == 0
    changes.set_status(row["event_id"], "pending")                       # 다시 넣어도 같은 개정은 다시 알리지 않는다(EC-06)
    assert admin.post("/recalls/process-pending").json()["notices"] == 0 and len(env.svc.store.notices_all()) == 2


def test_process_pending_failure_marks_failed(env):
    changes = env.app.state.change_store
    row = changes.add(changed())

    class Boom:
        mode = "rule"

        def judge(self, *a):
            raise RuntimeError("x")

    env.svc._judge = Boom()
    assert env.client(env.admin).post("/recalls/process-pending").json()["failed"] == 1
    assert changes.get(row["event_id"])["status"] == "failed"


def test_regulation_updated_requires_service_key(env, monkeypatch):
    """EC-10: 서비스 키가 없거나 틀리면 401. 서버에 키가 설정되지 않았으면 어떤 키도 받지 않는다."""
    c = env.client()
    assert c.post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": "anything"}).status_code == 401
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    assert c.post("/webhooks/regulation-updated", json=CHANGE).status_code == 401
    assert c.post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": "wrong"}).status_code == 401
    assert c.post("/webhooks/regulation-updated", content=b"not json", headers={"X-Service-Key": "wrong"}).status_code == 401
    assert env.client(env.admin).post("/webhooks/regulation-updated", json=CHANGE).status_code == 401   # 로그인으로는 안 된다


@pytest.mark.parametrize("body", [b"not json", b"[]", b"5", b'{"rule_seq": "x"}', b'{"rule_seq": 1}',
                                  b'{"rule_seq": 1, "article": "A", "change_type": "renamed"}',
                                  b'{"rule_seq": 1, "article": "A", "new_version_date": "2026/10/30"}',
                                  b'{"rule_seq": 1, "article": "A", "extra": 1}'])
def test_regulation_updated_bad_body_is_400(env, monkeypatch, body):
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    r = env.client().post("/webhooks/regulation-updated", content=body, headers={"X-Service-Key": SERVICE_KEY,
                                                                                  "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_regulation_updated_accepts_and_notifies_once(env, monkeypatch):
    """AC-06, EC-06: 202로 받고 응답 뒤 리콜이 돈다. 같은 개정을 다시 보내도 알림은 한 번이다. 웹훅은 서명해서 보낸다(AC-03)."""
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    c = env.client()
    r = c.post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": SERVICE_KEY})
    assert r.status_code == 202 and r.json()["accepted"] == 1 and len(r.json()["event_ids"]) == 1
    assert len(env.svc.store.notices_all()) == 2 and len(env.post.calls) == 2
    for _, content, headers in env.post.calls:
        assert verify_signature(content, headers[SIGNATURE_HEADER], SECRET)
    r = c.post("/webhooks/regulation-updated", json=[CHANGE], headers={"Authorization": f"Bearer {SERVICE_KEY}"})
    assert r.status_code == 202 and len(env.svc.store.notices_all()) == 2 and len(env.post.calls) == 2


def test_answer_on_new_version_not_notified_via_webhook(env, monkeypatch):
    """EC-03: 새 판 날짜 이후 기준으로 받은 답은 알리지 않는다."""
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    save_answer(env.svc.answers, "a-new", str(env.alice.user_id), as_of="2025-08-01")
    env.client().post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": SERVICE_KEY})
    assert "a-new" not in {r["answer_id"] for r in env.svc.store.notices_all()}


def test_webhook_retry_log_over_api(env, monkeypatch):
    """EC-05: 업무시스템이 5xx면 재시도하고, 시도 기록을 관리자가 본다."""
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    env.post.codes = [500, 503, 200]
    env.svc.answers._citations.pop("a-bob")                               # 알림 하나만
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    env.client().post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": SERVICE_KEY})
    [d] = env.client(env.admin).get("/webhook-deliveries").json()["items"]
    assert d["status"] == "success" and d["tries"] == 3 and [a["status_code"] for a in d["attempts"]] == [500, 503, 200]


def test_webhook_without_secret_is_recorded_failed(env, monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    env.client().post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": SERVICE_KEY})
    items = env.client(env.admin).get("/webhook-deliveries").json()["items"]
    assert env.post.calls == [] and {d["last_error"] for d in items} == {"secret_missing"}


# ---------------------------------------------------------------- 구독·후보


def test_subscriptions(env, monkeypatch):
    admin = env.client(env.admin)
    assert admin.post("/webhook-subscriptions", json={"url": "http://hooks.example.com/x"}).status_code == 400     # 배포는 https만
    assert admin.post("/webhook-subscriptions", json={"url": "https://10.0.0.1/x"}).status_code == 400
    assert admin.post("/webhook-subscriptions", json={"url": "https://hooks.example.com/x", "secret_ref": "DATABASE_URL"}).status_code == 400
    r = admin.post("/webhook-subscriptions", json={"url": "https://hooks.example.com/x"})
    assert r.status_code == 201 and r.json()["secret_configured"] is False and r.json()["secret_ref"] == "RECALL_WEBHOOK_SECRET"
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    [s] = admin.get("/webhook-subscriptions").json()["items"]
    assert s["secret_configured"] is True and SECRET not in str(s)


def test_candidates_decide(env):
    env.svc.links = MemoryLinks([{"rule_seq": 90003, "article": "Procurement", "title": "SaaS 도입 정책", "target": SEQ}])
    seed(env)
    admin = env.client(env.admin)
    [c] = admin.get("/maintenance-candidates").json()["items"]
    assert c["status"] == "pending" and c["decided_by"] is None
    r = admin.post(f"/maintenance-candidates/{c['candidate_id']}", json={"status": "needed"})
    assert r.status_code == 200 and r.json()["status"] == "needed" and r.json()["decided_by"] == "admin"
    assert admin.get("/maintenance-candidates", params={"status": "needed"}).json()["items"][0]["candidate_id"] == c["candidate_id"]
    assert admin.get("/maintenance-candidates", params={"status": "pending"}).json()["items"] == []
    assert admin.post("/maintenance-candidates/mc-none", json={"status": "needed"}).status_code == 404
    assert admin.post(f"/maintenance-candidates/{c['candidate_id']}", json={"status": "pending"}).status_code == 422


# ---------------------------------------------------------------- 영향 미리보기(드라이런)


def _snapshot(env) -> tuple:
    st = env.svc.store
    return len(st.notices_all()), len(st.deliveries()), len(st.events), len(st.candidates()), len(env.svc.answers.find_by_article(SEQ, ARTICLE))


def test_impact_preview_is_dry_run(env):
    """F-05: 영향 미리보기는 저장·알림·웹훅을 하지 않는다."""
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    before = _snapshot(env)
    body = {"changes": [{**CHANGE, "old_text": "도입 승인: 5천만원 이상은 디렉터가 승인한다.", "new_text": "도입 승인: 1억원 이상은 디렉터가 승인한다."}]}
    r = env.client(env.admin).post("/impact-preview", json=body)
    assert r.status_code == 200
    rep = r.json()
    assert rep["dry_run"] is True and rep["judge_mode"] == "rule"
    assert rep["summary"]["answers_checked"] == 2 and rep["summary"]["recipients"] == 2
    assert {a["answer_id"] for a in rep["answers"]} == {"a-alice", "a-bob"} and "드라이런" in rep["markdown"]
    assert _snapshot(env) == before and env.post.calls == []


def test_impact_preview_from_pages(env):
    old = "---\ntitle: X\n---\n\n## Policy\n\nWe disclose issues 30 days after the fix.\n"
    page = {"path": "content/handbook/security/x.md", "old": old, "new": old.replace("30 days", "90 days")}
    r = env.client(env.admin).post("/impact-preview", json={"pages": [page], "old_version_date": "2026-01-01",
                                                            "new_version_date": "2026-02-01"})
    assert r.status_code == 200 and r.json()["summary"]["changes"] == 1 and r.json()["changes"][0]["article"] == "Policy"


@pytest.mark.parametrize("body", [{}, {"changes": [CHANGE], "pages": [{"path": "a.md", "old": "x", "new": "y"}]},
                                  {"pages": [{"path": "a.md", "old": "x", "new": "y"}]}])
def test_impact_preview_bad_input(env, body):
    assert env.client(env.admin).post("/impact-preview", json=body).status_code == 400


# ---------------------------------------------------------------- 문서 권한(F-06)


def test_acl_filters_user_notices(env, monkeypatch):
    """EC-11: 볼 수 없는 섹션을 인용한 알림은 사용자에게 보이지 않는다(관리자는 본다)."""
    env.svc.acl = MemoryAcl({(SEQ, ARTICLE): {"finance"}})
    ids = seed(env)
    assert env.client(env.alice).get("/recalls").json()["items"] == []
    assert env.client(env.alice).get(f"/recalls/{ids['alice']}").status_code == 404
    assert len(env.client(env.admin).get("/recalls").json()["items"]) == 2
    original = FakeAuthStore.get_by_user_id

    def with_group(self, user_id):
        u = original(self, user_id)
        return dataclasses.replace(u, groups=("finance",)) if u is not None and u.login_id == "alice" else u

    monkeypatch.setattr(FakeAuthStore, "get_by_user_id", with_group)
    assert [n["notice_id"] for n in env.client(env.alice).get("/recalls").json()["items"]] == [ids["alice"]]
    assert env.client(env.bob).get("/recalls").json()["items"] == []


# ---------------------------------------------------------------- 화면 주소·경로 순서


@pytest.fixture
def spa_index(env, tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    env.app.state.react_index = index
    return index


@pytest.mark.parametrize("path", ["/recalls", "/recalls/rn-x", "/changes", "/changes/ev-x"])
def test_browser_navigation_gets_spa_html(env, spa_index, path):
    """주소창 입력·새로 고침(Accept에 text/html)은 로그인 전이라도 화면을 받는다."""
    r = env.client().get(path, headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "<title>spa</title>" in r.text


@pytest.mark.parametrize("path", ["/recalls", "/changes"])
def test_fetch_with_json_accept_gets_api(env, spa_index, path):
    c = env.client(env.alice)
    r = c.get(path, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json") and "items" in r.json()
    assert env.client().get(path, headers={"Accept": "application/json"}).status_code == 401


@pytest.mark.parametrize("path", ["/recalls", "/recalls/rn-x", "/changes", "/changes/ev-x"])
def test_screen_html_is_not_cached_and_varies_by_accept(env, spa_index, path):
    """화면 주소와 API 주소가 같아 브라우저가 HTML을 캐시하면 화면의 fetch 가 HTML을 받는다 -> no-store, Vary: Accept."""
    r = env.client().get(path, headers={"Accept": "text/html"})
    assert r.headers["cache-control"] == "no-store" and r.headers["vary"] == "Accept"


@pytest.mark.parametrize("path", ["/recalls", "/changes"])
def test_screen_api_json_is_not_cached_and_varies_by_accept(env, spa_index, path):
    r = env.client(env.alice).get(path, headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store" and "Accept" in r.headers["vary"]

def test_fixed_recall_paths_are_not_taken_as_notice_id(env):
    """`/recalls/digests`, `/recalls/feedback-stats`는 `/recalls/{notice_id}`보다 먼저 잡힌다."""
    assert env.client(env.alice).get("/recalls/digests").json() == {"digests": []}
    assert env.client(env.admin).get("/recalls/feedback-stats").json()["total"] == 0
    assert env.client(env.alice).get("/recalls/feedback-stats").status_code == 403     # 알림 404가 아니라 관리자 전용 403


# ---------------------------------------------------------------- 빈 상태·중복·삭제 (점검)


@pytest.mark.parametrize("who", ["alice", "admin"])
def test_empty_state_returns_empty_lists_not_errors(env, who):
    """저장된 알림·후보·구독·기록이 하나도 없어도 목록은 빈 배열로 200이다."""
    c = env.client(getattr(env, who))
    body = c.get("/recalls").json()
    assert body["items"] == [] and body["unread"] == 0
    if who == "admin":
        assert body["review_queue"] == [] and body["candidates"] == [] and body["judge_failures"] == []
        for path in ("/webhook-subscriptions", "/webhook-deliveries", "/maintenance-candidates", "/recalls/feedback-stats"):
            assert c.get(path).status_code == 200, path
    assert c.get("/recalls/digests").status_code == 200


def test_duplicate_events_in_one_batch_notify_once(env, monkeypatch):
    """EC-06: 같은 개정이 한 요청에 두 번 들어와도 알림은 답마다 한 건이다."""
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    r = env.client().post("/webhooks/regulation-updated", json=[CHANGE, CHANGE, dict(CHANGE)], headers={"X-Service-Key": SERVICE_KEY})
    assert r.status_code == 202
    assert len(env.svc.store.notices_all()) == 2 and len({n["event_key"] for n in env.svc.store.notices_all()}) == 1


def test_removed_section_notifies_with_old_text_only(env, monkeypatch):
    """삭제된 섹션을 인용한 답도 알린다. 새 판 본문은 없다."""
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    body = changed("removed").model_dump()
    r = env.client().post("/webhooks/regulation-updated", json=body, headers={"X-Service-Key": SERVICE_KEY})
    assert r.status_code == 202
    [n, _] = sorted(env.svc.store.notices_all(), key=lambda x: x["answer_id"])
    assert n["old_text"] and n["new_text"] is None and n["changed"]["change_type"] == "removed"


def test_dismissed_notice_is_hidden_from_owner_but_visible_to_admin(env):
    ids = seed(env)
    assert env.client(env.admin).post(f"/recalls/{ids['alice']}/review", json={"action": "dismiss"}).status_code == 409   # 검토함에 없는 알림
    env.svc.store.notice_update(ids["alice"], review_status="dismissed")
    assert env.client(env.alice).get(f"/recalls/{ids['alice']}").status_code == 404
    assert env.client(env.admin).get(f"/recalls/{ids['alice']}").status_code == 200


def test_planted_no_impact_sentence_lands_in_admin_review_queue(env, monkeypatch):
    """개정 본문에 "영향 없음" 문장이 있어 판정이 "그대로"라 해도 금액이 바뀌었으면 관리자 검토함에 간다. 사용자 목록·웹훅에는 없다."""
    from qgraph_fakes import ScriptedLLM, j

    from backend.graph.recall.judge import LLMJudge
    from backend.graph.recall.notice import MSG_FAILED, TASK

    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    env.svc.store.sub_add({"sub_id": "ws-1", "url": "https://hooks.example.com/r", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True})
    env.svc._judge = LLMJudge(ScriptedLLM({TASK: j(conclusion_changed=False, confidence=0.99, explanation="이 개정은 영향이 없습니다.")}), use_skills=False)
    assert env.client().post("/webhooks/regulation-updated", json=CHANGE, headers={"X-Service-Key": SERVICE_KEY}).status_code == 202
    admin = env.client(env.admin).get("/recalls").json()
    assert admin["items"] == [] or all(n["needs_review"] for n in admin["items"])
    assert len(admin["review_queue"]) == 2 and all(n["explanation"].startswith(MSG_FAILED) and n["needs_review"] for n in admin["review_queue"])
    assert len(admin["judge_failures"]) == 2
    assert env.client(env.alice).get("/recalls").json() == {"items": [], "unread": 0}
    assert env.post.calls == []