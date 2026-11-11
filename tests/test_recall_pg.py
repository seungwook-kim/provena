"""리콜 저장소의 진짜 Postgres 시험. PROVENA_TEST_DATABASE_URL(또는 TEST_DATABASE_URL)이 있을 때만 돈다(없으면 건너뜀).

시험용 DB에 db/01_init.sql, 1xx, 201, 202, 120을 차례로 적용해 둔다. 시험은 자기 키(접두어 pgt-)로만 쓰고 끝나면 지운다.
"""
from __future__ import annotations

import os
import uuid

import pytest
from recall_test_support import ARTICLE, NEW_DATE, OLD_DATE, SEQ, answers_with, changed, chunk, reader, save_answer

DSN = (os.getenv("PROVENA_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL"))
pytestmark = pytest.mark.skipif(not DSN, reason="PROVENA_TEST_DATABASE_URL·TEST_DATABASE_URL 없음")

from backend.graph.answer_store import PgAnswerStore, count_by_articles  # noqa: E402
from backend.graph.recall.acl import PgAcl  # noqa: E402
from backend.graph.recall.judge import RuleJudge  # noqa: E402
from backend.graph.recall.maintenance import PgLinks  # noqa: E402
from backend.graph.recall.monitor import PgChangeStore  # noqa: E402
from backend.graph.recall.service import RecallService, notice_id_of  # noqa: E402
from backend.graph.recall.store import PgRecallStore  # noqa: E402
from backend.rag.ingest.schedule import JOB, monitoring_paused  # noqa: E402

SEQ_PG = 990000 + (uuid.uuid4().int % 9000)       # 다른 시험·실제 데이터와 겹치지 않는 가상 정책 번호


def _conn():
    import psycopg

    return psycopg.connect(DSN, autocommit=True, prepare_threshold=None)


@pytest.fixture()
def tag():
    t = "pgt-" + uuid.uuid4().hex[:8]
    yield t
    with _conn() as c:
        c.execute("DELETE FROM recall_notices WHERE user_id LIKE %s", (t + "%",))
        c.execute("DELETE FROM recall_digests WHERE user_id LIKE %s", (t + "%",))
        c.execute("DELETE FROM webhook_deliveries WHERE sub_id LIKE %s", (t + "%",))
        c.execute("DELETE FROM webhook_subscriptions WHERE sub_id LIKE %s", (t + "%",))
        c.execute("DELETE FROM maintenance_candidates WHERE candidate_id LIKE %s", (t + "%",))
        c.execute("DELETE FROM recall_events WHERE event_key LIKE %s", (t + "%",))
        c.execute("DELETE FROM citations WHERE answer_id LIKE %s", (t + "%",))
        c.execute("DELETE FROM answers WHERE answer_id LIKE %s", (t + "%",))


def test_answer_store_save_find_count(tag):
    store = PgAnswerStore(DSN)
    ch = chunk(rule_seq=SEQ_PG, article=ARTICLE)
    save_answer(store, f"{tag}-a1", f"{tag}-u1", citations=[ch, ch])          # 같은 청크를 두 번 인용해도 한 줄
    save_answer(store, f"{tag}-a2", f"{tag}-u2", citations=[ch])
    save_answer(store, f"{tag}-a1", f"{tag}-u1", citations=[ch])              # 같은 답 다시 저장: 중복 없음
    rows = store.find_by_article(SEQ_PG, ARTICLE)
    assert [r["answer_id"] for r in rows] == [f"{tag}-a1", f"{tag}-a2"]
    assert rows[0]["thread_id"] == f"{tag}-u1:t1" and rows[0]["version_date"] == OLD_DATE and rows[0]["source_url"]
    assert count_by_articles(store, [(SEQ_PG, ARTICLE), (SEQ_PG, "없는 섹션")]) == {(SEQ_PG, ARTICLE): 2, (SEQ_PG, "없는 섹션"): 0}
    assert store.find_by_article(SEQ_PG, "없는 섹션") == []
    assert count_by_articles(store, []) == {}
    got = store.get(f"{tag}-a1")
    assert got["user_id"] == f"{tag}-u1" and len(got["citations"]) == 1


def test_service_end_to_end_on_postgres(tag):
    answers, store = PgAnswerStore(DSN), PgRecallStore(DSN)
    ch = chunk(rule_seq=SEQ_PG)
    for who in ("u1", "u2"):
        save_answer(answers, f"{tag}-{who}", f"{tag}-{who}", citations=[ch])
    svc = RecallService(store=store, answers=answers, read_section=reader(), judge=RuleJudge(), min_confidence=0.5)
    key = f"{tag}-ev1"
    res = svc.process(changed(rule_seq=SEQ_PG), event_key=key)
    assert res["status"] == "done" and len(res["notices"]) == 2 and len(res["to_send"]) == 2
    assert svc.process(changed(rule_seq=SEQ_PG), event_key=key)["status"] == "skipped"            # EC-06: 같은 개정은 한 번
    assert store.event_get(key)["status"] == "done" and store.event_get(key)["notices"] == 2
    nid = notice_id_of(f"{tag}-u1", key)
    n = store.notice_get(nid)
    assert n["user_id"] == f"{tag}-u1" and n["severity"] == "high" and n["changed"]["new_version_date"] == NEW_DATE and n["acked"] is False
    assert [x["user_id"] for x in store.notices_all(f"{tag}-u1")] == [f"{tag}-u1"]               # 남의 알림은 안 섞인다
    again, new = store.notice_add({**n, "explanation": "다른 문구"})
    assert new is False and again["explanation"] == n["explanation"]                              # UNIQUE (answer_id, event_key)
    up = store.notice_update(nid, acked=True, review_status="dismissed")
    assert up["acked"] is True and up["review_status"] == "dismissed"
    assert store.notice_update("pgt-없음", acked=True) is None


def test_grounding_lives_in_the_answers_row(tag):
    store = PgAnswerStore(DSN)
    ch = chunk(rule_seq=SEQ_PG, article=ARTICLE)
    save_answer(store, f"{tag}-g0", f"{tag}-u1", citations=[ch])
    assert store.get_grounding(f"{tag}-g0") is None                                              # 아직 기록하지 않음(NULL)
    store.save_grounding(f"{tag}-g0", {"grounded": True}, ["glossary"])
    got = store.get_grounding(f"{tag}-g0")
    assert got["grounding"] == {"grounded": True} and got["skills_used"] == ["glossary"] and [c["chunk_id"] for c in got["citations"]] == [ch.chunk_id]
    store.save_with_grounding(f"{tag}-g1", f"{tag}-u1", f"{tag}-u1:t1", "질문?", "답 [1]", None, [ch], {"grounded": False}, [])
    store.save_with_grounding(f"{tag}-g1", f"{tag}-u1", f"{tag}-u1:t1", "질문?", "답 [1]", None, [ch], {"grounded": True}, ["a"])   # 다시 저장: 근거 칸만 덮어쓴다
    again = store.get_grounding(f"{tag}-g1")
    assert again["grounding"] == {"grounded": True} and again["skills_used"] == ["a"] and len(again["citations"]) == 1
    store.save_grounding(f"{tag}-없는답", {"x": 1}, [])                                           # 답이 없으면 아무것도 쓰지 않는다
    assert store.get_grounding(f"{tag}-없는답") is None
    with _conn() as c:
        assert c.execute("SELECT to_regclass('public.answer_grounding')").fetchone()[0] is None


def test_failed_event_can_be_claimed_again(tag):
    store, key = PgRecallStore(DSN), f"{tag}-ev2"
    assert store.claim_event(key, {"x": 1}) is True and store.claim_event(key, {"x": 1}) is False
    store.finish_event(key, "failed", error_kind="RuntimeError")
    assert store.event_get(key)["error_kind"] == "RuntimeError"
    assert store.claim_event(key, {"x": 1}) is True and store.event_get(key)["error_kind"] is None


def _notice(tag, n, user="u1", pattern="amount"):
    return {"notice_id": f"{tag}-{n}", "event_key": f"{tag}-ev-{n}", "answer_id": f"{tag}-a-{n}", "user_id": f"{tag}-{user}",
            "changed": {"rule_seq": SEQ_PG, "article": ARTICLE, "old_version_date": OLD_DATE, "new_version_date": NEW_DATE, "change_type": "modified"},
            "conclusion_changed": True, "explanation": "금액이 바뀜", "severity": "high", "change_pattern": pattern}


def test_feedback_digest_candidates_and_webhook_records(tag):
    store = PgRecallStore(DSN)
    for n in ("n1", "n2"):
        store.notice_add(_notice(tag, n))                                                          # 의견은 알림 줄의 feedback_* 칸이다(옛 recall_feedback 표 없음)
    store.notice_add(_notice(tag, "n3", pattern="deadline"))                                      # 다른 변경 유형은 집계에 섞이지 않는다
    fb = {"notice_id": f"{tag}-n1", "user_id": f"{tag}-u1", "answer_id": f"{tag}-a-n1", "rule_seq": SEQ_PG, "article": ARTICLE, "pattern": "amount",
          "severity": "high", "useful": False, "reason": "관련 없음", "given_by": f"{tag}-u1"}
    store.feedback_put(fb)
    store.feedback_put({**fb, "notice_id": f"{tag}-n2"})
    store.feedback_put({**fb, "notice_id": f"{tag}-n3", "pattern": "deadline"})
    store.feedback_put({**fb, "useful": True})                                                    # 같은 알림에 다시 보내면 덮어쓴다
    assert store.feedback_counts(f"{tag}-u1", SEQ_PG, ARTICLE, "amount") == {"useful": 1, "not_useful": 1}
    assert store.feedback_counts(f"{tag}-u1", SEQ_PG, ARTICLE, "deadline") == {"useful": 0, "not_useful": 1}
    assert store.feedback_counts(f"{tag}-u2", SEQ_PG, ARTICLE, "amount") == {"useful": 0, "not_useful": 0}
    mine = [r for r in store.feedback_list() if r["user_id"] == f"{tag}-u1"]
    assert len(mine) == 3 and {"notice_id", "user_id", "answer_id", "rule_seq", "article", "pattern", "severity", "useful", "reason", "given_by",
                               "created_at"} <= set(mine[0])
    assert {(r["notice_id"], r["rule_seq"], r["pattern"], r["useful"]) for r in mine} == {
        (f"{tag}-n1", SEQ_PG, "amount", True), (f"{tag}-n2", SEQ_PG, "amount", False), (f"{tag}-n3", SEQ_PG, "deadline", False)}
    assert store.notice_get(f"{tag}-n1")["explanation"] == "금액이 바뀜" and "feedback_useful" not in store.notice_get(f"{tag}-n1")   # 알림 응답 모양은 그대로

    d = {"digest_id": f"{tag}-d1", "user_id": f"{tag}-u1", "day": "2026-11-09", "count": 2, "notice_ids": ["a", "b"], "payload": {"items": [1, 2]}}
    assert store.digest_add(d)[1] is True and store.digest_add({**d, "count": 9})[1] is False
    assert store.digests(f"{tag}-u1")[0]["count"] == 2 and store.digests(f"{tag}-zzz") == []

    cand = {"candidate_id": f"{tag}-c1", "event_key": f"{tag}-ev", "upper_rule": "정책", "upper_version_id": "v1", "rule_seq": SEQ_PG,
            "article": ARTICLE, "reason": "링크됨"}
    assert store.candidates_add([cand, cand]) == 1
    assert [c["status"] for c in store.candidates("pending") if c["candidate_id"] == f"{tag}-c1"] == ["pending"]
    done = store.candidate_decide(f"{tag}-c1", "needed", "admin")
    assert done["status"] == "needed" and done["decided_by"] == "admin" and done["decided_at"]
    assert store.candidate_decide("pgt-없음", "needed", "admin") is None

    sub = store.sub_add({"sub_id": f"{tag}-s1", "url": "https://example.invalid/hook", "secret_ref": "RECALL_WEBHOOK_SECRET", "active": True,
                         "created_by": "admin"})
    assert sub["active"] is True and any(s["sub_id"] == f"{tag}-s1" for s in store.subs(active_only=True))
    store.delivery_add({"delivery_id": f"{tag}-dl1", "sub_id": f"{tag}-s1", "notice_id": f"{tag}-n1", "kind": "notice", "status": "pending",
                        "tries": 0, "attempts": []})
    store.delivery_update(f"{tag}-dl1", status="failed", tries=3, last_status_code=503,
                          attempts=[{"try": 1, "status_code": 503}, {"try": 2, "status_code": 503}, {"try": 3, "status_code": 503}])
    [row] = store.deliveries(f"{tag}-n1")
    assert row["status"] == "failed" and row["tries"] == 3 and row["last_status_code"] == 503 and len(row["attempts"]) == 3


def test_digest_pending_hides_review_queue(tag):
    store = PgRecallStore(DSN)
    base = {"event_key": f"{tag}-ev", "user_id": f"{tag}-u1", "changed": {"a": 1}, "conclusion_changed": True, "explanation": "x", "severity": "low"}
    store.notice_add({**base, "notice_id": f"{tag}-p1", "answer_id": f"{tag}-p1", "digest_status": "pending"})
    store.notice_add({**base, "notice_id": f"{tag}-p2", "answer_id": f"{tag}-p2", "digest_status": "pending", "review_status": "pending"})
    ids = {n["notice_id"] for n in store.digest_pending()}
    assert f"{tag}-p1" in ids and f"{tag}-p2" not in ids


def test_change_store_monitoring_and_changes_on_postgres(tag):
    cs = PgChangeStore(DSN)
    with _conn() as c:
        before = c.execute("SELECT status FROM change_monitoring WHERE id = 1").fetchone()
    try:
        assert cs.monitoring_set("paused", "admin")["status"] == "paused"
        with _conn() as c:
            assert monitoring_paused(c) is True
        assert cs.monitoring_get()["status"] == "paused"
        assert cs.monitoring_set("active", "admin")["status"] == "active"
        with _conn() as c:
            assert monitoring_paused(c) is False
        with pytest.raises(ValueError):
            cs.monitoring_set("stopped", "admin")
    finally:
        with _conn() as c:
            if before:
                c.execute("UPDATE change_monitoring SET status = %s WHERE id = 1", (before[0],))
            else:
                c.execute("DELETE FROM change_monitoring WHERE id = 1")

    eid = f"{tag}-chg"
    with _conn() as c:
        run_id = c.execute("INSERT INTO sync_runs (job, slot, trigger, status, started_at) VALUES (%s, %s, 'manual', 'succeeded', now()) "
                           "RETURNING run_id", (JOB, tag)).fetchone()[0]
        c.execute("INSERT INTO docs (rule_seq, org, title, source_url, fetched_at) VALUES (%s, 'TEST', '가상 정책', 'https://example.invalid/p', now()) "
                  "ON CONFLICT DO NOTHING", (SEQ_PG,))
        c.execute("INSERT INTO changed_articles (event_id, run_id, rule_seq, article, old_version_date, new_version_date, change_type) "
                  "VALUES (%s, %s, %s, %s, %s, %s, 'modified')", (eid, run_id, SEQ_PG, ARTICLE, OLD_DATE, NEW_DATE))
    try:
        items, more = cs.changes("2025-01-01", 5000)
        mine = [i for i in items if i["event_id"] == eid]
        assert mine and mine[0]["page_title"] == "가상 정책" and mine[0]["status"] == "pending" and more is False
        assert cs.get(eid)["rule_seq"] == SEQ_PG and cs.get("pgt-없음") is None
        assert any(i["event_id"] == eid for i in cs.pending(5000))
        cs.set_status(eid, "sent")
        assert not any(i["event_id"] == eid for i in cs.pending(5000))
        with pytest.raises(ValueError):
            cs.set_status(eid, "bogus")
        assert cs.last_run() is not None
        page, more = cs.changes("2025-01-01", 1)
        assert len(page) == 1
    finally:
        with _conn() as c:
            c.execute("DELETE FROM changed_articles WHERE event_id = %s", (eid,))
            c.execute("DELETE FROM sync_runs WHERE run_id = %s", (run_id,))
            c.execute("DELETE FROM docs WHERE rule_seq = %s", (SEQ_PG,))


def test_pg_links_and_acl_read_chunks(tag):
    up, low = SEQ_PG + 1, SEQ_PG + 2
    with _conn() as c:
        for seq in (up, low):
            c.execute("INSERT INTO docs (rule_seq, org, title, source_url, fetched_at) VALUES (%s, 'TEST', %s, 'https://example.invalid/p', now())",
                      (seq, f"가상 정책 {seq}"))
            c.execute("INSERT INTO versions (rule_seq, version_id, version_date, valid_from) VALUES (%s, 'v1', '2025-01-01', '2025-01-01')", (seq,))
        c.execute("INSERT INTO chunks (chunk_id, version_id, rule_seq, seq, ord, article, kind, text, source_url, acl, link_targets) "
                  "VALUES (%s, 'v1', %s, 0, 0, '하위 섹션', 'article', 't', 'https://example.invalid/p', '{team-a,team-b}', %s)",
                  (tag + "-c", low, [up]))
    try:
        links = PgLinks(DSN)
        assert links.linked_from(up) == [{"rule_seq": low, "article": "하위 섹션", "title": f"가상 정책 {low}"}]
        assert links.linked_from(low) == [] and links.page_title(up) == f"가상 정책 {up}" and links.page_title(1) is None
        acl = PgAcl(DSN)
        assert acl.groups_for(low, "하위 섹션") == {"team-a", "team-b"} and acl.groups_for(up, "없음") == set()
    finally:
        with _conn() as c:
            c.execute("DELETE FROM chunks WHERE chunk_id = %s", (tag + "-c",))
            c.execute("DELETE FROM versions WHERE rule_seq IN (%s, %s)", (up, low))
            c.execute("DELETE FROM docs WHERE rule_seq IN (%s, %s)", (up, low))