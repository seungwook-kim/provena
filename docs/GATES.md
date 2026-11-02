# 필수 게이트 자기 점검

게이트는 점수가 아니라 **못 지키면 고정으로 깎이는 조건**입니다. 가산점은 7개를 모두 충족한 조만 받습니다. 정의의 정본은 3차 프로젝트 가이드이고, 이 표는 "이 저장소 어디에서 채우는가"를 적은 것입니다.

팀에서 매주 금요일에 아래 표를 갱신하세요. 11/6 중간 점검에서 이 표를 봅니다.

| 게이트 | 증명하는 곳 | 평가자가 확인하는 방법 | 지금 상태 |
|---|---|---|---|
| G1 배포 주소 | README 팀 정보의 배포 주소 | 평가용 계정으로 접속해 핵심 시나리오를 끝까지 본다 | 진행 중. Cloud Run 주소에서 `/health` 응답 확인([PR #4](https://github.com/aihuman-7th/proj3-c/pull/4)). 로그인과 핵심 시나리오는 아직 |
| G2 한 줄 기동 | `docker-compose.yml`, `.env.example`, 데모 모드 | 새 clone에서 `docker compose up`, 10분 안에 뜨는지 실측 | 진행 중. 템플릿 compose로 `/health` 확인(`docs/worklog.md` 10/28). 로그인 연결 PR에서 `.env` 없이 `docker compose up --build` 1분 25초, 데모 user·admin 로그인·`/me`·로그아웃 실측(10/30, 캐시 있는 기계). LLM 데모 모드(키 없으면 녹화 재생·결정적 가짜 응답, [PR #26](https://github.com/aihuman-7th/proj3-c/pull/26)) 머지. `HF_HUB_OFFLINE=1`에서 검색 기본 모델(arctic-embed-l-v2.0 임베딩, mmarco-mMiniLMv2·bge-reranker-v2-m3 리랭커)이 캐시만으로 불러와지고 인코딩되는 것 확인(11/1, CPU). 문서 100건 속도 실측과 1만 청크 환산(체크포인트 Before D1-1): `evals/results/speed100/speed100.md`. 새 clone 10분 실측, 모델 캐시를 이미지에 넣는 방법, 스냅샷 적재는 아직 |
| G3 코퍼스 | `data/manifest.jsonl`, `data/corpus.tar.gz`(원문 스냅샷) | 서로 다른 청크(본문 sha256 기준) 1만 개 이상, 문서 50건 이상, 파싱 1종 이상 | **충족(숫자): 서로 다른 청크 22,378(본문 sha256, 기준 1만), 문서 1,565(manifest 행, 청크가 있는 문서 1,512, 기준 50), 파싱 1종(Markdown 표·HTML 표).** 원문 대조 4건(`EVAL_REPORT.md` 1장, 기준 3건). 체크포인트 조별 체크포인트 현황판 G3 표시 확인(11/1): GitHub GraphQL이 773KB manifest를 잘라 읽지 못하던 것을 489KB로 줄여 해결([PR #30](https://github.com/aihuman-7th/proj3-c/pull/30)). 코퍼스 고정 커밋은 `data/data.md`. 경과: 수집 규칙(고른 17개 폴더, 1,564쪽) 머지([PR #5](https://github.com/aihuman-7th/proj3-c/pull/5)), 페이지 id 10자리([PR #6](https://github.com/aihuman-7th/proj3-c/pull/6)), git 원본 받기·저장([PR #7](https://github.com/aihuman-7th/proj3-c/pull/7)), 2023 권한표·개정 이력 수집과 단축코드 전처리([PR #11](https://github.com/aihuman-7th/proj3-c/pull/11)), Markdown 파싱 1종(markdown-it-py, [PR #12](https://github.com/aihuman-7th/proj3-c/pull/12)), 1,561쪽을 요소 85,388개로 파싱·권한표 363칸·원문 대조([PR #13](https://github.com/aihuman-7th/proj3-c/pull/13)), 페이지별 판 날짜(I-001, 판 643종, "2023-12-01 이전" 25쪽, [PR #18](https://github.com/aihuman-7th/proj3-c/pull/18)), 2023 권한표 표 밖 글 103요소(I-007, [PR #19](https://github.com/aihuman-7th/proj3-c/pull/19)) 머지. 청킹 머지: 청크 23,095, 서로 다른 본문 지문 22,378로 1만 개 넘음, 빠진 요소 0([PR #23](https://github.com/aihuman-7th/proj3-c/pull/23)). 원문 스냅샷 `data/corpus.tar.gz`(압축 한 파일, 풀 때 수집 sha256 대조), `data/manifest.jsonl`(문서 1,565), `data/chunks_index.jsonl`(청크 23,095, 서로 다른 chunk_sha256 22,378) 커밋 |
| G4 에이전트 | `backend/graph/`, `backend/auth.py`, `backend/memory/` | 코드와 시연. 평가용 계정 2개로 대화와 기억이 섞이지 않는지 | 진행 중. 질문 그래프 Spec 초안(`docs/specs/question-graph.md`), 그래프와 기억은 미착수. 로그인 API(`backend/auth.py`) [PR #9](https://github.com/aihuman-7th/proj3-c/pull/9), `current_user_id()`·로그인 실패 제한·더미 해시 [PR #14](https://github.com/aihuman-7th/proj3-c/pull/14), ID 5회·IP 30회 제한 분리 [PR #15](https://github.com/aihuman-7th/proj3-c/pull/15) 머지. `backend/main.py` 연결과 users 테이블·데모 계정 시드는 다음 PR. LLM 호출 한 곳(`backend/services/llm.py`, [PR #26](https://github.com/aihuman-7th/proj3-c/pull/26)) 머지. 검색 `search()` Spec([PR #25](https://github.com/aihuman-7th/proj3-c/pull/25)) 머지, 인계 11/4 |
| G5 평가 | `evals/`, `EVAL_REPORT.md` 2장, 3장 | 평가셋 50건 이상(동결 시점 기준, 관련과 비관련 각각 절반), 개선 전후 두 번 이상, 차이는 문항 목록과 함께 | 진행 중. `evals/dataset_v1.jsonl`에 v1 질문 30건(관련 15, 비관련 15)을 올렸고 두 판정자 판정 완료(30건 모두 Y). 위치가 갈린 5건(1·6·7·11·14번)은 두 판정자가 합의해 최종 정답 칸에 적었다. **v1 동결: 2026-11-01, sha256 `174996b9b499da38f739f700854e919bf7f122c3bbffb6c73021d31a1e9f4332`, 30건(관련 15, 비관련 15), `evals/FROZEN.json`.** 동결 검사 변이 확인(11/1): 사본에서 평가셋 한 글자를 바꾸면 `freeze.py --check`(종료 코드 1)와 `tests/test_frozen_evals.py`가 실패한다. 제외 파일 `evals/exclusions.json`(빈 목록)을 둔다. **베이스라인(11/2): `bge-m3`, 한국어 질문 벡터 검색, 리랭커 없음, Recall@5 0.700, MRR 0.602, `evals/results/baseline_v1/`, `EVAL_REPORT.md` 3장.** **커밋 순서(가이드 p.14 "평가셋과 Spec 커밋이 첫 구현 커밋보다 앞서야"):** Spec은 지켰다(수집 Spec `d1b6da0`이 첫 구현 커밋 `c8ef35f` 10/29 17:22보다 앞). 평가셋은 못 지켰다. 질문 30건 커밋 `a282956`(10/30 05:11)이 첫 구현 커밋보다 약 12시간 늦다. 첫 구현은 핸드북 수집 규칙이었고 검색·답변 코드는 아직 없었다. 이력은 고치지 않고 이 사실을 그대로 둔다 |
| G6 트레이스 | Langfuse 프로젝트, `EVAL_REPORT.md` 7장 | 대시보드에서 트레이스와 평가 점수가 연결되어 있는지 | 진행 중. Langfuse 콜백 핸들러와 `cost_usd` 점수 기록 코드(`backend/services/tracing.py`, [PR #26](https://github.com/aihuman-7th/proj3-c/pull/26)) 머지. 그래프 연결과 대시보드 확인은 아직 |
| G7 제출물 | README, `.env.example`, `docs/deliverables/` | 비밀값 커밋 없음, 3분 이내 시연 영상(정상 경로와 실패 경로) | 미착수 |

마지막 갱신: 2026-11-02 김승욱 (PR #31까지 반영, G5 베이스라인 기입)

## 상태 표기

`미착수` / `진행 중` / `충족` / `증거 보강 필요` 중 하나로 적고, 충족이면 **증거 링크**(파일, PR, 대시보드)를 같이 적으세요. 링크 없는 "충족"은 평가에서 인정되지 않습니다.

## 자주 놓치는 것

- G2: 평가자에게는 API 키가 없습니다. 키가 없으면 죽는 서비스는 G2를 못 넘습니다.
- G2: 로컬 모델(임베딩, 리랭커)을 쓰면 평가자 컴퓨터에서 내려받기가 막히거나 오래 걸립니다. `HF_HUB_OFFLINE=1`과 `local_files_only=True`를 쓰고, 모델 캐시 크기(예: KURE-v1 약 2.1GB, bge-reranker-v2-m3 약 2.1GB)를 README에 적으세요. 서버 기동 시 모델을 미리 올려(`warmup()`) 첫 질문이 느려지지 않게 합니다.
- G3: "청크 1만 개"는 서로 다른 청크입니다. 같은 문서를 복제하거나 약간 바꾼 것은 세지 않습니다. 정정공시처럼 본문이 같은 문서가 둘이면 한 개로 칩니다(DART 실험에서 11,022청크 중 서로 다른 청크는 11,008개였습니다). 본문 sha256으로 세세요.
- G4: 단일 에이전트로 되돌리는 것은 허용되지 않습니다. 11/6 중간 점검에서 분리를 확인합니다.
- G5: 한 번 재고 끝내면 미충족입니다. 어느 문항이 회귀했는지가 보여야 합니다. 차이가 1~4문항이면 "개선"이라 쓰지 말고 달라진 문항 목록을 적으세요.
- G5: 검색 결과를 후처리로 걸러 0~2개로 줄이면 "우연한 거절"이 생겨 점수가 실제보다 좋게 나올 수 있습니다. 검색 단계에서 필터를 걸거나, 후처리를 쓴다면 이 효과를 따로 보고하세요.
- G7: 시연 영상에는 잘 되는 경로만이 아니라 실패하는 경로도 들어가야 합니다.

## G4와 G5의 "통과"는 증거가 아닙니다: 변이 확인

테스트가 초록이라는 것은 아무것도 단언하지 않는 테스트도 초록이라는 뜻입니다. 핵심 코드를 **한 줄 깨뜨렸을 때 그 테스트가 실제로 실패하는지** 확인하고 기록하세요. 사례: 재작성 횟수 상한 테스트가 상수끼리 비교하면(`assert n == MAX_REWRITES`) 상한을 99로 올려도 통과합니다. 리터럴과 비교해야(`assert n == 2`) 상한 변경을 잡습니다. AI 에이전트가 "변이를 잡았다"고 보고해도 직접 확인하세요. DART 실험에서 그 보고가 틀렸습니다.

3건 이상을 적습니다.

| # | 깨뜨린 곳 (파일, 한 줄) | 실패해야 하는 테스트 | 실제로 실패했는가 | 확인한 날 |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
