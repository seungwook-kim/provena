# 멀티 판 배포 점검 (provena-api-00205-zit, 커밋 e822fb1e)

2026-11-17 15:24~15:41 KST, 커밋 `e822fb1e`(PR #183, `/chat` 멀티 그래프 전환 `7a52ef87`, 갈린 판정 대기 상한, 질문 속 출력 자리 요청 판정 포함)를 트래픽 0% 태그 판 `provena-api-00205-zit`(태그 `c1117m`)로 띄우고 서비스 전환 전 점검을 했다. 시작 때 트래픽은 `provena-api-00181-zub` 100%였고, 점검 도중인 15:33 KST에 `provena-api-00202-rid`가 트래픽 100%로 올라갔다(결정 0134, 이 점검과 따로 진행). 끝날 때 트래픽은 `provena-api-00202-rid` 100%였고 이 판은 0%였다(`gate_log.txt`의 START·END 줄).

이 판은 같은 판의 인젝션 재시험(`evals/results/injection_live_provena-api-00205-zit/`), v2 50건 3회와 새 검증 20건 3회(`evals/results/deploy_bundle_provena-api-00205-zit/`), 합동 검토 확인(아래)을 마친 뒤 2026-11-17 16:58 KST에 트래픽 100%로 올렸다(결정 0131).

## 배포 방식

- 커밋 `e822fb1e`를 `gcloud run deploy provena-api --source ... --no-traffic --tag c1117m --update-labels commit=e822fb1e`로 올렸다(15:24:20 시작, 15:29:31 `Done.`). 이 커밋은 PR #183 브랜치의 커밋이라 배포 때 트리가 `origin/main`(`1dfc3608`)과 다르다(`gate_log.txt`의 COMMIT 줄).
- 배포 직전 서비스 템플릿은 `provena-api-00202-rid`와 환경 변수·실행 설정·이미지가 같았다(TEMPLATE 줄).
- 환경 변수와 비밀 참조는 서비스 템플릿에서 물려받지 않고, `provena-api-00181-zub` 판을 `describe`해 전부 명시적으로 넣은 뒤 다섯 개를 더했다.
  - 일반 값 4개: `LLM_MAX_TOKENS=2500`, `DAILY_QUESTION_LIMIT=0`, `QUESTION_GRAPH_MODE=multi`, `GRAPH_SPLIT_VOTE_WAIT_S=1.0`
  - 비밀 참조 1개: `MCP_EXTERNAL_TOKEN`(Secret Manager 참조, 값은 기록하지 않음)
- 실행 설정: 최대 인스턴스 1, 동시성 80, 시간 제한 300초(00181-zub와 같음).
- 배포 로그의 `NativeCommandError` 줄은 gcloud가 진행 상황을 표준 오류로 쓴 것을 PowerShell이 감싼 표시이며, 배포는 `Done.`으로 끝났다.

## 결과

| 점검 | 결과 | 근거 |
|---|---|---|
| 설정 대조(00181-zub와) | 환경 변수 수 28 → 33. 차이는 더한 5개(`DAILY_QUESTION_LIMIT`, `GRAPH_SPLIT_VOTE_WAIT_S`, `LLM_MAX_TOKENS`, `MCP_EXTERNAL_TOKEN`, `QUESTION_GRAPH_MODE`)뿐이고 실행 설정 차이 없음. 이미지 digest `1a49f9e3` → `01eb2ac7`, `commit` 라벨 `9bc7d587` → `e822fb1e` | `describe_diff.txt` |
| 태그 주소 `/health` | 200 | `gate_log.txt`의 DEPLOYED 줄 |
| 배포 점검 `deploy_check` | 7/7 통과(L0, U1, X1, X2, R1, E1, H1), 15:40:47 KST | `deploy_check.json` |
| 워밍업 1건 | 상태 ok, 결과 answer, 인용 4개, 전체 9.639초(첫 토큰 9.625초), 비용 0.015235달러, LLM 호출 23회, 판정 방식 `two_agree` | `warmup/` |
| 멀티 그래프 동작(서버 로그) | 서버 시작 로그의 질문 그래프 모드 `multi`, 넣은 환경 변수에 `QUESTION_GRAPH_MODE`와 `GRAPH_SPLIT_VOTE_WAIT_S`가 있음 | `multi_check/log_mode.json` |
| 멀티 그래프 동작(Langfuse) | 워밍업 창(06:40:42~06:41:29 UTC)의 질문 trace 1건이 멀티(Supervisor 하위 구간 있음), 단일 0건 | `multi_check/langfuse_warmup.json` |
| DB 대화 저장 | 워밍업 대화의 `threads` 1행, `checkpoints` 22행, 상태 idle(대화 id는 가림) | `gate_log.txt`의 thread_check 줄 |
| 합동 검토 멈춤 | 16:36:43~16:37:00 KST 1회 실행, HTTP 200, `approval_request`(`issue_table`)에서 멈춤. 정리 단계에서 거절(HTTP 200, `rejected`), 남은 항목 0 | `joint_review_probe.json`, `joint_review_log.txt` |
| 합동 검토 팀 선택(Langfuse) | Supervisor 호출 1건, 팀 선택 규칙이 들어간 호출 1건, 출력에 팀 키 1건, 그 trace가 멀티 1건, 단일 0건 | `joint_review_langfuse.json` |

### `deploy_check` 7항목

| 번호 | 점검 | 결과 |
|---|---|---|
| L0 | 두 계정으로 로그인한다 | 통과 |
| U1 | 로그인하지 않은 요청은 401이다 | 통과 |
| X1 | 사용자 B는 A의 대화를 읽지 못한다(404) | 통과 |
| X2 | B의 기억 조회에 A의 기억이 섞이지 않는다 | 통과 |
| R1 | 관리자 전용 경로는 일반 사용자에게 403이다 | 통과 |
| E1 | 오류 본문에 스택 트레이스와 입력값이 없다 | 통과 |
| H1 | 응답에 X-Content-Type-Options와 X-Frame-Options가 있다 | 통과 |

## 진행 중 대기

배포 직후(15:29~15:40 KST) DB 연결 수(Supavisor)가 22~25로 점검 스크립트의 대기 상한 20보다 높아 점검을 미뤘고, 15:40:41에 20이 된 뒤 배포 점검을 실행했다. 배포된 판과 태그는 바뀌지 않았다.

`gate_log.txt` 끝의 15:41:55~15:41:57 줄은 실행기가 같은 배포 단계를 다시 시작하려다 태그 `c1117m`이 이미 있어 아무것도 하지 않고 멈춘 기록이다.

## 배포 기록 파일

`deploy_record.json`은 다음 단계 실행기가 읽는 배포 기록이다. 원래 파일이 없어져 다음 단계(인젝션 재시험)가 15:41:59에 시작 전에 멈췄고, 배포 로그(`gate_log.txt`의 15:29:35 DEPLOYED 줄과 15:41:54 END 줄)의 값으로 다시 만들었다(`rebuilt_from_log` 칸). 다시 만든 값은 리비전, 태그, 커밋, 배포·점검·워밍업·멀티 확인 결과뿐이고 측정값은 들어 있지 않다.

## 비용과 운영 상태

- 비용: 워밍업 0.015235달러, 합동 검토 멈춤 시험 추정 0.006달러. 배포 점검은 LLM을 부르지 않는다.
- 2026-11-17 16:58 KST부터 트래픽 100%는 이 판(`/chat` 멀티 그래프)이다.

## 파일

- `deploy_check.json`: 배포 점검 7항목 원자료
- `describe_diff.txt`: 00181-zub와 00205-zit의 `describe` 대조 요약(환경 변수는 이름과 값 해시로 비교, 비밀은 참조 이름만)
- `gate_log.txt`: 트래픽·태그 확인, 템플릿 대조, 환경 변수 이름 복사, 커밋 확인, 배포, `describe` 대조, `/health`, DB 연결 수, 배포 점검, 워밍업, 멀티 확인, DB 저장 확인 기록(KST)
- `deploy_record.json`: 배포 기록(배포 로그로 다시 만듦)
- `multi_check/`: 서버 로그의 그래프 모드(`log_mode.json`), 워밍업 창의 Langfuse 멀티 trace 확인(`langfuse_warmup.json`)
- `warmup/`: 워밍업 1건의 `summary.json`, `summary.md`, `rows.jsonl`(대화 id는 가림)
- `joint_review_probe.json`, `joint_review_window.json`, `joint_review_langfuse.json`, `joint_review_log.txt`: 합동 검토 멈춤 시험과 팀 선택 규칙 확인 원자료(16:36:41~16:38:06 KST)
