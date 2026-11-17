# 멀티 판 배포 점검 (provena-api-00217-kew, 커밋 ddce99b7)

2026-11-17 18:14~18:20 KST, 커밋 `ddce99b7`(멀티 그래프 하위 에이전트를 `durability="exit"`로 돌려 에이전트 안 단계 체크포인트를 남기지 않는 수정, 사전 등록 62.93)을 트래픽 0% 태그 판 `provena-api-00217-kew`(태그 `c1117n`)로 띄우고 서비스 전환 전 점검을 했다. 점검 동안 트래픽은 `provena-api-00205-zit` 100%로 바뀌지 않았다(`gate_log.txt`의 START·END 줄).

이 판은 같은 판의 인젝션 B 묶음 재시험(`evals/results/injection_live_provena-api-00217-kew/`), 새 검증 20건 3회와 v2 50건 3회(`evals/results/deploy_bundle_provena-api-00217-kew/`)를 마친 뒤 2026-11-17 18:50 KST에 트래픽 100%로 올렸다(결정 0137).

## 배포 방식

- 커밋 `ddce99b7`을 트래픽 없이 태그 `c1117n`으로 올렸다(18:14:27 시작, 18:18:23 `Done.`). 이 커밋은 `seunguk` 브랜치의 커밋이라 배포 때 트리가 `origin/main`(`1dfc3608`)과 다르다(`gate_log.txt`의 COMMIT 줄).
- 실행 설정은 `provena-api-00205-zit`와 차이가 없다(TEMPLATE 줄).
- 환경 변수와 비밀 참조는 `provena-api-00205-zit`를 `describe`해 전부 명시적으로 넣었다. 다른 것은 메일 발신 설정뿐이다: `GMAIL_SMTP_USER`와 `EMAIL_FROM`을 프로젝트 계정으로 바꾸고, 앱 비밀번호는 비밀 `provena-gmail-app-password-pp` 참조로 넣었다(값은 기록하지 않음). 그 밖의 값은 00205-zit와 같고 `DAILY_QUESTION_LIMIT`는 `0`이다.
- 배포 로그의 `NativeCommandError` 줄은 gcloud가 진행 상황을 표준 오류로 쓴 것을 PowerShell이 감싼 표시이며, 배포는 `Done.`으로 끝났다.

## 결과

| 점검 | 결과 | 근거 |
|---|---|---|
| 설정 대조(00205-zit와) | 환경 변수 수 33 → 33. 차이는 메일 발신 설정 3개(`EMAIL_FROM`, `GMAIL_APP_PASSWORD`, `GMAIL_SMTP_USER`)뿐이고 실행 설정 차이 없음. 이미지 digest `01eb2ac7` → `79ea4dfc`, `commit` 라벨 `e822fb1e` → `ddce99b7` | `describe_diff.txt` |
| 태그 주소 `/health` | 200 | `gate_log.txt`의 DEPLOYED 줄 |
| 배포 점검 `deploy_check` | 7/7 통과(L0, U1, X1, X2, R1, E1, H1), 18:18:34 KST | `deploy_check.json` |
| 워밍업 1건 | 상태 ok, 결과 answer, 인용 4개, 전체 7.837초, 비용 0.011925달러, LLM 호출 22회 | `warmup/` |
| 멀티 그래프 동작(서버 로그) | 서버 시작 로그의 질문 그래프 모드 `multi`, 넣은 환경 변수에 `QUESTION_GRAPH_MODE`와 `GRAPH_SPLIT_VOTE_WAIT_S`가 있음 | `multi_check/log_mode.json` |
| DB 대화 저장 | 워밍업 대화의 `threads` 1행, `checkpoints` 9행, 상태 idle(대화 id는 가림). 00205-zit 점검의 워밍업 대화는 `checkpoints` 22행이었다 | `gate_log.txt`의 thread_check 줄 |
| 5xx | 점검 창(09:16:27~09:20:50 UTC) 0건, `/chat` POST 2건 모두 이 판 | `errors_5xx.json` |

## 비용과 운영 상태

- 비용: 워밍업 0.011925달러. 배포 점검은 LLM을 부르지 않는다.
- 2026-11-17 18:50 KST부터 트래픽 100%는 이 판이다.

## 파일

- `deploy_check.json`: 배포 점검 7항목 원자료
- `describe_diff.txt`: 00205-zit와 00217-kew의 `describe` 대조 요약(환경 변수는 이름과 값 해시로 비교, 비밀은 참조 이름만, 계정 값은 가림)
- `gate_log.txt`: 트래픽·태그 확인, 템플릿 대조, 환경 변수 복사, 커밋 확인, 배포, `describe` 대조, `/health`, DB 연결 수, 배포 점검, 워밍업, 멀티 확인, DB 저장 확인, 5xx 기록(KST)
- `deploy_record.json`: 다음 단계 실행기가 읽는 배포 기록
- `multi_check/log_mode.json`: 서버 로그의 그래프 모드
- `warmup/`: 워밍업 1건의 `summary.json`, `summary.md`, `rows.jsonl`(대화 id는 가림)
- `errors_5xx.json`: 점검 창의 5xx·요청 수 감사
