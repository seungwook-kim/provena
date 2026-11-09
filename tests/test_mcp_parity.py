"""직접 호출과 MCP 호출의 결과 비교 시험 (미실행 초안). `docs/specs/mcp.md` AC-C2의 그래프 단위 확장이다.

전제: PR #52 머지(`sub_queries` 칸), 패치 04(가림 공통화), 패치 05(`make_mcp_retriever`).
비교 규칙:
- `chunk_id` 순서는 같아야 한다.
- `text`, `source_url`을 뺀 칸은 글자까지 같아야 한다. `text_sha256`도 같다(가리기 전 원문 지문이다).
- `text`, `source_url`은 `redact(직접 결과) == MCP 결과`여야 한다. 비공개 주소가 없는 청크는 글자까지 같다.
- 그래프 단계(`state["chunks"]`)에서는 양쪽이 모두 가려져 있으므로 완전히 같아야 한다.

CI: 가짜 검색기 + 같은 프로세스 FastMCP 서버(`Client(server)`). 네트워크, 키, DB를 쓰지 않는다.
로컬: `data/index` 스냅샷이 있으면 BM25 + 평가셋 v1. v2는 쓰지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("langchain.mcp")

from qgraph_fakes import j, normal_llm  # noqa: E402

from backend.graph.build import MSG_REFUSE_NO_KEY, MSG_REFUSE_SEARCH_DOWN, build_graph  # noqa: E402
from backend.graph.mcp_retriever import last_fallback_reason, make_mcp_retriever  # noqa: E402
from backend.rag.retrieve.embed import EmbedUnavailable  # noqa: E402
from backend.rag.retrieve.privacy import redact, redact_chunk  # noqa: E402
from backend.schemas import Chunk, SearchQuery  # noqa: E402
from extras.mcp_skill.mcp_server import server as srv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_BODY = "See [t](https://internal.gitlab.com/handbook/x) and internal.gitlab.com: gated"
SUBS = ["SEV2 first response", "who pages for SEV2"]


def mk(i: int, text: str = "body", org: str = "security") -> Chunk:
    return Chunk(chunk_id=f"{i:016x}", org=org, rule_seq=7, rule_title="T", article="A", version_id="v1", version_date="2026-10-30",
                 fetched_at="2026-10-30", kind="article", text=f"T > A\n{text}", text_sha256="f" * 64,
                 source_url="https://handbook.gitlab.com/handbook/security/t/")


class Search:
    def __init__(self, out=None, exc=None):
        self.out, self.exc, self.calls = out, exc, []

    def __call__(self, q: SearchQuery):
        self.calls.append(q)
        if self.exc:
            raise self.exc
        return list(self.out if self.out is not None else [mk(3), mk(1), mk(2)])


class OrgStore:
    """`_check_org`가 읽는 `orgs()`만 있는 저장소."""

    def orgs(self):
        return ["security", "finance"]


def via_mcp(search):
    return make_mcp_retriever(srv.build_server(search_fn=search, section_store=OrgStore()))


def assert_parity(direct: list[Chunk], mcp: list[Chunk]) -> None:
    assert [c.chunk_id for c in direct] == [c.chunk_id for c in mcp]
    for d, m in zip(direct, mcp):
        a, b = d.model_dump(), m.model_dump()
        for key in set(a) - {"text", "source_url"}:
            assert a[key] == b[key], key
        assert redact(a["text"]) == b["text"]
        assert redact(a["source_url"]) == b["source_url"]


# ---------- 검색기 단위 ----------

@pytest.mark.parametrize("q", [
    SearchQuery(query="on-call"),
    SearchQuery(query="on-call", org="security", as_of="2026-10-27", k=3),
    SearchQuery(query="SEV2", sub_queries=SUBS),
])
def test_same_order_and_fields(q):
    direct_s, mcp_s = Search(), Search()
    assert_parity(direct_s(q), via_mcp(mcp_s)(q))
    assert mcp_s.calls == [q]  # 서버는 입력을 바꾸지 않는다. sub_queries도 그대로다


def test_invalid_was_the_problem_sub_queries_now_pass():
    """분해 질문을 `query` 하나에 이어 붙이던 호출(1000자 초과)이 sub_queries 칸으로 거절 없이 간다."""
    long_subs = ["x" * 900, "y" * 900]
    s = Search()
    q = SearchQuery(query="short", sub_queries=long_subs)
    assert [c.chunk_id for c in via_mcp(s)(q)] == [c.chunk_id for c in Search()(q)]
    assert s.calls[0].sub_queries == long_subs


def test_private_chunk_differs_only_by_redaction():
    out = [mk(1, PRIVATE_BODY), mk(2)]
    q = SearchQuery(query="q")
    direct, mcp = Search(out)(q), via_mcp(Search(out))(q)
    assert_parity(direct, mcp)
    assert "internal.gitlab" not in mcp[0].text and mcp[0].text_sha256 == direct[0].text_sha256
    assert mcp[1].text == direct[1].text  # 비공개가 없으면 글자까지 같다


def test_not_found_is_empty_both_ways():
    q = SearchQuery(query="q")
    assert Search([])(q) == via_mcp(Search([]))(q) == []


def test_unknown_org_is_empty_both_ways():
    """직접 `search()`는 모르는 절이면 빈 목록이다. 서버는 `invalid`로 답하고, 그래프 쪽 검색기가 빈 목록으로 맞춘다."""
    s = Search()
    assert via_mcp(s)(SearchQuery(query="q", org="TEST-unknown")) == []
    assert s.calls == []


def test_too_long_query_is_empty_not_a_crash():
    """직접 호출은 길이 제한이 없고 서버는 1000자까지다. 이 차이는 사라지지 않으므로 결과가 달라질 수 있다. 그래프를 멈추지 않는 것만 보장한다."""
    assert via_mcp(Search())(SearchQuery(query="x" * 1001)) == []


def test_unavailable_becomes_embed_unavailable():
    with pytest.raises(EmbedUnavailable):
        via_mcp(Search(exc=EmbedUnavailable("down")))(SearchQuery(query="q"))


def test_fallback_reason_comes_from_note():
    s = Search([])
    s.last_trace = "no_key"  # 서버가 `search_fn.last_trace`를 읽어 note에 싣는다
    assert via_mcp(s)(SearchQuery(query="q")) == []
    assert last_fallback_reason() == "no_key"
    via_mcp(Search())(SearchQuery(query="q"))
    assert last_fallback_reason() is None  # 다음 검색이 앞 값을 지운다


# ---------- 그래프 단위 ----------

def run(retriever, llm=None, **kw) -> dict:
    g = build_graph(retriever, llm=llm or normal_llm(rewrite=j(query="SEV2", org="security", as_of=None)), use_skills=False, grounding_llm=False, **kw)
    return g.invoke({"question": "SEV2 대응은?", "user_id": "u", "thread_id": "t"})


def graph_view(state: dict) -> dict:
    return {"kind": state.get("kind"), "chunks": state.get("chunks"), "sub_queries": state.get("sub_queries"), "answer": state.get("answer"),
            "retries": state.get("retries"), "search_error": state.get("search_error")}


@pytest.mark.parametrize("decompose", [False, True])
def test_graph_state_is_identical(decompose):
    llm_kw = {"decompose": j(split=True, sub_questions=["SEV2 첫 대응은?", "SEV2 호출은 누가?"])} if decompose else {}
    make_llm = lambda: normal_llm(rewrite=j(query="SEV2", org="security", as_of=None), **llm_kw)  # noqa: E731
    out = [mk(3, PRIVATE_BODY), mk(1), mk(2)]
    direct = run(Search(out), make_llm(), decompose=decompose)
    mcp = run(via_mcp(Search(out)), make_llm(), decompose=decompose)
    assert graph_view(direct) == graph_view(mcp)
    assert all("internal.gitlab" not in c["text"] for c in direct["chunks"])


def test_graph_refuses_the_same_when_search_down():
    down = EmbedUnavailable("down")
    a, b = run(Search(exc=down)), run(via_mcp(Search(exc=down)))
    assert a["answer"] == b["answer"] == MSG_REFUSE_SEARCH_DOWN


def test_graph_refuses_the_same_with_no_key():
    s = Search([])
    s.last_trace = "no_key"
    assert run(via_mcp(s))["answer"] == MSG_REFUSE_NO_KEY


def test_redact_chunk_makes_direct_equal_to_mcp_dump():
    q = SearchQuery(query="q")
    out = [mk(1, PRIVATE_BODY)]
    assert redact_chunk(Search(out)(q)[0].model_dump()) == via_mcp(Search(out))(q)[0].model_dump()


# ---------- 로컬 스냅샷: 평가셋 v1만 ----------

SNAP = ROOT / "data/index/chunks.jsonl"
V1 = ROOT / "evals/dataset_v1.jsonl"


@pytest.mark.skipif(not (SNAP.exists() and V1.exists()), reason="data/index 스냅샷 없음(로컬에만)")
def test_snapshot_v1_with_decomposed_queries(monkeypatch):
    """평가셋 v1 30문항: BM25 검색기로 직접과 MCP를 비교한다. 분해 질문은 저장 결과 대신 문장 부호 기준 합성 분해를 쓴다(모델 호출 없음)."""
    from backend.rag.retrieve.search import make_search
    from backend.rag.retrieve.translate import Result as _translate_result

    monkeypatch.setattr("backend.rag.retrieve.translate.translate", lambda query, kind, store, call=None: _translate_result(query, "stored"))  # 모델 없이 비교한다. 양쪽이 같은 번역을 받는다
    search = make_search("none", "bm25_kw")
    retrieve = via_mcp(search)
    items = [json.loads(x) for x in V1.read_text(encoding="utf-8").splitlines() if x.strip()]
    split = 0
    for it in items:
        q = SearchQuery(query=it["input"], k=5)
        assert_parity(search(q), retrieve(q))
        parts = [p.strip() for p in it["input"].replace("?", "?\n").splitlines() if p.strip()][:3]
        if len(parts) >= 2:
            split += 1
            sq = SearchQuery(query=it["input"], k=5, sub_queries=parts)
            assert_parity(search(sq), retrieve(sq))
    assert split  # 분해 경로를 실제로 탔다
