"""처리 대기 중인 바뀐 섹션을 리콜에 넘긴다: `changed_articles.status = pending` -> 리콜 처리 -> `sent` 또는 `failed`.

    python -m backend.graph.recall.process_pending [--limit 50] [--force]

- 한 줄마다 `RecallService.process`(event_key = event_id). 이미 처리한 개정은 다시 판정하지 않고 `sent`로 둔다(EC-06).
  다른 처리기가 같은 개정을 처리 중이면 그대로 `pending`으로 둔다(다음 실행이 본다).
- 처리 중 예외가 나면 그 줄만 `failed`로 두고 다음 줄을 이어 간다. 다시 돌리려면 `pending`으로 되돌린다(실패한 개정은 다시 판정한다).
- 명령줄은 변경 감시가 `paused`이면 아무것도 하지 않는다(`--force`로 무시). 관리자 `POST /recalls/process-pending`은 스위치와 무관하다.
- 웹훅은 명령줄에서는 처리 뒤 바로 보내고, API에서는 응답 뒤 백그라운드로 보낸다.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from backend.graph.recall.monitor import changed_of

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def process_pending(service: Any, changes: Any, *, limit: int = DEFAULT_LIMIT) -> dict:
    """반환: 처리 요약과 보낼 알림 id(`to_send`)."""
    out = {"processed": 0, "sent": 0, "failed": 0, "skipped": 0, "notices": 0, "review": 0, "judge_failures": 0, "candidates": 0,
           "to_send": []}
    for row in changes.pending(limit):
        eid = row["event_id"]
        out["processed"] += 1
        try:
            res = service.process(changed_of(row), event_key=eid)
        except Exception as e:  # noqa: BLE001 - 한 줄이 실패해도 나머지는 이어 간다
            log.warning("리콜 처리 실패 event_id=%s: %s", eid, type(e).__name__)
            changes.set_status(eid, "failed")
            out["failed"] += 1
            continue
        if res["status"] == "skipped":
            ev = service.store.event_get(eid) or {}
            if ev.get("status") != "done":
                out["skipped"] += 1            # 처리 중인 다른 실행이 있다. 다음 실행이 다시 본다
                continue
        changes.set_status(eid, "sent")
        out["sent"] += 1
        out["notices"] += len(res["notices"])
        out["review"] += res["review"]
        out["judge_failures"] += len(res["judge_failures"])
        out["candidates"] += res["candidates"]
        out["to_send"] += res["to_send"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.graph.recall.process_pending", description="처리 대기 중인 바뀐 섹션을 리콜에 넘긴다")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"한 번에 처리할 최대 줄 수(1~{MAX_LIMIT})")
    ap.add_argument("--force", action="store_true", help="변경 감시가 paused여도 처리한다")
    a = ap.parse_args(argv)
    if not 1 <= a.limit <= MAX_LIMIT:
        ap.error(f"--limit는 1~{MAX_LIMIT}")
    from backend.graph.recall.runtime import build_service_from_env, make_change_store

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    changes = make_change_store()
    if not a.force and changes.monitoring_get().get("status") == "paused":
        print(json.dumps({"status": "paused"}, ensure_ascii=False))
        return 0
    service = build_service_from_env()
    res = process_pending(service, changes, limit=a.limit)
    deliveries = service.dispatch(res.pop("to_send"))
    print(json.dumps({"status": "done", **res, "deliveries": len(deliveries)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
