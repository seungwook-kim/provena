# backend/rag/ingest/ : 수집·파싱·청킹·증분 수집

## 이 폴더가 하는 일

`handbook.py`(고른 절 git 수집, 2023 권한표 판 고정), `history.py`(커밋 이력에서 판 목록), `parse.py`(Markdown·Hugo 단축코드·HTML 표), `chunk.py`(제목 단위, 약 800자, 120자 겹침, 청크 수는 겹침 없이 셈), `diff.py`(커밋 사이 바뀐 섹션), `load.py`(임베딩 적재, manifest), `schedule.py`(증분 수집, 가산 자동화). 수집은 로컬에서 한 번 하고 원문 스냅샷과 manifest를 커밋한다. 원문과 파싱 결과를 3건 이상 대조해 기록한다.

- 주인: 박진형
- 실행: `python -m backend.rag.ingest.handbook` → `python -m backend.rag.ingest.history` (Spec `docs/specs/collect.md`)
- 입력: 핸드북 저장소(고정 커밋)
- 출력: 원문 스냅샷, 청크, 바뀐 섹션 목록(`ChangedArticle`)

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
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
| I-004 | 2026-10-29 | 박진형 | 권한표 원문 'Non Billable Expenses' 금액 구간이 `Up to $5K` → `>$5K` → `>$50K` 로 겹침(>$5K의 끝이 없음) | 결정표가 $5K~$50K 사이를 어느 칸으로 볼지 원문만으론 못 정함 | 김승욱 (결정표) | 열림 | | 원문 그대로임(파서 오류 아님). `parse_report.json` `band_gaps` |
| I-006 | 2026-10-29 | 박진형 | 리콜 시험 커밋 `6baed99c`(장애 리뷰 기한)가 고른 폴더 밖 `engineering/root-cause-analysis.md` 도 고침 | 리콜 시연 때 바뀐 규칙의 절반만 코퍼스에 있음 | 김승욱 (리콜) | 열림 | | 고른 폴더 안 `infrastructure-platforms/incident-review.md` 변경은 이력에 있음 |
| I-005 | 2026-10-29 | 박진형 | 개정 이력이 최근 12개월뿐이라 팀 리콜 시험 커밋 12건 중 4건(2024-01-23 2건, 2024-10-18, 2025-09-19) 누락 | 리콜 시험 데이터 부족 | 박진형 | 해결 | 2026-10-29 | 기간 2024-01-01부터, `missing_recall` 검사 + `test_missing_recall_commits_detected`, 실행 결과 12건 모두 있음 |
| I-003 | 2026-10-29 | 박진형 | 팀 레포 `.gitignore` 의 `build/` 때문에 핸드북 폴더 `engineering/infrastructure-platforms/gitlab-delivery/build/` 13쪽이 git에 안 잡힘 | 커밋하면 1,564쪽 중 13쪽이 조용히 빠짐(평가자 재현 실패) | 김승욱 (PR #8) | 해결 | 2026-10-30 | PR #8: `.gitignore` 에 `!data/corpus/**/build/`, `.gitattributes` 에 `data/corpus/** -text`(1,564쪽 시험, decisions.md 2026-10-30) |
| I-001 | 2026-10-29 | 박진형 | 판 날짜(`version_date`)가 모든 페이지에서 수집 커밋 날짜 2026-10-27 하나 | 답에 "○월 ○일판" 인용 시 오래된 페이지도 10/27판으로 보임 | 박진형 | 진행 중 |  | decisions.md 2026-10-30: 페이지마다 그 페이지의 마지막 수정 커밋 날짜로 둔다(PR #7 리뷰) |
