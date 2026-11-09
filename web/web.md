# web/ : 화면

## 이 폴더가 하는 일

로그인, 채팅, 승인함, 리콜 알림, 관리자 화면. 확정된 프론트엔드 기술 스택은 Vite + React + Tailwind CSS이며, 프론트엔드 빌드 결과물은 FastAPI가 제공한다. 채팅·승인함 API(D6 오전)가 나온 뒤 붙인다.

기존 MVP 상태: 로그인 화면은 HTML·CSS·JavaScript로 먼저 구현·검증했다. 당시 React + Tailwind CSS 전환과 Vite 빌드 결과물의 FastAPI 제공은 아직 진행하지 않았다.

현재 D6 상태: React 채팅 프론트의 채팅 API adapter, SSE 파싱·오류 처리, threads 매핑, 승인 대기 UI, Memory adapter를 구현했다. React 테스트 44개 통과와 production build 성공을 확인했으며, 실제 API 통합 검증은 아직 미완료다. 실제 API 통합은 PR #60 반영 후 검증 예정이다.

- 주인: 강경희
- 입력: API 응답
- 출력: 화면

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 김승욱 (Claude Code) | 변경 감시 화면(`/changes`)의 분포 카드가 불러온 목록 50건만 세던 문제를 고쳤다. 분포·총 건수는 `GET /changes`가 새로 돌려주는 `counts`(종류별 전체 건수)를 `mapTypeCounts`로 합쳐 쓰고(카드 문구 "조회 기간 전체 기준", 동결 보류는 목록 맨 앞 알림 한 줄로 계속 셈), 목록은 기존대로 "더 보기"로 쪽마다 더 불러온다. 서버가 `counts`를 못 주면 옛 방식(불러온 목록 기준)으로 돌아간다. 삭제·추가처럼 한쪽 판이 없는 항목 요약은 "(2026-08-13 판에서 삭제)", "(2026-11-04 판에서 추가)"로, 양쪽이 있으면 "(A 판 → B 판)"으로 바꿨고 리콜 화면 머리글도 같은 `versionText`를 쓴다. 시험 `change-monitoring-service.test.js`·`recall-routes.test.jsx`·`recall-service.test.js` 64개 통과, `npm run build` 통과 | 미정 |
| 2026-11-09 | 박진형 | 답을 받는 중 화면 전체가 하얗게 되던 문제를 고쳤다. 배포 화면에서 재현해 콘솔 오류 `TypeError: e.abort is not a function`을 잡았다: 채팅 화면이 내려갈 때(다른 메뉴 이동, 창 포커스 재확인) 부르는 `dispose()`가 `controllers` 값(요청 기록 `{controller, activeThreadId, cancelled}`)에 바로 `abort()`를 불러 오류가 났고, React가 화면 전체를 지웠다. 이제 `request.controller.abort()`를 부르고 받는 중이던 요청을 취소로 표시한다. 안전망으로 `AppErrorBoundary`를 앱 전체에 씌워 그리기 오류가 나도 하얀 화면 대신 '화면 다시 불러오기' 안내를 보이고 오류는 `console.error`로 남긴다. vitest 137개 통과(새 시험 4개: 원인 시험 2개는 원래 코드에서 같은 TypeError로 실패 확인, 안전망 시험은 App에서 안전망을 빼면 실패 확인), build 성공. 대화 목록 제목 잘림은 #74(main)에 이미 고쳐져 있고 배포판에 아직 안 들어간 것을 확인했다(배포 CSS에 `flex:0 0 auto` 없음). | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | 승인함 화면(`/approvals`)을 실제 승인 API에 연결했다. `GET /approvals`로 결정표 초안, 쟁점표, 팀 검토 실패 알림 세 종류를 불러와 원문 대조표, 쟁점표, 실패한 팀을 보이고, `POST /approvals/{id}`(CSRF 포함)로 승인·반려·재시도·미검토 표시를 보낸 뒤 목록을 다시 불러온다. 원문과 다른 칸이 있는 초안의 승인과 반려에는 사유를 필수로 하고, 사유 필요·이미 결정됨·권한 없음 등 오류 코드별 한국어 안내와 빈 목록 안내를 넣었다. 실제 API에 없는 부서별 검토 입력, 보완 요청, 결정표 원문 링크는 실제 경로에서 숨겼다. `/demo/approvals`는 미리보기 서비스를 그대로 쓴다. 서비스 단위 시험과 라우트 시험을 추가해 vitest 170개 통과, build 성공을 확인했다. | 미정 |
| 2026-11-09 | 박진형 | 창 포커스·화면 이동 때 화면이 다시 그려지던 문제를 고쳤다(#71 리뷰). `SessionProvider.refresh()`가 `/me` 재확인 전에 `checking`·`user: null`로 바꿔 `Protected`가 페이지를 내리고 로딩 화면을 보였다(입력 중인 글·선택 상태가 사라짐). 이제 로그인된 사용자가 있으면 재확인 중에도 화면을 유지하고 결과로만 바꾼다: 같은 사용자면 그대로, 401이면 로그아웃, 다른 사용자·역할이면 갱신, 네트워크·5xx 오류면 로그인 유지. 첫 진입은 기존 동작 그대로. vitest 70개 통과(새 시험 5개 중 3개는 원래 코드에서 실패 확인, 2개는 401·역할 변경 회귀 확인), build 성공. | 미정 |
| 2026-11-09 | 박진형 | 새로고침 뒤 대화 목록을 눌러도 본문이 비던 문제를 고쳤다. 목록 클릭 시 `GET /threads/{id}`로 대화를 불러와(답변 생성 중이거나 이미 질문이 있는 대화는 로컬 유지) 불러오는 중·실패 문구를 보이고, `mapThreadRecord`가 `messages`를 쓰고 없으면 `last.answer`를 답으로 보인다. 근거 칸이 비던 문제도 고쳤다(서버 칸 `rule_title`·`article`·`version_date`를 화면 칸 `title`·`path`·`version`으로 맞추는 `normalizeCitation`, 원문 보기 링크는 근거의 `source_url`). vitest 65개 통과(새 시험 7개는 원래 코드에서 실패 확인), build 성공. 대화가 많아 목록이 스크롤될 때 대화 버튼이 42px로 눌려 제목 윗부분이 잘리던 것을 `.demo-thread`·`.demo-thread-title`에 `flex:0 0 auto`(줄어들지 않음)와 `line-height:1.45`를 주어 고쳤다. | 미정 |
| 2026-11-08 | kyunghee | MemorySettingsPage에 기억 초기화 DELETE 연동, 확인·중복 요청 방지, 마지막 단계 버튼을 추가했다. PATCH는 백엔드 계약대로 affiliation/rank만 전송하며 service는 화면 전용으로 유지했다. | 미정 |
| 2026-11-07 | kyunghee | D6 채팅 API adapter, `/threads` 매핑, `/chat` SSE 파싱(token/citation/approval_request/error/done), `apiRequest` 오류 message/code 처리, `AbortController` 중단, 승인 대기 UI와 Memory adapter를 구현했다. React 테스트 44개 통과와 production build 성공을 확인했다. Python 3.12 `.venv`에서 운영 DB·외부 API 환경변수를 제거하고 `python -m pytest -p no:cacheprovider --basetemp .pytest-basetemp-final -q`를 실행했으며, Windows 임시 폴더 권한 문제는 `--basetemp`로 우회했다(609 passed, 48 skipped, failed/errors 0). 실제 API 통합 검증은 미완료이며 PR #60 반영 후 진행 예정이다. | 미정 |
| 2026-10-30 | 강경희 | 로그인 화면과 인증 API 연결, 로그인 전 CSRF 발급, 로그인·로그아웃·재로그인, 비밀번호 입력 처리와 중복 요청 방지를 구현하고 검증했다. Google 로그인 버튼은 준비 중 상태로 유지했다. | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
