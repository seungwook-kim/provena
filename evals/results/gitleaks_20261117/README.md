# 최종 main 비밀값 검사 (gitleaks 8.30.1, 2026-11-17)

대상은 main `3dbc36ca`(PR #174 머지)의 전체 이력과 작업 폴더다. 모든 실행에 `--redact`를 붙여 보고서에 비밀값이 남지 않게 했고, 저장소의 `.gitleaks.toml`을 그대로 썼다. 원본 보고서에는 커밋 작성자 이름·이메일 칸이 있어 저장소에는 규칙·파일·줄·커밋·지문만 옮겼다.

| 검사 | 결과 |
|---|---|
| `gitleaks git .` 전체 이력(커밋 821개), `.gitleaksignore` 적용 | 검출 0건 |
| 같은 검사, 빈 ignore 파일 적용 | 11건, 모두 `.gitleaksignore`에 이미 등록된 오탐(`findings_without_gitleaksignore.json`의 `in_gitleaksignore` 전부 true) |
| `gitleaks dir .` 작업 폴더, ignore 갱신 전 | 77건 가운데 저장소에 올라가는 파일은 2건(리콜 웹훅 결과의 이벤트 식별자, 재실행 스크립트의 리비전 이름). 두 줄은 커밋 지문으로는 이미 등록돼 있었고 작업 폴더용 지문만 빠져 있었다 |
| `.gitleaksignore`에 작업 폴더용 지문 2줄 추가 뒤 `gitleaks dir .` | 75건, 저장소에 올라가는 파일 0건 |
| 추가 뒤 `gitleaks git .` 재실행 | 821개 커밋, 검출 0건 |

`dir` 검사의 나머지 75건은 커밋하지 않는 로컬 파일이다(`.env` 4, `.venv/` 61, `.trail/` 2, 내려받은 핸드북 원문과 그 가공본 `data/corpus`·`data/chunks`·`data/parsed`·`data/index` 8). 핸드북 원문의 검출은 GitLab 문서에 실린 예시 토큰 형식이다. 판정에는 `git ls-files`에 든 파일의 검출만 쓴다.

## 파일

- `summary.json`: 위 표의 수치(커밋 수, 검출 수, 작업 폴더 검출을 저장소 파일과 로컬 파일로 나눈 값)
- `findings_without_gitleaksignore.json`: 빈 ignore 파일로 돌린 11건의 규칙·파일·줄·커밋·지문과 등록 여부

## 재현

```
gitleaks git . --redact --report-format json --report-path report.json
gitleaks dir . --redact --report-format json --report-path report_dir.json
```
