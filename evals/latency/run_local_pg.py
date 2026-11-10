"""`evals/agent/exp_multi_v2.py run`을 `.env` 없이 로컬 Postgres(pgvector)로 돌리는 얇은 실행기. 운영 DB를 읽지도 쓰지도 않는다.

`exp_multi_v2 run --store pg`는 DB 주소를 저장소의 `.env`에서 읽는다. 이 실행기는 그 함수만 환경 변수 `LOCAL_PG_URL`의 주소로 바꾸고 나머지는 그대로 부른다.
(2026-11-10 사전 등록 62.8: 로컬 컨테이너 `pgvector/pgvector:pg16`에 `python -m backend.rag.retrieve.load_snapshot`으로 `data/index.tar.gz` 스냅샷을 적재하고
`db/manual/chunks_hnsw_voyage4.sql`로 HNSW 색인을 만든 뒤 `SEARCH_HNSW=1`로 돌렸다.)

사용: LOCAL_PG_URL=postgresql://app:app@localhost:55432/app python -m evals.latency.run_local_pg run <exp_multi_v2 run 인자...>
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str]) -> int:
    url = (os.environ.get("LOCAL_PG_URL") or "").strip()
    if not url:
        raise SystemExit("LOCAL_PG_URL이 없다(로컬 Postgres 주소). 운영 DB 주소는 쓰지 않는다")
    if "localhost" not in url and "127.0.0.1" not in url:
        raise SystemExit("LOCAL_PG_URL은 localhost여야 한다(운영 DB를 읽지 않기 위해)")
    import evals.agent.exp_service_v1 as S

    S.database_url_from_env_file = lambda: url
    from evals.agent import exp_multi_v2 as M

    return M.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
