-- 결정표와 사람 승인 표 (SDD 5장 decision_tables, approvals / 놓친 것 목록 B-06). 100번대 = 김승욱 파트(로그인·사용자·승인).
-- 컨테이너를 처음 만들 때 실행되고, 여러 번 돌려도 된다. LangGraph 체크포인트·Store 표는 여기서 만들지 않는다:
-- 앱이 시작할 때 backend/graph/checkpoint.py 의 open_persistence() 가 .setup() 으로 만든다(B-09).
-- 쟁점표(issue_table) 저장 표는 110_issue_tables.sql 이다. 승인 건은 같은 approvals 표를 kind 로 나눠 쓴다.
-- team_review_failed 는 재시도 상한까지 실패한 팀을 사람에게 알린 건이다. status 를 읽는 법은 아래 COMMENT ON COLUMN 에 적었다.

-- 결정표: 권한표 한 업무 종류(행 묶음) = 한 표. cells = DecisionRule 목록(JSON, backend/schemas/decision.py).
-- 승인된 표만 실행한다(J-07). 승인자 없는 approved 는 DB 가 거부한다.
CREATE TABLE IF NOT EXISTS decision_tables (
    table_id    text PRIMARY KEY,
    rule_seq    bigint NOT NULL,                 -- 권한표 페이지 id (docs.rule_seq 와 같은 값; 201 보다 먼저 만들어지므로 FK 는 걸지 않는다)
    version_id  text NOT NULL,                   -- 권한표 판(커밋 앞 12자)
    cells       jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'rejected')),
    approved_by text,                            -- 승인한 관리자 user_id. draft, rejected 에서는 비어 있다
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'approved') = (approved_by IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS decision_tables_status ON decision_tables (status);

-- 승인 건: 그래프가 interrupt 로 멈춘 한 번 = 한 줄. thread_id 로 같은 대화를 재개한다.
CREATE TABLE IF NOT EXISTS approvals (
    approval_id text PRIMARY KEY,
    kind        text NOT NULL,
    thread_id   text NOT NULL,
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by  text
);
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS approvals_kind_check;           -- 먼저 만들어진 표의 옛 제약을 지우고 다시 건다
ALTER TABLE approvals ADD CONSTRAINT approvals_kind_check CHECK (kind IN ('decision_table', 'issue_table', 'team_review_failed'));
-- 재개 때 노드가 다시 돌아도 승인 건이 둘이 되지 않는다. 결정표는 대화마다 1건이다.
-- 합동 검토는 한 대화에서 다시 할 수 있어 끝난 건을 기록으로 남기고, 대화마다 대기 건만 1건이다.
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS approvals_thread_id_kind_key;   -- 먼저 만들어진 표의 옛 제약
CREATE UNIQUE INDEX IF NOT EXISTS approvals_decision_thread ON approvals (thread_id) WHERE kind = 'decision_table';
CREATE UNIQUE INDEX IF NOT EXISTS approvals_review_pending ON approvals (thread_id) WHERE kind <> 'decision_table' AND status = 'pending';
-- 승인함 화면(ApprovalItem)과 결정 기록용 칸. 먼저 만들어진 approvals 표에도 칸을 더한다
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS summary    text NOT NULL DEFAULT '';
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS comment    text NOT NULL DEFAULT '';
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS decided_at timestamptz;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS target_id  text;          -- 승인 대상 id (결정표면 table_id, 쟁점표면 승인 전 approval_id, 승인 뒤 저장된 table_id, 팀 실패 알림이면 approval_id)
CREATE INDEX IF NOT EXISTS approvals_pending ON approvals (created_at) WHERE status = 'pending';
COMMENT ON COLUMN approvals.status IS 'pending, approved, rejected. kind = team_review_failed 이면 approved = retry(실패한 팀만 다시), rejected 이고 decided_by 있음 = mark_unreviewed(검토하지 못함으로 남김), rejected 이고 decided_by 없음 = 사람 결정 없이 다음 단계로 넘어가 닫힘.';

-- 앱은 DATABASE_URL 의 소유자 권한으로 읽고 쓴다(201_search.sql 과 같은 방침: 공개 API 키로는 못 보게 잠근다)
ALTER TABLE decision_tables ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
