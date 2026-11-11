# Spec — 사용자별 장기 기억 (P-01, G4)

상태: `backend/memory/`, `GET/PATCH/DELETE /me/memory`, 질문 그래프의 기억 읽기 구현 완료. 사용자 분리는 API 수준 시험(`tests/test_api_isolation.py`)으로 확인했다. 운영 DB에는 `store` 표가 있고(2026-11-10 조회 0행 / 56 KB, `docs/db/TABLE_SPEC.md:59`) 배포 환경에서 평가용 계정 두 개로 한 실측(2026-11-09: 일반 계정에 자기 대화만 보이고 남의 thread는 404, 기억 저장 시 `store`에 소속·직급이 생기고 초기화하면 지워짐)이 `EVAL_REPORT.md:509`·`docs/GATES.md` G4에 있다.

## Why

- **페르소나**: 같은 서비스에 로그인하는 서로 다른 소속의 사용자 두 명 이상, 사용자 분리를 확인하는 평가자
- **상황**: 사용자는 질문할 때마다 자신의 소속과 직급을 다시 적고 싶지 않다. 반대로 한 사용자의 소속·직급이 다른 사용자의 질문 처리에 들어가면 안 된다.
- **문제**:
  1. 대화 안의 값(State)과 다음 대화에도 쓸 값(Store)을 나누지 않으면 질문, 검색 결과, 답이 장기 기억으로 남는다.
  2. 기억의 주인을 요청 본문의 사용자 id로 정하면 다른 사용자의 기억을 읽거나 고칠 수 있다.
  3. 틀린 기억을 사용자가 고치거나 지울 길이 없으면 잘못된 소속이 검색 범위와 재작성에 계속 쓰인다.
- **측정 지표**: 두 사용자의 기억이 섞이지 않는지(`tests/test_api_isolation.py`의 기억 시험 6건), 허용하지 않은 칸이 저장되지 않는지

## Goal

- 소속(`affiliation`)·직급(`rank`)·담당 서비스(`service`) 세 칸만 LangGraph Store에 사용자별로 저장한다.
- 로그인한 사용자가 자신의 기억을 보고(`GET`), 고치고(`PATCH`), 지울(`DELETE`) 수 있다.
- 질문 그래프가 질문마다 첫 노드에서 로그인한 사용자의 기억만 읽어 State에 둔다.
- **Out of Scope**: 대화 내용, 질문, 검색 결과, 답의 장기 저장(State와 체크포인트가 맡는다), 그래프가 대화 중에 기억을 스스로 쓰는 것, 소속·직급·담당 서비스 밖의 칸, 기억의 유효 기간·자동 삭제

## What

### Happy Path

1. 사용자가 로그인한 뒤 `PATCH /me/memory`에 `{"affiliation": ..., "rank": ..., "service": ...}` 중 고칠 칸을 보낸다(CSRF 헤더 필요).
2. 서버는 로그인 쿠키에서 얻은 사용자 id로 Store의 `(user_id, "profile")` namespace, 키 `me`에 값을 쓴다. 보낸 칸만 갱신하고 나머지는 그대로 둔다.
3. 사용자가 `/chat`으로 질문하면 서버는 같은 사용자 id를 그래프 입력의 `user_id`로 넘긴다.
4. 그래프의 첫 노드 `load_memory`가 `get_profile(store, user_id)`로 그 사용자의 프로필을 읽어 State의 `profile`에 둔다.
5. `profile`은 질문 종류 분류 프롬프트와 재작성 프롬프트에 "소속·직급: ..." 줄에 프로필 dict 통째(담당 서비스 포함)로 들어가고, 입력에 절(`org`)이 없고 재작성도 절을 정하지 않았을 때 검색 범위(`search_org`)로 `affiliation` 값이 쓰인다.
6. 사용자가 `GET /me/memory`로 저장된 값을, `DELETE /me/memory`로 지운 결과를 확인한다.

### Edge Cases

| 상황 | 처리 |
|---|---|
| 로그인하지 않고 `/me/memory` 호출 | 401 `unauthorized` |
| `PATCH`, `DELETE`에 CSRF 헤더나 쿠키가 없음 | 403 `csrf_failed`. `GET`은 CSRF 검사가 없다 |
| `PATCH` 본문이 비었거나 고칠 칸이 없음 | 422 `validation_error` |
| `PATCH` 본문에 허용하지 않은 칸(`team`, `question`, `user_id` 등) | 422 `validation_error`. 저장하지 않는다 |
| 칸 값이 100자를 넘음 | 422 `validation_error` |
| 요청에 다른 사용자의 id를 적음(`?user_id=` 질의, 본문 `user_id`) | 질의 값은 읽지 않고 로그인한 사용자의 기억을 돌려준다. 본문의 `user_id`는 422 |
| 칸을 빈 문자열로 고침 | 저장은 되지만 이후 읽을 때(`GET`, 질문 처리) 값이 비어 있는 칸은 빼므로 그 칸은 없는 것으로 나온다. `PATCH` 응답에는 빈 문자열이 그대로 보인다 |
| 기억이 한 번도 저장되지 않은 사용자 | `profile`은 `{}`이고 그래프는 기억 없이 동작한다("소속·직급: 없음") |
| 그래프 입력의 `user_id`가 비어 있음 | `profile`은 `{}`이다. `profile_namespace()`는 빈 `user_id`에 `ValueError`를 낸다 |
| Store가 앱에 연결되지 않음(시작 때 DB를 열지 못한 경우 등) | 503 `not_configured` |

## How

### 저장 위치와 namespace

- 구현: `backend/memory/profile.py`. Store는 LangGraph `BaseStore`이며 `backend/graph/checkpoint.py`의 `open_persistence()`가 체크포인터와 함께 연다. `DATABASE_URL`이 있고 `CHECKPOINTER`가 `memory`가 아니면 `PostgresStore`(표 `store`, 앱 시작 때 `setup()`이 만들고 RLS를 켠다), 그렇지 않으면 `InMemoryStore`다. `build_graph(store=None)`도 `InMemoryStore`를 쓴다.
- namespace는 `(user_id, "profile")`이고 첫 요소가 사용자 id다. 키는 `me` 하나이며 값은 `{"affiliation": str, "rank": str, "service": str}` 형태(없는 칸은 빠짐)의 dict다. 사용자마다 namespace가 달라 다른 사용자의 값을 읽을 수 없다.
- 허용 칸은 `ALLOWED_FIELDS = ("affiliation", "rank", "service")`이다. `get_profile()`은 이 밖의 칸과 빈 값을 걸러서 돌려준다.
- State와 Store의 경계(SDD 5장): 질문, 검색 결과, 재검색 횟수, 초안 답은 State(체크포인트)에 두고, 다음 대화에도 쓸 소속·직급만 Store에 둔다. 기억 값과 질문 내용은 로그에 쓰지 않는다(`backend/api/routes.py`).

### 읽기

- 질문 그래프 `backend/graph/build.py`의 `load_memory` 노드가 START 다음 첫 노드다. 질문마다 Store를 다시 읽으므로 `PATCH`로 고친 값은 다음 질문부터 쓰인다.
- 사용처: 질문 종류 분류(`classify_user`), 질의 재작성(`rewrite_user`), 검색 범위(`scope_org`). 검색 범위의 우선순위는 입력의 `org`, 재작성이 뽑은 절, 프로필의 `affiliation` 순이다. 멀티 그래프(`backend/graph/multi.py`)의 서브에이전트도 State의 `profile`을 읽는 칸 목록에 갖고 있다.
- 그래프는 `get_profile`만 부르고 쓰지 않는다. 기억을 쓰는 곳은 아래 API뿐이다.

### 쓰기와 삭제 API

`backend/api/routes.py`, 오류 본문은 SDD 4-4절의 한 모양(`{"error": {"code", "message", "request_id"}}`)이다.

| 메서드 | 경로 | 인증 | 동작 |
|---|---|---|---|
| GET | `/me/memory` | 로그인 | `{user_id, profile, allowed_fields}` |
| PATCH | `/me/memory` | 로그인, CSRF | 본문 `{affiliation?, rank?, service?}`(각 100자 이하, 그 밖의 칸은 422). 보낸 칸만 갱신하고 `{user_id, profile}`을 돌려준다 |
| DELETE | `/me/memory` | 로그인, CSRF | `delete_profile()`로 키 `me`를 지우고 `{user_id, profile: {}}`을 돌려준다 |

- 사용자 id는 로그인 쿠키에서만 얻는다. `?user_id=`는 읽지 않고, 본문의 `user_id`는 `extra="forbid"`로 422다.
- 앱 시작(lifespan)에서 `app.state.store`에 Store를 둔다(`backend/main.py`, `open_decision_runtime()`). `/me/memory`를 포함한 `/chat`, `/threads` 라우터는 `DATABASE_URL`이 있을 때만 붙는다.

### 시험

`tests/test_api_isolation.py`는 사용자별 `TestClient`(쿠키 분리), 가짜 모델, 메모리 체크포인터, 메모리 Store로 돈다.

| 시험 | 확인하는 것 |
|---|---|
| `test_long_term_memory_is_per_user` | 두 사용자가 각자 고친 값이 서로의 `GET`에 보이지 않는다 |
| `test_memory_patch_is_partial_and_delete_only_clears_own` | `PATCH`는 보낸 칸만 갱신하고, `DELETE`는 자기 기억만 지운다 |
| `test_memory_accepts_only_allowed_fields` | 빈 본문, 허용하지 않은 칸, 100자 초과는 422이고 저장되지 않는다 |
| `test_request_cannot_choose_another_user_id` | 질의·본문의 다른 사용자 id로 남의 기억을 읽거나 고치지 못한다 |
| `test_memory_changes_need_login_and_csrf` | 로그인 없음은 401, CSRF 없는 `PATCH`·`DELETE`는 403, `GET`은 CSRF 없이 200 |
| `test_memory_is_read_by_the_next_question` | `PATCH`한 값이 그 사용자의 다음 질문 State `profile`에 들어가고 다른 사용자의 State에는 없다 |

그래프 쪽 시험은 `tests/test_question_graph.py`의 `test_memory_profile_used_for_org`, `test_graph_does_not_leak_profile_across_users`, `test_put_profile_ignores_unknown_fields_and_partial_update`다.

## 의존 파일·환경변수

| 구분 | 이름 | 쓰는 곳 |
|---|---|---|
| 파일 | `backend/memory/profile.py`, `backend/memory/__init__.py` | 기억 읽기·쓰기·삭제와 namespace(`profile_namespace`) |
| 파일 | `backend/api/routes.py`의 `/me/memory` 세 경로 | 로그인·CSRF 확인 뒤 위 함수를 부른다(`routes.py:358` 부근) |
| 파일 | `backend/graph/checkpoint.py` | 기억을 담는 Store(메모리 `InMemoryStore`, Postgres `PostgresStore`)를 앱 시작에서 연다 |
| 환경변수 | `DATABASE_URL` | 있으면 Postgres Store(`.env.example`) |
| 환경변수 | `CHECKPOINTER` | `memory` 또는 `postgres`. 비우면 `DATABASE_URL`이 있을 때 postgres, 없으면 memory(`checkpoint.py`의 `checkpointer_kind`). memory면 서버를 다시 띄울 때 기억도 사라진다 |

## 남은 점

- `backend/memory/__init__.py`의 `namespace(user_id)`는 `("memories", user_id)`를 돌려주지만 호출하는 곳이 없다. 실제 namespace는 `profile_namespace()`의 `(user_id, "profile")`이며 첫 요소가 사용자 id인 것도 이쪽뿐이다. 이 함수를 지울지 다른 용도로 쓸지는 정하지 않았다.
- 기억 설정 화면(`/onboarding`)의 팀·역할·담당 서비스는 각각 `affiliation`·`rank`·`service`에 저장한다. 내 정보 화면(`/myinfo`, 첫 등록 포함)은 `rank`·`service`만 보내고 소속 팀은 내 정보 `dept`에만 저장한다(2026-11-11). 화면의 팀 이름은 한글(보안, 재무 등)이고 코퍼스 절 이름은 영문(`security`, `finance` 등 11종)이라, 한글 팀 이름이 `affiliation`에 들어가면 검색 범위가 없는 절로 좁혀져 결과가 0건이 된다(numpy 저장소와 가짜 LLM 그래프로 확인, 실제 DB·배포는 미확인). 기억 설정 화면은 지금도 한글 팀 이름을 보내므로 팀 이름을 절 이름으로 바꾸는 표를 둘지는 정하지 않았다. SDD 4-3장과 `backend/memory/memory.md`의 서술이 이 이름과 맞는지는 다시 대조하지 않았다.
- `affiliation` 값은 검색 범위(절 이름)로도 쓰이는데, 기억을 저장할 때 허용 값 목록으로 검증하는 코드는 없다(길이 100자 제한뿐이다). 사용자가 적은 문자열은 그대로 LLM 프롬프트의 "소속·직급" 줄에도 들어가며 별도 정화 처리는 코드에 없다. 영향은 미확인이다.
- `tests/test_api_isolation.py`의 사용자 분리 시험은 메모리 Store 기준이고, `PostgresStore`·배포 환경(평가용 계정 A·B)은 2026-11-09 실측으로 확인했다(`EVAL_REPORT.md:509`). 실측 뒤 조회 시점의 `store`는 0행이다(소속·직급을 초기화해 지운 뒤).
- 운영 Supabase의 `store` 표는 2026-11-09 조회 때는 없었고 앱 첫 기동 때 `backend/graph/checkpoint.py:107-108`의 `setup()`이 만들었다. 2026-11-10 조회에는 있다(0행 / 56 KB, `docs/db/TABLE_SPEC.md:59`).
- 틀린 기억을 고치는 절차는 위 API로 구현했지만, 기억해도 되는 기준과 보존 기간은 SDD 5장 서술 외에 별도 규칙이 없다.

## AC (Given-When-Then)

- **AC-01 사용자별 저장**: GIVEN 로그인한 사용자 A와 B, WHEN 각자 `PATCH /me/memory`로 다른 소속을 저장, THEN 각자의 `GET /me/memory`는 자기 값만 돌려준다.
- **AC-02 부분 갱신**: GIVEN A의 소속이 저장돼 있음, WHEN A가 `rank`만 `PATCH`, THEN 소속은 그대로이고 직급이 더해진 `profile`을 돌려준다.
- **AC-03 자기 기억만 삭제**: GIVEN A와 B의 기억이 저장돼 있음, WHEN A가 `DELETE /me/memory`, THEN A의 `profile`은 `{}`이고 B의 기억은 그대로다.
- **AC-04 허용 칸**: GIVEN 로그인한 사용자, WHEN 빈 본문, 허용하지 않은 칸, 100자를 넘는 값을 `PATCH`, THEN 422 `validation_error`이고 아무것도 저장되지 않는다.
- **AC-05 사용자 id 고정**: GIVEN B의 기억이 저장돼 있음, WHEN A가 `?user_id=<B>`로 `GET`하거나 본문에 `user_id`를 넣어 `PATCH`, THEN A는 자기 기억만 보고 B의 기억은 바뀌지 않는다.
- **AC-06 인증과 CSRF**: GIVEN 로그인하지 않았거나 CSRF가 없음, WHEN `/me/memory`를 호출, THEN `GET`은 로그인 없으면 401, `PATCH`·`DELETE`는 CSRF가 없으면 403이다.
- **AC-07 다음 질문에 반영**: GIVEN A가 소속·직급을 저장함, WHEN A와 B가 같은 질문을 같은 `thread_id` 이름으로 보냄, THEN A의 State `profile`에는 저장한 값이, B의 State `profile`에는 `{}`가 들어 있다.
