"""결정표 실행 (D-06, J-07, docs/specs/decision-approval.md 사용 흐름). LLM을 쓰지 않는다.

승인 전 실행 금지: `DecisionExecutor.run()`은 규칙을 만지기 전에 표의 상태가 `approved`이고 승인자가 있는지 먼저 본다.
아니면 `NotApproved`(409)를 올리고 `executions`에도 남기지 않는다. 승인 전 실행 건수 = `len(executions)`가 0인지로 시험한다.

사용자에게 보이는 금액은 `band_label`의 정확한 금액으로 쓰고, 권한표 원문 표기(`$500K` 등)는 `source`와 근거 인용 칸(`decision_citation`) 안에만 둔다.
채팅 답 본문(`format_decision_answer`)에는 정확한 금액 표기만 쓴다.
"""
from __future__ import annotations

from typing import Any

from backend.graph.decision import rules as R
from backend.graph.decision.repo import DecisionRepo, table_category
from backend.rag.ingest.handbook import AUTHZ_COMMIT, AUTHZ_PATH, AUTHZ_PROJECT

AUTHZ_RULE_TITLE = "Authorization Matrix (2023-05)"  # 색인의 권한표 청크와 같은 제목
AUTHZ_VERSION_DATE = "2023-05-11"  # `AUTHZ_COMMIT`의 커밋 날짜


def _source_url(version_id: str) -> str | None:
    """표의 판이 고정해 둔 2023 권한표 판이면 그 원문 주소. 모르는 판이면 지어내지 않고 None."""
    if version_id and AUTHZ_COMMIT.startswith(version_id):
        return f"https://gitlab.com/{AUTHZ_PROJECT}/-/blob/{AUTHZ_COMMIT}/{AUTHZ_PATH}"
    return None


class DecisionExecutor:
    def __init__(self, repo: DecisionRepo) -> None:
        self.repo = repo
        self.executions: list[str] = []  # 실제로 규칙을 돌린 table_id (시험·감사용)

    def resolve(self, task_type: str | None, table_id: str | None = None):
        """표를 정한다. `table_id`가 있으면 그 표, 없으면 업무 종류로 승인된 표가 정확히 1개일 때만 (EC-04, AC-06)."""
        if table_id:
            table = self.repo.get_table(table_id)
            if task_type and R.norm(table_category(table)) != R.norm(task_type):
                raise R.NotFound("그 결정표의 업무 종류가 아니다")
            return table
        if not (task_type or "").strip():
            raise R.BadRequest("task_type이 필요하다")
        found = self.repo.find_approved(task_type)
        if len(found) != 1:
            raise R.AmbiguousTable(f"업무 종류 '{task_type}'로 승인된 결정표가 {len(found)}개라 실행하지 않는다 (정확히 1개일 때만 실행)")
        return found[0]

    def run(self, task_type: str | None, amount_usd: Any = None, *, table_id: str | None = None, band: str | None = None) -> dict:
        table = self.resolve(task_type, table_id)
        if table.status != "approved" or not (table.approved_by or "").strip():   # J-07: 규칙을 만지기 전에 막는다
            raise R.NotApproved(f"결정표 {table.table_id}는 {table.status} 상태라 실행할 수 없다")
        out = R.run_rules(table.cells, amount_usd, band)
        self.executions.append(table.table_id)
        source = {"rule_seq": table.rule_seq, "source_url": _source_url(table.version_id), **out.pop("source")}
        return {"table_id": table.table_id, "version_id": table.version_id, "approved_by": table.approved_by, "source": source, **out}


def decision_citation(result: dict) -> dict:
    """실행 결과의 근거 인용 칸(`citation` 이벤트 키). 원문 표기는 `article`에 그대로 둔다. 결정표 실행은 검색 청크를 쓰지 않으므로 `chunk_id`는 비어 있다."""
    src = result["source"]
    known = bool(src.get("source_url"))  # 고정해 둔 권한표 판일 때만 제목과 날짜를 적는다. 모르는 판은 지어내지 않는다
    return {"chunk_id": None, "rule_seq": src.get("rule_seq"), "rule_title": AUTHZ_RULE_TITLE if known else None, "article": src["article"],
            "version_id": result["version_id"], "version_date": AUTHZ_VERSION_DATE if known else None, "version_date_before": False,
            "source_url": src.get("source_url")}


def make_execute_node(executor: DecisionExecutor):
    """질문 그래프에 끼울 실행 노드. 상태의 `decision_query`({task_type, amount_usd, table_id?, band?})를 읽어
    `decision_result` 또는 `decision_error`({status, reason, message})를 채운다."""

    def decision_run(state: dict) -> dict:
        q = state.get("decision_query") or {}
        try:
            return {"decision_result": executor.run(q.get("task_type"), q.get("amount_usd"), table_id=q.get("table_id"), band=q.get("band"))}
        except R.DecisionError as e:
            return {"decision_error": {"status": e.status, "reason": e.reason, "message": e.message}}

    return decision_run


def format_decision_answer(result: dict) -> str:
    """실행 결과를 한국어 답으로 쓴다(코드, LLM 없음). 근거(표, 판, 원문 행)를 붙인다."""
    parts = [f"구간: {result['band_label']}", f"승인 순서: {' → '.join(result['approvers']) or '없음'}"]
    if result.get("cooperating"):
        parts.append(f"협조: {', '.join(result['cooperating'])}")
    if result.get("range_note"):
        parts.append(f"주의: {result['range_note']}")
    src = result["source"]
    parts.append(f"근거: 결정표 {result['table_id']} · 권한표 판 {result['version_id']} · {src['category']} / {result['band_label']}")
    return "\n".join(parts)
