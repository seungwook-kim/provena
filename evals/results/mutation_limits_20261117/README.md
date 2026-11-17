# 새 상한 상수 변이 확인과 D5 변이 재실행 (2026-11-17, 커밋 1b38366e)

커밋 `1b38366e`(main, #181 머지)에 들어간 상한 세 종류(LLM 출력 상한, 사람당 하루 질문 한도, 외부 MCP 호출 제한)의 기본값을 하나씩 바꿔 시험이 실패하는지 확인하고, 기존 변이 도구 `tests/mutation_d5.py`(변이 18~33번)를 같은 커밋에서 다시 돌린 기록이다. LLM·네트워크 호출은 없고 비용은 0원이다.

- 작업 위치: 팀 작업 폴더가 아닌 별도 `git worktree`(1b38366e, detached). 변이마다 원본을 복구하고 바이트 단위로 같은지 확인했으며, 끝난 뒤 `git status`에 코드 변경이 남지 않았다(시험 파일 교체 실행에서 넣은 `tests/test_mcp_external_rate.py`만 바뀐 상태였다).
- 변이 18번의 결정표 승인 시험은 Postgres가 있어야 건너뛰지 않으므로, CI와 같은 이미지(`pgvector/pgvector:pg16`)의 임시 컨테이너를 띄워 `PROVENA_D5_PG_URL`로 넘겼다(실행 뒤 지움).
- 도구: `mutation_limits.py`(이 폴더, `tests/mutation_d5.py`와 같은 규칙. `python -I -X utf8 mutation_limits.py <저장소 루트> [번호 ...]`), `python -I -X utf8 tests/mutation_d5.py <번호>`(번호마다 따로 실행).

## 1. 새 상한 상수 변이

외부 MCP 한도 시험은 기본값 30을 인자로 넘겨 비교했기 때문에, 상수 `DEFAULT_EXTERNAL_RATE_PER_MIN`·`DEFAULT_EXTERNAL_RATE_PER_DAY`를 바꿔도 통과했다. `tests/test_mcp_external_rate.py`에 시험 2개를 더했다.

- `test_default_limits_are_literal_30_per_min_500_per_day`: 두 상수를 값(30, 500)으로 단언한다.
- `test_app_without_rate_env_uses_30_and_500`: 한도 환경 변수가 없을 때 `mcp_http_app`이 제한기를 분당 30, 하루 500으로 만드는지 본다(연결 코드가 상수를 넘기는지).

| 번호 | 파일 | 변이 | 확인한 시험 | 시험 추가 전 | 시험 추가 뒤 |
|---|---|---|---|---|---|
| L1 | `backend/services/llm.py` | `DEFAULT_LLM_MAX_TOKENS = 2500` → 3000 | `tests/test_llm_max_tokens.py` | 잡음(14 실패) | 잡음(14 실패) |
| L2 | `backend/services/llm.py` | `TASK_MAX_TOKENS`의 `"single": 4000` → 5000 | `tests/test_llm_max_tokens.py` | 잡음(2 실패) | 잡음(2 실패) |
| L3 | `backend/api/daily_limit.py` | `DEFAULT_DAILY_QUESTION_LIMIT = 50` → 60 | `tests/test_daily_limit.py` | 잡음(4 실패) | 잡음(4 실패) |
| L4 | `extras/mcp_skill/mcp_server/server.py` | `DEFAULT_EXTERNAL_RATE_PER_MIN = 30` → 60 | `tests/test_mcp_external_rate.py` | 못 잡음(12 통과) | 잡음(2 실패) |
| L5 | `extras/mcp_skill/mcp_server/server.py` | `DEFAULT_EXTERNAL_RATE_PER_DAY = 500` → 1000 | `tests/test_mcp_external_rate.py` | 못 잡음(12 통과) | 잡음(2 실패) |
| L6 | `extras/mcp_skill/mcp_server/server.py` | `mcp_http_app`의 하루 한도 인자 `DEFAULT_EXTERNAL_RATE_PER_DAY` → 0(제한 없음) | `tests/test_mcp_external_rate.py` | 못 잡음(12 통과) | 잡음(1 실패) |

출력 원문: `limits_test_before_fix.txt`(커밋 1b38366e의 시험 파일 그대로), `limits_test_after_fix.txt`(시험 2개를 더한 파일). 변이 전 실행은 모든 경우 통과였다.

## 2. `tests/mutation_d5.py` 재실행 (변이 18~33번)

16건 모두 대상 줄이 1b38366e 코드에 그대로 한 번씩 있었고, 16건 모두 잡았다(변이 전 통과, 변이 뒤 실패). 실패 수는 2026-11-13 기록(`evals/results/d10_evidence_4c8d8bc/mutation/mutation_d5_output.txt`)과 같다. 출력 원문: `mutation_d5_1b38366e.txt`.

## 3. 변이 2번을 현재 줄로 다시 실행

`docs/GATES.md` 변이 표 2번의 대상 문자열 `merge_chunks(state.get("chunks", []), found)`는 1b38366e 코드에 없다(같은 합치기는 `backend/graph/build.py`의 `search` 안 `merged = merge_chunks(state.get("chunks", []), found, limit=cap)`로 바뀌었다). 이 줄의 첫 인자를 빈 목록으로 바꾸면(재검색 결과만 남김) `tests/test_question_graph.py::test_requery_keeps_first_search_chunks_so_their_citation_survives`가 실패했다(잡음, 변이 전 1 통과, 변이 뒤 1 실패). 출력 원문: `mutation_2_current_line.txt`.

## 대상 문자열 확인 (변이 1~17번)

변이 1~17번은 스크립트 없이 문장으로 적힌 변이라 다시 돌리지 않았다. 대상 문자열이 1b38366e의 `backend/graph/build.py`에 있는지만 세었다. 2번 문자열만 0건이고(위 3절), 나머지는 1건 이상 있다(여러 곳에 있는 문자열은 어느 곳을 바꿨는지 문장만으로는 정해지지 않는다).
