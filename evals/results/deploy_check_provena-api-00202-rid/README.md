# 트래픽 0% 판 배포 점검 (provena-api-00202-rid, 커밋 1dfc3608)

2026-11-17 12:10~12:53 KST, main `1dfc3608`을 트래픽 0% 태그 판 `provena-api-00202-rid`(태그 `c1117c`)로 띄우고 서비스 전환 전 점검을 했다. 시작과 끝 모두 트래픽은 `provena-api-00181-zub` 100%였고 이 점검으로 바뀌지 않았다(`gate_log.txt`의 START·END 줄).

## 배포 방식

- 커밋 `1dfc3608`을 `git archive`로 묶어 `gcloud run deploy provena-api --source ... --no-traffic --tag c1117c --update-labels commit=1dfc3608`로 올렸다. 배포 직전 이 커밋의 트리가 `origin/main`과 같음을 확인했다(`gate_log.txt`의 COMMIT 줄).
- 환경 변수와 비밀 참조는 서비스 템플릿에서 물려받지 않고, `provena-api-00181-zub` 판을 `describe`해 전부 명시적으로 넣은 뒤(`--env-vars-file`, `--set-secrets`) 세 개만 더했다.
  - 일반 값 2개: `LLM_MAX_TOKENS=2500`, `DAILY_QUESTION_LIMIT=0`
  - 비밀 참조 1개: `MCP_EXTERNAL_TOKEN`(Secret Manager 참조, 값은 기록하지 않음)
- 실행 설정: 최대 인스턴스 1, 동시성 80, 시간 제한 300초(00181-zub와 같음).
- 배포 로그의 `NativeCommandError` 줄은 gcloud가 진행 상황을 표준 오류로 쓴 것을 PowerShell이 감싼 표시이며, 배포는 `Done.`으로 끝났다(12:15:25 KST).

## 결과

| 점검 | 결과 | 근거 |
|---|---|---|
| 설정 대조(00181-zub와) | 환경 변수 수 28 → 31. 차이는 더한 3개(`DAILY_QUESTION_LIMIT`, `LLM_MAX_TOKENS`, `MCP_EXTERNAL_TOKEN`)뿐이고, 실행 설정(서비스 계정·동시성·시간 제한·자원·포트·시작 검사·최대/최소 인스턴스·CPU 설정·세션 고정) 차이 없음. 이미지 digest `1a49f9e3` → `a6f6a026`, `commit` 라벨 `9bc7d587` → `1dfc3608` | `describe_diff.txt` |
| 태그 주소 `/health` | 200(배포 직후, 점검 직전 모두) | `gate_log.txt` |
| 배포 점검 `deploy_check` | 7/7 통과(L0, U1, X1, X2, R1, E1, H1) | `deploy_check.json` |
| 워밍업 1건 | 상태 ok, 결과 answer, 인용 4개, 전체 6.488초(첫 토큰 6.477초), 비용 0.013398달러 | `warmup/` |
| DB 대화 저장 | 워밍업 대화의 `threads` 1행, `checkpoints` 11행, 상태 idle(대화 id는 가림) | `gate_log.txt`의 thread_check 줄 |
| MCP 인증과 호출 한도 | 아래 표 | `mcp_gate.json` |
| 공동 검토 멈춤 | 1회 실행, HTTP 200, `approval_request`(`issue_table`)에서 멈춤. 정리 단계에서 거절(HTTP 200, `rejected`), 남은 항목 0 | `joint_review_probe.json` |
| 5xx | 0건(03:13:00~03:55:30 UTC, 서비스 전체). 같은 창의 `/chat` POST 3건 모두 `provena-api-00202-rid` | `errors_5xx.json` |

### `deploy_check` 7항목

| 번호 | 점검 | 결과 |
|---|---|---|
| L0 | 두 계정으로 로그인한다 | 통과 |
| U1 | 로그인하지 않은 요청은 401이다(7개 경로) | 통과 |
| X1 | 사용자 B는 A의 대화를 읽지 못한다(404) | 통과 |
| X2 | B의 기억 조회에 A의 기억이 섞이지 않는다 | 통과 |
| R1 | 관리자 전용 경로는 일반 사용자에게 403이다(3개 경로) | 통과 |
| E1 | 오류 본문에 스택 트레이스와 입력값이 없다(5가지 오류 응답) | 통과 |
| H1 | 응답에 X-Content-Type-Options와 X-Frame-Options가 있다(4개 응답) | 통과 |

### MCP 점검 (12:51:05~12:52:23 KST)

| 단계 | 결과 |
|---|---|
| 토큰 없이 `initialize`, `tools/list` | 둘 다 401 |
| 틀린 토큰으로 `initialize`, `tools/call` | 둘 다 401(`invalid_token`) |
| 내부 토큰 `initialize`, `tools/list`, `tools/call` | 200, 도구 6개, 검색 결과 3건(status ok) |
| 외부 토큰 `initialize`, `tools/list`, `tools/call` | 200, 도구 6개, 검색 결과 3건(status ok) |
| 외부 토큰 `tools/call` 연속 31회 | 1~30번째 200(모두 status ok), 31번째 429(`rate_limited`, `Retry-After: 48`) |
| 한도에 걸린 뒤 | 외부 토큰 `tools/list` 200, 내부 토큰 `tools/call` 200(status ok) |

검색 질의는 `evals/dataset_v2.jsonl` 1번 문항이다. MCP 호출은 LLM을 부르지 않고 임베딩만 쓴다(호출당 28토큰).

## 진행 중 멈춤과 재실행

배포 직후(12:15~12:35 KST) DB 연결 수(Supavisor)가 12~16으로 점검 스크립트의 대기 상한 9보다 높아 점검이 12:35:40에 멈췄다. 12:46에 다시 시작했을 때도 10~11이어서, 상한을 12로 올려 12:52:45에 점검을 실행했다. 재실행은 점검만 다시 한 것이고 배포된 판과 태그는 바뀌지 않았다(PRECHECK 줄의 `c1117c->provena-api-00202-rid`).

## 비용과 운영 상태

- 비용: 워밍업 0.013398달러, 공동 검토 멈춤 시험 추정 0.006달러. 배포 점검과 MCP 점검은 LLM을 부르지 않는다.
- 2026-11-17 12:53 KST 기준 트래픽은 `provena-api-00181-zub` 100%이고, 태그 `c1117c`가 이 판을 가리킨다.
- 같은 판의 인젝션 재시험은 `evals/results/injection_live_provena-api-00202-rid/`에 있다.

## 파일

- `deploy_check.json`: 배포 점검 7항목 원자료
- `describe_diff.txt`: 00181-zub와 00202-rid의 `describe` 대조 요약(환경 변수는 이름과 값 해시로 비교, 비밀은 참조 이름만)
- `gate_log.txt`: 트래픽·태그 확인, 환경 변수 이름 복사, 커밋 확인, 배포, `describe` 대조, `/health`, DB 연결 수, 배포 점검, 워밍업, DB 저장 확인 기록(KST)
- `mcp_gate.json`: MCP 인증·호출·연속 호출 한도 원자료
- `joint_review_probe.json`: 공동 검토 멈춤 시험 원자료(12:53:08~12:53:27 KST)
- `errors_5xx.json`: 배포부터 점검 끝까지의 5xx·`/chat` 요청 수 감사(앞뒤 2분 여유)
- `warmup/`: 워밍업 1건의 `summary.json`, `summary.md`, `rows.jsonl`(대화 id는 가림)
