"""영향 미리보기 요약을 GitLab MR 댓글로 게시하는 함수(I-08). 네트워크 호출 없음: 전송 함수를 가짜로 바꿔 요청 내용만 본다."""
from __future__ import annotations

import pytest

from backend.graph.recall.impact import post_mr_comment


def test_skips_without_url_or_token(monkeypatch):
    monkeypatch.delenv("GITLAB_API_URL", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    calls = []
    post = lambda *a: calls.append(a) or 201  # noqa: E731
    assert post_mr_comment("본문", project_id=1, mr_iid=2, post=post) is False
    assert post_mr_comment("본문", project_id=1, mr_iid=2, api_url="https://g.example/api/v4", post=post) is False
    assert post_mr_comment("본문", project_id=1, mr_iid=2, token="t", post=post) is False
    assert calls == []


def test_posts_note_with_body_url_and_token_header(monkeypatch):
    monkeypatch.setenv("GITLAB_API_URL", "https://g.example/api/v4/")
    monkeypatch.setenv("GITLAB_TOKEN", "secret-token")
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body, headers))
        return 201

    assert post_mr_comment("### 요약", project_id="grp/proj", mr_iid="7", post=post) is True
    (url, body, headers), = calls
    assert url == "https://g.example/api/v4/projects/grp%2Fproj/merge_requests/7/notes"
    assert body == {"body": "### 요약"}
    assert headers["PRIVATE-TOKEN"] == "secret-token"


def test_non_2xx_raises():
    with pytest.raises(RuntimeError, match="403"):
        post_mr_comment("x", project_id=1, mr_iid=1, api_url="https://g.example/api/v4", token="t", post=lambda *a: 403)
