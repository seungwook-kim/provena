# 합동 검토 팀 선택과 멀티 그래프 trace 확인 (provena-api-00217-kew, 커밋 ddce99b7)

2026-11-17 18:56 KST, 서비스 판 `provena-api-00217-kew`(트래픽 100%) 서비스 주소에 합동 검토 질문 1건을 보내고, 그 시간 창(09:56:07~09:57:02 UTC)의 운영 Langfuse 관측을 읽었다. 방법은 `evals/results/deploy_check_provena-api-00205-zit/`의 합동 검토 확인과 같다.

| 확인 | 결과 |
|---|---|
| 합동 검토 멈춤 | HTTP 200, `approval_request`(`issue_table`)에서 멈춤. 정리 단계에서 반려(HTTP 200, `rejected`), 남은 항목 0, 대기 건 22개 그대로 |
| 팀 선택 규칙 | Supervisor 호출 1건, 팀 선택 규칙이 시스템 프롬프트에 들어간 호출 1건, 출력에 팀 키 1건(선택한 팀 infra, finance) |
| 멀티 그래프 trace | 창 안 trace 4건 중 멀티 1건, 단일 0건, 그 밖 3건(관측 1개짜리). 멀티 trace의 노드 순서: question → supervisor → review(supervisor → team_finance·team_infra → check_teams → merge → queue_approval → approval) |

- 비용: 합동 검토 1런(승인 대기에서 멈춰 응답에 비용 없음, 장부 예약값 0.006달러).

## 파일

- `probe.json`: 질문 1건의 응답 종류와 정리 결과
- `window.json`: 관측을 읽은 시간 창
- `langfuse_multi_review.json`: 팀 선택 규칙·멀티 trace 집계(trace id는 가림)
- `langfuse_capture.json`: 멀티 trace의 관측 34개(이름·종류·부모·시각·모델·글자 수만. 관측 id는 순번으로 바꿨고 trace id는 가림)
