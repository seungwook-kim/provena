# 질의-색인 대조표와 로컬 합성 DB EXPLAIN (재정렬 후 구조)

- 대상: 로컬 docker `provena-dbre-pg`의 데이터베이스 `explain_db`(운영 아님). `db/*.sql` 전체와 `db/109_realign.sql`을 적용한 뒤 합성 데이터를 넣었다.
- 합성 데이터 규모(운영 2026-11-10 조회와 맞춤): chunks 30,171행(전부 `voyage-4` 1024차원, 현재 판 23,095 + 닫힌 판 7,076), versions 1,798(현재 1,516 + 닫힌 282), docs 1,516, query_translations 692, threads 850, answers 315, citations 559, recall_events 318, changed_articles 318, maintenance_candidates 964(전부 pending), recall_notices 3, approvals 11, issue_tables 3, token_revocations 35, users 2. 크기는 chunks 240 MB(운영 264 MB), HNSW 65 MB(운영 64 MB).
- 한계: 분포가 균일하다(org 6종 각 약 1/6, 사용자 3명 각 1/3). `chunk_id`가 판마다 유일하고(운영은 판 사이에 공유), `link_targets`와 `line_start`는 비어 있었다(GIN 시험에서만 3,352행에 값을 넣었다). 작은 표는 계획기가 Seq Scan을 고르는 것이 정상이라 "색인을 탄다"는 EXPLAIN으로 직접 보이지 않는 곳이 많다. 그 곳은 색인 정의와 질의 조건을 대조해 판정했다(각 행에 표시).
- 실행 방식: SELECT에만 `EXPLAIN (ANALYZE, BUFFERS)`를 1회 실행했다. INSERT/UPDATE/DELETE는 실행하지 않았고 WHERE 조건을 같은 조건의 SELECT로 바꿔 쟀거나 계획만 봤다. 시간은 Execution Time이다.
- 조사 범위: ackend/, vals/(결과 폴더 제외)의 SQL 약 150문장. scripts/에는 파일이 없다. LangGraph 표의 SQL은 라이브러리 내부라 포함하지 않았다.

## 0. 운영 검색 경로

- 운영 Cloud Run 환경변수(`live_00032.json`)에는 `SEARCH_HNSW`가 없다. 그러나 앱 기동 때 `backend/main.py:299`가 `service_profile`로 `SEARCH_HNSW=1`을 채우므로(`service_profile.py:66`) `/chat`의 벡터 검색은 HNSW 질의(`search.py:351-355`)를 보낸다. 실제 프로세스 값은 보지 못했고 코드와 환경변수 목록으로 추론한 것이다.
- 운영 `chunks_emb_hnsw_half`는 64 MB이고 `idx_scan` 66,239로 조회됐다(2026-11-10 운영 읽기 전용 조회에서 읽은 값).

## 1. 벡터 질의 (search.py vector_top)

`ef_search=200`, `iterative_scan=strict_order`, k=5.

| 조합 | 전수 비교(SEARCH_HNSW 꺼짐) | HNSW(운영 경로) |
|---|---|---|
| org 없음, as_of 없음(현재 판) | Seq Scan chunks 30,171행 + Hash Join + 정렬, 158.9 ms (LIMIT 100은 188.6 ms) | `chunks_emb_hnsw_half` Index Scan 5행 + `versions_one_current` + `docs_pkey`, 1.08 ms (LIMIT 100은 1.80 ms) |
| org=hr, as_of 없음 | versions Seq Scan 1,516행(282 버림), docs Seq Scan(1,263 버림), chunks는 `chunks_page` 253회 반복 + top-N 정렬, 27.9 ms | HNSW를 쓰지 않고 전수 계획과 같다, 29.5 ms |
| org 없음, as_of=2026-10-15 | Seq Scan + versions 필터(282 버림), 188.3 ms | HNSW Index Scan 25행을 걷어 5개 채움(후보 20개가 versions 조건에서 탈락), 0.74 ms |
| org=hr, as_of=2026-10-15 | 위 org 계획과 같음, 32.8 ms | HNSW를 쓰지 않음, 32.5 ms |
| org 없음, as_of=2026-11-09(모두 현재 판) | 측정 안 함 | HNSW Index Scan 5행, 0.60 ms |
| org 없음, as_of=2026-09-01(닫힌 판만) | Seq Scan + versions 282행, 33.1 ms | HNSW를 쓰지 않음, `chunks_page` 282회 반복, 38.3 ms |
| org=hr, as_of=2026-09-01 | 측정 안 함 | HNSW를 쓰지 않음, 9.7 ms |

- org 필터가 있으면 HNSW 색인 스캔의 추정 비용(40,835)이 전수 계획(약 1,000)보다 높게 잡혀 색인을 쓰지 않는다. `enable_seqscan=off`로도 바뀌지 않았다. org가 `docs`에 있어 `chunks` 색인이 모르기 때문이다. 합성 분포 기준 29-33 ms이며 운영의 org 분포는 알지 못한다. 이 경우를 줄이려면 `chunks`에 org를 복사해 org별 부분 HNSW를 만드는 스키마 변경이 필요한데 효과를 운영 분포로 확인하지 못해 하지 않았다.
- 옛 판 행이 HNSW에 들어 있어도 현재 판 질의는 5행 만에 끝난다(옛 판 후보는 versions 조건에서 걸러지고 반복 스캔이 더 걷는다). 이 합성 데이터에서는 `chunks` 30,171행 중 7,076행이 옛 판이어도 1 ms 안팎이었다. 운영 실측은 `run_db_chunks_check.ps1` 결과가 필요하다.

## 2. 검색·수집 질의 (backend/rag, evals)

| file:line | 표 | 조건/정렬 | 색인 | EXPLAIN | 판정 |
|---|---|---|---|---|---|
| search.py:321, 328 | index_meta | id=1 (검색마다 generation 확인) | index_meta_pkey | Seq Scan 1행, 0.04 ms | 1행 표, 생략 |
| search.py:334 | chunks, versions, docs | 전체 JOIN, ORDER BY ord, chunk_id | pkey 들 | 전표 Seq Scan, 본문 없이 18.4 ms, 본문 포함 35.8 ms | 기동·generation 변경 때 전수 읽기가 의도 |
| search.py:351-355 | chunks, versions, docs | embedder, `_FILTER`, ORDER BY dist LIMIT n | chunks_emb_hnsw_half, versions_one_current, docs_pkey | 1장 | HNSW 경로 |
| search.py:364-368 | 같음 | 같음 (HNSW 꺼짐) | 거리용 색인 없음 | 1장 | 전수 비교가 의도 |
| search.py:377 | chunks | embedder, `ord % 211 = 3`, LIMIT 150 | 없음 | Seq Scan, 30,028행 버림, 10.1 ms | 기동 때 1회 |
| search.py:387-393 | chunks, versions, docs | rule_seq=ANY, `_FILTER`, NOT EXISTS | chunks_page | Bitmap Index Scan 126행, 1.25 ms | 충분 |
| search.py:404-406 | chunks, versions, docs | `strpos(lower(d.title or ' > ' or article), p) > 0` | 없음(식 검색) | Seq Scan 30,171행, 15-20 ms | 색인으로 줄일 수 없음, 15-20 ms |
| search.py:413-415 | chunks | rule_seq=ANY, `strpos(article,'$')`, `_FILTER` | chunks_page | 0.42 ms | 충분 |
| search.py:422-425 | chunks | unnest(chunk_id, version_id) | chunks_pkey | Index Scan, 0.17 ms | 충분 |
| search.py:432 | chunks | rule_seq, version_id, ORDER BY ord | chunks_page | 0.20 ms | 충분 |
| search.py:438-441 | chunks, versions, docs | unnest 조인 | pkey 들 | Index Scan, 0.14 ms | 충분 |
| search.py:448, 456-457 | query_translations | (query_sha256, model) | query_translations_pkey | Index Scan, 0.06 ms | 충분 |
| search.py:894 | chunks | chunk_id=ANY | chunks_pkey | 0.10 ms | 충분 |
| section.py:169-173 | versions, docs | rule_seq, valid_to IS NULL 또는 as_of 구간 | versions_one_current, versions_pkey, docs_pkey | 0.11 ms | 충분 |
| section.py:182-183, 189-190 | chunks | rule_seq, version_id, (article), ORDER BY seq | chunks_page | 0.17 ms, 0.25 ms | 충분 |
| section.py:194 | docs | DISTINCT org | 없음 | Seq Scan 1,516행, 0.28 ms | 1,516행, 생략 |
| load_snapshot.py:80-96, 164, 191 | index_meta | id=1 | pkey | 1행 | 생략 |
| load_snapshot.py:83 | chunks | `EXISTS(line_start IS NULL)` | 없음 | 합성은 1행 만에 종료 | 적재 때 1회 |
| load_snapshot.py:109-119 | docs, versions | ON CONFLICT | pkey | arbiter 확인 | 충분 |
| load_snapshot.py:122-135, 186-187 | chunks | COPY, ON CONFLICT (chunk_id, version_id), UPDATE FROM | chunks_pkey | 코드 읽기 | 충분 |
| load_snapshot.py:141-142 | chunks | unnest 대조 | chunks_pkey | Index Only Scan, 0.09 ms | 충분 |
| load_snapshot.py:144-145 | chunks | `embedding IS NULL OR embedder IS DISTINCT FROM OR vector_dims <> d` | 없음 | Seq Scan 30,171행, 142.0 ms | 적재 때 1회 전수 대조가 의도 |
| load_snapshot.py:152-162 | query_translations | ON CONFLICT DO NOTHING | pkey | arbiter 확인 | 충분 |
| schedule.py:127, 136, 145-148, 296, 334 | sync_runs | (job, slot) ON CONFLICT, job/status 정렬, run_id | sync_runs_job_slot_key, sync_runs_pkey | Seq Scan 1행, 0.04-0.08 ms | 1행 표(하루 1행씩 늘어남), 생략 |
| schedule.py:154, 278 | index_meta | id=1 | pkey | 1행 | 생략 |
| schedule.py:190 | chunks | rule_seq=ANY, embedder (벡터 재사용) | chunks_page | Bitmap Index Scan 126행, 0.35 ms | 충분 |
| schedule.py:226 | docs | 전표 | 없음 | Seq Scan 1,516행, 0.22 ms | 전표 읽기가 의도 |
| schedule.py:229 | chunks | max(ord) | 없음 | Seq Scan 30,171행, 7.3 ms | 실행당 1회, 색인 쓰기 비용이 더 커 만들지 않음 |
| schedule.py:233, 241, 263, 267 | versions | rule_seq, version_id, valid_to IS NULL | versions_pkey, versions_one_current | Index Only Scan 0.09 ms, 부분 UNIQUE Index Scan | 충분 |
| schedule.py:237-239, 245, 248, 256, 271 | docs, versions, chunks, changed_articles | INSERT ON CONFLICT, count by (rule_seq, version_id) | pkey, chunks_page | chunks_page Index Only Scan 0.18 ms | 충분 (쓰기마다 HNSW와 chunks_page 갱신) |
| snapshot_diff.py:103, 108 | sync_runs, changed_articles | INSERT ON CONFLICT | job_slot_key, changed_articles_pkey | arbiter 확인 | 충분 |
| changes.py:68-73 | changed_articles, docs | 날짜 식 >= since, org EXISTS, ORDER BY 식 LIMIT OFFSET | 식이라 색인 없음 | Seq Scan 318행, 0.20-0.28 ms | 318행, 생략 |
| changes.py:78-80 | sync_runs | job, status, ORDER BY finished_at | 없음 | 1행 | 생략 |
| evals/safety/deploy_corpus_injection_check.py:207-225 | index_meta, docs, versions, chunks | 접두 검색, 삽입, 정리 | pkey, chunks_page | 점검 합계 2.9 ms, 접두 검색 5.4 ms(Seq Scan), 정리는 pkey Index Scan 0.03-0.12 ms | 1회성 시험 |

## 3. 리콜·답변·변경 감시 질의

| file:line | 표 | 조건/정렬 | 색인 | EXPLAIN | 판정 |
|---|---|---|---|---|---|
| answer_store.py:140, 177, 183 | answers | INSERT ON CONFLICT (answer_id) | answers_pkey | 쓰기 | 충분 |
| answer_store.py:146, 189 | citations | INSERT ON CONFLICT DO NOTHING | citations_pkey | 쓰기 | 충분 |
| answer_store.py:199 | answers | UPDATE answer_id | answers_pkey | Index Scan | 충분 |
| answer_store.py:202, 210 | answers | answer_id | answers_pkey | 0.039 ms, 0.092 ms | 충분 |
| answer_store.py:205, 215 | citations | answer_id ORDER BY chunk_id | citations_pkey | Bitmap Index Scan + Sort, 0.083 ms | 충분 |
| answer_store.py:222 | citations, answers | rule_seq=, article=, ORDER BY created_at, answer_id (리콜 핵심) | citations_article_idx, answers_pkey | Index Scan 후 nested loop, 0.161 ms | 충분. 같은 섹션 인용 답이 수천이 되면 DISTINCT가 긴 본문 칸까지 정렬하므로 질의 모양(DISTINCT ON)을 볼 것 |
| answer_store.py:232 | citations | rule_seq/article 쌍 50개 | citations_article_idx | Hash Right Join + Seq Scan 559행, 0.239 ms | 충분 (행이 늘면 색인 nested loop으로 바뀜) |
| store.py:306, 315, 321 | recall_events | event_key | recall_events_pkey | Index Scan, 0.053 ms | 충분 |
| store.py:292, 331 | recall_notices | (answer_id, event_key) | UNIQUE | Seq Scan 3행, 0.041 ms | 3행, 생략 (행이 늘면 UNIQUE로 충분) |
| store.py:336, 301, 354 | recall_notices | notice_id | recall_notices_pkey | Seq Scan 3행 | 3행, 생략 |
| store.py:340 | recall_notices | user_id, ORDER BY created_at DESC, notice_id | recall_notices_user_idx | Seq Scan + Sort, 0.182 ms | 3행, 생략. LIMIT 없이 전부 읽고 앱에서 자른다 |
| store.py:340 (관리자) | recall_notices | 조건 없음, ORDER BY created_at DESC | 없음 | Seq Scan + Sort, 0.059 ms | 전체 읽기, 생략 |
| store.py:348 | recall_notices | digest_status='pending' AND (review_status IS NULL OR 'released') | recall_notices_digest_idx(부분) | Seq Scan 0행 | 3행, 생략. 조건이 색인 조건을 포함한다 |
| store.py:359 | recall_notices | user_id, change_pattern, changed->>'article', (changed->>'rule_seq')::bigint, feedback_useful IS NOT NULL | recall_notices_feedback_idx(부분) | Seq Scan 3행. 필터 출력이 색인 식과 글자 그대로 같다 | 정의 일치. 3행이라 색인 선택은 직접 보지 못했다 |
| store.py:365 | recall_notices | feedback_useful IS NOT NULL ORDER BY feedback_at | 부분 조건만 맞음 | Seq Scan + Sort 0행 | 관리자 전체 집계, 생략 |
| store.py:292, 375, 378 | recall_digests | digest_id, user_id | pkey, recall_digests_user_idx | Seq Scan 0행 | 0행, 생략 |
| store.py:383, 386, 390, 301 | maintenance_candidates | candidate_id, (status) ORDER BY created_at DESC | pkey, maintenance_candidates_status_idx | status 없음 Seq Scan + Sort 0.713 ms, pending 0.725 ms, needed는 status_idx Index Scan 0.128 ms, candidate_id Index Scan 0.062 ms | 충분. pending이 전부(964행)라 Seq Scan이 정상. LIMIT 없이 전부 읽는다 |
| store.py:400, 292, 407, 413 | webhook_subscriptions, webhook_deliveries | active 정렬, delivery_id, notice_id | pkey, webhook_deliveries_notice_idx | Seq Scan 0행 | 0행, 생략 |
| monitor.py:145 | pg_class | to_regclass | - | 0.056 ms (/changes 요청마다 4번) | 연결 왕복이 비용 |
| monitor.py:150, 157 | changed_articles, docs | 날짜 식 >= since, JOIN docs LIMIT | docs_pkey | Seq Scan 318행 + Sort, 0.597 ms / 0.145 ms | 318행, 생략. 날짜 식은 text→date 캐스트(STABLE)라 표현식 색인 불가 |
| monitor.py:164 | changed_articles, docs | event_id | pkeys | Nested Loop 0.112 ms | 충분 |
| monitor.py:170 | sync_runs | job, status ORDER BY finished_at DESC LIMIT 1 | 없음 | Seq Scan 1행 | 생략 |
| monitor.py:177 | changed_articles, docs | status='pending' ORDER BY created_at, event_id LIMIT | changed_articles_pending(부분) | Index Scan(0행), 0.049 ms | 충분 |
| monitor.py:182 | changed_articles | event_id | changed_articles_pkey | Index Only Scan, 0.044 ms | 충분 |
| monitor.py:187, 193 | change_monitoring | id=1 | pkey | 0행 | 생략 |
| maintenance.py:62 (변경 전) | chunks, versions, docs | `%s = ANY(c.link_targets)`, versions.valid_to IS NULL | link_targets 색인 없음 | 8.969 ms, 버퍼 26,159 (chunks 전체 훑기) | 색인 추가 제안 |
| maintenance.py:62 (변경 후) | 같음 | `c.link_targets @> ARRAY[%s]::bigint[]` | chunks_link_targets_gin | 합성 3,352행에 값을 넣고 측정: GIN 비트맵 스캔, 버퍼 56(hit 46 + read 10) | 변경 반영 |
| maintenance.py:72 | docs | rule_seq | docs_pkey | 0.156 ms | 충분 |
| acl.py:40 | chunks | rule_seq=, article IS NOT DISTINCT FROM | chunks_page | Index Scan 15행 읽고 2행 통과, 0.172 ms | 충분 |

## 4. 인증·승인·대화 질의

| file:line | 표 | 조건/정렬 | 색인 | EXPLAIN | 판정 |
|---|---|---|---|---|---|
| threads.py:128 | threads | INSERT ON CONFLICT (user_id, thread_id) | threads_pkey | 쓰기 (/chat 한 번에 2-4회, updated_at 갱신으로 두 색인 모두 갱신) | 충분 |
| threads.py:134 | threads | (user_id, thread_id) | threads_pkey | Index Scan, 0.056 ms | 충분 |
| threads.py:138 | threads | user_id ORDER BY updated_at DESC, created_at DESC (LIMIT 없음) | threads_user_updated_idx | 사용자 1/3(283행)은 Seq Scan + quicksort 0.130 ms. 좁은 조건이나 LIMIT 20이면 Index Scan + Incremental Sort 0.081 ms | 충분. 모든 대화를 가져오는 것이 비용이라 대화가 수천 개가 되면 LIMIT을 걸 것 |
| decision/repo.py:255 | approvals | thread_id, kind=결정표 | approvals_decision_thread(부분 UNIQUE) | Seq Scan 11행, 0.039 ms | 11행, 생략 |
| decision/repo.py:263, 300 | approvals | INSERT | pkey, 부분 UNIQUE 2개 | 쓰기 | 충분 |
| decision/repo.py:272, 310, 322 | approvals | approval_id (FOR UPDATE) | approvals_pkey | Seq Scan 11행, 0.061 ms | 충분(11행이라 계획기가 Seq Scan) |
| decision/repo.py:293 | approvals | thread_id=, kind<>결정표 (status 조건 없음) FOR UPDATE | 없음 (approvals_review_pending은 status='pending'을 요구) | Seq Scan 11행, 0.066 ms | 11행, 생략. 수천 행이 되면 `approvals(thread_id)` 일반 색인 또는 질의에 status 조건 추가 필요 |
| decision/repo.py:297 | approvals | UPDATE thread_id, kind<>결정표, status='pending' | approvals_review_pending(부분 UNIQUE) | 같은 조건 SELECT Seq Scan 0.041 ms | 구조 일치 |
| decision/repo.py:334 | approvals | status='pending' ORDER BY created_at | approvals_pending(부분) | Seq Scan + Sort 11행 중 3건, 0.047 ms | 충분. /chat과 GET /threads마다 불리는 가장 잦은 승인 질의 |
| decision/repo.py:279, 328, 260, 284 | decision_tables | table_id | decision_tables_pkey | 빈 표 | 충분 |
| decision/repo.py:337 | decision_tables | status='approved' ORDER BY table_id | decision_tables_status | Seq Scan + Sort 0행 | 업무 종류 수만큼이라 소량, 생략 |
| departments/store.py:67 | issue_tables | INSERT ON CONFLICT (approval_id) | issue_tables_approval_id_key | 쓰기 | 충분 |
| departments/store.py:81 | approvals | UPDATE approval_id, kind='issue_table', comment='' | approvals_pkey | Seq Scan 11행 0.017 ms | 충분 |
| departments/store.py:89 | issue_tables | thread_id, user_id ORDER BY approved_at DESC LIMIT 1 | issue_tables_thread_user_idx | Seq Scan + Sort + Limit 3행, 0.049 ms | 정의 일치 |
| auth_store.py:208, 215, 250, 265, 321, 365 | users | login_id, user_id | users_login_id_key, users_pkey | Seq Scan 2행, 0.03-0.057 ms | 충분 (인증된 모든 요청이 users_pkey 조회) |
| auth_store.py:225, 290, 312 | signup_requests | login_id, user_id | user_id UNIQUE, login_id 부분 UNIQUE(`db/113`, 거절 행 제외) | 빈 표 | 충분 |
| auth_store.py:298 | signup_requests | 조건 없음 ORDER BY requested_at, login_id | 없음 | 빈 표 | 전체 읽기, 생략 (옛 status_requested_at 색인은 이 질의에 못 쓰여 제거) |
| auth_store.py `_google_resolve` | user_identities, users, signup_requests | `(provider, subject)`, `users.login_id FOR UPDATE`, `signup_requests (user_id, login_id)`, `google_sub OR login_id` | user_identities_pkey, users_login_id_key, signup_requests_google_sub_key, signup_requests_login_id_key | 새 표(203 적용 전), 구글 로그인 때만 | 충분 (줄 번호는 다른 정리 때 맞춘다) |
| auth_store.py:349 | users | 조건 없음 ORDER BY created_at | 없음 | Seq Scan 2행, 0.071 ms | 생략 |
| auth_store.py:402 | token_revocations | jti=, expires_at > now() | token_revocations_pkey | Seq Scan 35행, 0.033 ms | 충분 (인증된 모든 요청마다 1회) |
| auth_store.py:410, 375, 377, 330, 270 | token_revocations, users, admin_role_log, signup_requests | INSERT/UPDATE by key | pkey/UNIQUE | 쓰기 | 충분. admin_role_log를 읽는 질의는 없다 |
| profile_store.py:71, 76, 81 | user_profiles | user_id | user_profiles_pkey | 빈 표 | 충분 |

## 5. 결론

- 큰 표(chunks 30,171, versions 1,798, docs 1,516, query_translations 692, threads 850, citations 559, changed_articles 318, maintenance_candidates 964)에서 Seq Scan이 남는 질의는 의도한 전수 읽기(기동·적재·증분 1회), 날짜 식 목록(318행)뿐이다. 검색의 `/chat` 경로는 HNSW(org 필터 없음 1 ms 안팎), org 필터 있는 경우 29-33 ms다.
- 색인 변경: 제거 7개(`answers_user_idx`, `issue_tables_thread_idx`, `issue_tables_user_idx`, `admin_role_log_at`, `token_revocations_expires_at`, `signup_requests_status_requested_at`, `recall_notices_review_idx`), 추가 2개(`issue_tables_thread_user_idx`, `chunks_link_targets_gin`), 부분 색인 `recall_notices_feedback_idx`는 의견 표 합침으로 추가.
- 만들지 않은 색인: `approvals(thread_id)`(11행, 수천 행이 되면), `changed_articles_pending` 칸 재설계(pending 0행), `chunks(ord)`(쓰기 비용), org별 부분 HNSW(운영 분포 모름), `chunks.org` 복사(스키마 변경).
- 코드 쪽 관찰(색인 문제가 아님, 이번에 고치지 않음): `recall_notices`·`maintenance_candidates` 목록을 LIMIT 없이 전부 읽고 앱에서 자른다(`recalls.py:177-187`), `GET /threads`가 사용자의 모든 대화를 읽는다(`threads.py:138`), `PgRecallStore._q`·`PgChangeStore._q`가 호출마다 새 연결을 연다(`/changes` 한 요청에 약 8번).
- 확인하지 못한 것: LangGraph 6표의 SQL(라이브러리 내부, explain_db에 이 표가 없음), 작은 표의 색인 선택 여부(`SET enable_seqscan=off`는 허용 범위 밖), 운영 `idx_scan`과 org·as_of 분포, `chunks_link_targets_gin`이 운영 규모에서 쓰기에 주는 부담(link_targets가 대부분 빈 배열이라 작을 것으로 보지만 미검증).
