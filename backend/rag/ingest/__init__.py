"""문서 파싱, 청킹, 인덱싱 (G3).

요건: 서로 다른 청크 1만 개 이상, 서로 다른 문서 50건 이상(복제와 변형 제외), 문서 파싱 1종 이상.
인덱스를 만들 때마다 data/manifest.jsonl에 문서와 청크 목록을 남기세요 (data/README.md 형식).
원문과 파싱 결과를 3건 이상 대조해 기록하세요 (EVAL_REPORT.md 1장).
"""


def ingest(corpus_dir: str = "data/corpus") -> None:
    raise NotImplementedError("TODO: 파싱, 청킹, 임베딩, 적재, manifest 기록")
