# docs/ : 문서

## 이 폴더가 하는 일

주제서(`TOPIC.md`), 아키텍처, 게이트 점검(`GATES.md`), 팀 작업 지침서(`TEAM_GUIDE.md`), 기능 Spec(`specs/`), 제출물(`deliverables/`), 매일 기록(`worklog.md`), 결정(`decisions.md`).

- 주인: 김승욱 (각자 자기 파트 절 작성)
- 입력: 없음
- 출력: 문서

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 김승욱 (Claude Code) | `specs/mcp.md` 도구 수 6개로 정정. `specs/incremental.md`에 `VOYAGE_API_KEY` 비밀값, 켜고 첫 실행 절차, 지금까지 실행 3건이 DATABASE_URL 없음으로 실패한 사실 추가. 정적 OpenAPI 명세 `api/` 폴더 추가 | 미정 |
| 2026-11-05 | 김승욱 (Claude Code) | `specs/question-graph.md`의 질문 분해 기본값 설명을 코드(기본 켬)에 맞추고 체크포인터 항목에 LangGraph 표 RLS를 적음. `specs/search.md` 환경 변수 표에 `SEARCH_HNSW` 추가 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | 로그인 연결에 맞춰 SPEC 4장(데모 계정·서명 키·구현 위치)과 ARCHITECTURE 계약표 김승욱 칸 채움 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | `docs/SPEC.md` 추가(범위, PRD 13-2 숫자 기준과 측정 방법, 데모 모드, 계약 위치). SDD 6장·TEAM_GUIDE 계약 사본을 `backend/schemas/`와 맞춤, `AgentEvent.data` 키 표 | 미정 |
| 2026-10-30 | 김승욱 (Claude Code) | GATES 상태 표 첫 갱신(PR #4~#15), pyproject·Makefile·`make test` 문구를 실제 설정(`backend/requirements.txt`, `pytest -q`)으로, D0 줄의 확인 항목 정리, 10/30 결정 3건(팀장 부재 시 머지, I-004, I-006), 세 사람 10/30 worklog | 미정 |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
