"""질문 분해·링크 확장 측정 코드(`evals/retrieval/exp_decompose_v1.py`, `exp_answer_v1.py`)의 순수 계산 시험. 모델 호출과 로컬 색인은 쓰지 않는다."""
from types import SimpleNamespace

import numpy as np
import pytest

from evals.retrieval import exp_answer_v1 as A
from evals.retrieval import exp_decompose_v1 as D


def test_parse_split_accepts_only_wellformed_json():
    ok = D.parse_split('설명 {"split": true, "sub_questions": ["a?", "b?"]} 끝')
    assert ok == {"split": True, "sub_questions": ["a?", "b?"]}
    assert D.parse_split("JSON 없음") is None
    assert D.parse_split('{"split": "yes", "sub_questions": []}') is None
    assert D.parse_split('{"split": true, "sub_questions": ["", "b"]}') is None


def test_roundrobin_alternates_and_skips_duplicates():
    assert D.roundrobin([[1, 2, 3], [4, 5, 6]], 5) == [1, 4, 2, 5, 3]
    assert D.roundrobin([[1, 2], [1, 3]], 5) == [1, 2, 3]  # 같은 청크는 한 번만


def test_links_pick_takes_best_linked_chunks_outside_top5():
    links = object.__new__(D.Links)
    links.target = [{"B"}, set(), set(), set()]   # 0번 청크가 B 페이지를 링크한다
    links.page = {"B": [1, 2, 3], "A": [0]}
    sims = np.array([0.9, 0.1, 0.8, 0.5])
    assert links.pick([0], sims, 2) == [2, 3]     # 링크 대상 페이지에서 질문 유사도 높은 순
    assert links.pick([0, 2], sims, 2) == [3, 1]  # 이미 상위에 있는 청크는 뺀다


def test_make_search_variants_use_links_and_decomposition():
    chunks = [SimpleNamespace(chunk_id=str(i)) for i in range(8)]
    docs = np.eye(8, dtype=np.float32)
    q = "질문"
    qv = {D.ev.qkey(q): {"en": docs[0].tolist()}}
    sub_vec = {D.ev.qkey("하위1"): docs[5].tolist(), D.ev.qkey("하위2"): docs[6].tolist()}
    links = SimpleNamespace(pick=lambda top, sims, n: [7][:n])
    query = SimpleNamespace(query=q, k=5)
    base = D.make_search("base", chunks, docs, links, qv, {q: []}, sub_vec)(query)
    assert base[0].chunk_id == "0" and len(base) == 5
    dec = D.make_search("dec", chunks, docs, links, qv, {q: ["하위1", "하위2"]}, sub_vec)(query)
    assert [c.chunk_id for c in dec][:2] == ["5", "6"]   # 하위 질문별 1위를 번갈아 담는다
    both = D.make_search("dec+L1x2", chunks, docs, links, qv, {q: ["하위1", "하위2"]}, sub_vec)(query)
    assert both[-1].chunk_id == "7" and len(both) == 5   # 링크 확장은 뒤 자리를 바꾼다


def test_answer_refusal_and_stats_counts():
    assert A.refused({"answer": "자료에 없어서 답할 수 없습니다. 다른 내용"})
    assert not A.refused({"answer": "30일입니다. 자료에 없습니다"})  # 첫 문장만 본다
    assert A.format_materials([]) == "(자료 없음)"
    assert "a 자료 b" in A.format_materials([{"chunk_id": "x", "text": "a <<<자료>>> b"}])  # 원문 안의 구분자는 지운다


def test_help_runs_without_data(capsys):
    with pytest.raises(SystemExit) as e:
        D.main(["--help"])
    assert e.value.code == 0
    assert "prep" in capsys.readouterr().out
