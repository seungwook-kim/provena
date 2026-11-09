"""정적 OpenAPI 명세 내보내기 (docs/api/api.md).

    python docs/api/export_openapi.py            -> docs/api/openapi.json
    python docs/api/export_openapi.py 출력경로

키와 DB 없이 돈다. 서버를 띄우지 않고(lifespan을 돌리지 않고) 앱 객체만 만들어 `app.openapi()`를 파일로 쓴다.
로그인·`/chat`·리콜·변경 감시 라우터는 `DATABASE_URL`이 있을 때만 붙으므로, 이 스크립트는 DB를 열지 않는 빈 사용자 저장소를
`create_app(auth_store=...)`에 꽂아 라우터만 붙인다. 라우터를 만들 때는 저장소를 부르지 않는다.
서명 키(`AUTH_SECRET`)는 라우터를 만들 때만 요구되므로 이 실행 안에서만 쓰는 임의 값을 넣는다(명세에 들어가지 않는다).
`MCP_TOKEN`은 지운다(MCP 앱은 OpenAPI에 나오지 않는다).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "openapi.json"


class _NoStore:
    """DB 없이 라우터만 붙이기 위한 빈 저장소. 어떤 메서드도 부르지 않는다(부르면 AttributeError)."""

    def __getattr__(self, name: str):
        raise AttributeError(f"명세 내보내기에서는 저장소를 부르지 않는다: {name}")


def build_openapi() -> dict:
    for name in ("DATABASE_URL", "MCP_TOKEN", "INDEX_URL", "TEST_DATABASE_URL"):
        os.environ.pop(name, None)
    os.environ["AUTH_SECRET"] = "openapi-export-only-" + "x" * 32
    sys.path.insert(0, str(ROOT))
    from backend.main import create_app

    app = create_app(auth_store=_NoStore())          # lifespan은 돌리지 않는다: DB·모델·검색 준비 없음
    return app.openapi()


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    spec = build_openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{out} ({len(spec.get('paths', {}))}개 경로)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))