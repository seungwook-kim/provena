"""PDF 파싱 (docs/specs/parse.md "PDF" 절 AC). Docling 없이 돈다.
- 번호 조항·부록·쪽 이음·순서 재정렬 시험은 이 파일 안에서 지어낸 합성 Docling JSON(agreement_doc)을 쓴다. 실제 문서의 문장이 아니다.
- 표·머리글·그림 시험은 저장해 둔 Docling JSON 일부(tests/fixtures/docling_pdf_sample.json, 치트시트 일부를 실제 변환 결과에서 잘라 냄)를 쓴다.
제목 규칙을 실제 문서에서 잰 값(재현율·정밀도·수준 순서)은 저장소 밖 시험 자료에 있고, 여기 시험은 규칙의 동작만 합성 입력으로 확인한다."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.rag.ingest import chunk as C
from backend.rag.ingest import parse as MD_PARSE
from backend.rag.ingest import pdf as P
from backend.schemas.chunk import Chunk

SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "docling_pdf_sample.json").read_text(encoding="utf-8"))


class Builder:
    """Docling JSON(dict) 모양의 합성 문서를 만든다. 본문 트리 순서는 add 를 부른 순서(= Docling 읽기 순서)다."""

    def __init__(self):
        self.doc = {"texts": [], "tables": [], "pictures": [], "groups": [], "pages": {}, "body": {"children": []}}

    def text(self, label, text, page, l, t, marker=None, h=18, r=520):
        self.doc["pages"].setdefault(str(page), {})
        obj = {"self_ref": f"#/texts/{len(self.doc['texts'])}", "label": label, "content_layer": "body", "text": text,
               "children": [], "prov": [{"page_no": page, "bbox": {"l": l, "b": t - h, "r": r, "t": t}}]}
        if marker:
            obj["marker"] = marker
        self.doc["texts"].append(obj)
        return {"$ref": obj["self_ref"]}

    def add(self, *refs):
        self.doc["body"]["children"] += refs
        return self

    def group(self, *refs):
        self.doc["groups"].append({"label": "list", "children": list(refs)})
        return {"$ref": f"#/groups/{len(self.doc['groups']) - 1}"}


def agreement_doc():
    """지어낸 '서비스 계약서' 3쪽. 1쪽: 제목, 번호 조항 목록(안쪽 글자 항목 포함), 문장이 쪽 끝에서 끊김. 2쪽: 이어진 글, 번호 달린 소제목.
    3쪽: 부록 제목 둘이 본문 뒤로 밀려 나온 한 단짜리 쪽(Docling 읽기 순서 결함을 흉내 냄)."""
    b = Builder()
    b.add(b.text("title", "Sample Services Agreement", 1, 72, 740, h=24))
    b.add(b.text("text", "This synthetic agreement exists only for tests.", 1, 72, 700))
    b.add(b.group(
        b.text("list_item", "Definitions. The terms below apply to every order.", 1, 72, 660, marker="1."),
        b.text("list_item", "Order. A request for services made under this agreement.", 1, 108, 630, marker="a."),
        b.text("list_item", "Reports. Upon completion the Provider sends a summary.", 1, 108, 600, marker="b."),
        b.text("list_item", "Status of the Parties. This agreement applies when the Provider stores records.", 1, 72, 570, marker="2."),
        b.text("list_item", '"Regulation" means the rules on the protection of persons with regard to the', 1, 108, 540, marker="c.")))
    b.add(b.text("text", "storage of records and on the free movement of such records.", 2, 72, 740))
    b.add(b.text("section_header", "14. Subprocessors. To the extent that the Provider acts as a Processor it may engage others.", 2, 72, 700))
    b.add(b.text("text", "The Customer authorizes the subprocessors listed on the Provider website.", 2, 72, 660))
    b.add(b.text("text", "Page three starts here and is not a continuation.", 3, 72, 520))      # 위쪽 제목보다 먼저 나온다
    b.add(b.group(b.text("list_item", "ALPHA", 3, 72, 620, marker="1.")))
    b.add(b.text("text", "These terms apply to the alpha region.", 3, 72, 590))
    b.add(b.group(b.text("list_item", "BETA", 3, 72, 540, marker="2.")))
    b.add(b.text("section_header", "EXHIBIT C", 3, 220, 720))
    b.add(b.text("section_header", "Region Specific Terms", 3, 180, 690))
    return b.doc


@pytest.fixture(scope="module")
def agreement():
    return P.build_ir(agreement_doc(), 111, "docs")


@pytest.fixture(scope="module")
def cheat():
    return P.build_ir(SAMPLE["cheat"], 222, "press")


def heads(els):
    return [(e["level"], e["text"]) for e in els if e["kind"] == "heading"]


# AC-PDF-01 · 제목 모양 구절 판별
@pytest.mark.parametrize("text,expect", [
    ("Status of the Parties. This agreement applies when the Provider stores records", ("Status of the Parties", "This agreement applies when the Provider stores records")),
    ("Audit.", ("Audit", "")),
    ("ALPHA", ("ALPHA", "")),
    ("Service Levels (SLA) and Support Hours. Upon request", ("Service Levels (SLA) and Support Hours", "Upon request")),
    ("The Provider will not disclose any Customer records.", None),                          # 문장(소문자 낱말)
    ("It shall comply with all laws. More.", None),
    ("Controller Obligations:", None),                                                         # 쌍점으로 끝나면 제목 아님
    ("A Very Long Title Of Thirteen Capitalized Words That Never Seems To End Here Now", None),
    ("Acme Inc. Q3 Results", None),                                                          # Inc. 에서 끊지 않는다
])
def test_split_title(text, expect):
    assert P.split_title(text) == expect


# AC-PDF-02 · 번호 조항 목록 항목이 제목이 되고 수준이 붙는다
def test_numbered_clauses_become_headings_with_levels(agreement):
    els, stats = agreement
    h = dict((t, l) for l, t in heads(els))
    assert h["Sample Services Agreement"] == 1
    assert h["1. Definitions"] == 2 and h["2. Status of the Parties"] == 2 and h["14. Subprocessors"] == 2
    assert h["EXHIBIT C"] == 2 and h["Region Specific Terms"] == 3 and h["1. ALPHA"] == 3     # 부록 안은 한 수준 아래
    assert stats["heading_from_list_item"] == 4             # 1. Definitions, 2. Status of the Parties, 1. ALPHA, 2. BETA


def test_heading_text_after_number_is_split_from_body(agreement):
    els, stats = agreement
    i = next(i for i, e in enumerate(els) if e["text"] == "14. Subprocessors")
    assert els[i]["kind"] == "heading" and els[i + 1]["kind"] == "paragraph"
    assert els[i + 1]["text"].startswith("To the extent that the Provider acts as a Processor")
    assert stats["heading_split_from_sentence"] == 1


# AC-PDF-03 · 숫자가 아닌 표지나 안쪽 항목은 제목이 아니다
def test_lettered_items_stay_list_items(agreement):
    els, _ = agreement
    item = next(e for e in els if e["text"].startswith("b. Reports. Upon completion"))
    assert item["kind"] == "list_item"
    assert all(not t.startswith(("a.", "b.", "c.")) for _, t in heads(els))


def mini_doc(items):
    """list 그룹 하나만 있는 작은 Docling dict. items = [(표지, 글, 왼쪽 좌표)]"""
    texts = [{"self_ref": f"#/texts/{i}", "label": "list_item", "content_layer": "body", "marker": m, "text": t, "children": [],
              "prov": [{"page_no": 1, "bbox": {"l": l, "b": 700 - 20 * i, "r": 500, "t": 710 - 20 * i}}]}
             for i, (m, t, l) in enumerate(items)]
    return {"texts": texts, "tables": [], "pictures": [], "pages": {"1": {}},
            "groups": [{"label": "list", "children": [{"$ref": f"#/texts/{i}"} for i in range(len(items))]}],
            "body": {"children": [{"$ref": "#/groups/0"}]}}


def test_nested_numbered_item_is_not_a_clause_heading():
    doc = mini_doc([("1.", "Definitions. The terms below apply.", 72), ("2.", "Nested Title. Inside the first clause.", 108),
                    ("3.", "Audit. Customer may audit.", 72)])
    els, _ = P.build_ir(doc, 5, "legal")
    assert [t for _, t in heads(els)] == ["1. Definitions", "3. Audit"]
    assert next(e for e in els if e["text"].startswith("2. Nested Title"))["kind"] == "list_item"


# AC-PDF-04 · 제목 경로와 부모
def test_heading_path_and_parent(agreement):
    els, _ = agreement
    by_id = {e["element_id"]: e for e in els}
    beta = next(e for e in els if e["text"] == "2. BETA")
    assert beta["heading_path"] == ["Sample Services Agreement", "EXHIBIT C", "2. BETA"]
    assert by_id[beta["parent_id"]]["text"] == "EXHIBIT C"
    first = els[0]
    assert first["kind"] == "heading" and first["parent_id"] is None and first["order"] == 0


# AC-PDF-05 · 쪽 경계에서 끊긴 글을 앞 요소에 잇고 쪽 범위를 남긴다
def test_page_break_continuation_is_merged(agreement):
    els, stats = agreement
    reg = next(e for e in els if e["text"].startswith('c. "Regulation"'))
    assert (reg["page"], reg["page_end"]) == (1, 2)
    assert "storage of records and on the free movement" in reg["text"]
    assert stats["merged_page_break"] == 1                  # 3쪽 첫 글은 앞 쪽이 마침표로 끝나 이어 붙이지 않는다
    assert not any(e["text"].startswith("storage of records and on the free") for e in els)    # 따로 남지 않음


# AC-PDF-06 · 한 단짜리 쪽에서 위로 올라가야 할 제목을 올리고, 다단 쪽은 Docling 순서 그대로
def test_single_column_reorder_and_multi_column_kept(agreement, cheat):
    els, d_stats = agreement
    p3 = [e["text"] for e in els if e["page"] == 3 and e["kind"] == "heading"]
    assert p3 == ["EXHIBIT C", "Region Specific Terms", "1. ALPHA", "2. BETA"]       # Docling 원순서는 EXHIBIT C 가 맨 끝
    assert d_stats["reordered_items"] > 0 and [e["page"] for e in els] == sorted(e["page"] for e in els)
    c_els, c_stats = cheat
    assert c_stats["reordered_items"] == 0
    assert [t for _, t in heads(c_els)][:5] == ["Git Cheat Sheet", "01 Git configuration", "02 Starting a project",
                                                 "03 Day-to-day work", "04 Storing your work"]


def test_reorder_function_leaves_multi_column_and_orders_single():
    def it(name, l, b, r, t):
        return {"page": 1, "page_end": 1, "bbox": [l, b, r, t], "name": name}
    two_col = [it("c1a", 50, 600, 250, 700), it("c1b", 50, 400, 250, 500), it("c2a", 300, 600, 500, 700)]
    keep = list(two_col)
    assert P.reorder_single_column_pages(keep) == 0 and keep == two_col
    one_col = [it("low", 50, 100, 500, 200), it("top", 200, 700, 300, 720)]
    assert P.reorder_single_column_pages(one_col) == 2 and [x["name"] for x in one_col] == ["top", "low"]


# AC-PDF-07 · IR 요소 형식 (docs/specs/parse.md 요소 필드). 줄 번호는 비우고 쪽·좌표를 둔다
def test_ir_fields(agreement, cheat):
    need = {"element_id", "rule_seq", "org", "kind", "heading_path", "parent_id", "order", "line_start", "line_end", "text",
            "links", "review", "page", "page_end", "bbox"}
    for els, _ in (agreement, cheat):
        assert [e["order"] for e in els] == list(range(len(els)))
        assert len({e["element_id"] for e in els}) == len(els)
        for e in els:
            assert need <= set(e) and e["line_start"] is None and e["line_end"] is None and len(e["bbox"]) == 4
            assert e["kind"] in {"heading", "paragraph", "list_item", "table_row", "code"}
            assert (e["kind"] == "heading") == ("level" in e)


def test_page_furniture_numbers_pictures_dropped(cheat):
    els, stats = cheat
    assert stats["dropped_page_furniture"] == 1 and stats["dropped_page_number"] == 1 and stats["dropped_pictures"] == 1
    assert not any(e["text"] in ("1", "2") for e in els)


# AC-PDF-08 · 표는 기존 표 행 형식
def test_table_rows_match_markdown_row_format(cheat):
    els, stats = cheat
    rows = [e for e in els if e["kind"] == "table_row"]
    assert stats["tables"] == 2 and len(rows) == 5
    r = rows[0]
    assert {"table_id", "row", "header", "cells"} <= set(r) and r["header"] == [] and len(r["cells"]) == 2
    assert r["text"] == MD_PARSE.row_text(r["header"], r["cells"]) == " | ".join(r["cells"])
    assert [x["row"] for x in rows if x["table_id"] == r["table_id"]] == [0, 1, 2]
    assert MD_PARSE.row_text(["명령", "설명"], ["a", "b"]) == P.row_text(["명령", "설명"], ["a", "b"]) == "명령: a | 설명: b"


def test_table_header_rows_and_spans():
    table = {"data": {"num_rows": 3, "num_cols": 3, "table_cells": [
        {"start_row_offset_idx": 0, "start_col_offset_idx": 0, "text": "", "column_header": True},
        {"start_row_offset_idx": 0, "start_col_offset_idx": 1, "text": "FY 2026", "column_header": True, "col_span": 2},
        {"start_row_offset_idx": 1, "start_col_offset_idx": 1, "text": "Q3", "column_header": True},
        {"start_row_offset_idx": 1, "start_col_offset_idx": 2, "text": "Q2", "column_header": True},
        {"start_row_offset_idx": 2, "start_col_offset_idx": 0, "text": "Revenue"},
        {"start_row_offset_idx": 2, "start_col_offset_idx": 1, "text": "10"},
        {"start_row_offset_idx": 2, "start_col_offset_idx": 2, "text": "9"}]}}
    header, rows = P.table_rows(table)
    assert header == ["", "FY 2026 Q3", "Q2"] and rows == [["Revenue", "10", "9"]]


# AC-PDF-09 · 청크: chunk.py 규칙 그대로, 쪽은 source_url 의 #page=N, Chunk 계약 통과
def page_for(els, rs, org, title):
    return {"rule_seq": rs, "org": org, "title": title, "version_id": "129243bcffcf", "version_date": "2026-10-27",
            "version_date_before": True, "fetched_at": "2026-11-03", "source_url": "https://handbook.gitlab.com/pdfs/x.pdf"}


def test_pdf_chunks_page_anchor_and_contract(agreement):
    els, _ = agreement
    chunks, missing = P.pdf_chunks(page_for(els, 111, "docs", "Sample Services Agreement"), els)
    assert missing == [] and chunks
    fields = set(Chunk.model_fields)
    for c in chunks:
        Chunk(**{k: v for k, v in c.items() if k in fields})                       # 계약 칸 그대로
        assert c["line_start"] is None and c["line_end"] is None
        assert c["source_url"] == f"https://handbook.gitlab.com/pdfs/x.pdf#page={c['pages'][0]}"
        assert c["body_chars"] <= 800 and c["config"] == "structure-s800-o120-h"
    reg = next(c for c in chunks if 'c. "Regulation"' in c["text"])
    assert reg["pages"] == [1, 2]                                                    # 쪽에 걸친 청크는 시작 쪽이 앵커, 전체 쪽은 pages
    assert reg["source_url"].endswith("#page=1")
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)


def test_chunk_header_uses_heading_path(agreement):
    els, _ = agreement
    chunks, _ = P.pdf_chunks(page_for(els, 111, "docs", "Sample Services Agreement"), els)
    beta = next(c for c in chunks if c["article"].endswith("2. BETA"))
    assert beta["article"] == "Sample Services Agreement > EXHIBIT C > 2. BETA"
    assert beta["text"].startswith("Sample Services Agreement > EXHIBIT C > 2. BETA\n")


# AC-PDF-10 · 기존 Markdown 경로는 그대로: 줄 번호가 있으면 min/max, 없으면 None
def test_line_span_markdown_unchanged_and_none_for_pdf():
    els = [{"line_start": 5, "line_end": 7}, {"line_start": 3, "line_end": 9}]
    assert C.line_span(els, "line_start", min) == 3 and C.line_span(els, "line_end", max) == 9
    assert C.line_span([{"line_start": None}], "line_start", min) is None
    assert C.line_span([{"line_start": 4}, {"line_start": None}], "line_start", min) is None


# AC-PDF-11 · 수집: 고정 커밋 원본과 크기·sha256·git blob id 가 모두 같아야 통과
def test_verify_pdf_rejects_other_file():
    data = b"%PDF-1.7 fixed original"
    src = {"path": "static/pdfs/x.pdf", "sha256": P.sha256(data), "git_blob": P.git_blob_id(data), "bytes": len(data)}
    P.verify_pdf(data, src)
    for bad in (data + b" ", data[:-1] + b"X", b"%PDF-1.7 similarly named other file"):
        with pytest.raises(ValueError):
            P.verify_pdf(bad, src)
    with pytest.raises(ValueError):                              # sha256 이 같아도 git blob id 가 다르면 다른 원본으로 본다
        P.verify_pdf(data, dict(src, git_blob="0" * 40))


def test_sources_pin_the_files_to_the_fixed_commit():
    paths = [s["path"] for s in P.SOURCES]
    assert "static/pdfs/press/git-cheat-sheet.pdf" in paths and len(paths) == len(set(paths)) == 7
    assert all(x.startswith("static/pdfs/") and x.endswith(".pdf") for x in paths)
    assert len({Path(x).name for x in paths}) == len(paths)                          # collect 는 파일 이름으로 찾으므로 이름이 겹치면 안 된다
    assert all(len(s["sha256"]) == 64 and len(s["git_blob"]) == 40 and s["bytes"] > 0 for s in P.SOURCES)
    assert P.git_blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"             # git hash-object 의 빈 파일 값
    assert P.PDF_REPO_RAW.endswith("129243bcffcf6cbc8c2e83f537f1836b99900a61/")


# AC-PDF-12 · Docling 은 변환할 때만 가져온다(Docling 없는 환경에서도 이 모듈과 시험이 돈다)
def test_importing_module_does_not_import_docling():
    code = "import sys, backend.rag.ingest.pdf; assert not [m for m in sys.modules if m.startswith('docling')], 'docling'"
    r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
