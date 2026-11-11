"""변경 감시 API와 감시 스위치 시험 (PRD 6-4, F-07). DB 없이 메모리 저장소로 본다."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from api_test_support import Env
from recall_test_support import ARTICLE, changed, reader, save_answer

from backend.graph.recall import process_pending as pp
from backend.graph.recall.monitor import InMemoryChangeStore
from backend.rag.ingest import schedule

CHANGE_KEYS = {"event_id", "rule_seq", "article", "page_title", "old_version_date", "new_version_date", "change_type", "status",
               "created_at", "source_url", "impacted_answer_count"}


@pytest.fixture
def env(monkeypatch):
    with Env(monkeypatch) as e:
        e.changes = e.app.state.change_store
        e.svc = e.app.state.recall_service
        e.svc.read_section = reader()
        yield e


def test_empty_db_returns_empty_list_not_500(env):
    r = env.client(env.alice).get("/changes")
    assert r.status_code == 200 and r.json() == {"items": [], "last_run": None, "more": False, "monitoring": "active", "total": 0, "counts": {}}


def test_list_shape_order_and_impacted_count(env):
    save_answer(env.svc.answers, "a1", str(env.alice.user_id))
    save_answer(env.svc.answers, "a2", str(env.bob.user_id))
    env.changes.add(changed(), page_title="승인 권한 정책", source_url="https://example.invalid/x")
    env.changes.add(changed(article="Other", new="2026-10-30"))
    env.changes.runs.append({"run_id": 3, "status": "succeeded", "finished_at": "2026-11-02T00:00:00+00:00", "to_commit": "abc",
                             "list_complete": True})
    body = env.client(env.alice).get("/changes", params={"since": "2020-01-01"}).json()
    assert [i["article"] for i in body["items"]] == ["Other", ARTICLE]          # 최근 것이 앞
    assert set(body["items"][1]) == CHANGE_KEYS
    assert body["items"][1]["impacted_answer_count"] == 2 and body["items"][0]["impacted_answer_count"] == 0
    assert body["items"][1]["page_title"] == "승인 권한 정책" and body["items"][1]["status"] == "pending"
    assert body["last_run"] == {"run_id": 3, "status": "succeeded", "finished_at": "2026-11-02T00:00:00+00:00", "to_commit": "abc",
                                "list_complete": True}


def test_since_limit_offset(env):
    for i in range(3):
        env.changes.add(changed(article=f"S{i}", new=f"2026-10-2{i}"))
    c = env.client(env.alice)
    page = c.get("/changes", params={"since": "2026-10-01", "limit": 2}).json()
    assert [i["article"] for i in page["items"]] == ["S2", "S1"] and page["more"] is True
    page = c.get("/changes", params={"since": "2026-10-01", "limit": 2, "offset": 2}).json()
    assert [i["article"] for i in page["items"]] == ["S0"] and page["more"] is False
    assert [i["article"] for i in c.get("/changes", params={"since": "2026-10-21"}).json()["items"]] == ["S2", "S1"]
    assert c.get("/changes", params={"since": "2026/10/01"}).status_code == 422
    assert c.get("/changes", params={"limit": 0}).status_code == 422


def test_total_and_counts_cover_all_rows_not_just_the_page(env):
    for i in range(3):
        env.changes.add(changed(article=f"M{i}", new=f"2026-10-2{i}"))
    env.changes.add(changed("added", article="A0", new="2026-10-25"))
    env.changes.add(changed("removed", article="R0", new="2026-10-26"))
    env.changes.add(changed(article="Old", new="2020-01-01"))                    # since 이전은 세지 않는다
    c = env.client(env.alice)
    body = c.get("/changes", params={"since": "2026-10-01", "limit": 2}).json()
    assert len(body["items"]) == 2 and body["more"] is True
    assert body["total"] == 5 and body["counts"] == {"modified": 3, "added": 1, "removed": 1}
    later = c.get("/changes", params={"since": "2026-10-01", "limit": 2, "offset": 4}).json()
    assert later["total"] == 5 and later["counts"] == body["counts"]             # 쪽을 넘겨도 합계는 같다


def test_totals_are_null_when_store_cannot_count(env):
    env.changes.add(changed())
    env.changes.count_by_type = lambda since: (_ for _ in ()).throw(RuntimeError("boom"))
    body = env.client(env.alice).get("/changes", params={"since": "2020-01-01"}).json()
    assert len(body["items"]) == 1 and body["total"] is None and body["counts"] is None


def test_default_since_is_30_days(env):
    env.changes.add(changed(new="2020-01-01"))                                   # 오래된 개정
    assert env.client(env.alice).get("/changes").json()["items"] == []


def test_detail_has_texts_and_404(env):
    row = env.changes.add(changed())
    r = env.client(env.alice).get(f"/changes/{row['event_id']}")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == CHANGE_KEYS | {"old_text", "new_text"} and "5천만원" in d["old_text"] and "1억원" in d["new_text"]
    assert env.client(env.alice).get("/changes/nope").status_code == 404


def test_detail_added_and_removed_skip_missing_side(env):
    added = env.changes.add(changed("added"))
    removed = env.changes.add(changed("removed", article="Gone"))
    c = env.client(env.alice)
    assert c.get(f"/changes/{added['event_id']}").json()["old_text"] is None
    assert c.get(f"/changes/{removed['event_id']}").json()["new_text"] is None


def test_detail_without_reader_has_null_texts(env):
    env.svc.read_section = None
    row = env.changes.add(changed())
    d = env.client(env.alice).get(f"/changes/{row['event_id']}").json()
    assert d["old_text"] is None and d["new_text"] is None


def test_monitoring_switch(env):
    c, admin = env.client(env.alice), env.client(env.admin)
    assert c.get("/changes/monitoring").json() == {"status": "active"}          # 고정 경로가 /changes/{event_id}보다 먼저다
    assert c.put("/changes/monitoring", json={"status": "paused"}).status_code == 403
    assert env.client(env.admin, csrf=False).put("/changes/monitoring", json={"status": "paused"}).status_code == 403
    assert admin.put("/changes/monitoring", json={"status": "stopped"}).status_code == 422
    r = admin.put("/changes/monitoring", json={"status": "paused"})
    assert r.status_code == 200 and r.json()["status"] == "paused" and r.json()["updated_by"] == "admin"
    assert c.get("/changes").json()["monitoring"] == "paused" and c.get("/changes/monitoring").json() == {"status": "paused"}
    assert admin.put("/changes/monitoring", json={"status": "active"}).json()["status"] == "active"


def test_monitoring_path_not_taken_as_event_id(env):
    env.changes.add(changed())
    r = env.client(env.alice).get("/changes/monitoring")
    assert r.status_code == 200 and set(r.json()) == {"status"}


# ---------------------------------------------------------------- 명령줄 처리기·증분 수집의 감시 스위치


def test_process_pending_cli_does_nothing_when_paused(monkeypatch, capsys):
    store = InMemoryChangeStore()
    store.add(changed())
    store.monitoring_set("paused", "admin")
    built = []
    monkeypatch.setattr("backend.graph.recall.runtime.make_change_store", lambda *a: store)
    monkeypatch.setattr("backend.graph.recall.runtime.build_service_from_env", lambda: built.append(1))
    assert pp.main([]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"status": "paused"} and built == []
    assert store.pending()[0]["status"] == "pending"


def test_process_pending_cli_force_ignores_pause(monkeypatch, capsys):
    from backend.graph.answer_store import InMemoryAnswerStore
    from backend.graph.recall.judge import RuleJudge
    from backend.graph.recall.service import RecallService
    from backend.graph.recall.store import InMemoryRecallStore

    store = InMemoryChangeStore()
    store.add(changed())
    store.monitoring_set("paused", "admin")
    answers = InMemoryAnswerStore()
    save_answer(answers, "a1", "u1")
    svc = RecallService(store=InMemoryRecallStore(), answers=answers, read_section=reader(), judge=RuleJudge())
    monkeypatch.setattr("backend.graph.recall.runtime.make_change_store", lambda *a: store)
    monkeypatch.setattr("backend.graph.recall.runtime.build_service_from_env", lambda: svc)
    assert pp.main(["--force"]) == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["status"] == "done" and out["sent"] == 1 and out["notices"] == 1 and store.pending() == []


class FakeConn:
    """schedule.run이 감시 스위치를 확인하는 데까지의 SQL만 흉내 낸다."""

    def __init__(self, table: bool, status: str | None):
        self.table, self.status, self.sql = table, status, []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        conn = self

        class Cur:
            def fetchone(self):
                if "to_regclass('change_monitoring')" in sql:
                    return (conn.table,)
                if "FROM change_monitoring" in sql:
                    return (conn.status,) if conn.status else None
                raise AssertionError(f"감시가 멈췄는데 다른 SQL이 실행됨: {sql[:60]}")

        return Cur()

    def commit(self):
        pass


@pytest.mark.parametrize("table,status,paused", [(True, "paused", True), (True, "active", False), (False, None, False), (True, None, False)])
def test_monitoring_paused(table, status, paused):
    assert schedule.monitoring_paused(FakeConn(table, status)) is paused


def test_schedule_run_is_noop_when_paused():
    conn = FakeConn(True, "paused")
    now = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)
    res = schedule.run(conn, trigger="schedule", now=now, slot=None, model="m", dim=1, source=lambda c: None, embed_fn=lambda t: None,
                       log=lambda *a: None)
    assert res["status"] == "noop" and res["reason"] == "paused" and res["slot"] == schedule.slot_of(now)
    assert not any("sync_runs" in s and "INSERT" in s for s in conn.sql[1:])     # 슬롯을 차지하지 않는다


def test_manual_sync_requires_login_and_admin(env):
    assert env.client().post("/admin/sync", json={}).status_code == 401
    assert env.client(env.alice).post("/admin/sync", json={}).status_code == 403
    assert env.client(env.admin, csrf=False).post("/admin/sync", json={}).status_code == 403   # CSRF 없이는 거부


def test_manual_sync_dry_run_is_default_and_starts_nothing(env):
    started = []
    env.app.state.sync_launcher = started.append
    admin = env.client(env.admin)
    for kwargs in ({}, {"json": {}}, {"json": {"dry_run": True}}):
        r = admin.post("/admin/sync", **kwargs)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dry_run"] is True and body["started"] is False and body["slot"].startswith("manual-")
        assert body["monitoring"] == "active"
    assert started == []


def test_manual_sync_real_run_only_when_asked_and_not_paused(env):
    started = []
    env.app.state.sync_launcher = started.append
    admin = env.client(env.admin)
    r = admin.post("/admin/sync", json={"dry_run": False})
    assert r.status_code == 200 and r.json()["started"] is True and started == [r.json()["slot"]]
    admin.put("/changes/monitoring", json={"status": "paused"})
    r = admin.post("/admin/sync", json={"dry_run": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "monitoring_paused" and len(started) == 1
    assert admin.post("/admin/sync", json={"dry_run": "x", "extra": 1}).status_code == 422
