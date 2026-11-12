# 키 없는 새 clone 기동 시간 (main 4c8d8bc, 2026-11-13)

`origin/main`의 병합 커밋 `4c8d8bc`(PR #141)를 별도 폴더에 새로 clone한 사본에서 `.env` 없이 `docker compose up`을 두 회차 쟀다. LLM·임베딩 키는 쓰지 않았고 운영 서비스는 부르지 않았다(비용 0원).

## 환경

| 항목 | 값 |
|---|---|
| 커밋 | `4c8d8bc2c43eee29814033267803c1f526bd00d3` |
| Docker Compose | v5.5.0 |
| Docker Engine | 29.7.2 |
| `.env` | 없음(측정 스크립트가 확인함) |
| compose 프로젝트 이름 | `e1fresh`(기존 컨테이너와 겹치지 않도록 `-p`로 지정, 포트는 README 그대로 8000) |
| 측정 방법 | PowerShell 스크립트가 시작 시각부터 1초 간격으로 `GET http://localhost:8000/health`를 불러 200이 처음 온 시각을 기록하고, 이어서 `demo-user`로 로그인해 데모 질문과 범위 밖 질문을 보냄 |

## 결과

| 회차 | 조건 | 시작에서 `/health` 200까지 | 시작에서 데모 질문 인용 답까지 | 비고 |
|---|---|---|---|---|
| 1 | `docker compose -p e1fresh build --no-cache` 뒤 `docker compose -p e1fresh up` (빌드 층 캐시 사용 안 함) | 136.0초 (빌드 98.5초 + up 37.5초) | 약 147초 | loader 적재 5.1초, 청크 23,095개, 인용 이벤트 2, `kind=answer`, 첫 질문 응답 10.6초 |
| 2 | 이미지를 지운 뒤 빌드 캐시가 있는 상태에서 `docker compose -p e1fresh up`(필요한 이미지를 캐시로 다시 빌드) | 30.4초 | 약 41초 | loader 적재 5.2초, 첫 질문 응답 10.4초 |

두 회차 모두 `demo-user` 로그인 200, 데모 질문(외부 SaaS 5만 달러 승인자) 응답은 `kind=answer`이고 인용 이벤트 2개와 비용 0.0달러이며, "오늘 점심 메뉴 추천해줘"는 `kind=refuse`(`no_results`)로 거절됐다. 같은 질문을 두 번째로 보내면 0.5초에 답이 나왔다. 응답 글은 `run1_nocache.answers_utf8.tsv`, `run2_buildcache.answers_utf8.tsv`에 있다.

"인용 답까지" 시간은 스크립트가 질문 단계 끝에 남긴 파일 기록 시각(초 단위)을 시작 시각에서 뺀 값이라 약 1초의 오차가 있다.

## 읽는 법과 한계

- **1회차는 완전한 콜드 시작이 아니다.** `--no-cache`는 빌드 층 캐시를 쓰지 않게 하지만, 이 PC에는 기반 이미지(`python:3.12-slim`, `node:22-alpine`, `pgvector`)가 이미 있어 그 이미지를 내려받는 시간은 들어 있지 않다. pip 패키지와 npm 패키지는 `--no-cache` 빌드에서 다시 내려받았다. 기반 이미지까지 처음 받는 PC에서는 더 걸린다. 2026-11-09 기록(`evals/results/g2_keyless_2026-11-09/summary.md`)에는 이미지 풀기 지연으로 10분 22초가 걸린 회차가 있다.
- 2회차는 빌드 캐시와 기반 이미지가 모두 있는 상태에서 이미지만 지운 값이다. 이미지와 캐시가 모두 있으면 이전 기록(2026-11-10 새 clone 기록의 14~23초 범위)과 같은 수준으로 뜬다.
- 측정 PC의 회선과 디스크에 따라 달라지는 단일 측정이다. 같은 조건을 여러 번 반복한 분포가 아니다.
- 이전 기록 `evals/results/fresh_clone_keyless_2026-11-10/`은 병합 커밋 `e8b8059` 기준이고, 이 문서는 현재 main 기준이다. 그 사이 데모 녹화 파일 `data/demo_replay/recorded.jsonl`이 `ed5ef33`, `9966bd3`, `41377ad` 세 커밋에서 바뀌었다. 이 측정의 데모 질문 답은 "검색된 근거를 그대로 발췌한 답입니다" 대체 문장이 아니라 녹화 재생 답이었다(`run1_nocache.answers_utf8.tsv`).

## 재현 명령

새 폴더에서 README의 순서 그대로이다.

```bash
git clone https://github.com/aihuman-7th/proj3-c.git
cd proj3-c
docker compose up          # .env 없이 뜬다
# 완전히 새로 빌드하는 값을 보려면 위 줄 대신
docker compose build --no-cache && docker compose up
```

기동 확인: `curl http://localhost:8000/health`가 200과 `{"status":"ok"}`를 돌려주면 된다. 끝낼 때는 `docker compose down -v`.

## 파일

| 파일 | 내용 |
|---|---|
| `keyless_boot/run1_nocache.timeline.txt` | 1회차 시각표(시작, 빌드 끝, loader 끝, `/health` 200, 스모크 끝) |
| `keyless_boot/run2_buildcache.timeline.txt` | 2회차 시각표 |
| `keyless_boot/run1_nocache.loader.txt`, `run2_buildcache.loader.txt` | loader 적재 로그(청크 23,095개) |
| `keyless_boot/run1_nocache.answers_utf8.tsv`, `run2_buildcache.answers_utf8.tsv` | 질문별 받은 답 글 |
