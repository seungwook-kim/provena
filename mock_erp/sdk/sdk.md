# sdk/ : 자동 생성 SDK

## 이 폴더가 하는 일

`docs/api/openapi.json`에서 openapi-generator로 만든 Python·Java 클라이언트 SDK다. 업무시스템(`mock_erp/`)이 손으로 `requests`를 쓰지 않고 이 SDK로 플랫폼 REST API를 부르게 하려는 것이다(PRD P-03, 놓친 것 C-15·P-07).

- 주인: 김승욱 (`mock_erp/` 폴더 주인). 이번 작업은 박진형이 했다
- 입력: `docs/api/openapi.json` (OpenAPI 3.1.0, 48경로, 54동작)
- 출력: `python/`(패키지 `provena_sdk`), `java/`(패키지 `com.provena.sdk`, `pom.xml`)

## 생성물이다 — 손으로 고치지 않는다

`python/`과 `java/`는 전부 생성기 출력이다. 고치려면 명세(`docs/api/openapi.json`)나 `generate.sh`를 고치고 다시 만든다. 명세는 `python docs/api/export_openapi.py`로 다시 내보낸다.

| 항목 | 값 |
|---|---|
| 도구 | openapi-generator-cli 7.26.0 (Maven Central `org.openapitools:openapi-generator-cli`) |
| jar SHA-256 | `1760050094997b9cc790cc1350be095f15da8c08a996b184d3eadc4ccda5e35e` (`generate.sh`가 받은 뒤 확인) |
| Python | 생성기 `python`, 패키지 `provena_sdk` 0.1.0, urllib3 + pydantic v2, Python 3.10 이상 |
| Java | 생성기 `java`, 라이브러리 `native`(JDK 11+ `java.net.http`), Jackson 사용, 패키지 `com.provena.sdk` |
| 만들지 않는 것 | 생성기의 시험·API/모델 문서 파일(`apiTests`, `modelTests`, `apiDocs`, `modelDocs` = false)로 크기를 줄임 |
| 지우는 것 | 빌드는 `pom.xml`로 하므로 `generate.sh`가 생성 뒤 `java/gradle/`(wrapper jar 포함), `gradlew`, `gradlew.bat`, `build.gradle`, `gradle.properties`, `build.sbt`, 생성기가 내는 CI 설정(`.github/`, `.gitlab-ci.yml`, `.travis.yml`)과 `src/main/AndroidManifest.xml`을 지운다(저장소에 바이너리를 넣지 않음) |

## 다시 만드는 법

```
bash mock_erp/sdk/generate.sh
```

jar는 `${TMPDIR:-/tmp}/openapi-generator/`(저장소 밖)로 내려받는다. 이미 있으면 `OPENAPI_GENERATOR_JAR=<경로>`로 지정한다. JDK 11 이상과 Python(명세 보정용, `PYTHON` 환경변수로 지정 가능)이 필요하다.

## 쓰는 법

Python SDK는 생성된 `requirements.txt`의 패키지(urllib3, python-dateutil, pydantic, typing-extensions)가 있어야 import 된다. 저장소 루트에서 `pip install -e mock_erp/sdk/python`으로 설치하면 의존성까지 같이 깔린다. Java SDK는 `mock_erp/sdk/java`의 `pom.xml`로 `mvn package`(JDK 11 이상) 빌드한다. 단 만들 때 Maven이 없어 `pom.xml` 빌드는 해 보지 않았고, Jackson·jakarta.annotation jar를 클래스패스에 두고 `javac` 컴파일만 확인했다.

## API가 바뀌면

라우트를 추가·삭제·이름 변경하면 `python docs/api/export_openapi.py`로 명세를 다시 내보낸 뒤 `bash mock_erp/sdk/generate.sh`를 다시 실행한다. `tests/test_sdk_matches_openapi.py`가 명세의 동작 목록과 Python·Java SDK 메서드 목록을 비교해, 다시 만들지 않으면 실패한다.

## 알려진 사정

- Java 생성기 7.26.0은 `HTTPValidationError.error.details`의 `anyOf`(배열 | 객체)에서 컴파일되지 않는 코드(`List<ValidationError>.class`)를 낸다. 그래서 `generate.sh`는 Java 생성에만 그 한 칸을 자유 형식 객체로 바꾼 임시 명세를 쓴다(저장소의 명세는 그대로). Python SDK는 원래 명세로 만든다.
- 모든 API가 `default` 태그라 클래스는 `DefaultApi` 하나이고 메서드 이름은 `경로_메서드` 꼴이다(예: `health_health_get`). 이름을 바꾸려면 FastAPI 라우트에 `tags`나 `operation_id`를 주고 명세를 다시 내보낸다(`backend/` 변경이라 이 폴더 밖 일).
- 로그인·CSRF 쿠키 흐름은 SDK가 자동으로 해 주지 않는다. 쿠키 처리와 SSE(`/chat`)는 `mock_erp/python_example/provena_client.py`가 보여 준다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-12 | 박진형 (jinyeong-731) | 신규. openapi-generator 7.26.0으로 Python·Java SDK 생성, `generate.sh`와 이 문서 추가(C-15·P-07) | #135 |
