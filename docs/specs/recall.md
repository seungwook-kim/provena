# Spec — 답변 리콜 (F-02)

## Why

- **페르소나**: 개발자(주 사용자)와 플랫폼팀 정책 관리 담당(관리자).
- **상황**: 개발자가 보안 취약점 이슈를 패치 후 며칠 뒤 공개하는지 물어 "30일"이라는 답을 받고 그대로 일했다. 그 뒤 정책이 바뀌어 "90일"이 되었다(2026-06-29 커밋). 정책을 고친 관리자는 누가 예전 기준으로 일하는지 모른다.
- **문제**:
  1. 정책·런북이 바뀌어도 예전에 받은 답(AI 답 포함)은 그대로 남아 바뀐 절차를 모르고 일하게 된다 (이 부분은 가설이다. "낡은 런북이 장애를 일으켰다"는 직접 통계는 찾지 못했다)
  2. 개발자 포털 정보의 정확성을 의심하는 비율이 50%이고, 완전히 신뢰하는 비율은 3%다 (Port 2025)
  3. 기존 제품(Guru, Glean, Notion)은 문서가 낡으면 문서 담당자에게 알린다. 이미 나간 답을 받은 사람에게 알린다는 내용은 찾지 못했다 (문서 기준)
- **측정 지표**: 답변 리콜 재현율·정밀도, 함께 볼 정책 후보 정밀도, 링크 추출 정확도

## Goal

- **해결 목표**: 정책 변경을 감지하면 그 섹션을 근거로 했던 과거 답을 다시 검증하고, 결론이 바뀐 답만 받은 사람과 업무시스템(웹훅)에 정정으로 알린다. 링크로 연결된 다른 정책은 관리자에게 "함께 볼 정책"으로 알린다.
- **성공 기준** (제안 기준이며 D0에 합의하면 동결한다)
  - 실제 개정 커밋 전후 판으로 만든 시험 답변에서 결론이 바뀐 답을 찾는 재현율 0.80 이상, 정밀도 0.80 이상
  - 함께 볼 정책 후보: 사람이 정한 연결 정책과 대조해 정밀도를 재서 공개
  - 링크 추출: 참조 그래프 간선을 원문과 대조해 정확도를 재서 공개
  - 웹훅 전송 실패 시 재시도하고 모든 시도를 기록
- **Out of Scope**: 틀린 답을 자동으로 고쳐 다시 보내기(알림까지만), 메일·메신저 직접 발송(웹훅까지만), 정책을 바꿀 때 영향 건수를 미리 세는 시뮬레이터(F-05), 최종 판단 대행

## What

**Happy Path**
1. 자동 수집이 마지막으로 받은 커밋 이후의 새 커밋만 받아, 바뀐 파일만 다시 파싱한다.
2. 같은 페이지의 두 커밋을 제목 경로 기준으로 정렬해 본문을 비교하고, 바뀐 섹션 목록(`ChangedArticle`)을 만든다.
3. 서식만 바뀐 커밋(링크·오탈자)은 표시만 하고 리콜에 넘기지 않는다.
4. 바뀐 섹션이 리콜 그래프에 전달된다(`POST /webhooks/regulation-updated`).
5. `citations`에서 그 섹션을 인용한 과거 답을 찾는다(코드). 이미 신판 날짜 이후 기준일로 받은 답은 영향이 없다고 보고 판정하지 않는다.
6. 개정 전후 섹션을 비교해 그 답의 결론이 바뀌었는지 판정한다(LLM).
7. 결론이 바뀐 답만 `RecallNotice`를 만든다. 받은 사람은 `GET /recalls`에서 바뀐 답, 개정 전후 섹션, 설명을 본다.
8. 등록된 업무시스템 웹훅 주소로 `RecallNotice`를 보낸다. 실패하면 재시도하고 기록한다.
9. 링크 참조 그래프로 연결된 다른 정책을 찾아 `MaintenanceCandidate`("함께 볼 정책" 후보)를 만들고, 관리자가 확인 필요·불필요를 판단한다.
10. 받은 사람이 확인 표시(`ack`)를 한다.

**Edge Cases** (최소 5개 + 처리 방식)

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 판정 LLM 응답이 깨졌다 | 알림을 보낸다(재현율 우선). 설명 맨 앞에 "[판정 실패, 확인 필요]"를 붙이고 실패 목록에도 남긴다 |
| EC-02 | 서식만 바뀐 커밋(링크·오탈자) | 바뀐 것으로 표시만 하고 리콜에 넘기지 않는다 |
| EC-03 | 답의 기준일이 신판 날짜 이후다 | 영향이 없다고 보고 판정하지 않는다 |
| EC-04 | 개정은 있었지만 결론이 안 바뀌었다 | 정정 알림을 보내지 않는다 (결론이 바뀐 답만 알린다) |
| EC-05 | 업무시스템 웹훅 수신이 실패한다 | 2xx가 아니거나 연결이 실패하면 최대 3번(`RECALL_WEBHOOK_MAX_TRIES`) 시도한다. 1초(`RECALL_WEBHOOK_BACKOFF_S`)부터 두 배씩 기다리며, 시도 한 번의 제한 시간은 5초(`RECALL_WEBHOOK_TIMEOUT_S`)다. 세 값의 기본값은 `backend/graph/recall/webhook.py:36`(3, 1.0, 5.0)이고 환경변수가 비면 이 값을 쓴다. 시도마다 상태 코드·오류 종류·시각을 `webhook_deliveries.attempts`에 남긴다. 그래도 실패하면 `failed`다. 비밀값이 비어 있으면 로컬 데모에서만 서명 없이 보내고 그 밖에서는 보내지 않고 `failed`(`secret_missing`)로 남긴다 |
| EC-06 | 같은 개정이 두 번 들어오거나 수집이 중복 실행된다 | 중복 실행을 막고, 같은 답에 같은 신판으로는 알림을 한 번만 만든다 |
| EC-07 | 그 섹션을 인용한 과거 답이 없다 | 수신자 알림은 0건이다. 연결 정책 후보는 따로 만든다 |
| EC-08 | 비공개 주소로만 가는 링크 | 끝점이 없는 간선이라 참조 그래프에서 뺀다. 후보로 알리지 않는다 |
| EC-09 | 페이지가 삭제됐다 | 파일 목록을 완전히 받았을 때만 삭제를 반영한다 |
| EC-10 | 서비스 키 없이 `/webhooks/regulation-updated`를 호출한다 | 401 |
| EC-11 | 일반 사용자가 다른 사람의 리콜 알림이나 전체 후보 목록을 요청한다 | 내 알림만 보인다. 남의 알림 한 건을 직접 요청하면 404다. 전체 알림과 후보 목록은 관리자만 본다 |
| EC-12 | 판정 확신도가 낮다(`RECALL_MIN_CONFIDENCE`, 기본 0.5 미만) | 사용자 알림과 웹훅을 보내지 않고 관리자 검토함에 둔다. 관리자가 풀어 주면(`release`) 사용자에게 보이고 웹훅이 나간다 |
| EC-13 | 판정 설명에 판정 지시문, `CANARY-` 같은 표지, 다른 사용자의 id·질문, 개정 전후 본문 속 지시 문장에서 옮겨 온 표식·문장(출력 검사 `GRAPH_SCRUB_OUTPUT`)이 섞인다. 판정 입력의 개정 전후 본문과 섹션 제목에는 입력 정화(`GRAPH_SANITIZE_INPUT`)가 걸린다 | 설명을 "[판정 실패, 확인 필요]"로 시작하는 고정 문장으로 바꾸고 실패 목록에 남긴다. 알림은 간다 |
| EC-16 | 판정은 "결론 그대로"인데 코드 규칙은 금액·승인자·기한·권한 변경이나 섹션 신설·삭제라고 본다 | 알림을 버리지 않고 `review_reason=judge_disagrees_with_rule`로 관리자 검토함에 둔다. 설명 맨 앞에 "[판정 실패, 확인 필요]"를 붙이고 실패 목록에 남기며, 사용자와 웹훅에는 나가지 않는다. 문구만 바뀐 개정은 알림이 없다 |
| EC-14 | 변경 감시를 멈췄다(`PUT /changes/monitoring`, `paused`) | 정해진 시각의 증분 수집은 그날의 실행 자리(슬롯)를 차지하지 않고 아무것도 하지 않고 끝난다. 명령줄 처리기도 멈춘다(`--force`로 무시) |
| EC-15 | 권한 확인에 실패하거나 사용자 그룹이 그 섹션의 권한 그룹에 없다(F-06) | 그 사용자에게는 알림을 보이지 않는다. 문서 권한은 지금 모두 공개(빈 그룹)이고, 연결 지점(`backend/graph/recall/acl.py`)만 구현했다 |

## How

```
POST /webhooks/regulation-updated
인증: 서비스 키 (수집 쪽에서 호출)

인증: 서비스 키. `X-Service-Key: <키>` 또는 `Authorization: Bearer <키>` (환경변수 `SERVICE_API_KEY`, 비어 있으면 항상 401). 본문을 읽기 전에 키부터 본다.

요청 바디: ChangedArticle 한 건, 또는 1~100건 목록
{
  "rule_seq": int,              // 페이지 id
  "article": string,            // 바뀐 섹션의 제목 경로
  "old_version_date": string,   // YYYY-MM-DD (신설이면 빈 문자열)
  "new_version_date": string,   // YYYY-MM-DD (삭제된 쪽 전체면 빈 문자열)
  "change_type": "added" | "removed" | "modified"
}

응답 성공 (202 Accepted): {"accepted": int, "event_ids": [string]}. 리콜 판정은 응답 뒤 백그라운드로 돈다
응답 실패:
400 요청 형식 오류 (깨진 JSON, 모르는 칸, 날짜·변경 종류 형식 오류, 빈 목록, 100건 초과)
401 서비스 키 없음/틀림
500 내부 서버 오류
```

```
GET  /recalls                  {items, unread}. 관리자는 전체 + review_queue + candidates + judge_failures   로그인
GET  /recalls/{id}             알림 한 건 (남의 알림·검토함 알림은 404, 관리자는 모두)   로그인
POST /recalls/{id}/ack         확인 표시, 갱신된 알림을 돌려준다 (본인만)         로그인, CSRF
POST /recalls/{id}/feedback    {useful, reason} → {notice_id, useful, counts}     로그인, CSRF
POST /recalls/{id}/review      {action: release | dismiss}, 검토함에 없으면 409    관리자, CSRF
GET  /recalls/feedback-stats   유형별 의견 집계                                  관리자
GET  /recalls/digests          하루 요약 목록 (본인, 관리자는 전체)                 로그인
POST /recalls/digest/flush     하루 요약 보내기 (?day=)                          관리자, CSRF
POST /recalls/process-pending  쌓인 변경 한 번 처리                              관리자, CSRF
POST, GET /webhook-subscriptions  업무시스템 웹훅 주소 등록(201, 주소·secret_ref 검사, 틀리면 400)·조회   관리자
GET  /webhook-deliveries       전송 기록 (시도별 상태 코드·오류 종류)              관리자
GET  /maintenance-candidates   연결 정책 후보 목록 (?status=)                    관리자
POST /maintenance-candidates/{id}  {status: needed | not_needed}, 없으면 404     관리자, CSRF
POST /impact-preview           바뀐 섹션(changes) 또는 두 판(pages)의 영향 미리보기. 저장·알림·웹훅 없음   관리자, CSRF
GET  /changes                  변경 감시 목록 {items, last_run, more, monitoring} (?since=&limit=&offset=)   로그인
GET  /changes/{event_id}       한 건과 개정 전후 본문                              로그인
GET, PUT /changes/monitoring   변경 감시 켜기·멈추기 {status: active | paused}      조회 로그인, 변경 관리자·CSRF
```

RecallNotice (알림 한 건, `GET /recalls` 응답과 웹훅 본문이 같다. 계약 모델(`backend/schemas/recall.py`)의 칸에 화면용 칸을 더한 모양이다):

```
{
  "notice_id": string,
  "answer_id": string,
  "user_id": string,
  "thread_id": string,
  "question": string,
  "answer_excerpt": string,
  "changed": ChangedArticle,
  "conclusion_changed": boolean,
  "explanation": string,       // 판정 실패 시 맨 앞에 "[판정 실패, 확인 필요]"
  "severity": "high" | "low",  // 금액·승인자·기한·권한이 바뀌면 high, 문구만 바뀌면 low
  "confidence": number | null, // 0~1, 판정 실패면 null
  "needs_review": boolean,
  "acked": boolean,
  "created_at": string,
  "source_url": string | null,
  "old_text": string | null,   // 개정 전 섹션 (신설이면 null)
  "new_text": string | null    // 개정 뒤 섹션 (삭제면 null)
}
```

MaintenanceCandidate (함께 볼 정책):

```
{
  "candidate_id": string,
  "upper_rule": string,         // 개정된 정책 페이지 (링크로 연결된 쪽)
  "upper_version_id": string,
  "rule_seq": int,              // 영향받는 다른 정책 페이지
  "article": string,
  "reason": string,             // 링크 그래프에서 찾은 근거
  "status": string              // 확인 필요 / 불필요 판단 (decided_by 기록)
}
```

업무시스템 쪽 수신 형식:

```
POST {등록한 업무시스템 주소}/webhooks/recall
본문: RecallNotice JSON 그대로
헤더: X-Signature: sha256=<HMAC-SHA256(secret, 원본 본문) 16진수>
```

- secret은 `webhook_subscriptions.secret_ref`가 가리키는 환경변수(`RECALL_WEBHOOK_SECRET` 또는 `RECALL_WEBHOOK_SECRET_<이름>`)의 값이고 저장소에 적지 않는다. 주소는 http·https만 받고, 로컬 데모가 아니면 https만, 내부망·메타데이터 주소는 막는다.
- 하루 요약(`RECALL_DIGEST=daily`)이면 알림마다 보내지 않고 사용자별 요약 한 건(`{"type": "recall_digest", "digest_id", "day", "count", "high", "low", "notices": [...]}`)으로 묶어 같은 서명 규칙으로 보낸다.
- 판 비교: 같은 페이지의 두 커밋을 제목 경로로 정렬해 본문을 비교한다. 리콜은 개정 전후 같은 섹션 원문이 필요하므로, 검색과 따로 섹션 단위 조회(`get_section(rule_seq, article, as_of)`)를 쓴다.
- 연결 정책: 핸드북 페이지 사이 링크로 만든 참조 그래프(`rule_links`: from_rule, to_rule, kind)를 쓴다. 비공개 주소로 가는 링크는 뺀다.
- 증분 수집(가산 자동화): 마지막 커밋 이후 새 커밋만 받고, 중복 실행을 막고, 정해진 시각 실행 기록과 실패 알림을 남긴다. 바뀐 섹션은 `changed_articles`에 쌓이고, `python -m backend.graph.recall.process_pending`이나 관리자 `POST /recalls/process-pending`이 같은 처리 경로로 리콜에 넘긴다(`event_key`는 수집의 `event_id`와 같다).
- git 없는 변경 감지(F-07): `python -m backend.rag.ingest.snapshot_diff`가 두 시점 문서 묶음을 섹션 단위로 비교해 같은 형식의 바뀐 섹션 목록을 만든다. `--feed`를 주면 `changed_articles`에 넣고 이후는 같은 경로로 처리한다.
- 판정기: LLM 키(`LLM_API_KEY`)가 있으면 LLM 판정(`recall_explain` 작업, `mail-templates` Skill, 답마다 따로 비용 집계), 키가 없거나 데모 모드이면 섹션 낱말 차이 규칙 판정이다. 규칙 판정은 재현율을 앞세워 정밀도가 LLM보다 낮을 수 있다.
- 알림 피로(F-08): 중요도(high, low)와 확신도(0~1)를 붙인다. 확신도가 낮으면 검토함(EC-12)으로 보내고, "필요 없음" 의견이 같은 사용자·섹션·변경 유형에 `RECALL_FEEDBACK_THRESHOLD`(기본 2, 0이면 끔)만큼 더 쌓이면 다음 알림 중요도를 한 단계 낮추고 두 배면 검토함으로 보낸다.
- 저장소: `RECALL_STORE=postgres`와 `DATABASE_URL`이 함께 있으면 Postgres, 아니면 메모리(서버를 다시 띄우면 사라진다).
- 테이블(`db/120_answers_recall.sql`, 다시 실행해도 된다): `answers`(인용 검사 결과는 `grounding`, `skills_used` 칸), `citations`(answer_id, chunk_id, version_id, rule_seq, article, version_date, source_url), `recall_events`(같은 개정은 한 번만 처리), `recall_notices`(UNIQUE (answer_id, event_key)로 같은 답·같은 개정은 한 건. 사용자 의견은 `feedback_*` 칸이다), `maintenance_candidates`, `webhook_subscriptions`(sub_id, url, secret_ref, active), `webhook_deliveries`(delivery_id, sub_id, notice_id, kind, status, tries, attempts), `recall_digests`, `change_monitoring`. 모든 표에 행 수준 보안을 켠다. `citations`가 리콜의 핵심이다. 답과 근거 판(커밋)을 묶어 두어야 영향받는 답을 찾을 수 있다.
- 시험 데이터: 핸드북 git 이력에서 고른 "답이 바뀌는 규칙 변경" 커밋의 개정 전후 판 쌍(고른 절에 최근 12개월 커밋 1,094건 중 12건 확인). 예: 취약점 이슈 공개 시점 30일 → 90일(2026-06-29, `4667e540`), Tier 2 호출 무응답 시 IMOC에게 전달(2026-01-26, `bf53a691`), 위험도 중간 공급사 승인자(2024-01-23, `0c787db1`), 권한표 2021년 개정 커밋.

## AC (Given-When-Then)

**AC-01 · 결론이 바뀐 답을 받은 사람에게 정정한다**
- GIVEN: 개정 전 판을 근거로 "공개 시점은 30일"이라는 답이 `answers`와 `citations`에 저장되어 있다 (사용자 A)
- WHEN: 해당 섹션의 개정 커밋(`4667e540`)이 수집되어 `ChangedArticle`이 전달된다
- THEN: A에게 `RecallNotice`(`conclusion_changed=true`, 개정 전후 섹션과 설명 포함)가 만들어져 `GET /recalls`에 보이고, 등록된 웹훅 주소로 전송된다

**AC-02 · 결론이 안 바뀐 답과 서식만 바뀐 커밋은 알리지 않는다**
- GIVEN: 같은 섹션을 인용한 답이 있고, 개정이 링크·오탈자만 바꿨거나 결론을 바꾸지 않는다
- WHEN: 리콜 판정이 실행된다
- THEN: 해당 답에 대한 정정 알림이 생기지 않는다

**AC-03 · 웹훅은 서명과 함께 가고, 실패하면 재시도·기록한다**
- GIVEN: 업무시스템 웹훅 주소가 등록되어 있다
- WHEN: 리콜 알림이 생겨 전송하는데 수신 쪽이 오류를 돌려준다
- THEN: 요청에 `X-Signature: sha256=<HMAC-SHA256>` 헤더가 있고, 재시도한 횟수와 최종 상태가 `webhook_deliveries`에 남는다

**AC-04 · 연결 정책은 관리자에게만 후보로 알린다**
- GIVEN: 개정된 정책 페이지가 링크로 다른 정책 페이지와 연결되어 있다
- WHEN: 개정이 처리된다
- THEN: 관리자는 `GET /maintenance-candidates`에서 연결 정책 후보와 근거(링크)를 보고 확인 필요·불필요를 판단할 수 있다. 일반 사용자에게는 보이지 않는다

**AC-05 · 판정이 실패해도 알림은 간다**
- GIVEN: 판정 LLM 응답을 해석할 수 없다
- WHEN: 리콜 판정이 실행된다
- THEN: 알림이 가고 설명 맨 앞에 "[판정 실패, 확인 필요]"가 붙으며, 실패 목록에도 남는다

**AC-06 · 서비스 키 없는 변경 알림은 받지 않는다**
- GIVEN: 서비스 키가 없는 호출자
- WHEN: `POST /webhooks/regulation-updated`를 호출한다
- THEN: 401을 돌려주고 리콜 판정은 시작되지 않는다
