# backend/rag/ingest/ : 수집·파싱·청킹·증분 수집

## 이 폴더가 하는 일

`handbook.py`(고른 절 git 수집, 2023 권한표 판 고정), `history.py`(커밋 이력에서 판 목록), `parse.py`(Markdown·Hugo 단축코드·HTML 표), `chunk.py`(제목 단위, 약 800자, 120자 겹침, 청크 수는 겹침 없이 셈), `diff.py`(커밋 사이 바뀐 섹션), `load.py`(임베딩 적재, manifest), `schedule.py`(증분 수집, 가산 자동화). 수집은 로컬에서 한 번 하고 원문 스냅샷(`snapshot.py`로 `data/corpus.tar.gz` 한 파일)과 manifest를 커밋한다. 원문과 파싱 결과를 3건 이상 대조해 기록한다.

- 주인: 박진형
- 실행: `python -m backend.rag.ingest.handbook` → `python -m backend.rag.ingest.history` (Spec `docs/specs/collect.md`) → `python -m backend.rag.ingest.parse` (Spec `docs/specs/parse.md`) → `python -m backend.rag.ingest.compare`(원문 대조표)
- 파싱 결과 `data/parsed/document_ir.jsonl` 한 줄 = 요소 하나: `element_id, rule_seq, org, kind(heading·paragraph·list_item·table_row·quote·html·code), heading_path, parent_id, order, line_start, line_end(원본 줄, 1부터), text, links, review`. 표 행은 `table_id, row, header, cells` 추가. 청킹(B-3)은 이 형식을 읽는다
- 입력: 핸드북 저장소(고정 커밋)
- 출력: 원문 스냅샷, 청크, 바뀐 섹션 목록(`ChangedArticle`)

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 증분 수집 ② `schedule.py`·`db/202_sync.sql`·`.github/workflows/handbook-sync.yml`(Spec `docs/specs/incremental.md`, 가산 자동화): 슬롯(UTC 날짜)마다 한 번(`sync_runs` 고유 키), 마지막 성공 커밋 → 원천 끝 커밋 비교, 한 트랜잭션으로 새 판 추가·옛 판 `valid_to` 닫기·바뀐 섹션 `changed_articles`(pending) 쌓기, 본문이 같은 청크는 벡터 재사용, 색인 장부 모델이 다르면 원천을 부르기 전에 멈춤, 삭제는 목록이 완전할 때만, 동결일(10/27) 판은 바꾸지 않음. 정시 실행 매일 UTC 18:07, 실패하면 디스코드 알림(Secret 없으면 로그에 '알림 꺼짐'). 테스트 13개(DB 12), 핵심 줄 9곳을 하나씩 깨뜨려 9개 모두 잡음. DB 사본 실제 실행(11/2, UTC 수정 전): 129243bcff → 4b0e803409, 140쪽(목록 완전) 중 서식만 116·본문 24, 바뀐 섹션 89, 새로 임베딩 124·재사용 4,007, 214초, 같은 커밋 다시 실행은 noop, as_of 10/27 청크 집합 반영 전후 같음 | 이 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 증분 수집 ① `diff.py`(Spec `docs/specs/incremental.md`): 두 커밋의 17개 폴더 목록을 경로·blob id로 비교(추가·수정·사라짐·그대로·옮김, 목록 완전성 증거 4개), 바뀐 쪽 파일을 fetch 한 번으로 묶어 받기, 쪽마다 제목 경로별 본문 비교(서식만·제목만 바뀜 짝 찾기, 문턱 0.35는 이력 400커밋의 짝 후보 65쌍으로 실측) → `ChangedArticle`. 10/27→10/30 139쪽 중 서식만 116·본문 23, 링크 정리 커밋 `2666725a9b` 110쪽 중 서식만 107, 리콜 시험 12건 모두 검출(11건 modified, `fc6633cf` 는 섹션 삭제라 removed). 테스트 36개(Docker python:3.12 통과), 변이 17개 모두 잡음. LLM 없음 | 이 PR |
| 2026-11-02 | 박진형 (jinyeong-731, Claude Code) | 판 날짜 UTC(I-011): `handbook.py` `utc_day()`·`commit_day()` — `%cs`(커밋한 사람 시간대) 대신 `%ct`를 UTC 날짜로, `history.py`도 같은 함수. `collect --fetched-at`(같은 고정 커밋을 다시 읽어 판 칸만 고칠 때 처음 받은 날 유지). 다시 수집: 1,564쪽 중 72쪽 `version_date` 하루 이동(이른 쪽 18·늦은 쪽 54), 다른 칸·원문 sha256·`corpus_id`·청크 id·`chunks_index.jsonl`·`manifest.jsonl` 그대로, 개정 이력 6,330건 중 219건 날짜만 이동. 10/27 넘는 판 날짜 1쪽(infrastructure-security) → 0쪽, as_of 2026-10-27에 보이는 청크 23,076 → 23,095. 테스트 `test_version_date_is_utc_not_committer_timezone`(한국 시간 10/28 03:00 커밋 → 10/27), UTC 변환을 +9시간으로 깨뜨리면 실패 확인 | 이 PR |
| 2026-10-31 | 김승욱(팀장) | 원문 스냅샷 압축 `snapshot.py`(pack·unpack·verify·ensure): `data/corpus/`를 `data/corpus.tar.gz` 한 파일로 묶고(같은 원문이면 같은 파일), 풀 때 쪽별·권한표 sha256과 `corpus_id`를 수집 때와 대조, 폴더 밖 경로는 막음. `parse`·`chunk`·`load` 시작 때 기본 위치에 원문이 없으면 자동으로 풂(각 2줄). 고치는 순서는 `data/data.md`. 테스트 `tests/test_ingest_snapshot.py` 5개 | |
| 2026-10-31 | 박진형 (jinyeong-731, Claude Code) | 청킹 `chunk.py`·manifest `load.py`·청크 대조표 `compare.py`(Spec `docs/specs/chunk.md`): 쪽의 요소를 제목 경로(절) 단위로 묶어 800자까지 한 청크로 하고, 긴 요소는 줄→문장→글자로 쪼개며, 같은 절 안에서만 앞 청크 끝 120자를 겹치고, 임베딩 글자 앞에 `쪽 제목 > 절` 머리말을 붙임. 권한표는 업무×금액 구간 한 행=청크(각주 본문 포함)·이사회 표는 항목마다·표 밖 글은 쪽과 같은 방식. 쪽의 `version_date_before`(#18)를 청크까지 넘기고 계약 `text_sha256` 을 채움. 실행 결과: 청크 **23,095**(article 23,048·row 47), 서로 다른 본문 지문 **22,378**(80자 이상만 21,314), 문서 1,512(+권한표), 빠진 요소 0, 겹침 0/120 G3 같음, 기준선 고정 길이 800/100은 15,590. 테스트 20개(일부러 깨뜨린 33개 중 31개를 잡고 나머지 2개는 결과가 같은 변경). 800/120은 잠정값이라 D2 골든셋으로 다시 잼 | |
| 2026-10-31 | 박진형 (jinyeong-731, Claude Code) | 2023 권한표 표 밖 본문 파싱(I-007) `parse.py` `parse_authz_prose()`: 계약 승인 절차·각주 목록·Authorization Matrix Policy 요소 103개를 `authz_ir.jsonl` 로(원문 되찾기 실패 0). 본표·이사회 표의 줄은 빼서 칸과 겹치지 않고, 정책 본문이 없거나 예상 밖 HTML이 있으면 멈춤. 테스트 2개 | #19 |
| 2026-10-30 | 박진형 (jinyeong-731, Claude Code) | 판 날짜 페이지별(I-001) `handbook.py` `last_changes()`: 페이지마다 마지막 커밋의 커밋 날짜(`%cs`), 2023-12-01 뒤로 안 바뀐 25쪽은 `version_date` 2023-12-01·`version_date_before` true(계약 칸, 화면 "2023-12-01 이전")·판은 고정 커밋, 이력을 잘라 받은 경계 커밋은 건너뜀. 판 643종, 다시 수집해 청크 id·본문 그대로(바뀐 칸은 판 칸뿐), 잘린 캐시·전체 캐시 결과 같음(1,564쪽 중 다른 쪽 0) | #18 |
| 2026-10-29 | 박진형 (jinyeong-731) | 원문 대조 3건(`compare.py` 대조표, GitLab 같은 판 줄 링크): 장애 대응 쪽 15요소, 표 많은 쪽 15요소, 2023 권한표 글자 있는 71칸 — 전부 일치 | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | `parse.py`: 1,561쪽 → 요소 85,388개(원본 줄 되찾기 실패 0, 처음 보는 단축코드 0), 권한표 9종 33행 363칸(역할 주석 대조 불일치 0, 글자 71칸), 이사회 15행, 각주 6. `compare.py` 원문 대조표. 파서는 PRD 9장대로 markdown-it-py·beautifulsoup4+lxml(표본 20쪽 비교로 확인). HTML 엔진을 기본 엔진에서 lxml로 바꾸자 깨진 HTML 표 1쪽이 바로잡힘(요소 85,389→85,388, 그 쪽 말고 차이 0). 비공개 링크만 있는 표 칸 9개 표시(`private_cells`, PRD 8장). 원문 대조는 EVAL_REPORT 1장 | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 권한표 파싱 `parse.py` `parse_authz()`: 2023 권한표 본표·이사회 표·각주, 칸마다 역할 주석과 열 이름 대조(다르면 멈춤), 금액 구간 끊김 보고와 테스트 | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | Markdown → 요소 `parse.py` `parse_page()`: markdown-it-py로 제목·문단·목록·표 행·코드·HTML 표를 요소로(원본 줄 번호·제목 경로 포함), 원본 되찾기 검사 `found_in_source()`와 테스트. 의존성 2줄 `backend/requirements.txt` | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 단축코드 전처리 `parse.py` `preprocess()`: Hugo 단축코드를 4가지(감싸기·이름·링크·데이터)로 나눠 정리, 줄 수는 바꾸지 않음, 모르는 단축코드는 지우지 않음과 테스트. Spec `docs/specs/parse.md` | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 개정 이력 기간을 "최근 12개월" → 2024-01-01부터로 넓힘(팀 리콜 시험 12건 중 4건이 빠져 있었음). 핸드북 커밋 6,332건, 12건 모두 있음 확인 검사·테스트 추가. 수집 원문은 그대로(corpus_id 같음) | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | `handbook.py`(고른 17개 폴더 1,564쪽, 고정 커밋 129243bc, 2023 권한표 API 1회)·`history.py`(핸드북 커밋 1,666건, 권한표 커밋 36건)·`tests/test_ingest_handbook.py` 18개. 1,564쪽 전부 git 원본과 바이트 대조 불일치 0, 두 번 실행 corpus_id 같음 | PR 전 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | git 원본 받기·저장 `handbook.py` `collect()`: 고른 폴더만 받고, 작업 폴더가 아니라 git 원본 바이트로 읽어 blob id 대조, 저장 후 다시 읽어 지문 대조, `pages.jsonl`·`collect_manifest.json` 기록과 테스트 (PR 2/7) | #7 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 수집 규칙 `handbook.py`: 고른 절 11개(17개 폴더)·고정 커밋, 페이지 id·URL·front matter, 쪽 수 검사(1,564쪽이 아니거나 빈 절·빈 파일이면 멈춤)와 테스트. Spec `docs/specs/collect.md`. 팀 300줄 규칙에 맞춰 수집·파싱을 PR 7개로 나눈 1번 | #5 |
| 2026-10-29 | 박진형 (jinyeong-731, Claude Code) | 페이지 id(`rule_seq`) 경로 해시 앞 15자 → 8자(18자리 → 최대 10자리, PR #5 리뷰). 1,564쪽 충돌 0, 다시 수집·파싱·청킹해 청크 내용·순서가 id 말고 모두 같음을 확인 | #6 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
| I-008 | 2026-10-31 | 박진형 | 이사회 표 첫 행(항목 칸이 비고 열 제목 'Board'만 있음)이 항목처럼 읽혀 본문이 `: Board` 인 청크가 1개 생김 | 뜻 없는 청크 1개가 G3 숫자와 검색에 섞이고, 뒤 이사회 청크 14개의 순번이 하나씩 밀림 | 박진형 | 해결 | 2026-10-31 | 원문 483~485줄(첫 칸 `grid-empty`, 둘째 `<b>Board</b>`). `authz_chunks` 가 건너뛰고 `chunk_report.json` 의 `skipped_board_header` 에 세며, 항목이 비었는데 열 제목이 아니면 멈춘다. `test_authz_rows_notes_and_board`·`test_authz_board_row_without_item_but_not_a_header_stops` |
| I-007 | 2026-10-29 | 박진형 | 2023 권한표 파일에서 표 칸만 읽고 표 밖 글(각주 목록·Authorization Matrix Policy 등 103요소)을 버림 | 골든셋 초안 R15(각주 6 CUD 승인)·R25(계약 쪼개기 금지) 정답이 코퍼스에 없어 어떤 검색으로도 못 찾음 | 박진형 | 해결 | 2026-10-31 | 골든셋 정답을 청크에 연결하다 발견. `parse_authz_prose` + 테스트 2개(변이 2/2 잡음), 표 밖 요소 103개 원문 되찾기 실패 0 |
| I-002 | 2026-10-29 | 박진형 | 내용 없이 "다른 곳으로 옮김"(`redirect_to`)만 있는 페이지 3쪽 | 빈 청크·잘못된 인용 | 박진형 | 해결 | 2026-10-29 | `parse.py` 가 건너뛰고 `parse_report.json` `skipped_redirect` 에 3쪽 기록 |
| I-004 | 2026-10-29 | 박진형 | 권한표 원문 'Non Billable Expenses' 금액 구간이 `Up to $5K` → `>$5K` → `>$50K` 로 겹침(>$5K의 끝이 없음) | 결정표가 $5K~$50K 사이를 어느 칸으로 볼지 원문만으론 못 정함 | 김승욱 (결정표) | 열림 | | 원문 그대로임(파서 오류 아님). `parse_report.json` `band_gaps` |
| I-006 | 2026-10-29 | 박진형 | 리콜 시험 커밋 `6baed99c`(장애 리뷰 기한)가 고른 폴더 밖 `engineering/root-cause-analysis.md` 도 고침 | 리콜 시연 때 바뀐 규칙의 절반만 코퍼스에 있음 | 김승욱 (리콜) | 열림 | | 고른 폴더 안 `infrastructure-platforms/incident-review.md` 변경은 이력에 있음 |
| I-005 | 2026-10-29 | 박진형 | 개정 이력이 최근 12개월뿐이라 팀 리콜 시험 커밋 12건 중 4건(2024-01-23 2건, 2024-10-18, 2025-09-19) 누락 | 리콜 시험 데이터 부족 | 박진형 | 해결 | 2026-10-29 | 기간 2024-01-01부터, `missing_recall` 검사 + `test_missing_recall_commits_detected`, 실행 결과 12건 모두 있음 |
| I-003 | 2026-10-29 | 박진형 | 팀 레포 `.gitignore` 의 `build/` 때문에 핸드북 폴더 `engineering/infrastructure-platforms/gitlab-delivery/build/` 13쪽이 git에 안 잡힘 | 커밋하면 1,564쪽 중 13쪽이 조용히 빠짐(평가자 재현 실패) | 김승욱 (PR #8) | 해결 | 2026-10-30 | PR #8: `.gitignore` 에 `!data/corpus/**/build/`, `.gitattributes` 에 `data/corpus/** -text`(1,564쪽 시험, decisions.md 2026-10-30) |
| I-001 | 2026-10-29 | 박진형 | 판 날짜(`version_date`)가 모든 페이지에서 수집 커밋 날짜 2026-10-27 하나 | 답에 "○월 ○일판" 인용 시 오래된 페이지도 10/27판으로 보임 | 박진형 | 해결 | 2026-10-30 | decisions.md 2026-10-30: 페이지마다 그 페이지의 마지막 수정 커밋 날짜로 둔다(PR #7 리뷰). 조장 답(10/30): 커밋 날짜(`%cs`), 2023-12-01 뒤로 안 바뀐 페이지는 이력을 더 받지 않고 "2023-12-01 이전" → 1,564쪽 중 25쪽, 계약 `Chunk.version_date_before`(PR #17)로 표시, 판은 고정 커밋 |
