"""리콜 알림 하루 요약(RECALL_DIGEST=daily, F-08).

- `RECALL_DIGEST=immediate`(기본, 비어 있거나 모르는 값도 같음): 알림마다 바로 웹훅.
- `RECALL_DIGEST=daily`: 새 알림은 앱(`GET /recalls`)에는 바로 보이고 웹훅만 보류한다(`digest_status=pending`).
  `flush_digests`가 사용자별로 쌓인 알림을 요약 한 건(`recall_digests`)과 웹훅 한 건으로 묶는다(중요도 high가 앞).
  관리자 검토함의 알림은 요약에 들어가지 않는다(풀어 주면 그때 쌓인다).
- 요약 웹훅 본문은 알림 한 건과 같은 칸(가장 앞선 알림의 값, 설명은 "[하루 요약 N건 ...]"으로 시작)에 요약 칸을 더한 것이다:
  `{"type": "recall_digest", "digest_id", "day", "count", "high", "low", "notices": [알림 ...]}`. 서명 규칙은 같다(X-Signature).
- 실행: `python -m backend.graph.recall.digest --flush [--day YYYY-MM-DD] [--no-send]`(외부 스케줄러가 하루 한 번, 프로세스 사이에 쌓인
  알림을 보려면 `RECALL_STORE=postgres`) 또는 관리자 `POST /recalls/digest/flush`. 같은 날 두 번 부르면 그 사이 새로 쌓인 알림만 두 번째 요약이 된다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

DIGEST_ENV = "RECALL_DIGEST"


def digest_mode() -> str:
    """"immediate" | "daily". 모르는 값은 immediate."""
    return "daily" if (os.environ.get(DIGEST_ENV) or "").strip().lower() == "daily" else "immediate"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_digest(user_id: str, day: str, notices: list[dict]) -> tuple[str, dict]:
    """(digest_id, 본문). 같은 사용자·날짜·알림 묶음이면 같은 id(다시 돌려도 중복 요약이 생기지 않는다). notices는 알림 JSON 목록."""
    ordered = sorted(notices, key=lambda n: (0 if n.get("severity", "high") == "high" else 1, str(n.get("created_at") or "")))
    ids = [n["notice_id"] for n in ordered]
    did = "dg-" + hashlib.sha256(f"{user_id}|{day}|{','.join(sorted(ids))}".encode()).hexdigest()[:16]
    high = sum(1 for n in ordered if n.get("severity", "high") == "high")
    first = ordered[0]
    rest = "; ".join(n["changed"]["article"] for n in ordered[1:6])
    more = f" 외 {len(ordered) - 1}건: {rest}{' 등' if len(ordered) > 6 else ''}" if len(ordered) > 1 else ""
    body = {
        **first,
        "user_id": user_id,
        "conclusion_changed": any(n.get("conclusion_changed") for n in ordered),
        "explanation": f"[하루 요약 {len(ordered)}건 (중요 {high}건, 일반 {len(ordered) - high}건)] {first['explanation']}{more}",
        "severity": "high" if high else "low",
        "needs_review": False,
        "type": "recall_digest", "digest_id": did, "day": day, "count": len(ordered), "high": high, "low": len(ordered) - high,
        "notices": ordered,
    }
    return did, body


def flush_digests(service: Any, *, day: str | None = None, send: bool = True, deliver: Any = None) -> list[dict]:
    """쌓인 알림을 사용자별 요약으로 묶고(send면) 웹훅을 보낸다. 만든 요약 목록.
    `deliver(digest_id, body_bytes)`를 주면 바로 보내지 않고 그 함수에 넘긴다(API는 응답 뒤 백그라운드로 보낸다)."""
    from backend.graph.recall.service import notice_json
    from backend.graph.recall.webhook import encode_body, webhook_view

    if deliver is None and service.sender is not None:
        def deliver(did: str, body: bytes) -> Any:
            return service.sender.send(did, body, kind="digest")
    day = day or _today()
    store = service.store
    by_user: dict[str, list[dict]] = defaultdict(list)
    for rec in store.digest_pending():
        by_user[rec["user_id"]].append(notice_json(rec))
    out = []
    for user_id in sorted(by_user):
        did, body = build_digest(user_id, day, by_user[user_id])
        rec, created = store.digest_add({"digest_id": did, "user_id": user_id, "day": day, "count": body["count"],
                                         "notice_ids": [n["notice_id"] for n in body["notices"]], "payload": body})
        for n in body["notices"]:
            store.notice_update(n["notice_id"], digest_status="sent")
        if created and send and deliver is not None:
            deliver(did, encode_body(webhook_view(body)))
        out.append(rec)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.graph.recall.digest", description="리콜 하루 요약 만들기·보내기")
    ap.add_argument("--flush", action="store_true", help="쌓인 알림을 사용자별 요약으로 묶고 웹훅을 보낸다")
    ap.add_argument("--day", help="요약 날짜(기본: 오늘 UTC)")
    ap.add_argument("--no-send", action="store_true", help="요약만 만들고 웹훅은 보내지 않는다")
    args = ap.parse_args(argv)
    if not args.flush:
        ap.print_help()
        return 2
    from backend.graph.recall.runtime import build_service_from_env

    service = build_service_from_env()
    made = flush_digests(service, day=args.day, send=not args.no_send)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps({"digests": len(made), "notices": sum(int(d["count"]) for d in made)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
