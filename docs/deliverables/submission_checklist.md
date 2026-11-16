# 제출 체크리스트

가이드 11장 "제출물" 표와 D12(11/17) 항목을 저장소 위치와 함께 정리한 목록입니다. 기준은 main `47e3b82a`(동결 코드 `194dfd9a`, 측정 판 `provena-api-00172-rex`, 2026-11-17 00:45 KST부터 같은 이미지에 LLM 키 비밀값만 바꾼 서비스 판 `provena-api-00178-max`)이며 2026-11-17에 점검했습니다. 동결(11/16 24:00) 뒤에는 `docs/deliverables/`와 발표 자료만 반영됩니다.

상태: 있음(저장소에서 열어 볼 수 있음), 사용자 처리(저장소 밖에서 팀이 제출).

## 가이드 11장 제출물

| 항목 | 가이드 요구 | 저장소 위치 | 상태 |
|---|---|---|---|
| GitHub 저장소 | `.env.example` 포함, 비밀값 커밋 금지 | [.env.example](../../.env.example), [README 비밀값 규칙](../../README.md#비밀값-규칙), [GATES G7](../GATES.md). 2026-11-17 gitleaks 8.30.1: 최종 main `3dbc36ca` 전체 이력 821커밋 검출 0건(`.gitleaksignore` 없이 11건, 모두 등록된 오탐), 작업 폴더 검사에서 추적 파일 검출 0건([evals/results/gitleaks_20261117/](../../evals/results/gitleaks_20261117/)) | 있음 |
| README | 한 줄 정의, 지표 표, `docker compose up` 실행 절차(10분 안 재현), 키 없는 데모 모드 | [README.md](../../README.md)의 "무엇을 하는 서비스인가", "최종 지표", "실행 방법". 2026-11-17 최종 main `47e3b82a` 새 clone 예행: clone 시작부터 `/health` 200까지 63.2초, `/` 200, README 질문 9개 9/9, `pytest -m demo_replay` 6 passed, `.env` 없음([evals/results/fresh_clone_20261117/](../../evals/results/fresh_clone_20261117/), [GATES G2](../GATES.md)). 브라우저 화면에서 백엔드까지 이어지는 경로는 이 예행에서 확인하지 않았다 | 있음 |
| SPEC.md, AGENTS.md | 정본 문서와 에이전트 지침 | [docs/SPEC.md](../SPEC.md), [AGENTS.md](../../AGENTS.md) | 있음 |
| 클라우드 배포 주소 | 평가용 계정으로 핵심 시나리오, `/health` 동작 | [README 배포 주소와 평가용 계정](../../README.md#배포-주소와-평가용-계정), [GATES G1](../GATES.md) | 있음 |
| 평가용 테스트 계정 2개 | 비공개 제출, 저장소에 적지 않음 | 저장소에 없음(README에 제출 방법만 적음) | 사용자 처리 |
| 인덱스 목록(manifest) | 서로 다른 청크 1만+, 문서 50+, 원문 길이·보존 길이·잘림 여부 | [data/manifest.jsonl](../../data/manifest.jsonl), [data/chunks_index.jsonl](../../data/chunks_index.jsonl), [EVAL_REPORT 1장](../../EVAL_REPORT.md#1-코퍼스와-인덱스-g3) | 있음 |
| 평가셋과 원시 결과, 재현 명령 | v2 50건+(관련 25+, 비관련 25+, 4종), v1·v2 동결 해시, 제외 파일, 한 줄 재현 명령 | [evals/dataset_v1.jsonl](../../evals/dataset_v1.jsonl), [evals/dataset_v2.jsonl](../../evals/dataset_v2.jsonl), [evals/FROZEN.json](../../evals/FROZEN.json), [evals/exclusions.json](../../evals/exclusions.json), `evals/results/`, [EVAL_REPORT 9장](../../EVAL_REPORT.md#9-재현-명령) | 있음 |
| 평가 리포트 | 개선 전후 지표표와 달라진 문항, 지표 5개 분리, 단일 대비 멀티, 대체재 비교(같은 질문 5개), 검색 실패 유형 | [EVAL_REPORT.md](../../EVAL_REPORT.md) 2·3·4·5·10장, 동결 판의 달라진 문항은 [failure_analysis.md](./failure_analysis.md) 2장 "동결 판 갱신" | 있음 |
| 신뢰 경계 1장 | 믿지 않기로 한 것, 인젝션 시험 3건 전후, 아직 막지 못한 것 | [EVAL_REPORT 6장](../../EVAL_REPORT.md#6-신뢰-경계). 값 뒤집기 3건의 동결 코드 서비스 판 재시험(2026-11-17, `provena-api-00178-max`): 3건 막힘, 3건 모두 시험 청크 인용([evals/results/injection_corpus_valueflip_provena-api-00178-max/](../../evals/results/injection_corpus_valueflip_provena-api-00178-max/)). 같은 판의 인젝션 시험(2026-11-17, 6장 29행): 발표 직접 인젝션 대비 12건·보조 4건 모두 막힘, 보조판 11건 중 뚫림 1건(LIVE-12pb, 답 끝에 요구 문구가 붙음, 사전 등록 62.77로 코드 수정, 운영 배포 전), 질문 쪽 주입 19건과 코퍼스 주입 35건 모두 막힘([injection_live](../../evals/results/injection_live_provena-api-00178-max/), [injection_deploy](../../evals/results/injection_deploy_provena-api-00178-max/), [injection_corpus_deploy](../../evals/results/injection_corpus_deploy_provena-api-00178-max/)). 막은 것과 막지 못한 것의 요약은 [failure_analysis.md](./failure_analysis.md) 7장 | 있음 |
| Langfuse 대시보드 | 스크린샷 3장 이상(트레이스 상세 1장 포함), 비용과 응답 시간 | [docs/images/langfuse/](../images/langfuse/) 6장, [EVAL_REPORT 7장](../../EVAL_REPORT.md#7-관측-g6) | 있음 |
| 시연 영상 | 링크, 3분 이내, 정상 경로 1개와 실패 경로 1개, 화면마다 한 문장 해설 | 저장소 밖 | 사용자 처리 |
| 발표 자료 | PPT/PDF, 문제 정의 → 구조 → 지표 → 한계, 전원이 파트를 맡음 | 저장소 밖 | 사용자 처리 |

## D12(11/17) 제출물

| 항목 | 저장소 위치 | 상태 |
|---|---|---|
| 실패 사례 분석 글 | [failure_analysis.md](./failure_analysis.md) | 있음(동결 판 00172-rex 기준 갱신) |
| AI 코딩 도구 사용 기록 | [ai_tools_log.md](./ai_tools_log.md) | 있음(2026-11-17까지) |
| 발표 자료 | 저장소 밖 | 사용자 처리 |
| 외부 시선 검토(설문) | [survey/](./survey/) | 있음 |
| 스크린샷 개인정보·비밀값 점검 | `docs/images/` 7장과 `docs/alternatives/captures_2026-11-13/` 3장을 2026-11-17에 육안 점검. API 키, 이메일, 비밀번호는 보이지 않음. `docs/images/langfuse/6-trace-detail-00065-q84.jpg`에 보이던 서비스 내부 사용자 식별자(UUID)와 대화 thread id 5곳(머리 줄 `user:`, 입력·출력의 `user_id`, `thread_id`)은 2026-11-17에 같은 배경색 상자로 가린 사본으로 바꿨다(로그인 아이디·이메일은 원래 보이지 않음). 대체재 캡처의 사람 이름은 GitLab 공개 핸드북에 있는 이름뿐 | 있음 |

## 체크포인트 D12 항목별 대응

2026-11-17에 체크포인트 사이트의 D12 항목을 다시 읽고 항목마다 저장소 위치를 맞춘 표입니다.

| D12 항목 | 저장소 위치 | 상태 |
|---|---|---|
| 실패 사례 분석 글(되돌린 결정, 채택하지 않은 실험, 판정자 한계 포함) | [failure_analysis.md](./failure_analysis.md) 4장 "채택하지 않았거나 효과를 입증하지 못한 실험" 표, 5장 "평가 정답의 판정자" 행과 "측정하지 않은 것", 6장 코드로 되돌린 결정(결정 0101) | 있음 |
| 인젝션: 막은 것과 막지 못한 것 | [failure_analysis.md](./failure_analysis.md) 7장, [EVAL_REPORT 6장](../../EVAL_REPORT.md#6-신뢰-경계) | 있음 |
| AI 코딩 도구 사용 기록 | [ai_tools_log.md](./ai_tools_log.md) | 있음 |
| 발표 자료와 리허설 2회 | 저장소 밖 | 사용자 처리 |
| 스크린샷 개인정보·비밀값 확인 | 위 D12 제출물 표의 "스크린샷 개인정보·비밀값 점검" 행 | 있음 |
| 제출 체크리스트(11/17 24:00까지) | 이 문서 | 있음 |

## 그 밖의 제출 전 점검

| 항목 | 내용 | 상태 |
|---|---|---|
| 변이 시험 2번의 대상 줄 | [GATES](../GATES.md)의 변이 시험 표 2번은 "재현 주의"로 표시했다. 현재 같은 자리는 `backend/graph/build.py` 1298행 `merged = merge_chunks(state.get("chunks", []), found, limit=cap)`이며 2026-11-05 뒤 다시 돌리지 않았다 | 있음(재현 주의) |
