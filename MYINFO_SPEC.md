# 첫 로그인 내 정보 시안 (2026-11-05, 요청 1번 — 강경희 요청)

요청 원문: "로그인 성공했을 때 처음 계정 만들면 다른 화면 아무것도 못하고 내 정보 기재하는 화면으로 바로 보이게 하기. 이름, 담당부서나 소속, 전화번호, 주소 — 암호화 aes256, 전화번호는 마스킹까지. 기존에 있는 화면 순서 정리해서 사용하기 / 내 정보 수정 가능하게, db 테이블도 수정, 관리자가 일반 직원들 개인정보는 못 보게"

> 현재 상태(2026-11-11): 이 문서는 2026-11-05 시안·제안 기록이다. 아래 시안 파일(`src/pages/MyInfoPage.jsx`, `src/lib/profile-preview.js`, `src/myinfo.css` 등)은 저장소에 없다. 실제 구현은 `backend/profile_api.py`(`/me/profile`)와 `web/react-app/src/pages/ProfileRequiredPage.jsx`, `profile.css`이고 커밋 75907e7(`feat: integrate profile and admin workflows`)이 들여왔다. 파일 이름·줄 번호는 제안 당시 값이다.

이 문서는 **시안(화면)** 과 **실제 적용 방법(제안)** 을 담는다. 팀 코드는 고치지 않았다. 근거는 `class-3-main`(main `e847c88`) 기준 `파일:줄`.

## 1. 시안
- 실행: `npx vite --host 127.0.0.1 --port 5184` → http://127.0.0.1:5184/demo/login (비밀번호 모두 `demo1234`)
- 계정: `demo-admin`(최고 관리자, 내 정보 **있음** → 바로 채팅) / `demo-a`·`kim.dev`·`lee.sre`(내 정보 **없음** → 첫 로그인 화면)
- 바뀐 파일: `src/App.jsx`(경로 1줄), `src/components/DemoLayout.jsx`(막기·메뉴·처음 상태로), `src/pages/DemoLoginPage.jsx`(로그인 뒤 갈 곳), `src/pages/AdminUsersPage.jsx`(개인정보 규칙 문장), `src/pages/MemorySettingsPage.jsx`(첫 순서 안내·나중에 하기), `src/admin-users.css`(2줄)
- 새 파일: `src/pages/MyInfoPage.jsx`, `src/lib/profile-preview.js`(가짜 내 정보 저장소, 로그인 계정 저장소와 따로), `src/myinfo.css`
- **시안은 암호화하지 않는다.** 브라우저 localStorage에 평문으로 남는다(화면에도 적어 둠). 암호화는 서버 일이다(4장).
- 확인(헤드리스 Chrome, 11/5): 내 정보 51개 통과, 관리자 흐름 17개 통과(첫 로그인 때 내 정보를 채우게 고친 복사본), 콘솔 오류 0, `vite build` 성공.

## 2. 화면 순서 (결정과 이유)
| 순서 | 화면 | 필수? | 이유 |
|---|---|---|---|
| 1 | 로그인 | 필수 | 그대로 |
| 2 | **내 정보** (`/myinfo`) | **필수 — 저장 전엔 다른 화면 모두 막힘** | 요청 "다른 화면 아무것도 못하고". 메뉴·내 계정 메뉴를 숨기고, 주소를 직접 쳐도 여기로 돌아온다. 로그아웃은 된다 |
| 3 | AI 기억 설정 (`/onboarding`, 기존) | 선택 — "나중에 하기" | 답을 맞추는 데 쓰는 정보(팀·역할·담당 서비스, `docs/SDD.md:253`)라 접근 조건이 아니다. 나중에 `/me/memory`로 고친다(`docs/SDD.md:285`) |
| 4 | 채팅 | — | 기존 첫 화면 |

- 두 번째부터는 로그인 → 바로 채팅. 내 정보는 **내 계정 → 내 정보 수정**, AI 기억은 **내 계정 → AI 기억 설정**.
- "profile" 두 개를 헷갈리지 않게 한다:

| | AI 기억 | 내 정보 (이번 요청) |
|---|---|---|
| 담는 것 | 팀·역할·담당 서비스 (`affiliation`·`rank`·`service`) | 이름·소속·전화번호·주소 |
| 저장 | LangGraph Store `(user_id, "profile")` (`docs/SDD.md:253`, `:333`) | 새 표 `user_profiles` (암호화) |
| LLM에 들어가나 | 들어감(답 맞춤) | **안 들어감** — 그래프·Store·Langfuse 어디에도 넣지 않는다 |
| 길 | `GET/PATCH/DELETE /me/memory` (`docs/SDD.md:285`) | `GET/PUT /me/profile` (제안) |

## 3. 실제 앱 고치는 곳
지금 `web/`는 HTML 로그인 MVP이고 React 전환은 아직이다(`web/web.md:7`). React로 옮길 때 시안 파일을 그대로 대응시킨다.

| 시안 | 실제 | 할 일 |
|---|---|---|
| `profile-preview.js` | `web/src/lib/profile-service.js` | `GET /me/profile`, `GET /me/profile?view=edit`, `PUT /me/profile`(CSRF 헤더 `X-CSRF-Token`, `backend/auth.py:565-576`) |
| `MyInfoPage.jsx` | `web/src/pages/MyInfoPage.jsx` | 시안과 같음. 입력 검사는 화면에도 두되 **서버 검사가 기준** |
| `DemoLayout.jsx` 막기 | `App.jsx`의 `Protected` | `/me` 응답의 `profile_completed`가 false면 `/myinfo`로. `/me`는 경로를 옮길 때마다 다시 부른다(기존 `refresh`) |
| `DemoLoginPage.jsx` | `LoginPage.jsx` | 로그인 뒤 `profile_completed`로 갈 곳을 고른다 |

### 서버 (제안)
| 경로 | 누가 | 응답 |
|---|---|---|
| `GET /me` (있음, `backend/auth.py:817-820`) | 로그인 | 지금 `{user_id, role}`(`backend/auth.py:496-498`) + **`profile_completed: bool`** (값은 안 줌, 있다/없다만) |
| `GET /me/profile` | 본인 | `{name, dept, phone_masked, address, updated_at}`. 없으면 404 |
| `GET /me/profile?view=edit` | 본인 | 위와 같되 `phone` 원래 값. `Cache-Control: no-store` |
| `PUT /me/profile` | 본인 + CSRF | 검사 → 암호화 → upsert → 가린 값으로 응답 |

- 사용자는 쿠키 JWT에서만 정한다. 요청 본문·주소의 `user_id`는 믿지 않는다(`docs/specs/login.md:54`). 라우트는 `create_current_user_dependency`(`backend/auth.py:599-607`)를 쓴다.
- **다른 사람 내 정보를 주는 경로는 만들지 않는다.** `/users/{id}/profile`·`/admin/.../profile` 없음. 관리자도 `GET /me/profile`로 자기 것만 본다. 관리자 목록 `GET /admin/users`는 `login_id, role, created_at, 최근 로그인`만(ADMIN_SPEC.md).
- 서버에서도 막을지(내 정보 없으면 `/chat` 등 업무 API가 403 `profile_required`)는 정할 것 5번. 화면만 막으면 API를 직접 부르면 지나간다.
- 오류 응답(422)에 입력값을 되풀이하지 않는다. 로그인 라우터가 이미 그렇게 한다(`backend/auth.py:550-560`). PUT 본문은 로그에 남기지 않는다.

### 입력 검사 (시안 = 서버 규칙)
| 칸 | 규칙 |
|---|---|
| 이름 | 글자·공백 2~20자 |
| 소속 | 1~40자 |
| 전화번호 | 숫자만 남겨 휴대폰 `01[016789]` 10~11자리 또는 지역번호 `02`·`031~064`. 저장은 `010-1234-5678` 모양으로 |
| 주소 | 5~100자 |

## 4. DB 표 (제안)
users 표는 손대지 않는다(`db/101_auth_users.sql:6-14`). 개인정보는 따로 둔다 → 로그인 조회(`backend/services/auth_store.py:19`의 칸 목록)에 개인정보가 섞이지 않는다.

```sql
-- db/104_user_profiles.sql (100번대 = 로그인·사용자, db/101_auth_users.sql:2)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id      uuid PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    name_enc     bytea NOT NULL,   -- 각 칸 = nonce(12바이트) + 암호문 + 태그(16바이트)
    dept_enc     bytea NOT NULL,
    phone_enc    bytea NOT NULL,
    address_enc  bytea NOT NULL,
    key_version  smallint NOT NULL, -- 어느 키로 잠갔나 (키 교체용)
    updated_at   timestamptz NOT NULL DEFAULT now()
);
```
- 평문 칸 없음. 전화번호 끝 4자리 칸도 두지 않는다 — 가린 값은 서버가 풀어서 만들면 되고, 전화번호로 찾는 기능이 없다(찾기가 필요해지면 그때 HMAC 칸을 검토).
- `profile_completed` = 이 표에 그 user_id 줄이 있는가.

## 5. 암호화 (서버)
| 항목 | 정한 것 |
|---|---|
| 방식 | AES-256-GCM. `cryptography` 라이브러리의 `AESGCM` |
| 라이브러리 | `backend/requirements.txt`에 **지금 없다**(전체 확인). 넣으면 PRD 라이브러리 표(`docs/PRD.md:317` 근처)에도 한 줄 |
| nonce | 칸마다, 저장할 때마다 새로 12바이트 무작위. 재사용 금지 |
| AAD | `user_id + 칸 이름` → 다른 사람·다른 칸에 암호문을 옮겨 붙이면 풀리지 않는다 |
| 키 | 32바이트, 환경변수(예: `PROFILE_ENC_KEYS=1:<base64>`). 로컬은 `.env`, 배포(Cloud Run)는 Secret Manager. **저장소에 두지 않는다** — `AUTH_SECRET` 규칙과 같다(`docs/ARCHITECTURE.md:50`, `docs/SPEC.md:70`, `docs/SDD.md:471`) |
| 키 없을 때 | 배포 모드는 앱이 시작하지 않는다(`AUTH_SECRET`과 같은 방식). 로컬은 정할 것 8번 |
| 키 교체 | 새 키를 `2:`로 더함 → 새로 쓰는 줄은 새 키 → 옛 줄은 일괄 다시 암호화 → 옛 키 뺌. 줄마다 `key_version`으로 고른다 |
| 가림 | 서버 응답에서 한다: `010-****-5678`. 화면에서 가리면 원래 값이 브라우저로 이미 온 것이다 |

## 6. 시험 (써야 할 것)
| 파일(제안) | 확인 |
|---|---|
| `tests/test_profile_crypto.py` | 잠갔다 풀면 같음 / 같은 값도 nonce가 달라 암호문이 다름 / 한 바이트 바꾸면 실패 / 다른 user_id(AAD)로 못 풂 / 옛 key_version으로 잠근 줄도 풀림 |
| `tests/test_profile_api.py` | 로그인 없이 401 / CSRF 없이 PUT 403 / 형식 틀리면 422이고 `error.details.fields`에 칸별 이유가 있고 응답에 입력값 없음(운영과 같은 `install_error_handlers`를 단 앱으로 시험) / GET은 가린 번호만 / `view=edit`만 원래 번호 / `/me`의 `profile_completed`가 저장 전 false, 뒤 true |
| `tests/test_auth_user_isolation.py`(있음)에 추가 | A가 저장 → B의 `GET /me/profile`은 404(A 값 안 나옴) / 관리자도 자기 것만 |
| 경로 목록 시험 | 앱의 모든 경로 중 `profile`이 들어간 것은 `/me/profile` 하나 |
| DB 시험 | 저장 뒤 `user_profiles` 줄을 그대로 읽어 전화번호·이름 문자열이 없음 |
| 화면 | 시안 `myinfo_flow.mjs`처럼 헤드리스로 첫 로그인 막힘·가림·수정·관리자 화면 누출 0 |

## 7. 누가 맡나 (팀 문서 기준)
| 부분 | 주인 | 근거 |
|---|---|---|
| 화면 `web/` | 강경희 | `docs/TEAM_GUIDE.md:82`, `web/web.md:9` |
| `/me` 확장, `/me/profile` 라우터 | 강경희 (`backend/auth.py` 주인) | `docs/TEAM_GUIDE.md:80` |
| `db/104_user_profiles.sql`, 저장·암호화(`backend/services/`) | 김승욱과 맞춤 (100번대·services 주인) | `db/101_auth_users.sql:2`, `docs/TEAM_GUIDE.md:79` |
| 시안·이 문서 | 박진형 | — |

## 8. 정할 것 (조장님·경희님께)
1. **"처음 계정 만들면"은 어느 길인가?** 회원가입은 범위 밖이다(`docs/specs/login.md:18`). 지금 계정은 데모 시드뿐이고, Google 첫 로그인은 계정을 만드는 자리(`backend/auth.py:159` `get_or_create_google_user`)만 있고 저장소 구현은 없다 → 관리자가 만든 계정의 첫 로그인으로 볼지, Google 첫 로그인으로 볼지.
2. **주소가 정말 필요한가?** 서비스(정책 질문·결정표)에 주소를 쓰는 곳이 없다. 안 쓰는 개인정보는 안 받는 게 원칙(최소 수집) → 빼거나 선택 칸으로. 전화번호도 쓰는 곳(예: 승인 알림)을 정해야 한다.
3. 관리자가 못 보면, 승인함·결정표에 이름을 보여 줘야 할 때는? (이름만 따로 공개 범위를 둘지)
4. 수정 화면에서 원래 전화번호를 보여 줄지, 칸을 비워 두고 "비우면 그대로"로 할지(더 안전).
5. 서버에서도 막을지(업무 API 403), 화면만 막을지.
6. 평가용 계정 A·B(`docs/PRD.md:388`)는 첫 로그인에 막힌다 → 가짜 내 정보를 미리 넣을지.
7. 이름 겹침: `/me/profile`(내 정보)과 Store `(user_id, "profile")`(AI 기억, `docs/SDD.md:253`). 헷갈리면 `/me/personal-info`로.
8. 로컬 데모 키: `.env`에 각자 만들기 / 실행마다 무작위(재시작하면 내 정보를 다시 입력).
9. 내 정보 "소속"과 AI 기억 "소속 팀"이 겹친다. 시안은 내 계정 메뉴에 내 정보 소속을 보여 준다. 하나로 합칠지.

## 9. 서버 구현 (sandbox, 11/5)
`class-3-sandbox`(진형 실험실)에서만 만들었다. 팀 레포·PR은 아직이다(검토 뒤).

| 파일 | 내용 |
|---|---|
| `db/104_user_profiles.sql` | 4장 표 그대로(+ `key_version > 0` 검사) |
| `backend/services/profile_crypto.py` | `ProfileCipher` AES-256-GCM, `PROFILE_ENC_KEYS="1:<b64>,2:<b64>"`, AAD = user_id + 칸 이름 |
| `backend/services/profile_store.py` | `PostgresProfileStore` get·exists·upsert만(목록·검색 없음) |
| `backend/profile_api.py` (새) | `GET /me/profile`, `GET /me/profile?view=edit`, `PUT /me/profile` |
| `backend/auth.py` (작게) | `create_auth_router(profile_completed=...)`, `MeResponse`. 콜백 없으면 `/me`·로그인 응답 그대로 |
| `backend/main.py` | `DATABASE_URL`이 있으면 내 정보 라우터를 붙인다. 키 없으면 배포 모드는 시작 안 함, 로컬 데모는 실행마다 무작위 |
| `backend/requirements.txt`, `.env.example` | `cryptography>=42`, `PROFILE_ENC_KEYS=`(만드는 명령 주석) |
| 시험 | `tests/test_profile_crypto.py`, `tests/test_profile_api.py`, `tests/test_profile_store_pg.py`(TEST_DATABASE_URL 있을 때만), `tests/profile_test_support.py`(메모리 저장소). `tests/test_auth_store.py` 1곳: `/me` 기대값에 `profile_completed: false` |
| 화면(이 시안) | `src/lib/profile-service.js`(새), `/myinfo` 실제 경로, `MyInfoPage`가 데이터 자리(`useSource`)를 받음, `Protected`가 `profile_completed === false`면 `/myinfo`로 |

만든 대로의 응답:
- `GET /me/profile` → `{name, dept, phone_masked, address, updated_at}`, 없으면 404. `view=edit`이면 `phone_masked` 대신 `phone`. 둘 다 `Cache-Control: no-store`. `view`에 다른 값은 422.
- `PUT /me/profile` → 로그인 + CSRF. 본문의 `user_id`는 무시. 틀리면 422 팀 표준 오류 `{"detail": message, "error": {"code": "validation_error", "message", "request_id", "details": {"fields": {칸: 이유}}}}`(입력값 없음, `ApiError`로 냄 — `HTTPException`의 dict detail은 운영 오류 처리기가 message·칸별 이유를 버린다). 성공하면 가린 보기로 응답.
- 저장소·암호 실패 → 503(이유 숨김). 저장소가 다른 사람 줄을 주거나 암호문을 옮겨 붙이면 풀리지 않아 503.
- 화면 검사는 따로 두지 않고 서버 422의 칸별 이유를 그대로 보여 준다(규칙이 한 곳).

시험 돌리기: `.venv\Scripts\python.exe -m pytest -q tests/test_profile_crypto.py tests/test_profile_api.py` / 진짜 DB: `TEST_DATABASE_URL=postgresql://...` 을 주고 `tests/test_profile_store_pg.py`.

남은 것:
1. **로그인 503**: `main.py`가 토큰 폐기 저장소를 넘기지 않아 로그인이 503(`backend/auth.py:355`). 내 정보 라우터도 같은 저장소를 쓴다. 조장님·경희님 몫(보고함). 로컬 확인은 scratchpad 실행기에서만 메모리 저장소로 우회했다.
2. 배포 키: `PROFILE_ENC_KEYS`를 Secret Manager에 두고 Cloud Run 환경변수로 연결.
3. 주인 검토: `backend/auth.py`·`profile_api.py` = 강경희, `db/104`·`backend/services/profile_*` = 김승욱. PR 전에 두 분 확인.
4. 8장 정할 것(주소 필요 여부, 서버에서도 막을지 등)은 그대로 열려 있다.

알려진 점(시안): 데모 경로의 AI 기억은 계정 구분 없이 한 칸(`MemorySettingsPage.jsx`의 `user?.user_id || 'anonymous'`)을 쓴다. 이번에 고치지 않았다.

## 시나리오
1. `lee.sre`로 처음 로그인 → 바로 **내 정보를 입력해 주세요** 화면. 위 메뉴는 없고 "내 정보를 저장하면 메뉴가 열립니다"와 로그아웃만 보인다. 순서 표시: 1 내 정보(필수) → 2 AI 기억 설정 → 3 채팅.
2. 주소창에 `/demo/chat`·`/demo/approvals`·`/demo/admin/users`를 쳐도 내 정보 화면으로 돌아온다.
3. 빈 채로 저장 → 4칸 모두 오류. 이름 `이영희1`, 전화 `1234`, 주소 `부산` → 칸마다 이유가 나오고 저장되지 않는다.
4. 바르게 넣고(전화 `01098765432`) **저장하고 다음** → AI 기억 설정 화면, 위에 "내 정보를 저장했습니다… 나중에 하기".
5. **나중에 하기** → 채팅. 메뉴(채팅·리콜 알림·변경 감시)가 열린다.
6. **내 계정** → 이름 이영희, 소속, 전화번호 `010-****-5432`(가린 값).
7. **내 정보 수정** → 보기 화면도 `010-****-5432`. **수정**을 누르면 그때만 칸에 `010-9876-5432`가 보인다. 소속·전화번호를 바꿔 저장 → "내 정보를 저장했습니다", `010-****-2222`. 새로고침해도 남는다.
8. 로그아웃 → `demo-admin`(최고 관리자) 로그인 → 내 정보가 이미 있어 바로 채팅.
9. **사용자 관리** → 표는 로그인 아이디·역할·가입일·최근 로그인뿐. 아래에 "개인정보(이름·소속·전화번호·주소)는 관리자에게도 보이지 않습니다". `lee.sre`를 조회해도 아이디·역할·가입일만. 관리자·승인함 화면 어디에도 이영희·전화번호가 없다.
10. 시안 띠의 **처음 상태로** → 내 정보도 지워진다. `lee.sre`는 다시 첫 로그인 화면, `demo-admin`은 그대로 바로 채팅.
