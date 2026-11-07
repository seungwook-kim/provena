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
| 2026-11-08 | kyunghee | MemorySettingsPage에 기억 초기화 DELETE 연동, 확인·중복 요청 방지, 마지막 단계 버튼을 추가했다. PATCH는 백엔드 계약대로 affiliation/rank만 전송하며 service는 화면 전용으로 유지했다. | 미정 |
| 2026-11-07 | kyunghee | D6 최종 Python 검증: Python 3.12 `.venv`에서 운영 DB·외부 API 환경변수를 제거하고 `python -m pytest -p no:cacheprovider --basetemp .pytest-basetemp-final -q`를 실행했다. Windows 임시 폴더 권한 문제를 `--basetemp`로 우회했으며 609 passed, 48 skipped, failed/errors 0이었다. 실제 API 통합 검증은 PR #60 반영 후 진행 예정이다. | 미정 |
| 2026-11-07 | kyunghee | D6 React 채팅 프론트의 채팅 API adapter, SSE 파싱·오류 처리, `GET /threads` 매핑, 승인 대기 UI, Memory adapter를 구현했다. React 테스트 44개 통과와 production build 성공을 확인했다. 실제 API 통합 검증은 미완료이며 PR #60 반영 후 검증 예정이다. | 미정 |
| 2026-11-07 | kyunghee | 첫 D6 PR 범위(①~⑥): 채팅 API adapter, `/threads` 매핑, `/chat` SSE 파싱, token/citation/approval_request/error/done 처리, `apiRequest` 오류 message/code 처리, `AbortController` 중단을 구현했다. React 테스트 44 passed와 production build 성공을 확인했으며 실제 API 통합은 미검증이고 PR #60 병합 후 검증 예정이다. | 미정 |
| 2026-10-30 | 강경희 | 로그인 화면과 인증 API 연결, 로그인 전 CSRF 발급, 로그인·로그아웃·재로그인, 비밀번호 입력 처리와 중복 요청 방지를 구현하고 검증했다. Google 로그인 버튼은 준비 중 상태로 유지했다. | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
