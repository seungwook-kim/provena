-- 답변·인용 저장과 답변 리콜(F-02), 알림 피로 줄이기(F-08), 변경 감시 스위치. 100번대 = 김승욱 파트(111 threads 다음 번호).
-- 읽고 쓰는 곳: backend/graph/answer_store.py 의 PgAnswerStore, backend/graph/recall/store.py 의 PgRecallStore, backend/graph/recall/monitor.py.
-- 앱은 RECALL_STORE=postgres 일 때만 이 표를 쓴다(비우면 메모리 저장소). 로컬 데모 모드에서는 앱이 시작할 때 이 파일을 실행하고,
-- 운영 Supabase에서는 db/db.md 절차대로 직접 실행한다. 전부 IF NOT EXISTS 라 여러 번 실행해도 된다.

-- 답. as_of 는 질문의 기준일(YYYY-MM-DD, 없으면 NULL = 그때의 현재 판). thread_id 는 그래프 이름 "<user_id>:<thread_id>" 그대로다.
CREATE TABLE IF NOT EXISTS answers (
    answer_id   text PRIMARY KEY,
    user_id     text NOT NULL,
    thread_id   text NOT NULL DEFAULT '',
    question    text NOT NULL,
    answer      text NOT NULL,
    as_of       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS answers_user_idx ON answers (user_id, created_at DESC);

-- 인용. 답과 근거 판(커밋)을 묶어 둔다. 리콜은 (rule_seq, article)로 영향받는 답을 찾는다.
CREATE TABLE IF NOT EXISTS citations (
    answer_id    text NOT NULL REFERENCES answers (answer_id) ON DELETE CASCADE,
    chunk_id     text NOT NULL,
    version_id   text NOT NULL,
    rule_seq     bigint NOT NULL,
    article      text,
    version_date text,
    source_url   text,
    PRIMARY KEY (answer_id, chunk_id, version_id)
);
CREATE INDEX IF NOT EXISTS citations_article_idx ON citations (rule_seq, article);

-- 인용 검사 결과(밖으로 낼 수 있는 값만). MCP 도구 get_grounding 이 읽는다.
CREATE TABLE IF NOT EXISTS answer_grounding (
    answer_id   text PRIMARY KEY REFERENCES answers (answer_id) ON DELETE CASCADE,
    grounding   jsonb NOT NULL DEFAULT '{}'::jsonb,
    skills_used jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- 리콜 처리 기록. 한 줄 = 바뀐 섹션 하나(event_key = changed_articles.event_id 와 같은 규칙). 같은 개정은 한 번만 판정한다(EC-06).
CREATE TABLE IF NOT EXISTS recall_events (
    event_key      text PRIMARY KEY,
    changed        jsonb NOT NULL,
    status         text NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    notices        integer NOT NULL DEFAULT 0,
    review         integer NOT NULL DEFAULT 0,
    judge_failures integer NOT NULL DEFAULT 0,
    candidates     integer NOT NULL DEFAULT 0,
    error_kind     text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);

-- 리콜 알림. 같은 답·같은 개정은 한 줄이다(UNIQUE (answer_id, event_key)).
-- review_status: 확신도가 낮거나 의견 규칙으로 눌린 알림은 pending(관리자 검토함). 사용자에게는 released 이거나 NULL 인 것만 보인다.
-- digest_status: RECALL_DIGEST=daily 일 때 요약 대기(pending) -> 요약 보냄(sent).
CREATE TABLE IF NOT EXISTS recall_notices (
    notice_id          text PRIMARY KEY,
    event_key          text NOT NULL,
    answer_id          text NOT NULL,
    user_id            text NOT NULL,
    thread_id          text,
    question           text,
    answer_excerpt     text,
    changed            jsonb NOT NULL,
    conclusion_changed boolean NOT NULL,
    explanation        text NOT NULL,
    severity           text NOT NULL CHECK (severity IN ('high', 'low')),
    confidence         double precision CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    change_pattern     text NOT NULL DEFAULT '',
    review_status      text CHECK (review_status IN ('pending', 'released', 'dismissed')),
    review_reason      text,
    digest_status      text CHECK (digest_status IN ('pending', 'sent')),
    judge_failed       boolean NOT NULL DEFAULT false,
    acked              boolean NOT NULL DEFAULT false,
    acked_at           timestamptz,
    source_url         text,
    old_text           text,
    new_text           text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (answer_id, event_key)
);
CREATE INDEX IF NOT EXISTS recall_notices_user_idx ON recall_notices (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS recall_notices_review_idx ON recall_notices (created_at DESC) WHERE review_status = 'pending';
CREATE INDEX IF NOT EXISTS recall_notices_digest_idx ON recall_notices (created_at) WHERE digest_status = 'pending';

-- 함께 볼 정책 후보(링크로 연결된 다른 정책). 관리자가 확인 필요(needed)·불필요(not_needed)를 판단한다.
CREATE TABLE IF NOT EXISTS maintenance_candidates (
    candidate_id     text PRIMARY KEY,
    event_key        text NOT NULL,
    upper_rule       text NOT NULL,
    upper_version_id text NOT NULL,
    rule_seq         bigint NOT NULL,
    article          text NOT NULL,
    reason           text NOT NULL,
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'needed', 'not_needed')),
    decided_by       text,
    decided_at       timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS maintenance_candidates_status_idx ON maintenance_candidates (status, created_at DESC);

-- 업무시스템 웹훅 구독. secret_ref 는 비밀값이 든 환경변수 이름이다(RECALL_WEBHOOK_SECRET 또는 RECALL_WEBHOOK_SECRET_<이름>). 값은 저장하지 않는다.
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    sub_id      text PRIMARY KEY,
    url         text NOT NULL,
    secret_ref  text NOT NULL DEFAULT 'RECALL_WEBHOOK_SECRET',
    active      boolean NOT NULL DEFAULT true,
    created_by  text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- 웹훅 전송 기록. 시도마다 attempts 에 상태 코드·오류 종류·시각을 남긴다(EC-05, AC-03).
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id      text PRIMARY KEY,
    sub_id           text NOT NULL,
    notice_id        text NOT NULL,                  -- 요약 전송이면 digest_id
    kind             text NOT NULL DEFAULT 'notice' CHECK (kind IN ('notice', 'digest')),
    status           text NOT NULL CHECK (status IN ('pending', 'success', 'failed')),
    tries            integer NOT NULL DEFAULT 0,
    last_status_code integer,
    last_error       text,
    attempts         jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_notice_idx ON webhook_deliveries (notice_id);

-- 알림 한 건에 대한 사용자 의견(도움 됨/필요 없음). 알림당 한 줄(다시 보내면 덮어쓴다).
-- (user_id, rule_seq, article, pattern) 이 "같은 사용자·섹션·변경 유형" 집계 키다.
CREATE TABLE IF NOT EXISTS recall_feedback (
    notice_id  text PRIMARY KEY,
    user_id    text NOT NULL,
    answer_id  text NOT NULL,
    rule_seq   bigint NOT NULL,
    article    text NOT NULL,
    pattern    text NOT NULL DEFAULT '',
    severity   text,
    useful     boolean NOT NULL,
    reason     text NOT NULL DEFAULT '',
    given_by   text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recall_feedback_key_idx ON recall_feedback (user_id, rule_seq, article, pattern);

-- 하루 요약(RECALL_DIGEST=daily). payload 는 웹훅으로 보낸 요약 JSON(알림 목록 포함)이다.
CREATE TABLE IF NOT EXISTS recall_digests (
    digest_id  text PRIMARY KEY,
    user_id    text NOT NULL,
    day        text NOT NULL,
    count      integer NOT NULL,
    notice_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recall_digests_user_idx ON recall_digests (user_id, created_at DESC);

-- 변경 감시 스위치(한 줄). paused 이면 증분 수집(backend/rag/ingest/schedule.py)이 아무것도 하지 않고 noop(paused)으로 끝낸다.
CREATE TABLE IF NOT EXISTS change_monitoring (
    id         smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Supabase는 public 표를 Data API로 내보내고 새 표에 anon 권한을 연다. RLS를 켜고 정책을 두지 않아 anon과 authenticated를 막는다(202_sync.sql과 같은 방식).
-- 앱은 DATABASE_URL 의 소유자 권한으로 읽고 쓰므로 RLS의 영향을 받지 않는다. 다시 실행해도 된다.
ALTER TABLE answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_grounding ENABLE ROW LEVEL SECURITY;
ALTER TABLE recall_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recall_notices ENABLE ROW LEVEL SECURITY;
ALTER TABLE maintenance_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE recall_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE recall_digests ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_monitoring ENABLE ROW LEVEL SECURITY;
