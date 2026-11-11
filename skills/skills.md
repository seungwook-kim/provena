# skills/ : 런타임 Skill

## 이 폴더가 하는 일

에이전트가 쓰는 Skill(가산: MCP와 Skill). 폴더마다 `SKILL.md`를 두고 현재 13개다. 공통 `citation-rules`, `grounding-check`, `glossary`, 권한표 해석 `delegation`, 합동 검토 팀 관점 `security`·`finance`·`infra`·`itops`와 쟁점표 작성 `report-writing`, 질문 경로 `chat-tool-guide`·`search-terms`(`GRAPH_REQUERY_TERMS` 켠 때만 판정에 붙음), 리콜 `mail-templates`, 검색 평가 `retrieval-slots`. 공통 Skill 목록은 `backend/services/skills.py`의 `SKILL_NAMES`, 팀 관점 Skill은 `backend/graph/departments/teams.py`가 읽고, `USE_SKILLS`로 전부 켜고 끈다.

- 주인: 김승욱
- 입력: 없음
- 출력: SKILL.md

## 작업 기록 (최신이 위)

| 날짜 | 작업자 | 한 일 | PR |
|---|---|---|---|
| 2026-11-09 | 김승욱 (Claude Code) | "이 폴더가 하는 일"을 현재 SKILL.md 13개와 읽는 위치(`SKILL_NAMES`, `teams.py`)에 맞춰 고침. 아래 11/02 줄의 Skill 3개는 당시 기록이라 그대로 둠 | 미정 |
| 2026-11-02 | 김승욱 (Claude Code) | 런타임 Skill 3개: `citation-rules`, `grounding-check`, `glossary` | 이번 PR |

## 문제 기록 (최신이 위)

| 번호 | 발견일 | 발견자 | 문제 | 영향 | 담당 | 상태 | 판정일 | 판정 근거 |
|---|---|---|---|---|---|---|---|---|
