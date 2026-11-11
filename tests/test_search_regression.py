"""검색 회귀 시험: 정해 둔 평가 문항에서 검색 정답 적중이 나빠지면 PR을 막는다 (D8 ⑦, 가이드 p.18 CI 회귀, docs/SCAFFOLD.md `tests/`와 CI).

키·Docker·DB 없이 돈다. 작은 고정 자료(tests/fixtures/search_regression/, 약 1.8MB)를 MemoryStore에 넣고 서비스 입구 search()를
그대로 부른다: 하위 질문마다 상위 k → 번갈아 합치기(roundrobin) → 링크 확장 L1x2(하위 질문마다 2자리 지킴), k=5, voyage-4 dense_en.
설정은 서비스와 같은 SearchConfig.from_env()(검색 환경 변수를 비운 기본값)이다. 질문·하위 질문 벡터는 저장된 것을 쓴다(Voyage를 부르지 않는다).

기대값(expected.json)은 전체 색인(23,095청크, float32)으로 돌린 결과다. 자료는 그 검색이 읽은 청크(질의마다 상위 10, 링크 후보 상위 10)와
정답 청크 일부만 float16으로 떼어 낸 것이고, 떼어 낸 자료의 상위 5가 전체 색인·로컬 Postgres(PgStore 전수)와 40/40 같음을 만들 때 확인했다.

문항: 동결 v1 30건(관련 15·비관련 15) + v2 관련 중 v1에 없는 10건(31~40) = 40건. 채점은 v2 관련 25건(정답은 동결 평가셋 파일에서 읽는다).
검색을 일부러 바꿨다면 PREREGISTER에 먼저 적고 자료·기대값을 다시 만든다(입력 파일은 저장소 밖, 받는 곳은 evals/retrieval/retrieval.md "재현 자료"):
    REPRO_DIR=<voyage-4 재현 zip 푼 폴더> REPRO_DATA=<data/chunks·data/parsed가 있는 폴더> python -m evals.retrieval.regress_fixture --n 10
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.rag.retrieve import search as contract_search      # 그래프가 받는 계약 함수(backend/rag/retrieve/__init__.py)
from backend.rag.retrieve.search import SearchConfig
from backend.schemas.chunk import DEFAULT_K
from evals.retrieval import regress_fixture as rf
from evals.retrieval.run import load_dataset, load_exclusions

FIX = Path(__file__).resolve().parent / "fixtures" / "search_regression"
REC = f"recall@{DEFAULT_K}"
SEARCH_ENV = ("EMBED_MODEL", "EMBED_REVISION", "SEARCH_MODE", "SEARCH_POOL", "RERANK_MODEL", "RERANK_TOP", "QUERY_TRANSLATE",
              "SEARCH_LINK_N", "SEARCH_RANGE_N")


@pytest.fixture(scope="module")
def got():
    rows, docs, vec, q, exp = rf.load_fixture(FIX)
    frozen = {s: {it["id"]: it for it in load_dataset(rf.ROOT / "evals" / f"dataset_{s}.jsonl")} for s in ("v1", "v2")}
    items, subs = [], {}
    for x in q["items"]:
        it = frozen[x["set"]][x["id"]]
        assert it["input"] == x["input"], f"{x['set']} {x['id']}: 자료의 질문이 동결 평가셋과 다르다"
        items.append(it)
        subs[x["id"]] = x["sub_queries"]
    with pytest.MonkeyPatch.context() as mp:
        for k in SEARCH_ENV:
            mp.delenv(k, raising=False)
        with pytest.MonkeyPatch.context() as keyed:         # 서비스 기본 설정은 실제 키가 있을 때의 값이다(키 없는 데모는 금액 구간 조회를 끈다). 설정을 읽는 동안만 키가 있는 것으로 본다
            keyed.delenv("DEMO_MODE", raising=False)
            keyed.setenv("LLM_API_KEY", "test-not-a-real-key")
            cfg = SearchConfig.from_env()                   # 서비스 warmup()과 같은 설정 읽기
        searcher, _ = rf.make_searcher(rows, docs, vec, cfg=cfg)
        mp.setattr(sys.modules["backend.rag.retrieve.search"], "_searcher", searcher)   # search()가 이 검색기를 쓴다(warmup·DB 없이)
        res, traces = rf.run(contract_search, items, subs, load_exclusions(rf.ROOT / "evals" / "exclusions.json"))
    return {"cfg": cfg, "res": res, "traces": traces, "exp": exp, "rows": {r["id"]: r for r in res["rows"]}}


def test_fixture_files_unchanged():
    """자료 파일이 기대값을 만들 때와 같다(자료만 고쳐 시험을 맞추지 못하게)."""
    exp = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
    for name, want in exp["files_sha256"].items():
        assert rf.fixture_sha(FIX / name) == want, f"{name}이 바뀌었다(regress_fixture로 다시 만든다)"


def test_config_is_confirmed_combination(got):
    """서비스 기본 설정이 기대값을 만든 확정 조합과 같다. 기본값을 바꾸면 여기서 먼저 알린다."""
    c, want = got["cfg"], got["exp"]["config"]
    assert (c.embed_model, c.mode, c.rerank_model, DEFAULT_K, c.link_n, c.link_keep_per_sub) == (
        want["embed_model"], want["mode"], want["rerank_model"], want["k"], want["link_n"], want["link_keep_per_sub"])
    # 금액 구간 조회(사전 등록 62.7, 상한은 62.13에서 2→3)는 기대값 파일에 칸이 없어 서비스 기본값 3을 글자로 비교한다(상수끼리 비교하면 기본값을 바꿔도 통과).
    # 지금 40문항에는 금액 질문이 없어 이 값이 결과를 바꾸지 않는다. 금액 질문 문항을 더할 때 기대값에도 range_n을 넣는다(#94 리뷰).
    assert c.range_n == 3


def test_recall_not_worse(got):
    """회귀 = 기대값에서 맞던 것이 나빠진 것(rag 3주 06강). 문항별 Recall@5가 줄거나 첫 정답 순위가 밀리면 실패.
    평균만 보지 않고 문항별로 본다. 좋아진 것은 막지 않는다(기대값은 다시 만들어 올린다)."""
    worse = []
    for e in got["exp"]["rows"]:
        if e["kind"] != "relevant":
            continue
        r = got["rows"][e["id"]]
        assert r.get("scored") == e["scored"], f"{e['id']}: 채점 여부가 다르다"
        if not e["scored"]:
            continue
        late = e["first_hit_rank"] is not None and (r["first_hit_rank"] is None or r["first_hit_rank"] > e["first_hit_rank"])
        if r[REC] < e[REC] - 1e-9 or late:
            worse.append((e["id"], f"{REC} {e[REC]:.3f}→{r[REC]:.3f}", f"첫 적중 {e['first_hit_rank']}→{r['first_hit_rank']}"))
    assert worse == [], f"정답 적중이 나빠진 문항: {worse}"
    s = got["res"]["summary"]
    assert s["n_relevant_scored"] == got["exp"]["summary"]["n_scored"] == 25
    assert s[REC]["value"] >= got["exp"]["summary"][REC] - 1e-9


def test_top5_unchanged(got):
    """변화 감지(회귀 판정과 별개): 문항별 상위 5 청크 집합이 기대값과 같다. Recall에 드러나지 않는 변화(비관련 문항,
    정답 밖 자리)도 잡는다. 좋아진 변경도 여기서 멈추므로, 일부러 바꿨다면 기대값을 다시 만들어 같은 PR에 올린다."""
    diff = []
    for e in got["exp"]["rows"]:
        r = got["rows"][e["id"]]
        if set(r["returned"]) != set(e["returned"]):
            diff.append((e["id"], sorted(set(e["returned"]) - set(r["returned"])), sorted(set(r["returned"]) - set(e["returned"]))))
    assert diff == [], f"상위 5가 바뀐 문항 (id, 빠진 것, 들어온 것): {diff}"


def test_no_empty_or_short_results(got):
    """문항마다 k개를 돌려준다. 저장소·필터가 바뀌어 검색이 조용히 0개(또는 k개 미만)를 돌려주면 여기서 먼저 멈춘다(rag 3주 12강)."""
    short = {i: len(r["returned"]) for i, r in got["rows"].items() if len(r["returned"]) != DEFAULT_K}
    assert short == {}, f"k={DEFAULT_K}개가 아닌 문항(id: 개수): {short}"


def test_paths_exercised(got):
    """하위 질문·링크 확장 경로를 실제로 탔다. 기대값과 문항별로 같아야 한다(경로를 피해 가면 위 시험이 헛통과한다)."""
    tr = got["traces"]
    assert {e["id"]: (e["n_sub"], e["n_link"]) for e in got["exp"]["rows"]} == {i: (t["n_sub"], t["n_link"]) for i, t in tr.items()}
    assert sum(1 for t in tr.values() if t["n_sub"]) >= 10 and sum(1 for t in tr.values() if t["n_link"]) >= 10
    assert {t["mode"] for t in tr.values()} == {"dense_en"}
