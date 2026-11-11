# PR #131 로컬 실측 (integ-1111, HEAD eb4579b)

**로컬 실측** 2026-11-11 20시대(KST). 운영 주소 호출 없음.

- 코드: `git archive HEAD`를 임시 폴더 `e2e-app`에 풀어 사용(worktree 수정 없음). 화면은 그 복사본에서 `npm run build`(node_modules는 junction).
- 서버: `uvicorn backend.main:app` 127.0.0.1:18131(주 서버), 18132(보조 서버). DB는 로컬 `pr1-pg`의 임시 DB `app_e2e`(`db/*.sql` 번호순 적용 오류 0건).
- 주 서버 설정: `.env.example` 값 + `PROVENA_ENV=local`, `PROVENA_DEV_MODE=1`, `DEMO_MODE=1`, `LLM_API_KEY` 비움, `SEARCH_WARMUP=0`, `PROVENA_OWNER_LOGIN_ID=demo-admin`, `RECALL_STORE=postgres`, `SERVICE_API_KEY`·`AUTH_SECRET` 임의값.
- 보조 서버(18132): 위와 같되 `PROVENA_DEV_MODE` 끔(웹훅 strict 검사는 로컬 데모가 아닐 때만 켜짐, `backend/api/recalls.py:293`), `PROVENA_DOCS_PUBLIC=0`, `PROFILE_ENC_KEYS` 임의값. 쿠키가 Secure라 로그인 쿠키는 헤더로 직접 전달.
- 데모 모드: 켬(LLM 키 사용 0, 녹화 재생, 비용 0). 색인 적재: **함, 청크 23,095개**(`snapshot unpack-index` + `load_snapshot`, 22.3초, 디스크 약 124MB, C: 여유 11GB에서 진행).
- 브라우저: 시스템 Chrome(headless)을 playwright로 구동해 화면 확인.

집계: 통과 55, 실패 0, 못 함 0, 참고(판정 대상 아님) 5

| # | 항목 | 요청 | 기대 | 실제 | 판정(통과/실패/못 함+이유) |
|---|---|---|---|---|---|
| 0 | strict 서버 관리자 로그인(PROVENA_DEV_MODE 끔, 쿠키 Secure라 헤더로 직접 전달) | POST /auth/login demo-admin | 200 | 200 {"user_id":"1f3be499-66bb-4392-bca9-3d8a1fe6ac00","role":"admin"} | 통과 |
| 1 | 기동 | GET /health, HEAD /health | 200, 200 | 200 {"status":"ok"}; HEAD 200 | 통과 |
| 2.1 | H-27 favicon | GET /favicon.ico | 200 | 200 image/svg+xml 9522B | 통과 |
| 2.2 | H-27 없는 화면 | GET /zz-no-such-page (Accept text/html) | 404 + HTML(React index) | 404 text/html; charset=utf-8 root div=True | 통과 |
| 2.3 | H-27 없는 API 경로 | GET /api/zz-none, GET /zz-no-such-page (Accept json) | 404 한국어 JSON | 404 {"detail":"요청한 경로를 찾을 수 없습니다.","error":{"code":"not_found","message":"요청한 경로를 찾을 수 없습니다.","request_id":"b5d67d2412c847b2b83fb4913447827c"}} \|\| 404 {"detail":"요청한 경로를 찾을 수 없습니다.","error":{"code":"not_found","message":"요청한 경로를 찾을 수 없습니다.","request_id":"e2a0aeaf043946efb17f0da40edabca8"}} | 통과 |
| 3 | C-24 HEAD /threads | HEAD /threads (비로그인) | 404(기록: GET 전용이라 StaticFiles로 떨어져 404, 본문 전송 없음) | 404 allow=None len=0 | 통과 |
| 4 | C-16/C-17 NUL 경로 | GET /threads/%00 (로그인) | 404 오류 봉투(JSON) | 404 application/json {"detail": "요청한 경로를 찾을 수 없습니다.", "error": {"code": "not_found", "message": "요청한 경로를 찾을 수 없습니다.", "request_id": "5594dbb6f9db4309aefb7fbefc996602"}} | 통과 |
| 4 | C-16/C-17 NUL 경로 | GET /threads/abc%00def (로그인) | 404 오류 봉투(JSON) | 404 application/json {"detail": "요청한 경로를 찾을 수 없습니다.", "error": {"code": "not_found", "message": "요청한 경로를 찾을 수 없습니다.", "request_id": "bb7a7b1d750d4e75b885700c3ac5655a"}} | 통과 |
| 4 | C-16/C-17 NUL 경로 | GET /me%00 (로그인) | 404 오류 봉투(JSON) | 404 application/json {"detail": "요청한 경로를 찾을 수 없습니다.", "error": {"code": "not_found", "message": "요청한 경로를 찾을 수 없습니다.", "request_id": "8c8ceaef4ba34c2dacbdec5819c93402"}} | 통과 |
| 5.1 | 로그인(데모 계정) | POST /auth/login demo-user | 200 | 200 {"user_id":"320916c2-bbf9-4494-9e14-3457ceb4e48e","role":"user"} | 통과 |
| 5.2 | H-13 /me login_id | GET /me | login_id 필드 존재 | 200 {"user_id":"320916c2-bbf9-4494-9e14-3457ceb4e48e","role":"user","profile_completed":false,"login_id":"demo-user","is_owner":false} | 통과 |
| 5.3 | 가입(이메일) | POST /auth/signup | 201 verification_sent | 201 {"code":"verification_sent","message":"가입 신청이 접수되었습니다. 메일로 받은 인증번호를 입력해 주세요.","verification_expires_at":"2026-11-11T11:59:52.097038+00:00","verification_resend_ | 통과 |
| 5.4 | 인증번호 확인(서버 로그 K-21) | POST /auth/signup/verify (코드는 서버 로그에서 읽음: 있음) | 200 | 200 {"status":"verified"} | 통과 |
| 5.5 | 관리자 로그인 | POST /auth/login demo-admin | 200 | 200 {"user_id":"1f3be499-66bb-4392-bca9-3d8a1fe6ac00","role":"admin"} | 통과 |
| 5.6 | 가입 승인 | POST /admin/signup-requests/e2e.tester@example.com/approve | 200 approved | 200 {"login_id":"e2e.tester@example.com","status":"approved","changed":true} | 통과 |
| 5.7 | 가입 계정 로그인 | POST /auth/login 시험 계정 | 200 | 200 {"user_id":"802aa12f-72c5-44bc-b874-d0de6bcb9491","role":"user"} | 통과 |
| 5.8 | H-13 /me(시험 계정) | GET /me | login_id=이메일 | 200 {"user_id":"802aa12f-72c5-44bc-b874-d0de6bcb9491","role":"user","profile_completed":false,"login_id":"e2e.tester@example.com","is_owner":false} | 통과 |
| 5.9 | J-15 대문자 아이디 로그인 | POST /auth/login login_id=E2E.TESTER@EXAMPLE.COM | 200 | 200 {"user_id":"802aa12f-72c5-44bc-b874-d0de6bcb9491","role":"user"} | 통과 |
| 6.1 | J-14 서명 토큰으로 변경 요청 | PUT /me/profile (/auth/csrf 발급 토큰) | 200 | 200 {"name":"홍길동","dept":"재무팀","phone_masked":"010-****-5678","address":"부산광역시 연제구 중앙대로 1000","updated_at":"2026-11-11T11:54:56.614817+00:00"} | 통과 |
| 6.2 | J-14 임의 값(쿠키=헤더) | PUT /me/profile cookie=header='arbitrary-value-123' | 403 | 403 {"detail":"CSRF 검증에 실패했습니다.","error":{"code":"csrf_failed","message":"CSRF 검증에 실패했습니다.","request_id":"3773894992bf410cace1df263b128455"}} | 통과 |
| 6.3 | J-14 서명 한 글자 변경 | PUT /me/profile 서명 마지막 글자 변경 토큰(쿠키=헤더) | 403 | 403 {"detail":"CSRF 검증에 실패했습니다.","error":{"code":"csrf_failed","message":"CSRF 검증에 실패했습니다.","request_id":"a2ce2cbac1f54b43b20a89f9ac5723ba"}} | 통과 |
| 6.4 | J-14 쿠키와 헤더가 다름 | PUT /me/profile 헤더만 다른 값 | 403 | 403 {"detail":"CSRF 검증에 실패했습니다.","error":{"code":"csrf_failed","message":"CSRF 검증에 실패했습니다.","request_id":"ea69e72f11e147aa9d8f87dc48480e21"}} | 통과 |
| 7.1 | C-19/C-20 내 정보 422 | PUT /me/profile 잘못된 값 4개 | 422 + 오류 봉투 details | 422 {"detail":"입력한 내용을 확인해 주세요.","error":{"code":"validation_error","message":"입력한 내용을 확인해 주세요.","request_id":"b96ce56366a74f8d902ca55000fac5f9","details":{"fields":{"name":"이름은 글자 2~20자로 입력해 주세요(숫자·기호 제외).","dept":"소속(담당부서)을 입력해 주세요.","phone":"전화번호 형식이 맞지 않습니다. 예: 010-1234-5678","address":"주소는 5~100자로 입력해 주세요."}}}} | 통과 |
| 7.2 | C-19 본문이 JSON 아님 | PUT /me/profile 'not json' | 422 봉투 | 422 {"detail":"입력한 내용을 확인해 주세요.","error":{"code":"validation_error","message":"입력한 내용을 확인해 주세요.","request_id":"5f72233620454d6383ecd62e9af4f5c8","details":{"fields":{}}}} | 통과 |
| 8.1 | C-21 재발송(이미 인증된 계정) | POST /auth/signup/resend | 본문에 code 없음 | 200 {"status":"unavailable"} | 통과 |
| 8.2 | C-21 재발송(인증 전 대기 계정, 옛 화면처럼 code를 같이 보냄) | POST /auth/signup/resend {login_id, code} | 응답 본문에 code 키 없음(200 또는 429) | 200 {"status":"unavailable"} | 통과 |
| 8.3 | C-21 재발송 성공 경로(reset-verification 뒤) | POST /auth/signup/resend {login_id, code} | status=sent, code 키 없음 | 200 {"status":"sent","verification_expires_at":"2026-11-11T12:02:56.219114+00:00","verification_resend_available_at":"2026-11-11T11:58:56.219114+00:00"} | 통과 |
| 9.1 | C-22/H-10 useful=문자열 | POST /recalls/rc-none/feedback {useful:'yes'} | 422 | 422 {"detail":"요청 형식이 올바르지 않습니다.","error":{"code":"validation_error","message":"요청 형식이 올바르지 않습니다.","request_id":"d40e42a0ae78469b93024a67db135df0","details":[{"loc":["body","useful"],"msg":"Input should be a valid boolean","type":"bool_type"}]}} | 통과 |
| 9.2 | H-10 useful=정수 1 | POST /recalls/rc-none/feedback {useful:1} | 422 | 422 {"detail":"요청 형식이 올바르지 않습니다.","error":{"code":"validation_error","message":"요청 형식이 올바르지 않습니다.","request_id":"b19218d06b99418ba9fccc7d4196b81e","details":[{"loc":["body","useful"],"msg":"Input should be a valid boolean","type":"bool_type"}]}} | 통과 |
| 9.3 | H-10 useful=true(대조, 없는 알림) | POST /recalls/rc-none/feedback {useful:true} | 404(알림 없음) | 404 {"detail":"리콜 알림을 찾을 수 없습니다.","error":{"code":"not_found","message":"리콜 알림을 찾을 수 없습니다.","request_id":"2dbe01eaba214c94bb7ef269a5e5cea9"}} | 통과 |
| 10.1 | C-23 없는 task_type | POST /decision-tables/run task_type='Zzz no such task' | 404 | 404 {"detail":"권한표에 그 업무 종류가 없다","error":{"code":"not_found","message":"권한표에 그 업무 종류가 없다","request_id":"f21fb77f8d6246339191e4a76314855c"}} | 통과 |
| 10.2 | C-23 있는 task_type(기존 동작) | POST /decision-tables/run task_type='Approving expense' | 404가 아님(승인된 표가 0개면 409, 있으면 200) | 409 {"detail":"업무 종류 'Approving expense'로 승인된 결정표가 0개라 실행하지 않는다 (정확히 1개일 때만 실행)","error":{"code":"ambiguous_table","message":"업무 종류 'Approving expense'로 승인된 결정표가 0개라 실행하지 않는다 (정확히 1개일 때만 실행)","request_id":"ef79bab719ef4e2fb3d701020d19e386"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(로컬 데모 모드) | POST /webhook-subscriptions url=http://127.0.0.1:9/hook | 로컬 데모는 strict=False라 허용(backend/api/recalls.py:293). 차단 확인은 strict 서버(18132)에서 | 201 {"sub_id":"ws-7b73e2a2d886","url":"http://127.0.0.1:9/hook","secret_ref":"RECALL_WEBHOOK_SECRET","active":true,"created_at":"2026-11-11T11:54:59.840295+00:00","secret_configured":false} | 참고 |
| 11 | J-12/J-13 웹훅 구독(로컬 데모 모드) | POST /webhook-subscriptions url=http://10.0.0.5/hook | 로컬 데모는 strict=False라 허용(backend/api/recalls.py:293). 차단 확인은 strict 서버(18132)에서 | 201 {"sub_id":"ws-bc0faa3dc210","url":"http://10.0.0.5/hook","secret_ref":"RECALL_WEBHOOK_SECRET","active":true,"created_at":"2026-11-11T11:54:59.927784+00:00","secret_configured":false} | 참고 |
| 11 | J-12/J-13 웹훅 구독(로컬 데모 모드) | POST /webhook-subscriptions url=http://169.254.169.254/latest | 로컬 데모는 strict=False라 허용(backend/api/recalls.py:293). 차단 확인은 strict 서버(18132)에서 | 201 {"sub_id":"ws-2f881b0cd799","url":"http://169.254.169.254/latest","secret_ref":"RECALL_WEBHOOK_SECRET","active":true,"created_at":"2026-11-11T11:55:00.058824+00:00","secret_configured":false} | 참고 |
| 11 | J-12/J-13 웹훅 구독(로컬 데모 모드) | POST /webhook-subscriptions url=https://example.com/hook | 로컬 데모는 strict=False라 허용(backend/api/recalls.py:293). 차단 확인은 strict 서버(18132)에서 | 201 {"sub_id":"ws-8f86a98c4be1","url":"https://example.com/hook","secret_ref":"RECALL_WEBHOOK_SECRET","active":true,"created_at":"2026-11-11T11:55:00.160542+00:00","secret_configured":false} | 참고 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=http://127.0.0.1:9/hook | 400 | 400 {"detail":"배포 환경에서는 https 주소만 쓸 수 있습니다","error":{"code":"bad_request","message":"배포 환경에서는 https 주소만 쓸 수 있습니다","request_id":"bf1bc234121044769d171bd921ad051e"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=https://127.0.0.1/hook | 400 | 400 {"detail":"공인 주소가 아닌 IP는 쓸 수 없습니다","error":{"code":"bad_request","message":"공인 주소가 아닌 IP는 쓸 수 없습니다","request_id":"97439b9a9e674cd0923fa7764db5cce3"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=https://10.0.0.5/hook | 400 | 400 {"detail":"공인 주소가 아닌 IP는 쓸 수 없습니다","error":{"code":"bad_request","message":"공인 주소가 아닌 IP는 쓸 수 없습니다","request_id":"7b137c6376654e5ebf96ba924b5a3e1f"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=https://169.254.169.254/latest | 400 | 400 {"detail":"공인 주소가 아닌 IP는 쓸 수 없습니다","error":{"code":"bad_request","message":"공인 주소가 아닌 IP는 쓸 수 없습니다","request_id":"438ccf3890cb45c0814ed4c5d8e86f61"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=http://example.com/hook | 400 | 400 {"detail":"배포 환경에서는 https 주소만 쓸 수 있습니다","error":{"code":"bad_request","message":"배포 환경에서는 https 주소만 쓸 수 있습니다","request_id":"f529b406668d48dd97f57a35efafa014"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=https://localhost/hook | 400 | 400 {"detail":"내부 주소는 쓸 수 없습니다","error":{"code":"bad_request","message":"내부 주소는 쓸 수 없습니다","request_id":"f2b9a83826f14b2ebdc25b7b30a984e7"}} | 통과 |
| 11 | J-12/J-13 웹훅 구독(strict, 로컬 데모 끔) | POST /webhook-subscriptions url=https://example.com/hook | 201 | 201 {"sub_id":"ws-a7e1cbb099a4","url":"https://example.com/hook","secret_ref":"RECALL_WEBHOOK_SECRET","active":true,"created_at":"2026-11-11T11:55:43.439899+00:00","secret_configured":false} | 통과 |
| 12.1 | H-21 digest flush | POST /recalls/digest/flush (관리자) | 200 {digests, notices} | 200 {"digests":0,"notices":0} | 통과 |
| 12.2 | H-21 digest flush 일반 사용자 | POST /recalls/digest/flush (일반) | 403 | 403 {"detail":"관리자 권한이 필요합니다.","error":{"code":"forbidden","message":"관리자 권한이 필요합니다.","request_id":"3069cf598b0243c5b66a6af53db0ff8e"}} | 통과 |
| 12.3 | H-21 reset-verification | POST /admin/signup-requests/by-id/2/reset-verification | 200 {request_id, reset:true} | 200 {"request_id":2,"reset":true} | 통과 |
| 12.4 | H-21 reset-verification 없는 id | POST .../by-id/999999/reset-verification | 404 | 404 {"detail":"사용자를 찾을 수 없습니다.","error":{"code":"not_found","message":"사용자를 찾을 수 없습니다.","request_id":"a14b9dd49ffe4976b363053f76a327dd"}} | 통과 |
| 12.5 | H-21 process-pending(데모 모드, LLM 없음) | POST /recalls/process-pending (관리자) | 200 처리 결과 JSON | 200 {"status":"done","processed":0,"sent":0,"failed":0,"skipped":0,"notices":0,"review":0,"judge_failures":0,"candidates":0} | 통과 |
| 13.1 | A-07 /docs 기본값 | GET /docs, /openapi.json (PROVENA_DOCS_PUBLIC 미설정) | 200, 200 | 200, 200 | 통과 |
| 13.2 | A-07 PROVENA_DOCS_PUBLIC=0 | GET /docs, /openapi.json | 404, 404 | 404, 404 | 통과 |
| 14 | H-29 로그인 실패 반복 | POST /auth/login 시험 계정(email2) 틀린 비밀번호 반복 | 429 + Retry-After | 상태열 [401, 401, 401, 401, 401, 429]; Retry-After=60 | 통과 |
| 15.1 | 화면 번들: #130 문구 | grep index-*.js '다른 사용자의 알림입니다.', '가입 승인 목록이 없습니다.', '서명 키 없음', '변경사항을 저장했습니다.', '결론 유지', '예: 결제 API, 사내 모니터링', '참고 근거', '회원가입 승인 목록' | 모두 1건 이상 | 전부 1~2건 발견 | 통과 |
| 15.2 | 화면 번들: findLastIndex | grep findLastIndex | 있음 | 1줄에 2곳(DemoChatPage의 messages.findLastIndex 두 군데) 발견 | 통과 |
| 15.3 | 화면 번들: approval_pending, renumberByAppearance 문자열 | grep approval_pending / renumberByAppearance | 번들에 글자 그대로 있는지 | 둘 다 0건. 원인: approval_pending은 src/lib/chat-service.js:161 주석에만 있고(번들에서 제거), renumberByAppearance는 함수 이름이라 minify로 바뀜. 대신 호출부 `Wc(e.messages[t]).c...`와 정규식 `\[(\d+)\]` 4건이 번들에 있음 | 통과(문자열 대신 동작 흔적으로 확인, 이름 검색은 부적합) |
| 16 | 키 없는 데모 채팅 | POST /chat 추천 질문 1(제3자가 프로덕션 데이터에 접근하거나...) | SSE가 끝 신호까지, 인용 포함 | 200 text/event-stream; charset=utf-8; 이벤트 ['token', 'token', 'token', 'token', 'token', 'token', 'token', 'token', 'token', 'token', 'token', 'token']...(43개) 28.8초; 인용 포함=True | 통과 |
| 16.1 | 채팅 뒤 /threads | GET /threads | 200, 목록에 방금 대화 | 200 {"threads":[{"thread_id":"t-6cf466d66212","title":"제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요?","status":"idle","created_at":"2026-11-11T11:57:26.9 | 통과 |
| 16.2 | 범위 밖 질문 거절 형식 | POST /chat 오늘 점심 메뉴 추천해줘 | 200 SSE 끝까지(거절) | 200 ['event: token', 'event: token', 'event: token', 'event: token', 'event: token', 'event: token', 'event: done'] | 통과 |
| 17.1 | 브라우저: 없는 화면 주소 | Chrome(headless)으로 /zz-no-such-page 열기 | React 404 안내 | 본문 '페이지를 찾을 수 없습니다. 주소가 잘못되었거나 옮겨진 페이지입니다. 처음으로' | 통과 |
| 17.2 | 브라우저: 로그인 → 채팅 → 추천 질문 입력 | 시험 계정 로그인 후 /chat에서 질문 1 입력, Enter, 45초 대기 | 인용 [1]이 붙은 답 | 로그인 뒤 /chat 이동, 답 본문에 [1]과 '근거 판 날짜 2026-09-13 · 출처: GitLab Handbook(CC BY-SA 4.0)' 표시, 참고 근거 영역 표시. 화면 캡처는 임시 폴더에만 두고 저장소에는 넣지 않음. 콘솔 오류는 404(없는 주소 시험)와 401(로그인 전 /me) 3건뿐 | 통과 |
| 17.3 | 브라우저: 데모 계정 로그인 직후 | demo-user 로그인 | 내 정보 미작성이면 /myinfo로 안내 | /myinfo로 이동(프로필 작성 전 계정), 시험 계정은 프로필 저장 뒤라 /chat으로 이동 | 참고 |

## 참고와 한계

- 11번(J-12·J-13): 로컬 데모 모드는 `strict=False`라 내부 IP도 구독이 등록된다(주 서버 4건 201). 차단 동작은 데모 모드를 끈 보조 서버에서 확인했다(내부 IP·http·localhost 400, 공인 이름 `https://example.com/hook` 201). 실제 웹훅 전송은 하지 않았다.
- 8번(C-21): 처음 재발송은 쿨다운 때문에 `unavailable`이었고(8.1·8.2), 관리자 reset-verification 뒤에 `sent`와 code 키 없음을 확인했다(8.3).
- 3번(C-24): HEAD `/threads`는 404이고 `Allow` 헤더가 없다. 기록(`backend/backend.md:19`)이 말한 현재 동작(규격상 405가 더 맞으나 동결 뒤 개선 후보)과 일치한다.
- 15번: 번들은 minify되어 함수 이름·주석이 사라진다. 문자열 검색 기준으로는 `approval_pending`, `renumberByAppearance`가 0건이므로 판정 기준을 동작 흔적으로 바꿨다.
- 17번 브라우저 확인은 채팅 한 줄기와 404 화면만 했다. 승인함·가입 승인 화면의 클릭은 하지 않았다.
- 절차 이탈 1건: 브라우저 도구 확인 중 `npx playwright --version`이 npx 캐시에 playwright 패키지를 내려받았다(프로젝트에는 설치하지 않음, 브라우저는 새로 받지 않고 시스템 Chrome 사용).
