"""서비스 질문 그래프의 기본 설정 (결정 0078, 사전 등록 61.51).

측정 실행기(`evals/agent/exp_multi_v2.py run`)는 설정을 인자로 받아 환경 변수와 `build_graph` 인자로 넘긴다. 서비스(`/chat`)에는 인자가 없으므로
같은 값을 이 파일 한 곳(`SERVICE_ENV`)에 두고, 앱이 뜰 때(`backend/main.py`의 lifespan) 환경 변수로 채운 뒤 질문 그래프를 만든다.
그래프, 프롬프트, 검색, LLM 코드는 지금처럼 환경 변수를 읽는다. 코드 기본값(모두 꺼짐)은 그대로라 시험과 측정 실행기는 바뀌지 않는다.

- 덮어쓰기: 환경 변수에 값이 있으면 그 값을 쓴다. 비어 있거나 없으면 `SERVICE_ENV`의 값을 넣는다. `off`면 그 설정을 쓰지 않는다(빈 값 = 코드 기본값).
- 묶음 끄기: `SERVICE_PROFILE=off`면 아무것도 채우지 않는다(값을 직접 준 변수만 쓴다, 61.51 이전 동작). 비우거나 `61.51`이면 채운다. 다른 값은 ValueError.
- 앱이 내려가면 채운 값을 되돌린다(같은 프로세스에서 앱을 여러 번 띄우는 시험이 서로 섞이지 않게).
- `--via-mcp`: 측정은 같은 프로세스의 MCP 서버로 검색과 섹션 읽기를 불렀다. 서비스는 `MCP_TOKEN`이 있을 때만 `SEARCH_VIA_MCP=1`을 채운다.
  토큰이 없으면 앱이 /mcp를 붙이지 않아 부를 곳이 없다(그때는 직접 호출이고 결과는 같다, tests/test_mcp_parity.py).
- `--connected`: 서비스는 원래 결정표 저장소와 합동 검토 그래프를 질문 그래프에 연결한다(`backend/main.py`의 `build_question_graph`).
- 추론 수준: anthropic 공급자는 `LLM_EFFORT*`, openrouter 공급자는 `LLM_REASONING*`를 읽는다(`backend/services/llm.py`). 둘 다 같은 수준으로 둔다.
  claude_cli(로컬 개발)는 `CLAUDE_CLI_EFFORT*`를 읽고 시간 제한을 쓰지 않는다.
- 측정 전용 인자는 넣지 않는다: `--llm`, `--store`, `--out`, `--arms`, `--ids`, `--repeat`, `--dataset*`, `--trace-detail`(호출 기록에 응답 원문),
  `--facts-log`(진단 기록), `--warm`(서비스는 `SEARCH_WARMUP=1`의 시작 준비가 `SEARCH_HNSW=1`일 때 같은 색인 미리 읽기를 한다).
- 측정 실행기가 그래프에 따로 넘긴 페이지 안 검색과 앞 청크 읽기는 서비스 검색기(`backend.rag.retrieve.search`)로 같은 일을 하는 함수를 넘긴다(`service_searches`).
- 사전 등록 62.72: 설계에 평가 정답을 본 장치(용어 덧붙임, 대상별 나누기, 제목 경로 추가·알림·절 이름 구, 인용 더하기·문장 공유 더하기·한정어 인용 빼기·되풀이 문장 쪽 인용,
  같은 페이지 재검색, 도입부 채우기, 페이지 재검색 새 청크만, 근거 고르는 순서 문장, 두 답 고르기 같은 문서 예외, 인용 추가 보정)는 코드째 제거해 이 표에 없다.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

PROFILE_ENV = "SERVICE_PROFILE"
PROFILE_NAME = "61.51"
OFF = "off"

# 사전 등록 61.51에서 고른 설정(bo2sd-a2)을 잰 측정 실행기 인자. 서비스 값(`SERVICE_ENV`)과 같은지 시험이 대조한다(tests/test_service_profile.py).
# 측정 전용 인자(`--llm`, `--store`, `--warm`, `--trace-detail`, `--facts-log`, `--out`)는 뺐다
MEASURED_ARGS = (
    "--via-mcp", "--connected", "--structured", "judge,answer,grounding", "--section-keeps-research", "--parallel-intake", "--skip-first-rewrite",
    "--stop-stalled-search", "--judge-answer", "parallel_all", "--judge-query", "--embed-keepalive", "--brief-output", "--max-research", "1",
    "--json-reminder", "--parallel-subs",
    "--unknown-name", "--refuse-on-none", "--grounding-quote",
    "--speculate-first", "--unchanged-rejudge", "--judge-vote",
    "--effort", "none", "--effort-by-task", "decompose=low,answer=low,judge=low", "--llm-deadline", "8", "--llm-hedge", "3.5", "--llm-retries", "2",
    "--answer-wait", "4.0", "--answer-budget", "6.5",
    "--judge-quote", "--answer-best2", "--speculate-ground",
)

EFFORT_BY_TASK = "decompose=low,answer=low,judge=low"  # 질문 분해, 답 작성, 근거 충분 판정만 낮은 추론. 나머지 단계는 끔

SERVICE_ENV: dict[str, str] = {
    # 그래프 흐름(측정 실행기는 build_graph 인자로 넘긴다)
    "GRAPH_PARALLEL_INTAKE": "1",       # --parallel-intake
    "LLM_BRIEF_OUTPUT": "1",            # --brief-output
    "SEARCH_MAX_RESEARCH": "1",         # --max-research 1
    "GRAPH_JUDGE_ANSWER": "parallel_all",  # --judge-answer parallel_all
    "GRAPH_SKIP_FIRST_REWRITE": "1",    # --skip-first-rewrite
    "GRAPH_STOP_STALLED_SEARCH": "1",   # --stop-stalled-search
    # 프롬프트와 판정
    "LLM_STRUCTURED": "judge,answer,grounding",  # --structured
    "GRAPH_JUDGE_QUERY": "1",           # --judge-query
    "LLM_JSON_REMINDER": "1",           # --json-reminder
    "GRAPH_SECTION_KEEPS_RESEARCH": "1",  # --section-keeps-research
    # 검색
    "EMBED_KEEPALIVE": "1",             # --embed-keepalive
    "SEARCH_PARALLEL_SUBS": "1",        # --parallel-subs
    "SEARCH_HNSW": "1",                 # 측정 환경 SEARCH_HNSW=1(운영 DB의 HNSW 색인, db/manual/chunks_hnsw_voyage4.sql)
    # 문항 수정 스위치(#44 이후)
    "GRAPH_UNKNOWN_NAME": "1",          # --unknown-name
    "GRAPH_REFUSE_ON_NONE": "1",        # --refuse-on-none
    "GRAPH_GROUNDING_QUOTE": "1",       # --grounding-quote
    "GRAPH_SPECULATE_FIRST": "1",       # --speculate-first
    "GRAPH_UNCHANGED_REJUDGE": "1",     # --unchanged-rejudge
    "GRAPH_JUDGE_VOTE": "1",            # --judge-vote
    # 답 고르기
    "GRAPH_JUDGE_QUOTE": "1",           # --judge-quote
    "GRAPH_ANSWER_BEST2": "1",          # --answer-best2
    "GRAPH_SPECULATE_GROUND": "1",      # --speculate-ground (사전 등록 62.8. 통과 기준은 못 넘었고 사용자 결정으로 켬)
    # 추론과 시간
    "LLM_EFFORT": "none",               # --effort none (anthropic)
    "LLM_EFFORT_BY_TASK": EFFORT_BY_TASK,  # --effort-by-task (anthropic)
    "LLM_REASONING": "none",            # openrouter에서 같은 수준
    "LLM_REASONING_BY_TASK": EFFORT_BY_TASK,  # openrouter에서 같은 수준
    "LLM_DEADLINE_S": "8",              # --llm-deadline 8
    "LLM_HEDGE_S": "3.5",               # --llm-hedge 3.5
    # 측정 인자에는 없다. 질문 그래프 밖의 긴 호출은 위 상한과 hedge를 걸지 않는다: 결정표 변환 초안(convert.py TASK_DRAFT),
    # 합동 검토 감독과 팀 에이전트(teams.py). 질문 그래프 단계(classify, rewrite, judge, answer, answer_fast, grounding, decompose 등)는 넣지 않는다
    "LLM_DEADLINE_SKIP_TASKS": "decision_draft,supervisor,team_*,single",   # single: 평가용 단일 검토자(admin 전용 /admin/eval/review). 팀 에이전트와 같은 조건으로 잰다(사전 등록 62.41)
    "LLM_MAX_RETRIES": "2",             # --llm-retries 2
    "GRAPH_ANSWER_WAIT_S": "4.0",       # --answer-wait 4.0 (사전 등록 62.18, 62.22: 5.5에서 줄임)
    "GRAPH_ANSWER_BUDGET_S": "6.5",     # --answer-budget 6.5 (8.0에서 줄임)
    # 사전 등록 62.40 속도 묶음 중 답·인용·거절이 그대로인 셋(사용자 결정 11/11 14 A). 측정 실행기 인자에는 없다(서비스 경로만)
    "ANSWER_STORE_REUSE_CONN": "1",     # 62.40: 답 저장소가 프로세스 안에서 연결을 다시 씀(저장 문장·트랜잭션 그대로)
    "GRAPH_REVISE_AHEAD": "1",          # 62.40: 근거 확인 실패 뒤 답 다시 쓰기와 문장 빼기 재확인을 동시에 시작(위 GRAPH_SPECULATE_GROUND가 켜져 있어야 한다)
    "LLM_DEADLINE_BY_TASK": "judge=12",  # 62.40: 판정 단계만 시도별 상한 12초(다른 단계는 LLM_DEADLINE_S 그대로)
    # 사전 등록 62.16의 그래프 밖 왕복 줄이기 둘(사용자 결정 11/11 19). 저장 내용은 같다. 측정 실행기 인자에는 없다(서비스 경로만)
    "CHAT_FINAL_FROM_STREAM": "1",         # 62.16: /chat이 끝난 뒤 체크포인트를 다시 읽지 않고 스트림 값을 씀
    "ANSWER_SAVE_ONE_CONN": "1",           # 62.16: 답 저장과 근거 기록 저장을 연결 하나로
    # 사전 등록 62.14의 검색 hedge(사용자 결정 11/11 26). 운영 Cloud Run 리비전에 이미 같은 값으로 켜져 있어 서비스 값으로 올려도 운영 동작은 그대로다. 측정 실행기 인자에는 없다(서비스 경로만)
    "SEARCH_HEDGE": "1",                   # 62.14: 첫 검색(임베딩 + 벡터 질의)이 SEARCH_HEDGE_S초 안에 안 오면 같은 검색을 하나 더 보내 먼저 온 결과를 씀
    "SEARCH_HEDGE_S": "1.5",               # 운영 값(Cloud Run 리비전 환경 변수, 2026-11-11 확인)
    # 사전 등록 62.53(62.15 재도입, 입력이 같은 변경): 원 질문 재작성과 첫 검색을 질문 접수와 동시에 시작한다. 예비 분해가 "안 나눔"이고 분류가 정책 경로일 때만 그 결과를 쓰고 아니면 버린다
    # (GRAPH_SPECULATE_FIRST가 켜져 있어야 한다). 측정 실행기 인자 --speculate-early-search는 있으나 측정 묶음 인자(MEASURED_ARGS)에는 넣지 않았다(서비스 경로만)
    "GRAPH_SPECULATE_EARLY_SEARCH": "1",   # 62.53
    # 사전 등록 62.67: anthropic 요청의 분류·판정·답 작성·근거 확인 시스템 프롬프트에 프롬프트 캐시 표시를 붙인다(`backend/services/llm.py`). 메시지와 답 경로는 그대로다.
    # 측정 실행기 인자에는 없다(서비스 경로만). 운영에서 끄려면 환경 변수에 `off`를 준다
    "LLM_PROMPT_CACHE": "1",               # 62.67
    # 사전 등록 62.68: 고른 답의 근거 확인이 실패하면 다시 쓰기 전에, 미리 부른 근거 확인이 이미 받쳐졌다고 한 다른 후보(같은 일부 답 값·같은 문맥)를 같은 검사를 거쳐 쓴다
    # (GRAPH_SPECULATE_GROUND가 켜져 있어야 한다). 측정 실행기 인자에는 없다(서비스 경로만). 운영에서 끄려면 환경 변수에 `off`를 준다
    "GRAPH_ADOPT_GROUNDED_CANDIDATE": "1",  # 62.68
    # 사전 등록 62.72: 판정 첫 두 표가 모두 근거 없음이면 셋째 표를 이 초까지만 기다리고 두 표로 확정한다(GRAPH_JUDGE_VOTE가 켜져 있어야 한다),
    # 버리기로 한 미리 돌리기의 답 후보는 근거 확인을 미리 부르지 않는다(GRAPH_SPECULATE_FIRST, GRAPH_SPECULATE_GROUND가 켜져 있어야 한다).
    # 측정 실행기 인자에는 없다(서비스 경로만). 운영에서 끄려면 환경 변수에 `off`를 준다
    "GRAPH_NONE_VOTE_WAIT_S": "1.0",       # 62.72
    "GRAPH_SPEC_STOP_GROUND": "1",         # 62.72
}


# 응답 시간 p95 단축 후보. 운영 측정 전이라 서비스 값(`SERVICE_ENV`)에 넣지 않는다(62.16의 두 스위치와 62.14의 검색 hedge는 서비스 값으로 올렸다). 켜려면 환경 변수로 직접 주고(Cloud Run 리비전 환경 변수),
# 측정 실행기(`evals/agent/exp_multi_v2.py`)에서는 같은 이름의 인자로 켠다. 꺼진 상태는 지금과 같다(tests/test_speed_p95_code.py).
CANDIDATE_ENV: dict[str, str] = {
    # 사전 등록 62.40: 답·인용·거절이 그대로인 속도 셋(ANSWER_STORE_REUSE_CONN, GRAPH_REVISE_AHEAD, LLM_DEADLINE_BY_TASK)은 서비스 값(SERVICE_ENV)으로 옮겼다.
    # 지금 후보 스위치는 없다(재검색 뒤 판정만 추론을 끄던 `GRAPH_JUDGE_RETRY_FAST`는 코드째 제거했다)
}


def profile_values(environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    """이번 실행에 채울 값. `SERVICE_ENV`에 `MCP_TOKEN`이 있을 때만 `SEARCH_VIA_MCP=1`을 더한다(--via-mcp)."""
    env = os.environ if environ is None else environ
    values = dict(SERVICE_ENV)
    if (env.get("MCP_TOKEN") or "").strip():
        values["SEARCH_VIA_MCP"] = "1"
    return values


def profile_enabled(environ: MutableMapping[str, str] | None = None) -> bool:
    """`SERVICE_PROFILE`이 비었거나 `61.51`이면 켬, `off`면 끔. 다른 값은 ValueError(앱이 뜨지 않는다)."""
    env = os.environ if environ is None else environ
    raw = (env.get(PROFILE_ENV) or "").strip().lower()
    if raw in ("", PROFILE_NAME):
        return True
    if raw == OFF:
        return False
    raise ValueError(f"{PROFILE_ENV}는 {PROFILE_NAME} 또는 {OFF}이다: {raw!r}")


def apply_service_profile(environ: MutableMapping[str, str] | None = None) -> dict[str, str | None]:
    """환경 변수를 채운다. 돌려주는 값은 바꾼 변수 -> 원래 값(없었으면 None)이고 `restore_env`에 넘긴다.

    값이 있으면 그대로 두고, `off`면 빈 값으로 바꾸고(묶음을 꺼도 같다), 비었거나 없으면 서비스 값을 넣는다(묶음을 켰을 때만)."""
    env = os.environ if environ is None else environ
    enabled = profile_enabled(env)
    before: dict[str, str | None] = {}
    for name, default in profile_values(env).items():
        raw = env.get(name)
        current = (raw or "").strip()
        if current.lower() == OFF:
            new = ""
        elif not current and enabled:
            new = default
        else:
            continue
        if raw != new:
            before[name] = raw
            env[name] = new
    kept = sorted(n for n in profile_values(env) if n not in before and (env.get(n) or "").strip())
    log.info("서비스 설정 %s: %s, 채움 %d개, 끔 %d개, 직접 준 값 %d개(%s)", PROFILE_NAME, "켬" if enabled else "끔",
             sum(1 for n in before if env.get(n)), sum(1 for n in before if not env.get(n)), len(kept), ", ".join(kept))
    return before


def restore_env(before: dict[str, str | None], environ: MutableMapping[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    for name, raw in before.items():
        if raw is None:
            env.pop(name, None)
        else:
            env[name] = raw


@contextmanager
def service_profile(enabled: bool = True, environ: MutableMapping[str, str] | None = None) -> Iterator[dict[str, str | None]]:
    """앱이 떠 있는 동안 서비스 설정을 환경 변수로 둔다. `enabled=False`(시험이 그래프를 직접 꽂을 때)면 아무것도 바꾸지 않는다."""
    before = apply_service_profile(environ) if enabled else {}
    try:
        yield before
    finally:
        restore_env(before, environ)


class SharedChatModel:
    """채팅 모델을 처음 부를 때 한 번 만들고 다시 쓴다. 측정 실행기가 모델 하나로 문항을 돌린 것과 같게 HTTP 연결을 재사용한다.
    키 없이도 앱이 떠야 하므로 만들 때까지 미룬다. 환경 변수는 앱이 뜰 때 정해지고 바뀌지 않는다."""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()

    def model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from backend.services.llm import get_chat_model

                    self._model = get_chat_model()
        return self._model

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return self.model().invoke(*args, **kwargs)


def _searcher():
    """서비스 검색기(`search()`가 쓰는 것과 같은 객체). `backend.rag.retrieve`는 같은 이름의 함수 `search`를 내보내므로 모듈은 이름으로 연다."""
    import importlib

    S = importlib.import_module("backend.rag.retrieve.search")
    return S._searcher or S.warmup()


def page_search(query: str, rule_seqs: list[int], org: str | None, as_of: str | None, k: int) -> list:
    """페이지 안 재검색(`GRAPH_PAGE_RESEARCH`). 측정 실행기의 `PageSearch`와 같은 `Searcher.search_pages`다."""
    return _searcher().search_pages(query, rule_seqs, org, as_of, k)


def service_searches() -> dict[str, Any]:
    """`build_graph`에 넘길 페이지 안 검색. 해당 스위치(`GRAPH_PAGE_RESEARCH`)가 켜졌을 때만 부른다."""
    return {"page_search": page_search}
