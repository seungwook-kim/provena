"""배포 화면 겉면 점검(11/10): 감시용 HEAD /health, 없는 경로의 404 문구가 한국어 하나로 통일."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import WEB_DIR
from test_auth_store import _app

NO_BUILD = not (WEB_DIR / "react-app" / "dist" / "index.html").is_file()


def test_head_health_is_alive_like_get(monkeypatch):
    client = TestClient(_app(monkeypatch))
    assert client.get("/health").status_code == 200
    head = client.head("/health")
    assert head.status_code == 200 and head.content == b""   # 감시 도구가 HEAD로 확인해도 죽은 서버로 보이지 않게


@pytest.mark.skipif(NO_BUILD, reason="React production build 없음")
def test_unknown_paths_return_the_same_korean_404(monkeypatch):
    client = TestClient(_app(monkeypatch))
    for path in ("/api/nope", "/assets/nope.js", "/nope"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.json()["error"]["message"] == "요청한 경로를 찾을 수 없습니다.", path


def test_health_operation_ids_are_unique_and_head_is_hidden(monkeypatch):
    spec = _app(monkeypatch).openapi()
    assert set(spec["paths"]["/health"]) == {"get"}   # HEAD는 문서에 올리지 않는다
    ids = [op["operationId"] for path in spec["paths"].values() for op in path.values() if isinstance(op, dict) and "operationId" in op]
    assert len(ids) == len(set(ids)) and "health_health_get" in ids
