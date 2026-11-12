# 이미지 크기·compose 기동 시간 로컬 실측 (K-11, S-05)

**로컬 실측** 2026-11-12 (KST), 기준 커밋 `601183c7`(origin/main). 운영 주소·LLM 호출 없음, Dockerfile·docker-compose.yml·.env.example 수정 없음.

## 무엇을 쟀나

1. 저장소 Dockerfile 그대로 `docker build -t provena-local:k11 .` 한 번: 빌드 시간, 이미지 크기, 층별 크기.
2. 이미지 안에 원문(코퍼스)·색인이 두 벌 들어 있는지: `docker run --rm --entrypoint sh`로 큰 파일 경로·크기·sha256 대조.
3. `docker compose -p k11measure up -d --build`를 `.env` 없이(키 없는 데모) 실행해 명령 시작부터 `/health` 200까지 시간. 끝나면 `docker compose -p k11measure down -v`.

## 왜 (놓친 것 목록 행)

- K-11: 비 root 실행·`.dockerignore`는 이미 있음(Dockerfile `USER app`, uid 10001 / `.dockerignore`). 이미지 안에 원문이 두 벌인지는 확인되지 않았던 항목.
- S-05: 조합별 이미지 크기, `docker compose up` 시간, 실제 CPU 응답 시간이 재지 않았던 항목(`docs/embedding_measurement.md` 한계 절). 이번에는 이미지 크기와 compose 기동 시간만 쟀다. CPU 응답 시간은 범위 밖.

## 결과 (로컬 실측)

| 항목 | 값 | 명령·근거 |
|---|---|---|
| 빌드 시간 | 262초 (4분 22초) | `docker build --progress=plain -t provena-local:k11 .` 앞뒤 `date`. 빌드 캐시 2단계 적중(Docker 캐시가 있던 PC) |
| 이미지 크기 | 디스크 1.17GB, 압축 내용 354MB | `docker images`, `docker image inspect`. 층 21개 |
| 큰 층 | pip 설치 404MB, 풀린 색인 130MB, `COPY data/` 106MB, 풀린 코퍼스 22.7MB, 화면(web) 약 15MB, 파이썬 기본 이미지 위 apt·파이썬 41MB 등 | `docker history --no-trunc` |
| 실행 사용자 | uid 10001 `app` (root 아님) | `docker run ... id` |
| compose 명령 | 53.1초 | `up -d --build` 시작부터 종료. 이미지는 위 빌드 캐시로 즉시 만들어짐 |
| compose 첫 `/health` 200 | 67.5초 | 명령 시작부터 폴링(`urllib`, 1초 간격). `db` healthy 후 `loader` 적재(청크 적재 포함) 후 `api` 시작 |
| compose가 만든 이미지 | `api`·`loader` 둘 다 같은 Dockerfile, 각 1.17GB로 표시 | 층을 공유해 실제 추가 디스크는 한 벌분 |
| DB 이미지 | `pgvector/pgvector:pg16` 621MB(디스크 표시) | `docker images` |

### 원문 두 벌인가 (K-11)

판정: **같은 내용이 압축본과 풀린 본, 두 형태로 이미지에 들어 있다. 같은 형태 두 벌은 아니다.**

| 경로 | 크기 | 설명 |
|---|---|---|
| `/app/data/index.tar.gz` | 94.5MB | 색인 압축본(커밋된 원본 그대로) |
| `/app/data/index/` | 124MB (벡터 92MB, chunks.jsonl 32.5MB) | 빌드 중 `snapshot unpack-index`로 풀린 본 |
| `/app/data/corpus.tar.gz` | 4.6MB | 원문 스냅샷 압축본 |
| `/app/data/corpus/` | 22MB (handbook 18.7MB, history 2.6MB, pages.jsonl 0.8MB) | 빌드 중 `snapshot unpack`으로 풀린 본 |
| `/app/data/chunks_index.jsonl` | 5.0MB | 청크 메타(본문 없음, 글자 수만) |

- 압축본 두 개 합계 약 99MB가 풀린 본(약 146MB)과 겹친다. 이미지 1.17GB의 약 8%.
- `index/chunks.jsonl`(32.5MB)은 청크 본문 텍스트이고 `corpus/`(22MB)는 마크다운 원문이라, 원문 텍스트가 가공된 형태로 한 번 더 있다. sha256은 파일마다 달라(`chunks_index.jsonl` 25177ae7…, `index/chunks.jsonl` 86e6c26c…, `pages.jsonl` 80f9c2b7…) 바이트 단위로 같은 파일은 없다.
- 압축본을 지우지 못하는 이유(코드·문서 근거): compose의 `loader`가 호스트 `./data/index`를 연결하고, 그 폴더가 비어 있으면 이미지 안의 `data/index.tar.gz`를 다시 푼다(`docker-compose.yml` loader 주석, `Dockerfile` unpack-index 주석). 그래서 압축본 제거는 이 흐름을 바꾸는 일이라 이번에 하지 않았다.
- 층 관점: `COPY data/`(106MB)에 압축본이 들어가고 `RUN unpack`, `RUN unpack-index` 층(22.7MB, 130MB)이 따로 쌓여 압축본과 풀린 본이 각각 다른 층에 있다.

### 조합별 이미지 크기 (S-05)

- 측정한 것은 **기본 조합 하나**(voyage-4 API, 로컬 모델 없음, `SEARCH_EMBED_MODEL`·`SEARCH_RERANK_MODEL` 빈 값)뿐이다. 1.17GB.
- 로컬 임베딩·리랭커 조합은 `--build-arg`로 `requirements-local-models.txt`(torch CPU판 등)와 모델을 받아야 해 이번에 만들지 않았다. 값 없음(미측정).

## 한계

- 조합별 이미지 크기는 기본 조합만 쟀다. 로컬 모델 조합(torch·sentence-transformers·모델 파일)은 빌드하지 않았다. 디스크 여유가 빌드 후 약 5GB로 줄어 추가 빌드를 하지 않았다.
- 빌드 시간은 Docker 빌드 캐시(2단계 적중)가 있는 PC 값이다. 완전히 새 PC의 첫 빌드(npm ci, pip 다운로드 전부)는 더 걸릴 수 있다.
- compose 시간은 이미지가 이미 빌드된 상태에서 쟀다(compose의 `--build`는 캐시 적중). 새 PC에서는 첫 빌드 시간이 더해진다. 같은 PC에서 한 번만 쟀다(반복 평균 아님).
- 실제 CPU 응답 시간은 재지 않았다(범위 밖).
- 이 PC에서 다른 컨테이너·작업이 동시에 Docker를 쓰고 있었다. 시간에 영향이 있을 수 있다.
- 정리: 내가 만든 이미지 3개(`provena-local:k11`, `k11measure-api`, `k11measure-loader`)와 compose 프로젝트(`k11measure`, 볼륨 포함)는 삭제했다. 빌드 캐시는 다른 작업과 섞여 있어 지우지 않았다.
