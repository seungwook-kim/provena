# Spec — 핸드북·권한표 파싱 (박진형, 업무 분담 B-2)

## Why

- **페르소나**: 청킹(B-3)·검색(B-4)·결정표(F-04, 김승욱)를 만드는 우리 조, 그리고 "이 인용이 원문 어디에 있나"를 확인하는 평가자
- **상황**: 수집한 원문(`data/corpus/`)에는 Hugo 단축코드 45종, HTML 아이콘·표, 코드 블록이 섞여 있다. 권한표는 CSS grid `div` 로 그린 표다.
- **문제**:
  1. 단축코드를 그대로 두면 청크가 `{{% alert %}}` 같은 잡음으로 오염된다.
  2. 문단이 어느 절(제목 경로)·원본 몇째 줄에서 왔는지 모르면 인용을 검증할 수 없다.
  3. 권한표 칸이 한 칸만 밀려도 결정표 정확도가 전부 틀린다.
- **측정 지표**: 원본 줄 번호로 되찾은 요소 비율, 권한표 역할 주석 대조 불일치 수, 검토 대기 쪽 수

## Goal

- **해결 목표**: 글자 층이 있는 PDF를 Docling(OCR 끔)으로 파싱해 기존 요소 형식(`element_id ... review`)으로 바꾸고(`data/parsed/pdf_ir.jsonl`), 같은 청킹 규칙(800자, 120자 겹침)으로 서비스 색인 전용 청크(`data/chunks/pdf_chunks.jsonl`)를 만든다. 문서 형식별 코드는 없고 원본 목록(`SOURCES`)에 파일을 추가하면 된다. 현재 색인 대상은 고정 커밋 `static/pdfs/` 아래 PDF 7건이다(`data/pdf/pdf_manifest.json`). 글자가 같은 `customer_dpa_05_01_26.pdf`와 `customer_dpa_5_1_26.pdf`는 하나만 둔다.
- **성공 기준**: 처음 보는 단축코드 0종(있으면 그 쪽은 검토 대기) / 요소 원문 되찾기 실패 0 / 권한표 363칸 역할 주석 불일치 0 / 금액 구간 끊김은 실패가 아니라 목록으로 보고
- **Out of Scope**: 청킹·청크 수(B-3), include 26곳 끌어오기(데이터카드에 기록), 결정표 만들기(F-04), 이모지를 그림 글자로 바꾸기

## What

**Happy Path**
1. `python -m backend.rag.ingest.parse`
2. 페이지마다: front matter와 단축코드를 **줄 수를 바꾸지 않고** 정리 → markdown-it-py(CommonMark + table)로 토큰화
3. 블록마다 요소 하나: 제목·문단·목록 항목(최상위)·표 행·코드·HTML 표 행·HTML 문단. 요소에 제목 경로·부모 제목·순서·원본 줄 범위를 붙인다
3-1. 셀 안에 빈 줄이 든 HTML 표(`<table>`~`</table>`)는 한 블록으로 읽는다(`join_html_tables`): markdown-it의 HTML 블록은 빈 줄에서 끝나 표가 끊기고 뒤 칸이 열 이름 없는 목록·문단 요소가 되므로, 표 안의 빈 줄만 `<!-- -->` 한 줄로 바꾼다(줄 수 그대로). 코드 블록(펜스) 안의 표는 건드리지 않는다. 칸 안 마크다운 링크 `[글자](주소)`는 글자만 남긴다
4. 권한표: BeautifulSoup으로 본표(`div.grid-auth-matrix`) 363칸, 이사회 표(`div.treasury-auth-matrix`), 각주 (1)~(6). 표 밖 글(계약 승인 절차·각주 목록·Authorization Matrix Policy)은 쪽과 같은 방식으로 요소로 만들고(`authz_ir.jsonl`), 두 표의 줄은 빼서 칸과 겹치지 않게 한다. 정책 본문(Primary Authorized Signatories)이 없거나 예상 밖 HTML이 있으면 `ParseError`
5. `data/parsed/` 에 쓰고 다시 읽어 건수를 대조, `parse_report.json` 에 집계

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 처음 보는 단축코드 | 그 쪽 요소에 `review` 표시(검토 대기), 다른 쪽은 계속. 끝나고 1개라도 있으면 종료 코드 1 |
| EC-02 | 코드 블록 안의 `#`, 백틱 4개 펜스 | markdown-it-py가 코드로 처리 (정규식 파서는 이 경우 제목을 잃음, 파서 비교) |
| EC-03 | 내용 없이 옮겨진 페이지(`redirect_to`) 3쪽 | 건너뛰고 보고 (I-002) |
| EC-04 | 표 행의 칸 수가 머리 칸 수와 다름 | 행은 남기고 `review` 표시 |
| EC-05 | 권한표 칸 수가 11이 아니거나 역할 주석이 열 이름과 다름 | `ParseError` 로 멈춤 (칸 밀림 = 정답지 오염) |
| EC-06 | 권한표 금액 구간이 이어지지 않음(예: `>$5K` 다음 `>$50K`) | 실패가 아니라 원문 사실로 `band_gaps` 에 보고 → 결정표 담당에게 |
| EC-07 | 이스케이프된 단축코드 `{{</* x */>}}` | Hugo처럼 글자 `{{< x >}}` 로 남김 |

## How

- 라이브러리: `markdown-it-py`(4.2.0), `beautifulsoup4`(4.15.0). 비교 근거: 표본 20쪽 파서 비교(제목 F1 0.996, 표 19/20, 코드 20/20)
- 단축코드 분류: 감싸기(alert·details·panel·note·tableau: 표시만 지우고 안 글자 유지, details·panel 제목 글자는 남김) / 이름(member-by-name·member-by-gitlab·member-and-role-by-gitlab·label: 인자 글자로) / 링크(ref: 경로로) / 데이터(나머지 36종: 사이트가 다른 데이터로 채움, 지우고 개수 기록)
- HTML → 글자 순서(rag1-07): script·style 내용째 제거 → 줄바꿈 태그를 줄바꿈으로 → 나머지 태그를 공백으로 → 엔티티 복원 → 공백 정리
- 출력 `data/parsed/`(원문에서 다시 만들므로 커밋하지 않는다. 결정표 변환이 실행 중에 읽는 `authz_cells.jsonl`만 커밋한다): `document_ir.jsonl`, `authz_cells.jsonl`, `authz_board.jsonl`, `authz_notes.jsonl`, `authz_ir.jsonl`, `parse_report.json`
- 요소 필드: `element_id, rule_seq, org, kind, heading_path, parent_id, order, line_start, line_end, text, links, review` (+ 표 행: `table_id, row, header`)
- 권한표 칸 필드: `category, category_notes, band, band_lo, band_hi, role, approval_type(functional|financial), value, notes, line`

## AC (Given-When-Then)

**AC-01 · 줄 번호 보존**
- GIVEN: front matter·단축코드가 있는 페이지
- WHEN: 전처리
- THEN: 줄 수가 원본과 같고, 각 요소의 `line_start~line_end` 원본 줄에서 요소 글자를 되찾을 수 있다

**AC-02 · HTML 정리 순서**
- GIVEN: `&lt;script&gt;` 를 설명하는 문장
- WHEN: HTML → 글자
- THEN: 설명 문장이 남는다(엔티티를 먼저 풀면 지워짐)

**AC-03 · 코드 블록 속 `#` 는 제목이 아님**
- GIVEN: 백틱 4개 펜스 안에 `# x` 와 백틱 3개 펜스
- WHEN: 파싱
- THEN: 제목 요소 0개, 코드 요소 1개

**AC-04 · 권한표 칸 밀림 감지**
- GIVEN: 역할 주석이 열 이름과 다른 칸, 또는 칸이 하나 모자란 행
- WHEN: 권한표 파싱
- THEN: `ParseError`

**AC-05 · 금액 구간 끊김 보고**
- GIVEN: `Up to $5K`, `>$5K`, `>$50K`
- WHEN: 구간 검산
- THEN: 끊김 1건 보고, 예외 없음

---

# Spec — PDF 파싱 (Docling, OCR 끔)

## Why

- **페르소나**: 핸드북이 링크하는 PDF도 답의 근거로 인용해야 하는 에이전트와, "이 인용이 PDF 몇 쪽인가"를 확인하는 평가자
- **상황**: 핸드북 고정 커밋 `129243bcffcf`의 `static/pdfs/` 아래에 PDF가 있다. Markdown 파서(`parse.py`)는 PDF를 읽지 못한다.
- **문제**: 쪽 번호, 제목 계층, 표 행·열을 함께 주는 파서가 필요하다. 비교 측정에서 Docling을 골랐다(근거와 측정값은 `조사/PDF 파서 비교 측정 (2026-11-03)`). 평가 색인(`chunks.jsonl`)과 동결 평가셋은 바꾸지 않는다.

## Goal

- **해결 목표**: 글자 층이 있는 PDF를 Docling(OCR 끔)으로 파싱해 기존 요소 형식(`element_id ... review`)으로 바꾸고(`data/parsed/pdf_ir.jsonl`), 같은 청킹 규칙(800자, 120자 겹침)으로 서비스 색인 전용 청크(`data/chunks/pdf_chunks.jsonl`)를 만든다. 문서 형식별 코드는 없고 원본 목록(`SOURCES`)에 파일을 추가하면 된다. 현재 색인 대상은 치트시트 1건이다.
- **성공 기준**: 빠진 요소 0 / Chunk 계약 통과 / 기존 `chunks.jsonl`과 평가 파일 해시 변동 0
- **Out of Scope**: OCR·스캔 PDF, 평가 색인에 PDF 넣기, 임베딩과 DB 적재(모델 확정 뒤)

## What

**Happy Path**
1. `python -m backend.rag.ingest.pdf collect --from <받아 둔 폴더> --collected-at YYYY-MM-DD`: 고정 커밋 원본과 크기·sha256·git blob id가 모두 같은 파일만 `data/pdf/`에 복사하고 `pdf_manifest.json`을 쓴다. `--download`는 고정 커밋 원본을 직접 받는다.
2. `python -m backend.rag.ingest.pdf run`: Docling(OCR 끔, 표 구조 켬, CPU)으로 변환해 JSON을 `data/parsed/pdf_docling/`에 저장하고(`--reuse-docling`이면 변환을 건너뜀), 본문 트리를 문서 순서로 훑어 요소를 만든다.
3. 청킹은 `chunk.py`의 `chunk_structure`를 그대로 쓴다. 쪽은 `source_url`의 `#page=N`(청크가 시작하는 쪽)에, 걸친 쪽 전체는 청크 파일의 `pages`에 둔다. `Chunk` 계약 칸은 늘리지 않는다. `line_start`, `line_end`는 비운다.

**요소 규칙** (글 모양만 본다)
- 쪽 머리글·바닥글(Docling `furniture`), 숫자만 있는 쪽 번호, 그림은 요소로 만들지 않고 건수를 `pdf_parse_report.json`에 센다.
- 제목 모양: 12단어 이하, 작은 낱말(of, the, and ...)을 뺀 모든 낱말이 대문자·숫자로 시작, 쉼표·쌍점으로 끝나지 않음, `Inc.` 같은 약어에서 끊지 않음.
- 숫자 표지(`13.`)가 있는 목록 항목 중 같은 목록에서 가장 왼쪽이고 첫 구절이 제목 모양이면 그 구절을 제목으로, 나머지를 문단으로 나눈다. 글자 표지(`a.`)나 안쪽 항목은 제목이 아니다. Docling이 제목으로 낸 글도 `제목. 본문` 모양이면 같은 방식으로 나눈다.
- 제목 수준: 문서 첫 제목 = 1, `EXHIBIT`·`ANNEX`·`APPENDIX`·`SCHEDULE`·`ATTACHMENT`로 시작하는 제목 = 2(그 뒤의 다른 제목은 3), 그 밖 = 2. `heading_path`는 이 수준으로 만든다.
- 표지가 없고 앞 쪽에서 끝난 문장 부호 없는 글 뒤에 오는 문단·목록 항목은 쪽 경계에서 끊긴 글로 보고 앞 요소에 잇는다(`page_end`에 쪽 범위).
- 한 단짜리 쪽(가로로 떨어지면서 세로로 겹치는 요소 쌍이 없는 쪽)은 위에서 아래로 순서를 다시 세운다. 다단 쪽은 Docling 순서를 그대로 둔다.
- 표는 기존 표 행 형식(`table_id, row, header, cells`, 행 글자는 `머리: 값 | ...`)으로 펼친다. 병합 칸은 왼쪽 위 칸에만 글자를 둔다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-PDF-01 | 받은 파일이 고정 커밋 원본과 다름(이름이 비슷한 다른 파일 포함) | `ValueError`로 멈춘다(크기, sha256, git blob id 모두 대조) |
| EC-PDF-02 | 그림 안의 글자(OCR 끔) | 요소로 만들지 않는다 |

## How

- 라이브러리: `docling==2.145.0`(`backend/requirements-ingest-pdf.txt`, 운영 이미지와 `backend/requirements.txt`에는 넣지 않음). `pdf.py`는 Docling을 `convert()` 안에서만 가져오므로 Docling 없는 환경에서도 이 모듈과 시험이 돈다.
- 출력(저장소에 커밋하지 않음): `data/parsed/pdf_ir.jsonl`, `data/parsed/pdf_parse_report.json`, `data/parsed/pdf_docling/*.docling.json`, `data/chunks/pdf_chunks.jsonl`. 원본 PDF와 `pdf_manifest.json`은 `data/pdf/`
- 요소 필드: 위 기존 요소 필드와 같고, `line_start`·`line_end`는 `null`, 대신 `page`(시작 쪽, 1부터), `page_end`, `bbox`(PDF 포인트 `[왼쪽, 아래, 오른쪽, 위]`, 원점 왼쪽 아래)
- 청크 칸: `org`는 `static/pdfs/` 아래 첫 폴더, `rule_seq`는 `static/pdfs/...` 경로의 해시, 제목은 문서의 수준 1 제목, `version_id`는 고정 커밋 앞 12자, `version_date`는 고정 커밋 날짜이고 파일을 고친 날을 모르므로 `version_date_before`는 참
- `chunk.py` 변경: `line_span()`을 추가해 줄 번호가 없는 요소(PDF)는 `line_start`·`line_end`를 비운다. 줄 번호가 있는 Markdown 요소는 이전과 같다.
- 적재: 임베딩 모델이 확정되면 `chunks.jsonl`과 같은 방식으로 `pdf_chunks.jsonl`을 임베딩해 같은 청크 저장소에 넣는다. 평가 색인과 `manifest.jsonl`은 바꾸지 않는다.
- 시험: `tests/test_ingest_pdf.py`. 번호 조항·부록·쪽 이음·순서 재정렬은 시험 안에서 지어낸 합성 입력으로, 표·머리글·그림은 `tests/fixtures/docling_pdf_sample.json`(치트시트 일부)으로 확인한다. 제목 규칙을 실제 문서에서 잰 값은 저장소 밖 시험 자료와 위 조사 문서에 있다.

## AC (Given-When-Then)

**AC-PDF-01 · 번호 조항 목록 항목이 제목이 됨**
- GIVEN: Docling 목록 항목 `2.` + `Status of the Parties. This agreement applies ...`(가장 왼쪽 숫자 표지)
- WHEN: 요소 만들기
- THEN: 제목 `2. Status of the Parties`(2수준)와 문단 `This agreement applies ...`로 나뉜다. 글자 표지 `a.`와 안쪽 숫자 항목은 제목이 아니다

**AC-PDF-02 · 부록 안 제목은 한 수준 아래**
- GIVEN: `EXHIBIT C`, `Region Specific Terms`, `1. ALPHA` 순서의 제목
- WHEN: 수준 부여
- THEN: `EXHIBIT C` 2수준, 나머지 3수준, 제목 경로 `... > EXHIBIT C > 1. ALPHA`

**AC-PDF-03 · 쪽 경계에서 끊긴 글 잇기, 순서 바로잡기**
- GIVEN: 쪽 끝에서 문장이 끝나지 않고 다음 쪽 첫머리가 표지 없는 글, 그리고 쪽 위쪽 제목이 본문 뒤에 나온 한 단짜리 쪽
- WHEN: 요소 만들기
- THEN: 앞 요소에 이어져 `page_end`가 다음 쪽이 되고, 제목이 위로 올라온다. 다단 쪽의 순서는 그대로다

**AC-PDF-04 · 표는 기존 표 행 형식**
- GIVEN: Docling 표 셀(열 제목 행, 병합 칸 포함)
- WHEN: 표 펼치기
- THEN: `table_id, row, header, cells`와 `parse.py`와 같은 행 글자, 병합 칸은 왼쪽 위 칸에만 글자

**AC-PDF-05 · 청크 쪽과 계약**
- GIVEN: PDF 요소
- WHEN: 청킹
- THEN: 청크가 `Chunk` 계약을 통과하고 `line_start`·`line_end`는 비며, `source_url`은 `...#page=N`(시작 쪽), 청크 파일의 `pages`는 걸친 쪽 전체다. 빠진 요소 0

**AC-PDF-06 · 수집은 고정 커밋 원본만**
- GIVEN: 크기·sha256·git blob id 중 하나라도 다른 파일
- WHEN: `collect`
- THEN: `ValueError`

**AC-PDF-07 · Docling 없이 돈다**
- GIVEN: Docling이 없는 환경
- WHEN: `backend.rag.ingest.pdf`를 가져오고 시험을 돌림
- THEN: 가져오기가 Docling을 불러오지 않고 시험이 통과한다
