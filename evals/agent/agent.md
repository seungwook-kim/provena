# evals/agent/ : 에이전트 평가

## 이 폴더가 하는 일

질문 그래프 지표(인용 정확도, 거절, 판 날짜 표시 등), LLM 채점, 단일 대 멀티 비교, 결정표·리콜 평가. 개선 전후 2회 이상 잰다(G5).

- 주인: 김승욱
- 입력: 평가셋, 그래프
- 출력: 지표, 비교표

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-13 | 김승욱 (Claude Code) | 합동 검토 재측정 0원 후처리 `analyze_pooled.py` 추가(리뷰 요청 대응). 저장된 결과 폴더만 읽어 팀 대 같은 자료 1인의 정답 쟁점 단위 짝 표, 문항 단위 부트스트랩 95% 구간(2000회, seed 7), 검색 천장(같은 자료 1인 런의 검색 결과에 정답 섹션이 든 정답 쟁점 수)과 도달 가능한 최대 차이, 충돌 행 수를 낸다. LLM·운영 호출 없음. 사전 등록 62.47 근거 칸의 00044 재분석 값 출력은 `evals/results/review_deploy_provena-api-00044-49s/pooled_reanalysis.txt`, 00049와 합친 값은 `evals/results/review_deploy_provena-api-00049-nph/pooled_report.txt`. 재현: `python -m evals.agent.analyze_pooled --dataset evals/dataset_review_v1_gold_draft.jsonl --runs 00044=evals/results/review_deploy_provena-api-00044-49s new=evals/results/review_deploy_provena-api-00049-nph` | PR #146 |
| 2026-11-11 | 박진형 (jinyeong-731) | 박진형이 J-14로 깨진 줄을 고침(조장 지시 11/11 목록 작업 중): `approval_latency.py` `run_http_bench`가 고정값 `"csrf"` 대신 `create_csrf_token(secret)`으로 서명된 토큰을 쓰게 하고, `APPROVAL_PG_URL`이 있을 때 도는 시험 `test_http_bench_passes_signed_csrf` 추가 | #131 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) `classify_overrefuse.py` 추가: 분류 단계만 불러 도메인 밖 분류를 확인(사전 등록 62.30, 62.A·62.34 프로브 문항 포함, 검색·답 작성 호출 없음, 커밋 8722491·4af95cc). `exp_joint_review.py`·`exp_multi_v2.py`에서 제목 경로 검색(`HeadingSearch`)을 지움(e1e37e1) | #119 |
| 2026-11-10 | 김승욱 (기록: 박진형) | 합동 검토(F-03) 평가 측정기 `exp_review_v1.py`(팀 에이전트 갈래 대 에이전트 하나 갈래, 만든 시점에는 재지 않음)와 평가셋 v2 38번 정답 변경의 영향을 저장된 결과로 다시 계산하는 `rescore_v2_item38.py`(LLM·검색 호출 없음) 추가. 결과 `evals/results/v2_item38_rescore/` (보충, PR #112 본문 기준) | #112 |
| 2026-11-10 | 김승욱 (Claude Code) | 합동 검토 대 단일 측정 도구 `exp_joint_review.py`(사전 등록 62.9, 62.11). 같은 입력을 단일 질문 그래프와 합동 검토 그래프에 번갈아 3회 넣고 쟁점표 산출, 응답 시간, 호출 수, 비용, 인용 통과율, 팀 절 범위를 잰다. 결과 `evals/results/joint_review_vs_single_2026-11-10/` | 미정 |
| 2026-11-09 | 김승욱 (기록: 박진형) | 리콜 판정 재현율·정밀도 측정 코드 `exp_recall_v1.py` 추가(`test_recall_notice`가 불러옴, 쌍 파일은 아직 없음) (보충, PR #72 본문 기준) | #72 |
| 2026-11-09 | 김승욱 (기록: 박진형) | v2 최종 측정(사전 등록 61.51) 평가 도구 추가: `stage_report.py`(저장된 결과로 단계별 시간·비용 다시 계산), `approval_latency.py`(승인 대기의 시스템 몫), 되묻기 유출 검사, Langfuse 문항 점수 연결(`tracking.py`). 결과 `evals/results/agent_v2_q_d6151_*` (보충, PR #67 본문 기준) | #67 |
| 2026-11-05 | 김승욱 (기록: 박진형) | 단일 대 멀티 비교 측정기 `exp_multi_v2.py`와 서비스 검색기 측정 `exp_service_v1.py` 반영, v1 수정 재측정과 v2 50건 단일·멀티 3회 결과(사전 등록 #23~#25) (보충, PR #54 본문 기준) | #54 |
| 2026-11-05 | 김승욱 (기록: 박진형) | 측정 실행기 `exp_confirmed_v1.py`(확정 검색 조합 측정 전용 검색기)와 `exp_service_v1.py`(`--store pg`) 추가, D4 수정(재검색 합치기, 되묻기 제한, 인용 범위 등)을 넣은 단일 에이전트 그래프 v1 재측정 (보충, PR #49 본문 기준) | #49 |
| 2026-11-02 | 김승욱 (Claude Code) | 질문 그래프 실행기 `run_eval.py`, LLM 채점 `judge.py`, 기록 `tracking.py`. 실제 검색으로 6문항 동작 확인(점수 아님) | 이번 PR |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
