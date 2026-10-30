# backend/schemas/ : 파트 사이 데이터 형식

## 이 폴더가 하는 일

검색 → 에이전트(`chunk.py`), 에이전트 → 화면(`events.py`), 승인(`approval.py`), 리콜(`recall.py`), 결정표(`decision.py`) 형식을 둔다. **혼자 고치지 않는다. 필드 추가는 PR 하나로 3명 승인, 이름 변경·삭제는 회의에서만 정한다.**

- 주인: 공동 (3명 승인)
- 입력: 없음
- 출력: Pydantic 모델

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-10-30 | 김승욱 (Claude Code) | SDD 6장의 chunk·events·approval·recall·decision 모델을 올렸다(`rule_seq`는 8자리 16진수라 DB는 BIGINT). SDD 11-1 추천안대로 `DecisionRule`에 업무 종류·금액 구간·업무 승인자·재무 승인자 칸(이름은 `parse_authz()` 출력과 같음), `Decision.decided_by`, `ChangedArticle.change_type`, `Chunk.text_sha256`을 더했다. 10/30 결정에 맞춰 `DecisionRule.range_note`(I-004), `Chunk.version_date_before`(I-001), `ApprovalItem.created_at`을 `datetime`으로, `AgentEvent.data`의 type별 키를 SDD 6장 표로 정했다. `tests/test_schemas.py`가 필드 이름을 고정한다(23 passed). 3명 승인 대기 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
