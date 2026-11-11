"""쟁점표 만들기와 합치기 (F-03). LLM 없이 코드로만 한다.

- `build_rows`: 팀 에이전트가 낸 쟁점을 검색된 청크와 대조해 행으로 만든다. 근거 제목 경로, 판 날짜, 원문 URL은 청크에서 복사하고
  모델이 쓴 값은 쓰지 않는다. 청크에 없는 chunk_id, 비공개 주소 청크, 모델이 인용 값을 틀리게 쓴 쟁점은 행이 되지 못한다(인용은 코드로 대조).
- `merge_table`: 팀 순서대로 행을 모으고, 같은 쟁점(topic)에 팀 입장이 갈리면 하나로 합치지 않고 나란히 두며 conflict를 표시한다(EC-05).
- 검토하지 못한 팀은 행이 아니라 `unreviewed`에 이유와 함께 남는다(EC-02). 행에는 항상 근거가 있다.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict

from backend.graph.citations import check_citations
from backend.rag.retrieve.privacy import PRIVATE_MARK

STANCES = ("allow", "condition", "block")
CONFIDENCES = ("high", "medium", "low")
MAX_ISSUES_PER_TEAM = 5  # 팀 하나가 내는 쟁점 상한(표가 길어지는 것을 막는다)
MAX_TEXT = 400  # 쟁점 문장 최대 글자 수
PRIVATE_HOST = "internal.gitlab.com"
ROW_FIELDS = (
    "team", "team_label", "topic", "issue", "stance", "confidence", "chunk_id", "rule_seq", "rule_title", "article",
    "section_path", "version_id", "version_date", "version_date_before", "source_url", "conflict",
)
_APPROVAL_NS = uuid.UUID("6f1d2b0e-5a0c-4f3e-9a58-2f6f0a1c7e11")
_MARK = re.compile(r"\[\[task:|<<<|>>>")


def is_private(chunk: dict) -> bool:
    """근거 주소가 비공개 문서(internal.gitlab.com)인가. 이런 청크는 근거로 쓰지 않는다(EC-09, AGENTS.md)."""
    url = str(chunk.get("source_url") or "")
    return PRIVATE_HOST in url or PRIVATE_MARK in url  # MCP를 거치면 주소가 표시로 바뀌어 있다


def section_path(chunk: dict) -> str:
    """근거 섹션 제목 경로: 페이지 제목 > 제목 경로. 제목 경로가 없으면 페이지 제목만."""
    return " > ".join(p for p in (chunk.get("rule_title"), chunk.get("article")) if p)


def _clean(value: object) -> str:
    s = value if isinstance(value, str) else ""
    return " ".join(_MARK.sub("", s).split())[:MAX_TEXT]


def build_rows(team_id: str, team_label: str, issues: object, chunks: list[dict], *, leaks=lambda text: False) -> tuple[list[dict], list]:
    """(행 목록, 버린 쟁점 목록). `issues`는 모델이 낸 [{topic, issue, chunk_id, stance, confidence}, ...]."""
    rows: list[dict] = []
    dropped: list = []
    if not isinstance(issues, list):
        return rows, [issues] if issues else []
    public = [c for c in chunks if not is_private(c)]
    seen: set[tuple[str, str]] = set()
    for item in issues:
        if not isinstance(item, dict):
            dropped.append(item)
            continue
        cid = item.get("chunk_id")
        issue = _clean(item.get("issue"))
        topic = _clean(item.get("topic"))
        if not isinstance(cid, str) or not issue or leaks(issue) or (topic and leaks(topic)):  # topic 칸도 모델이 쓴 글이라 쟁점 문장과 같은 검사를 거친다(사전 등록 62.26)
            dropped.append(item)
            continue
        # 인용 검사(코드): 이번에 검색된 공개 청크에 있어야 하고, 모델이 같이 쓴 값이 있으면 청크 값과 같아야 한다
        cited = {"chunk_id": cid, **{k: item[k] for k in ("rule_seq", "article", "version_id") if k in item}}
        valid, _, _ = check_citations([cited], public, "")
        if not valid:
            dropped.append(item)
            continue
        key = (cid, issue)
        if key in seen:
            continue
        seen.add(key)
        c = valid[0]
        stance = item.get("stance") if item.get("stance") in STANCES else "condition"
        conf = item.get("confidence") if item.get("confidence") in CONFIDENCES else "low"
        rows.append({
            "team": team_id, "team_label": team_label, "topic": topic.lower(), "issue": issue,
            "stance": stance, "confidence": conf, "chunk_id": c["chunk_id"], "rule_seq": c.get("rule_seq"),
            "rule_title": c.get("rule_title"), "article": c.get("article"), "section_path": section_path(c),
            "version_id": c.get("version_id"), "version_date": c.get("version_date"),
            "version_date_before": bool(c.get("version_date_before")), "source_url": c.get("source_url"), "conflict": False,
        })
        if len(rows) >= MAX_ISSUES_PER_TEAM:
            break
    return rows, dropped


def merge_table(request: str, as_of: str | None, team_order: list[str], team_results: dict[str, dict]) -> dict:
    """팀 결과를 쟁점표 하나로 합친다.

    team_results[team] = {"label", "status": "reviewed" | "not_reviewed", "rows": [...], "reason": str, "private_excluded": int}.
    같은 topic에 서로 다른 팀의 입장(stance)이 둘 이상 갈리면 그 행들에 conflict=True를 붙인다. 행은 지우거나 합치지 않는다.
    """
    rows: list[dict] = []
    unreviewed: list[dict] = []
    private_excluded: dict[str, int] = {}
    team_status: dict[str, str] = {}
    for t in team_order:
        r = team_results.get(t) or {"label": t, "status": "not_reviewed", "rows": [], "reason": "팀 에이전트 결과가 없음"}
        team_status[t] = r["status"]
        if r["status"] != "reviewed":
            unreviewed.append({"team": t, "team_label": r.get("label", t), "reason": r.get("reason") or "이유 기록 없음"})
        if r.get("private_excluded"):
            private_excluded[t] = r["private_excluded"]
        rows.extend(dict(x) for x in r.get("rows", []))
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if row["topic"]:
            groups[row["topic"]].append(i)
    for idx in groups.values():
        teams = {rows[i]["team"] for i in idx}
        stances = {rows[i]["stance"] for i in idx}
        if len(teams) >= 2 and len(stances) >= 2:
            for i in idx:
                rows[i]["conflict"] = True
    order = {t: n for n, t in enumerate(team_order)}
    keys = [row["topic"] or f"\0{i}" for i, row in enumerate(rows)]  # 같은 topic은 붙여 놓고, 그 밖에는 팀 순서를 지킨다
    first: dict[str, int] = {}
    for i, k in enumerate(keys):
        first.setdefault(k, i)
    rows = [rows[i] for i in sorted(range(len(rows)), key=lambda i: (first[keys[i]], order.get(rows[i]["team"], 99), i))]
    table = {
        "request": request, "as_of": as_of, "rows": rows, "unreviewed": unreviewed, "team_status": team_status,
        "private_excluded": private_excluded,
    }
    table["table_hash"] = table_hash(table)
    return table


def table_hash(table: dict) -> str:
    body = {k: table.get(k) for k in ("request", "as_of", "rows", "unreviewed")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def approval_id_for(thread_id: str, table: dict) -> str:
    """승인함 항목 id. 같은 thread와 같은 표면 늘 같은 값이다: 재개 때 노드가 처음부터 다시 돌아도 id가 바뀌지 않는다."""
    return str(uuid.uuid5(_APPROVAL_NS, f"{thread_id}:{table['table_hash']}"))


def failure_approval_id(thread_id: str, request: str, as_of: str | None, failed_teams: list[dict]) -> str:
    """팀 실패 알림의 승인 건 번호. `approval_id_for`와 같이 같은 입력이면 같은 값이다."""
    body = json.dumps({"request": request, "as_of": as_of, "failed_teams": failed_teams}, ensure_ascii=False, sort_keys=True)
    return str(uuid.uuid5(_APPROVAL_NS, f"team_review_failed:{thread_id}:{body}"))


def has_content(table: dict) -> bool:
    """쟁점이 있거나 검토하지 못한 팀이 있으면 승인 대상이다. 둘 다 없을 때만 '쟁점 없음'이다(EC-01, AC-05)."""
    return bool(table["rows"] or table["unreviewed"])


def summarize(table: dict) -> str:
    rows = table["rows"]
    per_team: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for r in rows:
        per_team[r["team"]] += 1
        labels[r["team"]] = r["team_label"]
    parts = [f"합동 검토 쟁점표: 쟁점 {len(rows)}건"]
    if per_team:
        parts.append("(" + ", ".join(f"{labels[t]} {n}" for t, n in per_team.items()) + ")")
    conflicts = sum(1 for r in rows if r["conflict"])
    if conflicts:
        parts.append(f"팀 의견이 갈린 행 {conflicts}건")
    if table["unreviewed"]:
        parts.append("검토하지 못한 팀 " + ", ".join(u["team_label"] for u in table["unreviewed"]))
    if table["private_excluded"]:
        parts.append("비공개 문서 " + str(sum(table["private_excluded"].values())) + "건은 근거에서 뺌")
    return " / ".join(parts)
