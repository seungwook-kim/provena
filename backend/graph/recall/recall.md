# backend/graph/recall/ : 답변 리콜과 변경 감시 (F-02, F-05, F-07, F-08)

## 이 폴더가 하는 일

바뀐 섹션을 인용한 예전 답을 찾아 결론이 바뀌었는지 판정하고, 받은 사람과 업무시스템(웹훅)에 알린다. 판정 실패는 "확인 필요"로 알린다. 링크로 연결된 다른 정책은 관리자에게 "함께 볼 정책" 후보로 만든다. 판정은 답 하나마다 따로 한다(사용자 사이 내용이 섞이지 않는다).

- 주인: 김승욱
- 입력: 바뀐 섹션 목록(`ChangedArticle`). 증분 수집이 `changed_articles`에 쌓은 줄, 또는 `POST /webhooks/regulation-updated`
- 출력: 리콜 알림(`RecallNotice` + 화면용 칸), 함께 볼 정책 후보, 웹훅 전송 기록, 하루 요약
- 요구사항: `docs/PRD.md` F-02, F-05, F-06, F-07, F-08, 6-4 자동화 / `docs/specs/recall.md`

## 모듈

| 파일 | 하는 일 |
|---|---|
| `graph.py` | 리콜 그래프(`find_answers` -> `judge` -> `notify`). 기준일이나 인용한 판이 새 판 날짜 이후인 답은 판정하지 않는다. 설명 검사(`guard_explanation`)도 여기서 건다 |
| `notice.py` | 판정 프롬프트(`recall_explain`, `mail-templates` Skill), `is_affected`, `judge_answer`, `guard_explanation` |
| `judge.py` | `LLMJudge`(LLM 키가 있을 때), `RuleJudge`(키가 없거나 데모 모드, 섹션 낱말 차이 규칙), `default_judge` |
| `severity.py` | 중요도(high, low)와 확신도(0~1). 금액·승인자·기한·권한이 바뀌면 high, 문구만 바뀌면 low이고 확신도에 상한을 둔다 |
| `service.py` | `RecallService`: 개정 한 건 처리(중복 방지, 저장, 후보 만들기, 웹훅 보내기), 알림 JSON 모양(`notice_json`) |
| `store.py` | 리콜 저장소. `InMemoryRecallStore`(기본), `PgRecallStore`(`db/120_answers_recall.sql`) |
| `webhook.py` | 업무시스템으로 보내는 웹훅: 서명, 재시도, 전송 기록, 주소 검사 |
| `feedback.py`, `digest.py` | 사용자 의견("필요 없음")으로 같은 유형의 알림 줄이기, 하루 요약 |
| `maintenance.py` | 링크 그래프로 "함께 볼 정책" 후보 만들기(개정 하나에 최대 50개) |
| `monitor.py` | 변경 감시 목록·실행 기록·감시 켜기/멈추기(`InMemoryChangeStore`, `PgChangeStore`) |
| `acl.py` | 문서 권한 연결 지점(F-06). 기본은 모두 공개이고, DB가 있으면 `chunks.acl`을 읽는다 |
| `impact.py` | 변경 전 영향 미리보기(F-05). 저장·알림·웹훅 없는 드라이런 |
| `process_pending.py` | `changed_articles.status = pending` 줄을 리콜에 넘기는 처리기(명령줄) |
| `runtime.py` | 앱 시작에서 저장소와 서비스를 만든다(`make_answer_store`, `open_recall_runtime`) |

`backend/api/recalls.py`, `backend/api/changes.py`가 이 모듈들을 HTTP로 내보낸다(경로는 `docs/specs/recall.md`). git 없는 변경 감지(F-07)는 `backend/rag/ingest/snapshot_diff.py`다.

## 환경변수

| 이름 | 기본값 / 동작 |
|---|---|
| `SERVICE_API_KEY` | `/webhooks/regulation-updated`의 서비스 키. 비면 그 경로는 항상 401 |
| `RECALL_STORE` | `postgres`이고 `DATABASE_URL`이 있으면 Postgres 저장소. 비우면 메모리(서버를 다시 띄우면 사라짐) |
| `RECALL_MIN_CONFIDENCE` | 0.5. 확신도가 이보다 낮은 알림은 관리자 검토함으로 가고 사용자에게 보이지 않으며 웹훅도 나가지 않는다 |
| `RECALL_DIGEST` | 비움 또는 `immediate`면 알림마다 바로 웹훅, `daily`면 하루 요약 한 건으로 묶는다 |
| `RECALL_FEEDBACK_THRESHOLD` | 2. 같은 사용자·섹션·변경 유형에서 "필요 없음"이 "도움 됨"보다 이 수만큼 많으면 중요도를 한 단계 낮추고, 두 배면 검토함으로 보낸다. 0이면 끈다 |
| `RECALL_WEBHOOK_SECRET`, `RECALL_WEBHOOK_SECRET_<이름>` | 웹훅 서명 키. 비면 로컬 데모(`PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`)에서만 서명 없이 보내고, 그 밖에서는 보내지 않고 전송 기록에 `failed`(`secret_missing`)로 남긴다 |
| `RECALL_WEBHOOK_MAX_TRIES`, `RECALL_WEBHOOK_BACKOFF_S`, `RECALL_WEBHOOK_TIMEOUT_S` | 3번, 1.0초(이후 두 배씩), 5초 |

## 처리기 실행

```
python -m backend.graph.recall.process_pending [--limit 50] [--force]
```

`changed_articles`에서 `pending`인 줄을 오래된 순으로 처리하고 `sent`(또는 실패하면 `failed`)로 바꾼다. 이미 처리한 개정은 다시 판정하지 않는다. 변경 감시가 `paused`이면 아무것도 하지 않는다(`--force`는 무시). 관리자 `POST /recalls/process-pending`은 감시 스위치와 무관하게 한 번 처리한다. 스냅샷 비교 결과를 넣으려면 `python -m backend.rag.ingest.snapshot_diff --feed`를 쓴다.

## 한계

- 규칙 판정(`RuleJudge`)은 재현율을 앞세워 정밀도가 LLM 판정보다 낮을 수 있다. 문구만 달라진 개정은 낮은 확신도로 검토함에 간다.
- 판정 설명은 저장 전에 검사한다. 설명이 판정 지시문(20자 이상 겹침)이나 `CANARY-` 표지를 담거나 다른 사용자의 id·질문을 담으면 "[판정 실패, 확인 필요]"로 시작하는 고정 문장으로 바꾸고 실패 목록에 남긴다.
- 판정이 "결론 그대로"라고 해도 코드 규칙(`severity.py`)이 금액·승인자·기한·권한 변경이나 섹션 신설·삭제라고 보면(개정 본문에 심어 둔 "영향 없음" 문장에 판정이 따랐을 수 있다) 알림을 버리지 않는다. `needs_review`, `review_reason="judge_disagrees_with_rule"`, 설명 맨 앞 "[판정 실패, 확인 필요]"로 관리자 검토함에 두고 실패 목록에 남기며, 사용자 목록과 웹훅에는 나가지 않는다. 문구만 바뀐 개정은 이전처럼 알림이 없다.
- 문서 권한(F-06)은 연결 지점만 있다. 지금 `chunks.acl`이 모두 비어 있어 모두 공개로 동작하고, 권한 확인에 실패하면 그 알림은 숨긴다.
- 함께 볼 정책 후보의 이유는 코드로만 만든다(LLM 초안 없음). 판정 비용 집계는 답마다 따로 한다.
- 영향 미리보기의 입력은 바뀐 섹션 목록(`changes`)과 두 판(`pages`)이다. git 커밋이나 unified diff를 직접 받지는 않는다.
- 메모리 저장소는 프로세스가 끝나면 사라진다. 운영은 `RECALL_STORE=postgres`와 `db/120_answers_recall.sql` 적용이 필요하다.
- 웹훅 IP 고정(J-12)은 프록시를 거치지 않는 직접 연결을 전제로 한다. `HTTPS_PROXY` 환경변수가 있으면 프록시 터널(httpcore `http_proxy`)이 `sni_hostname`을 쓰지 않고 IP로 TLS를 맺어 인증서 이름 불일치로 전송이 실패한다(내부로 새지 않고 막히는 쪽 실패). 주소가 IP로 바뀌어 있어 `NO_PROXY`의 이름 예외도 걸리지 않는다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-15 | 박진형 (jinyeong-731) | `impact.py` 영향 미리보기의 만든 날(`generated_on`) 기본값을 한국 날짜(`today_kst`)로(놓친 것 D-15, 조장 지시로 처리. 문제 기록은 `backend/graph/graph.md` G-002). 하루 요약 날짜(`digest.py` `_today`)는 중복 방지 id와 웹훅 본문에 들어가는 값이라 UTC 그대로 둠. 시험 `tests/test_today_kst.py::test_impact_preview_generated_on_is_korean_today` | #160 |
| 2026-11-13 | 박진형 (jinyeong-731) | `impact.py` `render_markdown`: 섹션 이름(article)이 비었거나 공백뿐이면 표에 `(제목 없는 구간)`으로 보임(표시만 바꿈, 빈 article은 `find_by_article`의 짝짓기 키라 리포트 JSON 값은 그대로). 시험 `tests/test_impact_empty_section.py` | #157 |
| 2026-11-11 | 박진형 (jinyeong-731) | `impact.py`에 `post_mr_comment`(영향 미리보기 요약을 GitLab MR 댓글로 게시, `GITLAB_API_URL`(https만)·`GITLAB_TOKEN`이 없으면 건너뜀)와 `--post-mr` 옵션 추가(I-08). 시험 `tests/test_recall_impact_comment.py`(네트워크 호출 없음) | #132 |
| 2026-11-11 | 박진형 (jinyeong-731) | 리뷰 후속 J-12(DNS 재바인딩): 웹훅을 보낼 때 주소 검사에서 나온 공인 IP 하나로 직접 연결한다(`check_target_url`이 IP를 돌려주고 `pin_request`가 host를 IP로 바꿈, `Host` 헤더·TLS SNI는 원래 이름, 리다이렉트 따라가지 않음). 단건·하루 요약 둘 다 같은 전송 함수라 한 곳에서 처리. 시험 `tests/test_recall_webhook.py` | #131 |
| 2026-11-11 | 박진형 (jinyeong-731) | 놓친 것 J-12(웹훅 주소를 실제로 풀어 나온 IP가 내부·루프백·링크로컬이면 등록·전송 때 막음, 정수·16진수 표기 포함), J-13(웹훅 본문에서 user_id·question·answer_excerpt·thread_id·acked 제거) | #131 |
| 2026-11-10 | 김승욱 (Claude Code) | 리콜 판정 입력의 개정 전후 본문과 섹션 제목에 입력 정화, 판정 설명에 출력 검사(`guard_explanation(sources=...)`, 이유 `injected_instruction`) 추가(사전 등록 62.26) | - |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #116) 합친 표(DB 재정렬)에 맞춰 `store.py`, `maintenance.py`를 고침 | #116 |
| 2026-11-09 | 김승욱 (Claude Code) | 리콜 그래프·판정기·저장소·웹훅·검토함·하루 요약·의견·함께 볼 정책 후보·변경 감시·영향 미리보기와 라우터를 구현하고 `db/120_answers_recall.sql`을 더했다. 판정 설명 검사(지시문·표지·다른 사용자 값)와 판정·코드 규칙 불일치 교차 검사를 넣었다. 시험은 `tests/test_recall_*.py`, `test_api_recalls.py`, `test_api_changes.py`, `test_snapshot_diff.py`와 실제 Postgres용 `test_recall_pg.py`(`PROVENA_TEST_DATABASE_URL`이 있을 때만) | 미정 |
| 2026-11-09 | 김승욱 (기록: 박진형) | (보충, PR #80) 변경 감시 분포를 전체 기준으로 표시: `monitor.py`가 종류별 전체 건수를 세도록 고침(`GET /changes`의 `total`·`counts`) | #80 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| A-001 | 2026-11-13 | 김승욱 | 영향 미리보기 결과 표의 '섹션' 칸이 빈 값으로 나옴(놓친 것 11/13 새로 발견 6, `impact.py` `render_markdown`) | 어느 구간이 바뀌었는지 표에서 알 수 없음 | 박진형 | 해결 | 2026-11-13 | `tests/test_impact_empty_section.py` 4개(표에는 `(제목 없는 구간)`, 보고서 JSON의 article은 빈 값 그대로) |
