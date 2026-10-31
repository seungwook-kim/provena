# data/ : 원문 스냅샷과 manifest

## 이 폴더가 하는 일

`corpus.tar.gz`에 고른 핸드북 원문 스냅샷(압축 한 파일), `manifest.jsonl`에 문서·청크 목록, `chunks_index.jsonl`에 청크 목록을 둔다(형식은 `data/README.md`). 원문 텍스트는 코드와 폴더를 나눈다. 라이선스 고지는 `LICENSES/`.

- 주인: 박진형 (`LICENSES/`는 팀장)
- 입력: 수집 결과
- 출력: 스냅샷, manifest

## 원문 스냅샷 쓰는 법

원문(1,570파일)은 `data/corpus.tar.gz` 한 파일로 커밋하고, 풀린 `data/corpus/`는 커밋하지 않는다(`.gitignore`).

- **푸는 것은 자동이다.** `docker compose up`(이미지를 만들 때)과 `python -m backend.rag.ingest.parse`·`chunk`·`load`(시작할 때 `data/corpus/`가 없으면)가 풀고, 수집 때 적은 sha256과 같은지 확인한다. 손으로 풀려면 `python -m backend.rag.ingest.snapshot unpack`.
- **원문을 고칠 때는 반드시 아래 순서로 한다.** 압축 파일을 직접 고치지 않는다.
  1. 원문을 연다: `data/corpus/`가 없으면 `python -m backend.rag.ingest.snapshot unpack`
  2. 고친다: 수집기를 다시 돌린다(`python -m backend.rag.ingest.handbook`, `history`). 수집기가 `pages.jsonl`의 쪽별 sha256과 `collect_manifest.json`의 `corpus_id`를 새로 적는다. 원문 파일을 손으로만 고치면 sha256이 맞지 않아 다음 단계에서 멈춘다(바뀐 원문이 모르게 들어가지 않게 하려는 의도)
  3. 다시 압축한다: `python -m backend.rag.ingest.snapshot pack` (sha256을 확인한 뒤 `data/corpus.tar.gz`를 새로 만든다. 같은 원문이면 같은 파일이 나와 diff가 없다)
  4. 파싱·청킹·manifest를 다시 돌리고 `data/corpus.tar.gz`, `manifest.jsonl`, `chunks_index.jsonl`을 같은 PR로 커밋한다. 아래 작업 기록에 한 줄 남긴다
- 평가셋 동결(11/3) 뒤에 원문이 바뀌어 정답이 달라진 문항은 평가셋을 고치지 않고 `evals/exclusions.json`에 적는다(`docs/PRD.md` 341행).

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-01 | 김승욱(팀장) | `manifest.jsonl`을 773KB에서 489KB로 줄임: 체크포인트 현황판이 G3 칸을 "manifest가 커서 읽지 못함"으로 표시해 확인하니 GitHub GraphQL이 파일 내용을 잘라 돌려줌(`isTruncated`). 모든 줄이 같은 `parser`(`data/parsed/parse_report.json`에 있음)와 `path`(`source_url`과 같은 쪽)를 빼고, `skipped`는 값이 있는 53줄에만 적고, JSON 공백을 없앰. 가이드 필수 칸(출처, 수집일, 문서당 청크 수, 원문·보존 길이, 잘림 여부)과 숫자(문서 1,565, 청크 23,095)는 그대로 | 이 PR |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷을 `data/corpus.tar.gz` 한 파일(4.5MB, 원문 20MB·1,570파일)로 커밋하고 푸는 명령 `backend/rag/ingest/snapshot.py`를 둠. 풀 때 쪽별 sha256·권한표 sha256·`corpus_id`를 수집 때와 대조하고, Docker 빌드와 `parse`·`chunk`·`load` 시작 때 자동으로 푼다. 원문 고치는 순서는 위 "원문 스냅샷 쓰는 법". 새로 clone한 저장소에서 압축을 풀어 파싱·청킹·manifest를 다시 돌려 커밋한 `manifest.jsonl`·`chunks_index.jsonl`과 같게 확인 | |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷(1,564쪽·2023 권한표·개정 이력), `data/manifest.jsonl`, 청크 목록 `data/chunks_index.jsonl`(서로 다른 `chunk_sha256` 22,378, G3 증거) 커밋(PR #23 리뷰 포인트 2). 다시 만들 수 있는 `data/parsed/`·`data/chunks/`는 `.gitignore`. PR #23 코드로 수집부터 다시 돌려 문서 1,565·청크 23,095·서로 다른 본문 지문 22,378을 같게 확인 | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
