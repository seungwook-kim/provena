# Spec — 증분 수집과 바뀐 섹션 찾기 (박진형, 업무 분담 B-5)

> 2026-11-02판. 조장 답 ⑦(정시 실행 = GitHub Actions)·⑧(`sync_runs`·`changed_articles` 승인, `ChangedArticle` 칸 이름)을 반영했다. 설계 근거와 강의 출처는 박진형 설계안(개인 공부 폴더)에 있고, 여기에는 팀이 지킬 약속만 적는다. 기본값으로 정한 곳은 "(기본값, 리뷰에서 확인)"으로 표시했다.

## Why

- **페르소나**: 리콜 그래프(F-02, 김승욱), 그리고 "정해진 시각 실행 기록"을 확인하는 평가자
- **상황**: 핸드북은 매일 고쳐진다. 고정 커밋 `129243bc`(10/27) 뒤 사흘(→ `52419353ea`, 10/30) 동안 고른 17개 폴더에서 139쪽(1,564쪽의 8.9%)이 바뀌었다(실측).
- **문제**:
  1. 고정 커밋만 쓰면 답이 점점 낡는다. 리콜(F-02)은 "어느 섹션이 바뀌었나" 목록 없이는 시작할 수 없다.
  2. 바뀐 139쪽 중 116쪽은 링크·공백만 바뀌었다. 링크 정리 커밋 하나(`2666725a9b`)가 혼자 110쪽을 고쳤다. 이런 것을 거르지 않으면 리콜이 쏟아진다.
  3. 다시 수집할 때 옛 판을 지우면 동결한 평가셋(기준일 = 고정 커밋 날짜)과 `as_of` 검색이 깨진다.
- **측정 지표**: 리콜 시험 커밋 12건 중 바뀐 섹션을 찾은 수, "서식만"으로 거른 비율, 같은 커밋 재반영 때 추가·갱신 수(0), 정해진 시각 실행 성공 수 / 예정 수

## Goal

- **해결 목표**: 매일 정해진 시각에 마지막으로 반영한 커밋 뒤의 새 커밋만 받아 바뀐 쪽만 다시 처리한다. 옛 판은 남긴 채 현재 판을 옮기고, 바뀐 섹션을 `ChangedArticle` 로 리콜 쪽에 넘긴다. 가이드 p.20 가산 자동화 조건 네 가지(추가·갱신 반영과 목록이 완전할 때만 삭제, 중복 실행 방지, 정해진 시각 실행 기록, 실패 알림)를 갖춘다.
- **성공 기준**
  - 리콜 시험 커밋 12건(`history.py` `RECALL_COMMITS`)을 12건 모두 찾는다(서식만으로 빠지는 것 0). 11건은 `modified`, `fc6633cf` 는 섹션이 지워진 커밋이라 `removed`.
  - 링크 정리 커밋 `2666725a9b` 110쪽 중 90% 이상을 "서식만"으로 거른다(실측 107쪽, 97.3%).
  - 같은 커밋을 다시 반영하면 추가 0·갱신 0, 표 지문이 같다.
  - 목록이 불완전하면 삭제 반영 0, 보류 알림 1건. 보류한 쪽은 다음 완전한 실행에서 다시 확인한다.
  - 같은 슬롯에 두 번 시작하면 실제 처리는 한 번.
  - 반영 뒤에도 `as_of=2026-10-27`(동결일) 검색 결과가 반영 전과 같다.
  - 실패한 실행마다 디스코드 알림 1건, 또는 알림을 끈 사실이 실행 로그에 남는다.
- **Out of Scope** (넣지 않은 것과 이유)
  - 리콜 웹훅 전송(`POST /webhooks/regulation-updated`): 받는 쪽이 아직 없다. 지금은 `changed_articles` 표(`status=pending`)에 쌓고, 받는 쪽이 생기면 전송을 붙인다(10줄 내외). 받는 쪽이 표를 직접 읽어도 된다(리뷰에서 확인).
  - 답의 결론이 바뀌었는지 판정(LLM, 리콜 그래프) / 사용자·업무시스템 알림(리콜)
  - 실행 되돌리기(`--rollback`): 가산 조건이 아니다. 잘못된 반영은 반영 직전 검사(행 수 대조·DB 고유 색인)가 커밋 전에 막는다.
  - 실행 기록 해시 체인, 26시간 무성공 알림, 비상 정지 변수: 기록은 `sync_runs`, 무성공은 실행 기록 날짜로 보이고, 멈춤은 Actions의 "Disable workflow"로 한다.
  - 쪽별 임베딩 보류(`needs_embedding`): 로컬 임베딩은 실패하면 모든 쪽이 함께 실패한다. 실행 전체를 `failed` 로 끝내고 다음 실행이 같은 커밋부터 다시 한다(옛 벡터를 새 판처럼 쓰지 않는다). API 임베딩 모델로 바뀌면 다시 본다.
  - 사라진 쪽의 실제 삭제일: 두 끝 비교라 어느 커밋에서 지워졌는지 보지 않고, 새 끝 커밋 날짜로 닫는다(실제보다 늦을 수 있다).
  - 옮긴 쪽(같은 blob이 다른 경로): `moved` 로 실행 기록에만 남기고, 리콜에는 `removed`·`added` 로 넘긴다(계약에 `moved` 없음, 기본값, 리뷰에서 확인).
  - git 없는 두 시점 문서 비교(F-07, `section_changes` 는 원문 두 개를 받게 만들어 둠), G3 숫자(고정 커밋 `data/manifest.jsonl` 로만 센다), 증분 전용 인젝션 검사(새 쪽은 D7 인젝션 시험 대상에 그대로 들어감)
  - 처리 규칙이 바뀐 것 알아채기(강의 14강 `processing_signature`): 증분은 같은 판(`rule_seq`·`version_id`)을 이미 넣었으면 건너뛰어서, 판 날짜 계산 규칙 같은 처리 규칙 변경은 못 잡는다(I-011 UTC 변경 때 확인). 규칙을 바꾸면 한 번뿐이므로 색인을 `index.py refresh`나 `build`로 갱신하고 `load_snapshot`으로 전체를 다시 적재한다

## What

**Happy Path**
1. 매일 UTC 18:07(한국 03:07)에 workflow가 `python -m backend.rag.ingest.schedule --once` 를 부른다.
2. 오늘 UTC 날짜 슬롯을 차지한다(`sync_runs` 의 `(job, slot)` UNIQUE). 이미 있으면 아무것도 하지 않고 끝난다.
3. 색인 장부(`index_meta`)의 임베딩 모델 이름·차원이 지금 쓸 모델과 같은지 본다.
4. 핸드북을 fetch하고, 마지막으로 성공 반영한 커밋(처음이면 고정 커밋)과 새 끝 커밋이 같으면 `noop` 으로 끝난다.
5. 두 커밋의 고른 17개 폴더 파일 목록(경로·blob id)을 비교하고 목록 완전성을 검사한다(`diff.list_changes`).
6. 바뀐 쪽만 파일을 한 번에 받아(`diff.fetch_blobs`) 옛 판·새 판의 섹션(제목 경로)을 비교해 `added`·`removed`·`modified` 를 만든다. 서식만 바뀐 섹션은 빼고, 제목만 바뀐 섹션은 본문 유사도 0.35 이상이면 같은 섹션으로 본다(`diff.section_changes`).
7. 바뀐 쪽을 처음 수집과 같은 함수(`parse_page`·`chunk_structure`, 800/120)로 청킹한다. 같은 쪽에 같은 글의 벡터가 있으면 재사용하고, 없는 글만 임베딩한다(서식만 바뀐 날은 모델을 올리지 않는다).
8. 한 트랜잭션으로: 옛 판의 `valid_to` 를 닫고 새 판·청크를 넣고, 사라진 쪽(목록이 완전할 때만)을 닫고, 바뀐 섹션을 `changed_articles` 에 넣고, `index_meta.generation` 을 올리고(api가 BM25를 다시 만듦), 실행 기록을 `succeeded` 로 확정한다.
9. 실패하면 전부 되돌리고 실행 기록을 `failed`(`error_kind`)로 남긴 뒤 종료 코드 1 → workflow의 `if: failure()` 단계가 디스코드로 알린다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 같은 슬롯에 두 번째 시작(수동 실행 겹침 등) | 아무것도 하지 않음(원천·임베딩 호출 0). 같은 날 한 번 더 돌려야 하면 `--slot manual-<시각>` |
| EC-02 | 새 커밋 없음 | `noop` 기록 |
| EC-03 | 17개 폴더 중 하나가 빔(목록은 받았지만 불완전) | 추가·수정만 반영, 삭제 보류(`list_complete=false`, `removed_held`). 성공으로 끝내되 보류 알림 1건. 보류한 쪽의 사라진 섹션은 리콜에 아직 넘기지 않음. 다음 완전한 실행이 새 커밋 목록으로 다시 확인해 여전히 없으면 닫고(유효 끝 = 보류한 날) 그때 넘김, 다시 있으면 그대로 |
| EC-03b | 커밋 없음(`commit_missing`)·`ls-tree` 실패 = 두 커밋을 비교하지 못함 | 추가·수정도 못 봤으므로 보류가 아니라 `failed`(`list_failed`) + 실패 알림, 다음 실행이 같은 커밋부터 다시 |
| EC-04 | 링크 주소·공백·`[TOC]` 만 바뀐 섹션 | 리콜에 넘기지 않음. 쪽은 새 판으로 옮김(줄 번호가 바뀔 수 있어서), 벡터는 재사용 |
| EC-05 | 제목만 바뀐 섹션 | 짝을 찾아 `modified` 하나, `article` 은 옛 제목 경로(지난 답이 인용한 것, 기본값, 리뷰에서 확인) |
| EC-06 | 쪽이 사라짐(목록 완전) | 행을 지우지 않고 현재 판의 `valid_to` 를 닫음. 섹션마다 `removed` 로 넘김. 그 날짜 전 `as_of` 검색에는 남음 |
| EC-07 | 고정 커밋과 같은 날(10/27) 고친 쪽 | 판 날짜는 그대로, 유효 시작은 10/28 → 동결일 검색은 옛 판 그대로 |
| EC-08 | 색인 장부 모델과 지금 모델이 다름(차원이 같아도) | 원천을 부르기 전에 `failed`(`index_mismatch`). 전체 다시 적재(`load_snapshot`)가 필요 |
| EC-09 | 임베딩 실패 | 실행 전체 `failed`, 마지막 성공 커밋은 그대로 → 다음 실행이 같은 커밋부터 |
| EC-10 | 한 쪽 파싱 실패 | 그 쪽만 건너뛰고 `detail.errors` 에 남김(나머지는 반영) |
| EC-11 | 처음 보는 단축코드 | 처음 수집과 같이 그 요소만 색인에서 빠지고 `detail.review` 에 남김 |
| EC-12 | 다른 쪽으로 넘기는 쪽(`redirect_to`) | 처음 수집과 같이 청크 없음 → 옛 판만 닫음 |

## How

**함수**

```
backend/rag/ingest/diff.py      (DB·모델 없음)
  list_changes(repo, old, new) -> Changes        # 추가·수정·사라짐·그대로 + list_complete + 이유
  section_changes(page, old_raw, new_raw)        # 섹션 비교 + 서식만 표시 (git 없이 원문 두 개)
  diff_commits(repo, old, new, raw_out=None)     # 위를 묶은 보고서. python -m backend.rag.ingest.diff <옛> <새>

backend/rag/ingest/schedule.py
  run(conn, *, trigger, now, slot, model, dim, source, embed_fn) -> {status, run_id, 개수}
      # 시각·원천·임베딩은 인자로 받는다(시험 재현). 실패면 기록 뒤 SyncError
  python -m backend.rag.ingest.schedule --once [--slot manual-<시각>] [--cache <핸드북 캐시>]
```

**DB** (`db/202_sync.sql`, 판·청크는 `201_search.sql` 표 그대로)

| 표 | 내용 |
|---|---|
| `sync_runs` | 실행 한 번 = 한 줄. `(job, slot)` UNIQUE, `status`(running·succeeded·noop·failed), `from_commit`·`to_commit`, `list_complete`, 개수(added·modified·format_only·removed_seen·removed_applied·articles·embedded·reused), `detail`(쪽 경로 목록·오류·검토 대기), `error_kind`·`error_detail` |
| `changed_articles` | `event_id`(PK, (rule_seq, article, new_version_date, change_type)의 sha256 앞 16자리) + `ChangedArticle` 칸 + `run_id`·`status`(pending·sent·failed) |

- 판은 고치지 않고 추가만 한다. 바꾸는 것은 옛 판의 `valid_to` 하나뿐이다(`versions_one_current` 고유 색인이 "현재 판 둘"을 막는다).
- 새 판 `valid_from` = max(판 날짜, 2026-10-28), 닫는 `valid_to` = max(새 판 유효 시작, 옛 판 `valid_from`).
- 쪽마다 넣은 청크 수와 DB 청크 수를 대조한다(rag4-09). 접속은 직접 연결 또는 session mode(transaction pooler 아님).

**정해진 시각 실행** (`.github/workflows/handbook-sync.yml`, 공용 폴더라 조장 승인)
- `schedule: cron "7 18 * * *"`(UTC), `workflow_dispatch`, `concurrency: {group: handbook-sync, cancel-in-progress: false}`, `permissions: contents: read`, `persist-credentials: false`, `timeout-minutes: 30`(첫 실행에서 재고 고침)
- 핸드북 캐시·모델 캐시는 `actions/cache` 로 이어 쓴다. 정시 실행은 main에 있는 workflow만 돈다.
- 비밀값: `DATABASE_URL`, `VOYAGE_API_KEY`(기본 모델 voyage-4가 API라 새 글이 있는 날 임베딩에 쓴다. 키가 없는 채로 새 글이 들어오는 날은 임베딩 단계에서 실패하고 실패 알림이 간다. 서식만 바뀐 날은 벡터를 재사용하므로 키를 쓰지 않는다), `SYNC_ALERT_WEBHOOK`(조장, 운영 DB가 정해진 뒤). 변수: `EMBED_MODEL`(색인 장부와 같은 모델)
- 켜고 첫 실행: workflow는 현재 비활성(`disabled_manually`)이다. 비밀값·변수를 등록한 뒤 `gh workflow enable handbook-sync.yml`, `gh workflow run handbook-sync.yml`로 한 번 돌리고 `gh run list --workflow handbook-sync.yml`로 결과를 본다. 손으로 돌린 실행은 `GITHUB_EVENT_NAME`이 `workflow_dispatch`라 `trigger=manual`로 기록되고, 슬롯은 기본으로 그날 UTC 날짜라 같은 날 정시 실행이 이미 있었으면 슬롯 충돌로 아무것도 하지 않는다. 첫 성공 뒤 DB `sync_runs`의 마지막 행(`status`, `to_commit`, `embedded`, `reused`)을 확인한다.
- 지금까지 실행 3건(2026-11-03~04)은 모두 "DATABASE_URL이 없다"로 실패했다(비밀값 미등록).

**재시도 규칙**

| 실패 | 처리 |
|---|---|
| git fetch | 5초·10초 간격으로 3번, 그래도 안 되면 `failed`(`fetch_failed`) + 알림 |
| 두 커밋 비교 실패(`list_failed`) | 재시도하지 않고 `failed` + 알림. 다음 정시 실행이 같은 커밋부터 다시 |
| 그 밖의 실패(DB·임베딩·행 수 어긋남) | 재시도하지 않고 `failed` + 알림. 다음 정시 실행이 같은 커밋부터 다시 |

## AC (Given-When-Then)

테스트: `tests/test_ingest_diff.py`(AC-01·02, 실제 핸드북 이력은 캐시가 있을 때만), `tests/test_ingest_schedule.py`(AC-03~10, DB 시험은 `TEST_DATABASE_URL` 이 있을 때만).

**AC-01 · 리콜 시험 커밋의 바뀐 섹션을 찾는다**
- GIVEN: 리콜 시험 커밋 12건(예: `4667e540` 취약점 이슈 공개 30일 → 90일)
- WHEN: 그 커밋과 부모 커밋으로 섹션을 비교한다
- THEN: 12건 모두 그 페이지에서 바뀐 섹션이 나오고 서식만으로 빠지지 않는다(11건 `modified`, `fc6633cf` 는 `removed`)

**AC-02 · 서식만 바뀐 커밋은 리콜에 넘기지 않는다**
- GIVEN: 링크 정리 커밋 `2666725a9b`(110쪽)
- WHEN: 섹션을 비교한다
- THEN: 90% 이상의 쪽이 "서식만"이고 넘길 목록에 들어가지 않는다. 본문 판정 3쪽은 사람이 원문과 대조해 기록한다

**AC-03 · 다시 돌려도 같다**
- GIVEN: 커밋 X를 반영한 DB
- WHEN: 다른 슬롯으로 다시 돌리고, 반영 함수를 같은 보고서로 한 번 더 부른다
- THEN: 앞은 `noop`, 뒤는 추가 0·갱신 0·새 섹션 0·임베딩 0이고, 표 지문이 같다

**AC-04 · 목록이 불완전하면 지우지 않는다**
- GIVEN: 사라진 쪽이 있고 목록 완전성 검사가 실패한 보고서
- WHEN: 반영한다
- THEN: `removed_seen=1`, `removed_applied=0`, 그 쪽은 현재 판 그대로. 목록이 완전하면 닫히고, 동결일 검색에는 남는다

**AC-05 · 같은 슬롯은 한 번만**
- GIVEN: 오늘 슬롯이 이미 시작됨
- WHEN: 같은 슬롯으로 한 번 더 들어온다
- THEN: 두 번째는 원천·임베딩 호출 0, `sync_runs` 한 줄

**AC-06 · 중간 실패는 전부 되돌린다**
- GIVEN: 새 판·청크를 쓴 뒤 바뀐 섹션을 쓰다가 실패
- WHEN: 실행이 끝난다
- THEN: 표가 실패 전과 같고, `failed` 기록, 다음 실행이 같은 커밋부터 다시 한다

**AC-07 · 옛 판을 지키고 검색이 판을 고른다**
- GIVEN: 9/1 판이 있는 쪽을 10/30 판으로 반영(그리고 10/27에 고친 쪽)
- WHEN: `as_of=2026-10-27` 과 `as_of` 없음으로 검색한다
- THEN: 앞은 옛 판, 뒤는 새 판. 10/27에 고친 쪽도 동결일 검색은 옛 판

**AC-08 · 모델이 다르면 시작하지 않는다**
- GIVEN: 색인 장부 모델이 지금 모델과 다름(차원은 같음)
- WHEN: 실행한다
- THEN: 원천 호출 0, `failed`(`index_mismatch`)

**AC-09 · 보류한 삭제는 다음 완전한 실행에서 다시 확인한다**
- GIVEN: 목록이 불완전해 쪽 하나의 삭제를 보류한 실행(그날 장부는 새 커밋으로 감 → 다음 날 비교에는 그 쪽이 나오지 않음)
- WHEN: 다음 날 목록이 완전한 실행이 돈다
- THEN: 새 커밋 목록에 없으면 닫히고(유효 끝 = 보류한 날) 사라진 섹션이 그때 리콜 표에 들어간다. 다시 있으면 그대로. 보류한 날은 `held`·`reasons` 를 workflow에 넘겨 보류 알림을 보낸다

**AC-10 · 비교를 못 한 날은 실패다**
- GIVEN: `commit_missing` 또는 `ls-tree` 실패가 이유인 보고서
- WHEN: 반영한다
- THEN: `failed`(`list_failed`), 표·마지막 성공 커밋은 그대로
