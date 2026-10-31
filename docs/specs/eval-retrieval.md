# Spec — 검색 채점과 평가셋 정답 위치 (김승욱)

## Why

- **페르소나**: 임베딩·검색 방식·리랭커를 고르는 우리 조, EVAL_REPORT의 선택 근거를 확인하는 평가자
- **상황**: 평가셋 v1(11/3)·v2(11/6)를 동결한 뒤 같은 셋으로 개선 전후를 두 번 이상 잰다(G5). 청킹 크기·겹침은 D2에 다시 잰다.
- **문제**:
  1. 정답을 청크 id로 적으면 청킹을 바꿀 때마다 동결한 평가셋이 깨진다.
  2. 정답을 페이지 주소로 적으면 그 페이지의 아무 청크나 정답으로 쳐서 점수가 부푼다.
  3. 조합(임베딩 × 방식 × 리랭커)이 많아 사람이 하나씩 돌리면 비교표와 버린 대안이 남지 않는다.
- **측정 지표**: Recall@5(섹션 단위), hit@5, page_hit@5(페이지 단위, 참고), MRR, nDCG@5, 비관련 거절률(Wilson 95%), 지연 p50·p95

## Goal

- **해결 목표**: 정답을 문서 위치로 적고 채점할 때 청크에 맞춰, 청킹이 바뀌어도 동결본 그대로 잰다. 검색 함수 하나를 넣으면 지표가, 조합 목록을 넣으면 비교표가 나온다.
- **성공 기준**: v1 관련 15건 정답이 PR #23 청크에서 모두 찾아짐 / 정답 청크를 그대로 돌려주는 검색으로 Recall@5 1.0·비관련 거절 15/15 / 같은 섹션이 청크 여러 개로 잘려도 Recall에서 한 번만 셈 / 비교를 중간에 멈춰도 이어서 돎
- **Out of Scope**: 임베딩·색인·`search()` 구현(B-4, 박진형), 답 생성 채점(`evals/agent/`), 평가셋 동결(`evals/freeze.py`)

## What

**Happy Path**
1. 판정자 두 명이 판정 시트(v1: `evals/judge_sheet_v1.csv`)에 Y/N과 정답 위치를 적는다. 둘 다 Y이고 위치가 같거나 `final_gold`가 있으면 `python evals/judge_sheet.py --to-jsonl ...`로 평가셋 파일을 만든다.
2. `python -m evals.retrieval.run --dataset evals/dataset_v1.jsonl --search-fn <모듈:함수> --chunks data/chunks/chunks.jsonl --out evals/results/<이름>.json`
3. 문항마다 `SearchQuery(query, as_of, k)`로 검색하고, 정답 위치와 맞는 청크의 순위로 지표를 낸다. 비관련은 빈 결과를 거절로 센다.
4. `python -m evals.retrieval.compare --dataset ... --factory <모듈:함수> --grid grid.json --out evals/results/<이름>/`로 조합마다 같은 채점을 하고 `compare.md` 표를 만든다.

**정답 위치 표기** (`evals/retrieval/gold.py`)

| 표기 | 뜻 |
|---|---|
| `경로.md > 제목 > 하위 제목` | 그 페이지의 그 섹션. 청크 제목 경로 안에 이어서 들어 있으면 맞다(앞에 페이지 제목이 붙거나 하위 섹션이어도 맞음). Hugo 제목 앵커 `{#id}`는 무시 |
| `경로.md#L123` | 그 페이지 원본 123행이 들어 있는 청크(제목으로 좁힐 수 없는 각주 등) |
| `authorization-matrix > 제목`, `authorization-matrix#L523` | 2023-05 권한표 |
| `위치 \| 위치` | 그중 하나만 찾으면 되는 정답(같은 문장이 여러 쪽에 있을 때). Recall에서 한 개로 센다 |
| 16자리 16진수 | 청크 id |

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 정답 위치가 코퍼스 어느 청크와도 안 맞음 | `--chunks`를 주면 그 문항을 분모에서 빼고 이유를 결과에 적는다 |
| EC-02 | 코퍼스가 바뀌어 정답이 달라진 문항 | 평가셋은 고치지 않고 `evals/exclusions.json`에 적어 지표에서만 뺀다(`evals/README.md`) |
| EC-03 | 같은 섹션이 청크 여러 개로 잘림 | 정답 위치 단위로 세므로 한 번만 센다 |
| EC-04 | 비관련 질문 | 순위 지표를 내지 않고 거절 여부만 센다. 유형별 거절률도 따로 낸다 |
| EC-05 | 판정자 위치가 다르고 `final_gold`가 빔 | `--to-jsonl`이 멈춘다(합의 전 동결 방지) |
| EC-06 | 비교 도중 멈춤 | 조합별 결과 파일이 있으면 다시 돌리지 않는다 |

## How

- 검색 함수: `SearchQuery -> list[Chunk]`(점수 내림차순). 조합 factory: 설정 dict를 키워드 인자로 받아 검색 함수를 돌려준다.
- 결과: `<out>.json`(`summary`, 문항별 `rows`, 평가셋 sha256), 같은 이름 `.md`. 비교는 `<out>/<조합 해시>.json`, `compare.md`.

## AC (Given-When-Then)

**AC-01 · 청킹과 무관한 정답**
- GIVEN 정답 `security/x.md > Access > Review`
- WHEN 청크 제목 경로가 `X Page > Access > Review` 또는 `Access > Review > Quarterly`이다
- THEN 정답으로 친다. 다른 페이지이거나 `Access`만 있으면 정답이 아니다

**AC-02 · 대안 묶음**
- GIVEN 정답 두 개 중 하나가 `A | B` 묶음이다
- WHEN 검색 결과에 A만 있다
- THEN Recall@5는 0.5다

**AC-03 · v1 정답 확인**
- GIVEN PR #23 청크와 `evals/dataset_v1.jsonl`
- WHEN 정답 청크만 돌려주는 검색으로 채점한다
- THEN 관련 15건 모두 채점되고 Recall@5 1.0, 비관련 거절 15/15다

시험: `tests/test_eval_retrieval.py`
