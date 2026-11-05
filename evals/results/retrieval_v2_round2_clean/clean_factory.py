"""리랭커 점수를 조합마다 새로 계산하는 make_search 래퍼 (저장소의 experiment_v1.py는 그대로 둔다).

저장소 폴더에서 `PYTHONPATH=evals/results/retrieval_v2_round2_clean`로 compare.py --factory clean_factory:make_search 로 부른다.
- 모델은 이름별로 한 번만 올려 재사용한다.
- 점수는 조합마다 비어 있는 _Scores에서 시작한다(다른 조합의 캐시를 읽지 않는다).
  점수 파일은 이 파일 옆 clean_scores/ 로 보내 data/index_exp/rerank_*.json 을 건드리지 않는다.
- 질문마다 후보 10개를 한 번에 predict 한다(서비스와 같은 묶음).
"""
from __future__ import annotations

import json
from pathlib import Path

from evals.retrieval import experiment_v1 as ev

SCRATCH = Path(__file__).resolve().parent
OUT_DIR = SCRATCH / "clean_scores"
_MODELS: dict[str, object] = {}


class FreshScores(ev._Scores):
    def __init__(self, name: str, tag: str) -> None:
        self.name = name
        OUT_DIR.mkdir(exist_ok=True)
        self.path = OUT_DIR / f"{tag}.json"
        self.data: dict[str, float] = {}
        self._model = _MODELS.get(name)

    def _predict(self, query, docs):
        out = super()._predict(query, docs)
        _MODELS[self.name] = self._model
        return out


def make_search(embedder: str, mode: str, reranker: str = "none", rerank_top: int = 0):
    s = ev._state(embedder)
    if reranker != "none":
        tag = f"{embedder}__{mode}__{reranker}".replace("+", "_")
        s.rerankers[reranker] = FreshScores(reranker, tag)
    return ev.make_search(embedder, mode, reranker, rerank_top)
