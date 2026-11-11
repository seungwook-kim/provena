"""A-07: PROVENA_DOCS_PUBLIC 스위치. 기본은 공개(기존 동작), 0이면 문서 주소가 404."""
import pytest
from fastapi.testclient import TestClient

PATHS = ("/docs", "/redoc", "/openapi.json")


def _client(monkeypatch, value):
    for key in ("DATABASE_URL", "AUTH_SECRET", "PROVENA_ENV", "PROVENA_DEV_MODE", "PROVENA_OWNER_LOGIN_ID"):
        monkeypatch.delenv(key, raising=False)
    if value is None:
        monkeypatch.delenv("PROVENA_DOCS_PUBLIC", raising=False)
    else:
        monkeypatch.setenv("PROVENA_DOCS_PUBLIC", value)
    from backend.main import create_app
    return TestClient(create_app())


@pytest.mark.parametrize("value", [None, "1", "yes", ""])
def test_docs_public_by_default(monkeypatch, value):
    c = _client(monkeypatch, value)
    assert [c.get(p).status_code for p in PATHS] == [200, 200, 200]


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_docs_can_be_turned_off(monkeypatch, value):
    c = _client(monkeypatch, value)
    assert [c.get(p).status_code for p in PATHS] == [404, 404, 404]
    assert c.get("/health").status_code == 200   # 다른 경로는 그대로
