"""bge int8 리랭커 점수는 저장 값을 쓰지 않는다 (I-013, S-07). 묶음 크기에 따라 같은 (질문, 청크) 점수가 달라져서,
저장 값을 읽으면 조합마다 다른 묶음으로 계산한 값이 섞인다. 가짜 모델만 쓰고 파일은 임시 폴더에만 쓴다."""
from types import SimpleNamespace

import pytest

from evals.retrieval import experiment_v1 as E


def chunks(n):
    return [SimpleNamespace(chunk_id=f"c{i}", text=f"본문{i}") for i in range(n)]


def make(name, tmp_path, monkeypatch, calls):
    monkeypatch.setattr(E, "CACHE", tmp_path)
    s = E._Scores(name)
    monkeypatch.setattr(s, "_predict", lambda q, docs: calls.append(list(docs)) or [float(len(calls)) for _ in docs])
    return s


def test_int8_scores_every_candidate_in_one_batch_each_time_and_writes_nothing(tmp_path, monkeypatch):
    calls = []
    s = make("int8", tmp_path, monkeypatch, calls)
    first = s.score("질문", chunks(5))
    second = s.score("질문", chunks(5))  # 같은 쌍이라도 저장 값을 쓰지 않고 다시 계산한다
    assert len(calls) == 2 and all(len(c) == 5 for c in calls)
    assert first != second
    assert list(tmp_path.iterdir()) == []


def test_int8_ignores_an_existing_saved_value(tmp_path, monkeypatch):
    calls = []
    s = make("int8", tmp_path, monkeypatch, calls)
    s.data = {f"{E.qkey('질문')}:c0": 99.0}
    assert s.score("질문", chunks(1)) == [1.0] and len(calls) == 1


def test_other_rerankers_still_reuse_saved_scores(tmp_path, monkeypatch):
    calls = []
    s = make("bge", tmp_path, monkeypatch, calls)
    a = s.score("질문", chunks(3))
    b = s.score("질문", chunks(3))
    assert a == b and len(calls) == 1 and (tmp_path / "rerank_bge.json").is_file()
