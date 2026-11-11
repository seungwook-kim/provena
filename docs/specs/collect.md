# Spec — 핸드북 수집과 개정 이력 (박진형, 업무 분담 B-1)

## Why

- **페르소나**: 이 저장소를 받은 평가자, 그리고 원문을 받아 쓰는 우리 조의 다음 단계(파싱·청킹·리콜)
- **상황**: 핸드북은 매일 고쳐진다. 받을 때마다 원문이 다르면 평가셋 정답과 청크 수가 흔들린다.
- **문제**:
  1. 같은 명령으로 다시 받아도 같은 원문이 나와야 한다(재현).
  2. 2023 승인 권한표는 지금 핸드북에서 비공개로 옮겨져 옛 저장소의 고정 커밋에만 있다.
  3. 리콜(F-02) 시험에는 "언제 어떤 페이지가 바뀌었나" 목록이 필요하다.
- **측정 지표**: 고른 절 쪽수(조장 실측 1,564쪽과 일치 여부), 저장 후 다시 읽은 파일의 지문 일치 수

## Goal

- **해결 목표**: 고정 커밋의 고른 17개 폴더(11개 절) 원문과 2023 권한표 1개 파일을 `data/corpus/`에 원본 그대로 받고, 수집 조건을 영수증(`collect_manifest.json`)으로 남긴다.
- **성공 기준**: 페이지 1,564쪽(다르면 멈춤) / 저장 후 다시 읽은 sha256이 git 원본과 100% 일치 / 권한표 sha256이 GitLab 응답 헤더 `x-gitlab-content-sha256`과 일치 / 같은 명령 두 번 실행 시 `corpus_id` 동일
- **Out of Scope**: 파싱·Hugo 단축코드 제거(B-2 `parse.py`), 청킹·`data/manifest.jsonl`(B-3), 증분 수집·바뀐 섹션 찾기(B-5 `diff.py`·`schedule.py`), "답을 바꾸는 개정"인지 고르기(사람)

## What

**Happy Path**
1. `python -m backend.rag.ingest.handbook` 실행
2. 핸드북 저장소를 캐시 폴더에 받는다(파일 내용 없이 2023-12-01 이후 이력만, 그다음 고른 폴더만 내용 받기)
3. 고정 커밋 `129243bc`의 고른 폴더에서 `.md` 목록을 만들고, git 원본 바이트를 그대로 `data/corpus/handbook/`에 쓴다
4. 페이지마다 이름표(절, 페이지 id, 제목, 원문 URL, 판, 판 날짜, 수집일, sha256, 글자 수, 이동 안내 여부)를 `pages.jsonl`에 쓴다
5. 권한표 1개 파일을 GitLab API로 받아 `data/corpus/authz/`에 쓴다
6. 쓴 파일을 다시 읽어 지문을 대조하고 영수증을 쓴다
7. `python -m backend.rag.ingest.history` 로 개정 이력 후보 목록을 쓴다

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 쪽수가 1,564와 다름 | 멈추고 절별 쪽수를 출력 (경로를 짐작해 고치지 않는다) |
| EC-02 | 0바이트 파일, 0쪽인 절 | 멈춤 |
| EC-03 | 권한표 응답이 200이 아님, 빈 본문, 지문 불일치, 제목이 다름 | 멈춤 (재시도하지 않는다. 1회 요청) |
| EC-04 | Windows 줄바꿈 변환(autocrlf)으로 작업 폴더 파일이 CRLF | 작업 폴더가 아니라 git 원본(blob)에서 읽는다 |
| EC-05 | 대문자가 섞인 경로(`billing-ops-GPO`) | URL은 소문자로 만든다(실제 사이트에서 대문자 404, 소문자 200 확인) |
| EC-06 | 다른 곳으로 옮겨진 페이지(`redirect_to`) 3쪽 | 받기는 하고 `redirect_to`에 표시 (파싱 단계에서 뺄지 정함) |
| EC-07 | 제목이 `Title:`(대문자)인 페이지 | 대소문자 구분 없이 읽는다 |
| EC-08 | 리콜 시험 커밋 12건 중 이력에 없는 것 | 멈추고 캐시 이력을 더 받는 명령을 알려 준다 |

## How

- 핸드북: `https://gitlab.com/gitlab-com/content-sites/handbook.git`, 고정 커밋 `129243bcffcf6cbc8c2e83f537f1836b99900a61`(2026-10-27). 고른 폴더는 `handbook.py`의 `SECTIONS` (조장 확인 2026-10-28)
- 받는 법: `git clone --filter=blob:none --no-checkout --shallow-since=2023-12-01` → `git sparse-checkout set --no-cone <폴더>` → `git checkout --detach <커밋>` → `git ls-tree`·`git cat-file --batch`로 원본 읽기
- 권한표: GitLab API `repository/files/.../raw?ref=0a3de833754144dc4d448814e2edbcaed0883f35`, User-Agent 표시, timeout 30초, 1회
- 페이지 id(`rule_seq`): 페이지 경로 sha256 앞 8자리 16진수 → 정수, 최대 10자리 (SDD 11-1 3-1 추천안, D0 확정 전 잠정). 15자리(18자리 정수)는 길다는 리뷰(PR #5)로 줄임 — 1,564쪽 실측 충돌 0, 계산상 충돌 확률 0.03%(5,000쪽 0.3%), 겹치면 수집이 멈춘다(`collect()` 중복 검사). DB 테이블에서는 `bigint`로 둔다(최댓값 4,294,967,295가 `integer` 최댓값 2,147,483,647을 넘음)
- 판(`version_id`): **페이지마다** 그 페이지를 마지막으로 고친 커밋의 sha 앞 12자리. 판 날짜(`version_date`): 그 커밋의 **커밋 날짜를 UTC로 센 날**(git `%ct` 초 → UTC 날짜). `%cs` 는 커밋한 사람 시간대의 날짜라 고정 커밋(UTC 10/27)보다 하루 늦은 날이 찍혀 `as_of` 2026-10-27 검색에서 빠지는 쪽이 생겼다(I-011, 1,564쪽 중 72쪽이 하루 다름, 청크 있는 쪽은 68쪽·1,005청크). 개정 이력(`history.py`)과 증분 수집(`schedule.py`)의 날짜도 같은 기준. 2023-12-01 뒤로 안 바뀐 페이지는 이력을 더 받지 않고 `version_date = "2023-12-01"`, `version_date_before = true`(계약 `Chunk.version_date_before`, 화면 "2023-12-01 이전"), `version_id` 는 마지막 수정 커밋을 모르므로 내용을 읽은 고정 커밋 sha 앞 12자리(계약상 비울 수 없음). 이력을 잘라 받은 경계 커밋은 모든 파일을 새로 추가한 것처럼 보이므로 마지막 수정으로 치지 않는다. I-001, 10/30 조장 결정(decisions.md 페이지별, 커밋 날짜·"이전" 표시는 조장 답). 한 커밋이 여러 페이지를 고치면 version_id가 같으므로 판은 `rule_seq` + `version_id` 로 구별한다
- 알려진 차이: 핸드북 사이트 "Last modified"는 작성일(Hugo `:git` = author date)이라 커밋 날짜와 1,564쪽 중 53쪽이 1~18일 다르다. `version_date_before = true` 인 판은 정확한 날을 모르므로 `as_of` 비교는 "그 날짜 이전 어느 날"로 다뤄야 한다
- 한계: 1,564쪽 중 499쪽(32%)은 마지막 수정이 100파일 넘게 바꾼 일괄 커밋(공백 제거·이름 변경·조직 개편)이다. 판 날짜는 "정책 내용이 바뀐 날"이 아니라 "글자가 마지막으로 바뀐 날"이다
- 출력: `data/corpus/handbook/**`, `data/corpus/authz/authorization-matrix-2023-05.html.md`, `data/corpus/pages.jsonl`, `data/corpus/collect_manifest.json`, `data/corpus/history/*.jsonl`
- 커밋: 위 출력 폴더는 커밋하지 않고 `python -m backend.rag.ingest.snapshot pack`으로 만든 `data/corpus.tar.gz` 한 파일을 커밋한다. 풀 때 쪽별·권한표 sha256과 `corpus_id`를 이 수집 결과와 대조한다(`backend/rag/ingest/snapshot.py`, 고치는 순서는 `data/data.md`)
- 개정 이력: `git log --no-merges --no-renames --name-status` (이름 바뀜 탐지는 파일 내용을 받아야 해서 끈다). 옵션 `python -m backend.rag.ingest.history --follow-renames`(F-11)는 `-M` 으로 읽어 옮긴 파일을 `R100` 상태와 `old_path` 로 남긴다(기본 꺼짐이라 `handbook_commits.jsonl` 은 그대로, 느림). 고른 폴더 밖에서 옮겨 온 파일은 경로 제한 때문에 추가(A)로 보이고, 판 날짜(`handbook.last_changes`)는 옮긴 커밋이 마지막 수정인 채 `--no-renames` 그대로다, **2024-01-01부터** 고정 커밋까지. 팀 리콜 시험 커밋 12건(`study`의 참고 URL 2장, 가장 오래된 것 2024-01-23)이 모두 있어야 하고 하나라도 없으면 멈춘다. (처음엔 주제서 초안의 "최근 12개월"이라 4건이 빠졌음, 10/29 수정) 권한표 이력은 API commits(`path`), 요청 간격 1초, 최대 20쪽

## AC (Given-When-Then)

**AC-01 · 고정 판 재현**
- GIVEN: 캐시가 없는 PC
- WHEN: 수집을 두 번 실행
- THEN: 두 번 모두 1,564쪽, `corpus_id` 같음

**AC-02 · 쪽수 불일치면 멈춤**
- GIVEN: 기대 쪽수와 다른 페이지 목록
- WHEN: 검사
- THEN: `CollectError`, 절별 쪽수가 메시지에 들어 있음

**AC-03 · 원본 그대로 저장**
- GIVEN: 수집 완료
- WHEN: 저장한 파일을 다시 읽음
- THEN: git blob 해시가 `git ls-tree` 값과 모두 같음

**AC-04 · 권한표 응답 검증**
- GIVEN: 상태 404, 빈 본문, 헤더 지문 불일치 중 하나
- WHEN: 권한표 받기
- THEN: `CollectError`

**AC-05 · URL 규칙**
- GIVEN: `content/handbook/finance/accounting/finance-ops/billing-ops-GPO/_index.md`
- WHEN: URL 만들기
- THEN: `https://handbook.gitlab.com/handbook/finance/accounting/finance-ops/billing-ops-gpo/`
