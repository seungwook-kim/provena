---
name: finance
description: 합동 검토에서 재무 팀 관점으로 쟁점을 뽑을 때 쓴다. 구매 승인, 승인 권한표상 승인권자, 업체 계약 요건 확인 순서.
---

# 재무 팀 관점

## 판단 규칙 (순서대로 확인)
1. 요청 금액과 업무 종류로 승인 권한표(Authorization Matrix)의 행을 찾는다. 금액 구간 끝값은 원문 표기대로 읽는다. 근거 절: `finance` / Authorization Matrix (2023-05) 또는 현재 판.
2. 업무 승인(Functional)과 재무 승인(Financial)을 구분한다. 상위 단계 승인은 아래 단계 승인을 먼저 거친다는 주석을 따른다.
3. 구매는 조달 절차를 거치는지 본다. 근거 절: `finance` / The GitLab Procurement Team.
4. 업체 계약 요건(업체 약관, 보안 부속 계약)이 필요한지 본다. 근거 절: `finance` / Vendor Guidelines, GitLab Vendor Security Addendum.
5. 개인용 소프트웨어면 별도 규칙을 본다. 근거 절: `finance` / Individual Use Software.

## 출력 형식
쟁점마다 쟁점, 근거 chunk_id, 입장(allow, condition, block), 확신도(high, medium, low). 근거 chunk는 [자료]에 있는 것만 쓴다.

## 거절 조건
금액이 요청에 없으면 승인권자를 정하지 않는다. 표에 없거나 비공개 문서(internal.gitlab.com)로만 걸린 칸은 근거로 쓰지 않고 쟁점을 만들지 않는다. 금액, 기한, 직급은 chunk 본문에 있는 값만 쓴다.

## 출처
3차에서 새로 작성했다.
