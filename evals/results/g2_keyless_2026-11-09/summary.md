# G2 키 없는 새 clone 재실측 (2026-11-09)

- 대상: main `6dd144be5430c05971886169a335b4a6fba752c6` (PR #91 병합 직후, PR #81 데모 재생 포함). `.env` 없음, LLM·Voyage 키 없음, `DEMO_MODE=1`(기본).
- 방법: `docker compose -p provena-g2 up -d --build`(프로젝트 이름만 지정). 시계는 `up` 시작부터 `/health` 200까지(clone 시간 제외).

## 기동 시간

| 회차 | 조건 | 결과 |
|---|---|---|
| 1 | 빌드 캐시 일부(파이썬 패키지 설치 층은 새로 받음), 이미지·DB 없음 | `/health` 200까지 622초(10분 22초). 이미지 풀기 229초, loader 적재 66.5초 |
| 2 | `build --no-cache` 74초 + `up -d --build` | `/health` 200까지 157초, 합계 231초(3분 51초). loader 적재 8.8초 |
| 3 | 이미지·DB·`data/index/` 삭제 후 `up -d --build`(빌드 캐시 있음) | 첫 `up`이 70초에 실패: loader가 `connection refused`로 종료(아래 문제). 다시 `up -d`하니 14초 만에 `/health` 200 |
| 반복 | 이미지 있음, 새 DB 3회 | 19~23초, 3회 모두 성공 |

문제: db 서비스 healthcheck가 `pg_isready -U app -d app`(소켓 검사)라서, 첫 기동 때 `db/` SQL을 적용하는 임시 서버(소켓만 열림, 약 40초)가 떠 있는 동안 healthy로 판정된다. 이때 loader가 TCP로 붙어 `Connection refused`로 끝나면 `api`가 뜨지 않는다. 1·2회차와 반복에서는 일어나지 않았고 3회차에서 1번 일어났다.

## 키 없는 질문 시험 (`/chat`, demo-user 로그인)

| 질문(README 녹화 목록) | 답 | 인용 수 | 인용 출처 |
|---|---|---|---|
| 제3자가 프로덕션 데이터에 접근하거나 영향을 줄 수 있다면 보안 검토가 필요한가요? | 있음 | 1~2 | GitLab Handbook, Third Party Risk Management (판 2026-09-13) |
| CVSS 9.0 이상 크리티컬 취약점은 얼마 안에 완화하고 얼마 안에 수정해야 해? | 있음(24시간, 30일) | 2 | GitLab Handbook, Vulnerability Resolution SLAs (판 2026-04-09) |
| 클라우드 호스팅 업체와 약정 사용 할인(CUD) 계약은 누가 승인해? | 있음(VP Infrastructure, VP Finance) | 1 | Authorization Matrix 2023-05 (판 2023-05-11) |
| EOC가 호출에 응답하지 않으면 어떻게 에스컬레이션돼? IMOC도 응답이 없으면? | 있음 | 3 | GitLab Handbook, Incident Management (판 2026-08-18) |
| 외부 SaaS 5만 달러 업무 승인자와 재무 승인자는? | 있음(Director, PAO 또는 VP Finance) | 3~4 | Authorization Matrix 2023-05 (판 2023-05-11) |
| 녹화에 없는 질문: 우리 회사 연차 휴가는 몇 일이고 이월은 어떻게 되나요? | 거절 "검색에 필요한 키가 설정되어 있지 않아 답하지 않습니다." | 0 | 해당 없음 |

같은 질문을 새로 띄운 스택에서 4번 물었을 때 5건 모두 매번 인용 답이 나왔다. 질문 1과 5는 인용 수가 회차마다 달랐다(1 또는 2, 3 또는 4). `recorded.jsonl`에 같은 요청 키로 응답이 여러 개(136건 중 고유 키 96개) 있어 재생되는 답이 매번 같지는 않다.
