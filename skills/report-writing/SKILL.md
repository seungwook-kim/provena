---
name: report-writing
description: 합동 검토에서 팀 에이전트가 쟁점표 행을 쓸 때 쓴다. 쟁점 문장 구성, 입장과 확신도 판단 기준, 쟁점 키.
---

# 쟁점표 작성

## 판단 규칙 (순서대로 확인)
1. 쟁점 문장은 한두 문장으로 쓰고 세 가지를 담는다: 무엇이 걸리는가, 그대로 진행하면 무엇에 영향이 있는가, 통과하려면 무엇을 해야 하는가. 자료에 없는 부분은 쓰지 않는다. 근거 절: `security` / Field Security Observation and OFI Quality Guide > Quality expectations, Third Party Risk Management > TPRM Security Notice Process.
2. 입장(stance)을 고른다.
   - `block`: 자료가 그 상태의 거절, 지급 거부, 진행 불가를 직접 정한 경우만. 예로 조달 절차를 따르지 않은 구매의 거절, 충분한 보증을 받지 못한 업체의 요청 거부가 있다. 근거 절: Authorization Matrix (2023-05) > Procurement, Third Party Risk Management > Requisition Denial.
   - `condition`: 자료가 검토, 승인, 문서 제출을 먼저 거치라고 정한 경우. 조달 절차를 진행 전에 시작하라는 규칙이 예다. 근거 절: `finance` / Procurement > The Procurement Process.
   - `allow`: 자료가 이 경우에 별도 절차가 필요 없다고 직접 말한 경우만. 자료에 언급이 없다는 것은 allow의 근거가 아니다.
3. 위험 수용으로 입장을 낮추지 않는다. 업체 위험은 책임자와 관련자가 수용할 수 있지만 그 결정은 사람이 하고 승인이 필요하다. 쟁점에는 수용 절차가 있다는 사실만 쓴다. 근거 절: Third Party Risk Management > Accepting the Risk.
4. 확신도(confidence)를 고른다. `high`: 근거 chunk가 이 요청의 대상과 경우를 직접 말한다. `medium`: 규칙은 직접이지만 이 요청에 적용되는지는 요청 내용으로 판단했다. `low`: 관련 주제이지만 적용 여부가 자료만으로 분명하지 않다.
5. 쟁점 키(topic)를 아래 목록에서 고른다. 맞는 키가 없을 때만 짧은 영어 소문자 키를 새로 쓴다. 같은 키라야 팀 입장이 갈린 것이 드러난다.
   `procurement`, `approval-chain`, `legal-review`, `security-review`, `privacy-review`, `compliance-review`, `third-party-risk`, `data-classification`, `vendor-contract`, `change-management`, `incident-response`, `on-call`, `access-management`, `tech-stack`, `budget`.
   근거 절: `finance` / Procurement > Review Steps, Timeline, and Considerations(검토 종류의 구분).
6. 팀이 맡은 범위 안의 쟁점만 쓴다. 다른 팀 절의 규칙을 짐작해 대신 쓰지 않는다.

## 출력 형식
팀 프롬프트가 정한 JSON의 `issues` 행(topic, issue, chunk_id, stance, confidence)을 그대로 쓴다. 제목 경로, 판 날짜, URL은 코드가 chunk에서 복사하므로 문장에 쓰지 않는다.

## 거절 조건
근거 chunk가 받쳐 주지 않는 쟁점은 내지 않는다. 비공개 문서로만 연결되는 내용은 쟁점으로 만들지 않는다. "승인한다", "도입해도 된다" 같은 최종 판단은 쓰지 않는다. 최종 판단은 사람 승인에서 한다.

## 출처
3차에서 새로 작성했다. 근거 문서: GitLab Handbook `security/security-assurance/field-security/field_security_observation_and_ofi_quality_guide`, `security/security-assurance/security-risk/third-party-risk-management`, `finance/procurement`, 고정 판 Authorization Matrix (2023-05). Quality Guide의 적용 범위는 Field Security 관찰 기록이고, 여기서는 쟁점 문장의 작성 기준으로 빌려 쓴다(프로젝트 해석). 입장 값 세 가지와 확신도 값 세 가지는 `backend/graph/departments/issue_table.py`의 정의다.
