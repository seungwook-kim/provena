# data/LICENSES/ : 원문 라이선스와 출처

## 이 폴더가 하는 일

`data/corpus/`의 원문은 GitLab 핸드북에서 가져왔다.

- 출처: https://gitlab.com/gitlab-com/content-sites/handbook (고정 커밋 `129243bcffcf6cbc8c2e83f537f1836b99900a61`, 2026-10-27. `data/data.md`와 스냅샷 안 `collect_manifest.json`에 기록)
- 라이선스: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
- 답에 원문을 보일 때는 페이지 URL, 라이선스 링크, 수정 여부를 함께 표시한다.
- 이 프로젝트는 GitLab Inc.와 제휴·보증 관계가 없다. GitLab 로고는 쓰지 않는다.
- 주인: 김승욱

## PDF (`static/pdfs/`, 서비스 색인 전용)

`data/pdf/`의 PDF 7건은 핸드북 고정 커밋 `129243bcffcf`의 `static/pdfs/` 아래 같은 경로 파일이다(`data/pdf/pdf_manifest.json`에 경로·크기·sha256·git blob id). 라이선스는 **미확인**이다. 위 "CC BY-SA 4.0" 표기는 `data/corpus/`의 Markdown 원문에 대한 것이고 이 PDF들에는 확인된 근거가 없어 적용하지 않는다.

- 핸드북 저장소 `LICENSE`는 MIT이며 소프트웨어를 대상으로 하고 PDF나 Creative Commons 문구는 없다.
- GitLab 블로그 "Our handbook is open source, here's why"(2016-07-12, `https://about.gitlab.com/blog/our-handbook-is-open-source-heres-why/`)에 핸드북이 Creative Commons 라이선스라는 문장이 있으나 `static/pdfs/` 파일은 언급하지 않는다.
- 7건 모두 텍스트 층에서 저작권 표시(`©`, `Copyright`, `All rights reserved`)와 Creative Commons 문구를 찾지 못했다. 본문의 `license`라는 낱말은 문서 내용이다.

## 2023 권한표 (`data/corpus/authz/`, `data/parsed/authz_cells.jsonl`)

- 출처 저장소: https://gitlab.com/gitlab-com/www-gitlab-com (위 핸드북 저장소와 다른 옛 저장소)
- 커밋: `0a3de833754144dc4d448814e2edbcaed0883f35` (2023-05-11, `backend/rag/ingest/handbook.py`의 `AUTHZ_COMMIT`)
- 파일: `sites/handbook/source/handbook/finance/authorization-matrix/index.html.md`
- 라이선스: CC BY-SA 4.0. 근거는 같은 커밋의 `sites/handbook/source/handbook/handbook-usage/index.html.md`에 있는 문장 "Our handbook falls under the Attribution-ShareAlike 4.0 International license"다. 확인한 범위는 이 문장까지다. 권한표 파일 자체에는 라이선스 문구가 없고, 같은 커밋의 저장소 최상위에서 `LICENSE`, `LICENSE.md`, `LICENSE.txt`를 찾지 못했다.
- `data/parsed/authz_cells.jsonl`은 이 파일의 표를 `parse_authz()`로 칸 단위 JSON Lines로 바꾼 파생 파일이다. 칸 값은 고치지 않았다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-05 | 김승욱(팀장, Claude Code) | `data/parsed/authz_cells.jsonl`을 커밋 대상으로 바꾸면서 2023 권한표의 출처와 라이선스 근거를 같은 커밋에서 확인해 기록 | #54 |
| 2026-11-03 | 김승욱(팀장, Claude Code) | `static/pdfs/` PDF 7건의 라이선스 근거를 공개 페이지에서 찾았으나 PDF 자체의 라이선스는 찾지 못해 "미확인"으로 기록 | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
