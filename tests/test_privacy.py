"""비공개 주소 가리기 공통화 시험 (미실행 초안)."""
from __future__ import annotations

from qgraph_fakes import normal_llm

from backend.graph.build import build_graph
from backend.graph.departments import issue_table as IT
from backend.rag.retrieve.privacy import PRIVATE_MARK, redact, redact_chunk
from backend.schemas import Chunk

BODY = "See [this template](https://internal.gitlab.com/handbook/security/x) and https://internal.gitlab.com/handbook/finance/tax/."


def chunk(text: str, url: str = "https://handbook.gitlab.com/handbook/security/t/") -> Chunk:
    return Chunk(chunk_id="a" * 16, org="security", rule_seq=1, rule_title="T", article="A", version_id="v1", version_date="2026-10-30",
                 fetched_at="2026-10-30", kind="article", text=f"T > A\n{text}", source_url=url, text_sha256="f" * 64)


def test_redact_is_idempotent():
    once = redact(BODY)
    assert "internal.gitlab" not in once and once.count(PRIVATE_MARK) == 2
    assert redact(once) == once


def test_redact_chunk_keeps_other_fields_and_original_hash():
    c = chunk(BODY).model_dump()
    out = redact_chunk(c)
    assert out["text_sha256"] == c["text_sha256"]
    assert {k: v for k, v in out.items() if k != "text"} == {k: v for k, v in c.items() if k != "text"}
    assert "internal.gitlab" in c["text"]  # 입력을 바꾸지 않는다


def test_public_chunk_is_unchanged():
    c = chunk("공개 본문만 있다.").model_dump()
    assert redact_chunk(c) == c


def test_graph_never_gives_private_address_to_llm():
    """직접 호출 경로도 MCP와 같이 가려진 글을 모델에 준다."""
    llm = normal_llm()
    state = build_graph(lambda q: [chunk(BODY)], llm=llm, use_skills=False, grounding_llm=False).invoke(
        {"question": "무엇을 따르나요?", "user_id": "u", "thread_id": "t"})
    assert all("internal.gitlab" not in user for _, user in llm.calls)
    assert all("internal.gitlab" not in c["text"] for c in state["chunks"])


def test_is_private_recognizes_both_forms():
    assert IT.is_private({"source_url": "https://internal.gitlab.com/x"})
    assert IT.is_private({"source_url": PRIVATE_MARK})
    assert not IT.is_private({"source_url": "https://handbook.gitlab.com/x"})
