#!/usr/bin/env bash
# docs/api/openapi.json 에서 Python·Java SDK 를 다시 만든다. 생성 결과는 손으로 고치지 않는다.
# 사용: OPENAPI_GENERATOR_JAR=/경로/openapi-generator-cli-7.26.0.jar bash mock_erp/sdk/generate.sh
# jar 가 없으면 Maven Central 에서 ${TMPDIR:-/tmp}/openapi-generator/ 로 받는다(저장소 밖).
set -euo pipefail

VERSION="7.26.0"
SHA256="1760050094997b9cc790cc1350be095f15da8c08a996b184d3eadc4ccda5e35e"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SPEC="$ROOT/docs/api/openapi.json"
JAR="${OPENAPI_GENERATOR_JAR:-${TMPDIR:-/tmp}/openapi-generator/openapi-generator-cli-$VERSION.jar}"

if [ ! -f "$JAR" ]; then
  mkdir -p "$(dirname "$JAR")"
  curl -fsSL -o "$JAR" "https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/$VERSION/openapi-generator-cli-$VERSION.jar"
fi
echo "$SHA256  $JAR" | sha256sum -c -

# 시험·문서 파일은 만들지 않아 크기를 줄인다(모델·API 클래스만).
COMMON=(--input-spec "$SPEC" --global-property "apiTests=false,modelTests=false,apiDocs=false,modelDocs=false")

# Java 생성기 7.26.0 은 anyOf(배열 | 객체)를 만나면 `List<ValidationError>.class` 같은
# 컴파일 안 되는 코드를 낸다(HTTPValidationError.error.details 한 곳). 그래서 Java 만
# 그 한 칸을 자유 형식 객체로 바꾼 임시 명세를 쓴다. docs/api/openapi.json 은 건드리지 않는다.
JAVA_SPEC="$(mktemp)"
trap 'rm -f "$JAVA_SPEC"' EXIT
"${PYTHON:-python}" -X utf8 - "$SPEC" "$JAVA_SPEC" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
err = d["components"]["schemas"]["HTTPValidationError"]["properties"]["error"]["properties"]
err["details"] = {"type": "object", "additionalProperties": True,
                  "description": "검증 오류 목록 또는 칸별 검사 결과(명세는 둘 중 하나, Java SDK 는 자유 형식)"}
json.dump(d, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
PY

rm -rf "$HERE/python" "$HERE/java"
java -jar "$JAR" generate -g python "${COMMON[@]}" -o "$HERE/python" \
  --additional-properties packageName=provena_sdk,projectName=provena-sdk,packageVersion=0.1.0
java -jar "$JAR" generate -g java --library native --input-spec "$JAVA_SPEC" --global-property "apiTests=false,modelTests=false,apiDocs=false,modelDocs=false" -o "$HERE/java" \
  --additional-properties invokerPackage=com.provena.sdk,apiPackage=com.provena.sdk.api,modelPackage=com.provena.sdk.model,artifactId=provena-sdk,artifactVersion=0.1.0,openApiNullable=false,useJakartaEe=true

# 빌드는 pom.xml 로 한다. 바이너리(gradle-wrapper.jar), 쓰지 않는 gradle·sbt 파일, 생성기 CI 설정·안드로이드 매니페스트는 저장소에 넣지 않으므로 지운다.
rm -rf "$HERE/java/gradle" "$HERE/java/gradlew" "$HERE/java/gradlew.bat" "$HERE/java/build.gradle" \
  "$HERE/java/settings.gradle" "$HERE/java/gradle.properties" "$HERE/java/build.sbt" \n  "$HERE/java/.github" "$HERE/python/.github" "$HERE/python/.gitlab-ci.yml" \n  "$HERE/java/.travis.yml" "$HERE/python/.travis.yml" "$HERE/java/src/main/AndroidManifest.xml"
