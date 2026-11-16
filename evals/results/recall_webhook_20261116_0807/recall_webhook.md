# 리콜 웹훅 운영 시험 (2026-11-16)

운영 판 `provena-api-00075-5zk`, 커밋 `eb7516ca`. 계정 B(영향받는 답의 주인), 관리자 A(검토함·전송 기록).

| 항목 | 값 |
|---|---|
| 개정 | 출처 S(R=리콜 시험 커밋, S=증분 수집), 판 `5f1484ae`, rule_seq 2545176027, `2. Write the definition` |
| 개정 전·후 날짜 | 2026-10-23 → 2026-11-11 (modified), event_key `27a9d01348c00f4c` |
| 영향받는 답 | 1건(모두 B, 다른 사용자 0), 만든 방법 seed |
| 웹훅 | 202, event_id 일치 통과 |
| 처리 | {'status': 'done', 'notices': 1, 'review': 1, 'judge_failures': 1, 'candidates': 2, 'error_kind': None} |
| 결과 | B에게 보이는 정정 알림 0건, 관리자 검토함 1건 → 통과 |
| 웹훅 구독·전송 | 구독 {'status': 200, 'active': 0, 'secret_configured': 0}, 전송 0건 |
| 비용 | 질문 0.018159달러, 판정 추정 0.01달러 이하 |

B에게 보인 알림:


운영에 남는 것(지우지 않음, 발표 시연용): recall_events 1줄, recall_notices, 함께 볼 정책 후보, 전송 기록, 씨앗 질문의 대화·답. 지우려면(실행하지 않음):

```sql
DELETE FROM webhook_deliveries WHERE notice_id IN (SELECT notice_id FROM recall_notices WHERE event_key = '27a9d01348c00f4c');
DELETE FROM recall_notices WHERE event_key = '27a9d01348c00f4c';
DELETE FROM maintenance_candidates WHERE event_key = '27a9d01348c00f4c';
DELETE FROM recall_events WHERE event_key = '27a9d01348c00f4c';
```
