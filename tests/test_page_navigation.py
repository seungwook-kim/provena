"""화면 주소와 API 주소가 같은 곳(/approvals): 브라우저 새로고침은 React 화면, 화면의 fetch는 API (docs/SDD.md 7장).

실제 앱(create_app)으로 확인한다. DB는 없다(127.0.0.1:1), 로그인하지 않았으니 API는 401이다.
lifespan은 돌리지 않는다(DB 연결 대기로 느림). 화면 판정은 권한·저장소보다 먼저라 필요 없다.
"""
from __future__ import annotations

import base64
import os
import secrets

import pytest
from fastapi.testclient import TestClient

from profile_test_support import MemoryProfileStore
from test_admin_api import FakeStore, make_user

from backend.services.profile_crypto import KEY_ENV

NAVIGATE = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}   # 브라우저 주소창·새로고침
PAGE = '<!doctype html><div id="root">react</div>'


@pytest.fixture
def app(monkeypatch, tmp_path):
    store = FakeStore([make_user("member", "user")])
    monkeypatch.setattr("backend.main.PostgresAuthStore", lambda dsn: store)
    monkeypatch.setattr("backend.main.PostgresProfileStore", lambda dsn: MemoryProfileStore())
    for key in ("PROVENA_ENV", "PROVENA_DEV_MODE", "MCP_TOKEN", "SEARCH_WARMUP"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv(KEY_ENV, "1:" + base64.b64encode(os.urandom(32)).decode())
    from backend.main import create_app

    app = create_app()
    page = tmp_path / "index.html"
    page.write_text(PAGE, encoding="utf-8")
    app.state.react_index = page
    return app


def is_json(response) -> bool:
    return response.headers.get("content-type", "").startswith("application/json")


def test_browser_navigation_gets_react_page(app):
    r = TestClient(app).get("/approvals", headers=NAVIGATE, follow_redirects=False)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.text == PAGE


@pytest.mark.parametrize("accept", [None, "*/*", "application/json"])
def test_fetch_gets_api_not_page(app, accept):
    headers = {"Accept": accept} if accept else {}
    client = TestClient(app)
    if accept is None:
        client.headers.pop("accept", None)   # TestClient 기본 Accept(*/*)도 빼서 헤더 없는 요청
    r = client.get("/approvals", headers=headers)
    assert r.status_code in (401, 403) and is_json(r)
    assert "root" not in r.text


def test_without_react_build_navigation_gets_api(app):
    app.state.react_index = None
    r = TestClient(app).get("/approvals", headers=NAVIGATE)
    assert r.status_code == 401 and is_json(r)


def test_post_is_never_turned_into_page(app):
    r = TestClient(app).post("/approvals/x", headers=NAVIGATE, json={})
    assert "root" not in r.text and is_json(r)


def test_other_api_path_is_unaffected(app):
    r = TestClient(app).get("/threads", headers=NAVIGATE)
    assert r.status_code == 401 and is_json(r)
