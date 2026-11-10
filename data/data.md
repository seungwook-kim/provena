# data/ : 원문 스냅샷과 manifest

## 이 폴더가 하는 일

`corpus.tar.gz`에 고른 핸드북 원문 스냅샷(압축 한 파일), `index.tar.gz`에 검색 색인 스냅샷(압축 한 파일), `manifest.jsonl`에 문서·청크 목록, `chunks_index.jsonl`에 청크 목록을 둔다(형식은 `data/README.md`). 원문 텍스트는 코드와 폴더를 나눈다. 라이선스 고지는 `LICENSES/`.

- 주인: 박진형 (`LICENSES/`는 팀장)
- 입력: 수집 결과
- 출력: 스냅샷, manifest

## 코퍼스 고정 커밋

| 항목 | 값 |
|---|---|
| 저장소 | https://gitlab.com/gitlab-com/content-sites/handbook |
| 고정 커밋 | `129243bcffcf6cbc8c2e83f537f1836b99900a61` (커밋 날짜 2026-10-27) |
| 기록 위치 | 스냅샷 안 `data/corpus/collect_manifest.json`(`commit`, `corpus_id`), 쪽마다 받은 판은 `data/manifest.jsonl`의 `version_id` |
| 규모 | 문서 1,565(1,564쪽 + 2023 권한표), 청크 23,095, 서로 다른 `chunk_sha256` 22,378 |

## PDF (서비스 색인 전용)

글자 층이 있는 PDF를 Docling(OCR 끔)으로 파싱한다. 문서 형식별 코드는 없고 `backend/rag/ingest/pdf.py`의 원본 목록(`SOURCES`)에 추가하면 된다. 현재 색인 대상은 고정 커밋 `129243bcffcf`의 `static/pdfs/` 아래 PDF 7건이다.

| 항목 | 값 |
|---|---|
| 원본 | `data/pdf/` 아래 7개 파일과 `pdf_manifest.json`(합계 약 1.1MB, 저장소에 커밋하는 대상). 모두 고정 커밋 원본과 크기·sha256·git blob id가 같다. 폴더: `customer-experience/`(3), `legal/privacy/`(1), `marketing/.../roles-personas/assets/`(2), `press/`(1) |
| 뺀 것 | `legal/privacy/customer_dpa_05_01_26.pdf`: `customer_dpa_5_1_26.pdf`와 추출한 글자가 같아 하나만 둔다 |
| 파생 | `data/parsed/pdf_ir.jsonl`(요소 800개), `data/chunks/pdf_chunks.jsonl`(청크 205개). 커밋하지 않고 `python -m backend.rag.ingest.pdf run`으로 다시 만든다(Docling 필요, `backend/requirements-ingest-pdf.txt`) |
| 평가와의 관계 | 평가 색인(`chunks.jsonl`, `manifest.jsonl`, `chunks_index.jsonl`)과 동결 평가셋에는 포함하지 않는다. G3 청크 수에도 더하지 않았다 |
| 라이선스 | 미확인(`LICENSES/LICENSES.md`) |
| Spec | `docs/specs/parse.md` "PDF 파싱" 절 |

## 원문 스냅샷 쓰는 법

원문(1,570파일)은 `data/corpus.tar.gz` 한 파일로 커밋하고, 풀린 `data/corpus/`는 커밋하지 않는다(`.gitignore`).

- **푸는 것은 자동이다.** `docker compose up`(이미지를 만들 때)과 `python -m backend.rag.ingest.parse`·`chunk`·`load`(시작할 때 `data/corpus/`가 없으면)가 풀고, 수집 때 적은 sha256과 같은지 확인한다. 손으로 풀려면 `python -m backend.rag.ingest.snapshot unpack`.
- **원문을 고칠 때는 반드시 아래 순서로 한다.** 압축 파일을 직접 고치지 않는다.
  1. 원문을 연다: `data/corpus/`가 없으면 `python -m backend.rag.ingest.snapshot unpack`
  2. 고친다: 수집기를 다시 돌린다(`python -m backend.rag.ingest.handbook`, `history`). 수집기가 `pages.jsonl`의 쪽별 sha256과 `collect_manifest.json`의 `corpus_id`를 새로 적는다. 원문 파일을 손으로만 고치면 sha256이 맞지 않아 다음 단계에서 멈춘다(바뀐 원문이 모르게 들어가지 않게 하려는 의도)
  3. 다시 압축한다: `python -m backend.rag.ingest.snapshot pack` (sha256을 확인한 뒤 `data/corpus.tar.gz`를 새로 만든다. 같은 원문이면 같은 파일이 나와 diff가 없다)
  4. 파싱·청킹·manifest를 다시 돌리고 `data/corpus.tar.gz`, `manifest.jsonl`, `chunks_index.jsonl`을 같은 PR로 커밋한다. 아래 작업 기록에 한 줄 남긴다
- 평가셋 동결(11/3) 뒤에 원문이 바뀌어 정답이 달라진 문항은 평가셋을 고치지 않고 `evals/exclusions.json`에 적는다(`docs/PRD.md` 341행).

## 검색 색인 스냅샷 쓰는 법

검색 색인(`meta.json`, `chunks.jsonl`, `links.jsonl`, `vectors/voyage-4.npy`, 합계 약 130MB)은 `data/index.tar.gz` 한 파일(약 94.5MB)로 커밋하고, 풀린 `data/index/`는 커밋하지 않는다(`.gitignore`). 압축에는 `meta.json`과 그것이 가리키는 파일만 넣는다.

- **푸는 것은 자동이다.** `docker compose up`(이미지를 만들 때, 그리고 `loader`가 시작할 때 연결한 `./data/index`가 비어 있으면)과 `python -m backend.rag.retrieve.load_snapshot`(시작할 때 `data/index/meta.json`이 없으면)이 풀고, 파일마다 sha256이 `meta.json`과 같은지 확인한다. 압축 파일이 없을 때만 `INDEX_URL`을 본다. 손으로 풀려면 `python -m backend.rag.ingest.snapshot unpack-index`.
- **색인을 고칠 때는 반드시 아래 순서로 한다.** 압축 파일을 직접 고치지 않는다.
  1. 색인을 연다: `data/index/`가 없으면 `python -m backend.rag.ingest.snapshot unpack-index`
  2. 고친다: `python -m backend.rag.retrieve.index`(`build`·`import`·`refresh`·`links`·`translations`)로 다시 만든다. 이 명령이 `meta.json`의 파일별 sha256을 새로 적는다. 파일을 손으로만 고치면 sha256이 맞지 않아 다음 단계에서 멈춘다
  3. 다시 압축한다: `python -m backend.rag.ingest.snapshot pack-index` (sha256을 확인한 뒤 `data/index.tar.gz`를 새로 만든다. 같은 색인이면 같은 파일이 나와 diff가 없다)
  4. `data/index.tar.gz`를 색인을 바꾼 코드와 같은 PR로 커밋하고, 아래 작업 기록에 한 줄 남긴다. 다시 커밋할 때마다 저장소 기록에 압축 파일 크기만큼 쌓이므로 모델·청크가 바뀔 때만 다시 만든다

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) `data/demo_replay/questions.txt`(녹화한 데모 질문 9개) 추가, `recorded.jsonl`을 최종 판정·분류·인용 수정 뒤로 다시 녹화(커밋 3c9a1ad, a03ac9f) | #119 |
| 2026-11-03 | 김승욱(팀장, Claude Code) | 고정 커밋 `static/pdfs/`의 PDF 7건을 `data/pdf/`에 받아 두고(고정 커밋 원본과 sha256·git blob id 대조) Docling(OCR 끔)으로 파싱·청킹하는 `backend/rag/ingest/pdf.py`를 추가함. 산출물은 평가 색인과 분리(`pdf_ir.jsonl` 요소 800개, `pdf_chunks.jsonl` 청크 205개). `chunks.jsonl`·`manifest.jsonl`·`chunks_index.jsonl` 해시 변동 없음, 임베딩·DB 적재는 하지 않음 | |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 판 날짜 UTC(I-011)로 `data/corpus.tar.gz` 다시 만듦: 같은 고정 커밋을 `handbook --skip-authz --fetched-at 2026-10-31`·`history --skip-authz`로 다시 읽음. 바뀐 것은 `pages.jsonl` 72쪽의 `version_date`, `history/handbook_commits.jsonl` 219건의 `date`, `collect_manifest.json`의 `version_rule` 글자·`git_version`(2.54→2.55)뿐. 원문·`corpus_id`·`manifest.jsonl`·`chunks_index.jsonl` 그대로 | 이 PR |
| 2026-11-01 | 김승욱(팀장) | 코퍼스 고정 커밋을 이 파일 "코퍼스 고정 커밋" 절에 적고, `AGENTS.md`·`LICENSES/LICENSES.md`의 "manifest에 기록" 문장을 실제 위치로 맞춤(고정 커밋은 스냅샷 안 `collect_manifest.json`에만 있어 저장소에서 바로 보이지 않았음) | 이 PR |
| 2026-11-01 | 김승욱(팀장) | `manifest.jsonl`을 773KB에서 489KB로 줄임: 체크포인트 현황판이 G3 칸을 "manifest가 커서 읽지 못함"으로 표시해 확인하니 GitHub GraphQL이 파일 내용을 잘라 돌려줌(`isTruncated`). 모든 줄이 같은 `parser`(`data/parsed/parse_report.json`에 있음)와 `path`(`source_url`과 같은 쪽)를 빼고, `skipped`는 값이 있는 53줄에만 적고, JSON 공백을 없앰. 가이드 필수 칸(출처, 수집일, 문서당 청크 수, 원문·보존 길이, 잘림 여부)과 숫자(문서 1,565, 청크 23,095)는 그대로 | 이 PR |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷을 `data/corpus.tar.gz` 한 파일(4.5MB, 원문 20MB·1,570파일)로 커밋하고 푸는 명령 `backend/rag/ingest/snapshot.py`를 둠. 풀 때 쪽별 sha256·권한표 sha256·`corpus_id`를 수집 때와 대조하고, Docker 빌드와 `parse`·`chunk`·`load` 시작 때 자동으로 푼다. 원문 고치는 순서는 위 "원문 스냅샷 쓰는 법". 새로 clone한 저장소에서 압축을 풀어 파싱·청킹·manifest를 다시 돌려 커밋한 `manifest.jsonl`·`chunks_index.jsonl`과 같게 확인 | |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷(1,564쪽·2023 권한표·개정 이력), `data/manifest.jsonl`, 청크 목록 `data/chunks_index.jsonl`(서로 다른 `chunk_sha256` 22,378, G3 증거) 커밋(PR #23 리뷰 포인트 2). 다시 만들 수 있는 `data/parsed/`·`data/chunks/`는 `.gitignore`. PR #23 코드로 수집부터 다시 돌려 문서 1,565·청크 23,095·서로 다른 본문 지문 22,378을 같게 확인 | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
