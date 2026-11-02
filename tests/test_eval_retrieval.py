"""검색 채점 도구(evals/retrieval) 시험. 모델·네트워크 없이 가짜 청크와 가짜 검색 함수로 돈다."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from backend.rag.ingest.handbook import AUTHZ_PATH, rule_seq
from evals.retrieval import compare
from evals.retrieval.gold import missing_in_corpus, parse_gold, parse_ref
from evals.retrieval.metrics import aggregate, ranking_metrics
from evals.retrieval.run import evaluate

PAGE = "security/x.md"
SEQ = rule_seq("content/handbook/" + PAGE)


def chunk(cid, article, seq=SEQ):
    return SimpleNamespace(chunk_id=cid, rule_seq=seq, article=article)


def test_location_matches_whatever_the_chunking():
    g = parse_ref(f"{PAGE} > Access > Review")
    assert g.matches(chunk("a" * 16, "X Page > Access > Review"))  # 앞에 페이지 제목
    assert g.matches(chunk("b" * 16, "Access > Review > Quarterly"))  # 하위 섹션 청크
    assert not g.matches(chunk("c" * 16, "Access"))  # 상위만
    assert not g.matches(chunk("d" * 16, "Access > Review", seq=SEQ + 1))  # 다른 페이지
    assert parse_ref(f"content/handbook/{PAGE} > Access") == parse_ref(f"{PAGE} > Access")


def test_authz_alias_and_chunk_id_and_bad_format():
    assert parse_ref("authorization-matrix > Notes").rule_seq == rule_seq(AUTHZ_PATH)
    assert parse_ref("0123456789abcdef").chunk_id == "0123456789abcdef"
    with pytest.raises(ValueError):
        parse_ref("Access > Review")  # 페이지 없음


def test_recall_counts_sections_not_chunks():
    gold = parse_gold([f"{PAGE} > A", f"{PAGE} > B"])
    got = [chunk("1" * 16, "A"), chunk("2" * 16, "A"), chunk("3" * 16, "Z"), chunk("4" * 16, "B")]
    m = ranking_metrics(gold, got, 5)
    assert m["recall@5"] == 1.0 and m["rr"] == 1.0 and m["n_found"] == 2
    assert ranking_metrics(gold, got, 2)["recall@2"] == 0.5  # 같은 섹션 두 청크는 한 번


def test_evaluate_rejection_exclusion_and_missing_corpus():
    items = [
        {"id": 1, "kind": "relevant", "input": "q1", "gold": parse_gold([f"{PAGE} > A"])},
        {"id": 2, "kind": "relevant", "input": "q2", "gold": parse_gold([f"{PAGE} > Gone"])},
        {"id": 3, "kind": "relevant", "input": "q3", "gold": parse_gold([f"{PAGE} > A"])},
        {"id": 4, "kind": "irrelevant", "irrelevant_type": "out_of_domain", "input": "q4", "gold": []},
    ]
    corpus = [chunk("1" * 16, "A")]

    def search(q):
        return [] if q.query == "q4" else corpus

    res = evaluate(items, search, 5, exclusions={"3": "코퍼스 변경"}, corpus=corpus)
    s = res["summary"]
    assert s["n_relevant_scored"] == 1 and sorted(s["excluded"]) == [2, 3]
    assert s["recall@5"]["value"] == 1.0
    assert s["irrelevant_rejection"]["k"] == 1 and s["irrelevant_rejection_by_type"]["out_of_domain"]["rejected"] == 1
    assert missing_in_corpus(items[1]["gold"], corpus) == [f"{PAGE} > Gone"]


def test_aggregate_without_irrelevant_items():
    s = aggregate([{"id": 1, "kind": "relevant", "scored": True, "recall@5": 1.0, "hit@5": 1.0, "page_hit@5": 1.0, "rr": 1.0, "ndcg@5": 1.0}], 5)
    assert s["irrelevant_rejection"]["value"] is None and s["recall@5"]["ci95"] is None


def test_compare_grid_expands_and_resumes(tmp_path, monkeypatch):
    assert len(compare.expand({"embedder": ["a", "b"], "rerank_top": [10, 50]})) == 4
    assert compare.expand([{"x": 1}]) == [{"x": 1}]
    data = tmp_path / "d.jsonl"
    data.write_text(json.dumps({"id": 1, "kind": "relevant", "input": "q", "gold_chunks": [f"{PAGE} > A"]}) + "\n", encoding="utf-8")
    grid = tmp_path / "g.json"
    grid.write_text(json.dumps({"hit": [True, False]}), encoding="utf-8")
    calls = []

    def factory(hit):
        calls.append(hit)
        return lambda q: [chunk("1" * 16, "A" if hit else "Z")]

    monkeypatch.setattr(compare, "resolve_fn", lambda spec: factory)
    args = ["--dataset", str(data), "--factory", "x:y", "--grid", str(grid), "--out", str(tmp_path / "o"), "--exclusions", str(tmp_path / "none.json")]
    compare.main(args)
    compare.main(args)  # 두 번째는 저장된 조합을 다시 쓴다
    assert calls == [True, False]
    md = (tmp_path / "o" / "compare.md").read_text(encoding="utf-8")
    assert md.index("| True |") < md.index("| False |")  # Recall 높은 조합이 위


def test_compare_records_dataset_sha256_and_remeasures_when_dataset_changes(tmp_path, monkeypatch):
    data = tmp_path / "d.jsonl"
    data.write_text(json.dumps({"id": 1, "kind": "relevant", "input": "q", "gold_chunks": [f"{PAGE} > A"]}) + "\n", encoding="utf-8")
    grid = tmp_path / "g.json"
    grid.write_text(json.dumps([{"hit": True}]), encoding="utf-8")
    calls = []

    def factory(hit):
        calls.append(hit)
        return lambda q: [chunk("1" * 16, "A")]

    monkeypatch.setattr(compare, "resolve_fn", lambda spec: factory)
    out = tmp_path / "o"
    args = ["--dataset", str(data), "--factory", "x:y", "--grid", str(grid), "--out", str(out), "--exclusions", str(tmp_path / "none.json")]
    compare.main(args)
    result = out / f"{compare.key_of({'hit': True})}.json"
    saved = json.loads(result.read_text(encoding="utf-8"))
    assert saved["meta"]["dataset_sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()
    compare.main(args)
    assert calls == [True]  # 같은 평가셋이면 다시 재지 않는다

    data.write_text(data.read_text(encoding="utf-8") + json.dumps({"id": 2, "kind": "relevant", "input": "r", "gold_chunks": [f"{PAGE} > A"]}) + "\n", encoding="utf-8")
    compare.main(args)
    assert calls == [True, True]  # 평가셋이 바뀌면 다시 잰다
    assert json.loads(result.read_text(encoding="utf-8"))["meta"]["dataset_sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()

    saved = json.loads(result.read_text(encoding="utf-8"))
    del saved["meta"]
    result.write_text(json.dumps(saved), encoding="utf-8")
    compare.main(args)
    assert calls == [True, True, True]  # sha256 기록이 없는 결과도 다시 잰다


def test_judge_sheet_turns_draft_locations_into_gold_format():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("judge_sheet", Path(__file__).resolve().parent.parent / "evals" / "judge_sheet.py")
    js = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(js)
    assert js.draft_gold("a/x.md", "Top (> Sub)") == "a/x.md > Top > Sub"
    assert js.draft_gold("finance/authorization-matrix (www-gitlab-com 0a3de83375, 2023-05)", "Matrix > Notes (6)") == "authorization-matrix > Matrix > Notes (6)"
    assert js.draft_gold("a/x.md ; b/y.md", "One ; Two") == "a/x.md > One ; b/y.md > Two"
    assert js.draft_gold("a/x.md ; b/on-call/_index.md", "One ; (on-call) Two") == "a/x.md > One ; b/on-call/_index.md > Two"
    assert js.draft_gold("a/x.md ; w/root-cause-analysis.md", "One ; (RCA) Two") == "a/x.md > One ; w/root-cause-analysis.md > Two"
    assert js.draft_gold("a/x.md ; b/y.md", "One ; Two ; Three").startswith("확인 필요")
    for e in js.draft_gold("a/x.md ; b/y.md", "One ; Two").split(" ; "):
        parse_ref(e)  # 채점 도구가 읽는 형식


def test_judge_sheet_refuses_unagreed_rows(tmp_path):
    import csv
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("judge_sheet", Path(__file__).resolve().parent.parent / "evals" / "judge_sheet.py")
    js = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(js)
    sheet = tmp_path / "s.csv"
    row = dict.fromkeys(js.COLUMNS, "")
    row.update({"id": 1, "version": "v1", "kind": "relevant", "input": "q", "judge1_ok": "Y", "judge2_ok": "Y",
                "judge1_gold": "a/x.md > A", "judge2_gold": "a/x.md > B"})
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=js.COLUMNS)
        w.writeheader()
        w.writerow(row)
    with pytest.raises(SystemExit):
        js.to_jsonl(sheet, "v1")  # 위치가 갈렸는데 final_gold가 비었다
    row["final_gold"] = "a/x.md > A"
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=js.COLUMNS)
        w.writeheader()
        w.writerow(row)
    assert js.to_jsonl(sheet, "v1")[0]["gold_chunks"] == ["a/x.md > A"]


def test_alternatives_and_heading_anchors():
    g = parse_ref(f"{PAGE} > CI Health > Fix it | other/y.md > Fix")
    assert g.matches(chunk("a" * 16, "CI Health {#broken-master} > Fix it {#resolution}"))  # 앵커는 빼고 맞춘다
    m = ranking_metrics([g, parse_ref(f"{PAGE} > B")], [chunk("1" * 16, "CI Health > Fix it")], 5)
    assert m["recall@5"] == 0.5  # 대안 묶음은 정답 한 개


def test_line_reference():
    g = parse_ref("authorization-matrix#L523")
    hit = SimpleNamespace(chunk_id="a" * 16, rule_seq=rule_seq(AUTHZ_PATH), article="Authorization Matrix", line_start=522, line_end=524)
    miss = SimpleNamespace(chunk_id="b" * 16, rule_seq=rule_seq(AUTHZ_PATH), article="Authorization Matrix", line_start=400, line_end=410)
    assert g.matches(hit) and not g.matches(miss) and g.page_matches(miss)
