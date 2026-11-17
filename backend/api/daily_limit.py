"""사용자별 하루 질문 한도 (`DAILY_QUESTION_LIMIT`, docs/specs/llm.md 환경 변수 표, SDD 4-4).

- 한도: 환경 변수 `DAILY_QUESTION_LIMIT`(기본 50). `0`, `off`, `false`, `no`이면 한도 없음. 숫자가 아니거나 음수면 경고를 남기고 기본값 50을 쓴다.
- 하루: 한국 시각(KST, UTC+9) 자정부터 다음 자정 전까지. 한국은 서머타임이 없어 고정 +09:00으로 계산한다(`kst_day_window`).
- 세는 곳: 서버 메모리가 아니라 DB다. 인스턴스가 여러 개여도 같은 값을 본다. `/chat` 질문 하나마다 질문 그래프가 입력 체크포인트
  (LangGraph `checkpoints` 표, `checkpoint_ns = ''`, `metadata.source = 'input'`) 한 줄을 남기므로 그 줄을 센다. 이어 묻기·거절·되묻기도 한 건이다.
  thread 이름은 `<user_id>:<thread_id>`이고, 시각은 체크포인트의 `ts`(UTC ISO 문자열)다.
- 비용: 먼저 `threads` 표의 `(user_id, updated_at)` 색인으로 오늘 손댄 대화만 고르고(질문마다 `thread_touch`가 `updated_at`을 바꾼다),
  그 대화의 체크포인트만 기본키 색인으로 읽는다. 운영 DB에서 오늘 192건인 계정이 5.6ms, 0건인 계정이 0.6ms였다(2026-11-17 읽기 전용 EXPLAIN ANALYZE).
- 메모리 체크포인터(시험·로컬)는 체크포인터의 `list()`로 같은 규칙을 센다.
- 세기에 실패하면(DB 오류) 질문을 막지 않고 경고 로그만 남긴다. 같은 순간에 같은 사용자의 질문이 여러 개 들어오면 한도를 몇 건 넘길 수 있다(잠금 없이 센다).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DAILY_QUESTION_LIMIT = 50
KST = timezone(timedelta(hours=9), "KST")
OFF_VALUES = {"0", "off", "false", "no"}
DAILY_LIMIT_CODE = "daily_limit"

# 오늘 손댄 대화(threads 색인) -> 그 대화의 입력 체크포인트(checkpoints 기본키 색인). 시각 비교는 timestamptz로 한다
COUNT_SQL = (
    "SELECT count(*) AS n FROM checkpoints c WHERE c.thread_id IN ("
    "SELECT %(uid)s || ':' || t.thread_id FROM threads t WHERE t.user_id = %(uid)s AND t.updated_at >= %(start)s) "
    "AND c.checkpoint_ns = '' AND c.metadata->>'source' = 'input' "
    "AND (c.checkpoint->>'ts')::timestamptz >= %(start)s AND (c.checkpoint->>'ts')::timestamptz < %(end)s"
)


def daily_question_limit() -> int:
    """`DAILY_QUESTION_LIMIT`. 0이면 한도 없음. 규칙은 모듈 설명."""
    raw = (os.environ.get("DAILY_QUESTION_LIMIT") or "").strip().lower()
    if not raw:
        return DEFAULT_DAILY_QUESTION_LIMIT
    if raw in OFF_VALUES:
        return 0
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        log.warning("DAILY_QUESTION_LIMIT=%r는 0 이상 정수가 아니라 기본값 %d을 씁니다", raw, DEFAULT_DAILY_QUESTION_LIMIT)
        return DEFAULT_DAILY_QUESTION_LIMIT
    return value


def kst_day_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """`now`가 속한 한국 날짜의 [자정, 다음 자정) 구간. 시간대가 없는 `now`는 UTC로 본다."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def limit_message(limit: int) -> str:
    return f"오늘 질문 한도({limit}건)를 넘었습니다. 내일 다시 이용해 주세요."


def _parse_ts(value: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def _count_postgres(saver: Any, user_id: str, start: datetime, end: datetime) -> int:
    with saver.conn.connection() as conn:   # 체크포인터의 연결 풀(autocommit, 준비된 문장 없음, dict_row)
        row = conn.execute(COUNT_SQL, {"uid": user_id, "start": start, "end": end}).fetchone()
    if row is None:
        return 0
    return int(row["n"] if isinstance(row, dict) else row[0])


def _count_listing(saver: Any, user_id: str, start: datetime, end: datetime) -> int:
    prefix = f"{user_id}:"
    n = 0
    for item in saver.list(None, filter={"source": "input"}):
        conf = (item.config or {}).get("configurable") or {}
        if not str(conf.get("thread_id") or "").startswith(prefix) or conf.get("checkpoint_ns", ""):
            continue
        ts = _parse_ts((item.checkpoint or {}).get("ts"))
        if ts is not None and start <= ts < end:
            n += 1
    return n


def count_questions_today(saver: Any, user_id: str, now: datetime | None = None) -> int:
    """오늘(KST) 이 사용자가 `/chat`으로 보낸 질문 수. 체크포인터가 없으면 0."""
    if saver is None:
        return 0
    start, end = kst_day_window(now)
    if type(saver).__name__ == "PostgresSaver":
        return _count_postgres(saver, user_id, start, end)
    return _count_listing(saver, user_id, start, end)


def check_daily_limit(saver: Any, user_id: str, *, now: datetime | None = None) -> tuple[int, int, datetime] | None:
    """한도에 닿았으면 (한도, 오늘 센 수, 다음 자정 KST)를, 아니면 None을 돌려준다. 한도가 꺼져 있거나 세기에 실패하면 None."""
    limit = daily_question_limit()
    if limit <= 0:
        return None
    try:
        used = count_questions_today(saver, user_id, now)
    except Exception as exc:  # noqa: BLE001 - DB 오류는 질문을 막지 않는다. 접속 문자열이 섞일 수 있어 종류만 남긴다
        log.warning("하루 질문 수를 세지 못해 한도 검사를 건너뜀: %s", type(exc).__name__)
        return None
    if used < limit:
        return None
    return limit, used, kst_day_window(now)[1]
