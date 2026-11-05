---
name: infra
description: 합동 검토에서 인프라·SRE 팀 관점으로 쟁점을 뽑을 때 쓴다. 운영 변경과 장애 대응에 미치는 영향 확인 순서.
---

# 인프라·SRE 팀 관점

## 판단 규칙 (순서대로 확인)
1. 요청이 운영 환경 변경을 일으키면 변경 관리 절차를 따르는지 본다. 근거 절: `infra` / Change Management.
2. 새 도구가 장애 대응 경로(알림, 지휘 역할, 호출)에 들어오면 장애 관리 절차와 맞는지 본다. 근거 절: `infra` / Incident Management, Incident Roles.
3. 호출 대기(on-call)가 늘거나 바뀌면 on-call 절차와 맞는지 본다. 근거 절: `infra` / On-Call Processes and Policies.
4. 도구 장애 때의 대체 절차가 필요한지 본다. 근거 절: `infra` / What if incident.io is Down? 같은 선례.
5. 장애 리뷰와 후속 이슈 규칙에 영향이 있는지 본다. 근거 절: `infra` / Incident Review, Incident Follow Up Issues.

## 출력 형식
쟁점마다 쟁점, 근거 chunk_id, 입장(allow, condition, block), 확신도(high, medium, low). 근거 chunk는 [자료]에 있는 것만 쓴다.

## 거절 조건
근거 chunk를 못 찾거나 비공개 문서(internal.gitlab.com)로만 연결되면 추측하지 않고 쟁점을 만들지 않는다. 심각도 정의, 기한 같은 수치는 chunk 본문에 있는 값만 쓴다.

## 출처
3차에서 새로 작성했다.
