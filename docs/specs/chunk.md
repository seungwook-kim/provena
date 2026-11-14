# Spec — 청킹과 manifest (박진형, 업무 분담 B-3)

## Why

- **페르소나**: 검색(B-4)·질문 그래프(김승욱)가 쓸 청크를 받는 우리 조, G3(서로 다른 청크 1만+)를 확인하는 평가자
- **상황**: 파싱 결과(`data/parsed/document_ir.jsonl`)는 요소 85,332개다(2026-11-14 `data/corpus.tar.gz`를 풀어 `parse`를 다시 돌린 값, 1,561쪽. 515acc3d의 HTML 표 합치기 전 11-12 값은 85,388. 권한표 표 밖 요소 103개는 `authz_ir.jsonl`에 따로 있다). 검색 단위는 요소보다 크고 문서보다 작아야 한다.
- **문제**:
  1. 문단 중간에서 자르면 근거가 반쪽이 된다.
  2. 청크만 보고 어느 페이지·절인지 모르면 LLM이 질문 속 이름을 가져다 답한다(rag1-09).
  3. 겹침을 넣은 청크를 그대로 세면 G3 숫자가 부푼다.
- **측정 지표**: 청크 수·서로 다른 본문 지문 수(G3), 요소 글자가 청크에 들어간 비율, 청크 길이 분포

## Goal

- **해결 목표**: 절(제목 경로) 단위로 요소를 묶은 청크와, 문서별 manifest를 만든다. 크기·겹침·머리말은 옵션이라 D2 골든셋으로 다시 잰다.
- **성공 기준**: 서로 다른 본문 지문 1만 이상(G3) / 요소 글자 100%가 청크에 들어감 / 겹침 설정을 바꿔도 G3 숫자가 같음 / 청크마다 원본 줄 범위로 원문을 되찾음(코드 조각은 조각별 정확한 줄. 쪼갠 다른 요소와 HTML 표 행은 요소 전체 줄 범위라 넓다 — `data/data.md` 알려진 한계)
- **Out of Scope**: 임베딩·DB 적재(B-4 `load.py` 뒤쪽), 시맨틱·late 청킹, 크기·겹침 최종값 결정(D2)

## What

**Happy Path**
1. `python -m backend.rag.ingest.chunk` (기본: 구조 방식, 800자, 겹침 120자, 머리말 있음)
2. 쪽마다 제목(1~4단계)이 아닌 요소를 같은 제목 경로끼리 묶는다(절)
3. 절 안에서 요소를 순서대로 담다가 800자를 넘으면 새 청크. 요소는 자르지 않는다
4. 800자 넘는 요소 하나는 줄 → 문장 → 표 칸 경계(`| ` 뒤)·공백 → 글자 순으로 쪼갠다. 낱말·숫자 한가운데서 자르지 않는다. 공백이 하나도 없는 긴 글만 구분 글자(`|`, `,;`, `/`) 뒤에서, 그것도 없을 때만 글자 단위로 자른다(2026-11-13: 이전에는 문장 안에서 800자마다 글자 단위로 잘라 `1174,`가 `117`/`4,`로 갈렸다)
5. 같은 절 안의 둘째 청크부터 앞 청크 끝 120자를 앞에 붙인다(단어 경계). 겹침이 표 행(`table_row`) 안에서 시작하면 그 행의 처음부터 가져온다(행 처음부터 앞 청크 끝까지가 400자(`ROW_TAIL_MAX`) 이하일 때). 더 길거나 행 처음이 앞 청크에 없으면(쪼갠 행의 뒤 조각) 평소 겹침 앞에 그 행의 첫 칸(`열 이름: 값`)을 `첫 칸 | `로 붙인다. 표가 아닌 요소의 겹침은 그대로. `body_sha256`·`chunk_id`는 본문만으로 정해지므로 겹침 변경으로 바뀌지 않는다(임베딩할 `text`만 바뀐다). `section.py`의 겹침 떼기가 이 두 꼴도 처리한다
6. 임베딩할 글자 = `페이지 제목 > 제목 경로` 머리말 + 겹침 + 본문
7. 권한표는 `업무 × 금액 구간` 한 행 = 청크(각주 본문 포함), 이사회 표는 항목마다 청크(열 제목 행 제외). 표 밖 글(`authz_ir.jsonl`)은 쪽과 같은 방식(구조·고정 길이 설정 그대로)으로 자르고 빠짐없음 검사도 같이 한다
8. `python -m backend.rag.ingest.load --manifest` 로 `data/manifest.jsonl`

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 80자 미만 청크 | 남긴다. G3는 전체와 80자 미만 제외(조장 실측 기준) 두 숫자로 보고 |
| EC-02 | 제목만 있고 본문 없는 절 | 청크를 만들지 않는다. 부모 제목이면 하위 절 머리말에 남지만, 형제 절 제목이나 iframe 같은 임베드만 있는 절은 어디에도 남지 않는다(제목 16,842개 중 172개) |
| EC-03 | 다른 쪽에 같은 본문 | 청크는 따로 두고 G3는 본문 지문으로 한 번만 센다 |
| EC-04 | 검토 대기(`review`) 요소 | 청크에서 뺀다(색인 제외, rag4-15) |
| EC-05 | 권한표 행이 0개인 업무(Employee Travel) | 청크 없음. `data/parsed/parse_report.json` 의 `authz.categories` 에 0으로 남는다 |
| EC-06 | 이사회 표 첫 행(항목 칸이 비고 'Board'만 있는 열 제목) | 청크를 만들지 않고 `chunk_report.json` 의 `skipped_board_header` 에 센다. 항목이 비었는데 열 제목이 아니면 멈춘다 |

## How

- 입력: `data/parsed/document_ir.jsonl`, `authz_cells.jsonl`, `authz_board.jsonl`, `authz_notes.jsonl`, `authz_ir.jsonl`, `data/corpus/pages.jsonl`
- 청크 필드: SDD 6장 `Chunk`(`chunk_id, org, rule_seq, rule_title, article, version_id, version_date, fetched_at, kind, text, source_url`, `text_sha256`, `version_date_before`) + `body_sha256` + `seq, header, overlap_chars, element_ids, line_start, line_end, config`
- `text_sha256` = `body_sha256` = 본문(머리말·겹침 제외) sha256. 계약 칸 이름은 `text_sha256`(D0 안건 3-6), `body_sha256` 은 기존 도구(`chunks_index`·벡터 대조)가 쓰는 이름이라 둘 다 둔다. 머리말·겹침이 든 `text` 의 해시가 아니다(`embed.py` 의 `text_sha256` 은 그쪽)
- `kind` 는 `article`(쪽 본문·권한표 표 밖 글)과 `row`(권한표 행·이사회 항목) 두 값만 쓴다. `version_date_before` 는 쪽은 `pages.jsonl` 값을 그대로 넘기고(없으면 `KeyError`), 권한표는 커밋 날짜를 정확히 알아 `False`
- `chunk_id` = sha256(`rule_seq:seq:본문`) 앞 16자(같은 본문이 다른 쪽, 같은 쪽 다른 자리에 있어도 겹치지 않게). 겹침·크기 설정이 달라도 본문과 순서가 같으면 id가 같으니 한 인덱스·DB 테이블에는 설정 하나만 적재한다. G3는 `body_sha256`(머리말·겹침 제외)으로 센다
- 출력: `data/chunks/chunks.jsonl`(본문 포함, 커밋 안 함), `data/chunks_index.jsonl`(번호·위치·지문, 커밋), `data/chunks/chunk_report.json`, `data/manifest.jsonl`(커밋)
- manifest 한 줄 = 문서 하나(현재 1,565줄 = 핸드북 1,564쪽 + 2023 권한표 1). 칸은 `doc_id, org, title, source_url, version_id, collected_at, chunks, chars_original, chars_kept, truncated`와 건너뛴 쪽의 `skipped`(`backend/rag/ingest/load.py` `build_manifest`)다. `version_id`는 그 쪽 판 커밋의 앞 12자이고, 수집 고정 커밋 전체 sha(`129243bcffcf…`)는 manifest가 아니라 스냅샷 안 `collect_manifest.json`과 `data/data.md`에 있다
- 비교용 고정 길이: `--mode fixed --size 800 --overlap 100`(쪽 본문을 이어 붙여 글자 수로)

## AC (Given-When-Then)

**AC-01 · 절을 넘지 않음**
- GIVEN: 두 절에 걸친 요소들
- WHEN: 청킹
- THEN: 어떤 청크도 두 제목 경로의 요소를 함께 담지 않는다

**AC-02 · 요소를 자르지 않음**
- GIVEN: 각각 300자인 요소 3개(크기 800)
- WHEN: 청킹
- THEN: 청크 2개(601자 = 300 + 줄바꿈 + 300, 그리고 300자), 요소가 중간에 잘리지 않는다

**AC-03 · G3는 겹침과 무관**
- GIVEN: 같은 입력
- WHEN: 겹침 0과 120으로 청킹
- THEN: 서로 다른 `body_sha256` 수가 같다

**AC-04 · 머리말은 임베딩 글자에만**
- GIVEN: 제목 경로 `Incident Management > Severities`
- WHEN: 청킹
- THEN: `text` 는 머리말로 시작하고 `body_sha256` 은 머리말 없는 본문의 지문

**AC-05 · 빠짐없음**
- GIVEN: 쪽 전체
- WHEN: 청킹
- THEN: 제목·검토 대기를 뺀 모든 요소 글자가 그 절 청크 본문에 들어 있다

**AC-06 · 판 날짜 "이전" 표시가 청크까지 간다**
- GIVEN: `version_date_before` 가 True/False인 쪽
- WHEN: 구조·고정 길이로 청킹
- THEN: 모든 청크의 `version_date_before` 가 그 쪽 값과 같고, 칸이 없으면 `KeyError` 로 멈춘다

**AC-07 · 권한표**
- GIVEN: 업무 × 금액 구간 칸, 각주, 이사회 표(열 제목 행 포함)
- WHEN: 청킹
- THEN: 업무가 다르면 같은 구간도 다른 행 청크, 채운 칸만 본문에 넣고 쓰인 각주 본문만 붙고(링크는 글자만), 칸이 모두 비면 `no approver listed`, 이사회 열 제목은 청크가 아니라 `skipped_board_header` 로 센다

**AC-08 · 계약 칸**
- GIVEN: 만든 청크 기록
- WHEN: 팀 `Chunk` 모델에 넣음
- THEN: 검증을 통과하고 `text_sha256` 은 본문 해시(`body_sha256`)이며 머리말·겹침이 든 `text` 의 해시가 아니다

**AC-09 · 고정 길이 기준선**
- GIVEN: 검토 대기 요소가 섞인 쪽
- WHEN: `--mode fixed`
- THEN: 청크 본문(겹침 제외)을 이어 붙이면 검토 대기를 뺀 쪽 본문과 같다

**AC-10 · manifest**
- GIVEN: 청크 파일과 `pages.jsonl`
- WHEN: `load --manifest`
- THEN: 문서별 청크 수 합이 청크 수와 같고, 옮겨진 쪽은 `redirect`, 본문 없는 쪽은 `no_body` 로 표시한다
