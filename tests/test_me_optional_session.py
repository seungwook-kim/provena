"""`GET /me`의 머리글 `X-Session-Optional: 1` (놓친 것 H-33). 키·네트워크·DB 없음.

로그아웃 상태에서 화면이 첫 세션 확인을 할 때마다 브라우저 콘솔에 401 오류가 남던 것. 로그인 쿠키가 아예 없을 때만 204로 답하고,
쿠키가 있거나(만료·위조 포함) 머리글이 없으면 예전과 같다.
"""
from __future__ import annotations

import pytest
from api_test_support import Env

OPTIONAL = {"X-Session-Optional": "1"}


@pytest.fixture
def env(monkeypatch):
    with Env(monkeypatch) as e:
        yield e


def test_no_cookie_with_header_is_204_without_body(env):
    r = env.client(None).get("/me", headers=OPTIONAL)
    assert r.status_code == 204 and r.content == b""
    assert r.headers.get("cache-control") == "no-store" and r.headers.get("x-request-id")


def test_without_header_is_still_401(env):
    assert env.client(None).get("/me").status_code == 401
    assert env.client(None).get("/me", headers={"X-Session-Optional": "yes"}).status_code == 401


def test_signed_in_user_gets_the_same_body_with_or_without_header(env):
    c = env.client(env.alice)
    plain, optional = c.get("/me"), c.get("/me", headers=OPTIONAL)
    assert plain.status_code == optional.status_code == 200
    assert plain.json() == optional.json() and optional.json()["user_id"]


def test_broken_cookie_with_header_is_still_401(env):
    c = env.client(None)
    c.cookies.set("provena_auth", "not-a-token")
    assert c.get("/me", headers=OPTIONAL).status_code == 401
