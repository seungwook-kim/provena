"""새 검증 문항 20건(evals/dataset_holdout_v2.jsonl, id 501~520) 형식 확인.

박진형 501~510, 강경희 511~520이 각자 관련 7건·관련 없음 3건을 써서 측정 전에 등록했다.
문항 내용은 고치지 않으므로, 여기서는 형식과 측정 도구가 읽을 수 있는지만 본다.
sha256(줄바꿈을 LF로 맞춘 바이트)은 측정 전 등록 시점의 값이다. 바뀌면 측정 뒤에 문항을 고친 것이다.
"""
import hashlib
import json
import re
from pathlib import Path

from evals.retrieval.gold import parse_gold
from evals.retrieval.run import load_dataset

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "evals" / "dataset_holdout_v2.jsonl"
HANDBOOK = ROOT / "data" / "corpus" / "handbook"
SHA256_LF = "0eedb8c078dbbaddf90388f3afb9cc53b09555e7c206f2cb78744434a9647abd"
KEYS = {"id", "input", "kind", "expected", "gold_chunks", "why", "as_of", "corpus_version", "judges", "author"}
ITYPES = {"out_of_domain", "unknown_entity", "missing_attribute", "wrong_period"}
REF = re.compile(r"[a-z0-9_./-]+\.md#L[1-9]\d*")


def _rows() -> list[dict]:
    return [json.loads(line) for line in PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_unchanged_since_registration():
    assert hashlib.sha256(PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == SHA256_LF


def test_twenty_rows_ids_and_authors():
    rows = _rows()
    assert [r["id"] for r in rows] == list(range(501, 521))
    for author, ids in (("박진형", range(501, 511)), ("강경희", range(511, 521))):
        mine = [r for r in rows if r["id"] in ids]
        assert {r["author"] for r in mine} == {author}
        assert sum(r["kind"] == "relevant" for r in mine) == 7
        assert sum(r["kind"] == "irrelevant" for r in mine) == 3


def test_schema_matches_holdout_v1():
    for r in _rows():
        assert set(r) - {"irrelevant_type"} == KEYS, r["id"]
        assert r["as_of"] == "2026-10-27" and r["corpus_version"] == "129243bc" and r["judges"] == []
        assert r["input"].strip() and r["expected"].strip() and r["why"].strip()
        if r["kind"] == "irrelevant":
            assert r["irrelevant_type"] in ITYPES and r["gold_chunks"] == []
        else:
            assert r["kind"] == "relevant" and "irrelevant_type" not in r
            assert 1 <= len(r["gold_chunks"]) <= 2


def test_gold_paths_well_formed():
    for r in _rows():
        for entry in r["gold_chunks"]:
            for alt in entry.split(" | "):
                assert REF.fullmatch(alt), (r["id"], alt)
                if HANDBOOK.is_dir():   # 풀린 원문이 있으면 줄 번호가 파일 안인지도 본다
                    path, line = alt.split("#L")
                    lines = (HANDBOOK / path).read_text(encoding="utf-8").splitlines()
                    assert 1 <= int(line) <= len(lines), (r["id"], alt)
        parse_gold(r["gold_chunks"])


def test_eval_loader_reads_it():
    items = load_dataset(PATH)
    assert len(items) == 20
    assert all(len(it["gold"]) == len(it["gold_chunks"]) for it in items if it["kind"] == "relevant")
