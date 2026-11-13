"""청킹 (docs/specs/chunk.md AC). 작은 예시로 돈다."""
import json
from collections import Counter

import pytest

from backend.rag.ingest import chunk as C
from backend.rag.ingest import load as L
from backend.rag.ingest.handbook import AUTHZ_COMMIT
from backend.schemas.chunk import Chunk

PAGE = {"rule_seq": 7, "org": "infra", "title": "Incident Management", "version_id": "129243bcffcf",
        "version_date": "2026-10-27", "version_date_before": False, "fetched_at": "2026-10-29", "source_url": "https://handbook.gitlab.com/x/"}


def el(n, text, path=("Severities",), kind="paragraph", **kw):
    return {"element_id": f"7-{n:04d}", "rule_seq": 7, "kind": kind, "text": text, "heading_path": list(path), "review": None,
            "line_start": n + 1, "line_end": n + 1, **kw}


def run(els, size=800, overlap=120, header=True):
    return C.chunk_structure(PAGE, els, size, overlap, header, "t")


# AC-01 · 절을 넘지 않음
def test_chunks_do_not_cross_sections():
    chunks = run([el(1, "a" * 100, ("A",)), el(2, "b" * 100, ("B",))])
    assert [c["article"] for c in chunks] == ["A", "B"]
    assert [c["element_ids"] for c in chunks] == [["7-0001"], ["7-0002"]]


# AC-02 · 요소를 자르지 않음
def test_elements_packed_not_split():
    chunks = run([el(i, chr(97 + i) * 300) for i in range(3)], overlap=0)
    assert [c["body_chars"] for c in chunks] == [601, 300]          # 300 + 줄바꿈 + 300, 그다음 300
    assert chunks[0]["element_ids"] == ["7-0000", "7-0001"]


def test_long_element_split_rejoins_exactly():
    text = "\n".join(f"Sentence number {i} is here. Another one follows." for i in range(40))
    pieces = C.split_long(text, 200)
    assert "".join(pieces) == text and max(map(len, pieces)) <= 200
    chunks = run([el(1, text)], size=200, overlap=0)
    assert len(chunks) == len(pieces) and C.covered([el(1, text)], chunks) == []
    code = el(10, text, kind="code")                                  # 원본: 10번째 줄 = 펜스, 그다음부터 코드
    code_chunks = run([code], size=200, overlap=0)
    assert code_chunks[0]["line_start"] == 12
    assert code_chunks[1]["line_start"] == 12 + pieces[0].count("\n")  # 조각마다 자기 줄 범위


# AC-03 · G3는 겹침과 무관
def test_g3_count_independent_of_overlap():
    els = [el(i, f"Rule {i}: " + "word " * 60) for i in range(10)]
    with_ov, no_ov = run(els, overlap=120), run(els, overlap=0)
    assert {c["body_sha256"] for c in with_ov} == {c["body_sha256"] for c in no_ov}
    assert with_ov[1]["overlap_chars"] > 0 and with_ov[1]["text"] != no_ov[1]["text"]


def test_overlap_only_within_section_and_on_word_boundary():
    chunks = run([el(1, "x" * 700), el(2, "alpha beta gamma " * 10), el(3, "z" * 100, ("Other",))])
    assert chunks[0]["overlap_chars"] == 0 and chunks[2]["overlap_chars"] == 0   # 절의 첫 청크는 겹침 없음
    assert C.overlap_tail("one two three four", 9) == "four"                     # 단어 중간에서 시작하지 않음


# AC-04 · 머리말은 임베딩 글자에만
def test_header_in_text_not_in_body_hash():
    chunk = run([el(1, "S1 is the highest.", ("Incident Management", "Severities"))])[0]
    assert chunk["text"] == "Incident Management > Severities\nS1 is the highest."      # 페이지 제목 = 첫 제목이면 한 번만
    assert chunk["body_sha256"] == "057013fc27c702c6657bf2747ef31ff22982d31bf109abbb712dea8592bf5c73"   # 머리말 없는 본문의 sha256
    assert run([el(1, "S1 is the highest.")], header=False)[0]["text"] == "S1 is the highest."


# AC-04 · 첫 제목이 페이지 제목과 같으면 머리말에 한 번만
def test_header_when_article_equals_page_title():
    chunk = run([el(1, "intro", ("Incident Management",))])[0]
    assert chunk["header"] == "Incident Management" and chunk["text"] == "Incident Management\nintro"


# AC-06 · 판 날짜 "이전" 표시를 청크까지 넘김 (조장 PR #18 리뷰, 계약 Chunk.version_date_before)
def test_version_date_before_reaches_every_chunk():
    els = [el(1, "a" * 100, ("A",)), el(2, "b" * 100, ("B",))]
    for before in (True, False):
        page = dict(PAGE, version_date_before=before)
        chunks = (C.chunk_structure(page, els, 800, 120, True, "t") + C.chunk_fixed(page, els, 800, 100, "t"))
        assert chunks and all(c["version_date_before"] is before for c in chunks)


def test_missing_version_date_before_fails_loudly():
    page = {k: v for k, v in PAGE.items() if k != "version_date_before"}
    with pytest.raises(KeyError, match="version_date_before"):
        C.chunk_structure(page, [el(1, "a" * 100)], 800, 120, True, "t")


# AC-05 · 빠짐없음 + 제목·검토 대기 제외
def test_headings_and_review_excluded_and_rest_covered():
    els = [el(0, "Severities", kind="heading", level=2), el(1, "body"), el(2, "bad", review="cell_count"),
           el(3, "Deep", kind="heading", level=5)]
    chunks = run(els)
    assert chunks[0]["_body"] == "body\nDeep"                       # 5단계 제목은 본문 글자로
    assert C.covered(els, chunks) == []
    assert C.covered(els + [el(9, "never chunked")], chunks) == ["7-0009"]
    chunks[0]["_body"] = "Deep"                                       # 요소 번호는 있는데 글자가 빠진 청크
    assert C.covered(els, chunks) == ["7-0001"]


# AC-02 · 담는 경계: 800자까지는 한 청크, 하나라도 넘으면 새 청크 (요소 사이 줄바꿈 1자 포함)
def test_pack_boundary_counts_the_joining_newline():
    fits = run([el(1, "a" * 400), el(2, "b" * 399)], overlap=0)
    assert [c["body_chars"] for c in fits] == [800]
    spills = run([el(1, "a" * 400), el(2, "b" * 400)], overlap=0)
    assert [c["body_chars"] for c in spills] == [400, 400]


# AC-02 · 긴 요소 쪼개기: 줄 → 문장 → 글자 순
def test_split_long_falls_back_from_sentences_to_characters():
    assert C.split_long("Aaa bbb. Ccc ddd. Eee fff.", 12) == ["Aaa bbb. ", "Ccc ddd. ", "Eee fff."]
    assert C.split_long("x" * 30, 12) == ["x" * 12, "x" * 12, "x" * 6]


# AC-03 · 겹침: 앞 청크 끝에서 단어 경계로만 가져온다
def test_overlap_tail_edges():
    assert C.overlap_tail("one two", 3) == "two"                  # 자르는 자리가 마침 단어 경계
    assert C.overlap_tail("one twothree", 5) == ""                # 단어 한가운데면 시작하지 않음
    assert C.overlap_tail("abc", 0) == "" and C.overlap_tail("", 5) == ""


# 같은 쪽에 같은 본문이 두 번 있어도 chunk_id 는 다르다 (실데이터 75쪽에서 발생)
def test_same_body_twice_in_one_page_gets_different_chunk_ids():
    chunks = run([el(1, "Same text here.", ("A",)), el(2, "Same text here.", ("B",))])
    assert len({c["body_sha256"] for c in chunks}) == 1
    assert len({c["chunk_id"] for c in chunks}) == 2


# AC-05 · 제목 단계: 4단계까지는 머리말, 5단계부터는 본문 글자
def test_heading_level_4_is_header_and_level_5_is_body():
    els = [el(0, "H4", kind="heading", level=4), el(1, "H5", kind="heading", level=5), el(2, "body")]
    chunks = run(els)
    assert chunks[0]["_body"] == "H5\nbody"
    assert C.covered(els, chunks) == []


# 기준선(고정 길이): 본문은 겹침을 빼고 이어 붙이면 원래 글자와 같고, 검토 대기는 빠진다
def test_fixed_bodies_rejoin_and_skip_review():
    els = [el(1, "a" * 50), el(2, "R" * 50, review="cell_count"), el(3, "c" * 50), el(4, "d" * 50)]
    chunks = C.chunk_fixed(PAGE, els, 100, 20, "t")
    assert "".join(c["_body"] for c in chunks) == "\n".join(["a" * 50, "c" * 50, "d" * 50])
    assert [c["overlap_chars"] for c in chunks][0] == 0 and all(c["overlap_chars"] == 20 for c in chunks[1:])
    assert not any("R" in c["text"] for c in chunks)


# 계약: 청크 기록이 팀 Chunk 모델에 들어가고, text_sha256 은 머리말·겹침을 뺀 본문 해시
def test_chunk_record_fits_team_contract():
    chunks = run([el(1, "word " * 140), el(2, "alpha beta gamma " * 10)])
    assert chunks[1]["overlap_chars"] > 0
    for c in chunks:
        model = Chunk(**c)
        assert model.text_sha256 == C.sha(c["_body"]) == c["body_sha256"]
        assert model.text_sha256 != C.sha(c["text"])               # 머리말·겹침이 들어간 text 의 해시가 아님


# ---- 권한표·run·manifest: 작은 가짜 파일로 끝까지 ----
def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def cell(category, band, role, value, line, notes=(), category_notes=(1,)):
    return {"category": category, "category_notes": list(category_notes), "band": band, "band_lo": 0.0, "band_hi": 25000.0,
            "role": role, "approval_type": "functional", "value": value, "notes": list(notes), "line": line,
            "comment_alias": None}


def make_corpus(tmp_path):
    corpus, parsed = tmp_path / "corpus", tmp_path / "parsed"
    (corpus / "history").mkdir(parents=True)
    (corpus / "authz").mkdir()
    parsed.mkdir()
    page = {"org": "infra", "source_url": "https://handbook.gitlab.com/x/", "version_id": "129243bcffcf",
            "fetched_at": "2026-10-29", "redirect_to": None}
    write_jsonl(corpus / "pages.jsonl", [
        dict(page, rule_seq=7, path="content/handbook/a.md", title="Incident Management", chars=300,
             version_date="2023-12-01", version_date_before=True),
        dict(page, rule_seq=8, path="content/handbook/b.md", title="Moved", chars=40, redirect_to="/x/",
             version_date="2026-10-01", version_date_before=False),
        dict(page, rule_seq=9, path="content/handbook/c.md", title="Empty", chars=30,
             version_date="2026-10-01", version_date_before=False)])
    write_jsonl(parsed / "document_ir.jsonl", [el(1, "First paragraph.", ("Severities",)), el(2, "Second paragraph.", ("Other",))])
    write_jsonl(parsed / "authz_cells.jsonl", [
        cell("Approving expense", ">$0K to $25K", "Manager", "Approves", 5, notes=(2,)),
        cell("Approving expense", ">$0K to $25K", "Director", "", 6),
        cell("Approving expense", ">$25K up to $50K", "Manager", "", 8),
        cell("Legal Contracts", ">$0K to $25K", "CLO", "Approves", 10, category_notes=())])
    write_jsonl(parsed / "authz_board.jsonl", [
        {"item": "", "approval": "Board", "links": [], "line": 20, "private_reference": False},
        {"item": "Letters of Credit", "approval": ">$5M - BOD approval required", "links": [], "line": 22,
         "private_reference": False}])
    write_jsonl(parsed / "authz_notes.jsonl", [{"note": 1, "text": "Delegation up to [90 days](http://x) is permitted."},
                                              {"note": 2, "text": "If not included in Company Plan."}])
    write_jsonl(parsed / "authz_ir.jsonl", [dict(el(1, "Policy text.", ("Policy Scope",)), rule_seq=99, element_id="99-0001")])
    write_jsonl(corpus / "history/authz_commits.jsonl", [{"sha": AUTHZ_COMMIT, "date": "2023-05-11"}])
    (corpus / "collect_manifest.json").write_text(json.dumps(
        {"collected_at": "2026-10-31", "authz": {"source_url": "https://gitlab.com/x", "commit": AUTHZ_COMMIT}}), encoding="utf-8")
    (corpus / "authz/authorization-matrix-2023-05.html.md").write_text("x" * 100, encoding="utf-8")
    return corpus, parsed


# AC-07 · 권한표: 업무 × 금액 구간 한 행 = 청크, 각주 본문 포함, 이사회 열 제목은 항목이 아님
def test_authz_rows_notes_and_board(tmp_path):
    corpus, parsed = make_corpus(tmp_path)
    chunks, missing, skipped = C.authz_chunks(parsed, corpus, "structure", 800, 120, True, "t")
    assert missing == [] and skipped == 1
    rows = [c for c in chunks if c["config"] == "authz-row"]
    assert [c["article"] for c in rows] == ["Approving expense > >$0K to $25K", "Approving expense > >$25K up to $50K",
                                          "Legal Contracts > >$0K to $25K"]                      # 업무가 다르면 구간이 같아도 따로
    first, second, third = rows
    assert "- Manager (functional approval): Approves (2)" in first["_body"] and "Director" not in first["_body"]
    assert "(1) Delegation up to 90 days is permitted." in first["_body"] and "(2) If not included" in first["_body"]
    assert "(2)" not in second["_body"] and "- no approver listed" in second["_body"]             # 각주 2는 이 행 것이 아님
    assert "(1)" not in third["_body"]
    assert first["source_url"].endswith("#L5-6") and (first["line_start"], first["line_end"]) == (5, 6)
    board = [c for c in chunks if c["config"] == "authz-board"]
    assert [c["_body"] for c in board] == ["Letters of Credit: >$5M - BOD approval required"]
    assert board[0]["source_url"].endswith("#L22") and (board[0]["line_start"], board[0]["line_end"]) == (22, 23)
    assert all(c["version_date_before"] is False and c["version_date"] == "2023-05-11" for c in chunks)
    assert [c["_body"] for c in chunks if c["config"] == "t"] == ["Policy text."]                 # 표 밖 글


def test_authz_board_row_without_item_but_not_a_header_stops(tmp_path):
    corpus, parsed = make_corpus(tmp_path)
    write_jsonl(parsed / "authz_board.jsonl", [{"item": "", "approval": "Approves", "links": [], "line": 20,
                                                "private_reference": False}])
    with pytest.raises(ValueError, match="항목 없는 행"):
        C.authz_chunks(parsed, corpus, "structure", 800, 120, True, "t")


# run() 끝까지: 쪽의 판 날짜 "이전" 표시가 파일에 쓰인 청크까지 가고, 보고서·manifest 숫자가 서로 맞는다
def test_run_and_manifest_end_to_end(tmp_path):
    corpus, parsed = make_corpus(tmp_path)
    out, data = tmp_path / "chunks", tmp_path / "data"
    data.mkdir()
    report = C.run(parsed, corpus, out, "structure", 800, 120, True)
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open(encoding="utf-8")]
    assert report["chunks"] == len(chunks) == 2 + 1 + 3 + 1 and report["skipped_board_header"] == 1
    assert report["missing_elements"] == 0 and report["by_kind"] == {"article": 3, "row": 4}
    assert {c["version_date_before"] for c in chunks if c["rule_seq"] == 7} == {True}
    assert {c["version_date_before"] for c in chunks if c["config"].startswith("authz")} == {False}
    result = L.build_manifest(corpus, out, data)
    assert result["chunks"] == len(chunks) and result["docs"] == 4                              # 쪽 3 + 권한표
    assert result["skipped"] == Counter({"redirect": 1, "no_body": 1})
    rows = {r["doc_id"]: r for r in map(json.loads, (data / "manifest.jsonl").open(encoding="utf-8"))}
    assert rows[7]["chunks"] == 2 and rows[7]["chars_kept"] == len("First paragraph.") + len("Second paragraph.")
    assert rows[8]["skipped"] == "redirect" and rows[9]["skipped"] == "no_body"


# ---- 2026-11-13 청크 결함 3가지 수정: 쪼갤 때 낱말·숫자 보존, 표 행 겹침은 행 처음부터 ----
def tokens_whole(text, pieces):
    """조각 경계 양쪽이 모두 공백이 아닌 곳(= 낱말·숫자 한가운데)이 없다."""
    pos = 0
    for p in pieces[:-1]:
        pos += len(p)
        assert text[pos - 1].isspace() or text[pos].isspace(), (text[max(pos - 8, 0):pos], text[pos:pos + 8])


def test_split_long_never_cuts_inside_a_number_or_word():
    # metrics.md의 이슈 번호 목록처럼 문장 부호 없이 800자를 넘는 글(결함 1: 1174, → 117 / 4,)
    text = "Issues: " + " ".join(f"#{n}," for n in range(1000, 1300))
    pieces = C.split_long(text, 100)
    assert len(pieces) > 1 and "".join(pieces) == text and max(map(len, pieces)) <= 100
    tokens_whole(text, pieces)
    assert all(not p.startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ",")) for p in pieces)   # 숫자 한가운데서 시작하지 않음
    lines = "word " * 40
    tokens_whole(lines, C.split_long(lines, 33))                    # 낱말도 마찬가지


def test_split_long_prefers_table_cell_boundary():
    row = " | ".join(f"Column {i}: " + "value " * 9 for i in range(8))
    pieces = C.split_long(row, 150)
    assert "".join(pieces) == row and len(pieces) > 1
    assert all(p.endswith(" | ") for p in pieces[:-1])             # 칸 경계(| 뒤)에서 자른다
    assert all(p.startswith("Column ") for p in pieces)


def test_split_long_token_without_spaces_cuts_at_delimiters_then_characters():
    token = "||".join(f"file[x]:app/{n}/models" for n in range(60))
    pieces = C.split_long(token, 120)
    assert "".join(pieces) == token and max(map(len, pieces)) <= 120
    assert all(p.endswith("|") for p in pieces[:-1])                # 구분 글자 뒤에서
    assert C.split_long("x" * 30, 12) == ["x" * 12, "x" * 12, "x" * 6]    # 정말 아무 경계도 없으면 글자 단위(기존 동작)
    digits = "ab 1234567890 cd"                                     # 공백 자리에서만 자른다(숫자 덩어리를 반으로 안 가른다)
    assert C.split_long(digits, 12) == ["ab ", "1234567890 ", "cd"]


def tail_of(chunk):
    """청크 글에서 머리말 줄 다음의 겹침 글(overlap_chars 만큼)."""
    return chunk["text"][len(chunk["header"]) + 1:][:chunk["overlap_chars"]]


def row_el(n, label, rest, **kw):
    """표 행 요소. text 는 parse.row_text 모양(`열 이름: 값 | 열 이름: 값`)."""
    cells = [label, rest]
    header = ["Label", "When it's used"]
    text = " | ".join(f"{h}: {v}" for h, v in zip(header, cells))
    return el(n, text, kind="table_row", header=header, cells=cells, **kw)


# 결함 3: 겹침이 표 행 중간에서 시작하면 첫 칸(라벨)이 빠진다
def test_overlap_starting_inside_table_row_takes_the_whole_row():
    rows = [row_el(1, "bt-infra::access-request", "Applied to all access requests that we are responsible for provisioning " * 2),
            row_el(2, "bt-infra::other", "Something else entirely " * 4)]
    old_tail = C.overlap_tail(rows[0]["text"], 120)
    assert not old_tail.startswith("Label:")                                 # 이전 방식: 라벨이 잘렸다
    chunks = run(rows, size=len(rows[0]["text"]) + 5, overlap=120)
    assert len(chunks) == 2
    assert tail_of(chunks[1]) == rows[0]["text"].rstrip()                # 행 전체(라벨 포함)를 가져옴
    assert chunks[1]["overlap_chars"] == len(rows[0]["text"].rstrip())
    assert chunks[1]["body_sha256"] == C.sha(rows[1]["text"]) and chunks[1]["chunk_id"] == run(rows, size=len(rows[0]["text"]) + 5, overlap=0)[1]["chunk_id"]   # 본문·id는 그대로


def test_overlap_in_long_table_row_gets_first_cell_label():
    long_row = row_el(1, "bt-infra::access-request", "Applied to all access requests, " * 20)
    assert len(long_row["text"]) > C.ROW_TAIL_MAX
    chunks = run([long_row, row_el(2, "next", "x y z " * 40)], size=len(long_row["text"]) + 5, overlap=120)
    tail = tail_of(chunks[1])
    assert tail == "Label: bt-infra::access-request | " + C.overlap_tail(long_row["text"], 120)    # 라벨 + 평소 겹침
    assert len(tail) < 200


def test_overlap_in_second_piece_of_split_row_gets_label():
    # 행이 800자를 넘어 쪼개지면 뒤 조각에는 행 처음이 없으니 라벨을 붙인다
    big = row_el(1, "bt-infra::access-request", "Applied to all access requests we handle. " * 12)
    chunks = run([big, row_el(2, "last", "q w e " * 30)], size=200, overlap=60)
    pieces = C.split_long(big["text"], 200)
    assert len(pieces) >= 3
    assert chunks[0]["overlap_chars"] == 0                                   # 첫 조각
    assert tail_of(chunks[1]).startswith("Label: bt-infra::access-request | ")    # 둘째 조각 앞 겹침(첫 조각 끝)
    assert chunks[1]["body_sha256"] == C.sha(pieces[1])


def test_overlap_from_non_table_elements_is_unchanged():
    paras = [el(1, "alpha beta gamma delta " * 12), el(2, "epsilon zeta eta " * 12)]
    chunks = run(paras, size=len(paras[0]["text"]) + 5, overlap=120)
    assert tail_of(chunks[1]) == C.overlap_tail(paras[0]["text"], 120)    # 표 아님 = 평소 겹침
    code = [el(1, "line one\n" * 30, kind="code"), el(2, "zzz yyy", kind="paragraph")]
    for kind_els in (code, [el(1, "item " * 30, kind="list_item"), el(2, "y " * 20)]):
        out = run(kind_els, size=len(kind_els[0]["text"]) + 3, overlap=120)
        assert tail_of(out[1]) == C.overlap_tail(kind_els[0]["text"], 120)


def test_overlap_starting_exactly_at_row_start_is_unchanged():
    row = row_el(2, "label", "tiny")
    first = el(1, "p " * 10)
    chunks = run([first, row], size=len(first["text"]) + 3, overlap=len(row["text"]))
    assert tail_of(chunks[1]) == C.overlap_tail(first["text"], len(row["text"]))
    chunks = run([row_el(1, "a", "b c d " * 6), row_el(2, "z", "y " * 30)], size=60, overlap=10_000)
    assert tail_of(chunks[1]) == chunks[0]["_body"]            # 행 처음부터 = 앞 청크 본문 전체
