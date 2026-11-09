---
name: search-terms
description: 근거가 부족해 재검색어를 쓸 때 질문의 일상 표현을 핸드북 영어 용어로 바꾼다. 스위치 GRAPH_REQUERY_TERMS를 켰을 때만 판정에 붙는다.
---

# 재검색어 용어표

## 판단 규칙 (순서대로 확인)
1. 재검색어는 질문의 일상 표현을 아래 표의 핸드북 용어로 바꿔 쓴다. 표에 없으면 질문의 말을 그대로 영어로 옮긴다.
2. 표의 용어는 검색어에만 쓴다. 답에는 자료 본문의 표기를 쓴다.
3. 질문에 없는 고유 이름(이미 찾은 자료에만 나온 양식, 팀, 도구 이름)은 검색어에 넣지 않는다. 같은 자료로 되돌아가기 때문이다.
4. 질문이 대상(사내 팀원, 고객)을 말하지 않았으면, 빠진 대상의 용어(team member, customer, GitLab.com user)를 검색어에 넣는다.

| 질문의 표현 | 핸드북 용어 |
|---|---|
| 구매, 도입, 새 도구·소프트웨어·서비스 요청 | procurement, purchase request, new vendor, Zip |
| 업체·외부 서비스의 보안 검토 | Third Party Risk Management (TPRM), TPRM assessment, security review |
| 개인이 쓰는 소프트웨어 | individual use software |
| 계정 잠김, 2단계 인증 초기화 | 2FA removal, account verification |
| 사내 직원 | team member |
| 고객, 외부 사용자 | customer, GitLab.com user |
| 권한 신청 | access request |
| 장애 | incident, severity, on-call |
| 휴가 | time off, PTO |
| 경비, 출장비 | expenses, travel |
| 승인권자 | approver, authorization matrix |

## 출력 형식
따로 출력하지 않는다. 판정 JSON의 query 칸에 영어 검색어 한 줄(12단어 이내)로만 반영한다.

## 거절 조건
표의 용어가 질문의 사실과 맞지 않으면 쓰지 않는다. 용어표는 정의가 아니므로 답의 근거로 쓰지 않는다.

## 출처
3차에서 새로 작성했다. 용어는 GitLab Handbook의 절 이름(`finance/procurement`, `security/security-assurance/security-risk/third-party-risk-management`, `support/workflows/2fa-removal`, `people-group`)에서 가져왔다. 평가셋 v2 38, 39번 사후 진단 뒤에 작성했으므로 그 두 문항에 맞춰졌을 수 있다.
