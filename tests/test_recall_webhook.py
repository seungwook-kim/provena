"""리콜 웹훅 시험 (docs/specs/recall.md AC-03, EC-05, SDD 3-7·3-8). 실제 네트워크 없이 `post`·`sleep`을 바꿔 넣는다."""
from __future__ import annotations

import json

import pytest

from backend.graph.recall.store import InMemoryRecallStore
from backend.graph.recall.webhook import (
    SIGNATURE_HEADER, WebhookSender, check_secret_ref, check_target_url, encode_body, resolve_secret, sign_payload, verify_signature,
)

SECRET = "test-webhook-secret"
BODY = encode_body({"notice_id": "rn-1", "explanation": "기한이 달라졌습니다."})


class Post:
    """상태 코드 목록을 차례로 돌려준다(마지막 값 반복). 예외 객체면 던진다."""

    def __init__(self, *codes):
        self.codes = list(codes)
        self.calls: list[tuple[str, bytes, dict]] = []

    def __call__(self, url, content, headers):
        self.calls.append((url, content, dict(headers)))
        code = self.codes[min(len(self.calls), len(self.codes)) - 1]
        if isinstance(code, Exception):
            raise code
        return code


def store_with(url="https://hooks.example.com/recall", secret_ref="RECALL_WEBHOOK_SECRET", active=True) -> InMemoryRecallStore:
    st = InMemoryRecallStore()
    st.sub_add({"sub_id": "ws-1", "url": url, "secret_ref": secret_ref, "active": active, "created_by": "admin"})
    return st


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET", SECRET)
    return SECRET


def sender(st, post, *, local_demo=False, sleeps=None, max_tries=3):
    return WebhookSender(st, post=post, sleep=(sleeps.append if sleeps is not None else (lambda s: None)), max_tries=max_tries,
                         backoff=1.0, local_demo=local_demo)


def test_signature_roundtrip():
    sig = sign_payload(BODY, SECRET)
    assert sig.startswith("sha256=") and len(sig) == 7 + 64
    assert verify_signature(BODY, sig, SECRET)
    assert not verify_signature(BODY, sig, "other")
    assert not verify_signature(BODY + b" ", sig, SECRET)
    assert not verify_signature(BODY, sig[7:], SECRET)            # 접두사 없음
    assert not verify_signature(BODY, None, SECRET) and not verify_signature(BODY, sig, "")


def test_success_sends_signed_body(secret):
    st, post = store_with(), Post(200)
    [rec] = sender(st, post).send("rn-1", BODY)
    url, content, headers = post.calls[0]
    assert rec["status"] == "success" and rec["tries"] == 1 and rec["last_status_code"] == 200
    assert content == BODY and verify_signature(content, headers[SIGNATURE_HEADER], SECRET)
    assert headers["Content-Type"] == "application/json" and headers["X-Webhook-Delivery"] == rec["delivery_id"]
    assert st.deliveries("rn-1")[0]["status"] == "success"


def test_5xx_then_ok_retries_with_backoff_and_logs_attempts(secret):
    """EC-05: 실패하면 1초부터 두 배씩 기다려 다시 보내고, 시도마다 기록을 남긴다."""
    st, post, sleeps = store_with(), Post(503, 502, 200), []
    [rec] = sender(st, post, sleeps=sleeps).send("rn-1", BODY)
    assert rec["status"] == "success" and rec["tries"] == 3 and sleeps == [1.0, 2.0]
    saved = st.deliveries("rn-1")[0]
    assert [a["status_code"] for a in saved["attempts"]] == [503, 502, 200]
    assert [a["ok"] for a in saved["attempts"]] == [False, False, True] and saved["tries"] == 3


def test_gives_up_after_max_tries(secret):
    st, post, sleeps = store_with(), Post(500), []
    [rec] = sender(st, post, sleeps=sleeps).send("rn-1", BODY)
    assert rec["status"] == "failed" and rec["tries"] == 3 and rec["last_error"] == "http_500" and len(post.calls) == 3
    assert sleeps == [1.0, 2.0]                                   # 마지막 실패 뒤에는 기다리지 않는다
    assert st.deliveries()[0]["status"] == "failed"


def test_connection_error_is_recorded_by_kind(secret):
    st = store_with()
    [rec] = sender(st, Post(ConnectionError("https://secret-host"), 200)).send("rn-1", BODY)
    assert rec["status"] == "success" and rec["attempts"][0]["error"] == "ConnectionError"
    assert "secret-host" not in json.dumps(rec["attempts"])


def test_missing_secret_outside_local_demo_is_not_sent(monkeypatch):
    """3-8: 배포에서는 서명 없는 웹훅을 보내지 않고 failed(secret_missing)로 남긴다."""
    monkeypatch.delenv("RECALL_WEBHOOK_SECRET", raising=False)
    st, post = store_with(), Post(200)
    [rec] = sender(st, post).send("rn-1", BODY)
    assert post.calls == [] and rec["status"] == "failed" and rec["last_error"] == "secret_missing"
    assert st.deliveries()[0]["attempts"][0]["error"] == "secret_missing"


def test_missing_secret_in_local_demo_sends_unsigned(monkeypatch):
    monkeypatch.delenv("RECALL_WEBHOOK_SECRET", raising=False)
    st, post = store_with(url="http://localhost:9000/hook"), Post(200)
    [rec] = sender(st, post, local_demo=True).send("rn-1", BODY)
    assert rec["status"] == "success" and SIGNATURE_HEADER not in post.calls[0][2]


def test_named_secret_ref(monkeypatch):
    monkeypatch.setenv("RECALL_WEBHOOK_SECRET_ERP", "erp-secret")
    st, post = store_with(secret_ref="RECALL_WEBHOOK_SECRET_ERP"), Post(200)
    sender(st, post).send("rn-1", BODY)
    assert verify_signature(BODY, post.calls[0][2][SIGNATURE_HEADER], "erp-secret")


def test_secret_ref_cannot_point_to_other_env(monkeypatch):
    """구독의 secret_ref로 다른 환경변수(예: DATABASE_URL) 값을 서명 키로 쓰게 할 수 없다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert resolve_secret("DATABASE_URL") is None
    with pytest.raises(ValueError):
        check_secret_ref("DATABASE_URL")
    check_secret_ref("RECALL_WEBHOOK_SECRET_ERP_2")


@pytest.mark.parametrize("url", ["http://hooks.example.com/x", "https://localhost/x", "https://10.0.0.5/x", "https://169.254.169.254/latest",
                                 "https://metadata.google.internal/x", "https://svc.internal/x", "ftp://hooks.example.com/x",
                                 "https://user:pw@hooks.example.com/x"])
def test_blocked_urls_in_strict_mode(url):
    with pytest.raises(ValueError):
        check_target_url(url, strict=True)


def test_public_https_url_allowed():
    check_target_url("https://hooks.example.com/recall", strict=True)
    check_target_url("http://localhost:9000/x", strict=False)


def test_blocked_url_is_recorded_not_sent(secret):
    st, post = store_with(url="https://10.0.0.5/hook"), Post(200)
    [rec] = sender(st, post).send("rn-1", BODY)
    assert post.calls == [] and rec["status"] == "failed" and rec["last_error"].startswith("blocked_url")


def test_inactive_subscription_is_skipped(secret):
    st, post = store_with(active=False), Post(200)
    assert sender(st, post).send("rn-1", BODY) == [] and post.calls == []


def test_env_defaults(monkeypatch):
    for k in ("RECALL_WEBHOOK_MAX_TRIES", "RECALL_WEBHOOK_BACKOFF_S"):
        monkeypatch.delenv(k, raising=False)
    s = WebhookSender(InMemoryRecallStore(), post=Post(200), local_demo=False)
    assert s.max_tries == 3 and s.backoff == 1.0
    monkeypatch.setenv("RECALL_WEBHOOK_MAX_TRIES", "5")
    monkeypatch.setenv("RECALL_WEBHOOK_BACKOFF_S", "x")
    s = WebhookSender(InMemoryRecallStore(), post=Post(200), local_demo=False)
    assert s.max_tries == 5 and s.backoff == 1.0
