"""배포본 인용 정답 대조(`evals/latency/deploy_citation_gold.py`)와 인용 청크 id 기록(`deploy_latency.py`) 시험. 가짜 SSE와 가짜 청크만 쓰고 키·네트워크·운영 접속은 없다."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.latency import deploy_citation_gold as cg
from evals.latency import deploy_latency as dl
from evals.retrieval.gold import page_seq, parse_gold


def sse(event: str, data: dict) -> list[str]:
    return [f"event: {event}\r\n", "data: " + json.dumps({"type": event, "thread_id": "t-x", "data": data}) + "\r\n", "\r\n"]


def chunk(cid: str, path: str, article: str, start: int = 1, end: int = 2, version_date: str = "2026-09-01") -> SimpleNamespace:
    return SimpleNamespace(chunk_id=cid, rule_seq=page_seq(path), article=article, line_start=start, line_end=end, version_date=version_date, version_id="v1")


CORPUS = [
    chunk("c1", "a/x.md", "Page X > Sec A"),
    chunk("c2", "a/x.md", "Page X > Other"),
    chunk("c3", "a/y.md", "Sec B > Sub"),
    chunk("c4", "c/z.md", "Z", 10, 15),
]


def items() -> list[dict]:
    raw = [{"id": 1, "kind": "relevant", "gold_chunks": ["a/x.md > Sec A", "a/y.md > Sec B"]},
           {"id": 2, "kind": "relevant", "gold_chunks": ["c/z.md#L12"]},
           {"id": 3, "kind": "irrelevant", "gold_chunks": []}]
    for r in raw:
        r["gold"] = parse_gold(r["gold_chunks"]) if r["kind"] == "relevant" else []
    return raw


def row(run: int, i: int, result: str = "answer", cited: list[str] | None = None, status: str = "ok", dates: list[str] | None = None) -> dict:
    cited = cited or []
    r = {"run": run, "id": i, "status": status, "result": result, "citations": len(cited), "cited_chunk_ids": cited}
    if dates is not None:
        r["cited_version_dates"] = dates
    return r


# ---------------------------------------------------------------- deploy_latency: 인용 청크 id 기록

def test_stream_keeps_cited_chunk_ids_in_event_order_and_keeps_old_fields():
    lines = sse("token", {"text": "답"}) + sse("citation", {"chunk_id": "b2", "version_date": "2026-01-01"}) + \
        sse("citation", {"chunk_id": "a1", "version_date": "2026-02-02"}) + sse("done", {"kind": "answer", "usage": {}})
    ticks = iter(range(100))
    got = dl.consume_chat_stream(lines, t0=0.0, clock=lambda: float(next(ticks)))
    assert got["cited_chunk_ids"] == ["b2", "a1"] and got["cited_version_dates"] == ["2026-01-01", "2026-02-02"]
    assert got["citations"] == 2 and got["status"] == "ok" and got["result"] == "answer"
    refuse = dl.consume_chat_stream(sse("done", {"kind": "refuse", "usage": {}}), t0=0.0, clock=lambda: 1.0)
    assert refuse["cited_chunk_ids"] == [] and refuse["citations"] == 0


def test_dataset_label_is_repo_relative_inside_repo_and_as_given_outside(tmp_path):
    assert dl.dataset_label(dl.DATASET) == "evals/dataset_v2.jsonl"
    outside = tmp_path / "d.jsonl"
    assert dl.dataset_label(outside) == outside.as_posix()


def test_markdown_title_follows_dataset_name_and_defaults_to_v2():
    runs = {1: [{"run": 1, "id": 1, "status": "ok", "first_token_s": 1.0, "total_s": 2.0, "result": "answer", "citations": 1, "cost_usd": 0.01, "expect_refusal": False}]}
    base = {"n_questions": 1, "base_url": "x", "timeout_s": 120}
    assert dl.render_markdown(dl.build_summary(runs, {**base, "dataset": "dataset_v2.jsonl"})).startswith("# 배포본 응답 시간 (평가셋 v2 1건 x 1회)")
    assert dl.render_markdown(dl.build_summary(runs, base)).startswith("# 배포본 응답 시간 (평가셋 v2 1건 x 1회)")
    assert "평가셋 dataset_holdout_v1.jsonl 1건" in dl.render_markdown(dl.build_summary(runs, {**base, "dataset": "dataset_holdout_v1.jsonl"}))


# ---------------------------------------------------------------- 정답 대조

def test_score_row_matches_gold_by_section_and_by_line_and_counts_off_gold():
    by_id = {c.chunk_id: c for c in CORPUS}
    its = {it["id"]: it for it in items()}
    r1 = cg.score_row(row(1, 1, cited=["c1", "c2", "zz"]), its[1], by_id)   # c1은 정답(Sec A), c2는 같은 쪽 다른 절, zz는 스냅샷에 없음
    assert r1["cited_on_gold"] == 1 and r1["cited_off_gold"] == 2 and r1["gold_hit"] == 1 and r1["gold_total"] == 2
    assert r1["wrong_citation"] and r1["gold_cited"] and r1["unresolved"] == ["zz"] and r1["cited_gold_flags"] == [True, False, False]
    r2 = cg.score_row(row(1, 2, cited=["c4"]), its[2], by_id)   # 줄 번호 정답 12가 청크 줄 범위 10~15 안
    assert r2["cited_on_gold"] == 1 and r2["gold_hit"] == 1 and not r2["wrong_citation"]
    r3 = cg.score_row(row(1, 2, cited=["c4", "c3"]), its[2], by_id)
    assert r3["wrong_citation"] and r3["cited_off_gold"] == 1


def test_chunk_id_gold_matches_even_when_snapshot_lacks_the_chunk():
    it = {"id": 9, "kind": "relevant", "gold": parse_gold(["0123456789abcdef"])}
    got = cg.score_row(row(1, 9, cited=["0123456789abcdef"]), it, {})
    assert got["cited_on_gold"] == 1 and got["unresolved"] == ["0123456789abcdef"] and got["gold_hit"] == 1


def test_refusal_or_failed_rows_are_not_answered_and_version_date_mismatch_is_listed():
    by_id = {c.chunk_id: c for c in CORPUS}
    its = {it["id"]: it for it in items()}
    refused = cg.score_row(row(1, 1, result="refuse"), its[1], by_id)
    assert not refused["answered"] and not refused["gold_cited"] and not refused["wrong_citation"]
    failed = cg.score_row({"run": 1, "id": 1, "status": "timeout", "result": None, "citations": 0}, its[1], by_id)   # 옛 결과에는 청크 id 칸이 없다
    assert not failed["answered"] and not failed["has_chunk_ids"]
    mism = cg.score_row(row(1, 1, cited=["c1", "c3"], dates=["2026-09-01", "1999-01-01"]), its[1], by_id)
    assert mism["version_date_mismatch"] == ["c3"]


def test_metrics_match_hand_computed_values_and_follow_run_eval_definitions():
    runs = {1: [row(1, 1, cited=["c1", "c2", "zz"]), row(1, 2, cited=["c4"]), row(1, 3, cited=["c2"])],
            2: [row(2, 1, result="refuse"), row(2, 2, status="timeout", result=None), row(2, 3, result="refuse")]}
    res = cg.score_runs(runs, items(), CORPUS)
    p1, p2 = res["summary"]["per_run"]
    assert p1["cited_correct_rate"] == pytest.approx((0.5 + 1.0) / 2)            # 관련 2건 분모, 문항별 맞힌 정답 위치 비율
    assert p1["wrong_citation_rate"] == pytest.approx(0.5) and p1["wrong_citation_rows"] == 1
    assert p1["citation_accuracy"] == pytest.approx((1 / 3 + 1.0) / 2)           # 답한 관련 2건 분모
    assert p1["citation_accuracy_pooled"] == pytest.approx(2 / 4)
    assert p1["over_refusal_rate"] == 0.0 and p1["correct_refusal_rate"] == 0.0 and p1["answered_irrelevant"] == 1
    assert p1["unresolved_citations"] == 1 and p1["cited_all_rows"] == 5
    assert p2["cited_correct_rate"] == 0.0 and p2["over_refusal_rate"] == 1.0 and p2["correct_refusal_rate"] == 1.0
    assert p2["wrong_citation_rate"] is None and p2["citation_accuracy"] is None and p2["n_fail_rows"] == 1
    m = res["summary"]["mean_over_runs"]
    assert m["cited_correct_rate"] == {"mean": 0.375, "min": 0.0, "max": 0.75}
    assert m["wrong_citation_rate"]["mean"] == 0.5          # 값이 있는 회차만 평균
    assert res["problems"] == [] and res["gold_unlocatable"] == {}
    assert len(res["rows"]) == 6


def test_exclusions_unknown_ids_and_unlocatable_gold():
    its = items()
    its.append({"id": 4, "kind": "relevant", "gold": parse_gold(["q/none.md > Nowhere"])})
    res = cg.score_runs({1: [row(1, 1, cited=["c1"]), row(1, 4), row(1, 77)]}, its, CORPUS, exclusions={"1": "시험"})
    ids = [r["id"] for r in res["rows"]]
    assert ids == [4]                                         # 1번은 제외, 77번은 평가셋에 없어 문제로 적는다
    assert any("77" in p for p in res["problems"])
    assert list(res["gold_unlocatable"]) == ["4"]


def test_corpus_info_compares_deployed_id_and_records_that_it_may_differ():
    meta = {"chunks_fingerprint": "dd284b465cf37a75aaaa", "chunks_sha256": "86e6c26c8a0c", "n_chunks": 4}
    same = cg.corpus_info(CORPUS, meta, "x", [{"corpus_version": "129243bc"}], "dd284b46")
    assert same["same_as_deployed"] is True and same["dataset_corpus_versions"] == ["129243bc"] and same["n_chunks"] == 4
    assert cg.corpus_info(CORPUS, meta, "x", [], "ffffffff")["same_as_deployed"] is False
    unknown = cg.corpus_info(CORPUS, meta, "x", [], None)
    assert unknown["same_as_deployed"] is None and "같은 코퍼스인지는" in unknown["note"]


def test_main_end_to_end_writes_json_and_markdown_without_network(tmp_path: Path):
    res_dir = tmp_path / "res"
    for n, rows in {1: [row(1, 1, cited=["c1"]), row(1, 3, result="refuse")], 2: [row(2, 1, cited=["c1", "c2"]), row(2, 3, result="refuse")]}.items():
        d = res_dir / f"run{n}"
        d.mkdir(parents=True)
        (d / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    ds = tmp_path / "ds.jsonl"
    ds.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in [
        {"id": 1, "kind": "relevant", "gold_chunks": ["a/x.md > Sec A"], "corpus_version": "129243bc"}, {"id": 3, "kind": "irrelevant"}]), encoding="utf-8")
    idx = tmp_path / "idx"
    idx.mkdir()
    (idx / "chunks.jsonl").write_text("".join(json.dumps({k: v for k, v in vars(c).items()}, ensure_ascii=False) + "\n" for c in CORPUS), encoding="utf-8")
    (idx / "meta.json").write_text(json.dumps({"chunks_fingerprint": "abc123", "n_chunks": 4}), encoding="utf-8")
    (res_dir / "summary.json").write_text(json.dumps({"meta": {"dataset_sha256": __import__("hashlib").sha256(ds.read_bytes()).hexdigest()}}), encoding="utf-8")
    assert cg.main(["--results", str(res_dir), "--dataset", str(ds), "--chunks", str(idx / "chunks.jsonl"), "--deployed-corpus-id", "abc123", "--exclusions", str(tmp_path / "none.json")]) == 0
    out = json.loads((res_dir / "citation_gold.json").read_text(encoding="utf-8"))
    assert out["meta"]["dataset_sha_match"] is True and out["meta"]["corpus"]["same_as_deployed"] is True
    s = out["summary"]
    assert [p["cited_correct_rate"] for p in s["per_run"]] == [1.0, 1.0] and [p["wrong_citation_rows"] for p in s["per_run"]] == [0, 1]
    assert (res_dir / "citation_gold.md").read_text(encoding="utf-8").startswith("# 배포본 인용 정답 대조 (ds.jsonl x 2회)")


def test_score_row_passes_through_the_servers_refuse_stage_and_reason():
    its = {it["id"]: it for it in items()}
    by_id = {c.chunk_id: c for c in CORPUS}
    r = row(1, 3, result="refuse", cited=[])
    r.update(refuse_stage="ground", refuse_reason="unsupported")
    scored = cg.score_row(r, its[3], by_id)
    assert (scored["refuse_stage"], scored["refuse_reason"]) == ("ground", "unsupported")
    assert cg.score_row(row(1, 3, result="refuse", cited=[]), its[3], by_id)["refuse_stage"] is None      # 옛 행
