# data/LICENSES/ : 원문 라이선스와 출처

## 이 폴더가 하는 일

`data/corpus/`의 원문은 GitLab 핸드북에서 가져왔다.

- 출처: https://gitlab.com/gitlab-com/content-sites/handbook (고정 커밋 `129243bcffcf6cbc8c2e83f537f1836b99900a61`, 2026-10-27. `data/data.md`와 스냅샷 안 `collect_manifest.json`에 기록)
- 라이선스: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
- 답에 원문을 보일 때는 페이지 URL, 라이선스 링크, 수정 여부를 함께 표시한다.
- 이 프로젝트는 GitLab Inc.와 제휴·보증 관계가 없다. GitLab 로고는 쓰지 않는다.
- 주인: 김승욱

## PDF (`static/pdfs/`, 서비스 색인 전용)

`data/pdf/`의 PDF 7건은 핸드북 고정 커밋 `129243bcffcf`의 `static/pdfs/` 아래 같은 경로 파일이다(`data/pdf/pdf_manifest.json`에 경로·크기·sha256·git blob id). 라이선스는 **PDF를 직접 지목한 근거가 없다**(2026-11-12 재확인, 아래 "2026-11-12 확인"). 위 "CC BY-SA 4.0" 표기는 `data/corpus/`의 Markdown 원문에 대한 것이고 이 PDF들에는 확인된 근거가 없어 적용하지 않는다.

- 핸드북 저장소 `LICENSE`는 MIT이며 소프트웨어를 대상으로 하고 PDF나 Creative Commons 문구는 없다.
- GitLab 블로그 "Our handbook is open source, here's why"(2016-07-12, `https://about.gitlab.com/blog/our-handbook-is-open-source-heres-why/`)에 핸드북이 Creative Commons 라이선스라는 문장이 있으나 `static/pdfs/` 파일은 언급하지 않는다.
- 7건 모두 텍스트 층에서 저작권 표시(`©`, `Copyright`, `All rights reserved`)와 Creative Commons 문구를 찾지 못했다. 본문의 `license`라는 낱말은 문서 내용이다.

### 2026-11-12 확인 (F-16, 박진형, 접근일 2026-11-12)

확인된 사실(원문 인용)

- 핸드북 사용 안내(현재 사이트 https://handbook.gitlab.com/handbook/about/handbook-usage/ , 2023-05-11 옛 저장소 `0a3de833`의 같은 문서 `index.html.md:303`에도 같은 문장): "Our handbook falls under the Attribution-ShareAlike 4.0 International license." (링크 https://creativecommons.org/licenses/by-sa/4.0/). 대상은 "handbook"이라고만 쓰여 있고 `static/` 자산이나 PDF를 따로 언급하지 않는다.
- 핸드북 사이트 맨 아래 문구(https://handbook.gitlab.com/ 의 HTML footer): "© 2026 GitLab All Rights Reserved". 라이선스 링크는 없다. 위 CC BY-SA 문장과 문구가 어긋난다.
- 핸드북 저장소 `LICENSE`(고정 커밋 `129243bc`, https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/129243bcffcf6cbc8c2e83f537f1836b99900a61/LICENSE): "Copyright (c) 2011-present GitLab B.V. / With regard to the GitLab Software: Permission is hereby granted..." (MIT). 끝에 "For all third party components incorporated into the GitLab Software ... those components are licensed under the original license provided by the owner of the applicable component." 문서·콘텐츠·Creative Commons·PDF는 언급이 없다. 같은 저장소 `README.md`에도 라이선스 문장이 없다.
- 사용처: PDF 7건은 `backend/rag/ingest/pdf.py` `SOURCES`(31행 이후)로 파싱만 하고 산출물(`pdf_ir.jsonl`, `pdf_chunks.jsonl`)은 저장소에 커밋하지 않는다(`docs/specs/parse.md:118`). 임베딩·DB 적재는 하지 않았다(`backend/rag/ingest/ingest.md:23`). 저장소에 올라간 것은 원본 PDF 7건과 `pdf_manifest.json`이다(`data/data.md:26`).
- 본문 첫 쪽 확인(pdftotext): 6건은 GitLab 소개·내부 자료 성격, `customer_dpa_5_1_26.pdf`는 "GitLab Data Processing Addendum"이라는 GitLab의 고객 계약 부속서다. 7건 모두 텍스트에 `©`·`Copyright`·Creative Commons 문구가 없다(위 항목).

추정(확인 못 한 것)

- "handbook"에 PDF가 포함된다는 해석은 추정이다. PDF를 직접 지목한 문장을 찾지 못했다.
- 6건의 저자가 GitLab 직원이라는 점은 파일 위치(`static/pdfs/`)와 내용에서 짐작한 것이며, `git-cheat-sheet.pdf`의 저자와 PDF 속 이미지·글꼴의 제3자 권리는 확인하지 못했다.
- 고정 커밋 이후 핸드북이 라이선스를 바꿨는지, 저작권 담당(GitLab Legal)에 문의하면 어떻게 답하는지는 확인하지 않았다.

PDF별 판정

| PDF | 판정 | 근거 | 권고 |
|---|---|---|---|
| `gitlab-customer-journey.pdf` | 근거 약함(핸드북 전체 문장만) | 핸드북 사용 안내의 CC BY-SA 4.0 문장. PDF를 지목하지 않음, footer는 All Rights Reserved | 팀 결정 전까지 유지. 근거가 PDF를 지목하지 않아 CC BY-SA 4.0을 적용했다고 쓰지 않는다. 유지하기로 하면 출처 URL 표시 |
| `gitlab_customer_success_capabilities_roadmap.pdf` | 근거 약함 | 위와 같음 | 유지(같은 조건) |
| `industry-ai-governance-question-bank.pdf` | 근거 약함 | 위와 같음 | 유지(같은 조건) |
| `Incident_Response_Flow_SecOpsEngineer.pdf` | 근거 약함 | 위와 같음 | 유지(같은 조건) |
| `Persona_SecOpsEngineer.pdf` | 근거 약함 | 위와 같음 | 유지(같은 조건) |
| `git-cheat-sheet.pdf` | 근거 없음(저자 미확인) | 저작권 표시·저자 표시를 PDF에서 찾지 못함 | 저장소에서 빼고 manifest만 남김 |
| `customer_dpa_5_1_26.pdf` | 근거 없음(법률 계약 문서) | 핸드북 문장은 일반 문서 기준이며 계약서 재배포를 허용한다는 말이 없음 | 저장소에서 빼고 manifest만 남김 |

- 가장 보수적인 선택은 7건 모두 빼고 manifest(경로·sha256·`source_url`)만 남기는 것이다. `collect --download`로 언제든 같은 파일을 다시 받을 수 있다(`docs/specs/parse.md:95`).
- 파일을 빼거나 옮기는 것은 팀 결정이다. 이 문서는 파일을 지우지 않았다.

## 2023 권한표 (`data/corpus/authz/`, `data/parsed/authz_cells.jsonl`)

- 출처 저장소: https://gitlab.com/gitlab-com/www-gitlab-com (위 핸드북 저장소와 다른 옛 저장소)
- 커밋: `0a3de833754144dc4d448814e2edbcaed0883f35` (2023-05-11, `backend/rag/ingest/handbook.py`의 `AUTHZ_COMMIT`)
- 파일: `sites/handbook/source/handbook/finance/authorization-matrix/index.html.md`
- 라이선스: CC BY-SA 4.0. 근거는 같은 커밋의 `sites/handbook/source/handbook/handbook-usage/index.html.md`에 있는 문장 "Our handbook falls under the Attribution-ShareAlike 4.0 International license"다. 확인한 범위는 이 문장까지다. 권한표 파일 자체에는 라이선스 문구가 없고, 같은 커밋의 저장소 최상위에서 `LICENSE`, `LICENSE.md`, `LICENSE.txt`를 찾지 못했다.
- `data/parsed/authz_cells.jsonl`은 이 파일의 표를 `parse_authz()`로 칸 단위 JSON Lines로 바꾼 파생 파일이다. 칸 값은 고치지 않았다.

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-12 | 박진형 (jinyeong-731) | F-16: `static/pdfs/` PDF 7건 재배포 근거 확인. 핸드북 사용 안내의 CC BY-SA 4.0 문장은 PDF를 지목하지 않고 사이트 footer는 All Rights Reserved. PDF별 판정표 추가, 파일은 그대로 둠 | 미정 |
| 2026-11-05 | 김승욱(팀장, Claude Code) | `data/parsed/authz_cells.jsonl`을 커밋 대상으로 바꾸면서 2023 권한표의 출처와 라이선스 근거를 같은 커밋에서 확인해 기록 | #54 |
| 2026-11-03 | 김승욱(팀장, Claude Code) | `static/pdfs/` PDF 7건의 라이선스 근거를 공개 페이지에서 찾았으나 PDF 자체의 라이선스는 찾지 못해 "미확인"으로 기록 | |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
