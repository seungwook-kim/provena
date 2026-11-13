# 정답 근거 청크의 표·수치 원문 대조 (2026-11-13)

- 대상: v1 30건의 관련 15문항, v2 50건의 관련 25문항, 검증 20건의 관련 10문항과 새 인용 5건의 관련 5문항의 정답 위치에 맞는 청크 123개 중 수치 값이나 표가 든 60개(서로 다른 청크, 한 청크가 여러 문항의 정답이면 문항을 모두 적음).
- 스냅샷 `data/corpus.tar.gz`(sha256 `51227fb1842f9eda…`)의 해당 페이지와 줄 범위(`line_start`~`line_end`)와 대조: 60개 중 일치 60개, 불일치 0개.
- 공개 원문(`source_url`, GET만)의 2026-11-13T13:00:59+09:00 본문과 대조: 60개 확인, 일치 60개, 불일치 0개.

일치의 뜻: 청크의 수치 값(금액, 비율, 기간, 등급, 개수, 표 청크의 단위 없는 숫자)이 모두 원문에 있고, 값 앞뒤 낱말 3개가 원문과 같다. 자세한 규칙은 `check.py` 머리말.

| 청크 id | 문항 | 종류 | 수치 값 | 스냅샷 줄 | 스냅샷 일치 | 현재 원문 일치 | 확인 시각 |
|---|---|---|---|---|---|---|---|
| `34032311f59f0f48` | v1 1, v2 1 | 수치 | 15 minute | `engineering/development/sec/oncall/communication-and-culture.md` 187~187 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `159e4f13dc80e656` | v1 1, v2 1 | 수치 | 15 minute | `engineering/devops/oncall/communication-and-culture.md` 170~170 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `fb3ba634a8d30bda` | v1 1, v2 1 | 수치 | tier 1, tier 2, 15 minute | `engineering/infrastructure-platforms/incident-management/on-call/_index.md` 98~100 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `9fb825ed83c31843` | v1 1, v2 1 | 수치 | tier 1, tier 2 | `engineering/infrastructure-platforms/incident-management/on-call/_index.md` 109~110 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `9959baf3c8f4f4dd` | v1 1, v2 1 | 수치 | tier 1, tier 2 | `engineering/infrastructure-platforms/incident-management/on-call/_index.md` 111~112 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `24a485a6ba92892f` | v1 1, v2 1 | 수치 | tier 1, tier 2, 2 day | `engineering/infrastructure-platforms/incident-management/on-call/_index.md` 113~116 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `92b237219ea249df` | v1 1, v2 1 | 수치 | tier 1, tier 2 | `engineering/infrastructure-platforms/incident-management/on-call/_index.md` 113~116 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `35792cd8fb054365` | v1 1, v2 1 | 수치 | tier 1, tier 2 | `engineering/infrastructure-platforms/incident-management/on-call/_index.md` 117~118 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `7cd641d28bcdfeb5` | v1 2, v2 2 | 수치 | s1, 15 minute | `engineering/infrastructure-platforms/incident-management/_index.md` 190~198 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `d23336c2bb0af64a` | v1 2, v2 2 | 수치 | 15 minute, s1 | `engineering/infrastructure-platforms/incident-management/_index.md` 199~208 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `c0b70df826324df3` | v1 2, v2 2 | 수치 | s1 | `engineering/infrastructure-platforms/incident-management/_index.md` 211~213 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `ece9c56501261bbd` | v1 2, v2 2 | 수치 | s1 | `engineering/infrastructure-platforms/incident-management/_index.md` 215~231 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `d55fdad5821a802f` | v1 3, v2 3 | 표+수치 | 숫자 13, 00 | `engineering/releases/monthly-releases/index.md` 87~89 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `98f3fd335aae5cb7` | v1 4, v2 4 | 수치 | 15 minute | `engineering/deployments-and-releases/deployments/index.md` 44~56 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `c8367415ba48ad91` | v1 4, v2 4 | 수치 | 30 minute | `engineering/deployments-and-releases/deployments/index.md` 59~60 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `377c9fd1edb06d26` | v1 6, v2 6 | 수치 | 24 hour, severity 3, severity 2 | `engineering/testing/flaky-tests/_index.md` 79~83 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `f8ad5739e3666b41` | v1 6, v2 6 | 표+수치 | 3 day, 3 month, 1 week, 숫자 3, 1 | `engineering/testing/quarantine-process.md` 100~103 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `a28e2bc1ab86d482` | v1 8, v2 8 | 수치 | 2 day | `engineering/workflow/code-review.md` 572~582 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `1e96e77a038841f2` | v1 8, v2 8 | 수치 | 2 day, 36 hour | `engineering/workflow/code-review.md` 583~596 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `c3b5296636ea8c06` | v1 9, v1 11, v2 9, v2 11 | 표+수치 | 24 hour, 30 day, 숫자 9, 1, 24, 30 | `security/product-security/vulnerability-management/sla.md` 9~13 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `1760f9bd2b094dd5` | v1 9, v1 11, v2 9, v2 11 | 표+수치 | 24 hour, 30 day, 90 day, 180 day, 숫자 1, 24, 30, 7, 2, 4… | `security/product-security/vulnerability-management/sla.md` 14~23 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `b8f138d76e58138e` | v1 10, v2 10 | 표+수치 | 6 month, 숫자 6 | `security/security-assurance/security-compliance/access-reviews.md` 78~81 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `afbf8346bd662039` | v1 11, v2 11 | 표+수치 | 30 day, 90 day, 24 hour, 숫자 1, 30, 26, 9, 2, 60… | `security/security-observations-risk-management.md` 146~147 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `4de9926da327a146` | v1 11, v2 11 | 표+수치 | 24 hour, 120 day, 숫자 24, 21, 7, 3, 90, 11… | `security/security-observations-risk-management.md` 148~149 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `0cbc62bd8d22eda8` | v1 13, v2 13 | 수치 | 30 day, 90 day | `support/priority_prospects.md` 16~32 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `7ad651dbe57bb485` | v1 13, v2 13 | 수치 | 24 hour | `support/priority_prospects.md` 33~40 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `cc7e86c9948b205d` | v2 31 | 수치 | 5 day, 7 day, severity 1 | `engineering/infrastructure-platforms/incident-review/_index.md` 149~149 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `466343fe561e453b` | v2 31 | 수치 | severity 1 | `engineering/workflow/root-cause-analysis.md` 41~41 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `c07479ec82f10149` | v2 34 | 수치 | s1, s2 | `engineering/releases/patch-releases/index.md` 98~122 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `133f8fdfd459e861` | v2 35 | 표+수치 | 숫자 1, 5, 2 | `engineering/infrastructure-platforms/developer-experience/ai/_index.md` 29~34 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `5fff43a9dd7762b5` | v2 35 | 표+수치 | 숫자 3, 4, 5 | `engineering/infrastructure-platforms/developer-experience/ai/_index.md` 35~41 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `eb716842d2574546` | v2 36 | 표 | - | `security/security-assurance/security-risk/third-party-risk-management.md` 53~54 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `e92ff33755911829` | v2 36 | 표+수치 | 12 month, 숫자 12 | `security/security-assurance/security-risk/third-party-risk-management.md` 55~56 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `71546862abfa5085` | v2 36 | 표 | - | `security/security-assurance/security-risk/third-party-risk-management.md` 57~58 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `17997f24b5e563bd` | v2 36 | 표 | - | `security/security-assurance/security-risk/third-party-risk-management.md` 59~60 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `8d1287e09ae75d03` | v2 36, v2 38 | 수치 | 12 month | `security/security-assurance/security-risk/third-party-risk-management.md` 64~69 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `46febe6f4a6ae0bc` | v2 36 | 표+수치 | tier 1, 12 month, tier 2, tier 3, 24 month, 숫자 1, 12, 2, 3, 24 | `security/security-assurance/security-risk/third-party-risk-management.md` 353~359 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `931a9097b6def468` | v2 36 | 표+수치 | 12 month, tier 3, 24 month, tier 4, tier 1, 숫자 12, 3, 24, 4, 1 | `security/security-assurance/security-risk/third-party-risk-management.md` 360~364 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `e426f23ef1c805be` | v2 37 | 수치 | 12 character | `security/policies_and_standards/password-standard.md` 36~42 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `28f705901df4164f` | v2 37 | 수치 | 12 character | `security/policies_and_standards/password-standard.md` 56~60 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `1f56e00edc2f2e1f` | v2 37 | 수치 | 90 day | `security/policies_and_standards/password-standard.md` 61~64 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `349e97b509c1da3a` | v2 37 | 수치 | 10 attempt | `security/policies_and_standards/password-standard.md` 65~67 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `ccfb6ebf411e08fb` | v2 38 | 수치 | $25k, $0 | `finance/procurement/_index.md` 126~139 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `2981c3e50443587a` | v2 38 | 수치 | 3 year, $250k, $100k, $25k | `finance/procurement/_index.md` 140~145 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `74664b2724e87c96` | v2 40 | 수치 | 60 day | `authorization-matrix-2023-05.html.md` 559~559 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `5529f76ff65dffe4` | 검증 101 | 수치 | $50 | `finance/expenses.md` 53~55 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `0455d5d3f3342461` | 검증 101 | 수치 | $5000, 90 day | `finance/expenses.md` 56~57 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `09b3cf4eaec6798c` | 검증 101 | 수치 | 90 day | `finance/spending-company-money.md` 12~14 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `1625c847bacf5675` | 검증 102 | 수치 | $5000, $100, 20 people, $125 | `finance/accounts-payable/corp-credit-cards.md` 41~50 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `65b354ed06c8e3ad` | 검증 104 | 수치 | 1 week | `security/security-assurance/governance/phishing.md` 109~115 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `6ae438193abc5b4f` | 검증 105 | 표+수치 | 1 year, 3 month, 숫자 1, 3 | `security/policies_and_standards/records-retention-deletion.md` 39~44 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `3b259d9d77bd1d56` | 검증 105 | 표+수치 | 3 year, 2 year, 숫자 3, 2 | `security/policies_and_standards/records-retention-deletion.md` 57~62 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `bb5eee21805e7c1b` | 검증 106 | 표+수치 | 숫자 3 | `support/training/onboarding_buddy.md` 28~31 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `d4918e31a5b3c954` | 검증 106 | 수치 | 2 week | `support/training/onboarding_buddy.md` 16~19 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `95301b7ac46e267c` | 검증 108 | 표 | - | `support/knowledge-base/kb-faq.md` 55~58 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `8346358e1a239c03` | 새 인용 301 | 표+수치 | 4 hour, 3 hour, 6 hour, 숫자 13, 00, 17, 21, 01, 4… | `support/data-analysis.md` 66~70 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `405d7236eab82379` | 새 인용 302 | 표+수치 | 1 week, 3 week, 2 month, 4 month, 숫자 1, 5, 2, 13, 26, 52 | `enterprise-data/how-we-work/planning/index.md` 60~63 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `5ebbb861d33d404e` | 새 인용 303 | 표+수치 | 1 week, p3, 72 hour, p2, 36 hour, p1, 숫자 1, 72, 36 | `engineering/ai/duo-chat/_index.md` 170~172 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `eec6f89825ff7fc2` | 새 인용 304 | 표+수치 | 1 day, 2 day, 1 week, 2 week, 숫자 1, 2, 3, 5 | `security/product-security/infrastructure-security/metrics/capacity.md` 50~53 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |
| `0038ce8d57073dcf` | 새 인용 305 | 표+수치 | 5 day, 8 day, 13 day, 21 day, 숫자 5, 8, 13, 21 | `engineering/development/sec/security-factory/code-scanning/_index.md` 104~110 | 일치 | 일치 | 2026-11-13T13:00:59+09:00 |

## 불일치

없음.
