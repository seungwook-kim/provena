# 트래픽 0% 판 배포 점검 (provena-api-00181-zub, 커밋 9bc7d587)

2026-11-17 02:49:24~02:49:43 KST, main `9bc7d587`(PR #176, 사전 등록 62.77 포함)을 트래픽 0% 태그 판 `provena-api-00181-zub`(태그 `c1117b`)로 띄우고 서비스 전환 전 점검을 했다. 시작과 끝 모두 트래픽은 `provena-api-00178-max` 100%였고 이 점검으로 바뀌지 않았다(`gate_log.txt`의 START·END 줄).

## 결과 (4/4)

| 점검 | 결과 | 근거 |
|---|---|---|
| 설정 대조(00178-max와) | 차이는 이미지 digest(`23557e67` → `1a49f9e3`), `commit` 라벨(`194dfd9a` → `9bc7d587`), `configurationGeneration`(124 → 126), 빌드 메타 주석뿐. 환경 변수·비밀 참조·스케일·동시성 차이 없음 | `describe_diff.txt` |
| 태그 주소 `/health` | 200 | `gate_log.txt` |
| 배포 점검 `deploy_check` | 7/7 통과(L0, U1, X1, X2, R1, E1, H1) | `deploy_check.json` |
| 워밍업 1건과 DB 대화 저장 | 성공 1, 실패 0, 전체 9.805초, 답(인용 4개). 워밍업 대화의 `threads` 1행, `checkpoints` 11행, 상태 idle | `gate_log.txt` |

같은 판의 인젝션 재시험은 `evals/results/injection_live_provena-api-00181-zub/`, v2 50건 지표는 `evals/results/deploy_latency_c1117b_provena-api-00181-zub/`에 있다.

## 비용과 운영 상태

- 비용: 0.014239달러(워밍업 1건). 배포 점검은 LLM을 부르지 않는다.
- 2026-11-17 03시 기준 트래픽은 `provena-api-00178-max` 100%이고, 이 판의 승격은 사용자 승인 대기였다. 배포 방식상 서비스 템플릿은 이 판(00181-zub)이었다. 2026-11-17 09:15 KST 무렵 이 판이 트래픽 100%로 승격되었다(`../promote_provena-api-00181-zub/`).

## 파일

- `deploy_check.json`: 배포 점검 7항목 원자료
- `describe_diff.txt`: 00178-max와 00181-zub의 `describe` 57줄 대조 요약(비밀 값은 이름만)
- `gate_log.txt`: 트래픽 확인, `/health`, DB 연결 수, 배포 점검, 워밍업, DB 저장 확인 기록(KST)
