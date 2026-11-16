# 트래픽 0% 판 배포 점검 (provena-api-00180-xap, 커밋 c7a0e29d)

2026-11-17 02:27:58~02:28:20 KST, main `c7a0e29d`(PR #175)를 트래픽 0% 태그 판 `provena-api-00180-xap`(태그 `c1117`)로 띄우고 서비스 전환 전 점검을 했다. 시작과 끝 모두 트래픽은 `provena-api-00178-max` 100%였고 이 점검으로 바뀌지 않았다(`gate_log.txt`의 START·END 줄).

## 결과

| 점검 | 결과 | 근거 |
|---|---|---|
| 설정 대조(00178-max와) | 차이는 이미지, `commit` 라벨, 빌드 소스 주석뿐. 환경 변수·비밀 참조·스케일·동시성 차이 없음 | 배포 직후 `gcloud run services describe` 대조 |
| 태그 주소 `/health` | 200 | `gate_log.txt` |
| 배포 점검 `deploy_check` | 7/7 통과(L0, U1, X1, X2, R1, E1, H1) | `deploy_check.json` |
| 워밍업 1건 | 성공 1, 실패 0, 전체 10.049초, 답(인용 4개) | `gate_log.txt` |
| DB 대화 저장 | 워밍업 대화의 `threads` 1행, `checkpoints` 11행, 상태 idle | `gate_log.txt` |

v2 지표와 인젝션 재시험은 이 판이 아니라 다음 커밋 `9bc7d587`의 0% 판 `provena-api-00181-zub`에서 쟀다(`evals/results/deploy_check_provena-api-00181-zub/`).

## 비용과 운영 상태

- 비용: 0.014197달러(워밍업 1건). 배포 점검은 LLM을 부르지 않는다.
- 이 판은 승격하지 않았다. 배포 방식상 서비스 템플릿은 이 판으로 바뀌었고(이후 00181-zub로 다시 바뀜), 트래픽은 00178-max 100% 그대로다.

## 파일

- `deploy_check.json`: 배포 점검 7항목 원자료
- `gate_log.txt`: 트래픽 확인, `/health`, DB 연결 수, 배포 점검, 워밍업, DB 저장 확인 기록(KST)
