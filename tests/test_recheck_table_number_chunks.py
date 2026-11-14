"""0원 시험: evals/recheck_table_number_chunks.py (청크 파일 일치 확인, 명령 조립, 핵심 값 추출). 대조 자체는 돌리지 않는다."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("recheck_tnc", Path(__file__).resolve().parents[1] / "evals" / "recheck_table_number_chunks.py")
tnc = importlib.util.module_from_spec(SPEC)
sys.modules["recheck_tnc"] = tnc
SPEC.loader.exec_module(tnc)


def _root(tmp_path, a=b"x\n", b=b"x\n"):
    (tmp_path / "data" / "chunks").mkdir(parents=True)
    (tmp_path / "data" / "index").mkdir(parents=True)
    if a is not None:
        (tmp_path / "data" / "chunks" / "chunks.jsonl").write_bytes(a)
    if b is not None:
        (tmp_path / "data" / "index" / "chunks.jsonl").write_bytes(b)
    return tmp_path


def test_identical_chunk_files_pass(tmp_path):
    assert tnc.chunk_files_problem(_root(tmp_path)) is None


def test_missing_or_different_chunk_files_stop_the_run(tmp_path):
    assert "가 없습니다" in tnc.chunk_files_problem(_root(tmp_path / "a", b=None))
    row = lambda text, vd="2026-06-25": (json.dumps({"chunk_id": "c1", "text": text, "version_date": vd}) + "\n").encode()
    assert "칸이 다릅니다" in tnc.chunk_files_problem(_root(tmp_path / "b", a=row("가"), b=row("나")))
    assert "줄 수가 다릅니다" in tnc.chunk_files_problem(_root(tmp_path / "c", a=row("가") * 2, b=row("가")))


def test_files_that_differ_only_in_version_date_pass_with_a_note(tmp_path):
    row = lambda vd: (json.dumps({"chunk_id": "c1", "text": "가", "version_date": vd}) + "\n").encode()
    notes: list[str] = []
    assert tnc.chunk_files_problem(_root(tmp_path, a=row("2026-06-25"), b=row("2026-06-24")), notes) is None
    assert len(notes) == 1 and "version_date" in notes[0] and "1줄" in notes[0]


def test_main_refuses_an_existing_nonempty_out_folder_and_never_runs_the_checker(tmp_path, monkeypatch):
    root = _root(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "old.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(tnc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert tnc.main(["--root", str(root), "--out", str(out)]) == 2
    assert (out / "old.txt").read_text(encoding="utf-8") == "keep"


def test_command_uses_isolated_python_and_the_given_folders(tmp_path):
    cmd = tnc.build_command(tmp_path, tmp_path / "o")
    assert cmd[1:3] == ["-I", "-B"] and cmd[3].endswith("check_corpus.py") and cmd[cmd.index("--root") + 1] == str(tmp_path) and cmd[cmd.index("--out") + 1] == str(tmp_path / "o")
    assert "--fetch-sample" not in cmd                      # 네트워크를 쓰지 않는다
    assert tnc.CHECKER.is_file()


def test_overlap_classes_tell_tail_label_plus_tail_and_other_apart():
    def c(rule, text, n=0):
        return {"rule_seq": rule, "text": text, "header": "", "overlap_chars": n}

    assert tnc.overlap_classes([c(1, "앞 글 abcdef"), c(1, "전혀 다른 것 본문", 5)]) == {"overlap_tail": 0, "overlap_label_plus_tail": 0, "overlap_other": 1}
    # 라벨+꼬리: 앞 청크가 "... Field: x | 긴 칸 값 끝"으로 끝나고 겹침이 "Field: x | 긴 칸 값 끝"의 라벨 + 꼬리
    prev = c(1, "앞 글\nField: x | y: aaaa bbbb cccc")
    cur = c(1, "Field: x | bbbb cccc 본문", 20)
    got = tnc.overlap_classes([prev, cur])
    assert got == {"overlap_tail": 0, "overlap_label_plus_tail": 1, "overlap_other": 0}
    assert tnc.overlap_classes([c(1, "앞 글 abc"), c(2, "abc 다음", 3)]) == {"overlap_tail": 0, "overlap_label_plus_tail": 0, "overlap_other": 0}   # 쪽이 다르면 세지 않는다
    assert tnc.overlap_classes([c(1, "앞 글 abc"), c(1, "abc 다음", 3)])["overlap_tail"] == 1


def test_key_numbers_read_overlap_values_from_the_summary():
    s = {"total_chunks": 5, "selected": 2, "mismatch": 0, "overlap": {"table_row_mid": 0, "first_cell_missing": 0}}
    k = tnc.key_numbers(s)
    assert k["total_chunks"] == 5 and k["table_row_mid"] == 0 and k["first_cell_missing"] == 0 and k["numbers_mismatch"] is None
