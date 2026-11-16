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

## PDF (서비스 색인 전용, 아직 검색 색인에 없음)

글자 층이 있는 PDF를 Docling(OCR 끔)으로 파싱한다. 문서 형식별 코드는 없고 `backend/rag/ingest/pdf.py`의 원본 목록(`SOURCES`)에 추가하면 된다. 현재 파싱 대상은 고정 커밋 `129243bcffcf`의 `static/pdfs/` 아래 PDF 7건이다.

| 항목 | 값 |
|---|---|
| 원본 | `data/pdf/` 아래 7개 파일과 `pdf_manifest.json`(합계 약 1.1MB, 저장소에 커밋하는 대상). 모두 고정 커밋 원본과 크기·sha256·git blob id가 같다. 폴더: `customer-experience/`(3), `legal/privacy/`(1), `marketing/.../roles-personas/assets/`(2), `press/`(1) |
| 뺀 것 | `legal/privacy/customer_dpa_05_01_26.pdf`: `customer_dpa_5_1_26.pdf`와 추출한 글자가 같아 하나만 둔다 |
| 파생 | `data/parsed/pdf_ir.jsonl`(요소 800개), `data/chunks/pdf_chunks.jsonl`(청크 205개). 커밋하지 않고 `python -m backend.rag.ingest.pdf run`으로 다시 만든다(Docling 필요, `backend/requirements-ingest-pdf.txt`) |
| 평가와의 관계 | 평가 색인(`chunks.jsonl`, `manifest.jsonl`, `chunks_index.jsonl`)과 동결 평가셋에는 포함하지 않는다. G3 청크 수에도 더하지 않았다 |
| 알려진 한계 (S-08) | 이 7건은 아직 검색 색인에 없다. 2026-11-13 실측: `grep -c '"pdf' data/chunks_index.jsonl` 0건, `static/pdfs` 0건, `manifest.jsonl`의 `pdf` 0건, `index.tar.gz`는 `chunks.jsonl`·`links.jsonl`·`meta.json`·`vectors/voyage-4.npy`뿐(색인 23,095청크가 모두 Markdown). `pdf_chunks.jsonl`을 DB나 색인에 넣는 코드도 없다(`backend/`에서 `pdf_chunks`를 쓰는 곳은 `ingest/pdf.py`뿐). 그래서 답변은 PDF 내용을 근거로 인용하지 못한다. 이유 둘: ① 라이선스 근거가 PDF를 지목하지 못하고 핸드북이 Creative Commons라는 근거가 2016년 블로그 글 한 건뿐이다(`LICENSES/LICENSES.md:17-18`) ② 적재는 임베딩 모델 확정 뒤로 미뤘고 평가 색인에 PDF를 넣지 않기로 했다(`docs/specs/parse.md` Out of Scope). 색인에 넣으려면 라이선스 확인(팀장)과 적재 코드가 먼저 필요하다 |
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
- 평가셋 동결(11/3) 뒤에 원문이 바뀌어 정답이 달라진 문항은 평가셋을 고치지 않고 `evals/exclusions.json`에 적는다(`docs/PRD.md` 10장 평가 계획, 동결 뒤 정답이 달라진 문항 항목).

## 검색 색인 스냅샷 쓰는 법

검색 색인(`meta.json`, `chunks.jsonl`, `links.jsonl`, `vectors/voyage-4.npy`, 합계 약 130MB)은 `data/index.tar.gz` 한 파일(약 94.5MB)로 커밋하고, 풀린 `data/index/`는 커밋하지 않는다(`.gitignore`). 압축에는 `meta.json`과 그것이 가리키는 파일만 넣는다.

- **푸는 것은 자동이다.** `docker compose up`(이미지를 만들 때, 그리고 `loader`가 시작할 때 연결한 `./data/index`가 비어 있으면)과 `python -m backend.rag.retrieve.load_snapshot`(시작할 때 `data/index/meta.json`이 없으면)이 풀고, 파일마다 sha256이 `meta.json`과 같은지 확인한다. 압축 파일이 없을 때만 `INDEX_URL`을 본다. 손으로 풀려면 `python -m backend.rag.ingest.snapshot unpack-index`.
- **색인을 고칠 때는 반드시 아래 순서로 한다.** 압축 파일을 직접 고치지 않는다.
  1. 색인을 연다: `data/index/`가 없으면 `python -m backend.rag.ingest.snapshot unpack-index`
  2. 고친다: `python -m backend.rag.retrieve.index`(`build`·`import`·`refresh`·`links`·`translations`)로 다시 만든다. 이 명령이 `meta.json`의 파일별 sha256을 새로 적는다. 파일을 손으로만 고치면 sha256이 맞지 않아 다음 단계에서 멈춘다
  3. 다시 압축한다: `python -m backend.rag.ingest.snapshot pack-index` (sha256을 확인한 뒤 `data/index.tar.gz`를 새로 만든다. 같은 색인이면 같은 파일이 나와 diff가 없다)
  4. `data/index.tar.gz`를 색인을 바꾼 코드와 같은 PR로 커밋하고, 아래 작업 기록에 한 줄 남긴다. 다시 커밋할 때마다 저장소 기록에 압축 파일 크기만큼 쌓이므로 모델·청크가 바뀔 때만 다시 만든다

## 키 없는 데모 녹화

`data/demo_replay/recorded.jsonl`은 키 없는 데모(`DEMO_MODE=1`)가 재생하는 LLM 응답과 질문 임베딩(voyage-4 벡터) 녹화이고, 질문 목록은 `data/demo_replay/questions.txt`(README "키 없이 뜨는 데모 모드"의 질문 9개)이다. 녹화 요청과 맞지 않는 호출은 결정적 가짜 응답으로 대신한다.

- **확인.** 녹화가 현재 코드와 맞는지는 키·네트워크 없이 `python -m pytest -m demo_replay`(`tests/test_demo_replay_fresh.py`)로 본다. 데모 질문마다 서버와 같은 질문 그래프를 새 Postgres에서 돌려 녹화에 없는 요청이 하나라도 있으면 실패하고 다시 녹화하라고 안내한다(프롬프트나 검색을 바꾼 뒤 실행하며, Docker와 pgvector 이미지가 필요하다. 접속 정보를 직접 줄 때는 `PROVENA_D5_PG_URL`).
- **다시 녹화.** 색인이나 프롬프트를 바꾸면 다시 녹화한다. 색인이 적재된 새 DB(`docker compose down -v` 뒤)에서 이미 있는 `recorded.jsonl`을 지우고(남아 있으면 새 응답이 섞인다) `python -m backend.services.demo_record --questions data/demo_replay/questions.txt`를 실행한다(`DATABASE_URL`, `LLM_API_KEY`, `LLM_PROVIDER`, `VOYAGE_API_KEY` 필요). 이 명령은 서버와 같은 질문 그래프와 검색 설정(금액 구간 조회 `SEARCH_RANGE_N` 기본 3 포함)으로 돌려 재생과 같은 검색 조건을 맞춘다. `SEARCH_RANGE_N`을 직접 주면 재생도 녹화와 같은 값이어야 녹화 키가 맞는다. 녹화 뒤 `python -m pytest -m demo_replay`로 확인한다.
- **녹화 이력.** 현재 녹화는 2026-11-16 03:35~03:37에 커밋 `5a8c652`의 코드로 질문 9개 전부를 새 DB에서 다시 뜬 것이다(금액 구간 조회 켬, LLM 비용 0.136달러, 커밋 `a374decb`). 그 전 녹화는 2026-11-11 20:44의 전체 녹화(기준 커밋 `9c71e0a`)에 2026-11-12 16:31(커밋 `9966bd3`)과 23:43~23:44(커밋 `41377ad`, PR #140)의 일부 재녹화, 2026-11-13 03:22의 금액 질문 3개 재녹화(사전 등록 62.46)를 바꿔 넣은 것이었다. 2026-11-13 전에는 녹화가 금액 구간 조회를 넣기 전 것이라 데모 모드만 조회를 끄고 재생했다. 2026-11-09 녹화는 커밋 `4f03a8d` 이후의 프롬프트(`ANSWER_SYSTEM`, `redraft_user` 규칙 추가)와 맞지 않아 답 본문이 "검색된 근거를 그대로 발췌한 답입니다(데모 모드: 실제 LLM이 쓴 답이 아닙니다)"라는 대체 문장이 되던 상태여서 새 녹화로 대체했다. 10만 달러 질문은 2026-11-13 녹화까지는 거절로 끝났고 2026-11-16 재녹화부터 답한다. 새 clone 확인 기록은 `docs/GATES.md` G2에 있다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-15 | 박진형 (jinyeong-731) | 놓친 것 K-22: 키 없는 데모 녹화 `data/demo_replay/recorded.jsonl`을 다시 녹화(K-24 수정 커밋 `9f91b3b0` 위). 방법은 `backend/services/demo_record.py` 머리말 그대로: 임시 docker Postgres(`pgvector/pgvector:pg16`, `db/*.sql` 적용) → `python -m backend.rag.retrieve.load_snapshot`(청크 23,095개, 번역 0개) → 기존 녹화를 저장소 밖에 두고 `python -m backend.services.demo_record --questions data/demo_replay/questions.txt --max-total-usd 0.5`(모델 `claude-haiku-5-5`, 질문 벡터 `voyage-4`, `.env.example`을 바탕 환경으로). 9개 질문 모두 성공, 녹화 228줄, LLM 비용 0.223달러(머리말 추정 0.05~0.12달러보다 큼). 운영 DB는 쓰지 않음(번역 장부가 차 있어 재생과 키가 어긋난다). 임시 컨테이너는 지움 | #162 |
| 2026-11-13 | 박진형 (jinyeong-731) | 팀장 커밋 515acc3d(표 행 겹침 상한 400자, 결정 0115)가 `data/manifest.jsonl`·`data/chunks_index.jsonl`을 바꾼 것을 기록. `data/index.tar.gz`의 `chunks.jsonl`(옛 색인)과 지금 `chunks_index.jsonl`을 chunk_id로 대조(Python `tarfile`)하면 23,095개 중 37개가 달라졌다(옛 쪽에만 37, 새 쪽에만 37). 청크 수와 서로 다른 본문 수는 그대로다. 겹침만 바뀌어 id가 그대로인 청크는 이 대조에 안 잡히며(커밋 메시지는 바뀐 청크 762개 = id 유지 725 + 새 id 37이라 적었다, 725는 여기서 재지 않았다) `index.tar.gz`는 그 커밋에서 바뀌지 않았다. 코드·데이터 변경 없음, 문서만 | #157 |
| 2026-11-13 | 박진형 (jinyeong-731) | S-08: PDF 절에 알려진 한계 기록(PDF 7건이 검색 색인에 없음, 실측 4곳 0건, 이유는 라이선스 근거 부족·적재 미룸). 제목과 "현재 색인 대상" 문구를 "현재 파싱 대상"으로 정정. 코드·데이터 변경 없음 | #157 |
| 2026-11-10 | 김승욱 (기록: 박진형) | (보충, PR #119) `data/demo_replay/questions.txt`(녹화한 데모 질문 9개) 추가, `recorded.jsonl`을 최종 판정·분류·인용 수정 뒤로 다시 녹화(커밋 3c9a1ad, a03ac9f) | #119 |
| 2026-11-03 | 김승욱(팀장, Claude Code) | 고정 커밋 `static/pdfs/`의 PDF 7건을 `data/pdf/`에 받아 두고(고정 커밋 원본과 sha256·git blob id 대조) Docling(OCR 끔)으로 파싱·청킹하는 `backend/rag/ingest/pdf.py`를 추가함. 산출물은 평가 색인과 분리(`pdf_ir.jsonl` 요소 800개, `pdf_chunks.jsonl` 청크 205개). `chunks.jsonl`·`manifest.jsonl`·`chunks_index.jsonl` 해시 변동 없음, 임베딩·DB 적재는 하지 않음 | |
| 2026-11-02 | 박진형 (jinyeong-731) | 판 날짜 UTC(I-011)로 `data/corpus.tar.gz` 다시 만듦: 같은 고정 커밋을 `handbook --skip-authz --fetched-at 2026-10-31`·`history --skip-authz`로 다시 읽음. 바뀐 것은 `pages.jsonl` 72쪽의 `version_date`, `history/handbook_commits.jsonl` 219건의 `date`, `collect_manifest.json`의 `version_rule` 글자·`git_version`(2.54→2.55)뿐. 원문·`corpus_id`·`manifest.jsonl`·`chunks_index.jsonl` 그대로 | 이 PR |
| 2026-11-01 | 김승욱(팀장) | 코퍼스 고정 커밋을 이 파일 "코퍼스 고정 커밋" 절에 적고, `AGENTS.md`·`LICENSES/LICENSES.md`의 "manifest에 기록" 문장을 실제 위치로 맞춤(고정 커밋은 스냅샷 안 `collect_manifest.json`에만 있어 저장소에서 바로 보이지 않았음) | 이 PR |
| 2026-11-01 | 김승욱(팀장) | `manifest.jsonl`을 773KB에서 489KB로 줄임: 체크포인트 현황판이 G3 칸을 "manifest가 커서 읽지 못함"으로 표시해 확인하니 GitHub GraphQL이 파일 내용을 잘라 돌려줌(`isTruncated`). 모든 줄이 같은 `parser`(`data/parsed/parse_report.json`에 있음)와 `path`(`source_url`과 같은 쪽)를 빼고, `skipped`는 값이 있는 53줄에만 적고, JSON 공백을 없앰. 가이드 필수 칸(출처, 수집일, 문서당 청크 수, 원문·보존 길이, 잘림 여부)과 숫자(문서 1,565, 청크 23,095)는 그대로 | 이 PR |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷을 `data/corpus.tar.gz` 한 파일(4.5MB, 원문 20MB·1,570파일)로 커밋하고 푸는 명령 `backend/rag/ingest/snapshot.py`를 둠. 풀 때 쪽별 sha256·권한표 sha256·`corpus_id`를 수집 때와 대조하고, Docker 빌드와 `parse`·`chunk`·`load` 시작 때 자동으로 푼다. 원문 고치는 순서는 위 "원문 스냅샷 쓰는 법". 새로 clone한 저장소에서 압축을 풀어 파싱·청킹·manifest를 다시 돌려 커밋한 `manifest.jsonl`·`chunks_index.jsonl`과 같게 확인 | |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷(1,564쪽·2023 권한표·개정 이력), `data/manifest.jsonl`, 청크 목록 `data/chunks_index.jsonl`(서로 다른 `chunk_sha256` 22,378, G3 증거) 커밋(PR #23 리뷰 포인트 2). 다시 만들 수 있는 `data/parsed/`·`data/chunks/`는 `.gitignore`. PR #23 코드로 수집부터 다시 돌려 문서 1,565·청크 23,095·서로 다른 본문 지문 22,378을 같게 확인 | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
