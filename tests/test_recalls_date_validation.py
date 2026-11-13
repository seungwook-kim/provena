"""리콜 날짜 칸 검증 시험: digest flush day, impact-preview 날짜, 규정 웹훅 날짜는 없는 날짜·전각 숫자를 422 validation_error로 막는다.

가짜 모델·메모리 저장소로 앱을 띄운다(`test_api_recalls.py`와 같은 준비). 입력값은 응답에 담기지 않아야 한다.
"""
from __future__ import annotations

import pytest
from api_test_support import Env
from recall_test_support import changed, reader

SERVICE_KEY = "test-service-key"
CHANGE = changed().model_dump()
BAD_DATES = ["2026-02-30", "2025-02-29", "２０２６-０１-０１"]
HEADERS = {"X-Service-Key": SERVICE_KEY}
KINDS = ["flush", "webhook", "webhook_old", "impact_top", "impact_old", "impact_change", "impact_change_old"]


@pytest.fixture
def env(monkeypatch):
    for k in ("RECALL_DIGEST", "RECALL_STORE", "RECALL_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SERVICE_API_KEY", SERVICE_KEY)
    with Env(monkeypatch) as e:
        e.app.state.recall_service.read_section = reader()
        yield e


def _pages(old: str, new: str) -> dict:
    return {"pages": [{"path": "a", "old": "x", "new": "y"}], "old_version_date": old, "new_version_date": new}


def _send(env, kind: str, d: str):
    if kind == "flush":
        return env.client(env.admin).post("/recalls/digest/flush", params={"day": d})
    if kind == "webhook":
        return env.client().post("/webhooks/regulation-updated", json={**CHANGE, "new_version_date": d}, headers=HEADERS)
    if kind == "webhook_old":
        return env.client().post("/webhooks/regulation-updated", json=[{**CHANGE, "old_version_date": d}], headers=HEADERS)
    body = {
        "impact_top": lambda: _pages("2026-01-01", d),
        "impact_old": lambda: _pages(d, "2026-02-01"),
        "impact_change": lambda: {"changes": [{**CHANGE, "new_version_date": d}]},
        "impact_change_old": lambda: {"changes": [{**CHANGE, "old_version_date": d}]},
    }[kind]()
    return env.client(env.admin).post("/impact-preview", json=body)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bad", BAD_DATES)
def test_impossible_or_non_ascii_date_is_422(env, kind, bad):
    r = _send(env, kind, bad)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"
    assert bad not in r.text and bad not in str(r.json())


@pytest.mark.parametrize("kind", KINDS)
def test_leap_day_is_accepted(env, kind):
    assert _send(env, kind, "2024-02-29").status_code != 422


def test_bad_day_does_not_store_digest(env):
    _send(env, "flush", "2026-02-30")
    assert env.app.state.recall_service.store.digests(None) == []
