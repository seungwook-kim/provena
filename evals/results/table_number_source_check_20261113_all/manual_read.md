# 표 청크 9개를 원문과 나란히 놓고 읽은 기록 (2026-11-13)

읽은 쪽: Claude Code(김승욱 작업 세션). 팀원이 다시 읽은 것은 아니다. 프로그램 대조(`check.py`, `word_check.py`)가 값과 낱말만 보므로, 행 순서와 칸 짝짓기까지 눈으로 본 표본이다.
방법: 청크 본문(`chunks.jsonl`)과 스냅샷 `data/corpus.tar.gz` 원문의 `line_start`~`line_end` 줄(앞 청크에서 겹쳐 들어온 앞부분은 그 앞 줄)을 나란히 출력해 행마다 칸 값을 맞췄다. 표본은 숫자·기간·금액이 든 표 청크와 표가 아닌 긴 문장 청크 하나를 골랐다(무작위 추출이 아니다).
결과: 9개 모두 행 수, 행 순서, 칸 값이 원문과 같았다. 열 이름은 `열 이름: 값` 꼴로 청크가 행마다 붙인 것이고 원문 값이 바뀐 곳은 없었다.

| 청크 id | 원문 (줄) | 본 것 | 결과 |
|---|---|---|---|
| `1760f9bd2b094dd5` | `security/product-security/vulnerability-management/sla.md` 14~23, 겹침은 13행 | CVSS 점수 구간 3행, 심각도·우선순위 라벨, 완화 시간(Within 24 hours, N/A), 해결 기한(30, 30, 90, 180 day SLA), 각주 3줄 | 일치. 관찰: 앞 겹침 조각이 원문 13행 중간(`~severity::1`)에서 시작해 이 행의 점수 칸 `9.0-10.0 (Critical)`이 이 청크에 없다 |
| `3b259d9d77bd1d56` | `security/policies_and_standards/records-retention-deletion.md` 57~62, 겹침은 56행 | 보관 기간 7행(3 years, Indefinite, 2 years)과 폐기 방식 | 일치. 관찰: 첫 행이 `Record:` 라벨 없이 시작한다(겹침 조각이 행 중간에서 시작) |
| `f8ad5739e3666b41` | `engineering/testing/quarantine-process.md` 100~103 | 4단계의 기간(3 days maximum, 3 months maximum, 1 week, After 3 months)과 조치 | 일치 |
| `46febe6f4a6ae0bc` | `security/security-assurance/security-risk/third-party-risk-management.md` 353~359 | 설명 문단과 3행(Tier 1 12 months, Tier 2 12 months, Tier 3 24 months) | 일치 |
| `8346358e1a239c03` | `support/data-analysis.md` 66~70, 겹침은 65행 | 시간대 6행의 시작·끝 시각과 길이(AMER-Late 13:00~17:00 PT, APAC-Early 3 hours 등) | 일치. 관찰: 첫 행(AMER-Late)이 `Region:` 라벨 없이 시작한다 |
| `afbf8346bd662039` | `security/security-observations-risk-management.md` 146~147 | 우선순위 1, 2의 라벨, 기준, 목표 해결(30 days maximum, 60-90 days), 알림, StORM·CVSS 구간 | 일치 |
| `405d7236eab82379` | `enterprise-data/how-we-work/planning/index.md` 60~63, 겹침은 59행 | 크기 M, L, XL, XXL의 인원 시간(1 Week, 2-3 Weeks, 1-2 Months, 2-4 Months)과 이슈 점수(5-8, 13, 26, 52+) | 일치. 관찰: 맨 앞이 원문 59행(크기 S) 설명 칸의 뒷부분이라 크기·시간·점수 칸이 이 청크에 없다 |
| `5ebbb861d33d404e` | `engineering/ai/duo-chat/_index.md` 170~172, 겹침은 169행 | 우선순위 P4(겹침), P3, P2, P1의 기대 해결(Within 1 week, 72 hours, 36 hours, ASAP) | 일치. 관찰: P4 행은 설명 칸 중간부터 들어와 `Priority: P4` 라벨이 없다 |
| `74664b2724e87c96` | `authz/authorization-matrix-2023-05.html.md` 559 | 정책 범위 문단의 "within 60 days of approval" 등 수치와 문장 | 일치(문단이라 표가 아님) |

확인하지 못한 것: 123개 중 이 9개만 눈으로 읽었다. 나머지 114개는 프로그램 대조(값 앞뒤 낱말 3개, 낱말 개수)만 했다. 앞 청크에서 겹쳐 들어온 조각이 행 중간에서 시작하는 현상은 겹침이 있는 읽은 표 청크 5개(`1760f9bd…`, `3b259d9d…`, `8346358e…`, `405d7236…`, `5ebbb861…`) 모두에서 봤다. 값이 틀린 것은 아니지만 그 첫 행의 라벨이 빠진다. 읽지 않은 표 청크의 겹침 조각은 전수로 보지 않았다.
