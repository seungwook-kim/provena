"""MCP 읽기 전용 도구 3개 시험 (docs/specs/mcp.md AC-01·02·03·07·08·09, EC-01~12).

CI: 가짜 검색기·가짜 저장소를 넣은 서버를 fastmcp 메모리 클라이언트로 부른다(네트워크 없음). /mcp 인증은 FastAPI TestClient로.
로컬: 스냅샷(data/index/)이 있으면 BM25 검색기로 평가셋 v1 30문항을 MCP와 직접 호출로 대조하고, 전체 청크의 비공개 주소를 본다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")
from fastmcp import Client  # noqa: E402

from backend.rag.ingest.changes import LastRun  # noqa: E402
from backend.rag.retrieve.section import MemorySectionStore  # noqa: E402
from backend.schemas.chunk import Chunk, SearchQuery  # noqa: E402
from backend.schemas.recall import ChangedArticle  # noqa: E402
from extras.mcp_skill.mcp_server import server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"search_handbook", "get_section", "list_changed_sections"}


def chunk(i: int, text: str = "body", org: str = "security") -> Chunk:
    return Chunk(chunk_id=f"c{i}", org=org, rule_seq=7, rule_title="T", article="A", version_id="v1",
                 version_date="2026-10-30", fetched_at="2026-10-30", kind="article", text=f"T > A\n{text}",
                 source_url="https://handbook.gitlab.com/handbook/security/t/")


class FakeSearch:
    def __init__(self, out=None, exc=None, fallback=None):
        self.out, self.exc, self.last_trace, self.calls = out, exc, fallback, []

    def __call__(self, q: SearchQuery):
        self.calls.append(q)
        if self.exc:
            raise self.exc
        return self.out if self.out is not None else [chunk(1), chunk(2)]


def section_rows(bodies: list[str]):
    rows = [{"chunk_id": f"s{i}", "rule_seq": 7, "version_id": "v1", "seq": i, "article": "A", "kind": "row",
             "org": "security", "text": f"T > A\n{b}", "text_sha256": hashlib.sha256(b.encode()).hexdigest(),
             "line_start": i + 1, "line_end": i + 1} for i, b in enumerate(bodies)]
    pages = [{"rule_seq": 7, "version_id": "v1", "title": "T", "source_url": "https://handbook.gitlab.com/t/",
              "version_date": "2026-10-30", "version_date_before": False, "valid_from": "2026-10-30", "valid_to": None}]
    return MemorySectionStore(rows, pages)


class FakeChanges:
    def __init__(self, items=(), run="ok", exc=None):
        self.items, self.run, self.exc, self.writes = list(items), run, exc, 0

    def rows(self, since, org, limit):
        if self.exc:
            raise self.exc
        return [a.model_dump() for a in self.items][:limit]

    def last_run(self):
        if self.run is None:
            return None
        return {"run_id": 5, "status": "succeeded", "finished_at": "2026-11-02T18:09:00+00:00", "to_commit": "abc123",
                "list_complete": self.run != "held"}


def call(mcp, tool: str, args: dict) -> dict:
    async def go():
        async with Client(mcp) as c:
            return (await c.call_tool(tool, args, raise_on_error=False)).structured_content
    return asyncio.run(go())


def make(search=None, store=None, changes=None):
    return server.build_server(search_fn=search or FakeSearch(), section_store=store or section_rows(["x"]),
                               changes_store=changes or FakeChanges())


# ---------- AC-01 ----------

def test_exactly_three_read_only_ascii_tools():
    async def go():
        async with Client(make()) as c:
            return await c.list_tools()
    tools = asyncio.run(go())
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.name.isascii() and all(p.isascii() for p in t.input_schema["properties"])
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False
        for part in ("언제 쓰나", "언제 쓰지 않나", "입력", "출력", "제약"):       # 설명 5요소
            assert part in t.description, (t.name, part)


# ---------- search_handbook ----------

def test_search_passes_query_and_returns_chunks_in_order():
    """AC-02 (CI): 도구는 search()를 그대로 부르고 순서를 바꾸지 않는다."""
    fs = FakeSearch(out=[chunk(3), chunk(1), chunk(2)])
    r = call(make(fs), "search_handbook", {"query": "공개 기한", "org": "security", "as_of": "2026-10-27", "k": 3})
    assert r["status"] == "ok" and [c["chunk_id"] for c in r["results"]] == ["c3", "c1", "c2"]
    assert fs.calls == [SearchQuery(query="공개 기한", org="security", as_of="2026-10-27", k=3)]
    assert r["as_of"] == "2026-10-27" and r["source"] == "handbook"


def test_search_empty_is_not_found():
    """EC-01: 결과 0개는 ok + 빈 목록이 아니다."""
    r = call(make(FakeSearch(out=[])), "search_handbook", {"query": "없는 것"})
    assert r["status"] == "not_found" and r["results"] == []


@pytest.mark.parametrize("args", [{"query": ""}, {"query": "   "}, {"query": "x" * 1001}, {"query": "q", "k": 0},
                                  {"query": "q", "k": 21}, {"query": "q", "as_of": "2026-02-30"},
                                  {"query": "q", "as_of": "11/03"}, {"query": "q", "org": "nope"}])
def test_search_bad_input_is_invalid(args):
    """EC-03: 틀린 입력은 invalid, retryable=false, 검색을 부르지 않는다."""
    fs = FakeSearch()
    r = call(make(fs), "search_handbook", args)
    assert r["status"] == "invalid" and r["retryable"] is False and r["note"] and fs.calls == []


def test_search_db_failure_is_unavailable_without_detail():
    """EC-04·AC-03: 예외 글·DB 주소를 응답에 넣지 않는다."""
    secret = "postgresql://app:pw@db.internal:5432/app"
    r = call(make(FakeSearch(exc=ConnectionError(f"connection to {secret} failed"))), "search_handbook", {"query": "q"})
    assert r["status"] == "unavailable" and r["retryable"] is True
    assert secret not in json.dumps(r, ensure_ascii=False) and "pw" not in json.dumps(r)


def test_search_fallback_reason_in_note():
    """EC-12: 번역 실패로 내려간 검색은 ok + note."""
    r = call(make(FakeSearch(fallback="translate_timeout")), "search_handbook", {"query": "q"})
    assert r["status"] == "ok" and "translate_timeout" in r["note"]


def test_search_timeout_is_unavailable(monkeypatch):
    import time
    monkeypatch.setattr(server, "TOOL_TIMEOUT_S", 0.05)
    slow = FakeSearch()
    slow_fn = lambda q: (time.sleep(0.3), slow(q))[1]        # noqa: E731
    r = call(make(slow_fn), "search_handbook", {"query": "q"})
    assert r["status"] == "unavailable" and "시간 초과" in r["note"]


def test_private_address_is_marked_not_sent():
    """AC-09 (CI)·SDD 76줄: 본문의 비공개 주소 링크는 [비공개 문서]로 바꿔 보낸다."""
    body = ("See [this template](https://internal.gitlab.com/handbook/security/x) and "
            "https://internal.gitlab.com/handbook/finance/tax/. Domains: internal.gitlab.com: gated")
    r = call(make(FakeSearch(out=[chunk(1, body)])), "search_handbook", {"query": "q"})
    text = r["results"][0]["text"]
    assert "internal.gitlab" not in json.dumps(r) and text.count(server.PRIVATE_MARK) == 3
    assert "this template [비공개 문서]" in text


# ---------- get_section ----------

def test_get_section_ok():
    r = call(make(store=section_rows(["first", "second"])), "get_section", {"rule_seq": 7, "article": "A"})
    assert r["status"] == "ok" and r["results"][0]["text"] == "first\nsecond"
    assert r["results"][0]["chunk_ids"] == ["s0", "s1"]


def test_get_section_missing_lists_candidates():
    """EC-02: 없는 섹션 → not_found + 그 판 섹션 이름 후보."""
    r = call(make(store=section_rows(["x"])), "get_section", {"rule_seq": 7, "article": "Nope"})
    assert r["status"] == "not_found" and "A" in r["note"]
    r = call(make(store=section_rows(["x"])), "get_section", {"rule_seq": 8, "article": "A"})
    assert r["status"] == "not_found" and "판이 없습니다" in r["note"]


def test_get_section_before_first_version_is_not_found():
    """EC-08: 가장 이른 판보다 앞 날짜는 가까운 판으로 바꾸지 않는다."""
    r = call(make(store=section_rows(["x"])), "get_section", {"rule_seq": 7, "article": "A", "as_of": "2026-01-01"})
    assert r["status"] == "not_found" and r["results"] == []


def test_get_section_integrity_is_error():
    """EC-05: 지문이 다르면 틀린 원문 대신 error(retryable=false)."""
    st = section_rows(["first", "second"])
    st.rows[1]["text"] += " tampered"
    r = call(make(store=st), "get_section", {"rule_seq": 7, "article": "A"})
    assert r["status"] == "error" and r["retryable"] is False and r["results"] == []
    assert "tampered" not in json.dumps(r)


@pytest.mark.parametrize("args", [{"rule_seq": -1, "article": "A"}, {"rule_seq": 2**32, "article": "A"},
                                  {"rule_seq": 7, "article": " "}, {"rule_seq": 7, "article": "A", "as_of": "x"}])
def test_get_section_bad_input(args):
    assert call(make(), "get_section", args)["status"] == "invalid"


# ---------- list_changed_sections ----------

ART = ChangedArticle(rule_seq=7, article="A", old_version_date="2026-09-01", new_version_date="2026-10-30",
                     change_type="modified")


def test_list_changed_ok_with_run_source():
    r = call(make(changes=FakeChanges([ART])), "list_changed_sections", {"since": "2026-10-01"})
    assert r["status"] == "ok" and r["results"] == [ART.model_dump()]
    assert r["source"] == "sync_runs:5@abc123" and r["as_of"] == "2026-11-02T18:09:00+00:00" and r["note"] is None


def test_list_changed_states():
    """AC-07: 실행 없음 = not_ready / 바뀐 것 없음 = ok + 빈 목록 + 실행 시각 / 삭제 보류 = note."""
    r = call(make(changes=FakeChanges(run=None)), "list_changed_sections", {"since": "2026-10-01"})
    assert r["status"] == "not_ready"
    r = call(make(changes=FakeChanges([])), "list_changed_sections", {"since": "2026-10-01"})
    assert r["status"] == "ok" and r["results"] == [] and r["as_of"]
    r = call(make(changes=FakeChanges([ART], run="held")), "list_changed_sections", {"since": "2026-10-01"})
    assert r["status"] == "ok" and "삭제를 보류" in r["note"]


@pytest.mark.parametrize("args", [{"since": "2026-13-01"}, {"since": "2026-10-01", "limit": 0},
                                  {"since": "2026-10-01", "limit": 201}, {"since": "2026-10-01", "org": "nope"}])
def test_list_changed_bad_input(args):
    assert call(make(changes=FakeChanges([ART])), "list_changed_sections", args)["status"] == "invalid"


def test_list_changed_db_failure():
    r = call(make(changes=FakeChanges(exc=OSError("db down"))), "list_changed_sections", {"since": "2026-10-01"})
    assert r["status"] == "unavailable" and r["retryable"] is True and "db down" not in json.dumps(r)


def test_last_run_model_matches_store_shape():
    assert LastRun(**FakeChanges().last_run()).run_id == 5


# ---------- AC-08: /mcp 인증 ----------

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    def make_client(token: str):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("MCP_TOKEN", token)
        return TestClient(create_app())
    return make_client


def test_mcp_needs_bearer_token(app_client):
    with app_client("abc") as c:
        assert c.post("/mcp/", json=INIT, headers=HDR).status_code == 401
        assert c.post("/mcp/", json=INIT, headers={**HDR, "Authorization": "Bearer abd"}).status_code == 401
        assert c.post("/mcp/?token=abc", json=INIT, headers=HDR).status_code == 401           # 쿼리 토큰은 받지 않는다
        assert c.post("/mcp/?access_token=abc", json=INIT, headers=HDR).status_code == 401
        ok = c.post("/mcp/", json=INIT, headers={**HDR, "Authorization": "Bearer abc"})
        assert ok.status_code == 200 and "provena-handbook" in ok.text
        assert c.get("/health").status_code == 200


def test_mcp_not_mounted_without_token(app_client):
    """EC-10: MCP_TOKEN이 비면 /mcp를 붙이지 않는다(정적 파일 쪽으로 넘어가 404·405, MCP 응답 아님)."""
    with app_client("  ") as c:
        r = c.post("/mcp/", json=INIT, headers={**HDR, "Authorization": "Bearer abc"})
        assert r.status_code in (404, 405) and "jsonrpc" not in r.text
        assert c.get("/health").status_code == 200


def test_empty_token_checked_on_both_sides(monkeypatch):
    """EC-10: main.py와 server.py가 각자 빈 토큰을 거른다(한쪽이 깨져도 다른 쪽 시험이 잡게 따로 본다)."""
    from backend import main
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    assert main.create_mcp_app() is None                       # 환경 변수가 아예 없을 때
    monkeypatch.setenv("MCP_TOKEN", "")
    assert main.create_mcp_app() is None
    for token in ("", "   "):
        assert server.mcp_http_app(token=token) is None        # main을 거치지 않고 불러도 열리지 않는다
    assert server.mcp_http_app(token="abc") is not None


# ---------- 로컬: 실제 스냅샷 ----------

SNAP = ROOT / "data/index/chunks.jsonl"


@pytest.mark.skipif(not SNAP.exists(), reason="data/index 스냅샷 없음(로컬에만)")
def test_snapshot_private_address_never_leaves():
    """AC-09 (로컬): 비공개 주소가 든 실제 청크 전부가 도구 출력에서 [비공개 문서]로 바뀐다."""
    hits = [Chunk(**{k: v for k, v in json.loads(line).items() if k in Chunk.model_fields})
            for line in SNAP.open(encoding="utf-8") if "internal.gitlab.com" in line]
    assert hits
    r = call(make(FakeSearch(out=hits)), "search_handbook", {"query": "q", "k": 20})
    assert "internal.gitlab.com" not in json.dumps(r, ensure_ascii=False)


@pytest.mark.skipif(not SNAP.exists(), reason="data/index 스냅샷 없음(로컬에만)")
def test_snapshot_v1_mcp_equals_direct():
    """AC-02 (로컬): 평가셋 v1 30문항 — MCP search_handbook = search() 직접 호출(chunk_id 순서까지). 모델 없이 BM25로."""
    from backend.rag.retrieve.search import make_search
    fn = make_search("none", "bm25_kw")
    qs = [json.loads(line)["input"] for line in (ROOT / "evals/dataset_v1.jsonl").open(encoding="utf-8")]
    mcp_fn = server.build_server(search_fn=fn, section_store=section_rows(["x"]), changes_store=FakeChanges())
    same = 0
    for q in qs:
        direct = [c.chunk_id for c in fn(SearchQuery(query=q, k=8))]
        via = call(mcp_fn, "search_handbook", {"query": q, "k": 8})
        same += direct == [c["chunk_id"] for c in via["results"]]
    assert len(qs) == 30 and same == 30
