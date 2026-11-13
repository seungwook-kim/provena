# 정답 근거 청크 전체의 본문 낱말 대조 (2026-11-13)

- 대상: v1, v2, 검증, 새 인용 문항의 정답 위치에 맞는 청크 123개 전부(수치가 없는 청크 포함). 방법은 `word_check.py` 머리말.
- 본문 낱말이 모두 원문 줄 범위에 있음: 101개.
- 본문 낱말 가운데 줄 범위에 없거나 개수가 모자란 것이 있으나 모두 같은 쪽 안에 있음: 22개 (표 청크 22개). 열 이름을 행마다 되풀이해 적는 표 청크 구조 때문이다.
- 원문 쪽에 없는 낱말이 있는 청크: 0개.

| 청크 id | 문항 | 종류 | 표 | 줄 범위 | 본문 낱말 | 줄 범위의 개수 초과 | 쪽의 다른 줄에만 있음 | 쪽에 없음 | 개수 초과 낱말 예 | 다른 줄 낱말 예 |
|---|---|---|---|---|---|---|---|---|---|---|
| `0038ce8d57073dcf` | 새 인용 305 | article | 예 | `engineering/development/sec/security-factory/code-scanning/_index.md` 104~110 | 89 | 5 | 3 | 0 | weight, days | reference |
| `1760f9bd2b094dd5` | v1 9, v1 11, v2 9, v2 11 | article | 예 | `security/product-security/vulnerability-management/sla.md` 14~23 | 96 | 2 | 21 | 0 | cvssv3 | time, to, mitigate, remediate, ttr |
| `17997f24b5e563bd` | v2 36 | article | 예 | `security/security-assurance/security-risk/third-party-risk-management.md` 59~60 | 76 | 0 | 4 | 0 | - | question, answer |
| `3b259d9d77bd1d56` | 검증 105 | article | 예 | `security/policies_and_standards/records-retention-deletion.md` 57~62 | 83 | 0 | 30 | 0 | - | requirement, record, retention, disposal |
| `405d7236eab82379` | 새 인용 302 | article | 예 | `enterprise-data/how-we-work/planning/index.md` 60~63 | 90 | 0 | 32 | 0 | - | size, dedicated, person, time, weight, issue |
| `46febe6f4a6ae0bc` | v2 36 | article | 예 | `security/security-assurance/security-risk/third-party-risk-management.md` 353~359 | 112 | 1 | 0 | 0 | window | - |
| `4de9926da327a146` | v1 11, v2 11 | article | 예 | `security/security-observations-risk-management.md` 148~149 | 67 | 1 | 12 | 0 | notification | label, criteria, target, resolution, equivalent, mappings |
| `5ebbb861d33d404e` | 새 인용 303 | article | 예 | `engineering/ai/duo-chat/_index.md` 170~172 | 83 | 0 | 18 | 0 | - | priority, typically, used, for, expected, resolution |
| `5fff43a9dd7762b5` | v2 35 | article | 예 | `engineering/infrastructure-platforms/developer-experience/ai/_index.md` 35~41 | 118 | 0 | 6 | 0 | - | label, meaning |
| `6ae438193abc5b4f` | 검증 105 | article | 예 | `security/policies_and_standards/records-retention-deletion.md` 39~44 | 94 | 0 | 30 | 0 | - | requirement, record, retention, disposal |
| `71546862abfa5085` | v2 36 | article | 예 | `security/security-assurance/security-risk/third-party-risk-management.md` 57~58 | 79 | 0 | 4 | 0 | - | question, answer |
| `8346358e1a239c03` | 새 인용 301 | article | 예 | `support/data-analysis.md` 66~70 | 120 | 0 | 60 | 0 | - | local, start, end, utc, region, anchor |
| `931a9097b6def468` | v2 36 | article | 예 | `security/security-assurance/security-risk/third-party-risk-management.md` 360~364 | 87 | 0 | 3 | 0 | - | system, approval, window |
| `95301b7ac46e267c` | 검증 108 | article | 예 | `support/knowledge-base/kb-faq.md` 55~58 | 89 | 0 | 8 | 0 | - | feature, notes |
| `afbf8346bd662039` | v1 11, v2 11 | article | 예 | `security/security-observations-risk-management.md` 146~147 | 78 | 1 | 12 | 0 | notification | label, criteria, target, resolution, equivalent, mappings |
| `b8f138d76e58138e` | v1 10, v2 10 | article | 예 | `security/security-assurance/security-compliance/access-reviews.md` 78~81 | 61 | 0 | 24 | 0 | - | review, system, type, frequency, scope |
| `bb5eee21805e7c1b` | 검증 106 | article | 예 | `support/training/onboarding_buddy.md` 28~31 | 95 | 0 | 5 | 0 | - | task, estimated |
| `d55fdad5821a802f` | v1 3, v2 3 | article | 예 | `engineering/releases/monthly-releases/index.md` 87~89 | 32 | 0 | 6 | 0 | - | step, purpose |
| `e92ff33755911829` | v2 36 | article | 예 | `security/security-assurance/security-risk/third-party-risk-management.md` 55~56 | 106 | 0 | 4 | 0 | - | question, answer |
| `eb716842d2574546` | v2 36 | article | 예 | `security/security-assurance/security-risk/third-party-risk-management.md` 53~54 | 74 | 0 | 4 | 0 | - | question, answer |
| `eec6f89825ff7fc2` | 새 인용 304 | article | 예 | `security/product-security/infrastructure-security/metrics/capacity.md` 50~53 | 87 | 3 | 20 | 0 | label | weight, classification, description, estimation, guide |
| `f8ad5739e3666b41` | v1 6, v2 6 | article | 예 | `engineering/testing/quarantine-process.md` 100~103 | 51 | 0 | 16 | 0 | - | phase, duration, action, required |

한계: 낱말 개수를 맞춘 약한 대조이며 낱말의 순서와 문장 뜻은 보지 않는다. 표 청크의 열 이름 되풀이는 파싱 방식이므로 불일치로 세지 않았다(EVAL_REPORT 1장 원문 대조 2번 행). 순서와 문장은 사람이 읽은 표본(EVAL_REPORT 1장 원문 대조 7번 행)으로만 봤다.
