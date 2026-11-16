# 최종 main 새 clone 키 없는 기동 리허설 (2026-11-17 00:54 KST)

main `47e3b82a`(PR #172 머지, 동결 코드 `194dfd9a`와 코드 경로가 같고 문서 1줄만 다름)를 빈 폴더에 새로 clone해 `.env` 없이 `docker compose up -d --build`로 띄웠다. 실행 프로세스에서 키 이름이 든 환경 변수를 모두 지운 뒤 시작했다(`log.txt` 첫 줄, 남은 키 변수 0개). 로컬 실행이라 운영 서비스·유료 API 호출은 없다.

| 항목 | 값 | 근거 |
|---|---|---|
| clone 시작 → clone 끝 | 14초 | `timing.txt` |
| clone 시작 → `/health` 200 | 63.2초(`compose up` 시작부터 49.2초) | `timing.txt` |
| `/` 응답 | 200 | `timing.txt` |
| README 질문 9개(키 없는 데모) | 9/9 기대와 같음(인용 답 7, 거절 2), 모든 요청 비용 0달러 | `summary.md`, `answers.jsonl` |
| `pytest -m demo_replay` | 6 passed(149.19초) | `demo_replay.txt` |

`demo_replay.txt` 끝의 `couldn't stop thread 'pool-6-...'` 경고는 시험이 모두 끝난 뒤 연결 풀 스레드 종료를 기다리며 나온 것이고 결과(6 passed)에는 영향이 없다. 확인 뒤 `docker compose down -v`로 컨테이너와 볼륨을 지웠다(`log.txt` 끝).

`.env` 파일은 clone에 없었다(`timing.txt`의 `.env exists: False`).
