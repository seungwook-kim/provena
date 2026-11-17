# 서비스 판 승격 기록 (provena-api-00181-zub, 커밋 9bc7d587)

2026-11-17 09:15 KST 무렵(Cloud Run 감사 로그의 `ReplaceService` 2026-11-17T00:15:43Z) 팀장 결정으로 트래픽 0% 태그 판 `provena-api-00181-zub`(태그 `c1117b`, main 코드 `9bc7d587`)를 트래픽 100%로 올렸다. 직전 서비스 판은 동결 코드 `194dfd9a`의 `provena-api-00178-max`(2026-11-17 00:45 KST부터)였다. 승격 뒤 확인은 모두 읽기 전용이고, 이 확인으로 트래픽은 바꾸지 않았다.

## 판의 성격

- 공식 측정값은 그대로 측정 판 `provena-api-00172-rex`(동결 코드 `194dfd9a`)의 3회 측정이다(`EVAL_REPORT.md` 8장). 동결 SHA `47e3b82a`(실행 코드 `194dfd9a`)는 승격 전까지 00172-rex·00178-max가 서비스했다.
- 00181-zub는 측정한 코드에 질문 속 한국어 출력 자리 지시 규칙(사전 등록 62.77), 기억 칸 값의 프롬프트 입력 정화, `/admin/sync` 501 안내 문구를 더한 판이다(backend 4개 파일 `api/changes.py`, `api/errors.py`, `graph/untrusted.py`, `prompts/question.py`). main HEAD `141d4bd9`의 실행 코드는 `9bc7d587`과 같다.
- 설정은 00178-max와 이미지 digest(`23557e67` → `1a49f9e3`), `commit` 라벨, 빌드 주석만 다르다(`../deploy_check_provena-api-00181-zub/describe_diff.txt`).
- 이 판에서 따로 확인한 것: 배포 점검 7/7(`../deploy_check_provena-api-00181-zub/`), 직접 인젝션 재시험 27건 모두 막힘(LIVE-12pb 포함, 대조군 3/3 정상, `../injection_live_provena-api-00181-zub/`), v2 50건 1회 정답 근거 인용률 0.933·인용 정확도 0.940(00172-rex 3회와 다른 문항은 39번 하나, `../deploy_latency_c1117b_provena-api-00181-zub/`), 같은 이미지의 임시 0% 판에서 실패 경로 3종(`../failure_paths_provena-api-00181-zub/`).

## 승격 뒤 확인 (2026-11-17 09:16~09:23 KST)

| 확인 | 결과 | 근거 |
|---|---|---|
| 트래픽 | `provena-api-00181-zub` 100%. 0% 태그 판으로 00166-mob(`lf1116`), 00172-rex(`p1116`), 00178-max(`fix1117`), 00180-xap(`c1117`)이 남아 있다 | `traffic.txt`(09:23 KST) |
| 리비전 라벨·이미지 | `commit=9bc7d587`, `sha256:1a49f9e3…` | `traffic.txt` |
| 배포 주소 `/health` | 200 `{"status":"ok"}`, 0.307초(09:18 KST). 워밍업 직전 측정 도구의 확인도 200(0.105초) | `traffic.txt`, `warmup_summary.json`의 `meta.health_s` |
| 워밍업 1건(배포 주소, 평가셋 v2 1번) | 성공 1, 실패 0, 첫 토큰 10.804초, 전체 10.864초, 답(인용 4개), 비용 0.015241달러(09:16:44~09:16:54 KST) | `warmup_summary.json`, `warmup_summary.md` |
| 워밍업 대화의 DB 저장 | `threads` 1행(상태 `idle`, 마지막 답 종류 `answer`, 생성 00:16:44Z·갱신 00:16:55Z). 읽기 전용 트랜잭션으로 조회 | 아래 "조회 방법" |
| 5xx | 00181-zub 리비전 로그에서 2026-11-17T00:10:00Z(09:10 KST)부터 조회 시각 00:18:36Z까지 5xx 0건. 같은 창의 요청 8건(200 6건, 204 2건), 오류 등급 로그 0건 | `traffic.txt` |

- `warmup_summary.json`·`warmup_summary.md`의 `commit` 값 `194dfd9a`는 측정 도구를 실행한 작업 사본의 커밋이다. 요청을 받은 판은 `revision` 값 `provena-api-00181-zub`(라벨 `commit=9bc7d587`)이다.
- 워밍업 원자료 행(`rows.jsonl`)은 대화 식별자와 답 본문이 있어 저장소에 넣지 않았다.
- 서비스 템플릿(가장 최근 판)은 실패 경로 확인 뒤 설정 복원 때 생긴 0% 판 `provena-api-fprest1117`(00181-zub와 같은 이미지·설정)이다(`docs/deliverables/submission_checklist.md` D11 행).

## 조회 방법

- 트래픽: `gcloud run services describe provena-api --project provena-team --region asia-northeast3 --format "value(status.traffic)"`
- 5xx: `gcloud logging read`에 `traffic.txt`의 필터(리비전 라벨 `provena-api-00181-zub`, `httpRequest.status>=500`, `timestamp>="2026-11-17T00:10:00Z"`)
- DB: 저장소 `.env`의 `DATABASE_URL`을 프로세스 환경 변수로만 읽고, `SET TRANSACTION READ ONLY` 트랜잭션에서 `threads`를 워밍업 대화 식별자로 조회한 뒤 되돌렸다(세션 설정 없음).

## 비용

- 워밍업 0.015241달러. 나머지 확인은 LLM을 부르지 않는다.
