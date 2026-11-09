# docs/ : 문서

## 이 폴더가 하는 일

주제서(`TOPIC.md`), 아키텍처, 게이트 점검(`GATES.md`), 팀 작업 지침서(`TEAM_GUIDE.md`), 기능 Spec(`specs/`), 제출물(`deliverables/`), 매일 기록(`worklog.md`), 결정(`decisions.md`).

- 주인: 김승욱 (각자 자기 파트 절 작성)
- 입력: 없음
- 출력: 문서

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
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
