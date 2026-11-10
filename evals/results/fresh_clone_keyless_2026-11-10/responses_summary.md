# 질문 응답 요약 (2026-11-10, 커밋 e8b8059)

키 없는 새 clone 서버에 질문 10개를 보낸 결과를 한 줄씩 요약한 것이다. q1~q5는 README 키 없이 인용 답이 나오는 질문 목록이고 r1~r4, n1은 거절 질문이다. 답 본문(	ext)이 검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다)로 시작하는 것은 녹화된 LLM 응답이 아니라 대체 문장이다.

```text
== n1_unrecorded.json | Q: 신입 개발자 온보딩 체크리스트는 어디서 볼 수 있어?
  kind=refuse code=no_results citations=0 seconds=0.1 cost=0.0
  text: 검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다.
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'code']
== q1_third_party_security.json | Q: 제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?
  kind=answer code=None citations=2 seconds=0.6 cost=0.0
  cite: {"chunk_id": "d96029d78f460b1a", "rule_title": "Security Third Party Risk Management", "article": "What Triggers a TPRM Assessment?", "version_date": "2026-09-13", "version_date_before": false, "source_url": "https://handbook.gitlab.com/handbook/security/security-assurance/security-risk/third-party-
  cite: {"chunk_id": "c9fbc47432ef97c9", "rule_title": "Security Third Party Risk Management", "article": "Third Party Minimum Security Standards > Other Types of Third Party Assessments > Third Party Application Integrations", "version_date": "2026-09-13", "version_date_before": false, "source_url": "https
  text: 검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다). | - Security Third Party Risk Management > What Triggers a TPRM Assessment? [1] | - Security Third Party Risk Management > Third Party Minimum Security Standards > Other Types of Third Party Assessments > Third Party Application Integrations [2] | 기준일: 2026-11-10 |  | 기준일 2026-11-10 · 근거 판 날짜 2026-09-13 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'attribution']
== q2_cvss9.json | Q: CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화(mitigate)하고 얼마 안에 수정(remediate)해야 해?
  kind=answer code=None citations=2 seconds=0.5 cost=0.0
  cite: {"chunk_id": "c3b5296636ea8c06", "rule_title": "Vulnerability Resolution SLAs", "article": "Vulnerability Management SLAs and Labels", "version_date": "2026-04-09", "version_date_before": false, "source_url": "https://handbook.gitlab.com/handbook/security/product-security/vulnerability-management/sl
  cite: {"chunk_id": "1760f9bd2b094dd5", "rule_title": "Vulnerability Resolution SLAs", "article": "Vulnerability Management SLAs and Labels", "version_date": "2026-04-09", "version_date_before": false, "source_url": "https://handbook.gitlab.com/handbook/security/product-security/vulnerability-management/sl
  text: 검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다). | - Vulnerability Resolution SLAs > Vulnerability Management SLAs and Labels [1] | - Vulnerability Resolution SLAs > Vulnerability Management SLAs and Labels [2] | 기준일: 2026-11-10 |  | 기준일 2026-11-10 · 근거 판 날짜 2026-04-09 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'attribution']
== q3_cud.json | Q: 클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해?
  kind=answer code=None citations=2 seconds=0.5 cost=0.0
  cite: {"chunk_id": "fa4c75698c139086", "rule_title": "Authorization Matrix (2023-05)", "article": "Authorization Matrix", "version_date": "2023-05-11", "version_date_before": false, "source_url": "https://gitlab.com/gitlab-com/www-gitlab-com/-/blob/0a3de833754144dc4d448814e2edbcaed0883f35/sites/handbook/s
  cite: {"chunk_id": "221f16d102d25e79", "rule_title": "Hosting", "article": "GCP - Committed Use Discount ( CUD ) Process", "version_date": "2025-07-04", "version_date_before": false, "source_url": "https://handbook.gitlab.com/handbook/finance/financial-planning-and-analysis/r-and-d-finance/hosting-main/",
  text: 검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다). | - Authorization Matrix (2023-05) > Authorization Matrix [1] | - Hosting > GCP - Committed Use Discount ( CUD ) Process [2] | 기준일: 2026-11-10 |  | 기준일 2026-11-10 · 근거 판 날짜 2023-05-11, 2025-07-04 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'attribution']
== q4_eoc_imoc.json | Q: EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면?
  kind=answer code=None citations=2 seconds=0.5 cost=0.0
  cite: {"chunk_id": "1bcdf8557f4f92c2", "rule_title": "Incident Management", "article": "References > Incident Manager Escalation", "version_date": "2026-08-18", "version_date_before": false, "source_url": "https://handbook.gitlab.com/handbook/engineering/infrastructure-platforms/incident-management/", "te
  cite: {"chunk_id": "2944820ef4895720", "rule_title": "Incident Roles - Incident Responder", "article": null, "version_date": "2026-01-23", "version_date_before": false, "source_url": "https://handbook.gitlab.com/handbook/engineering/infrastructure-platforms/incident-management/roles/incident-responder/", 
  text: 검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다). | - Incident Management > References > Incident Manager Escalation [1] | - Incident Roles - Incident Responder [2] | 기준일: 2026-11-10 |  | 기준일 2026-11-10 · 근거 판 날짜 2026-08-18, 2026-01-23 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'attribution']
== q5_saas_50k.json | Q: 외부 SaaS를 도입하려고 합니다. 계약 금액이 5만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  kind=answer code=None citations=4 seconds=0.5 cost=0.0
  cite: {"chunk_id": "905520380353f37a", "rule_title": "Authorization Matrix (2023-05)", "article": "Legal Contracts > Non standard terms > $500k annual revenue", "version_date": "2023-05-11", "version_date_before": false, "source_url": "https://gitlab.com/gitlab-com/www-gitlab-com/-/blob/0a3de833754144dc4d
  cite: {"chunk_id": "68ef17df6892a0de", "rule_title": "Authorization Matrix (2023-05)", "article": "Approving Payment > >$0k up to $500k", "version_date": "2023-05-11", "version_date_before": false, "source_url": "https://gitlab.com/gitlab-com/www-gitlab-com/-/blob/0a3de833754144dc4d448814e2edbcaed0883f35/
  cite: {"chunk_id": "f7b2279a86888e7c", "rule_title": "Authorization Matrix (2023-05)", "article": "Approving Payment > >$500K and above", "version_date": "2023-05-11", "version_date_before": false, "source_url": "https://gitlab.com/gitlab-com/www-gitlab-com/-/blob/0a3de833754144dc4d448814e2edbcaed0883f35/
  cite: {"chunk_id": "9b386ea93519a5a3", "rule_title": "Authorization Matrix (2023-05)", "article": "Approving expense > >$25K up to $50K", "version_date": "2023-05-11", "version_date_before": false, "source_url": "https://gitlab.com/gitlab-com/www-gitlab-com/-/blob/0a3de833754144dc4d448814e2edbcaed0883f35/
  text: 검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다). | - Authorization Matrix (2023-05) > Legal Contracts > Non standard terms > $500k annual revenue [1] | - Authorization Matrix (2023-05) > Approving Payment > >$0k up to $500k [2][4][3] | 기준일: 2026-11-10 |  | 기준일 2026-11-10 · 근거 판 날짜 2023-05-11 · 출처: GitLab Handbook (CC BY-SA 4.0, 수정됨)
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'attribution']
== r1_refuse_purchase.json | Q: 구매 승인에는 어떤 승인자가 필요한가요?
  kind=refuse code=no_results citations=0 seconds=0.4 cost=0.0
  text: 핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'code']
== r2_refuse_lunch.json | Q: 오늘 점심 메뉴 추천해줘
  kind=refuse code=no_results citations=0 seconds=0.1 cost=0.0
  text: 핸드북과 관련 없는 질문이라 답하지 않습니다.
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'code']
== r3_saas_30k.json | Q: 외부 SaaS를 도입하려고 합니다. 계약 금액이 3만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  kind=refuse code=no_results citations=0 seconds=0.6 cost=0.0
  text: 핸드북에서 질문에 답할 충분한 근거를 찾지 못해 답하지 않습니다.
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'code']
== r4_saas_100k.json | Q: 외부 SaaS를 도입하려고 합니다. 계약 금액이 10만 달러라면 업무 승인자와 재무 승인자는 누구인가요?
  kind=refuse code=no_results citations=0 seconds=0.1 cost=0.0
  text: 검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다.
  done keys: ['answer_id', 'kind', 'as_of', 'usage', 'code']
```

## 서버 로그에서 가려낸 데모 재생 경고

```text

api-1  | INFO backend.services.demo_seed: 로컬 데모 계정 2개를 시드했다(아이디: demo-user, demo-admin)
api-1  | WARNING backend.admin_api: 최고 관리자 설정(PROVENA_OWNER_LOGIN_ID)이 없어 사용자 관리를 닫았다
api-1  | WARNING backend.services.demo_replay: 데모 재생: 녹화 응답이 없어 결정적 가짜 응답을 씁니다(역할 answer_fast, 녹화 96건, 폴더 /app/data/demo_replay). 이 메시지는 한 번만 냅니다.
api-1  | INFO backend.rag.retrieve.search: 검색 방식을 dense_ko로 내림: demo_no_record
api-1  | WARNING backend.rag.retrieve.search: 임베딩 API 키가 없어 검색하지 않음(no_key)
api-1  | INFO backend.rag.retrieve.search: 검색 방식을 dense_ko로 내림: demo_no_record
api-1  | WARNING backend.rag.retrieve.search: 임베딩 API 키가 없어 검색하지 않음(no_key)
```
