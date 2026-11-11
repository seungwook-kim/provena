-- 승인 건의 그래프 재개 기록 (강사 코멘트 11/11: 재개 횟수를 API로 볼 수 없다). 100번대 = 김승욱 파트(승인). 102_decision_approvals.sql 다음에 실행한다.
-- 결정 처리가 그래프를 실제로 재개한 횟수와 같은 결정의 재전송이 무시된 횟수를 승인 건 줄에 남긴다.
-- 읽는 곳: GET /approvals, GET /approvals/{approval_id} (backend/graph/decision/routes.py). 쓰는 곳: PostgresDecisionRepo.record_resume.
-- 전부 IF NOT EXISTS 라 여러 번 실행해도 된다. 이 파일을 적용하기 전에도 앱은 뜨고 승인은 되며, 재개 기록만 남지 않는다(경고 로그).
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS resume_count            integer NOT NULL DEFAULT 0;   -- 그래프를 재개한 횟수(성공·실패·재개 값 거절 포함)
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS duplicate_ignored_count integer NOT NULL DEFAULT 0;   -- 이미 끝난 건에 같은 결정이 또 와서 그래프를 돌리지 않은 횟수
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS last_resumed_at         timestamptz;                  -- 마지막으로 그래프를 재개한 시각. 재개한 적이 없으면 NULL
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS last_resume_result      text;                         -- resumed | resume_failed | rejected_value | duplicate_ignored
COMMENT ON COLUMN approvals.last_resume_result IS 'resumed(재개해 끝까지), resume_failed(재개 도중 오류), rejected_value(그래프가 재개 값을 거절), duplicate_ignored(같은 결정 재전송이라 그래프를 돌리지 않음)';
-- approvals 의 RLS 는 102_decision_approvals.sql 이 이미 켰다.
