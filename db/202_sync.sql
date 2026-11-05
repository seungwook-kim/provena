-- 증분 수집 표 (docs/specs/incremental.md, 조장 승인 11/2 ⑧). 200번대 = 검색·데이터(박진형).
-- schedule.py가 실행마다 먼저 실행한다. 여러 번 돌려도 된다. 판·청크는 201_search.sql 표를 그대로 쓴다
-- (옛 판은 지우지 않고 valid_to로 닫는다 → as_of 검색과 동결 평가셋이 그대로 남는다).

-- 실행 기록: 한 줄 = 정해진 시각 실행 한 번. (job, slot) UNIQUE = 같은 슬롯은 한 번만 시작한다(중복 실행 방지, rag3-19).
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id          bigserial PRIMARY KEY,
    job             text NOT NULL,
    slot            text NOT NULL,                  -- 하루 1회 = UTC 날짜(예: 2026-11-03). 손으로 한 번 더 돌릴 때는 manual-<시각>
    trigger         text NOT NULL CHECK (trigger IN ('schedule', 'manual')),
    status          text NOT NULL CHECK (status IN ('running', 'succeeded', 'noop', 'failed')),
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz,
    from_commit     text,
    to_commit       text,
    list_complete   boolean,                        -- 목록을 끝까지 받았나(아니면 삭제 보류, rag4-13)
    added           integer,
    modified        integer,
    format_only     integer,                        -- 링크 주소·공백만 바뀐 쪽(리콜에 안 보냄)
    removed_seen    integer,                        -- 사라진 것으로 본 쪽
    removed_applied integer,                        -- 실제로 닫은 쪽(목록이 불완전하면 0)
    articles        integer,                        -- 리콜에 넘긴 바뀐 섹션 수
    embedded        integer,                        -- 새로 임베딩한 청크
    reused          integer,                        -- 같은 글이라 벡터를 재사용한 청크
    detail          jsonb NOT NULL DEFAULT '{}',    -- 쪽별 결과(경로 목록·오류·검토 대기). 개수만 남기지 않는다(rag4-13)
    error_kind      text,
    error_detail    text,
    UNIQUE (job, slot)
);

-- 리콜에 넘길 바뀐 섹션 (칸 이름 = 계약 ChangedArticle, backend/schemas/recall.py).
-- 리콜 쪽(김승욱)이 이 표를 읽거나, POST /webhooks/regulation-updated 가 생기면 그리로 보낸다(status).
-- event_id = (rule_seq, article, new_version_date, change_type)의 sha256 앞 16자리 → 같은 개정은 다시 돌려도 한 줄.
CREATE TABLE IF NOT EXISTS changed_articles (
    event_id         text PRIMARY KEY,
    run_id           bigint NOT NULL REFERENCES sync_runs (run_id),
    rule_seq         bigint NOT NULL,
    article          text NOT NULL,
    old_version_date text NOT NULL,
    new_version_date text NOT NULL,
    change_type      text NOT NULL CHECK (change_type IN ('added', 'removed', 'modified')),
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS changed_articles_pending ON changed_articles (status) WHERE status = 'pending';

-- Supabase는 public 표를 Data API로 내보내고 새 표에 anon 권한을 연다. RLS를 켜고 정책을 두지 않아 anon과 authenticated를 막는다(201_search.sql과 같은 방식).
-- schedule.py는 표 소유자로 접속하므로 RLS의 영향을 받지 않는다. 다시 실행해도 된다.
ALTER TABLE sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE changed_articles ENABLE ROW LEVEL SECURITY;
