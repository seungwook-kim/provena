"""새 지표 정답 변환·확인(0원, 네트워크·DB 없음). 요청 문서의 작성 예시는 어떤 경우에도 측정 행이 되지 않아야 한다."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from evals.newmetrics.common import AUTHZ_MD, HANDBOOK, GoldError, check_rows
from evals.newmetrics.gold_convert import convert, split_row
from evals.newmetrics.gold_validate import Report, evidence_core, norm_text, strip_tags, validate_decision, validate_link, validate_maintenance

REQUEST_DOC = Path.home() / "Downloads" / "새 지표 정답 세트 작성 요청 (2026-11-16).md"

RECALL_HEAD = ("| id | 커밋 | 결론 바뀜 | 질문 | 지난 답 (개정 전 판 기준) | 개정 전 근거 문장 | 개정 뒤 근거 문장 | 비고 |\n"
               "|---|---|---|---|---|---|---|---|\n")


def _md_example_rows() -> str:
    return (RECALL_HEAD
            + "| X1 | `4667e540` | 예 | 보안 취약점 기밀 이슈는 패치가 나오고 얼마 뒤에 공개로 바꿔? | 30일 | \"a\" | \"b\" | |\n"
            + "| X2 | `4667e540` | 아니오 | 계속 기밀로 둬야 하는 보안 이슈는 어떻게 표시해? | c | \"a\" | \"b\" | |\n"
            + "| R01 | | | | | | | |\n")


def test_split_row_handles_escaped_pipe_and_backticks():
    assert split_row("| a | b \\| c | `x|y` |") == ["a", "b | c", "`x|y`"]


def test_examples_and_empty_rows_never_become_rows():
    out, rep = convert([("x.md", _md_example_rows())])
    assert out["recall"] == []
    assert rep["skipped_examples"] == 2 and rep["skipped_empty"] == 1


@pytest.mark.skipif(not REQUEST_DOC.exists(), reason="요청 문서 없음")
def test_unfilled_request_doc_converts_to_zero_rows():
    out, rep = convert([("req.md", REQUEST_DOC.read_text(encoding="utf-8-sig"))])
    assert all(v == [] for v in out.values()), {k: len(v) for k, v in out.items()}
    assert rep["skipped_examples"] >= 1          # X, X1, X2 예시 행이 버려졌다
    assert not rep["conflicts"]


def test_filled_rows_parse_and_conflicts_stop():
    md = RECALL_HEAD + "| R01 | `0c787db1` | 예 | 질문 하나 | 답 하나 | \"전\" | \"뒤\" | 애매 |\n"
    out, _ = convert([("a.md", md)])
    r = out["recall"][0]
    assert (r["id"], r["expected"], r["ambiguous"], r["commit"]) == ("R01", True, True, "0c787db1")
    md2 = RECALL_HEAD + "| R01 | `0c787db1` | 예 | 다른 질문 | 답 하나 | \"전\" | \"뒤\" | |\n"
    _, rep = convert([("a.md", md), ("b.md", md2)])
    assert rep["conflicts"] and rep["conflicts"][0]["id"] == "R01"


def test_check_rows_rejects_examples_excluded_commit_and_duplicates():
    with pytest.raises(GoldError):
        check_rows("recall", [{"id": "X1"}])
    with pytest.raises(GoldError):
        check_rows("recall", [{"id": "R01", "commit": "4667e540"}])
    with pytest.raises(GoldError):
        check_rows("link", [{"id": "L001"}, {"id": "L001"}])
    with pytest.raises(GoldError):
        check_rows("decision", [{"id": "D41"}])
    check_rows("maintenance", [{"id": "M01"}, {"id": "M60"}])


def test_evidence_normalization_ignores_link_markup_and_quotes():
    assert evidence_core('"see [the policy](/handbook/x/) **now**…"') == "see the policy now"
    assert norm_text("a  `b`\n c") == "a b c"
    assert norm_text("> [!NOTE]\n> The rule") == "[!NOTE] The rule"


# ---------- 위치 확인(실제 코퍼스 파일, 내용은 고치지 않음) ----------

needs_corpus = pytest.mark.skipif(not (AUTHZ_MD.exists() and HANDBOOK.exists()), reason="코퍼스 없음(data/corpus는 저장소에 없음)")


@needs_corpus
def test_validate_decision_band_line():
    from evals.newmetrics.fakes import decision_row

    rep = Report()
    validate_decision([decision_row("D01", 77), decision_row("D02", 77, band="다른 구간"), decision_row("D03", 20)], rep)
    ids = sorted(e["id"] for e in rep.errors)
    assert ids == ["D02", "D03"], rep.errors


def _first_link_line(rel: str) -> tuple[int, str]:
    for i, line in enumerate((HANDBOOK / rel).read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n"), start=1):
        m = re.search(r"\]\((/handbook/[^)\s]+)\)", line)
        if m:
            return i, m.group(1)
    pytest.skip("링크 줄 없음")


@needs_corpus
def test_validate_link_line_has_url():
    rel = "security/policies_and_standards/password-standard.md"
    n, url = _first_link_line(rel)
    ok = {"id": "L001", "author": "박진형", "source_page": rel, "line": n, "line_raw": str(n), "url": url, "target": "코퍼스 밖", "target_raw": "코퍼스 밖", "section": ""}
    bad = {**ok, "id": "L002", "line": n + 1 if n > 1 else n + 2, "url": "/handbook/never-there-xyz/"}
    rep = Report()
    validate_link([ok, bad], rep)
    assert [e["id"] for e in rep.errors] == ["L002"], rep.errors


@needs_corpus
def test_validate_maintenance_slug_on_line():
    hit = None
    for p in sorted(HANDBOOK.rglob("*.md")):
        rel = p.relative_to(HANDBOOK).as_posix()
        if rel == "finance/expenses.md":
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n"), start=1):
            if "finance/expenses" in ln:
                hit = (rel, i)
                break
        if hit:
            break
    if not hit:
        pytest.skip("링크하는 페이지 없음")
    rel, line = hit
    ok = {"id": "M31", "linking_page": rel, "revised_page": "finance/expenses.md", "lines": [int(line)], "needed": True, "needed_raw": "예"}
    bad = {**ok, "id": "M32", "lines": [1], "needed": None, "needed_raw": "모름"}
    rep = Report()
    validate_maintenance([ok, bad], rep)
    assert {e["id"] for e in rep.errors} == {"M32"}
