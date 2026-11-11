"""대화 상태 저장소(`api/threads.py`)와 인증 조회(`services/auth_store.py`)의 연결 다시 쓰기 시험 (사용자 결정 23 ①, 사전 등록 62.40).

답 저장소와 같은 스위치(`ANSWER_STORE_REUSE_CONN`)와 같은 방식(`graph/answer_store.py` `_ConnectionReuse`)이다.
- 꺼져 있으면 호출마다 연결하고 오류는 한 번만 부른다(지금과 같다).
- 켜져 있으면 인증된 요청마다 도는 읽기(`get_by_user_id`·`get_by_login_id`·`is_revoked`)와 대화 상태(`thread_touch`·`thread_get`·`threads_of`)가 연결을 다시 쓰고,
  서버가 끊은 연결이면 새 연결로 한 번 더 부른다. 결과는 같다.
- 가입·승인 같은 쓰기와 여러 문장 트랜잭션은 켜져 있어도 호출마다 연결한다.
가짜 연결만 쓴다(DB 0, 유료 0).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import backend.graph.answer_store as AS
from backend.api import threads as T
from backend.services import auth_store as A

UID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ROW = (UID, "alice@example.com", "hash", "user", True)


class Cur:
    def __init__(self, conn, sql):
        self.conn, self.sql = conn, sql
        self.description = [("x",)]

    def fetchone(self):
        return self.conn.rows.get("one")

    def fetchall(self):
        return self.conn.rows.get("all", [])

    def execute(self, sql, params=None):
        self.conn.log.append(("exec", self.conn.ident, " ".join(sql.split())[:24]))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Conn:
    """재사용 풀이 읽는 만큼만 가진 가짜 연결. `drop_first`면 첫 문장에서 서버가 끊은 연결처럼 OperationalError를 낸다."""

    def __init__(self, log, ident, rows, drop_first=False):
        from psycopg.pq import TransactionStatus

        self.log, self.ident, self.rows, self.closed, self.drop_first = log, ident, rows, False, drop_first
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)

    def close(self):
        self.closed = True
        self.log.append(("close", self.ident))

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def cursor(self, row_factory=None):
        import psycopg

        if self.drop_first:
            self.drop_first, self.closed = False, True
            raise psycopg.OperationalError("서버가 연결을 닫았다")
        return Cur(self, "")

    def __enter__(self):          # 평소(재사용 끔) `with psycopg.connect(...)` 모양
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture()
def fake_pg(monkeypatch):
    """`psycopg.connect`를 가짜로 바꾼다. `state.opened`가 지금까지 연 연결, `state.drop`이 끊긴 채로 열 연결 번호."""
    import psycopg

    state = SimpleNamespace(opened=[], log=[], rows={"one": (False,), "all": []}, drop=set())

    def connect(*a, **k):
        c = Conn(state.log, len(state.opened) + 1, state.rows, drop_first=(len(state.opened) + 1) in state.drop)
        state.opened.append(c)
        return c

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.delenv("ANSWER_STORE_REUSE_CONN", raising=False)
    return state


DSN = "postgresql://u:p@127.0.0.1:1/x"


# ---------- 스위치 ----------

def test_switch_off_connects_per_call_and_does_not_retry(fake_pg):
    import psycopg

    fake_pg.rows["one"] = USER_ROW
    store = A.PostgresAuthStore(DSN)
    assert store.get_by_user_id(UID).login_id == "alice@example.com" and store.get_by_user_id(UID) is not None
    assert len(fake_pg.opened) == 2 and all(c.closed for c in fake_pg.opened)          # 호출마다 연결하고 닫는다(지금과 같다)
    fake_pg.drop.add(3)
    with pytest.raises(psycopg.OperationalError):
        store.get_by_user_id(UID)                                                      # 꺼져 있으면 다시 부르지 않는다
    assert len(fake_pg.opened) == 3


def test_switch_on_reuses_one_connection_for_the_per_request_auth_reads(fake_pg, monkeypatch):
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    fake_pg.rows["one"] = USER_ROW
    store = A.PostgresAuthStore(DSN)
    for _ in range(3):
        assert store.get_by_user_id(UID).role == "user"
    assert store.get_by_login_id("alice@example.com").user_id == UID
    assert len(fake_pg.opened) == 1 and not fake_pg.opened[0].closed
    fake_pg.rows["one"] = (True,)
    rev = A.PostgresTokenRevocationStore(DSN)
    assert rev.is_revoked("j1") is True and rev.is_revoked("j2") is True
    assert len(fake_pg.opened) == 2                                                   # 폐기 저장소의 연결 하나(저장소마다 따로 다시 쓴다)


def test_switch_on_reads_give_the_same_results_as_off(fake_pg, monkeypatch):
    def run():
        fake_pg.rows["one"] = USER_ROW
        s = A.PostgresAuthStore(DSN)
        out = [s.get_by_user_id(UID), s.get_by_login_id("alice@example.com"), s.get_by_user_id("not-a-uuid")]
        fake_pg.rows["one"] = None
        out.append(s.get_by_user_id(UID))
        fake_pg.rows["one"] = (True,)
        r = A.PostgresTokenRevocationStore(DSN)
        fake_pg.rows["one"] = (False,)
        return out + [r.is_revoked("j")]

    off = run()
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    assert run() == off and off[-1] is False and off[3] is None and off[2] is None


def test_switch_on_retries_the_read_once_with_a_new_connection_when_the_kept_one_was_closed_by_the_server(fake_pg, monkeypatch):
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    fake_pg.rows["one"] = USER_ROW
    fake_pg.drop.add(1)                                      # 첫 연결은 서버 쪽에서 끊겨 있다
    user = A.PostgresAuthStore(DSN).get_by_user_id(UID)
    assert user is not None and user.user_id == UID
    assert len(fake_pg.opened) == 2 and fake_pg.opened[0].closed and not fake_pg.opened[1].closed


def test_switch_on_second_failure_is_raised_not_swallowed(fake_pg, monkeypatch):
    import psycopg

    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    fake_pg.drop.update({1, 2})
    with pytest.raises(psycopg.OperationalError):
        A.PostgresTokenRevocationStore(DSN).is_revoked("j")  # 한 번만 다시 부른다(무한히 되풀이하지 않는다)
    assert len(fake_pg.opened) == 2


def test_writes_and_multi_statement_calls_keep_connecting_per_call_even_when_the_switch_is_on(fake_pg, monkeypatch):
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    store = A.PostgresAuthStore(DSN)
    assert not isinstance(store._connect, AS._ConnectionReuse) and isinstance(store._read_connect, AS._ConnectionReuse)
    assert not isinstance(A.PostgresTokenRevocationStore(DSN)._connect, AS._ConnectionReuse)
    store.delete_pending_signup("bob@example.com")
    store.delete_pending_signup("bob@example.com")
    assert len(fake_pg.opened) == 2 and all(c.closed for c in fake_pg.opened)         # 쓰기는 호출마다 연결하고 닫는다


def test_injected_connect_is_used_as_is_for_reads(fake_pg):
    """시험이 `connect`를 넣으면 읽기도 그 연결을 쓴다(재사용 감쌈 없음, 재시도 없음)."""
    calls = []
    c = Conn([], 1, {"one": USER_ROW})

    def connect():
        calls.append(1)
        return c

    s = A.PostgresAuthStore(connect=connect)
    assert s._read_connect is connect and s.get_by_user_id(UID).login_id == "alice@example.com" and len(calls) == 1


# ---------- 대화 상태 저장소 ----------

def test_threads_switch_off_connects_per_call(fake_pg):
    store = T.PostgresThreadStore(DSN)
    store.thread_touch("u1", "t1", title="질문", status="running")
    assert store.thread_get("u1", "t1") is None
    assert len(fake_pg.opened) == 2 and all(c.closed for c in fake_pg.opened)


def test_threads_switch_on_reuses_one_connection_and_gives_the_same_values(fake_pg, monkeypatch):
    def run(store):
        fake_pg.rows["all"] = [{"thread_id": "t1", "title": "질문", "status": "idle", "last": None, "created_at": "2026-11-11", "updated_at": "2026-11-11"}]
        store.thread_touch("u1", "t1", title="질문", status="running")
        return store.thread_get("u1", "t1"), store.threads_of("u1")

    off = run(T.PostgresThreadStore(DSN))
    n_off = len(fake_pg.opened)
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    start = len(fake_pg.opened)
    on = run(T.PostgresThreadStore(DSN))
    assert on == off and off[0]["thread_id"] == "t1" and n_off == 3
    assert len(fake_pg.opened) - start == 1                                           # 세 호출이 연결 하나


def test_threads_switch_on_retries_the_upsert_once_when_the_kept_connection_was_closed(fake_pg, monkeypatch):
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    fake_pg.drop.add(1)
    T.PostgresThreadStore(DSN).thread_touch("u1", "t1", title="질문", status="running")
    sql = [x for x in fake_pg.log if x[0] == "exec"]
    assert len(fake_pg.opened) == 2 and fake_pg.opened[0].closed and len(sql) == 1 and sql[0][1] == 2 and sql[0][2].startswith("INSERT INTO threads")


def test_threads_switch_off_does_not_retry(fake_pg):
    import psycopg

    fake_pg.drop.add(1)
    with pytest.raises(psycopg.OperationalError):
        T.PostgresThreadStore(DSN).thread_touch("u1", "t1", title="질문")
    assert len(fake_pg.opened) == 1


# ---------- 공용 도우미 ----------

def test_helpers_are_shared_with_the_answer_store(monkeypatch):
    monkeypatch.delenv("ANSWER_STORE_REUSE_CONN", raising=False)
    plain = lambda: None  # noqa: E731
    assert AS.reuse_if_enabled(plain) is plain
    assert AS.run_again(plain, lambda: 7) == 7
    monkeypatch.setenv("ANSWER_STORE_REUSE_CONN", "1")
    wrapped = AS.reuse_if_enabled(plain)
    assert isinstance(wrapped, AS._ConnectionReuse) and AS.run_again(wrapped, lambda: 8) == 8
