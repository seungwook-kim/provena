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

- **해결 목표**: 원문을 요소 단위 중간 표현(`document_ir.jsonl`)과 권한표 칸 목록(`authz_cells.jsonl`)으로 바꾸고, 무엇을 지웠고 무엇을 못 했는지 기록한다.
- **성공 기준**: 처음 보는 단축코드 0종(있으면 그 쪽은 검토 대기) / 요소 원문 되찾기 실패 0 / 권한표 363칸 역할 주석 불일치 0 / 금액 구간 끊김은 실패가 아니라 목록으로 보고
- **Out of Scope**: 청킹·청크 수(B-3), include 26곳 끌어오기(데이터카드에 기록), 결정표 만들기(F-04), 이모지를 그림 글자로 바꾸기

## What

**Happy Path**
1. `python -m backend.rag.ingest.parse`
2. 페이지마다: front matter와 단축코드를 **줄 수를 바꾸지 않고** 정리 → markdown-it-py(CommonMark + table)로 토큰화
3. 블록마다 요소 하나: 제목·문단·목록 항목(최상위)·표 행·코드·HTML 표 행·HTML 문단. 요소에 제목 경로·부모 제목·순서·원본 줄 범위를 붙인다
4. 권한표: BeautifulSoup으로 본표(`div.grid-auth-matrix`) 363칸, 이사회 표(`div.treasury-auth-matrix`), 각주 (1)~(6)
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
- 출력 `data/parsed/`(저장소에 커밋하지 않음, 원문에서 다시 만든다): `document_ir.jsonl`, `authz_cells.jsonl`, `authz_board.jsonl`, `authz_notes.jsonl`, `parse_report.json`
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
