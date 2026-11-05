"""읽기 전용 MCP 도구 `get_agent_trace`: 대화(thread_id)의 LangGraph 체크포인트를 읽어 마지막 실행의 단계(노드 순서·시각·걸린 시간),
Supervisor 결정, 합동 검토 팀별 상태, 승인 대기 여부를 돌려준다. 체크포인터에 쓰지 않는다(`list()`만, `setup()` 없음).

체크포인트에서 읽는 것(2026-11-05 InMemorySaver로 실제 그래프를 돌려 확인):
- 한 thread의 체크포인트는 그래프마다 `checkpoint_ns`로 나뉜다. 바깥 그래프는 "", 하위 그래프는 "<노드 이름>:<task id>"다
  (질문 그래프의 `review` 노드 → "review:...", 멀티 그래프의 하위 에이전트 → "retriever:..."·"writer:..."·"verifier:...").
  합동 검토 그래프를 따로 돌리면(`routes.py` open_decision_runtime의 review_graph) 검토 상태가 "" 에 있다. 두 모양 모두 읽는다.
- 하위 그래프 체크포인트의 metadata `parents[""]` = 그때 바깥 그래프의 체크포인트 id. 이것으로 마지막 실행에 속한 하위 그래프를 고른다.
- 그 단계에 돈 노드 = 앞 체크포인트와 이 체크포인트의 `versions_seen`이 달라진 노드(metadata에는 step·source·parents만 있다).
- 단계 시간 = 같은 ns의 앞 체크포인트 `ts`와 이 체크포인트 `ts`의 차이. 사람 승인을 기다린 단계는 그 시간이 들어 있어 표시한다.
- 승인 대기 = 그 ns 마지막 체크포인트의 pending_writes에 "__interrupt__"가 있고 "__resume__"이 없다.

비용은 지어내지 않는다: 체크포인트 상태(AgentState·MultiState·ReviewState)에 비용 칸이 없고, LLM 호출별 기록(`backend/services/llm_trace.py`)은
서비스 요청 경로에서 켜지 않는다. 그래서 `cost_usd`는 null이다.

내보내지 않는 것: 질문·답 본문, user_id, 검색 청크, 쟁점표 행, 사람 결정의 comment·decided_by, 팀 결과의 rows·reason, Supervisor의 팀별 지시 글.
읽어 온 상태에서 칸을 지우지 않고, 아래 함수가 고른 칸(코드가 정한 이름·상태값·숫자·시각)만 새 dict에 옮긴다(화이트리스트).
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Any

from extras.mcp_skill.mcp_server.server import (
    READ_ONLY, Invalid, ToolResponse, _failure, _resp, _run, missing_table, pg_pool,
)

MAX_THREAD_ID = 200        # thread_id 형식은 정해진 것이 없다(SDD /chat `{thread_id, message}`). 저장소 안 실제 값: "convert_" + 16진수 16자(routes.py new_id), 평가 "eval-<id>-<6자>"
MAX_CHECKPOINTS = 200      # 읽을 체크포인트 상한(최신부터). 합동 검토 한 번 ≈ 12개, 멀티 그래프 질문 한 번 ≈ 22개(실측)
SOURCE = "checkpoints"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")        # 노드·에이전트·팀 이름. 코드가 정한 식별자만 내보낸다
INTERRUPT, RESUME, ERROR = "__interrupt__", "__resume__", "__error__"   # langgraph 1.x 채널 이름(langgraph._internal 상수, 공개 API 아님)
ROUTES = ("rule", "decision", "review", "out_of_domain")                                      # build.py ROUTES
REVIEW_STATUS = ("clarify", "no_issues", "team_review_failed", "pending_approval", "approved", "rejected")   # review.py ReviewState
TEAM_STATUS = ("reviewed", "not_reviewed")                                                    # review.py review_team

NOTE = ("단계 시간(duration_ms) = 같은 그래프(graph)의 앞 체크포인트와 이 체크포인트의 저장 시각(ts) 차이(노드 실행 + 저장). "
        "includes_human_wait=true인 단계는 사람 승인을 기다린 시간이 들어 있다. "
        "비용 기록 없음: 체크포인트에 비용 칸이 없고 서비스 경로는 LLM 호출 기록을 켜지 않는다(cost_usd=null).")


# ---------- 체크포인트 → 고른 칸 (순수 함수) ----------

def _ns(t) -> str:
    return t.config["configurable"].get("checkpoint_ns") or ""


def _md(t) -> dict:
    return dict(t.metadata or {})


def _ts(t) -> datetime | None:
    try:
        return datetime.fromisoformat(t.checkpoint["ts"])
    except (KeyError, TypeError, ValueError):
        return None


def _channels(t) -> set[str]:
    return {w[1] for w in (t.pending_writes or []) if len(w) >= 2}


def _name(v: Any) -> str | None:
    return v if isinstance(v, str) and NAME.fullmatch(v) else None


def _one_of(v: Any, allowed: tuple[str, ...]) -> str | None:
    return v if v in allowed else None


def _ran(prev, cur) -> list[str]:
    """이 체크포인트까지 돈 노드: versions_seen이 달라진 노드. "__"로 시작하는 내부 노드(__start__ 등)는 뺀다."""
    before = prev.checkpoint.get("versions_seen", {}) if prev is not None else {}
    now = cur.checkpoint.get("versions_seen", {})
    return sorted(n for n in (_name(k) for k, v in now.items() if before.get(k) != v) if n and not n.startswith("__"))


def _graph_label(ns: str) -> str:
    return "main" if not ns else (_name(ns.split(":", 1)[0]) or "subgraph")


def _waiting(last) -> bool:
    ch = _channels(last)
    return INTERRUPT in ch and RESUME not in ch


def _ms(a: datetime | None, b: datetime | None) -> int | None:
    return None if a is None or b is None else max(0, round((b - a).total_seconds() * 1000))


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _steps(label: str, rows: list) -> list[dict]:
    out, prev = [], None
    for t in rows:
        nodes = _ran(prev, t) if prev is not None else []
        if nodes:
            out.append({"graph": label, "step": _md(t).get("step") if isinstance(_md(t).get("step"), int) else None,
                        "nodes": nodes, "at": _iso(_ts(t)), "duration_ms": _ms(_ts(prev), _ts(t)),
                        "includes_human_wait": INTERRUPT in _channels(prev)})
        prev = t
    return out


def _review(values: dict, last) -> dict:
    teams = []
    results = values.get("team_results") if isinstance(values.get("team_results"), dict) else {}
    for team, r in sorted(results.items()):
        if _name(team) and isinstance(r, dict):
            attempts = r.get("attempts")
            teams.append({"team": team, "status": _one_of(r.get("status"), TEAM_STATUS),
                          "attempts": attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else None})
    failed = values.get("failed_teams") if isinstance(values.get("failed_teams"), list) else []
    return {
        "review_status": _one_of(values.get("review_status"), REVIEW_STATUS),
        "waiting_approval": _waiting(last),
        "teams": teams,
        "failed_teams": [f["team"] for f in failed if isinstance(f, dict) and _name(f.get("team"))],
    }


def summarize(tuples: list, thread_id: str, truncated: bool) -> dict | None:
    """체크포인트 목록(아무 순서) → 마지막 실행의 요약 한 줄. 체크포인트가 없으면 None."""
    if not tuples:
        return None
    by_ns: dict[str, list] = {}
    for t in tuples:
        by_ns.setdefault(_ns(t), []).append(t)
    for rows in by_ns.values():
        rows.sort(key=lambda t: (t.checkpoint.get("ts") or "", t.checkpoint.get("id") or ""))
    root = by_ns.get("", [])
    starts = [i for i, t in enumerate(root) if _md(t).get("source") == "input"]
    run = root[starts[-1]:] if starts else root
    run_ids = {t.checkpoint.get("id") for t in run}
    children = {ns: rows for ns, rows in by_ns.items()
                if ns and any((_md(t).get("parents") or {}).get("") in run_ids for t in rows)}

    steps = _steps("main", run)
    for ns, rows in children.items():
        steps.extend(_steps(_graph_label(ns), rows))
    steps.sort(key=lambda s: s["at"] or "")

    values = run[-1].checkpoint.get("channel_values", {}) if run else {}
    review_ns = sorted((rows for ns, rows in children.items() if _graph_label(ns) == "review"), key=lambda r: r[-1].checkpoint.get("ts") or "")
    if review_ns:
        rv = _review(review_ns[-1][-1].checkpoint.get("channel_values", {}), review_ns[-1][-1])
    elif "team_results" in values:                                # 합동 검토 그래프를 따로 돌린 모양
        rv = _review(values, run[-1])
    else:
        rv = None

    log = values.get("supervisor_log") if isinstance(values.get("supervisor_log"), list) else None
    trace = values.get("agent_trace") if isinstance(values.get("agent_trace"), list) else None
    all_rows = [*run, *(t for rows in children.values() for t in rows)]
    times = [d for d in (_ts(t) for t in all_rows) if d is not None]
    started, last = (min(times), max(times)) if times else (None, None)
    return {
        "thread_id": thread_id,
        "run_started_at": _iso(started),
        "last_checkpoint_at": _iso(last),
        "elapsed_ms": _ms(started, last),
        "runs_in_thread": len(starts),
        "complete": bool(starts) and not truncated,
        "route": _one_of(values.get("route"), ROUTES),
        "agent_trace": [a for a in map(_name, trace) if a] if trace is not None else None,
        "supervisor_log": [{"after": _name(e.get("after")), "to": _name(e.get("to")), "closed_by": _name(e.get("closed_by"))}
                           for e in log if isinstance(e, dict)] if log is not None else None,
        "review": rv,
        "waiting_approval": any(_waiting(rows[-1]) for rows in [run, *children.values()] if rows),
        "stopped_on_error": any(ERROR in _channels(rows[-1]) for rows in [run, *children.values()] if rows),
        "steps": steps,
        "cost_usd": None,
    }


def read_trace(saver, thread_id: str) -> tuple[dict | None, bool]:
    """체크포인터에서 그 thread의 체크포인트를 최신부터 MAX_CHECKPOINTS개 읽어 요약한다. 쓰지 않는다."""
    rows = list(saver.list({"configurable": {"thread_id": thread_id}}, limit=MAX_CHECKPOINTS + 1))
    truncated = len(rows) > MAX_CHECKPOINTS
    if truncated:                                                 # Postgres·메모리 모두 checkpoint_id(시간순) 내림차순
        rows.sort(key=lambda t: t.checkpoint.get("id") or "", reverse=True)
        rows = rows[:MAX_CHECKPOINTS]
    return summarize(rows, thread_id, truncated), truncated


def _check(thread_id: Any) -> None:
    if not isinstance(thread_id, str) or not thread_id.strip() or len(thread_id) > MAX_THREAD_ID or not thread_id.isprintable():
        raise Invalid(f"thread_id는 1~{MAX_THREAD_ID}자, 제어 문자 없음")


class _Saver:
    """체크포인터. 주면 그것, 비우면 DATABASE_URL이 있을 때 처음 부를 때 PostgresSaver를 만든다(읽기만, setup 없음)."""

    def __init__(self, saver=None):
        self._saver, self._lock = saver, threading.Lock()

    def get(self):
        with self._lock:
            if self._saver is None:
                pool = pg_pool()
                if pool is None:
                    return None
                from langgraph.checkpoint.postgres import PostgresSaver
                self._saver = PostgresSaver(pool)
            return self._saver


def register(mcp, saver=None) -> None:
    """get_agent_trace를 mcp에 붙인다. saver가 없고 DATABASE_URL도 없으면 도구는 not_ready를 돌려준다."""
    store = _Saver(saver)

    @mcp.tool(annotations=READ_ONLY)
    async def get_agent_trace(thread_id: str) -> ToolResponse:
        """대화 하나(thread_id)의 마지막 그래프 실행을 체크포인트에서 읽어 단계별로 돌려준다: 돈 노드 순서와 시각·걸린 시간,
        멀티 에이전트 Supervisor 결정(어디서 와서 어디로), 합동 검토 팀별 상태·시도 횟수, review_status, 사람 승인 대기 여부.

        언제 쓰나: 어느 실행이 어느 단계에서 멈췄는지·오래 걸렸는지, 합동 검토가 어느 팀에서 실패했는지, 승인을 기다리는지 볼 때.
        언제 쓰지 않나: 질문·답·근거 글이나 쟁점표 내용을 볼 때(이 도구는 글을 돌려주지 않는다). LLM 비용을 볼 때(기록 없음).
        입력: thread_id = 대화 id(그래프를 부를 때 configurable.thread_id로 쓴 값, 1~200자).
        출력: results = [요약 하나]: run_started_at, last_checkpoint_at, elapsed_ms, runs_in_thread(이 thread의 실행 수), complete,
              route, agent_trace, supervisor_log[{after, to, closed_by}], review{review_status, waiting_approval,
              teams[{team, status, attempts}], failed_teams}, waiting_approval, stopped_on_error,
              steps[{graph(main 또는 하위 그래프 이름), step, nodes, at, duration_ms, includes_human_wait}], cost_usd=null.
              source = checkpoints, as_of = 마지막 체크포인트 시각.
        제약: 같은 thread의 이전 실행은 runs_in_thread로 수만 센다. 체크포인트가 200개를 넘으면 최신 200개만 읽고 complete=false.
              thread가 없으면 not_found, DATABASE_URL이 없거나 체크포인트 표가 아직 없으면 not_ready, 연결 실패는 unavailable.
              user_id·질문·답·사람 결정 사유는 내보내지 않는다. 비용은 기록이 없어 null이다(0이 아님).
        """
        try:
            _check(thread_id)
            s = store.get()
            if s is None:
                return _resp("not_ready", SOURCE, retryable=False,
                             note="서버에 체크포인트 저장소(DATABASE_URL)가 없습니다. 대화가 없다는 뜻이 아닙니다.")
            out, truncated = await _run(read_trace, s, thread_id)
        except Exception as e:  # noqa: BLE001 — 상태로 돌려준다
            if missing_table(e):
                return _resp("not_ready", SOURCE, retryable=False,
                             note="체크포인트 표가 아직 DB에 없습니다(앱이 한 번도 체크포인터를 열지 않음). 대화가 없다는 뜻이 아닙니다.")
            return _failure("get_agent_trace", SOURCE, e)
        if out is None:
            return _resp("not_found", SOURCE, note="그 thread_id의 체크포인트가 없습니다.")
        notes = [NOTE]
        if truncated or not out["complete"]:
            notes.append(f"체크포인트가 {MAX_CHECKPOINTS}개를 넘었거나 실행 시작이 잘려 최근 것만 읽었습니다. 앞 단계가 빠졌을 수 있습니다.")
        return _resp("ok", SOURCE, [out], as_of=out["last_checkpoint_at"], note=" / ".join(notes))
