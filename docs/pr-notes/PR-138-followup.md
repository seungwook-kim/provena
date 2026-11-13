# #138 후속 — 기록 칸 채우기, 작업 내역 이름 정리, D0~D8 정리, 포트폴리오 보강, SDK 링크, 문서·코드 맞추기
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: origin/main `b541e97a`(#145까지)를 합친 브랜치 `pr138-followup` + 갈래 `sdk-links`, `docs-align-1113`을 git merge로 묶음
- 근거 종류 표기: [코드] `파일:줄` / [문서] 팀 문서 / [실측] 직접 돌린 결과 / [추정].
- 운영 호출 없음(조장 11/13 배포·운영 측정 중 운영 시험 중지 요청). LLM·Voyage 호출 없음. 코드 동작은 바꾸지 않았다(문서·SDK 설명·생성 스크립트 후처리·`.gitattributes`만).

## 1. 한 것
| 항목 | 무엇 | 근거 |
|---|---|---|
| 기록 칸 `미정` | 박진형 행 38칸을 실제로 머지된 PR 번호로 채움(#132 26칸, #138 12칸). 남의 행은 건드리지 않음 | [실측] 행마다 `git blame`으로 그 줄을 넣은 커밋을 찾고, 그 커밋을 처음 담은 main의 머지 커밋(첫 부모 줄)에서 PR 번호를 읽음. 바뀐 낱말은 `미정` → `#번호` 38개뿐(`git diff --word-diff`) |
| 작업 내역 이름 | `docs/pr-notes/PR-next.md` → `PR-138.md`. 머리말(PR 번호·머지 시각), 빠져 있던 프론트 버그 수정·화면 안내 절(2-0), 5절 숫자(vitest 369, pytest 3550)를 채움. 이 이름을 가리키던 `docs/docs.md`·`ai_tools_log.md` 두 곳도 고침 | 지침 "PR마다 `PR-<번호>.md`", 미정은 머지 직후 후속 커밋으로(팀원 기록 규칙). 프론트 숫자 출처는 그 작업의 검증 기록(11/12) |
| D0~D8 정리 | `docs/deliverables/work-summary-박진형.md` 새 파일. 11/11 main `54f8e37`(#125 직후) 기준 그대로이고 그 뒤 PR은 넣지 않음(진형 결정 11/13). 결과 파일 이름 2개만 AI 도구 이름이 들어 있어 "결과 JSON 2개"로 바꿈 | 11/11 조장 지적(진형 작업 문서 없음) 뒤 만든 문서가 PR에 실리지 않았다 [실측: 모든 브랜치 이력에서 이 파일 0건] |
| M-22 포트폴리오 | `portfolio-박진형.md` 숫자 표에 LangGraph 승인·재개 줄, 멀티에이전트 줄(정책 질문 단일 대 멀티, 합동 검토 팀 대 1인)을 "팀 결과"로 더함. "차이 없음"도 그대로 적음 | 체크포인트 D12 "포트폴리오 1장(LangGraph, 멀티에이전트, 평가, 관측의 수치 포함)". 전에는 `LangGraph`·`멀티` 0건이었다. 숫자 출처 `EVAL_REPORT.md:503`, `:514-515`, `:592` |
| 포트폴리오 줄 번호 | main을 합친 뒤 `EVAL_REPORT.md` 줄이 밀려(#142~#145에서 +94 −61) 근거 줄 3곳을 새 줄로 고침: 배포 답변 행 `686, 687, 892, 704` → `686, 687, 874, 901~905, 709`(조장이 #143에서 00047 값으로 바꾼 행), 배포 실측 `804, 805` → `809, 810`, 관측 `822` → `827`. 기준 커밋 표기 `3225f107` → `b541e97a` | [실측] 표의 숫자 36개를 근거 줄에서 찾는 스크립트: 고치기 전 11개 불일치 → 고친 뒤 0 |
| C-26 SDK README 링크 | `mock_erp/sdk/java/README.md`(142개)·`python/README.md`(89개)의 없는 파일로 가는 상대 링크를 글자만 남기고 풂. 새 `mock_erp/sdk/strip_dead_links.py`를 `generate.sh` 끝에서 불러 다시 생성해도 유지. `sdk.md`에 후처리 한 줄 | [코드] `generate.sh`가 `apiDocs=false,modelDocs=false`로 문서 페이지를 만들지 않는데(`sdk.md:21` "크기 절감") README 표는 그 페이지를 링크했다. [실측] 깨진 링크 231 → 0, 원래 맞던 링크(http 4, 앵커 2)는 그대로, 바뀐 줄은 링크 줄뿐(142·89줄), `.java`·`.py` SDK 소스 변경 0, `tests/test_sdk_matches_openapi.py` 3 passed |
| K-03 PRD 라이브러리 표 | `docs/PRD.md` 9장 BM25 `bm25s` → `rank-bm25`(`BM25Okapi`), bcrypt `5.0.0` → `>=4.2,<5`, 저장 행 `langchain-postgres` → `pgvector`·`psycopg` 직접 SQL. 하단 주석 줄 번호 `search.py:607` → `:622` | [코드] `backend/rag/retrieve/search.py:622` `from rank_bm25 import BM25Okapi`, `backend/requirements.txt:8`·`:17-19`, `backend/`에 `bm25s`·`langchain_postgres` import 0건 |
| O-07 SDD LangChain | `docs/SDD.md:50` "LangChain 채팅 모델" → 채팅 모델(`langchain-anthropic`·`langchain-openai`, `services/llm.py`)과 `langchain_core` 메시지·콜백·Runnable 타입에만 쓴다 | [코드] `langchain_openai`·`langchain_anthropic` import는 `llm.py`에만 있고 다른 곳은 `langchain_core`만 |
| M-14 AGENTS.md | 주장 19개를 코드와 대조, 틀린 2개 고침: `SEARCH_MODE` 위치 `search.py:82` → `:77`, "LLM 호출은 `llm.py`에서만"에 평가 스크립트 예외(`evals/latency/deploy_ragas.py:265`)와 임베딩 호출(`embed.py`)을 적음 | [코드] 대조표는 7절 |
| F-10 DocumentSource 한계 | 연결하지 않고 한계로 기록(진형 결정 11/13): `docs/SDD.md:52` 모듈 표·디렉토리 트리, `backend/rag/ingest/ingest.md` "알려진 한계" | [코드] `source.py:7`, 쓰는 곳은 `source.py`와 `tests/test_ingest_source.py`뿐, `schedule.py` import(`:33-36`)에 없음 |
| L-27 평가셋 줄바꿈 고정 | `.gitattributes`에 `evals/dataset_holdout_v1.jsonl`·`evals/dataset_cite_new_v1.jsonl` `text eol=crlf` 두 줄과 해시 출처 주석. 이 고정으로 틀린 말이 된 `EVAL_REPORT.md` 두 문장(1절 해시 설명 "지정이 없어 … 달라지며", 9장 재현 명령 주석)을 "2026-11-13부터 CRLF 고정"으로 고침 | [실측] `core.autocrlf=false`로 새로 clone하면 두 파일 sha256이 문서 값(`c877c065…`, `8823195a…`, `EVAL_REPORT.md`)과 같다. 저장소 안 blob은 그대로(LF), `python evals/freeze.py --check` 통과 |

## 2. 진형이 결정한 것
| 결정 | 고른 것 | 왜 | 버린 대안 |
|---|---|---|---|
| #138 후속을 누가 | 이 PR 하나에서 놓친 것 쪽과 프론트 쪽 행을 다 채움 | 같은 파일(`docs/docs.md`, `ai_tools_log.md`, `web/web.md`)을 두 작업이 나눠 고치면 다시 충돌한다 | 작업마다 따로 후속 PR |
| D0~D8 정리 | 11/11 기준 그대로 올림 | D0~D8 기간 정리라서 그 뒤 일을 섞지 않음. 그 뒤 일은 PR마다 작업 내역(`PR-*.md`)에 있다 | 11/12까지로 다시 씀 |
| 포트폴리오 멀티에이전트 줄 | 팀 결과로 표시하고 "차이 없음"을 그대로 적음 | 그래프·Supervisor는 김승욱 몫이다. 가이드는 부풀리지 말고 전후를 함께 쓰라고 함 | 넣지 않음(체크포인트 요구 미충족), 좋은 숫자만 적음 |
| SDK 링크 | 링크를 푸는 후처리 | 문서 페이지 생성(`apiDocs=true`)은 `sdk.md:21` 크기 절감 결정을 뒤집고 파일 수십 개가 늘며, 재생성이 소스를 바꿀 위험이 있다 | 문서 페이지 생성 |
| F-10 | 한계로 기록 | 동결(11/16) 전 수집 경로를 바꾸면 청크 23,095개 재현성 시험을 다시 해야 한다 | `handbook.collect()`를 `DocumentSource`로 연결 |

## 3. 동결 전 로컬 확인 중 남은 것
Q-24(키 없는 기동)·K-22(main pytest)·Q-21·K-16은 조장 #142 D10 증거로 정리됐고, K-19(README 질문)는 조장이 확인해 이 절에서 뺐다.
| 항목 | 결과 |
|---|---|
| README Windows clone | Windows에서 README의 `git clone`(README:123)을 그대로 하면 `data/pdf/...` 경로가 길어 체크아웃이 실패한다(`Filename too long`). `git -c core.longpaths=true clone`으로는 된다 [실측, 11/13]. README는 조장 파일이라 고치지 않고 알림 |
| L-28 동결 목록 | `evals/FROZEN.json`은 v1·v2만 담는다. 검증 문항은 동결 목록 밖에 두고 `--dataset-sha256`으로 확인하는 설계다 [코드: `evals/agent/exp_multi_v2.py:357`]. 빠뜨린 것이 아니라 설계이므로 놓친 것에서 뺀다 |

## 4. 확인한 것
| 대상 | 결과 |
|---|---|
| 포트폴리오 인용 | 표의 숫자 36개가 모두 근거 줄에 있음(`EVAL_REPORT.md` main `b541e97a`) [실측] |
| 갈래별 독립 검증 | SDK 링크·문서 맞추기 갈래마다 작업과 다른 검증자가 diff만 보고 다시 셈(깨진 링크 수, 인용 줄, 새 clone 해시) [실측] |
| AI 표기 검사 | 커밋 메시지 0. 추가 줄 1건은 원래 있던 `docs/docs.md` 행(`.claude/skills/` 경로를 가리키는 #132 기록)의 PR 칸만 바꾼 것이라 새 표기 0(`ai_tools_log.md` 제외) |

## 5. 남의 폴더 (조장 확인 필요)
- `docs/`(조장): `docs/docs.md` 기록 칸·행, `docs/pr-notes/`(이름 바꾸기, 이 문서), `docs/PRD.md` 9장 표, `docs/SDD.md:50·52`·트리.
- `docs/deliverables/`(조장): `work-summary-박진형.md`(새 파일, 본인 정리), `portfolio-박진형.md`(본인 제출물), `ai_tools_log.md` 한 줄과 이름 바꾼 곳.
- `mock_erp/`(조장): `mock_erp/sdk/`(SDK는 박진형이 만듦, SDD:661) README·`generate.sh`·새 스크립트·`sdk.md`, `mock_erp/mock_erp.md` 한 행.
- 공동: `AGENTS.md` 2곳, `.gitattributes` 두 줄과 주석.
- 루트(조장): `EVAL_REPORT.md` 두 문장(검증 20건 줄바꿈 설명). 열린 #146이 고치는 줄(17·25·668~760·1001)과 겹치지 않음 [실측: `git diff origin/main...pr/146` 범위].
- 기록 칸만 고친 폴더: `backend/`, `backend/graph/recall/`, `backend/memory/`, `db/`, `data/LICENSES/`, `web/` — 박진형 행의 PR 칸만.

## 6. 한계·남은 일
- C-14(수집 실행 501의 안내 문구가 꺼진 정시 수집을 쓰라고 함)는 조장 결정 기록(`docs/decisions.md:12`, `SDD.md:367`)과 같은 문장이라 고치지 않고 조장 질문으로 남김.
- README Windows clone 안내, `README.md`·`docs/GATES.md`의 pytest 숫자(11/10 값)는 조장 파일이라 알림만.
- PRD 9장 `langfuse` 행(`5.0.4`)과 `requirements.txt:12`(`langfuse>=4`)가 다르고, `docs/decisions.md:19`의 줄 참조가 낡았다 — 결정 기록·범위 밖이라 그대로 둠.
- `AGENTS.md`는 `SEARCH_MODE` 위치를 줄 번호로 적어 코드가 바뀌면 또 낡는다.
- SDK README 표에서 메서드별 상세 문서로는 이동할 수 없다(링크를 풀기만 함).
- 이 PR 번호가 나오면 이 문서를 `PR-<번호>.md`로 바꾸고 기록 칸 `미정`을 채운다.

## 7. M-14 AGENTS.md 대조표
| 주장 | 근거 | 결과 |
|---|---|---|
| `SEARCH_MODE` 기본 `dense_en`, `search.py:82` | 실제 `search.py:77` | 고침 |
| LLM 호출은 `llm.py`에서만 | `backend/` 직접 import는 `llm.py`뿐, 평가 스크립트 `evals/latency/deploy_ragas.py:265` 예외, 임베딩은 `embed.py` | 고침(예외 명시) |
| `LLM_MODEL` 기본값 `llm.py:67` | `llm.py:67` | 맞음 |
| `LLM_PROVIDER` 선택지는 `docs/specs/llm.md` | `llm.md:10` | 맞음 |
| Python 3.12 | `Dockerfile:10`, `ci.yml:23` | 맞음 |
| `voyage-4` 1024차원 | `embed.py:51` | 맞음 |
| BM25·리랭커 기본 미사용 | `EVAL_REPORT.md` 3-2절 | 맞음 |
| 로컬 모델은 서비스 이미지에 안 넣음 | `requirements-local-models.txt` 분리 | 맞음 |
| 데모는 compose pgvector | `docker-compose.yml:61` | 맞음 |
| MCP는 FastMCP | `requirements.txt:25`, `extras/mcp_skill` | 맞음 |
| Langfuse | `requirements.txt:12`, `tracing.py:97` | 맞음 |
| 문서 위치(PRD 9장, TEAM_GUIDE 5장, SDD 3장, SCAFFOLD, `_example.md` 다섯 섹션, FROZEN·PREREGISTER, requirements-dev, SPEC, ai_tools_log, ingest.md, data.md 고정 커밋, `pytest -q`) | 파일·줄 확인 | 맞음 |
| 비용 한도·요청 간격·User-Agent | 팀 규칙·가이드 인용이라 코드로 확인 안 함 | 그대로 |
