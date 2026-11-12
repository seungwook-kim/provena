# PR (미정) — OpenAPI에서 Java·Python SDK 생성 (C-15, P-07)
- 작업자: 박진형 (jinyeong-731) / 머지: 아직 안 함 / 기준: origin/main `601183c7` 위 브랜치 `gap3-sdk`
- 배포 서비스, 운영 DB, 실제 LLM 호출은 하지 않았다. 확인은 전부 로컬이다.

## 무엇을
| 항목 | 내용 |
|---|---|
| 도구 | openapi-generator-cli **7.26.0** (Maven Central `org.openapitools:openapi-generator-cli`, 2026-10-06 공개, 2주 이상 지난 최신판. 7.27.0은 11/02 공개라 제외) |
| jar 검증 | SHA-256 `1760050094997b9cc790cc1350be095f15da8c08a996b184d3eadc4ccda5e35e` (SHA-1은 Maven Central과 일치). jar는 저장소에 넣지 않는다 |
| 위치 | `mock_erp/sdk/` (`mock_erp/` 안: TEAM_GUIDE 5장 폴더 주인표에 `mock_erp/`는 업무시스템 목업, SDD 디렉토리 트리도 `mock_erp/` 아래. 새 최상위 폴더를 만들지 않음) |
| 파일 | `generate.sh`(고정 버전·SHA 확인·고정 옵션), `sdk.md`(폴더 문서), `python/`(패키지 `provena_sdk`), `java/`(패키지 `com.provena.sdk`, `native` 라이브러리, `pom.xml`) |
| 문서 | PRD P-03, SDD 5장·11장·디렉토리 트리, SPEC P-03, `specs/erp-integration.md`, `mock_erp.md`, `docs/docs.md`의 SDK 문구를 "생성함, 도구는 openapi-generator 7.26.0"으로 고침 |
| 생성 크기 | Python 60파일 776,617바이트, Java 58파일 697,711바이트, 합계 118파일 1,474,328바이트(약 1.5MB). gradle 래퍼(바이너리 `gradle-wrapper.jar` 포함)와 미사용 gradle·sbt 파일은 `generate.sh`가 지워 저장소에 바이너리가 없다(`git diff --name-only origin/main..HEAD`에서 .jar·.class 0건). 기준(2MB)보다 작아 생성 코드를 커밋한다. 시험·모델 문서 파일은 만들지 않게 해서 줄였다 |
| 재생성 | `bash mock_erp/sdk/generate.sh` |

## 왜 (근거)
- 조장 목록 C-15 "OpenAPI에서 Java·Python SDK 생성"(근거 칸 PRD:176, SDD:533)과 P-07 "SDK 생성 도구, 미정"(SDD:533, 기한 11/16). [문서] `놓친 것 목록 (2026-11-11) (1).md`의 `| C-15 |`, `| P-07 |` 행.
- PRD P-03: "자동 생성 SDK(Java·Python)"를 제공한다고 적혀 있다. [문서] `docs/PRD.md:176`.
- SDD: SDK는 "OpenAPI 명세에서 자동 생성한 Java·Python SDK (생성 도구는 11장)"로 적혀 있고(`docs/SDD.md:56`), 11장에 "SDK 생성 도구 … 선택 기록을 저장소에서 찾지 못했다"(`docs/SDD.md:661`)와 "후보를 D0에 정한다"(`docs/SDD.md:702`)가 있었다. 조장 목록의 "SDD:533"은 옛 줄 번호이고 현재 판에서는 위 세 줄이다. 이 두 줄(661·702)을 도구 확정으로 고쳤다.
- 도구 선택은 진형이 정했다(11/11): Java·Python을 한 도구로 만들 수 있어서 openapi-generator.

## 확인한 것(로컬)
| 확인 | 결과 | 근거 종류 |
|---|---|---|
| 생성 | Python·Java 모두 오류 없이 생성 (명세 `docs/api/openapi.json` OpenAPI 3.1.0, 48경로) | 실측 |
| Python 동작 수 | `DefaultApi`의 공개 동작 메서드 **54개** = 명세의 54 operations | 실측 |
| Python 실제 호출 | 이 저장소 앱(`backend.main:app`)을 키·DB 없이 `127.0.0.1:8765`에 uvicorn으로 띄우고 `DefaultApi.health_health_get()` 호출 → `{'status': 'ok'}`, 서버 로그 `GET /health status=200` | 실측 |
| Java 컴파일 | JDK 26 `javac`, Jackson 2.17.2(core·annotations·databind·jsr310)와 jakarta.annotation-api 2.1.1을 Maven Central에서 내려받아 클래스패스에 두고 컴파일: 소스 47개 → 클래스 108개, 오류 0 | 실측 |
| 커밋 규칙 | 커밋 메시지·본문의 AI 도구 표기 0건 | 실측 |

## 한계
- Java는 컴파일만 확인했다. 실제 HTTP 호출은 하지 않았다. 컴파일에 쓴 jar는 저장소 밖에 두었고, Maven/Gradle이 없어 `pom.xml` 빌드는 해 보지 않았다(`pom.xml`의 Jackson 버전은 2.21.x, 컴파일은 2.17.2로 함).
- Java 생성기 7.26.0은 `HTTPValidationError.error.details`의 `anyOf`(배열 | 객체)에서 컴파일 안 되는 코드(`List<ValidationError>.class`)를 낸다. 그래서 `generate.sh`가 Java 생성에만 그 한 칸을 자유 형식 객체로 바꾼 임시 명세를 쓴다. 저장소의 명세는 그대로이고, 그 한 칸만 Java SDK에서 타입이 느슨하다. 명세 쪽에서 `details`를 한 가지 모양으로 정하면 이 보정은 필요 없다.
- 모든 API가 `default` 태그라 클래스가 `DefaultApi` 하나고 메서드 이름이 `health_health_get`처럼 길다. 고치려면 `backend/`의 라우트에 `tags`·`operation_id`를 줘야 해서(김승욱 폴더) 이번에는 건드리지 않았다.
- 로그인·CSRF 쿠키 흐름과 `/chat` SSE는 SDK가 자동으로 처리하지 않는다. `mock_erp/python_example/provena_client.py`가 보여 준다. Java 목업은 여전히 없다.
- `mock_erp/`와 `docs/`는 김승욱·팀장 폴더다. 이 변경은 PR로 올려 주인 확인을 받는다. 명세가 바뀌면 SDK도 `generate.sh`로 다시 만들어야 한다(자동 검사는 없다).
