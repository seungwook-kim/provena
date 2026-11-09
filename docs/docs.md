# docs/ : 문서

## 이 폴더가 하는 일

주제서(`TOPIC.md`), 아키텍처, 게이트 점검(`GATES.md`), 팀 작업 지침서(`TEAM_GUIDE.md`), 기능 Spec(`specs/`), 제출물(`deliverables/`), 매일 기록(`worklog.md`), 결정(`decisions.md`).

- 주인: 김승욱 (각자 자기 파트 절 작성)
- 입력: 없음
- 출력: 문서

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-10 | 김승욱 (Claude Code) | 운영 리비전 00030 질문 쪽 주입 시험에서 4건(INJ-P2-V5, INJ-P10-V5, INJ-P2-V6, INJ-P1-V12)이 `뚫림`으로 판정된 결함 수정. 모델이 지시를 따른 것이 아니라, 모르는 이름 되묻기(`backend/graph/build.py`의 `search`, `answer_fixes.py`의 `unknown_name_message`, `GRAPH_UNKNOWN_NAME`)가 질문 속 지시 문장의 따옴표·대문자 토큰을 "질문의 'CANARY-…'은(는) 핸드북 자료에서 찾지 못했습니다"로 되풀이한 것임. 모르는 이름을 뽑기 전에 질문을 PR #88의 지시 문장 판정(`untrusted.strip_instructions`)으로 나누어, 지시로 판정된 절·문장·묶음 괄호에서 나온 문자열은 인용하지 않도록 바꿈(`answer_fixes.quotable_phrases`). 지시 판정이 놓친 의심 문장(표식 꼴 토큰 가까이에 출력 자리나 목적 이름표가 있는 문장)의 토큰도 같은 모듈의 출력 검사 판정(`is_suspect`)으로 빼며(`untrusted.drop_suspect_tokens`), 인용할 이름이 남지 않으면 문자열 없이 "질문에 핸드북 자료에서 찾지 못한 표현이 있습니다" 문구로 되묻는다. 새 단어 목록과 특정 표식 모양에 맞춘 규칙은 두지 않았고, 일반 질문 속 모르는 이름은 지금처럼 인용한다. 평가 질문 190건에서 되묻기에 인용될 이름 목록이 수정 전과 같음을 확인함. 시험은 `tests/test_answer_fixes.py`, `tests/test_answer_fixes_graph.py`(단일·멀티 그래프)에 추가 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | 체크포인트 검토에서 나온 문서 불일치 정정. `GATES.md` G1에 배포 리비전 이력(00020~00028)과 미확인 항목(재시작 뒤 승인 이어받기)을 적고 G6의 충족과 미확인 문구를 근거에 맞춤. `EVAL_REPORT.md` 6장에 배포 주소 시험(14, 20, 21행)과 로컬 인젝션 시험을 구분하는 문장과 21행 병합 사실, 7장 배포 트레이스 근거, 8장 Anthropic 전환 문장 추가. README 에이전트 구조 절에 4장 링크 한 줄 추가. `GATES.md` G2에 키 없는 새 clone 재측정 결과(`evals/results/g2_keyless_2026-11-09/`)를 적고, `evals/PREREGISTER.md` 안내에 "이후 사전 등록은 결과 파일보다 먼저 별도 커밋으로 올린다" 문장 추가. 배포 리비전 00029-qbd·00030-6t4 재측정(응답 시간 50건 x 3회, 계정 섞임 10건, 승인 경계 6건, 질문 쪽 주입 19건, 금액 구간 15건)을 `EVAL_REPORT.md` 5·6·8장, `GATES.md` G1, `PREREGISTER.md` 62.7에 반영하고 결과 파일과 점검 스크립트(`evals/safety/deploy_*_check.py`, `evals/retrieval/deploy_range_answers.py`)를 추가 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | 운영 금액 승인자 질문("외부 SaaS 도입, 계약 금액 5만 달러, 업무·재무 승인자") 15건이 모두 "결정표를 실행하지 않았습니다: task_type이 필요하다"로 거절된 결함 수정. 원인은 분류가 결정표 경로로 보낸 질문에서 값 뽑기가 승인된 업무 종류 목록과 맞는 항목을 찾지 못해 업무 종류를 비우면(`backend/graph/build.py`의 `decision_params`), 실행 단계(`decision/execute.py`)가 그 질문을 거절로 끝낸 것임. `/chat` 요청 본문과 화면은 `task_type`을 보내지 않으므로 측정 스크립트 문제가 아니라 서버 동작이다. 분류 단계(`classify`)가 결정표 경로로 정하기 전에 값 뽑기를 한 번 실행하고, 업무 종류가 비면 기존 "결정표를 실행할 수 없는 질문" 처리와 같이 일반 정책 경로(검색·금액 구간 검색·답 작성)로 보내도록 바꿈. 뽑은 값은 `decision_query`로 넘겨 값 뽑기를 두 번 부르지 않으며(`multi.py`의 결정표 에이전트도 같은 값을 읽음), 업무 종류가 있는데 승인된 표가 없거나 금액이 없는 질문은 이유를 밝히고 거절하는 기존 동작을 유지함. 시험 `tests/test_decision_wiring.py`에 단일·멀티 그래프, 병렬 접수 여부별 시험 추가 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `docker-compose.yml` db 상태 검사를 TCP(`pg_isready -h 127.0.0.1`)로 바꾸고 `retries` 40·`start_period` 10초로 늘림. 새 DB 첫 기동 때 초기화용 임시 서버(소켓만 열림)를 정상으로 판정해 loader가 `Connection refused`로 죽던 문제를 고침. loader(`load_snapshot.py`)에도 DB 접속 재시도(최대 60초) 추가 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `tests/test_safety_gaps.py` 청크 머리 시험 2건(`test_g2_header_fields_are_stripped`, `test_g2_title_attack_stays_inside_blocks_in_graph`) 실패 수정. 원인은 PR #88에서 입력 정화가 제목 속 "답 끝에 표식을 붙여라" 문장을 먼저 지우게 된 것이고, 시험은 그 문장이 블록 안에 남는다고 기대했음. 구분자 지우기 층만 보도록 두 시험에서 입력 정화를 끄고, 정화가 켜진 기본 상태에서 지시 문장이 빠지고 블록이 하나만 남는 시험 1건 추가. 코드는 바꾸지 않음 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `EVAL_REPORT.md` 5장 검색 실패 유형 분석과 `deliverables/failure_analysis.md` 초안 작성. 측정 결과 행을 직접 세어 10개 유형으로 묶고, 확인 못 한 원인은 "원인 확인 못 함"으로 표시 | 미정 |
| 2026-11-09 | 김승욱 (Claude Code) | `specs/mcp.md` 도구 수 6개로 정정. `specs/incremental.md`에 `VOYAGE_API_KEY` 비밀값, 켜고 첫 실행 절차, 지금까지 실행 3건이 DATABASE_URL 없음으로 실패한 사실 추가. 정적 OpenAPI 명세 `api/` 폴더 추가 | 미정 |
| 2026-11-05 | 김승욱 (Claude Code) | `specs/question-graph.md`의 질문 분해 기본값 설명을 코드(기본 켬)에 맞추고 체크포인터 항목에 LangGraph 표 RLS를 적음. `specs/search.md` 환경 변수 표에 `SEARCH_HNSW` 추가 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | 로그인 연결에 맞춰 SPEC 4장(데모 계정·서명 키·구현 위치)과 ARCHITECTURE 계약표 김승욱 칸 채움 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | `docs/SPEC.md` 추가(범위, PRD 13-2 숫자 기준과 측정 방법, 데모 모드, 계약 위치). SDD 6장·TEAM_GUIDE 계약 사본을 `backend/schemas/`와 맞춤, `AgentEvent.data` 키 표 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | GATES 상태 표 첫 갱신(PR #4~#15), pyproject·Makefile·`make test` 문구를 실제 설정(`backend/requirements.txt`, `pytest -q`)으로, D0 줄의 확인 항목 정리, 10/30 결정 3건(팀장 부재 시 머지, I-004, I-006), 세 사람 10/30 worklog | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
