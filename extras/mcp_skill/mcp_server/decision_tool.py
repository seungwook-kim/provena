"""읽기 전용 MCP 도구 `explain_decision`: 승인된 결정표를 금액으로 실행한 결과(승인 순서와 근거)를 돌려준다.

판단 코드를 따로 두지 않는다. 그래프(`backend/graph/build.py`의 `make_execute_node(DecisionExecutor(...))`)와 HTTP
(`backend/graph/decision/routes.py`의 `DecisionExecutor(...).run(...)`)가 쓰는 같은 실행기를 부른다. MCP만 다른 판단 코드를 쓰면
같은 질문에 답이 달라질 수 있기 때문이다(경계 금액, 겹치는 구간 거절, 위 끝이 빈 구간 해석은 모두 `rules.py`가 정한다).
실행기는 LLM을 쓰지 않고 표를 바꾸지 않는다(`execute.py` 1~8줄). 승인 전 표는 실행기가 먼저 막는다(`NotApproved`).

내보내는 칸은 HTTP 응답 모양(`routes.py` `RunResponse`·`RunSource`)과 같고, 고른 칸만 새 dict에 옮긴다(화이트리스트).
`approved_by`(승인한 관리자 user_id, `db/102_decision_approvals.sql`)는 내보내지 않는다. MCP 토큰은 기계 키 하나라
누가 묻는지 모른다(`server.BearerTokenVerifier`). HTTP 실행 응답에도 이 칸은 없다. 대신 사람 id 없는 `approved: true`를 둔다.

실행기 오류 → 상태 (`rules.py` DecisionError의 status·reason을 보고 옮긴다):
  BadRequest 400            → invalid    (입력을 고쳐 다시. 예: 금액이 음수, 금액 없는 업무에 band 없음)
  NotFound 404              → not_found  (그 표·구간이 없음, 금액이 지정한 구간 밖)
  NotApproved 409           → not_ready  (표가 사람 승인 전. 규칙은 실행되지 않았다)
  AmbiguousTable 409, 0개   → not_ready  (그 업무 종류로 승인된 표가 아직 없다. "없다"와 구분. note에 승인된 업무 종류 후보)
  AmbiguousTable 409, 2개+  → invalid    (table_id를 지정해 다시. note에 후보 table_id)
  AmbiguousBand 422         → not_found  (금액이 두 구간에 함께 들어 하나로 정할 수 없다. 입력이 틀린 것이 아니고, band를 줘도 같으므로
                                          invalid로 두지 않는다. 결정표가 이 금액에는 답을 주지 않는다는 뜻)
메시지는 실행기 코드가 쓴 글만 쓴다. 저장소 예외 글·DB 주소는 내보내지 않는다(server._failure).

저장소: MCP 앱은 FastAPI lifespan보다 먼저 만들어지므로(`backend/main.py` create_app) `app.state.decision_repo`를 읽지 않는다.
`register(mcp, repo=...)`로 넣거나, 비우면 처음 부를 때 `DATABASE_URL`로 `PostgresDecisionRepo(server.pg_pool())`를 만든다.
"""
from __future__ import annotations

import threading
from typing import Any

from pydantic import StrictFloat

from extras.mcp_skill.mcp_server.server import (
    READ_ONLY, Invalid, ToolResponse, _check_text, _failure, _resp, _run, missing_table, pg_pool, redact,
)

MAX_TEXT = 200        # task_type·table_id·band 길이 상한. 2023 권한표 업무 종류 이름 최대 39자, table_id는 `new_id` 22자 안팎
MAX_CANDIDATES = 10   # note에 보이는 후보 수(server.MAX_NAMES와 같은 값)
SOURCE = "decision_tables"


def _text(value: Any) -> Any:
    return redact(value) if isinstance(value, str) else value


def _names(values: Any) -> list[str]:
    return [redact(str(v)) for v in values] if isinstance(values, list) else []


def explain(result: dict) -> dict[str, Any]:
    """실행기 결과 → 내보낼 dict. 칸을 지우지 않고 고른 칸만 새로 옮긴다(실행기에 칸이 늘어도 새지 않게)."""
    src = result.get("source") or {}
    return {
        "table_id": result.get("table_id"),
        "version_id": result.get("version_id"),
        "approved": True,                                 # 실행기는 approved이고 승인자가 있는 표만 실행한다(execute.py run)
        "band_label": _text(result.get("band_label")),
        "range_note": _text(result.get("range_note")),
        "approvers": _names(result.get("approvers")),
        "functional_approvers": _names(result.get("functional_approvers")),
        "financial_approvers": _names(result.get("financial_approvers")),
        "cooperating": _names(result.get("cooperating")),
        "source": {
            "rule_seq": src.get("rule_seq"),
            "category": _text(src.get("category")),
            "band": _text(src.get("band")),
            "article": _text(src.get("article")),
            "source_url": src.get("source_url"),
        },
    }


def _check(task_type, amount_usd, table_id, band) -> None:
    """길이·형식만 본다. 금액 값(음수·무한대)과 업무·구간 판단은 실행기가 한다(HTTP와 같은 규칙, routes.py `_parse_run`)."""
    if not isinstance(task_type, str) or not task_type.strip() or len(task_type) > MAX_TEXT:
        raise Invalid(f"task_type은 1~{MAX_TEXT}자(권한표 업무 종류 이름, 예: Approving expense)")
    for name, value in (("table_id", table_id), ("band", band)):
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT):
            raise Invalid(f"{name}는 1~{MAX_TEXT}자 또는 비움")
        if value is not None:
            _check_text(value, name)     # table_id는 SQL로 간다. NUL이면 psycopg DataError → error로 새므로 미리 invalid


class _Repo:
    """결정표 저장소. 주면 그것, 비우면 DATABASE_URL이 있을 때 처음 부를 때 PostgresDecisionRepo를 만든다(없으면 None)."""

    def __init__(self, repo=None):
        self._repo, self._lock = repo, threading.Lock()

    def get(self):
        with self._lock:
            if self._repo is None:
                pool = pg_pool()
                if pool is None:
                    return None
                from backend.graph.decision.repo import PostgresDecisionRepo
                self._repo = PostgresDecisionRepo(pool)
            return self._repo


def _execute(repo, task_type, amount_usd, table_id, band) -> dict:
    """실행기를 그대로 부른다. 결과 또는 오류 상태 dict. 호출마다 새 실행기(routes.py execute와 같다)."""
    from backend.graph.decision import rules as R
    from backend.graph.decision.execute import DecisionExecutor, decision_citation

    try:
        result = DecisionExecutor(repo).run(task_type, amount_usd, table_id=table_id, band=band)
    except R.AmbiguousTable as e:
        found = repo.find_approved(task_type)
        return {"error": e, "approved_ids": sorted(t.table_id for t in found),
                "categories": sorted({c for c in (_category(t) for t in repo.list_approved()) if c}) if not found else []}
    except R.DecisionError as e:
        return {"error": e}
    return {"result": result, "version_date": decision_citation(result)["version_date"]}


def _category(table) -> str:
    from backend.graph.decision.repo import table_category
    return table_category(table)


def _error_response(out: dict) -> ToolResponse:
    from backend.graph.decision import rules as R

    e = out["error"]
    msg = redact(e.message)
    if isinstance(e, R.AmbiguousTable):
        ids = out["approved_ids"]
        if not ids:
            cats = out["categories"]
            hint = " 승인된 결정표의 업무 종류: " + " | ".join(redact(c) for c in cats[:MAX_CANDIDATES]) if cats else " 승인된 결정표가 하나도 없습니다."
            return _resp("not_ready", SOURCE, retryable=False,
                         note=f"{msg}. 승인된 결정표가 아직 없거나 업무 종류 이름이 다릅니다(결정표가 없다는 뜻이 아님).{hint}")
        return _resp("invalid", SOURCE, note=f"{msg}. table_id를 지정해 다시 부르세요: " + " | ".join(ids[:MAX_CANDIDATES]))
    if isinstance(e, R.NotApproved):
        return _resp("not_ready", SOURCE, retryable=False, note=f"{msg}. 사람이 승인한 결정표만 실행합니다.")
    if isinstance(e, R.AmbiguousBand):
        return _resp("not_found", SOURCE, note=f"{msg}. 이 금액은 결정표 해석상 구간이 하나로 정해지지 않아 실행하지 않았습니다(band를 줘도 같음).")
    if e.status == 404:
        return _resp("not_found", SOURCE, note=msg)
    if e.status == 400:
        return _resp("invalid", SOURCE, note=msg)
    return _resp("error", SOURCE, retryable=False, note="결정표를 실행하지 못했습니다. 다시 불러도 같습니다.")


def register(mcp, repo=None) -> None:
    """explain_decision을 mcp에 붙인다. repo가 없고 DATABASE_URL도 없으면 도구는 not_ready를 돌려준다."""
    store = _Repo(repo)

    @mcp.tool(annotations=READ_ONLY)
    # amount_usd는 StrictFloat: 기본 float는 "30000"(글)·true를 숫자로 바꿔 받는다(실측: true → $1로 실행됨). HTTP는 둘 다 400이다
    # (routes.py _parse_run → rules.check_amount). 엄격 숫자로 두면 FastMCP 입력 검사에서 막히고 정수는 그대로 받는다.
    async def explain_decision(task_type: str, amount_usd: StrictFloat | None = None, table_id: str | None = None,
                               band: str | None = None) -> ToolResponse:
        """승인된 결정표(2023 권한표 → 사람이 승인한 규칙)를 금액으로 실행해 승인 순서와 근거 행을 돌려준다.
        그래프와 HTTP 실행(`POST /decision-tables/run`)이 쓰는 같은 실행기(DecisionExecutor)를 부르므로 답이 같다. LLM 없음.

        언제 쓰나: "이 업무를 이 금액으로 하면 누구 승인이 필요한가"에 결정표 근거로 답할 때.
        언제 쓰지 않나: 결정표를 만들거나 승인·수정할 때(승인함 화면과 사람 승인을 거친다, MCP 도구 없음).
              권한표 원문 글을 읽을 때는 search_handbook·get_section.
        입력: task_type = 권한표 업무 종류 이름(예: Approving expense, 대소문자·공백 무시) /
              amount_usd = 금액(USD, 0 이상) / table_id = 결정표 id(같은 업무 종류로 승인된 표가 둘 이상일 때) /
              band = 구간 이름(금액 칸이 없는 업무, 예: Legal Contracts의 Standard Terms).
        출력: results = [실행 결과 하나]: band_label(정확한 금액 표기), approvers(승인 순서: 업무 승인 다음 재무 승인),
              functional_approvers, financial_approvers, cooperating(승인 아닌 협조), range_note(해석으로 채운 구간 끝 설명),
              table_id, version_id, approved=true, source(rule_seq, category, band·article = 권한표 원문 표기, source_url).
              source = decision_tables:<table_id>@<version_id>, as_of = 권한표 판 날짜(고정해 둔 판일 때만, 아니면 null).
        제약: 승인한 관리자 id는 내보내지 않는다. 승인 전 표·그 업무로 승인된 표 없음 = not_ready(없다는 뜻이 아님),
              표·구간 없음과 금액이 두 구간에 함께 듦 = not_found, 승인된 표가 둘 이상 = invalid(note의 table_id로 다시),
              DATABASE_URL이 없으면 not_ready, 저장소 연결 실패는 unavailable(잠시 뒤 다시).
              range_note가 있으면 답 끝에 주의로 붙인다(원문에 없는 구간 끝을 해석으로 채움).
        """
        try:
            _check(task_type, amount_usd, table_id, band)
            r = store.get()
            if r is None:
                return _resp("not_ready", SOURCE, retryable=False,
                             note="서버에 결정표 저장소(DATABASE_URL)가 없습니다. 결정표가 없다는 뜻이 아닙니다.")
            out = await _run(_execute, r, task_type, amount_usd, table_id, band)
        except Exception as e:  # noqa: BLE001 — 상태로 돌려준다
            if missing_table(e):
                return _resp("not_ready", SOURCE, retryable=False,
                             note="결정표 표(decision_tables)가 아직 DB에 없습니다. 결정표가 없다는 뜻이 아닙니다.")
            return _failure("explain_decision", SOURCE, e)
        if "error" in out:
            return _error_response(out)
        res = out["result"]
        return _resp("ok", f"{SOURCE}:{res['table_id']}@{res['version_id']}", [explain(res)], as_of=out["version_date"])
