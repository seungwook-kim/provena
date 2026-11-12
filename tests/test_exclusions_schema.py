"""evals/exclusions.json 형식 시험(L-04). 항목이 0개여도 통과하고, 나쁜 입력은 사유를 돌려준다."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXCLUSIONS = ROOT / "evals" / "exclusions.json"
DATASETS = ("dataset_v1.jsonl", "dataset_v2.jsonl")


def dataset_ids() -> set[str]:
    ids: set[str] = set()
    for name in DATASETS:
        for line in (ROOT / "evals" / name).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                ids.add(str(json.loads(line)["id"]))
    return ids


def check_exclusions(path: Path, known_ids: set[str]) -> list[str]:
    """문제 목록을 돌려준다. 빈 목록이면 형식이 맞는 것."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"JSON을 읽지 못함: {e}"]
    if not isinstance(data, dict) or "as_of" not in data or "excluded" not in data:
        return ["as_of, excluded 키가 필요함"]
    if not isinstance(data["excluded"], list):
        return ["excluded는 목록이어야 함"]
    problems: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(data["excluded"]):
        if not isinstance(item, dict) or "id" not in item:
            problems.append(f"{i}번 항목에 id 없음")
            continue
        key = str(item["id"])
        if key not in known_ids:
            problems.append(f"{i}번 id {key}가 평가셋 v1·v2에 없음")
        if key in seen:
            problems.append(f"id {key} 중복")
        seen.add(key)
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            problems.append(f"{i}번 항목 reason이 비었거나 문자열이 아님")
    return problems


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "exclusions.json"
    p.write_text(text, encoding="utf-8")
    return p


def test_real_exclusions_file_is_valid():
    assert check_exclusions(EXCLUSIONS, dataset_ids()) == []


def test_zero_items_pass(tmp_path):
    assert check_exclusions(write(tmp_path, '{"as_of": null, "excluded": []}'), dataset_ids()) == []


def test_valid_item_passes(tmp_path):
    p = write(tmp_path, '{"as_of": "2026-11-08", "excluded": [{"id": 1, "reason": "정답 청크가 바뀜"}]}')
    assert check_exclusions(p, dataset_ids()) == []


@pytest.mark.parametrize("text, expect", [
    ("{not json", "JSON"),
    ('{"excluded": []}', "as_of"),
    ('{"as_of": null}', "excluded"),
    ('{"as_of": null, "excluded": [{"id": 999999, "reason": "x"}]}', "평가셋 v1·v2에 없음"),
    ('{"as_of": null, "excluded": [{"id": 1, "reason": ""}]}', "reason"),
    ('{"as_of": null, "excluded": [{"id": 1, "reason": "  "}]}', "reason"),
    ('{"as_of": null, "excluded": [{"id": 1}]}', "reason"),
    ('{"as_of": null, "excluded": [{"reason": "x"}]}', "id 없음"),
    ('{"as_of": null, "excluded": [{"id": 1, "reason": "a"}, {"id": 1, "reason": "b"}]}', "중복"),
])
def test_bad_input_is_caught(tmp_path, text, expect):
    problems = check_exclusions(write(tmp_path, text), dataset_ids())
    assert problems and any(expect in p for p in problems), problems
