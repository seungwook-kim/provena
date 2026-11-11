# 배포본 단계별 시간 (provena-api-00035-h69, Langfuse 트레이스)

D8 "비용과 응답 시간을 현재 코드로 단계별 실측"의 운영 측정분이다. 같은 폴더 `stage_times.json`의 요약이며, 값은 `EVAL_REPORT.md` 8장 표의 검색·생성 칸과 "단계별 시간(배포본 `provena-api-00035-h69`, Langfuse 트레이스, 현재 공식 값)" 단락과 같다.

## 측정 조건

- 대상: 운영 Cloud Run 리비전 `provena-api-00035-h69`(커밋 `b2bc434`). 평가셋 v2 50건 x 3회, 문항마다 새 대화, 동시 요청 없음(2026-11-10 23:48~2026-11-11 00:02 +09:00, 150건). 요청 보내기와 클라이언트 측 전체 시간은 같은 폴더 `summary.md`.
- 단계별 시간: 그 150건의 트레이스를 팀 Langfuse 공개 API(`/api/public/v2/observations`, 읽기만)로 내려받아 `evals/latency/stage_times.py`로 계산했다. 새로 호출하지 않았다.
- 짝지은 세션: 150건 중 Langfuse에 세션이 남은 64건(1회 22, 2회 21, 3회 21). 나머지 86건은 세션이 없었다. `provena-api-00032-zhs`에서도 같은 64건만 남았고 원인은 확인하지 못했다.

## 단계별 시간 (64세션)

| 단계 | p50 | p95 | 평균 |
|---|---|---|---|
| 검색 (세션의 검색 노드 시간 합, 검색 노드가 없는 세션 9개 포함) | 0.00초 | 1.22초 | 0.28초 |
| 생성 (그래프가 도는 동안의 LLM 호출 시간, 겹친 호출은 합집합) | 5.36초 | 9.45초 | 5.33초 |
| LLM 호출 밖 (그래프 시간 - 생성) | 0.41초 | 1.27초 | 0.45초 |
| 그래프 전체 | 5.92초 | 9.87초 | 5.78초 |
| 클라이언트 측 전체 (짝지은 64건) | 6.20초 | 10.14초 | 6.06초 |

- 세션당 LLM 호출 수: p50 17.5, p95 38, 평균 17.52.
- 위 값은 `stage_times.json`에서 `evals/latency/stage_times.py`의 `pct`(p95)와 `statistics.median`·`mean`으로 다시 계산해 8장 값과 같은 것을 확인했다.

## 개선 전후

### 단계별 시간: `provena-api-00020` → `provena-api-00035-h69` (Langfuse 트레이스)

| 단계 | 00020 p50 / p95 (74세션) | 00035 p50 / p95 (64세션) | p95 차이 |
|---|---|---|---|
| 검색 | 0.00초 / 1.40초 | 0.00초 / 1.22초 | -0.18초 |
| 생성 | 9.66초 / 15.26초 | 5.36초 / 9.45초 | -5.81초 |
| LLM 호출 밖 | 0.49초 / 1.64초 | 0.41초 / 1.27초 | -0.37초 |
| 그래프 전체 | 10.19초 / 15.28초 | 5.92초 / 9.87초 | -5.41초 |
| 클라이언트 측 전체 (짝지은 세션) | 10.49초 / 15.59초 | 6.20초 / 10.14초 | -5.45초 |
| 세션당 LLM 호출 수 | 13 / 20 | 17.5 / 38 | 늘어남 |

- 00020 값은 `evals/results/deploy_latency_v2/stage_times.json`에서 리비전 `provena-api-00020` 74행을 같은 방법으로 다시 계산한 것이며 8장 "단계별 시간(배포본 `provena-api-00020`, Langfuse 트레이스, 이력)" 단락의 값과 같다.
- 줄어든 시간은 대부분 생성 단계다(p95 -5.81초). 검색과 LLM 호출 밖은 차이가 작다.
- LLM 호출 수는 오히려 늘었는데 생성 시간은 줄었다. 두 리비전 사이에 운영 LLM 공급자가 OpenRouter에서 Anthropic 직접 호출로 바뀌었고(결정 0086) 코드도 여러 번 바뀌어서, 줄어든 몫을 어느 한 변경의 효과로 나누지 못한다.
- 00020 값은 음수 생성 시간 결함을 고치기 전 도구로 계산했다(음수 세션 0개). 원본 트레이스가 없어 고친 도구로 다시 계산하지 못했다.

### 전체 응답 시간: 리비전별 (클라이언트 측, v2 50건 x 3회 평균, `EVAL_REPORT.md` 8장 표)

| 리비전 | p50 | p95 | 요청당 비용 |
|---|---|---|---|
| `provena-api-00020` (OpenRouter) | 9.322초 | 15.641초 | 0.0050달러 |
| `provena-api-00029-qbd` | 6.269초 | 11.153초 | 0.0052달러 |
| `provena-api-00032-zhs` | 5.991초 | 8.473초 | 0.0067달러 |
| `provena-api-00035-h69` (현재 공식 값) | 5.738초 | 8.942초 | 0.0074달러 |

- p95는 15.641초에서 8.942초로 6.699초 줄어 SPEC 10초 안에 들었다. 00032보다는 0.469초 늘었다.
- 요청당 비용은 0.0050달러에서 0.0074달러로 늘었다.
- 이 표는 150건 전체의 값이고 위 단계별 표는 Langfuse에 남은 세션만의 값이라 두 표의 숫자를 서로 바꿔 쓰지 않는다.

## 한계

- 표본은 150건 중 64건이고 관련 문항 쪽으로 치우칠 수 있다. 그래서 8장 표 "전체" 행(150건 3회 평균, `summary.md`)과 같은 방식의 값이 아니다.
- 검색 시간과 그래프 전체 시간은 서버가 요청마다 기록하는 칸이 없어 Langfuse 세션 단위로만 계산했다. 150건 전체에서 검색 시간을 재려면 응답에 검색 시간 칸을 더하는 코드 변경과 재배포 뒤 재측정이 필요하다.
- 단계별 비용과 요청별 LLM 호출 시간(`llm_s`)은 서버가 `done.cost_by_step`에 기록한 150행 전체 값이며 `summary.md`·`summary.json`에 있다(8장 "배포본 단계별 비용" 표).
- 계산 중 도구 결함 하나를 고쳤다. 그래프가 끝난 뒤 시작한 LLM 호출을 그래프 구간으로 잘라 내면 생성 합이 음수가 됐다(64세션 중 7개, 가장 작은 값 -9.03초). 이런 호출은 생성 시간에서 뺀다(`tests/test_stage_times.py`).
- 원본 트레이스는 질문 원문과 사용자 식별자가 들어 있어 올리지 않았다. `stage_times.json`에는 질문 번호, 대화 식별자, 단계 시간만 있다.
- 8장 표의 승인 대기 칸(29.6밀리초, 55.3밀리초)은 운영이 아니라 로컬 Postgres와 가짜 모델로 잰 값이라 이 문서에 넣지 않았다(`evals/results/d8_stage_report/approval_latency_postgres.json`).

## 재현

```
# 입력은 측정 시간대의 Langfuse 관측 목록(질문 원문이 있어 커밋하지 않음)
python evals/latency/stage_times.py --obs <관측 목록.json> --rows anthropic=provena-api-00035-h69=TaskEffortAnthropic=evals/results/deploy_latency_provena-api-00035-h69/run1/rows.jsonl --rows anthropic=provena-api-00035-h69=TaskEffortAnthropic=evals/results/deploy_latency_provena-api-00035-h69/run2/rows.jsonl --rows anthropic=provena-api-00035-h69=TaskEffortAnthropic=evals/results/deploy_latency_provena-api-00035-h69/run3/rows.jsonl --out evals/results/deploy_latency_provena-api-00035-h69/stage_times.json
```
