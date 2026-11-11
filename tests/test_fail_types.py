"""evals/retrieval/fail_types.py: 가짜 행으로 실패 유형 세기를 확인한다(네트워크·키 없음)."""
from __future__ import annotations

from types import SimpleNamespace

from evals.latency.deploy_citation_gold import score_runs
from evals.retrieval.fail_types import classify
from evals.retrieval.gold import parse_gold

A, B, C, D = "a" * 16, "b" * 16, "c" * 16, "d" * 16
CORPUS = [SimpleNamespace(chunk_id=x, rule_seq=None, article=None, line_start=None, line_end=None, version_date=None) for x in (A, B, C, D)]
ITEMS = [
    {"id": 1, "kind": "relevant", "gold": parse_gold([A, B])},
    {"id": 2, "kind": "relevant", "gold": parse_gold([A])},
    {"id": 3, "kind": "irrelevant", "gold": []},
]


def row(i: int, result: str, cited: list[str], stage: str | None = None) -> dict:
    return {"run": 1, "id": i, "status": "ok", "result": result, "cited_chunk_ids": cited, "refuse_stage": stage, "citations": len(cited)}


def count(rows: list[dict]) -> dict:
    res = score_runs({1: rows}, ITEMS, CORPUS)
    return classify(res["rows"])


def test_each_type_is_counted_once():
    c = count([row(1, "answer", [A]), row(2, "answer", [C]), row(3, "answer", [A])])
    assert c["relevant_rows"] == 2
    assert c["partial_gold_cited"] == 1          # 1번: 정답 2곳 중 A만
    assert c["no_gold_cited"] == 1               # 2번: 정답 위치를 하나도 인용하지 않음
    assert c["off_gold_cited"] == 1              # 2번의 C
    assert c["answered_for_off_gold"] == 2
    assert c["irrelevant_answered"] == 1         # 3번은 답하면 안 된다
    assert c["questions"]["no_gold_cited"] == {"2": 1}


def test_refusals_by_stage_and_out_of_domain():
    c = count([row(1, "refuse", [], "out_of_domain"), row(2, "refuse", [], "give_up"), row(3, "clarify", [], "search")])
    assert c["refused_relevant"] == 2 and c["refused_out_of_domain"] == 1
    assert c["refused_by_stage"] == {"refuse/out_of_domain": 1, "refuse/give_up": 1}
    assert c["no_gold_cited"] == 0 and c["off_gold_cited"] == 0   # 거절 행은 인용 칸에 세지 않는다
    assert c["irrelevant_answered"] == 0 and c["irrelevant_clarified"] == 1


def test_full_gold_with_extra_chunk_is_only_off_gold():
    c = count([row(1, "answer", [A, B, D])])
    assert c["partial_gold_cited"] == 0 and c["no_gold_cited"] == 0 and c["off_gold_cited"] == 1
