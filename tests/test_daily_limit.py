"""사용자별 하루 질문 한도(`DAILY_QUESTION_LIMIT`, `backend/api/daily_limit.py`). 메모리 체크포인터와 가짜 DB 연결만 쓴다(네트워크·DB 없음)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from api_test_support import Env, ask

from backend.api import daily_limit as D

UTC = timezone.utc


@pytest.mark.parametrize("raw, expected", [(None, 50), ("", 50), ("30", 30), ("0", 0), ("off", 0), ("OFF", 0), ("false", 0), ("no", 0),
                                           ("-1", 50), ("abc", 50)])
def test_limit_env_parsing(monkeypatch, raw, expected):
    monkeypatch.delenv("DAILY_QUESTION_LIMIT", raising=False)
    if raw is not None:
        monkeypatch.setenv("DAILY_QUESTION_LIMIT", raw)
    assert D.daily_question_limit() == expected


def test_kst_day_window_boundaries():
    # 2026-11-17 23:59:59 KST = 14:59:59 UTC → 그날 KST 자정(11-16 15:00 UTC)부터 다음 자정(11-17 15:00 UTC) 전까지
    start, end = D.kst_day_window(datetime(2026, 11, 17, 14, 59, 59, tzinfo=UTC))
    assert start == datetime(2026, 11, 16, 15, 0, tzinfo=UTC) and end == datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
    # 1초 뒤(11-18 00:00:00 KST)는 다음 날이다
    start2, end2 = D.kst_day_window(datetime(2026, 11, 17, 15, 0, 0, tzinfo=UTC))
    assert start2 == end and end2 == end + timedelta(days=1)
    # 시간대 없는 값은 UTC로 본다
    assert D.kst_day_window(datetime(2026, 11, 17, 15, 0, 0)) == (start2, end2)
    assert start.utcoffset() == timedelta(hours=9)


def _item(thread_id: str, ts: str, ns: str = ""):
    return SimpleNamespace(config={"configurable": {"thread_id": thread_id, "checkpoint_ns": ns}}, checkpoint={"ts": ts})


class ListingSaver:
    def __init__(self, items):
        self.items, self.filters = items, []

    def list(self, config, *, filter=None):
        self.filters.append(filter)
        return iter(self.items)


def test_listing_count_uses_kst_window_and_user_prefix():
    now = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)               # 11-17 12:00 KST
    saver = ListingSaver([
        _item("u1:t1", "2026-11-16T15:00:00+00:00"),              # 11-17 00:00:00 KST: 오늘(경계 포함)
        _item("u1:t2", "2026-11-17T14:59:59.999999+00:00"),       # 11-17 23:59:59 KST: 오늘
        _item("u1:t1", "2026-11-16T14:59:59+00:00"),              # 11-16 23:59:59 KST: 어제
        _item("u1:t3", "2026-11-17T15:00:00+00:00"),              # 11-18 00:00 KST: 내일
        _item("u10:t1", "2026-11-17T01:00:00+00:00"),             # 다른 사용자(접두어만 같음)
        _item("u1:t1", "2026-11-17T01:00:00+00:00", ns="review"), # 하위 그래프 체크포인트
        _item("u1:t4", "not-a-date"),
    ])
    assert D.count_questions_today(saver, "u1", now) == 2
    assert saver.filters == [{"source": "input"}]
    assert D.count_questions_today(None, "u1", now) == 0


class FakeConn:
    def __init__(self, n):
        self.n, self.calls = n, []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: {"n": self.n})


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connection(self):
        yield self.conn


def test_postgres_count_uses_indexed_query_with_kst_window():
    conn = FakeConn(7)
    saver = type("PostgresSaver", (), {})()
    saver.conn = FakePool(conn)
    now = datetime(2026, 11, 17, 3, 0, tzinfo=UTC)
    assert D.count_questions_today(saver, "u1", now) == 7
    sql, params = conn.calls[0]
    assert "FROM threads t WHERE t.user_id = %(uid)s AND t.updated_at >= %(start)s" in sql   # threads (user_id, updated_at) 색인
    assert "c.checkpoint_ns = ''" in sql and "c.metadata->>'source' = 'input'" in sql
    assert params == {"uid": "u1", "start": datetime(2026, 11, 16, 15, 0, tzinfo=UTC), "end": datetime(2026, 11, 17, 15, 0, tzinfo=UTC)}


def test_check_is_off_at_zero_and_fails_open(monkeypatch):
    class Broken:
        def list(self, *a, **k):
            raise RuntimeError("db down")

    monkeypatch.setenv("DAILY_QUESTION_LIMIT", "1")
    assert D.check_daily_limit(Broken(), "u1") is None          # 세기 실패는 막지 않는다
    full = ListingSaver([_item("u1:t1", datetime.now(UTC).isoformat())])
    limit, used, resets = D.check_daily_limit(full, "u1")
    assert (limit, used) == (1, 1) and resets > datetime.now(UTC)
    monkeypatch.setenv("DAILY_QUESTION_LIMIT", "0")
    assert D.check_daily_limit(full, "u1") is None


def test_chat_returns_429_daily_limit_before_running_the_graph(monkeypatch):
    with Env(monkeypatch) as env:
        monkeypatch.setenv("DAILY_QUESTION_LIMIT", "2")
        alice, bob = env.client(env.alice), env.client(env.bob)
        for _ in range(2):
            r, events = ask(alice, "What is the expense approval limit?")
            assert r.status_code == 200 and events[-1][0] == "done"
        saver = env.app.state.question_graph.checkpointer
        assert D.count_questions_today(saver, str(env.alice.user_id)) == 2

        r, _ = ask(alice, "What is the expense approval limit?")
        assert r.status_code == 429
        body = r.json()
        message = "오늘 질문 한도(2건)를 넘었습니다. 내일 다시 이용해 주세요."
        assert body["error"]["code"] == "daily_limit"
        assert body["error"]["message"] == message and body["detail"] == message
        assert body["error"]["request_id"] == r.headers["X-Request-ID"]
        assert body["error"]["details"]["limit"] == 2 and body["error"]["details"]["used"] == 2
        assert body["error"]["details"]["resets_at"].endswith("+09:00")
        assert 0 < int(r.headers["Retry-After"]) <= 86400
        # 막힌 질문은 그래프를 돌리지 않았다(입력 체크포인트가 늘지 않음)
        assert D.count_questions_today(saver, str(env.alice.user_id)) == 2

        # 한도는 사람마다 따로다
        r, events = ask(bob, "What is the expense approval limit?")
        assert r.status_code == 200 and events[-1][0] == "done"

        # 0이면 한도 없음
        monkeypatch.setenv("DAILY_QUESTION_LIMIT", "0")
        r, events = ask(alice, "What is the expense approval limit?")
        assert r.status_code == 200
