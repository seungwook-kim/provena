# db/ : DB 초기화와 시드

## 이 폴더가 하는 일

pgvector 확장 생성(`01_init.sql`), 데모 계정 2개 시드. SQL 파일 번호대는 파트마다 100번대씩 나눈다.

- 주인: 김승욱
- 입력: 없음
- 출력: 스키마, 시드 데이터

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | `201_search.sql`(검색 파트 200번대): `docs`·`versions`(판 유효 구간 `valid_from`·`valid_to`, `version_date_before`)·`chunks`(열쇠 (chunk_id, version_id), 줄 범위, 차원 없는 `vector`)·`index_meta`(색인 장부)·`query_translations`(번역 장부). 모두 `IF NOT EXISTS`라 compose 첫 기동(initdb)과 `loader`가 두 번 돌려도 같다 | 이 PR |
| 2026-10-30 | 김승욱 (Claude Code) | `101_auth_users.sql`(users 테이블, SQL 번호대 100번대는 김승욱 파트로 잡음) 추가. 데모 계정은 SQL이 아니라 앱 시작 때 환경변수로 시드한다 | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
