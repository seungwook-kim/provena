"""DB 재정렬 마이그레이션 시험 (db/109_realign.sql, 결정 0090).

옛 모양으로 만든 DB(운영 Supabase와 같은 모양: answer_grounding, recall_feedback, issue_table_rejections 표와 옛 색인)에 109를 적용하면
데이터가 합친 칸으로 옮겨지고, 옛 표는 이름만 바뀌어 남고, 다시 돌려도 같고, 합친 구조의 db 파일을 그 위에 다시 실행해도 되는지 본다.
새 DB에서 db/ 파일을 처음부터 두 번 적용해 표 목록이 합친 구조인지도 본다.

Postgres가 있어야 한다: PROVENA_D5_PG_URL(역할과 DB를 만들 수 있는 접속 정보, test_decision_approval.py와 같은 값)이 없으면 건너뛴다. 내려받거나 컨테이너를 만들지 않는다.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN = os.getenv("PROVENA_D5_PG_URL")
pytestmark = pytest.mark.skipif(not ADMIN, reason="PROVENA_D5_PG_URL 없음")

MERGED_AWAY = ("answer_grounding", "recall_feedback", "issue_table_rejections")
OLD = "_old_20261110"

# 109 이전 모양 (운영 Supabase 2026-11-10 조회와 같은 표·색인). 합치지 않은 표의 정의는 현재 db 파일을 그대로 쓴다.
OLD_SHAPE = """
CREATE TABLE answers (answer_id text PRIMARY KEY, user_id text NOT NULL, thread_id text NOT NULL DEFAULT '', question text NOT NULL,
    answer text NOT NULL, as_of text, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX answers_user_idx ON answers (user_id, created_at DESC);
CREATE TABLE answer_grounding (answer_id text PRIMARY KEY REFERENCES answers (answer_id) ON DELETE CASCADE,
    grounding jsonb NOT NULL DEFAULT '{}'::jsonb, skills_used jsonb NOT NULL DEFAULT '[]'::jsonb);
CREATE TABLE recall_notices (notice_id text PRIMARY KEY, event_key text NOT NULL, answer_id text NOT NULL, user_id text NOT NULL, thread_id text,
    question text, answer_excerpt text, changed jsonb NOT NULL, conclusion_changed boolean NOT NULL, explanation text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('high', 'low')), confidence double precision, change_pattern text NOT NULL DEFAULT '',
    review_status text, review_reason text, digest_status text, judge_failed boolean NOT NULL DEFAULT false,
    acked boolean NOT NULL DEFAULT false, acked_at timestamptz, source_url text, old_text text, new_text text,
    created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (answer_id, event_key));
CREATE TABLE recall_feedback (notice_id text PRIMARY KEY, user_id text NOT NULL, answer_id text NOT NULL, rule_seq bigint NOT NULL,
    article text NOT NULL, pattern text NOT NULL DEFAULT '', severity text, useful boolean NOT NULL, reason text NOT NULL DEFAULT '',
    given_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX recall_feedback_key_idx ON recall_feedback (user_id, rule_seq, article, pattern);
CREATE TABLE issue_tables (table_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), approval_id text NOT NULL UNIQUE, thread_id text NOT NULL,
    user_id text NOT NULL, request text NOT NULL, as_of date, issue_rows jsonb NOT NULL, unreviewed jsonb NOT NULL DEFAULT '[]'::jsonb,
    approved_by text, approved_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX issue_tables_thread_idx ON issue_tables (thread_id);
CREATE INDEX issue_tables_user_idx ON issue_tables (user_id, approved_at DESC);
CREATE TABLE issue_table_rejections (approval_id text PRIMARY KEY, thread_id text NOT NULL, user_id text NOT NULL,
    reason text NOT NULL DEFAULT '', decided_by text, decided_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX admin_role_log_at ON admin_role_log (at);
"""


def _url(db: str) -> str:
    u = urlsplit(ADMIN)
    return urlunsplit((u.scheme, u.netloc, f"/{db}", "", ""))


@pytest.fixture()
def db():
    import psycopg

    name = "provena_realign_" + uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    try:
        yield _url(name)
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _sql(name: str) -> str:
    return (ROOT / "db" / name).read_text(encoding="utf-8")


def _tables(c) -> set[str]:
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")}


def _indexes(c) -> set[str]:
    return {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}


def _old_db(url: str):
    import psycopg

    c = psycopg.connect(url, autocommit=True)
    c.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for f in ("101_auth_users.sql", "102_decision_approvals.sql", "105_admin_role_log.sql"):
        c.execute(_sql(f))
    c.execute(OLD_SHAPE)
    # 승인함: 쟁점표 반려 3건(둘은 사유 칸이 비어 있고 하나는 이미 사유가 있다), 그 밖의 줄 하나
    for aid, st, cm in (("ap-r1", "rejected", ""), ("ap-r2", "rejected", ""), ("ap-r3", "rejected", "승인함 사유"), ("ap-ok", "approved", "")):
        c.execute("INSERT INTO approvals (approval_id, kind, thread_id, status, target_id, comment) VALUES (%s, 'issue_table', %s, %s, 'x', %s)",
                  (aid, "t-" + aid, st, cm))
    for aid, reason, by in (("ap-r1", "옛 표 사유 1", "admin-1"), ("ap-r2", "옛 표 사유 2", None), ("ap-r3", "옛 표 사유 3", "admin-3"),
                            ("ap-고아", "승인함에 줄이 없음", "admin-9")):
        c.execute("INSERT INTO issue_table_rejections (approval_id, thread_id, user_id, reason, decided_by) VALUES (%s, %s, 'u', %s, %s)",
                  (aid, "t-" + aid, reason, by))
    for i in (1, 2, 3):
        c.execute("INSERT INTO answers (answer_id, user_id, question, answer) VALUES (%s, 'u1', 'q', 'a')", (f"a{i}",))
    c.execute("INSERT INTO answer_grounding (answer_id, grounding, skills_used) VALUES ('a1', '{\"grounded\": true}', '[\"s1\"]'), ('a2', '{}', '[]')")
    ch = '{"rule_seq": 7, "article": "Art", "change_type": "modified"}'
    for i in (1, 2, 3):
        c.execute("INSERT INTO recall_notices (notice_id, event_key, answer_id, user_id, changed, conclusion_changed, explanation, severity, change_pattern) "
                  "VALUES (%s, %s, %s, 'u1', %s::jsonb, true, 'e', 'high', 'amount')", (f"n{i}", f"ev{i}", f"a{i}", ch))
    c.execute("INSERT INTO recall_feedback (notice_id, user_id, answer_id, rule_seq, article, pattern, useful, reason, given_by) VALUES "
              "('n1', 'u1', 'a1', 7, 'Art', 'amount', false, '관련 없음', 'u1'), ('n-고아', 'u1', 'a9', 7, 'Art', 'amount', true, '', 'u1')")
    return c


def test_109_moves_data_renames_old_tables_and_is_repeatable(db):
    c = _old_db(db)
    before = _tables(c)
    assert set(MERGED_AWAY) <= before and {"answers_user_idx", "issue_tables_thread_idx", "issue_tables_user_idx", "admin_role_log_at"} <= _indexes(c)

    sql = _sql("109_realign.sql")
    c.execute(sql)
    after = _tables(c)
    assert not set(MERGED_AWAY) & after and {n + OLD for n in MERGED_AWAY} <= after
    assert after - {n + OLD for n in MERGED_AWAY} == before - set(MERGED_AWAY)               # 그 밖의 표는 그대로, 새 표도 없다
    assert c.execute(f"SELECT count(*) FROM answer_grounding{OLD}").fetchone()[0] == 2        # 옛 데이터는 그대로 남는다

    # answer_grounding -> answers: 기록이 있던 답만 NULL 이 아니다
    got = dict((r[0], (r[1], r[2])) for r in c.execute("SELECT answer_id, grounding, skills_used FROM answers ORDER BY 1"))
    assert got["a1"] == ({"grounded": True}, ["s1"]) and got["a2"] == ({}, []) and got["a3"] == (None, None)
    # recall_feedback -> recall_notices: 알림이 있는 의견만 옮겨진다(고아 의견은 _old 에만)
    fb = c.execute("SELECT notice_id, feedback_useful, feedback_reason, feedback_by FROM recall_notices WHERE feedback_useful IS NOT NULL").fetchall()
    assert fb == [("n1", False, "관련 없음", "u1")]
    assert c.execute(f"SELECT count(*) FROM recall_feedback{OLD}").fetchone()[0] == 2
    # issue_table_rejections -> approvals: 빈 사유만 채우고 이미 있던 사유는 지키며, 줄이 없던 것은 건너뛴다. 줄 수는 그대로
    appr = {r[0]: (r[1], r[2]) for r in c.execute("SELECT approval_id, comment, decided_by FROM approvals")}
    assert len(appr) == 4 and appr["ap-r1"] == ("옛 표 사유 1", "admin-1") and appr["ap-r2"] == ("옛 표 사유 2", None)
    assert appr["ap-r3"][0] == "승인함 사유" and appr["ap-ok"] == ("", None)
    # 색인
    idx = _indexes(c)
    assert not {"answers_user_idx", "issue_tables_thread_idx", "issue_tables_user_idx", "admin_role_log_at"} & idx
    assert {"issue_tables_thread_user_idx", "recall_notices_feedback_idx"} <= idx
    # 의견 집계가 부분 색인 식으로 같은 값을 준다
    n = c.execute("SELECT count(*) FROM recall_notices WHERE user_id = 'u1' AND change_pattern = 'amount' AND (changed ->> 'article') = 'Art' "
                  "AND ((changed ->> 'rule_seq')::bigint) = 7 AND feedback_useful IS NOT NULL").fetchone()[0]
    assert n == 1

    snapshot = (sorted(after), sorted(idx), got, appr)
    c.execute(sql)                                                                             # 다시 돌려도 같다
    again = (sorted(_tables(c)), sorted(_indexes(c)),
             dict((r[0], (r[1], r[2])) for r in c.execute("SELECT answer_id, grounding, skills_used FROM answers ORDER BY 1")),
             {r[0]: (r[1], r[2]) for r in c.execute("SELECT approval_id, comment, decided_by FROM approvals")})
    assert again == snapshot
    # 합친 구조의 db 파일을 그 위에 다시 실행해도 옛 표가 되살아나지 않고 오류도 없다
    for f in ("110_issue_tables.sql", "120_answers_recall.sql", "105_admin_role_log.sql"):
        c.execute(_sql(f))
    assert not set(MERGED_AWAY) & _tables(c)
    c.close()


def test_109_revokes_public_api_roles_when_they_exist(db):
    import psycopg

    created = []
    with psycopg.connect(ADMIN, autocommit=True) as a:
        for role in ("anon", "authenticated"):
            if not a.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                a.execute(f"CREATE ROLE {role} NOLOGIN")
                created.append(role)
    try:
        c = _old_db(db)
        c.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated")     # Supabase가 새 표에 여는 권한과 같게
        c.execute(_sql("109_realign.sql"))
        left = c.execute("SELECT c.relname, r.rolname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace CROSS JOIN pg_roles r "
                         "WHERE n.nspname = 'public' AND c.relkind = 'r' AND r.rolname IN ('anon', 'authenticated') "
                         "AND (has_table_privilege(r.oid, c.oid, 'SELECT') OR has_table_privilege(r.oid, c.oid, 'INSERT') "
                         "OR has_table_privilege(r.oid, c.oid, 'UPDATE') OR has_table_privilege(r.oid, c.oid, 'DELETE'))").fetchall()
        assert left == []
        c.execute("CREATE TABLE later_table (id int)")                                     # 앞으로 만드는 표도 같다(기본 권한)
        assert c.execute("SELECT has_table_privilege('anon', 'later_table', 'SELECT')").fetchone()[0] is False
        c.close()
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as a:
            a.execute("DROP DATABASE IF EXISTS " + urlsplit(db).path.lstrip("/") + " WITH (FORCE)")
            for role in created:
                a.execute(f"DROP OWNED BY {role}")
                a.execute(f"DROP ROLE {role}")


def test_fresh_database_gets_the_merged_structure_and_109_is_a_noop(db):
    import psycopg

    files = sorted((ROOT / "db").glob("*.sql"))
    with psycopg.connect(db, autocommit=True) as c:
        for _ in range(2):                                                                   # 처음부터 두 번(여러 번 돌려도 된다)
            for f in files:
                c.execute(f.read_text(encoding="utf-8"))
        tables = _tables(c)
        assert not set(MERGED_AWAY) & tables and not {t for t in tables if "_old_" in t}
        assert {"answers", "recall_notices", "approvals", "issue_tables", "chunks", "changed_articles"} <= tables
        cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'answers'")}
        assert {"grounding", "skills_used"} <= cols
        cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'recall_notices'")}
        assert {"feedback_useful", "feedback_reason", "feedback_by", "feedback_at"} <= cols
        assert {"recall_notices_feedback_idx", "issue_tables_thread_user_idx"} <= _indexes(c)
        assert not {"answers_user_idx", "admin_role_log_at", "issue_tables_user_idx", "issue_tables_thread_idx"} & _indexes(c)
