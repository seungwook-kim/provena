# 50건 재생 CI 단계를 깨끗한 1b38366e에서 다시 돌린 기록 (2026-11-17)

`evals/results/ci_replay_local_20261117/`은 커밋 전 변경이 있는 작업 트리에서 돌려 결과 파일의 `commit` 칸(HEAD 값)과 실제로 돈 코드가 같다고 말할 수 없었다. 이 폴더는 같은 두 명령을 커밋 `1b38366e`(main, #181 머지)의 깨끗한 checkout에서 다시 돌린 기록이다. 결과 파일의 `commit` 칸은 두 실행 모두 `1b38366e`이고, 실행 직전 `git status`에 바뀐 파일이 없었다(아래 2번 실행에서 푼 `data/index/`는 `.gitignore` 대상이라 상태에 나타나지 않는다).

- 작업 위치: 팀 작업 폴더가 아닌 별도 `git worktree`(1b38366e, detached). Python 환경은 저장소의 `backend/requirements-dev.txt`로 만든 로컬 가상 환경.
- 비용: 0원. LLM·Voyage·운영 DB 호출 없음(`ci_current_eval.py`가 프로세스에서 키를 지우고 녹화 재생으로 돈다).
- Postgres: CI 서비스 컨테이너와 같은 이미지 `pgvector/pgvector:pg16`을 로컬 임시 컨테이너로 띄우고(접속 정보는 CI 파일과 같은 시험용 값, 포트만 55433), 끝난 뒤 지웠다.
- 로그 파일은 `.gitignore`의 `*.log` 규칙 때문에 같은 내용을 `.log.txt` 이름으로 저장했다(개인 경로·키 없음 확인).

## 실행한 명령

```
PROVENA_D5_PG_URL=postgresql://app:<시험용>@127.0.0.1:55433/postgres python evals/ci_current_eval.py --out <폴더>/ci_current_result.json --require-v2
python evals/ci_compare.py --current <폴더>/ci_current_result.json
```

2번 실행은 위 두 명령 전에 `python -m backend.rag.ingest.snapshot unpack-index`(커밋된 `data/index.tar.gz`를 `data/index/`로 풀고 `meta.json` sha256 대조)를 한 번 더 돌렸다.

## 결과

| 실행 | 시각(KST) | 조건 | 0원 평가 종료 코드 | 비교 종료 코드 | 50건 결과 | 폴더 |
|---|---|---|---|---|---|---|
| 1 | 10:51:52 ~ 10:53:33 | 새 checkout 그대로(`.github/workflows/ci.yml`의 단계와 같음) | 0 | 1(실패) | 관련 25건 중 인용 답 24, 비관련 25건 중 거절 25(되묻기 0), 녹화에 없는 요청 12(#23 2건, #25 10건), 발췌형 대체 답 0. 데모 질문 9개는 인용 답 7/7, 거절 2/2, 녹화에 없는 요청 0 | `1_clean_checkout/` |
| 2 | 11:00:06 ~ 11:03:08 | 새 checkout + 색인 압축 풀기(`unpack-index`) | 0 | 0(통과) | 관련 25건 중 인용 답 24, 비관련 25건 중 거절 24(되묻기 1), 녹화에 없는 요청 0, 발췌형 대체 답 0. 두 경로(추론 답 보냄, 빠른 답만) 같은 값 | `2_index_unpacked/` |

- 2번 실행의 문항별 결과(`rows`)는 `ci_replay_local_20261117/ci_current_result.json`의 문항별 결과와 모두 같다. 그 폴더의 실행은 팀 작업 폴더에서 돌았고, 그 폴더에는 풀린 `data/index/`가 있었다.
- 같은 1번 조건을 한 번 더 돌려도(같은 날 10:54 무렵) 같은 #23, #25에서 녹화에 없는 요청 12가 나왔다. 팀 작업 폴더(풀린 `data/index/` 있음)에서 같은 코드로 돌리면 0이었다. 이 두 확인 실행의 출력은 저장하지 않았다.

## 1번이 실패한 이유

`backend/graph/answer_fixes.py:689`의 `_CORPUS_FILES`는 "질문 속 영문 구가 코퍼스에 있는가" 검사(D1)에 `data/chunks/chunks.jsonl` 또는 `data/index/chunks.jsonl`을 읽는다. 둘 다 커밋하지 않는 폴더라 새 checkout에는 없고, 없으면 이 검사를 건너뛴다(`corpus_text`가 빈 문자열을 돌려준다). 50건 녹화는 풀린 색인이 있는 상태에서 만들어졌으므로, 영문 구가 들어 있고 코퍼스에 없는 비관련 질문 두 개(#23 "EU DORA …", #25 "… Critical PCL …")는 새 checkout에서 녹화 때와 다른 요청(분류 단계 요청과 질문 벡터)을 보내 녹화에 없는 요청으로 잡혔다. 서비스 이미지와 `docker compose`는 시작할 때 `data/index/`를 풀기 때문에 서비스 동작과 같은 조건은 2번이다.

`.github/workflows/ci.yml`에는 색인을 푸는 단계가 없으므로, GitHub Actions에서 이 단계를 그대로 돌리면 1번과 같은 결과가 나올 것으로 본다(Actions는 무료 한도 소진으로 11/9 이후 돌지 않아 실제로 확인하지는 않았다). CI 파일에 `python -m backend.rag.ingest.snapshot unpack-index` 단계를 더할지는 이 기록에서 정하지 않았다.

- 후속(2026-11-17): `.github/workflows/ci.yml`에 0원 평가 단계 바로 앞의 색인 압축 풀기 단계(`python -m backend.rag.ingest.snapshot unpack-index`)를 더했다(커밋 `17951939`). 같은 순서(색인 풀기 → `ci_current_eval.py --require-v2` → `ci_compare.py`)를 커밋 `639e49ad`의 깨끗한 `git worktree`에서 로컬로 돌린 결과 세 명령 모두 종료 코드 0(색인 `meta.json` sha256 같음, 50건은 두 경로 모두 관련 25건 중 인용 답 24, 비관련 25건 중 거절 24, 녹화에 없는 요청 0, 발췌형 대체 답 0, 비교 결과 통과)이었고, 실행 뒤 작업 트리에 생긴 파일은 결과 파일 `ci_current_result.json`뿐이었다(출력은 저장하지 않음).

## 읽는 법

- 50건 재생은 녹화(`evals/ci_replay_v2/`)를 만든 시점의 모델 응답을 다시 쓰는 회귀 검사다. 프롬프트·검색·입력이 바뀌면 "녹화에 없는 요청"이 0보다 커져 실패한다. 모델 품질을 새로 잰 값이 아니다.
- 1번의 비관련 거절 25(되묻기 0)는 녹화에 없는 요청이 생긴 문항(#25가 되묻기에서 거절로 바뀜)을 포함한 값이라 2번의 24(되묻기 1)와 같은 조건의 값이 아니다.
