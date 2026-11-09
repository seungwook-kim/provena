"""변경 전 영향 미리보기(F-05): 정책 변경을 병합하기 전에 "무효가 될 과거 답 N건, 달라질 결정표 칸 M개, 알림 받을 사람 K명"을 계산한다.

리콜 그래프와 같은 논리(인용한 과거 답 찾기 -> 결론 변화 판정)를 **드라이런**으로 돌린다. 드라이런은 구조로 보장한다.
- `preview_impact`는 리콜 저장소·웹훅 전송기를 받지 않는다. 답 저장소는 `find_by_article`만 연 읽기 전용 덮개, 결정표는 승인된 표 목록만 받는다.
- 보고서는 `dry_run: true`로 고정이다. 저장·알림·웹훅은 하지 않는다.

입력(셋 중 하나):
- 바뀐 섹션 목록(`ChangedArticle` JSON, 항목마다 `old_text`·`new_text`를 함께 줄 수 있다. 없으면 DB의 섹션 원문을 읽는다).
- 바꿀 쪽의 옛 원문·새 원문 쌍(`pages: [{path, old, new}]`, MR의 변경 파일). 수집과 같은 섹션 비교(`diff.section_changes`)로 바뀐 섹션을 만든다.
- 명령줄의 두 시점 묶음(`--snapshot 옛 새`, `backend/rag/ingest/snapshot_diff.py`).
판정은 리콜과 같은 판정기다(`judge.py`): 키가 있으면 LLM, 데모 모드면 규칙 판정. 결정표 칸은 같은 정책(rule_seq)의 승인된 표에서
칸의 승인자·금액 구간 글자가 개정 전 섹션에 있고 개정 뒤에 줄어든 칸을 "text-match"로, 섹션 원문을 못 찾으면 "unverified"로 센다.

    python -m backend.graph.recall.impact --changes 변경.json [--answers 답.json] [--format md|json]
    python -m backend.graph.recall.impact --snapshot 옛폴더 새폴더 --old-date ... --new-date ... [--prefix content/handbook/]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.graph.recall.graph import min_confidence_from_env
from backend.graph.recall.judge import default_judge
from backend.graph.recall.notice import is_affected
from backend.schemas.recall import ChangedArticle

Verdict = Literal["changed", "unchanged", "needs_review"]
EXCERPT = 80
_TOKEN = re.compile(r"[0-9A-Za-z가-힣$%]+")
ATTRIBUTION = "출처: GitLab Handbook (CC BY-SA 4.0), 요약·재서술. GitLab Inc.와 제휴·보증 관계가 없습니다."


class ChangeView(BaseModel):
    rule_seq: int
    article: str
    change_type: Literal["added", "removed", "modified"]
    old_version_date: str
    new_version_date: str
    answers_affected: int = 0
    answers_invalidated: int = 0
    decision_cells: int = 0


class AnswerImpact(BaseModel):
    answer_id: str
    user_id: str
    question_excerpt: str
    answer_as_of: str | None = None
    rule_seq: int
    article: str
    cited_version_id: str | None = None
    change_type: Literal["added", "removed", "modified"]
    verdict: Verdict
    verdict_note: str
    confidence: float | None = None


class CellImpact(BaseModel):
    table_id: str
    rule_seq: int
    cell_index: int
    category: str
    band: str
    approvers: str
    confidence: Literal["text-match", "unverified"]
    reason: str


class ImpactSummary(BaseModel):
    changes: int
    changes_by_type: dict[str, int]
    answers_checked: int            # 바뀐 섹션을 인용한 과거 답(중복 없이)
    answers_invalidated: int        # 결론이 바뀌거나(changed) 확인이 필요한(needs_review) 답 = 알림 대상
    answers_needs_review: int
    answers_unchanged: int
    decision_tables: int
    decision_cells: int             # 칸 글자가 바뀐 섹션에서 사라진 칸(text-match)
    decision_cells_unverified: int
    recipients: int                 # 알림 받을 서로 다른 사용자 수


class ImpactReport(BaseModel):
    dry_run: Literal[True] = True
    judge_mode: Literal["rule", "llm"]
    generated_on: str
    summary: ImpactSummary
    changes: list[ChangeView]
    answers: list[AnswerImpact]
    cells: list[CellImpact]
    notes: list[str] = Field(default_factory=list)


class _ReadOnlyAnswers:
    """`find_by_article` 하나만 열어 둔다. save 등 다른 이름은 속성 자체가 없다."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        return [dict(r) for r in self._inner.find_by_article(rule_seq, article)]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "")}


def _cell_rows(table: Any) -> list[dict]:
    cells = table.cells if hasattr(table, "cells") else table.get("cells")
    return [c if isinstance(c, dict) else getattr(c, "model_dump", lambda: {})() for c in (cells or [])]


def table_impacts(ch: ChangedArticle, old: str, new: str, tables: list) -> list[CellImpact]:
    out: list[CellImpact] = []
    o_set, n_set = _tokens(old), _tokens(new)
    for t in tables:
        seq = t.rule_seq if hasattr(t, "rule_seq") else t.get("rule_seq")
        if int(seq) != ch.rule_seq:
            continue
        tid = t.table_id if hasattr(t, "table_id") else t.get("table_id")
        for i, cell in enumerate(_cell_rows(t)):
            roles = [*(cell.get("approvers") or []), *(cell.get("financial_approvers") or [])]
            words = _tokens(" ".join([*roles, str(cell.get("band") or "")]))
            base = {"table_id": str(tid), "rule_seq": ch.rule_seq, "cell_index": i, "category": str(cell.get("category") or ""),
                    "band": str(cell.get("band") or ""), "approvers": ", ".join(roles)}
            if not o_set and not n_set:
                out.append(CellImpact(**base, confidence="unverified", reason="섹션 원문을 찾지 못해 칸 단위로 가릴 수 없습니다."))
                continue
            if not words:
                continue
            before, after = len(words & o_set) / len(words), len(words & n_set) / len(words)
            if before >= 0.6 and after < before:
                out.append(CellImpact(**base, confidence="text-match",
                                      reason=f"칸의 승인자·금액 구간 글자가 개정 전 섹션에 {before:.0%}, 개정 뒤에 {after:.0%} 있습니다."))
    return out


def preview_impact(changes: list[ChangedArticle], *, answers: Any, read_section: Any = None,
                   texts: Mapping[tuple[int, str], tuple[str, str]] | None = None, tables: list | None = None, judge: Any = None,
                   llm: Any = None, today: str | None = None) -> ImpactReport:
    """드라이런 영향 계산. 저장·알림·웹훅에 닿는 인자가 없다."""
    ro = _ReadOnlyAnswers(answers)
    judge_ = judge if judge is not None else default_judge(llm)
    floor = min_confidence_from_env()
    views, rows_out, cells_out, notes = [], [], [], []
    seen_answers: set[str] = set()
    for ch in changes:
        old, new = (texts or {}).get((ch.rule_seq, ch.article), (None, None))
        if old is None and new is None and read_section is not None:
            o = read_section(ch.rule_seq, ch.article, ch.old_version_date) if ch.change_type != "added" and ch.old_version_date else None
            n = read_section(ch.rule_seq, ch.article, ch.new_version_date) if ch.change_type != "removed" and ch.new_version_date else None
            old, new = (o or {}).get("text"), (n or {}).get("text")
        old = "" if ch.change_type == "added" else (old or "")
        new = "" if ch.change_type == "removed" else (new or "")
        view = ChangeView(**ch.model_dump())
        affected, ids = [], set()
        for r in ro.find_by_article(ch.rule_seq, ch.article):
            if r["answer_id"] not in ids and is_affected(r, ch):
                ids.add(r["answer_id"])
                affected.append(r)
        for r in affected:
            v = judge_.judge(r, ch, old, new)
            conf = v.get("confidence")
            verdict: Verdict = ("needs_review" if v["judge_failed"] or (v["conclusion_changed"] and conf is not None and conf < floor)
                                else "changed" if v["conclusion_changed"] else "unchanged")
            rows_out.append(AnswerImpact(answer_id=r["answer_id"], user_id=r["user_id"], question_excerpt=_excerpt(r.get("question")),
                                         answer_as_of=r.get("as_of"), rule_seq=ch.rule_seq, article=ch.article, cited_version_id=r.get("version_id"),
                                         change_type=ch.change_type, verdict=verdict, verdict_note=v["explanation"], confidence=conf))
            seen_answers.add(r["answer_id"])
        view.answers_affected = len(affected)
        view.answers_invalidated = sum(1 for a in rows_out[-len(affected):] if a.verdict != "unchanged") if affected else 0
        cells = table_impacts(ch, old, new, tables or [])
        view.decision_cells = sum(1 for c in cells if c.confidence == "text-match")
        cells_out += cells
        views.append(view)
    invalid = [a for a in rows_out if a.verdict != "unchanged"]
    by_type = {k: sum(1 for c in changes if c.change_type == k) for k in ("added", "removed", "modified")}
    if not rows_out:
        notes.append("바뀐 섹션을 인용한 과거 답이 없습니다(답 저장소가 비어 있으면 0건으로 나옵니다).")
    if getattr(judge_, "mode", "") == "rule":
        notes.append("규칙 판정(키 없음)이라 결론 변화는 사람이 확인해야 합니다.")
    summary = ImpactSummary(
        changes=len(changes), changes_by_type=by_type, answers_checked=len(seen_answers),
        answers_invalidated=len({a.answer_id for a in invalid}), answers_needs_review=sum(1 for a in rows_out if a.verdict == "needs_review"),
        answers_unchanged=sum(1 for a in rows_out if a.verdict == "unchanged"),
        decision_tables=len({c.table_id for c in cells_out if c.confidence == "text-match"}),
        decision_cells=sum(1 for c in cells_out if c.confidence == "text-match"),
        decision_cells_unverified=sum(1 for c in cells_out if c.confidence == "unverified"),
        recipients=len({a.user_id for a in invalid}),
    )
    return ImpactReport(judge_mode="rule" if getattr(judge_, "mode", "") == "rule" else "llm", generated_on=today or date.today().isoformat(),
                        summary=summary, changes=views, answers=rows_out, cells=cells_out, notes=notes)


def _excerpt(text: str | None, n: int = EXCERPT) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: ImpactReport, *, max_rows: int = 15) -> str:
    """MR 댓글용 한국어 요약. 사용자 id는 싣지 않는다(JSON에만 있다)."""
    s = report.summary
    ko = {"changed": "결론이 바뀜", "unchanged": "그대로", "needs_review": "확인 필요"}
    lines = ["### 변경 전 영향 미리보기 (드라이런)", "",
             f"- 바뀐 섹션 **{s.changes}개** (수정 {s.changes_by_type['modified']}, 추가 {s.changes_by_type['added']}, 삭제 {s.changes_by_type['removed']})",
             f"- 무효가 될 수 있는 과거 답 **{s.answers_invalidated}건** (확인 필요 {s.answers_needs_review}건, 그대로 {s.answers_unchanged}건, 검사한 답 {s.answers_checked}건)",
             f"- 달라질 결정표 칸 **{s.decision_cells}개** (표 {s.decision_tables}개, 칸 단위로 가리지 못한 칸 {s.decision_cells_unverified}개)",
             f"- 알림 받을 사람 **{s.recipients}명**", "",
             "| 섹션 | 변경 | 인용한 답 | 무효 후보 | 결정표 칸 |", "|---|---|---|---|---|"]
    lines += [f"| {_cell(c.article)} | {c.change_type} | {c.answers_affected} | {c.answers_invalidated} | {c.decision_cells} |" for c in report.changes[:max_rows]]
    bad = [a for a in report.answers if a.verdict != "unchanged"]
    if bad:
        lines += ["", "| 질문 | 섹션 | 판정 | 설명 |", "|---|---|---|---|"]
        lines += [f"| {_cell(a.question_excerpt)} | {_cell(a.article)} | {ko[a.verdict]} | {_cell(_excerpt(a.verdict_note, 120))} |" for a in bad[:max_rows]]
    lines += [""] + [f"> {n}" for n in report.notes] + ["", ATTRIBUTION]
    return "\n".join(lines)


def changes_from_pages(pages: list[dict], *, old_date: str, new_date: str) -> tuple[list[ChangedArticle], dict]:
    """[{path, old, new}] -> (바뀐 섹션, 개정 전후 본문). 수집과 같은 섹션 비교를 쓴다(서식만 바뀐 섹션은 뺀다)."""
    from backend.rag.ingest.snapshot_diff import diff_snapshots

    old = {p["path"]: p["old"] for p in pages if p.get("old") is not None}
    new = {p["path"]: p["new"] for p in pages if p.get("new") is not None}
    res = diff_snapshots(old, new, old_date=old_date, new_date=new_date)
    return res.articles, res.texts


class _FileAnswers:
    """명령줄 `--answers`: [{answer_id, user_id, question, answer, as_of, citations: [{rule_seq, article, version_id, version_date}]}]."""

    def __init__(self, items: list[dict]) -> None:
        self.items = items

    def find_by_article(self, rule_seq: int, article: str) -> list[dict]:
        out = []
        for a in self.items:
            for c in a.get("citations") or []:
                if int(c["rule_seq"]) == rule_seq and c.get("article") == article:
                    out.append({**{k: a.get(k) for k in ("answer_id", "user_id", "question", "answer", "as_of")},
                                "version_id": c.get("version_id"), "version_date": c.get("version_date")})
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.graph.recall.impact", description="변경 전 영향 미리보기(드라이런)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--changes", type=Path, help="바뀐 섹션 JSON(목록 또는 {\"changes\": [...]})")
    src.add_argument("--snapshot", nargs=2, type=Path, metavar=("OLD", "NEW"), help="두 시점 묶음(폴더 또는 JSONL)")
    ap.add_argument("--old-date")
    ap.add_argument("--new-date")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--answers", type=Path, help="답 JSON 파일(없으면 RECALL_STORE에 따른 답 저장소)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    a = ap.parse_args(argv)
    texts: dict = {}
    if a.changes:
        data = json.loads(a.changes.read_text(encoding="utf-8"))
        items = data.get("changes", []) if isinstance(data, dict) else data
        changes = [ChangedArticle.model_validate({k: v for k, v in it.items() if k in ChangedArticle.model_fields}) for it in items]
        texts = {(c.rule_seq, c.article): (it.get("old_text"), it.get("new_text")) for c, it in zip(changes, items) if "old_text" in it or "new_text" in it}
    else:
        if not (a.old_date and a.new_date):
            ap.error("--snapshot에는 --old-date, --new-date가 필요하다")
        from backend.rag.ingest.snapshot_diff import diff_snapshots, read_snapshot

        res = diff_snapshots(read_snapshot(a.snapshot[0], a.prefix), read_snapshot(a.snapshot[1], a.prefix), old_date=a.old_date, new_date=a.new_date)
        changes, texts = res.articles, res.texts
    from backend.graph.recall.runtime import make_answer_store, section_reader

    answers = _FileAnswers(json.loads(a.answers.read_text(encoding="utf-8"))) if a.answers else make_answer_store()
    report = preview_impact(changes, answers=answers, read_section=section_reader(), texts=texts)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(report.model_dump_json(indent=1) if a.format == "json" else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
