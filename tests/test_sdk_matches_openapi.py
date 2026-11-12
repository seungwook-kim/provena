"""생성 SDK(mock_erp/sdk)가 docs/api/openapi.json 과 같은 동작 목록을 갖는지 본다.

API가 바뀌었는데 generate.sh 를 다시 돌리지 않으면 여기서 실패한다.
SDK를 import 하지 않고(생성 SDK 의존성 없이) 생성된 소스의 메서드 이름만 읽는다.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/api/openapi.json"
PY_API = ROOT / "mock_erp/sdk/python/provena_sdk/api/default_api.py"
JAVA_API = ROOT / "mock_erp/sdk/java/src/main/java/com/provena/sdk/api/DefaultApi.java"
METHODS = {"get", "post", "put", "patch", "delete"}


def spec_operations():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    return {op["operationId"] for item in spec["paths"].values() for m, op in item.items() if m in METHODS}


def python_methods():
    src = PY_API.read_text(encoding="utf-8")
    names = set(re.findall(r"^    def ([a-z0-9_]+)\(", src, re.M))
    return {n for n in names if not n.startswith("_") and not n.endswith(("_with_http_info", "_without_preload_content"))}


def java_methods():
    src = JAVA_API.read_text(encoding="utf-8")
    names = set(re.findall(r"^  public [^=(]*?\b(\w+)\(", src, re.M))
    # 생성자(DefaultApi)와 생성기 공통 도우미(downloadFileFromResponse)는 동작이 아니다
    return {n for n in names if not n.endswith("WithHttpInfo")} - {"DefaultApi", "downloadFileFromResponse"}


def _python_name(op):
    # 생성기는 밑줄 여러 개를 하나로 줄인다(예: recalls__notice_id__get -> recalls_notice_id_get)
    return re.sub(r"_+", "_", op).strip("_")


def _java_name(op):
    parts = [p for p in op.split("_") if p]
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def test_spec_has_operations():
    assert len(spec_operations()) > 0


def test_python_sdk_matches_spec():
    expected = {_python_name(op) for op in spec_operations()}
    got = python_methods()
    assert expected - got == set(), f"SDK에 없는 동작(generate.sh 다시 실행): {sorted(expected - got)}"
    assert got - expected == set(), f"명세에 없는 SDK 메서드(generate.sh 다시 실행): {sorted(got - expected)}"


def test_java_sdk_matches_spec():
    expected = {_java_name(op).lower() for op in spec_operations()}
    got = {n.lower() for n in java_methods()}
    assert expected - got == set(), f"SDK에 없는 동작(generate.sh 다시 실행): {sorted(expected - got)}"
    assert got - expected == set(), f"명세에 없는 SDK 메서드(generate.sh 다시 실행): {sorted(got - expected)}"
