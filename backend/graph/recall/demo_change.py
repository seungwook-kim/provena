"""키 없는 데모의 가상 개정 한 건 (2026-11-16, README "키 없이 뜨는 데모 모드"의 데모 구간 03).

키 없는 로컬 데모에는 증분 수집(GitLab 키)이 없어 바뀐 섹션이 생기지 않으므로 리콜 흐름을 볼 수 없었다(L-23). 이 모듈은 `data/demo_replay/scenarios.json`의
`recall` 항목(승인 권한표 2023-05판의 `Approving expense > >$25K up to $50K` 행에서 업무 승인자 한 줄만 바꾼 데모용 가상 개정본, 실제 핸드북 문구 아님)으로
다음 둘만 한다. 리콜 그래프·판정·저장·알림 코드는 그대로다.

- `seed_pending_change`: `changed_articles`에 처리 대기(`pending`) 한 줄을 넣는다(실행 기록 `sync_runs`는 `job = demo_revision`, 증분 수집의 마지막 실행으로 세지 않는다).
  관리자가 리콜 화면의 "처리 대기 변경 지금 처리"(`POST /recalls/process-pending`)를 누르면 리콜이 돈다. 리콜 저장소가 메모리(기본)이면
  다시 시작할 때 알림이 사라지므로 이 줄도 처리 대기로 되돌린다.
- `with_demo_revision`: 섹션 원문 읽기(`runtime.section_reader`)를 감싸, 이 개정의 새 판 날짜로 그 섹션을 읽으면 개정본 글을 돌려준다(개정 전 원문은 DB 그대로).

`runtime.open_recall_runtime`이 로컬 데모(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`)이고 키 없는 데모 모드(`is_demo_mode()`)일 때만 부른다. 운영(Cloud Run)은 둘 다 아니다.
새 판 날짜(2027-07-01)보다 뒤에 물은 답은 새 판 이후 답으로 보아 리콜하지 않는다(`notice.is_affected`).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.rag.ingest.schedule import event_id

log = logging.getLogger(__name__)

SCENARIOS_FILE = Path(__file__).resolve().parents[3] / "data" / "demo_replay" / "scenarios.json"
DEMO_JOB = "demo_revision"
DEMO_VERSION_ID = "demo-revision"
CHANGE_KEYS = ("rule_seq", "article", "old_version_date", "new_version_date", "change_type")


def load_demo_change(path: Path | str | None = None) -> dict | None:
    """`scenarios.json`의 `recall` 항목({rule_seq, article, old_version_date, new_version_date, change_type, new_text}). 파일이나 항목이 없으면 None."""
    p = Path(path) if path is not None else SCENARIOS_FILE
    try:
        rec = json.loads(p.read_text(encoding="utf-8")).get("recall")
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or not all(rec.get(k) not in (None, "") for k in (*CHANGE_KEYS, "new_text")):
        return None
    return {**rec, "rule_seq": int(rec["rule_seq"])}


def changed_of(rec: dict) -> dict:
    return {k: rec[k] for k in CHANGE_KEYS}


def with_demo_revision(reader: Callable[[int, str, str | None], dict | None] | None, rec: dict | None):
    """섹션 읽기 함수를 감싼다. (rule_seq, article, 새 판 날짜) 읽기는 개정 전 섹션의 칸에 개정본 글·새 판 날짜를 넣어 돌려준다. 그 밖의 읽기는 그대로다."""
    if reader is None or rec is None:
        return reader

    def read(rule_seq: int, article: str, as_of: str | None) -> dict | None:
        if int(rule_seq) == rec["rule_seq"] and article == rec["article"] and as_of == rec["new_version_date"]:
            old = reader(rule_seq, article, rec["old_version_date"]) or {}
            return {**old, "rule_seq": rec["rule_seq"], "article": rec["article"], "text": rec["new_text"],
                    "version_id": DEMO_VERSION_ID, "version_date": rec["new_version_date"], "version_date_before": False}
        return reader(rule_seq, article, as_of)

    return read


def seed_pending_change(database_url: str, rec: dict, *, reset: bool, connect: Callable[[], Any] | None = None) -> str | None:
    """가상 개정 한 줄을 `changed_articles`에 넣는다(이미 있으면 그대로, `reset`이면 처리 대기로 되돌린다). event_id, 표가 없으면 None."""
    import psycopg

    eid = event_id(changed_of(rec))
    conn_fn = connect or (lambda: psycopg.connect(database_url, autocommit=True, connect_timeout=5, prepare_threshold=None))
    with conn_fn() as conn:
        ok = conn.execute("SELECT to_regclass('changed_articles') IS NOT NULL AND to_regclass('sync_runs') IS NOT NULL").fetchone()[0]
        if not ok:
            return None
        run_id = conn.execute(
            "INSERT INTO sync_runs (job, slot, trigger, status, started_at, finished_at, articles, detail) "
            "VALUES (%s, 'demo', 'manual', 'succeeded', now(), now(), 1, %s::jsonb) "
            "ON CONFLICT (job, slot) DO UPDATE SET job = EXCLUDED.job RETURNING run_id",
            (DEMO_JOB, json.dumps({"note": "키 없는 데모의 가상 개정(실제 핸드북 변경 아님)"}, ensure_ascii=False)),
        ).fetchone()[0]
        on_conflict = "DO UPDATE SET status = 'pending'" if reset else "DO NOTHING"
        conn.execute(
            "INSERT INTO changed_articles (event_id, run_id, rule_seq, article, old_version_date, new_version_date, change_type, status) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending') ON CONFLICT (event_id) {on_conflict}",
            (eid, run_id, rec["rule_seq"], rec["article"], rec["old_version_date"], rec["new_version_date"], rec["change_type"]),
        )
    return eid
