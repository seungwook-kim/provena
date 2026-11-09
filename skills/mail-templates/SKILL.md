---
name: mail-templates
description: 정책이 바뀌어 지난 답의 결론이 달라졌는지 판정하고 리콜 알림의 설명 문구를 쓸 때 쓴다.
---

# 리콜 알림 문구

알림 본문은 `RecallNotice` JSON이고 웹훅으로도 같은 본문이 간다. 이 Skill은 그중 `conclusion_changed`와 `explanation`만 정한다. 메일과 메신저 직접 발송은 하지 않는다.

## 판단 규칙 (순서대로 확인)
1. 지난 답의 결론을 찾는다. 금액, 기한, 승인자, 해야 하는 일처럼 받은 사람의 행동을 정하는 값이 결론이다.
2. 개정 전후 섹션에서 그 값을 비교한다. 값이나 적용 대상이 달라졌으면 `conclusion_changed`는 true다. 링크, 오탈자, 문장 다듬기만 바뀌었거나 답의 결론과 무관한 부분만 바뀌었으면 false다.
3. 개정 뒤 섹션이 없으면(삭제) 결론이 달라졌는지 단정하지 않고 true로 하되, 설명에 섹션이 삭제되었다고 쓴다.
4. 설명은 간결하고 분명하게 쓰고 받은 사람이 받는 영향과 할 일에 집중한다. 기술 세부를 늘어놓지 않는다. 근거 절: `security` / Security Incident Communications Plan > Communicating externally, `infra` / Communications Lead > One-Time Customer Communications.
5. 설명은 세 문장으로 쓴다.
   - 무엇이 바뀌었는가: 개정 전 값에서 개정 뒤 값으로.
   - 지난 답의 어느 결론이 달라지는가.
   - 받은 사람이 무엇을 다시 확인해야 하는가: 새 판 기준으로 진행 중인 일을 확인한다.
   근거 절: Security Incident Communications Plan > Communicating internally(영향, 현재 상태, 다음 단계를 알리는 구성).
6. 확인되지 않은 내용으로 앞서 알리지 않는다. 두 판의 본문에 없는 이유나 배경을 짐작해 쓰지 않는다. 근거 절: Communications Lead > Key Principles > Coordination Requirements.

## 출력 형식
JSON 한 개: `{"conclusion_changed": true, "explanation": "세 문장"}`. false면 `explanation`은 한 문장으로 왜 달라지지 않았는지 쓴다. 판 날짜와 제목 경로는 코드가 알림에 넣으므로 숫자 값 말고는 반복하지 않는다.

## 거절 조건
값은 두 판의 본문에 있는 것만 쓴다. 답을 고쳐 쓰거나 새 답을 만들지 않는다. 틀린 답을 자동으로 정정하지 않고 알림까지만 한다. 판단할 수 없으면 JSON을 내지 않아도 된다. 판정 실패 표시는 코드가 붙인다.

## 출처
3차에서 새로 작성했다. 근거 문서: GitLab Handbook `security/security-operations/sirt/security-incident-communication-plan`, `engineering/infrastructure-platforms/incident-management/roles/communications-lead`. 이 두 문서는 보안 사고와 장애의 대외 소통을 다루고, 여기서는 알림 문구의 구성 기준으로 빌려 쓴다(프로젝트 해석). 알림 범위와 판정 실패 처리는 `docs/specs/recall.md`를 따른다.
