"""`chat-tool-guide` 시험 (미실행 초안). 가짜 모델과 가짜 검색기만 쓴다."""
from __future__ import annotations

from qgraph_fakes import j, normal_llm

from backend.graph.build import MAX_RESEARCH, MAX_SECTION_CHARS, build_graph, expand_chunk, pick_section
from backend.schemas import Chunk

CID = "a" * 16


def mk(version_id: str = "v1", text: str = "목록은 다음과 같다:") -> Chunk:
    return Chunk(chunk_id=CID, org="security", rule_seq=7, rule_title="T", article="A > B", version_id=version_id, version_date="2026-10-30",
                 fetched_at="2026-10-30", kind="article", text=f"T > A > B\n{text}", source_url="https://handbook.gitlab.com/handbook/security/t/")


class Reader:
    def __init__(self, out=None, exc=None):
        self.out, self.exc, self.calls = out, exc, []

    def __call__(self, rule_seq, article, as_of):
        self.calls.append((rule_seq, article, as_of))
        if self.exc:
            raise self.exc
        return self.out


class Search:
    def __init__(self):
        self.calls = []

    def __call__(self, q):
        self.calls.append(q)
        return [mk()]


NEXT = j(sufficient=False, reason="잘림", clarify=None, next_tool="get_section", chunk_id=CID)
ENOUGH = j(sufficient=True, reason="", clarify=None)


def run(judge, reader, use_skills=True):
    llm, search = normal_llm(judge=judge), Search()
    state = build_graph(search, llm=llm, use_skills=use_skills, grounding_llm=False, decompose=False, section_reader=reader).invoke(
        {"question": "목록이 무엇인가요?", "user_id": "u", "thread_id": "t"})
    return state, llm, search


def test_section_read_replaces_requery_and_saves_calls():
    """판정이 섹션 읽기를 고르면 재작성 LLM과 재검색이 줄고 판정은 그대로 두 번이다."""
    reader = Reader({"text": "- 항목 하나\n- 항목 둘", "version_id": "v1"})
    state, llm, search = run([NEXT, ENOUGH], reader)
    tasks = [t for t, _ in llm.calls]
    assert tasks.count("rewrite") == 1 and tasks.count("judge") == 2
    assert len(search.calls) == 1 and len(reader.calls) == 1
    assert "항목 둘" in state["chunks"][0]["text"] and state["chunks"][0]["chunk_id"] == CID
    assert state["search_stats"]["section_reads"] == 1
    assert "chat-tool-guide" in state["skills_used"]


def test_answer_cites_the_same_chunk_after_widening():
    state, _, _ = run([NEXT, ENOUGH], Reader({"text": "본문", "version_id": "v1"}))
    assert [c["chunk_id"] for c in state["citations"]] == [CID]


def test_unknown_chunk_id_falls_back_to_requery():
    reader = Reader({"text": "x", "version_id": "v1"})
    _, llm, _ = run([j(sufficient=False, reason="r", clarify=None, next_tool="get_section", chunk_id="b" * 16), ENOUGH], reader)
    assert reader.calls == []
    assert [t for t, _ in llm.calls].count("rewrite") == 2  # 같은 검색어면 검색은 기억에서 나온다. 재작성 수로 본다


def test_other_tool_name_is_ignored():
    reader = Reader()
    _, llm, _ = run([j(sufficient=False, reason="r", clarify=None, next_tool="approve_decision", chunk_id=CID), ENOUGH], reader)
    assert reader.calls == [] and [t for t, _ in llm.calls].count("rewrite") == 2


def test_skills_off_never_reads_section():
    reader = Reader({"text": "x", "version_id": "v1"})
    state, llm, _ = run([NEXT, ENOUGH], reader, use_skills=False)
    assert reader.calls == [] and [t for t, _ in llm.calls].count("rewrite") == 2
    assert "chat-tool-guide" not in state["skills_used"]


def test_retry_limit_is_kept():
    """섹션 읽기도 재시도 상한 안에 든다. 같은 청크를 두 번 넓히지 않는다."""
    reader = Reader({"text": "x", "version_id": "v1"})
    state, llm, _ = run(NEXT, reader)
    assert len(reader.calls) == 1
    assert state["retries"] <= MAX_RESEARCH + 1 and [t for t, _ in llm.calls].count("judge") <= MAX_RESEARCH + 1  # 판정 횟수를 센다. 첫 판정까지 상한 + 1번


def test_section_read_can_keep_the_research_when_switched_on(monkeypatch):
    """스위치를 켜면 섹션 읽기 뒤에도 재검색을 한 번 더 한다. 섹션 읽기는 한 번만이다."""
    monkeypatch.setenv("GRAPH_SECTION_KEEPS_RESEARCH", "1")
    reader = Reader({"text": "x", "version_id": "v1"})
    state, llm, _ = run(NEXT, reader)
    assert len(reader.calls) == 1
    assert state["retries"] == MAX_RESEARCH + 2 and [t for t, _ in llm.calls].count("judge") == MAX_RESEARCH + 2


def test_reader_failure_does_not_stop_the_answer():
    state, _, _ = run([NEXT, ENOUGH], Reader(exc=ConnectionError("down")))
    assert state["kind"] != "error" and state["search_stats"]["section_reads"] == 1


def test_other_version_is_not_mixed_in():
    chunks = [mk("v1").model_dump()]
    out = expand_chunk(chunks, CID, {"text": "다른 판", "version_id": "v2"})
    assert "다른 판" not in out[0]["text"] and out[0]["section_read"] is True


def test_too_long_section_is_not_used():
    chunks = [mk().model_dump()]
    out = expand_chunk(chunks, CID, {"text": "x" * (MAX_SECTION_CHARS + 1), "version_id": "v1"})
    assert out[0]["text"] == chunks[0]["text"]


def test_widened_text_keeps_title_line():
    out = expand_chunk([mk().model_dump()], CID, {"text": "본문", "version_id": "v1"})
    assert out[0]["text"] == "T > A > B\n본문"


def test_pick_section_rules():
    chunks = [mk().model_dump()]
    assert pick_section({"next_tool": "search_handbook"}, chunks) is None
    assert pick_section({"next_tool": "get_section", "chunk_id": "b" * 16}, chunks) is None
    assert pick_section({"next_tool": "get_section", "chunk_id": CID}, chunks) == {"chunk_id": CID, "rule_seq": 7, "article": "A > B"}
    assert pick_section({"next_tool": "get_section", "chunk_id": CID}, [{**chunks[0], "section_read": True}]) is None
