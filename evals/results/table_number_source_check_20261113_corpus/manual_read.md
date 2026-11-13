# 전체 청크 표본 30개를 원문과 나란히 놓고 읽은 기록 (2026-11-13)

읽은 쪽: Claude Code(김승욱 작업 세션). 팀원이 다시 읽어 확인한 것은 아직 없다.
표본: 선정 대상 4,319개 중 무작위 30개. 시드 `20261113`, 표 청크 20개(풀 1,892개) + 수치 문단 청크 10개(풀 2,427개). 목록은 `sample.json`.
방법: `check_corpus.py`가 청크 글과 스냅샷 `data/corpus.tar.gz` 원문의 `line_start`~`line_end` 줄(겹침 조각의 원 줄 포함)을 `sample_side_by_side.txt`로 나란히 출력했고, 행마다 칸 값과 순서를 눈으로 맞췄다. HTML 표는 표 머리 행과 이 청크의 행만 원문 쪽에 뽑았다.
추가 대조: 표본 30개의 원문 쪽(공개 주소)을 GET으로 1.5초 간격 1회씩 받아 현재 쪽 글에 같은 값이 있는지 봤다(`sample_current_page.json`): 30개 모두 일치. 현재 쪽 대조는 스냅샷이 아닌 지금 쪽이므로 보조 확인이다.

## 결과

30개 모두 행 수, 행 순서, 칸 값이 원문과 같았다. 값이 바뀐 곳은 없었다. 아래 "관찰"은 값 오류가 아니라 청크 구조 때문에 눈에 띈 것이다.

### 표 청크 20개

| 청크 id | 원문 (줄) | 본 것 | 결과 |
|---|---|---|---|
| `2ec7d538b0feacd1` | `security/security-observations-risk-management.md` 238~255 | 위험 등급별 검토 주기 4행(Critical 6개월, High 12개월, Medium 18개월, Low 24개월) | 일치. 관찰: 뒤 목록 1~6번이 번호 없는 `-` 목록으로 바뀜 |
| `04ca31de1e4a75b0` | `engineering/infrastructure-platforms/environments/_index.md` 80~85 | Production-Canary 1행 7칸(gprd-cny, gitlab.com 등) | 일치 |
| `e91fc6ad680a2252` | `engineering/development/sec/delineate-sec.md` 16~22 | 7행. `{{< member-by-gitlab "abellucci" >}}`가 `PM: abellucci`로 풀림, 17행의 빈 PM 칸은 생략 | 일치 |
| `1f5a1d09537d1c59` | `engineering/ai/ai-core-infra/_index.md` 18~22 | 1행(Ashraf Khamis, Senior Technical Writer) | 일치 |
| `66a01030d737d3d3` | `engineering/devops/verify/pipeline-authoring/_index.md` 21~23 | 3행(팀 핸들, 슬랙 채널, 엔지니어 핸들) | 일치. 21행은 원문이 `\|GitLab`처럼 공백 없이 시작 |
| `fef711e65284bfbb` | `support/knowledge-base/article-creation-workflow.md` 96~107 | 5행(Break/Fix, FAQ, How-To, Process, Troubleshooting)과 템플릿 파일명 | 일치 |
| `b36c530f2a21a296` | `security/corporate/systems/_index.md` HTML 표 블록 24~1153(이 청크의 행은 1084~1131) | SentinelOne, Slack 2행의 칸 값, 배지 글(ADMIN SSO, USER SSO 등) | 일치. 관찰: 겹침 106자가 앞 행(sandbox-cloud) 중간에서 시작 |
| `fce0c6356ff3e96f` | `engineering/devops/create/code-review/frontend.md` 58~59 | 2행(2019, 2023-09)과 Tech Lead `—` | 일치 |
| `026d7ffe989a4f89` | `support/amer.md` 114~121, 겹침 119자 | 휴일 8행의 날짜, 요일, 지역, 목표 근무율(55%, 47%, 15%, 15%, 21%, 15%, 15%, 65%) | 일치. 관찰: 맨 앞이 `64%`뿐이다. 그 행(Thanksgiving Canada, 2026-10-12, Mon, US + Canada)의 앞 4칸이 이 청크에 없다. 바로 뒤 Remembrance Day 행(62%)은 온전히 들어옴 |
| `80b1d5cc653055a3` | `security/product-security/vulnerability-management/labels.md` 32~35, 겹침 119자 | 라벨 4행 | 일치. 관찰: 맨 앞이 원문 31행 설명 칸의 뒷부분이라 그 행의 라벨 이름이 없다 |
| `0ff86c3e8f40b550` | `engineering/devops/runner/runner-core/bug-triage-matrix.md` 41~43 | 점수 2(20+ upvotes), 1(10-19 upvotes), 0(`<10 upvotes`) | 일치. 원문의 `\<10` 이스케이프는 `<10`으로 풀림 |
| `90d2185908336f79` | `enterprise-data/ai/context-layer/_index.md` 130~134, 겹침 119자 | 용어 5행 | 일치. 관찰: 맨 앞이 `\| Meaning: ...`으로 시작해 원문 129행의 용어명 `Reference query`가 없다 |
| `1fa9aaf41986b129` | `enterprise-data/marketing-analytics/.../marketing-analytics-data-l2r.md` 83~92 | 번호 목록 2개와 필드 5행 | 일치. 관찰: 링크 주소는 빠지고 글자만 남음(`Defined in model`) |
| `168d83c43af6018a` | `enterprise-data/ai/context-layer/add-a-domain/eval-harness.md` 233~244, 겹침 114자 | 입력 표 2행(`mode` 기본 `full`, `models` 기본 `gitlab/duo-chat-sonnet-5`). 3행(`domain`)은 다음 청크 | 일치. 관찰: 번호 목록 1~3번이 `-`로 바뀌어 같은 청크의 "skip steps 1 to 3"이 가리킬 번호가 없다 |
| `0bf9861989809ac3` | `engineering/infrastructure-platforms/project-management/index.md` 180~181, 겹침 120자 | 상태 라벨 2행(Stalled, Blocked) | 일치. 라벨 이름은 이미지 대체 글에서 가져옴. 관찰: 맨 앞이 원문 179행(Cancelled) 설명의 뒷부분 |
| `6cfb6df5e6bda72a` | `engineering/infrastructure-platforms/gitlab-dedicated/dedicated-migrations.md` 24~28 | 이름과 직책 5행(Petar Prokić 악센트 유지) | 일치 |
| `0cc2358a4bd54fba` | `finance/committee-composition.md` 85~91, 겹침 115자 | 보고서 준비 일정 7행(13, 12, 8, 5, 4, 2 - 4, 1 - 2 days)과 담당 | 일치. 관찰: 맨 앞이 `\| DRIs: SEC & SOX Director`로, 원문 83행(16 days)의 일수 칸과 할 일 칸이 없다. 84행(14 days)은 온전히 들어옴 |
| `9bd7f78d2eab215c` | `security/corporate/systems/okta/.../device-posture-windows/_index.md` 9~13 | 한 칸짜리 Remediation 표의 Windows 10, 11 각 3단계 | 일치. `<br>`는 줄바꿈으로 바뀜 |
| `1aaa65c90174a51e` | `security/policies_and_standards/password-standard.md` 24~26 | 역할과 책임 3행 | 일치 |
| `a8a0139d83f52a52` | `engineering/infrastructure-platforms/production-engineering/fleet-management/_index.md` 32~34 | 머리 행이 빈 표라 첫 칸이 라벨(Workflow, GitLab.com, Team Slack Channels) | 일치 |

### 수치 문단 청크 10개

| 청크 id | 원문 (줄) | 본 것 | 결과 |
|---|---|---|---|
| `88be72621052cf95` | `security/product-security/.../prodsec-to-product-workflow/_index.md` 126~135, 겹침 117자 | Phase 3 활동 3개와 산출물 3개 | 일치. 관찰: 번호 목록이 `-`로 바뀜, 겹침 조각이 문장 중간(`activities:`)에서 시작 |
| `0cc2bf8465b7dd60` | `support/knowledge-base/knowledge-base-training.md` 6~32 | 영상 길이 `5 minutes`, `2 minutes`, `5 Minutes`와 링크 주소 | 일치 |
| `8730f8ad1802dbbf` | `enterprise-data/platform/_index.md` 1204 | Data Pump 문단 1개 | 일치. 굵은 글씨, 링크 표기만 빠짐 |
| `dbf699a6d1835cef` | `engineering/infrastructure-platforms/gitlab-dedicated/_index.md` 661~701(긴 목록 항목을 800자로 쪼갠 조각), 겹침 119자 | `due-date ... 1 week in the future` 등 하위 항목 | 일치. 관찰: 들여쓴 하위 목록이 평평한 목록으로 바뀜. 이 조각은 662~682행 분량만 담고 나머지는 다음 청크 |
| `06d7200e611bb565` | `business-technology/_index.md` 22~25 | `tier 1 metrics` 문장 포함 원칙 4개 | 일치. 관찰: 번호 1~4가 `-`로 바뀜 |
| `881253a5c2d9ce50` | `engineering/development/sec/security-platform/abuse-engineering/_index.md` 6~9 | `FY27` 문장 | 일치 |
| `ddb2133eb4566109` | `support/workflows/account_deletion_access_request_workflows.md` 238~247, 겹침 120자 | 계정 삭제 절차 문단과 목록 | 일치. 겹침 조각이 문장 중간에서 시작 |
| `c0a4237e384cd1f0` | `engineering/infrastructure-platforms/change-management/_index.md` 344, 겹침 116자 | `S1/S2` 사고 승인 절차 문단 | 일치. 겹침 조각이 문장 중간에서 시작 |
| `7635540301f031c5` | `engineering/deployments-and-releases/deployments/index.md` 139~151, 겹침 119자 | 배포 차단 안내 문단과 목록(`gstg-cny`, `gprd-cny` 등) | 일치. 번호 2~3번이 `-`로 바뀜 |
| `13d2f4cb86347ae8` | `support/workflows/dedicated_cmoc.md` 106~108 | `every 60 minutes` 문장 | 일치 |

## 읽으며 본 반복 현상 (값 오류 아님)

1. 앞 청크에서 겹쳐 들어온 조각이 표 행이나 문장 중간에서 시작한다: 표본 중 겹침이 있는 표 청크 7개(`026d7ffe`, `80b1d5cc`, `90d21859`, `b36c530f`, `168d83c4`, `0bf98619`, `0cc2358a`) 모두에서 봤다. 그중 `026d7ffe`, `80b1d5cc`, `90d21859`, `0bf98619`, `0cc2358a`는 첫 행의 라벨 또는 첫 칸이 이 청크에 없다. 전수 건수는 `report.md` 4장.
2. 번호 목록의 번호가 `-`로 바뀐다: 표본 6개(`2ec7d538`, `168d83c4`, `88be7262`, `06d7200e`, `76355403`, `1fa9aaf4`)에서 봤다. 이 글에서 "steps 1 to 3"처럼 번호를 가리키면 청크 안에서 찾을 수 없다.
3. 링크 주소, 굵은 글씨, 이미지, 백틱은 글자만 남는다. 의도된 파싱이다.

## 확인하지 못한 것

- 4,319개 중 이 30개만 눈으로 읽었다. 나머지는 프로그램 대조(`report.md` 2장)만 했다.
- 읽은 쪽이 Claude Code 하나라서 같은 해석 편향이 있을 수 있다. 팀원 재확인 전이다.
- 표본의 원문 쪽 GET은 현재 쪽이며 스냅샷과 시점이 다를 수 있다.
