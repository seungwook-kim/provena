"""합동 검토 그래프 (F-03, docs/specs/team-review.md). Supervisor가 요청을 네 팀 에이전트에 나눠 주고, 쟁점표 하나로 합친 뒤 사람 승인에서 멈춘다.

흐름: Supervisor(빠진 값이 있으면 되묻고 끝) -> 팀 에이전트 4개(보안, 인프라·SRE, IT 운영, 재무, 병렬)
-> 재시도 상한까지 실패한 팀이 있으면 사람에게 알림 `interrupt()`(`team_review_failed`) -> `retry`면 그 팀만 다시, `mark_unreviewed`면 다음으로
-> 쟁점표 합치기(코드) -> 쟁점도 검토 못 한 팀도 없으면 "쟁점 없음"으로 끝 / 있으면 승인함에 올림 -> 사람 승인 `interrupt()` -> 승인이면 저장, 반려면 사유만 기록.

- 검색기, 채팅 모델, 체크포인터, 쟁점표 저장소는 모두 인자로 받는다(`build_graph`와 같은 방식). 체크포인터가 있어야 interrupt가 멈춘 자리에서 재개된다.
  Postgres 체크포인터는 호출하는 쪽(서버 조립)이 넘긴다. 이 파일은 체크포인터를 만들지 않는다.
- 승인 전에는 저장소를 부르지 않는다: 저장은 `finalize` 노드에서만 하고, 그 노드는 interrupt가 `approve=True`(불리언)로 재개된 뒤에만 저장한다.
  interrupt 노드는 재개할 때 처음부터 다시 돌기 때문에 쓰기는 앞뒤 노드(`queue_approval`, `finalize`)로 나눴다. 둘 다 같은 입력으로 다시 돌아도 결과가 같다.
  승인 id는 표 내용에서 정해진다(`approval_id_for`).
- 승인함: `approvals`(`DecisionRepo`)를 넘기면 `queue_approval`이 `kind="issue_table"`로 올리고 `finalize`가 결과를 적는다. 저장을 먼저 하고 승인 건을 나중에 닫으므로
  중간에 실패해도 "승인됨인데 표가 없음"이 생기지 않는다. 재시도는 `backend/graph/decision/routes.py`가 한다.
- 팀 에이전트 실패는 조용히 빠지지 않는다. 그 팀만 상한(`TEAM_ATTEMPTS`)까지 다시 돌리고(모델 응답을 읽지 못함, 쟁점이 모두 인용 검사에서 걸림, 일시 오류),
  그래도 안 되면 사람에게 먼저 알린다. interrupt 값은 `{"approval_id", "kind": "team_review_failed", "summary", "failed_teams": [{"team", "reason", "attempts"}], "thread_id"}`,
  재개 값은 `{"action": "retry" | "mark_unreviewed", "decided_by", "comment"}`다. `mark_unreviewed`일 때만 `unreviewed`에 이유와 함께 남겨 쟁점표 승인 대기로 간다.
  틀린 재개 값은 상태를 바꾸지 않고 같은 요청이 `rejected_resume` 이유와 함께 다시 올라온다(`bad_action`, `approver_missing`). 이 멈춤 동안 쟁점표는 저장되지 않는다.
  재시도한 쟁점도 인용 검사를 똑같이 통과해야 행이 된다. 근거 자체가 없는 경우와 설정 오류(Skill 파일 없음)는 다시 해도 같으므로 재시도도 알림도 없이 `unreviewed`가 된다.
  비용 상한(`CostCapExceeded`)만 그대로 올린다.
- 검색된 원문은 `<<<자료>>>`로 감싼 데이터로만 프롬프트에 넣는다. 원문 안의 지시는 따르지 않고, 승인은 코드 경로(interrupt)로만 통과한다.
`approval_request` 이벤트, 403(관리자만), `Command(resume=...)` 호출은 서버 쪽(체크포인터·승인함 담당)이 한다. 이 그래프는 interrupt 값을 낸다:
`{"approval_id", "kind": "issue_table", "summary", "thread_id", "table"}`. 재개 값은 `{"approve": bool, "comment": str, "decided_by": str | None}`(`Decision`과 같은 이름).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.graph import untrusted as U
from backend.graph.state import today_kst
from backend.graph.departments import issue_table as IT
from backend.graph.departments import teams as T
from backend.graph.decision.repo import TEAM_FAILED_KIND
from backend.graph.departments.store import InMemoryIssueTableStore, IssueTableStore
from backend.graph.mcp_retriever import default_retriever
from backend.graph.parsing import parse_json_obj
from backend.prompts import question as P
from backend.rag.retrieve.privacy import redact_chunk
from backend.schemas import Chunk, SearchQuery
from backend.services.llm import get_chat_model

log = logging.getLogger(__name__)

JSON_ATTEMPTS = 2  # Supervisor: LLM 응답 형식이 깨지면 1회 다시 요청한다
TEAM_ATTEMPTS = 3  # 팀 하나의 시도 상한(첫 시도 포함). 모델 호출도 팀마다 이 수를 넘지 않는다
TEAM_RETRY_WAIT_SECONDS = 1.0  # 일시 오류 뒤 다시 시도하기 전에 기다리는 시간
TEAM_ACTIONS = ("retry", "mark_unreviewed")  # 재시도 상한까지 실패한 팀을 두고 사람이 고르는 것
RETRY_NOTE = "\n\n[다시 요청] 직전 응답을 쓸 수 없었다. JSON 한 개만 출력하고, 쟁점의 chunk_id는 위 자료 머리말에 있는 값만 그대로 쓴다. 자료가 받쳐 주지 않는 쟁점은 내지 않는다."
SEARCH_K = 10  # 팀마다 검색 한 번, 하위 질문 둘(요청 + 보조어, 팀 보조어)을 번갈아 합쳐 10개(재검색 없음, 사전 등록 62.41)
MSG_NO_ISSUES = "쟁점 없음: 네 팀 모두 이 요청에서 쟁점을 찾지 못했습니다."
MSG_SAVED = "승인되어 쟁점표를 저장했습니다."
MSG_REJECTED = "반려되어 쟁점표를 저장하지 않았습니다."


def _merge_dicts(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


class ReviewState(TypedDict, total=False):
    # 입력
    question: str  # 합동 검토 요청 한 건
    user_id: str
    thread_id: str
    as_of: str | None
    # 중간 값
    tasks: dict  # 팀별로 볼 것 (Supervisor가 정한다)
    team_results: Annotated[dict, _merge_dicts]  # 팀 id -> {label, status, rows, reason, private_excluded, dropped}
    failed_teams: list[dict]  # 재시도 상한까지 실패한 팀 [{team, reason, attempts}]
    team_action: str  # 그 팀들에 대한 사람의 결정: retry | mark_unreviewed
    table: dict  # 합친 쟁점표
    approval_id: str
    decision: dict | None  # 사람 결정 {approve, comment, decided_by}. 팀 실패 알림이면 action도 있다. 저장소에 적으면 지운다
    # 출력
    kind: str  # answer | clarify
    answer: str
    clarify_question: str | None
    review_status: str  # clarify | no_issues | team_review_failed | pending_approval | approved | rejected
    saved_table_id: str | None
    issue_table: dict  # 승인되어 저장된 표(화면용)


def _text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):  # 블록 목록(Anthropic API가 생각 블록과 함께 돌려줄 때): 글 블록만 잇는다
        return "".join(b if isinstance(b, str) else str(b.get("text") or "") for b in c if isinstance(b, str) or (isinstance(b, dict) and b.get("type") == "text"))
    return c if isinstance(c, str) else str(c)


def _squash(s: str) -> str:
    return "".join(s.split())


def _fragments() -> list[str]:
    out: list[str] = []
    for sp in (T.SUPERVISOR_SYSTEM, *(T.team_system(t, "") for t in T.TEAMS)):
        for ln in sp.splitlines():
            ln = _squash(ln)
            if len(ln) >= 15 and ln not in out:
                out.append(ln)
    return out


_FRAGMENTS = _fragments()


def leaks_internal(text: str) -> bool:
    """쟁점 문장에 내부 표식이나 이 그래프 프롬프트 문장(15자 이상인 줄)이 그대로 들어 있는지."""
    if P.leaks_internal(text):
        return True
    flat = _squash(text)
    return any(f in flat for f in _FRAGMENTS)


def build_review_graph(
    retriever: Callable[[SearchQuery], list[Chunk]] | None = None,
    checkpointer=None,
    *,
    llm=None,
    store: IssueTableStore | None = None,
    use_skills: bool | None = None,
    approvals: Any = None,
):
    """컴파일된 합동 검토 그래프를 만든다.

    - retriever: `SearchQuery -> list[Chunk]`. None이면 `backend.rag.retrieve.search`.
    - llm: `.invoke(messages)`를 가진 채팅 모델. None이면 `get_chat_model()`.
    - checkpointer: interrupt에서 멈춘 자리를 저장한다. 없으면 interrupt를 쓸 수 없다(LangGraph가 오류를 낸다).
    - store: 쟁점표 저장소. None이면 인메모리.
    - use_skills: None이면 환경변수 USE_SKILLS를 따른다.
    - approvals: 승인함 저장소(`DecisionRepo`). 서버는 반드시 넘긴다. None이면 승인함에 올리지 않는다(그래프만 도는 시험용).
    """
    retrieve = retriever if retriever is not None else default_retriever
    llm = llm if llm is not None else get_chat_model()
    store = store if store is not None else InMemoryIssueTableStore()

    def ask_json(system: str, user: str, attempts: int = JSON_ATTEMPTS) -> dict | None:
        from langchain_core.messages import HumanMessage, SystemMessage

        for _ in range(attempts):
            obj = parse_json_obj(_text(llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])))
            if obj is not None:
                return obj
        return None

    # ---- 노드 ----
    def supervisor(state: ReviewState) -> dict:
        request = (state.get("question") or "").strip()
        base: dict = {
            "as_of": state.get("as_of") or today_kst().isoformat(), "kind": "", "answer": "", "clarify_question": None,
            "review_status": "", "saved_table_id": None, "team_results": {}, "tasks": {},
        }
        if not request:
            msg = "검토할 업무 요청이 비어 있습니다. 도입하려는 도구와 금액 같은 내용을 적어 주세요."
            return {**base, "kind": "clarify", "answer": msg, "clarify_question": msg, "review_status": "clarify"}
        obj = ask_json(T.SUPERVISOR_SYSTEM, T.supervisor_user(request, base["as_of"])) or {}
        missing = [IT._clean(m) for m in obj["missing"] if isinstance(m, str) and m.strip()] if isinstance(obj.get("missing"), list) else []
        if missing:  # EC-08: 검토에 필요한 값이 빠졌으면 되묻고 끝낸다
            msg = f"검토에 필요한 값이 요청에 없습니다: {', '.join(missing)}. 알려 주시면 검토합니다."
            return {**base, "kind": "clarify", "answer": msg, "clarify_question": msg, "review_status": "clarify"}
        given = obj.get("tasks") if isinstance(obj.get("tasks"), dict) else {}
        tasks = {t.team_id: (IT._clean(given.get(t.team_id)) or request) for t in T.TEAMS}  # 모델이 팀 몫을 안 냈으면 요청 그대로
        return {**base, "tasks": tasks}

    def after_supervisor(state: ReviewState):
        return END if state.get("review_status") == "clarify" else [f"team_{t.team_id}" for t in T.TEAMS]

    def not_reviewed(team: T.Team, reason: str, **extra) -> dict:
        return {"label": team.label, "status": "not_reviewed", "rows": [], "reason": reason, "private_excluded": 0, "dropped": 0, **extra}

    def review_team(team: T.Team, state: ReviewState) -> dict:
        request = state["question"].strip()
        skill_body = T.team_skills(team, enabled=use_skills)  # 설정 오류는 다시 해도 같다. 바깥에서 "검토하지 못함"이 된다
        query = SearchQuery(query=T.search_text(team, request), sub_queries=T.search_subs(team, request), org=team.org, as_of=state.get("as_of"), k=SEARCH_K)
        found: list[dict] | None = None  # 검색이 한 번 되면 그 결과로 모델만 다시 돌린다. 인용 검사도 같은 자료와 맞댄다
        failure: dict = {}
        note = ""
        for attempt in range(1, TEAM_ATTEMPTS + 1):
            try:
                if found is None:
                    found = [redact_chunk(c.model_dump()) for c in retrieve(query)]
                private = [c for c in found if IT.is_private(c)]
                public = [c for c in found if not IT.is_private(c)]
                if not public:  # 근거가 없는 것은 실패가 아니라 결과다. 다시 찾아도 같다
                    reason = "근거가 비공개 문서(internal.gitlab.com)뿐이라 근거로 쓰지 않았습니다." if private else "핸드북에서 근거를 찾지 못했습니다."
                    return not_reviewed(team, reason, private_excluded=len(private))
                user = T.team_user(request, state["tasks"].get(team.team_id, request), state.get("as_of"), P.format_materials(public)) + note
                obj = ask_json(T.team_system(team, skill_body), user, attempts=1)
            except Exception as e:  # noqa: BLE001 - 일시 오류일 수 있어 상한까지 다시 한다. 비용 상한만 그대로 올린다
                if type(e).__name__ == "CostCapExceeded":
                    raise
                log.warning("팀 에이전트 오류 %s (%d/%d): %s", team.team_id, attempt, TEAM_ATTEMPTS, type(e).__name__)
                failure = not_reviewed(team, f"검토 중 오류가 나 검토하지 못했습니다 ({type(e).__name__}).", attempts=attempt, gave_up=True)
                if attempt < TEAM_ATTEMPTS and TEAM_RETRY_WAIT_SECONDS:
                    time.sleep(TEAM_RETRY_WAIT_SECONDS)
                continue
            note = RETRY_NOTE
            if obj is None or not isinstance(obj.get("issues"), list):
                failure = not_reviewed(team, "모델 응답을 읽지 못했습니다.", private_excluded=len(private), attempts=attempt, gave_up=True)
                continue
            rows, dropped = IT.build_rows(team.team_id, team.label, obj["issues"], public,
                                          leaks=lambda t: leaks_internal(t) or U.leaks_instruction(t, public, request))  # 출력 검사(GRAPH_SCRUB_OUTPUT): 원문 지시에서 온 표식을 옮긴 쟁점은 행이 되지 못한다
            if obj["issues"] and not rows:  # 쟁점을 냈지만 인용 검사에서 모두 걸렸다: 쟁점 없음으로 위장하지 않는다
                failure = not_reviewed(team, f"쟁점 {len(obj['issues'])}개가 근거 인용 검사를 통과하지 못했습니다.", private_excluded=len(private),
                                       dropped=len(dropped), attempts=attempt, gave_up=True)
                continue
            return {"label": team.label, "status": "reviewed", "rows": rows, "reason": "", "private_excluded": len(private),
                    "dropped": len(dropped), "attempts": attempt}
        return failure

    def team_node(team: T.Team):
        def run(state: ReviewState) -> dict:
            started = time.perf_counter()
            try:
                res = review_team(team, state)
            except Exception as e:  # noqa: BLE001 - 한 팀의 실패가 전체를 멈추거나 조용히 빠지지 않게 한다. 비용 상한만 그대로 올린다
                if type(e).__name__ == "CostCapExceeded":
                    raise
                log.warning("팀 에이전트 실패 %s: %s", team.team_id, type(e).__name__)
                res = not_reviewed(team, f"검토 중 오류가 나 검토하지 못했습니다 ({type(e).__name__}).")
            return {"team_results": {team.team_id: {**res, "seconds": round(time.perf_counter() - started, 3)}}}  # 표 해시와 승인 id에 들어가지 않는 칸이다

        return run

    def check_teams(state: ReviewState) -> dict:
        results = state.get("team_results") or {}
        failed = [{"team": t, "reason": results[t]["reason"], "attempts": results[t].get("attempts", TEAM_ATTEMPTS)}
                  for t in T.TEAM_IDS if (results.get(t) or {}).get("gave_up")]
        return {"failed_teams": failed, **({"review_status": TEAM_FAILED_KIND} if failed else {})}

    def after_check(state: ReviewState):
        return "queue_team_failure" if state.get("failed_teams") else "merge"

    def failure_summary(failed: list[dict]) -> str:
        labels = {t.team_id: t.label for t in T.TEAMS}
        return f"팀 검토 실패: {', '.join(labels[f['team']] for f in failed)}. 다시 돌릴지, 검토하지 못함으로 남길지 정해 주세요."

    def queue_team_failure(state: ReviewState, config: RunnableConfig) -> dict:
        failed = state["failed_teams"]
        run_thread = config["configurable"].get("thread_id") or ""
        approval_id = IT.failure_approval_id(state.get("thread_id") or run_thread, state["question"].strip(), state.get("as_of"), failed)
        if approvals is not None:
            approval_id = approvals.queue_review_item(run_thread, approval_id, failure_summary(failed), kind=TEAM_FAILED_KIND).approval_id
        return {"approval_id": approval_id, "decision": None}

    def team_failure_gate(state: ReviewState, config: RunnableConfig) -> dict:
        # 이 노드는 재개할 때 처음부터 다시 돈다. interrupt 앞에는 읽기만 둔다. 틀린 재개 값은 상태를 바꾸지 않고 같은 요청을 다시 올린다.
        failed = state["failed_teams"]
        payload = {"approval_id": state["approval_id"], "kind": TEAM_FAILED_KIND, "summary": failure_summary(failed), "failed_teams": failed,
                   "thread_id": state.get("thread_id") or config["configurable"].get("thread_id") or ""}
        while True:
            raw = interrupt(payload)
            d = raw if isinstance(raw, dict) else {}
            action, by = d.get("action"), d.get("decided_by")
            if d.get("approval_id") not in (None, state["approval_id"]):   # 앞 승인 건의 재개 값이 남아 들어온 것(아래 `approval` 참고): 받지 않고 같은 요청을 다시 올린다
                continue
            if not isinstance(action, str) or action not in TEAM_ACTIONS:
                payload = {**payload, "rejected_resume": "bad_action"}
            elif not isinstance(by, str) or not by.strip():
                payload = {**payload, "rejected_resume": "approver_missing"}
            else:
                return {"decision": {"action": action, "approve": action == "retry", "comment": IT._clean(d.get("comment")), "decided_by": by}}

    def apply_team_action(state: ReviewState) -> dict:
        d = state["decision"]
        if approvals is not None:  # 같은 입력으로 다시 돌아도 결과가 같다
            approvals.decide_review_item(state["approval_id"], d["approve"], d["decided_by"], d["comment"])
        return {"team_action": d["action"], "decision": None}

    def after_team_action(state: ReviewState):
        return [f"team_{f['team']}" for f in state["failed_teams"]] if state.get("team_action") == "retry" else "merge"

    def merge(state: ReviewState) -> dict:
        table = IT.merge_table(state["question"].strip(), state.get("as_of"), list(T.TEAM_IDS), state.get("team_results") or {})
        if not IT.has_content(table):  # EC-01, AC-05: 승인함에 올리지 않는다
            return {"table": table, "kind": "answer", "answer": f"{MSG_NO_ISSUES} {T.LICENSE_NOTE}", "review_status": "no_issues"}
        return {"table": table, "review_status": "pending_approval"}

    def after_merge(state: ReviewState):
        return END if state.get("review_status") == "no_issues" else "queue_approval"

    def queue_approval(state: ReviewState, config: RunnableConfig) -> dict:
        table = state["table"]
        run_thread = config["configurable"].get("thread_id") or ""  # 재개에 쓰는 진짜 대화 번호
        approval_id = IT.approval_id_for(state.get("thread_id") or run_thread, table)
        if approvals is not None:
            approval_id = approvals.queue_review_item(run_thread, approval_id, IT.summarize(table)).approval_id
        return {"approval_id": approval_id, "decision": None}  # 같은 대화의 앞선 결정이 다음 표에 쓰이지 않게 지운다

    def approval(state: ReviewState) -> dict:
        # 이 노드는 재개할 때 처음부터 다시 돈다. interrupt 앞에는 읽기만 둔다.
        table = state["table"]
        payload = {
            "approval_id": state["approval_id"], "kind": "issue_table", "summary": IT.summarize(table),
            "thread_id": state.get("thread_id") or "", "table": table,
        }
        while True:
            raw = interrupt(payload)
            d = raw if isinstance(raw, dict) else {}
            if d.get("approval_id") not in (None, state["approval_id"]):
                # 팀 실패 알림 결정을 적은 뒤 다음 단계에서 오류가 나 같은 결정으로 이어 돌릴 때, 질문 그래프 아래 하위 그래프에서는 앞 승인 건의 재개 값이
                # 이 멈춤의 재개 값으로 다시 들어온다. 그대로 두면 사람이 보지 않은 쟁점표가 반려로 끝난다. 다른 승인 건 번호의 값은 받지 않고 같은 요청을 다시 올린다.
                continue
            decision = {
                "approve": d.get("approve") is True,  # 불리언 True만 승인이다. "true", 1, 빈 값은 승인이 아니다
                "comment": IT._clean(d.get("comment")),
                "decided_by": d.get("decided_by") if isinstance(d.get("decided_by"), str) else None,
            }
            if approvals is not None and decision["approve"] and not (decision["decided_by"] or "").strip():
                payload = {**payload, "rejected_resume": "approver_missing"}  # 승인함의 승인에는 승인한 관리자가 있어야 한다. 저장하지 않고 다시 묻는다
                continue
            return {"decision": decision}

    def finalize(state: ReviewState) -> dict:
        table, decision = state["table"], state["decision"]
        common = dict(approval_id=state["approval_id"], thread_id=state.get("thread_id") or "", user_id=state.get("user_id") or "")
        if decision["approve"]:
            table_id = store.save(**common, request=table["request"], as_of=table.get("as_of"), rows=table["rows"],
                                  unreviewed=table["unreviewed"], approved_by=decision["decided_by"])
            if approvals is not None:
                approvals.decide_review_item(state["approval_id"], True, decision["decided_by"], decision["comment"], table_id=table_id)
            return {"kind": "answer", "review_status": "approved", "saved_table_id": table_id, "issue_table": table,
                    "answer": f"{MSG_SAVED} {IT.summarize(table)} {T.LICENSE_NOTE}"}
        reason = decision["comment"] or "사유 없음"
        store.record_rejection(**common, reason=reason, decided_by=decision["decided_by"])
        if approvals is not None:
            approvals.decide_review_item(state["approval_id"], False, decision["decided_by"], decision["comment"])
        return {"kind": "answer", "review_status": "rejected", "saved_table_id": None, "answer": f"{MSG_REJECTED} 사유: {reason}"}

    g = StateGraph(ReviewState)
    g.add_node("supervisor", supervisor)
    for t in T.TEAMS:
        g.add_node(f"team_{t.team_id}", team_node(t))
    g.add_node("check_teams", check_teams)
    g.add_node("queue_team_failure", queue_team_failure)
    g.add_node("team_failure_gate", team_failure_gate)
    g.add_node("apply_team_action", apply_team_action)
    g.add_node("merge", merge)
    g.add_node("queue_approval", queue_approval)
    g.add_node("approval", approval)
    g.add_node("finalize", finalize)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", after_supervisor)
    for t in T.TEAMS:  # 모두 기다리는 묶음 간선을 쓰지 않는다: 재시도에서는 실패한 팀만 돈다. 같은 단계에서 돈 팀들 뒤에 `check_teams`는 한 번 돈다
        g.add_edge(f"team_{t.team_id}", "check_teams")
    g.add_conditional_edges("check_teams", after_check)
    g.add_edge("queue_team_failure", "team_failure_gate")
    g.add_edge("team_failure_gate", "apply_team_action")
    g.add_conditional_edges("apply_team_action", after_team_action)
    g.add_conditional_edges("merge", after_merge)
    g.add_edge("queue_approval", "approval")
    g.add_edge("approval", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
