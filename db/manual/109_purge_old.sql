-- db/manual/109_purge_old.sql : db/manual/109_retire_old.sql 이 이름만 바꿔 둔 옛 표 3개를 완전히 지우는 수동 실행 파일이다.
-- 자동으로 적용되지 않는다(compose 초기화와 시험은 db/ 바로 아래 파일만 실행한다).
-- 실행 전 확인: 새 코드가 배포되어 두어 날 동안 문제가 없었고, 옛 표의 행 수와 합쳐진 칸의 값이 같다고 확인했을 것.
--   SELECT (SELECT count(*) FROM answer_grounding_old_20261110) AS grounding_old,
--          (SELECT count(*) FROM answers WHERE grounding IS NOT NULL) AS grounding_new;
-- 이 파일을 실행하면 되돌릴 수 없다. 백업(dump) 뒤에 실행한다.
DROP TABLE IF EXISTS answer_grounding_old_20261110;
DROP TABLE IF EXISTS recall_feedback_old_20261110;
DROP TABLE IF EXISTS issue_table_rejections_old_20261110;
