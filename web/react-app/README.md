# Provena React 프런트엔드

Vite + React + Tailwind CSS 기반 Provena 화면입니다.

## 실행

```bash
npm ci
npm run dev
```

개발 서버가 출력하는 로컬 주소로 접속합니다. 기본 Vite 포트에서는 다음 경로를 사용합니다.

- `/login` — 아이디·비밀번호 로그인
- `/signup` — 회원가입 UI
- `/chat` — AI 채팅
- `/recalls` — 리콜 알림
- `/approvals` — 승인함
- `/admin` — 관리자 화면

## API 기본 주소

`VITE_API_BASE_URL`은 공개 가능한 API 기본 주소입니다. `src/lib/api.js`는 값이 비어 있으면 현재 origin을 사용합니다.

```env
# FastAPI와 같은 origin으로 제공할 때는 비워 둡니다.
VITE_API_BASE_URL=
```

다른 API origin을 사용할 때만 그 공개 주소를 설정합니다. 비밀번호, 토큰, OAuth client secret 같은 비밀값은 `VITE_` 환경 변수에 넣지 않습니다.

## 현재 인증·연동 상태

- 로그인 UI는 아이디와 비밀번호를 받고, 서버 요청 본문에 기존 계약 그대로 `login_id`와 `password`를 전달합니다.
- 회원가입은 서버 `POST /auth/signup`(backend/auth.py:1001-1002)에 연결되어 있고(`src/lib/signup.js:21`), 가입 신청 계정은 관리자 승인 대기 상태로 저장됩니다. Google 로그인은 서버 라우트(`/auth/google/start`·`callback`, backend/auth.py:1109·1102)와 화면 버튼(`LoginPage.jsx:48`, `SignupPage.jsx:48`)이 있습니다. 사용자 생성 함수 `get_or_create_google_user`는 `backend/auth.py:159`에 Protocol로 선언되어 있고 `MemoryAuthStore`·`PostgresAuthStore`에 구현이 있습니다(backend/services/auth_store.py:161, 482). 실제 Google 로그인은 실행해 보지 않았습니다(코드로만 확인).
- 실제 API·DB 연동, 권한별 접근 제한, Cloud Run 배포 동작은 별도로 검증해야 합니다.

## 사후 구현 상태 정정

현재 React 앱에는 로그인(`/login`), 회원가입(`/signup`), 최초 회원정보 입력·수정(`/myinfo`), 채팅(`/chat`), 최고 관리자 사용자 관리(`/admin/users`)가 구현되어 있다. 로그인 결과의 `profile_completed`에 따라 `/myinfo` 또는 `/chat`으로 이동한다.

로그인 화면에는 아이디 문구와 비밀번호 표시·숨김 버튼이 있고, 회원정보 화면에는 전화번호 자동 하이픈과 기존 사용자 전용 `← 뒤로가기`가 연결되어 있다. 사용자 관리 화면은 최고 관리자(`is_owner`)에게만 메뉴를 보이고 공통 `DemoLayout` 안에서 목록·승격·해제 UI를 표시한다. 개발용 Mock 미리보기는 `/dev-preview/myinfo`, `/dev-preview/admin-users`다.

소스 연결과 React 개발 서버 반영은 확인했지만, 회원가입부터 실제 로그인·회원정보 저장까지의 브라우저 통합 검증과 관리자 승격·해제의 실제 DB 왕복 검증은 완료되지 않았다. Google OAuth의 실제 PostgreSQL 사용자 연결과 운영 배포도 미검증이다.

## 세션과 임시 기억

- 최초 진입·화면 전환·브라우저 포커스 복귀에서 `/me`로 확인합니다. 네트워크 오류는 재시도 화면, 401은 미로그인 상태로 처리합니다.
- 관리자 메뉴와 `/admin`, `/approvals` UI는 `/me`의 `admin` role에서만 표시합니다. 클라이언트 검사는 보안 경계가 아니며 실제 API는 서버에서 권한을 검사해야 합니다.
- 로그아웃은 CSRF 발급 후 서버 204 응답을 확인해야 완료됩니다. 실패하면 현재 화면에 오류를 표시합니다.
- 임시 기억은 사용자별 sessionStorage에만 저장하며 로그아웃·세션 만료·사용자 변경 시 정리합니다. 기존 공용 localStorage 기억은 읽거나 사용자에게 이관하지 않습니다.
- 브라우저 저장소는 보안 격리 수단이 아닙니다. 민감한 정보는 저장하지 않습니다. 서버 장기 기억 `GET/PATCH/DELETE /me/memory`(backend/api/routes.py:359-378)는 `src/lib/api.js:142·150·151`의 `getMemory`·`patchMemory`·`deleteMemory`로 연결되어 있고(소속·직급 두 칸), sessionStorage는 임시 기억만 담습니다.

## 검증

```bash
npm test
npm run build
npm run lint
```

Vitest·Testing Library·jsdom 테스트는 가짜 fetch로 세션·권한 UI·A/B 전환을 검증합니다. 실제 쿠키 전송·Supabase·Cloud Run·서버 데이터 권한 검증을 대신하지 않습니다.

공식 API 참고: [React Context](https://react.dev/reference/react/useContext), [Vitest](https://vitest.dev/guide/), [Testing Library](https://testing-library.com/docs/react-testing-library/api/).
