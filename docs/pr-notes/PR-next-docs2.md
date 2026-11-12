# 다음 PR 작업 내역: 주말 동결 제안(K-15)과 ACL 알려진 한계 기록
- 작업자: 박진형 (jinyeong-731) / PR: 미정 / 기준: origin/main `601183c7` 위 브랜치 `gap3-docs2`
- 문서만 바꿨다. 코드, workflow, `.env.example`, `docker-compose.yml`, `backend/schemas/`는 건드리지 않았다. 배포·운영 DB·LLM·Voyage 호출 없음.

## 무엇을
| 번호 | 바꾼 곳 | 내용 |
|---|---|---|
| K-15 (I-06, P-09, F-08 관련) | `docs/decisions.md` 결정 표 맨 위 행 | "(제안, 조장 승인 대기)" 주말 11/14~15와 동결(11/16 24:00) 뒤: 새 자동 실행·배포 없음, `handbook-sync`는 `disabled_manually` 유지, 동결 뒤 코드 변경 없음 |
| K-15 | `docs/TEAM_GUIDE.md` 일정 표 11/14~15 행 | `handbook-sync`는 꺼 둔 채 둔다는 제안과 `decisions.md` 가리킴 |
| J-01, J-02, J-03, L-09, O-16 | `EVAL_REPORT.md` 6장 "아직 막지 못한 것" (7) | 문서 권한 검색 전 거르기를 동결 전에 만들지 않는 알려진 한계 |
| 같은 번호 | `docs/SDD.md` 문서 권한(F-06) 줄 | "미구현 부분" 문장 끝에 2026-11-11 진형 결정과 EVAL_REPORT 6장 연결 |

## 왜 (근거)
- [문서] 주말 자동 실행·배포 금지: `docs/PRD.md:378`, `docs/TEAM_GUIDE.md:32`, 동결 `TEAM_GUIDE.md:33`, 가이드 p.5(조장 목록 K-15 행).
- [코드] workflow 상태: `.github/workflows/handbook-sync.yml:9` 정시 `cron "7 18 * * *"`(켜면 매일 한국 03:07, 운영 DB와 Voyage 사용, 파일 머리 주석 `:3-4`). `disabled_manually`는 조장 목록 K-15·F-08 행과 `docs/specs/incremental.md:111`.
- [문서] 정시 실행 3회 실패·원인 미확인, 결제 한도로 러너 미기동: `docs/specs/incremental.md:112-113`.
- [코드] ACL: `backend/graph/recall/acl.py:6`("그룹을 채우는 정책 파일과 검색 단계 거르기는 검색 파트 몫"), `backend/rag/retrieve/search.py`에 `acl`·`allowed_groups` 0건(grep), `SDD.md:235`가 이미 미구현이라고 적음.
- [결정] 진형 2026-11-11: 검색 결과와 평가 점수가 바뀌므로 동결 전에 검색 전 ACL 거르기를 만들지 않는다.

## 확인한 것
- `.github/workflows/`는 `ci.yml`, `handbook-sync.yml`, `secret-scan.yml` 3개, 주말에 도는 다른 정시 실행은 없음(`schedule:`은 handbook-sync에만, grep).
- `handbook-sync`를 언급하는 문서: `SDD.md:318`, `TEAM_GUIDE.md:114`, `specs/incremental.md:107-113`, `specs/mcp.md:84`. 이번에 바꾼 곳과 모순 없음.
- 일정이 주말을 적은 곳은 `PRD.md:378`과 `TEAM_GUIDE.md:32`뿐이다. PRD는 가이드 문구 그대로라 두고 `TEAM_GUIDE.md`만 고쳤다.
- 줄 번호 인용은 이 브랜치 파일에서 직접 다시 읽어 확인했다.

## 한계
- K-15는 제안이다. 조장이 승인하기 전에는 확정이 아니다. 조장 목록의 "다시 켜기 전, 늦어도 11/13(금)" 기한이 남아 있다.
- `disabled_manually` 상태는 GitHub 설정이라 저장소에서 확인되지 않고 조장 목록(11/11 `gh run list`)을 따랐다. 오늘 상태는 다시 보지 않았다.
- ACL은 기록만 했다. 문서 권한이 필요한 청크가 생기면 검색·인용에 그대로 나온다(지금 코퍼스 `acl`은 전부 비어 있어 영향 없음). 사용자 그룹을 채우는 로그인 경로(J-02)와 정책 파일(J-03)도 열려 있다.
- 11/17 제출 문서(실패 사례 분석 등)는 동결(코드) 뒤에도 가이드 일정대로 낼 수 있다고 보았다. 이 해석은 조장 확인이 필요하다.
