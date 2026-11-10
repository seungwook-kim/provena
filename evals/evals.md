# evals/ : 평가

## 이 폴더가 하는 일

평가셋 v1(30건, D2 동결)·v2(50건 이상, D5 동결)는 템플릿 자리(`dataset_v1.jsonl`, `freeze.py`, `FROZEN.json`)를 따른다. 바꾸기 전에 `PREREGISTER.md`에 기대를 먼저 적는다. 동결한 평가셋은 고치지 않는다.

- 주인: 공동 (평가셋), 하위 폴더는 각 주인
- 입력: 평가셋, 그래프
- 출력: 지표, `results/`

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-11 | 박진형 (Claude Code) | D8 8장 빈칸 채움, 새 LLM 호출 없음: 승인 대기를 Postgres 체크포인터로 실측(`agent/approval_latency.py` n=20, 같은 PC Docker Postgres 16.15, 결과 `results/d8_stage_report/approval_latency_postgres.json`), 표의 검색·생성 시간을 배포본 `provena-api-00035-h69` Langfuse 트레이스로 다시 셈(세션 64/150, 결과 `results/deploy_latency_provena-api-00035-h69/stage_times.json`). `latency/stage_times.py`가 그래프가 끝난 뒤 시작한 호출 때문에 생성 시간을 음수로 내던 결함을 고치고 시험 `tests/test_stage_times.py`를 붙임(00035 64세션 중 7개, 00020·00024 81세션은 영향 없음). 결정표 변환 멈춤이 `9c65296`부터 약 0.2초 늘어난 것을 이분 탐색으로 찾아 8장에 적음. CI 문단에 Actions 결제 한도 실패와 로컬 실행 결과 기록 | |
| 2026-11-10 | 김승욱 (Claude Code) | 질문 쪽 주입 시험 도구 `safety/deploy_injection_check.py`의 종료 코드를 나눔(사전 등록 62.27 (다), 운영 00032 결과를 본 뒤의 변경): 주입 사례 실패 1, 비용 상한 3, 주입은 모두 막혔는데 대조군(금액 질문 201·201·205)만 정상 답이 아니면 4. `summary`에 `injection_all_passed`·`control_all_passed` 추가, `all_passed`는 그대로. 시험 `tests/test_deploy_injection_check.py`(서버 없이 가짜 결과). 금액 구간 조회 수정의 0원 재현 결과는 `results/range_retrieval_62_7/replay_62_27.json` | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 합동 검토(F-03) 평가셋 초안과 측정기를 저장소에 올림: `dataset_review_v1.jsonl`(요청 10건, 정답 쟁점 칸·판정자 칸 비어 있음), 판정 안내 `review_judge_guide.md`, 측정기 `agent/exp_review_v1.py`(팀 에이전트 갈래 대 에이전트 하나 갈래, 코드만 있고 돌린 적 없음), 시험 `tests/test_exp_review.py`(30개, 모델 호출 없음). EVAL_REPORT 4장과 `ARCHITECTURE.md`가 이 파일을 "저장소에 없다"고 적던 문구를 고침. 판정 전이라 정답 쟁점 누락률은 아직 재지 못함 | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 응답 시간 p95 단축 로컬 측정(사전 등록 62.8, 62.10, 62.12). 결과 `evals/results/speed_p95_2026-11-10/`(끔 2회, 켬 3회, 공급자 정렬 1회, 분해 hedge 1회), 도구 `evals/latency/run_local_pg.py`(.env 없이 로컬 Postgres), `local_summary.py`, `local_stages.py`. 결과는 EVAL_REPORT 8장 | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | D8 단계별 실측 보강(LLM·Langfuse 호출 없음): `evals/agent/stage_report.py`가 최종 측정 결과에 나오는 호출 이름 3개(`search/decompose_gate`, `write_answer/answer_fast`, `ground/answer_fast`)를 단계 표에 몰라 멈추던 것을 표에 더했다. 최종 측정 3회(`agent_v2_q_d6151_r1~r3_bo2sda2_api`)의 단일 150건 단계별 시간·비용과 승인 대기 시스템 몫(메모리 체크포인터, 가짜 모델)을 `evals/results/d8_stage_report/`에 저장하고 `EVAL_REPORT.md` 8장에 행 1개와 설명 2단을 더했다 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `EVAL_REPORT.md` 두 곳 보강: 3장에 사전 등록 #10 이후 107개 항목의 커밋 순서를 git 이력으로 센 값(별도 커밋이 먼저인 항목 #26, #27 두 개, 결과와 같은 커밋 104개, 결과 없음 1개)과 한계를 적고, 8장 단계 표의 리랭킹 행을 `사용하지 않음`으로, 마지막 `왜 이 모델과 이 구성인가`를 4장·결정 기록 근거로 썼다. 검색·생성 단계 시간은 배포본 Langfuse 트레이스(리비전 00020, 세션 74개)에서 다시 계산해 8장에 채우고, 계산 도구 vals/latency/stage_times.py와 세션별 값 vals/results/deploy_latency_v2/stage_times.json을 올렸다. 62.1 행 복구(#82·#83 병합 충돌 해소 때 누락) | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | CI 평가 점수 비교 단계 추가(강사 지적): `evals/ci_compare.py`가 커밋된 최종 결과(`agent_v2_q_d6151_r{1,2,3}_bo2sda2_api` single·multi 3회 평균)를 통과선(인용 정확도·정답 근거 0.85, 거절 0.90, p95 10초)과 `evals/ci_baseline.json`(EVAL_REPORT 4장 최종 행)에 견주고, `FROZEN.json` 해시와 다른 옛 결과는 뺀다. 표는 `$GITHUB_STEP_SUMMARY`에 쓰고, 시험은 `tests/test_ci_compare.py`, `ci.yml` test 잡에 단계 1개 추가. 키·네트워크 없음 | 없음 |
| 2026-11-09 | 김승욱 (Claude Code) | `PREREGISTER.md` 62.3 Skill 유무 비교 사전 등록(`USE_SKILLS` 켬/끔, 4장 최종 측정과 같은 조건, 끔만 새로 1회). Anthropic 키가 인증 거절되어 사용자 승인으로 OpenRouter에서 켬·끔 번갈아 3회씩 측정(`results/skill_ab_v2/`, 비용 0.916달러, 개정 1 결과는 PREREGISTER 62.3). EVAL_REPORT는 고치지 않음 | 미정 |
| 2026-11-10 | 김승욱 (Claude Code) | 검증 20건(`dataset_holdout_v1.jsonl`)의 판정 기록 문장 정정(결정 0096): 두 판정자(박진형, 강경희)의 문항별 판정 결과와 날짜를 저장소와 팀 대화에서 찾지 못했다(기록 분실로 봄). `EVAL_REPORT.md` 2장, 4장, 5장, 11장과 `docs/SPEC.md`의 문장을 "기록을 찾지 못했다"로 고치고 지표 옆에 한계를 적음. 같은 형식의 판정 시트 `judge_sheet_holdout_v1.csv`(판정 칸 비어 있음)를 올리고 두 판정자에게 다시 판정을 받기로 함. 측정·LLM 호출 없음 | 미정 |
| 2026-11-11 | 김승욱 (Claude Code) | 검증 20건 재판정 완료(결정 0096): 두 판정자(박진형, 강경희) 20건 모두 Y, 두 판정자의 정답 위치가 초안 정답과 20건 모두 같아 정답 변화 없음, 검증 20건 지표는 그대로. `judge_sheet_holdout_v1.csv`를 판정 결과로 덮어쓰고 `final_gold`는 두 판정자가 합의한 값으로 채움(판정자 비고 6건은 참고 의견). 측정·LLM 호출 없음 | 미정 |
| 2026-11-02 | 김승욱(팀장), 박진형, 강경희 | 평가셋 v2 판정 기록: 15시 46분 김승욱이 `judge_sheet_v2.csv`(50건) 배포, 판정자 judge1 박진형·judge2 강경희. 1~30번은 v1 동결본이라 판정 불필요로 Y, 31~50번 새 20건이 판정 대상. 17시 16분 박진형이 강경희와 대조해 수정 2건 제안(36번 모범답안을 "Tier 1·2는 12개월, Tier 3·4는 24개월"로, 48번 질문을 "보안 부서 AI 프로그램(ATO)의 FY28-Q1 마일스톤과 목표 날짜는?"로 교체: 옛 질문은 챔피언 회의 매주·office hours 2주마다라 2월 답을 계산할 수 있었음), 17시 17분 김승욱 승인, 박진형이 `judge_sheet_v2_최종.csv` 업로드. 17시 27분 48번 새 질문 기준 강경희 재판정 요청(원문 `security/ai/ato-program-plan.md`), 17시 31분 수정 완료. 최종 판정은 `judge_sheet_v2.csv`에 있고 문항별 Y/N·정답 위치는 이 파일을 본다 | 없음 |
| 2026-11-01 | 김승욱(팀장) | 동결 검사 변이 확인: 저장소 사본에서 `dataset_v1.jsonl` 한 글자를 바꾸자 `python evals/freeze.py --check`가 바뀐 파일로 `dataset_v1.jsonl`을 보이며 종료 코드 1, `pytest tests/test_frozen_evals.py`가 실패(가이드 p.17, 체크포인트 Pitfalls 3). 코퍼스가 바뀔 때 문항을 지표에서만 빼는 `evals/exclusions.json`을 빈 목록으로 둠(가이드 p.16) | 이 PR |
| 2026-11-01 | 김승욱(팀장) | 평가셋 v1 동결: 두 판정자 최종본으로 `judge_sheet_v1.csv`를 바꾸고 `judge_sheet.py --to-jsonl`로 `dataset_v1.jsonl`을 다시 만든 뒤 `freeze.py`로 동결(sha256 `174996b9…f4332`, 30건, 관련 15, 비관련 15). 위치가 갈린 1·6·7·11·14번은 판정자 합의본(`final_gold`). 관련 15건 정답 위치가 모두 청크에 있는지 확인 | 없음 |
| 2026-10-31 | 김승욱(팀장) | 평가셋 v1 정리: 관련 15건 정답을 페이지 주소에서 섹션 위치(`경로.md > 제목`, 같은 문장이 여러 쪽에 있으면 `위치 \| 위치`, 권한표 각주는 `authorization-matrix#L523`)로 좁힘. 위치는 박진형 점검의 근거 줄을 PR #23 청크에 대응시켜 정했고 15건 모두 코퍼스에서 찾아짐. 30번은 코퍼스에 답이 있어 v2 관련 후보(판정 시트 51번)로 옮기고, 같은 유형(기간이 다름)의 새 비관련 질문으로 바꿔 관련 15·비관련 15 유지. 판정 시트 `judge_sheet.py`·`judge_sheet_v1.csv`(v1 30건, 11/3 동결용. v2 20건과 옮긴 1건은 v2 판정 때 같은 도구 `--only all`로 만든다). 두 판정자 Y·위치 합의 전에는 jsonl을 만들지 않는다 | |
| 2026-10-31 | 박진형 (jinyeong-731, Claude Code) | 평가셋 v1 정답 반영: 강경희 님의 1차 검토본(30문항)을 진형이 고정 코퍼스와 대조해 점검한 결과를 `dataset_v1.jsonl` 에 옮김. 관련 질문의 비어 있던 `gold_chunks`(근거 쪽 주소, 복수 허용)·`expected`·`why`, 비관련 15건의 `why`(코퍼스에 없다는 근거). 점검 결과: 일치 10, 비관련 유지 14, 수정 3(Q1 근거 주소 정정·Q2 IMOC 15분 조건 추가·Q6 격리 기간 병기), 주의 2(Q8·Q11 정답 쪽 범위), 정답 변경 1(Q30: 질문은 조장이 쓴 그대로 두고, 코퍼스에 답이 있어 "거절"이 아니라 실제 답으로 바꾸고 비관련 → 관련으로 옮김 → 관련 16·비관련 14). 점검은 핵심어·문장 검색이라 동의어로 숨은 근거까지 전수 확인한 것은 아님. 동결 전(`FROZEN.json` 없음) | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
