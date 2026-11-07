"""`/chat`, `/threads`, `/me/memory` 시험용 앱 조립. 가짜 모델, 메모리 체크포인터, 메모리 Store로 `create_app`을 만든다(키·네트워크·DB 없음).

사용자마다 `TestClient`를 따로 만들어 쿠키가 섞이지 않게 한다. 로그인 쿠키는 서명 키로 직접 만든다(로그인 라우터는 따로 시험한다).
"""
from __future__ import annotations

import json
import secrets
from uuid import uuid4

from auth_test_support import MemoryRevocationStore
from fake_search import fake_search
from fastapi.testclient import TestClient
from qgraph_fakes import normal_llm
from team_review_fakes import Retriever

from backend.auth import AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, AuthUser, create_access_token
from backend.graph.build import build_graph
from backend.graph.departments.review import build_review_graph

CSRF = "csrf-token-for-test"
ENV_KEYS = ("DATABASE_URL", "AUTH_SECRET", "PROVENA_ENV", "PROVENA_DEV_MODE", "CHECKPOINTER", "MCP_TOKEN", "SEARCH_WARMUP",
            "LLM_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "USE_SKILLS")


class FakeAuthStore:
    def __init__(self, *users: AuthUser) -> None:
        self.users = {str(u.user_id): u for u in users}

    def get_by_login_id(self, login_id):
        return next((u for u in self.users.values() if u.login_id == login_id), None)

    def get_by_user_id(self, user_id):
        return self.users.get(str(user_id))


def graph_factory(llm=None, search=fake_search, review_llm=None):
    """`create_app(graph_factory=...)`에 넘길 함수. 앱이 연 체크포인터·Store·저장소로 가짜 모델 질문 그래프를 만든다."""
    def make(state):
        review = None
        if review_llm is not None:
            review = build_review_graph(Retriever(), None, llm=review_llm, store=state.issue_store, approvals=state.decision_repo)
        return build_graph(search, state.checkpointer, llm=llm or normal_llm(), store=state.store, answer_store=state.answer_store,
                           decision_repo=state.decision_repo, review_graph=review, decompose=False)

    return make


class Env:
    """사용자 alice, bob(일반)과 admin(관리자). `with Env(...) as env:` 안에서 앱 lifespan이 열린다."""

    def __init__(self, monkeypatch, **factory_kw) -> None:
        from backend.main import create_app

        for key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        self.secret = secrets.token_urlsafe(32)
        monkeypatch.setenv("AUTH_SECRET", self.secret)
        monkeypatch.setenv("CHECKPOINTER", "memory")
        self.alice = AuthUser(user_id=uuid4(), login_id="alice", password_hash="x", role="user")
        self.bob = AuthUser(user_id=uuid4(), login_id="bob", password_hash="x", role="user")
        self.admin = AuthUser(user_id=uuid4(), login_id="admin", password_hash="x", role="admin")
        self.app = create_app(auth_store=FakeAuthStore(self.alice, self.bob, self.admin), revocation_store=MemoryRevocationStore(),
                              graph_factory=graph_factory(**factory_kw))
        self._boot = TestClient(self.app)

    def __enter__(self) -> "Env":
        self._boot.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self._boot.__exit__(*exc)

    def client(self, who: AuthUser | None = None, csrf: bool = True) -> TestClient:
        c = TestClient(self.app)
        if who is not None:
            c.cookies.set(AUTH_COOKIE_NAME, create_access_token(who.user_id, who.role, secret=self.secret))
        if csrf:
            c.cookies.set(CSRF_COOKIE_NAME, CSRF)
            c.headers["X-CSRF-Token"] = CSRF
        return c


def sse_events(text: str) -> list[tuple[str, dict]]:
    """SSE 본문을 (event, data) 목록으로. ':'로 시작하는 줄(ping)은 건너뛴다."""
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith(":") or not line:
                continue
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:"):].strip())
        if name:
            out.append((name, json.loads("\n".join(data))))
    return out


def ask(client: TestClient, message: str, thread_id: str | None = None, **extra):
    body = {"message": message, **extra}
    if thread_id is not None:
        body["thread_id"] = thread_id
    r = client.post("/chat", json=body)
    return r, (sse_events(r.text) if r.status_code == 200 else [])
