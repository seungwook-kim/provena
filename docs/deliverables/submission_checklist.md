# 제출 체크리스트

가이드 11장 "제출물" 표와 D12(11/17) 항목을 저장소 위치와 함께 정리한 목록입니다. 기준은 main `47e3b82a`(동결 코드 `194dfd9a`, 측정 판 `provena-api-00172-rex`, 2026-11-17 00:45 KST부터 09:15 KST 무렵까지 같은 이미지에 LLM 키 비밀값만 바꾼 서비스 판 `provena-api-00178-max`, 그 뒤 서비스 판은 main 코드 `9bc7d587`의 `provena-api-00181-zub`)이며 2026-11-17에 점검했습니다. 동결(11/16 24:00) 뒤에는 `docs/deliverables/`와 발표 자료만 반영됩니다.

**코드 위치(2026-11-17 `gcloud run services describe`·`revisions list`로 확인).** 동결 SHA `47e3b82a`(실행 코드는 `194dfd9a`와 같음)는 측정 판 `provena-api-00172-rex`와, 2026-11-17 00:45 KST부터 09:15 KST 무렵까지 서비스 판 `provena-api-00178-max`(이미지 `sha256:23557e67…`, 라벨 `commit=194dfd9a`)가 서비스했습니다. main에는 동결 뒤 코드 병합 커밋 `c7a0e29d`(PR #175)와 `9bc7d587`(PR #176)이 더 있으며, 바뀐 실행 코드는 backend 4개 파일 `backend/api/changes.py`, `backend/api/errors.py`, `backend/graph/untrusted.py`, `backend/prompts/question.py`(+43/−5, web 변경 없음)입니다. 2026-11-17 09:15 KST 무렵 팀장 결정으로 `9bc7d587`의 `provena-api-00181-zub`(태그 `c1117b`, 이미지 `sha256:1a49f9e3…`)를 트래픽 100%로 올렸습니다. 측정한 코드에 질문 속 한국어 출력 자리 지시 규칙(사전 등록 62.77), 기억 칸 값의 프롬프트 입력 정화, `/admin/sync` 501 안내 문구를 더한 판이며, 공식 측정값은 그대로 00172-rex의 3회 측정입니다. 이 판에서 따로 확인한 것은 배포 점검 7/7, 직접 인젝션 시험 27건 모두 막힘(대조군 3/3 정상), v2 50건 1회 정답 근거 인용률 0.933·인용 정확도 0.940(00172-rex 3회와 다른 문항은 39번 하나), 같은 이미지의 임시 0% 판에서 실패 경로 3종(검색 0건, 비용 상한, 시간 초과)입니다. 승격 뒤 확인(09:16~09:18 KST): 트래픽 00181-zub 100%, `/health` 200, 워밍업 1건 성공(10.9초, 0.0152달러, 대화 DB 저장 확인), 00181-zub 5xx 0건입니다([evals/results/promote_provena-api-00181-zub/](../../evals/results/promote_provena-api-00181-zub/)). 트래픽 0% 판 `provena-api-00180-xap`(`c7a0e29d`)은 되돌림용으로 남아 있습니다.

**동결 뒤 코드 변경 요약(2026-11-17).** 판은 넷입니다: 2026-11-17 09:15~15:33 KST 서비스 판 `provena-api-00181-zub`(코드 `9bc7d587`), 15:33~16:58 KST 서비스 판 `provena-api-00202-rid`(main `1dfc3608`, `/chat` 단일), 16:58~18:50 KST 서비스 판인 멀티 판 `provena-api-00205-zit`(커밋 `e822fb1e`, `/chat` 멀티), 18:50 KST에 승격한 멀티 판 `provena-api-00217-kew`(커밋 `ddce99b7`)와 같은 이미지·코드에 하루 질문 한도만 켠 지금 서비스 판 `provena-api-00149-cm2`(18:59 KST 무렵부터). main `1b38366e`(PR #181, 2026-11-17 10:35 KST 병합)에 동결 뒤 코드 커밋 `8dd9976e`가 더 들어갔습니다: LLM 호출 1건의 출력 상한(`LLM_MAX_TOKENS` 기본 2500, 평가 전용 단일 검토만 4000), 사람당 하루 질문 한도(`DAILY_QUESTION_LIMIT` 기본 50, 0이면 끔, KST 하루 집계, 넘으면 `/chat` 429 `daily_limit`), 외부 MCP 토큰 호출 제한(`MCP_EXTERNAL_TOKEN`만 분당 30·하루 500, 내부 `MCP_TOKEN`은 그대로), 합동 검토 Supervisor 팀 선택(`REVIEW_TEAM_SELECT` 서비스 설정 켬, 데모 모드 끔, 사전 등록 62.82). 이 코드는 2026-11-17 15:33 KST부터 서비스 판 `provena-api-00202-rid`에 반영되었습니다(운영 환경 변수 `LLM_MAX_TOKENS=2500`, `DAILY_QUESTION_LIMIT=0`(남은 유료 측정 동안 끔, 2026-11-17 18:59 KST 무렵 50으로 바꿔 `provena-api-00149-cm2`), 결정 0134, [evals/results/deploy_check_provena-api-00202-rid/](../../evals/results/deploy_check_provena-api-00202-rid/)). PR #183에는 동결 뒤 코드 커밋 `7a52ef87`(`/chat` 멀티 그래프 전환 `QUESTION_GRAPH_MODE`, 갈린 판정 대기 상한 `GRAPH_SPLIT_VOTE_WAIT_S`), `e822fb1e`(질문 속 출력 자리 요청 판정 `output_request`), `17951939`(CI 색인 풀기, 서비스 코드 아님)가 더 들어 있고, 이 코드는 멀티 판 3회 측정 뒤 2026-11-17 16:58 KST에 서비스 판 `provena-api-00205-zit`로 반영했습니다(결정 0130~0133, [evals/results/deploy_check_provena-api-00205-zit/](../../evals/results/deploy_check_provena-api-00205-zit/), 측정 [evals/results/deploy_bundle_provena-api-00205-zit/](../../evals/results/deploy_bundle_provena-api-00205-zit/)). 그 뒤 커밋 `ddce99b7`(멀티 그래프 하위 에이전트가 에이전트 안 단계 체크포인트를 남기지 않고 끝날 때만 남김, MCP `get_agent_trace`는 에이전트 단위 단계만 보여 줌, 사전 등록 62.93)을 판 `provena-api-00217-kew`로 3회 측정한 뒤 18:50 KST에 올렸고(결정 0137, [evals/results/deploy_check_provena-api-00217-kew/](../../evals/results/deploy_check_provena-api-00217-kew/), 측정 [evals/results/deploy_bundle_provena-api-00217-kew/](../../evals/results/deploy_bundle_provena-api-00217-kew/)), 18:59 KST 무렵 `DAILY_QUESTION_LIMIT=50`만 바꾼 리비전 `provena-api-00149-cm2`가 서비스합니다. 팀 선택은 같은 날 같은 측정기로 켬·끔 각 3회를 다시 재어 정답 쟁점 누락률 평균 켬 0.622(0.568~0.676), 끔 0.649(0.595~0.703), 문항당 비용 켬 0.00279달러, 끔 0.00317달러였고, 회별 범위가 차이보다 커서 누락률 차이는 단정하지 않습니다(사전 등록 62.83, [evals/results/review_team_select_3run_20261117/](../../evals/results/review_team_select_3run_20261117/), 첫 1회 측정은 [review_team_select_20261117/](../../evals/results/review_team_select_20261117/)).

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
| 신뢰 경계 1장 | 믿지 않기로 한 것, 인젝션 시험 3건 전후, 알려진 한계 | [EVAL_REPORT 6장](../../EVAL_REPORT.md#6-신뢰-경계). 값 바꾸기 3건의 동결 코드 서비스 판 시험(2026-11-17, `provena-api-00178-max`): 3건 막힘, 3건 모두 시험 청크 인용([evals/results/injection_corpus_valueflip_provena-api-00178-max/](../../evals/results/injection_corpus_valueflip_provena-api-00178-max/)). 같은 판의 인젝션 시험(2026-11-17, 6장 29행): 발표 직접 인젝션 대비 12건 모두 막힘, 보조 15건 중 막힘 14건(사전 등록 62.77로 규칙 보강), 질문 쪽 주입 19건과 코퍼스 주입 35건 모두 막힘([injection_live](../../evals/results/injection_live_provena-api-00178-max/), [injection_deploy](../../evals/results/injection_deploy_provena-api-00178-max/), [injection_corpus_deploy](../../evals/results/injection_corpus_deploy_provena-api-00178-max/)). 수정을 담은 main `9bc7d587`의 트래픽 0% 판 `provena-api-00181-zub` 재시험(2026-11-17 02:50~02:53 KST): 27건 모두 막힘, 대조군 3/3 정상([injection_live 00181-zub](../../evals/results/injection_live_provena-api-00181-zub/)). 00181-zub는 2026-11-17 09:15 KST 무렵 트래픽 100%로 승격됨(승격 뒤 `/health` 200, 5xx 0건, [promote 기록](../../evals/results/promote_provena-api-00181-zub/)). 막은 것과 막지 못한 것의 요약은 [failure_analysis.md](./failure_analysis.md) 7장 | 있음 |
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
| 인젝션: 막은 것과 알려진 한계 | [failure_analysis.md](./failure_analysis.md) 7장, [EVAL_REPORT 6장](../../EVAL_REPORT.md#6-신뢰-경계) | 있음 |
| AI 코딩 도구 사용 기록 | [ai_tools_log.md](./ai_tools_log.md) | 있음 |
| 발표 자료와 리허설 2회 | 저장소 밖 | 사용자 처리 |
| 스크린샷 개인정보·비밀값 확인 | 위 D12 제출물 표의 "스크린샷 개인정보·비밀값 점검" 행 | 있음 |
| 제출 체크리스트(11/17 24:00까지) | 이 문서 | 있음 |

## 그 밖의 제출 전 점검

| 항목 | 내용 | 상태 |
|---|---|---|
| D11 실패 경로(키 한도, 검색 0건, 시간 초과)와 사용자 안내 | main `9bc7d587` 이미지(트래픽 0% 판 `provena-api-00181-zub`와 같은 이미지의 임시 0% 판)에서 2026-11-17 03:53~04:00 KST에 다시 확인: 검색 0건 `no_results`, 비용 상한 `limit_exceeded`(`LLM_COST_CAP_USD=0.0001`), 시간 초과 `timeout`(`LLM_DEADLINE_S=0.01`, `LLM_MAX_RETRIES=0`) 모두 기대 코드와 서버 문구가 일치했고, 웹 화면의 대체 문구도 서버 문구와 같다. 제공자 요청 한도·잔액 부족(`provider_limit`)은 운영에서 안전하게 만들 수 없어 코드와 단위 시험으로만 확인했다. 브라우저 화면 캡처는 평가용 계정 로그인이 필요해 하지 않았다. 비용 0.000747달러, 운영 트래픽 `provena-api-00178-max` 100% 유지, 임시 판 2개는 삭제했고 설정 복원 때 생긴 0% 판 `provena-api-fprest1117`(00181-zub와 같은 이미지·설정)은 최근 판이라 지우지 못해 남아 있다([evals/results/failure_paths_provena-api-00181-zub/](../../evals/results/failure_paths_provena-api-00181-zub/)). 동결 코드 쪽 이전 기록은 `provena-api-00075-5zk`(커밋 `eb7516ca`)의 [failure_paths_after_fix_20261116/](../../evals/results/failure_paths_after_fix_20261116/)이며 `/chat` 오류 분류 코드(`backend/api/routes.py`)와 웹 코드는 그 뒤 바뀌지 않았다 | 있음(provider_limit는 단위 시험) |
| 증분 수집·정시 실행(가산) 증거 | 정시 실행 주체는 팀장 PC 작업 스케줄러(매일 02:14 KST)이고, 그 작업이 부르는 감싸개의 저장소 사본은 [scripts/ops/sync_task.ps1](../../scripts/ops/sync_task.ps1)이다(실패·시간 초과·준비 실패 때 메일 1통, 삭제 보류 때 메일 1통, 비밀값은 실행할 때만 받음, 값·주소는 환경 변수로 받음). 운영 DB `sync_runs`의 정시 실행 기록은 2026-11-16 02:14 run_id=2(추가 2·수정 50·서식만 6)와 2026-11-17 02:14 run_id=3(수정 6·서식만 1·삭제 33, 새 판 7개, `generation` 5→6) 두 건이며 모두 성공했다([evals/results/sync_prod_20261116/](../../evals/results/sync_prod_20261116/), [evals/results/sync_prod_20261117/](../../evals/results/sync_prod_20261117/), [docs/specs/incremental.md](../specs/incremental.md) "재임베딩 단위와 실행 기록의 현재 상태"). 한계: 정시 실행은 팀장 PC 작업 스케줄러에 기대므로 PC가 꺼져 있으면 그날 실행되지 않고, 저장소에 남은 운영 정시 실행 기록은 2회다 | 있음 |
| 변이 시험 2번의 대상 줄 | [GATES](../GATES.md)의 변이 시험 표 2번은 "재현 주의"로 표시했다. 현재 같은 자리는 `backend/graph/build.py` 1298행 `merged = merge_chunks(state.get("chunks", []), found, limit=cap)`이며 2026-11-05 뒤 다시 돌리지 않았다 | 있음(재현 주의) |
