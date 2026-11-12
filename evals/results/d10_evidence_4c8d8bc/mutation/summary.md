# 변이 확인 실행 요약 (main 4c8d8bc, 2026-11-13)

현재 main 4c8d8bc를 새로 clone한 별도 사본에서 `python -I tests/mutation_d5.py`를 실행했다. 변이마다 핵심 코드 한 줄을 깨뜨리고 그 줄에 걸린 시험 묶음이 실제로 실패하는지 본 뒤 원본을 복구한다(`docs/GATES.md` 변이 확인 표 18~33번). 키, 네트워크, LLM 호출이 없고 비용은 0원이다.

- 종료 코드 0, 실행 시간 약 302초(PC 부하에 따라 달라짐)
- 변이 16건 모두 변이 뒤 시험이 실패했다(판정 `잡음`). 서로 다른 파일 9개: `backend/graph/build.py`, `backend/graph/decision/execute.py`, `backend/graph/grounding.py`, `backend/graph/multi.py`, `backend/graph/recall/digest.py`, `backend/graph/recall/impact.py`, `backend/rag/retrieve/search.py`, `backend/services/auth_store.py`, `evals/retrieval/experiment_v1.py`
- 실행 뒤 사본의 `git status`는 비어 있었다(모든 변이가 원래대로 복구됨)
- 원본 출력은 `mutation_d5_output.txt`(UTF-8)이다. 실패 수는 `docs/GATES.md` 표의 값(18번 3개, 19번 118개, 20번 20개, 21번 1개, 22번 3개, 23번 1개, 24번 6개, 25번 2개, 26~29번 각 1개, 30번 2개, 31번 2개, 32·33번 각 1개)과 같다.

| # | 깨뜨린 파일 | 변이 전 | 변이 뒤 | 판정 |
|---|---|---|---|---|
| 18 | `backend/graph/decision/execute.py` | 52 passed in 43.97s | 3 failed, 49 passed in 50.78s | 잡음 |
| 19 | `backend/graph/multi.py` | 659 passed in 20.95s | 118 failed, 541 passed in 25.56s | 잡음 |
| 20 | `backend/graph/multi.py` | 659 passed in 22.20s | 20 failed, 639 passed in 25.19s | 잡음 |
| 21 | `backend/graph/grounding.py` | 3 passed in 0.04s | 1 failed, 2 passed in 0.11s | 잡음 |
| 22 | `backend/graph/grounding.py` | 172 passed in 4.35s | 3 failed, 169 passed in 4.32s | 잡음 |
| 23 | `backend/graph/grounding.py` | 761 passed in 22.42s | 1 failed, 760 passed in 22.08s | 잡음 |
| 24 | `backend/graph/build.py` | 6 passed in 0.76s | 6 failed in 0.81s | 잡음 |
| 25 | `backend/rag/retrieve/search.py` | 6 passed in 0.14s | 2 failed, 4 passed in 0.24s | 잡음 |
| 26 | `backend/graph/recall/digest.py` | 4 passed in 0.04s | 1 failed, 3 passed in 0.11s | 잡음 |
| 27 | `backend/graph/recall/digest.py` | 4 passed in 0.05s | 1 failed, 3 passed in 0.11s | 잡음 |
| 28 | `backend/graph/recall/impact.py` | 9 passed in 0.62s | 1 failed, 8 passed in 0.73s | 잡음 |
| 29 | `backend/graph/recall/impact.py` | 9 passed in 0.63s | 1 failed, 8 passed in 0.74s | 잡음 |
| 30 | `backend/graph/recall/impact.py` | 9 passed in 0.64s | 2 failed, 7 passed in 0.73s | 잡음 |
| 31 | `evals/retrieval/experiment_v1.py` | 3 passed in 0.13s | 2 failed, 1 passed in 0.24s | 잡음 |
| 32 | `backend/services/auth_store.py` | 2 passed in 2.69s | 1 failed, 1 passed in 2.85s | 잡음 |
| 33 | `backend/services/auth_store.py` | 2 passed in 2.68s | 1 failed, 1 passed in 2.74s | 잡음 |

1~17번은 `tests/mutation_d5.py`로 돌린 변이가 아니라(이 실행기에는 18번부터 들어 있다) 이 실행에 포함되지 않는다. 그 17건은 `docs/GATES.md` 표 아래 설명대로 따로 실행한 결과이다.