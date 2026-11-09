# 관리자 역할 관리(최고 관리자) API 명세서

상태: 구현 (2026-11-09 팀 레포로 옮김, 박진형). 11/5 로컬 구현을 그대로 옮겼고 달라진 점은 아래 "11/9 팀 레포로 옮기며 바꾼 것". 화면은 `web/react-app/src/pages/AdminUsersPage.jsx`(이미 main에 있음).

- 11/9 팀 레포로 옮기며 바꾼 것: ① 화면 주소와 API 주소가 같은 문제("처음 계획과 달라진 것" 4번)를 서버에서 풀었다. 브라우저가 `/admin/users`를 직접 열면(`Accept`에 `text/html`) React `index.html`을 내주고, 화면의 fetch(`Accept: */*`)에는 API가 답한다(`backend/admin_api.py` `html_page`, 시험 `tests/test_admin_api.py` 끝 2개). ② `db/104_user_profiles.sql`에 RLS를 켰다(다른 표와 같게). ③ 아래 "선행 조건"의 토큰 폐기 저장소는 main에서 이미 연결됐다(`backend/main.py` `app.state.token_revocation_store`).

- 11/5 번호 변경: 기록 표 SQL은 **`db/105_admin_role_log.sql`**, 내 정보는 `db/104_user_profiles.sql`. 102는 결정표(PR #54), 103은 PR #53이 쓴다(PR #54 조장 답).

## Why

- **페르소나**: 배포판을 운영하는 최고 관리자 1명, 승인함·결정표를 쓰는 관리자, 일반 사용자.
- **상황**: 정책 담당자는 관리자 역할을 겸한다(`docs/PRD.md:75`). 누가 관리자인지는 배포 뒤에도 바뀐다. 지금은 DB를 직접 고치는 방법밖에 없다.
- **문제**: 관리자 누구나 관리자를 만들 수 있으면 관리자 하나가 털릴 때 권한이 번진다. 배포판에는 첫 관리자를 만드는 길도 없다. 데모 시드는 로컬 전용이다(`backend/services/demo_seed.py:3`, `:8`).
- **목표 지표**: 최고 관리자가 아닌 요청의 사용자 관리 호출은 모두 403이고 DB 쓰기 0건. 등록·해제는 다시 로그인하지 않아도 다음 요청부터 반영된다. 아래 시험 목록이 모두 통과한다.

## Goal

- 배포판 하나에 최고 관리자 1명을 둔다(방식 B, 11/5 진형 결정). 최고 관리자만 관리자를 등록·해제한다.
- DB 역할은 지금처럼 `user`/`admin` 둘만 쓴다(`db/101_auth_users.sql:10`). 최고 관리자는 설정값 `PROVENA_OWNER_LOGIN_ID`로 정한다.
- 엔드포인트 3개(`GET /admin/users`, `POST /admin/users/{login_id}/promote`, `POST /admin/users/{login_id}/revoke`)와 `/me`의 `is_owner` 칸을 더한다.
- 등록·해제 기록 표 `admin_role_log`를 둔다.
- 배포판의 첫 계정(최고 관리자, 평가용 계정 A·B)을 만드는 일회용 명령 `python -m backend.services.create_account`를 둔다.
- **범위 = 한 회사용 (11/5 진형 결정)**: 회사 표·회사 칸·회사별 관리자는 두지 않는다. 회사가 여럿이면 회사마다 따로 설치한다(남은 일). 근거: `users` 표에 회사 칸이 없다(`db/101_auth_users.sql:6-14`). 지불 주체를 한 조직으로 본다(`docs/PRD.md:76`, `:125`).
- **Out of Scope**: 회원가입, 비밀번호 바꾸기·찾기 화면, 계정 만들기·지우기·비활성화 화면, 최고 관리자를 화면에서 바꾸기, 이름·부서 같은 개인정보(요청 1번, 강경희 담당), 문서 권한 그룹(`groups`, F-06) 편집, 여러 회사, 사용자 목록 페이지 나누기, 관리자 API 전용 요청 수 제한.

## What

### 역할

| 역할 | 할 수 있는 것 | 정하는 곳 |
|---|---|---|
| 일반 | 채팅·리콜 알림 등 로그인 기능 | DB `role='user'` |
| 관리자 | 일반 + 승인함·결정표·영향 미리보기 등 SDD "관리자" 경로(`docs/SDD.md:286-296`) | DB `role='admin'` |
| 최고 관리자 (배포판에 1명) | 관리자 + 사용자 관리(관리자 등록·해제) | DB `role='admin'` 이고 `is_active=true` 이고 `login_id`가 `PROVENA_OWNER_LOGIN_ID`와 정확히 같음 |

- 새 DB 역할(`owner`)을 만들지 않는 이유: DB가 `user`/`admin`만 받고(`db/101_auth_users.sql:10`), 그 밖의 역할은 로그인과 요청 인증에서 401로 막힌다(`backend/auth.py:594`, `:703`). 역할을 늘리면 SQL·로그인·시험을 모두 바꿔야 한다.

### Happy Path

1. 배포 담당이 Supabase에 `db/101_auth_users.sql`, `db/104_user_profiles.sql`, `db/105_admin_role_log.sql`을 적용하고, `create_account`로 최고 관리자 계정(role admin)을 만든다. Cloud Run에 `PROVENA_OWNER_LOGIN_ID`를 넣는다.
2. 서버가 시작할 때 그 계정이 있고 admin이고 활성인지 확인해 로그에 남긴다(값은 쓰지 않는다).
3. 최고 관리자가 로그인한다. `GET /me`가 `{user_id, role:"admin", is_owner:true}`를 돌려주고, 화면은 "사용자 관리" 메뉴를 보인다.
4. `GET /admin/users`로 목록(아이디·역할·만든 날짜)을 본다.
5. `POST /admin/users/{login_id}/promote`(CSRF 헤더 포함)로 일반 사용자를 관리자로 바꾼다. 서버는 역할 변경과 기록 1줄을 한 트랜잭션으로 쓴다.
6. 등록된 사람은 다시 로그인하지 않아도 다음 요청부터 관리자 경로를 쓴다. 서버가 요청마다 DB에서 역할을 다시 읽기 때문이다(`backend/auth.py:583`, `:591`). 사용자 관리는 계속 403이다.
7. `POST /admin/users/{login_id}/revoke`로 해제하면 다음 요청부터 관리자 경로가 403이다.

### 일반 계정은 어떻게 생기나

| 길 | 지금 상태 | 근거 |
|---|---|---|
| Google 로그인 첫 접속 때 자동 생성(role user) | 계약만 있음. `PostgresAuthStore`에 `get_or_create_google_user`가 없고 `users` 표에 provider·sub 칸이 없어, 지금 배포판에서는 Google 로그인이 실패 화면으로 간다 | `backend/auth.py:780`, `:671`, `:678-679`, `:786-788` / `backend/services/auth_store.py:3` / `db/101_auth_users.sql:6-14` / 시험 대역은 role `user`로 만듦 `tests/test_google_oauth.py:71` |
| `create_account` 명령(이 Spec) | 새로 만듦 | 아래 How |
| 로컬 데모 시드 | 로컬 전용, 바꾸지 않음 | `backend/services/demo_seed.py:3` |

- Google로 생긴 계정은 항상 `user`로 시작한다. 이메일로 기존 계정·관리자 권한을 잇지 않는 로그인 규칙(`docs/specs/login.md:79`)을 그대로 따른다. 관리자가 되는 길은 최고 관리자의 등록뿐이다.

### Edge Cases

| 상황 | 처리 |
|---|---|
| 로그인 안 함·쿠키 만료·변조 | 401 (기존 `get_current_user`, `backend/auth.py:584-589`) |
| 일반 사용자·일반 관리자가 사용자 관리 호출 | 403 `최고 관리자 권한이 필요합니다.` DB 쓰기 0건 |
| 최고 관리자가 아닌 사람이 없는 아이디로 promote | 403 (404 아님). 권한을 먼저 봐서 아이디가 있는지 새지 않게 한다 |
| `PROVENA_OWNER_LOGIN_ID`가 비었음 | 사용자 관리는 모두에게 403(닫힘). 시작 로그 경고 1줄. 나머지 앱은 정상 |
| 설정값 계정이 없음·`user`·비활성 | 시작 로그 오류 1줄(값은 쓰지 않음). 요청마다 다시 확인하므로 닫힌 채 유지되고, 계정을 고치면 재배포 없이 열린다 |
| 설정값이 Google 자동 아이디 머리글자로 시작 | 시작 로그 오류, 사용자 관리 닫힘(Google 계정이 최고 관리자 아이디를 차지하는 길을 막음). 머리글자는 열린 항목 4 |
| 아이디 대소문자 다름 (`Owner` 대 `owner`) | 다른 사람으로 본다(정확히 같을 때만 최고 관리자). `users.login_id` UNIQUE가 대소문자를 구분한다 |
| promote·revoke에 CSRF 쿠키·헤더 없음·다름 | 403 `CSRF 검증에 실패했습니다.`(`backend/auth.py:565-576`). DB 쓰기 0건 |
| 대상 아이디 없음 | 404 `사용자를 찾을 수 없습니다.` |
| 대상이 최고 관리자 본인(자기 해제 포함) | 409 `최고 관리자는 바꿀 수 없습니다.` 변경·기록 0건 |
| 대상이 비활성 계정 | 409 `비활성 계정입니다.` |
| 이미 admin인데 promote, 이미 user인데 revoke | 200 `changed:false`, 기록 0건(두 번 눌러도 같은 결과) |
| 요청 본문·주소에 `is_owner`, `role` 등을 넣음 | 무시. 권한은 쿠키 인증 + DB + 설정값으로만 정한다 |
| 역할 변경은 됐는데 기록 쓰기 실패 | 한 트랜잭션이라 둘 다 되돌린다. 503 |
| 저장소 오류 | 503 `인증 저장소를 사용할 수 없습니다.`(기존 문구) |
| 해제된 관리자가 열어 둔 승인함 화면 | 다음 API 요청이 403. 화면은 `/me`를 다시 불러 메뉴를 숨긴다 |

## How

### 엔드포인트

| 메서드 | 경로 | 권한 | 요청 | 성공 응답 | 오류 |
|---|---|---|---|---|---|
| GET | `/me` (기존, 칸 추가) | 로그인 | - | 200 `{user_id, role, is_owner}` | 401, 503 |
| GET | `/admin/users` | 최고 관리자 | - | 200 `{"users":[{"login_id","role","is_owner","created_at"}]}`, `created_at` 오름차순 | 401, 403, 503 |
| POST | `/admin/users/{login_id}/promote` | 최고 관리자 + CSRF | 본문 없음, 헤더 `X-CSRF-Token` | 200 `{"login_id","role":"admin","changed":true\|false}` | 401, 403, 404, 409, 503 |
| POST | `/admin/users/{login_id}/revoke` | 최고 관리자 + CSRF | 본문 없음, 헤더 `X-CSRF-Token` | 200 `{"login_id","role":"user","changed":true\|false}` | 401, 403, 404, 409, 503 |

- 검사 순서: 인증(401) → 최고 관리자(403) → CSRF(403) → 대상 조회(404) → 대상이 최고 관리자·비활성(409) → 쓰기. CSRF는 쓰기 전에 반드시 본다.
- 응답에 `Cache-Control: no-store`(기존 `/me`와 같게, `backend/auth.py:819`).
- 목록 칸은 `login_id`, `role`, `is_owner`, `created_at`만이다. `user_id`, `password_hash`, `groups`, `is_active`는 내보내지 않는다. `users` 표에 마지막 로그인 칸은 없다(`backend/`·`db/`에서 `last_login` 0건) → 시안의 `last_login`(ADMIN_SPEC.md:40)은 빼고 열린 항목 3으로 둔다.
- `is_owner`는 화면이 메뉴를 숨기는 데만 쓴다. 서버는 화면을 믿지 않고 요청마다 다시 확인한다.
- SDD 4-4 엔드포인트 표(`docs/SDD.md:278-297`)에 위 3줄을 더해야 한다(조장 문서).

### 최고 관리자 확인

- (구현: `backend/auth.py`가 아니라 새 파일 `backend/admin_api.py`의 `owner_guard`·`is_owner`에 뒀다. auth.py 변경을 `/me` 칸 1개 + 콜백 인자 1개로 줄이려고. 아래 "구현 (로컬, 2026-11-05)" 절.) 처음 계획: `backend/auth.py`에 `create_require_owner_dependency(*, store, owner_login_id, secret=None, revocation_store=None)`를 더한다. 안에서 기존 `require_admin`(`backend/auth.py:610-623`)을 먼저 부르고, `owner_login_id`가 비어 있지 않고 `hmac.compare_digest(user.login_id, owner_login_id)`일 때만 통과시킨다. 아니면 403.
- 설정값은 `main.py`가 시작할 때 한 번 읽어 넘긴다(요청마다 환경변수를 읽지 않음, 시험에서 값을 넣기 쉽게). 최고 관리자를 바꾸려면 Cloud Run 새 리비전이 필요하고, 그래야 화면에서 못 바꾼다는 결정과 맞는다.
- **`login_id`로 정하는 이유**: `user_id`(UUID)는 DB가 만들 때 정해져(`db/101_auth_users.sql:7`) 계정을 만들기 전에 설정할 수 없다. `login_id`는 UNIQUE이고(`:8`) 바꾸는 API가 없다(로그인 Spec 범위 밖, `docs/specs/login.md:18`). 대신 기록 표에는 바뀌지 않는 `user_id`를 쓴다. 남는 위험: DB에서 누가 아이디를 바꾸거나 같은 아이디로 다시 만들면 그 계정이 최고 관리자가 된다 → DB 접속 권한이 있는 사람만 가능하고, 그래도 role admin이어야 한다.

### 저장소 (`backend/services/auth_store.py`, 김승욱)

| 메서드 | 하는 일 |
|---|---|
| `list_users()` | `SELECT login_id, role, created_at FROM users ORDER BY created_at` (파라미터 바인딩, 문자열 조립 없음) |
| `set_role(target_login_id, new_role, by_user_id)` | 한 트랜잭션: `SELECT ... FOR UPDATE` → 같으면 `changed=False` → 다르면 `UPDATE users SET role` + `INSERT INTO admin_role_log`. 지금 연결은 `autocommit=True`라(`backend/services/auth_store.py:26`) `with conn.transaction():`으로 묶는다 |
| `create_user(login_id, password_hash, role)` | `INSERT`만. 같은 아이디가 있으면 오류(덮어쓰지 않음) |
| `set_password(login_id, password_hash)` | 해시만 바꾸고 `is_active=true`. 역할은 그대로 |

- 기존 `upsert_user`(`backend/services/auth_store.py:69-81`)는 역할까지 덮어써서 배포 계정에는 쓰지 않는다. 데모 시드 전용으로 남긴다.
- 파일 머리 설명 "계정 만들기는 데모 시드가 upsert_user로만 한다"(`backend/services/auth_store.py:3-4`)를 함께 고친다.

### DB 변경: `db/105_admin_role_log.sql` (100번대, 김승욱)

```sql
-- 관리자 등록·해제 기록 (docs/specs/admin-roles.md). 화면에서 한 일만 남긴다. 여러 번 돌려도 된다.
CREATE TABLE IF NOT EXISTS admin_role_log (
    log_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at             timestamptz NOT NULL DEFAULT now(),
    by_user_id     uuid NOT NULL REFERENCES users(user_id),
    target_user_id uuid NOT NULL REFERENCES users(user_id),
    action         text NOT NULL CHECK (action IN ('promote', 'revoke'))
);
CREATE INDEX IF NOT EXISTS admin_role_log_at ON admin_role_log (at);
-- Supabase는 public 표를 Data API로 내보낸다(db/201_search.sql:89 설명과 같은 이유).
ALTER TABLE admin_role_log ENABLE ROW LEVEL SECURITY;
```

- 번호: `db/101_auth_users.sql:2`가 100번대를 김승욱 파트(로그인·사용자)로 정했다. 102는 결정표(PR #54), 103은 PR #53 → 내 정보 104(`db/104_user_profiles.sql`), 기록 표 105.
- 기록 칸은 누가·누구를·무엇을·언제만. 아이디 문자열·IP·브라우저 정보는 넣지 않는다.
- 로컬: `ensure_schema()`가 101 파일만 읽었다 → 101 다음에 105도 읽게 고쳤다(`backend/services/auth_store.py`). 배포: 스키마는 미리 적용해야 한다(`backend/main.py:10`).
- `users` 표에는 RLS가 없다(`db/101_auth_users.sql` 전체에 `ROW LEVEL` 0건). 비밀번호 해시가 있는 표라 105에 `ALTER TABLE users ENABLE ROW LEVEL SECURITY;`를 같이 넣을지 열린 항목 3.

### 첫 계정 만들기: `create_account` 명령

**고른 방법: 일회용 명령** `python -m backend.services.create_account` (파일 `backend/services/create_account.py`, 김승욱 폴더 `TEAM_GUIDE.md:79`). 새 최상위 `scripts/` 폴더는 저장소 구조(`docs/TEAM_GUIDE.md:105-159`)에 없어 만들지 않는다.

| 방법 | 장점 | 단점 | 판정 |
|---|---|---|---|
| ① 일회용 명령 (고름) | 한 번만 돌고 비밀번호가 배포 환경에 남지 않는다. 로그인과 같은 `hash_password`(`backend/auth.py:150-155`, 8자~72바이트 검사)를 쓴다. 가짜 저장소로 시험할 수 있다 | 돌리는 사람 PC에 Supabase 연결 문자열이 필요하다 | 채택 |
| ② SQL 직접 입력 | 도구가 필요 없다 | 해시를 따로 만들어야 하고 길이 검사가 없다. 해시·아이디가 SQL 편집기 기록에 남는다 | 버림 |
| ③ 앱 시작 때 환경변수로 넣기 | 자동 | 인스턴스가 뜰 때마다 돌고 비밀번호가 Cloud Run 환경에 계속 남는다. 데모 시드를 배포에 쓰지 않는다는 규칙(`backend/services/demo_seed.py:8`)과 같은 길이 된다 | 버림 |

사용법:

```
python -m backend.services.create_account --login-id <아이디> --role admin      # 최고 관리자
python -m backend.services.create_account --login-id <아이디> --role user       # 평가용 계정 A·B
python -m backend.services.create_account --login-id <아이디> --reset-password  # 비밀번호 잃었을 때
```

- `DATABASE_URL`은 환경변수(돌리는 사람의 로컬 `.env`, 커밋 금지)에서 읽는다. 연결 문자열은 화면·로그에 쓰지 않는다(`backend/main.py:48` 방식).
- 비밀번호는 화면에 안 보이는 입력(`getpass`)으로 두 번 받는다. 셸 기록에 남지 않게 명령 인자로 받지 않는다. 터미널이 없을 때만 환경변수 `PROVENA_NEW_ACCOUNT_PASSWORD`를 읽는다.
- 같은 아이디가 있으면 멈춘다(덮어쓰지 않음). `--reset-password`일 때만 해시를 바꾸고 역할은 그대로 둔다.
- `--role`은 `user`/`admin`만. 출력은 `계정 생성: <아이디> (<역할>)` 한 줄뿐, 비밀번호·해시는 쓰지 않는다.
- 비밀번호는 PC에서 bcrypt로 바꾸고 해시만 DB로 보낸다.
- 이 명령으로 만든 일은 `admin_role_log`에 남지 않는다(화면 기록 전용). 돌린 사람이 `db/db.md` 작업 기록에 "누가, 언제, 어떤 역할 몇 개"만 적는다(아이디·비밀번호는 적지 않음).

### 설정값

| 이름 | 어디 | 값 | 비어 있으면 |
|---|---|---|---|
| `PROVENA_OWNER_LOGIN_ID` | Cloud Run 환경변수. `.env.example` "로그인" 칸(`.env.example:69-76`) 아래에 빈 키 + 설명만 | 최고 관리자 아이디 | 사용자 관리 닫힘(403), 경고 로그 |
| `PROVENA_NEW_ACCOUNT_PASSWORD` | `create_account`를 터미널 없이 돌릴 때만 | 새 비밀번호 | 숨김 입력으로 받음 |

- 로컬 데모에서는 `.env`에 `PROVENA_OWNER_LOGIN_ID`를 데모 관리자 아이디로 적으면 된다. 데모 시드는 바꾸지 않는다(`backend/services/demo_seed.py:3`).
- 최고 관리자 아이디는 비밀값은 아니지만 저장소·채팅에 적지 않는다(계정 값 규칙 `db/101_auth_users.sql:3`).

### 시작 때 확인 (`backend/main.py`, 김승욱)

- `store`가 있으면 lifespan에서 `check_owner(store, owner_login_id)`를 한 번 돈다.
  - 비어 있음 → `warning: 최고 관리자 설정이 없어 사용자 관리를 닫았다`
  - 계정 없음·`user`·비활성·Google 머리글자 → `error: 최고 관리자 설정이 users 표와 맞지 않아 사용자 관리를 닫았다` (아이디 값은 쓰지 않음)
  - DB 조회 실패 → `warning`, 종류 이름만(`backend/main.py:48` 방식)
- 서버는 멈추지 않는다. `AUTH_SECRET`과 달리(`backend/auth.py:660`) 이 설정은 기능 하나만 막으면 되고, `/health`와 로그인은 G1 때문에 살아 있어야 한다.
- 시작 확인은 알림이다. 실제로 막는 곳은 요청마다 도는 최고 관리자 확인이다. 그래서 배포 뒤에 `create_account`를 돌려도 재배포 없이 열린다.

### 보안 규칙

1. 닫힘이 기본: 설정이 없거나 틀리면 아무도 사용자 관리를 못 한다.
2. 최고 관리자는 화면에서 대상이 될 수 없다(409). 자기 해제도 409라 관리자가 0명이 되는 일이 없다.
3. 권한은 쿠키 인증 + DB 역할 + 설정값으로만 정한다. JWT 안의 role과 요청 본문은 믿지 않는다(`backend/auth.py:583`, `:617`).
4. 바꾸는 요청은 CSRF 필수(`backend/auth.py:565-576`, `:632` 안내 그대로).
5. 역할 변경과 기록은 한 트랜잭션.
6. 목록에 개인정보·해시·UUID를 내보내지 않는다.
7. 계정 값은 코드·저장소·채팅에 쓰지 않는다(`db/101_auth_users.sql:3`, `backend/services/demo_seed.py:8`).
8. 요청 수 제한: 로그인 제한(`backend/auth.py:501-541`)은 그대로이고 관리자 API에는 따로 두지 않는다. 최고 관리자 1명만 부를 수 있어서다(Out of Scope).
9. 해제는 토큰을 폐기하지 않는다. 요청마다 역할을 다시 읽으므로 필요 없다.

### 선행 조건 (지금 main e847c88에서 막힌 것)

- **토큰 폐기 저장소가 연결되지 않아 배포 배선으로는 로그인이 503이다.** `backend/main.py:117`이 `revocation_store`를 넘기지 않고 `app.state.token_revocation_store`도 두지 않는다 → `backend/auth.py:355-357`이 오류 → `:710-713`에서 503. 재현(11/5, 가짜 저장소 + main.py와 같은 인자로 라우터 생성): `POST /auth/login` → 503 `인증 폐기 저장소를 사용할 수 없습니다.` 로그인 Spec도 J-05를 열림으로 적었다(`docs/specs/login.md:78`). 관리자 기능은 이것이 연결된 뒤에야 쓸 수 있다.
- Google 자동 계정은 저장소·칸이 없어 아직 안 된다(위 표).

### 누가 무엇을

| 일 | 파일 | 담당 (`docs/TEAM_GUIDE.md:79-82`) |
|---|---|---|
| 이 Spec, 시험 `tests/test_admin_roles.py` | `docs/specs/`, `tests/` | 박진형 |
| 최고 관리자 확인, 관리자 라우터 3개, `/me`의 `is_owner` | `backend/auth.py` | 강경희 |
| 저장소 메서드, `create_account`, `105` SQL, `ensure_schema`, `main.py` 배선·시작 확인, `.env.example` | `backend/services/`, `db/`, `backend/main.py` | 김승욱 |
| 사용자 관리 화면 | `web/` | 강경희 (시안: 박진형) |
| Supabase 적용, Cloud Run 설정, 첫 계정 실행 | 배포 | 열린 항목 1 (조장 또는 강경희, `docs/TEAM_GUIDE.md:56`) |

## AC (Given-When-Then)

시험은 실제 DB 없이 가짜 저장소로 돈다(`tests/test_auth_security_dependencies.py:24-40`의 `GuardStore` 방식). 쓰기 횟수를 센다.

- **AC-01 목록**: GIVEN 최고 관리자 쿠키, WHEN `GET /admin/users`, THEN 200이고 각 줄의 키가 정확히 `login_id, role, is_owner, created_at`이다.
- **AC-02 권한 없음**: GIVEN 일반 관리자 / 일반 사용자 / 쿠키 없음, WHEN `GET /admin/users`, THEN 403 / 403 / 401.
- **AC-03 닫힘**: GIVEN 설정값이 빔 / 없는 아이디 / `user` 계정 / Google 머리글자, WHEN 그 이름의 계정(있으면)으로 `GET /admin/users`, THEN 403.
- **AC-04 등록**: GIVEN 최고 관리자와 일반 사용자 X, WHEN X promote(CSRF 포함), THEN 200 `changed:true`, X의 역할 admin, 기록 1줄(by = 최고 관리자 user_id, target = X user_id, promote).
- **AC-05 다시 로그인 없이 반영**: GIVEN X가 등록 전에 받은 쿠키, WHEN 등록 뒤 같은 쿠키로 관리자 경로(`create_require_admin_dependency`) 호출, THEN 200. 그리고 `GET /admin/users`는 403.
- **AC-06 해제**: GIVEN 관리자 X, WHEN revoke, THEN 200 `changed:true`, 기록 1줄, 같은 쿠키로 관리자 경로 403, `/me`의 role `user`.
- **AC-07 같은 요청 두 번**: GIVEN 이미 admin, WHEN promote, THEN 200 `changed:false`, 기록 0줄.
- **AC-08 없는 아이디**: GIVEN 최고 관리자, WHEN 없는 아이디 promote, THEN 404, 쓰기 0.
- **AC-09 존재 숨김**: GIVEN 일반 관리자, WHEN 없는 아이디 promote, THEN 403(404 아님), 쓰기 0.
- **AC-10 최고 관리자 보호**: GIVEN 최고 관리자, WHEN 자기 아이디 promote / revoke, THEN 409, 쓰기 0.
- **AC-11 비활성 대상**: GIVEN 비활성 계정, WHEN promote, THEN 409, 쓰기 0.
- **AC-12 CSRF**: GIVEN 최고 관리자, WHEN CSRF 헤더 없음 / 쿠키와 다름, THEN 403, 쓰기 0.
- **AC-13 요청으로 올리기 불가**: GIVEN 일반 관리자, WHEN 본문 `{"is_owner":true}`·주소 `?owner=1`을 붙여 호출, THEN 403.
- **AC-14 대소문자**: GIVEN 설정값 `owner`, WHEN 아이디 `Owner`인 admin이 호출, THEN 403.
- **AC-15 트랜잭션**: GIVEN 기록 쓰기가 실패하는 저장소, WHEN promote, THEN 503이고 역할도 바뀌지 않았다.
- **AC-16 저장소 오류**: GIVEN 조회가 실패하는 저장소, WHEN 사용자 관리 호출, THEN 503.
- **AC-17 `/me`**: GIVEN 최고 관리자 / 일반 관리자, WHEN `/me`, THEN `is_owner` true / false.
- **AC-18 시작 확인**: GIVEN 설정값 빔 / 계정 없음 / `user` / 비활성, WHEN 앱 시작, THEN 경고·오류 로그 1줄, 로그에 설정값 문자열이 없음, `/health` 200.
- **AC-19 계정 만들기**: GIVEN 가짜 저장소, WHEN `create_account --role admin`, THEN 저장된 해시가 `verify_password`로 맞고, 출력에 비밀번호·해시가 없다.
- **AC-20 덮어쓰기 금지**: GIVEN 있는 아이디, WHEN `--reset-password` 없이 실행, THEN 0이 아닌 종료 코드, 저장소 변경 0. WHEN `--reset-password`, THEN 해시만 바뀌고 역할은 그대로.
- **AC-21 입력 검사**: WHEN 7자 비밀번호 / `--role owner`, THEN 오류로 멈추고 메시지에 입력값이 없다.
- **AC-22 회귀**: 기존 인증 시험과 전체 `pytest -q`가 그대로 통과한다.

## 열린 항목 (조장님께)

1. **첫 계정은 누가 돌리나**: 조장님이 돌리나, 팀 지침서대로 강경희(운영 DB·Cloud Run 환경변수·평가용 계정 A·B 절차, `docs/TEAM_GUIDE.md:56`)가 돌리나. 최고 관리자 아이디는 누구 것으로 하나.
2. **평가용 계정 A·B 역할**: 둘 다 `user`인가, 하나는 `admin`(최고 관리자 아님)인가. 평가자가 승인함까지 보려면 admin이 하나 필요하다(G1 "핵심 시나리오 끝까지"). A·B 중 한 명만 재무 절을 보는 일(`docs/PRD.md:184`)은 `groups`라 이 Spec 밖.
3. **표 칸**: `users`에 RLS를 105에서 같이 켤지, `last_login` 칸을 더할지(더하면 로그인 성공 때 쓰기가 생김, `backend/auth.py` 수정).
4. **Google 자동 아이디 머리글자**: Google 계정의 `login_id`를 어떤 머리글자로 만들지(시험 대역은 `google-`, `tests/test_google_oauth.py:71`). 최고 관리자 설정값이 그 머리글자로 시작하면 막는다.
5. **토큰 폐기 저장소(J-05) 연결 시점**: 지금 배선으로는 로그인이 503이라 관리자 기능도 그 뒤다.

## 시나리오

| 단계 | 누가 | 하는 일 | 보는 것 / HTTP |
|---|---|---|---|
| 1 배포 준비 | 배포 담당(열린 항목 1) | Supabase SQL 편집기에서 `101`, `104`, `105` 적용. Cloud Run에 `DATABASE_URL`, `AUTH_SECRET`, `PROVENA_OWNER_LOGIN_ID`를 비밀값·환경변수로 넣고 새 리비전 배포 | 시작 로그 `error: 최고 관리자 설정이 users 표와 맞지 않아 사용자 관리를 닫았다`(아직 계정 없음). `/health` 200 |
| 2 첫 계정 | 같은 사람 | 자기 PC에서 `python -m backend.services.create_account --login-id <설정값과 같은 아이디> --role admin`, 비밀번호 숨김 입력 2번 | `계정 생성: <아이디> (admin)` 한 줄. 재배포 필요 없음 |
| 3 평가용 계정 | 같은 사람 | 같은 명령을 `--role user`(또는 열린 항목 2 결과)로 2번 | 계정 2개. 값은 강사 DM으로만 제출 |
| 4 최고 관리자 로그인 | 최고 관리자 | `GET /auth/csrf` → `POST /auth/login` → `GET /me` | 200 `{role:"admin", is_owner:true}`, "사용자 관리" 메뉴 보임 |
| 5 일반 사용자 로그인 | 사용자 X | 로그인 → `GET /me` → 승인함 주소 직접 입력(`GET /approvals`) | `/me` 200 `{role:"user", is_owner:false}`. 승인함 403 |
| 6 등록 | 최고 관리자 | `GET /admin/users` → X 줄에서 "관리자 등록" → 확인 창 → `POST /admin/users/X/promote` | 목록 200(아이디·역할·날짜만). 등록 200 `changed:true`. 기록 1줄 |
| 7 등록 뒤 X | 사용자 X (다시 로그인 안 함) | 화면 이동 때 `/me` → 승인함 `GET /approvals` → 사용자 관리 주소 직접 `GET /admin/users` | `/me` role admin, 승인함 200, 사용자 관리 403 "최고 관리자 권한이 필요합니다", 메뉴에 사용자 관리 없음 |
| 8 X가 등록 시도 | 사용자 X | `POST /admin/users/Y/promote` | 403, DB 쓰기 0 |
| 9 해제 | 최고 관리자 | X 줄 "관리자 해제" → `POST /admin/users/X/revoke` | 200 `changed:true`, 기록 2줄째 |
| 10 해제 뒤 X | 사용자 X (같은 쿠키) | 열어 둔 승인함에서 다음 요청 | 403. `/me` role user → 관리자 메뉴 사라짐 |
| 11 최고 관리자 보호 | 최고 관리자 | 자기 줄 revoke 시도(화면은 버튼을 안 보이지만 주소로 직접) | 409 "최고 관리자는 바꿀 수 없습니다" |
| 12 잘못된 설정 A | 배포 담당 실수 | `PROVENA_OWNER_LOGIN_ID`를 비우고 배포 | 시작 경고 1줄. 최고 관리자도 사용자 관리 403, `/me` `is_owner:false`. 승인함·채팅은 정상 |
| 13 잘못된 설정 B | 배포 담당 실수 | 설정값을 오타 아이디 / `user` 계정으로 배포 | 시작 오류 1줄(값 없음). 사용자 관리 모두 403. 고친 값으로 새 리비전 배포하면 열림 |
| 14 비밀번호 잃음 | 최고 관리자 → 배포 담당 | `create_account --login-id <아이디> --reset-password` | 해시만 바뀜, 역할 admin 유지. 새 비밀번호로 로그인 200 |
| 15 최고 관리자 바꾸기 | 조장 결정 → 배포 담당 | 새 사람을 admin으로 만든 뒤(6단계 또는 2단계) Cloud Run 설정값을 바꿔 새 리비전 배포 | 새 사람 `is_owner:true`. 예전 최고 관리자는 일반 관리자로 남고, 새 최고 관리자가 해제할 수 있다 |

## 구현 (로컬, 2026-11-05)

11/5에는 박진형 로컬에서만 만들었고 11/9 이 PR로 팀 레포에 옮겼다.

### 만든·바꾼 파일

| 파일 | 내용 | 담당 (`docs/TEAM_GUIDE.md:79-82`) |
|---|---|---|
| `db/105_admin_role_log.sql` (새) | 위 SQL 그대로(번호만 105) | 김승욱 |
| `backend/services/auth_store.py` | `create_user`(:102, `ON CONFLICT DO NOTHING` → 있으면 `AccountExistsError`), `set_password`(:115), `list_users`(:122, 해시를 SELECT 하지 않음), `set_role`(:130, `conn.transaction()` 안에서 `FOR UPDATE` → UPDATE + 기록 INSERT, 결과 `changed/unchanged/missing/inactive`), `ensure_schema`가 101 다음 105(:159). `upsert_user`는 데모 시드용 그대로 | 김승욱 |
| `backend/admin_api.py` (새) | `owner_configured`(:46, 빈 값·`google-` 머리글자면 닫힘), `is_owner`(:50, admin + 활성 + `hmac.compare_digest`), `check_owner`(:61, 시작 로그 1줄, 값 없음), `create_admin_router`(:91, 엔드포인트 3개), `owner_check_for`(:169, `/me`용) | 강경희(auth) 쪽과 맞출 것 |
| `backend/auth.py` | `MeResponse.is_owner`(:505), `create_auth_router(owner_check=...)`(:660), `/me`가 채움(:838). 콜백을 안 넘기면 `/me`는 예전 모양(`response_model_exclude_none`) | 강경희 |
| `backend/main.py` | `PROVENA_OWNER_LOGIN_ID`를 시작 때 한 번 읽음(:113, 앞뒤 공백만 뗌), lifespan에서 `check_owner`(:121), `/me` 콜백(:136), 관리자 라우터(:140) | 김승욱 |
| `backend/services/create_account.py` (새) | 위 "첫 계정 만들기" 그대로. 종료 코드 0 성공 / 2 입력 / 3 같은 아이디·없는 아이디 / 4 DB. argparse 기본 오류(입력값을 되풀이함)를 값 없는 문장으로 바꿈 | 김승욱 |
| `tests/test_admin_api.py`, `tests/test_create_account.py`, `tests/test_admin_store_pg.py` (새), `tests/test_auth_store.py`(`/me` 기대값에 `is_owner:false` 추가) | AC-01~21 | 박진형 |

### 처음 계획과 달라진 것

1. 최고 관리자 확인을 `auth.py`가 아니라 `backend/admin_api.py`에 뒀다(위). 검사 순서는 그대로: 인증 → 최고 관리자 → CSRF(`admin_api.py:130`) → 대상 조회 → 409 → 쓰기.
2. 기록을 보는 API는 없다(Spec 엔드포인트 3개 그대로). 화면은 "이 화면에서 한 변경"만 보이고, 서버 기록은 `admin_role_log` 표에 남는다.
3. 목록에는 비활성 계정도 나온다(`is_active`는 내보내지 않음). 그 줄을 등록하면 409 `비활성 계정입니다.`
4. 화면 주소 `/admin/users`와 API 주소 `/admin/users`가 같다. 로컬 vite는 `Accept: text/html`(화면 열기)만 index.html로 돌린다(`provena-ivory-1105/vite.config.js`). 배포에서 같은 도메인으로 화면을 내주면 같은 처리가 필요하다(남은 일).

### 시험 돌리는 법

```
.venv/Scripts/python.exe -m pytest -q tests/test_admin_api.py tests/test_create_account.py   # DB 없이
TEST_DATABASE_URL=<로컬 시험 DB> .venv/Scripts/python.exe -m pytest -q tests/test_admin_store_pg.py   # 로컬 Postgres 있을 때만
.venv/Scripts/python.exe -m pytest -q   # 전체
```

결과(11/5): 새 시험 35개 함수(매개변수 포함 52건) — DB 없이 48 통과, PG 4 통과(로컬 `app_myinfo`). 전체 681 통과 / 35 건너뜀(그 전 621/31, 늘어난 60 = 이 기능 48 + 다른 작업의 `tests/test_mcp_client.py` 12, 건너뜀 +4 = PG 시험). 변이 시험 11/11 잡힘(최고 관리자 확인이 login_id 무시, 존재를 권한보다 먼저 봄, 최고 관리자 대상 허용, 목록에 password_hash, CSRF 건너뜀, 두 번째도 changed:true, Google 머리글자 허용, 역할 무시, 트랜잭션 없음, 같은 아이디 덮어씀, 해시 출력). 실제 서버 + 헤드리스 Chrome 2개 60/60.

### 알아 둘 것

- 윈도우에서 `create_account`를 `< NUL`로 돌리면 `isatty()`가 참이라 숨김 입력을 기다리며 멈춘다. 터미널 없이 돌릴 때는 빈 파이프(예: PowerShell `'' | python -m backend.services.create_account ...`)와 `PROVENA_NEW_ACCOUNT_PASSWORD`를 쓴다.
- 로그인 503(토큰 폐기 저장소 미연결, 위 "선행 조건")은 고치지 않았다. 로컬 확인은 메모리 저장소로 했다.
