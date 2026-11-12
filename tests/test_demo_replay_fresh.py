"""키 없는 데모의 녹화(`data/demo_replay/recorded.jsonl`)가 현재 코드와 맞는지 보는 시험 (0원: LLM·Voyage·운영 호출 없음).

배경: 재생 키는 sha256(역할 + 정규화한 메시지 전부)라서 프롬프트나 검색 결과가 한 글자만 달라져도 녹화에 없는 요청이 된다. 그러면 데모는 조용히
"결정적 가짜 응답"(`demo_fallback`, 답 머리에 "실제 LLM이 쓴 답이 아닙니다")으로 내려가고, 인용과 검색은 되니 겉으로는 정상으로 보인다.
2026-11-10에 `4f03a8d`(답 시스템 프롬프트에 단서 문장 금지 규칙 추가)가 이렇게 녹화를 어긋나게 했다. 이 시험이 그 일을 잡는다.

- 기본 실행: 질문 목록 파일(`data/demo_replay/questions.txt`)이 README 데모 질문을 글자 그대로 담고 있는지만 본다.
- `demo_replay` 표지(기본 실행에서 뺀다. `python -m pytest -m demo_replay`): 서버와 같은 질문 그래프(서비스 설정 61.51, 서버와 같은 Postgres 검색)를 키 없이
  메모리 체크포인터로 질문마다 돌리고, 그래프가 보내려는 LLM 요청 키가 녹화에 모두 있는지 확인한다. 하나라도 없으면 실패하고 "다시 녹화하라"는 안내를 낸다.
  Postgres는 `test_decision_approval.py`와 같은 방법으로 고른다(`PROVENA_D5_PG_URL`, `PROVENA_D5_PG_BIN`, 받아 둔 pgvector 이미지의 무작위 이름 임시 컨테이너). 없으면 건너뛴다.
  새 DB에 `db/*.sql`을 적용하고 `data/index.tar.gz`를 풀어 적재한다(번역 장부가 빈 새 DB. 키 없는 새 clone과 같은 조건).
"""
from __future__ import annotations

import importlib
import json
import os
import uuid
from pathlib import Path

import pytest
from test_decision_approval import pg_admin_url  # noqa: F401  (같은 임시 Postgres 고르기)
from test_demo_replay import _readme_demo_questions

ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = ROOT / "data" / "demo_replay"
QUESTIONS = REPLAY_DIR / "questions.txt"

RERECORD_HINT = (
    "녹화가 현재 코드와 맞지 않는다. 다시 녹화하라: 새 Postgres에 색인을 적재하고(`db/*.sql` 적용, `python -m backend.rag.retrieve.load_snapshot`) "
    "`data/demo_replay/recorded.jsonl`을 치운 뒤 `python -m backend.services.demo_record --questions data/demo_replay/questions.txt`를 "
    "LLM_API_KEY·LLM_PROVIDER·VOYAGE_API_KEY·DATABASE_URL을 프로세스 환경에 두고 돌린다(저장소 밖 실행기 run_demo_rerecord.ps1). 그 뒤 이 시험을 다시 돌린다."
)


def _file_questions() -> list[str]:
    from backend.services.demo_record import load_questions

    return [q["question"] for q in load_questions(QUESTIONS)]


def test_questions_file_contains_every_readme_demo_question_as_written():
    """README가 키 없이 된다고 적은 질문(인용 답 6개, 거절 3개)이 질문 파일에 글자 그대로 있어야 녹화가 그 질문을 돈다."""
    answers, refusals = _readme_demo_questions()
    assert len(answers) == 6 and len(refusals) == 3
    got = _file_questions()
    assert len(got) == len(set(got)), "질문 파일에 같은 질문이 두 번 있다"
    for q in answers + refusals:
        assert q in got, f"질문 파일에 README의 이 질문이 글자 그대로 없다: {q}"


def test_first_screen_suggestions_are_readme_keyless_answer_questions():
    """첫 화면 추천 질문(web/react-app/src/lib/demo-suggestions.js)은 README가 키 없이 인용 답이 나온다고 적은 질문이어야 하고 질문 파일(녹화 대상)에도 있어야 한다."""
    import re

    src = (ROOT / "web" / "react-app" / "src" / "lib" / "demo-suggestions.js").read_text(encoding="utf-8")
    block = src.split("DEMO_SUGGESTIONS = [", 1)[1].split("]", 1)[0]
    suggestions = re.findall(r"'([^']+)'", block)
    assert len(suggestions) == 3
    answers, _ = _readme_demo_questions()
    got = _file_questions()
    for s in suggestions:
        assert s in answers, f"추천 질문이 README의 키 없이 인용 답이 나오는 질문에 없다: {s}"
        assert s in got, f"추천 질문이 질문 파일(녹화)에 없다: {s}"


# ---------------------------------------------------------------- 녹화 키 대조 (0원, 느림)
_ENV_CLEAR = (
    "LLM_API_KEY", "VOYAGE_API_KEY", "DEMO_MODE", "LLM_RECORD", "LLM_PROVIDER", "LLM_MODEL", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "DEMO_REPLAY_DIR", "SEARCH_RANGE_N", "SERVICE_PROFILE", "MCP_TOKEN", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "SEARCH_DECOMPOSE", "SEARCH_INDEX_DIR",
)


@pytest.fixture(scope="module")
def keyless_db(pg_admin_url, tmp_path_factory):  # noqa: F811
    """색인을 적재한 새 DB(키 없는 새 clone의 db + loader와 같은 상태). 시험이 끝나면 만든 DB만 지운다."""
    import psycopg

    from backend.rag.ingest.snapshot import INDEX_ARCHIVE, unpack_index
    from backend.rag.retrieve import load_snapshot

    name = "provena_demo_replay_" + uuid.uuid4().hex[:8]
    with psycopg.connect(pg_admin_url, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    from urllib.parse import urlsplit, urlunsplit

    u = urlsplit(pg_admin_url)
    url = urlunsplit((u.scheme, u.netloc, f"/{name}", "", ""))
    try:
        with psycopg.connect(url, autocommit=True) as c:
            for f in sorted((ROOT / "db").glob("*.sql")):
                c.execute(f.read_text(encoding="utf-8"))
        index = tmp_path_factory.mktemp("demo_replay_index") / "index"
        unpack_index(ROOT / INDEX_ARCHIVE, index)
        mp = pytest.MonkeyPatch()
        mp.setenv("DATABASE_URL", url)
        try:
            assert load_snapshot.main(["--index", str(index)]) == 0
        finally:
            mp.undo()
        yield url
    finally:
        with psycopg.connect(pg_admin_url, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


FAKE_ANSWER_MARK = "실제 LLM이 쓴 답이 아닙니다"   # backend/services/demo_replay.py demo_fallback의 발췌형 대체 답 머리 문장


def _recorded_answer_text() -> str:
    """녹화한 답 응답(역할 answer, answer_fast)의 글 전체. 재생한 답이 인용한 청크가 녹화 답에서 온 것인지 대조하는 데 쓴다."""
    out = []
    for line in (REPLAY_DIR / "recorded.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["role"] in ("answer", "answer_fast"):
                out.append(str(row["response"]))
    return "\n".join(out)


# 질문을 받은 뒤 추론 답을 기다릴 수 있는 시간(GRAPH_ANSWER_BUDGET_S). 서버에서는 검색이 따뜻하면 예산 안이고(추론 답도 보냄), 차가운 첫 질문은 예산을 넘겨 빠른 답만 보낸다.
# 이 시험은 검색 속도에 기대지 않고 두 경우를 모두 고정해서 돌린다(예전에는 시험의 첫 질문이 늘 차가워 빠른 답 경로만 탔고, 서버의 첫 질문이 가짜 답으로 나오는 것을 놓쳤다).
@pytest.mark.demo_replay
@pytest.mark.parametrize("budget,slow_answers_sent", [("1000", True), ("0.001", False)], ids=["reasoning_answer_in_time", "reasoning_answer_skipped"])
def test_every_llm_request_of_the_demo_questions_is_in_the_recording(keyless_db, monkeypatch, budget, slow_answers_sent):
    """질문마다 서버와 같은 그래프를 키 없이 돌려, 재생 저장소에서 찾지 못한 요청 키(역할)를 모은다. 하나라도 있으면 녹화가 오래된 것이다.
    추론 답이 녹화에 없는 것(차가운 첫 질문으로 녹화된 질문)은 빠른 답으로 넘어가므로 허용하되, 답 글은 가짜 대체 답이 아니어야 하고 인용은 녹화 답에서 와야 한다."""
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from backend.graph.decision.repo import InMemoryDecisionRepo
    from backend.graph.departments.store import InMemoryIssueTableStore
    from backend.graph.recall.runtime import make_answer_store
    from backend.graph.service_profile import service_profile
    from backend.main import build_question_graph
    from backend.services import demo_replay as dr
    from backend.services.llm import finish_run, run_config

    search = importlib.import_module("backend.rag.retrieve.search")   # `backend.rag.retrieve.search`는 패키지 속성으로는 같은 이름의 함수다
    for name in _ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", keyless_db)
    monkeypatch.setenv("DEMO_REPLAY_DIR", str(REPLAY_DIR))
    assert dr.replay_dir() == REPLAY_DIR                # SEARCH_DECOMPOSE도 지웠다: tests/conftest.py가 끈 값이 아니라 코드 기본(켬), 서버와 같다
    state = {"roles": []}

    class SpyStore(dr.ReplayStore):
        """질문 벡터(get)를 못 찾은 경우도 모은다. LLM 요청(pick)을 못 찾은 경우는 아래 demo_fallback 감시가 역할과 함께 모은다."""

        def get(self, key):
            row = super().get(key)
            if row is None:
                state["roles"].append("query_embedding")
            return row

    store = SpyStore(REPLAY_DIR)
    assert len(store) > 0, f"녹화 폴더가 비었다: {REPLAY_DIR}"
    monkeypatch.setitem(dr._stores, str(REPLAY_DIR), store)
    monkeypatch.setattr(dr, "_warned", True)           # 첫 미적중 경고 한 줄을 시험 출력에 섞지 않는다

    real_role = dr.message_role

    def spy_fallback(messages, _orig=dr.demo_fallback):
        state["roles"].append(real_role(messages))
        return _orig(messages)

    monkeypatch.setattr(dr, "demo_fallback", spy_fallback)
    monkeypatch.setattr(search, "_searcher", None)     # 이 DB로 새로 연다. 끝나면 monkeypatch가 되돌린다
    monkeypatch.setenv("GRAPH_ANSWER_BUDGET_S", budget)  # service_profile()은 비어 있는 값만 채운다

    slow = {"sent": 0, "missed": 0}
    real_generate = dr.ReplayChatModel._generate

    def counting_generate(self, messages, *a, **kw):
        sent = real_role(messages) == dr.SLOW_ANSWER_ROLE
        slow["sent"] += sent
        try:
            return real_generate(self, messages, *a, **kw)
        except dr.ReplayMiss:
            slow["missed"] += 1
            raise

    monkeypatch.setattr(dr.ReplayChatModel, "_generate", counting_generate)

    results: list[dict] = []
    answers, _ = _readme_demo_questions()
    try:
        with service_profile():
            st = SimpleNamespace(issue_store=InMemoryIssueTableStore(), decision_repo=InMemoryDecisionRepo(), checkpointer=InMemorySaver(),
                                 store=InMemoryStore(), answer_store=make_answer_store(None))
            graph = build_question_graph(st)
            for q in _file_questions():
                state["roles"].clear()
                tid = "demo-replay-check-" + uuid.uuid4().hex[:8]
                cfg = run_config("demo_replay_check", thread_id=tid, configurable={"thread_id": tid})
                try:
                    out = graph.invoke({"question": q, "user_id": "demo-replay-check", "thread_id": tid, "org": None, "as_of": None}, cfg)
                finally:
                    finish_run(cfg)
                results.append({"question": q, "kind": out.get("kind"), "citations": len(out.get("citations") or []), "missed_roles": sorted(set(state["roles"])),
                                "missed_calls": len(state["roles"]), "answer": out.get("answer") or "", "cited": [c.get("chunk_id") for c in out.get("citations") or []]})
    finally:
        s = search._searcher
        if s is not None and hasattr(s.store, "close"):
            s.store.close()

    stale = [r for r in results if r["missed_calls"]]
    report = json.dumps(results, ensure_ascii=False, indent=1)
    assert not stale, (
        f"{RERECORD_HINT}\n녹화에 없는 요청이 있는 질문 {len(stale)}/{len(results)}개 (역할: {sorted({x for r in stale for x in r['missed_roles']})}).\n{report}"
    )
    # 요청 키가 다 맞으면 README가 적은 결과(인용 답 / 거절)도 나와야 한다: 키가 맞아도 녹화한 응답 자체가 README와 다르면 README를 고치거나 다시 녹화한다
    assert bool(slow["sent"]) is slow_answers_sent, f"이 시험이 노린 경로(추론 답을 보냄={slow_answers_sent})를 타지 않았다: 추론 답 요청 {slow['sent']}건"
    recorded_answers = _recorded_answer_text()
    for r in results:
        if r["question"] in answers:
            assert r["kind"] == "answer" and r["citations"] > 0, f"README는 인용 답이라고 적었는데 {r['kind']}(인용 {r['citations']}): {r['question']}"
            # 발췌형 대체 답(녹화에 없을 때의 가짜 답)이 아니라 녹화한 LLM 답이어야 하고, 인용은 그 녹화 답이 가리킨 청크여야 한다
            assert FAKE_ANSWER_MARK not in r["answer"], f"녹화 답이 아니라 발췌형 대체 답이 나왔다: {r['question']}\n{r['answer'][:300]}"
            # (그래프가 인용 확장으로 같은 문서의 청크를 더 붙일 수 있으므로 전부가 아니라 하나 이상)
            assert any(cid and cid in recorded_answers for cid in r["cited"]), f"녹화한 답이 인용한 청크가 하나도 없다: {r['question']} {r['cited']}"
        else:
            assert r["kind"] == "refuse", f"README는 거절이라고 적었는데 {r['kind']}: {r['question']}"
