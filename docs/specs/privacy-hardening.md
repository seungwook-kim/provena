# 개인정보 보호 강화

## Why

- **페르소나**: Provena 사용자와 서비스를 운영하는 관리자
- **상황**: 프로필 개인정보가 저장·조회·관리자 API·로그를 통해 처리된다.
- **문제**: 암호화 키가 없을 때 임시 키를 사용하면 재시작 후 복호화가 불가능하고, AI 기억 저장 구조가 개인정보 보호 경계를 명확히 갖지 못한다.
- **측정 지표**: 프로필 저장 암호문에서 평문 미검출, 타인 프로필 조회 0건, 관리자 프로필 원문 조회 0건, 키 미설정 저장 0건

## Goal

- **해결 목표**: 프로필 개인정보는 AES-256-GCM 암호문으로만 PostgreSQL에 저장하고, 본인 외 조회 경로를 제공하지 않는다.
- **성공 기준**: 32바이트 키·새 nonce·AAD·키 버전을 사용하며, 키가 없거나 잘못되면 앱 시작/저장을 거부한다.
- **Out of Scope**: DB 스키마 변경, 운영 DB 접근, 새 AI 기억 영구 저장소 구축, 프런트엔드 변경

## What

**Happy Path**

1. 서버가 `PROFILE_ENC_KEYS`에서 버전별 32바이트 키를 읽는다.
2. 이름·소속·전화번호·주소를 필드별 새 nonce와 AAD로 AES-256-GCM 암호화한다.
3. `user_profiles`의 `*_enc` bytea 칸에 nonce+암호문+태그를 저장한다.
4. 인증된 본인 요청만 `/me/profile`에서 복호화한다.
5. 관리자 API는 `user_profiles`를 읽지 않고 계정 관리 최소 정보만 반환한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 키 미설정·형식 오류 | 앱 시작을 거부하고 평문 저장하지 않음 |
| EC-02 | 암호문 변조·키 불일치 | 일반 503 오류만 반환하고 원문·암호문·키를 노출하지 않음 |
| EC-03 | 타인 ID를 본문에 포함 | 본문 ID를 무시하고 JWT 사용자만 사용 |
| EC-04 | 관리자 타인 프로필 요청 | 타인 프로필 경로 자체가 없어 접근 차단 |
| EC-05 | 기존 평문 의심 데이터 | 자동 덮어쓰기·삭제 없이 백업 후 별도 수동 전환 절차 필요 |
| EC-06 | 로컬 데모(`PROVENA_ENV=local`·`PROVENA_DEV_MODE=1`)에서 키 미설정 (K-23) | 키를 한 번 만들어 키 파일(`PROFILE_KEY_FILE`, 비우면 `~/.provena/local_demo_profile.key`)에 두고 재시작 때 다시 읽음. 로컬 데모가 아니면 키 파일을 읽지도 쓰지도 않음(EC-01 그대로) |
| EC-07 | 로컬 데모가 만든 키로 옛 줄을 풀 수 없음(키 파일이 사라짐) (K-23) | `GET /me/profile`이 404 `profile_reentry_required`. 화면이 빈 칸을 열고 `PUT`으로 덮어씀. `PROFILE_ENC_KEYS`를 준 실행은 EC-02 그대로 503 |

## How

- **암호화**: `backend/services/profile_crypto.py`의 `AESGCM`, 32바이트 키, 12바이트 nonce, `user_id|field` AAD
- **저장**: `backend/services/profile_store.py`, `db/104_user_profiles.sql`의 암호문 전용 칸
- **API**: `backend/profile_api.py`의 `/me/profile`만 본인 프로필을 처리
- **관리자**: `backend/admin_api.py`와 `backend/services/auth_store.py`는 프로필 테이블을 조회하지 않음
- **키 교체**: 새 버전을 환경변수에 추가하면 신규 저장은 최신 버전, 기존 행은 기존 `key_version`으로 복호화한다. 일괄 재암호화 후 구 키를 제거한다.
- **AI 기억**: `backend/memory/profile.py`는 LangGraph Store 헬퍼이고 `GET/PATCH/DELETE /me/memory`(`backend/api/routes.py:359-378`)로 FastAPI에 연결돼 있다(`memory.md`). 저장 칸은 소속·직급·담당 서비스 세 개다. 이 값은 `store.put`으로 LangGraph `store` 표에 JSON 그대로 들어가(`backend/memory/profile.py:43`) 위 `ProfileCipher` 암호화를 거치지 않는다. 암호화 대상에 넣을지는 팀장 판단 사항이다.

## AC

**AC-01 · 키 없는 시작 거부**

- GIVEN: `PROFILE_ENC_KEYS`가 없음
- WHEN: 프로필 암호기를 생성함
- THEN: 임시 키를 만들지 않고 `ProfileCryptoError`를 발생시킨다.

**AC-02 · 암호문 저장**

- GIVEN: 유효한 32바이트 키와 프로필 값
- WHEN: 프로필을 저장함
- THEN: 저장 바이트에 이름·전화번호·주소 평문이 포함되지 않는다.

**AC-03 · 관리자 차단**

- GIVEN: 관리자 또는 최고 관리자 인증
- WHEN: 다른 사용자의 프로필을 요청함
- THEN: 프로필 원문·마스킹 값 모두 반환하지 않는다.

**AC-04 · 로컬 데모 재시작 뒤 같은 키 (K-23)**

- GIVEN: 로컬 데모 모드, `PROFILE_ENC_KEYS` 없음, 내 정보를 한 번 저장함
- WHEN: 서버를 다시 띄워 프로필 암호기를 새로 만듦
- THEN: 같은 키 파일을 읽어 저장된 값을 푼다. 로컬 데모가 아니면 키 파일을 만들지 않고 `ProfileCryptoError`를 낸다(`tests/test_profile_crypto.py`).

**AC-05 · 풀 수 없는 줄은 다시 입력 (K-23)**

- GIVEN: 로컬 데모가 만든 키로 도는 서버, 다른 키로 잠근 줄이 남아 있음
- WHEN: `GET /me/profile`
- THEN: 404 `profile_reentry_required`이고 값은 담지 않는다. `PUT /me/profile` 뒤에는 200으로 읽힌다. `PROFILE_ENC_KEYS`로 받은 키면 503이다(`tests/test_profile_api.py`).
